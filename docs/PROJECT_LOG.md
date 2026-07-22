# VeriTool-RL 项目中间记录

本文件是 append-only 的执行与决策日志，记录项目完成过程中值得跨会话保留的困难、
证据、选择、替代方案和后果。它不替代 `docs/EXECUTION_PLAN.md` 的阶段状态、
`docs/adr/` 的长期架构决策或 `reports/` 的完整实验结果。

## 自动记录协议

Codex、Claude 或其他 coding agent 在开始实质任务时必须读取
`docs/EXECUTION_PLAN.md` 的当前阶段和本文件最近记录。出现以下任一情况时，在最终
答复前追加一条记录，并在答复中报告 `LOG` ID：

- 阶段开始、完成、阻塞、恢复或退出门变化；
- 实现或实验遇到非显然失败，需要诊断、绕行或改变原方案；
- 数据划分、评测口径、依赖、后端、模型、资源或安全约束发生实质变化；
- 做出会影响后续工作的设计/实验决策，或明确否决了有意义的替代方案；
- 执行 GPU smoke、正式训练、批量 benchmark 评测或 go/no-go；
- 得到改变下一阶段安排的正结果、负结果、审查结论或风险；
- 发现或怀疑 benchmark 泄漏、结果不可复现、指标失真或 provenance 缺失。

以下情况不记录：纯只读查询、例行成功命令、只报告状态、拼写/格式修正、无后续
影响的瞬时错误，以及已有记录的重复叙述。不得把 secret、模型权重、原始受限数据、
带答案的 holdout/训练样例或冗长终端输出写入本文件。

历史条目不得修改或删除。事实变化、纠错或决策被取代时追加新条目，并用
`取代/更正: LOG-...` 建立关联。日志只写实际证据；未运行的结果不得写成结论。

## 条目模板

```markdown
### LOG-YYYYMMDD-NN：简短标题

- 日期：YYYY-MM-DD
- 阶段/任务：P? / task
- 状态：决定 / 解决 / 阻塞 / 观察 / 阶段变更
- 关联：无，或 LOG/ADR/report/config 路径

**背景与难点**：为什么需要处理。

**证据**：真实错误、测试、指标、commit、配置或产物路径；避免粘贴大段输出。

**决定与方案**：实际选择以及执行方式。

**备选方案与未选择理由**：至少记录有意义的替代方案；若无则写“无”。

**后果与下一步**：风险、限制、负责人/触发条件和要更新的阶段门。
```

## 记录

### LOG-20260717-01：采用共享指令与 Stop 检查的项目记录系统

- 日期：2026-07-17
- 阶段/任务：P2 / 执行治理
- 状态：决定
- 关联：`docs/adr/0003-project-execution-memory.md`

**背景与难点**：项目已有 `CLAUDE.md`、按周里程碑、ADR 和实验报告，但没有一个
跨会话持续更新的阶段事实源，也没有覆盖故障、实验取舍和被否决方案的中间日志。
根目录没有 `AGENTS.md`，且项目约束明确禁止创建它，因此 Codex 与 Claude 需要共用
现有指令入口。

**证据**：仓库审计只发现 `docs/adr/0001` 和 `0002`；`SPEC.md` 的 W1-W12 计划未
反映已经完成的 BFCL Base/SFT；OpenAI 官方配置支持在缺少 `AGENTS.md` 时设置项目
文档 fallback，Anthropic 官方文档区分了持久指令与 lifecycle hook。

**决定与方案**：以 `docs/EXECUTION_PLAN.md` 作为唯一阶段事实源，以本文件作为
append-only 中间日志；在 `CLAUDE.md` 放置共同触发协议；用 `.codex/config.toml`
加载该协议；用 Claude Stop prompt hook 检查本轮是否遗漏日志处置说明。Stop hook
只做提醒，实际记录仍由 agent 根据证据完成。

**备选方案与未选择理由**：不采用仅靠指令的方案，因为缺少结束时遗漏检查；不采用
脚本自动写日志，因为容易制造噪声、误判决策和泄漏 benchmark 内容；不创建根目录
`task_plan.md/findings.md/progress.md` 三套文件，因为会与两份权威文档形成重复状态源；
保留 ADR，但只用于长期架构决策，不承担日常执行流水。

**后果与下一步**：Claude 每次 Stop 会多一次快速判断，并可能在实质任务漏记时继续
一轮；Codex 项目必须被信任并重新启动会话才能加载项目级 fallback。完成 P2 配置和
质量门后，把 P2 标为已完成并开始 P3 前置设计。

