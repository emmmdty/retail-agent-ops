# 模型卡：qwen3-4b-retailops-sft-001

本卡描述 RetailAgentOps R3 产出的**唯一正式候选**，以及它**未获准部署**的原因。
所有数字来自实际运行产物，可经 `report_id` 自哈希与逐产物 SHA-256 复算追溯；
没有原始产物支撑的数字不写入本卡（`docs/CAREER_CONTEXT.md` 证据纪律）。

## 1. 身份与出处

| 项 | 值 |
|---|---|
| 候选标识 | `qwen3-4b-retailops-sft-001`（adapter，23.6 MB） |
| 基座 | `Qwen/Qwen3-4B`，ModelScope 仓库提交 `8cd0101f70cac4f1efcebc979faf483558e39297` |
| 基座完整性 | 13 个文件逐一 SHA-256 锁定，训练与评测前均由 `verify_local_model_files` 校验，清单外文件/子目录/symlink 一律拒绝 |
| 训练产物 | `reports/retail_ops/v1/r3/sft-001/`（config、log、metrics、trainer_log_history、adapter） |
| adapter 指纹 | `adapter_model.safetensors` = `34544fac3ec9afae10f9212f730aaf275bc86b536ffaeecfb4fe0eeb745e8748`（7 个文件全部锁定） |
| 代码 commit | 评测证据内嵌 `90c90382e70cc2a16f99719eae9f7efe9efece9a`；依赖锁 `uv.lock` = `9227e307…` |
| 硬件 | 单卡 NVIDIA RTX 5090（gpu-5090，物理 GPU 0，UUID `GPU-07af326b-…`） |

`policy_id` 在证据中完整表达组合身份：
`qwen:Qwen/Qwen3-4B@8cd0101f…+adapter:reports/retail_ops/v1/r3/sft-001#34544fac3ec9`。
基座侧证据的 `policy_id` 没有 adapter 后缀，两者在字段级不可混淆。

## 2. 预期用途

**适用**：中文零售客服工具 Agent 的**退款闭环**——订单查询、退款允许、退款拒绝
（超窗/非本人/重复退款三种）、瞬时故障后的重试恢复。工具面固定为
`get_order`、`refund_order`、`get_store_hours`（第三个是 schema 干扰项）。

**不适用**：本领域之外的任何任务；多轮自由对话；未在 bundle 中声明的工具；
需要 3 次以上工具调用的长链路（见 §5 失败模式）。本候选**未通过发布门禁**，
因此不得作为生产默认模型加载——服务入口对此有代码级强制（见系统卡 §4）。

## 3. 训练数据与过程

| 项 | 值 |
|---|---|
| 数据版本 | `retail_ops_v1_r2_20260722`（seed 0，生成器 `family_sha256_v1`） |
| 训练集 | 240 条 train（六类各 40），来自 DeepSeek `deepseek-v4-flash` teacher 采集，全部经 replay + 最终状态 + 政策 verifier 校验；不合格由 internal reference 补齐 |
| teacher 质量门 | 全量采集 238/240 通过（99.2%），整体 ≥70%、每类别 ≥50% 的门槛均满足 |
| 验证集 | 60 条 dev（Oracle 生成的 SFT 格式，仅作弱 sanity 信号，与 train 分布不同） |
| 序列预算 | `max_seq_len=1024`；用**训练框架实际使用的** TRL chat template 审计，train max=730 / dev max=727 token，0/300 超限，无静默截断 |
| 方法 | QLoRA，4-bit NF4 量化基座，assistant-only loss |
| LoRA | r=16，alpha=32，dropout=0.05，target=`q_proj,k_proj,v_proj,o_proj` |
| 优化 | 3 epoch / 45 steps，有效 batch 16（2×8），lr 2e-4，bf16，gradient checkpointing |
| 资源 | 134.3 s wall time，CUDA 峰值分配 5.16 GiB |
| 结果 | `train_loss=0.3722`；`eval_loss` 三 epoch 为 0.5266 / 0.5603 / 0.5797；`eval_mean_token_accuracy` 0.9321 / 0.9472 / 0.9436 |

