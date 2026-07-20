# 旧项目状态与迁移清单

## Git 来源

- 原仓库：`/home/tjk/myProjects/internship-projects/veritool-rl`
- 原分支/起点：`main@3e1a88d7d5298bb825c41db8b07a98dea2f5c490`
- 初始化目录：`/home/tjk/myProjects/internship-projects/.worktrees/retail-agent-ops`（现已转为独立 checkout）
- 初始化分支：`portfolio/retail-agent-ops-init`
- 迁入状态快照：`29ea3b9`
- 初始化来源远程仅有 `gpu-4090`；独立 checkout 不配置远程，远程操作继续按显式审批执行。

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
- `data/external_repos` 是 ignored 相对软链接，当前指向原仓库固定 checkout。
- Gorilla/BFCL commit 必须保持 `6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`。
- 模型、数据、checkpoint 和运行产物继续不进入 Git。

## 命名边界

产品、简历和公开文档使用 RetailAgentOps；Python 包、已有配置路径和历史报告暂保留 `veritool_rl`/`VeriTool-RL`。代码级改名必须作为独立任务执行并验证所有调用点，不在初始化阶段机械替换。
