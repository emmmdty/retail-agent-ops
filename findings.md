# Findings: RetailAgentOps

## Stable Facts

- 产品定位已经从研究型 VeriTool-RL 改为工程型 RetailAgentOps。
- 当前 Python 包名仍为 `veritool_rl`；产品改名不等于代码包已改名。
- 现有 MiniRetail 和 BFCL 能支撑流水线起点，但不能证明真实生产价值。
- BFCL Base/SFT 的 +2 个百分点置信区间跨 0，不能写成稳定提升。
- 固定 200 条 holdout 是硬隔离边界，不能用于后续优化。
- 默认单卡 4090、一个开发训练 seed；最终简历数字才做一次独立重建。
- 最值得优先验证的是数据执行质量、parser/模板、政策 verifier 和发布门禁，不是 GRPO。

## Current Initialization Findings

- 隔离 worktree 基线为 107 tests passed，Ruff 与 mypy 通过。
- BFCL evaluator 使用独立 `tools/bfcl_eval/.venv`，避免依赖污染。
- benchmark checkout 通过 ignored 软链接共享，Git 历史和原工作区保持不变。
- 项目治理测试 5 项已通过，活跃文档不再把论文、多 seed 或 GRPO 设为默认交付。
- 本机 uv 还受到 `UV_INDEX_URL` 之外的索引配置影响；冻结环境可直接用 `.venv/bin/*` 验收而不改 lockfile。

## Open Questions

- R1 开始前需要用户确认内部 RetailOps v1 任务契约和冻结 holdout 生成规则。
- Qwen3-4B 下载、单卡 smoke 和 API 教师模型选择均不属于 R0。

## R1 Decision Preparation