### LOG-20260717-02：Claude Stop hook 运行时 smoke 受用户级认证阻塞

- 日期：2026-07-17
- 阶段/任务：P2 / Agent 配置验收
- 状态：阻塞
- 关联：`.claude/settings.json`、`tests/test_agent_workflow_config.py`

**背景与难点**：静态 JSON 和回归测试通过后，尝试用只读 `claude -p` 请求触发一次
真实 Stop 事件，以确认项目 hook 在当前 CLI 上运行。

**证据**：Claude Code 2.1.212 完成项目会话初始化，但提示显式认证源优先于
claude.ai 登录，随后主模型请求持续返回 HTTP 401 `authentication_failed`。请求在
产生模型回复和 Stop 事件前被终止；`total_cost_usd` 为 0。配置文件解析和 CLI 启动
未报告 settings schema 错误。

**决定与方案**：不修改或 unset 用户级认证信息。保留官方格式的 Stop prompt hook，
以 JSON/TOML 解析、仓库回归测试和 CLI 配置加载作为当前可执行验收；真实 Stop 行为
留到用户认证恢复后的新 Claude Code 会话验证。

**备选方案与未选择理由**：未切换认证源或重新登录，因为它们属于仓库范围外的用户
账户状态，可能影响其他项目；未把 prompt hook 改为自动写文件的 command hook，
因为认证失败不改变后者可能误写事实和 benchmark 内容的风险。

**后果与下一步**：自动记录协议和配置可以提交，但必须明确标注“Claude Stop 运行时
smoke 未完成”。认证恢复后运行 `/hooks` 确认 Project Stop hook，并用只读响应验证
一次允许路径；该限制不影响 Codex fallback 或仓库质量门。

### LOG-20260717-03：P2 执行治理阶段完成

- 日期：2026-07-17
- 阶段/任务：P2 / 阶段退出门
- 状态：阶段变更
- 关联：LOG-20260717-01、LOG-20260717-02、`docs/EXECUTION_PLAN.md`

**背景与难点**：阶段计划、日志、共享 Agent 指令和两端配置完成后，需要确认它们
没有形成冲突状态源，并明确认证限制是否阻塞 P2。

**证据**：新增配置回归测试先因文件缺失得到 2 个预期失败，配置落地后通过；完整
测试为 101 passed，Ruff、mypy、JSON/TOML 解析和差异空白检查通过；Claude Code
2.1.212 doctor 未发现安装问题。LOG-20260717-02 记录的 401 发生在用户级模型认证，
不是 settings 解析或仓库实现错误。

**决定与方案**：P2 标为已完成；P3 标为待执行的下一阶段但不自动启动。把真实 Stop
事件 smoke 保留为认证恢复后的验收补充，不通过改写用户认证扩大本次任务边界。

**备选方案与未选择理由**：未因外部认证问题把 P2 整体标为阻塞，因为仓库配置、
CLI 兼容性和全部本地质量门已有独立证据；未提前启动 P3，因为本次授权仅覆盖执行
计划和记录系统。

**后果与下一步**：后续实质任务从 P3 入口门开始；先冻结共享 benchmark 接口、
manifest、holdout 和 evaluator，再启动阶段内并行轨道。认证恢复时补做 Claude Stop
hook 允许路径 smoke，并追加新日志，不修改本条历史。

### LOG-20260717-04：Codex fallback 运行时 smoke 受用户配置与认证阻塞

- 日期：2026-07-17
- 阶段/任务：P2 / Agent 配置验收补充
- 状态：观察
- 关联：`.codex/config.toml`、LOG-20260717-03

**背景与难点**：为验证新 Codex 会话是否把 `CLAUDE.md` 作为仓库级 fallback，运行
只读、ephemeral、read-only 的 `codex exec` 指令发现 smoke。

**证据**：首次严格模式在进入项目前发现用户级 `~/.codex/config.toml` 的
`disable_response_storage` 已不是 Codex CLI 0.144.4 的已知字段。使用
`--ignore-user-config --strict-config` 后，项目配置通过严格解析并创建新 thread，但
账户 refresh token 已过期，模型请求以 HTTP 401 `refresh_token_expired` 结束，未能
返回实际加载的指令文件名。

