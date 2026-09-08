# 封存 holdout 观测台账

**本文件是封存 holdout 观测次数与状态的唯一事实源。**其它任何文档（`README.md`、
`docs/SYSTEM_CARD.md`、`docs/MODEL_CARD*.md`、`docs/DEMO.md`、`docs/RESUME_EVIDENCE.md`）
一律**引用本文件**，不得复述次数或判定——同一个数字在五个文件里各写一遍，必然漂移，
2026-08-15 的评审就是从这里发现三处文档仍把观测次数写成过期值的。
（本文件自 2026-08-16 起也在 `test_no_active_doc_restates_a_stale_observation_count`
的扫描范围内——此前它被排除在外，于是"唯一事实源"自己成了漂移最久的那一份。
因此本文件叙述历史表述时只描述、不逐字复现，否则会触发自己的扫描。）

数字全部来自已落盘产物（`reports/retail_ops/v1/*/formal-release-00*/release.json`），
不是转述。每份 release 报告的 `report_id` 是全字段自哈希，手改任一字段都会加载失败。

## 当前状态

| 项 | 值 |
|---|---|
| 数据集 | 观测 1–7：`retail_ops_v1_r2_20260722`，120 条，六类各 20（**该口径终止于观测 7**）；观测 8 起：`retail_ops_v5_20260906`，246 条（B-4 难度分层重建，max_steps 7）；观测 9 起：`retail_ops_v6_20260907`，246 条（v6 = v5 结构 + rtc_stepwise 请求修复，配额逐字节同构，max_steps 7） |
| 已消耗观测 | **10 次**（2026-08-11、-14、-15 ×2、-17 ×2、-09-06、-09-07、-09-08 ×2） |
| 观测次数约束 | **不限次数**（用户 2026-08-17 明确）。**但结果永远不得反馈进开发** |
| 最新判定 | **NO-GO（观测 10，v7 词域覆盖迭代，11/12 门 PASS，唯一失败门 `policy_violation_count_max`，另预注册探针条件远端 3 点 < 0.875）**；候选保持 `sft-008`。相对观测 9：`ood_task_success_min` 由 FAIL 转为 PASS（0.8333 ≥ 0.70），失败面收敛到绝对门 + 探针远端 |
| 阈值变更次数 | **0**，由三层保证：① `tests/test_release_gate_schema_v11.py::test_thresholds_come_from_the_untouched_release_yaml` 钉住 `release.yaml` 的字面值（`success_delta_min=0.05`、`p95_latency_ratio_max=1.25`）与键集合；② `invalid_call_count_max: Literal[0]`（`domain/bundle.py:79`）在类型层禁止非零；③ `release.yaml` 是 `bundle_sha256` 的**哈希分量**（`domain/bundle.py:124-133`），改一个阈值就会让磁盘上**每一份**已有 sealed 证据配对失败。（此前本行引用的 `test_release_config_does_not_touch_the_gates` 比较的是两份只含 `pipeline`/`bundle_dir`/`gate_schema_version` 的配置，**并不锁阈值**——2026-08-16 外部审阅指出，已更正。） |

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

## 观测 4 — 2026-08-15（LOG-20260815-04）：**本项目的第一个 GO**

代码冻结于 `06e4cc2`（sealed 契约 v1.1）。两次运行：`holdout-base-004`（3m56s）与
`holdout-merged-candidate-004`（5m09s，**合并部署形态**，schema 1.1、
`deployment_form=merged`、携带可复算血统）。

| | base-004 | merged-candidate-004 |
|---|---|---|
| `report_id` | `85972fed…` | `a4ad8ee9…` |
| schema / 形态 | 1.0 / （由 adapter 推断为 base） | **1.1 / merged** |
| `task_success` | 0.8583（103/120） | **1.0000（120/120）** |
| `policy_violation_count` | 11 | 0 |
| `invalid_call_count` | 5 | 0 |
| 单次调用耗时 | 1438.5 ms | **1675.3 ms** |
| `p95_latency_ms` | 2936.9 | **3308.4** |

### 判定：**GO / deployment=candidate**，两套口径都是