- R1 的最小闭环已经固定为 `build -> evaluate -> release -> serve`，且本阶段不进行正式训练。
- RetailOps 内部任务必须以最终状态、政策违规、非法工具调用和参数错误为主判据；语言质量不能替代执行真值。
- 固定 BFCL 200 条及其失败样例只能用于窄口径外部回归，不能作为 RetailOps v1 的开发数据或内部 holdout。
- 在用户选择任务契约与冻结规则之前，`docs/EXECUTION_PLAN.md` 的 R1 状态保持“待执行”；该前置条件已由方案 A 选择解除。
- 当前分支为 `portfolio/retail-agent-ops-init`，HEAD 为 `5e25bd7`；核对时除本轮治理记录外没有其他未提交改动。
- `SPEC.md` 已冻结稳定入口、主指标和默认发布门槛，但尚未冻结 RetailOps v1 的具体工具 schema、任务规模、政策条款和内部 holdout 生成算法。
- 当前受版本控制资产以 MiniRetail、BFCL 和通用 trajectory/evaluator 为主，尚无正式 domain bundle、release policy 或 serve 模块。
- MiniRetail 当前包含 `get_order`、`refund_order` 两个业务工具，4 类任务和 4 条退款约束；schema 扰动另加一个门店营业时间干扰工具。
- MiniRetail 默认切分为 128/32/32，但按 split/seed 动态生成，当前没有独立 RetailOps holdout manifest、内容哈希或禁止开发读取的加载边界。
- `TaskSpec` 内嵌 `target_state` 与 `expected_calls`，现有 `Evaluator` 还会把完整任务随 trajectory 写入产物；仅做 ID 互斥不足以防止 holdout 答案进入开发分析。
- 当前 `cli.py` 只提供通用参数解析与配置加载，尚未实现产品要求的 `build/evaluate/release/serve` 命令面。
- 现有评测已支持顺序执行、replay、确定性指标和 base/adapter 配对，但缺 run manifest、证据完整率、p95 延迟、版本化门禁和 HTML/Markdown 发布报告。
- `pyproject.toml` 尚无 FastAPI/服务依赖或产品命令 entry point，项目描述仍保留旧研究定位文本。
- 现有 `mvp_eval_*` 配置只声明 `environment: mini_retail` 与 `split: test`，未绑定 task manifest、bundle/policy 版本或哈希。
- `scripts/evaluate.py` 按运行 seed 重新生成评测任务；`scripts/build_trajectories.py` 将 test 的完整 task/trajectory 写入普通输出目录，且 manifest 只哈希 trajectory 文件，不能充当 sealed holdout。
- R1 的 holdout 执行入口应只消费冻结 manifest，开发可见 evidence 不应默认包含 `target_state`、`expected_calls` 或原始失败样例。
- 当前 BFCL 200 条 manifest 的 SHA-256 已复核为 `a74a3748d3af289e8d3f808930b99b6eb5cb9c7d84ba678ff627c762e9448da9`；RetailOps 两案均不修改或复用该集合。
- R1 应只用 qualification fixture 验证契约与门禁；正式 RetailOps train/dev/holdout 数据及 manifest 按批准配额留到 R2 冻结。
- 用户已选择方案 A：RetailOps v1 采用 2 个正式业务工具、6 类任务、R1 qualification 12 条，R2 目标配额 train/dev/holdout 为 `240/60/120`。
- 方案 A 的正确拒绝必须与 policy violation 分开验证；`policy_denied` 不能自动计为成功或失败，取决于任务期望决策与模型是否实际尝试被禁止变更。
- 方案 A 设计规格已写入 `docs/superpowers/specs/2026-07-20-retailops-v1-contract-design.md`；用户复核前不创建实现计划。
- 用户已批准方案 A 书面规格，可以创建 R1 实现计划；尚未授权开始代码实现。
- 现有 `OraclePolicy` 完全按 `expected_calls` 执行，R1 需要为正确拒绝引入 `expected_decision/required_reads` 语义，同时保持旧 MiniRetail Oracle 回归不变。
- FastAPI/uvicorn 尚未进入 `pyproject.toml` 或 `uv.lock`；根 `/data/` 已被 `.gitignore` 排除，可作为 R2 sealed holdout artifact 的默认本地边界。
- `RetailOpsEnv` 可直接实现现有 `ToolEnv` 接口并复用 runner/reward/replay；其 milestone 应报告必要读取与决策进度，不需要引入通用状态机 DSL。
- sealed artifact 默认使用项目相对 `data/private/retail_ops/v1/`，兼容现有相对路径校验且由根 `/data/` ignore 规则排除。
- R1 实现计划固定为 10 个 TDD 任务，新增代码集中在 `veritool_rl.retail_ops`；通用 runner/replay/metrics 只做向后兼容扩展。
- R1 evaluation 只实现 qualification/development；正式 sealed holdout 的生成与 evaluator 接入留到 R2，R1 仅实现 receipt、隔离、授权和脱敏契约测试。
- 实现计划位于 `docs/superpowers/plans/2026-07-20-retailops-v1-r1-vertical-slice.md`，用户选择执行方式前不开始代码实现。
- 工作期间仓库被独立化为自身 `.git` 且追加 `ec22ec0`/`b8e84b6`；`ec22ec0` 删除一个冗余 Codex fallback 测试，因此当前完整收集基线为 111 tests，而不是 R0 记录的 112。
- 用户已选择 subagent-driven 执行 R1；计划 preflight 未发现任务间或全局约束冲突，执行前 HEAD `88448f3` 的完整测试为 111 passed。
- R1 Task 1 已在 `0c9d639` 完成版本化 bundle：冻结 3 个工具 schema、6 类任务、退款政策和 release 阈值，并以严格 Pydantic 模型、跨文档退款原因校验和 canonical 组件哈希保护契约；独立任务审查无问题。
- R1 Task 2 已在 `d253cbf` 完成任务 schema、12 条确定性 qualification fixture、policy-aware 环境及 runner/replay 终止响应 hook；独立审查无阻塞问题，仅记录“恢复测试未显式发起第三次退款”的 Minor 覆盖项供最终审查复核。
- R1 Task 3 在 `02b501a` 初始实现后以 `6faf8d4` 修复并通过重审：factory 先拒绝非 qualification split，baseline 拒绝空/非 `get_order` 首调用，分类断言精确；legacy Oracle 未改。独立重审无阻塞问题，另记录报告早段 stale final SHA 的 Minor 审计项。
- R1 Task 4 已在 `5b2e043` 完成 TaskSpec JSONL、12 条 qualification 的确定性 manifest、逐任务/整文件哈希和目录存在即拒绝的不可覆盖构建；独立审查无阻塞问题，记录 partial-write 故障注入与类别顺序负测两个 Minor 覆盖项。
- R1 Task 5 在 `c7e63c6` 初始实现后以 `6cb816c` 完成治理加固并通过无问题重审：receipt 内部计数/ID/hash 一致性、单 manifest 重复、跨 split 隔离、release-only purpose/path/规则文件/hash 顺序均有合成负测；正式 private holdout 路径未创建或读取。
- 2026-07-21 从 Codex 会话 `019f7e4b-48d3-7513-aa20-9f0a864018ed` 续接；planning catchup 未报告未同步上下文。
- 当前规划证据确认 R1 Task 1–5 已完成并审查，续接范围应从 Task 6 开始，最终仍需完成 Task 1–10、whole-branch 审查与完整质量门。
- `progress.md` 当前只记录到 R1 subagent-driven 执行启动，尚未同步 Task 1–5 的实施进度；`docs/PROJECT_LOG.md` 最近一条长期决定仍是批准方案 A 与 10 项 TDD 计划，任务级完成证据主要保存在 `findings.md` 和 Git 历史中。
- 当前为独立 Git checkout（`git-dir == git-common-dir`，非 submodule），分支 `portfolio/retail-agent-ops-init`；用户已明确要求在该路径和会话基础上继续，因此无需创建嵌套 worktree。
- 恢复时 HEAD 为 `da12c3b`（Task 5 审查记录），工作树除本轮 `findings.md` 恢复记录外干净；没有 Task 6 代码或提交需要保留/回退。
- 剩余计划为 Task 6 评测证据/延迟分位数/脱敏、Task 7 配对发布门禁与确定性报告、Task 8 稳定 CLI、Task 9 FastAPI fallback 服务、Task 10 端到端验收与 R1 收口；均为 CPU-only。
- Task 6 的公开脱敏边界必须至少排除 `target_state`、`expected_calls`、`user_request`、`task_id`，且上一会话 reviewer 已特别要求复核字段名变体与嵌套结构是否能绕过脱敏。
- R1 Task 1–5 当前完整 pytest 基线为 173 passed；恢复点没有预存失败，可把 Task 6 新失败明确归因于新增测试。
- 现有 `compute_metrics` 已按 episode 汇总 `average_latency_ms`，新增 p50/p95 可在同一 episode latency 数组上计算并为 empty metrics 返回 `0.0`，不需要改变旧指标语义。
- `Trajectory` 内含完整 `TaskSpec`、逐步 state、raw output 和 metadata；公开 failure 不能对完整模型 dump 做黑名单递归删除，应从失败 taxonomy、场景、终止原因、违规码和有限工具错误字段构造固定允许列表。
- `load_built_tasks` 已验证 tasks 文件哈希、顺序、数量和逐任务哈希；Task 6 仍需额外核对 manifest 的 bundle hash、split/mode 与 CLI seed，避免只验证任务内容却接受错误运行契约。
- 通用 `Evaluator` 会 `exist_ok=True` 写输出，不满足 R1 正式目录不可覆盖；RetailOps evaluation 应直接用 `create_output_dir` 并一次性写 `config.yaml`、`trajectories.jsonl`、`metrics.json`、`failures.jsonl`、`log.txt`、`run.json`。
- 设计规格要求 Task 6 同时报告轨迹可重放率与证据完整率，失败 taxonomy 至少覆盖 parser/格式、工具选择、参数 schema、政策违规、恢复失败、步数上限和环境错误；R1 qualification 实际出现的类别必须稳定输出，未出现类别可不伪造计数。
- 上一会话派发 Task 6 时明确要求：evidence 同时绑定 bundle 与 manifest SHA，验证任务覆盖完整性，在任何 policy 执行前拒绝 holdout；实现子代理尚未留下代码，因此本轮可从真实 RED 开始。
- Task 6 RED 已确认失败原因正确：7 个用例因 `veritool_rl.retail_ops.evaluation` 不存在失败，2 个指标断言因缺少 p50/p95 key 失败；其余既有 metrics 用例仍通过。
- Task 6 首轮实现已达到 180 tests、Ruff 与 mypy 全绿；自审继续发现两个计划契约应补显式测试：manifest 的类别/family 覆盖完整性不能只靠文件哈希，`EvaluationMode.DEVELOPMENT` 不能被 qualification policy 的 split guard 意外阻断。
- R1 Task 6 已在 `9b13c84` 完成：evidence 双哈希绑定 bundle/manifest，固定产物逐项哈希与 loader 防篡改，qualification/development 模式、任务覆盖/seed/split 前置校验、100% replay 指标、p50/p95、不可覆盖输出及允许列表失败脱敏；自审补测后 22 selected、182 full tests、Ruff、mypy 与 diff 检查通过。
- Task 7 的配对门禁必须先验证 mode、bundle、manifest、evaluator、任务数、seed、parser 与 budget 完全一致，再一次性计算成功率增量、政策违规增量、非法调用、p95 比率和证据完整性；任何失败都选择 baseline，不能首错短路。
- Task 7 自审发现仅校验 `failed_gate_ids` 一致性仍允许删除整个通过 gate；已用失败测试固定五项 gate 的集合与顺序，保证 loader 不接受残缺 release report。
- R1 Task 7 已在 `042071a` 完成五项配对发布门禁、八字段公平性校验、零基座延迟安全处理、GO/NO-GO baseline fallback 决策及确定性 JSON/Markdown/HTML 报告；最终 16 selected、196 full tests、Ruff、mypy 与 diff 检查通过。
- 现有通用参数/`load_config` 位于 `src/veritool_rl/cli.py`，尚无产品 console script；Task 8 可新增独立 `product_cli.py` 而不修改历史脚本入口或包名。
- 已提交 config 的路径治理目前由 `veritool_rl.paths.validate_project_relative_path` 提供；Task 8 只需验证配置内 `bundle_dir`，用户显式传入的 input/output run 目录不受项目相对限制。
- Task 8 自审发现 release CLI 若只比较 base/candidate，可能用另一 bundle 的阈值发布；已用失败测试要求两份 run evidence 同时匹配配置加载的 release bundle SHA。
- 当前 uv 版本使用 `UV_DEFAULT_INDEX` 覆盖全局 default-index；`UV_INDEX_URL` 无法阻止全局镜像 URL 规范化。显式设为 lock 中的 `https://pypi.tuna.tsinghua.edu.cn/simple` 后离线解析不改 `uv.lock`。
- R1 Task 8 已在 `df68c60` 完成独立 `product_cli.py`、严格命令配置键、build/evaluate/release 分发、项目相对 bundle 路径、5 份稳定 YAML 和 `retail-agent-ops` console entry；最终 15 selected、201 full tests、Ruff、mypy、配置解析、lock 与 diff 检查通过。
- Task 9 依赖已通过项目 uv 环境安装：FastAPI 0.139.2、Uvicorn 0.51.0、HTTPX 0.28.1；`uv add` 自动写入的项目级清华镜像块不属于产品需求，已删除并保留依赖 lock 更新。
- 当前 Starlette 1.3.1 的 `TestClient` 优先导入 HTTPX2，回退 HTTPX 会发弃用警告；因此 dev 依赖从计划时的 `httpx>=0.27` 调整为 `httpx2>=2.0`，实际安装 2.7.0，产品运行依赖不受影响。
- R1 Task 9 已在 `b6cc1e4` 完成：服务只接受与 release 同哈希的 bundle 和 qualification manifest，GO 部署 candidate、NO-GO 回退 baseline，固定任务执行响应不包含任务真值；最终 12 selected、208 full tests、Ruff、mypy、lock 与 diff 检查通过。
- Task 10 首次验收中，CPU 端到端 build/base-oracle-fault evaluate/GO-NO-GO release/TestClient 已通过；新增治理断言仅在尚未写入的 R1 README、阶段状态和 completion log 上失败，说明产品闭环无需额外代码修复。
- README 中记录的六条 CPU 命令已原样生成 `reports/retail_ops/v1/qualification-r1-final/`：build、base/oracle/fault evidence 及 GO/NO-GO 三格式报告均存在；未启动持久服务。
- 新鲜与重复 qualification 树逐文件 `diff -qr` 无差异；baseline/oracle/fault 分别为 8/12、12/12、0/12 且均 12/12 可重放，发布为 GO/candidate 与 NO-GO/baseline。manifest SHA-256 为 `6f510a699c33a5ec9c7df3ef4310a36165b4acff270425b6bfc8c6fd39124f6e`。
- 两份 HTML 被识别为 UTF-8 HTML；公开 release 三格式报告未命中任务真值、holdout、BFCL、常见 secret/private-key 标记，证据树不存在常见模型权重扩展名。正式 holdout 路径仍由根 `/data/` ignore 规则隔离。
- Task 10 提交前完整质量门为 211 passed、Ruff 和 mypy 46 files 通过、lock 与 diff 无变化；随后工作树审计发现新 `reports/retail_ops/` 尚未受 ignore 规则保护，需要在提交前补治理契约。
- `/reports/retail_ops/` ignore 治理断言先失败后通过；本地证据树被保留用于复核，但不进入 Git。修复后重新执行完整门禁仍为 211 passed，Ruff、mypy、lock 与 diff 全部通过。
- whole-branch 自审发现 README 曾把本地 `trajectories.jsonl` 误称为“脱敏轨迹”；实际脱敏边界是 `failures.jsonl` 与公开 release 报告。文档已改为“本地完整轨迹、脱敏失败摘要”，避免把 qualification 产物边界写宽。
- whole-branch 核心 diff 复核确认 legacy MiniRetail 场景集合被显式冻结、final-response hook 在 run/replay 两端对称、输出目录不可覆盖、holdout 在 policy 前拒绝、paired release 八字段一致性与服务 fallback 均有负测；未发现阻塞缺陷。E2E 进一步固定每个 release 目录必须恰有 JSON/Markdown/HTML 三份报告。
- 2026-07-22 迁移前复核：当前目录已经是 `git-dir == git-common-dir` 的普通独立仓库，原 `veritool-rl` 只登记自身 main worktree；因此应迁移现有目录而不是再次 `git init` 或复制历史。
- 物理路径迁移会使 `.venv/bin/*` 与 `tools/bfcl_eval/.venv/bin/*` 的绝对 shebang 失效，且 `data/external_repos -> ../../../veritool-rl/data/external_repos` 在新层级下解析错误；迁移验收必须重建两个 uv 环境并把链接改为 `../../veritool-rl/data/external_repos`。
- R2 仍缺数据来源/teacher/provider/计划主模型的用户决策；交接提示词可以授权阶段启动和 CPU 实现，但必须在正式数据生成、商业 API、模型下载或远程 GPU 前分别展示方案/精确命令并等待确认。
- 迁移前新鲜 CPU 基线为 `211 passed`，目标目录不存在，HEAD 为 `59cc1b574da0b55cb249aaeca09ab5a720b24ea6`，磁盘可用 813G；可在保留回滚点的前提下原子移动现有 201M 目录。
- R2 可复用 R1 的 `TaskSpec`、`RetailOpsEnv`、`TaskManifest`、`HoldoutReceipt`、`assert_split_isolation`、`authorize_holdout`、replay、metrics 和 redaction，但现有 `build_qualification_tasks` 仅能生成 12 条 qualification，`evaluate_retail_ops` 明确拒绝 holdout，通用 `scripts/build_trajectories.py`/`scripts/evaluate.py` 仍是 MiniRetail-only，不能直接冒充 R2 正式流水线。
- 现有 `build_success_trajectories` 与 `trajectory_to_sft_example` 可作为 train/dev 轨迹质检基础；R2 需要独立 RetailOps split builder、数据 provenance/quality report、sealed holdout freeze/evaluator 和 base-run contract，而 QLoRA 训练本身属于 R3，不应塞入 R2 提示词。
- `data/external_repos` 的真实目标包含 `gorilla/`、`ToolSandbox/`、`tau2-bench/` 与 `appworld/`；迁移后应验证 `data/external_repos/gorilla` 的固定 commit，而不是误在 external_repos 父目录读取原 `veritool-rl` 的 HEAD。
- R2 只读 subagent 审计确认：当前 `TaskManifest` 的完整任务 hash 会随 task_id/split 改变，不能识别派生泄漏，必须增加 answer-free content 与 derivation/source fingerprint；holdout loader 也必须在整文件 SHA 后核对 receipt 的逐项内容一致性。
- 正式 base evidence 需补 checkpoint/revision/file hash、commit、lock SHA、GPU UUID、显存、wall time、吞吐和成本；CPU 测试使用 fake backend。现有通用 evaluator 继续拒绝 holdout，新的 sealed evaluator 独立实现，完整轨迹留 private、公共只出聚合 allowlist。
- `docs/EXECUTION_PLAN.md` 要求 R2 同时建立 Qwen3-1.7B 与计划主模型 base，R3 又把 Qwen3-4B 下载/smoke 列在 R3。R2 提示词已把此冲突设为用户决策门：要么审批 R2 两个 base，要么正式修改阶段验收；不能缺报告却直接收口。
- 2026-07-22 实际迁移完成：正式目录为 `/home/tjk/myProjects/internship-projects/retail-agent-ops`，旧 `.worktrees/retail-agent-ops` 路径已不存在；仓库仍为自身 `.git`、分支 `portfolio/retail-agent-ops-init`、无 remote，且 HEAD 保持 R1 基线 `59cc1b5` 的后代。
- 新建主环境与 BFCL evaluator 环境均为 Python 3.11.15；`.venv/bin/pytest` 和 `.venv/bin/mypy` shebang 已指向正式目录。外部仓库链接解析到未修改的原项目路径，Gorilla commit 仍为 `6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`。

