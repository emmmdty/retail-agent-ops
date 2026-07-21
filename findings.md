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