**决定与方案**：不修改仓库范围外的用户配置或登录态。以项目 TOML 严格解析、
`tomllib` 回归测试和 OpenAI 官方 fallback 发现规则作为当前验收；用户修复全局字段
并重新登录后，再从仓库根目录启动新 Codex 会话完成指令来源 smoke。

**备选方案与未选择理由**：未删除 `~/.codex/config.toml` 字段或执行 `codex logout`
/`login`，因为这会改变用户所有 Codex 项目的全局行为和账户状态；未创建根
`AGENTS.md` 绕过 fallback，因为项目明确禁止。

**后果与下一步**：仓库实现可用且 P2 保持完成，但“新 Codex 会话实际回显加载了
`CLAUDE.md`”仍是认证恢复后的补充验收项；完成后追加日志，不更改既有记录。

### LOG-20260717-05：通过官方设备登录恢复 Codex 认证并补验 fallback

- 日期：2026-07-17
- 阶段/任务：P2 / Agent 配置验收补充
- 状态：解决
- 关联：LOG-20260717-04、`.codex/config.toml`

**背景与难点**：用户提供了一份浏览器侧导出的 `auth.json`，希望判断能否替换已经
过期的 Codex CLI 认证。认证材料必须脱敏检查，且不能把 token 写入仓库或终端记录。

**证据**：目标文件结构完整，access token 尚在有效期内，并能访问 Codex models
端点；但完整文件的隔离 `codex exec` 在 refresh 时返回 401。公开 OAuth 元数据显示
目标 token 与当前 CLI 登录属于不同 client，refresh token 因此不能由当前 CLI 使用；
手工 `codex login --with-access-token` 也因 token 类型不符合 agent identity JWT 而被
拒绝。随后使用官方 `codex login --device-auth` 成功生成 CLI 自有凭据。

**决定与方案**：未复制或修改浏览器导出的认证文件。先把旧 CLI 认证备份到
`/home/tjk/.codex/auth.json.backup-20260717-122713`，再完成设备码登录；新
`~/.codex/auth.json` 权限设为 `600`。真实只读 `codex exec` 返回 `AUTH_OK`，新的项目
会话也加载了 `CLAUDE.md` 并识别 `docs/EXECUTION_PLAN.md` 为阶段状态事实来源。

**备选方案与未选择理由**：未手改 JWT、client ID、refresh token 或时间戳，因为这些
字段受 OAuth 签名和 client 绑定保护；未用浏览器 access token 作为长期替代，因为它
无法由 CLI 自动刷新；未删除用户提供的原文件，因为删除仓库外敏感文件需要单独确认。

**后果与下一步**：LOG-20260717-04 的 Codex 认证和 fallback 补充验收已解决。用户级
`~/.codex/config.toml` 仍含 Codex 0.144.4 严格模式不识别的
`disable_response_storage`，但正常 CLI 调用可运行；Claude Code 使用独立认证链，
本次 Codex 登录不会修复 LOG-20260717-02 的 Claude 401。

### LOG-20260717-06：修复 SFT 格式回归与 BFCL provenance 校验缺口

- 日期：2026-07-17
- 阶段/任务：P2 完成后 / 全仓代码审查
- 状态：解决
- 关联：`src/veritool_rl/training/sft.py`、`src/veritool_rl/eval/bfcl_compare.py`

**背景与难点**：BFCL 显式 labels 训练接入后，共用 SFT runner 只接受预 tokenized
数据，但两个受版本控制的 MiniRetail 配置仍指向 `messages + tools` JSONL；同时 BFCL
配对聚合未读取每次评测生成的运行清单，无法证明输入分数仍对应当前冻结 manifest。

**证据**：真实 MiniRetail 训练行只有 `messages/scenario/task_id/tools`，旧入口会报
`tokenized 字段必须是列表`；篡改 manifest 的 `selection_sha256` 后，旧聚合器仍可
接受自洽的 ID/score 文件。轨迹重放还会接受被篡改的 `Step.index`，通用指标入口会把
`True` 当成一次 bootstrap。新增回归测试先得到 6 个预期失败；修复后完整测试为
107 passed，Ruff、mypy（35 个源码文件）和 `git diff --check` 均通过。真实 MiniRetail
128/32 条数据通过格式准备，两份现有 BFCL 正式运行清单通过收紧后的 provenance 校验。

