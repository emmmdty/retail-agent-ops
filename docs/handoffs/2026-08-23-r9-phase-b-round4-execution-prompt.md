# R9 Phase B 第四轮执行提示词：专修 refund_then_cancel 双订单场景

**用途**：新窗口启动时，按此提示词执行 Phase B 第四轮。
**前置**：读完本文档后，先按 AGENTS.md 固定流程恢复上下文。

---

## 第一步：恢复上下文（必须按顺序）

1. `AGENTS.md`（固定流程）
2. `docs/R9_PHASE_B_RESULTS.md`（**第三轮收尾存档——本轮的直接前情**）
3. `docs/PROJECT_LOG.md` 最近三条 LOG（20260822-03/04/05）
4. `findings.md` 的「R9 Phase B 发现」小节
5. `task_plan.md`、`progress.md` 最新小节
6. `src/veritool_rl/retail_ops/domain/formal_tasks.py` 的 `_v4_scenario_contract`
   与 `domain/environment.py` 的 `_cancel_order`

## 第二步：只读 Preflight

```bash
.venv/bin/pytest -q                    # 1226 passed
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy                         # Success
env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check
git diff --check && git log --oneline -3
```

若 HEAD 在 `64a6e8f` 之后且含 findings/progress/文档更新提交，属正常。

## 第三步：问题定义（不要重新诊断，直接从这里出发）

**目标失败模式**：refund_then_cancel 场景（12 场景中唯一双订单任务）：

```
用户请求：「请先为订单 A 办理退款，再取消订单 B。」（B 是独立订单）
gold 序列：get_order(A) → refund_order(A) → get_order(B) → cancel_order(B)
模型实际：get_order(A) → get_order(B) → refund_order(A) → refund_order(B)
                                                        ↑ 把 B 也退款了
```

三轮读数：sft-001 dev 4/10；sft-002/sft-003 全评测面 **0/10**
（dev、OOD v4 均然）。失败与措辞增强负相关；oversample 已证明有害。

**已证伪的方向（不得重复）**：
- ❌ 调该场景 oversample 权重（×3 使其恶化到 0/10；去掉也不恢复）
- ❌ 统一调用顺序假设（教师序与 Oracle 序混合不是原因——sft-003 已排除）

## 第四步：第四轮主攻方向（用户已批准的方向）

**核心假设**：cancel 动作先验太弱。语料中 refund 动作频率远高于 cancel，
模型对「提到的订单」默认用主导动作（退款）处理。修复方向是**提高 cancel
先验或降低复合任务的组合难度**，按以下两个方案做单变量消融：

### 方案甲（推荐先做）：提高 cancel 类场景数据配比

- 把 CANCEL_ELIGIBLE / CANCEL_RECOVERY / CANCEL_DENIED_* 从每场景 20 个
  train family 提到 30–35 个（改 `_v4_family_spec` 的切分逻辑或加 per-scenario
  oversample），使 cancel 动作样本占比接近 refund。
- **单变量纪律**：只改这一个配比，其余（bank-v4 措辞 ×3、无 rtc oversample）
  与 sft-003 完全一致。新导出 attempt_id `train-export-v4-004`，候选 `sft-004`。
- 预期：rtc dev ≥ 5/10 即视为方向正确；同时盯 OOD v2 duplicate-deny 不许
  恶化（pv ≤ 7）。

### 方案乙（甲不达标时）：RTC 中间辅助任务课程

- 构造辅助训练场景 `rtc_stepwise`：同一状态拆成两段——第一段只要求
  「查 B 并取消 B」（复用 cancel_eligible 结构但订单号来自 RTC 的 other_order），
  让模型在简单语境下学会「第二个被点名的订单 → cancel」；
  再混入完整 RTC。比例约 辅助:完整 = 1:1。
- 需要新增 scenario 枚举值 + 合约 + 用户请求模板；走 TDD。
- 此方案改动面大，**必须先把方案写进 task_plan.md 并获用户确认再动工**。