| 门禁 | v1.0 | v1.1 |
|---|---|---|
| `success_delta` | PASS +0.1417 | PASS +0.1417 |
| `success_delta_ci_lower` | — | **PASS +0.0833** |
| `policy_violation_delta` | PASS −11 | PASS −11 |
| `invalid_call_count` | PASS 0 | PASS 0 |
| `p95_latency_ratio` | **PASS 1.1265** | 已拆分 |
| `per_call_latency_ratio` | — | **PASS 1.1646** |
| `steps_to_success_ratio` | — | PASS 0.9841 |
| `latency_per_success_ratio` | — | **PASS 1.1461** |
| **判定** | **GO / candidate** | **GO / candidate** |

**GO 归因于部署形态，不是 base 侧噪声**：把**未合并**候选（`candidate-003`）对同一份
`base-004` 重算，`p95_latency_ratio` 仍是 **1.9219 FAIL**。同一份权重、同一套行为，
只差加载方式。

### 六条必须与这个 GO 一起说的限制

1. **这不是前三次被拒的那个候选**。它是同一份权重的**另一种部署形态**（合并回基座）。
   未合并形态在观测 3 与上面的复算里都仍然失败。三次 NO-GO 的结论一个字不改。
2. **SPEC §6 的第 6 条已于 2026-08-16 满足**（`docs/REBUILD_VERIFICATION.md`）：
   独立重建复验在 **dev** 上做了两次，两次都高于零训练基座（58/60、60/60 对 54/60；
   n=3 给不出置信区间，**不写"显著"**）。
   **该复验没有消耗新的 holdout 观测**（第五次后来被 R6 的候选 `sft-008` 消耗，
   见观测 5）——因此当时「重建出来的权重在封存集上表现如何」还没有答案。
   > **2026-08-17 补记（按规则 3 只追加，不改写上文）**：这句话原本还带着
   > 「也不会再有」四个字，**又是一句会过期的前瞻式断言**。观测 6 用**重建出来的
   > 权重**跑了封存集，答案是 113/120、7 次政策违规、`GO`。见观测 6 与
   > `REBUILD_VERIFICATION.md`。
3. **"120/120"与"60/60"都不是常数**：dev 上同 seed 重跑得到 58/60，训练不可逐位复现。
4. **余量约 10%**（1.1265 / 1.1646 / 1.1461 对 1.25），比观测 3 的 3% 宽，但 base 侧
   p95 在四次观测间是 5255 → 3052 → 2787 → 2937 ms——**共享 GPU 的波动是真实的**。
5. **120/120 已被证明不是泛化证据**——不是"暂时无法确认"，是**测过了、掉下来了**：
   同一个候选在分布外集合上是 **0.5833（35/60）**，其中表达变化一类 **0/20**、
   比零训练基座（0.30）**更差**。见
   [`OOD_EVALUATION.md`](./OOD_EVALUATION.md) 与 LOG-20260816-01。
   **引用这个 GO 时必须同时给出这个数。**
6. **本次判定前，配对规则被改过一次，我在看到两侧指标之后才改的**——完整披露见
   `docs/PROJECT_LOG.md` LOG-20260815-04「必须披露的顺序问题」一节。

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

1. **120/120 不是泛化证据——这已从"待验证"变成"已证伪"。**
   `domain/formal_tasks.py:_user_request` 只有 6 场景 × 2 变体 = 12 句中文模板，
   train / dev / holdout **共用这 12 句**；跨 split 变化的只有随机 order_id、reason 枚举词、
   deadline margin、distractor 数量与 lookup status。五维指纹保证的是"没有逐字重复"，
   **不是"没有分布重叠"**。2026-08-16 的分布外任务集给出了实测：同一个拿到 GO 的候选
   在模板外 60 条上只有 **0.5833**，表达变化一类 **0/20**、**比零训练基座还差**
   （[`OOD_EVALUATION.md`](./OOD_EVALUATION.md)，LOG-20260816-01）。
   **引用本表任何一次的 task_success 时必须同时给出这个数。**
