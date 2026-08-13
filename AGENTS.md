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
- 产品名、分发名与 CLI 是 **RetailAgentOps** / `retail-agent-ops`；Python 导入名仍是 `veritool_rl`，未经单独计划不得全仓改名（理由见 `docs/REPO_MAP.md` 第 5 节）。
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
6. 只有**改变方法论选型或工程实践**的事件（方案选型及其被证伪、正式 GPU/长任务运行、go/no-go、契约冻结、约束变化）才追加 `docs/PROJECT_LOG.md`；代码 bug、测试、重构、配置微调不写。门槛见 CLAUDE.md 第 7 节，历史不得改写。
7. 最终至少运行 `.venv/bin/pytest -q`、`.venv/bin/ruff check .`、`.venv/bin/mypy` 和 `git diff --check`。

## 当前状态

- 当前阶段：`R3` 单卡适配与服务 v1；R1 产品契约与 v0.1、R2 数据与评测流水线均已完成。
- R2 已完成方案审批，批准的正式规格与计划位于 `docs/archive/superpowers/specs/2026-07-22-retailops-v1-r2-formal-data-and-base-design.md` 和 `docs/archive/superpowers/plans/2026-07-22-retailops-v1-r2-formal-data-and-base.md`。
- 正式数据、API、模型下载、SSH 和每条 GPU 命令仍需分别确认；CPU 实现授权不跨越这些外部资源门。
- R3 已完成：首次真实 Qwen3-4B QLoRA-SFT（`reports/retail_ops/v1/r3/sft-001/`）与 60 条 dev 候选配对评测。
- R3 候选结论：格式/安全类失败清零（invalid_call 21→0、policy_violation 8→0），但 task_success 48/60→43/60，回退集中在需 ≥2 次工具调用的场景，**不适合直接替换 base**；这是 dev 结论，不是 release 判定。
- 尚未进入：正式 120 条 holdout 评测、release GO/NO-GO、serve 部署。
- 当前 BFCL Base/SFT 为 163/200 与 167/200，差值置信区间跨 0，不能声称稳定改善。
- 正式 RetailOps holdout 至今未运行真实模型；任何 release 访问仍须满足 sealed purpose/hash 门禁。
- 仓库形态：唯一 `main` 分支、0 remote、对原 `veritool-rl` 工作区零依赖；目录职责见 `docs/REPO_MAP.md`。
