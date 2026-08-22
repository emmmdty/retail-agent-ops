# R9 Phase B 执行提示词

**用途**：新窗口启动时，按此提示词执行 R9 Phase B（数据多样性扩展）。
**前置**：读完本文档后，先按 AGENTS.md 固定流程恢复上下文。

---

## 第一步：恢复上下文（必须按顺序）

1. `AGENTS.md`（固定流程）
2. `docs/EXECUTION_PLAN.md`（阶段状态）
3. `docs/R9_SPEC.md`（本轮 Spec，重点 §3 Phase B）
4. `docs/R8_DIAGNOSIS.md`（根因分析）
5. `task_plan.md` R9 节（当前状态）
6. `findings.md` 最后 100 行（Phase A 结果）
7. `progress.md` 最后 50 行
8. `docs/PROJECT_LOG.md` 最近一条 LOG

## 第二步：只读 Preflight

```bash
.venv/bin/pytest -q                    # 确认 1219 passed
.venv/bin/ruff check .                 # 确认 All checks passed
.venv/bin/ruff format --check .        # 确认 207 files already formatted
.venv/bin/mypy                         # 确认 Success, no issues found
env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check  # 确认 Resolved 105 packages
git diff --check                       # 确认干净
git log --oneline -3                   # 确认 HEAD 状态
```

## 第三步：Phase B 前置确认

**Phase B 启动前必须获得用户对以下两项的明确确认：**
1. 同意扩展工具集（3→5 工具）
2. 同意新增场景（6→12 场景）

**如果用户未确认，不得进入 Phase B 实现。**

## 第四步：定义 5 工具 schema

在 `domains/retail_ops/v4/tools.yaml` 中定义 5 个工具：

| 工具 | 来源 | 说明 |
|---|---|---|
| get_order | 从 v1 复制 | 查询订单详情 |
| refund_order | 从 v1 复制 | 办理退款 |
| get_store_hours | 从 v1 复制 | 查询门店营业时间 |
| get_refund_status | **新增** | 查询退款状态（与 get_order 有语义重叠） |
| cancel_order | **新增** | 取消订单（与 refund_order 有语义重叠） |

每个工具需要：
- name
- description（含"何时使用"语义）
- parameters（JSON Schema）

**关键设计**：新增工具与原有工具有**语义重叠**，模型需要学会在多个可能的工具中选择正确的那个。

## 第五步：定义 12 场景模板

在 `src/veritool_rl/retail_ops/domain/v4_tasks.py` 中定义 12 类场景：

| 原有 6 类 | 新增 6 类 |
|---|---|
| lookup_status | check_refund_status（需要 get_refund_status） |
| refund_eligible | cancel_eligible（需要 cancel_order） |
| refund_denied_window | cancel_denied_recent（取消最近订单被拒） |
| refund_denied_ownership | cancel_denied_in_use（订单使用中被拒） |
| refund_denied_duplicate | refund_then_cancel（退款后取消关联订单） |
| refund_recovery | cancel_recovery（取消失败后重试） |

每类 5 种口吻：书面正式、口语随意、极简指令、情绪化、中英混合。

**模板数量**：12 类 × 5 口吻 = 60 句模板。

## 第六步：Teacher 采集 2500 条

用 DeepSeek teacher 为每个模板生成完整轨迹。

**质量门**：通过率 ≥ 85%。

**执行命令**（需用户逐条确认）：

```bash
# CPU 实现（不消耗 API）
.venv/bin/retail-agent-ops build \
  --config configs/retail_ops_v1_r9_phase_b_teacher.yaml \
  --input_dir data/private/retail_ops/v1/r9/phase-b \
  --output_dir reports/retail_ops/v1/r9/phase-b/teacher-001
```

**GPU 训练**（需用户确认）：

```bash
# 在 gpu-5090 上执行
cd /mnt/aidata/tongjiakai/retail-agent-ops
.venv/bin/retail-agent-ops build \
  --config configs/retail_ops_v1_r9_phase_b_sft.yaml \
  --input_dir data/private/retail_ops/v1/r9/phase-b \
  --output_dir reports/retail_ops/v1/r9/phase-b/sft-001
```

训练配置：Qwen3-4B + QLoRA full linear, r=16, alpha=32, 3 epoch, lr=2e-4。

## 第七步：全套评测

```bash
# Dev 评测（原有 60 条，检测退化）
.venv/bin/retail-agent-ops evaluate \
  --config configs/retail_ops_v1_r9_phase_b_dev.yaml

# OOD v2 评测（原有 60 条，核心对比）
.venv/bin/retail-agent-ops evaluate \
  --config configs/retail_ops_v1_r9_phase_b_ood.yaml

# 跨工具 OOD 评测（新增 40 条，工具选择泛化）
.venv/bin/retail-agent-ops evaluate \
  --config configs/retail_ops_v1_r9_phase_b_cross_tool.yaml

# 多步组合评测（新增 30 条，多步容错）
.venv/bin/retail-agent-ops evaluate \
  --config configs/retail_ops_v1_r9_phase_b_multi_step.yaml
```

## 第八步：Phase B 判读

按 Spec §3.3 的判读规则：

| 结果 | 判定 |
|---|---|
| OOD ≥ 0.80 + 跨工具 ≥ 0.70 | 数据多样性是主因，可考虑继续扩大 |
| OOD 改善但跨工具差 | 多样性有帮助但跨工具组合需要更多数据 |
| 任意评测集下降 | 新工具引入了干扰，需要更精细的数据平衡 |

**把 Phase B 结果写入 `findings.md` 和 `progress.md`。**

## 第九步：独立验收

Phase B 完成后，做一轮独立验收：

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
   - 判读按 Spec §3.3 的规则，不自行调整阈值
   - 结果写入 findings.md，标注"探索性结论，不用于发布判定"

## 第十步：更新文档

完成后更新：
- `findings.md`：追加 Phase B 结果
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
- **远程 GPU 命令必须逐条确认**
- **v1/v2 bundle 逐字节不动**

## Phase A 已知结果

- Dev：task_success 0.983 (59/60)，显著优于 baseline 0.800 (48/60)
- OOD：评测失败，未产出结果
- 根因：oversampling 脚本未更新 trajectory steps 中的 tool_call arguments（已修复）

## Phase B 与 Phase A 的关系

- Phase A 测试"数据量"的独立贡献（240→1600 条）
- Phase B 测试"数据多样性"的独立贡献（3→5 工具，6→12 场景，12→60+ 模板）
- 两者互补，不是替代关系
