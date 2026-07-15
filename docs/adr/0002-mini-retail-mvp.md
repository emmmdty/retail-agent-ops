# ADR 0002: 采用领域专用 MiniRetail 环境打通 MVP

- 状态: 已接受
- 日期: 2026-07-15

## 背景

项目需要先证明 task、工具调用、观测、确定性 verifier、轨迹、重放和指标能够
形成可信闭环，再承担 ToolSandbox 的依赖隔离和 tau2 user simulator 成本。

## 决策

实现纯 Python、无外部副作用的 MiniRetail 订单环境，覆盖状态查询、合规退款、
拒绝违规退款和一次性工具错误恢复。任务规格完整嵌入版本化 trajectory；
AgentRunner、Policy、ToolEnv 与 Replay 使用明确接口解耦。每个 assistant turn
只允许一个 Hermes tool call，多调用视为协议错误。

训练数据由通过 verifier 的 Oracle 轨迹转换为 TRL 原生 `messages + tools` 格式。
Qwen3 基线与 QLoRA adapter 使用相同 4-bit NF4 推理条件，训练前后按 task_id
配对，不预设必须提升。

## 后果

- 状态变化、政策规则和奖励均可逐行审计，本地测试无需模型或 GPU；
- 相同 seed 的任务和 JSONL 可重复，轨迹篡改会在具体 step/field 被重放发现；
- MiniRetail 只证明基础设施，不作为 BFCL/ToolSandbox/tau2 研究成绩；
- parallel tool call、真实 benchmark adapter、DPO/GRPO 和奖励校准留待后续 ADR。

## 备选方案

曾考虑用 YAML/JSON 条件与 effect DSL 构建通用状态机。该方案扩展领域更快，
但会在 MVP 阶段额外引入表达式语义、类型转换和 verifier 可信面，因此暂不采用。