**`eval_loss` 轻微上升不是过拟合信号**：dev 侧 SFT 文件的最终回复是 Oracle 常量串，
与 teacher 风格的 train 分布不同，两者 loss 不可直接比较。这一口径限制在训练前就已记录，
候选质量的权威依据是行为式评测（§4），不是 loss。

训练前完成了三级验证阶梯：smoke（管线可跑、adapter 可重载）→ overfit（train loss
1.2729→0.0168，76 倍单调下降，token accuracy 0.8605→0.9965，排除 label/mask 系统性缺陷）
→ 全量。overfit 这一级信息量最大，smoke 通过并不能替代它。

## 4. 评测结果

两套评测均为确定性解码（`do_sample=false`、`enable_thinking=false`、
`max_new_tokens=256`、NF4），base 与 candidate 共用同一份任务、预算、parser 与 evaluator。

### 4.1 开发集（60 条 dev，可用于分析与改进）

| 指标 | Qwen3-1.7B base | Qwen3-4B base | **候选（4B+adapter）** |
|---|---|---|---|
| task_success | 0.7000 | **0.8000**（48/60） | 0.7167（43/60） |
| 政策违规数 | 0 | 8 | **0** |
| 非法调用数 | 2 | 21 | **0** |
| schema 有效率 | 0.9714 | 0.7813 | **1.0000** |
| p95 延迟 | 2201 ms | 6068 ms | 5211 ms |
| 峰值显存 | 1.53 GB | 2.94 GB | 2.95 GB |

### 4.2 封存 holdout（120 条，仅用于发布判定，本卡对应**观测 1**）

> 后续观测的主角是另一个候选 `sft-006`，见
> [`MODEL_CARD_sft-006.md`](./MODEL_CARD_sft-006.md)。**观测次数与判定的唯一事实源是
> [`HOLDOUT_LEDGER.md`](./HOLDOUT_LEDGER.md)，本卡不复述次数。**

| 指标 | 基座 | **候选** | 变化 |
|---|---|---|---|
| task_success | **0.7833**（94/120） | 0.7500（90/120） | −0.0333 |
| CI95 | [0.7083, 0.8500] | [0.6750, 0.8250] | 大幅重叠 |
| 政策违规数 | 16（全为 `refund_without_lookup`） | **0** | −16 |
| 非法调用数 | 41 | **0** | −41 |
| schema 有效率 | 0.7819 | **1.0000** | +0.218 |
| p50 / p95 延迟 | 2035 / 5255 ms | 4700 / 5712 ms | p95 比值 1.0870 |
| 输出吞吐 | 45.68 tok/s | 32.32 tok/s | |
| 峰值显存 | 2.95 GB | 2.95 GB | 持平 |
| verifier_reward | 0.5646 | 0.7500 | **与主判据反向** |
| 可重放率 / 证据完整 | 120/120 / true | 120/120 / true | |

证据：`report_id` base `b538a6c4…` / candidate `a8cfcf38…`，均通过全字段自哈希校验；
各 4 个私有产物 SHA-256 独立重算一致；holdout artifact 两侧同为 `c5ef5063…`。

## 5. 失败模式（本卡最重要的部分）

**候选在 holdout 上的失败 100% 是 `premature_final_response`（30 条），
政策违规与非法调用各 0 条。** 它从不违规、从不乱调工具，只是**说完就停**。

| 类别 | 候选失败数 | 说明 |
|---|---|---|
| `refund_eligible` | **20 / 20 全数失败** | 需要 `get_order` → `refund_order` 两步；候选查完就写总结，从不执行状态变更 |
| `refund_recovery` | 9 / 20 | 需要三步（含瞬时故障后重试） |
| `refund_denied_ownership` | 1 / 20 | |
| 其余三类 | 0 | 单次工具调用即可完成的类别全对 |