## R2 正式数据与双模型 Base 启动发现（2026-07-22）

- 用户已批准 `retail_ops_v1_r2_20260722`、seed 0、六类各 35 个 semantic family × 2 个表述变体；family-first 配额为每类 train/dev/holdout=`20/5/10` families，即任务 `40/10/20`，总计 `240/60/120`。
- teacher 只访问 train，正式导出每任务恰一条可回放轨迹；优先合格 teacher，缺口由 internal reference 补齐。teacher 总通过率低于 70% 或任一类别低于 50% 时必须停止，不能自动换 provider/model/prompt。
- provider 路由采用 `.env` selector：`TEACHER_LLM_PROVIDER=<name>` 动态选择 `TEACHER_LLM_<NAME>_{BASE_URL,API_KEY,MODEL,EXTRA_BODY_JSON}`。选中 route 的非秘密快照和哈希绑定 smoke/full attempt；route 变化必须重新 smoke。
- 当前 `.env` 只读检查发现变量名为 `DEEPSEEK_API_KRY`、权限 0644 且 model 仍为旧配置；API 门前需要用户改为中立 provider profile key，agent 不读取或打印密钥，并将权限收紧为 0600。
- R2 dev base 固定 Qwen3-1.7B revision `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e` 与 Qwen3-4B revision `1cfa9a7208912126459214e8b04321603b3df60c`；均只跑 60 条 dev、4-bit NF4、deterministic non-thinking、无 adapter，不打开正式 holdout。
- 远端项目根为 `/data/TJK/internship-projects/retail-agent-ops`，模型根为 `/data/TJK/models`；任何 SSH、目录创建/同步、模型下载和 GPU 命令仍需逐条展示实际工作目录、物理 GPU、时长与产物后等待批准。
- `uv 0.11.8` 基线 lock 失败不是依赖变化：用户配置的清华镜像为 `https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/`，现有 lock 使用等价旧别名 `https://pypi.tuna.tsinghua.edu.cn/simple`，临时解析产生 4336 行纯 URL diff。显式旧别名后 `uv lock --check` 通过，R2 应项目级固定索引而非重写全部 lock。
- R2 计划独立审阅指出旧 `AGENTS.md` 和 handoff 仍保留 R1 审批入口，同时 answer-free projection、dev 私有真值加载和 teacher 私有导出边界未完全闭合；这些都是执行前必须解决的治理缺口，不是实现阶段可默认为真的细节。
- 已把 active instructions 切换到已批准 R2 CPU 实现，并固定 family 轴：lookup 七状态、窗口 margin `1/2/3/5/7/10/14`、0..4 distractor、四原因映射。content fingerprint 明确排除 task_id/split/答案字段；dev base 必须经过 private artifact SHA 与公开 manifest 双检；train/SFT 逐任务文件只写 ignored private root。
- 二次计划审阅仅余 teacher 原始采集目录未显式限定 private。已新增治理 RED，并把 smoke/full 的 raw response、step、trajectory、usage、checkpoint 和哈希固定到不可覆盖的 private ignored `teacher-collection/<attempt>/`，计划要求测试拒绝公开或非私有输出。
- 最终只读复审确认 R2 规格/计划 PASS，无 Critical/Important；CPU 实现可以依次执行，外部资源审批门保持不变。
- Task 2 可在不改 R1 schema 的前提下新增 `FormalTaskManifest`/`FormalHoldoutReceipt`：现有 R1 writer 会公开原始 task/family ID，不能复用为 R2 public manifest；但 `canonical_json`、`create_output_dir`、`sha256_file` 和 strict Pydantic 模式可以复用。
- 现有 `authorize_holdout` 已有 purpose-first、路径和整文件 SHA 门，但旧 receipt 暴露 task/family ID，loader 也不验证 R2 五类指纹/配额/顺序；R2 必须保持独立两阶段授权，且非 release 必须在任何 open/read 前失败。
- Task 1 独立审查发现初版 derivation 指纹信任 `metadata.formal_family`，实际 deadline/owner/refund status/lookup status 被篡改时可能不变；正式 integrity 校验必须从 task 真值重建政策投影，不能把同一记录携带的 metadata 当独立证据。
- 初版 quota 校验只计每 family 两条，会接受复制 variant 0 替换 variant 1；需同时校验 `{0,1}`、task/content 唯一和五指纹可重算一致。420 条环境语义、catalog 轴和冻结原因集合也必须进入自动测试，不能只留在临时验证报告。
- Task 2 writer 不能仅依赖 `write_json`/`write_jsonl`，因为这些 helper 会创建 parent 且覆盖同名文件；必须先对 private/public 两个版本根执行不可覆盖创建，并对部分创建失败设计清理或预检，避免只写出一半契约。
- R1 `authorize_holdout` 的 purpose-first 顺序可保留为兼容基线，但 R2 receipt 必须使用 opaque 五指纹而非 raw ID，并把整文件 SHA 认证与 JSONL 解析拆成两个公开接口；测试应使用 spy path/file 证明非 release 不触发 `exists/is_file/read/open`。
- Task 2 初版自审需特别攻击两个尚未由接口形状自动保证的点：private row 的 `variant_index`/task metadata 是否精确成 `{0,1}` 且一致，以及正式 seed 0、dataset/generator ID 是否由 schema/loader 冻结而非仅被 public manifest 自报。
- `_create_output_pair` 的 exists 预检可拒绝常见覆盖/嵌套，但两个 `mkdir` 不是事务：若 private 创建成功后 public 创建因权限或竞态失败，会残留半成品 private root。需由独立审查判断是否应在写前验证/临时目录提交或安全回滚。
- Task 2 独立审查已实证 6 个 Important：自由 public identifier 可承载 request/ID/private path；dataset/split/private provenance 未统一串链；row variant 可改为 `[0,0]`；双根失败留半成品；physical artifact 可经 root 外 symlink 授权；公开 dataclass + module seal 可伪造授权 token。当前不得进入 Task 3。
- 修复合同应以固定 R2 Literal、同 bytes 的 verified-dataset loader、private row 完整 provenance、family variant 重建、staging 后双根发布、trusted physical root + no-follow fd 读取，以及内部注册 capability 为核心；同进程 Python 私有对象不是密码学安全边界，不应夸大为绝对防伪。
- Task 2 修复后统一 verified dataset、fixed provenance、private variant 重建、failure-atomic staging/publish、trusted-root 同 fd 读取和 factory-issued capability 均通过契约复审；最终无 Critical/Important/Minor，R1 行为未修改。
- Task 3 基线尚无 OpenAI SDK 依赖或 `[tool.uv]` 项目索引；`uv.lock` 只有现有 HTTPX。应把 SDK 放入独立 `teacher` optional group并保持 lazy import，核心安装/测试不能因未安装 teacher extra 失败。
- provider route 的唯一动态入口是 `TEACHER_LLM_PROVIDER` 选择 `TEACHER_LLM_<NORMALIZED>_*`；实现和测试都只能使用传入的 fake environment，不枚举真实进程环境，也不读取 `.env`。API key 只作为 loader 的内存返回值，route snapshot/hash/异常均不得包含它。
- 现有 agent 抽象实际位于 `agent/qwen.py` 的 `GenerationBackend` 与 `agent/policy.py` 的 `Policy`，不存在 `agent/base.py`。Task 3 的 `TeacherClient` 应保持独立的结构化 Chat Completions 边界，Task 4 再适配 episode/trajectory，避免把 API transport 塞进 Qwen text backend。
- runner 的 message/tool 形态已经是 OpenAI-compatible 基础结构，但 observation message 没有 tool-call ID；Task 3 只需精确传译输入并规范化响应，不应提前改变 R1 runner 或 Qwen parser。

