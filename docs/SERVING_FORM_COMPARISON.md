# 部署形态对照：未合并 LoRA vs 合并回基座权重

**这不是发布判定，无论 dev 还是 holdout 侧。** 合并版没有 adapter、且是不同的
`ModelArtifact`，`require_comparable_sealed_runs` 会（正确地）拒绝把它当作 candidate
——封存判定的契约要求 candidate = 同一基座 + adapter。**第三次的正式判定跑的是
未合并候选，两套口径都是 NO-GO**（见 [`HOLDOUT_LEDGER.md`](./HOLDOUT_LEDGER.md) 观测 3）。

本文件先给 dev 侧的对照（§"三档对照"，dev 已被用于候选选择、带选择偏差），
再给 2026-08-15 第三次观测里的 holdout 侧对照（文末）。

## 由来（评审 P0-3）

`core/agent/qwen.py` 的部署形态是 bnb 4-bit 基座 + `PeftModel` **未 merge** +
HF `generate` 逐 episode 串行；全仓无 `merge_and_unload`、无 vLLM/SGLang、无
`torch.compile`。未合并的 LoRA 每层多两次低秩矩阵乘并走一遍 4bit 反量化路径，
是**纯实现开销，与模型能力无关**。

`docs/GATE_SCHEMA_V11_RECOMPUTE.md` 已把前两次观测的失败精确隔离到这一项：
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

这不等于候选可以上线：正式判定仍是 NO-GO，而且合并形态在当前契约下**根本无法**
获得判定。它等于：**在讨论"这个模型是不是太慢"之前，先要确认测的是模型还是部署形态。**

## 封存 holdout 上的同一对照（2026-08-15，观测 3）

dev 的结论在 holdout 上**复现了，且更接近门槛**。三档同 commit（`b529bc9`）、
同一天连续跑完：

| | base(4bit) | adapter 未合并 | **合并后重新量化** |
|---|---|---|---|
| `task_success` | 0.8583（103/120） | **1.0000** | **1.0000** |
| `policy_violation_count` | 11 | 0 | 0 |
| `average_tool_calls` | 1.3083 | 1.5000 | **1.5000** |
| 单次调用耗时 | 1389.3 ms | 2946.5 ms | **1717.7 ms** |
| `p95_latency_ms` | 2787.4 | 5644.4 | **3384.0** |
| 输出吞吐 | 50.66 tok/s | 29.78 | **48.87** |
| **p95 比值** | — | **2.0250** | **1.2141** |
| **单次调用比值** | — | **2.1209** | **1.2364** |

**合并版在 holdout 上同样是 120/120、零违规、零非法调用、调用次数一模一样。**
合并 + 重新量化没有损伤模型，这一点在 dev 与 holdout 上都成立。

把候选侧换成合并版后，v1.0 与 v1.1 的门禁算术**全部通过**（`p95_latency_ratio`
1.2141、`per_call_latency_ratio` 1.2364、`latency_per_success_ratio` 1.2167）。

**但这不是发布判定，也不能是。** 合并版没有 adapter、且是不同的 `ModelArtifact`，
`require_comparable_sealed_runs` 会（正确地）拒绝把它当作 candidate——该契约要求
candidate = 同一基座 + adapter。第三次的**正式判定**是未合并候选，两套口径都是
**NO-GO**。逐项读数见 [`HOLDOUT_LEDGER.md`](./HOLDOUT_LEDGER.md)。

**余量必须一起说**：1.2141 与 1.2364 对阈值 1.25，只剩 3% 和 1%；而 base 侧 p95 在
观测 2 是 3052.2 ms、观测 3 是 2787.4 ms——同机同配置 **9% 的波动**。
**一次重跑就可能把它推到另一侧。** 这不是"延迟问题已解决"，是"延迟的主因已定位并
已被消掉大部分，余量仍薄"。

## 第四档：merged + vLLM（2026-08-16，LOG-20260816-02）

**这是旁证，不是评测证据。** vLLM 装在独立 venv 里，项目 `uv.lock` 一个字节没动
——`uv_lock_sha256` 在 `SEALED_PAIRING_FIELDS` 内，装进项目环境会让**全部**已有
sealed 证据不可配对。它不产出 run evidence，也不进任何发布判定。

### 先证明测的还是同一个模型

只报吞吐是不够的：vLLM 用自己的 kernel，且这一档跑 bf16 而项目 HF 路径跑 NF4，
两处都可能改变输出。若两侧行为不同，那份吞吐数字衡量的是**另一个模型**。

`scripts/ops/compare_engine_outputs.py` 在同一批提示词上把两侧逐条比对：

| | 结果 |
|---|---|
| 解析后工具调用（名字 + 参数）一致 | **12/12** |
| 归一化特殊标记后文本逐字相同 | **12/12** |
| 三侧各自的输出 token 总数 | **390 / 390 / 390** |

三侧吐出**完全相同的 390 个 token**。这是"它们在做同一件事"最直接的确认，
也让下面的时间数字可以直接相除。

### 三档拆解：3.32× 里，引擎与量化各占多少