**曾判定的根因已被 R4 实验证伪**（2026-08-11，LOG-20260811-09）。原判定是：240 条训练
数据中 160 条（66.7%）只含 1 次工具调用，模型学到"调一次 → 写总结"并过度泛化；
更精确的口径是——在「`get_order` 已返回 + 用户以核实/检查口吻要求退款」这一上下文族内，
训练数据是 120 条 denied（写文本并停止）对 40 条 `refund_eligible`（调 `refund_order`），
**3:1 偏向写文本**。

R4 第一轮把该比例**拉到 1:1**（对两个多步家族各重复采样 ×3，sft 240→400 行，
其余一切不变）。结果：`refund_eligible` 在 dev 上从 0/10 变为 **0/10——精确的零变化**。
因此"决策点上的条件动作比例是该行为的主要成因"这一假设在该量级上**不成立**。

**该轮唯一的正向信息**是两个多步家族在同一处理下的分化：`refund_recovery` 3/10→5/10 而
`refund_eligible` 0/10→0/10。二者样本数变化相同，差别在请求措辞——前者是无"核实"字样的
祈使句，后者两个变体都以核实/检查开头。残余嫌疑因此转向**措辞把任务框定成"先核实再回报"**，
但这是观察，**尚未验证**。

行为侧的稳定事实（未被证伪）：失败 100% 是"正确判定可退后向用户请求确认并停止"，
`violations=[]`、`invalid_call=0`；旁证 `average_tool_calls` 1.25→1.18、
`average_turns` 2.25→2.09、`average_output_tokens` 109→147（学到 teacher 的详尽风格）。
该行为在 dev（60 条）与 holdout（120 条）上一致复现，不是小样本偶然。

**基座的失败画像完全不同**：16 次政策违规全部是"未查询即退款"
（`refund_without_lookup`），另有 verifier_failure 7、parser_format 3。
两个模型在不同维度失败——这说明"格式/安全合规"与"多步执行完成"是可以彼此独立变动的
两类能力，SFT 换来了前者、损失了后者。

## 6. 发布判定：NO-GO

| 门禁 | 观测 | 阈值 | 结果 |
|---|---|---|---|
| `success_delta` | **−0.0333** | ≥ +0.05 | **未通过** |
| `policy_violation_delta` | −16 | ≤ 0 | 通过 |
| `invalid_call_count` | 0 | ≤ 0 | 通过 |
| `p95_latency_ratio` | 1.0870 | ≤ 1.25 | 通过 |
| `evidence_complete` | true | true | 通过 |

决策产物：`reports/retail_ops/v1/r3/formal-release-001/`（JSON/Markdown/HTML），
`decision=NO-GO`、`deployment=baseline`。服务据此回滚加载纯基座。

**门禁不等于统计显著性**。两侧 CI95 大幅重叠，仅凭 −3.3pp 不能断言整体显著回退；
但门禁要求的是实测 +5pp 的提升，候选没有做到，NO-GO 因此成立、且不需要附加解释。
反过来，`refund_eligible` 20/20 全数失败是结构性崩溃而非噪声，与格式类
41→0、16→0 的确凿改善同样应当照实陈述。

## 7. 已知限制

1. **单 seed**：一次训练 seed，未做多 seed 重复；不能声称结果对随机性稳健。
2. **`verifier_reward` 不可作为主判据**：它从 0.5646 升到 0.7500，而任务成功率下降。
   复合奖励里的格式/政策分量足以掩盖任务失败。这在 dev 与 holdout 上各发生一次。
3. **延迟精度有限**：gpu-5090 为多人共用，评测期间他人占用在 12.6→11.9→10.8 GB、
   利用率 56%→0%→100% 之间变动。p95 比值 1.0870 距阈值 1.25 有余量，噪声不足以翻转结论，
   但该数**不得表述为精确测量**。
