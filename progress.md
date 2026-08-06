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
| 2026-07-22 | 正式目录迁移后首次完整质量门 | 211 passed；Ruff passed；mypy 46 files passed；lock 解析 101 packages；diff passed |
| 2026-07-22 | 迁移路径与资产检查 | 新旧路径、独立 `.git`、R1 ancestry、无 remote、ignored evidence、新 shebang、Gorilla 固定 commit 全部通过 |
| 2026-07-22 | R2 交接提交 `32b9bf7` 实际 HEAD 复验 | 211 passed；Ruff、mypy、lock、diff、迁移路径、BFCL/敏感路径与提示词静态边界全部通过；工作树干净 |
| 2026-08-05 | gpu-5090 环境搭建 `uv sync --extra dev --extra train --frozen` | 成功；`torch==2.13.0+cu130`，`torch.cuda.is_available()==True`，识别 `NVIDIA GeForce RTX 5090` |
| 2026-08-05 | ModelScope Qwen3-1.7B/4B 下载 + 逐文件 SHA256 校验 | `ALL_FILES_VERIFIED_OK`，13/13、14/14 文件全部 `OK`，合计 11.4G |
| 2026-08-05 | DeepSeek `deepseek-v4-flash` 真实 API smoke | HTTP 200；发现默认 thinking 模式，`extra_body={"thinking":{"type":"disabled"}}` 后确认可关闭 |
| 2026-08-05 | Task 3 独立审查后最终 `.venv/bin/pytest -q` + Ruff + mypy + `uv lock --check` + `git diff --check` | 323 passed；Ruff passed；mypy 51 files passed；lock 与 diff 均通过 |
| 2026-08-05 | Task 4 RED（新建 `tests/test_teacher_data.py`） | 缺 `teacher_data` 模块，全部按预期失败 |
| 2026-08-05 | Task 4 首轮 GREEN | 27 selected passed；360 full passed（新增 runner.py/generators.py wire-format 回归） |
| 2026-08-05 | Task 4 独立审查后修复三项真实治理漏洞并补对抗性回归测试 | 32 selected passed；365 full passed；Ruff、mypy 52 files、lock、diff 全部通过 |

## 初始化决策

- 产品名为 RetailAgentOps，Python 包名暂留 `veritool_rl`。
- 默认单卡开发、单 seed 迭代；只有最终简历数字做一次独立重建。
- `AGENTS.md` 成为主入口，`CLAUDE.md` 保持兼容；物理原仓库不修改。

## Next Gate

R1 已完成并关闭；R2 仍为待执行，必须由用户另行确认后才可生成正式
train/dev/holdout、调用模型或进入训练。

## 2026-07-22 — 正式目录迁移与 R2 Codex 交接

- 用户批准把现有独立 checkout 迁移为正式项目目录，并要求生成可在新目录启动、允许 subagent 的 R2 全阶段执行提示词。
- 本轮只做迁移、环境重建、交接设计和静态/CPU 验证；R2 正式数据、模型、API 与 GPU 仍由新会话按门禁执行。
- 迁移前基线：`portfolio/retail-agent-ops-init@59cc1b5`，工作树干净，无 remote；目标目录为 `/home/tjk/myProjects/internship-projects/retail-agent-ops`。
- 现有独立仓库已原子移动到正式目录；旧 `.worktrees/retail-agent-ops` 路径已不存在，Git 历史、分支、ignored qualification 证据和无 remote 状态均保留。
- 主项目与 `tools/bfcl_eval` 的路径敏感虚拟环境已用冻结 lock 在新目录重建；`data/external_repos` 已改为 `../../veritool-rl/data/external_repos`，Gorilla 仍固定在 `6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`。
- R2 完整执行交接入口为 `docs/handoffs/2026-07-22-r2-codex-execution-prompt.md`；它允许 subagent，但保留正式数据来源、teacher/API、计划主模型、模型下载和远程 GPU 的用户审批门。
- 迁移与 R2 交接主体已提交为 `32b9bf7`；该提交已在实际 HEAD 上从头通过完整 CPU、路径、历史、泄漏和 BFCL 边界复验。
- 最终门禁通过后，旧虚拟环境与旧软链接的临时回滚目录已用 `gio trash` 移入系统回收站；Git、R1 evidence 和原 `veritool-rl` 仓库均不在清理范围。

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

