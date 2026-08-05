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

### LOG-20260722-02：批准并启动 R2 正式数据与双模型 Base

- 日期：2026-07-22
- 阶段/任务：R2 / 正式数据、teacher 与 dev base
- 状态：阶段变更
- 关联：`docs/superpowers/specs/2026-07-22-retailops-v1-r2-formal-data-and-base-design.md`、`docs/superpowers/plans/2026-07-22-retailops-v1-r2-formal-data-and-base.md`

**背景与难点**：R2 需要从 12 条 qualification 进入真正可用于领域适配的数据合同，同时
不能让 teacher、派生样例或开发评测泄漏到正式 holdout。用户还要求 provider 可由 `.env`
一行切换，并要求 Qwen3-1.7B/4B 两份真实 dev base，但所有 API、模型下载和远端 GPU 资源
仍需保留逐项审批。

**证据**：用户逐段批准 family-first `240/60/120`、五维指纹隔离、R2 专用 manifest/receipt、
teacher 总体 70%/单类 50% 质量门、selector + provider namespace 路由、两份固定 Qwen revision、
`/data/TJK/internship-projects/retail-agent-ops` 远端根和 `/data/TJK/models` 模型根。执行前
HEAD 为 `a3c748b`，CPU 基线为 211 passed，Ruff 与 mypy 通过。`uv lock --check` 的异常已证明
只是用户级清华镜像 URL 规范化，显式使用现有 lock 索引别名即可通过。

**决定与方案**：从基线新建 `feature/r2-formal-data-and-base-eval`。保留 R1 类型与 CLI 兼容，
新增 R2 formal task/manifest/governance、动态 OpenAI-compatible teacher、train export、sealed
evaluator 和 base evidence。teacher 仅访问 train，dev 用 internal reference，正式 holdout 在
R2 不运行真实模型。先完成 CPU TDD/审查，再分别请求正式数据、API smoke/full、SSH、同步、
两个模型下载和每条 GPU 命令批准。

**备选方案与未选择理由**：未把 provider 写死为 DeepSeek，因为用户需要后续一行切换；未把
Qwen3-4B 留到 R3，因为用户批准 R2 同时建立两份 dev base；未提前执行 holdout base，因为会
破坏冻结评测独立性；未设置 API 金额上限，因为用户使用自己的套餐，但仍固定任务、episode、
步数、重试和 usage 记录。

**后果与下一步**：R2 状态改为“当前”，进入八个 TDD/审查任务。正式外部动作尚未授权；
在对应命令获得批准前，不生成仓库正式数据、不调用 API、不连接服务器、不下载模型、不运行 GPU。

### LOG-20260722-03：R2 Task 1 指纹完整性审查失败并修复

- 日期：2026-07-22
- 阶段/任务：R2 / Task 1 formal family-first 任务生成
- 状态：失败已修复
- 关联：`83bd0b3`、`dfdb8dd`

**背景与难点**：初版已生成精确的六类 × 35 family × 2 variant，并能让全部 420 条任务在
`RetailOpsEnv` 中执行成功；但正式数据隔离不仅要求当前结果正确，还要求后续篡改和派生泄漏能被
指纹与自动测试可靠发现。

**失败证据**：独立审查证明初版 `derivation_fingerprint` 信任任务自带的
`metadata.formal_family`，只修改实际 deadline/owner/refund status/lookup status 时可能不变；
`assert_exact_quotas()` 也会接受复制 variant 0 替换 variant 1。catalog 与 420 条环境执行当时仅
存在临时验证，未固化成回归测试，因此审查结论为 NOT PASS。

**修复与验证**：从实际 initial/target state 重建去 opaque ID 的政策投影，逐条重算五类指纹，
强制每 family 的 variant 为 `{0,1}` 且 task/content 唯一；新增七状态、七 margin、0..4 distractor、
四原因公式、调用序列、冻结 bundle 原因和全部 420 条环境语义测试。复审确认 3 个 Important 和
1 个 Minor 全部关闭；17 个 focused、219 个全仓测试、Ruff、mypy 与 diff 检查通过。

**后果与下一步**：Task 1 可以作为 Task 2 manifest/holdout 的可信输入。该失败没有读取或生成
正式数据，也没有调用 API、模型、SSH 或 GPU；外部审批门保持不变。