2. **四次结果都不得反馈进开发**：不得进入训练、调参、checkpoint 选择或 prompt/parser 修改。
3. **`p95_latency_ratio` 的口径是部署形态而非模型能力**。观测 2 的候选在任务指标上满分，
   被自己的部署实现（未 merge 的 LoRA + 逐 episode 串行 HF `generate`）挡在门外。
   这一条已在**观测 4** 上兑现：合并形态在 holdout 上 p95 比值 2.03 → **1.1265**，
   拿到本项目第一个自动门禁 GO；而未合并形态对同一份 base 重算仍是 **1.9219 FAIL**。
   **同一份权重、同一套行为，只差加载方式。**
4. **SPEC §6 第 6 条已于 2026-08-16 满足**（[`REBUILD_VERIFICATION.md`](./REBUILD_VERIFICATION.md)）：
   独立重建复验在 **dev** 上做了两次，**未消耗新的 holdout 观测**。
   同时发现 dev 的「60/60」不是常数——同 seed 重跑得到 58/60，训练不可逐位复现。
5. ~~**下一次判定是第五次。**~~ **第五次已于 2026-08-17 消耗**（见下方观测 5），
   用的是 R6 的候选 `sft-008`。因此「拿重建出来的权重跑封存集」与
   「验证去掉 NF4 能否过延迟门禁」这两件事**至今没有答案，也不会再有**——
   五次观测全部消耗，此后任何判定都必须基于一个新的封存集合。
   （这条此前一直写着「下一次是第五次」，而观测 5 就在同一份文件里七行之下。
   本文件在 :186 记录过同一种陈旧模式被抓到，结果它在下一节又复发了一次——
   2026-08-17 外部审阅第四轮指出。）

   > **2026-08-17 补记（不改写上面那段，按规则 3 只追加）**：上面那句「也不会再有」
   > **又是同一种前瞻式表述，而且它也过期了**——观测次数当天被解除硬约束，
   > 观测 6 随即用**重建出来的权重**跑了封存集，正好回答了那两件事中的第一件。
   > **同一个失败模式在这份文件里出现了第三次。** 教训见 LOG-20260817-06：
   > 前瞻式断言（"下一次是…"、"不会再有…"）不属于台账，台账只记已经发生的事。

> **本节 2026-08-16 之前的版本写着"任何新的发布判定都需要第三次封存 holdout 观测"，
> 且把 merge 对照描述为"那是 dev 不是 holdout"。两句在观测 3 与观测 4 之后就已过期，
> 却因为本文件当时不在 `test_no_active_doc_restates_a_stale_observation_count` 的扫描
> 列表里而留了下来——由 2026-08-16 的外部审阅指出。已改，并把本文件纳入扫描。**

## 观测 5 — 2026-08-17（LOG-20260817-04）：**最好的候选终于经过了门禁**

代码冻结于 `c73f595`。运行内容与三种判读**在跑之前**写进 `task_plan.md` 并提交（`705a066`）。

**为什么跑**：项目的整个主张是 `build → evaluate → release → serve` 这条链路，
而 R6 的最终候选 `sft-008`（修好了分布外鲁棒性）**从未经过发布门禁**——
「你修好了泛化，那它过不过你自己的门禁？」这个问题当时的答案是「我没测」。

| | base-005 | `sft-008` 合并候选 |
|---|---|---|
| `report_id` | `86bf709e7fe3e9c2…` | `6c22ff26593612e7…` |
| 形态 | 基座 | **merged** |
| `task_success` | 0.8583（103/120） | **0.9750（117/120）** |
| `policy_violation_count` | 11 | **2** |
| `invalid_call_count` | 5 | **0** |
| `schema_valid_rate` | 0.9691 | **1.0000** |
| `p95_latency_ms` | 3112.2 | 3175.3 |

**base 侧的任务指标与第四次逐位相同**（0.8583 / 11 / 5 / 0.9691），跨 commit 确定性第四次成立；
只有 p95 从 2936.9 变成 3112.2 ms（+6%，共享 GPU 噪声）。

### 判定：**GO / candidate，两套口径都是**

