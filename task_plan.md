# Task Plan: RetailAgentOps

## Goal

在 12 周内交付可公开、可复现、可面试解释的零售工具 Agent 单卡适配与发布流水线，并在前 6 周完成首个工程闭环。

## Current Phase

R1 当前；方案 A 已获用户选择，尚未进入实现。

## Current Task

- 输入：用户选择的方案 A、R0 文档、现有 MiniRetail/BFCL 资产和 [设计规格](docs/superpowers/specs/2026-07-20-retailops-v1-contract-design.md)。
- 输出：基于已批准规格的可执行 R1 实现计划；用户选择执行方式前不实现代码。
- 非目标：不实现 R1 代码；不生成正式 R2 数据或 holdout；不运行 GPU、模型、API、下载或正式训练。
- 影响文件：实现计划、`task_plan.md`、`findings.md`、`progress.md`、`docs/PROJECT_LOG.md`。
- [x] 核对方案 A 范围与现有代码缺口。
- [x] 编写契约、工具、政策、指标和 holdout 设计。
- [x] 完成规格自审并取得用户书面批准。
- [x] 编写并自审 R1 实现计划。
- [x] 提交 R1 实现计划（本提交）。
- [ ] 等待用户选择执行方式；选择前不修改产品代码。
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

## Maintenance: Codex 启动简化

- [x] 确认 `AGENTS.md` 已覆盖 Codex 接管和记录协议
- [x] 移除冗余 `.codex/config.toml` 与对应 fallback 测试
- [x] 将 linked worktree 原地转为独立 Git checkout
- [x] 验证环境、ignored benchmark 链接、质量门和 Codex 启动
- [x] 提交结果，保持 R1 规格复核门不变