## 2026-07-22 — R2 正式数据与双模型 Base 执行启动

- 用户完成数据规模/生成算法、密封治理、provider 路由、teacher 阈值、Qwen3-1.7B/4B dev base、远端目录和审批门设计复核，并授权实施。
- 从 `a3c748bdad1ce6fb7ec8a838d2f1f36da0bbae60` 创建分支 `feature/r2-formal-data-and-base-eval`；未创建第二 worktree、remote 或外部仓库。
- 分支基线为 211 passed、Ruff 和 mypy 通过；`uv lock --check` 的唯一异常已定位为用户级清华镜像 URL 规范化，不涉及依赖版本或哈希变化。
- 当前只进入 CPU 实现与 fake backend 验证。正式数据生成、API、模型下载、SSH 与 GPU 仍保持逐项审批；本地禁止 GPU，R2 禁止 adapter 训练和正式 holdout 模型评测。
- R2 正式规格和逐任务 TDD 计划已经两轮独立只读审阅；content/dev loader/train export/teacher collection 等治理缺口均已收口，最终结论 PASS（无 Critical/Important）。
- Task 1 以 `83bd0b3` 实现 formal family-first 任务生成；独立审查发现三项 integrity/测试缺口后，以 `dfdb8dd` 修复实际政策状态 derivation、重复变体/五指纹重算和全 catalog/420 条环境回归，复审 PASS。最终 219 passed、Ruff/mypy 通过。
- Task 2 以 `e877bd2` 实现 formal manifest/holdout；独立审查发现六项治理绕过后，以 `87a65ff` 增加 fixed provenance、统一 verified dataset、private variant 重建、failure-atomic 双根发布、trusted-root 同 fd 读取和 factory-issued capability。复审 PASS；最终 284 passed。

## 2026-08-05 — gpu-5090 环境扩展与 R2 Task 3 完成

- `.env` 修复：`DEEPSEEK_API_KRY` 等三个变量重命名为 `TEACHER_LLM_DEEPSEEK_*`，新增
  `TEACHER_LLM_PROVIDER=deepseek`，权限 644→600。
- 新增 `gpu-5090` 为第二远程环境（保留 `gpu-4090`），代码通过 git bundle 迁移，`uv` 环境验证
  `torch` 正确识别 RTX 5090，ModelScope 下载的 Qwen3-1.7B/4B 逐文件 SHA256 全部校验通过，
  取代原 HuggingFace revision 作为正式 pin。文档记录提交 `d40c43a`。
- 确认正式 teacher 模型 `deepseek-v4-flash` 可用，发现其默认 thinking 模式会在 `max_tokens`
  不足时把预算耗尽在 `reasoning_content` 上，`extra_body={"thinking":{"type":"disabled"}}`
  可关闭。
- Task 3（provider-agnostic teacher 路由 + OpenAI-compatible client）完成：修复 Ruff/mypy
  各 2 项真实问题，修正 `[tool.uv]` 索引配置错误（`index-url` 在 `uv 0.11.8` 下不生效，改用
  `[[tool.uv.index]] default = true` 后 `uv.lock` diff 从约 3671 行降到 129 行），独立审查
  发现并修复 `RecursionError` 未捕获导致的崩溃（深层嵌套 JSON 会绕过预期的
  `ValueError`/`TeacherClientError`）。最终 323 passed、Ruff、mypy 51 files、lock 与 diff
  检查通过，提交为 `7153c26`。
