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
| 2026-07-21 | R1 Task 1–5 恢复基线 `.venv/bin/pytest -q` | 173 passed |
| 2026-07-21 | Task 6 RED `.venv/bin/pytest tests/test_retail_ops_evaluation.py tests/test_metrics.py -q` | expected 8 failed, 4 passed；缺 `evaluation.py` 与 p50/p95 指标 |
| 2026-07-21 | Task 6 首轮 GREEN focused/full + Ruff + mypy | 20 selected passed；180 full passed；Ruff passed；mypy 43 files passed |
| 2026-07-21 | Task 6 最终 focused/full + Ruff + mypy + diff | 22 selected passed；182 full passed；Ruff passed；mypy 43 files passed；diff passed |
| 2026-07-21 | Task 7 RED `.venv/bin/pytest tests/test_release_policy.py -q` | expected 13 failed；缺 `retail_ops.release` 模块 |
| 2026-07-21 | Task 7 首轮 GREEN/full + Ruff + mypy | 15 selected passed；195 full passed；Ruff passed；mypy 44 files passed |
| 2026-07-21 | Task 7 自审补测/final | 缺失固定 gate 的 RED 生效；16 selected、196 full passed；Ruff、mypy、diff passed |
| 2026-07-21 | Task 8 RED/首轮 GREEN | 4 expected failures（缺产品 CLI/entry point）后 14 selected passed；bundle provenance 补测先失败后修复，最终 15 selected passed |
| 2026-07-21 | Task 8 lock 审计 | `UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple uv lock --offline` 解析 95 packages；`uv.lock` 无 diff |
| 2026-07-21 | Task 8 final | 15 selected、201 full passed；Ruff、mypy 45 files、TOML/5 YAML、lock check、diff passed |
| 2026-07-21 | Task 9 dependency setup | uv 添加 FastAPI 0.139.2、Uvicorn 0.51.0 与 dev HTTPX 0.28.1；console script 可执行；未安装到系统 Python |
| 2026-07-21 | Task 9 RED/首轮 GREEN | 7 expected failures（缺 service/serve）后 12 selected passed；按上游迁移将 dev client 改为 HTTPX2 2.7.0，测试无弃用警告 |
| 2026-07-21 | Task 9 final | 12 selected、208 full passed；Ruff、mypy 46 files、targeted format、lock 与 diff 检查通过 |
| 2026-07-21 | Task 10 RED | E2E 闭环通过；8 项 selected 中仅 closeout 文档治理断言按预期失败 |
| 2026-07-21 | Task 10 artifact acceptance | baseline/oracle/fault 为 8/12、12/12、0/12；GO/candidate 与 NO-GO/baseline；重复树逐文件一致；公开边界与 HTML 检查通过 |
| 2026-07-21 | Task 10 final before commit | 8 selected、211 full passed；Ruff、mypy 46 files、lock 与 diff 检查通过；RetailOps reports ignore 治理负测/修复通过 |

## 初始化决策

- 产品名为 RetailAgentOps，Python 包名暂留 `veritool_rl`。
- 默认单卡开发、单 seed 迭代；只有最终简历数字做一次独立重建。
- `AGENTS.md` 成为主入口，`CLAUDE.md` 保持兼容；物理原仓库不修改。

## Next Gate

R1 已完成并关闭；R2 仍为待执行，必须由用户另行确认后才可生成正式
train/dev/holdout、调用模型或进入训练。

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

## 2026-07-21 — R1 Task 6 续接

- 从 Codex 会话 `019f7e4b-48d3-7513-aa20-9f0a864018ed` 恢复；Task 1–5 已完成并审查。
- 上一会话在 Task 6 RED/GREEN 期间因实现子代理外部 403 退出，仓库未留下 Task 6 代码或提交。
- 恢复时 HEAD 为 `da12c3b`，仅本轮 planning 记录有未提交修改；完整基线为 173 passed。
- 后续从 Task 6 评测证据、指标与脱敏开始，继续执行到 Task 10 和最终 HEAD 质量门。
- Task 6 以提交 `9b13c84` 完成；公开 failures 使用固定允许列表，run loader 会验证 run ID 与 5 个证据产物哈希，holdout 在 policy 执行前拒绝。
- Task 7 以提交 `042071a` 完成；Oracle 走 GO/candidate，unknown-tool 走 NO-GO/baseline，报告无时间戳且 HTML 文本转义。
- Task 8 以提交 `df68c60` 完成；稳定 build/evaluate/release CLI、5 份配置和 console entry 已落地，release 会核对配置 bundle 与两份 evidence 的 SHA。
- Task 9 以提交 `b6cc1e4` 完成；qualification FastAPI 服务按 release 选择 candidate 或 baseline，启动前核对 bundle/manifest，公开响应采用固定字段集合。
- Task 10 的新鲜证据位于 `reports/retail_ops/v1/qualification-r1-final/`，重复证据位于相邻 `qualification-r1-repeat/`；两树逐文件一致，manifest SHA-256 为 `6f510a699c33a5ec9c7df3ef4310a36165b4acff270425b6bfc8c6fd39124f6e`。

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