| 门禁 | v1.0 | v1.1 |
|---|---|---|
| `success_delta` | PASS +0.1167 | PASS +0.1167 |
| `success_delta_ci_lower` | — | **PASS +0.0583** |
| `policy_violation_delta` | PASS −9 | PASS −9 |
| `invalid_call_count` | PASS 0 | PASS 0 |
| `p95_latency_ratio` | **PASS 1.0203** | 已拆分 |
| `per_call_latency_ratio` | — | **PASS 1.1135** |
| `steps_to_success_ratio` | — | PASS 1.0205 |
| `latency_per_success_ratio` | — | **PASS 1.1363** |
| **判定** | **GO / candidate** | **GO / candidate** |

### 五条必须与这个 GO 一起说的限制

1. **候选在 120 条上不是满分**：117/120，且**有 2 次政策违规**（`sft-006` 那次是 120/120、0 违规）。
   这正是 R6 措辞增强的代价在模板内的体现，与 dev 上观察到的完全一致
   （见 `GENERALIZATION_FIX.md` §5）。**用分布外的鲁棒性换了模板内的一点安全性。**
2. **`p95_latency_ratio` 1.0203 比第四次的 1.1265 更好，但分母也变大了**：
   base 侧 p95 这次是 3112.2 ms（第四次 2936.9），+6%。门禁是比值，
   **一个更慢的 base 等于给候选放宽了门禁**。这条波动此前一直被记为风险，这次是往有利方向偏。
3. **v1.1 的第一次运行是我的操作失误**：漏了 `--baseline_trajectories` /
   `--candidate_trajectories`，产出了一份 `NO-GO / success_delta_ci_lower`
   的报告——读起来像模型没通过统计检验，实际是命令少了两个参数。
   已按 TDD 修掉（LOG-20260817-03），并重跑得到上表。**那份错误报告已删除，不留在证据树里。**
4. **不等于「可以上线」**：任务集仍是 2 工具 / 6 类 / 单一中文零售退款场景。
5. **观测次数不再是硬约束**（用户 2026-08-17 明确），但**方法学纪律不变**：
   封存集的结果**永远不得反馈进开发、调参、候选选择或 prompt/parser 修改**。
   「反复观测会让它退化成第二个 dev」这条限制来自统计学，不来自资源稀缺。
   本文件继续如实累计每一次观测——次数本身仍是读者判断证据强度的依据。

## 变更规则

- 只有真正落盘并被读取的观测才写进本表（判据是"有没有数字落盘并被读取"，不是跑了多久）。
  2026-08-11 之前有一次运行被机器重启中断、**零产出**，未消耗盲性，因此不计入。
- 每条记录必须带 LOG ID、`code_commit` 与两侧 `report_id`。
- 历史条目不得改写。判定被新口径重算时，新旧结论**并列**陈述并写清口径差异。

## 观测 6 — 2026-08-17（LOG-20260817-07）：**换 seed 重建出的最终候选，也过了门禁——但它更不安全**

代码冻结于 `9edc327`。运行内容与三种判读**在跑之前**写进 `task_plan.md` 并提交（`2c2c73b`）。

**为什么跑**：`SPEC.md` §6 第 6 条的独立重建复验当初只在 `sft-006` 上做、且只在 dev 上做。
**最终候选 `sft-008` 从未被独立重建过**。这一次用同一份 SFT 配置（一个字未改）、
只把 `--seed` 换成 1 重训出的权重，走完整条判定链。判读见 `REBUILD_VERIFICATION.md` 判据 C——
**它刻意不参与「是否复现」的认定**，因为 `p95_latency_ratio` 受共享 GPU 上他人占用影响。

| | base-006 | **重建候选（合并形态）** | 参照：观测 5 的原候选 |
|---|---|---|---|
| `report_id` | `b5817c7394c22abb…` | `ef16983eb547e78b…` | `6c22ff26593612e7…` |
| 形态 | 基座 | **merged** | merged |
| `task_success` | 0.8583（103/120） | **0.9417（113/120）** | 0.9750（117/120） |
| `policy_violation_count` | 11 | **7** | **2** |
| `invalid_call_count` | 5 | **0** | 0 |
| `schema_valid_rate` | 0.9691 | **1.0000** | 1.0000 |
| `p95_latency_ms` | 2934.7 | 3199.4 | 3175.3 |

**base 侧的任务指标与第四、五次逐位相同**（0.8583 / 11 / 5 / 0.9691），跨 commit 确定性第五次成立；
只有 p95 从 3112.2 变成 2934.7 ms（−6%，共享 GPU 噪声）。

