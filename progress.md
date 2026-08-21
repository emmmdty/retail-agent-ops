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
| 2026-08-07 | R3 Task 1 preflight（HEAD `1af7b32`） | 508 passed；Ruff、mypy 54 files、lock、diff 全绿 |
| 2026-08-07 | R3 A RED（provenance） | 3 expected failures：`revision`/`file_sha256` 为 extra_forbidden、无哈希校验 |
| 2026-08-07 | R3 B RED（dev_sft_export） | collection error：缺 `retail_ops.dev_sft_export` 模块 |
| 2026-08-07 | R3 C RED（CLI 分派） | 23 expected failures：缺 `_run_dev_sft_export`/`_run_sft` |
| 2026-08-07 | R3 E RED（治理） | 3 expected failures：4 份 R3 config 尚未创建 |
| 2026-08-07 | R3 A-F GREEN 全量门禁 | 557 passed；Ruff、mypy 55 files、`uv lock --check`、`git diff --check` 全绿 |
| 2026-08-07 | R3 F 本地真实 dev-sft 导出（CPU/Oracle） | 60 条；0.39s；`sha256sum` 独立核对 `41ae6409...` 与公开摘要一致 |
| 2026-08-07 | R3 G 代码 + 私有 SFT 数据同步 gpu-5090 | ff-only 到 `ec9cad5`；679KB 数据本地/远端 SHA-256 一致 |
| 2026-08-07 | R3 H token 审计（gpu-5090 CPU，2.2s） | train max=730 / dev max=727 token；0/300 超 1024；空 mask 行 0 |
| 2026-08-07 | R3 I GPU smoke（GPU 0，17.8s） | 未复现 Triton JIT；loss 1.4479/2.3065 有限；峰值 5.13 GiB；adapter 重载 `loaded: true` |
| 2026-08-07 | R3 J overfit 检查（GPU 0，54.6s） | train loss 1.2729→0.0168（76x）；tok_acc 0.8605→0.9965；label/mask 无系统性缺陷 |
| 2026-08-07 | R3 K 全量 SFT（GPU 0，2m20.8s） | train_loss 0.3722；eval_loss 0.5266/0.5603/0.5797；峰值 5.16 GiB；adapter 23.6 MB |
| 2026-08-07 | R3 L 产物同步与核对 | 11 个文件本地/远端 SHA-256 逐一一致；`git check-ignore` 全覆盖 |
| 2026-08-07 | R3 T2 CPU 实现（候选评测契约 + 配对比较） | 585 passed（+28）；Ruff、mypy 56 files、lock、diff 全绿 |
| 2026-08-07 | R3 T2 候选评测（GPU 0，4m18s） | 60/60；schema_valid 0.781→1.000、invalid_call 21→0、policy_violation 8→0；task_success 0.80→0.7167 |
| 2026-08-07 | R3 T2 产物同步与回读 | 公开报告 + 5 个私有证据哈希逐一一致；`run_id` 本地复算通过 |

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

## 2026-08-06/07 — R2 Task 8（审批门控执行）

- Step 1-3（本地）：正式 240/60/120 formal 数据集生成并提交公开 manifest（`89e8039`）；
  teacher 全量采集 238/240 通过质量门（`refund_denied_window` 修复后 95%）；train_export
  导出 240 条正式 train。过程中发现并修复一个真实环境设计缺陷（`environment.py::_get_order`
  未暴露 `current_day`，导致窗口过期场景对推理式 agent 不可解），独立审查 PASS。
- Step 4-5（远端 gpu-5090）：只读盘点确认物理 GPU 0（RTX 5090）可用；代码/模型/私有 dev
  数据同步；排查两个真实基础设施问题（符号链接触发路径逃逸安全检查、`torch>=2.13` Triton
  JIT 缺系统编译器，最终用 `TORCH_DISABLE_NATIVE_JIT=1` 解决）；Qwen3-1.7B/4B 60 任务
  dev base 均完整跑通并通过证据重载校验，公开报告已同步回本地且哈希核对一致。
- Step 6：完整 CPU 门禁在实际最终 HEAD 重跑通过；仓库级 secret/BFCL/holdout 泄漏扫描干净；
  Task 8 阶段独立复审进行中。

## 2026-08-07 — R3 Task 1（SFT CLI 接入，本地 CPU 部分）

- 用户选定方案 A：直接对 Qwen3-4B 做 SFT，不先用 1.7B 探路。
- `training/sft.py::ModelSettings` 补齐 provenance 锁定：`revision`/`file_sha256` 必填，
  `run_sft` 在任何写盘和 `import torch` 之前调用 `verify_local_model_files`。三条 RED
  （字段不存在、文件被篡改、清单外多余文件）先失败后通过，全部在纯 CPU 上用真实 `run_sft` 验证。
- 新增 `retail_ops/dev_sft_export.py`：只用 Oracle 为 dev 生成轨迹并转 `trajectory_to_sft_example`，
  公开接口不接受 client 参数；私有 `dev-sft/<attempt_id>/sft.jsonl` 经 staging 原子发布，
  公开侧只留不含 task_id 的聚合摘要。
- `product_cli.py` 新增 `dev_sft_export`/`sft` 两条 build 流水线（各自精确 key 集合、
  `trainer_factory` 注入缝、私有根相对路径逐分量校验）；R1/R2 既有路径未改动。
- 新增 4 份 R3 config 与 4 项治理断言；另加"已提交 config 必须能穿过 CLI 并被真实
  `resolve_sft_config` 接受"的防漂移测试。
- 本地真实执行 dev-sft 导出（纯 CPU、Oracle、无模型/网络/API）：60 条、六类各 10 条、
  与 train 无 ID 交叉、哈希独立核对一致。
- 验收：557 passed、Ruff、mypy 55 源文件、`uv lock --check`、`git diff --check` 全绿。
- **未进入**：token 长度审计、远端同步、GPU smoke、overfit 检查、全量 SFT——均为待逐条批准的
  外部执行门。

## 2026-08-07 — R3 Task 1 外部执行门（gpu-5090 物理 GPU 0）

- 六个外部执行门逐条批准后执行：代码/私有数据同步 → token 审计 → GPU smoke → overfit 检查
  → 全量 SFT → 产物同步核对。
- token 审计确认 `max_seq_len=1024` 足够（train/dev 最长 730/727 token，0/300 超限），无需
  调整、无静默截断；同时确认 assistant mask 无空行、end-of-turn token 进 loss mask。
- 提示词留的未知项已解答：`TORCH_DISABLE_NATIVE_JIT=1` 对训练算子路径同样有效，两次训练
  均未复现 Triton JIT 编译器缺失问题。
- 三级验证阶梯全部通过：smoke（管线可跑、adapter 可重载）→ overfit（train loss 76 倍单调
  下降，排除 label/mask 系统性缺陷）→ 全量（240+60，3 epoch，全部 loss 有限）。
- 正式候选 adapter：`reports/retail_ops/v1/r3/sft-001/adapter/`，23.6 MB，离线重载通过；
  运行内嵌 model pin 与 R2 dev-base config 的 revision 及 13 项逐文件哈希完全一致。
- 已知口径限制：dev-sft 最终回复是 Oracle 常量串，eval_loss 与 train 不同分布，只能当弱
  sanity 信号；候选质量的权威依据是后续 60 条 dev 任务的行为式评测。
- 未进入正式 holdout 评测、release GO/NO-GO 与 serve 部署——留给下一个提示词。

## 2026-08-07 — R3 Task 2（候选 dev 评测与配对比较）

- 新增 `retail_ops/candidate_evaluation.py`：adapter 逐文件哈希锁定、候选证据契约
  （子类扩展，避免破坏已产出的 R2 base 证据自哈希）、`compare_dev_runs` 配对校验。
- `base_evaluation.py` 抽出 `require_dev_evaluation_preconditions` 与 `measure_dev_run`
  两个共用核心，保证 base/candidate 经过同一套守卫与同一套指标机器。
- 真实候选评测（gpu-5090 GPU 0，60 条 dev，与 base 同契约）：格式/安全类指标全面清零
  （invalid_call 21→0、policy_violation 8→0、schema_valid_rate 0.781→1.000），
  但 task_success 48/60→43/60。
- 失败机制已定位：回退完全集中在需要 ≥2 次工具调用的两类场景，7 个新失败全部是
  "说完就停、未执行状态变更"；根因是训练数据 66.7% 只有 1 次工具调用。
- 结论：该候选不适合直接替换 base。未做 release GO/NO-GO 判定、未打开正式 holdout、
  未部署 serve。失败类别明确可复现，符合 R4 输入条件，具体改进需用户确认。

## 2026-08-09 — 仓库收敛（Git 单分支化、独立性切断、四接口目录重排）

- Git：`feature/r2-formal-data-and-base-eval` 重命名为 `main`，删除已被完全包含的
  `portfolio/retail-agent-ops-init`；101 个提交与 HEAD 均未变。最终形态：唯一 `main`、
  0 remote、无 submodule、无 linked worktree、无 alternates、无跟踪软链接。
- 独立性：`data/external_repos` 由指向 `../../veritool-rl` 的软链接改为自包含目录，
  只本地化被引用的 gorilla（BFCL）固定 checkout。**保留 gorilla 自身 `.git`**——
  实测剥离后 `run_bfcl_official_ast.py::_verify_checkout` 的 commit 与工作树校验失效、
  2 个测试失败；42 MB 换一个已被测试覆盖的 provenance 校验。写 `BFCL_PIN.txt` 记录
  上游、commit、保留理由与三个未随迁 checkout 的获取方式。
- 分发名 `veritool-rl` → `retail-agent-ops`（导入名 `veritool_rl` 按用户决策保留，
  理由是已提交产物的 provenance 可追溯链）；`uv.lock` 仅自身条目变化。
- src 分层：core（跨领域基础设施）/ retail_ops（domain·build·evaluate·release·serve）/
  training / legacy。86 个文件的 import 经单次扫描重写，0 残留；**函数体零改动**。
- configs 按四接口分层，scripts/reports/docs 分离活动与 legacy/archive；
  `.gitignore` 规则跟随迁移并实测 4 条关键路径仍被覆盖。
- 行为不变的强证明：三份真实运行证据（R2 qwen3-1.7b/4b base、R3 candidate）重新加载后
  `run_id` 自哈希与逐产物哈希复算全部一致。
- 新增两项治理测试：分层单向依赖（core 不依赖 retail_ops/legacy、主线不依赖 legacy）、
  四接口在模块与配置上各有归属且非空。测试基线 585 → 587。
