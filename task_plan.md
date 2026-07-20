# Task Plan: RetailAgentOps

## Goal

在 12 周内交付可公开、可复现、可面试解释的零售工具 Agent 单卡适配与发布流水线，并在前 6 周完成首个工程闭环。

## Current Phase

R1 当前；方案 A 已获用户选择，尚未进入实现。

## Current Task

- 输入：用户选择的方案 A、R0 文档、现有 MiniRetail/BFCL 资产和 [设计规格](docs/superpowers/specs/2026-07-20-retailops-v1-contract-design.md)。
- 输出：经书面复核的 RetailOps v1 契约设计；用户复核前不创建实现计划。
- 非目标：不实现 R1 代码；不生成正式 R2 数据或 holdout；不运行 GPU、模型、API、下载或正式训练。
- 影响文件：设计规格、R1 阶段记录、`task_plan.md`、`findings.md`、`progress.md`、`docs/PROJECT_LOG.md`。
- [x] 核对方案 A 范围与现有代码缺口。
- [x] 编写契约、工具、政策、指标和 holdout 设计。
- [ ] 完成规格自审并等待用户书面复核。
- 验收命令：`.venv/bin/pytest -q`、`.venv/bin/ruff check .`、`.venv/bin/mypy`、`git diff --check`。

## Task Rules

- 本文件只跟踪当前任务；长期阶段状态以 `docs/EXECUTION_PLAN.md` 为准。
- 新任务开始时重写 Current Task，保留已完成任务的摘要到 `progress.md`。
- 输入、输出、非目标、失败模式和验收命令不完整时不得开始实现。
- GPU、API、数据下载和公开发布必须显式标注授权状态。

## Errors

| Date | Error | Resolution |
|---|---|---|
| 2026-07-20 | 新 worktree 缺 BFCL evaluator 环境和 ignored benchmark checkout | 建立独立 evaluator venv，并通过相对软链接共享固定 checkout |
| 2026-07-20 | 本机镜像变量机械改写 `uv.lock` | 反向应用仅 lock diff，后续命令显式清除 `UV_INDEX_URL` |
| 2026-07-20 | 清除 `UV_INDEX_URL` 后 `uv run` 仍按全局索引改写 `uv.lock` | 最终验收直接调用已冻结 `.venv/bin/*`，提交前精确回退 lock diff |
| 2026-07-20 | 新治理测试被 Ruff I001 拒绝双空行 | 按 import sorter 的最小 diff 删除一行空白后重跑 |