### LOG-20260722-04：R2 Task 2 数据治理绕过修复

- 日期：2026-07-22
- 阶段/任务：R2 / Task 2 formal manifest 与 sealed holdout
- 状态：失败已修复
- 关联：`e877bd2`、`87a65ff`

**失败证据**：初版 exact schema、公开/私有分离和两阶段 hash-before-parse 已通过 255 个测试，
但独立审查仍复现六项 Important：允许字段值可承载私有文本、dataset/split/private provenance 未
形成统一验证链、private variant 可失配、双输出根失败后会残留半成品、physical artifact 可经
非可信路径进入授权，以及授权对象可由公开构造路径复制。

**决定与修复**：冻结本 R2 的 dataset/generator/parser/evaluator/seed；新增一次读取并交叉核对四份
公开文件的 `VerifiedFormalDataset`；private row 绑定完整 provenance 并重建 family `{0,1}`；writer
改为 staging/验证/双根发布并对各故障点清理；holdout 从 trusted root 逐级 no-follow 打开 regular
file，在同一 fd 上 `fstat/read/hash`；dataset 与 holdout 采用 factory-issued 注册对象。该对象只作为
进程内受支持 API 门禁，不声称替代操作系统权限或抵御同进程对所有私有实现的恶意调用。

**验证与后果**：103 个 Task 2 + R1 回归、284 个全仓测试、Ruff、mypy 和 diff 均通过；最终复审
无 Critical/Important/Minor。R1 schema/行为未修改，仓库未生成正式数据，也未读取 `.env`、正式
private/holdout/BFCL 或访问网络/API/SSH/GPU。Task 3 可开始，但真实 API 仍须单独批准。

### LOG-20260805-01：新增 gpu-5090 远程环境并修复 teacher route .env

- 日期：2026-08-05
- 阶段/任务：R2 / 环境与资源边界扩展
- 状态：阶段变更
- 关联：`CLAUDE.md` 第4节、`.env`

**背景与难点**：R2 Task 3（provider-agnostic teacher route，尚未提交）的 `.env` 仍是旧版本命名
（`DEEPSEEK_API_KRY` 拼写错误、权限 0644），不满足 `teacher_route.py` 的
`TEACHER_LLM_<PROVIDER>_*` schema。同时用户要求把项目扩展到第二台共享 GPU 服务器
`gpu-5090`（远端用户 `tongjiakai`），并计划从 ModelScope 下载 Qwen3-1.7B/4B；但 R2 已批准方案
把这两个模型锁定为具体 HuggingFace revision 用于可复现 base 评测，ModelScope 没有对应
commit 概念，构成与既有可复现性承诺的冲突，需要用户裁决。

**证据**：`.env` 已重命名为 `TEACHER_LLM_DEEPSEEK_{BASE_URL,API_KEY,MODEL}` 并新增
`TEACHER_LLM_PROVIDER=deepseek`，权限改为 600；未读取或打印密钥值，`TEACHER_LLM_DEEPSEEK_MODEL`
实际取值未改动。只读 SSH 侦察确认 `gpu-5090`：RTX 5090 32GB 显存（当前空闲约 27GB，另有 2 个
进程共占约 4.5GB，证明服务器多人共用）、24 核、62GB 内存（55GB 可用）、`/mnt/aidata` 3.6T
空闲 2.0T、根分区 962G 空闲 341G，`~/.local/bin/uv 0.11.33` 与系统 `python3` 已就绪，
`~/.modelscope` 缓存目录已存在。`/mnt/aidata/tongjiakai` 内已有该用户其他项目（`ekg`、
`embed_server`、`llm-lifecycle-lab`、`ollama`、`SARGE`、`sysroot`、`envs`、`downloads`、`bin`），
本次未创建或修改任何既有目录。

**决定与方案**：用户逐项确认：（1）`gpu-5090` 作为第二远程环境新增，不替换 `gpu-4090`，两者
并存，后续任务需在报告中明确使用哪一个；（2）项目远程目录固定为
`/mnt/aidata/tongjiakai/retail-agent-ops`；（3）Qwen3-1.7B/4B 改用 ModelScope 侧版本标识重新
锁定作为新的正式 pin，原 HuggingFace revision 记录待替换。`CLAUDE.md` 第4节已更新为两套并列
远程环境定义，并要求执行前核对显存/进程占用与磁盘余量。