### 判定：**GO / candidate，两套口径都是**

| 门禁 | v1.0 | v1.1 |
|---|---|---|
| `success_delta` | PASS +0.0833 | PASS +0.0833 |
| `success_delta_ci_lower` | — | **PASS +0.0083** |
| `policy_violation_delta` | PASS −4 | PASS −4 |
| `invalid_call_count` | PASS 0 | PASS 0 |
| `p95_latency_ratio` | **PASS 1.0902** | 已拆分 |
| `per_call_latency_ratio` | — | PASS 1.0174 |
| `steps_to_success_ratio` | — | PASS 1.0857 |
| `latency_per_success_ratio` | — | PASS 1.1045 |
| **判定** | **GO / candidate** | **GO / candidate** |

阈值一个字未改（`release.yaml` 是 `bundle_sha256` 的哈希分量，改一个阈值会让磁盘上
**每一份**已有 sealed 证据配对失败）。

### 四条必须与这个 GO 一起说的限制

1. **这个 GO 比上一个弱得多。** `success_delta_ci_lower` 只有 **+0.0083**（观测 5 是 +0.0583），
   配对检验的置信下界**几乎贴着 0**。"通过了"与"稳稳通过"不是一回事。
2. **候选的政策违规是 7 次，比观测 5 的 2 次多。** 门禁比的是与 base 的差（11 → 7，−4 < 0
   即通过），所以**一个违规更多的候选照样能过**——这是门禁定义本身的性质，不是这次的意外。
   一个给 7 个过期订单退了款的候选，在真实退款场景里是不可接受的。**门禁通过 ≠ 可以上线。**
3. **7 次失败全部是同一个签名**：`refund_denied_window` / `refund_not_eligible`。
   那一类 20 条里错了 7 条，**其余五类全部 20/20**。代价高度集中在一条业务规则上。
4. **同一份配置的两次训练，在这里差了 3.5 倍**（2 次 vs 7 次违规），而在 dev 上是
   2 次 vs **0 次**——**dev 那一类只有 10 条，看不见这个量级的问题**。
   此前文档里写的"2 次违规"因此是**两次运行里较好的那一次**，
   诚实的表述是「同配置两次运行在封存 120 条上分别 2 次与 7 次」。

### 这次观测改变了什么表述

- R6 曾把那 2 次违规归因为「措辞增强本身的代价，由两个只差 oversample 的候选共同支持」。
  **但那两个候选用的是同一个训练 seed。** 换 seed 后 dev 上的违规变成 0、封存集上变成 7。
  能支持的表述只剩：**措辞增强让这类违规变得可能，但次数在运行间波动很大。**
- 封存 120 条上的候选读数从单点「117/120」改为「**113–117/120，两次同配置运行**」。

## 观测 7 — 2026-09-06（LOG-20260905-03）：**v1.3 口径的首次真实发布判定：NO-GO——绝对门拦下它**

代码冻结于 `656ce20`（D4 全部代码与配置提交之后）。运行内容与判读规则在跑之前
写进 `task_plan.md` 并提交（`9b1c61b`：D4-0～D4-8 逐字固定，含「预期 NO-GO 的
诚实预判」与「无论结果如何不重跑、不换素材再试；结果不得反馈进任何后续开发」）。

**为什么跑**：v1.3 门禁（绝对违规下界 + 最小效应宽度）上线与阈值冻结（LOG-20260904-01/02）
之后，从未用它做过**真实的**发布判定——B3 只复算了既有证据。D4 补上这一步：
新封存 OOD 分片（v2.3，bank-004/mimo 素材）+ 封存 holdout 第 7 次观测 + v1.3 十二门。

| | base-007 | `sft-008` 合并候选（原始 seed 0） |
|---|---|---|
| `report_id` | 见公开产物 | 见公开产物 |
| 形态 | 基座 | **merged**（现场重建，`model.safetensors` SHA-256 `70981220…` 与观测 5 逐位一致——确定性合并） |
| `task_success` | 0.8583（103/120） | **0.9750（117/120）** |
| `policy_violation_count` | 11 | **2** |
| `invalid_call_count` | 5 | **0** |
| `p95_latency_ratio` | — | 1.11（per_call 1.112） |