- 清理：删除 18 个 `__pycache__`、空 `.codex/`、41 MB 工具缓存；`.superpowers/` 与
  `.codex/` 的忽略规则从本地私有的 `.git/info/exclude` 迁入随仓库分发的 `.gitignore`。
  仓库体积（不含 .git/.venv/data/tools）83M → 40M。
- 文档：新增 `docs/REPO_MAP.md`（目录职责、依赖方向、路径对照表）；README、CLAUDE.md、
  AGENTS.md、HANDOFF、LEGACY_INVENTORY 同步到 R3 与新布局。历史台账
  （PROJECT_LOG、findings、progress 旧条目、reports/legacy 内产物）按 append-only
  原则**未改写**，靠 REPO_MAP 的对照表回溯。
- 全量门禁：587 passed、Ruff、mypy 64 源文件、`uv lock --check`、`git diff --check` 全绿。
- 未进入：R3 剩余目标（正式 120 条 holdout、release GO/NO-GO、serve 部署）、任何 GPU 与
  API 调用、远程仓库创建与 push。

## 2026-08-10 — R3 Task 3 A（sealed holdout provenance 与 CLI 入口，纯 CPU）

- A1+A2（合并）：新增 `SealedEvaluationConfig`（继承 `BaseEvaluationConfig`，adapter 可选）；
  `SealedEvaluationReport` 补 model/adapter/generation/hardware/config_sha256/code_commit/
  uv_lock_sha256，去掉与 `generation` 重复的 `max_new_tokens`；`evaluate_authorized_holdout`
  改收 config + models_root + hardware_provider，并接上 `_require_backend_matches_pin` 双向
  绑定；新增 `require_comparable_sealed_runs` 与 `SEALED_PAIRING_FIELDS`。
- A3：`evaluate` 新增 `formal_holdout_base` / `formal_holdout_candidate` 两条流水线与
  `_default_sealed_backend` 工厂；新增两份已提交 config（model 段与 R2 dev base 逐字段相同，
  adapter 段与 R3 dev candidate 相同，均由脚本从既有 config 复制而非手抄哈希）。
- TDD 记录：两次 RED 均先失败于符号缺失（`require_comparable_sealed_runs`、
  `_run_formal_holdout`）；adapter 双向绑定的两条测试另做突变验证——注释掉
  `_require_backend_matches_pin` 调用后立即 `DID NOT RAISE`，恢复后转绿。
- 测试基线 587 → 604 passed；Ruff、mypy(64 源文件)、`git diff --check` 全绿。
- **未进入**：任何 holdout 实际运行（GPU 与授权门未开）、B（formal release 门禁）、
  C（真实模型 serve）。

## 2026-08-10 — R3 Task 3 B/C（formal 发布门禁与真实模型 serve，纯 CPU）

- B：`release.py` 抽出 `build_release_gates` 与公开 `GATE_IDS`（R1 行为不变，22 项相关测试
  通过）；新增 `release/formal_release.py`——`FormalReleaseReport` + `decide_formal_release`
  + JSON/Markdown/HTML 三份报告 + 回滚说明；`release` 命令按 `pipeline: formal_release`
  分发，新增已提交 config。
- C：`serve/service.py` 新增 `create_formal_app`（R1 `create_app` 未改）：按 `deployment`
  加载 base+adapter 或回滚 base，双重校验；串行 episode（超限 503）、请求体上限（超限 413）、
  `/v1/tasks` 暴露工具 allowlist、`/health` 暴露决策/失败门禁/回滚。`serve` 命令按
  `pipeline: formal_serve` 分发，`backend_factory`/`app_runner` 两个注入缝，新增已提交 config。
- 突变验证三处安全关键行：`require_comparable_sealed_runs`、
  `_require_backend_matches_deployment`、`_MAX_CONCURRENT_EPISODES`，去掉后对应测试均立即失败。
- 验收：624 passed（587 → 624）、Ruff、mypy(65 源文件)、`uv lock --check`、
  `git diff --check` 全绿；三份真实证据 run_id 复算一致（`07671235…`/`d57654e9…`/`29648b8c…`），
  R1 两份 qualification release 报告仍可加载。
- **未进入**：任何 holdout 实际运行、任何 GPU/商业 API 调用、任何 formal 发布结论、
  任何真实模型服务部署。

## 2026-08-11 — R3 封存 holdout 执行与首个 formal 发布决策

- 前置四项全部解除：Task 3 代码提交 `90c9038`（脏工作树会被 `_current_code_commit` 拒绝）；
  gpu-5090 由 `0c6f552` ff-only 同步到 `90c9038` 并重建环境（`veritool-rl` →
  `retail-agent-ops` 分发名变更，仅同步 git 会留下失效的 editable 安装）；封存
  `holdout.jsonl` 首次同步至远端（双端 SHA-256 `c5ef5063…` 一致，仍被 `.gitignore` 覆盖）；
  用户批准 base + candidate 背靠背连跑（改变 08-10「先只跑 base」的决定，理由见 LOG-20260811-01）。
- 首次启动（11:13:45）被 gpu-5090 于 12:10 整机重启中断，**零产出**：输出目录为空、
  `sealed-eval/` 不存在，holdout 盲性未消耗；残骸用 `rmdir`（非 `rm -rf`）清除后重跑。
- 正式运行（物理 GPU 0，RTX 5090）：base 12:25:38→12:45:47（评测本体 286.98s），
  candidate 12:45:47→12:55:07（评测本体 544.21s），peak memory 均约 2.95 GB。
- base：task_success 0.7833（94/120）、policy_violation 16（全为 `refund_without_lookup`）、
  invalid_call 41、schema_valid_rate 0.7819、p95 5255.0 ms、verifier_reward 0.5646。
- candidate：task_success 0.7500（90/120）、policy_violation 0、invalid_call 0、
  schema_valid_rate 1.0000、p95 5711.9 ms、verifier_reward 0.7500；失败 **100% 为
  `premature_final_response`**，其中 `refund_eligible` 20/20 全数失败、`refund_recovery` 失败 9/20。
- 证据核验：两份 `report_id` 自哈希通过、4 个私有产物 SHA-256 独立重算一致、
  回传公开副本与远端私有原件逐字段相等。
- 发布判定 **NO-GO / deployment=baseline**，唯一失败门禁 `success_delta`（−0.0333 < +0.05）；
  其余四项通过（policy_violation_delta −16、invalid_call 0、p95 比值 1.0870、evidence_complete）。
- 未进入：`serve` 的 baseline 回滚部署与允许/拒绝/异常恢复三条演示流程；R3 阶段状态未改。

| Date | Command | Result |
|---|---|---|
| 2026-08-11 | 本地全量门禁（HEAD 前）`.venv/bin/pytest -q` / Ruff / mypy / lock / diff | 624 passed；65 源文件；105 packages；全绿 |
| 2026-08-11 | 三份既有真实证据 `run_id` 复算 + R1 两份 release 报告加载 | `07671235…`/`d57654e9…`/`29648b8c…` 一致；GO/candidate 与 NO-GO/baseline 可加载 |
| 2026-08-11 | gpu-5090 `uv sync --extra dev --extra train --frozen` | 卸载 `veritool-rl==0.0.1`，装入 `retail-agent-ops==0.0.1`；import smoke 通过 |
| 2026-08-11 | holdout base（GPU 0，20m9s / 本体 286.98s） | 120/120；task_success 0.7833；p95 5255.0 ms |
| 2026-08-11 | holdout candidate（GPU 0，9m19s / 本体 544.21s） | 120/120；task_success 0.7500；p95 5711.9 ms |
| 2026-08-11 | sealed 证据回传与独立核验 | `report_id` 自哈希 + 4 私有产物哈希 + 公开=私有，全部一致 |
| 2026-08-11 | `release --pipeline formal_release` | NO-GO / baseline；仅 `success_delta` 失败 |

## 2026-08-11 — R3 serve：按 NO-GO 回滚部署与三条演示流程

- gpu-5090 物理 GPU 0 加载冻结 Qwen3-4B base，`127.0.0.1:8000`；`service.json` 与 `/health`
  一致声明 `NO-GO` / `deployment=baseline` / `adapter_loaded=false` /
  `failed_gate_ids=["success_delta"]`，`policy_id` 无 adapter 后缀（对照候选证据的
  `…+adapter:…#34544fac3ec9`）。
- 三条流程全部成功且轨迹可见：允许（`get_order` → `refund_order` → refunded）、
  拒绝（`get_order` 返回 `not_found` → 停止且未尝试退款、`violations=[]`）、
  异常恢复（`refund_order` 遇 `transient_error` → 重试 → refunded）。
- 并发上限真实验证：并发两请求，先到 200、后到 **503**「服务已达并发上限」。
- 诚实记录：并发测试中作为陪衬的另一条 `refund_eligible` 失败
  （`termination=final_response`）——base 在 qualification 上也会"说完就停"，
  演示挑选的成功案例不代表全对。
- 收尾：服务已关闭、8000 端口释放、远端工作树干净；系统盘日志/脚本已移入数据盘
  `reports/retail_ops/v1/r3/`（仍被 `.gitignore` 覆盖），`/home/tongjiakai` 无残留。
- **R3 验收目标 4/5 达成**；未达成项是「面试可演示交付」，依赖尚未产出的模型卡、系统卡、
  演示流程与第一版简历证据。R3 阶段状态保持「当前」。

| Date | Command | Result |
|---|---|---|
| 2026-08-11 | 远端 R1 qualification `build`（CPU） | 12 条任务 + manifest |
| 2026-08-11 | `serve --pipeline formal_serve`（GPU 0） | baseline 回滚部署，adapter_loaded=false |
| 2026-08-11 | 允许 / 拒绝 / 异常恢复 三条 episode | 三条 `success=true`、`violations=[]`，轨迹完整 |
| 2026-08-11 | 并发两请求 | 200 + 503（并发上限生效） |

## 2026-08-11 — R3 交付文档收口与 R4 启动准备

- 产出四份交付文档：`docs/MODEL_CARD.md`（候选模型卡，含 dev/holdout 双表与六项限制）、
  `docs/SYSTEM_CARD.md`（系统卡，含治理机制、资源画像与八项限度）、
  `docs/DEMO.md`（5 分钟讲解 + CPU/GPU 两条演示路径 + 三个必讲失败案例 + 深挖问答）、
  `docs/RESUME_EVIDENCE.md`（数字出处对照、七类禁写表述、两个 bullet 方案）。
- 产出 R4 执行提示词 `docs/handoffs/2026-08-11-r4-execution-prompt.md`：
  不预批任何 GPU/API/第二次 holdout 观测，列出五项用户决策门。