**备选方案与未选择理由**：未把 `gpu-5090` 设为替换 `gpu-4090` 的唯一远程环境，因为用户明确
要求保留旧配置；未直接复用旧 HuggingFace revision 跳过重新锁定，因为 ModelScope 分发文件不
保证与 HF revision 字节一致，直接复用会破坏 R2 已批准的“正式运行固定模型版本”要求；未修改
`.env` 中的 model 取值，因为 agent 不应替用户猜测正式模型标识。

**后果与下一步**：尚未创建远程项目目录、未传输代码、未安装远程环境、未查询或下载任何模型；
这些均为后续任务，逐项执行前会分别报告命令、工作目录、物理 GPU、预计时长和产物。ModelScope
版本标识确认后需回填 `findings.md` 的 R2 dev base revision 记录。

### LOG-20260805-02：gpu-5090 环境执行完成，模型下载校验进行中

- 日期：2026-08-05
- 阶段/任务：R2 / gpu-5090 环境执行
- 状态：进行中（模型下载校验未最终确认）
- 关联：LOG-20260805-01、`findings.md` "gpu-5090 环境扩展与 ModelScope 重新锁定" 小节

**背景**：LOG-20260805-01 已批准新增 gpu-5090 远程环境、确定项目路径与 ModelScope 重新锁定
策略，但当时尚未执行任何远程写入。本条记录该决定的实际执行结果。

**证据**：
- 代码迁移：本地 `git bundle --all`（仅两个分支的已提交历史，不含本轮未提交的
  `CLAUDE.md`/`PROJECT_LOG.md`/`findings.md`/`task_plan.md`/`pyproject.toml`/`uv.lock` 改动，
  也不含未提交的 `teacher_client.py`/`teacher_route.py` 及测试）已传输并在
  `/mnt/aidata/tongjiakai/retail-agent-ops` clone，远端 HEAD 为 `155d67a`；已删除指向本地
  bundle 的悬空 `origin` remote。
- 环境搭建：远端 `uv sync --extra dev --extra train --frozen` 成功（首次因 `teacher` extra
  未提交而失败，已改用不含 teacher 的组合重试）；`.venv` 5.2G，`torch==2.13.0+cu130` 验证
  `torch.cuda.is_available()==True` 并正确识别 `NVIDIA GeForce RTX 5090`；同步后
  `/mnt/aidata` 仍有 2.0T 可用。
- ModelScope 查询：通过只读 REST API 取得 `Qwen/Qwen3-1.7B`（权重提交
  `980712f58bdf09497308d37d0e30b535064cde04`，4.08GB）与 `Qwen/Qwen3-4B`（权重提交
  `8cd0101f70cac4f1efcebc979faf483558e39297`，8.06GB）的逐文件 SHA256 manifest，比单一
  revision 字符串更严格；用户已确认下载两个模型并存至 `/mnt/aidata/tongjiakai/models`。
- 下载与校验脚本（`snapshot_download` + 逐文件 SHA256 比对，任一文件缺失/大小/哈希不符即整体
  判定失败）已在远端后台启动，执行结果尚未返回，本条记录不代表下载已成功。

**决定与方案**：按已批准范围执行，未扩大到 Task 3 之外的其他远程操作；`teacher` extra 留待
本地 Task 3 提交后再补 `uv sync`。

**后果与下一步**：等待后台下载脚本返回 `ALL_FILES_VERIFIED_OK` 或失败详情；成功后需把
ModelScope 提交哈希回填为正式 R2 dev base pin（替换原 HuggingFace revision 记录），失败则需
诊断具体文件并重试，不得在校验不通过时声称模型已就绪。

### LOG-20260805-03：gpu-5090 模型下载全部校验通过，R2 dev base 完成重新锁定

- 日期：2026-08-05
- 阶段/任务：R2 / gpu-5090 环境执行收尾
- 状态：解决
- 关联：LOG-20260805-01、LOG-20260805-02

