# 封存 holdout 观测台账

**本文件是封存 holdout 观测次数与状态的唯一事实源。**其它任何文档（`README.md`、
`docs/SYSTEM_CARD.md`、`docs/MODEL_CARD*.md`、`docs/DEMO.md`、`docs/RESUME_EVIDENCE.md`）
一律**引用本文件**，不得复述次数或判定——同一个数字在五个文件里各写一遍，必然漂移，
2026-08-15 的评审就是从这里发现三处文档仍写着"唯一一次观测"的。

数字全部来自已落盘产物（`reports/retail_ops/v1/*/formal-release-00*/release.json`），
不是转述。每份 release 报告的 `report_id` 是全字段自哈希，手改任一字段都会加载失败。

## 当前状态

| 项 | 值 |
|---|---|
| 数据集 | `retail_ops_v1_r2_20260722`，120 条，六类各 20 |
| 已消耗观测 | **3 次**（2026-08-11、2026-08-14、2026-08-15），第三次含 **3 次运行**（base / candidate / 合并版探针） |
| 剩余"未观测"状态 | **无**。每一次新判定都需用户单独决策 |
| 最新判定 | **NO-GO / baseline**（三次判定全部如此） |
| 阈值变更次数 | **0**（`tests/test_retail_ops_r4_release_configs.py::test_release_config_does_not_touch_the_gates` 锁定） |

配对可比性的连带代价：`code_commit`、`uv_lock_sha256`、`system_prompt_sha256` 都在
`SEALED_PAIRING_FIELDS` 内，因此**任何后续提交之后，已有的 sealed base 证据都不再可与
新候选配对**。下一次判定必然是 base + candidate **两侧**完整重跑。

## 观测 1 — 2026-08-11（LOG-20260811-03）

| | base | candidate |
|---|---|---|
| policy | `qwen:Qwen/Qwen3-4B@8cd0101f` | 同基座 `+adapter:reports/retail_ops/v1/r3/sft-001#34544fac3ec9` |
| `task_success` | 0.7833（94/120） | 0.7500（90/120） |
| `policy_violation_count` | 16 | 0 |
| `invalid_call_count` | 41 | 0 |
| `schema_valid_rate` | 0.7819 | 1.0000 |
| `p95_latency_ms` | 5255.02 | 5711.94 |

**判定：NO-GO / baseline**，唯一失败门禁 `success_delta` = **−0.0333** < +0.05。
其余四项全过（`policy_violation_delta` −16、`invalid_call_count` 0、
`p95_latency_ratio` **1.0870** ≤ 1.25、`evidence_complete` true）。

候选失败 **100% 是 `premature_final_response`**，`refund_eligible` 20/20 全数失败——
判定正确但不执行。`code_commit` `90c9038`，`report_id` base `b538a6c4…` / candidate `a8cfcf38…`。

## 观测 2 — 2026-08-14（LOG-20260814-04）

| | base | candidate |
|---|---|---|
| policy | `qwen:Qwen/Qwen3-4B@8cd0101f` | 同基座 `+adapter:reports/retail_ops/v1/r4/sft-006#8a49251fbfc9` |
| `task_success` | 0.8583（103/120） | **1.0000（120/120，六类各 20/20）** |
| `policy_violation_count` | 11 | 0 |
| `invalid_call_count` | 5 | 0 |
| `schema_valid_rate` | 0.9691 | 1.0000 |
| `p95_latency_ms` | 3052.15 | 5730.25 |
| `average_tool_calls` | 1.3083 | 1.5000 |
| `average_latency_ms` | 1958.26 | 4457.06 |

**判定：NO-GO / baseline**，唯一失败门禁 `p95_latency_ratio` = **1.8774** > 1.25。
`success_delta` **+0.1417** 通过。`code_commit` `ae82917`，
`report_id` base `89fe01d8…` / candidate `866d21e9…`。

