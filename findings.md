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

## R2 Task 8 Step 1-2：正式数据冻结与 teacher smoke 首次真实执行（2026-08-06）

- Step 1 formal freeze 已批准执行并提交（`89e8039`）：正式 240/60/120 数据集生成，
  `dataset.json` 内嵌 `public_files_sha256` 与外部 `sha256sum` 核对一致，六类配额精确为
  train 40/dev 10/holdout 20（`seed=0`，`dataset_version=retail_ops_v1_r2_20260722`）。
- **重大发现**：`configs/retail_ops_v1_r2_teacher_smoke.yaml`（`pipeline: teacher_collect`）
  没有任何任务数量限制字段，只降低了 `max_episodes_per_task=1`/`max_request_attempts=1`；
  它会处理 `--input_dir` 私有根目录下 `train.jsonl` 的全部记录，不是命令清单文档描述的
  "每类别 1 条、共 6 条"。批准执行后实际处理了全部 240 条 train 任务（519 次真实请求，
  299,956 prompt + 45,893 completion tokens，约 $0.055，而非 <$0.01）。命令清单文档
  （`docs/handoffs/2026-08-06-r2-external-run-commands.md` 第 3 节）对这条命令行为的描述
  是错误的，需要用户决定是否/如何修正；这是文档准确性问题，不是 `teacher_collect` 代码
  本身的缺陷。
- 该次运行（reduced episode/attempt 预算）产出的真实类别信号：整体 211/240=87.9% 通过
  （高于 70% 门槛），但 `refund_denied_window` 仅 12/40=30.0%（低于 50% 每类别门槛）；
  全部 28 条失败样本的 `termination` 均为 `policy_violation`、`violations` 均为
  `refund_not_eligible`。
- **根因已确认（非模型能力问题，是任务/环境设计缺陷）**：`refund_denied_window` 是三个
  DENY 场景里唯一"disqualifying 信号无法从 `get_order` 响应直接推断"的场景。
  `environment.py::_get_order` 对 ownership 不匹配直接返回 `error_code=not_found`，对
  duplicate 直接原样返回 `refund_status="refunded"`，模型都能拿到明确信号；但 window
  场景只返回裸整数 `refund_deadline`（如 19），环境内部用于判定的参照值
  `current_day`（固定常量 20，`formal_tasks.py::_CURRENT_DAY`）从未通过 `SYSTEM_PROMPT`、
  `user_request` 或任何工具响应暴露给模型——任何推理式 agent 都无法仅凭对话历史判断订单
  是否过期，只能靠试探性调用 `refund_order`（试探本身即被记为 `policy_violation`）或猜测。
  Task 1-7 的 506 个 CPU 测试和多轮独立审查从未发现，因为测试路径只用 Oracle policy（直接
  读 `expected_decision` 真值，不受此信息缺口影响）或脚本化 fake client，从未让"只能看
  对话历史"的真实推理 agent 独立解这个场景。影响范围：train/dev/holdout 各 40/10/20 条
  （六类中的 1/6）；其余 5 类不受影响。详见 `docs/PROJECT_LOG.md` LOG-20260806-07。
- 本会话已停止，未请求 Step 3（240 任务正式全量）批准，也未修改
  `environment.py`/`formal_tasks.py`/prompt/parser/模型/provider/阈值，等待用户对补救
  方向的决策（是否修复环境暴露 `current_day`/相对天数信息、是否需要重新冻结受影响
  split、如何处理已产生的 `teacher-smoke-001` 证据）。

## R2 Task 8 Step 3-6：teacher 全量、GPU dev base 与最终收口（2026-08-06/07）

- 用户选择修复环境（暴露 `current_day`）而非放宽验收；修复不需要重新冻结数据（`current_day`
  早已写入 `_materialize_task` 产出的 `initial_state`，`formal_tasks.py`/`formal_manifests.py`
  从不 import `environment.py`）。修复后 `teacher-full-001`（完整 2 episode/3 attempt 预算）
  重新采集：`refund_denied_window` 30%→95%，整体 238/240=99.2%，确认修复有效非偶然。
- gpu-5090 首次真正跑模型 `generate()`（此前只验证过 `torch.cuda.is_available()`）暴露两个
  真实基础设施问题：(1) 复用已下载模型时用符号链接指回仓库外真实存储路径，被
  `base_evaluation.py::_resolve_within`（Task 5 审计过的路径逃逸检查）正确拦截——不应放宽
  这类安全检查，正确修复是把模型文件真实复制进受信根目录；(2) `torch==2.13.0+cu130` 的
  RoPE 计算（`bmm_outer_product`）默认走 Triton JIT，需要系统 C 编译器，gpu-5090 无
  gcc/sudo/conda；中途尝试用 `ziglang`（pip 装的用户态编译器）当 `CC`，编译能过但 zig 的
  cc 前端用自带 glibc shim 库构造链接命令、完全不转发 `-L` 去搜宿主系统库目录，链接
  `libcuda.so.1` 失败；最终发现 `torch._native/triton_utils.py` 读取的
  `TORCH_DISABLE_NATIVE_JIT=1` 是官方预留开关，设置后跳过整条 Triton override 注册，
  回退纯 PyTorch 实现，不需要任何编译器——比 ziglang 方案简单，无新依赖，已把 ziglang
  相关改动干净回退。
- 两份 dev base 结果不是单调的"更大模型更好"：Qwen3-4B 任务成功率更高（0.80 vs 1.7B 的
  0.70）、恢复能力更强，但 schema 有效率更低、非法调用率和政策违规率都显著更高——原样记录
  为真实的 base 权衡信号，R2 不做调优或解释。
- Task 8 独立复审（`c4d7fdc..HEAD`）用**独立重算**而非文本比对验证了哈希闭合性（从公开
  `dev.json` 重新计算 `dev_manifest_sha256`，逐字符匹配两份 `base-report.json` 的记录），
  结论 PASS，无 Critical/Important。R2 是否达到 `docs/EXECUTION_PLAN.md` 验收目标、能否
  标记已完成，交由用户最终确认。

## R3 Task 1：SFT CLI 接入与 provenance 锁定（2026-08-07）

- 用户选定**方案 A：直接对 Qwen3-4B 做 SFT**（不先跑 1.7B 全链路验证）。1.7B 的 dev base
  （task_success=0.70）继续作为系统卡里的成本/延迟对照基线，本轮不重复训练。
- `ModelSettings.revision`/`file_sha256` 定为**必填**（与 `base_evaluation.py::ModelArtifact`
  同一口径），而不是可选字段——可选就等于把"是否校验"交给配置作者，洞还在。直接后果是 4 份
  legacy SFT config（`sft.example`/`mvp_sft_qwen3_1_7b`/`bfcl_v4_sft_seed0`/
  `bfcl_v4_sft_seed0_smoke`）现在会在配置校验阶段 fail-closed；它们只被 legacy
  `scripts/train_sft.py` 使用，不在 R1-R3 流水线上，已在文件头注明需要回填真实哈希后才能恢复使用。
- `verify_local_model_files` 的调用点选在 `run_sft` 里"确认 model_path 是目录"之后、
  `_ensure_new_training_output` 与 `import torch` 之前。这个位置有两个好处：被篡改的模型目录
  不会在输出目录留下任何声称跑了锁定模型的产物；而且整条校验路径纯 CPU，本地没装 torch 也能
  用真实 `run_sft`（而非 mock）写回归测试。
- dev 侧导出放在新模块 `retail_ops/dev_sft_export.py` 而不是 `teacher_data.py`：关键治理属性是
  "dev 任务绝不会调用 teacher client"，把它做成**函数签名里根本没有 client 参数**比事后断言更强。
  落盘复用 `teacher_data.py` 已审计的 `_resolve_within`/staging-publish/失败回滚，不新写第五份
  路径安全实现（Task 7 审查专门点过这类漂移风险）。
- 两份新 config 的训练数据路径采用 `--input_dir` + 私有根内相对路径（`train_relpath`/
  `eval_relpath`），而不是把 `data/private/...` 写进已提交 config。这样 R2 建立的"已提交 config
  不含私有根字面量"治理断言可以原样扩展到 R3，代价只是 CLI 里多一层 `_private_data_path`
  逐分量校验+`_resolve_within` 拼接。
- 回滚原子性测试最初断言"整个 `dev-sft/` 父目录消失"，实测残留一个空父目录——这与
  `write_formal_train_export` 的既有回滚口径一致（只回滚 attempt 目录）。已把断言改成真实契约
  （attempt 目录消失且父目录为空），没有为了让测试通过而收紧生产行为。
- 本地真实 dev-sft 导出结果：60 条，六类各 10 条，`sha256sum` 独立重算
  `41ae6409438005d2f2c36dcec135c27b44232e24a0b95850c70668cfa6a26024` 与公开摘要
  `private_artifact_sha256` 一致；与 train 侧 240 条无任何 task_id 交叉，字段集合与 `tools`
  完全一致，训练器的格式检测可直接同格式加载。
- **未解决**：`max_seq_len=1024` 仍只有字符数粗估支撑（p95≈1025 字符），真实 Qwen3 tokenizer
  审计尚未执行。本地既无 Qwen3 tokenizer 文件也没装 transformers，因此审计安排在 gpu-5090 上
  以与训练完全相同的 transformers 版本执行（比在本地新建一套 tokenizer-only 环境更可信）。

## R3 Task 1 外部执行结果（gpu-5090，2026-08-07）

- **`TORCH_DISABLE_NATIVE_JIT=1` 对训练算子路径同样有效**——R2 只验证过推理路径，提示词把这
  当作必须重新观察的未知项。smoke 与 overfit 两次训练均未复现 Triton JIT 编译器缺失问题。
- **一次被自己推翻的判断**：直接用模型自带 chat template 调 `return_assistant_tokens_mask=True`
  得到全零 mask，一度判为阻塞。读 TRL 1.8 源码后确认 `SFTTrainer` 在
  `assistant_only_loss=True` 且模板无 `{% generation %}` 时会自动
  `get_training_chat_template(processing_class)` 换用带标记的训练模板，并对"任何样本无
  assistant token"硬抛 `RuntimeError`。教训：用裸 tokenizer 模板测出来的数字不代表训练时的
  真实口径，要测就要测框架实际会用的那一份。
- token 审计（用 TRL 训练模板）：train 总 token max=730/p95=723，dev max=727/p95=723，
  **0/300 超过 1024**；assistant 监督 token train p50=139/dev p50=47，空 mask 行 0 条；
  `is_chat_template_stop_token_trained=True`（end-of-turn 进 loss mask，模型会学会停）。
- **overfit 检查是三级阶梯里信息量最大的一级**：train loss 1.2729→0.0168（76 倍，单调），
  token accuracy 0.8605→0.9965。这直接排除了"assistant mask 覆盖错导致 loss 卡在高位"这类
  系统性缺陷；smoke 通过并不能证明这一点（smoke 只跑 2 步，loss 甚至因 warmup 让 lr=0 而
  两步不变）。
- overfit 的 eval_loss 形状 `2.24 → 0.80（epoch 3 最低）→ 1.47 平台` 有额外信息：先降说明
  dev 侧的工具调用部分确实与 train 共享可学结构、不是纯噪声。
- 全量运行：`train_loss=0.3722`、`eval_loss` 三 epoch 为 `0.5266/0.5603/0.5797`、
  `eval_mean_token_accuracy` 为 `0.9321/0.9472/0.9436`。**eval_loss 轻微上升而 token accuracy
  上升后持平**——这正是已记录口径差异的预期表现，不是过拟合信号。
- 实测速度远快于预估：45 step 全量只用 134s wall time（预估 2.5-4 分钟，落在区间内但接近
  下界）；显存三次运行稳定在 5.13-5.16 GiB，与 batch/seq 形状而非 step 数相关。