**证据**：后台下载脚本返回 `ALL_FILES_VERIFIED_OK`；`Qwen/Qwen3-1.7B` 13/13 文件、
`Qwen/Qwen3-4B` 14/14 文件逐项 `OK`（文件名/大小/SHA256 与 ModelScope API manifest 完全一致，
无一处缺失或不符）。落盘路径 `/mnt/aidata/tongjiakai/models/{Qwen3-1.7B,Qwen3-4B}/`，实际占用
3.8G + 7.6G = 11.4G；下载后 `/mnt/aidata` 仍报告 2.0T 可用，对共享服务器磁盘无实质影响。

**决定与方案**：ModelScope 提交哈希
`980712f58bdf09497308d37d0e30b535064cde04`（Qwen3-1.7B 权重）与
`8cd0101f70cac4f1efcebc979faf483558e39297`（Qwen3-4B 权重）正式取代 R2 计划原有的
HuggingFace revision 记录，作为本项目 dev base 的正式模型 pin；已回填至 `findings.md`。

**后果与下一步**：gpu-5090 环境（代码、uv 依赖、GPU 可用性、模型权重）已具备执行 Qwen3-1.7B/4B
dev base 评测的前置条件；但本轮未运行任何评测或 GPU 推理任务，`teacher` extra 仍待本地 R2
Task 3 提交后同步。dev base 实际评测运行仍需按 CLAUDE.md 远程协议逐条报告命令、工作目录、
物理 GPU、预计时长和产物后再执行。

### LOG-20260805-04：DeepSeek teacher 真实 API 首次 smoke 通过，发现 thinking 行为

- 日期：2026-08-05
- 阶段/任务：R2 / Task 3 provider-agnostic teacher
- 状态：解决
- 关联：`.env`、`src/veritool_rl/retail_ops/teacher_route.py`

**背景**：用户确认正式 teacher 模型为 `deepseek-v4-flash`，要求先验证可用性再进入 Task 3 全流程
开发。`.env` 中 `TEACHER_LLM_DEEPSEEK_MODEL`/`BASE_URL` 已经是该值，未做改动。

**证据**：只读检索确认 `deepseek-v4-flash` 是 DeepSeek 当前在售正式模型（284B 总参数/13B 激活
MoE，OpenAI 兼容协议，真实 endpoint 为 `{base_url}/chat/completions` 而非 `/v1/chat/completions`，
与现有 `TEACHER_LLM_DEEPSEEK_BASE_URL=https://api.deepseek.com` 一致）。随后用配置的真实凭据发起
一次最小 smoke 请求（`max_tokens=8`），HTTP 200，响应 `model` 字段回显 `deepseek-v4-flash`；本次
未读取或打印 API key 明文，仅在 shell 变量中使用。用量 `prompt_tokens=88`、
`completion_tokens=8`、`total_tokens=96`，按官方定价（输入 $0.14/M、输出 $0.28/M）成本约
$0.0000145，可忽略。

**发现**：响应包含非空 `reasoning_content` 而 `content` 为空、`finish_reason="length"`——说明
`deepseek-v4-flash` 默认按 thinking 模式返回，`max_tokens` 预算会被推理链占用。TeacherClient
实现必须显式处理该字段（提高预算或关闭 thinking），否则会把推理草稿误当空回复处理。

**决定与方案**：模型确认可用，进入 Task 3 全流程 TDD 实现，需要把 thinking/`reasoning_content`
处理纳入实现和测试范围，而不是假设 provider 总是直接返回 `content`。

**后果与下一步**：本次 API 调用为一次性最小 smoke，未进行批量采集或正式 train 导出；Task 3 实现
和后续真实 teacher 批量采集仍需分别验证。

### LOG-20260805-05：R2 Task 3 完成，独立审查修复 RecursionError 泄漏并修正 uv 索引配置

- 日期：2026-08-05
- 阶段/任务：R2 / Task 3 provider-agnostic teacher 路由与 client
- 状态：解决
- 关联：`d40c43a`、`7153c26`

**背景与难点**：接手时 `teacher_route.py`/`teacher_client.py` 已有前序会话留下的完整实现和
37 个通过的测试，但从未跑过 Ruff/mypy/独立审查，也没有针对刚确认的 `deepseek-v4-flash`
thinking 行为的验证。