**决定与方案**：SFT runner 严格自动识别两种已有格式：BFCL 继续使用显式 labels、
关闭 TRL 二次处理并保留显式 collator；MiniRetail 恢复 TRL chat template 与
assistant-only loss 路径。BFCL 聚合强制校验运行清单中的冻结 manifest 哈希、内嵌
内容、任务顺序、seed 以及 benchmark/evaluator commit。重放逐步核对记录索引，
bootstrap 次数拒绝布尔值和非正整数。

**备选方案与未选择理由**：未给配置新增必填 `data.format`，因为格式可由互斥字段
无歧义识别，新增字段会无必要地破坏现有配置；未废弃 MiniRetail 训练入口，因为它是
P0 可复现路径；未在本地启动 GPU smoke，因为项目约束禁止本地 GPU 训练/推理，且本次
未获得远程训练授权。

**后果与下一步**：历史 MiniRetail 配置重新具备可执行的数据入口，BFCL 配对结果的
manifest provenance 链在聚合时强制闭合。此次只完成 CPU 级数据与产物校验；下次经
授权运行远程 SFT smoke 时，应分别覆盖 `messages` 和 `pretokenized` 两条 trainer
路径。P2 保持完成，P3 仍未启动。

### LOG-20260720-01：隔离并重定位为 RetailAgentOps 求职工程

- 日期：2026-07-20
- 阶段/任务：R0 / 项目初始化
- 状态：已完成
- 关联：`docs/adr/0004-reposition-as-retail-agent-ops.md`、`docs/EXECUTION_PLAN.md`

**背景与难点**：用户需要在三个月内完成面向 Agent 求职的工程项目，具体代码由 Codex/Claude
Code 承担，用户负责方向和阶段决策。旧路线以研究型多 seed、偏好优化和论文式证据为主，且原工作区
含未提交成果，不能直接覆盖。

**证据**：在共同父目录创建隔离 worktree 和分支，迁入有效修改后逐项比较，原工作区状态未变化；
迁入快照为 `29ea3b9`。最终初始化验收为 112 tests passed，Ruff、mypy、JSON/TOML 和 diff 检查
通过。旧生成报告未迁入，三个文件
的路径和 SHA-256 已写入 `docs/LEGACY_INVENTORY.md`。

**决定与方案**：产品更名为 RetailAgentOps，保持 `veritool_rl` 包名，以单卡可复现的
`build/evaluate/release/serve` 和发布门禁为主线；默认一个开发 seed，最终简历数字才做一次独立重建。
新增 `AGENTS.md`、求职背景、产品简报、R0-R5 计划、接管说明和三份项目记录文件。

**备选方案与未选择理由**：未继续把 GRPO 和多 seed 设为必做，因为缺少失败证据且算力/周期不匹配；
未只包装 BFCL，因为不能证明零售应用闭环；未在初始化中重命名 Python 包，因为会扩大无价值 diff。

**后果与下一步**：R0 已关闭并停止，等待用户批准 R1 的任务契约和 holdout 规则；
本次不下载模型、不调用 API、不运行本地或远程 GPU。

### LOG-20260720-02：选择 RetailOps v1 方案 A 并进入规格复核

- 日期：2026-07-20
- 阶段/任务：R1 / 产品契约与冻结规则
- 状态：决定
- 关联：`docs/superpowers/specs/2026-07-20-retailops-v1-contract-design.md`、`docs/EXECUTION_PLAN.md`

**背景与难点**：R0 只固定了产品边界，尚未决定 RetailOps v1 的任务类别、工具集合、政策
验证和 holdout 保护方式。直接沿用 MiniRetail 动态 `test` split 会把任务真值写进轨迹，
无法满足正式发布的泄漏边界。

**证据**：用户选择方案 A。现有代码包含 `get_order`、`refund_order` 和 4 类 MiniRetail
场景，但评测按 seed 动态生成任务，`TaskSpec` 内嵌目标状态/期望调用，评测产物会保存完整
trajectory。R1/R2 计划分别要求 qualification vertical slice 和正式冻结 split。

**决定与方案**：采用 2 个正式业务工具、6 类任务、6 条政策约束；R1 只用 12 条
qualification fixture，R2 目标配额为 train/dev/holdout `240/60/120`。holdout 先按
任务族分组划分，公共 receipt 只保存版本、配额、指纹和哈希，原始真值与完整逐任务证据
保持 sealed。正确拒绝和违规调用分开计量；release 门禁失败即 NO-GO 并回退 base。