### 判读规则（跑之前写定，写入 task_plan.md 后提交）

| 结果 | 判定 | 后续 |
|---|---|---|
| rtc dev ≥ 8/10 且 OOD v4 rtc ≥ 5/10 且 pv 不升 | 修好 | 收口 Phase B |
| rtc 改善但 < 上述线 | 方向对，力度不够 | 甲→乙升级或加大配比 |
| rtc 无改善或 pv 恶化 | 假设错 | 停止，记录负结果，Phase B 就此收口 |

## 第五步：执行命令（GPU 部分需逐条确认）

```bash
# 本地 CPU：导出（不消耗 API）
.venv/bin/retail-agent-ops build \
  --config configs/retail_ops/build/<新导出配置>.yaml \
  --input_dir data/private/retail_ops/v1/r2/retail_ops_v4_20260822 \
  --output_dir reports/retail_ops/v1/r9/phase-b/train-export-004

# gpu-5090 训练（需确认；~25min，1920+ 行）
ssh gpu-5090 "cd /mnt/aidata/tongjiakai/retail-agent-ops && \
  env TORCH_DISABLE_NATIVE_JIT=1 .venv/bin/retail-agent-ops build \
  --config configs/retail_ops/build/retail_ops_v4_r9_sft.yaml \
  --input_dir data/private/retail_ops/v1/r2/retail_ops_v4_20260822 \
  --output_dir reports/retail_ops/v1/r9/phase-b/sft-004"

# 三面评测链（需确认；~40min）：v4 dev → OOD v2 → OOD v4
# 配置模板已存在：retail_ops_v4_r9_dev_sft00{3}.yaml /
# retail_ops_ood_r9_sft00{3}.yaml / retail_ops_ood_v4_r9_sft00{3}.yaml
# 复制替换 adapter 哈希与 attempt_id 即可（注意别残留旧 attempt_id！）
```

**已知坑（前三轮踩过，勿再踩）**：
1. 远端工作树不干净会拒盖 code_commit——同步后先 commit；
2. 训练用 SFT 格式 dev.jsonl、评测用 TaskSpec 格式，同路径互斥——
   训练前换入 SFT 版（`dev-sft/dev-sft-v4-001/sft.jsonl`），
   评测前换回 TaskSpec 版（本地 `data/private/.../dev.jsonl`）；
3. 新 adapter 的 `file_sha256` 必须从远端 `sha256sum` 现算填入，不能留空 `{}`；
4. 输出目录不可覆盖——重跑前先删旧目录或换 attempt_id。

## 第六步：结果判读与收尾

1. 按第四步判读规则得出结论，**如实记录负结果**；
2. 更新 `docs/R9_PHASE_B_RESULTS.md`（追加第四轮小节）、
   `findings.md`、`progress.md`、LOG；
3. 若 rtc 修复：把「cancel 先验」经验写成可复用结论；
4. 若未修复：Phase B 按第五节限定口径收口，rtc 作为已知边界写入文档。

## 硬边界（与前三轮相同）

- 不改 parser / max_steps / verify_final_state
- 不改发布门禁阈值；发布候选仍是 sft-008，本轮结论仅探索性
- 不消耗封存 holdout 观测
- 远程 GPU 命令逐条确认；API 调用前预估费用并监控余额（上轮 ~¥11 教训）
- v1/v2 bundle 逐字节不动；OOD v2 任务集不动

## 当前基线速查

| 资产 | 值 |
|---|---|
| sft-003（对照点） | dev 0.917/pv0 · OOD v2 0.867/pv7 · OOD v4 0.892/pv2 |
| rtc 现状 | dev 0/10 · OOD v4 0/10 |
| bank-v4 sha256 | `aa6ccee397266e2aa8501ffed08c92412759809c341b8a0ab6a5420c8fe533d9` |
| 数据版本 | `retail_ops_v4_20260822` / OOD `retail_ops_ood_v4_20260823` |
| 单轮采集成本 | ~¥1.3；SFT ~25min；三面评测 ~40min |
