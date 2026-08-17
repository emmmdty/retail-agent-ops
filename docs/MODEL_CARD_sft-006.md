# 模型卡：qwen3-4b-retailops-sft-006

本卡描述 RetailAgentOps R4 第三轮产出的候选 `sft-006`——**迄今在封存 holdout 上任务
指标最好的候选（120/120）**，以及它**仍未获准部署**的原因。它与 R3 的
[`MODEL_CARD.md`](./MODEL_CARD.md)（候选 `sft-001`）是两个不同的 artifact：不同的
LoRA 覆盖、不同的训练数据、不同的 system prompt、不同的失败门禁。

所有数字来自实际运行产物。发布判定与两侧读数的唯一事实源是
[`HOLDOUT_LEDGER.md`](./HOLDOUT_LEDGER.md)，本卡只做候选侧的解释，不复述台账。

> **产物可得性风险（必须先读）**：`reports/retail_ops/v1/r4/sft-006/`
> （adapter 权重、训练日志、metrics）**只存在于 gpu-5090**，本地 checkout 没有；
> 2026-08-15 合并产出的 `models/Qwen3-4B-sft-006-merged/`（7.6 GB）同样只在远端。
> 本卡引用的 7 个文件 SHA-256 来自 `formal-release-002/release.json` 内嵌的 adapter pin，
> 因此**指纹可验证、权重不可本地复算**。远端目录丢失即候选不可重建。

## 1. 身份与出处

| 项 | 值 |
|---|---|
| 候选标识 | `qwen3-4b-retailops-sft-006`（adapter） |
| 基座 | `Qwen/Qwen3-4B`，仓库提交 `8cd0101f70cac4f1efcebc979faf483558e39297`（与 `sft-001` 同一份基座） |
| 基座完整性 | 13 个文件逐一 SHA-256 锁定，训练与评测前由 `verify_local_model_files` 校验 |
| 训练产物 | `reports/retail_ops/v1/r4/sft-006/`（**仅在 gpu-5090**，见上方风险提示） |
| adapter 指纹 | `adapter_model.safetensors` = `8a49251fbfc9d1bab23041a97727c65f34d2dd1704c6453ec39e4ec95eefcd95`（7 个文件全部锁定） |
| 代码 commit | `ae82917e6ee43d0da8fe8418bba1b6b162a958fe`；依赖锁 `uv.lock` = `9227e307…` |
| `system_prompt_sha256` | `8ae813c4284246b9700470053ba90339a3f88439d9e57905d5db704ca63283dd`（**新 prompt**；`sft-001` 用的是 `d919602e…`） |
| `tool_schema_sha256` | `12b83460988bd3b61dccf0e1ca644dc45adfcf6c30a1db020a6aefdb78cccb85` |
| 硬件 | 单卡 NVIDIA RTX 5090（gpu-5090，物理 GPU 0，UUID `GPU-07af326b-…`） |
| 配置 | `configs/retail_ops/build/retail_ops_v1_r4_round3_capacity_prompt_sft.yaml` |

`policy_id`：
`qwen:Qwen/Qwen3-4B@8cd0101f…+adapter:reports/retail_ops/v1/r4/sft-006#8a49251fbfc9`。

## 2. 与 `sft-001` 的差异（这是本卡存在的理由）

| 维度 | `sft-001`（R3） | `sft-006`（R4 第三轮） |
|---|---|---|
| LoRA `target_modules` | `q,k,v,o`（attention-only，4 投影） | `q,k,v,o,gate,up,down`（**全 linear**，7 投影） |
| 训练数据 | `train-export-001`（240 行） | `train-export-004`（400 行，含 ×3 oversample） |
| 训练集 system 消息 | 旧 prompt | **新 prompt**（与评测时的常量一致） |
| holdout 任务成功率 | 0.7500（90/120） | **1.0000（120/120）** |
| 失败门禁 | `success_delta` −0.0333 | **`p95_latency_ratio` 1.8774** |
| adapter 体积 | 23,631,816 B（22 MiB） | **66,127,776 B（63 MiB）**——2026-08-16 在 gpu-5090 上实测；与同为全 linear 的 `sft-003` 及两次 R5 重建**逐字节同尺寸**。（此前本行写「本地无产物，不写具体数值」，是过度保守：产物一直在远端，量一下即可。） |

**这两条差异不能拆开评估。** R4 第三轮的跨规模验证（LOG-20260814-05）证明：
`train-export-004` 的 ×3 oversample 使"执行:拒绝" = 240:120 = 2:1，该偏向在 4B + 全 linear
下无害，在 **1.7B + 全 linear** 下致命（`refund_denied_ownership` 10/10 全灭）。
数据配比与 LoRA 容量是**一个二维选型**，不是两个独立旋钮。

## 3. 训练过程

