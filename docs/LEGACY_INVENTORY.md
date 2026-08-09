# 旧项目状态与迁移清单

## Git 来源与独立性

- 原仓库：`/home/tjk/myProjects/internship-projects/veritool-rl`
- 原分支/起点：`main@3e1a88d7d5298bb825c41db8b07a98dea2f5c490`
- 初始化目录：`/home/tjk/myProjects/internship-projects/.worktrees/retail-agent-ops`（历史路径，2026-07-22 已迁出）
- 当前正式目录：`/home/tjk/myProjects/internship-projects/retail-agent-ops`（独立 Git checkout）
- 初始化分支：`portfolio/retail-agent-ops-init`（2026-08-09 收敛后已删除，其提交全部包含在 `main` 中）
- 迁入状态快照：`29ea3b9`

**2026-08-09 起本项目对原仓库零依赖**，逐项核实：唯一 `main` 分支、0 remote、
无 submodule、无 linked worktree、无 `.git/objects/info/alternates`、无跟踪软链接、
无跨仓库文件系统链接；虚拟环境只指向本目录。101 个提交完整保留。
删除原 `veritool-rl` 工作区不会影响本项目的任何命令。

## 已继承能力

- MiniRetail 确定性任务、trajectory、replay、verifier 和指标；
- Qwen3-1.7B Base/QLoRA-SFT 最小闭环；
- BFCL 固定 720/80/200 数据划分、官方 AST evaluator 和固定 200 条 holdout；
- Base/SFT 163/200 与 167/200 的窄口径结果及失败分析；
- messages/pretokenized SFT 数据兼容、防篡改 manifest 校验和相关测试；
- append-only 项目日志、ADR 与 Claude Code 配置；Codex 由根目录 `AGENTS.md` 接管。

这些事实可以作为工程基础，但旧的课程式训练、多 seed、偏好优化和 GRPO 路线不再是活动计划。

## 未迁入的新工作区生成物

以下未跟踪文件仍完整保留在原工作区，因为它们是旧研究路线的生成型报告，不属于新公开主线：

| 文件 | SHA-256 |
|---|---|
| `docs/progress-report-20260717/artifact.json` | `1239a822787bfa6cac6365648e9111a98c8e66b81b7b26b66927e809a4b40d69` |
| `docs/progress-report-20260717/report.html` | `5417b5105faff05010c8c4ca1eda399e24e86c1874b31f0dce97feece4c15860` |
| `docs/progress-report-20260717/source_queries.sql` | `9edd41a891b16ef5776d2c4d13755c11fc1e4c42352d4dff69d08e3679d4e68e` |

没有删除这些文件。若未来需要归档，必须重新核对内容和公开边界后单独决定。

## 本地非 Git 依赖

- `tools/bfcl_eval/.venv` 由 `uv sync --project tools/bfcl_eval --frozen` 创建。
- `data/external_repos/gorilla` 是**自包含**的 BFCL checkout（2026-08-09 由原软链接
  `../../veritool-rl/data/external_repos` 本地化而来），保留其自身 `.git` 以支持
  `run_bfcl_official_ast.py` 的 commit 与工作树校验；细节见
  `data/external_repos/BFCL_PIN.txt`。
- Gorilla/BFCL commit 必须保持 `6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`。
- 未随迁的 `tau2-bench`/`appworld`/`ToolSandbox` 在本仓库零引用；需要时按 `BFCL_PIN.txt`
  记录的上游地址单独获取并固定 commit。
- 模型、数据、checkpoint 和运行产物继续不进入 Git。

## 命名边界

产品、简历、公开文档、**分发名与 CLI 入口**统一为 RetailAgentOps / `retail-agent-ops`
（分发名于 2026-08-09 从 `veritool-rl` 改为 `retail-agent-ops`）。

Python 导入名与历史报告仍是 `veritool_rl`/`VeriTool-RL`：已提交产物记录了产出它们的
代码标识，改名会切断"代码 commit ↔ 运行产物"的可追溯链。导入名重命名必须作为独立任务
执行、验证全部调用点，并单独说明 provenance 断层，不做机械替换。

目录职责与 2026-08-09 的路径对照见 [`REPO_MAP.md`](./REPO_MAP.md)。