## gpu-5090 环境扩展与 ModelScope 重新锁定（2026-08-05）

- `.env` 已修复：`DEEPSEEK_API_KRY`（拼写错误）等三个变量重命名为
  `TEACHER_LLM_DEEPSEEK_{BASE_URL,API_KEY,MODEL}`，新增 `TEACHER_LLM_PROVIDER=deepseek`，
  权限从 644 收紧为 600；未读取或打印密钥值，`TEACHER_LLM_DEEPSEEK_MODEL` 实际取值未改动，
  用户仍需确认目标 DeepSeek 模型标识是否需要更新。
- 用户批准新增 `gpu-5090` 作为第二远程环境（不替换 `gpu-4090`），远端用户 `tongjiakai`，
  项目路径固定为 `/mnt/aidata/tongjiakai/retail-agent-ops`，模型根为
  `/mnt/aidata/tongjiakai/models`；`CLAUDE.md` 第4节已更新，两套远程环境并列，之后每次远程
  操作需在报告中注明使用哪一个。详见 `docs/PROJECT_LOG.md` LOG-20260805-01。
- gpu-5090 只读侦察结果：RTX 5090 32GB 显存（侦察时空闲约27GB，另有其他用户2个进程共占约
  4.5GB，证明多人共用）、24 核、62GB 内存、`/mnt/aidata` 3.6T 空闲 2.0T、根分区 962G 空闲
  341G、驱动 580.126.09、Python 3.12.3、`~/.local/bin/uv 0.11.33` 已就绪。
  `/mnt/aidata/tongjiakai` 下已有该用户其他项目（`ekg`/`embed_server`/`llm-lifecycle-lab`/
  `ollama`/`SARGE`/`sysroot`/`envs`/`downloads`/`bin`），迁移只新建 `retail-agent-ops` 子目录，
  未修改任何既有目录。