| 项 | 值 |
|---|---|
| 数据版本 | `retail_ops_v1_r2_20260722`（seed 0） |
| 训练集 | `train-export-004`，400 行（240 行基础 + 两个多步家族 ×3 oversample），system 消息全部为新 prompt |
| 验证集 | 60 条 dev（Oracle 生成的 SFT 格式，弱 sanity 信号） |
| 方法 | QLoRA，4-bit NF4 量化基座，assistant-only loss |
| LoRA | r=16，alpha=32，dropout=0.05，target = 全部 7 个 linear 投影 |
| 优化 | 3 epoch，有效 batch 16（2×8），lr 2e-4，bf16，gradient checkpointing，`max_seq_len=1024` |
| 资源 | 293.7 s wall time（同卡另有约 81% 占用），CUDA 峰值 5.647 GB |
| 结果 | `train_loss = 0.1795` |

**`train_loss` 更低不构成候选更好的证据。** R4 第一轮的 `train_loss` 同样从 0.3722 降到
0.2198，而目标行为一点没改善。本项目"主判据是最终状态与政策 verifier"的立场是实测结论
而非教条，见 §6。

## 4. 评测结果

确定性解码（`do_sample=false`、`enable_thinking=false`、`max_new_tokens=256`、nf4）。

### 4.1 开发集（60 条 dev，配对 `qwen3-4b-dev-base-002`，两侧同 prompt）

| 指标 | base-002（新 prompt，零训练） | **sft-006** |
|---|---|---|
| task_success | 54/60 | **60/60** |
| `success_delta` | — | **+0.100** |
| `policy_violation` | 5 | **0** |
| `recovery_success` | 0.5 | **1.0** |

这次配对**关掉了第二轮遗留的方法论缺口**：候选 A 当时的 +0.200 是对照旧 prompt 的
base 取得的，delta 里混着"没给 base 换 prompt"的免费收益。同 prompt 配对下训练仍有
**+0.100**，这才是训练的独立增量。

**dev 已被用于候选选择，带选择偏差**；60/60 是满分的退化区间，不构成能力上界的证据。

### 4.2 封存 holdout（观测 2）

