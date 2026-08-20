# Claude Code / Codex 接管说明

## 接管读取顺序

新会话开始时必须依次读取：

1. `AGENTS.md` 或 `CLAUDE.md`；
2. `docs/CAREER_CONTEXT.md`；
3. `docs/PRODUCT_BRIEF.md`；
4. `docs/EXECUTION_PLAN.md` 的当前阶段；
5. `task_plan.md`、`findings.md`、`progress.md`；
6. `docs/PROJECT_LOG.md` 最近一条记录；
7. 当前 `git status`、分支、HEAD 和相关测试。

如果这些文件对当前阶段、产品边界或验收口径描述冲突，立即停止并询问用户，不得自行选择对自己实现最方便的版本。

## 本地工作区

- 工作区：`/home/tjk/myProjects/internship-projects/retail-agent-ops`（独立 Git checkout，不是 linked worktree）
- 分支：唯一 `main`，remote `origin = https://github.com/emmmdty/retail-agent-ops.git`（2026-08-20 首次 push），无 submodule，无 linked worktree。
- **本项目自 2026-08-09 起对原 `veritool-rl` 工作区零依赖**：不共享 Git 对象、不共享
  benchmark checkout、不共享虚拟环境。原工作区仍在磁盘上但只是历史存档，删除它不影响
  本项目；同样不得反向清理或覆盖它。
- 分发名与 CLI 入口是 `retail-agent-ops`；Python 导入名仍是 `veritool_rl`
  （已提交产物的 provenance 依赖它，改名属独立任务，见 `docs/LEGACY_INVENTORY.md`）。
- Codex 直接读取根目录 `AGENTS.md`；项目不使用 `.codex` 配置或 Hook。

本地初始化：

```bash
UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple uv sync --extra dev --frozen
UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple uv sync --project tools/bfcl_eval --frozen
```

本地 `data/external_repos/gorilla` 是 ignored 的**自包含** BFCL checkout（固定 commit
`6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`，保留其自身 `.git` 以便
`scripts/legacy/bfcl/run_bfcl_official_ast.py` 校验 commit 与工作树未被改动）。
若目录缺失，按 `data/external_repos/BFCL_PIN.txt` 重建，不得联网拉取浮动 HEAD 替代。

## 历史交接入口（R2，已完成）

在正式目录启动新的 Codex 会话后，把
`docs/archive/handoffs/2026-07-22-r2-codex-execution-prompt.md` 的完整内容作为首条任务提示词。
该提示词负责把 R2 拆成审批、实现、证据和收口门；它允许使用 subagent，但不会替用户
选择正式数据来源、teacher/API、计划主模型或远程 GPU 命令。

## 任务开始协议

在 `task_plan.md` 写明：

- 所属阶段和任务编号；
- 输入、输出、约束和非目标；
- 影响文件；
- 失败模式；
- 验收命令与预期产物；
- 是否涉及 GPU、API、数据下载、公开发布或 holdout。

重大产品/模型/算法/数据/部署选择必须给出至少两个方案、影响和验收差异，然后停止等待用户决策。普通修复和已批准计划内的纵向切片可以直接端到端实施。

## 任务结束协议

1. 更新 `progress.md` 的命令、结果和文件清单。
2. 把跨会话有效的发现写入 `findings.md`。
3. 达到阶段门时更新 `docs/EXECUTION_PLAN.md`，不得提前标完成。
4. 只有改变方法论选型或工程实践的事件才追加 `docs/PROJECT_LOG.md`（门槛见 CLAUDE.md 第 7 节）；代码 bug、测试与重构不写。
5. 运行测试、Ruff、mypy、配置解析和 `git diff --check`。
6. 最终报告实际完成项、未完成项、风险和下一入口，不用计划目标冒充结果。

## 必须停止的情况

- 需要启动任何未获确认的长时间 GPU、批量评测或多 GPU 作业；
- 需要使用、修改或分析固定 holdout 答案来提高候选；
- 需要新增业务领域、算法主线、模型家族或公开发布；
- 数据许可证、API 凭据、成本上限或远程目录不明确；
- 计划要求与现有代码/证据明显冲突；
- 同一阻塞连续三次仍无法解决。

遇到上述情况时保留现场、记录证据并停止并询问用户。