4. **holdout 已消耗三次观测**（次数与判定以 [`HOLDOUT_LEDGER.md`](./HOLDOUT_LEDGER.md) 为准）：结果不得反馈进开发、调参、
   prompt/parser 或 checkpoint 选择。任何新判定都是**第三次**，需用户单独决策。
5. **本卡的结论按模型规模分别成立，不得跨规模引用**（LOG-20260814-05）：
   「LoRA 覆盖越多越好」只在 4B 成立——1.7B 上 attention-only 最好（58/60），
   全 linear 反而把拒绝类由 30/30 打到 15/30；「一句提示词解决大半」同样只在 4B 成立，
   对 1.7B 完全无效。**LoRA 容量必须与模型规模匹配，且与数据配比耦合。**
6. **n=120 的统计功效有限**：±7.5pp 量级的 CI 宽度决定了本项目无法分辨小幅差异，
   这是任务集规模的固有限制，不是评测实现的缺陷。
7. **领域窄**：2 个业务工具、6 类任务、单一中文零售退款场景。跨领域泛化未做任何验证。

## 8. R4 第一轮：已执行，判负

失败类别数量足够、可观测、可复现，满足 R4 的改进准入条件。首选方向定为**训练数据的动作
分布**，并已于 2026-08-11 执行完毕（LOG-20260811-09）。

| 项 | 值 |
|---|---|
| 改动 | 唯一变量是训练数据：`train-export-002`（同一批 240 条冻结任务与同一批 teacher 证据，两个多步家族各重复采样 ×3，sft 240→400 行）；model/lora/training 超参与 R3 逐字段相同 |
| 候选 | `sft-002` / `candidate-002`，`policy_id` 后缀 `#cefbd181ae7f` |
| 训练 | 466.4 s / 75 steps / 峰值 5.54 GB（gpu-5090 GPU 0，他人占用致耗时高于线性外推） |
| 预设门槛 | dev `refund_eligible` ≥7/10，且 `invalid_call`=0、`policy_violation`=0、`schema_valid_rate`=1.0（改动前写定） |
| **结果** | **未通过**：`refund_eligible` **0/10** |
| 逐场景 | 四个单步类保持全对；`refund_recovery` 3/10→**5/10**；`refund_eligible` 0/10→**0/10**；合计 43/60→45/60，仍低于 base 48/60 |
| 格式/安全 | 全部保住：`invalid_call` 0、`policy_violation` 0、`schema_valid_rate` 1.0 |

**按预设停止条件停止**——未改训练目标、未改 system prompt、未扩展算法，
**未消耗封存 holdout 的第二次观测**。该候选从未进入 release 判定，也从未被部署。

一个必须与结果一起说的观察：本轮 `train_loss` 从 0.3722 降到 **0.2198**、
`verifier_reward` 从 0.5792 升到 0.7500，而目标行为没有任何改善。**可优化的代理量全在改善、
真实任务没有**；`verifier_reward` 与主判据反向至此已发生三次（R3 dev、封存 holdout、R4 dev）。

是否开第二轮、验证哪个假设（当前证据指向请求措辞而非数据量），是用户决策门。
是否进入偏好优化仍需等 SFT 路线确认停滞，且必须先有足量执行有效的偏好对——
**一轮负结果不等于停滞**。

## 9. 追溯

| 内容 | 位置 |
|---|---|
| 决定与不可逆边界 | `docs/PROJECT_LOG.md` LOG-20260811-01 |
| 运行中断与恢复 | LOG-20260811-02 |
| holdout 结果与发布判定 | LOG-20260811-03 |
| 服务演示与验收 | LOG-20260811-04 |
| dev 候选评测与失败机制 | LOG-20260807-09 |
| 训练执行 | LOG-20260807-05 ~ -08，`progress.md` 2026-08-07 条目 |