逐项读数见 [`HOLDOUT_LEDGER.md`](./HOLDOUT_LEDGER.md#观测-2--2026-08-14log-20260814-04)。
候选侧要点：**120/120（六类各 20/20）**、`policy_violation_count` 0、
`invalid_call_count` 0、`schema_valid_rate` 1.0000、`failure_type_counts` **空**。

**判定仍是 `NO-GO` / `deployment=baseline`**，唯一失败门禁 `p95_latency_ratio`
1.8774 > 1.25。

## 5. 失败模式（本卡最重要的部分）

`sft-006` 在 holdout 上**没有任务失败**。它唯一的失败是**部署形态的延迟**：

| 量 | base | sft-006 | 比值 |
|---|---|---|---|
| `average_tool_calls` | 1.3083 | 1.5000 | 1.146 |
| `average_turns` | 2.0417 | 2.1667 | 1.061 |
| `average_latency_ms` | 1958.26 | 4457.06 | 2.276 |
| **单次调用耗时** | **1496.8 ms** | **2971.4 ms** | **1.985** |
| `output_tokens_per_second` | 47.02 | 29.53 | 0.628 |

剔除调用次数之后，单次调用仍慢近一倍。因此代价来自**全 linear LoRA 的前向开销**
（7 个投影层每次都要多做低秩矩阵乘），**不是**"候选多做了工具调用"。旁证：观测 1 的
attention-only adapter（4 投影）p95 比值仅 1.087。

**这个数字大部分是可以工程消除的，而 2026-08-15 之前的部署实现没有做那件事**：
`core/agent/qwen.py` 的 `TransformersBackend` 是 bnb 4-bit 基座 + `PeftModel`
**未 merge** + HF `generate` 逐 episode 串行，全仓没有 `merge_and_unload`、
没有 vLLM/SGLang、没有 `torch.compile`。

**对照实验已完成（dev 60 条，不是发布判定）**，详见
[`SERVING_FORM_COMPARISON.md`](./SERVING_FORM_COMPARISON.md)：把本 adapter 在 bf16 下
合并回基座、再按同一份生成参数量化回 NF4，

| | 未合并 | 合并版 |
|---|---|---|
| dev `task_success` | 60/60 | **60/60**（能力未损伤） |
| `average_tool_calls` | 1.5000 | **1.5000**（行为一致） |
| 单次调用耗时 | 3063.9 ms | **1653.7 ms（−46%）** |
| 输出吞吐 | 28.38 tok/s | **50.74 tok/s**（略高于基座 48.89） |

**2026-08-15 的第三次封存 holdout 观测把这一条从 dev 推进到了 holdout**
（逐项读数见 [`HOLDOUT_LEDGER.md`](./HOLDOUT_LEDGER.md) 观测 3）：合并版在 120 条
holdout 上同样 **120/120**、零违规、零非法调用、`average_tool_calls` 与未合并版
完全相同（1.5000），单次调用 2946.5 → **1717.7 ms**，p95 比值 2.0250 → **1.2141**。

## 5.1 发布判定：**合并形态在第四次观测拿到 GO**

2026-08-15 扩展 sealed 契约（v1.1，支持 merged 形态）之后，第四次观测给出了本项目
历史上**第一个 GO**：`deployment=candidate`、`form=merged`，v1.0 与 v1.1 两套口径都是。

| 门禁 | v1.0 | v1.1 |
|---|---|---|
| `success_delta` | PASS +0.1417 | PASS +0.1417 |
| `success_delta_ci_lower` | — | PASS +0.0833 |
| `policy_violation_delta` | PASS −11 | PASS −11 |
| `invalid_call_count` | PASS 0 | PASS 0 |
| `p95_latency_ratio` | **PASS 1.1265** | 已拆分 |
| `per_call_latency_ratio` | — | **PASS 1.1646** |
| `steps_to_success_ratio` | — | PASS 0.9841 |
| `latency_per_success_ratio` | — | **PASS 1.1461** |

**GO 归因于部署形态**：把**未合并**候选对同一份 base-004 重算，`p95_latency_ratio`
仍是 **1.9219 FAIL**。同一份权重、同一套行为，只差加载方式。

**必须与这个 GO 一起说的四条**：

1. **这不是前三次被拒的那个形态。** 未合并形态的历次判定**全部 NO-GO**，结论一个字不改。
2. **SPEC §6 的第 6 条已于 2026-08-16 满足**：独立重建复验在 dev 上做了两次
   （同 seed 与异 seed 各一次），两次都高于零训练基座（58/60、60/60 对 54/60；
   n=3 给不出置信区间，**不写"显著"**），政策违规都是 0
   （`docs/REBUILD_VERIFICATION.md`）。**但仍不等于"可以上线"**——复验证明的是
   这个流程能稳定重现这个结果，不是这个结果能泛化；同一候选在分布外集合上只有 0.5833。
3. **"60/60"不是常数**：同 seed 重跑产出逐位不同的权重，三次同配置运行是 60 / 58 / 60，
   波动全部落在 `refund_recovery`。**训练是本项目唯一不能逐位复现的环节。**
4. **余量约 10%**，而 base 侧 p95 在历次观测间为 5255 → 3052 → 2787 → 2937 → 3112 → 2935 ms——
   共享 GPU 的波动是真实的（次数以 [`HOLDOUT_LEDGER.md`](./HOLDOUT_LEDGER.md) 为准）。

判定前配对规则被改过一次、且我是在看到两侧指标之后改的——完整披露见 LOG-20260815-04。
逐项读数见 [`HOLDOUT_LEDGER.md`](./HOLDOUT_LEDGER.md) 观测 4。

**120/120 已被证明不是泛化证据。** 2026-08-16 的分布外评测（60 条独立 dataset
artifact）给出：本候选 **0.5833（35/60）**，其中

| 类别 | base（零训练） | 本候选 |
|---|---|---|
| `scenario_ood`（做不到的请求 + 多实体） | 0.00 | **0.75** |
| `adversarial`（错订单号 / 脏字段 / 工具诱导） | 0.35 | **1.00** |
| `expression_ood`（口语 / 错别字 / 中英夹杂 / 极简） | 0.30 | **0.00** |

**表达类归零，且比零训练基座更差**（`code_switch` 1.00 → 0.00）。20 条失败全部是
`premature_final_response`——换一种说法本候选就退回 R3 的老失败模式。

正确的描述是：**这次 SFT 用表面形式的鲁棒性换来了任务结构与安全性。**
在冻结 holdout 上只看得见换来的那一半，因为那 120 条与训练集共用同一批 12 句模板。
详见 [`OOD_EVALUATION.md`](./OOD_EVALUATION.md)。**引用本卡的 GO 时必须同时给出这个数。**

## 6. 已知限度（引用本卡时必须一并引用）

1. **120/120 不是泛化证据。** train/dev/holdout 共用同一批 12 句请求模板
   （`domain/formal_tasks.py:_user_request`），holdout 落在 train 的模板空间内。
   五维指纹保证"没有逐字重复"，不保证"没有分布重叠"。
2. **未获准部署。** 服务入口对此有代码级强制：NO-GO 时 adapter 根本不传给后端工厂，
   且随后核对工厂返回的后端确实没挂 adapter。
3. **结论带规模条件。** 全 linear 在 4B 上是最优解，在 **1.7B 上方向相反**
   （45/60，拒绝类崩塌）。"容量决定训练效果的符号"这个一般化表述已被本项目自己的
   跨规模实验证伪，正确表述是"**LoRA 容量必须与模型规模匹配**"。
4. **prompt 与训练的分工结论只在 4B 成立**：新 prompt 使 4B 的 `refund_eligible`
   5/10→9/10，对 1.7B 完全无效（0/10）。
5. **`verifier_reward` 不可作为判据**：它在本项目已**三次**与主判据反向
   （R3 dev、封存 holdout、R4 dev）。本轮起它在报告中被降级为诊断量。
6. **训练不可逐位复现**。独立重建复验已完成（`docs/REBUILD_VERIFICATION.md`），
   dev 读数应表述为 **58–60/60，三次同配置运行**，不是单点 60/60。
7. **产物只在远端**（见开头风险提示）。
