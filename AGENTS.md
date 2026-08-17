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

- 当前阶段：`R6` 泛化修复与收口（含最终候选的独立重建复验）**已完成**（2026-08-17）；R0–R5 全部已完成。阶段状态的唯一事实源是 `docs/EXECUTION_PLAN.md`，本节只做摘要。
- R2 已完成方案审批，批准的正式规格与计划位于 `docs/archive/superpowers/specs/2026-07-22-retailops-v1-r2-formal-data-and-base-design.md` 和 `docs/archive/superpowers/plans/2026-07-22-retailops-v1-r2-formal-data-and-base.md`。
- 正式数据、API、模型下载、SSH 和每条 GPU 命令仍需分别确认；CPU 实现授权不跨越这些外部资源门。
- **封存 holdout 的观测次数、逐次读数与判定见 `docs/HOLDOUT_LEDGER.md`（唯一事实源，本文件不复述次数）。**
  **观测次数不再是硬约束**（用户 2026-08-17），但**结果永远不得反馈进开发**。
- release 判定：**前三次 NO-GO / baseline**（第一次输在 `success_delta` −0.0333，第二、三次候选做到 120/120、`success_delta` +0.1417 但输在延迟）；此后转为 `GO` / candidate，候选是同一份权重的**合并部署形态**（p95 比值 2.03 → 1.13）。发布门禁阈值一个字未改，有测试锁定。逐次判定见台账。
- **引用那个 GO 必须同时给出分布外读数**：同一候选在模板外 60 条上只有 0.5833、表达变化类 0/20，比零训练基座还差（`docs/OOD_EVALUATION.md`）。120/120 不是泛化，有测试强制两者成对出现。
- **SPEC §6 六条门禁已全部满足**，第 6 条「独立重建复验」见 `docs/REBUILD_VERIFICATION.md`。同时发现**训练不可逐位复现**：同 seed 重跑得到 58/60，dev 读数须表述为「58–60/60，三次同配置运行」。
- R4 的两条结论都经过跨规模检验并被限缩，引用时必须带规模条件：**LoRA 容量须与模型规模匹配**（4B 上全 linear 最好，1.7B 上 attention-only 最好、全 linear 让拒绝类由 30/30 崩到 15/30）；**提示词干预是规模依赖的**（对 4B 有效、对 1.7B 完全无效）。见 LOG-20260814-05。
- 候选结论一律以 dev 或 holdout 口径分别陈述，**不得把 dev 读数写成 release 判定**；dev 已被用于候选选择，带选择偏差。
- 当前 BFCL Base/SFT 为 163/200 与 167/200，差值置信区间跨 0，不能声称稳定改善。
- 质量门为 `pytest` / `ruff check` / **`ruff format --check`** / `mypy` / `uv lock --check` / `git diff --check` / `scripts/ci/audit_public_release.py`，全部必须通过。
- 仓库形态：唯一 `main` 分支、0 remote、对原 `veritool-rl` 工作区零依赖；目录职责见 `docs/REPO_MAP.md`。
