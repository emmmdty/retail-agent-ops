# 部署形态对照：未合并 LoRA vs 合并回基座权重

**这不是发布判定。** 全部读数来自 **60 条 dev**，不是封存 holdout。dev 已被用于候选
选择，带选择偏差。真正的发布判定需要**第三次**封存 holdout 观测（base + candidate
两侧完整重跑），那是用户单独决策门，**本轮没有做**。

## 由来（评审 P0-3）

`core/agent/qwen.py` 的部署形态是 bnb 4-bit 基座 + `PeftModel` **未 merge** +
HF `generate` 逐 episode 串行；全仓无 `merge_and_unload`、无 vLLM/SGLang、无
`torch.compile`。未合并的 LoRA 每层多两次低秩矩阵乘并走一遍 4bit 反量化路径，
是**纯实现开销，与模型能力无关**。

`docs/GATE_SCHEMA_V11_RECOMPUTE.md` 已把两次观测的失败精确隔离到这一项：
`steps_to_success_ratio` 0.9841 < 1（候选每成功一条任务的调用数比基座**更少**），
而 `per_call_latency_ratio` 1.9852。**归因之后，那个显而易见的动作一直没有人做。**

## 做了什么

`scripts/ops/merge_lora_adapter.py`：在 **bf16** 下 `merge_and_unload`（不在 4-bit
权重上合并——那会把量化误差固化进合并结果），产出独立模型目录 + sidecar provenance。
派生标识 `merged_revision = 00f51386…` 由「基座 revision + adapter 逐文件哈希」
确定性导出，`repo` 写作 `local/…`，**不冒充上游 pin**。

评测走 `formal_dev_base`（合并后模型里已经没有 adapter，用 candidate 通道会要求一个
不存在的 adapter pin），生成参数与两侧完全相同（`max_new_tokens=256`、
`do_sample=false`、`enable_thinking=false`、NF4）。

**最大的风险是合并 + 重新量化会损伤模型**：「基座 NF4 + LoRA」与「合并后再 NF4」
不是同一组权重。这个风险**没有兑现**（在 dev 上）。

## 三档对照（dev 60 条，gpu-5090 物理 GPU 0）

| | base-002（零训练） | 未合并 sft-006 | **合并版 sft-006** |
|---|---|---|---|
| `task_success` | 0.9000（54/60） | **1.0000（60/60）** | **1.0000（60/60）** |
| `policy_violation_count` | 5 | 0 | 0 |
| `invalid_call_count` | 0 | 0 | 0 |
| `average_tool_calls` | 1.3167 | 1.5000 | **1.5000** |
| `average_output_tokens` | 87.42 | 130.52 | 125.97 |
| `average_latency_ms` | 1786.17 | 4595.79 | **2480.48** |
| `p50 / p95 latency_ms` | 1745.76 / 2564.00 | 4891.15 / 5897.56 | **2420.03 / 3366.44** |
| **单次调用耗时** | **1356.6 ms** | **3063.9 ms** | **1653.7 ms** |
| 输出吞吐 tok/s | 48.89 | 28.38 | **50.74** |
| 峰值显存 | — | — | 2.91 GB |
| wall time（60 条） | — | — | 148.96 s |

**行为完全一致**：合并前后 `average_tool_calls` 都是 1.5000、`task_success` 都是
60/60、违规与非法调用都是 0。合并改变的只有前向路径，不是模型要做的事。

**吞吐甚至略高于基座**（50.74 vs 48.89 tok/s）。这不奇怪：合并版是单份 bf16 权重
重新量化的结果，前向路径比基座 NF4 + 7 个 LoRA 旁路更短。

## 同一批读数在两套门禁下的结论

对照基座 `base-002`，**dev**、非发布判定：

| 门禁 | 未合并 | 合并版 |
|---|---|---|
| `success_delta` | PASS +0.1000 | PASS +0.1000 |
| `success_delta_ci_lower` | PASS +0.0333 | PASS +0.0333 |
| `policy_violation_delta` | PASS −5 | PASS −5 |
| `invalid_call_count` | PASS 0 | PASS 0 |
| `per_call_latency_ratio` | **FAIL 2.2585** | **PASS 1.2190** |
| `steps_to_success_ratio` | PASS 1.0253 | PASS 1.0253 |
| `latency_per_success_ratio` | **FAIL 2.3157** | **PASS 1.2498** |
| `evidence_complete` | PASS | PASS |
| **v1.1 合计** | 6/8 | **8/8** |
| **v1.0 `p95_latency_ratio`** | **FAIL 2.3001** | **FAIL 1.3130** |

## 必须与结果一起说的四条

1. **旧口径下合并版仍然不过。** v1.0 的 `p95_latency_ratio` 是 **1.3130 > 1.25**。
   dev 上这个"全过"是**合并 + 口径拆分两件事共同作用**的结果，不是单靠合并。
   按提示词 §6 的诚信约束，这一点必须显式指出，不能只说"合并之后全过了"。
2. **`latency_per_success_ratio` = 1.2498 对阈值 1.25，只差 0.0002。** 这不是稳健通过，
   是**擦边**。任何测量噪声、任何任务分布变化都可能把它推到另一侧。不得据此宣称
   "延迟问题已解决"。
3. **dev ≠ holdout，且量级差异很大。** 未合并候选的延迟比值在 dev 上是 2.30、在 holdout
   上是 1.88；同一个 adapter、同一套代码，只因任务分布不同就差了 0.4。**不得**用 dev 的
   1.2190 推断 holdout 上会是多少。
4. **dev 带选择偏差。** `sft-006` 正是在 dev 上被选出来的，60/60 是它的选择依据本身。

## 这条结论改变了什么

在此之前，项目对第二次 NO-GO 的表述是"效果/延迟权衡：容量换来 +14.2pp 与满分，
代价是 p95 接近翻倍"。现在这个表述**不完整**：那个代价里有很大一部分**不是模型的**，
是部署实现的。同一份权重、同一套行为，换一种加载方式，单次调用耗时从 3063.9 ms
降到 1653.7 ms（**−46%**），吞吐从 28.38 回到 50.74 tok/s。

这不等于候选可以上线——发布判定只能来自封存 holdout，而那需要第三次观测。
它等于：**在讨论"这个模型是不是太慢"之前，先要确认测的是模型还是部署形态。**

## 未做的部分（提示词 §7.2 的四档只做了三档）

**merged + vLLM（prefix caching）没有做**：需要引入新依赖，属独立确认门。
`torch.compile` 同理未做。因此"单卡部署"这个卖点目前兑现到"合并后重新量化"这一档，
再往上的吞吐还没有数据。
