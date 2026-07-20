# ADR 0003: 采用阶段计划与 append-only 项目日志

- 状态: 已接受
- 日期: 2026-07-17

## 背景

VeriTool-RL 已跨越环境搭建、MiniRetail 和 BFCL Base/SFT 多个阶段。`SPEC.md` 的
按周里程碑不能表达当前依赖与并行边界，ADR 又只适合长期架构决定；普通故障、实验
取舍和阶段门变化缺少稳定的跨会话记录。根目录没有 `AGENTS.md`，且项目约束禁止
创建，因此 Codex 与 Claude 还需要共用已有的 `CLAUDE.md` 协议。

## 决策

- `docs/EXECUTION_PLAN.md` 是阶段状态、依赖、并行轨道和验收门的唯一事实来源；
- `docs/PROJECT_LOG.md` 是 append-only 的中间记录，保存困难、证据、选择、替代方案、
  未选择理由和后果；
- `docs/adr/` 继续只记录影响长期架构或研究方法的决策，`reports/` 保存完整实验产物；
- `CLAUDE.md` 直接包含简短记录触发协议；Codex 通过项目级 fallback 自动加载它；
- Claude 使用 Stop prompt hook 检查实质任务是否报告日志处置，但不自动生成事实内容。

## 后果

- 后续 agent 无需用户重复提醒即可在阶段和决策事件发生时维护日志；
- 阶段事实、日常记录、长期决策和实验报告职责分离，减少互相覆盖；
- Claude Stop 检查会增加一次快速模型判断，且只根据本轮结束信息做遗漏提醒，不作为
  文件内容已正确写入的强证明；
- Codex 只有在信任项目并启动新会话后才读取 `.codex/config.toml`。

## 备选方案

1. **仅更新 `CLAUDE.md`**：最简单，但没有生命周期检查，长期任务更容易漏记。
2. **Hook 自动生成日志**：自动化更强，但无法可靠区分事实和推断，容易产生噪声或
   把 benchmark 答案、终端输出写入版本控制。
3. **根目录三文件计划系统**：`task_plan.md`、`findings.md`、`progress.md` 适合单次
   复杂任务，但会与项目级阶段计划和日志重复，难以确定哪一份是当前事实。

## 参考依据

- OpenAI Codex：[`AGENTS.md` 与 fallback 文件发现](https://developers.openai.com/codex/agent-configuration/agents-md)
- OpenAI Codex：[`config.toml` 项目级配置](https://developers.openai.com/codex/config-reference)
- Anthropic Claude Code：[`CLAUDE.md` 与项目记忆](https://code.claude.com/docs/en/memory)
- Anthropic Claude Code：[`Stop` 与 prompt hooks](https://code.claude.com/docs/en/hooks)
