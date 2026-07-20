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

- 推荐工作区：`/home/tjk/myProjects/internship-projects/.worktrees/retail-agent-ops`（独立 Git checkout，不是 linked worktree）
- 初始化分支：`portfolio/retail-agent-ops-init`
- 原始工作区：`/home/tjk/myProjects/internship-projects/veritool-rl`，不得清理或覆盖。
- Python 包暂为 `veritool_rl`；产品品牌是 RetailAgentOps。
- Codex 直接读取根目录 `AGENTS.md`；项目不使用 `.codex` 配置或 Hook。

本地初始化：

```bash
env -u UV_INDEX_URL uv sync --extra dev --frozen
env -u UV_INDEX_URL uv sync --project tools/bfcl_eval --frozen
```

本地 `data/external_repos` 是 ignored 相对软链接，指向原仓库已固定的 benchmark checkout。若链接不存在，先核对 `docs/LEGACY_INVENTORY.md`，不得联网拉取浮动 HEAD 替代。

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
4. 重大决定、失败、GPU 运行或结论追加 `docs/PROJECT_LOG.md`。
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
