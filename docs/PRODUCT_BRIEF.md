# RetailAgentOps 产品说明

## 一句话定位

RetailAgentOps 是面向零售订单、退款和客服操作的**单卡工具 Agent 领域适配与发布流水线**：把工具 schema、业务政策和可执行任务转换为可验证轨迹，完成轻量后训练、评测、发布门禁和推理服务。

## 使用者与应用场景

目标使用者是需要私有化、低成本工具 Agent 的算法工程师和 Agent 平台团队。参考场景是高频零售后台操作：订单查询、退款允许/拒绝、异常恢复和政策冲突处理。

完整业务流：

```text
工具与政策定义
  → 轨迹生成/采集
  → 工具执行和最终状态校验
  → 数据质量与覆盖分析
  → QLoRA-SFT
  → 固定任务评测
  → GO/NO-GO 发布门禁
  → 单卡服务与证据报告
```

## 工程价值

- 将“模型微调”提升为有输入契约、数据治理、执行真值和发布决策的完整交付过程。
- 用本地 1.7B/4B 模型验证隐私、成本和延迟边界，而不是笼统声称小模型优于商业 API。
- 将政策违规、非法工具调用、最终状态错误与语言质量分开，避免只看文本相似度。
- 候选模型不达标时输出 `NO-GO`，防止为了简历数字放宽门槛。

## 对外接口与产物

计划稳定接口为 `build`、`evaluate`、`release`、`serve`。每次运行必须输出：

- 代码 commit、数据/manifest 哈希、模型和 provider 标识；
- 评测阶段产出逐任务执行轨迹（`trajectories.jsonl`）、最终状态与失败分类；发布阶段产出聚合指标（`release.json`）和门禁判定；
- LoRA adapter 或明确的 `NO-GO` 结论；
- JSON / Markdown / HTML 发布报告和 FastAPI 演示服务。

### CLI 关键参数

所有命令共用三个公共参数：`--config`（已提交的 YAML 配置，必填）、`--seed`（运行随机种子，默认 0）、`--output_dir`（新产物目录，必填）。

| 命令 | 独有参数 | 说明 |
|---|---|---|
| `release` | `--baseline_dir` | 基座 run evidence 目录（必填） |
| `release` | `--candidate_dir` | 候选 run evidence 目录（必填） |
| `release` | `--baseline_trajectories` | 可选：基座逐任务 trajectories.jsonl（v1.1 配对统计检验需要） |
| `release` | `--candidate_trajectories` | 可选：候选逐任务 trajectories.jsonl，与上一项必须成对提供 |
| `serve` | `--release_dir` | release report 目录（必填） |
| `serve` | `--input_dir` | build 产物目录（必填） |

`release` 读取两份评测证据（baseline + candidate），逐字段配对校验后计算 delta 并判定
GO/NO-GO。`serve` 加载 release 结论和 build 产物，按发布决策启动服务（GO 加载候选、NO-GO 回滚到基座）。
监听地址、端口和 API 密钥由配置文件和环境变量（`RETAIL_AGENT_OPS_API_KEY`）控制，不走 CLI 参数。

## 竞争边界

RetailAgentOps 不与 veRL、Agent Lightning 等通用训练框架竞争。它的差异是一个具体零售工具 Agent 从领域定义到单卡发布的工程闭环。框架可以作为底层依赖，但不能替代业务政策、执行式数据质检、固定任务门禁和发布报告。

### 竞争格局（2026-08 调研）

现有工具沿"训练—评测—发布"链条分段占位，没有一个覆盖全链且以**发布决策**为输出：

| 层次 | 代表 | 解决什么 | 不解决什么 |
|---|---|---|---|
| Agent 训练框架 | veRL、Agent Lightning、ART、OpenRLHF | 怎么把 agent 训起来（RL/GRPO、框架解耦、trace→triplet） | 领域数据是否执行有效、候选该不该上线 |
| 蒸馏/微调平台 | OpenPipe、distillanything | 用 teacher 造数据把大模型换成小模型 | 业务政策合规、状态级真值、回滚路径 |
| Agent 评测 | τ²-bench、BFCL、DeepEval、MLflow、Confident AI | 打分与 CI 回归（部分已支持 release gate/PROMOTE-HOLD-ROLLBACK） | 领域数据生产、后训练、单卡部署成本边界 |
| 学术闭环 | CLAP（arXiv 2607.01846） | 训练—评测—发布控制的闭环方法论 | 论文口径，不是可交付的工程流水线 |