同一批 **12 条公开 R1 qualification fixture**（提示词 420–435 token，mean 427.9）、
同一份合并权重、同一套贪心契约（`temperature=0`、`max_new_tokens=256`）、
gpu-5090 物理 GPU 0：

| | **HF + NF4**（当前服务栈） | HF + bf16 | **vLLM + bf16** |
|---|---|---|---|
| 单流 mean 延迟 | 675.97 ms | 411.66 ms | **203.51 ms** |
| 单流 p50 | 633.70 ms | 370.64 ms | **199.99 ms** |
| 单流 p95 | 1078.70 ms | 817.23 ms | **220.39 ms** |
| 输出吞吐 | 48.08 tok/s | 78.95 tok/s | **159.70 tok/s** |
| p95 / p50 | 1.70 | 2.21 | **1.10** |
| 权重显存 | ≈2.9 GB | ≈8 GB | ≈8 GB |

**乘性分解（1.64 × 2.02 = 3.32）**：

- **去掉 NF4** ：48.08 → 78.95 tok/s，**1.64×**。**不需要新依赖、不需要新引擎，
  栈保持冻结。** 5090 有 32 GB，4B 模型 bf16 才 8 GB——NF4 从来不是容量需要。
- **再换 vLLM**：78.95 → 159.70 tok/s，**再 2.02×**。这一半才是引擎的功劳。

**把 3.32× 整个记在 vLLM 头上是错的。一半来自不再做 4bit 反量化。**

另一条值得注意：**vLLM 的尾延迟稳定得多**（p95/p50 = 1.10 vs 1.70 / 2.21）。
发布门禁测的正是 p95，对一个 p95 门禁而言这个差别可能比均值更重要。
但 n = 12，不要用它分辨小幅差异。

### 批量吞吐与 prefix caching

| | prefix caching 开 | 关 |
|---|---|---|
| 单流吞吐 | 159.70 tok/s | 151.56 tok/s |
| **批量冷启**（12 并发，另一组没跑过的提示词） | **1375.38 tok/s** | 873.11 tok/s |
| 批量第二遍（同一组） | 1439.93 tok/s | 861.16 tok/s |

- **prefix caching 值 +57.5%**（873.11 → 1375.38）。这个收益在本应用里格外真实：
  每个请求都共享同一段约 400 token 的系统提示与工具 schema。
- 关掉之后第二遍与第一遍持平（873.11 → 861.16），**这是对照组**，说明开启时
  那个提升确实来自缓存而不是别的。
- 批量 1375.38 tok/s 是单流 HF+NF4 的 **28.6×**——但**当前的服务契约拿不到它**：
  服务刻意串行、并发上限为 1（`docs/SYSTEM_CARD.md` §4.2），因为并发会让延迟测量
  失真而延迟是门禁项。**这一档衡量的是放弃了什么，不是已经得到了什么。**
- `gpu_memory_utilization=0.35`（约 11 GB，共享卡上的克制值）限制了 KV cache，
  批量数字是**下界**不是上界。

### 这一档**不**声称什么

1. ~~**它没有跑过任何评测任务。**~~ **这条已于 2026-08-16 被补上，且当时的理由是错的**
   ——见 [`ENGINE_SUBSTITUTION.md`](./ENGINE_SUBSTITUTION.md)。我曾以为"跑完整
   evaluate 路径必须把 vLLM 引入项目依赖"，但 `uv_lock_sha256` 哈希的是仓库里的
   `uv.lock` 文件而不是实际装了什么包，换 venv 跑它根本发现不了。真正的拦截是
   `GenerationSettings.quantization: Literal["nf4"]`，让 vLLM 也跑 NF4 即可绕开
   而无需改任何契约。**结论也随之更细**：dev 与 OOD 上合并候选逐项一致，
   但**零训练基座不一致**（13/60 → 14/60）——引擎替换不是普遍保行为的。
2. **"去掉 NF4 就能过延迟门禁"是假设，不是结论。** 门禁是**比值**，base 侧也是 NF4；
   要验证必须跑一次配对的 base/candidate。而按 `SEALED_PAIRING_FIELDS` 的约束，
   那会是封存 holdout 的**第五次**观测，需用户单独决策。本文件不据此推断门禁结果。
3. **`torch.compile` 仍未做。**
4. n = 12，且是 qualification fixture 不是评测任务。

### 复现（gpu-5090）

`/mnt/aidata/tongjiakai/run_vllm_bench.sh`。两处环境约束是硬的：

- **vLLM 需要 Python ≥ 3.12**（3.11 下 `flashinfer` 在模块级用 `array.array[int]`，
  而 `array.array` 从 3.12 起才可下标）。项目自身仍是 3.11——正因为它在独立 venv 里。
- **`VLLM_USE_FLASHINFER_SAMPLER=0`**：flashinfer 的采样核要运行时 JIT 编译需要 `nvcc`，
  本机只有驱动没有 CUDA toolkit。贪心解码本来就不需要它。
- **两个 venv 的 `TRITON_CACHE_DIR` 必须分开**，理由见
  [`findings.md`](../findings.md)「triton 缓存跨 venv 污染」——违反这一条会**打挂项目
  自己的 HF 评测路径**，2026-08-16 已经发生过一次。