- Task 4（teacher 采集、回放质检、train 导出）完成：`collect_teacher_attempt` 覆盖 8 类结果
  分类，`export_formal_train`/`write_formal_train_export` 实现质量门与导出。独立审查发现三个
  真实治理漏洞（私有根路径校验可被 `..` 穿越/绝对路径/symlink 绕过、checkpoint resume 不
  校验证据内容、多文件导出非原子写入），均已修复并补对抗性回归测试，复用
  `formal_manifests.py` 里已审计过的 resolve+staging+rollback 模式。最终 365 passed、Ruff、
  mypy 52 files、lock 与 diff 检查通过，提交为 `1d60af2`。R2 CPU 实现的核心数据链路
  （Task 1-4）已完成；剩余 Qwen dev base 配置（对应 R2 计划 Task 5）和最终 R2 收口待开始。

## 2026-08-05 — R2 Task 5（sealed evaluator 与 dev base 证据，CPU 实现）

- 新增 `src/veritool_rl/retail_ops/sealed_evaluation.py`、`src/veritool_rl/retail_ops/base_evaluation.py`，
  并兼容扩展 `src/veritool_rl/agent/qwen.py`（`GenerationSettings`、`GpuMeasurement`、
  `HardwareProvider`/`CudaHardwareProvider`、`hash_local_model_files`/`verify_local_model_files`、
  `TransformersBackend` 的可选 `revision`/`expected_file_sha256`/`settings`）。R1 与 BFCL 的
  两处 `TransformersBackend.from_pretrained(model_name, adapter_path)` 调用点保持原样可用。
- TDD：先写 `tests/test_sealed_evaluation.py`、`tests/test_base_evaluation.py` 并确认因缺模块/
  缺符号而 RED，再实现；`tests/test_qwen_policy.py` 补 7 个模型哈希/revision/硬件测量用例。
- 自审补漏：dev base 评测改为独立重新加载并哈希校验私有 `dev.jsonl` 后再逐条比对调用方
  records；`bootstrap_samples` 冻结为 1000 以保证两个模型可比。
- 验收：`tests/test_sealed_evaluation.py tests/test_base_evaluation.py tests/test_qwen_policy.py
  tests/test_retail_ops_evaluation.py` 92 passed；全仓 `.venv/bin/pytest -q` 442 passed；
  Ruff、mypy 54 files、`git diff --check` 通过。本任务全部在 CPU + fake backend/fake hardware
  provider 上完成，未加载真实模型、未访问 CUDA、未运行任何 API/GPU/下载命令。

## 2026-08-05 — R2 Task 6（CLI pipeline 分派与 CPU 端到端验收）

- `product_cli.py` 新增按 config `pipeline` 字段分派的四条 R2 流水线（`formal_freeze`/
  `teacher_collect`/`train_export` 挂在 `build` 下，`formal_dev_base` 挂在 `evaluate` 下），
  `release`/`serve` 未新增任何 R2 路径；`build` 新增可选 `--input_dir`。R1 四个命令在无
  `pipeline` 字段时逐字节保留原行为（`tests/test_retail_ops_cli.py` 未改一行，5 passed）。
- 新增 6 份 config：`configs/retail_ops_v1_r2_{formal_freeze,teacher_smoke,teacher_full,
  train_export,qwen3_1_7b_dev,qwen3_4b_dev}.yaml`；两份 dev-base config 的 `model.revision`/
  `file_sha256` 是显式标注的占位值（真实 Qwen3 权重尚待用户批准下载）。
- TDD：先写 `tests/test_retail_ops_r2_cli.py`（33 用例，覆盖精确 key 集合、`--input_dir`
  必须/禁止、绝对路径、未知 pipeline、错误 dataset_version/seed/model revision、holdout
  manifest 误传、adapter 相关多余字段、输出覆盖、env 边界）并确认因 `_require_config_keys`
  拒绝新 key、`ImportError`、argparse 报错而 RED，再实现。
- CPU 端到端（`tests/test_retail_ops_r2_e2e.py`，4 用例）：两个隔离 tmp 根各跑一次
  formal_freeze 并逐字节比较全部公开/私有产物；240 条 train 任务跑一次 teacher_collect
  （通用 fake teacher client 按场景无关地回放 `expected_calls`，每类别标记 8/40 失败 ->
  整体/逐类别 80% 接受，越过 70%/50% 质量门）后 train_export 导出 240 条
  train.jsonl/sft.jsonl，来源精确对应 teacher/internal_reference；两份 dev-base config
  各自通过 fake backend + fake hardware provider 跑通 60 条 dev 任务并用真实
  `load_base_run_evidence` 回读校验、扫描公开报告无任务级泄漏。