τ²-bench 是最接近的评测参照：它同样用**数据库最终状态**而非文本相似度判定成功，同样覆盖
retail 域并考察政策遵从。差异在于它是**固定的公开 benchmark**，而本项目要解决的是
"拿到一份私有工具 schema 与业务政策后，如何从零产出可发布的领域模型"。

### 差异化突破口

1. **输出是决策而非指标**。竞品的终点是分数或报告；本项目的终点是 `GO/NO-GO` 加一份
   可审计证据包（逐任务轨迹、失败分类、资源记录、provenance manifest）与明确回滚路径。
   能诚实输出 NO-GO 本身是发布系统的价值，而不是失败。
2. **单一 provenance 贯穿全链**。数据、训练、评测、发布共用同一套内容哈希与配对契约
   （base/candidate 的 bundle/manifest/parser/seed/预算/生成参数逐字段校验，任一不符即
   拒绝给出 delta）。竞品在链条各段之间是断开的。
3. **抗污染 by construction**。2026 年 benchmark 污染已是默认假设（公开 split 泄漏进
   训练语料、SWE-bench Verified 出现确认泄漏）。本项目的主判据来自私有领域任务与密封
   holdout，配合内容哈希与授权门，天然不受公开榜单污染影响——公开 benchmark 只作背景。
4. **把奖励与真值分开**。R3 已出现具体例证：候选的 `verifier_reward` 从 0.579 升到 0.717，
   而真实任务成功率从 48/60 降到 43/60——复合奖励里的格式分量掩盖了执行能力退化。
   坚持"最终状态与政策 verifier 是主真值、奖励值不是"因此不是教条，而是有代价的实践结论。

## 核心指标

- 最终状态任务成功率；
- 关键政策违规数；
- 非法工具调用和参数错误率；
- p50/p95 延迟、吞吐、显存和单任务成本；
- 数据执行通过率、覆盖率、重复率和轨迹可重放率；
- 发布门禁的 GO/NO-GO 结果。

候选相对同基座的默认发布线是：内部冻结 holdout 绝对提升至少 5 个百分点、关键政策违规不增加、无非法工具调用、p95 延迟不超过基座 1.25 倍。具体门槛只能通过正式决策记录修改。

## 已知限制

- **v1 政策规则为 Python 硬编码**：`policies.yaml` 的 `rules:` 在 v1 形态下仅包含六个名字，语义硬编码在 `policy_rules.py` 的 `V1_BUILTIN_RULES` 中。修改退款窗口（如 14 天改为 7 天）需要改 Python 代码。v2 起规则内联在 YAML 里，改阈值不需要碰代码。（参见 `policy_rules.py` 文档字符串）
- **幂等键（`idempotency_key`）仅在 v2+ 生效**：v1 的 `refund_order` schema 不含 `idempotency_key` 参数，环境的 `_replay_same_idempotency_key` 对 v1 走不到。v1 的重复退款去重依赖 `refund_status` 字段而非幂等键。
- **Guardrail 默认不启用**：`run_episode` 的 `guardrail` 参数默认 `None`，正式评测路径当前不传入 guardrail。guardrail 层（注入消毒、作用域检查）需要显式构造并传入。
- **哈希切分不考虑任务难度**：train/dev/holdout 按 `sha256(family)` 确定性切分（240/60/120），不按 margin 或场景难度分层。拒绝类场景的难度分布（margin 值）在 dev 和 holdout 之间可能不对称。

## 非目标

- 不产出论文，不以 ablation 数量或三 seed 作为工程完成标准。
- 不做通用 RL/post-training 框架。
- 不默认做 DPO、GRPO 或在线 RL。
- 不训练基础模型，不追求击败闭源大模型。
- 不把 MiniRetail 或固定 BFCL 子集包装成真实生产数据或官方排行榜成绩。
- 不在没有数据授权和明确业务需求时扩展金融、医疗等新领域。

## 面试叙事

核心问题不是“用了什么微调算法”，而是：如何定义业务任务、如何防止数据和 holdout 泄漏、如何验证工具执行与政策、如何决定模型能否发布、为什么选择单卡部署，以及候选失败时系统如何给出可审计的 `NO-GO`。