## R3 Task 2：候选 dev 评测结果与失败机制（2026-08-07）

- **候选把一类失败换成了另一类**：格式/政策类问题被彻底清零（invalid_call 21→0、
  policy_violation 8→0、schema_valid_rate 0.781→1.000），但 task_success 从 48/60 降到
  43/60。终止原因分布最能说明问题：base 是 `{success:48, policy_violation:8,
  final_response:3, step_limit:1}`，candidate 是 `{success:43, final_response:17}`——候选
  从不违规、从不乱调工具，它只是**说完就停**。
- **回退与"所需工具调用数"完全对应**：需要 1 次调用的四类做到 40/40；需要 2 次的
  `refund_eligible` 5/10→0/10，需要 3 次的 `refund_recovery` 5/10→3/10。7 个新失败**全部**
  是 `termination=final_response`、`violations=[]`。
- **根因是训练数据的动作长度不平衡**：240 条 train 里 160 条（66.7%）只有 1 次工具调用。
  模型学到"调一次→写总结"的主导模式并过度泛化。旁证：`average_tool_calls` 1.25→1.10、
  `average_turns` 2.28→2.05、`average_output_tokens` 112→149（学到 teacher 的详尽风格，
  也解释了平均延迟 2562→4176ms 的上升）。
- **统计口径**：整体 task_success 的配对 2x2 是 b=2/c=7，精确 McNemar **p=0.1797，不显著**
  ——单看这一项不能断言回退。但格式类是 21 vs 0（p<0.0001）与 8 vs 0（p=0.0078），确凿；
  `refund_eligible` 单场景 0 vs 5（p=0.0625）配合上述结构性对应关系，也不能当噪声处理。
  这组数字是"n=60 时哪些结论能说、哪些不能说"的现成例子。
- **`verifier_reward` 反而从 0.579 升到 0.717**，而 task_success 下降——复合奖励里格式/政策
  分量把任务失败掩盖了。这是 SPEC/CLAUDE.md 坚持"主判据是最终状态与政策 verifier、不是
  奖励值"的具体例证。
- 工程侧：`BaseRunEvidence` 一个字段都不能加（`_content_id` 把全部字段算进 `run_id`，
  加字段会让两份已产出的 R2 base 证据加载失败）。候选契约改用子类扩展解决，并把这条约束
  固化成一条以真实报告为输入的回归测试，而不是只写在注释里。
- `_require_backend_matches_pin` 现在是**双向**的：base 拒绝任何 adapter（原有防线），
  candidate 拒绝缺失或不符的 adapter——否则证据会声称评测了候选而实际跑的是 base。

## R3 Task 3 A：sealed holdout 的 provenance 与 CLI 入口（2026-08-10）

- **schema 窗口确实还开着，现在已经用掉**：`SealedEvaluationReport` 原本缺
  model/generation/hardware/config_sha256/code_commit/uv_lock_sha256/adapter，两份 sealed
  报告在字段级无法证明可比。核实 `data/private/.../sealed-eval/` 不存在、`reports/` 无
  sealed 产物后确认 holdout 从未跑过，因此补字段零成本。`_content_id` 只排除
  `report_id` 与 `schema_version`，新增字段自动落入自哈希（已用篡改 `model.revision`
  的测试钉住）。**此后再改 sealed schema 就会作废已产出证据。**
- **sealed 用单一类型 + 可选 adapter，而不是像 dev 侧那样分两个类型**。理由：sealed
  报告是对外的单一 allowlist schema，分裂成两个 schema_version 会让公开产物形态随
  base/candidate 变化；base/candidate 的角色由 `require_comparable_sealed_runs` 显式
  断言（base 必须无 adapter、candidate 必须有）。代价是少了一层类型级保护，因此这两条
  断言都有测试，且两条 adapter 双向绑定测试经过突变验证。
- **CLI 侧反过来拆成两条流水线** `formal_holdout_base` / `formal_holdout_candidate`。
  `_require_config_keys` 是精确 key 集合，若合成一条则 adapter 只能是可选 key，
  "漏写 adapter" 会静默变成 base 运行。拆开后配置文件本身声明意图，且 base 配置里
  出现 adapter 会被 key 契约挡住（有测试）。
- **突变验证的价值**：`_require_backend_matches_pin` 是在 GREEN 阶段顺手接上的，没有先
  失败的测试。事后把那一行注释掉重跑，两条 adapter 绑定测试立即 `DID NOT RAISE`，证明
  它们不是空测试；随后恢复。这个手法比"补一条事后测试"能给出真正的失败证据。
- **配置层面的可归因性现在可机器检查**：新增三条测试断言 R2 dev base、R3 dev candidate、
  两条 holdout 通道的 `model` 段逐字段相同，且 holdout candidate 与 dev candidate 的
  `adapter` 段相同。"delta 可归因于 adapter" 在配置层的前提不再只写在注释里。
- `authorize_formal_holdout` 的两条硬约束在 CLI 接线时**未放宽**：purpose 固定
  `EvidencePurpose.RELEASE`，logical_path 由代码拼成
  `data/private/retail_ops/v1/r2/<dataset_version>/holdout.jsonl`，不从配置读取。

## R3 Task 3 B/C：formal 发布门禁与真实模型 serve（2026-08-10）

- **同一份 `release.yaml` 只能有一种语义**，因此把门禁算术从 `decide_release` 抽成
  `build_release_gates`，R1 与 formal 共用；`GATE_IDS` 也提升为公开常量供两侧断言顺序。
  否则 formal 侧复制一套阈值后，同一候选可能在两条通道上得到互相矛盾的结论。
- **`FormalReleaseReport` 的 `deployment` 是可执行指令而不是描述性字段**：`serve` 直接按
  它决定加载什么，因此它与 `decision` 的一致性由 model validator 强制。手改 JSON 里的
  `decision`/`deployment` 会在加载时失败（有测试）——"不能靠改字段放行"是代码事实。
- **serve 的回滚是双重执行的**。只根据 `deployment` 决定传不传 adapter 给后端工厂不够：
  工厂是注入缝，实现可能来自别处。`_require_backend_matches_deployment` 还会核对工厂真正
  返回的后端声明的 `adapter_path`。突变验证：注释掉这一行后 rogue-factory 测试立即失败。
- **并发上限设为 1 是刻意的**：单卡并发解码会让显存峰值不可预测，也会破坏逐 episode 的
  延迟测量。超限返回 503 而不是排队——排队会让延迟指标失真。经突变验证（改成 8 即失败）。
- `MAX_REQUEST_BYTES` 目前是**前瞻性**的：现有端点不接受请求体。保留它是为了后续新增带
  body 的端点时，超限请求在触达模型之前就被拒绝，而不是等出问题再补。
- **两个注入缝的分工**：`backend_factory` 让本地 CPU 用 fake 后端装配真实服务代码路径，
  `app_runner` 让测试不必真的 `uvicorn.run` 阻塞。二者合起来使 SPEC §9 的全部约束都能在
  没有 GPU 的机器上回归。

## R3 封存 holdout 结果与首个 formal 发布决策（2026-08-11）

- **dev 的预测被封存集证实，且更极端**。候选在 holdout 上把格式/安全类同样清零
  （invalid_call 41→0、policy_violation 16→0、schema_valid_rate 0.7819→1.0000），
  但 `refund_eligible` **20/20 全数失败**（dev 上是 10 条中 0 条成功），
  `refund_recovery` 失败 9/20。候选失败类型 **100% 是 `premature_final_response`**，
  违规与非法调用各 0 条——它从不违规、从不乱调工具，只是"说完就停"。
  LOG-20260807-09 定位的机制（训练数据 66.7% 仅 1 次工具调用）不是 dev 的偶然。
- **base 的失败画像完全不同**：16 次 policy_violation 全部是 `refund_without_lookup`
  （未查询即退款），另有 verifier_failure 7、parser_format 3。两个模型是在不同维度上失败，
  这正是"格式/安全"与"多步执行"两类能力可以彼此独立的证据。
- **门禁不需要统计显著性，这一点值得写进面试叙述**。两侧 CI95 大幅重叠
  （base [0.708, 0.850] / candidate [0.675, 0.825]），单看 −3.3pp 不能断言整体显著回退；
  但发布门禁要求的是实测 +5pp，候选没有做到，NO-GO 因此成立且无需附加解释。
  把"显著性"与"发布标准"混为一谈是常见错误——后者是产品决策阈值，不是统计检验。
- **`verifier_reward` 第二次与主判据背离**：0.5646 → 0.7500 上升而 task_success 下降。
  第一次发生在 dev（LOG-20260807-09），这次发生在**发布证据**上。复合奖励里的格式/政策
  分量足以掩盖任务失败，这是坚持"主判据是最终状态与政策 verifier"的实证而非教条。
- **步骤 wall time ≠ 评测延迟**。base 步骤耗时 20m9s、candidate 9m19s，方向与 dev 相反，
  一度被误推测为他人负载抢占；sealed 报告的 `wall_time_seconds`（286.98 vs 544.21）
  推翻了该推测——差额几乎全部是 base 的冷启动：首读 7.6 GB 权重 + 13 个文件逐一 SHA-256
  校验，candidate 时页缓存已热。**provenance 里的字段才是可用于比较的量**。
- **共享 GPU 对延迟门禁的精度限度**：运行期间他人占用在 12574→11854→10768 MiB、
  利用率 56%→0%→100% 之间变动。p95 比值 1.0870 距阈值 1.25 有余量，噪声不足以翻转结论，
  但系统卡中不得把该数表述为精确测量。
- **中断诊断的可复用判据**：判断一次被杀的运行是否"消耗了 holdout"，看的不是它跑了多久，
  而是**有没有数字落盘并被读取**。本次中断留下的是一个空输出目录、不存在的 `sealed-eval/`，
  因此盲性完好。用 `rmdir` 而非 `rm -rf` 清理残骸——对非空目录失败这一性质，本身就是
  "绝不误删已产出证据"的保证。

## R3 serve 演示：回滚是可观测的，演示不等于能力证明（2026-08-11）

- **回滚在响应层可验证，而不只是配置声明**。`/health` 与每条 episode 响应都带
  `deployment=baseline` 和不含 adapter 后缀的 `policy_id`
  （`qwen:Qwen/Qwen3-4B@8cd0101f…`），与候选证据里的 `…+adapter:…#34544fac3ec9` 直接对照。
  加上 `create_formal_app` 会核对工厂真正返回后端声明的 `adapter_path`，
  "未过门禁的模型不会被加载"从文档承诺变成了三处独立可查的事实。
- **正确拒绝与政策违规的区分在服务层同样成立**：`refund_denied_ownership` 那条
  `get_order` 拿到 `not_found` 后直接停止、`violations=[]`、`success=true`。
  这正是 R1 设计里刻意分开的两种语义在真实模型上的体现。
- **演示成功不能当能力证明**。并发测试里作为陪衬发出的另一条 `refund_eligible` 失败于
  `termination=final_response`——base 也会"说完就停"，只是频率低于候选。
  面试叙述里应当同时给出 holdout 的 94/120 与这条负例，而不是只展示三条挑好的成功轨迹。
- **`pkill -f` 会匹配到自己**：用 `pkill -f 'retail-agent-ops serve'` 停服务时，
  该模式也匹配承载它的 ssh 命令行，shell 被自己杀掉、输出丢失，一度无法确认服务是否停止。
  改用 `pgrep -f 'retail.agent.ops ser[v]e'` 取 PID 再 `kill`（方括号让模式不自匹配），
  并以端口占用作为独立复核。远程停服务时这个坑值得记住。