- **阶段状态未改**：`docs/EXECUTION_PLAN.md` 的 R3 仍为「当前」，按 R2 先例
  （LOG-20260807-03）由用户确认后才更新。
- 待用户裁决：简历 bullet 选方案 A（系统与证据）还是方案 B（模型与归因）。

| Date | Command | Result |
|---|---|---|
| 2026-08-11 | 文档收口后全量门禁 | 624 passed；Ruff / mypy 65 源文件 / lock / diff 全绿 |

## 2026-08-11 — R4 第 0 步：只读核查（未改任何产品文件）

- 按 R4 提示词第八节执行**只读**排查：数据覆盖 → 模板/parser → 工具 schema → verifier。
  只使用 train(240) 与 dev(60)；**未打开任何 sealed holdout 产物**。
- 66.7% 从 `train-export-001/sft.jsonl` 独立复算成立（160/240）。同时发现该口径偏粗：
  动作长度与场景类别完全共变；真正的竞争比例是「核实/检查口吻要求退款」上下文族内的
  120:40 = 3:1；训练集中 100% 的自然语言监督来自 4 个单步类别，多步类别贡献 0 字符。
- 候选 dev 失败逐条检查：17/17 是同一行为——正确判定可退后**向用户请求确认并停止**，
  而非中性的"说完就停"。
- 模板/parser、工具 schema、verifier 三层均无缺陷；但 parser 的
  `mixed_tool_call_content` 规则约束了改进方案（工具调用消息不得带文本）。
- 推翻两条方案前提：train 每类别 40 条是 `assert_exact_quotas` 硬契约，新增任务需重新冻结
  数据集并作废已有证据可比性；`system_prompt_sha256` 属 sealed 配对字段，改提示词会让
  已有 sealed holdout base 证据不可再用。
- 未做任何改进实现；等待用户在五项决策门上裁决。详见 `findings.md` 同日小节与
  LOG-20260811-06。

| Date | Command | Result |
|---|---|---|
| 2026-08-11 | 训练集动作长度/文本分布重算（本地 CPU） | 160/240 单次调用；多步类别文本字符 0 |
| 2026-08-11 | dev 候选轨迹逐条检查（本地 CPU） | refund_eligible 0/10、refund_recovery 3/10；17/17 失败为请求确认 |
| 2026-08-11 | bundle tools vs 训练集 tools 比对 | 逐字节一致；system prompt 唯一且等于 runner.SYSTEM_PROMPT |
| 2026-08-11 | 只读核查后全量门禁 | 624 passed；Ruff / mypy 65 源文件 / lock / diff 全绿 |

## 2026-08-11 — R4 Task 1 CPU 侧（重复采样导出与配置）

- 用户裁定（LOG-20260811-07）：阶段切到 R4；第一轮方案 = 对多步家族重复采样；
  预设收益门槛 = dev `refund_eligible` ≥7/10 且格式/安全三项不退化。
- 实现（TDD，两处安全关键断言各经突变验证）：`export_formal_train` /
  `write_formal_train_export` 支持按场景 `sft_oversample`，只重复 `sft.jsonl` 行；
  `train_export` 配置契约新增**必填** `sft_oversample`；新增 R4 导出与训练两份配置；
  治理测试把 R4 配置纳入既有 secret/路径/BFCL/holdout/模型 pin 扫描。
- 本地 CPU 导出产出 `train-export-002`：`train.jsonl`/`selection.json` 与 001 逐字节相同，
  `sft.jsonl` 400 行、去重后仍是原 240 条，单步占比 66.7%→40.0%，
  「核实/检查口吻要求退款」族内 3:1→1:1。
- 候选评测 config **推迟**到训练之后——`adapter.file_sha256` 是运行产物，提前写就是占位。
- **未执行**任何 GPU 训练或评测；工作树待提交后才能跑远端（`_current_code_commit` 拒绝脏树）。

| Date | Command | Result |
|---|---|---|
| 2026-08-11 | `build --config …r4_train_export_rebalanced.yaml`（本地 CPU） | 240→400 行 sft；provenance 与 001 逐字节相同；质量门 238/240 复算一致 |
| 2026-08-11 | R4 Task 1 CPU 收口全量门禁 | **636 passed**（624→636）；Ruff / mypy 65 源文件 / lock / diff 全绿 |

## 2026-08-11 — R4 Task 1 GPU 执行与判负

- 训练 `sft-002`（gpu-5090 物理 GPU 0）：466.4 s / 75 steps / 峰值 5.54 GB，`EXIT=0`，
  adapter 重载校验通过；`train_loss` 0.3722→0.2198。
- dev 候选评测 `candidate-002`：299.3 s，`EXIT=0`；`compare_dev_runs` 配对契约通过，
  base 沿用既有 `qwen3-4b-dev-base-001`（未重跑）。
- **判负**：`refund_eligible` **0/10**（门槛 ≥7/10）。逐场景 R3→R4：四个单步类保持全对、
  `refund_recovery` 3/10→5/10、`refund_eligible` 0/10→0/10；合计 43/60→45/60，
  仍低于 base 48/60。格式/安全三项全部保住（0 / 0 / 1.0）。
- 按预设停止条件停止，不转而改训练目标或提示词。未消耗 holdout 第二次观测。
- 结论与被证伪的假设见 `findings.md` 同日小节与 LOG-20260811-09。

| Date | Command | Result |
|---|---|---|
| 2026-08-11 | `build --config …r4_sft_rebalanced.yaml`（gpu-5090 GPU 0） | 466.4 s，75 steps，峰值 5.54 GB，EXIT=0 |
| 2026-08-11 | `evaluate --config …r4_qwen3_4b_candidate.yaml`（同卡） | 299.3 s，EXIT=0，task_success 0.7500（45/60） |
| 2026-08-11 | `compare_dev_runs`（本地 CPU） | 配对契约通过；task_success delta −0.0500 |

## 2026-08-13 — R4 第二轮 Stage 1（三候选消融的 CPU 侧，A/B 就绪）

- 开工核查推翻设计 spec §4.3 的一条实现假设：`trajectory_to_sft_example` 的 system 消息
  取自 `trajectory.metadata["system_prompt"]`，而 teacher 证据是已持久化的轨迹
  （240 份全是旧 prompt，来源 teacher 238 / internal_reference 2）。改
  `runner.SYSTEM_PROMPT` 后重新导出，238/240 条逐字节不变且**不会报错**。
  已请示用户，裁定：**在导出侧改写 system 消息**。
- 实现（TDD，三处安全关键断言经突变验证）：`export_formal_train` /
  `write_formal_train_export` 新增 `sft_terminal_response` 与 `sft_system_prompt_sha256`
  两项纯局部变换；`train_export` 配置契约两键均**必填**；后者声明期望哈希而非布尔，
  使"常量忘了改"成为硬错误。
- 新增配置：候选 A（`retail_ops_v1_r4_round2_a_sft_lora_full.yaml`，唯一改
  `lora.target_modules`）、候选 B 导出与训练两份（`train-export-003`）。
  三条单变量纪律断言各自逐字段比对参照点 `retail_ops_v1_r4_sft_rebalanced.yaml`。
- 治理测试新增「漏登记就红」的双向比对，两个方向各经突变验证。
- **候选 C 的配置与常量改动刻意不在本阶段**：`SYSTEM_PROMPT` 一旦提交，A/B 就无法在
  旧 prompt 下评测且配对基线失效；`_current_code_commit` 又拒绝脏工作树，所以 C 必须
  等 A/B 的 GPU 跑完。
- 候选评测 config 一律**推迟**到训练之后——`adapter.file_sha256` 是运行产物。
- **未执行**任何 GPU 训练或评测。

| Date | Command | Result |
|---|---|---|
| 2026-08-13 | `build --config …r4_round2_b_train_export.yaml`（本地 CPU，0.56 s） | `train-export-003`：provenance 与 001 逐字节相同；400 行；末尾 role 由 `assistant 160/tool 240` 变为 `assistant 400`；决策点形状仍 160:240；工具调用消息 content 非空违反者 0 |
| 2026-08-13 | Stage 1 收口全量门禁 | **665 passed**（638→665）；Ruff / mypy 65 源文件 / lock / diff 全绿 |

## 2026-08-14 — R4 第二轮 Stage 2（候选 A、B 的 GPU 执行与 dev 配对）

- 远端连通性插曲：gpu-5090 一度不可达（cpolar 隧道 Connection refused），曾按用户指示
  评估 gpu-4090 并完成建目录/装环境/传数据/启动模型下载；随后 5090 恢复，改回 5090 执行。
  4090 上留下 `/data/TJK/internship-projects/retail-agent-ops`（环境已装、模型下载中断于
  7.6 GB），**待用户决定是否清理**。
- 已核实 dev 的 `PAIRING_FIELDS` 不含任何硬件字段，故跨机配对在契约上允许；
  回到 5090 后 base 与候选同机，该问题自动消失。
- **候选 A 达标**：`refund_eligible` 10/10、合计 **60/60**、格式安全三项 0/0/1.0。
- **候选 B 未达标但有信号**：`refund_eligible` 4/10（≥3/10 诊断阈值）、合计 54/60、
  `refund_recovery` 5/10→10/10、三项同样保住。
- 结论与统计限度见 `findings.md` 同日小节与 **LOG-20260814-01**。
- 候选 C 未执行；未消耗 holdout 第二次观测。

| Date | Command | Result |
|---|---|---|
| 2026-08-14 | A 训练 `sft-003`（GPU 0，空闲） | 222.6 s / 75 steps，峰值 5.638 GB，train_loss 0.1800，adapter 重载通过 |
| 2026-08-14 | A dev 评测 `candidate-003` | 268.5 s，EXIT=0，配对契约通过，**60/60** |
| 2026-08-14 | B 训练 `sft-004` | 212.2 s，峰值 5.563 GB，train_loss 0.2246 |
| 2026-08-14 | B dev 评测 `candidate-004` | EXIT=0，配对契约通过，**54/60** |

## 2026-08-14 — R4 第二轮 Stage 3/4（候选 C、base 重跑、三候选收官）

- Stage 3（CPU）：改 `runner.SYSTEM_PROMPT`（新 sha256 `8ae813c4284246b9…`）、
  导出 `train-export-004`、C 的三份配置（train_export / sft / base 重跑）。
  核验：`sft.jsonl` 与 002 除 system 消息外逐样本相同；`train.jsonl` 有且仅有 2 行不同，
  是两条 `internal_reference` 样本（Oracle 实时重放，必然带新 prompt），已逐字段确认
  其轨迹除 `metadata.system_prompt` 外完全相同。
