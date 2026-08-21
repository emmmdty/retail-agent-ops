# R9 执行提示词

**用途**：新窗口启动时，按此提示词执行 R9 Spec v2 的 Phase A + Phase B。
**前置**：读完本文档后，先按 AGENTS.md 固定流程恢复上下文。

---

## 第一步：恢复上下文（必须按顺序）

1. `AGENTS.md`（固定流程）
2. `docs/EXECUTION_PLAN.md`（阶段状态）
3. `docs/R9_SPEC.md`（本轮 Spec）
4. `docs/R8_DIAGNOSIS.md`（根因分析）
5. `task_plan.md` R8 节（当前状态）
6. `findings.md` 最后 50 行
7. `progress.md` 最后 50 行
8. `docs/PROJECT_LOG.md` 最近一条 LOG

## 第二步：只读 Preflight

```bash
.venv/bin/pytest -q                    # 确认 1219 passed
.venv/bin/ruff check .                 # 确认 All checks passed
.venv/bin/ruff format --check .        # 确认 206 files already formatted
.venv/bin/mypy                         # 确认 Success, no issues found
env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check  # 确认 Resolved 105 packages
git diff --check                       # 确认干净
git log --oneline -3                   # 确认 HEAD 是 0c6dad0
```

## 第三步：执行 Phase A

### 3.1 Oversample 240→2000 条

**不做任何代码改动**，只生成新的训练数据。

做法：
1. 读取现有 `data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722/train.jsonl`（240 条）
2. 对每条样本，生成 7-8 个变体：
   - 替换 order_id（随机生成新的 16 位 hex）
   - 替换 reason（从 damaged/wrong_item/not_as_described/changed_mind 中轮换）
   - 替换 margin（从 _MARGINS=(1,2,3,5,7,10,14) 中轮换）
   - 替换 customer_id（从 CUST001-CUST010 中轮换）
3. 保持 user_request 模板**不变**（仍是那 12 句），只替换其中的实体
4. 去重：同一模板+同一实体组合只保留一条
5. 目标 2,000 条，实际可能 1,800-2,200 条（去重后）
6. 按 sha256 切分 train/dev/holdout = 80/10/10

**产出**：`data/private/retail_ops/v1/r9/phase-a/` 目录，含 `sft.jsonl`（~1600-1800 条）和 metadata。

### 3.2 Teacher 验证子集（可选）

如果担心 oversample 后的数据质量，随机抽 200 条用 teacher 跑一遍验证通过率。
但 Phase A 的核心是实体替换，不是新模板，teacher 通过率应该接近 100%。

### 3.3 训练 Phase A 候选

```bash
# 在 gpu-5090 上执行
cd /mnt/aidata/tongjiakai/retail-agent-ops
.venv/bin/retail-agent-ops build \
  --config configs/retail_ops_v1_r9_phase_a_sft.yaml \
  --input_dir data/private/retail_ops/v1/r9/phase-a \
  --output_dir reports/retail_ops/v1/r9/phase-a/sft-001
```

训练配置：Qwen3-4B + QLoRA full linear, r=16, alpha=32, 3 epoch, lr=2e-4。

### 3.4 评测

```bash
# Dev 评测（现有 60 条）
.venv/bin/retail-agent-ops evaluate \
  --config configs/retail_ops_v1_r9_phase_a_dev.yaml

# OOD 评测（现有 60 条）
.venv/bin/retail-agent-ops evaluate \
  --config configs/retail_ops_v1_r9_phase_a_ood.yaml

# Oversampled OOD（新增 60 条，同模板不同实体）
.venv/bin/retail-agent-ops evaluate \
  --config configs/retail_ops_v1_r9_phase_a_ood_oversampled.yaml
```

### 3.5 Phase A 判读

按 Spec §2.3 的判读规则：
- OOD ≥ 0.70 → 进入 Phase B
- OOD 改善但 < 0.70 → 必须进入 Phase B
- OOD 无停止 → 跳过 Phase B，重新诊断

**把 Phase A 结果写入 `findings.md` 和 `progress.md`，然后请求用户确认是否进入 Phase B。**

## 第四步：Phase B（需用户确认）

**Phase B 启动前必须获得用户对以下两项的明确确认：**
1. 同意扩展工具集（3→5 工具）
2. 同意新增场景（6→12 场景）

### 4.1 定义 5 工具 schema

在 `domains/retail_ops/v4/tools.yaml` 中定义 5 个工具：
- get_order（从 v1 复制）
- refund_order（从 v1 复制）
- get_store_hours（从 v1 复制）
- get_refund_status（新增）
- cancel_order（新增）

每个工具需要：name, description（含"何时使用"语义）, parameters（JSON Schema）。

### 4.2 定义 12 场景模板

在 `src/veritool_rl/retail_ops/domain/v4_tasks.py` 中定义 12 类场景：
- 原有 6 类（从 formal_tasks.py 复制逻辑）
- 新增 6 类（check_refund_status, cancel_eligible, cancel_denied_recent, cancel_denied_in_use, refund_then_cancel, cancel_recovery）

每类 5 种口吻：书面正式、口语随意、极简指令、情绪化、中英混合。

### 4.3 Teacher 采集 2500 条

用 DeepSeek teacher 为每个模板生成完整轨迹。质量门：通过率 ≥ 85%。

### 4.4 训练 Phase B 候选

同 Phase A 的训练配置，只是输入数据换为 Phase B 的 2500 条。

### 4.5 全套评测

- dev（原有 60 条）→ 检测退化
- OOD v2（原有 60 条）→ 核心对比
- 跨工具 OOD（新增 40 条）→ 工具选择泛化
- 多步组合（新增 30 条）→ 多步容错

## 第五步：独立验收

Phase A 和 Phase B 各完成后，分别做一轮独立验收：

1. **数据质量检查**：
   - 训练集去重率（期望 > 95%）
   - 每个场景/工具类别至少 50 条
   - teacher 通过率 ≥ 85%

2. **评测一致性检查**：
   - dev 结果与 baseline 可比（不应大幅下降）
   - OOD 评测集无数据泄露（与训练集无逐字重复）

3. **代码兼容性检查**：
   - `pytest -q` 全绿
   - ruff / mypy / lock / diff 全绿
   - v1/v2 bundle 逐字节未动

4. **结果诚实性检查**：
   - 判读按 Spec §4.3 的规则，不自行调整阈值
   - 结果写入 findings.md，标注"探索性结论，不用于发布判定"

## 第六步：更新文档

完成后更新：
- `findings.md`：追加 Phase A/B 结果
- `progress.md`：追加运行记录
- `docs/PROJECT_LOG.md`：追加 LOG（如果结果有方法论级发现）
- `docs/EXECUTION_PLAN.md`：更新阶段状态

## 验收命令

```bash
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy
env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check
.venv/bin/python scripts/ci/audit_public_release.py
.venv/bin/python scripts/ci/verify_qualification_chain.py
git diff --check
```

## 硬边界

- **不改 parser / max_steps / verify_final_state**
- **不改发布门禁阈值**
- **不消耗封存 holdout 观测**
- **不替换当前候选 sft-008**
- **Phase B 必须获得用户确认才启动**
- **远程 GPU 命令必须逐条确认**