**备选方案与未选择理由**：未选择更丰富的 5 工具/8 类操作流方案，因为它会在 R1 同时
引入取消、政策查询和工单升级，增加 verifier 误判与时程风险；未直接冻结正式 holdout，
因为 R2 才负责生成和冻结正式数据。

**后果与下一步**：R1 可进入规格复核，但仍不实现代码。用户复核规格后才创建实现计划；
若 qualification 无法稳定区分正确拒绝与 policy violation，或 sealed evidence 边界
无法自动验证，停止进入 R2 并记录阻塞。BFCL 固定 200 条继续独立只读。

### LOG-20260720-03：移除冗余 Codex 项目配置并独立化 checkout

- 日期：2026-07-20
- 阶段/任务：R1 / 开发环境维护
- 状态：已完成
- 关联：`AGENTS.md`、`docs/HANDOFF.md`、`docs/adr/0003-project-execution-memory.md`

**背景与难点**：RetailAgentOps 已有根目录 `AGENTS.md`，但仍保留只为加载
`CLAUDE.md` 而存在的 `.codex/config.toml`，并且目录仍是 `veritool-rl` 的 linked
worktree。Codex 0.144.6 会对 linked worktree 的 Hook 使用 root checkout 配置，
使两个项目未来可能再次耦合。

**决定与方案**：删除冗余 Codex 项目配置和专用 fallback 测试；Codex 直接以
`AGENTS.md` 为入口。保持路径和工作文件不变，把 Git 元数据原地替换为独立 checkout，
不配置远程；Claude Code 的 Stop prompt hook 不变。

**选择理由**：该方案保留所有 R1 文档、环境和 ignored benchmark 资产，同时消除原仓库
配置覆盖、项目 Hook 审核和误写远程的风险。记录协议仍由版本化指令、计划、进度和本日志保证。

**备选方案与未选择理由**：继续使用 linked worktree 当前也能加载，但未来 root checkout
增加 Hook 时会重新耦合；保留 `.codex/config.toml` 没有新增能力；删除 Claude Hook 超出
本次 Codex 启动问题范围。

**后果与下一步**：R1 规格复核门不变，不进入实现，不运行 GPU、API 或数据下载。后续 Codex
会话从 `AGENTS.md` 和 `docs/HANDOFF.md` 接管。

### LOG-20260720-04：批准方案 A 规格并冻结 R1 实现计划边界

- 日期：2026-07-20
- 阶段/任务：R1 / 规格复核与实现计划
- 状态：决定
- 关联：`docs/superpowers/specs/2026-07-20-retailops-v1-contract-design.md`、`docs/superpowers/plans/2026-07-20-retailops-v1-r1-vertical-slice.md`

**背景与难点**：方案选择只确定方向，仍需把正确拒绝、qualification、holdout 隔离、
release 和 serve 拆成可执行接口，避免实施时把 R2 正式数据冻结或 R3 模型服务提前带入。

**证据**：用户书面批准方案 A 设计规格。代码映射确认现有 `OraclePolicy` 依赖
`expected_calls`，FastAPI/Uvicorn 尚未进入依赖锁，根 `/data/` 已被 Git 忽略，现有
`ToolEnv`、runner、replay 和 metrics 可以通过兼容扩展复用。

**决定与方案**：R1 使用一个纵向实现计划，分成 10 个独立 TDD/commit 单元。新增领域
代码集中在 `veritool_rl.retail_ops`；正式评测只覆盖 qualification/development，R1
实现 holdout receipt、隔离、授权和脱敏契约，但不生成或打开正式 holdout。FastAPI
只服务 qualification policy，并按 GO/NO-GO 选择 candidate 或 base fallback。

**备选方案与未选择理由**：未拆成多个互不关联的计划，因为 bundle、environment、
evidence、release 和 serve 共享同一冻结契约；未在 R1 实现 sealed holdout evaluation
mode，因为这会提前执行 R2 的正式数据职责；未引入通用状态机 DSL。

**后果与下一步**：实现计划已可执行，但尚未授权开始代码。下一步由用户选择逐任务
subagent-driven execution 或当前会话 inline execution；任一方式都必须逐任务 TDD、
审查并在最终 HEAD 重跑完整质量门。

### LOG-20260721-01：R1 qualification 纵向切片完成

- 日期：2026-07-21
- 阶段/任务：R1 / 端到端验收与阶段收口
- 状态：阶段变更
- 关联：`reports/retail_ops/v1/qualification-r1-final/`、`docs/EXECUTION_PLAN.md`