**证据**：
- Ruff/mypy 各发现 2 个真实问题（测试 fixture 可变默认参数、import 顺序、
  `TEACHER_PROTOCOL_ID` 缺 `Literal` 标注导致字段默认值类型不兼容），已修复。
- 实测证实 `[tool.uv] index-url = "..."` 在 `uv 0.11.8` 下完全不生效（用假域名替换后
  `uv lock --check` 仍瞬间通过），是本项目反复出现的"镜像 URL 机械改写 uv.lock"问题的根因；
  改用已验证生效的 `[[tool.uv.index]] url = "..." default = true` 后，`uv.lock` diff 从
  约 3671 行降到 129 行，`git diff --check`、全量测试、Ruff、mypy、lock check 均通过。
- 独立只读审查发现 1 项阻塞级问题：`_parse_extra_body`/`_normalize_tool_calls` 的 JSON 解析
  未捕获 `RecursionError`，几 KB 的深层嵌套输入（未达 16KB 上限）会让加载路径整体崩溃而非
  返回预期的 `ValueError`/`TeacherClientError`。已用 `"[" * 4000 + "]" * 4000` 复现 RED，
  补两处 except 元组后 GREEN；三项非阻塞建议（`__context__` 未清空、SDK 无显式
  timeout/max_retries、secret-key 黑名单可被零宽字符绕过）判定为可接受风险，记录在
  `findings.md`，未改代码。

**决定与方案**：Task 3 按 `docs/superpowers/plans/2026-07-22-retailops-v1-r2-formal-data-and-base.md`
第 115-165 行验收，先提交环境/DeepSeek 验证文档（`d40c43a`），再提交
`feat: add dynamic teacher routing`（`7153c26`），最终 323 个全仓测试、Ruff、mypy 51 个源
文件、`uv lock --check`、`git diff --check` 全部通过。

**后果与下一步**：Task 4（teacher 采集、回放质检与 train 导出）可以开始；采集配置需要复用
`{"thinking":{"type":"disabled"}}` 的 `extra_body` 模式，避免真实批量采集把预算浪费在
推理链上。真实批量 teacher 调用仍需单独确认后才能执行。

### LOG-20260805-06：R2 Task 4 费用/时间预测与 smoke-first 建议

- 日期：2026-08-05
- 阶段/任务：R2 / Task 4 teacher 采集规划（尚未实现）
- 状态：进行中（等待用户确认 smoke 规模）
- 关联：LOG-20260805-05、`docs/superpowers/plans/2026-07-22-retailops-v1-r2-formal-data-and-base.md` 第 166-212 行

**背景**：Task 3 完成后，用户要求在实现 Task 4（teacher 批量采集/回放质检/train 导出）前先
估算真实批量调用的费用和时间，用于决定是否批准正式批量 API 调用。

**证据与假设**：train 配额固定 240 条，计划边界为单任务至多 2 episode × 5 步（理论上限
2400 次调用）；按多数任务在 episode 1 内完成且用不满步数上限，估计实际约 900~1400 次调用
（中位数 ~1100 次）。Token 假设参考 R1 MiniRetail 实测的 `average_input_tokens≈555-685`、
`average_output_tokens≈50-60`（更简单的 2 工具版本），R2 正式任务工具/政策更复杂，按
input≈900、output≈60 token/次估算；未做真实多轮 smoke，此假设未经测量验证。按
`deepseek-v4-flash` 定价（$0.14/M cache-miss 输入、$0.28/M 输出，未计入可能的 cache-hit
折扣）估算：中位数场景约 $0.15，理论上限场景约 $0.40-0.45。延迟未实测，按 flash 模型定位
估计单次 1-3 秒；若串行执行预计 35 分钟到 2 小时，若实现并发可能压缩到 5-15 分钟，取决于
Task 4 尚未确定的并发设计。

**决定与方案**：本轮只产出预测，未实现 Task 4 代码，未发起任何批量 API 调用。建议正式批量
采集前先用 10-20 条 train 任务做一次真实 smoke，把上述假设换成实测数字，再据此批准全量
240 条采集，延续本项目一贯的 API smoke-then-full 节奏。