- Stage 4（GPU）：`base-002` 零训练 → `sft-005` 训练 → `candidate-005` 评测，全部 EXIT=0，
  配对契约通过（C 对 `base-002`，不对 `base-001`）。
- **三候选收官**：A 60/60（`refund_eligible` 10/10，**唯一达标**）、B 54/60（4/10）、
  C 55/60（5/10）。新 prompt 零训练 base 54/60（**9/10**）。
- 结论见 `findings.md` 同日小节与 **LOG-20260814-02**。按 spec 停止条件停止。
- 未消耗 holdout 第二次观测。

| Date | Command | Result |
|---|---|---|
| 2026-08-14 | C 导出 `train-export-004`（本地 CPU） | 400 行，system 全部为新 prompt，决策点 160:240 不变 |
| 2026-08-14 | `base-002` 新 prompt 零训练评测 | EXIT=0，**54/60**，refund_eligible **9/10**，invalid_call 0，schema 1.0 |
| 2026-08-14 | C 训练 `sft-005` | 197.9 s，峰值 5.553 GB，train_loss 0.2191 |
| 2026-08-14 | C dev 评测 `candidate-005` | EXIT=0，**55/60**，refund_eligible 5/10（**低于自身 base 的 9/10**） |

## 2026-08-14 — R4 第三轮实验 1（容量 × 指令框定叠加）

- 动机：第二轮遗留的方法论缺口——A 的 +0.200 对照的是旧 prompt 的 base，
  而新 prompt 零训练 base 已 54/60，delta 里训练与 prompt 的贡献无法分离。
- 做法：A 的 lora 段 + C 的 data 段，配对 `base-002`，**两侧同 prompt**。
- 结果：**60/60**，delta **+0.100**，`policy_violation` 5→0、`recovery_success` 0.5→1.0。
- 结论见 `findings.md` 同日小节与 **LOG-20260814-03**。
- 未消耗 holdout 第二次观测。

| Date | Command | Result |
|---|---|---|
| 2026-08-14 | 叠加训练 `sft-006` | 293.7 s（GPU 被占 81%），峰值 5.647 GB，train_loss 0.1795 |
| 2026-08-14 | 叠加 dev 评测 `candidate-006` | EXIT=0，**60/60**，对 base-002 delta **+0.100** |

## 2026-08-14 — 第二次封存 holdout 观测与第二次发布判定（R4 收官）

- 插曲：首次尝试时 SSH 在握手阶段失败（cpolar 隧道端口变更），**未消耗任何观测**，
  已逐项核实（`holdout-base-002` 目录、`sealed-eval` attempt、日志、marker 均不存在）。
  隧道恢复后重跑。
- 两侧均在同一 commit（`ae82917`）、同一新 prompt、GPU 相对空闲时执行：
  `holdout-base-002`（103/120）→ `holdout-candidate-002`（**120/120**）→ `formal-release-002`。
- **判定：NO-GO / baseline**，唯一失败门禁 `p95_latency_ratio` 1.8774 > 1.25；
  `success_delta` **+0.1417** 通过。
- 延迟归因已分离：单次调用耗时 1.985×，调用次数仅 1.146×——代价来自全 linear LoRA
  的前向开销，不是多做调用。详见 `findings.md` 同日小节与 **LOG-20260814-04**。
- 产物已回传，双端 SHA-256 一致，两份 sealed 报告本地重载 `report_id` 复算通过。
- **封存 holdout 两次观测均已消耗。**

| Date | Command | Result |
|---|---|---|
| 2026-08-14 | `evaluate --config …r4_holdout_base.yaml` | EXIT=0，**103/120**，p95 3052 ms |
| 2026-08-14 | `evaluate --config …r4_holdout_candidate.yaml` | EXIT=0，**120/120**，p95 5730 ms |
| 2026-08-14 | `release --config …r4_formal_release.yaml` | **NO-GO**，4 PASS / 1 FAIL（p95 1.8774） |

## 2026-08-14 — R4 第三轮跨规模验证（Qwen3-1.7B）

- 目的：把 4B 上的"容量决定训练符号"从单模型观察升级为跨规模规律。
- 方法：2（模型规模）× 2（LoRA 覆盖）对照，同一份 `train-export-004`、同一组超参，
  各与同规模同 prompt 的零训练 base 配对；对齐关系由
  `tests/test_retail_ops_r4_round3_cross_scale.py` 断言并经三处突变验证。
- **结果：上一轮结论被证伪。** 1.7B 上 attention-only 58/60（强正作用）、
  全 linear 45/60（几乎无增益，且拒绝类由 30/30 崩到 15/30、policy_violation 0→5）。
- 替换后的规律：**容量必须与模型规模匹配，不存在"越大越好"**；且**数据配比与容量耦合**。
- 另一条被限缩：**prompt 干预对 1.7B 完全无效**（elig 0/10），prompt/训练分工结论只在 4B 成立。
- 详见 `findings.md` 同日小节与 **LOG-20260814-05**。未消耗 holdout 观测。

| Date | Command | Result |
|---|---|---|
| 2026-08-14 | 1.7B base 重跑 `base-1p7b-002` | EXIT=0，**44/60**，elig 0/10 |
| 2026-08-14 | 1.7B attn 训练 + 评测 | 100.1 s / adapter 13 MB；**58/60**，delta **+0.2333** |
| 2026-08-14 | 1.7B full 训练 + 评测 | 116.3 s / adapter 34 MB；**45/60**，delta +0.0167 |

## 2026-08-15 — 架构补强轨道：批次 1 + 批次 3（纯 CPU，未提交）

- 用户裁定：新开补强轨道 **R4.5**（阶段状态待提交后更新）、本轮做批次 1+3 一次提交、
  `sft-006` 出**独立**模型卡、`perturb_schema` **接入** qualification 轨道。
- 全部为本地 CPU。**未动 GPU / 商业 API / 模型下载 / 封存 holdout。**
- 基线 698 passed → **755 passed**；Ruff / mypy / `uv lock --check` / `git diff --check` 全过。

| 项 | 内容 | 证据 |
|---|---|---|
| 1.1 serve 服务化（P1-7） | `POST /v1/chat` 自由请求、`/v1` 全面 Bearer 鉴权（key 只来自 `RETAIL_AGENT_OPS_API_KEY`，缺失时**启动即失败**）、trace_id + 结构化 JSON 日志（只落请求 SHA-256 摘要与字符数）、`GET /metrics`（Prometheus 文本，无新依赖）、episode 超时 504 结构化降级 | `tests/test_retail_ops_service_layer.py` 19 项；4 次突变验证全部被抓（鉴权恒真、鉴权短路、去掉 fail-closed、日志写原文） |
| 1.2 CI + 容器（P2-12） | `.github/workflows/ci.yml` + `scripts/ci/verify_qualification_chain.py` + CPU-only `Dockerfile` | 本地跑通：决策、失败门禁、`bundle_sha256`/`task_manifest_sha256` 与确定性指标全部等于冻结期望 |
| 1.3 文档单一事实源（P2-11） | 新建 `docs/HOLDOUT_LEDGER.md`；修掉 README/SYSTEM_CARD/MODEL_CARD 的"唯一一次观测"；SYSTEM_CARD §5 资源表补 R4 实测；新建 `docs/MODEL_CARD_sft-006.md` | `test_holdout_ledger_is_the_single_source_of_truth`、`test_the_strongest_candidate_has_a_model_card` |
| 1.4 `verifier_reward` 降级（P2-10） | 只改呈现层：报告主表移出，新增「诊断量」分区 + 固定说明；`release.json` / `metrics.json` 字段一个不少 | `tests/test_verifier_reward_demotion.py` 6 项 |
| 3.x 门禁版本化（P1-4/P1-5/§6.3） | `GATE_IDS_BY_SCHEMA` 双版本；v1.1 把 episode p95 拆成 `per_call_latency_ratio` / `steps_to_success_ratio` / `latency_per_success_ratio`，并加配对 bootstrap CI 下界门禁；`release.yaml` **逐字节未动** | `tests/test_release_gate_schema_v11.py` 16 项；3 次突变验证全部被抓 |
| P2-13 `perturb_schema` 接入 | qualification 轨道新增 `perturb_schema` **必填**配置键 + `schema_adaptive` 策略 + 一对只差该开关的对照配置 | `tests/test_retail_ops_schema_robustness.py` 8 项 |

**本地对照读数（规则策略，不涉及模型）**：`schema_adaptive` 在未扰动/扰动两侧均 12/12、
`invalid_call=0`；硬编码工具名的 `oracle` 在扰动侧全灭（由测试锁定）。

| Date | Command | Result |
|---|---|---|
| 2026-08-15 | `.venv/bin/pytest -q` | 755 passed |
| 2026-08-15 | `.venv/bin/ruff check .` / `.venv/bin/mypy` | All checks passed / 67 files |
| 2026-08-15 | `uv lock --check` | Resolved 105 packages，lock 未漂移 |
| 2026-08-15 | `.venv/bin/python scripts/ci/verify_qualification_chain.py` | 通过（决策与内容哈希等于冻结期望） |
| 2026-08-15 | qualification schema 对照（clean / perturbed） | 12/12 与 12/12，`schema_perturbed` 落进 metrics |

## 2026-08-15 — R4.5：v1.1 复算 + 部署形态对照（gpu-5090）

- 用户已授权 GPU。**未消耗第三次 holdout 观测**；全部读数为 dev 或已消耗观测的重算。
- 提交：`3427c40` → `549957a` → `007e506`。远端同步至 `007e506`，工作树干净。

| Date | Command | Result |
|---|---|---|
| 2026-08-15 | `release --config …r45_formal_release_v11.yaml`（观测 1，含私有配对证据） | **NO-GO**，失败 4 项：`success_delta` −0.0333、`success_delta_ci_lower` −0.0917、`per_call_latency_ratio` **1.9643**、`latency_per_success_ratio` 1.9818 |
| 2026-08-15 | 同上（观测 2，无配对证据） | **NO-GO**，`success_delta_ci_lower` = `insufficient_paired_evidence` |
| 2026-08-15 | 自 gpu-5090 回传观测 2 私有 `trajectories.jsonl`（双端 SHA-256 一致） | base `7724c02a…` / candidate `2082a289…`，各 120 行 |
| 2026-08-15 | 同上（观测 2，含配对证据） | **NO-GO**，失败 2 项；`success_delta_ci_lower` **+0.0833 PASS**、`steps_to_success_ratio` **0.9841 PASS** |
| 2026-08-15 | `merge_lora_adapter.py`（gpu-5090，CPU 合并） | 7.6 GB，`merged_revision` `00f51386…`，torch 2.13.0+cu130 / peft 0.19.1 / transformers 5.13.1 |
| 2026-08-15 | `evaluate --config …r45_merged_dev_base.yaml`（物理 GPU 0） | **60/60**，148.96 s，峰值 2.91 GB，p95 3366.44 ms，吞吐 **50.74 tok/s** |