- 代码迁移用 `git bundle --all`（只含两个本地分支的已提交历史，不含本轮未提交的
  `CLAUDE.md`/`docs/PROJECT_LOG.md`/`findings.md`/`task_plan.md`/`pyproject.toml`/`uv.lock`
  修改，也不含未提交的 `teacher_client.py`/`teacher_route.py` 及其测试）传输后在远端
  clone，随后移除指向已删除本地 bundle 文件的 `origin` remote，避免残留悬空引用。远端 HEAD
  当前停在 `155d67a`（Task 2 治理复审记录），落后本地工作区；`teacher` extra 尚未提交，因此
  远端首次 `uv sync --extra teacher` 失败（`Extra teacher is not defined`），改为
  `--extra dev --extra train` 后成功。
- 远端 `.venv`（5.2G）已验证 `torch==2.13.0+cu130`，`torch.cuda.is_available()` 为
  `True` 且正确识别 `NVIDIA GeForce RTX 5090`；同步后 `/mnt/aidata` 仍显示 2.0T 可用。
- ModelScope 侧文件级信息已通过其只读 REST API（`/api/v1/models/{id}/repo/files?Revision=master`）
  查得，比单一 revision 字符串更严格——直接记录了逐文件 SHA256：
  - `Qwen/Qwen3-1.7B`：权重文件（`model-00001-of-00002.safetensors` /
    `model-00002-of-00002.safetensors`）提交哈希 `980712f58bdf09497308d37d0e30b535064cde04`，
    总大小 4.08GB。
  - `Qwen/Qwen3-4B`：权重文件（三个 safetensors 分片）提交哈希
    `8cd0101f70cac4f1efcebc979faf483558e39297`，总大小 8.06GB。
  - 用户已确认改用 ModelScope 侧标识重新锁定，替代原 R2 计划里的 HuggingFace revision
    （`70d244cc86ccca08cf5af4e1e306ecf908b1ad5e` / `1cfa9a7208912126459214e8b04321603b3df60c`）；
    完整逐文件 sha256 manifest 保存在会话 scratchpad
    `modelscope_manifest.json`，下载后需要回填/替换本文件中原有的 HF revision 记录为正式
    ModelScope pin。
  - 下载与校验通过一次性脚本执行：`snapshot_download(revision="master")` 落盘后逐文件重算
    SHA256 并与上述 manifest 比对，任何文件缺失/大小不符/哈希不符都会使整体判定失败，不接受
    部分匹配。
  - **下载已完成并全部校验通过**（`ALL_FILES_VERIFIED_OK`，13/13 与 14/14 文件逐项 `OK`）。
    实际磁盘占用：`Qwen3-1.7B` 3.8G，`Qwen3-4B` 7.6G，合计 11.4G；`/mnt/aidata` 仍保持
    2.0T 可用。上述 ModelScope 提交哈希（`980712f58bdf...`／`8cd0101f70ca...`）现为
    R2 dev base 的正式 pin，取代原 R2 计划中的 HuggingFace revision 记录。落盘路径：
    `/mnt/aidata/tongjiakai/models/Qwen3-1.7B/`、`/mnt/aidata/tongjiakai/models/Qwen3-4B/`。

## R2 Task 3：provider-agnostic teacher 路由与 client（2026-08-05）

