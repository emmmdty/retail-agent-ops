# Task Plan: RetailAgentOps

## Goal

在 12 周内交付可公开、可复现、可面试解释的零售工具 Agent 单卡适配与发布流水线，并在前 6 周完成首个工程闭环。

## Current Phase

R0 已完成；等待用户确认后才能建立 R1 任务。

## Current Task

- [x] 建立独立 worktree 和分支。
- [x] 迁入并验证旧工作状态。
- [x] 完成产品、求职、阶段、接管和 legacy 文档。
- [x] 通过治理契约测试和完整质量门。
- [x] 提交初始化结果，等待用户确认进入 R1（本提交）。

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