**后果与下一步**：等待用户确认 smoke 规模；确认后需要先实现 Task 4 的最小采集路径才能执行
smoke，smoke 结果应回填本记录或新增记录，不得让本预测的假设数字被当作实测结论使用。

### LOG-20260805-07：20 条真实 teacher smoke 完成，发现并绕过两个 runner 真实 bug

- 日期：2026-08-05
- 阶段/任务：R2 / Task 4 前置 smoke（临时脚本，非正式实现）
- 状态：解决（smoke 本身）／待处理（runner.py 的两个 bug 尚未在正式代码里修复）
- 关联：LOG-20260805-06

**背景**：用户要求用 20 条真实 formal train 任务实测 Task 4 的真实费用/时间，并解释预测偏差
原因和任务本身的作用。用临时脚本（未提交，位于会话 scratchpad）复用已有
`build_formal_task_set`、`RetailOpsEnv`、`run_episode`、`TeacherClient`、`replay_trajectory`，
新写一个 `TeacherPolicy`（把 `TeacherResponse` 适配成 `PolicyOutput`，参照 `QwenPolicy` 模式）。

**发现的真实 bug（均在既有共享代码 `src/veritool_rl/agent/runner.py::run_episode` 里，非
teacher 专属，此前从未被真实 OpenAI 兼容 HTTP API 检验过——本地 Qwen backend 走
`tokenizer.apply_chat_template` 对此完全宽容）**：
1. 组装 assistant 消息时 `tool_calls[].function.arguments` 直接放原始 dict，而 OpenAI 协议
   要求该字段必须是 JSON 编码的字符串；DeepSeek 返回 HTTP 400
   "invalid type: map, expected a string"。
2. assistant 的 `tool_calls[]` 条目和随后的 `tool` role 观测消息都没有 `id`/`tool_call_id`
   字段，同样是真实 OpenAI 兼容 API 会拒绝的缺口（本次因先撞见 bug 1 而未先触发，修复 bug 1
   后单独复现）。
- 额外发现（配置而非代码问题）：`.env` 缺少 `TEACHER_LLM_DEEPSEEK_EXTRA_BODY_JSON`，
  `deepseek-v4-flash` 默认走 thinking 模式，多轮对话下 DeepSeek 要求把上一轮
  `reasoning_content` 传回去，而 `messages` 历史里没有这个字段，第二轮必现 400。已在 `.env`
  追加 `TEACHER_LLM_DEEPSEEK_EXTRA_BODY_JSON='{"thinking":{"type":"disabled"}}'`（单引号包裹
  是因为 `source .env` 会剥掉未加引号值里的双引号，之前漏了这一层）解决。

**处理方式**：三处修复都只做在会话 scratchpad 的临时脚本/本地 `.env` 里（消息级 JSON 字符串化
+ 合成 `id`/`tool_call_id`、thinking 关闭），**没有修改任何已提交代码**；`run_episode` 的两个
真实 bug 仍原样存在于仓库，需要在 Task 4 正式实现时用 TDD 补齐（这会影响所有未来接入真实
OpenAI 兼容 API 的 policy，不只是 teacher）。

**实测证据**（修复生效后，20/20 条 `lookup_status` 类真实 train 任务，非全部 6 类的代表性
抽样——`records("train")` 按 family 顺序排列，前 20 条恰好全部同一类别）：20/20 成功，
20/20 `replay_trajectory` 校验通过；40 次真实调用（2 次/任务）；实测
`avg_input_tokens/call≈562`、`avg_output_tokens/call≈76`、`avg_latency≈1061.7ms`；
20 任务串行墙钟 42.5 秒；实测成本 $0.003996。按同类推算 240 条（**未跨类别外推，其他 5 类
step 数可能更高**）：约 480 次调用、约 8.5 分钟串行、约 $0.048。均远低于
LOG-20260805-06 的保守预测（预测调用 token 数偏高，是因为参照了更简单的 MiniRetail 2 工具
历史数据，且未计入本任务只需 2 步就能完成）。