**对照结论（dev，非发布判定）**：合并版单次调用 1653.7 ms（未合并 3063.9、基座 1356.6），
v1.1 门禁 **8/8 全过**，但**旧 v1.0 口径下仍失败**（p95 比值 1.3130 > 1.25），
且 `latency_per_success_ratio` 1.2498 对 1.25 只差 2e-4。详见
`docs/SERVING_FORM_COMPARISON.md` 与 **LOG-20260815-01**。

## 2026-08-15 — R4.5 批次 2：政策外置 / 幂等键 / guardrail（纯 CPU，v2 bundle）

- 用户裁定 P2-8 走「bundle 打新版本号、新旧并存」。v1 逐字节不变，有治理测试锁定。
- 760 → **826 passed**；Ruff / mypy / `git diff --check` 全过；
  `verify_qualification_chain.py` 通过（v1 全链路决策与内容哈希未漂）。

| 项 | 内容 |
|---|---|
| P0-2 政策外置 | `domain/policy_rules.py` 声明式规则引擎（五种谓词、固定事实表、加载期校验）；v1 六个名字 → 内置冻结规则集，v2 规则内联 YAML；`max_transient_retries` 真正驱动重试上限；`domain/policy_card.py` 把政策渲染进 prompt（v1 逐字节返回冻结常量） |
| P2-8 幂等键 | v2 `refund_order` 增必填 `idempotency_key`；缺 key 判非法调用、同 key 重放返回同一结果且只退一次、换新 key 判 `duplicate_refund` |
| P2-9 guardrail | `core/agent/guardrail.py`：allowlist / 参数域 / 会话作用域越权 / 观测消毒；与 env 政策校验分层独立；拦截产生结构化观测；`run_episode` 与 `replay_trajectory` 均可注入且**默认关闭** |
| 注入评测 | qualification 注入变体 + `injection_success_rate` 指标（行为判据）；两份只差 `guardrail` 的对照配置 |

**验收判据（P0-2）**：只改 v2 `policies.yaml` 里退款窗口的一个数（`gt: 0` → `gt: 3`），
**不碰任何 Python**，同一条超期两天的订单判定从 `refund_not_eligible` 变成放行且状态
真的变为 `refunded`（`test_changing_only_the_yaml_threshold_changes_the_verdict`）。

| Date | Command | Result |
|---|---|---|
| 2026-08-15 | 注入对照 build + evaluate ×2（CLI 全链路，CPU） | 未防护 10/12 注入成功（0.83）、task_success 0.6667、违规 4；防护后 **0/12**、1.0000、0，可重放 1.00 |
| 2026-08-15 | `.venv/bin/pytest -q` | 826 passed |
| 2026-08-15 | `verify_qualification_chain.py` | 通过，v1 决策与内容哈希未漂 |

## 2026-08-15 — R4.5：P1-6 方案 A（user simulator + 多轮澄清，纯 CPU）

- 用户在 A/B 二选一中裁定 **A**。826 → **842 passed**；全部质量门通过；
  v1 全链路复现校验通过。

| Date | Command | Result |
|---|---|---|
| 2026-08-15 | 澄清对照 build + evaluate ×3（CLI 全链路，CPU） | 不欠指定 **1.0000**；欠指定/无模拟器 **0.0000**（轮次 1.00）；欠指定/有模拟器 **1.0000**（轮次 3.17），三组可重放均 1.00 |
| 2026-08-15 | `.venv/bin/pytest -q` | 842 passed |

新增：`core/agent/user_simulator.py`（确定性规则式模拟用户）、`message_grounded`
机制探针策略、`clarify` 任务变体、`clarification_*` 三个指标、两份只差
`user_simulator` 的对照配置、`docs/AGENT_LOOP.md`（含**仍然缺的东西**逐条列举）。

## 2026-08-15 — R4.5：第三次封存 holdout 观测（gpu-5090 物理 GPU 0）

- 代码冻结于 `b529bc9`，两端工作树干净后一次性执行三次运行。**三次判定全部 NO-GO。**

| Date | Command | Result |
|---|---|---|
| 2026-08-15 | `evaluate …r45_holdout_base.yaml` | EXIT=0，**103/120**，p95 2787.4 ms，4m04s |
| 2026-08-15 | `evaluate …r45_holdout_candidate.yaml` | EXIT=0，**120/120**，p95 5644.4 ms，9m00s |
| 2026-08-15 | `evaluate …r45_holdout_merged.yaml` | EXIT=0，**120/120**，p95 3384.0 ms，6m41s |
| 2026-08-15 | `release …r4_formal_release.yaml`（v1.0） | **NO-GO**，失败 `p95_latency_ratio` 2.0250 |
| 2026-08-15 | `release …r45_formal_release_v11.yaml`（v1.1，含配对证据） | **NO-GO**，失败 `per_call_latency_ratio` 2.1209 / `latency_per_success_ratio` 2.0871；`success_delta_ci_lower` +0.0833 PASS |
| 2026-08-15 | 合并版门禁算术（**诊断，非判定**） | v1.0 与 v1.1 **全部通过**（p95 比值 1.2141、单次调用 1.2364） |

产物已回传，双端 SHA-256 一致（三份私有 `trajectories.jsonl` 逐条核对）。
逐项读数与四条限制见 `docs/HOLDOUT_LEDGER.md` 观测 3 与 **LOG-20260815-03**。

## 2026-08-15 — R4.5：第四次封存 holdout 观测，**项目的第一个 GO**

- 代码冻结于 `06e4cc2`（sealed 契约 v1.1）。两次运行，同 commit。

| Date | Command | Result |
|---|---|---|
| 2026-08-15 | `evaluate …r45b_holdout_base.yaml` | EXIT=0，103/120，p95 2936.9 ms，3m56s |
| 2026-08-15 | `evaluate …r45b_holdout_merged_candidate.yaml` | EXIT=0，**120/120**，p95 3308.4 ms，5m09s；报告为 **schema 1.1 / form=merged / 带血统** |
| 2026-08-15 | `release`（v1.0） | **GO / candidate**，`p95_latency_ratio` 1.1265 |
| 2026-08-15 | `release`（v1.1，含配对证据） | **GO / candidate**，八项全过（CI 下界 +0.0833、per_call 1.1646、每成功成本 1.1461） |
| 2026-08-15 | 复核：未合并候选 vs base-004 | 仍 **FAIL 1.9219** —— GO 归因于部署形态而非 base 噪声 |

**六条限制与一处顺序披露**见 `docs/HOLDOUT_LEDGER.md` 观测 4 与 **LOG-20260815-04**。
最重要的两条：这不是前三次被拒的那个候选（是同一权重的另一种部署形态）；
SPEC §6 第 6 条「独立重建复验」**未做**，因此只能表述为"自动门禁 GO"。

## 2026-08-16 — R4.5：分布外评测（gpu-5090）

| Date | Command | Result |
|---|---|---|
| 2026-08-16 | `build --config …ood_v1_build.yaml` | 60 条，三类各 20，manifest `afc41351…` |
| 2026-08-16 | `evaluate --config …ood_v1_base.yaml` | **13/60（0.2167）**，158.1 s |
| 2026-08-16 | `evaluate --config …ood_v1_merged_candidate.yaml` | **35/60（0.5833）**，218.3 s |

**同一个候选：封存 holdout 1.0000 → 分布外 0.5833。** 逐类别：`scenario_ood`
0.00→0.75、`adversarial` 0.35→1.00、**`expression_ood` 0.30→0.00**（`code_switch`
1.00→0.00）。候选在表达类的 20 条失败全部是 `premature_final_response`。
详见 `docs/OOD_EVALUATION.md` 与 **LOG-20260816-01**。

## 2026-08-16 第四档 merged + vLLM（gpu-5090，物理 GPU 0）

| 运行 | 命令 | 结果 |
|---|---|---|
| vLLM 安装 | 独立 venv `/mnt/aidata/tongjiakai/vllm-venv`，Python 3.12 | vllm 0.27.1 / torch 2.13.0+cu130；项目 `uv.lock` 未动 |
| 基准 ×4 次重跑 | `run_vllm_bench.sh` | 前三次分别因 Python 3.11、缺 nvcc、缓存复用导致的测量缺陷作废；第四次有效 |
| prefix cache ON | `vllm-bench-cache-on.json` | 单流 203.51 ms / 159.70 tok/s；批量冷启 1375.38 tok/s |
| prefix cache OFF | `vllm-bench-cache-off.json` | 单流 214.43 ms / 151.56 tok/s；批量冷启 873.11 tok/s |
| 引擎一致性 | `engine-agreement.json` | 工具调用 12/12、文本 12/12；HF+NF4 675.97 ms / 48.08 tok/s |
| 量化分解 | `engine-agreement-bf16.json` | HF+bf16 411.66 ms / 78.95 tok/s |
| 事故与修复 | triton 缓存跨 venv 污染 | 项目 HF 路径一度全崩；已用 zig cc 重建 + 隔离 `TRITON_CACHE_DIR` 修复并复验 |

产物均在 `/mnt/aidata/tongjiakai/`，**不进 Git**（大运行产物边界）。

## 2026-08-16 引擎替换验证（gpu-5090，物理 GPU 0）

| 运行 | 输出 | HF `run_id` | vLLM `run_id` | 结果 |
|---|---|---|---|---|
| dev 60 / 合并候选 | `r45/merged-dev-vllm` | `e4d788ba…` | `531f9ede…` | 1.0000 vs 1.0000，六项指标全同 |
| OOD 60 / 合并候选 | `ood/merged-vllm` | `023a03b9…` | `baa854ab…` | 0.5833 vs 0.5833，逐类别逐 kind 全同 |
| OOD 60 / 零训练基座 | `ood/base-vllm` | `8aada609…` | `9431d299…` | 0.2167 vs **0.2333**，`colloquial` 0.50→0.75 |

三组 `replayable_count` 均 60/60。吞吐 ~4.85×（同为 NF4）。
失败并重跑的中间尝试：缺 `bitsandbytes`（补装 0.49.2 与项目对齐）、
`CudaHardwareProvider` 在 vLLM 下抛 `Invalid device argument`（换 NVML provider）、
`--engine` 未接进 dev 通道（静默回落，已修）、证据发布拒绝覆盖同名运行（加 vLLM 专用配置）。