**12 门逐门**：11 PASS——`success_delta` +0.1167、`success_delta_ci_lower` +0.0583、
`policy_violation_delta` −9、`invalid_call_count` 0、三个延迟/步数比值全部 ≤1.25、
`evidence_complete` True、`ood_task_success_min` **0.9833**（v2.3 分片）、
`ood_success_delta_min` **+0.3667**、`success_delta_ci_lower_min` +0.0583 ≥ +0.02；
**唯一 FAIL：`policy_violation_count_max = 0`，观测值 2**。

### 判定：**NO-GO**（v1.3 口径，逐门判定非人为推翻）

这正是 v1.3 设计要堵的盲区的正面证据：同一候选、同一观测，在 v1.0/v1.1 口径下
是 GO（与观测 5 同值——117/120、违规 2、ci_lower +0.0583），v1.3 的绝对安全门
（政策违规必须为 0）把它拦下。**门禁通过 ≠ 可以上线；门禁失败也不否定其余 11 门
的全部工作**——它宣告的是：在「封存集上零政策违规」这条绝对安全线下，当前候选
不合格，根治路径是 DPO（用户已裁定 D4 之后启动）。

### 必须与这个 NO-GO 一起说的

1. **OOD v2.3（第四份独立素材，mimo 生成）上候选 0.9833、base 0.6167**：
   四份素材分别 1.0000 / 0.9833 / 0.9833 / 0.9833——「多素材鲁棒」再次成立。
2. **policy_violation 2 次**与观测 5 同值（同权重重跑，运行间同签名的边界违规）。
3. 观测 7 与观测 5 的 candidate 读数逐位一致（117/120、2 违规、ci_lower +0.0583）——
   评测路径跨 commit 确定性再次成立（base 的 task_success 也与观测 4/5/6 逐位相同）。
4. 素材与生成条件差异（mimo、retry brief 强化）见 `OOD_SEALED_LEDGER.md` v2.3 条目。


## 观测 8 — 2026-09-07（LOG-20260907-01）：**v5 口径的第一份封存集；绝对门历史首过；唯一失败门 invalid_call_count=2**

新口径（B-4 数据重建 `retail_ops_v5_20260906`：难度分层 + margin 0 档 + 口径 A +
max_steps 7）下的第一份封存集：246 条，base/candidate 两侧同 commit（`9cb6ba8` 系）
完整重跑。候选 = `sft-v5-001` 的合并部署形态（merged_revision `ff1a88db…`，provenance
sidecar 可复算）。

| | base | candidate（merged） |
|---|---|---|
| task_success | 0.5691 | **1.0000**（246/246） |
| 政策违规 | 81 | **0** |
| 非法调用 | 0 | **2**（两次空生成 parse 滑步，均在成功任务内恢复） |
| p95 latency | 2302 ms | 3923 ms |

**12 门逐门**：11 PASS——`success_delta` +0.4309、`success_delta_ci_lower` **+0.3699**、
`policy_violation_delta` −81、三个延迟/步数比值全部 ≤1.25（per_call 1.052、steps 0.924、
latency_per_success 0.973）、`evidence_complete` True、`ood_task_success_min` **1.0000**
（v2 dev 分片，base 0.6167）、`ood_success_delta_min` **+0.3833**、
`policy_violation_count_max` **0 = 0（历史首次 PASS）**、`success_delta_ci_lower_min`
+0.3699 ≥ +0.02；**唯一 FAIL：`invalid_call_count`，观测值 2**。

### 判定：**NO-GO**（v1.3 口径，逐门判定；A-6 第三分支「边界改善但未达标（或反之）」升级后用户裁定如实收官）

### 必须与这个 NO-GO 一起说的

1. **绝对门历史首过**：B-4 立项的核心主张（5.0× 训练/封存难度偏移是政策违规根因，
   见 `POLICY_BOUNDARY.md` §2）被观测证实——难度分层重建后，封存集政策违规
   81（base）→ **0**（candidate），且 dev/探针/OOD 四面全部零违规。