## R3 交付文档的编写取舍（2026-08-11）

- **把"不可写的表述"与"可用数字"并置成表**（`RESUME_EVIDENCE.md` §1/§2），而不是在文末
  加一段免责声明。理由：误用需要主动违反一条具名规则，比"没注意到限制"更难发生。
  七条禁写项各自绑定原因（如"候选在 holdout 上是下降 3.3pp"），不是笼统的"注意严谨"。
- **演示文档强制含失败案例一节**。挑三条成功轨迹讲很容易，但同批次那条失败的
  `refund_eligible` 才是可信度的来源。三个主动交代项（演示不等于能力、Oracle 测试发现不了
  信息缺口、把推测当结论被数据推翻）都是真实发生过的，不是为了显得谦虚而编的。
- **简历 bullet 不由 agent 代选**。方案 A 与 B 用同一批数字，差别只在把「系统与证据」
  还是「模型与归因」放在主语位置——这取决于主投岗位，属于用户的策略决策。
  给两版加理由，比给一版加免责更有用。
- **R4 提示词要求执行方重新统计 66.7%**，而不是引用提示词自身。交接文档里的数字一旦被
  下游当作前提引用，就会脱离产物；让它从 train 导出文件重算一遍，成本极低而防漂移。
- **阶段状态不由 agent 宣告**。R3 第五项验收目标是「可在面试中演示」，其成立取决于用户
  实际走读与脱稿复盘。产出文档 ≠ 达成该目标，沿用 R2 由用户确认收口的先例。

## R4 只读核查：失败根因的精确化与两条被推翻的方案前提（2026-08-11）

只用 train(240) 与 dev(60)，未打开任何 sealed holdout 产物。按「数据覆盖 → 模板/parser →
工具 schema → verifier」四层逐项排查。

**66.7% 已独立复算成立，但它是根因的粗口径表述。** 从 `train-export-001/sft.jsonl` 重新
统计：160/240 恰好 1 次工具调用（66.6667%），`refund_eligible` 40 条为 2 次、
`refund_recovery` 40 条为 3 次。**动作长度与场景类别完全共变**，每个场景的调用次数是常数，
因此"重平衡动作长度"在本数据集上等价于"重平衡类别比例"，不存在只动长度不动类别的做法。

**更精确的机制（三条，均为本次新发现）**：

1. **训练集中「输出自然语言」与「回合结束」100% 共变。** 被监督的自然语言文本共 29519
   字符（字符代理，本地无 tokenizer，不冒充 token 计数），**其中 100% 来自 4 个单步类别**；
   `refund_eligible` 与 `refund_recovery` 的 assistant 消息 `content` 长度全为 0，两类合计
   贡献 0 个文本字符。模型从未见过"先说话再继续调工具"的样本，也从未见过多步场景里的任何
   自然语言。根源在环境而非导出：`runner.py:123` 在 `final_state == 1.0` 时立即 break，
   而 `environment.py:59` 的 `verify_final_state` 对 REFUND 类**不要求**终局回复，
   退款成功那一刻轨迹即被截断。
2. **真正的竞争发生在「get_order 已返回 + 用户以核实/检查口吻要求退款」这一上下文族内，
   比例是 120 : 40 = 3:1 偏向写文本。** `_user_request`（`formal_tasks.py:516`）给
   `refund_eligible` 与三个 `refund_denied_*` 的措辞几乎不可区分（核实/检查/查看/核验），
   唯一判别信号在 get_order 返回值里。该族内 120 条 denied 训练样本教「写文本并停止」，
   只有 40 条 eligible 教「调 refund_order」。`refund_recovery` 用的是无"核实"字样的祈使句
   （"请为订单 X 按 Y 办理退款"），候选在 dev 上该类 3/10 成功而 `refund_eligible` 0/10——
   与该口径一致。
3. **候选的失败不是"说完就停"这么中性，17/17 是同一个具体行为：向用户请求确认后停止。**
   dev 候选轨迹逐条检查：`refund_eligible` 10/10、`refund_recovery` 7/10 失败，末句全部形如
   "请问您需要我为您办理退款吗？""请问您是否确认要继续办理退款？"。模型**已正确读出订单状态
   并正确判定可退**（"退款截止日期是第 30 天，当前是第 20 天，仍在退款期内。因此，我可以为您
   办理退款"），只是不肯自己动手。这不是能力丢失，是行为倾向。旁证：训练集 160 条终局文本里
   大量以礼貌问句/邀请结尾（"请问还有其他需要帮助的吗？" 27 次等），teacher 的客服人设被继承。

**模板/parser：无缺陷，但有一条对改进方案的硬约束。** `parse_qwen_response` 正确解析了
失败轨迹第 0 步的 `<tool_call>`（`parse_error=None`），失败不是解析问题。但
`parser.py:29-31` 把「文本 + 工具调用同时出现」判为 `mixed_tool_call_content` 即非法调用——
因此**任何"让模型先声明再执行"的数据方案都会把 invalid_call 从 0 打回去**，
assistant 工具调用消息必须保持 `content` 为空。assistant-only loss 一项不重开：
LOG-20260807-06 已实测 TRL 1.8 自动换用带 `{% generation %}` 的训练模板、空 mask 行 0 条。
（adapter 目录里的 `chat_template.jinja` 无 generation 标记，那是 `save_pretrained` 存下的
模型自带模板，不是训练时口径——容易误判，记此备忘。）

**工具 schema：逐字节一致。** `load_bundle('domains/retail_ops/v1')` 的
`to_transformers()` 与 `sft.jsonl` 内嵌 `tools` 完全相等；训练集 system prompt 唯一且等于
`runner.SYSTEM_PROMPT`；`perturb_schema` 全仓只被 `tests/test_mini_retail_env.py` 调用，
评测路径不启用。

**verifier：判定正确，但本身贡献了同一处不对称。** REFUND 类只看 `_refund_applied` +
状态匹配，INFORM/DENY 类额外要求 `_terminal_response`。候选一次都没调 `refund_order`，
失败是真实的，不是 verifier 造成的。

**两条前提被实测推翻，直接改变 R4 方案的成本排序**：

- **「给 `refund_eligible` 家族增采」不是"多花点 teacher API 钱"，而是要重新冻结数据集。**
  `formal_tasks.py:118` 的 `assert_exact_quotas` 把 train/dev/holdout 每类别
  40/10/20 写成硬契约，多一条任务就要改契约并重新冻结，`dataset_version` 与 manifest 哈希
  随之变化，已产出的 dev base、sealed holdout base/candidate 证据**全部失去可比性**。
  相比之下，对现有 80 条多步样本做**重复采样**只改 SFT 导出产物，任务契约、manifest、
  已有证据均不受影响。
- **系统提示词是 sealed 配对字段。** `system_prompt_sha256` 在
  `SEALED_PAIRING_FIELDS`（`sealed_evaluation.py:307`）内。给 system prompt 补一句
  "确认符合政策后直接执行，不要再向用户确认"是本次证据下最省力的干预，但它会让**已有的
  sealed holdout base 证据不可再用**——将来任何发布判定都需要重跑 base，即一次判定要消耗
  base + candidate 两侧的 holdout 观测，而不是只消耗候选一侧。

**由上一条追出的、适用于全部方案的结论**：`code_commit` 与 `uv_lock_sha256` 同样在
`SEALED_PAIRING_FIELDS` 内，而 `_current_code_commit`（`product_cli.py:743`）取 git HEAD
并拒绝脏工作树。因此**任何 R4 改进提交后，已有 sealed holdout base 证据都不再可配对**。
这抹平了各方案在这一项上的差别——"改提示词会额外消耗 base 侧观测"不能用作选型理由，
因为改代码同样会。真正的结论是：**R4 之后的任何一次 release 判定都等于封存 holdout 的
第二次完整观测（base + candidate 两侧）**。不得为规避这点放宽 `require_comparable_sealed_runs`。

**成本口径（用于排优先级）**：训练 134 s、dev 评测 base 154 s / candidate 251 s。
一轮"改数据 → 训练 → dev 配对"的 GPU 时间约 7 分钟，**便宜的是实验，贵的是 holdout 观测**。

## R4 Task 1 实现取舍：重复采样落在数据产物而不是训练代码（2026-08-11）

- **重复采样只作用于 `sft.jsonl`，`train.jsonl` 与 `selection.json` 保持与 240 条冻结任务
  1:1**。后两者是 provenance，声称"本次导出覆盖了哪些冻结任务"；让重复漏进去会让产物
  声称 400 条任务，而冻结契约只有 240 条。实测两份文件与 `train-export-001` **逐字节相同**
  （`29f02425…` / `f60744f7…`），这同时证明了导出过程是确定的、重采样没有污染其余环节。
- **选"重复行"而不是"训练侧样本权重"**：改动完全落在可哈希的数据产物里，训练代码一行不改，
  与 R3 候选的差异因此可以精确到一个文件。`test_r4_sft_config_changes_exactly_one_variable`
  把这条纪律变成断言——R4 训练配置除 `data.train_relpath` 外，model/lora/training 三段
  必须与 R3 逐字段相同。
- **`sft_oversample` 是必填配置键，不给默认值**。有默认值时"忘了写"与"故意不重采样"
  产出同一份数据，事后无法从配置本身分辨这轮实验是否设置过。同理，未知场景名与非正因子
  一律硬失败：静默忽略会产出一份与未重采样逐字节相同的文件，却让整轮结论挂在一个没发生的改动上。
- **新增 `sft_oversample.json` 并纳入 `private_artifact_sha256`**：只看 `sft.jsonl` 无法区分
  "400 条任务"与"240 条任务、其中 80 条重复三次"，而这两者对结论的含义完全不同。
- **刻意不降采 denied 三类**：它们正是 invalid_call 41→0、policy_violation 16→0 这一侧收益的
  训练信号来源。降采能同样改变比例，但会把已经拿到的东西一起丢掉。
- **本轮不做任何消息内容改写**。"让模型先声明再执行"看起来能直接治好"请求确认"这个行为，
  但 `parser.py` 把「文本+工具调用同时出现」判为 `mixed_tool_call_content` 即非法调用——
  那样会把 invalid_call 从 0 打回去，用一个已解决的失败换另一个。
- 实测效果（本地 CPU 导出，非模型结果）：sft 400 行、场景计数 40/40/40/40/120/120、
  去重后 240 条且集合与 001 完全相同；单步样本占比 66.7% → **40.0%**；
  「核实/检查口吻要求退款」族内 denied:eligible 由 **3:1 → 1:1**。
  这些是**输入分布**的变化，不是能力证明——候选是否变好只能由 dev 行为式评测回答。

## R4 第一轮的负结果：比例不是主因，措辞才是嫌疑（2026-08-11）

- **把决策点比例从 3:1 拉到 1:1，`refund_eligible` 的通过数变化是精确的 0**（0/10 → 0/10）。
  这不是"改善不显著"，是完全没动。据此，"决策点上的条件动作比例是该行为的主要成因"
  这一假设在 1:1 量级上**被证伪**。样本数翻三倍对这一类的作用为零。
- **唯一正向信息来自两个多步家族在同一处理下的分化**：都 ×3，`refund_recovery` +2、
  `refund_eligible` +0。二者样本数变化相同，差别在 `_user_request` 的措辞——
  `refund_recovery` 是无"核实"字样的祈使句，`refund_eligible` 的两个变体都以核实/检查开头。
  残余决定因素更像是**请求措辞把任务框定成"先核实再回报"**。这是观察不是结论。
- **`train_loss` 更低（0.3722→0.2198）而目标行为没有改善**。这与 `verifier_reward` 三次
  与主判据背离是同一件事的两种表现：可优化的代理量全都在改善，唯独真实任务没有。
  面试里这比任何正结果都更能说明"为什么主判据必须是最终状态"。