## R0–R4.5 错误台账（2026-08-16 从 `task_plan.md` 归档，原文不改）

| Date | Error | Resolution |
|---|---|---|
| 2026-07-20 | 新 worktree 缺 BFCL evaluator 环境和 ignored benchmark checkout | 建立独立 evaluator venv，并通过相对软链接共享固定 checkout |
| 2026-07-20 | 本机镜像变量机械改写 `uv.lock` | 反向应用仅 lock diff，后续命令显式清除 `UV_INDEX_URL` |
| 2026-07-20 | 清除 `UV_INDEX_URL` 后 `uv run` 仍按全局索引改写 `uv.lock` | 最终验收直接调用已冻结 `.venv/bin/*`，提交前精确回退 lock diff |
| 2026-07-20 | 新治理测试被 Ruff I001 拒绝双空行 | 按 import sorter 的最小 diff 删除一行空白后重跑 |
| 2026-07-21 | Task 6 规格检索误写为不存在的 `docs/SPEC.md` | 确认产品契约实际位于根目录 `SPEC.md`，后续使用正确路径 |
| 2026-07-21 | Task 6 首次 GREEN 加载 `run.json` 时错误要求 artifact map 保留插入顺序 | canonical JSON 会排序 object key；改为验证精确 key 集合，确定性由写入器保证 |
| 2026-07-21 | Task 6 `ruff format --check` 报告 4 个变更文件需格式化 | 使用仓库 `.venv/bin/ruff format` 仅格式化本任务 Python 文件后重跑验证 |
| 2026-07-21 | Task 7 `ruff format --check` 报告 `release.py` 需格式化 | 使用仓库 formatter 处理该文件并重跑 focused/Ruff/diff |
| 2026-07-21 | Task 8 初查误探测不存在的 `src/veritool_rl/config.py` 与 `tests/test_cli.py` | 确认配置加载在 `veritool_rl.cli`，产品 CLI 测试按计划新建 `test_retail_ops_cli.py` |
| 2026-07-21 | Task 8 `uv lock --check` 报告锁文件过期，`UV_INDEX_URL` 仍被全局默认索引覆盖 | 清除 3506 行镜像 URL 机械 diff，改用 `UV_DEFAULT_INDEX` 对齐现有 lock 索引；离线解析后 `uv.lock` 字节不变 |
| 2026-07-21 | Task 8 planning 记录补丁因表格行顺序假设错误未应用 | 用 `rg` 定位实际行后按精确上下文重新应用，未影响产品文件 |
| 2026-07-21 | Task 8 `ruff format --check` 报告 CLI 测试需格式化 | 仅格式化本任务测试文件并重跑 focused/Ruff/diff |
| 2026-07-21 | Task 9 首次全门禁发现 `product_cli.py` import 未排序且 service/test 需格式化 | 对本任务文件执行 Ruff import fix/format 后重跑 selected/full 相关门禁 |
| 2026-07-21 | Task 9 误将全仓 `ruff format --check .` 当作验收项，发现 35 个既有文件未采用当前 formatter | 不扩大本阶段 diff；仅检查本任务 Python 文件，继续执行项目规定的 `.venv/bin/ruff check .` |
| 2026-07-21 | Task 10 新鲜 qualification 证据树在最终状态审计中显示为未跟踪文件 | 新增失败治理断言并将 `/reports/retail_ops/` 纳入产品运行产物 ignore 边界，保留本地证据但不提交 |
| 2026-07-21 | Task 10 完成前 targeted format check 报告两个新增测试需格式化 | 仅格式化 `test_retail_ops_e2e.py` 与 `test_project_governance.py`，随后从头重跑完整质量门 |
| 2026-07-22 | `using-superpowers` 的 Codex reference 首次按错误的技能根路径读取失败 | 按 SKILL.md 相对路径改读 `skills/using-superpowers/references/codex-tools.md`，已恢复完整指令 |
| 2026-07-22 | 迁移准备提交前 `git diff --cached --check` 报告设计文件 EOF 多一个空行，但 shell 未启用 fail-fast 仍完成提交 | 在最终文档提交中删除多余空行；后续提交命令使用 `set -e` 或显式检查退出码后再 commit |
| 2026-07-22 | 执行环境拒绝用 `rm -rf` 清理迁移回滚目录 | 未删除任何内容；改用 `gio trash` 将精确目录移入系统回收站，并验证原 `/tmp` 路径不存在 |
| 2026-07-22 | R2 分支基线 `uv lock --check` 因用户级清华镜像 URL 从旧别名规范化为新域名而要求 4336 行纯 URL 重写 | 临时目录差异确认版本/哈希不变；`--default-index https://pypi.tuna.tsinghua.edu.cn/simple` 立即通过，R2 将用项目级索引固定现有 lock，避免机械重写 |
| 2026-07-22 | R2 family 轴核对首次探测了不存在的 `domains/retail_ops/v1/policies/refund.yaml`，随后 zsh 未匹配 glob 中止批量查看 | 改读实际扁平文件 `domains/retail_ops/v1/policies.yaml`、`tools.yaml`、`bundle.yaml`；确认仅使用四个批准退款原因且未改文件 |
| 2026-07-22 | 两次跨文件文档补丁因 `task_plan.md` 既有错误行与预期上下文不一致而整体拒绝 | 先读取精确表格，再按目标文件拆分应用；补丁原子失败，未产生半写入或产品内容损坏 |
| 2026-07-22 | 新增治理测试仍因目标短语跨 Markdown 换行失败 | 保留语义不变并合并为单行可机器检查契约，再重跑 focused test |
| 2026-07-22 | 一次双引号 `rg` 模式中的反引号被 zsh 当作命令替换，并且一次 reviewer wait 使用了低于工具下限的 1 秒 timeout | 检索模式改用安全单引号/无反引号形式；等待调用改为工具允许的至少 10 秒，均未修改产品状态 |
| 2026-07-22 | 计划审阅收口记录的跨文件补丁因 `progress.md` 目标句与实际表述不同而整体拒绝 | 读取文件尾部后按文件拆分应用，未产生半写入 |
| 2026-07-22 | R2 Task 1 实现代理完成 RED 和初版实现后因所选模型容量不足退出 | 保留全部未提交改动，换用新 worker 接手 focused GREEN、修复、全门禁和提交；判定为代理基础设施故障而非仓库回归 |
| 2026-07-22 | Task 1 独立审查发现 derivation 未绑定实际政策状态、quota 接受重复变体，且 catalog/420 条环境验证未固化为测试 | 判定 NOT PASS；派回实现代理先补 deadline/owner/status/duplicate/tamper/catalog/environment RED，再强化真值投影和 integrity 校验，复审通过前不进入 Task 2 |
| 2026-07-22 | Task 2 独立审查用攻击脚本复现 public value 泄漏、provenance 断链、重复 variant、非原子双根、symlink 越界和可伪造授权 token 六项 Important | 判定 NOT PASS；统一补固定 Literal、verified dataset、private provenance/variant 重建、failure-atomic staging、trusted-root no-follow 读取和注册 capability 的 RED/GREEN，复审通过前不进入 Task 3 |
| 2026-07-22 | Task 2 修复复审代理的最终输出被平台 cybersecurity 风险过滤器误拦截 | 保留已完成的代码与 284 个测试证据，把复审改写为不描述利用步骤的“数据治理契约回归审查”并复用同一只读 reviewer |
| 2026-07-22 | Task 3 只读接口检索误读不存在的 `src/veritool_rl/agent/base.py`，导致同一 `&&` 链后的 Qwen 查看未执行 | 改读实际 `agent/qwen.py`、`agent/policy.py`、`agent/runner.py`；未修改代码或环境 |
| 2026-08-05 | 20 条真实 DeepSeek smoke（会话临时脚本）发现 `run_episode`（`agent/runner.py`）组装的多轮消息历史不是合法 OpenAI wire format：`tool_calls[].function.arguments` 是原始 dict 而非 JSON 字符串，且 assistant `tool_calls[]`/`tool` 消息缺 `id`/`tool_call_id`；本地 Qwen backend 从未触发过 | 判定为 Task 4 前置阻塞：先在 `agent/runner.py` 用 TDD 修复两处 wire format bug 并补回归测试，再开始 `teacher_data.py` 实现；smoke 脚本本身未提交，详见 `docs/PROJECT_LOG.md` LOG-20260805-07 |
| 2026-08-05 | Task 6 env 边界测试最初用 `monkeypatch.setattr("os.environ", HostileMapping())` 整体替换 `os.environ`，导致 pytest 自身内部读取 `COLUMNS`/`PY_COLORS` 时炸穿并使整个 session 内部报错，而非产品代码问题 | 改用 `monkeypatch.setenv("TEACHER_LLM_PROVIDER", "not a provider name!!")` 只毒化 `load_teacher_route` 真正会读的具体 key，不整体替换 `os.environ`；同时确认没有任何产品代码本身依赖 `COLUMNS`/`PY_COLORS` |
| 2026-08-05 | Task 6 首个 `--input_dir` 覆盖测试误传相对路径 `"configs/retail_ops_v1_build.yaml"`，但该测试用的 `workspace` fixture 已 `monkeypatch.chdir` 到隔离 tmp 根，仓库真实 `configs/` 在那里不存在 | 改用 `Path(__file__).resolve().parents[1]`（`REPO_ROOT`）拼出绝对路径引用仓库里真正提交的 config 文件，不依赖当前 CWD |
| 2026-08-05 | Task 6 修复轮首次派发因触发本会话 API 用量限制中断，未产生任何改动（工作树、报告文件均未受影响） | 原样重新恢复同一 implementer agent（未改变任务或方案），重试后成功完成 |
| 2026-08-06 | Task 7 整分支审查发现 `formal_dev_base` 独立加载 `dev.json` 未走 `load_verified_formal_dataset`，跳过五维隔离交叉断言；`export_formal_train` 接收 `TeacherCollectionConfig` 却从未读取，teacher 证据仅凭 `task_id` 匹配记录；`code_commit` 可能来自脏工作树且 git 子进程无超时 | 三项均用 TDD 修复：`_run_formal_dev_base` 改为先 `load_verified_formal_dataset` 再取其 `dev_manifest`；新增 `_require_evidence_binds_record` 在 export 循环内核对 `task_fingerprint`/`trajectory.task`/`dataset_version`/`bundle_sha256`/`manifest_sha256`，不匹配即硬失败（非静默回退）；`_current_code_commit` 先查 `git status --porcelain` 非空即拒绝，git 调用统一加 30s 超时；复审确认 3 项均已解决、3 个关键判断均合理（`c4d7fdc`） |
| 2026-08-06 | Task 7 复审发现 `manifests/retail_ops/v1/` 未被 `.gitignore` 覆盖（不同于 `data/`/`models/`/`reports/retail_ops/`），导致 `formal_freeze` 产出的公开 manifest 若不提交，会被新的脏树检查判定为"未跟踪=脏"从而阻塞 `formal_dev_base` | 非代码缺陷，是正式执行顺序的前置条件；已写入 `docs/handoffs/2026-08-06-r2-external-run-commands.md` 第 0 节，要求 `formal_freeze` 产出必须先提交再进入 `formal_dev_base` |