**延迟代价的归因**（这一条决定了后续做法）：调用次数只增 **1.146×**、turns 1.061×，
而单次调用耗时 **1496.8 → 2971.4 ms（1.985×）**。因此代价来自**全 linear LoRA 的前向
开销**，不是"候选多做了工具调用"。旁证：观测 1 的 attention-only adapter（4 投影）
p95 比值仅 1.087。

## 观测 3 — 2026-08-15（LOG-20260815-03，第三次判定，两套口径并列）

代码冻结于 `b529bc9`，三次运行同 commit、同 `uv_lock` `9227e307…`。
**base / candidate 侧相对第二次观测除 `attempt_id` 外逐字段相同**（模型 pin、生成参数、
receipt、bundle 一个字未改），有治理测试锁定；因此两次之间的差异只可能来自
`code_commit` 与 `uv_lock`。

| | base-003 | candidate-003（未合并） | merged-003（**探针**） |
|---|---|---|---|
| `report_id` | `931ed6f8…` | `4c8839a2…` | `19f858fb…` |
| `task_success` | 0.8583（103/120） | **1.0000** | **1.0000** |
| `policy_violation_count` | 11 | 0 | 0 |
| `invalid_call_count` | 5 | 0 | 0 |
| `average_tool_calls` | 1.3083 | 1.5000 | **1.5000** |
| 单次调用耗时 | 1389.3 ms | 2946.5 ms | **1717.7 ms** |
| `p95_latency_ms` | 2787.4 | 5644.4 | **3384.0** |
| 输出吞吐 | 50.66 tok/s | 29.78 | **48.87** |
| wall time | 218.4 s | 530.7 s | 309.5 s |

**任务指标逐位复现**：base-003 与 base-002 的 `task_success` / 违规 / 非法调用 /
schema 合规率完全相同，candidate 同理。跨 commit 的确定性成立。

### 第三次判定（未合并候选，两套口径）

| | v1.0 | v1.1 |
|---|---|---|
| `success_delta` | PASS +0.1417 | PASS +0.1417 |
| `success_delta_ci_lower` | — | **PASS +0.0833** |
| `policy_violation_delta` | PASS −11 | PASS −11 |
| `invalid_call_count` | PASS 0 | PASS 0 |
| `p95_latency_ratio` | **FAIL 2.0250** | 已拆分 |
| `per_call_latency_ratio` | — | **FAIL 2.1209** |
| `steps_to_success_ratio` | — | PASS 0.9841 |
| `latency_per_success_ratio` | — | **FAIL 2.0871** |
| **判定** | **NO-GO / baseline** | **NO-GO / baseline** |

**三次判定全部 NO-GO，阈值一个字未改。**

### 合并部署形态的诊断算术——**不是发布判定**

合并版没有 adapter、且是不同的 `ModelArtifact`，`require_comparable_sealed_runs`
会（正确地）拒绝把它当作 candidate：该契约要求 candidate = 同一基座 + adapter。
**因此下面这组数字是诊断，不是判定，不得表述为"候选通过了发布门禁"。**

同一批门禁算术，把候选侧换成合并版：

| 门禁 | v1.0 | v1.1 |
|---|---|---|
| `success_delta` | PASS +0.1417 | PASS +0.1417 |
| `success_delta_ci_lower` | — | PASS +0.0833 |
| `policy_violation_delta` | PASS −11 | PASS −11 |
| `invalid_call_count` | PASS 0 | PASS 0 |
| `p95_latency_ratio` | **PASS 1.2141** | 已拆分 |
| `per_call_latency_ratio` | — | **PASS 1.2364** |
| `steps_to_success_ratio` | — | PASS 0.9841 |
| `latency_per_success_ratio` | — | **PASS 1.2167** |
| 失败门禁 | 无 | 无 |

**同一份权重、同一套行为**（两侧 `average_tool_calls` 都是 1.5000、任务指标都是
120/120），只差加载方式，就是 NO-GO 与"全部门禁算术通过"之间的全部距离。

**四条必须一起说的限制**：