- **"重复采样而不降采 denied 三类"这个取舍被验证是对的**：比例照样被改变，而
  invalid_call 0、policy_violation 0、schema 1.0 全部保住，已获得的收益一件没丢。
  如果当初选降采，本轮会同时失去格式收益和执行改善，且无法分辨是哪一侧造成的。
- **纪律执行**：预设门槛是改动前写进 `task_plan.md` 与 LOG-20260811-07 的，
  达不到即停止。这里没有事后调整门槛、没有改判据、没有转而扩展算法。
  一个诚实的负结果加一个被证伪的假设，是本轮的全部产出。

## R4 第二轮开工核查：候选 C 的实现假设与代码事实冲突（2026-08-13）

设计 spec §4.3 与执行提示词第 3 节都假定「改 `runner.SYSTEM_PROMPT` 后重新导出
`train-export-004`，system 消息就会换成新 prompt」。**实测这个假设不成立。**

- `trajectory_to_sft_example`（`core/generators.py:34`）的 system 消息取自
  `trajectory.metadata["system_prompt"]`，而 `metadata` 是 `run_episode`
  （`core/agent/runner.py:141`）在**采集当时**写入轨迹的。
- teacher 证据是**已持久化的轨迹 JSON**：240 份
  `teacher-collection/teacher-full-001/*.json` 的
  `trajectory.metadata.system_prompt` 全部是旧 prompt（sha256 前缀 `d919602e25f2`）。
- `selection.json` 显示导出来源是 **teacher 238 / internal_reference 2**。
  只有 `internal_reference` 那 2 条走 `_build_reference_trajectory` → 实时
  `run_episode`，会拿到新 prompt。

因此改常量后重新导出，**238/240 条样本的 system 消息逐字节不变**。
`_require_evidence_binds_record` 比较的是 `task_fingerprint` / `trajectory.task` /
`dataset_version` / `bundle_sha256` / `manifest_sha256`，**都不含 system_prompt**，
所以这不会硬失败——会**静默**产出一份 99.2% 仍是旧 prompt 的 `train-export-004`，
产物看起来完全正常，而 C 的变量根本没生效。这是本轮最危险的失败模式。

**不受影响的部分**：dev 评测两侧都在运行时调 `run_episode`，读的是当前常量，
所以「新 prompt 下的 base（零训练）」这条读数——spec §4.3 标为本轮最有价值的单条
结论——完全成立，不依赖导出侧如何处理。受影响的只有 C 的 candidate 侧训练数据。

## R4 第二轮 Stage 1 的实现取舍（2026-08-13）

- **两个新变换键都做成必填，且 `sft_system_prompt_sha256` 声明的是期望哈希而不是布尔。**
  布尔值下「配置写了 `true` 但常量忘了改」会产出一份与未改写逐字节相同的训练集且
  不报错——正是本轮开工时被推翻的那个假设的同一个形状。让配置声明期望哈希，
  `export_formal_train` 拿它与当前 `runner.SYSTEM_PROMPT` 的实际哈希比对，
  不符即硬失败，把静默失效变成硬错误。
- **终局回复是独立的 assistant 消息，不与 tool_call 同处一条。** `parser.py` 把
  「文本 + 工具调用同时出现」判为 `mixed_tool_call_content`，拼进去会把已取得的
  `invalid_call = 0` 打回去。实测导出后 400 条样本里工具调用消息 `content` 非空的
  违反者为 **0**。
- **决策点未被稀释，这是可执行断言而不是推理。** 终局回复加在 `refund_order` 之后，
  决策点是 `get_order` 返回之后。实测 `train-export-002` 与 `003` 的决策点形状分布
  **都是 text 160 : tool_call 240，完全一致**。
- **`_last_successful_refund` 反向遍历取最后一次成功的退款返回。** 突变验证：改成
  正向遍历（取 `refund_recovery` 首次 `transient_error` 那次）后，
  `test_export_terminal_response_uses_the_last_successful_refund` 立即失败。
  其中「末尾那次失败则回退」的分支在当前冻结数据下**不可达**（只接受成功轨迹，
  且 REFUND 类 verifier 要求 `_refund_applied`），已用一条直接测私有变换的用例覆盖，
  不让它停留在"写了但从未执行过"的状态。
- **治理扫描列表改为「漏登记就红」。** `_R4_CONFIG_NAMES` 是手工维护的，而全部治理
  断言的价值取决于它是否完整——漏登记一份配置，那份配置就完全不受 secret / 绝对路径 /
  私有根 / BFCL / holdout 检查约束且没有任何信号。新增
  `test_every_r4_config_is_enrolled_in_the_governance_scan` 双向比对磁盘与列表，
  两个方向各经突变验证。
- **`train-export-003` 实测**：`train.jsonl`/`selection.json` 与 001 **逐字节相同**
  （`29f02425…`/`f60744f7…`）；400 行、场景计数 40/40/40/40/120/120 与 002 相同；
  末尾 role 分布由 002 的 `assistant 160 / tool 240` 变为 **`assistant 400`**——
  多步路径全部获得自然终点，这正是候选 B 要造的变化；多步 240 条各仅追加一条消息、
  单步 160 条逐字段不变。**这是输入分布的变化，不是能力证明。**

### 执行顺序的硬约束（Stage 划分的全部理由）

`SYSTEM_PROMPT` 被 `base_evaluation.py:381` 与 `sealed_evaluation.py:217` 哈希，且
`system_prompt_sha256` 在 dev 的 `PAIRING_FIELDS` 内。一旦提交 C 的常量改动，
A/B 就再也无法在旧 prompt 下评测，其配对基线 `qwen3-4b-dev-base-001` 同时失效。
又因 `_current_code_commit` 拒绝脏工作树，C 的改动连"放在工作树里不提交"都不行。
**因此 C 的全部改动（含它的两份配置）必须等 A/B 的 GPU 跑完才能进工作树**，
Stage 1 只交付 C 所需的导出侧能力，不交付 C 的配置。

## R4 第二轮 Stage 2：容量是瓶颈，前两轮的解释被改写（2026-08-14）

- **同一份训练数据，只改 `lora.target_modules`，`refund_eligible` 0/10 → 10/10。**
  候选 A 与第一轮共用 `train-export-002`（逐字节相同），唯一差别是 LoRA 从
  `[q,k,v,o]_proj` 扩到加上 `gate/up/down_proj`。这个对照排除了数据污染的解释——
  若有污染，第一轮在同一份数据上也会满分而不是 45/60。
- **"格式类改成功、行为倾向类改失败"有了正确解释**：不是"条件决策需要更均衡的数据"，
  而是**浅层输出模式能被 attention-only 的低秩更新学到，条件决策不能**。
  第一轮把决策点比例从 3:1 拉到 1:1 而 `refund_eligible` 变化精确为 0，
  原因不是"量级不够"，是容量根本不足以表达那个决策。
- **候选 B 是独立的次要信号**：容量不变，仅在多步样本末尾追加一条独立的 assistant
  终局回复，`refund_eligible` 0/10→4/10、`refund_recovery` 5/10→10/10。
  "多步路径在训练数据里没有闭环"是真实成因，但不足以单独跨过门槛。
  **A 与 B 是并列消融、未叠加，两者叠加的效果本轮没测过，不得推断。**
- **`adapter_model.safetensors` 66 MB vs 23.6 MB**，与可训练参数增至约 2.5–3 倍吻合；
  峰值显存 5.638 GB vs 5.563 GB，几乎没变——容量的代价在参数量而不在显存。
- **`verifier_reward` 首次与主判据同向**（A：0.579→1.000）。此前三次背离仍然成立，
  一次同向不足以推翻"奖励值不能代替最终状态判据"。
- **统计限度**：每类 n = 10，单条样本即 10 个百分点。A 的 `task_success_ci95` 是
  [1.0, 1.0]，那是 60/60 的退化区间，不代表 holdout 会复现。dev ≠ 发布判定。
- **延迟不可跨轮比较**：本次 GPU 空闲，第一轮为他人占用 96–98%。

### 逐场景数据的取得方式（报告本身不含）

公开 `candidate-report.json` 是 allowlist 字段集，**不含逐任务/逐类别成功数**
（`metrics` 里只有 `recovery_success` 一个类别级指标）。逐场景数字来自私有产物
`data/private/.../dev-candidate/<attempt>/trajectories.jsonl`。复算
`candidate-002` 得 45/60，与 LOG-20260811-09 记录一致，可用于验证方法。

## 候选 C 的导出：train.jsonl 会变，且这不是缺陷（2026-08-14）

新 `SYSTEM_PROMPT` sha256 = `8ae813c4284246b9700470053ba90339a3f88439d9e57905d5db704ca63283dd`
（旧值 `d919602e25f2c87c…`）。全文：

> 你是订单工具助手。只能使用提供的工具处理请求；退款前必须查询订单，遇到
> transient_error 时可以重试。确认符合退款政策后直接调用工具执行，不要再向用户征询确认。

`train-export-004` 的核验：`sft.jsonl` 与 `002` **除 system 消息外逐样本相同**
（其余消息 0 处不同、其他字段 0 处不同），system prompt 唯一且等于新常量（400/400），
决策点形状仍 160 : 240，工具调用消息 `content` 违反者 0，`selection.json` 与 001 逐字节相同。

**但 `train.jsonl` 与 001 不再逐字节相同——精确 2 行不同，全部是
`internal_reference` 来源的那两条**（`73a84baf…`、`b9a13c39…`）。原因：这两条不走
teacher 证据，而是 `_build_reference_trajectory` 用 Oracle **实时** `run_episode` 生成，
因此其 `trajectory.metadata.system_prompt` 自然是新常量。已逐字段核对：
两条轨迹除 `metadata.system_prompt` 外**完全相同**。

因此「`train.jsonl` 与 001 逐字节相同」这条验收标准**只对不改 prompt 的导出成立**
（001/002/003 都成立）。改 prompt 的导出必然有这 2 行差异，且差异本身是正确的——
teacher 轨迹是历史事实应当保持原样，实时重放的轨迹应当反映当前常量。
两者角色不同，产物层面的不一致是这个设计的正确结果，不是 bug。

## R4 第二轮收官：训练的符号由容量决定，而这个行为本不需要训练（2026-08-14）

- **attention-only LoRA 的 SFT 对 `refund_eligible` 是净负作用，横跨两个 prompt、
  四次独立训练**：旧 prompt base 5/10 → 训练后 0/10（R3、R4-1 各一次）；
  新 prompt base 9/10 → 训练后 5/10（C）。方向一致、量级相近（−4 到 −5）。
  **低秩更新只挂 attention 时，SFT 学到输出形状，代价是覆盖掉基座原有的条件决策能力。**
- **加 MLP 三投影后，同一份数据、同一组超参，训练从负作用变正作用**（5/10 → 10/10）。
  容量决定的不是训练效果的大小，而是**符号**。
- **纯 prompt 干预零训练拿到 `refund_eligible` 9/10**，且 `invalid_call` 21→0、
  `policy_violation` 8→5、`schema_valid_rate` 0.781→1.000。候选 A 的 10/10 只多 1 条，
  **n = 10 下这个差距不足以支撑"训练优于 prompt"的排序结论**。
- **但"prompt 就够了"只对 `refund_eligible` 成立**：`refund_recovery` 在两个 prompt 下
  base 都是 5/10（prompt 完全无效），四次训练后为 5/10 / 10/10 / 10/10 / 10/10。
  需要"失败后重试"的多步恢复能力来自训练数据，不来自指令。这一条阻止了把本轮结论
  过度推广成"SFT 无用"。
