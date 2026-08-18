# 门禁 schema v1.1 对已有观测的复算

**这不是新的观测。** 输入是**已经落盘**的封存 holdout 证据（观测 2 与观测 3），没有跑模型、
没有消耗任何观测。产出是"同一批证据在新口径下长什么样"的对照。

**旧口径的两次 NO-GO 结论保留不改写**，见 [`HOLDOUT_LEDGER.md`](./HOLDOUT_LEDGER.md)。
新旧结论在本文件里**并列**陈述。

## 诚信前提（可核对）

1. v1.1 的门禁定义、阈值来源与三个比值的计算方式，在 commit `3427c40` 里定稿并提交；
   本文件的全部数字是**在那次提交之后**算出来的。顺序颠倒就是"照着结果改门禁"。
2. 提交前已把预判写进 `findings.md` 第 (j) 条：*拆分后第二次观测仍应是 NO-GO，
   因为 `per_call_latency_ratio` = 1.985 > 1.25*。复算证实了这一条。
3. **阈值一个字没改**：三个比值门禁复用 `release.yaml` 的 `p95_latency_ratio_max`
   = 1.25，CI 下界的 0 是结构性常量。`release.yaml` 逐字节未动。
4. **没有任何候选从 NO-GO 变成 GO。** 观测 1 在新口径下失败门禁反而**多了两项**。

## 复算命令

```bash
.venv/bin/retail-agent-ops release \
  --config configs/retail_ops/release/retail_ops_v1_r45_formal_release_v11.yaml --seed 0 \
  --baseline_dir  reports/retail_ops/v1/r4/holdout-base-002 \
  --candidate_dir reports/retail_ops/v1/r4/holdout-candidate-002 \
  --baseline_trajectories  <私有>/qwen3-4b-holdout-base-002/trajectories.jsonl \
  --candidate_trajectories <私有>/qwen3-4b-holdout-candidate-002/trajectories.jsonl \
  --output_dir reports/retail_ops/v1/r45/formal-release-002-v11-paired
```

逐任务配对结局只能来自私有 `trajectories.jsonl`（公开 sealed 报告是聚合量）。
观测 2 的私有产物于 2026-08-15 从 gpu-5090 回传，双端 SHA-256 一致
（base `7724c02a9626b3b2…`、candidate `2082a289439fad33…`）。

## 观测 1（2026-08-11，候选 `sft-001`，attention-only LoRA）

| 门禁 | v1.0 | v1.1 |
|---|---|---|
| `success_delta` | **FAIL** −0.0333 | **FAIL** −0.0333 |
| `success_delta_ci_lower` | — | **FAIL** −0.0917 |
| `policy_violation_delta` | PASS −16 | PASS −16 |
| `invalid_call_count` | PASS 0 | PASS 0 |
| `p95_latency_ratio` | **PASS 1.0870** | 已拆分 |
| `per_call_latency_ratio` | — | **FAIL 1.9643** |
| `steps_to_success_ratio` | — | PASS 1.0089 |
| `latency_per_success_ratio` | — | **FAIL 1.9818** |
| `evidence_complete` | PASS | PASS |
| **判定** | **NO-GO / baseline** | **NO-GO / baseline** |

### 这次复算最重要的发现

**旧口径把观测 1 的部署代价整个藏了起来。** episode 级 `p95_latency_ratio` 是
**1.0870（通过）**，而单次调用耗时比值是 **1.9643（失败）**——差了近一倍。

原因就是 P1-4 指出的那个偏置，现在有了自家数据的实证：观测 1 的候选**更差**
（0.7833→0.7500），失败形态 100% 是 `premature_final_response`，即"说完就停"。
它因此**调用得更少**（`average_tool_calls` 1.225→1.183）、**episode 结束得更早**，
于是 episode 级延迟看起来几乎没涨。**做得更差反而显得更快**，门禁就放行了。

拆分之后，两次观测的候选都暴露出 **1.96–1.99× 的单次前向开销**——这是一个此前
从未被任何门禁捕捉到的、稳定存在于两个不同 adapter 上的部署成本。

## 观测 2（2026-08-14，候选 `sft-006`，全 linear LoRA）

| 门禁 | v1.0 | v1.1 |
|---|---|---|
| `success_delta` | PASS +0.1417 | PASS +0.1417 |
| `success_delta_ci_lower` | — | **PASS +0.0833** |
| `policy_violation_delta` | PASS −11 | PASS −11 |
| `invalid_call_count` | PASS 0 | PASS 0 |
| `p95_latency_ratio` | **FAIL 1.8774** | 已拆分 |
| `per_call_latency_ratio` | — | **FAIL 1.9852** |
| `steps_to_success_ratio` | — | **PASS 0.9841** |
| `latency_per_success_ratio` | — | **FAIL 1.9536** |
| `evidence_complete` | PASS | PASS |
| **判定** | **NO-GO / baseline** | **NO-GO / baseline** |

### 新口径下这个候选的结论变得更清晰，而不是更宽松

1. **能力主张被加强了。** `success_delta` 从裸点估计升级为配对 bootstrap 检验后
   仍然通过：CI95 下界 **+0.0833 > 0**。此前 `MODEL_CARD.md` §6 只能说"两侧 CI 大幅
   重叠"（那是**独立**区间），配对检验消掉了任务难度本身的方差，把"确实有提升"变成
   了可陈述的结论。
2. **失败被精确隔离到部署形态。** `steps_to_success_ratio` = **0.9841 < 1**：
   每成功一条任务所需的工具调用**比基座还少**。候选不是"靠多做几步换成功率"，
   它的规划效率是净改善的。两项失败门禁（1.9852 / 1.9536）几乎完全由单次前向开销
   构成。
3. **因此 P0-3 是唯一有意义的下一步**：`core/agent/qwen.py` 的部署形态是
   bnb 4-bit 基座 + `PeftModel` **未 merge** + HF `generate` 逐 episode 串行；
   全仓没有 `merge_and_unload`、没有 vLLM、没有 `torch.compile`。把 adapter 合并
   回基座权重不改变模型要做的事，只去掉低秩旁路的前向开销。

**在 merge 后的对照实验完成之前，本文件不声称"merge 就能过门禁"。**
合并后重新量化到 NF4 与"基座 NF4 + LoRA"在数值上并不等价，因此合并版的任务指标
必须重测，不能假设。

## 口径变更的净效果

| | 旧口径 v1.0 | 新口径 v1.1 |
|---|---|---|
| 观测 1 失败门禁数 | 1 | **3** |
| 观测 2 失败门禁数 | 1 | 2 |
| 判定翻转 | — | **无** |
| 新增能力信息 | — | 观测 2 的提升通过配对显著性检验 |
| 新增诊断信息 | — | 两次观测的候选都有 ~1.96–1.99× 单次前向开销；观测 1 的这项代价在旧口径下被完全掩盖 |

新口径**更严**而不是更松。它的价值不在于让哪个候选过关，而在于把"更慢"这一个数
拆成"部署慢"和"多做了工作"两件事——结果发现两次观测里**都不是**"多做了工作"。