**背景与难点**：R1 需要证明版本化 bundle、固定 qualification、评测证据、发布门禁和
fallback 服务形成同一条可审计闭环，同时不能把合成 Oracle 结果、BFCL 外部回归或未生成的
正式 holdout 误写成产品模型效果。

**证据**：README 中的六条 CPU 命令生成 12 条 qualification；baseline、Oracle 和
unknown-tool fault 分别成功 8/12、12/12、0/12，三组证据均 12/12 可重放。发布结果分别为
GO/candidate 与 NO-GO/baseline。新鲜树与独立重复树逐文件一致；task manifest SHA-256 为
`6f510a699c33a5ec9c7df3ef4310a36165b4acff270425b6bfc8c6fd39124f6e`。两份 HTML 可识别，
公开 release 报告未命中任务真值、holdout、BFCL、常见 secret/private-key 标记，产物树无
常见模型权重文件。服务用 TestClient 验证，未启动持久进程。
提交前完整质量门为 211 passed，Ruff、mypy 46 个源文件、`uv lock --check` 与
`git diff --check` 全部通过；治理测试同时保证 RetailOps 运行报告不进入 Git。

**决定与方案**：R1 标为已完成，R2 保持待执行。Oracle 只作为确定性资格上限，fault 只用于
验证门禁和 baseline fallback；它们均不作为候选模型效果。正式 train/dev/holdout 仍由 R2
在用户确认后冻结。

**备选方案与未选择理由**：未把 qualification 扩展成正式 holdout，因为会越过 R2 的数据
冻结与授权边界；未因 Oracle 12/12 声称模型改善；未启动服务进程，因为 TestClient 已覆盖
允许、拒绝、恢复和 fallback 路径，持久进程不增加 R1 验收证据。

**后果与下一步**：R1 关闭后停止继续实现。R2 只有在用户确认正式数据来源、配额和冻结规则后
才可启动；在此之前不得下载模型、调用商业 API、运行 GPU 或生成正式 holdout。

### LOG-20260722-01：迁入正式项目目录并建立 R2 Codex 交接门

- 日期：2026-07-22
- 阶段/任务：R1→R2 / 项目迁移与执行交接
- 状态：解决
- 关联：`docs/handoffs/2026-07-22-r2-codex-execution-prompt.md`、`docs/LEGACY_INVENTORY.md`、`59025fc`

**背景与难点**：仓库虽已拥有独立 `.git`，物理目录仍位于 `.worktrees/`，容易被当成
临时 checkout。直接改路径会破坏两个虚拟环境中的绝对 shebang，也会使共享 benchmark
checkout 的旧相对链接按错误层级解析；同时 R2 需要在新目录保留数据、API、模型和 GPU
审批门，而不是把“完整执行”误解为可自行选择外部资源。

**证据**：现有仓库已移动到
`/home/tjk/myProjects/internship-projects/retail-agent-ops`，旧目录不存在；Git 仍为自身
`.git`、分支 `portfolio/retail-agent-ops-init`、无 remote，且 HEAD 是 R1 提交 `59cc1b5`
的后代。主项目与 BFCL evaluator 环境均以冻结 lock 重建为 Python 3.11.15，主命令
shebang 已指向新目录；`data/external_repos` 解析到未修改的原仓库 external checkout，
Gorilla 仍固定在 `6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`。新目录首次完整门禁为
211 passed、Ruff 通过、mypy 46 个源文件通过、lock 解析 101 packages、diff 检查通过。

**决定与方案**：原子移动唯一活动仓库，不建立第二份 clone；把路径敏感环境视为可重建
资产，用 `uv sync --frozen` 重建，并把软链接改为新层级的相对路径。R2 使用专门交接提示词，
允许批准计划后的 subagent TDD/双重审查，但正式数据来源、teacher/API、计划主模型、模型
下载和每条远程 GPU 命令仍需用户分别确认。

**备选方案与未选择理由**：未复制或本地 clone，因为会留下两个活动事实源且无法自然迁移
ignored evidence；未继续保留 `.worktrees/` 历史路径，因为目录语义仍有误清理风险；未在本轮
启动 R2，因为数据/teacher 和两模型 base 的阶段口径仍需用户裁决。

**后果与下一步**：新 Codex 会话从正式目录读取 R2 交接提示词并先执行只读 preflight；
R2 状态继续为“待执行”，本轮未生成正式数据、未调用 API、未下载模型、未运行 GPU。