- **未测的组合**：A + 新 prompt、A + B、三者叠加。并列消融，**不得推断叠加效果**。
- 面试口径：这一轮的价值不在"找到了能达标的候选"，而在于用一个 base 重跑（约 200 s、
  0 次 holdout 观测）证明了**前两轮努力的方向本身是错的**——先前把 0/10 归因于数据分布，
  真实原因是容量不足导致训练反向，且该行为用一句 prompt 就能解决大半。

## R4 第三轮：prompt 与训练的贡献可以精确分离（2026-08-14）

- **同 prompt 两侧配对下，训练仍有 +0.100**（base-002 54/60 → sft-006 60/60）。
  这关掉了第二轮遗留的方法论缺口：候选 A 的 +0.200 是对照旧 prompt 的 base 取得的，
  其中混着"没给 base 换 prompt"的免费收益。
- **逐类别拆解显示 prompt 与训练几乎不重叠**：
  | 来源 | refund_eligible | refund_recovery | policy_violation |
  |---|---|---|---|
  | base（旧 prompt） | 5/10 | 5/10 | 8 |
  | + prompt（零训练） | **9/10** | 5/10（**0 变化**） | 5 |
  | + 训练（full-linear） | 10/10 | **10/10** | **0** |
  **指令能解除"判定后不敢执行"，但教不会"失败后重试"**——后者只能来自轨迹数据。
- **容量足够时 prompt 增益归零**：full-linear 在新旧 prompt 下都是 60/60；
  而零训练 / attn-only 下 prompt 分别值 +6 / +10 分。**prompt 工程的收益随可塑性递减。**
- 面试口径（这一条比任何单个数字都值钱）：项目用四次训练 + 两次零训练 base 构成
  一个 2×2 矩阵，把"提示词工程"与"后训练"的贡献分离到**类别级**，并指出两者
  各自的能力边界。这是绝大多数同类项目给不出的证据形态。

## 第二次 holdout 观测与发布判定：延迟成为唯一门槛（2026-08-14）

- **候选在 120 条封存 holdout 上 120/120**（六类各 20/20），成功率 0.8583→1.0000
  （+14.2pp），政策违规 11→0、非法调用 5→0、schema 0.9691→1.0000。
  **但发布判定仍是 NO-GO**，唯一失败门禁 `p95_latency_ratio` **1.8774 > 1.25**。
- **延迟代价的正确归因（我的第一个解释是错的）**：初看以为候选慢是"真的在执行多步任务"，
  数据否定了这一点——`average_tool_calls` 比值仅 **1.146**、`average_turns` 1.061，
  而 `average_latency_ms` 比值 **2.276**。剔除调用次数后，**单次调用耗时
  1497→2971 ms（1.985×）**。`average_output_tokens` 增长 1.429 倍不足以解释差额。
  主因是**全 linear layer LoRA 的前向开销**：7 个投影层每次都要多做低秩矩阵乘。
  旁证：第一次观测的 attention-only adapter（4 投影）p95 比值仅 **1.087**。
- **因此 R4 的终局结论是一个可量化的效果/延迟权衡**，不是"门禁不合理"：
  容量换来 +14.2pp 与满分，代价是 p95 接近翻倍。**阈值一个字未改**
  （`test_release_config_does_not_touch_the_gates` 锁定 R4 release 配置与 R3 逐字段相同）。
- **新 prompt 的效应在 holdout 上复现**：base 94/120→**103/120**，`invalid_call` 41→5，
  `schema_valid_rate` 0.7819→0.9691。这同时把 `success_delta` 的门槛从 0.8333 抬到
  **0.9083**，候选以 1.0000 通过。
- **dev→holdout 未回落**（dev 60/60 → holdout 120/120）值得记录，但不构成对未见分布的
  保证：ci95 [1.0,1.0] 是满分的退化区间，任务集是 2 工具 / 6 类 / 单一中文零售退款场景。
- 面试口径：这一枪的价值在于**系统拒绝了一个任务指标完美的候选**。它同时证明了
  发布门禁不是装饰、以及"更强的模型"未必"该上线"——这比拿到 GO 更能说明工程判断力。

## 跨规模验证：上一轮的容量结论被证伪（2026-08-14）

- **"容量决定训练效果的符号"作为一般规律不成立。** 1.7B 上方向与 4B 完全相反：

  | 模型 | 零训练 | attention-only | 全 linear |
  |---|---|---|---|
  | 4B | 54/60（elig 9/10） | 55/60（elig 5/10） | **60/60** |
  | 1.7B | 44/60（elig **0/10**） | **58/60** | 45/60 |

- **1.7B 全 linear 的失败形态是关键**：15 条失败**全部**是"该拒绝却没拒绝"
  （`refund_denied_ownership` 10/10 全灭、`window` 5/10），`policy_violation` 0→5，
  `average_tool_calls` 1.267→2.083。模型被训练成"什么都调 refund_order"——
  **不是没学会，是学过头**。attention-only 在 1.7B 上恰好起到正则作用。
- **替换后的规律**：**LoRA 容量必须与模型规模匹配，不存在"越大越好"。**
  容量不足学不会条件决策（4B + attn：elig 被压到 5/10）；容量过剩被训练数据的类别偏向
  带跑，牺牲与主偏向相反的能力（1.7B + full：拒绝类崩塌）。
- **连带结论（改变后续做法）**：**数据配比与 LoRA 容量耦合，不能独立调。**
  `train-export-004` 沿用第一轮为提升 elig 做的 ×3 oversample，使"执行:拒绝" = 240:120
  = 2:1。该偏向在 4B 无害、在 1.7B + 过剩容量下致命。今后调 oversample 必须连同
  `target_modules` 一起评估，当作**一个二维选型**。
- **第二条被限缩的结论**：**"一句 prompt 解决大半"是模型规模依赖的。** 新 prompt 对 4B
  有效（elig 5/10→9/10），对 1.7B **完全无效**（0/10）——小模型的指令跟随能力不足以
  消费那句显式授权，而训练对它极其有效（0/10→10/10）。因此 prompt/训练分工的结论
  **只在 4B 成立**。
- 方法口径：跨规模只比"训练相对同规模零训练 base 的符号与量级"，1.7B 的 58/60 与 4B 的
  60/60 **不可直接相比**（不同基座）。全部 dev，未触碰 holdout。

## 架构补强轨道：冻结契约影响矩阵（2026-08-15，纯 CPU 静态核查）

提示词 `docs/handoffs/2026-08-15-architecture-hardening-execution-prompt.md` 第 2 节要求的
前置产物。**13 条评审问题的证据位置已逐条复核，全部属实**（`GATE_IDS` 五元组被两个
report 模型同时断言、`policies.yaml` 的 `rules` 在 `src/` 零引用、`_user_request` 只有
12 句模板、`parser.py` 的两条非法判定、`serve` 只有预置任务端点、`refund_order` 无
幂等键、`perturb_schema` 零调用）。

### 矩阵

| 改动项 | 触碰的哈希字段 | 需重跑 dev base | 使 sealed base 失效 |
|---|---|---|---|
| 1.1 serve 服务化（只加 `create_formal_app` 端点） | `code_commit` | 否 | 是 |
| 1.2 CI workflow + Dockerfile | `code_commit`（若不改 `uv.lock`） | 否 | 是 |
| 1.3 文档单一事实源 + `sft-006` 模型卡 | `code_commit` | 否 | 是 |
| 1.4 `verifier_reward` 移出主表（只改呈现层） | `code_commit` | 否 | 是 |
| 3.x 门禁版本化（**不动 `release.yaml`**，见下） | `code_commit` | 否 | 是 |
| 2.1 政策外置（`policies.yaml` + prompt 由 bundle 渲染） | `bundle_sha256`、`system_prompt_sha256`、`code_commit` | **是** | 是 |
| 2.2 幂等键（`tools.yaml` 增必填参数） | `tool_schema_sha256`、`bundle_sha256`、`code_commit` | **是** | 是 |
| 2.3 guardrail 层（不改 bundle 时） | `code_commit` | 否 | 是 |
| 4.1 分布外 holdout（独立 dataset artifact） | 新 `dataset_version`，不触碰现有三字段 | 否（自带 base） | 否 |
| 4.2 serving 形态对照（若装 vLLM） | `uv_lock_sha256`、`code_commit` | 否 | 是 |

**"使 sealed base 失效"整列为是，是本轮第一次提交就发生的一次性代价**，后续提交不再
追加代价——`code_commit` 与 `uv_lock_sha256` 都在 `SEALED_PAIRING_FIELDS` 内。第三次
封存 holdout 观测因此必然是 base + candidate **两侧**重跑，属用户单独决策门。

### 提示词未展开、本次核查新增的两条硬约束

**(e) `bundle_sha256` 把 `release.yaml` 也算进去了——这改变了批次 3 的可行路径。**
`domain/bundle.py:109-120`：`component_sha256` 是 `bundle.yaml` / `tools.yaml` /
`policies.yaml` / **`release.yaml`** 四个文件哈希的 mapping，`bundle_sha256` 是该 mapping
的 canonical JSON 哈希。而 `bundle_sha256` 同时在 dev `PAIRING_FIELDS` 与
`SEALED_PAIRING_FIELDS` 内。
→ **在 `release.yaml` 里新增任何一个门禁参数，都会使全部已有 dev/sealed 证据不可配对，
并要求重跑 dev base**。提示词 §6.4 断言"批次 3 纯 CPU 即可完成"**只在 `release.yaml`
逐字节不变时成立**。
→ 因此 v1.1 门禁集合的实现约束是：`ReleasePolicyConfig` 的五个阈值字段与
`domains/retail_ops/v1/release.yaml` 逐字节不变，新门禁只能复用这五个阈值或使用
schema v1.1 语义自带的结构性常量（如 CI 下界 ≥ 0），并用测试锁定这一点。
另注：`ReleasePolicyConfig` 是 `StrictModel` 且 `schema_version` / `policy_version` /
`invalid_call_count_max` / `require_complete_evidence` 都是 `Literal`，就地加字段还会
让**已提交的 `release.yaml` 本身**无法通过校验。

**(f) `SealedEvaluationReport` 不含逐任务结果，配对统计检验无法从公开 sealed 报告重算。**
公开 sealed 报告是 allowlist 字段集（`metrics` 是聚合量），刻意不含 task 级信息。
McNemar / 配对 bootstrap 需要逐任务的 base↔candidate 配对结局，只能来自私有
`sealed-eval/*/trajectories.jsonl`。
→ 本地实际可用的私有逐任务产物**只有第一次观测**
（`data/private/.../sealed-eval/qwen3-4b-holdout-{base,candidate}-001/`）；
**第二次观测（`-002`）的私有轨迹不在本地**，`reports/retail_ops/v1/r4/holdout-*-002/`
只有 `sealed-report.json`。第二次观测的新口径重算需要先从 gpu-5090 回传私有产物
（外部执行门 7），或接受"该门禁在证据不足时判 FAIL"的保守语义。
→ 设计取向：v1.1 的统计门禁接受可选的逐任务配对输入，缺失时观测值记为
`insufficient_paired_evidence` 且 `passed=False`——保守方向与"不因缺证据放宽门禁"一致。

### 单次调用延迟可从聚合量复算，不需要逐任务数据

`average_latency_ms / average_tool_calls`：base-002 = 1958.26/1.3083 = **1496.8 ms**，
candidate-002 = 4457.06/1.5000 = **2971.4 ms**，比值 **1.985**——与 LOG-20260814-04 记录的
归因逐位一致。因此 `per_call_latency_ratio` 门禁可从**已有公开 sealed 报告**直接重算。
**预判（在实现前写下，避免事后合理化）：新口径不会把第二次判定从 NO-GO 翻成 GO**，
因为 1.985 > 1.25 仍然失败；拆分只是把失败归因从"更慢"精确到"单次前向更慢"，
并让 `steps_to_success` 侧证明候选**没有**靠多调用换成功率。

