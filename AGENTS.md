# AGENTS.md — RetailAgentOps

本文件是 Codex 和其他 coding agent 的首要入口。Claude Code 同时读取
[`CLAUDE.md`](./CLAUDE.md)。开始任何实质工作前，必须按以下顺序恢复上下文：

1. [`docs/CAREER_CONTEXT.md`](./docs/CAREER_CONTEXT.md)
2. [`docs/PRODUCT_BRIEF.md`](./docs/PRODUCT_BRIEF.md)
3. [`docs/EXECUTION_PLAN.md`](./docs/EXECUTION_PLAN.md)
4. 根目录 [`task_plan.md`](./task_plan.md)、[`findings.md`](./findings.md)、[`progress.md`](./progress.md)
5. [`docs/PROJECT_LOG.md`](./docs/PROJECT_LOG.md) 最近一条记录

## 不可违反的边界

- 项目目标是可部署的零售工具 Agent 工程闭环，**不产出论文，不以论文实验为交付物**。
- 当前产品名是 **RetailAgentOps**；Python 包暂保留 `veritool_rl`，未经单独计划不得全仓改名。
- 用户负责产品方向、重大方案选择、验收与面试复盘；Codex/Claude 可以实现全部代码和测试。
- 未经用户确认，不得新增产品方向、业务领域、训练算法、模型家族或大型基础设施。
- 本地 WSL 只运行 CPU 开发、测试、lint 和类型检查；不得在本地运行 GPU 推理或训练。
- 任何远程 GPU 命令必须先给出精确命令、工作目录、物理 GPU、预计时长和产物，等待用户确认。
- 固定 BFCL holdout 及其失败样例不得进入训练、开发、调参、checkpoint 选择或提示词修改。
- 外部 benchmark 成绩必须使用窄口径，不得声称官方全量、排行榜或生产效果。
- 开发阶段默认一个训练 seed；只有简历要引用模型提升时才做一次独立重建复验，不默认做三 seed。
- 12 周必做范围不包含 GRPO/在线 RL；DPO 只有满足执行计划中的失败数据入口门才允许启动。
- Python 统一使用 `uv`；文档、注释和报告默认简体中文。
- 不覆盖、不清理其他工作区的未提交内容；不自动 push、发布或创建外部仓库。

## 每个任务的固定流程

1. 在 `task_plan.md` 写清输入、输出、非目标、影响文件和验收命令。
2. 高影响方案至少给出两个选项并停止，等待用户决策；低风险实现按现有计划直接推进。
3. 行为变更先写失败测试，再实现最小闭环。
4. 每两次重要查看/检索后，把发现写入 `findings.md`。
5. 完成一个阶段后更新 `progress.md` 和 `docs/EXECUTION_PLAN.md` 状态。
6. 触发长期决策、实验结果、失败或 go/no-go 时，追加 `docs/PROJECT_LOG.md`，历史不得改写。
7. 最终至少运行 `.venv/bin/pytest -q`、`.venv/bin/ruff check .`、`.venv/bin/mypy` 和 `git diff --check`。

## 当前状态

- 当前阶段：`R0` 初始化与治理已完成，等待用户批准 `R1`。
- 已继承 MiniRetail、BFCL 固定评测、QLoRA-SFT 与可追溯运行基础。
- 当前 BFCL Base/SFT 为 163/200 与 167/200，差值置信区间跨 0，不能声称稳定改善。
- 不自动进入 `R1`；下一任务先由用户确认产品契约和冻结规则。