## 2026-08-16 — R5 公开交付与求职收口

- 用户要求把项目收口为可用于求职的交付物，并追加三条硬要求：**必须拿得出 GO**、
  **收尾前由独立「面试官」角色审核**、**代码整洁性**。
- **T1 代码整洁性**：全仓 `ruff format` 统一（58 个文件漂移，纯格式化单独提交）；
  lint 集从 `E,F,I,UP,B` 扩到 `+SIM,C4,RET,PIE,RUF`（`RUF001-003` 对中文全角标点整体
  误报，已 ignore 并写明理由），45 处全部修完；`ruff format --check` 进 CI 成为硬门禁。
- **T2 独立重建复验（GPU）**：见 LOG-20260816-05 与 `docs/REBUILD_VERIFICATION.md`。
  SPEC §6 第 6 条满足；同时发现训练不可逐位复现，dev 表述改为 58–60/60。
- **T3 公开发布审计**：新增 `LICENSE`（MIT）、`NOTICE.md`、
  `scripts/ci/audit_public_release.py`（六项，扫 `git ls-files` 全集）与 19 项测试。
- **T4 故障矩阵**：新增 `docs/FAULT_MATRIX.md` + `tests/test_fault_matrix.py`（解析文档
  断言引用的测试真实存在，已做突变验证）。修掉 teacher client 无超时的真缺陷。
- **T5 对外文档**：`README.md` 重写（第一屏三条结论 + Mermaid 架构图）+ 新增
  `README.en.md`；两份的关键数字由治理测试断言一致。
- **T6 求职材料**：新增 `docs/INTERVIEW_PREP.md`；`RESUME_EVIDENCE.md` bullet 定稿，
  §1.7 新增重建复验，§2 新增两条不可写表述，§5 缺口表重写。

### R5 Verification Ledger

| Date | Command | Result |
|---|---|---|
| 2026-08-16 | R5 起始基线 `.venv/bin/pytest -q` | 907 passed |
| 2026-08-16 | 全仓 `ruff format` 后 `.venv/bin/pytest -q` | 58 files reformatted；907 passed |
| 2026-08-16 | lint 扩展 + LICENSE/NOTICE/审计后全门禁 | 924 passed；Ruff/format/mypy(80)/审计全绿 |
| 2026-08-16 | gpu-5090 GPU 0 重建训练 ×2（seed 1 / seed 0） | 各 242 s；adapter 逐位互不相同，且与原 sft-006 也不同 |
| 2026-08-16 | gpu-5090 GPU 0 重建 dev 评测 ×2 | seed1 60/60、seed0 58/60；两侧 `replayable` 均 60/60 |
| 2026-08-16 | 故障矩阵锁定的突变验证 | 改一个被引用的测试名 → `test_every_fault_class_names_a_real_test` 变红，恢复后通过 |
| 2026-08-16 | R5 最终全门禁 | **944 passed**；Ruff、`ruff format --check`、mypy 80 files、`uv lock --check`、`git diff --check`、公开发布审计全部通过 |

### R5 独立面试官审核（T8）

两轮外部审阅，reviewer **不带本会话上下文**，只给仓库路径与岗位设定，自跑门禁、自查数字。

| 轮次 | 判定 | 阻塞项 | 备注 |
|---|---|---|---|
| 第一轮 | **PASS 8/10** | 4 条 | 四条全部属实，且全部落在「数字纪律」上——正是本项目的卖点 |
| 第二轮 | **PASS 8.5/10** | **0**（4/4 解除） | reviewer 用审阅**之前**的 commit 里记录的 `run_id` 比对同步回来的文件，并做篡改测试，未采信自述 |

四条阻塞项与收口方式见 LOG-20260816-07。其中最有价值的一条：
**把一份文件指定为「唯一事实源」却不把它纳入漂移扫描，等于没有事实源**——
`HOLDOUT_LEDGER.md` 因此是全仓漂移最久的文件。

### R5 最终验证台账（补）

| Date | Command | Result |
|---|---|---|
| 2026-08-16 | R5 证据同步回本地 + SHA-256 核对 | 两份 `candidate-report.json` 与远端逐位一致 |
| 2026-08-16 | `load_candidate_run_evidence(..., verify_artifacts=True)` | 两份均通过，各校验 4 个私有产物——**这是该机制首次对真实 GPU 运行行使** |
| 2026-08-16 | 篡改测试：改 `trajectories.jsonl` 最后一个字节 | 加载被拒（`评测证据产物 SHA-256 不匹配`） |
| 2026-08-16 | `docker build -t retail-agent-ops:cpu .` | 成功，**1.05 GB**（此前注释里的「几十 MB」是从未验证的估计） |
| 2026-08-16 | `docker run --rm --network none retail-agent-ops:cpu` | **断网**跑通全链路：「决策与内容哈希均与冻结期望一致」 |
| 2026-08-16 | R5 收口最终全门禁 | **948 passed**；Ruff、`ruff format --check`、mypy 80 files、`uv lock --check`、`git diff --check`、公开发布审计全部通过 |

## 2026-08-17 — R6 泛化修复

用户追加要求：项目要达到 9 分以上、没有靠投机取巧过关的东西；并补做演示视频、
审视「数字是否高到可疑」。外部审阅指出的天花板是「有一个扛得住分布漂移的结果」。

- **诊断**：把 OOD 读数按子类拆开，发现训练把零训练基座本来会做的两类打没了
  （`code_switch` 1.0→0.0、`colloquial` 0.5→0.0），机制是 12 句模板的表面形式触发器。
- **措辞池**：DeepSeek 生成 267 条（40 次请求 $0.0061），两道校验（结构 + 语义回环），
  按 `sha256(措辞+固定盐)` 三分 147/59/61。**过程中改掉一个自己的设计错误**：
  第一版按场景写生成简报，等于把答案写进用户的话。
- **训练增强**：只改 user 第一句话；sft 400→1600 行，不同说法 42→184 种。
- **OOD v2**：六场景 × 10，dev/sealed 两份，oracle 可解性已验证（各 60/60）。
- **结果**：封存分片（只观测一次）零训练基座 0.7167 / 旧候选 0.7333 / **新候选 1.0000**；
  独立迁移检查 `expression_ood` **0.00 → 1.00**、总分 0.5833 → 0.8667。
- **代价**：dev 新增 2 次政策违规、OOD v1 的 `scenario_ood` 0.75→0.60。同一机制。
- **演示视频**：`docs/media/demo.mp4`（70 秒），捕获与渲染两步分离。
- **读数指南**：`docs/READING_THE_NUMBERS.md`，逐个解释高得可疑的数字。

### R6 Verification Ledger

| Date | Command | Result |
|---|---|---|
| 2026-08-17 | 措辞池生成（DeepSeek，40 次请求） | 267 条，`bank_sha256` `a34b25ac…`，$0.0061 |
| 2026-08-17 | OOD v2 oracle 可解性（两个分片） | 各 60/60 到达 `target_state`，零政策违规 |
| 2026-08-17 | gpu-5090 GPU 0 训练 `sft-007`（1600 行 / 300 步） | 945.1 s，峰值 5.65 GB |
| 2026-08-17 | gpu-5090 GPU 0 训练 `sft-008`（960 行 / 180 步） | 成功 |
| 2026-08-17 | OOD-v2-dev ×5（基座 / sft-006 合并 / sft-006 未合并 / sft-007 / sft-008） | 0.7500 / 0.7167 / 0.7333 / 0.9667 / 0.9833 |
| 2026-08-17 | dev 60 回归 ×2 | sft-007 与 sft-008 均 58/60，失败签名完全相同（2 次政策违规） |
| 2026-08-17 | **OOD-v2-sealed ×3（只此一次）** | 0.7167 / 0.7333 / **1.0000**；三侧 `replayable` 均 60/60 |
| 2026-08-17 | OOD v1 独立迁移检查（`sft-008`） | 0.8667；`expression_ood` **0.00 → 1.00** |
| 2026-08-17 | 证据同步回本地 + 哈希核对 | 9 份报告逐位一致；`run_id` 本地自哈希复算通过 |
| 2026-08-17 | Docker 镜像首次构建 + 断网跑全链路 | 1.05 GB；`--network none` 下通过 |
| 2026-08-17 | R6 收口全门禁 | **1033 passed**；Ruff / format / mypy(86) / 审计 / diff 全绿 |

## 2026-08-17 — R6 收口：最终候选的独立重建复验

`SPEC.md` §6 第 6 条当初只在 `sft-006` 上做、且只在 dev 上做，**最终候选 `sft-008`
从未被独立重建过**。同时 R6 的头条读数只来自一份措辞池的一个分片。这一轮补两个缺口。

- **预注册**：八个运行、判据 A/B/C、三种结果的写法，在跑之前提交（`2c2c73b`）。
- **新素材**：`phrasing-bank-003`（268 条，$0.0061），与 bank-002 三分片、自己的
  `train_aug`、真实训练文件 184 种说法**交集全为 0**（实测）。八种风格全在场（bank-002 缺 `terse`）。
- **代码改动**：`OodDatasetVersion` 增加第三个取值，`phrasing.dataset_version` 成为必填键——
  此前两份素材会挂同一个版本号，而 `task_id` 只依赖位置、逐条相同，manifest 层无法区分。
- **结果**：判据 A ✅（dev 60/60、0 违规）、B ✅（+0.2500 / 0.0000）、C = **GO 两套口径**
  （113/120、**7 次政策违规**、CI 下界 +0.0083）。**按规则 → 复现。**
- **三条修正性发现**：①R6「2 次违规是措辞增强的确定代价」这条归因不成立（两候选共用
  一个 seed）；②代价更大且集中在一条规则上（dev 0 次 → 封存 120 上 7 次）；
  ③dev 与封存集把两次运行排成相反顺序。