### 执行顺序结论

1. 批次 1 与批次 3 都不触碰 `bundle_sha256` / `system_prompt_sha256` / `tool_schema_sha256`，
   可以在同一轮里连续做完再一次性提交（合并成一次 `code_commit` 变更，代价最小）。
2. 批次 3 的新口径必须在**看到任何新读数之前**定稿并提交——因此不得在实现前打开
   `sealed-eval/*/trajectories.jsonl`。本次核查只读了公开聚合 `metrics`（其数值早已在
   `CLAUDE.md` 与 LOG-20260814-04 中公开记录）。
3. 批次 2 三项必须成组做完、一次提交、一次重跑 dev base；拆开做会多烧两次 GPU。

## 架构补强轨道批次 1+3 的实现级发现（2026-08-15，纯 CPU）

**(g) `run_id` / `report_id` 不是跨机器可复现的。**
`RunEvidence.run_id` 是全字段自哈希，而 `metrics` 里含 p50/p95 延迟与 token 计数——
机器相关。本机重跑 R1 全链路得到 `348b046f…`，而 2026-07-21 落盘的是 `376e0d2c…`，
`bundle_sha256` 与 `task_manifest_sha256` 则**逐位一致**。
→ 自哈希保证的是"这份证据文件没被改过"，**不保证跨机器逐位重建**。
`scripts/ci/verify_qualification_chain.py` 因此只断言内容哈希 + 决策 + 确定性指标
（`task_success` / `policy_violation_count` / `invalid_call_count`），不断言 `run_id`；
否则一台更快的机器会被报成"链条漂移"。这条区分以前没有任何地方写清楚。

**(h) 自由请求端点必须与"有真值的评测"在类型上分开。**
`run_episode` 在 `verify_final_state()==1.0` 时终止，而自由请求没有 `target_state`。
做法是给 chat 任务一个**永远不可能达成**的 target（`{"__no_ground_truth__": true}`），
使 `final_state` 恒为 0，episode 只能由最终答复 / 步数上限 / 政策违规终止；响应里
**删掉 `success`** 并给出 `ground_truth: false`。
填一个恒假的 `success` 比不填更糟——下游会把它读成"这次请求失败了"。

**(i) 超时不能假装能中断生成。**
HF `generate` 是同步阻塞调用，无法从外部杀死。实现是：单 worker 线程池 + 信号量，
超时立刻返回 504，但**信号量直到那次生成自然结束才释放**。于是后续请求得到 503，
而不是把第二份工作压到同一张卡上。这是诚实的降级，不是"取消了那次生成"。

**(j) v1.1 门禁在设计阶段就写下了预判，避免事后合理化。**
拆分后第二次观测**仍应是 NO-GO**：`per_call_latency_ratio` = 1.985 > 1.25。
拆分只把失败归因从"更慢"精确到"单次前向更慢"，并让 `steps_to_success_ratio` 侧
证明候选**没有**靠多调用换成功率。复算在提交之后进行，届时与此处预判对照。

**(k) 配对统计检验的证据来源受限（承接 (f)）。**
`success_delta_ci_lower` 需要逐任务配对结局，公开 sealed 报告没有。CLI 因此新增
`--baseline_trajectories` / `--candidate_trajectories` 两个**成对**可选参数指向私有
`trajectories.jsonl`；只给一侧直接报错（不降级），两者都不给则该门禁判 FAIL。
本地只有第一次观测的私有轨迹，第二次观测的需从 gpu-5090 回传。

**(l) `perturb_schema` 的对照只有换掉策略才有信息量。**
原有三个 qualification 策略（oracle / baseline / unknown_tool）全部硬编码工具名，
在扰动下必然全灭——那只是复述"改了名字就找不到了"。新增 `schema_adaptive`：按
**参数键集合**在当前工具清单里唯一匹配（`{order_id}` / `{order_id,reason}` / `{city}`
互不相同，匹配唯一），扰动前后都是 12/12。解析不到时**原样发出 gold 名字**让它以
`unknown_tool` 可见失败——静默换一个工具会让报告看起来"schema 兼容"，其实是被兜住了。
另外：重放必须用与运行时**相同**的扰动种子，否则 `replayable_rate` 会假性下降。

## 部署形态才是第二次 NO-GO 的主因（2026-08-15，gpu-5090，dev 60 条）

- **合并 LoRA 之后单次调用耗时 3063.9 → 1653.7 ms（−46%），吞吐 28.38 → 50.74 tok/s
  （反超基座 48.89），而 `task_success` 60/60、`average_tool_calls` 1.5000 一字未变。**
  行为完全一致，改变的只有前向路径。
- **最大的风险没有兑现**：「基座 NF4 + LoRA」与「合并后再 NF4」不是同一组权重，
  合并 + 重新量化本可能损伤模型。dev 上没有：六类失败分布为空。
- **但这不足以宣布延迟问题解决**，四条限制缺一不可：
  (a) dev 不是 holdout，且 dev 已被用于选出该候选；
  (b) **旧 v1.0 口径下合并版在 dev 上仍失败**（p95 比值 1.3130 > 1.25）——v1.1 的 8/8
      是"合并 + 口径拆分"共同作用，不是单靠合并；
  (c) `latency_per_success_ratio` 1.2498 对 1.25，只差 2e-4，擦边；
  (d) 同一 adapter 的延迟比值 dev 2.30 / holdout 1.88，**dev 不可外推 holdout**。
- **面试口径**：这一步的价值不在"救回了候选"（没有，发布判定仍需第三次 holdout 观测），
  而在于把一个被写进交付文档的模型结论（"容量换效果的代价是 p95 翻倍"）**降级为部署
  实现问题**，并用同一份权重的两种加载方式给出可复算的证据。先归因、再验证归因，
  而不是直接换模型。

### 实现级注意点

- **不要在 4-bit 权重上 merge**：那会先反量化再合并，把量化误差固化进合并结果。
  正确做法是 bf16 合并 + 评测时统一量化，两侧走同一条量化路径。
- **合并产物不能冒充上游 pin**：`ModelArtifact.revision` 只要求 7–64 位十六进制，
  用「基座 revision + adapter 逐文件哈希」派生一个确定性标识，`repo` 写 `local/…`。
  直接抄基座 revision 会让"这权重是官方那一份"变成假话。
- **provenance 必须放模型目录之外**：`verify_local_model_files` 要求目录内容与锁定清单
  精确相等，多一个文件就失败。写成同级 sidecar `<dir>.provenance.json`。
- **合并版走 `formal_dev_base` 而不是 candidate 通道**：合并后模型里已经没有 adapter，
  candidate 通道会要求一个不存在的 adapter pin。代价是它与 `base-002` 的 `model` 字段
  不同，`compare_dev_runs` 会（正确地）拒绝配对——跨形态对照只能比绝对值。
- **轮询远程进程别用 `pgrep -f <pattern>`**：ssh 命令行本身含该 pattern，pgrep 会
  自匹配，导致"永远 RUNNING"的假阳性（本次两次都踩到）。用 `[p]attern` 形式。

## 批次 2：政策外置 / 幂等键 / guardrail（2026-08-15，纯 CPU，落在独立 v2 bundle）

- **v1 逐字节不变**（`bundle_sha256` 仍是 `8c158a30…`，有治理测试锁定）。用户裁定
  "打新版本号、新旧并存"而不是迁移轨迹——teacher 证据是已持久化的历史事实，
  回填参数等于改写它；且改 v1 一个字节就让全部已有 dev/sealed 证据不可配对。
- **政策引擎只有一条求值路径，两种规则来源**：v1 的六个名字解析到内置冻结规则集，
  v2 的规则内联在 YAML。不是两套实现。混用名字与内联被显式拒绝。
- **`_refund_order` 的交错顺序是契约**：未查询规则 → `not_found` → 其余规则。
  「订单不存在」不是政策判断而是可见性事实；把它塞进规则集会让规则语义变浑。
  订单为 None 时事实给**合规**默认值，否则某条规则会凭空命中、把 not_found 报成违规。
- **幂等重放必须先于政策规则求值**：同 key 重复调用不是新请求而是重试，放在规则之后
  会被 `duplicate_refund_forbidden` 拦下——那正是 v1 分不清"客户端重试"与"再退一次"
  的缺口。缓存里只有**已成功**的 key，因此重放不可能绕过任何一条当初通过了的规则。
- **guardrail 改了 replay 的前提**：guardrail 会消毒观测、也会拦调用，两者都写进轨迹。
  用不带 guardrail 的环境重放一条带 guardrail 的轨迹必然 `ReplayMismatch`——那不是证据
  损坏，是重放条件没对齐。`replay_trajectory` 因此新增 `guardrail_factory`，且**每次
  重放构造新实例**：guardrail 持有会话级作用域，复用会把上一次的授权带进来。
- **注入对照的实测（12 条 qualification，纯 CPU）**：未防护 10/12 被注入（0.83）、
  `task_success` 0.6667、政策违规 4；防护后 **0/12**、`task_success` 1.0000、违规 0、
  可重放 1.00。**这度量的是上下文污染，不是任何真实模型的易感性**——探针策略只有
  真的读到那句指令才会动干扰订单。真实模型的注入成功率需要 GPU 评测，未做也不声称。
- **注入不只是"多调一次工具"**：未防护侧掉了 4 条任务并产生真实政策违规——被注入的
  调用会撞上环境的归属/重复规则。**两层都拦到**正是纵深防御的样子。
- **政策卡渲染必须是纯函数**：不读时间、不读环境变量、不遍历无序容器。
  `system_prompt_sha256` 在两套配对字段内，一个不稳定的渲染会让配对契约变成不可复现的，
  那比不渲染更糟。v1 逐字节返回冻结常量，一个字都不加。
- **边界**：正式数据集轨道仍只接受 v1（`formal_manifests` 显式拒绝其它版本）。
  v2 至今只在 qualification 轨道跑过，**没有任何真实模型在 v2 上跑过**。

## P1-6 方案 A：多轮澄清（2026-08-15，纯 CPU）

- **三组对照缺一不可**：不欠指定/无模拟器 **1.0000**（证明策略本来就能做对）、
  欠指定/无模拟器 **0.0000**（证明缺口是真的）、欠指定/有模拟器 **1.0000**、
  平均轮次 1.00 → 3.17、可重放 1.00。只跑第三组会在缺口不存在时也通过。
- **模拟器必须是规则式的**：LLM 模拟用户会让每次运行的用户侧输入都不同，
  `replay_trajectory` 直接失效，配对比较也不再成立。自然度换可重放性——对一个以
  证据链为核心主张的项目，这个取舍没有第二个答案。
- **又一次撞上"运行条件必须能被重放复现"**：模拟器决定一句"最终答复"是提问还是收尾，
  而只有收尾的那一句才被 `record_final_response`，这直接改 `verify_final_state`。
  不带模拟器重放多轮轨迹会在 **reward** 字段上不一致（guardrail 那次是在
  **observation** 上）。两次都不是证据损坏，是重放条件没对齐——这条已经出现两次，
  应视为该架构的一般规律：**任何新增的 episode 级可注入缝，都必须同步进 replay。**
- **澄清提问不得记成最终答复**：否则 INFORM/DENY 类任务凭一句反问就判成功
  （有专门测试锁定：欠指定/无模拟器时 `task_success` 必须是 0.0000）。
- **模拟器只回答用户本来就知道的事**（metadata 里的订单号），刻意不从 `expected_calls`
  / `target_state` 取值——那些是判定依据，从它们取值会让多轮变成泄题。