- 用户确认正式 teacher 模型为 `deepseek-v4-flash`；只读检索确认其为 DeepSeek 当前在售正式
  模型，真实 endpoint 为 `{base_url}/chat/completions`（非 `/v1/chat/completions`），与
  `.env` 现有 `TEACHER_LLM_DEEPSEEK_BASE_URL` 一致。真实 smoke（`max_tokens=8`）返回
  HTTP 200，但发现 `deepseek-v4-flash` 默认走 thinking 模式：`content` 为空、
  `reasoning_content` 非空、`finish_reason=length`。追加验证确认在请求体加入
  `"thinking":{"type":"disabled"}`（`extra_body` 透传）后 `content` 直接返回、
  `finish_reason=stop`，且只消耗 1 个 completion token；这个模式已经固化进
  `test_teacher_route.py`/`test_teacher_client.py` 的 fixture，Task 4 采集配置应复用。
- 接手时 `teacher_route.py`/`teacher_client.py` 已有前序会话留下的完整实现和 37 个通过的
  测试，但未跑过 Ruff/mypy：`ruff` 报 2 个真实问题（测试 fixture 里 `SimpleNamespace(...)`
  作为可变默认参数、`test_teacher_route.py` import 顺序），`mypy` 报 2 个真实问题
  （`TEACHER_PROTOCOL_ID` 模块常量未标注为 `Literal`，导致 pydantic 字段默认值类型不兼容）。
  四项均已修复，不涉及行为变化。
- **实测发现 `[tool.uv] index-url = "..."` 在当前 `uv 0.11.8` 下完全不生效**：用一个不存在
  的域名替换该值后 `uv lock --check` 仍瞬间通过，证明该 key 被静默忽略；已验证的正确写法是
  `[[tool.uv.index]] url = "..." default = true`（同样用假域名测试，会真的尝试连接并报错，
  证明生效）。这正是 R1/R2 反复出现的"用户级镜像 URL 机械改写 uv.lock"问题的根因——旧配置
  没有真正锁定索引。改用正确写法后 `uv lock` 重新生成，`uv.lock` diff 从约 3671 行降到
  129 行（只剩 openai/distro/jiter 等真实新增依赖），`git diff --check` 与全量测试/Ruff/
  mypy/lock check 均通过。
- 独立只读审查（general-purpose agent）发现 1 项阻塞级问题：`_parse_extra_body`
  （`teacher_route.py`）和 `_normalize_tool_calls`（`teacher_client.py`）的 JSON 解析
  except 元组未捕获 `RecursionError`，深层嵌套但仅几 KB 的 `EXTRA_BODY_JSON`/tool
  arguments（未达 16KB 上限）会让加载路径整体崩溃而非返回预期的 `ValueError`/
  `TeacherClientError`。已用 `"[" * 4000 + "]" * 4000` 复现（RED），补两处 except 元组后
  确认修复（GREEN）。审查同时给出三项非阻塞建议（`from None` 不清除 `__context__`、未显式
  设置 SDK timeout/max_retries、`_reject_secret_keys` 是黑名单式子串匹配对零宽字符等极端
  构造无能为力）——均判定为可接受风险，原因：`__context__` 场景需要脆弱的自引用异常技巧才能
  完全清除，价值不足；timeout/重试边界属于 Task 4（真正发起批量请求的一方）该决定的参数；
  黑名单绕过的触发者就是本就控制该 env var 的操作者，不构成外部攻击面。均未改代码，留作
  已知限度记录而非修复项。
- Task 3 最终验收：323 个全仓测试、Ruff、mypy 51 个源文件、`uv lock --check`、
  `git diff --check` 全部通过，提交为 `7153c26`（`feat: add dynamic teacher routing`）。

## R2 Task 4：teacher 采集、质量门与 train 导出（2026-08-05）

- 新增 `src/veritool_rl/retail_ops/teacher_data.py`：`collect_teacher_attempt` 对每条 train
  任务最多跑 2 个 episode，只对可重试传输错误（`TeacherClientError.retryable`，靠
  `status_code`/异常类名鸭子类型判断，不硬依赖 openai SDK）重试最多 3 次；八类结果
  （成功/schema 非法/非法工具/政策违规/步数上限/终态错误/传输耗尽/replay 不一致）全部
  有真实场景测试覆盖，dev/holdout 任务在调用 client 前就被拒绝。
- 顺带修复 `src/veritool_rl/data/generators.py::trajectory_to_sft_example`：与 Task 3 对
  `run_episode` 的修复同一个问题（`tool_calls[].function.arguments` 需要是 JSON 字符串、
  需要 `id`/`tool_call_id`），因为 Task 4 的导出路径最终会把这个函数的输出写进 `sft.jsonl`。
- 独立审查在"测试全绿"之后仍然按 Task 1/2 同等严格度复现了三个真实漏洞（都已用攻击脚本验证
  成立，不是理论推测）：
  1. 私有根路径校验（原 `_assert_private_root`）只做 `.parts` 里的字符串成分检查，可被
     `..` 穿越、含相同片段的任意绝对路径、或把中间目录做成 symlink 绕过，已实测三种都能
     逃出预期目录。修复：写入函数改为接收调用方建立的受信 `private_root` + 校验过的简单
     `attempt_id`/`task_id` 分量，内部用 `resolve()` 做逃逸检测，复用 `formal_manifests.py`
     里已经审计过的模式。
  2. `load_teacher_checkpoint` 会解析 `accepted_task_ids` 引用的每个证据文件，但解析结果
     直接丢弃，从未跟 checkpoint 自身的六项治理哈希/`accepted`/`task_id` 做交叉校验——实测
     把某个证据文件替换成 `accepted=False`、哈希全不同的版本后，resume 照样把它当"已接受"
     任务继续。修复：逐字段核对证据文件内容与 checkpoint 记录一致，不一致就报错。
  3. `write_formal_train_export` 原来是 `train.jsonl`/`sft.jsonl`/`selection.json`/公开
     `quality.json` 四个文件顺序写入，中途失败会在 `train-export/<attempt>` 留下不一致的
     半成品，且无法安全重试（部分文件已存在会直接报 `FileExistsError`）。修复：private 三
     文件走 staging 目录 + 原子 rename 一次性发布，任何后续步骤（含公开 `quality.json` 冲突）
     失败都会把已发布的 private 目录整体回滚删除，复用 `formal_manifests.py::write_formal_task_set`
     的 staging/publish/rollback 模式。
  三处修复都补了对应的对抗性回归测试（路径穿越、intermediate symlink、证据内容篡改、
  公开产物冲突时的私有目录回滚），不是只补"正常路径"测试。
- 非阻塞建议判定为可接受风险、未改代码：重试之间无退避（真实批量采集时才会暴露，留给
  实际运行观察）；`_classify_outcome` 对"同时命中 unknown_tool 与 invalid_arguments"的
  优先级未单独测试但逻辑清楚（ILLEGAL_TOOL 优先）；`scenario_by_task_id` 无枚举类型约束
  （当前所有调用点都传枚举值，暂不可利用）。
- Task 4 最终验收：365 个全仓测试、Ruff、mypy 52 个源文件、`uv lock --check`、
  `git diff --check` 全部通过，提交为 `1d60af2`（`feat: add audited teacher data pipeline`）。