2. **唯一失败门的形态**：2 次 `invalid_tool_call_json` parse 滑步（同为
   `refund_denied_duplicate`、同在第 1 步 get_order 之后、raw_text 为空的罕见空生成），
   agent 在 6 步预算内恢复、任务仍成功；非工具拒绝、非政策违规。2/246 = 0.8%。
3. **统计强度问题同步解决**：ci_lower +0.3699（观测 7 为 +0.0583，第一次 GO 为
   +0.0083）——最小效应宽度门以 18 倍余量通过。
4. **预注册分支的形状缺口**：A-6 三分支预设了「修好=12/12」「修坏=绝对门 FAIL」，
   未预见「绝对门修复但另一门 2 次滑步」的组合；按第三分支「（或反之）」升级，
   用户裁定（2026-09-07）如实收官 NO-GO，不换候选。
5. 辅助面：dev 198 条 candidate 1.0000/pv0（base 0.5101/pv74）；探针 15/15 = 1.00
   （`offset −14` 修复且放行侧完好）；OOD v4 0.9917（base 0.45）。

## 观测 9 — 2026-09-08（LOG-20260908-01）：**v6 口径第一份封存集；解析器容忍首过（invalid=0）；绝对门与 OOD 绝对门双 FAIL，另探针条件 DENY 侧塌方**

v6 数据集（`retail_ops_v6_20260907`：v5 结构 + rtc_stepwise 请求 reason 修复，配额与
v5 逐字节同构）下的第一份封存集：246 条，base/candidate 两侧同 commit（`49269b02` 系）
完整重跑。候选 = `sft-v6-001` 的合并部署形态（merged_revision `8f2c0591…`，provenance
sidecar 可复算）；解析器 = `hermes-single-call-v2-unterminated`（V6-2b，两侧同口径）。

| | base | candidate（merged） |
|---|---|---|
| task_success | 0.5691 | **0.9959**（245/246） |
| 政策违规 | 85 | **1**（`refund_denied_window`，variant-1 措辞，deadline 已过 7 天，查状态后仍执行） |
| 非法调用 | 2 | **0**（V6-2b 解析器容忍：`unterminated_call_count` 诊断计数同报告可查） |
| p95 latency | 2288 ms | 3290 ms（合并形态三比值全 PASS） |

**12 门逐门**：10 PASS——`success_delta` +0.4268、`success_delta_ci_lower` +0.3618、
`policy_violation_delta` −84、`invalid_call_count` 0（v5 唯一失败门被 V6-2b 修复，门级验证）、
三个延迟/步数比值全部 ≤1.25（per_call 1.003）、`evidence_complete` True、
`ood_success_delta_min` +0.0667、`success_delta_ci_lower_min` +0.3618；
**FAIL ×2：`policy_violation_count_max`（1 > 0，绝对门）与 `ood_task_success_min`
（0.6833 < 0.70）**。

### 判定：**NO-GO**（v1.3 口径，逐门判定；另预注册探针条件独立 FAIL——DENY 侧 7 点 0.00–0.107 < 0.875，按 v6 预注册三分支第二分支处置）

### 必须与这个 NO-GO 一起说的

1. **V6-2b 解析器容忍达到工程目标**：v5 的唯一失败门 `invalid_call_count=2` 归零
   （`unterminated_call_count` 诊断计数与报告同盘可查，不进门禁）。
2. **rtc_stepwise 修复在采集端完全生效**：teacher 分桶接受率 42/42 = 1.000（v5 为
   0.643），总体 579/588 = 98.5%（v5 96.3%）。
3. **新的失败类 = 措辞域依赖的「该拒绝却执行」**：同源词域面（dev 0.9949/pv1、封存
   0.9959/pv1）近乎满分，v1 风格枚举词域面（探针 DENY 侧 0.107、OOD v2 candidate
   0.6833/pv9）塌方——枚举词 deny 请求在 v5/v6 训练分布中都不存在，对该词域的拒绝
   泛化是训练运行的 basin 性质（R8 seed 方差 7 倍跨度的定性版）。v5 的 15/15 是
   basin 运气，不是被训练出的能力。**「同源评测面高估」第三次实证**（R7、R11 之后）。