- 未做且不假装做了：工具面仍是 3 个、parser 仍禁并行调用与 thinking、无工具检索、
  多轮**政策冲突**（τ² 的另一半）未做。逐条列在 `docs/AGENT_LOOP.md`。

## 第三次封存 holdout 观测：合并部署形态把差距拉进门槛内，但拿不到判定（2026-08-15）

- **三次运行同 commit `b529bc9`**：base-003 / candidate-003（未合并）/ merged-003（探针）。
  base 与 candidate 相对第二次观测除 `attempt_id` 外逐字段相同，有治理测试锁定。
- **任务指标跨 commit 逐位复现**：base-003 与 base-002 的 `task_success` 0.8583、
  违规 11、非法调用 5、schema 0.9691 完全相同；candidate 同为 120/120。
  确定性在代码大改之后仍然成立——这是本轮质量门之外的一条独立证据。
- **第三次判定：v1.0 与 v1.1 都是 NO-GO**（未合并候选）。
  v1.0 失败 `p95_latency_ratio` 2.0250；v1.1 失败 `per_call_latency_ratio` 2.1209 与
  `latency_per_success_ratio` 2.0871，而 `success_delta_ci_lower` **+0.0833 PASS**、
  `steps_to_success_ratio` **0.9841 PASS**。
- **合并版在 holdout 上同样 120/120、零违规、零非法调用、`average_tool_calls` 与未合并
  版完全相同（1.5000）**。单次调用 2946.5 → **1717.7 ms**，p95 比值 2.0250 → **1.2141**，
  吞吐 29.78 → 48.87 tok/s（基座 50.66）。把候选侧换成合并版后，v1.0 与 v1.1 的门禁
  算术**全部通过**。
- **但那不是判定，也拿不到判定**：`require_comparable_sealed_runs` 要求
  candidate = 同一基座 + adapter；合并版两条都不满足。要让它可判定，必须版本化
  `SealedEvaluationReport`，而 `report_id` 是全字段自哈希——需要**版本感知的内容哈希**
  才能让两份旧 sealed 证据仍可加载。这是一次独立决策，本轮未做。
- **余量薄到必须写进每一处引用**：1.2141 / 1.2364 对 1.25 只剩 3% 和 1%；而 base 侧
  p95 在观测 2 是 3052.2 ms、观测 3 是 2787.4 ms——同机同配置 **9% 的波动**。
  一次重跑就可能翻到另一侧。正确表述是"延迟主因已定位并已消掉大部分，余量仍薄"，
  不是"延迟问题已解决"。
- **本次观测消耗了三次运行**。合并版探针只为测部署形态，但它同样产出任务指标、
  同样读了 holdout，因此如实计入消耗，不做"只算延迟不算观测"的记账。

## vLLM 第四档的环境约束（2026-08-16，gpu-5090）

- **vLLM 必须装在独立 venv**：`uv_lock_sha256` 在 `SEALED_PAIRING_FIELDS` 内，装进项目
  环境会让全部已有 sealed 证据不可配对。因此它的读数是**旁证**，不产出 run evidence、
  不进任何发布判定。已核实：安装后项目仓库 `git status` 干净。
- **vLLM 0.27.1 需要 Python ≥ 3.12**：3.11 下 `flashinfer/comm/fd_exchange.py` 在模块级
  用了 `array.array[int]` 注解，而 `array.array` 从 3.12 起才可下标，
  引擎在 `load_model` 阶段以 `TypeError: type 'array.array' is not subscriptable` 崩溃。
  换 3.12 后 `vllm 0.27.1 / torch 2.13.0+cu130` 正常导入。
  这条与项目本身的 Python 3.11 约束**不冲突**——正因为它在独立 venv 里。
- **基准提示词只用 R1 qualification 的 12 条公开 fixture**（token 数 420–435，
  与真实评测同量级）。不用 holdout/dev 请求：那些是评测输入，复制进临时基准文件会绕开
  公开/私有边界的全部治理。
- **共享卡上的礼貌**：`gpu_memory_utilization=0.35`（约 11 GB）而不是默认 0.9。
  这会限制 KV cache 从而影响批量吞吐的绝对值——报告时必须带上这个参数。

## triton 缓存跨 venv 污染，把项目自己的 HF 评测路径打挂了（2026-08-16，已修复）

**这是本轮唯一一次真正弄坏了东西，且是我造成的。记在这里因为它会再发生。**

**现象**：跑完 vLLM 基准后，项目 venv 里任何一次 `TransformersBackend.generate`
都崩在 `RuntimeError: Failed to find C compiler`。连零训练基座 + 一句"你好"都跑不了。
几小时前（8-15 23:59）的 OOD 正式评测还是好的，项目 venv 与 `uv.lock` 均未改动
（`uv lock --check` 通过，`site-packages` 的 mtime 停在 8/5–8/6）。

**机制**（已验证，不是猜测）：

1. torch 2.13 的 `torch._native` 会把 `bmm_outer_product` 派发到 triton 实现，
   于是 Qwen3 的前向**必然**初始化 triton；triton 首次运行要编译一个
   `cuda_utils` 扩展。
2. triton 的缓存键**只含源码与 triton 版本，不含 Python ABI**。两个 venv 的
   triton 都是 **3.7.1**，因此项目（3.11）与 vLLM venv（3.12）落到**同一个键**
   `MIH4X24…`，而目录里的 `.so` 文件名带 ABI（`cuda_utils.cpython-3XX-….so`）。
3. 后跑的一方覆盖前一方。我的 3.12 运行之后，缓存里只剩 312 版；
   项目的 3.11 找不到自己那份，转而重新编译。
4. **这台机器没有 C 编译器**——`dpkg` 里只有 `cpp` 预处理器与 `gcc-*-base`，
   没有 `gcc` 本体。于是重编译必然失败。

**决定性证据**：修复后同一个键 `MIH4X24…` 下变成 `cuda_utils.cpython-**311**-….so`，
项目路径恢复；两个版本映射到同一个键因此得证。

**修复**（两条都必要）：

- 用**用户态**编译器补回缺失的构建能力：`/mnt/aidata/tongjiakai/cc-venv` 里装
  `ziglang`，`$D/bin/cc` 是个 shim。zig cc 自带 sysroot、不搜索系统库目录，
  因此 shim 要把 triton 传的 `-l:libcuda.so.1` 改写成绝对路径
  `/usr/lib/x86_64-linux-gnu/libcuda.so.1`，否则 `ld.lld` 报 unable to find library。
- **给 vLLM 侧单独的 `TRITON_CACHE_DIR`**（`run_vllm_bench.sh` 已固化）。
  项目保持默认 `~/.triton/cache`——让入侵者搬走，而不是让项目依赖额外环境变量，
  否则哪天忘了设就又挂了。

**教训（会改变后续做法）**：在这台机器上引入**任何**第二个 Python 版本的深度学习
环境之前，先把它的 `TRITON_CACHE_DIR` 隔离掉。共享缓存 + 无编译器 = 一次运行就能
让另一个环境永久失效，而症状（"找不到 C 编译器"）完全不指向真正的原因。

## 第四档的读数（2026-08-16，gpu-5090 物理 GPU 0）

同一批 12 条公开 qualification fixture、同一份合并权重、同一套贪心契约，
三侧输出 token 总数**都是 390**，工具调用与文本 **12/12 全同**：

| | HF+NF4 | HF+bf16 | vLLM+bf16 |
|---|---|---|---|
| mean / p50 / p95 (ms) | 675.97 / 633.70 / 1078.70 | 411.66 / 370.64 / 817.23 | 203.51 / 199.99 / 220.39 |
| tok/s | 48.08 | 78.95 | 159.70 |

- **3.32× 是乘性的两段**：去量化 1.64× + 换引擎 2.02×。前一段不需要新依赖。
- 批量 12 并发冷启 1375.38 tok/s；prefix caching 值 **+57.5%**（对照组：关掉后
  第二遍 861.16 与第一遍 873.11 持平）。
- HF+NF4 在这 12 条上的 48.08 tok/s 与封存 holdout 观测 3 的 48.87 tok/s 几乎相同，
  说明这个微基准在吞吐维度上是有代表性的（延迟维度**不可**跨集合比较：
  输入 428 vs ~1067 token、输出 ~32 vs ~126 token）。

## 引擎替换的正确性（2026-08-16，三组 × 两引擎）

详见 `docs/ENGINE_SUBSTITUTION.md`。要点：

- **我此前的判断错了，且字段找错了**：`uv_lock_sha256` 哈希的是仓库里的 `uv.lock`
  文件（`product_cli.py:1500`），不是实际装了什么包——换 venv 跑它**发现不了**。
  真正拦住 vLLM 的是 `GenerationSettings.quantization: Literal["nf4"]` 加上
  `_require_backend_matches_pin` 的逐字段比较。让 vLLM 也跑 bnb NF4，契约一字不改。
- **结果**：dev/合并候选 1.0000 vs 1.0000；OOD/合并候选 0.5833 vs 0.5833（逐类别、
  逐 kind、失败分布全同）；**OOD/零训练基座 0.2167 vs 0.2333——不一致**，
  差异全在 `colloquial` 一个 kind（失败 2→1）。
- **机制**：基座约 47 次调用里 44 次非法，输出本就在合法/非法边界上；两个引擎的 NF4
  算子实现不同，数值微差足以把边界样本推到另一侧。训练过的模型输出决断，推不动。
- **吞吐（同为 NF4，纯引擎效应）**：三组分别 4.86× / 4.84× / 4.89×，稳定在 ~4.85×。
  **与第四档微基准的 2.02× 不一致且必须一起看**——那里是 bf16 对 bf16 的单轮 fixture，
  这里是 NF4 对 NF4 的真实多轮任务。HF 的 bnb NF4 前向要逐次反量化，相对代价远大于
  bf16。**"引擎快多少"不是一个数**，取决于量化方式与工作负载。
- **连带发现的一个 bug**：`--engine` 最初只接进 OOD 通道，dev 通道**静默回落**到
  transformers——证据看起来完全正常却不是那个引擎跑的。已修并加回归测试。
- **`peak_memory_bytes` 跨引擎不可比**：HF 是进程真实峰值（3.02 GB），vLLM 是整卡
  NVML 水位（15.65 GB，含预占池与同卡他人进程）。`CudaHardwareProvider` 在 vLLM 下
  先是抛 `Invalid device argument`（父进程没 CUDA 上下文），强行初始化则恒为 0——
  那个 0 会被写进证据，比报错更糟。

## 证据现在记得住"跑在哪里"（2026-08-16，补 `uv_lock_sha256` 的盲区）

- **缺口**：`uv_lock_sha256` 哈希的是仓库里的 `uv.lock` **文件**
  （`product_cli.py:1500`），不是实际装了什么包。本轮三次 vLLM 评测跑在完全不同的
  venv 里，证据却逐字段声称用的是冻结依赖，**没有任何机制发现得了**。
- **做法**：新增 `inference_engine` 与 `runtime_env_sha256`（实际安装包集合的摘要），
  要么两个都记要么都不记——半份记录回答不了"跑在哪里"。
- **刻意不用 `schema_version` 承载这次演进**：`CandidateRunEvidence` 早已把它当作
  **类型判别符**（固定 `"1.1"`，使 base 的严格模型无法加载候选证据，反之亦然）。
  再叠演进语义会让同一个 `"1.1"` 表示两件事，且会改变磁盘上已有候选证据的哈希投影。
  改成 **"取值为 None 即不参与内容哈希"**：旧证据加载后两字段为 None，复算逐位不变。
  gpu-5090 上对 **48 份**已有证据全量复算：**0 不匹配**。