## 2026-08-05 — R2 Task 5：sealed evaluator 与 dev base 证据

- 模块划分：`sealed_evaluation.py` 只放 release 侧密封合同（`SealedEvaluationReport`、
  `evaluate_authorized_holdout`、`load_sealed_evaluation_report`）；`base_evaluation.py`
  放 develop 侧（`load_verified_formal_dev`、`ModelArtifact`、`HardwareProvenance`、
  `BaseEvaluationConfig`、`BaseRunEvidence`、`evaluate_formal_dev_base`、
  `load_base_run_evidence`）以及两者共用的评测机器（路径防护、staging 原子发布、
  episode/replay 执行、产物哈希、自哈希 ID）。计划的文件清单只允许这两个新模块，
  因此共享实现放在 `base_evaluation.py`，`sealed_evaluation.py` 按本包既有约定跨模块
  引用其模块私有名（同 `formal_governance` 引用 `formal_manifests._parse_and_validate_private_rows`）。
- 授权边界复用而非重造：`evaluate_authorized_holdout` 只接受 `AuthorizedFormalHoldout`，
  记录经 `load_authorized_formal_holdout` 重新哈希并逐行校验；伪造实例（`object.__new__`）
  和任意非授权对象都在任何文件写入之前 `PermissionError`。私有证据固定写到授权时使用的
  `trusted_private_root/sealed-eval/<attempt_id>/`，调用方无法把完整轨迹重定向到公开路径。
- dev loader 只固定解析 `<private_root>/dev.jsonl`：purpose 和 `split=dev` 在触碰文件系统
  之前判定，随后核对私有 artifact SHA-256 并交给已审计的 `_parse_and_validate_private_rows`
  做行数/类别/顺序/split/五指纹全量校验。传 `FormalHoldoutReceipt`、train manifest、
  `release`/`build` purpose 或字符串 `"develop"` 全部拒绝，不存在通往 holdout 的开发入口。
- 自审时补上的真实缺口：`evaluate_formal_dev_base` 原来只按公开 manifest 复核调用方传入的
  records，`dev_artifact_sha256` 等于调用方的一面之词。已改为在评测前独立重新加载并哈希
  校验 `dev.jsonl`，再逐条比对内容（`_require_records_match_private_artifact`），并补
  "加载后篡改磁盘 artifact 即拒绝评测"的回归测试。
- 模型 pin 只做形状校验、绝不在代码里硬编码 revision：`ModelArtifact.repo/revision/local_dir`
  是配置数据（`local_dir` 必须是受信 `models_root` 下的安全单一片段），真正的防篡改依据是
  `verify_local_model_files` 的逐文件 SHA-256 + "未列入清单的文件/子目录/symlink 一律拒绝"。
  `TransformersBackend` 会声明自身 `model_dir`/`revision`，评测端据此拒绝声明与锁定不一致
  的后端，避免"证据写着 A 模型、实际跑的是 B 模型"。
- 硬件测量做成可注入协议（`HardwareProvider`/`GpuMeasurement`），CPU 测试用 fake provider；
  真实 `CudaHardwareProvider` 只在方法内部导入 torch，并把逻辑 ordinal 通过
  `CUDA_VISIBLE_DEVICES` 映射回物理 index（非数字条目直接报错，不猜测物理身份）。
  `test_dev_base_never_imports_cuda_or_model_runtime` 用 `builtins.__import__` 守卫证明
  整条 CPU 评测路径不导入 torch/transformers/peft/bitsandbytes/pynvml。
- 公开输出按固定 allowlist 建模：sealed 报告只有聚合指标、运行 provenance 和失败 taxonomy
  计数；测试用私有记录的 task_id/user_request/family_id/order_id/customer_id 和五类指纹做
  子串扫描，确认公开 JSON 里一个都不出现（连 opaque fingerprint 也不出现）。

## R2 Task 6（CLI pipeline 分派与 CPU 端到端验收）

- `product_cli.py` 的 `build`/`evaluate` 现在先看 config 有没有 `pipeline` 字段：没有就
  逐字节走原 R1 精确 key 集合路径（`_run_release`/`_run_serve` 完全未改一行）；有就分派到
  四个新流水线函数（`_run_formal_freeze`/`_run_teacher_collect`/`_run_train_export`/
  `_run_formal_dev_base`），每个流水线各自校验自己的精确 key 集合，互不借用。
- 唯一允许读 `os.environ` 的地方是 `_run_teacher_collect` 里的一行
  `env = environ if environ is not None else os.environ`：写在全部 config/治理校验（含
  dataset_version 与已发布正式数据交叉核对）之后，真正要构造 client 之前才执行。用
  `monkeypatch.setenv("TEACHER_LLM_PROVIDER", "not a provider name!!")`（不是整体替换
  `os.environ`——那会连 pytest 自己读终端宽度都炸掉）证明其余四条流水线 + 未改的 R1 路径
  完全不受影响、也不会因为缺 `TEACHER_LLM_*` 而报错。
- 两处 CPU 测试无法构造真实依赖的流水线用同一种缝：可选关键字参数
  （`client_factory`/`backend_factory`/`hardware_provider_factory`），默认值是
  `None`，函数体内 `factory or _default_xxx` 在调用时才查找模块级默认工厂——这样默认工厂
  既可以在直接调用内部处理函数时被参数覆盖，也可以在只走 `main()` 时通过
  `monkeypatch.setattr(product_cli, "_default_xxx", fake)` 在其唯一定义点被替换，不需要
  额外的"测试模式"开关。生产默认工厂（`_default_teacher_client_factory`、
  `_default_generation_backend`、`_default_hardware_provider`）分别真实调用
  `OpenAICompatibleTeacherClient.from_route`、`TransformersBackend.from_pretrained`、
  `CudaHardwareProvider`。
- `code_commit`/`uv_lock_sha256` 不放进 config（会在提交后立刻过期）：CLI 用
  `Path(__file__).resolve().parents[2]` 定位仓库根后现算 `git rev-parse HEAD` 与
  `uv.lock` 的 SHA-256，与调用方是否把 CWD chdir 到隔离 tmp 根无关（CPU e2e 测试必须
  chdir 到 tmp 根才能让 config 里的项目相对路径落在隔离目录里）。
- `train_export` 需要给 `TeacherCollectionConfig` 一个 `route_sha256`，但 `export_formal_train`
  函数体内实际上从未读取这个字段（核实过——只用于构造合法 config 对象）。没有为此读
  `os.environ`，而是从已加载的 teacher evidence 里的 `route_sha256` 去重推导；顺带对"同一次
  导出引用的证据混用了不同 route"这种不该发生的情况加了一道额外校验。
- teacher_collect 的续采集边界：`load_teacher_checkpoint` 只覆盖"已接受"任务；CLI 自己额外
  扫描 `<private_root>/teacher-collection/<attempt_id>/*.json`（排除 checkpoint.json）算出
  "本次运行前已经尝试过"的任务集合并整体跳过——不止跳过已接受的，也跳过已尝试但被拒绝的，
  因为 `write_teacher_attempt_evidence` 对同一 `(attempt_id, task_id)` 是不可覆盖的。这意味着
  同一 `attempt_id` 下被拒绝的任务不会被自动重试；要重试必须换一个新 `attempt_id`，与
  `dev-base`/`sealed-eval` 的 attempt_id 语义（一次运行=一个不可变身份）保持一致。
