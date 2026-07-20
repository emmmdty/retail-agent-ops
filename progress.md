# Progress: RetailAgentOps

## 2026-07-20 — R0 初始化

- 创建 worktree `.worktrees/retail-agent-ops` 和分支 `portfolio/retail-agent-ops-init`。
- 从原工作区迁入有效 tracked/untracked 成果，原工作区状态未变化。
- 提交迁入状态快照 `29ea3b9`。
- 建立主 `uv` 环境和独立 BFCL evaluator 环境。
- 建立 ignored `data/external_repos` 相对软链接并验证 Gorilla commit。
- 基线验证：107 tests passed，Ruff 通过，mypy 通过。
- 完成产品重定位、求职背景、R0-R5 阶段计划、Agent 接管和 legacy 文档。
- 新增治理测试并通过 5 项文档契约检查。
- 完整验收：112 tests passed；Ruff、mypy、JSON/TOML 解析和 `git diff --check` 通过。

## Verification Ledger

| Date | Command | Result |
|---|---|---|
| 2026-07-20 | `env -u UV_INDEX_URL uv run pytest -q` | 107 passed |
| 2026-07-20 | `uv run ruff check .` | passed |
| 2026-07-20 | `uv run mypy` | 35 source files passed |
| 2026-07-20 | `.venv/bin/pytest tests/test_project_governance.py -q` | 5 passed |
| 2026-07-20 | `.venv/bin/pytest -q` | 112 passed |
| 2026-07-20 | `.venv/bin/ruff check .` | passed |
| 2026-07-20 | `.venv/bin/mypy` | 35 source files passed |
| 2026-07-20 | JSON/TOML parse + `git diff --check` | passed |

## 初始化决策

- 产品名为 RetailAgentOps，Python 包名暂留 `veritool_rl`。
- 默认单卡开发、单 seed 迭代；只有最终简历数字做一次独立重建。
- `AGENTS.md` 成为主入口，`CLAUDE.md` 保持兼容；物理原仓库不修改。

## Next Gate

R0 已关闭，方案 A 规格与 R1 实现计划已批准。用户选择 subagent-driven 执行，
R1 正在按 10 个 TDD/审查单元实施；正式 train/dev/holdout 仍留到 R2 冻结。

## 2026-07-20 — R1 方案 A 规格准备

- 用户选择窄而完整的退款闭环：2 个正式业务工具、6 类任务、12 条 R1 qualification fixture。
- 设计了正确拒绝与政策违规的分离 verifier 语义，以及 sealed holdout receipt/evidence 边界。
- 未实现代码、未生成正式 R2 数据、未运行 GPU、模型下载、商业 API 或训练。
- 当前设计文件：`docs/superpowers/specs/2026-07-20-retailops-v1-contract-design.md`。

## 2026-07-20 — R1 实现计划

- 用户书面批准方案 A 设计规格。
- 实现计划拆为 bundle、环境、qualification policy、manifest、holdout governance、
  evaluation、release、CLI、FastAPI service 和最终验收 10 个 TDD 任务。
- 计划明确 R1 不读取或生成正式 holdout，R2 才接入 sealed holdout evaluator。
- 尚未实现产品代码，等待用户选择 subagent-driven 或 inline execution。

## 2026-07-20 — R1 subagent-driven 执行启动

- 用户选择方案 1，授权按已批准计划连续执行 Task 1-10，并在每项后做规格与质量审查。
- 当前独立 checkout 为分支 `portfolio/retail-agent-ops-init`，preflight 未发现计划冲突。
- 执行前基线：`.venv/bin/pytest -q` 为 111 passed；未运行 GPU、模型、API 或数据生成。

## 2026-07-20 — Codex 启动与仓库隔离简化

- 复核结论：Codex 当前直接读取根目录 `AGENTS.md`，无需 `.codex/config.toml` 再把
  `CLAUDE.md` 配成 fallback。
- 处理：移除冗余 Codex 项目配置及其专用测试；Claude Code 的 Stop prompt hook 保持不变。
- 隔离：将现有路径原地转为拥有自身 `.git` 的独立 checkout，保留本地 `.venv`、
  `tools/bfcl_eval/.venv`、ignored 数据和固定 benchmark 软链接。
- 阶段边界不变：R1 仍停在规格复核门，不因本维护任务进入实现。
- 验收：111 tests passed，Ruff、mypy 和 diff 检查通过；两个虚拟环境可用，Gorilla
  checkout 仍固定在 `6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`；`git-common-dir`
  为自身 `.git`，无远程；真实 Codex 启动到达正常目录信任界面并以 0 退出。