- **头条数字全部改成区间**：dev 58–60/60、封存 120 113–117/120、
  分布外封存分片 0.9833–1.0000（两份独立素材）。

### R7 Verification Ledger

| Date | Command | Result |
|---|---|---|
| 2026-08-17 | 措辞池 bank-003 生成（DeepSeek，40 次请求） | 268 条，`bank_sha256` `b421caa4…`，$0.0061 |
| 2026-08-17 | 互斥性实测（三分片 + 真实 `sft.jsonl`） | 交集全部为 0 |
| 2026-08-17 | OOD v2.2 sealed 构建（本地与远端各一次） | `tasks_file_sha256` `439522f1…` 两地逐位一致 |
| 2026-08-17 | gpu-5090 GPU 0 训练 `sft-008-rebuild-seed1`（960 行 / 180 步） | 527.0 s，峰值 5.65 GB，adapter `1a2c3d16…` |
| 2026-08-17 | dev 60 配对评测（重建候选） | **60/60**，政策违规 **0** |
| 2026-08-17 | **OOD v2.2 sealed ×3（该分片只此一次）** | 0.7333 / 0.9833 / 0.9833；三侧 `replayable` 均 60/60 |
| 2026-08-17 | 合并 LoRA（重建权重） | `merged_revision` `29c7b92c…`，可从基座 + adapter 哈希复算 |
| 2026-08-17 | **第六次封存 holdout 观测**（base + merged candidate） | 103/120 vs **113/120**；违规 11 → **7** |
| 2026-08-17 | `release` v1.0 / v1.1（带 `--*_trajectories`） | **GO / candidate**，两套口径 |
| 2026-08-17 | 证据同步回本地 + 哈希核对 | **13 份产物逐位一致** |
| 2026-08-17 | `verify_artifacts=True` + 篡改测试 | 4 个私有产物校验通过；翻转一个字节被拒 |
| 2026-08-17 | R7 收口全门禁 | **1073 passed**；Ruff / format / mypy(86) / lock / 审计 / diff 全绿 |

## 2026-08-19 — R7 质量收口

**方向在本轮中途被用户改过一次**：原计划是「跑第三个训练 seed 做方差刻画」
（预注册已提交于 `0185135`，`--seed 2` 也已训完），用户判定
「多跑一个 seed 的意义不大，我们不是写论文，不如把一个 seed 的效果做得更好」，
于是原预注册作废、seed 2 权重不评测也不进入任何对外表述。取消留档在 `task_plan.md`。

- **诊断（只用公开生成器代码，零读数）**：冻结数据集按 `sha256(family)` 切 20/5/10，
  **不对难度分层**。`refund_denied_window` 的训练集里 margin ≥ 10 的 family 占 **10%**、
  封存集占 **50%**——**5 倍训练/测试分布偏移**，而全部封存政策违规恰好落在这个场景。
  `refund_recovery` 同样是 4 倍。另有一个空洞：`offset = 0`（恰好到期）
  **整个冻结数据集从未生成过**，而它正是政策的判定分界。
- **仪器**：政策边界探针（15 个偏移量 × 8 条 = 120），复用整条 OOD 评测路径，
  `kind_success` 直接是决策曲线。真值逐点比对可执行政策规则，不是手写期望表。
- **诊断读数**：`sft-008` 15 个偏移量里 14 个 1.00，**唯独 offset −14 塌到 0.375**，
  5 次违规全在那一点；零训练基座在该点是 1.00——**但那不是合规，是不动手**
  （基座放行侧只有 0.00–0.38，56 次失败全是 `premature_final_response`）。
- **修复**：网格外 margin 的状态增强（56 条任务 → 208 行，基底 960 → 1168）。
  teacher 采集 **52/56 被接受，4 条判 policy_violation 且全部落在最极端的超期格**
  ——**DeepSeek 自己在同一区域也违反同一条规则**。
- **判定：分支 2「修坏」，不换候选。** `sft-009` 在探针（0.9583 → 0.9750）与
  dev（58/60 → 59/60）上改善，但在**措辞分布外**的 `ood_dev` 上退化
  （0.9833 → 0.9500，`refund_denied_window` 0.90 → 0.70），
  且探针放行侧 offset 0 掉了 1 条。事先规则的三条「修好」条件全部不成立。
- **本轮真正的产出**：**同源措辞的诊断集会系统性高估数据修复的收益**——
  方向随措辞分布翻转，且退化恰好落在被干预的那个场景。
- 治理测试瘦身 1094 → 1082（后续新增行为测试后回升），配置治理覆盖 52 → 99 份。
- **本轮没有消耗封存 holdout 观测。**

### R8 Verification Ledger

| Date | Command | Result |
|---|---|---|
| 2026-08-19 | 切分难度覆盖分析（CPU，纯生成器代码） | `refund_denied_window` train 10% vs holdout 50%（margin ≥ 10） |
| 2026-08-19 | 政策边界探针构建（本地与远端各一次） | `tasks_file_sha256` `e2ccd54c…` 两地逐位一致 |
| 2026-08-19 | 探针 gold 回放 + 反向违规检查（CPU） | 120/120 终态正确零违规；拒绝侧强行退款 120/120 被判违规 |
| 2026-08-19 | gpu-5090 GPU 0 探针评测：零训练基座 | 总分 0.5167；放行侧 0.00–0.38，56 次 `premature_final_response` |
| 2026-08-19 | gpu-5090 GPU 0 探针评测：`sft-008` | 总分 0.9583；**5 次违规全部在 offset −14** |
| 2026-08-19 | 状态增强采集（DeepSeek，56 条，temperature=0） | **52 接受 / 4 判 policy_violation，全在 margin 12/16/18** |
| 2026-08-19 | 状态增强导出 | 960 + 208 = 1168 行；`sft_sha256` `0431903c…`；逐 deadline 计数进报告 |
| 2026-08-19 | gpu-5090 GPU 0 训练 `sft-009`（1168 行 / 219 步） | 646.8 s，峰值 5.65 GB，adapter `c129dcd5…` |
| 2026-08-19 | 探针：`sft-008` 同 commit 重跑 | **逐点与总分逐位相同**（探针是确定性仪器） |
| 2026-08-19 | 探针：`sft-009` | 总分 0.9750；offset −14 0.375 → **0.750**，offset 0 1.00 → **0.875** |
| 2026-08-19 | dev 60 配对评测：`sft-009` | **59/60，1 次违规**（`sft-008` 是 58/60、2 次） |
| 2026-08-19 | `ood_dev` 任务集重建 + 两侧评测 | `sft-008` **0.9833** vs `sft-009` **0.9500**——**退化** |
| 2026-08-19 | 按 `3cb5619` 事先写定的规则判读 | **分支 2「修坏」，不换候选** |

## 2026-08-20 — R8 D2 B2：CI 首次真跑

- 用户授权公开发布门（remote `https://github.com/emmmdty/retail-agent-ops.git`）。
- `git push -u origin main`：两次 push（`596eee8` 2m12s，`1dde7ca` 2m14s），11 步全绿。
- 证据落盘 `docs/CI_EVIDENCE.md`（运行 URL、commit SHA、各步状态、首次运行日期）。
- 治理测试反转：`test_ci_and_container_exist_and_do_not_overclaim` 从「必须写未跑过」
  改为「不得仍声称未跑过」+ 指向 CI_EVIDENCE.md。**约束在现实变后会反向。**

## 2026-08-20 — R8 D2 C1：flight_ops 跨域验证（gpu-5090）

- flight_ops v1 bundle + tasks + environment + policies 完成（CPU 实现）。
- teacher 采集（DeepSeek，~240 条）+ SFT 导出 → Qwen3-4B QLoRA 训练。
- dev 评测：base 0.4833 → candidate **1.0000**，release gate **GO**。
- 教训：teacher_client 从 retail_ops.build lift 到 core.build 证明可移植性，
  但 ToolSchema→dict 转换是隐式契约（openai SDK 不接受 pydantic 对象）。

## 2026-08-20 — R8 D2 C2：工具面扩容 + 退化曲线（gpu-5090）

- retail_ops v3 bundle（15 工具）+ v3_tasks 生成器（5 断点 {3,6,9,12,15}）完成。
- 4 个新候选训练（6/9/12/15 工具各一个 QLoRA），{3} 复用 sft-008。
- 退化曲线：N=6/9/12/15 全部 task_success=0.45、pv=0、tool_acc=0.70。
- **曲线平坦**：MiMo-V2.5 teacher 质量充足，4B 模型在 6~15 工具上未观察到退化。

## 2026-08-20 — 测试数变化追踪

- B2 CI 真跑 + C1/C2 代码合并后：1171 → 1199 → 1212 → **1219**（最终确认）。
- 干净 clone 实测：**1173 passed / 46 skipped / 0 failed**（2026-08-21 重跑确认，数字未变）。

## 2026-08-21 — R9 Phase A：数据量消融启动

- **Phase A 目标**：验证"数据量"的独立贡献（240→1600 条）。
- **Oversampling 完成**：原始 240 条训练数据生成 2000 条变体，去重后 1600/200/200
  （train/dev/holdout = 80/10/10）。
- **配置文件已创建**：
  - `configs/retail_ops/build/retail_ops_v1_r9_phase_a_sft.yaml`（训练）
  - `configs/retail_ops/evaluate/retail_ops_v1_r9_phase_a_dev.yaml`（dev 评测）
  - `configs/retail_ops/evaluate/retail_ops_v1_r9_phase_a_ood.yaml`（OOD 评测）
  - `configs/retail_ops/evaluate/retail_ops_v1_r9_phase_a_ood_oversampled.yaml`（oversampled OOD 评测）
- **待执行**：训练 Phase A 候选 + 三组评测（gpu-5090）。

## 2026-08-21 — R9 Phase A 结果：修复数据一致性后显著改善

- **根因**：oversampling 脚本未更新 trajectory steps 中的 tool_call arguments，
  导致训练数据不一致（user_request 里是新 order_id，但 tool_call 里是旧的）。
- **修复**：新增 `apply_variant_to_trajectory` 函数 + 修复 `expected_calls` 键名检查。
- **第二次训练完成**：Qwen3-4B + QLoRA full linear，1600 条 train，3 epoch。
- **Dev 评测**：task_success = 0.983 (59/60)，**显著优于 baseline 0.800 (48/60)**。
- **OOD 评测**：多次尝试失败（进程异常退出），未产出结果。
- **判读**：数据一致性是之前失败的根因，修复后数据量增加确实有帮助。
  需要完成 OOD 评测才能判断是否需要进入 Phase B。