1. **这不是 GO。** 正式判定是上面那两张表：**NO-GO**。要让合并形态获得判定，需要
   版本化 `SealedEvaluationReport` 使"合并型候选"可被表达——那是一次独立决策，
   且 `report_id` 是全字段自哈希，需要版本感知的内容哈希才能让两份旧证据仍可加载。
2. **余量很薄**：1.2141 与 1.2364 对阈值 1.25，只剩 3% 和 1%。而 base 侧的 p95 在
   观测 2 是 3052.2 ms、观测 3 是 2787.4 ms——同机同配置，**9% 的波动**。
   **一次重跑就可能把它推到另一侧。** 不得据此宣称延迟问题已解决。
3. **本次观测消耗了三次运行**（base / candidate / 合并版探针）。合并版探针只为测部署
   形态，但它同样产出任务指标、同样读了 holdout，因此如实计入消耗。
4. 120/120 仍**不是泛化证据**：train/dev/holdout 共用同一批 12 句模板（见下方边界）。

## 新口径（gate schema v1.1）复算：两次判定都**不变**

2026-08-15 用版本化后的 v1.1 门禁重算了上面两次观测（**读已落盘证据，未跑模型、
未消耗观测**）。两次仍是 **NO-GO / baseline**，没有任何候选翻转。逐门禁对照与
诚信前提见 [`GATE_SCHEMA_V11_RECOMPUTE.md`](./GATE_SCHEMA_V11_RECOMPUTE.md)。

两条必须一并引用的结论：

- **观测 1 的部署代价此前被旧口径完全掩盖**：episode 级 `p95_latency_ratio`
  1.0870 通过，而单次调用比值是 **1.9643**。原因是那个候选更差、"说完就停"、
  调用更少、结束更早——**做得更差反而显得更快**。
- **观测 2 的提升通过了配对显著性检验**：`success_delta_ci_lower` = **+0.0833 > 0**
  （配对 bootstrap CI95 下界），且 `steps_to_success_ratio` = **0.9841 < 1**——
  候选每成功一条任务所需的调用比基座**更少**。它的两项失败门禁几乎完全由单次
  前向开销构成，不是"多做了工作"。

## 判定口径的边界（引用时必须一并引用）

1. **120/120 不是泛化证据。** `domain/formal_tasks.py:_user_request` 只有 6 场景 × 2 变体
   = 12 句中文模板，train / dev / holdout **共用这 12 句**；跨 split 变化的只有随机
   order_id、reason 枚举词、deadline margin、distractor 数量与 lookup status。五维指纹
   保证的是"没有逐字重复"，**不是"没有分布重叠"**。在分布外 holdout（提示词 §7.1）
   完成之前，不得把 120/120 表述为泛化能力。
2. **两次结果都不得反馈进开发**：不得进入训练、调参、checkpoint 选择或 prompt/parser 修改。
3. **`p95_latency_ratio` 的口径是部署形态而非模型能力**。观测 2 的候选在任务指标上满分，
   被自己的部署实现（未 merge 的 LoRA + 逐 episode 串行 HF `generate`）挡在门外。
   **merge 后的对照已于 2026-08-15 在 dev 上完成**（见
   [`SERVING_FORM_COMPARISON.md`](./SERVING_FORM_COMPARISON.md)）：同一份行为下单次调用
   耗时 −46%、吞吐回到基座水平以上，任务指标 60/60 未损伤。**但那是 dev 不是 holdout**，
   且旧 v1.0 口径下合并版在 dev 上仍然失败（p95 比值 1.3130 > 1.25）。
   任何新的发布判定都需要**第三次**封存 holdout 观测，属用户单独决策门。

## 变更规则

- 只有真正落盘并被读取的观测才写进本表（判据是"有没有数字落盘并被读取"，不是跑了多久）。
  2026-08-11 之前有一次运行被机器重启中断、**零产出**，未消耗盲性，因此不计入。
- 每条记录必须带 LOG ID、`code_commit` 与两侧 `report_id`。
- 历史条目不得改写。判定被新口径重算时，新旧结论**并列**陈述并写清口径差异。