4. **预注册的探针条件与 OOD 绝对门正是为这类失败而设**：二者独立于封存读数拦下候选，
   门禁未因「修的是格式类缺陷」而放宽。
5. 观测后结果不反馈进开发；候选保持 `sft-008`。措辞域覆盖（显式纳入枚举词 deny 请求
   并双词域判读）列为下一迭代的候选方向，待单独预注册。

## 观测 10 — 2026-09-08（LOG-20260908-02）：**v7 词域覆盖迭代；OOD 绝对门历史首过（0.8333 ≥ 0.70）；绝对门 pv=5 与探针远端 3 点双 FAIL**

v7 干预 = 只动 train_export：`retail_ops_v6_20260907` 任务集与封存集逐字节不动，
在训练分布中显式追加 426 行「v1 风格枚举词请求」行（deny 三场景 + allow 三场景，
模板族与探针同形、实例只来自 train split 任务；allow 210 / deny 216 配额预注册写死，
task_plan `bc1fb01`）。训练 `sft-v7-001`（522 步，loss 1.639→0.016）；候选 = 合并部署
形态（merged_revision `a121894a…`，provenance sidecar 可复算）；全部 9 个评测运行同
commit（`4e3b70d6` 系）；解析器两侧同口径 `hermes-single-call-v2-unterminated`。

| | base | candidate（merged） |
|---|---|---|
| task_success | 0.5691 | **0.9797**（241/246） |
| 政策违规 | 85 | **5**（4× `cancel_denied_recent` + 1× `refund_denied_window` variant-1） |
| 非法调用 | 2 | **0** |
| p95 latency | 2383 ms | 4259 ms（三比值全 PASS：per_call 1.046 / steps 0.958 / per_success 1.002） |

**12 门逐门**：11 PASS——`success_delta` +0.4106、`success_delta_ci_lower` +0.3496、
`policy_violation_delta` −80、`invalid_call_count` 0、三延迟/步数比值全 PASS、
`evidence_complete` True、**`ood_task_success_min` 0.8333（v6 的失败门，本轮历史首过）**、
`ood_success_delta_min` +0.2167、`success_delta_ci_lower_min` +0.3496；
**FAIL ×1：`policy_violation_count_max`（5 > 0，绝对门）**。

**预注册探针条件独立 FAIL（先于封存运行已知形状）**：ALLOW 侧 8 点全 1.00（防过校正
门内防线完好）；DENY 侧近边界被词域覆盖修复（−1/−2/−5 = 1.00、−3 = 0.875 恰好达标；
v6 同点 0.00–0.107），**远端仍塌**（−7 = 0.250、−10 = 0.500、−14 = 0.625）——三点
< 0.875。词域覆盖的泛化是**分级次的**：近边界修复 ≠ 远端修复。

### 判定：**NO-GO**（v1.3 口径，逐门判定；探针条件按 v7 预注册三分支第二分支处置）

### 必须与这个 NO-GO 一起说的

1. **干预在它的靶面上有效**：v6 的失败面（枚举词域 deny 塌方）被针对性数据覆盖
   大幅收窄——OOD v2 绝对门首过（0.6833 → 0.8333）、探针近边界从 0.00–0.107 修复
   到 ≥0.875、探针 pv 50 → 14。**「枚举词 deny 请求缺失」这一根因链被证实且被部分修复**。
2. **绝对门败在新的失败点 + 已知残留**：5 次违规中 4 次是 `cancel_denied_recent`
   （v6/观测 9 该场景为 0）——重训后 deny 边界在**另一个场景族**摆动（预注册风险 1
   预期的抽签成分，期望 0–2，实际 5 超出预期带，如实记录）；1 次是观测 9 同款
   `refund_denied_window` variant-1。封存面 task_success 0.9959 → 0.9797 同向回落。
3. **同源词域面无过校正**：dev 0.9949/pv1 与观测 9 逐位相同；ALLOW 侧探针 8 点全
   1.00——210/216 平衡配额的防线按设计工作。
4. 预注册纪律第五次实证：探针条件与绝对门独立拦下候选，11/12 不因「修好了 OOD 门」
   而放行；观测后结果不反馈进开发；候选保持 `sft-008`。