- **踩到并修掉的一个真缺陷**：第一版用 `importlib.metadata.distributions()`，
  它沿 `sys.path` 搜索，量的是"当前能 import 到什么"。结果同一个 vllm venv 里
  OOD 记下 `60dd5028…`、dev 记下 `3a5c65b5…`——**这个字段变成了噪声，比没有更糟**
  （它看起来像个可比的标识）。改按 `sysconfig` 的 purelib/platlib 扫描后，
  三次评测记下同一个摘要，读数也逐字复现（0.5833 / 0.2333 / 1.0000）。
- **仍未做**：`SealedEvaluationReport` 未加这两个字段。封存轨道至今只在 transformers
  上跑过，且改它需要 v1.2 版本化——那是独立决策。

## 2026-08-16 — R5 收口

### 独立重建复验（SPEC §6 第 6 条）

- 原 `sft-006` 用的是 `seed: 0`（从 `reports/.../r4/sft-006/config.yaml` 读到）。
- SFT 的 CLI 入口是 `build --config <sft.yaml> --seed N --input_dir <私有数据根> --output_dir`，
  **`--input_dir` 是必填**（`product_cli.py:1396`），私有数据根是
  `data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722`。首次起跑漏了它，硬失败退出。
- `formal_dev_candidate` **冻结 `--seed 0`**（`product_cli.py:1118`），
  评测侧的 seed 与训练侧的 seed 是两个不同的东西，不要混。
- 排除混淆的三条核对：`src/veritool_rl/training/` 最后改动 `c466b64`（2026-08-09），
  **早于** sft-006 的 8-14 训练；`train-export-004/sft.jsonl` SHA-256 `9ef21dcc…` 一致；
  解析后 `config.yaml` 与原次逐行 diff **只差 `adapter_dir`/`output_dir` 两行**。
- 结论：同 seed 产出的 adapter 权重逐位不同（`8a49251f…` vs `c93c6698…`）。
  dev 读数 60/60 → 58/60，**两条失败都是 `refund_recovery` / `recovery_failure`**。

### 公开发布审计

- 第一版按**文件文本**扫描绝对路径与 holdout 真值键名，产生 14 条误报：
  配置注释里的溯源、测试里作为坏输入的 `/data/TJK/...`、源码里的 `reference_trajectory`
  字段名。**"提到"与"取值"是两件事**——改为扫 YAML/JSON 解析后的取值后归零。
- 上游 BFCL 的 `*_result.json` 实际是 **JSON Lines**，`json.loads` 直接失败。
  审计里不能"解析不了就跳过"，要换正确的解析方式，否则那些文件永远不被扫描。
- 审计脚本与它的负测试**必然**包含凭据形态字面量，只能豁免这两个文件；
  豁免清单本身被测试钉死为恰好两项。

### teacher client 的超时缺口

- `_classify_retryable` 把超时归类为可重试（`teacher_client.py:237` 附近），
  但 `from_route` 构造 `OpenAI(...)` 时**没有传 `timeout` 也没有传 `max_retries`**。
  openai SDK 的默认超时是 600 s。519 次请求的采集里一次挂起 = 10 分钟静默停摆。
- SDK 层重试上限与采集层（`TeacherCollectionConfig`）重试上限**相乘**才是最坏请求数，
  必须是两个分开且都有界的旋钮。

### 文档漂移的结构性原因

- `test_no_active_doc_restates_a_stale_observation_count` 的 `checked` 列表
  **不含 `AGENTS.md` / `CLAUDE.md`**，所以"两次观测"从 R4 一路留到 R5 才被发现。
  治理测试只覆盖它列出的文件——**新增活动文档时必须同时加进这类扫描列表**，
  否则治理是有洞的。

## 2026-08-20 — R8 D2（B2 CI 真跑 + C1 跨域）

### B2 CI 真跑：诚实口径的反转

- 用户 2026-08-20 授权公开发布门（remote `https://github.com/emmmdty/retail-agent-ops.git`）。
  push 后 GitHub Actions 首次真跑（commit `596eee8`，11 步全绿，2m12s）。
- **治理测试必须同步反转**：`test_ci_and_container_exist_and_do_not_overclaim` 此前
  断言 workflow「必须写未跑过」；CI 真跑后这条断言变成**逼着文档撒谎**——
  改成「不得仍声称未跑过」+ 指向 `docs/CI_EVIDENCE.md`。这正是项目反复抓的那类
  失败：**约束在现实变后会反向**，"未跑"从诚实变成造假。
- **两个干净环境的 skip 数差 1**：本地干净 clone 1126 passed / 46 skipped（有 ffprobe），
  GitHub runner 1125 passed / 47 skipped（无 ffprobe）。两者 passed+skipped 都等于
  收集总数。`test_the_author_environment_baseline_never_appears_without_the_clean_clone_one`
  锁住的就是「写作者基线必须同时披露干净 clone 基线，且 passed+skipped 必须等于
  收集总数」——差异在环境不在代码。
- 干净 clone 的数字必须**实跑**而非推算：先写预期值（1199/1153-46），再 clone 到
  /tmp 实测，对上才落进文档。CI 在 GitHub runner 上的跑本身就是一种干净 clone 证据
  （公开 URL 可审计）。

### C1 flight_ops 跨域：build/evaluate 层的耦合结构

- `retail_ops.build.teacher_data.collect_teacher_attempt` **本身是泛型的**：只依赖
  `env_factory`（造环境）、`record.task` + `record.task_fingerprint`、`run_episode`/
  `replay_trajectory`（都在 core）。它不引用 `RetailOpsEnv` 或 retail_ops 特有类型。
- 但 `teacher_client.py` / `teacher_route.py` 住在 `retail_ops.build` 下，且
  `teacher_data.py` import 它们。flight_ops 若直接 import 这两个模块就**违反 one-way
  依赖**（flight_ops 不得依赖 retail_ops）——于是跨域可移植性在 build 层卡住。
- **实际执行**：lift teacher_client/teacher_route 到 core.build/（2026-08-20），留
  re-export shim。零回归（1199 tests 全绿）。flight_ops build 层自己写最小 collection
  loop 调用 core primitives——transport 在 core（证明端口能力），orchestration 在域
  层（诚实——每个域有自己的数据管线）。
- flight_ops evaluate 层：FlightRunEvidence 的 report_id 排除 runtime_seconds（wall clock
  不可复现，不进 tamper-evident hash）。OraclePolicy 是 per-task 的——不能跨 task 复用
  同一个 policy object（第一个 task 用完 index 后后续 task 全跳过）。改 run_evaluation
  接受 `policy_factory: Callable[[TaskSpec], Policy]`，与 env_factory 模式对齐。
- recovery 场景的 expected_calls 必须包含**两次** rebook_flight（第一次 transient fail，
  第二次 succeed）。oracle 逐个回放不重试；测试里的 retry 逻辑会破坏第二次调用。

### C1 flight_ops 任务生成器的简化选择

- flight_ops 不复制 retail 的 5 指纹 family pairing：那套是 retail 有封存 holdout 时的
  反污染机制；flight_ops 无封存（C1 是可移植性证明不是发布判定），更简单的
  train/dev split + 内容哈希是诚实而非偷工。已在 task_plan R8 D2 非目标写明。

## C2 退化曲线：工具数 6→15 不导致退化（2026-08-21，gpu-5090）

- **退化曲线平坦**：N=6/9/12/15 四个断点全部 task_success=0.45、pv=0、tool_acc=0.70。
  曲线无下降趋势。{3} 断点复用 sft-008（v1 的 3 工具训练），{6,9,12,15} 各新训一个
  Qwen3-4B QLoRA 候选。
- **归因**：teacher（MiMo-V2.5）质量充足，4B 模型在 6~15 工具规模上能力足够，
  未观察到工具选择退化。但 0.45 的 task_success 较低（六类中多步类需要多次正确调用），
  且 pv=0 说明模型不违规但也不总是完成任务——可能是容量或数据问题而非工具数问题。
- **诚实边界**：仅在一个 teacher/provider（MiMo-V2.5）、一个模型（Qwen3-4B）、
  一个任务集（retail_ops v3 六类）上测量。不能声称"工具数不影响 tool selection"的一般性
  结论。不同模型规模、不同工具语义重叠度、不同任务复杂度下结论可能不同。

## C1 flight_ops 集成修复：隐式契约与模式统一（2026-08-21）

- **teacher_data ToolSchema→dict（openai SDK 兼容）**：flight_ops 的 teacher 采集调用
  `core.build.teacher_client.OpenAICompatibleTeacherClient`，但 ToolSchema 是 Pydantic
  对象，openai SDK 的 `chat.completions.create(tools=[...])` 不接受 Pydantic 实例——
  需要 `model_dump()` 转为 dict。这是隐式契约：SDK 类型提示不拦截 Pydantic 对象，
  运行时才报错。修复点在 flight_ops 的 teacher collection loop。
- **run.py train config schema（UserSFTConfig 严格模式）**：flight_ops 的 run.py
  构造 SFT config dict 时直接用字面量，没有通过 `UserSFTConfig` 校验。严格模式下
  缺字段/类型不匹配会直接报 ValidationError，比静默跑错配置更安全。
- **eval 用 QwenPolicy.from_config（替代不存在的 load_model）**：flight_ops 的 eval
  入口原先调用不存在的 `load_model`，改为 `QwenPolicy.from_config(dict)`——
  与 retail_ops 的 eval 入口统一。
- **model sha256 非递归包含所有文件**：flight_ops 的 model pin 计算只遍历
  `model_dir.iterdir()` 的直接子文件，不进入子目录。若模型目录有嵌套结构（如
  checkpoint 子目录），会遗漏文件。当前 Qwen3 模型文件都是扁平的所以不影响，
  但这是一个潜在的坑。

## R9 Phase A：数据量消融（2026-08-21，CPU）

### Oversampling 实现

- **数据结构**：原始 240 条训练数据，6 个场景各 40 条，42 个不同的 user_request 模板
  （替换 order_id 后）。
- **变体生成**：对每条原始样本生成 7-8 个变体，替换 order_id（随机 16 位 hex）、
  reason（从 4 个中轮换）、margin（从 7 个值中轮换）、customer_id（从 CUST001-CUST010
  中轮换），保持 user_request 模板不变。
- **去重**：同一模板+同一实体组合只保留一条，最终生成 2000 条，无重复。
- **切分**：按 sha256 切分 train/dev/holdout = 80/10/10（1600/200/200）。
- **场景分布**：train 集中 lookup_status 303、refund_eligible 283、refund_denied_duplicate
  261、refund_recovery 261、refund_denied_ownership 251、refund_denied_window 241。

### Phase A 配置

- 训练配置：`configs/retail_ops/build/retail_ops_v1_r9_phase_a_sft.yaml`
- 评测配置：
  - `configs/retail_ops/evaluate/retail_ops_v1_r9_phase_a_dev.yaml`（原有 60 条）
  - `configs/retail_ops/evaluate/retail_ops_v1_r9_phase_a_ood.yaml`（原有 60 条）
  - `configs/retail_ops/evaluate/retail_ops_v1_r9_phase_a_ood_oversampled.yaml`（新增 60 条）

### 待执行

- A-1：训练 Phase A 候选（gpu-5090，~15min）
- A-2：Dev 评测（原有 60 条）
- A-3：OOD 评测（原有 60 条）
- A-4：oversampled OOD 评测（新增 60 条）

### 判读规则（在看到结果前写定）

| 结果 | 判定 |
|---|---|
| OOD ≥ 0.70 | 数据量是重要因素，继续 Phase B |
| OOD 改善但 < 0.70 | 数据量有帮助但不够，Phase B 必须做 |
| OOD 无改善 | 数据量不是瓶颈，需重新诊断 |