- 240 条 train 任务的"受控 pass/fallback 混合"CPU 测试不需要为 6 个场景各写一套脚本：写了
  一个通用 fake teacher client，把 `record.task.expected_calls`（gold 调用序列）原样回放，
  被标记为"应失败"的任务永远返回一个不存在的工具名（`ILLEGAL_TOOL`，不被接受）。这依赖
  `run_episode` 的一个真实机制——`env.record_final_response` 发生在 `compute_reward_breakdown`
  之前，所以对 `INFORM`/`DENY` 这类没有状态变更调用的场景，"回放完 gold 调用后随便说一句
  收尾"也能让 `reward.final_state` 变成 1.0 从而落在 `SUCCESS`（不是 `FINAL_RESPONSE`），
  这正是 `teacher_data.py` 自己的 `_build_reference_trajectory`（`OraclePolicy`）已经在用的
  同一套机制。

## R2 Task 5/6 独立审查与 Task 7 整分支审查（2026-08-05/06）

- Task 5 独立审查（在实现代理自己发现并修复"dev artifact hash 信任调用方"之后）另外发现
  1 项 Important：`_require_backend_matches_pin` 只核对 `backend.model_dir`/`backend.revision`，
  未核对 adapter 状态或实际生成参数——`TransformersBackend` 原先从不发布这两项，导致挂载
  adapter 或改了采样参数的后端也能通过 dev base 全部检查。修复：`TransformersBackend` 如实
  发布 `adapter_path`/`settings`，绑定校验依次拒绝非空 adapter、目录/revision 不符、
  `settings != config.generation`（`bea052c`）。8 项 Minor 记入 SDD 工作区 ledger（未进 Git）
  留待整分支审查统一分诊。
- Task 6 独立审查发现 4 项 Important：私有根 `_r2_private_root` 直接拼接未校验的
  `dataset_version`（当时仅因下游 `write_formal_task_set` 恰好先拒绝非冻结值才"意外安全"）；
  `.env` 边界回归测试用 `pytest.raises(Exception)` 过宽且 `formal_freeze`/`formal_dev_base`
  从未在污染环境下被实际跑过；`teacher_collect` 的 resume/skip 路径零测试覆盖（而
  `collect_teacher_attempt` 真实计费调用发生在不可覆盖检查之前）；计划 Step 5 明确要求的
  `uv lock --check` 治理扫描未落地为自动化测试。四项均修复并补对抗性回归测试（`96536c9`）；
  首次修复派发因触发本会话 API 用量限制中断（未产生任何改动），原样重试后成功。10 项 Minor
  同样记入 ledger。
- Task 7 整分支审查（`a3c748bdad1ce6fb7ec8a838d2f1f36da0bbae60..96536c9`，19 commits）确认：
  路径安全模式在 `formal_manifests.py`/`teacher_data.py`/`base_evaluation.py`/`product_cli.py`
  四处独立实现行为完全等价（非漂移，只是错误消息文案不同）；`.env` 边界、BFCL/holdout 隔离
  在全分支范围内成立；无任何硬编码 model revision；无 hard-stop 条件被违反。另发现 3 项新
  Important（跨任务视角才能看到，单任务审查无法发现）：
  1. `formal_dev_base` 独立加载 `dev.json`，未像 `teacher_collect`/`train_export` 那样经过
     `load_verified_formal_dataset`，跳过五维隔离交叉断言——`content_fingerprint`/
     `derivation_fingerprint` 刻意不含 `split`/`task_id`，理论上只有这层交叉断言能挡住被
     重新贴标签的内容（当前不可达，因为 dataset_version/generator/seed 是冻结 `Literal` 且
     生成过程确定性，但属于"央定不变量在这条路径未被重申"）。
  2. `export_formal_train` 接收 `TeacherCollectionConfig` 参数但函数体从未读取，teacher 证据
     仅凭 `task_id` 与任务记录匹配——独立 replay 只针对轨迹自带的 `task` 字段重放，两份被
     互换 `trajectory` 的证据文件（同一 `task_id` key）各自都能重放通过并被导出。
  3. `code_commit` 可能来自脏工作树（`_current_code_commit` 无 `git status --porcelain`
     检查，也无 subprocess 超时），与 Task 8"任何相关提交后拒绝陈旧运行"的验收要求冲突。
  三项均用 TDD 修复：`_run_formal_dev_base` 改为先 `load_verified_formal_dataset(dev_manifest_path.parent)`
  取其 `dataset.dev_manifest`，且要求独立解析的 `declared_manifest` 与之相等（不静默丢弃
  `dev_manifest_path`）；新增 `_require_evidence_binds_record` 校验
  `task_fingerprint`/`trajectory.task`/`dataset_version`/`bundle_sha256`/`manifest_sha256`，
  故意排除 `config_sha256`/`seed`（export 端用不同预算/seed 重建 config）与 `route_sha256`
  （从 evidence 自身推导，比较是同义反复），均在代码注释里写明排除理由避免被"修复"成恒假断言；
  发现证据不匹配时硬失败（非静默回退到 internal_reference）——`export_formal_train` 本身不
  做任何磁盘写入（纯函数返回 rows，写入都在 `write_formal_train_export`），因此硬失败不违反
  "不允许半成品导出"的既有约定。`_current_code_commit` 先查 `git status --porcelain`（未跟踪
  文件也算脏）非空即拒绝，git 子进程统一收敛到 `_run_readonly_git`（30 秒超时 + 可读错误）；
  新增 `code_commit_factory` 注入缝（与既有 `backend_factory`/`hardware_provider_factory`
  同一套模式，`main()` 从不传入，信任级别与已有的 `backend_factory` 相同）。复审（opus，
  完整深度，因为整分支审查按流程只有一轮修复）确认 3 项均已解决、3 个关键判断（硬失败而非
  回退；排除三个哈希字段；`code_commit_factory` 作用域）均合理，无新 Critical/Important
  代码缺陷（`c4d7fdc`）。
- Task 7 复审额外发现一处**运行流程**问题（非代码缺陷）：`manifests/retail_ops/v1/` 不在
  `.gitignore` 覆盖范围内（不同于 `data/`/`models/`/`reports/retail_ops/`），意味着
  `formal_freeze` 产出的 4 个公开文件若不提交，会被新的脏树检查判定为"未跟踪=脏"从而阻塞
  `formal_dev_base`——已写入正式执行顺序：`formal_freeze` → 提交公开 manifest →
  才能跑 `formal_dev_base`；两份 dev-base config 的真实 `model.revision`/`file_sha256` 也
  必须提交而不能只在远端临时编辑。完整清单见
  `docs/handoffs/2026-08-06-r2-external-run-commands.md`。