**后果与下一步**：LOG-20260805-06 的预测已被本条实测数据取代，Task 4 全量费用/时间预期下调；
但需在 Task 4 正式实现前修复 `run_episode` 的两个真实 OpenAI 协议 bug（写失败测试固定期望
的 wire format），并在正式采集前额外对至少一个非 `lookup_status` 类别（比如需要更多步的
`refund_recovery`）做真实抽样，避免用单一最简类别的数据外推全部 6 类。

### LOG-20260805-08：R2 Task 4 完成，独立审查发现并修复三项数据治理漏洞

- 日期：2026-08-05
- 阶段/任务：R2 / Task 4 teacher 采集、质量门与 train 导出
- 状态：解决
- 关联：`99bc4ec`（run_episode wire format 前置修复）、`1d60af2`

**背景**：在 LOG-20260805-07 的 smoke 测试基础上，先用 TDD 把 `run_episode`（`agent/runner.py`）
组装多轮消息历史时的两个真实 OpenAI wire format bug（`tool_calls[].function.arguments`
需为 JSON 字符串、需要 `id`/`tool_call_id`）修复并提交（`99bc4ec`，已确认 Qwen3 真实
chat_template 原生支持字符串/字典两种形式，对本地 Qwen 路径无回归），随后实现 Task 4 正式
模块 `teacher_data.py`。

**证据**：
- `collect_teacher_attempt` 覆盖 8 类结果分类（成功/schema 非法/非法工具/政策违规/步数
  上限/终态错误/传输耗尽/replay 不一致），每类都有基于真实 formal train 任务的场景测试；
  dev/holdout 任务在调用 teacher client 前即被拒绝。
- 新增 `TeacherClientError.retryable` 分类（`teacher_client.py`，靠 `status_code`/异常类名
  鸭子类型判断可重试传输错误，不硬依赖 openai SDK），供采集循环区分"重试"与"直接判定
  schema 非法"。
- 顺带修复 `data/generators.py::trajectory_to_sft_example` 的同一 wire format 问题，因为
  Task 4 导出路径最终把它的输出写进 `sft.jsonl`。
- 独立只读审查在测试全绿之后，按 Task 1/2 同等严格度复现三个真实漏洞（均用攻击脚本验证）：
  1. 私有根路径校验只做字符串成分检查，可被 `..` 穿越、含相同片段的任意绝对路径、或把
     中间目录做成 symlink 绕过；修复为接收调用方建立的受信 `private_root` + 校验过的简单
     `attempt_id`/`task_id` 分量，内部 `resolve()` 做逃逸检测，复用 `formal_manifests.py`
     已审计模式。
  2. `load_teacher_checkpoint` 解析证据文件后从未与 checkpoint 自身治理哈希/`accepted`/
     `task_id` 交叉校验，实测替换证据文件内容后 resume 仍会接受；修复为逐字段核对。
  3. `write_formal_train_export` 四文件顺序写入非原子，中途失败留半成品且无法安全重试；
     修复为 private 三文件走 staging + 原子 rename，任何后续失败（含公开 `quality.json`
     冲突）都整体回滚已发布的 private 目录，复用 `write_formal_task_set` 的模式。
  三处修复均补了对抗性回归测试（路径穿越、intermediate symlink、证据内容篡改、公开产物
  冲突时的私有目录回滚），非阻塞建议（重试无退避等）判定为可接受风险，记录在 `findings.md`
  未改代码。

**决定与方案**：Task 4 按 `docs/superpowers/plans/2026-07-22-retailops-v1-r2-formal-data-and-base.md`
第 166-212 行验收，最终 365 个全仓测试、Ruff、mypy 52 个源文件、`uv lock --check`、
`git diff --check` 全部通过，提交为 `1d60af2`（`feat: add audited teacher data pipeline`）。

**后果与下一步**：R2 核心数据链路（Task 1-4：formal 任务生成、manifest/holdout 治理、
teacher 路由与 client、teacher 采集与 train 导出）CPU 实现全部完成并审查。剩余 R2 计划
Task 5（Qwen3-1.7B/4B dev base 配置与运行证据）和 Task 6（CLI 分派与端到端验收）待开始；
真实批量 teacher 采集（240 条 train）和模型 dev base 评测仍需分别单独确认后才能执行。