- `tests/test_project_governance.py` 新增 3 个断言：R2 私有/模型/产物路径仍被既有
  `.gitignore` 规则覆盖（公开 manifest 根相反、不应被忽略）；6 份新 config 解析后的实际
  取值不含绝对路径/私有根路径字面量/凭据标记；`product_cli.py` 和新 config 不引用 BFCL。
- 验收：全仓 `.venv/bin/pytest -q` 489 passed（Task 5 收口基线 449 + 本任务新增 40：
  `test_retail_ops_r2_cli.py` 33、`test_retail_ops_r2_e2e.py` 4（含 1 个双参数化用例）、
  `test_project_governance.py` 新增 3）；Ruff、
  `ruff format`、mypy 54 files、`env -u UV_INDEX_URL uv lock --check`、
  `git diff --cached --check` 全部通过。全程只用 tmp_path 隔离根/fake client/fake
  backend/fake hardware provider，未生成仓库真正的正式数据集输出位置，未加载真实模型、
  未访问 CUDA、未发起任何真实网络请求。

## 2026-08-05/06 — R2 Task 5-7 独立审查、修复与整分支收口

- Task 5、6 各自完成一轮独立审查 + 修复 + scoped re-review：Task 5 发现 1 项 Important
  （backend↔pin 未绑定 adapter/生成参数，`bea052c` 修复）；Task 6 发现 4 项 Important
  （私有根路径未校验、`.env` 边界测试过宽、teacher_collect resume 零覆盖、缺
  `uv lock --check` 治理测试，`96536c9` 修复，其中一次修复派发因触发会话用量限制中断后
  原样重试成功）。均复审通过，无残留 Critical/Important；Minor 记入 SDD 工作区 ledger。
- Task 7 整分支审查（`a3c748bdad1ce6fb7ec8a838d2f1f36da0bbae60..96536c9`，19 commits、
  48 files、+12215/-107）发现 3 项新 Important（`formal_dev_base` 跳过五维隔离断言、
  `export_formal_train` 仅凭 task_id 匹配证据未核验内容、`code_commit` 可能来自脏工作树），
  按流程只有一轮修复+复审：`c4d7fdc` 修复全部 3 项并补 TDD 回归测试，复审（opus 全深度）
  确认全部 ADDRESSED、3 个关键判断（硬失败 vs 回退、排除的哈希字段、注入缝作用域）均合理，
  无新 Critical/Important。
- Task 7 另完成：从头重跑完整 CPU 门禁（`.venv/bin/pytest -q` 506 passed、Ruff、mypy 54
  files、`uv lock --check`、`git diff --check` 全绿，含 `test_retail_ops_r2_e2e.py` 的
  formal_freeze 两根逐字节重复构建比较）；超出 R2 专属治理测试范围的仓库级人工扫描
  （secret 形态字面量、BFCL 引用、holdout 内容跟踪状态）全部干净。
- 产出 `docs/handoffs/2026-08-06-r2-external-run-commands.md`：formal freeze、`.env`
  preflight、6 任务/240 任务 API 调用、只读 SSH 盘点、远端代码同步、模型下载（复用
  gpu-5090 已下载校验过的 Qwen3-1.7B/4B，或全新下载）、单任务/60 任务 GPU dev run、证据
  同步与最终验收，逐节写明"未执行"，并把整分支审查/复审发现的两条真实执行前提（`formal_freeze`
  公开产物需先提交才能进 `formal_dev_base`——`manifests/retail_ops/v1/` 不在 `.gitignore`
  覆盖范围；两份 dev-base config 的真实 model revision/hash 必须提交而非远端临时编辑）
  写入第 0 节。
- R2 阶段状态：CPU 实现（Task 1-7）完成，独立审查全部通过；Task 8（正式数据生成、API
  全量、模型下载、SSH、GPU 命令）仍需逐条单独批准，R2 未标记为已完成。
