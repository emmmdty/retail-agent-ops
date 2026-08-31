# RetailAgentOps 产品规格

本文件是产品边界和验收原则的单一事实来源。阶段状态以 [`docs/EXECUTION_PLAN.md`](./docs/EXECUTION_PLAN.md) 为准，求职约束以 [`docs/CAREER_CONTEXT.md`](./docs/CAREER_CONTEXT.md) 为准。

## 1. 产品定义

RetailAgentOps 将零售工具 Agent 的领域定义、轨迹数据、轻量后训练、执行式评测、发布门禁和单卡服务统一为可复现流水线。

目标用户是需要在企业内网或成本敏感场景部署工具 Agent 的算法工程师和 Agent 平台团队。参考业务覆盖订单查询、退款允许/拒绝、异常恢复和政策冲突，不扩展到未经确认的新领域。

## 2. 输入与输出

输入：

- 工具或 OpenAPI schema；
- 版本化业务政策；
- train/dev/frozen-holdout 任务和可执行初始状态；
- 基础模型、模板/parser、运行预算和发布策略。

输出：

- 经过 replay/verifier 的训练或评测轨迹；
- 数据质量、覆盖和泄漏报告；
- LoRA adapter 或训练 `NO-GO`；
- 逐任务指标、失败分类、资源与 provenance manifest；
- `GO/NO-GO` 发布报告；
- 单卡 FastAPI 推理服务和系统卡。

## 3. 稳定接口

计划提供四个稳定入口：

- `build`：生成或导入轨迹并进行执行校验、去重、覆盖和数据划分审计；
- `evaluate`：在冻结任务上运行 base/candidate 并输出可比较证据；
- `release`：按版本化策略产生 `GO/NO-GO`；
- `serve`：加载通过门禁的 base+adapter，暴露受控工具 Agent 服务。

接口必须支持配置文件、seed 和输出目录；运行目录不可覆盖已有正式产物。

## 4. 核心不变量

- 工具调用结果、最终状态和政策 verifier 是主真值；LLM judge 只能补充分析。
- 固定 holdout、答案和失败样例不得进入训练、开发、调参、checkpoint 或 prompt/parser 优化。
- train/dev/holdout ID 必须互斥，manifest 与数据文件必须带哈希。
- 模型、模板、parser、任务、预算和 evaluator 在一次配对比较中必须冻结。
- 正式产物包含代码 commit、依赖锁、数据/模型标识、命令、硬件、耗时和逐任务结果。
- 没有通过发布门禁的模型不得被服务入口默认加载。

## 5. 评测指标

主指标：最终状态任务成功率、关键政策违规、非法工具调用和参数错误率。

工程指标：p50/p95 延迟、吞吐、显存、单任务 token/API 成本、数据执行通过率、轨迹可重放率、环境失败率和证据完整率。

失败至少区分：parser/格式、工具选择、参数 schema、调用次数、业务语义、政策拒绝、恢复失败、环境/API 失败。

## 6. 发布门禁

默认候选必须同时满足：

1. 内部冻结 holdout 相对同基座绝对提升至少 5 个百分点；
2. 关键政策违规不增加；
3. 无非法工具调用；
4. p95 延迟不超过基座 1.25 倍；
5. manifest、逐任务证据和运行环境完整；
6. 最终候选独立重建后仍保持正向提升。

门槛可以经用户决策和日志记录调整，但不得根据 holdout 结果临时降低。

## 7. 训练与算力策略

- Qwen3-1.7B 保留为成本和兼容性基线；Qwen3-4B 是计划主模型，下载和 GPU smoke 需单独确认。
- 主训练路径是单卡 QLoRA-SFT；开发阶段固定一个训练 seed。
- 只有简历引用模型提升时才做一次独立重建，不默认运行三 seed。
- DPO 仅在稳定错误类别可构造足量、执行有效的偏好对且 SFT 已停滞时进入。
- GRPO/在线 RL 不属于 12 周必做范围。
- 商业 API 可用于教师轨迹、用户模拟器和参考上限，但 provider/model ID、成本和采样参数必须记录。

## 8. Benchmark 边界

- MiniRetail 是基础设施和本地回归环境，不等同真实生产数据。
- BFCL 用于 function-calling 兼容与静态能力验证；现有固定 200 条 holdout 保持只读。
- ToolSandbox/τ2 可作为外部有状态 sanity check；若使用其训练数据，不得声称标准排行榜成绩。
- 真实价值主要由 RetailOps 内部冻结任务和发布决策证明，外部 benchmark 只提供可比背景。

## 9. 可靠性与安全

- 工具 schema、参数、状态变更和业务政策必须在执行前后校验。
- 业务政策必须是**可执行的版本化输入**：改阈值不得需要改代码。退款规则自 bundle v2 起由
  `domain/policy_rules.py` 的声明式规则引擎驱动，并渲染成政策卡注入 prompt；
  取消订单规则在 v4 中仍为环境硬编码（声明在 `policies.yaml` 但求值不走统一引擎）。
- guardrail 是与环境校验**分层独立**的可选层：调用前置校验（allowlist、参数域、会话作用域）
  与观测内容消毒（间接 prompt injection）。默认评测路径不启用 guardrail，需显式构造并传入。
- 外部 API 需要超时、重试上限、幂等和错误分类；不得无限重试。
  自 bundle v2 起 `refund_order` 有必填 `idempotency_key`，重试上限由 `policies.yaml`
  的 `max_transient_retries` 驱动（见 `docs/DOMAIN_BUNDLE_V2.md`）；
  v1/v4 的 `refund_order` 不含幂等键，重复退款去重依赖状态字段。
- 日志和报告不得包含 API key、原始受限数据或带答案 holdout 样例。
- 服务必须限制工具 allowlist、请求大小、并发和资源预算，并提供回滚到冻结 base 的路径。

## 10. 非目标

- 不产出论文，不做通用研究平台。
- 不追求基础模型预训练、闭源 SOTA 或 benchmark 排行榜。
- 不为保留算法叙事而强行加入偏好优化或 RL。
- 不构建与当前零售场景无关的复杂前端、分布式训练或多 Agent 编排。
- 不用未验证目标值或生成报告替代实际运行结果。

## 11. 工程完成标准

前 6 周完成的 v1 必须具备：版本化领域输入、可执行数据质检、单卡候选构建、冻结任务评测、发布门禁、服务入口、证据报告和失败恢复说明。

12 周交付必须进一步具备：跨模型或 provider 对比、新鲜任务验证、故障测试、双语公开文档、演示视频、简历量化结果和面试问答。任一数字没有原始产物时不得写入交付。
