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

### LOG-20260805-09：写出 R2 Task 5-7 执行提示词（未提交）

- 日期：2026-08-05
- 阶段/任务：R2 / 阶段交接文档
- 状态：解决
- 关联：`docs/handoffs/2026-08-05-r2-task5-7-execution-prompt.md`（未提交）

**背景**：用户要求给出下一阶段的启动提示词，用于在新会话（Claude Code 或 Codex）里继续
R2 剩余工作。参照 `docs/handoffs/2026-07-22-r2-codex-execution-prompt.md` 的既有格式和
边界写法产出新版本。

**内容**：新提示词范围限定在 Task 5（sealed evaluator + Qwen3-1.7B/4B dev base 证据，
CPU fake backend）、Task 6（CLI `pipeline` 分派 + CPU 端到端验收）、Task 7（整分支独立
审查 + 写出"未执行、逐条待批准"的外部命令清单），明确不包含 Task 8 的任何实际外部操作
（正式数据生成、API、模型下载、SSH、GPU）。内容里显式指向本次 Task 1-4 已经审计过的
`_resolve_within`/staging/原子发布模式，要求 Task 5 复用而不是重新实现同类路径校验；
新增一条硬停止条件：私有产物写入若又退化成纯字符串路径检查，直接算阻塞级问题。同时说明
gpu-5090 已下载并哈希校验过 Qwen3-1.7B/4B，Task 7 命令清单应询问用户是否复用而不是默认
重新下载。

**决定与方案**：本轮只创建了提示词文件，未提交、未开始执行 Task 5-7 的任何实现；是否
提交、是否立即启动 Task 5 均等待用户决定。

**后果与下一步**：若用户批准，下一步是把此文件提交或直接用它启动新会话执行 Task 5-7；
Task 8（正式数据/API/模型/GPU）仍需在 Task 7 产出命令清单后逐条单独批准，不在本文档
范围内。

### LOG-20260805-10：接受 R2 Task 5-7 执行范围，采用 SDD 流程启动 Task 5

- 日期：2026-08-05
- 阶段/任务：R2 / Task 5（sealed evaluator + Qwen dev base 证据）
- 状态：进行中
- 关联：LOG-20260805-09、`docs/handoffs/2026-08-05-r2-task5-7-execution-prompt.md`、
  `docs/superpowers/plans/2026-07-22-retailops-v1-r2-formal-data-and-base.md`

**背景与难点**：新会话按用户指示，以 `docs/handoffs/2026-08-05-r2-task5-7-execution-prompt.md`
为执行依据，接管 R2 剩余的 Task 5（sealed evaluator + 双模型 dev base 证据）、Task 6（CLI
`pipeline` 分派与 CPU 端到端验收）、Task 7（整分支审查与外部审批命令清单），不涉及 Task 8
的任何实际外部操作。开工前完整读取了 CAREER_CONTEXT/PRODUCT_BRIEF/EXECUTION_PLAN/
task_plan/findings/progress/PROJECT_LOG（LOG-20260805-05 至 09）/SPEC/R2 设计规格/R2 实现
计划全文，并核对了只读 preflight（HEAD 是 `a3c748b`、`1d60af2` 的后代；`.venv/bin/pytest -q`
365 passed；Ruff、mypy、`git diff --check`、`uv lock --check` 全部通过）。工作树内此前会话
遗留的 `.gitignore`/`docs/PROJECT_LOG.md`（LOG-20260805-09）/handoff 文档三处未提交改动已
先行提交（`1d8b8b3`），保持后续 Task 5 diff 干净。

**决定与方案**：采用 `superpowers:subagent-driven-development`（SDD）流程执行 Task 5-7：
在 `.superpowers/sdd/2026-07-22-retailops-v1-r2-formal-data-and-base/progress.md` 建立本次
会话的 ledger（首行标注计划文件路径，记录 Task 1-4 为此前会话在 SDD 工具外完成、已提交，
Task 5-7 为本次会话范围，Task 8 显式排除）。已读取该计划文件的 Global Constraints 及 Task
5/6/7 完整小节，扫描未发现任务间或与全局约束的冲突，按流程规定无需在开工前向用户批注即可
继续。已生成 Task 5 brief（`task-5-brief.md`），派发一个 opus 模型的 general-purpose
implementer 子代理在后台执行 Task 5 的 TDD 实现（sealed evaluator 与 Qwen3-1.7B/4B dev base
证据，`src/veritool_rl/retail_ops/sealed_evaluation.py`/`base_evaluation.py`，扩展
`agent/qwen.py`），要求其复用 Task 2/4 已审计过的 `_resolve_within`/staging/原子发布/
trusted-root fd 读取模式，禁止仅做字符串路径检查，禁止在新代码中硬编码任何具体模型
revision 字面量（因为该 pin 本项目内已经变更过一次，见 findings.md "gpu-5090 环境扩展"
小节），CPU 测试全程只用 fake backend/fake hardware provider。

**后果与下一步**：等待 Task 5 implementer 完成并进入任务审查 + 修复循环；随后按同一 SDD
流程执行 Task 6（CLI pipeline 分派与 CPU 端到端验收）与 Task 7（整分支审查、完整 CPU 门禁
重跑、外部审批命令清单）。Task 7 结束时只能把 R2 状态记录为"CPU 实现完成、外部证据待批准"，
不得标记 R2 已完成；Task 8 的正式数据、API、模型下载与 GPU 命令仍需逐条另行获得用户批准后
才能执行。

### LOG-20260805-11：Task 5 独立审查发现 1 项 Important，修复并进入 scoped re-review

- 日期：2026-08-05
- 阶段/任务：R2 / Task 5（sealed evaluator + Qwen dev base 证据）
- 状态：进行中
- 关联：LOG-20260805-10、`06a41f9`、`bea052c`

**背景与难点**：Task 5 implementer（opus）完成 sealed evaluator（`sealed_evaluation.py`）与
dev base 证据（`base_evaluation.py`，扩展 `agent/qwen.py`）的 TDD 实现，提交 `06a41f9`；
自审时已自行发现并修复一项 Important 级问题（dev 证据原先信任调用方哈希，现已改为独立
重新加载校验 `dev.jsonl`）。442 全量测试通过，Ruff/mypy/lock/diff 全绿。

**证据**：独立只读审查（opus）确认治理主干（dev loader 落盘前拒绝、sealed capability 复用、
allowlist 测试、路径逃逸防护、无硬编码 revision）扎实，但发现 1 项新的 Important：
`_require_backend_matches_pin` 只核对 `backend.model_dir`/`backend.revision`，未核对 adapter
状态或实际生成参数——`TransformersBackend` 从未把 adapter_path 或真实 `GenerationSettings`
暴露给绑定校验，导致挂载了 adapter 或改了采样参数的后端也能通过 `evaluate_formal_dev_base`
的全部检查，产出与真实 base run 无法区分的证据，恰好是这个 evaluator 存在的核心目的
（base vs. adapter 区分）失守。另有 8 项 Minor 记入 `.superpowers/sdd/.../progress.md` 留待
最终整分支审查统一分诊。

**决定与方案**：按 subagent-driven-development 流程，仅这 1 项 Important 触发修复循环
（Minor 不进入循环）。恢复原 implementer 完成 fix round 1：`TransformersBackend` 现在
如实发布 `adapter_path` 与 `settings`；`_require_backend_matches_pin` 依次拒绝非空 adapter、
目录/revision 不符、`settings != config.generation`。新增对抗性回归测试覆盖 adapter 后端、
四种参数漂移场景与一个正例对照；顺带解决了一项已记录的 Minor（`max_new_tokens` 死代码，
因整体 settings 比较而自然生效）。提交 `bea052c`；focused 7、四个覆盖文件 99、全量 449
测试通过，Ruff/mypy/diff 干净。implementer 明确说明未对 sealed evaluator（`evaluate_authorized_holdout`）
加同样绑定，理由是 R3 需要在正式 holdout 上合法运行挂载 adapter 的候选模型，这属于已记录
的 Minor（sealed evaluator 按设计不含模型/生成参数绑定），不是同一 Important 的重现。
已派发 sonnet 模型的 scoped re-review 验证该修复且检查修复本身有无引入新问题。

**后果与下一步**：等待 scoped re-review 结果；若确认 addressed 且无新 Critical/Important，
Task 5 记为 complete 并进入 Task 6（CLI pipeline 分派与 CPU 端到端验收）。

### LOG-20260805-12：Task 6（CLI pipeline 分派与 CPU 端到端验收）实现完成

- 日期：2026-08-05
- 阶段/任务：R2 / Task 6（CLI pipeline 分派与 CPU 端到端验收）
- 状态：进行中（implementer 侧完成，等待独立审查）
- 关联：LOG-20260805-11、`.superpowers/sdd/2026-07-22-retailops-v1-r2-formal-data-and-base/task-6-brief.md`

**背景与难点**：Task 5 完成后进入 Task 6：把 Task 1-5 已实现但从未接入 CLI 的四条 R2
库函数（formal_freeze、teacher_collect、train_export、formal_dev_base）以 `pipeline` 字段
分派方式接入既有稳定 `product_cli.py`，同时不得改变 R1 四个命令在无 `pipeline` 字段时的
任何行为。其中最安全敏感的一点是 `.env`/环境变量边界：只有 `teacher_collect` 允许读取
`TEACHER_LLM_*`，且必须证明其余流水线（含全部未改动的 R1 路径）在环境变量被污染时完全
不受影响、也不会因为缺少这些变量而报错。

**决定与方案**：`build`/`evaluate` 先看 config 有没有顶层 `pipeline` 字段，没有就逐字节走
原 R1 精确 key 集合路径（`_run_release`/`_run_serve` 未新增任何 R2 路径，一行未改）；有则
分派到四个独立命名的流水线函数，各自校验自己的精确 key 集合。`teacher_collect` 需要真实
`TeacherClient` 而 CPU 测试无法构造、`formal_dev_base` 需要真实 `GenerationBackend`/
`HardwareProvider` 而 CPU 测试同样无法构造，两处都用同一种窄注入缝：可选关键字参数
（`client_factory`/`backend_factory`/`hardware_provider_factory`，默认 `None`），函数体内
`factory or _default_xxx` 在调用时才动态查找模块级默认工厂，因此测试既可以直接调用内部
处理函数并传入 fake，也可以只走 `main()` 并在唯一定义点 monkeypatch 默认工厂，不需要额外
"测试模式"开关。`code_commit`/`uv_lock_sha256` 不放进 config（提交后立刻过期），改为 CLI
用 `Path(__file__).resolve().parents[2]` 定位仓库根后现算，与调用方 CWD 是否被测试
chdir 到隔离 tmp 根无关。

**证据**：TDD 全程：先写 `tests/test_retail_ops_r2_cli.py`（33 用例）确认因
`_require_config_keys` 拒绝新增 `pipeline`/R2 key、`ImportError`、argparse 未知参数而 RED，
再实现 `product_cli.py` 与 6 份新 config、`tests/test_retail_ops_r2_e2e.py`（4 用例，含 1 个
双参数化）。CPU 端到端覆盖：两个隔离 tmp 根各跑一次 formal_freeze 并逐字节比较全部
公开/私有产物；240 条 train 任务跑一次 teacher_collect（通用 fake teacher client 按
`task.expected_calls` 回放，不依赖具体场景，每类别标记 8/40 失败，越过 70%/50% 质量门）
后 train_export 导出 240 条 train.jsonl/sft.jsonl，来源精确对应 teacher 接受与
internal_reference 回退；两份 dev-base config 各自通过 fake backend/fake hardware provider
跑通 60 条 dev 任务并用真实 `load_base_run_evidence` 回读校验、扫描无任务级泄漏。
`tests/test_project_governance.py` 新增 3 个断言：R2 私有/模型/产物路径仍被既有
`.gitignore` 规则覆盖、6 份新 config 的实际取值不含绝对路径/私有根路径/凭据标记、
`product_cli.py` 与新 config 不引用 BFCL。`tests/test_retail_ops_cli.py`（R1 CLI 测试）
diff 为空，逐字节未改。全仓 `.venv/bin/pytest -q` 489 passed（Task 5 收口基线 449 +
本任务新增 40）；Ruff、`ruff format`、mypy 54 files、`env -u UV_INDEX_URL uv lock --check`、
`git diff --cached --check` 全部通过。

**后果与下一步**：等待独立审查（reviewer）确认 `.env` 边界、注入缝设计和 R1 等价性无
Critical/Important 问题；确认后进入 Task 7（整分支审查、完整 CPU 门禁重跑、外部审批命令
清单）。两份 dev-base config 的 `model.revision`/`file_sha256` 仍是显式标注的占位值——
真实 Qwen3-1.7B/4B 权重下载与哈希固化仍需用户逐项审批，不在本任务范围内。

### LOG-20260805-13：Task 6 独立审查发现 4 项 Important，修复后进入 scoped re-review

- 日期：2026-08-05
- 阶段/任务：R2 / Task 6（CLI pipeline 分派与 CPU 端到端验收）
- 状态：进行中
- 关联：LOG-20260805-12、`07da971`、`96536c9`

**背景与难点**：独立只读审查（opus）确认 `.env` 边界实现本身、R1 等价性、确定性测试、
注入缝设计、`export_formal_train`/`route_sha256` 绕行方案均扎实且经代码核实，但发现 4 项
Important：(1) `_r2_private_root` 直接拼接未校验的 `dataset_version` 字符串，当前仅因下游
`write_formal_task_set` 恰好先拒绝非冻结值才"意外安全"，不满足"必须自身做 resolve() 逃逸
检查"的约束；(2) `.env` 边界回归测试用 `pytest.raises(Exception)` 过宽（读到污染环境变量
并报错也会通过），且名不副实——`formal_freeze`/`formal_dev_base` 从未在污染环境下被实际
跑过；(3) `teacher_collect` 的 resume/skip 路径零测试覆盖，而 `collect_teacher_attempt`
（真实计费调用）发生在 `write_teacher_attempt_evidence` 的不可覆盖检查之前，skip 逻辑一旦
出错会静默重复计费已采集任务；(4) 计划 Step 5 明确要求的 `uv lock --check` 治理扫描未落地
为自动化测试，只靠手动跑过 Step 6 门禁。另有 10 项 Minor 记入 ledger 留待最终整分支审查。

**决定与方案**：恢复原 implementer 修复全部 4 项 Important。首次恢复因触发本会话 API
用量限制（提示 3:30am 台北时间重置）在产生任何改动前中断，工作树和报告文件均未受影响；
未改变任务或方案，直接原样重试恢复同一 agent 后成功完成。修复内容：`_r2_private_root`
改为调用 `_validate_path_component`/`_resolve_within`（与文件内 `attempt_id` 同一套已审计
模式）；环境边界测试收紧为 `pytest.raises(TeacherQualityGateError)` 并新增
`formal_freeze`/`formal_dev_base` 在污染环境下的成功产出断言；新增
`_CountingAlwaysFailTeacherClient` 与两次运行同一 `attempt_id` 的 resume 测试，断言第二次
运行客户端调用数为零；`test_project_governance.py` 新增 `uv lock --check` 断言。顺带免费
解决两项 Minor（测试 fixture 统一用 `REPO_ROOT`、BFCL 扫描范围扩大到
`src/veritool_rl/retail_ops/`）。提交 `96536c9`；focused 37+12、全量 495 测试通过，
Ruff/mypy/lock/diff 全部干净。已派发 sonnet 模型的 scoped re-review 验证这 4 项修复且检查
修复本身有无引入新问题。

**后果与下一步**：等待 scoped re-review 结果；若确认 addressed 且无新 Critical/Important，
Task 6 记为 complete 并进入 Task 7（整分支审查、完整 CPU 门禁重跑、外部审批命令清单）。

### LOG-20260805-14：Task 6 re-review 通过，标记 complete，进入 Task 7

- 日期：2026-08-05
- 阶段/任务：R2 / Task 6 → Task 7
- 状态：解决（Task 6）／进行中（Task 7 启动）
- 关联：LOG-20260805-13、`96536c9`

**背景与证据**：scoped re-review（sonnet）逐项核对 4 项 Important 修复，全部判定
ADDRESSED（含独立复核 `_r2_private_root` 的 `resolve()` 逃逸检查确实是使遍历测试失败的
唯一原因、`formal_freeze`/`formal_dev_base` 在污染环境下真的产出了 `train.jsonl`/
`base-report.json` 而非静默跳过、resume 测试第二次运行的计数客户端确实零调用），未发现
新的 Critical/Important。唯一记录项是修复报告把 focused 测试数误写成 37（实际 38，独立
重跑验证），纯笔误、不影响结论。

**决定与方案**：Task 6 标记 complete（commits `bea052c..96536c9`）。10 项 Minor 加上这条
计数笔误一并留在 SDD ledger（`.superpowers/sdd/2026-07-22-retailops-v1-r2-formal-data-and-base/
progress.md`）等最终整分支审查统一分诊。R2 Task 5、6 现已在同一分支
`feature/r2-formal-data-and-base-eval` 上完成并各自通过独立审查；进入 Task 7：整分支审查
（`a3c748b..HEAD`）、从头完整 CPU 门禁、临时目录 formal 重复构建哈希比较、仓库级
secret/BFCL/holdout 泄漏扫描，并撰写 `docs/handoffs/<date>-r2-external-run-commands.md`。

**后果与下一步**：Task 7 结束时只能把 R2 状态记为"CPU 实现完成、外部证据待批准"，不得标记
R2 已完成；Task 8（正式数据生成、API 全量、模型下载、SSH、GPU 命令）仍需在命令清单产出后
逐条单独获得用户批准。

### LOG-20260805-15：Task 7 整分支独立审查已派发；主 agent 从头完整 CPU 门禁与仓库级泄漏扫描全部通过

- 日期：2026-08-05
- 阶段/任务：R2 / Task 7（整分支审查与外部审批命令清单）
- 状态：进行中
- 关联：LOG-20260805-14

**背景**：Task 5、6 均已完成并各自通过独立审查（含修复循环）。Task 7 要求：(1) 从每个
任务基准和整个分支 `a3c748b..HEAD` 生成审查包；(2) 从头跑一遍完整 CPU 门禁 + 临时目录
formal 重复构建哈希比较 + 仓库级 secret/BFCL/holdout 泄漏扫描；(3) 产出外部审批命令清单；
(4) 更新阶段记录但不得把 R2 标为已完成。

**证据**：已派发 opus 模型的整分支独立审查，diff 范围 `a3c748bdad1ce6fb7ec8a838d2f1f36da0bbae60
..96536c9`（19 commits、48 files、+12215/-107），要求其聚焦跨任务视角（路径安全模式在 4 处
独立实现是否等价、`.env` 边界是否在整个分支范围内成立、BFCL/holdout 隔离是否在全分支范围
内成立、Task 6 是否正确调用了 Task 5 修复轮之后的最终接口、有无硬编码 model revision）
并对 Task 5/6 遗留的 8+10 项 Minor 逐条给出 must-fix-before-done / acceptable-to-defer 裁决。
同时主 agent 直接从头跑完整 CPU 门禁：`.venv/bin/pytest -q` 495 passed（含
`test_retail_ops_r2_e2e.py` 的两次独立 tmp 根 formal_freeze 逐字节重复构建比较）、
`.venv/bin/ruff check .`、`.venv/bin/mypy`（54 源文件）、`env -u UV_INDEX_URL uv lock
--check`（105 packages）、`git diff --check` 全部干净。另外手动跑了超出 R2 专属治理测试
范围的仓库级扫描：`git grep` 未发现任何 secret 形态字面量（`api_key`/`secret`/`password`/
`token`/`sk-*`/`AKIA*` 模式）；`src/veritool_rl/retail_ops/`、`configs/retail_ops_*` 内
无任何 BFCL 引用，仓库其余 "bfcl" 命中均为预期的基础设施引用（`.gitignore` 规则、
`pyproject.toml` 脚本/依赖条目、治理测试自身的断言字符串）；`data/private/`、
`manifests/retail_ops/v1/`、`reports/retail_ops/` 下均无任何已跟踪文件（Task 8 尚未执行，
符合预期），且用 `git check-ignore -v` 逐条验证了忽略规则确实覆盖这些路径。

**决定与方案**：等待整分支独立审查结果；有 Critical/Important 发现则进入修复+re-review
循环，之后按计划撰写 `docs/handoffs/<date>-r2-external-run-commands.md` 并更新阶段记录为
"CPU 实现完成、外部证据待批准"。

**后果与下一步**：无新决定；证据保存在 SDD 工作区
`.superpowers/sdd/2026-07-22-retailops-v1-r2-formal-data-and-base/progress.md`（该目录被
gitignore，不进入 Git，仅供本会话使用），本条 PROJECT_LOG 记录是这些结果的持久留存。

### LOG-20260805-16：整分支审查（a3c748b..HEAD）结论"With fixes"，发现 3 项 Important，修复已派发

- 日期：2026-08-05
- 阶段/任务：R2 / Task 7（整分支审查）
- 状态：进行中
- 关联：LOG-20260805-15、`96536c9`

**背景**：opus 模型对 `a3c748bdad1ce6fb7ec8a838d2f1f36da0bbae60..96536c9`（19 commits、
Task 1-6 全部）做整分支审查。结论：无 Critical，无任何 section 七硬停止条件被违反（无
split 交叉、无 holdout 内容进 Git/规划/报告、未依据 holdout 调参、无私有写入函数退化为纯
字符串路径检查、无非 staged 多文件写入、未改配额/算法、未执行任何 GPU/API/下载命令）。
审查确认路径安全模式的 4 处独立实现行为完全等价（非漂移）、`.env` 边界在全分支范围内成立、
BFCL/holdout 隔离在全分支范围内成立、Task 6 正确调用了 Task 5 修复轮之后的最终接口、无
任何硬编码 model revision。对 Task 5（8 项）与 Task 6（10 项+1 项计数笔误）遗留 Minor 逐条
裁决：多数 acceptable-to-defer（部分已因 Task 5 修复轮而自动解决），Task 5"sealed evaluator
无模型/硬件绑定"标记为 R3 阻塞项（非 R2 阻塞），Task 6"code_commit 不检查脏工作树"被提升为
新的 Important。

**发现的 3 项 Important**（完整文本见 SDD 工作区
`final-review-findings.md`，未进 Git）：
1. `formal_dev_base` 流水线跳过五维隔离断言——它独立加载 `dev.json`，不像
   `teacher_collect`/`train_export` 那样经过 `load_verified_formal_dataset` 与
   `train.json`/`holdout-receipt.json` 交叉校验；`content_fingerprint`/`derivation_fingerprint`
   刻意不含 `split`/`task_id`，理论上只有这一层交叉隔离断言能挡住被重新贴标签的内容。
2. `export_formal_train` 接收 `TeacherCollectionConfig` 参数但函数体从未读取它，teacher
   证据仅凭 `task_id` 与任务记录匹配，未核对 `evidence.task_fingerprint`/
   `trajectory.task`/`dataset_version`/`bundle_sha256`/`manifest_sha256`；独立 replay 只针对
   轨迹自带的 `task` 字段重放，两份被互换 trajectory 的证据文件各自都能重放通过。
3. `code_commit` 可能来自脏工作树（`_current_code_commit` 无 `git status --porcelain`
   检查，也无 subprocess 超时），与 Task 8 Step 5"任何相关提交后拒绝陈旧运行"的验收要求
   直接冲突；审查时工作树确实处于脏状态（本会话自己的 PROJECT_LOG 记录），非假设场景。

**决定与方案**：按 SDD 流程，整分支最终审查的修复只有一轮（无第二次完整审查）。已把 3 项
发现连同建议修法写入 `final-review-findings.md` 并派发一个 opus 模型的修复 agent 一次性
处理全部 3 项（涉及 Task 4/5/6 跨越的代码，允许跨任务文件修改），要求逐项先写失败测试。
审查报告另建议的两项优化（dev-base 双跑确定性测试、production factory 的 no-torch 单测）
标注为非阻塞可选项，不强制本轮完成。

**后果与下一步**：等待修复结果；修复+scoped re-review 通过后（无 Critical/Important 残留
或已裁决），Task 7 撰写 `docs/handoffs/<date>-r2-external-run-commands.md` 并更新阶段记录为
"CPU 实现完成、外部证据待批准"，不得标记 R2 已完成。

### LOG-20260806-01：整分支审查 3 项 Important 已修复；dev-base 现在拒绝脏工作树

- 日期：2026-08-06
- 阶段/任务：R2 / Task 7（整分支审查修复轮）
- 状态：解决
- 关联：LOG-20260805-16、`96536c9`

**背景**：按 LOG-20260805-16 派发的一次性修复轮（无第二次完整审查），逐项先写失败测试
再实现最小闭环，修复整分支审查发现的 3 项 Important。

**实现与判断**：
1. `_run_formal_dev_base` 改为先 `load_verified_formal_dataset(dev_manifest_path.parent)`
   （与 `teacher_collect`/`train_export` 同一条路径），再单独解析 `dev_manifest_path` 并要求
   它与 `dataset.dev_manifest` 完全相等，最后用 `dataset.dev_manifest` 作为公开 manifest。
   保留 `dev_manifest_path` 这个 config key（不改 schema，已提交的两份 dev config 无需改动，
   其 parent 本就含 `dataset.json`）；保留原有 `dataset_version` 交叉检查。先加载数据集再
   解析单文件的顺序是刻意的：holdout receipt 被当作 dev manifest 传入时仍按原样抛
   `ValidationError`，既有拒绝测试行为不变。
2. `export_formal_train` 新增 `_require_evidence_binds_record`，在选用某条 teacher 证据之前
   核对 `task_fingerprint`/`trajectory.task`/`dataset_version`/`bundle_sha256`/`manifest_sha256`。
   **判断项（审查留给实现方决定）：不一致时直接抛 `ValueError` 而不是静默退回
   internal_reference**——证据目录被替换/混用属完整性事件，静默降级会产出一份与正常导出
   逐字节难以区分的产物；抛错发生在 `write_formal_train_export` 之前，不违反"绝不半途导出"
   契约。刻意不比较 `config_sha256`/`seed`（导出侧用默认预算字段与导出 seed 重建 config，
   与采集时本就允许不同，比较它们会变成永远失败的断言），也不比较 `route_sha256`
   （`_teacher_evidence_route_sha256` 正是从证据自身推导该值，比较是同义反复）。
3. `_current_code_commit` 先跑 `git status --porcelain`，非空即抛 `ValueError` 并列出脏路径
   （未跟踪文件同样算脏），并把两次 git 调用收敛到 `_run_readonly_git`：统一 30 秒超时，
   把 `CalledProcessError`/`TimeoutExpired` 转成含 stderr 的可读错误。不做 `-dirty` 后缀式
   降级：`BaseEvaluationConfig.code_commit` 是严格 40 位十六进制。
   为此给 `_run_formal_dev_base` 增加 `code_commit_factory` 注入缝（与既有
   `backend_factory`/`hardware_provider_factory` 同一模式），使 CPU 测试不依赖跑测试时仓库
   恰好处于什么 git 状态；`main()` 默认路径不注入，守卫始终生效。

**对 Task 8 的直接影响（须写进外部审批命令清单）**：远程 GPU 环境必须是干净的 git checkout。
两份 dev-base config 里的 `model.revision`/`file_sha256` 目前是占位值，把真实哈希填进 YAML
后必须提交，不能只在远程工作树里就地改——否则 `formal_dev_base` 会在评测开始前拒绝运行。
这正是期望行为：config 属于冻结运行契约的一部分。

**验证**：新增 11 条测试（隔离交叉/manifest 脱钩、证据调包/治理上下文/预算字段差异豁免、
脏工作树 modified+untracked/干净仓库/超时上界/git 失败信息、默认路径拒绝脏工作树），每条
先确认 RED 原因正确。全量 `.venv/bin/pytest -q` 506 passed（修复前 495，净增 11），
Ruff/mypy/`uv lock --check`/`git diff --check` 全部干净。

**残留观察（未修，不阻塞）**：`compute_teacher_quality_report` 仍会把 attempt 目录里全部证据
计入通过率，包括 `accepted=True` 但 `trajectory=None` 的条目；由于 `scenario_by_task_id`
查表对陌生 task_id 会直接 KeyError，可利用面很窄，且不属本轮 3 项发现范围。

**后果与下一步**：交回 Task 7 做 scoped re-review 与整合评审，之后撰写
`docs/handoffs/<date>-r2-external-run-commands.md`。

### LOG-20260806-02：Task 7 收口——R2 CPU 实现（Task 1-7）完成，外部证据待批准

- 日期：2026-08-06
- 阶段/任务：R2 / Task 7 完成
- 状态：阶段变更
- 关联：LOG-20260805-10 至 LOG-20260806-01，`c4d7fdc`

**背景**：整分支修复轮（LOG-20260806-01）之后，Task 7 的 scoped re-review（opus，完整深度）
确认 3 项 Important 全部 ADDRESSED、3 个关键判断均合理，无新 Critical/Important 代码缺陷；
唯一遗留项是文档性的——外部命令清单必须完整写出脏树检查带来的执行顺序前提。

**收口证据**：
- 从头在实际最终 HEAD 重跑完整 CPU 门禁：`.venv/bin/pytest -q` 506 passed、
  `.venv/bin/ruff check .` 通过、`.venv/bin/mypy` 54 源文件通过、
  `env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check` 通过（105 packages）、
  `git diff --check` 干净。
- 超出 R2 专属治理测试范围的仓库级人工扫描：`git grep` 未发现任何 secret 形态字面量；
  `src/veritool_rl/retail_ops/`、`configs/retail_ops_*` 内无 BFCL 引用（仓库其余命中均为
  `.gitignore`/`pyproject.toml`/治理测试自身断言字符串等预期基础设施引用）；
  `data/private/`、`manifests/retail_ops/v1/`、`reports/retail_ops/` 下均无已跟踪文件
  （Task 8 尚未执行）；`git check-ignore -v` 逐条验证忽略规则确实覆盖 R2 私有/产物路径。
- formal 重复构建哈希比较已包含在 CPU 门禁内（`test_retail_ops_r2_e2e.py` 的两根逐字节
  比较）。
- 产出 `docs/handoffs/2026-08-06-r2-external-run-commands.md`：分节列出 formal freeze、
  `.env` preflight、6 任务/240 任务 teacher API 调用、只读 SSH 盘点（gpu-4090/gpu-5090
  二选一，注明 gpu-5090 已下载并校验过 Qwen3-1.7B/4B 可复用）、远端代码同步、模型下载、
  单任务/60 任务 GPU dev run、证据同步与最终验收，每条命令均标注"未执行"；第 0 节写明
  本会话整分支修复引入的真实前置条件：`formal_freeze` 公开产物须先提交（`manifests/
  retail_ops/v1/` 不在 `.gitignore` 覆盖范围）才能进入 `formal_dev_base`，dev-base config
  的真实 `model.revision`/`file_sha256` 须提交而非远端临时编辑，所有 `--output_dir` 须指向
  已忽略路径。
- `task_plan.md`/`findings.md`/`progress.md` 已同步更新（Task 5-7 独立审查发现与修复的完整
  记录、Errors 表新增 3 条）；`docs/EXECUTION_PLAN.md` 的 R2 状态**保持"当前"不变**——没有
  验收目标获得实际数据支撑的证据，不属于"已完成"。

**决定与方案**：R2 阶段状态记为"CPU 实现（Task 1-7）完成，独立审查全部通过；外部证据
（正式数据、teacher 全量、双模型 dev base）待用户逐项批准 Task 8 命令后生成"。不合并、
不 push、不标记 R2 完成。

**后果与下一步**：等待用户按 `docs/handoffs/2026-08-06-r2-external-run-commands.md` 逐条
批准 Task 8 命令；批准前 agent 不得执行清单中的任何一条外部命令。分支处置（是否/何时
merge）留待 Task 8 全部证据回收并在最终 HEAD 复验通过后，由用户决定。

### LOG-20260806-03：写出 R2 Task 8 执行提示词（未提交）

- 日期：2026-08-06
- 阶段/任务：R2 / 阶段交接文档
- 状态：解决
- 关联：LOG-20260806-02、`docs/handoffs/2026-08-06-r2-task8-execution-prompt.md`（未提交）

**背景**：用户要求给出 Task 8（审批门控的正式运行与最终收口）的启动提示词，用于在新会话
里继续 R2 剩余工作。参照 `docs/handoffs/2026-08-05-r2-task5-7-execution-prompt.md` 的
既有格式产出新版本，但性质不同——Task 8 不是 TDD 实现任务，而是"逐条获批后执行外部命令"，
因此不采用 subagent-driven-development，改为主 agent 独占执行所有 API/SSH/下载/GPU 命令。

**内容**：新提示词把 `docs/handoffs/2026-08-06-r2-external-run-commands.md` 列为主要命令
来源，明确"清单本身不是批准"——即使那份文档把命令都准备好了，仍需逐条单独获得用户确认，
不得批量执行。按 Step 1-6（对应计划 Task 8 原文）拆出 formal freeze→提交公开产物→
`.env` preflight→6 任务 smoke→（用户单独确认后）240 任务全量→远端只读盘点→代码同步→
模型下载（先问是否复用 gpu-5090 已验证的 Qwen3-1.7B/4B）→单任务 GPU smoke→60 任务 GPU
dev run→证据同步→最终整分支复审与收口的顺序，每步都是独立审批门。硬停止条件补充了
Task 7 修复引入的新检查（`formal_dev_base` 因工作树不干净被拒绝时不得绕过，须按命令清单
第 0 节顺序先提交必要文件）。

**决定与方案**：本轮只创建了提示词文件，未提交、未开始执行 Task 8 的任何操作；是否提交、
是否立即启动均等待用户决定。

**后果与下一步**：若用户批准，下一步是把此文件提交或直接用它启动新会话执行 Task 8；
所有正式数据生成、API、模型下载、SSH 与 GPU 命令仍需逐条单独审批，不因为提示词存在而
预先获得批准。

### LOG-20260806-04：Task 8 Step 1 完成——正式 240/60/120 数据集已生成并提交

- 日期：2026-08-06
- 阶段/任务：R2 / Task 8 Step 1（formal freeze）
- 状态：解决
- 关联：LOG-20260806-03、`docs/handoffs/2026-08-06-r2-task8-execution-prompt.md`、`89e8039`

**背景**：新会话按 Task 8 执行提示词接手。先完整读取固定上下文恢复顺序（CAREER_CONTEXT、
PRODUCT_BRIEF、EXECUTION_PLAN、task_plan/findings/progress、PROJECT_LOG 近期记录、SPEC、
R2 spec/plan 的 Task 8 小节、外部命令清单、提示词本身），再执行只读 preflight。

**Preflight 结果**：HEAD `665e6c8`（是 `7f77f0a`/`c4d7fdc` 的后代，工作树干净）；
`.venv/bin/pytest -q` 506 passed；Ruff、mypy（54 源文件）、`git diff --check`、
`env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check`（105 packages）全部通过；`.env`
权限 `600`，变量名精确匹配预期五项 `TEACHER_LLM_PROVIDER`/`TEACHER_LLM_DEEPSEEK_{BASE_URL,
API_KEY,MODEL,EXTRA_BODY_JSON}`。均与命令清单预期基线一致，未发现环境问题。

**Step 1 执行**：用户对精确命令单独批准（含"批准后紧接着提交公开 manifest"）后执行：

```bash
.venv/bin/retail-agent-ops build \
  --config configs/retail_ops_v1_r2_formal_freeze.yaml \
  --output_dir manifests/retail_ops/v1/retail_ops_v1_r2_20260722
```

产出私有 `data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722/{train,dev,holdout}.jsonl`
（240/60/120 行，与批准的方案 A 配额一致）与公开
`manifests/retail_ops/v1/retail_ops_v1_r2_20260722/{train.json,dev.json,holdout-receipt.json,
dataset.json}`。`dataset.json` 内嵌 `public_files_sha256` 与外部 `sha256sum` 结果逐一核对
一致；`split_category_counts` 六类均为 train 40/dev 10/holdout 20，`seed=0`，
`dataset_version=retail_ops_v1_r2_20260722`，`schema_version=2.0`，均符合冻结配额。

**决定与方案**：按命令清单第 0 节前置条件，批准执行后立即提交公开 manifest（`89e8039`：
"data: freeze RetailOps v1 R2 formal answer-free manifests"），避免后续 `formal_dev_base`
因未跟踪文件被判定工作树不干净而拒绝。私有数据保持在 ignored 路径，未进入 Git。

**后果与下一步**：Step 1 完成。进入 Step 2（`.env` preflight 只读检查 + 6 任务 teacher
API smoke，真实网络调用，预计费用 <$0.01），需用户对该节精确命令单独批准。

### LOG-20260806-05：Step 2 只读检查通过，6 任务 teacher smoke 已获批准并启动（结果待补）

- 日期：2026-08-06
- 阶段/任务：R2 / Task 8 Step 2（`.env` preflight + 6 任务 API smoke）
- 状态：进行中
- 关联：LOG-20260806-04

**背景与证据**：`.env` 只读检查（权限 `600`，五个变量名精确匹配预期）经用户确认无误后，
本地加载并打印不含密钥的 route snapshot：`provider=deepseek`、
`base_url=https://api.deepseek.com`、`model=deepseek-v4-flash`、
`extra_body={"thinking":{"type":"disabled"}}`、`route_sha256=e47b1c0da206a327afb64a868b13ca8
26d311bfbae8d07a8c5fa5595891e88a6`——与 2026-08-05 记录的正式 teacher 模型确认一致。用户
随后对命令清单第 3 节精确命令单独批准（6 条 train 任务、预计费用 <$0.01、预计耗时数秒到
约 1 分钟）。

**决定与方案**：已启动：
```bash
.venv/bin/retail-agent-ops build \
  --config configs/retail_ops_v1_r2_teacher_smoke.yaml \
  --input_dir data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722 \
  --output_dir reports/retail_ops/v1/r2/retail_ops_v1_r2_20260722/teacher-smoke-001
```
命令超过预计上限（120 秒未返回），已转入后台继续执行，未被中断或重试；按系统规则不对
仍在运行的后台任务猜测或伪造结果。

**后果与下一步**：等待命令自然完成后，本条记录将被后续 LOG 条目补充实际结果（route
snapshot 复核、6/6 结构成功率、环境成功率、总请求数、token 用量、错误分类）；结果确认
"符合预期"后才能请求 Step 3（240 任务全量）批准。

### LOG-20260806-06：Step 2 命令实际处理了全部 240 条 train（非文档描述的 6 条），发现
`refund_denied_window` 类别真实通过率 30%——已停止，未请求 Step 3 批准

- 日期：2026-08-06
- 阶段/任务：R2 / Task 8 Step 2（发现文档/配置不一致 + teacher 质量信号）
- 状态：阻塞（等待用户决定）
- 关联：LOG-20260806-05、`configs/retail_ops_v1_r2_teacher_smoke.yaml`、
  `docs/handoffs/2026-08-06-r2-external-run-commands.md` 第 3 节

**发现（文档/配置不一致，非代码缺陷）**：命令完成后 `summary.json` 显示
`processed_this_run=240`、`train_task_count=240`，而不是命令清单第 3 节承诺的"每类别 1
条、共 6 条"。核实私有 `teacher-collection/teacher-smoke-001/` 目录，确认写入 241 个文件
（240 条任务证据 + `checkpoint.json`），逐一比对 `data/private/.../train.jsonl` 的 240 个
`task_id` 全部命中。根因：`configs/retail_ops_v1_r2_teacher_smoke.yaml` 的 `pipeline:
teacher_collect` 没有任何任务数量限制字段（只有 `max_episodes_per_task: 1`、
`max_request_attempts: 1` 降低了单任务重试预算），`teacher_collect` 代码本身也没有"6 任务"
筛选逻辑——它会处理 `--input_dir` 私有根目录下 `train.jsonl` 的全部记录。命令清单第 3 节
"6 条"的描述是文档层面的错误设想，从未与实际实现核对过。本会话在派发这条命令给用户批准前
展示了文档里的"6 任务"描述，但未在批准前先读 `.yaml` 文件核实数量——这是本会话自己的
verification 缺口，而非用户批准范围之外的越权执行（用户确实批准了这条精确命令；只是命令
实际行为与展示给用户的描述不符）。

**真实影响（已核实，非估算）**：
- 未触碰 dev/holdout——证据文件数与 train 记录数精确一致（240），isolation 未被违反。
- 真实网络请求：519 次（`request_attempts` 汇总），299,956 prompt tokens + 45,893
  completion tokens；按 2026-08-05 记录的 DeepSeek 单价（$0.14/M 输入、$0.28/M 输出）
  折算约 **$0.055**，而非承诺的 "<$0.01"（约 5.5 倍，绝对金额仍很小，CAREER_CONTEXT 明确
  成本非硬约束）。
- outcome 分布：`success=211`、`policy_violation=28`、`transport_exhausted=1`（总 240）。
- 整体通过率 211/240=87.9%（高于 70% 门槛），但**逐类别聚合发现
  `refund_denied_window` 仅 12/40=30.0%，低于 50% 每类别门槛**；其余 5 类
  （`lookup_status` 39/40、其余 4 类均 40/40）全部远高于门槛。
- 对 28 条 `refund_denied_window` 失败样本做了不含原始任务内容的聚合诊断（只读
  `trajectory.violations`/`termination`，未打印 user_request/order_id 等字段）：全部 28
  条的 `termination=policy_violation`、`violations=('refund_not_eligible',)`——即 teacher
  在窗口已过期、任务期望拒绝退款的场景下，仍然真实执行了 `refund_order`。28 条失败模式
  完全一致（同一违规码），不是随机传输错误，提示这更像 teacher 对退款窗口边界政策的系统性
  误判，而不是本次 `max_episodes_per_task=1`/`max_request_attempts=1` 降低重试预算导致的
  偶发失败——但尚未用完整预算（2 episode/3 attempt）验证这个判断，不能排除部分样本在更多
  重试下会转为成功。

**决定与方案**：按 CLAUDE.md 第 1 节"发现冲突或高影响信息缺失时，停止并询问用户，不得自行
扩展方向"与 Task 8 提示词硬停止条件（"teacher 总通过率<70%或任一类别<50%——停止并报告，
不自动换 provider/model/prompt"），本会话已停止，**未请求 Step 3（240 任务正式全量采集）
批准**，也未修改 prompt/parser/模型/provider/阈值。已把发现原样报告给用户，交由用户决定：
(a) 是否需要先修正命令清单文档对 `teacher_collect` 行为的描述（不影响产品代码，只是文档
准确性）；(b) 是否仍要在完整预算（`teacher_full.yaml`：`max_episodes_per_task=2`、
`max_request_attempts=3`，独立 `attempt_id=teacher-full-001`，不复用本次 checkpoint）下
正式运行 Step 3 以获得权威质量门判定，还是先诊断/等待 `refund_denied_window` 问题再决定；
(c) 本次 `teacher-smoke-001` 采集的私有证据是否保留（未提交 Git，产品代码不会用它替代
正式 `teacher-full-001` 的质量门判定，`export_formal_train` 只按调用方传入的证据集合计算
质量门，不会跨 attempt_id 静默合并）。

**后果与下一步**：Task 8 Step 2 暂停在"结果不符合预期"状态，未获得用户对 Step 3 的确认，
不进入 Step 3 审批门。

### LOG-20260806-07：确认 `refund_denied_window` 失败根因是任务/环境设计缺陷，非模型能力问题

- 日期：2026-08-06
- 阶段/任务：R2 / Task 8 Step 2（诊断，用户指示"先诊断 refund_denied_window 失败样本"）
- 状态：阻塞（等待用户对补救方案决策）
- 关联：LOG-20260806-06、`src/veritool_rl/retail_ops/formal_tasks.py`、
  `src/veritool_rl/retail_ops/environment.py`、`src/veritool_rl/agent/runner.py`

**诊断过程**：只读检索 `domains/retail_ops/v1/tools.yaml`（`refund_order` 工具描述只写
"为符合政策的订单办理退款"，未说明窗口规则）、`agent/runner.py` 的 `SYSTEM_PROMPT`
（"退款前必须查询订单，遇到 transient_error 时可以重试"，未提及窗口/日期）、
`formal_tasks.py::_user_request`（`refund_denied_window` 场景文案为中性的"请检查订单
{order_id} 是否能因 {reason} 退款"，不含任何日期/时长提示）、`environment.py::_get_order`
（返回 `copy.deepcopy(order)`，`order` 字典只有 `customer_id`/`status`/`refund_deadline`/
`refund_status` 四个字段，**不含 `current_day`**）、`formal_tasks.py::_materialize_task`
（`current_day` 只写入 `initial_state`，从未通过任何工具响应或消息暴露给模型）。抽查一条
真实失败轨迹（train 私有数据，非 holdout）验证：`get_order` 返回
`{"refund_deadline": 19, "refund_status": "none", "status": "delivered", ...}`，不含
`current_day`；模型随即调用 `refund_order` 被环境拒绝（`error_code=policy_denied`，
`error="订单已超过退款期限"`），这次调用本身被 `environment.py::_refund_order` 记为
`_deny("refund_not_eligible", ...)` 违规。

**根因**：`refund_denied_window` 是唯一一个"disqualifying 信号不可从 `get_order` 响应直接
推断"的 DENY 类别。对照另外两个 DENY 类别可确认差异：`refund_denied_ownership` 时
`environment.py::_get_order` 会在 `order.customer_id != state.customer_id` 时直接返回
`ok=False, error_code=not_found`——模型第一步就拿到明确信号，不需要额外参照；
`refund_denied_duplicate` 时 `get_order` 直接把 `refund_status="refunded"` 字段原样返回，
同样是可直接读出的信号。只有 `refund_denied_window` 需要比较 `refund_deadline`（如 19）
与"今天"（`current_day=20`，固定常量）的大小关系，而"今天"这个参照值在系统提示词、
`user_request` 和全部工具响应中都不存在——**任何模型，无论能力强弱，都无法仅凭对话历史
判断这个订单是否过期**，只能靠调用 `refund_order` 试探（试探本身就被记为策略违规）或纯粹
猜测。这不是 teacher 模型（`deepseek-v4-flash`）的能力缺陷，是 `formal_tasks.py`/
`environment.py` 的任务设计缺口：该场景对真实推理式 agent 事实上不可解，只有直接读取
`expected_decision` 的 Oracle policy（R1-R7 CPU 测试和 internal_reference 回退用的都是
Oracle）才会"看起来正确"，因为 Oracle 作弊读取真值而不是从暴露信息推理。这解释了为什么
Task 1-7 长达 506 个测试和多轮独立审查都未发现——CPU 测试从未让一个"只能看对话历史"的
真实推理 agent 独立解出这个场景。

**范围**：三个 DENY 场景共享同一套 `_materialize_task`/`_get_order` 实现，`current_day`
的缺失只影响 `refund_denied_window`（train/dev/holdout 各 40/10/20 条，占六类总量的
1/6）；其余 5 个场景不受影响。若不修复，该场景对训练数据（teacher 或 internal_reference
都无法提供可泛化学习信号——internal_reference 端也只是把不可推断的真值直接搬进 SFT 目标）
和后续评测（候选模型大概率同样系统性答错）都会造成不可解的固定失分，与"教师能力不足"或
"budget 不够"是完全不同性质的问题，无法通过换模型/加预算解决。

**决定与方案**：未修改任何代码。按 CLAUDE.md 第 3 节"重大产品、模型、数据、算法和部署
选择先给至少两个方案，等待用户决定"，把根因和至少两个候选补救方向原样报告给用户，
不自行选择方向或开始实现。

**后果与下一步**：等待用户决策后续路径（是否修复环境暴露 `current_day`/相对天数信息、
是否重新冻结受影响 split、如何处理已产生的 `teacher-smoke-001` 证据）；在决策前不请求
Step 3 批准，不修改 `environment.py`/`formal_tasks.py`/prompt/parser。

### LOG-20260806-08：用户决策——修复 `environment.py::_get_order` 暴露 `current_day`，无需重新冻结数据

- 日期：2026-08-06
- 阶段/任务：R2 / Task 8 修复轮（`refund_denied_window` 环境设计缺陷）
- 状态：进行中
- 关联：LOG-20260806-07

**决定**：用户选择"修复环境暴露日期信息"方向（而非保留现状记录为已知限制，也未选择
"相对剩余天数"的替代表达）。技术方案已与用户逐条确认：`environment.py::_get_order` 的
`Observation.content` 统一（不区分场景）额外加入 `current_day` 字段（来自
`self._state.get("current_day")`），与已有 `refund_deadline` 字段并列返回，让推理式
agent 能直接比较两者判断是否过期。

**关键判断（本会话核实，非用户逐字指示）**：`content_fingerprint`/`derivation_fingerprint`
和已冻结的 task manifest 只依赖 `TaskSpec`（`initial_state`/`target_state`/
`expected_calls` 等），不依赖 `environment.py` 运行时如何构造工具响应；`current_day` 早已
写入 `_materialize_task` 产出的 `initial_state`（`formal_tasks.py` 第 380 行），只是运行时
从未通过任何工具响应暴露出来。因此本次修复**不需要重新生成或重新冻结 train/dev/holdout**，
Step 1 已提交的公开 manifest（`89e8039`）和私有 jsonl 保持有效，只需修复
`environment.py` 的运行时行为。

**范围**：按 CLAUDE.md 第 6 节先写 `task_plan.md`，再走 TDD（先写失败测试确认真实原因，
再最小实现），修改点集中在 `src/veritool_rl/retail_ops/environment.py::_get_order` 及其
覆盖测试（`tests/test_retail_ops_environment.py` 等 grep 命中的相关测试文件，逐一核实是否
对 `get_order` 返回内容做了不含 `current_day` 的精确断言）。完成后需要独立审查（复用
Task 1-7 建立的实现后独立复审模式），确认无 Critical/Important 后再恢复 Task 8 Step 2/3
的真实 API 调用。已产生的 `teacher-smoke-001` 私有证据（240 条，基于修复前环境采集）
保留在原地供审计追溯，但不会被当作正式 teacher 采集结果使用——Step 3 的官方全量采集会
用独立的新 `attempt_id`（`teacher-full-001`）在修复后的环境下重新进行。

**后果与下一步**：进入 TDD 实现；完成并通过全套质量门 + 独立审查后，回到 Task 8 Step 2/3
外部命令审批门（在修复后的环境下重新执行，并需要重新明确"6 任务"描述与实际
`teacher_collect` 行为不符的文档问题该如何处理）。

### LOG-20260806-09：`environment.py::_get_order` 修复完成，TDD 通过，等待独立审查

- 日期：2026-08-06
- 阶段/任务：R2 / Task 8 修复轮
- 状态：进行中
- 关联：LOG-20260806-08

**实现**：`src/veritool_rl/retail_ops/environment.py::_get_order` 在 `Observation.content`
里统一追加 `content["current_day"] = self._state.get("current_day")`（紧跟已有的
`refund_deadline` 等字段），`_refund_order`/`_get_store_hours`/`not_found` 分支未改。
`tests/test_retail_ops_environment.py` 新增两个测试：
`test_get_order_exposes_current_day_so_window_denial_is_inferable`（REFUND_DENIED_WINDOW
场景断言 `get_order` 返回内容同时含 `current_day`/`refund_deadline`，且与
`task.initial_state` 中的真值一致）与
`test_get_order_current_day_matches_env_state_for_every_scenario`（REFUND_ELIGIBLE 场景
交叉验证暴露不区分场景）。TDD 全程：先确认 RED（`KeyError: 'current_day'`，原因正确），
再最小实现。

**验证**：
- `.venv/bin/pytest -q` 508 passed（基线 506 + 新增 2 条），`.venv/bin/ruff check .`、
  `.venv/bin/ruff format --check`、`.venv/bin/mypy`（54 源文件）、`git diff --check` 全部
  通过。全仓搜索确认没有测试对 `get_order` 返回内容做精确 dict 相等断言会被新字段破坏。
- **关键判断已验证（非假设）**：`grep` 确认 `formal_tasks.py`/`formal_manifests.py`
  完全不 import `environment.py`——数据生成/冻结流水线与 `RetailOpsEnv` 运行时完全独立，
  修复 `_get_order` 不可能影响已冻结的 `train/dev/holdout.jsonl` 或已提交的公开 manifest。
  （原计划用"临时目录重新生成再比对哈希"做实证验证，但 `build_formal_task_set()` 本身不
  接收 `bundle` 参数、不产出 bundle 印章字段，直接跟磁盘文件比对会产生误报差异；改用更
  直接的静态引用检查，结论同样成立且更可靠。）

**后果与下一步**：修复完成，进入独立审查（复用 Task 1-7 的实现后独立复审标准）；通过后
提交，再恢复 Task 8 Step 2（在修复后的环境下重新执行 teacher smoke，同时需要用户对
"6 任务"文档描述不符的问题给出处理方式）。

### LOG-20260806-10：独立审查 PASS，`environment.py` 修复无 Critical/Important 问题

- 日期：2026-08-06
- 阶段/任务：R2 / Task 8 修复轮 → 独立审查
- 状态：解决
- 关联：LOG-20260806-09、`11029bb`

**审查范围**：`git show 11029bb` 全量 diff、`environment.py`、`agent/runner.py`、
`agent/qwen.py`、`trajectory/schema.py`、`trajectory/replay.py`、`rewards/verifier.py`、
`formal_tasks.py`/`formal_manifests.py`、`envs/mini_retail.py`，以及全仓
`get_order`/`.content`/`current_day`/`refund_deadline` 引用点；独立重跑
`.venv/bin/pytest -q`（508 passed）、Ruff、mypy 确认干净。

**结论：PASS，无 Critical/Important**。逐项核实：
1. 正确性：暴露的 `current_day`/`refund_deadline` 与 `_refund_order` 内部判定逻辑
   （`current_day > refund_deadline`）完全一致，含边界情况（`_MARGINS` 固定为
   `(1,2,3,5,7,10,14)`，永远 ≥1，边界相等场景在冻结数据中不会出现，但设计本身在边界处
   一致，不是近似）。
2. 无信息泄漏：`_CURRENT_DAY=20` 是所有任务/场景/split 共享的全局常量，非任务级机密；
   ownership 分支仍在 `current_day` 那行之前就以 `not_found` 短路，跨客户泄漏不受影响。
3. 一致性：`perturb_schema`/`_get_store_hours`/`_deny` 均无需同步修改。一项 Minor（超出
   本次范围）：legacy `src/veritool_rl/envs/mini_retail.py`（未接入 R2 流水线，
   `product_cli.py` 不引用）有相同潜在缺口，留作后续可选项，不阻塞本次修复。
4. 无回归：`Observation.content` 是 `Any` 类型、无 Pydantic 精确字段集合校验；
   `rewards/verifier.py` 的 reward 计算读内部 `_state` 而非 `Observation.content`；
   数据生成路径不 import `environment.py`，已提交公开 manifest 确认不受影响。唯一需要
   注意（非本次缺陷）：`trajectory/replay.py` 会精确比较 `Observation`，意味着修复前
   `teacher-smoke-001` 采集的 240 条证据无法用修复后的环境重放——这与 LOG-20260806-08/09
   已记录的处置一致（该批证据保留仅供审计，Step 3 用独立新 `attempt_id` 重新采集）。
5. 测试充分性：第一个新测试偏同义反复（CPU 测试无法证明"模型能推理"，只能证明管线正确），
   第二个跨场景测试是真正有效的防护（防止"只在 window 场景加字段"这种会重新引入不一致的
   捷径修法）。
6. 替代设计：`formal_tasks.py::_normalized_order` 里已有 `refund_deadline_offset`（相对值，
   仅用于 fingerprint 去重，不面向模型）说明相对天数是一个真实存在过的备选方案；用户已在
   LOG-20260806-08 明确选择绝对双字段暴露，非遗漏步骤。唯一开放点：`SYSTEM_PROMPT`
   未显式解释这两个字段的语义，属于合理的"让模型自己从字段名推断"的赌注，审查建议：
   若接下来的 Step 2 重跑里这一类别仍因"读错字段"类原因欠佳，下一步应先补
   `SYSTEM_PROMPT` 说明而非怀疑环境修复本身失败。

**后果与下一步**：修复轮结束。回到 Task 8 Step 2：需要用户决定 (a) 如何处理"6 任务"
文档描述与 `teacher_collect` 实际行为（无任务数限制）不符的问题，(b) 是否现在批准在修复后
环境下重新执行 teacher 采集（新 `attempt_id`，真实网络调用与费用）。

### LOG-20260806-11：用户决策——跳过重复 smoke，直接批准完整预算全量采集（结果待补）

- 日期：2026-08-06
- 阶段/任务：R2 / Task 8 Step 3（240 任务 teacher 全量采集 + train 导出）
- 状态：进行中
- 关联：LOG-20260806-10

**决定**：已把命令清单第 3 节文档更正为准确描述（`teacher_smoke.yaml` 无任务数限制，
"smoke"/"full" 真实差异只是重试预算 1/1 vs 2/3，两者费用量级相近），提交 `63137aa`。
用户在此基础上选择跳过重复的 smoke 步骤，直接批准完整预算全量采集（避免对同一批 240 条
任务重复花费两次真实费用）。

**已批准并启动**：
```bash
.venv/bin/retail-agent-ops build \
  --config configs/retail_ops_v1_r2_teacher_full.yaml \
  --input_dir data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722 \
  --output_dir reports/retail_ops/v1/r2/retail_ops_v1_r2_20260722/teacher-full-001
```
`attempt_id=teacher-full-001`（新 ID，不复用 `teacher-smoke-001` 的证据/checkpoint）、
`max_episodes_per_task=2`、`max_request_attempts=3`。命令已转入后台执行，尚未返回结果；
按系统规则不对仍在运行的任务猜测结果。

**后果与下一步**：等待命令完成后，本条记录将由后续 LOG 条目补充实际结果（teacher
总/逐类别通过率——重点核实 `refund_denied_window` 是否真的改善、请求数、token 用量、
费用、耗时），随后批准执行 `train_export`（`teacher_attempt_id=teacher-full-001`，
质量门 70%/50%，不达标则停止报告，不自动改 prompt/模型/provider）。

### LOG-20260806-12：`teacher-full-001` 完成——环境修复确认有效，`refund_denied_window` 30%→95%

- 日期：2026-08-06
- 阶段/任务：R2 / Task 8 Step 3（240 任务 teacher 全量采集）
- 状态：解决
- 关联：LOG-20260806-11

**结果（已核实，非估算）**：命令退出码 0，实际耗时 11 分 23 秒。`summary.json`：
`processed_this_run=240`、`total_accepted=238`。私有证据目录 240 个文件（与 train 任务数
精确一致，未触碰 dev/holdout）。逐类别通过率：
- `lookup_status` 40/40=100%、`refund_denied_duplicate` 40/40=100%、
  `refund_denied_ownership` 40/40=100%、`refund_eligible` 40/40=100%、
  `refund_recovery` 40/40=100%；
- **`refund_denied_window` 38/40=95.0%**（LOG-20260806-06 修复前的同预算对照组是
  12/40=30.0%；本次预算已提升到 2 episode/3 attempt，但提升幅度远超预算差异能解释的量级，
  确认环境修复是主因）。剩余 2 条失败均为 `episode_index=1`（重试后仍失败）、
  `violations=refund_not_eligible`，判定为零星推理失误而非系统性问题（95% 远高于 50%
  每类别门槛，不阻塞）。

整体 238/240=99.2%，outcome 分布 `{success: 238, policy_violation: 2}`，无
`transport_exhausted`/`schema` 类失败。真实请求 526 次，306,189 prompt + 46,700
completion tokens，按已记录单价折算约 **$0.0559**（预计 $0.05-0.15 区间内）。质量门
（整体≥70%、每类别≥50%）大幅通过。

**决定与方案**：结果符合预期，环境修复的有效性已用真实数据验证。进入 `train_export`
审批门。

### LOG-20260806-13：`train_export` 完成——Task 8 Step 3 收口，240 条正式 train 已导出

- 日期：2026-08-06
- 阶段/任务：R2 / Task 8 Step 3（train_export）
- 状态：解决
- 关联：LOG-20260806-12

**结果**：批准执行后命令退出码 0（本地 CPU，无真实网络调用）。公开
`train-export-001/quality.json`：`passes_gate=true`、`overall_pass_rate=0.9917`、
`refund_denied_window=0.95`（其余五类均 1.0）、`total_accepted=238`/`total_tasks=240`，
与 `teacher-full-001` 的采集结果逐字段一致。私有
`train-export/train-export-001/{train.jsonl,sft.jsonl,selection.json}` 各 240 行；
`selection.json` 来源构成 `teacher=238`、`internal_reference=2`（精确对应
`refund_denied_window` 剩余的 2 条零星失败，Oracle 回退按设计工作）。

**决定与方案**：Task 8 Step 3（240 任务全量采集 + train 导出）完成。正式 train 数据现已
就绪：240/60/120 formal 数据集（Step 1）+ 240 条 teacher/internal_reference 混合 train
轨迹（Step 3），可供后续 R3 QLoRA-SFT 使用（不在本任务范围内）。

**后果与下一步**：进入 Task 8 Step 4（远端只读盘点 + GPU 审批门，gpu-4090/gpu-5090
二选一）。

### LOG-20260806-14：Step 4 只读盘点完成，选定 gpu-5090

- 日期：2026-08-06
- 阶段/任务：R2 / Task 8 Step 4（远端只读盘点）
- 状态：解决
- 关联：LOG-20260806-13

**决定**：用户选择 gpu-5090（Qwen3-1.7B/4B 已下载并逐文件 SHA256 校验通过，可直接复用，
无需重新下载 11.4G）。按 CLAUDE.md 第4节记录：本任务本阶段只使用 gpu-5090，不使用
gpu-4090。

**盘点结果（只读，无副作用）**：
```
ssh gpu-5090 'nvidia-smi --query-gpu=... --format=csv'
→ index=0, uuid=GPU-07af326b-f41d-a706-2150-bc560c7db304, name=NVIDIA GeForce RTX 5090,
  memory.used=5360 MiB, memory.total=32607 MiB, utilization=0%
ssh gpu-5090 'nvidia-smi --query-compute-apps=...'
→ 两个其他用户进程占用（pid 455812/2784MiB、pid 457566/2460MiB），确认多人共用属实
ssh gpu-5090 'nproc && free -h' → 24 核，62Gi 内存，55Gi 可用
ssh gpu-5090 'df -h /mnt/aidata' → 3.6T 总量，1.9T 空闲（45% 已用）
ssh gpu-5090 'whoami && pwd' → tongjiakai / /home/tongjiakai
```
物理 GPU 0 空闲显存约 27GB，磁盘空闲 1.9T，均充足支撑 Qwen3-1.7B/4B 4-bit NF4 单卡评测。

**后果与下一步**：进入远端代码同步审批门（`git bundle` 传输已提交历史 + `uv sync --extra
teacher` + 确认远端工作树干净）。

### LOG-20260806-15：远端代码同步完成，gpu-5090 HEAD 快进到 `f3543e7`

- 日期：2026-08-06
- 阶段/任务：R2 / Task 8 Step 4（远端代码同步）
- 状态：解决
- 关联：LOG-20260806-14

**结果**：`git bundle create` 只含已提交历史（无未提交改动混入）；`scp` 传输到
`gpu-5090:/tmp/`；远端 `git fetch` 到 `incoming` 分支后核对 `incoming` HEAD
（`f3543e7afe13951997fba90fb4be57d65c2b5e51`）与本地 HEAD 完全一致，且确认远端原分支
（`155d67a`，Task 2 治理复审记录）是 `incoming` 的祖先，可安全快进。用户批准后执行
`git merge --ff-only incoming`（Fast-forward，44 files changed），删除临时 `incoming`
分支。`uv sync --extra dev --extra train --extra teacher --frozen` 成功，新增
`openai==2.46.0`/`distro`/`jiter`/`sniffio`。同步后核实：远端工作树干净
（`git status --porcelain` 空）、`openai 2.46.0` 可导入、`torch 2.13.0+cu130` 且
`cuda.is_available()=True` 不受影响。

**后果与下一步**：进入模型审批门——先问用户是否复用 gpu-5090 已下载并校验过的
Qwen3-1.7B/4B（而非重新下载）。

### LOG-20260806-16：复用 gpu-5090 已有模型，回填并提交真实 model pin

- 日期：2026-08-06
- 阶段/任务：R2 / Task 8 Step 4（模型审批门）
- 状态：解决
- 关联：LOG-20260806-15

**决定**：用户选择复用 gpu-5090 已下载并逐文件 SHA256 校验过的 Qwen3-1.7B/4B（3.8G/7.6G，
2026-08-05 下载），不重新下载 11.4G。

**执行**：`ssh gpu-5090 'ls -la .../models/Qwen3-{1.7B,4B}/'` 确认文件存在（各 14 个文件，
含 `.gitattributes`）；批准后创建符号链接 `models/Qwen3-{1.7B,4B}-pinned` 指向
`/mnt/aidata/tongjiakai/models/Qwen3-{1.7B,4B}/`（不复制数据）。用
`hash_local_model_files` 重新逐文件计算 SHA-256（不信任旧的整仓库级 ModelScope commit
哈希）：1.7B 12 个文件、4B 13 个文件（额外一个 safetensors 分片），逐文件哈希已记录在
两份 config 里。回填本地 `configs/retail_ops_v1_r2_qwen3_{1_7b,4b}_dev.yaml` 的
`model.revision`（ModelScope commit `980712f5...`/`8cd0101f...`）与 `model.file_sha256`
（真实逐文件值，替换原占位 3 键示例为完整 12/13 键列表）。

**验证**：YAML 解析确认 revision/file 数量正确；`.venv/bin/pytest -q` 508 passed，Ruff、
mypy（54 源文件）、`git diff --check` 全部通过。按命令清单第 0 节第 2 点，改完立即提交
（`06af683`）——不提交会导致远端 `formal_dev_base` 因工作树/config 与本地不一致被拒绝。

**后果与下一步**：需要把这个新提交同步到 gpu-5090（重复第 6 节的 bundle/fetch/ff-only
流程），之后才能进入单任务 GPU smoke。

### LOG-20260806-17：Qwen3-1.7B dev run 首次尝试因符号链接触发路径逃逸检查失败

- 日期：2026-08-06
- 阶段/任务：R2 / Task 8 Step 4（GPU dev run）
- 状态：阻塞（等待用户确认修复方式）

**决定**：跳过命令清单第 8 节设想的"单任务 smoke"（CLI 无任务数限制机制，同 Step 2 教训），
直接对 Qwen3-1.7B 批准执行完整 60 任务 dev run（gpu-5090 物理 GPU 0）。

**失败**：命令在模型加载后立即失败：
`ValueError: 目标路径逃逸出受信根目录: models/Qwen3-1.7B-pinned`。根因是
`base_evaluation.py::_resolve_within`（Task 5 审计过的安全检查）对 `models_root` 拼接结果
做 `resolve()` 并拒绝任何解析后逃逸出受信根目录的路径，专门用来挡"中间某段是指向仓库外的
符号链接"——而命令清单文档第 7 节建议的"用符号链接指回真实存储路径，不复制 11.4G"方案
（`models/Qwen3-1.7B-pinned -> /mnt/aidata/tongjiakai/models/Qwen3-1.7B`，指向仓库外）
正是这条检查设计要拦截的情况。这是命令清单文档与已审计安全实现之间的真实冲突，不是产品
缺陷，不应绕过或放宽这条检查。

**解决**：不放宽检查。删除两个符号链接，改为 `cp -r` 把模型文件真实复制进
`models/Qwen3-{1.7B,4B}-pinned/`（受信根目录内），用 config 里的真实哈希重新
`verify_local_model_files` 通过。状态改为解决。

### LOG-20260806-18：gpu-5090 缺系统 C 编译器，装 ziglang 作为用户态 CC

- 日期：2026-08-06
- 阶段/任务：R2 / Task 8 Step 4（GPU dev run）
- 状态：解决

**背景**：修复符号链接问题后重跑 Qwen3-1.7B，模型加载成功，但真实推理（RoPE 计算）失败：
`torch==2.13.0+cu130` 的 `bmm_outer_product` 算子走 Triton JIT 编译，需要系统 C 编译器；
gpu-5090 上 `gcc`/`cc`/`g++` 均不存在，也没有免密 sudo 或 conda——这是该服务器第一次真正
跑模型 `generate()`（此前只验证过 `torch.cuda.is_available()`），暴露出真实基础设施缺口。

**决定**：不在共享服务器上装系统包（需要 root，会影响其他用户）。改为给 `train` extra
新增 `ziglang`（pip 可装的用户态 C 编译器）依赖，并新增仓库脚本 `scripts/zig-cc`
包装 `python -m ziglang cc`，通过 `CC=$(pwd)/scripts/zig-cc` 环境变量提供给 triton。
`pyproject.toml`/`uv.lock` 已提交（`7cea3dc`），远端已 `uv sync` 安装。

**修正**：zig-cc 实际用上后暴露新问题——它能编译，但链接阶段报
`ld.lld: error: unable to find library -l:libcuda.so.1`；手动加 `-v` 复现确认根因是
zig 的 cc 前端用自己打包的一套 glibc shim 库直接构造链接命令，完全不转发 `-L` 参数去
搜索宿主系统目录（即便 `libcuda.so.1` 确实存在于 `/lib/x86_64-linux-gnu/`），不是常规
编译器行为，短期内无法可靠修好。改为直接读 `torch._native/triton_utils.py` 源码，
发现 `TORCH_DISABLE_NATIVE_JIT=1` 是官方预留的开关（`check_native_jit_disabled()`），
设置后会跳过这整条 Triton override 注册，RoPE 计算回退到普通 PyTorch 实现，完全不需要
任何编译器。验证通过后，ziglang 依赖和 `scripts/zig-cc` 判定为不再需要，已回退移除
（`pyproject.toml`/`uv.lock` 恢复、脚本删除），508 测试/Ruff/mypy/diff 全绿。

**结果（Qwen3-1.7B dev base，`CUDA_VISIBLE_DEVICES=0 TORCH_DISABLE_NATIVE_JIT=1`）**：
物理 GPU 0（RTX 5090，`GPU-07af326b-f41d-a706-2150-bc560c7db304`），峰值显存
1,525,927,936 字节（约1.42GB，4-bit NF4），wall time 75.7s（总耗时约89.5s，含模型加载），
60/60 任务、`task_success=0.70`、`policy_violation_rate=0.0`、`schema_valid_rate=0.971`、
`argument_accuracy=0.7`、`tool_selection_accuracy=0.696`、`recovery_success=0.2`、
`evidence_complete=true`、`replayable_count=60`。用 `load_base_run_evidence` 指向私有
`dev-base/qwen3-1.7b-dev-base-001/run.json` 重新加载并完整校验产物哈希，`run_id` 一致，
未被篡改。

### LOG-20260807-01：Qwen3-4B dev base 完成，两模型 dev base 均获得完整证据

- 日期：2026-08-07
- 阶段/任务：R2 / Task 8 Step 4（GPU dev run）
- 状态：解决
- 关联：LOG-20260806-18

**结果（`CUDA_VISIBLE_DEVICES=0 TORCH_DISABLE_NATIVE_JIT=1`，同一物理 GPU 0、同一
bundle/manifest/parser/seed=0/预算，仅 model/attempt_id 不同，可配对比较）**：峰值显存
2,941,568,000 字节（约2.74GB），wall time 154.0s，`task_success=0.80`、
`policy_violation_rate=0.133`（8/60，全部为 `refund_denied_window` 或误判场景，高于
1.7B 的 0）、`schema_valid_rate=0.781`（低于 1.7B 的 0.971）、`invalid_call_rate=0.219`
（远高于 1.7B 的 0.029）、`recovery_success=0.5`（高于 1.7B 的 0.2）、
`evidence_complete=true`、`replayable_count=60`。`load_base_run_evidence` 重新加载私有
`dev-base/qwen3-4b-dev-base-001/run.json` 并完整校验产物哈希通过，`run_id` 一致。

**观察**：4B 相对 1.7B 最终任务成功率更高（0.80 vs 0.70）、恢复能力更强，但 schema
有效率更低、非法调用率显著更高、政策违规从 0 升到 8——不是单调的"更大模型更好"，是
真实的 base 权衡信号，原样记录，不做解释或调优（R2 不训练、不调 prompt）。两份 dev base
现已完整（Task 8 Step 4 GPU 部分完成），进入 Step 5（证据同步）。

### LOG-20260807-02：Task 8 Step 6 独立复审 PASS，CPU 门禁在最终 HEAD 重跑通过

- 日期：2026-08-07
- 阶段/任务：R2 / Task 8 Step 6（最终验证与收口）
- 状态：解决
- 关联：LOG-20260807-01

**验证**：最终 HEAD（`5b3b45f`）重跑 `.venv/bin/pytest -q`（508 passed）、
`.venv/bin/ruff check .`、`.venv/bin/mypy`（54 源文件）、`uv lock --check`、
`git diff --check` 全部通过；仓库级 secret/BFCL/holdout 泄漏扫描干净（`holdout-receipt.json`
仅含指纹/计数，无任务内容）。独立复审（`c4d7fdc..HEAD`）**结论 PASS**：核实 PROJECT_LOG
数字声明与实际产物字段（`dataset.json`/`quality.json`/两份 `base-report.json`）逐一吻合；
`environment.py` 自 `11029bb` 后未被改动；从公开 `dev.json` **独立重算**
`dev_manifest_sha256` 与两份 `base-report.json` 记录逐字符一致（排除哈希编造可能）；
ziglang 加入又移除干净无残留；两份 dev-base config 的 `model.revision`/`file_sha256`
为真实值且与 `base-report.json` 一致；未发现任何 Critical/Important 问题。

**收口证据清单**：正式 240/60/120 formal 数据集（五维隔离，manifest 哈希闭合）；teacher
全量 238/240 通过质量门（六类全部 ≥50%）；两份 Qwen3-1.7B/4B dev base（60/60 任务，
证据完整、哈希重载校验通过、GPU/commit/config provenance 齐全）；仓库级泄漏扫描干净；
完整 CPU 门禁在最终 HEAD 通过。是否满足 `docs/EXECUTION_PLAN.md` R2 验收目标、能否标记
R2 已完成，交由用户最终确认。

### LOG-20260807-03：用户确认 R2 已完成，`docs/EXECUTION_PLAN.md` 状态更新

- 日期：2026-08-07
- 阶段/任务：R2 收口 → R3 启动前
- 状态：阶段变更
- 关联：LOG-20260807-02

**决定**：用户核对 R2 五项验收目标与实际证据的对照表后，明确确认 R2 已满足验收目标。
`docs/EXECUTION_PLAN.md` 阶段总览表：R2 状态由"当前"改为"已完成"，R3（单卡适配与服务
v1）由"待执行"改为"当前"。

**后果与下一步**：R3 尚未启动任何实现；QLoRA-SFT、adapter 训练、下载/smoke Qwen3-4B 等
均需用户单独确认后才能开始，本次状态变更不构成对 R3 具体任务或时间表的授权。分支
（`feature/r2-formal-data-and-base-eval`）处置仍需单独走 finishing-a-development-branch
流程，不因阶段状态变更而自动 merge。

### LOG-20260807-04：R3 SFT 执行提示词与两处代码缺口

- 日期：2026-08-07
- 阶段/任务：R3 / Task 1 启动准备
- 状态：进行中（待用户确认目标模型）
- 关联：LOG-20260807-03、`docs/handoffs/2026-08-07-r3-sft-execution-prompt.md`

**只读盘点发现的两处真实缺口**（不是提示词里的设想，是核实过的代码事实）：
1. `training/sft.py::ModelSettings` 只有 `name: str` 路径，**没有** `revision`/`file_sha256`
   逐文件哈希锁定（对比 `base_evaluation.py::ModelArtifact` 已有的完整 pin）。按 CLAUDE.md
   第 5 节"正式运行固定模型标识并保存 manifest"，正式训练前必须补上并调用已有的
   `verify_local_model_files`，否则训练可能悄悄跑在未校验的模型目录上。
2. **dev 侧没有 sft 格式数据**：`teacher_collect` 按设计只碰 train，dev 从未产生 teacher
   轨迹，因此只有 `train-export-001/sft.jsonl`（240 条）存在。训练要用
   `eval_strategy="epoch"` 就需要新增一个只用 internal_reference（Oracle）跑通 60 条 dev
   并转 `trajectory_to_sft_example` 的导出函数——这是 R3 Task 1 除 CLI 接入外唯一的新增
   产品代码。

**已定方案**：复用现有 `training/sft.py`（516 行完整 QLoRA-SFT 执行器，含 4-bit NF4、
assistant-only loss、smoke 模式、adapter reload、不可覆盖输出）与 R2 Task 6 的
`pipeline` 字段分派 + factory 注入缝模式，不重新发明；超参沿用其现有默认值；验证拆三层
（GPU smoke 测管线 → 小样本 overfit 测 label/mask 正确性 → 全量 SFT），因为 smoke 通过
不能证明数据可学。`max_seq_len=1024` 仅有字符数粗估（p95≈1025 字符）支撑，必须用真实
tokenizer 审计后才能采信。

**待用户确认**：目标模型二选一——方案 A（推荐）直接 SFT Qwen3-4B（SPEC 第 7 节已定为计划
主模型，R2 已验证全链路），方案 B 先用 1.7B 做便宜的全链路验证。R3 正式 holdout 评测、
release、serve 不在本提示词范围内，留待训练结果产出后单独提示词。

### LOG-20260807-05：R3 Task 1 目标模型定为 Qwen3-4B；SFT provenance 锁定改为必填

- 日期：2026-08-07
- 阶段/任务：R3 / Task 1（SFT 训练接入）
- 状态：进行中（本地 CPU 部分完成，外部执行门未开）
- 关联：LOG-20260807-04

**决定 1（用户）**：目标模型选方案 A——直接对 Qwen3-4B 做 QLoRA-SFT，不先用 Qwen3-1.7B 做
一轮便宜的全链路验证。理由沿用提示词：`SPEC.md` 第 7 节已把 4B 定为计划主模型，R2 Task 8 已在
gpu-5090 验证过 4B 的下载/校验/真实 GPU 推理全链路，没有需要用小模型探路的基础设施不确定性。
1.7B 的 dev base 保留为系统卡里的成本/延迟对照基线。

**决定 2（工程）**：`training/sft.py::ModelSettings` 的 `revision`/`file_sha256` 定为**必填**
而非可选。可选字段等于把"要不要校验模型"交给配置作者，原来的洞并未真正关闭。校验点放在
`run_sft` 里确认 model_path 是目录之后、`_ensure_new_training_output` 与 `import torch` 之前，
保证被篡改的模型目录不会在输出目录留下任何产物，同时整条校验路径纯 CPU 可测。

**已知后果（需要记录，不是缺陷）**：4 份 legacy SFT config（`sft.example.yaml`、
`mvp_sft_qwen3_1_7b.yaml`、`bfcl_v4_sft_seed0.yaml`、`bfcl_v4_sft_seed0_smoke.yaml`）现在会在
配置校验阶段 fail-closed。它们只被 legacy `scripts/train_sft.py` 使用，不在 R1-R3 流水线上；
已在各文件头注明恢复使用前需用 `hash_local_model_files` 回填真实值。选择 fail-closed 而不是
填占位哈希：占位值会在更远的地方以更难解释的形式失败。

**决定 3（工程）**：dev 侧 SFT 导出放进新模块 `retail_ops/dev_sft_export.py`，其公开接口
**不接受任何 client 参数**——"dev 任务绝不调用 teacher"这条治理属性由函数签名结构性保证，
比事后断言强。落盘复用 `teacher_data.py` 已审计的路径安全/staging-publish/失败回滚实现，
不新写第五份路径安全代码（Task 7 整分支审查专门点过这类实现漂移风险）。

**决定 4（工程）**：R3 SFT config 的训练数据路径写成私有根内的相对片段
（`train_relpath`/`eval_relpath`）+ 运行时 `--input_dir`，而不是把 `data/private/...` 写进已
提交配置，使 R2 建立的"已提交 config 不含私有根字面量"治理断言可以原样覆盖 R3。

**验证**：557 passed（R2 收口基线 508 + 本任务 49）、Ruff、mypy 55 源文件、
`uv lock --check`、`git diff --check` 全绿。本地真实执行了一次 dev-sft 导出（纯 CPU、Oracle
policy、无模型/无网络/无 API，0.39s）：60 条、六类各 10 条、与 train 240 条无 task_id 交叉，
`sha256sum` 独立重算 `41ae6409438005d2f2c36dcec135c27b44232e24a0b95850c70668cfa6a26024`
与公开摘要 `private_artifact_sha256` 逐字符一致。

**未解决 / 下一步**：`max_seq_len=1024` 仍只有字符数粗估支撑，真实 Qwen3 tokenizer 审计尚未
执行——本地既无 Qwen3 tokenizer 文件也未安装 transformers，因此审计安排在 gpu-5090 上用与训练
完全相同的 transformers 版本执行（比在本地新建 tokenizer-only 环境更可信）。远端同步、token
审计、GPU smoke、overfit 检查、全量 SFT 五个外部执行门均未开，需逐条单独批准。

### LOG-20260807-06：token 长度审计通过；dev eval loss 口径被确认为弱信号

- 日期：2026-08-07
- 阶段/任务：R3 / Task 1（外部执行门 ①，gpu-5090，纯 CPU）
- 状态：解决
- 关联：LOG-20260807-05

**执行**：私有 SFT 数据（`train-export-001/sft.jsonl` 240 条、`dev-sft-001/sft.jsonl` 60 条，
共 679KB）同步到 gpu-5090，本地/远端 SHA-256 逐一核对一致（`09035786...`／`41ae6409...`）。
随后用真实 Qwen3-4B tokenizer 跑 token 长度审计（`CUDA_VISIBLE_DEVICES=` 置空，2.2s，未占 GPU）。

**结果（用 TRL 实际会使用的训练模板测量）**：train 总 token `max=730`/`p95=723`，
dev `max=727`/`p95=723`，**0/300 超过 `max_seq_len=1024`**（余量约 29%），不存在截断风险，
1024 无需调整。assistant 监督 token：train `min=45`/`p50=139`/`max=204`，
dev `min=44`/`p50=47`/`max=133`，**空 mask 行 0 条**；`is_chat_template_stop_token_trained`
为 True（end-of-turn token 在 loss mask 内，模型会学会停）。

**一次被自己推翻的中途判断（记录以免后人重踩）**：直接对模型自带 chat template 调
`return_assistant_tokens_mask=True` 得到全零 mask，一度被判为阻塞。实际读 TRL 1.8 源码确认
`SFTTrainer` 在 `assistant_only_loss=True` 且模板无 `{% generation %}` 时会自动
`get_training_chat_template(processing_class)` 换用带标记的训练模板，并对"任何样本无 assistant
token"硬抛 `RuntimeError`。用裸 tokenizer 模板测量得到的数字不代表训练时的真实口径。

**决定（用户）**：dev-sft 的最终 assistant 回复是 Oracle 常量串（60 条里 40 条最终回复，
去重后只有 `"任务已完成。"` 一种，平均 6 字符），而 train 的 238 条 teacher 回复有 159 种不同
表述、平均 184 字符。两者分布不同，因此 `eval_strategy="epoch"` 的 eval loss **只能当作弱
sanity 信号，其上升不等于过拟合**。用户选择保持现状并写明口径，不为此改动 240/60 配额、
不放宽 `collect_teacher_attempt` 的 "只接受 train split" 硬校验、不额外消耗 teacher API 预算。
理由：eval 数据不参与梯度、`save_strategy="no"` 用最终 epoch adapter，因此失真的 eval loss
不污染训练或 checkpoint 选择；候选质量的权威依据是后续对 60 条 dev 任务的行为式评测
（task_success/政策违规/非法调用），那是独立的下一个提示词范围。

### LOG-20260807-07：GPU smoke 与小样本 overfit 均通过；训练路径不复现 Triton JIT 问题

- 日期：2026-08-07
- 阶段/任务：R3 / Task 1（外部执行门 ②③，gpu-5090 物理 GPU 0）
- 状态：解决
- 关联：LOG-20260807-06

**环境**：gpu-5090，物理 GPU 0（RTX 5090，`GPU-07af326b-f41d-a706-2150-bc560c7db304`），
执行前他人占用 6034 MiB；`CUDA_VISIBLE_DEVICES=0 TORCH_DISABLE_NATIVE_JIT=1`；
代码 `ec9cad5`；transformers 5.13.1 / trl 1.8.0 / torch 2.13.0+cu130。

**提示词留的未知项已解答**：R2 Task 8 只验证过 `TORCH_DISABLE_NATIVE_JIT=1` 能绕开**推理**
路径的 Triton JIT 编译器缺失问题，训练算子路径是否同样适用未知。两次训练运行**均未复现**该
问题，该环境变量对训练路径同样有效，不需要任何编译器或新依赖。

**smoke（`retail_ops_v1_r3_sft_smoke.yaml`，8 条 / 2 step，17.8s 进程 / 7.9s wall）**：
`train_loss=1.4479`、`eval_loss=2.3065`（均有限）；峰值 `cuda_peak_allocated=5,506,825,216`
字节（≈5.13 GiB）；adapter 23.6 MB，`reload_adapter_offline` 返回 `loaded: true`（0.99s）；
`loss_mask_source=trl_chat_template_assistant_mask`，确认走 TRL assistant mask 而非全序列监督。

**overfit（`retail_ops_v1_r3_sft_overfit.yaml`，16 条 / 60 step / 15 epoch，54.6s 进程 /
49.0s wall）**：train loss `1.2729 → 0.0168`（**76 倍降幅，单调下降**），
`mean_token_accuracy 0.8605 → 0.9965`。**结论：label/assistant mask 无系统性缺陷，这批数据
可学。** 峰值 `cuda_peak_allocated=5,511,306,752` 字节（≈5.13 GiB，与 smoke 同量级）。

**eval_loss 形状（记录以便日后解读全量运行）**：`2.240 → 0.800`（epoch 3 最低）`→ 1.469`
并平台化。先降说明 dev 侧的**工具调用部分**确实与 train 共享可学结构、不是纯噪声；后升是
16 条样本上的正常过拟合，叠加 LOG-20260807-06 记录的最终回复口径差异（Oracle 常量串 vs
teacher 详尽表述）。因此全量运行若出现 eval_loss 上升，**不应据此判定过拟合或 NO-GO**。

**产物**（均在 ignored 路径，目录不可覆盖）：
`reports/retail_ops/v1/r3/sft-smoke-001/`、`reports/retail_ops/v1/r3/sft-overfit-001/`，
各含 `config.yaml`/`adapter/`/`checkpoints/`/`metrics.json`/`trainer_log_history.json`/`log.txt`。
两者均为诊断运行，不是正式候选 adapter。

### LOG-20260807-08：R3 Task 1 完成——Qwen3-4B 首次真实全量 QLoRA-SFT

- 日期：2026-08-07
- 阶段/任务：R3 / Task 1（外部执行门 ④⑤，gpu-5090 物理 GPU 0）
- 状态：解决
- 关联：LOG-20260807-07

**运行**：`configs/retail_ops_v1_r3_sft.yaml`，seed=0，输出
`reports/retail_ops/v1/r3/sft-001/`。240 条 train + 60 条 dev，3 epoch，45 个 optimizer step，
有效 batch 16（2×8），lr 2e-4，`max_seq_len=1024`，4-bit NF4，assistant-only loss，
LoRA r=16/alpha=32/dropout=0.05/[q,k,v,o]_proj。超参全部沿用 `training/sft.py` 既有默认值，
未做任何调整。

**结果**：`train_loss=0.3722`（逐步曲线 `1.1916 → 0.2074`，`mean_token_accuracy 0.8782 →
0.938~0.956`）；`eval_loss` 逐 epoch `0.5266 / 0.5603 / 0.5797`，
`eval_mean_token_accuracy 0.9321 / 0.9472 / 0.9436`。全部 loss 有限（`_require_finite_losses`
通过）。wall time 134.25s（进程 2m20.8s）；峰值 `cuda_peak_allocated=5,543,735,296` 字节
（≈5.16 GiB，与 smoke/overfit 的 5.13 GiB 同量级）；`total_flos=1.0808e16`。
adapter `adapter_model.safetensors` 23,631,816 字节（目录 34 MB），
`reload_adapter_offline` 返回 `loaded: true`（1.00s）。

**eval_loss 逐 epoch 轻微上升（0.527→0.580，+10%）而 eval token accuracy 反而上升后持平
（0.932→0.947→0.944）**，与 LOG-20260807-06/07 已记录的口径差异一致：dev-sft 的最终回复是
Oracle 常量串，train 是 teacher 详尽表述。**这不构成过拟合判据，也不是 NO-GO 依据**；候选
质量的权威信号是后续对 60 条 dev 任务的行为式评测（task_success/政策违规/非法调用），属于
下一个提示词范围。

**provenance 闭合**：运行写出的 `config.yaml` 内嵌 `model.revision=8cd0101f70cac...` 与 13 项
逐文件 SHA-256，经核对**与 `configs/retail_ops_v1_r2_qwen3_4b_dev.yaml` 完全一致**——base 与
candidate 跑在同一份已哈希校验的模型文件上，后续配对评测可比。训练开始前
`verify_local_model_files` 已逐文件校验通过（否则不会有任何产物落盘）。

**产物同步（门 ⑤）**：11 个文件 rsync 回本地 `reports/retail_ops/v1/r3/sft-001/`，
本地/远端 SHA-256 **逐一完全一致**，关键项：
`adapter_model.safetensors=34544fac3ec9afae10f9212f730aaf275bc86b536ffaeecfb4fe0eeb745e8748`、
`metrics.json=22621291593a19d0ecc01e65e4b08565ab75556c778d514f5466da420efb8b30`、
`config.yaml=d103d3002254628c079d3fb8d483e1e2c7225f55f0bc82149d06f98422e2ee94`。
全部路径经 `git check-ignore` 确认被忽略，`git status` 干净，无权重进 Git。

**边界**：本任务到此为止。未打开或评测正式 120 条 holdout、未调用
`evaluate_authorized_holdout`/`sealed_evaluation.py`、未做 release GO/NO-GO 决策、未部署 serve、
未触碰 BFCL 固定 200 条。这些留给下一个提示词。

### LOG-20260807-09：R3 Task 2 候选 dev 评测——格式/安全全面清零，但退款执行类场景显著回退

- 日期：2026-08-07
- 阶段/任务：R3 / Task 2（dev 候选评测，gpu-5090 物理 GPU 0）
- 状态：解决（结论：该候选不适合直接替换 base；失败机制已定位）
- 关联：LOG-20260807-08

**运行**：`configs/retail_ops_v1_r3_qwen3_4b_candidate.yaml`，seed=0，与
`qwen3-4b-dev-base-001` 同 bundle/manifest/parser/预算/生成参数、同一份已哈希校验的基座模型
（revision `8cd0101f...`，13 项逐文件哈希逐字段相同），仅多挂 R3 adapter。`compare_dev_runs`
的 15 项配对契约字段 + model + generation + task_count 全部通过校验，delta 可归因于 adapter。
wall time 250.7s，峰值显存 2,952,253,440 字节（base 2,941,568,000，基本持平）。

**格式与安全：大幅且统计上确凿的改善**

| 指标 | base | candidate | 精确 McNemar |
|---|---|---|---|
| invalid_call_count | 21 | **0** | p < 0.0001 |
| policy_violation_count | 8 | **0** | p = 0.0078 |
| schema_valid_rate | 0.781 | **1.000** | — |
| format_error_rate | 0.153 | **0.000** | — |

**任务成功率：回退，但整体不显著**

`task_success` 0.800 → 0.7167（48/60 → 43/60）。配对 2×2：base✓cand✓ 41、
base✗cand✓ 2、base✓cand✗ 7、base✗cand✗ 10，精确 McNemar **p = 0.1797——在 n=60 上不显著**，
单看这一项不能断言回退。

**但按场景拆开后模式是确凿的，且有明确机制**

| 场景（所需工具调用数） | base | candidate |
|---|---|---|
| lookup_status（1） | 10/10 | **10/10** |
| refund_denied_duplicate（1） | 9/10 | **10/10** |
| refund_denied_ownership（1） | 9/10 | **10/10** |
| refund_denied_window（1） | 10/10 | **10/10** |
| refund_eligible（2） | 5/10 | **0/10** |
| refund_recovery（3） | 5/10 | **3/10** |

只需 1 次工具调用的四类做到 40/40 全对；需要 ≥2 次调用的两类全面回退。7 个新失败任务
**全部**是 `termination=final_response`、`violations=[]`——模型没有违规、没有非法调用，
它只是**说完就停，没有执行必要的状态变更**。终止原因分布：base
`{success:48, policy_violation:8, final_response:3, step_limit:1}` →
candidate `{success:43, final_response:17}`。

**根因（有数据支撑，非推测）**：训练数据的动作长度严重不平衡——240 条里 **160 条
（66.7%）只有 1 次工具调用**，`refund_eligible` 40 条为 2 次、`refund_recovery` 40 条为 3 次。
模型学到了占主导的"调一次 → 写总结"模式，并把它过度泛化到需要多步执行的场景。旁证：
`average_tool_calls` 1.25→1.10、`average_turns` 2.28→2.05（更"果断"），
`average_output_tokens` 112→149（学到 teacher 的详尽表述风格，也解释了
`average_latency_ms` 2562→4176 的上升）。`refund_eligible` 单场景 0 vs 5 的精确
McNemar p=0.0625，配合"回退与所需调用数完全对应"这一结构性证据，不能当作噪声。

**verifier_reward 反而上升（0.579 → 0.717）**：复合奖励里格式/政策分量占权重，任务成功率
下降被格式满分掩盖。这正是 SPEC 与 CLAUDE.md 坚持"主判据是最终状态与政策 verifier、
不是奖励值"的原因，本次是一个具体例证，记录备用。

**结论与边界**：按 dev 证据，该候选**不适合直接替换 base**——它把一类失败（格式/违规）
换成了另一类（漏执行）。本条不构成 SPEC 发布门禁的 GO/NO-GO 判定（那需要走 release 流程，
属于独立范围）。未打开正式 120 条 holdout、未做 release 决策、未部署 serve。失败类别
明确、可复现、有机制，符合 R4「失败驱动优化」的输入条件；具体改进方案需用户确认后再启动。

### LOG-20260809-01：仓库收敛——Git 单分支化、切断原工作区依赖、按四接口重排目录

- 日期：2026-08-09
- 阶段/任务：R3 阶段间的仓库收敛任务（不推进 R3 剩余目标）
- 状态：解决
- 关联：LOG-20260807-09

**用户决策（三选一逐项确认）**：外部依赖只本地化被引用的 gorilla；Python 导入名保留
`veritool_rl` 不改；目录采用**激进重构**（按四个稳定接口重排 src 与 configs，legacy 下沉）。
执行中用户追加两条要求：确保本项目后续是独立项目、做好废弃文件归档与清理。

**Git 收敛**：`feature/r2-formal-data-and-base-eval` 重命名为 `main`；
`portfolio/retail-agent-ops-init`（a3c748b）经 `git merge-base --is-ancestor` 确认是
`main` 的祖先后删除。101 个提交与 HEAD（acdc0f0）均未变。

**独立性（本条是本次的核心结论）**：原 `data/external_repos` 是指向
`../../veritool-rl/data/external_repos` 的 ignored 软链接，这是本项目对原工作区的**最后
一处依赖**。实测只有 gorilla 被引用（4 个 bfcl config + `tests/test_bfcl_official.py`），
tau2-bench(847M)/appworld(14M)/ToolSandbox(1.9M) 在本仓库零引用。因此只复制 gorilla。

**一个被实测推翻的决策细节**：原计划剥离 gorilla 的 `.git` 以求"不依赖任何外部 git"。
剥离后 `scripts/legacy/bfcl/run_bfcl_official_ast.py::_verify_checkout` 的两项校验
（`rev-parse HEAD` 与 `status --porcelain` 为空）全部失效，2 个测试立即失败。该 `.git`
并非对任何**本地仓库**的依赖，而是自包含快照的 provenance 凭证；自建等价校验需要新代码、
新测试和每次运行的全树哈希开销。结论：保留（+42 MB），并在 `BFCL_PIN.txt` 写明理由。
教训记录：**"切断依赖"的目标是消除对原工作区的耦合，不是机械删除一切 `.git`**。

审计结论：唯一 `main`、0 remote、无 submodule、无 linked worktree、无
`.git/objects/info/alternates`、无跟踪软链接、无跨仓库文件系统链接、虚拟环境只指向本目录。
**删除原 `veritool-rl` 工作区不影响本项目任何命令。**

**身份独立**：分发名 `veritool-rl` → `retail-agent-ops`（`pyproject.toml`），description
从旧研究表述改为当前产品定位。导入名 `veritool_rl` 按用户决策保留——已提交的 `reports/`
产物与 manifest 记录了产出它们的代码标识，改名会切断"代码 commit ↔ 运行产物"的可追溯链，
而可追溯性正是本项目的核心主张。`uv.lock` 仅自身包条目变化。

**目录重排**：`src/veritool_rl` 分为 core（跨领域基础设施）/ retail_ops
（domain·build·evaluate·release·serve）/ training / legacy；configs 按四接口分层；
scripts、reports、docs 分离活动与 legacy/archive。全程只做 `git mv` + import 重写，
**函数体零改动**；86 个文件的 import 经单次正则扫描重写（按长度降序的 alternation，
避免 `retail_ops.release` → `release.release` 这类级联误替换），残留检查 0 命中。

**行为不变的证明**（不是"测试通过"这种弱证明）：三份真实运行证据重新加载后
`run_id` 自哈希复算全部一致——R2 base qwen3-1.7b `07671235…`、R2 base qwen3-4b
`d57654e9…`、R3 candidate `29648b8c…`（后者还通过了逐产物 SHA-256 校验）。这直接证明
`_content_id` 覆盖的全部字段与产物内容在重构前后逐字节相同。

**新增结构治理**：两项测试把 REPO_MAP 的架构主张变成可验证不变量——
(1) 分层单向依赖：core 不依赖 retail_ops/legacy/training，retail_ops 与 training 不依赖
legacy，product_cli 不依赖 legacy；(2) 四个稳定接口在模块目录与 configs 目录各有归属
且配置非空。测试基线 585 → 587。

**清理**：删除 18 个 `__pycache__`、空 `.codex/`、41 MB 工具缓存（可重建）。
`.superpowers/` 与 `.codex/` 的忽略规则从**本地私有**的 `.git/info/exclude` 迁入
随仓库分发的 `.gitignore`——前者不随克隆分发，属于可移植性缺陷。仓库体积
（不含 .git/.venv/data/tools）83M → 40M。`.superpowers/` 的 37 个 review diff 保留在本地。

**历史记录处理**：`docs/PROJECT_LOG.md`、`findings.md`、`progress.md` 旧条目与
`reports/legacy/**` 内已提交产物中的旧路径**一律未改写**（append-only 原则），
改由 `docs/REPO_MAP.md` 第 6 节的路径对照表回溯。

**验收**：587 passed、Ruff、mypy 64 源文件、`uv lock --check`、`git diff --check` 全绿。

**边界**：未推进 R3 剩余目标（正式 120 条 holdout、release GO/NO-GO、serve 部署），
未运行任何 GPU 或商业 API，未创建远程仓库，未 push。

### LOG-20260810-01：R3 Task 3 立项——发布闭环的代码侧缺口、schema 不可逆窗口与三项用户决策

- 日期：2026-08-10
- 阶段/任务：R3 / Task 3 立项（只读审查 + 计划，未实现任何代码）
- 状态：解决（计划已冻结，实现待用户放行）
- 关联：LOG-20260807-09、LOG-20260809-01

**触发**：对当前状态做文档与代码的交叉核实，确定最值得做的下一步。实测基线
587 passed / Ruff / mypy(64 源文件) / `git diff --check` 全绿，工作树干净，HEAD `74f526f`。

**核心发现：仓库存在两条平行证据链，真实模型轨道断在 `evaluate`**。R1 qualification
轨道（规则策略）四个接口全通；R2/R3 formal 轨道（真实 Qwen3-4B）只到 dev 评测。三处
是**代码不存在**而非未获执行授权：
(1) `evaluate_authorized_holdout` / `authorize_formal_holdout` 全仓只被 `tests/` 引用，
`product_cli.py::_run_evaluate` 只识别 `formal_dev_base` / `formal_dev_candidate`，
正式 120 条 holdout 无任何命令可跑；
(2) `release.py::decide_release` 只接受 R1 的 `RunEvidence`，`_validate_paired_evidence`
比对的 `mode` / `task_manifest_sha256` / `budget` 是 formal 证据没有的字段——**SPEC §6
的发布门禁对真实模型不可执行**；
(3) `serve/service.py:45` 硬要求 `manifest.split == "qualification"` 并只构造
`build_qualification_policy` 规则策略，从不加载模型或 adapter。

结论：PRODUCT_BRIEF 主打的差异化「输出是决策而非指标」目前只在玩具规则策略上成立。

**约束变化（不可逆窗口，本条是本次最重要的记录）**：`SealedEvaluationReport`
（`sealed_evaluation.py:64`）缺 `model` / `generation` / `hardware` / `config_sha256` /
`code_commit` / `uv_lock_sha256` / adapter —— 恰是 `compare_dev_runs` 用来证明 base 与
candidate 同条件的那组字段，两份 sealed 报告放在一起无法在字段级证明可比。而
`report_id` 是 `_content_id` 对全字段的自哈希，加字段会让已产出报告永久加载失败，
`BaseRunEvidence` 已因此被冻死（`findings.md:532`）。已核实
`data/private/.../sealed-eval/` 不存在、`reports/` 无任何 sealed 产物，**holdout 从未
跑过**，所以现在扩字段零成本，**第一次 holdout 运行落盘的瞬间窗口关闭**。因此
「补 schema」被定为 Task 3 的 A1，且必须先于任何 holdout 运行。

**设计决定**：formal 发布门禁**只新增并行类型**（`FormalReleaseReport`），不改
`ReleaseReport`。理由是 `ReleaseReport.validate_decision_consistency`（`release.py:71-82`）
断言 gate 集合与顺序精确等于 `_GATE_IDS`，且 `decide_release` 的返回类型被
`service.py` 与 `tests/test_release_policy.py` / `test_service.py` 依赖。沿用 Task 2 用
子类扩展 `CandidateRunEvidence` 的既有做法。**被否决的替代方案**：放宽
`_validate_paired_evidence` 让 formal 证据穿过现有 `decide_release`——会使 R1 的配对
公平性检查失效；以及复制一套 formal 门禁算术——会让同一份 `release.yaml` 产生两种语义。
两者均写入计划的失败模式。

**已识别的安全陷阱**：serve 的可切换后端注入缝容易写成「CPU 假后端也能标 GO 并部署」，
违反 SPEC §4「没有通过发布门禁的模型不得被服务入口默认加载」。C1 的 RED 先钉死这条。

**用户决策（三项）**：
1. Task 3 范围 = A+B+C 一次做完（holdout CLI 入口与 schema 补全 + formal release 门禁 +
   真实模型 serve），纯 CPU、TDD；
2. holdout 时机 = 代码就绪后**先只跑 base**。理由：base 是固定参照、不涉及候选选择，
   跑它不产生选择性泄漏，且未来每次发布决策都要用；候选侧的第一枪留到 R4 出更好候选
   再打，不花在已知会 FAIL 的当前候选上；
3. serve 形态 = 后端经工厂注入、默认本地 CPU 可启动，GPU 主机上换真实
   Qwen3-4B+adapter；测试不依赖 GPU。

**当前候选按 `domains/retail_ops/v1/release.yaml` 的预判**（dev 数字，非 holdout）：
success_delta −0.083（阈值 +0.05）**FAIL**；policy_violation_delta −8 PASS；
invalid_call_count 0 PASS；p95 ratio 5211/6068 = 0.859 PASS；evidence_complete PASS。
5 项里 4 项通过，唯一失败的是唯一重要的那项。注意 p95 反而下降——base 的尾延迟被它
自己的违规/重试拉高。这组数字将作为 B3 的端到端 NO-GO 回归输入。

**顺带修正的文档漂移**：`CLAUDE.md:92` 与 `docs/REPO_MAP.md:25` 仍写 585，实际 587
（收敛任务新增 2 项治理测试），已改。`REPO_MAP.md:84` 的 585 描述的是「重构行为不变的
证明用的是重构前那 585 项」，语境正确，未动。

**边界**：本次只做只读审查与计划，未实现任何代码，未运行 GPU/商业 API/holdout，
未提交。实现从 A1 开始，待用户放行。

### LOG-20260810-02：sealed 报告 schema 窗口已关闭；holdout 评测入口落地

- 日期：2026-08-10
- 阶段/任务：R3 / Task 3 A（纯 CPU 实现，未运行 holdout）
- 状态：解决
- 关联：LOG-20260810-01

**不可逆约束变化（本条的核心）**：`SealedEvaluationReport` 已补入
`model`/`adapter`/`generation`/`hardware`/`config_sha256`/`code_commit`/`uv_lock_sha256`，
并去掉与 `generation` 重复的 `max_new_tokens`。补字段之所以可行，是因为实测确认
`data/private/.../sealed-eval/` 不存在、`reports/` 无任何 sealed 产物——**holdout 从未跑过**。
`_content_id` 只排除 `report_id` 与 `schema_version`，新字段自动进入自哈希（已用篡改
`model.revision` 后 `report_id` 失配的测试钉住）。**自本条起，sealed schema 的修改窗口
关闭：再改会作废届时已产出的 holdout 证据，与 `BaseRunEvidence` 当前的处境相同。**

**设计决定一：sealed 报告用单一类型 + 可选 adapter，不复制 dev 侧的双类型模式。**
dev 侧是 `BaseRunEvidence` / `CandidateRunEvidence` 两个类型，靠类型不兼容互相排斥。
sealed 报告是**对外的单一 allowlist 产物**，若分裂成两个 schema_version，公开产物形态会
随 base/candidate 变化。改为由 `require_comparable_sealed_runs` 显式断言角色（base 必须
无 adapter、candidate 必须有）。代价是少一层类型级保护，因此这两条断言各有测试。

**设计决定二：CLI 侧反过来拆成两条流水线** `formal_holdout_base` /
`formal_holdout_candidate`。`_require_config_keys` 是精确 key 集合；若合成一条，adapter
只能是可选 key，**"漏写 adapter" 会静默降级成一次 base 运行并被标为候选证据**。拆开后
配置文件本身声明意图，且 base 配置里出现 adapter 会被 key 契约挡住。两个方向相反的选择
各有其理由，记录在此以免后续被"统一风格"重构掉。

**过程失误与其纠正**：`_require_backend_matches_pin` 的接线是在 GREEN 阶段顺手写的，
没有先失败的测试。事后把该调用注释掉重跑，两条 adapter 双向绑定测试立即
`DID NOT RAISE`，随后恢复转绿。结论：对"顺手补上的守卫"，突变验证比补一条事后测试
更能给出真实失败证据；后续 B/C 段沿用。

**新增的可机器检查主张**：三条测试断言 R2 dev base、R3 dev candidate 与两条 holdout
通道的 `model` 段逐字段相同，且 holdout candidate 与 dev candidate 的 `adapter` 段相同。
"delta 可归因于 adapter" 在配置层的前提不再只写在注释里。

**授权边界未放宽**：CLI 接线中 purpose 固定 `EvidencePurpose.RELEASE`，logical_path 由
代码拼成 `data/private/retail_ops/v1/r2/<dataset_version>/holdout.jsonl`，不从配置读取。

**验收**：604 passed（587 → 604）、Ruff、mypy 64 源文件、`git diff --check` 全绿。
未运行任何 GPU/商业 API/holdout，未提交，未进入 B（formal release 门禁）与 C（真实模型 serve）。

### LOG-20260810-03：R3 Task 3 完成——formal 轨道的 evaluate→release→serve 代码闭环

- 日期：2026-08-10
- 阶段/任务：R3 / Task 3（B 段发布门禁、C 段真实模型服务，纯 CPU）
- 状态：解决（代码闭环完成；**尚未执行任何 holdout 运行**）
- 关联：LOG-20260810-01、LOG-20260810-02

**阶段性事实变化**：LOG-20260810-01 记录的三处缺口已全部补齐。formal（真实 Qwen3-4B）
轨道现在四个接口齐备：`evaluate` 有封存 holdout 的 base/candidate 两条流水线，
`release` 有 `decide_formal_release`，`serve` 有 `create_formal_app`。R1 qualification
轨道的已冻结契约逐字未改（`ReleaseReport`、`create_app` 及其 22 项相关测试全通过）。

**设计决定：门禁算术抽成 `build_release_gates`，R1 与 formal 共用。** 被否决的替代方案是
让 formal 侧自带一套阈值实现——那样同一份 `domains/retail_ops/v1/release.yaml` 会有两种
语义，同一个候选可能在两条通道上得到互相矛盾的结论。`GATE_IDS` 一并提升为公开常量，
使门禁集合与顺序在两侧都可断言。

**设计决定：serve 的回滚是双重执行的。** 只根据 `deployment` 决定传不传 adapter 给后端
工厂并不够——工厂是注入缝，实现可能来自别处。因此 `create_formal_app` 还会核对工厂真正
返回的后端所声明的 `adapter_path`。这是 SPEC §4"没有通过发布门禁的模型不得被服务入口
加载"从文档承诺变成代码事实的地方。

**设计决定：并发上限固定为 1，超限返回 503 而不是排队。** 单卡并发解码会让显存峰值不可
预测，排队则会让逐 episode 的延迟测量失真——而延迟是发布门禁的一项。

**方法沿用**：LOG-20260810-02 记录的突变验证在本段用于三处安全关键行
（`require_comparable_sealed_runs`、`_require_backend_matches_deployment`、
`_MAX_CONCURRENT_EPISODES`）。三处去掉后对应测试均立即失败，随后恢复。

**用真实 dev 数字固化的 NO-GO 回归**：以 base 0.800 / candidate 0.7167 /
p95 6068 vs 5211 为输入，断言五项门禁里恰好 `success_delta` 失败、`deployment` 为
`baseline`。这条测试把 LOG-20260807-09 的结论变成了可执行回归。**它是预期而非结论**：
真正的发布判定必须来自封存 holdout 上的 sealed 证据。

**边界（重要，勿被"闭环完成"误读）**：正式 120 条 holdout **至今从未执行**。因此不存在
任何 sealed 证据、任何 formal GO/NO-GO 结论、任何真实模型服务部署。R3 的验收目标里
"候选满足发布门禁才标 GO""服务能完成允许/拒绝/异常恢复流程"仍未达成——它们需要 GPU
运行，属下一个授权门。已按用户 2026-08-10 的决定，把"先只跑 base 侧 holdout"记为下一步。

**验收**：624 passed（587 → 624）、Ruff、mypy 65 源文件、`uv lock --check`、
`git diff --check` 全绿；三份真实证据 `run_id` 复算与 LOG-20260809-01 记录一致
（`07671235…`/`d57654e9…`/`29648b8c…`），R1 两份 qualification release 报告仍可加载。
未运行 GPU/商业 API/holdout，未提交，未创建远程仓库。

### LOG-20260811-01：封存 holdout 首次执行——base 与 candidate 背靠背，理由与不可逆边界

- 日期：2026-08-11
- 阶段/任务：R3 / Task 3 收口（从「代码完成」进入「实际执行」）
- 状态：进行中（本条记录决定与前置事实，运行结果另条追加）
- 关联：LOG-20260810-01、LOG-20260810-02、LOG-20260810-03、LOG-20260807-09

**不可逆事实**：正式 120 条封存 holdout 自 R2 冻结以来从未执行；本次是**第一次**。
一旦运行并读到聚合数字，该集合对本项目的完全盲性即结束。此后它仍是硬隔离边界
（结果不得反馈进开发、调参、prompt/parser 或 checkpoint 选择），但"从未被观测"
这一属性无法恢复。

**决定变更：从「先只跑 base」改为「base + candidate 背靠背连续跑」。** LOG-20260810-03
记录的原决定是本轮只跑 base（base 是固定参照，不涉及候选选择，不产生选择性泄漏）。
本次执行前的只读盘点提供了原决定作出时不掌握的两项事实，用户据此改变决定：

1. **延迟门禁的可比性是有时效的**。gpu-5090 为多人共用，运行前 GPU 0 已被他人 3 个进程
   占用 14892/32607 MiB、利用率 100%。发布门禁第五项是 `candidate p95 ≤ 1.25 × base p95`；
   若两份 sealed 证据跑在不同时段的不同负载下，该比值度量的是机器负载差异而非模型差异。
   背靠背连续执行是唯一能让这一项保持可解释的安排。
2. **只跑 base 拿不到任何发布结论**。R3 验收目标「候选满足门禁才标 GO，否则诚实标 NO-GO」
   与「服务完成允许/拒绝/异常恢复流程」都需要 candidate 侧 sealed 证据；只有 base 时
   `decide_formal_release` 无输入，R3 无法收口。

被接受的代价：在 dev 上已知回退的候选（LOG-20260807-09：task_success 48/60→43/60）上
用掉一次 holdout 观测。**这不是缺陷而是 holdout 的用途**——发布门禁需要一次诚实的判定，
包括诚实的 NO-GO。R4 改进后的候选若要再次判定，需另行决定是否再用一次。

**前置条件与其解除**（四项，均为执行前实测发现，非文档转述）：

1. **脏工作树会硬阻塞 sealed 运行**。`_current_code_commit`（`product_cli.py:1189`）以
   `git status --porcelain` 非空即拒绝。因此 Task 3 的全部改动先提交为 `90c9038`
   （12 modified + 7 新增，含 4 份新 config、`formal_release.py` 与两份新测试）。
2. **远端落后两个提交**：gpu-5090 停在 `0c6f552`，缺 `c466b64`（仓库收敛：目录分层 +
   分发名 `veritool-rl` → `retail-agent-ops`）。经增量 bundle ff-only 同步到 `90c9038`
   后**必须重建环境**——`uv sync` 实测卸载 `veritool-rl==0.0.1` 并装入
   `retail-agent-ops==0.0.1`，仅靠 git 同步会留下指向旧分发名的 editable 安装。
3. **封存 holdout 私有数据首次离开本机**。远端此前只有 `dev.jsonl` 与派生产物，无
   `holdout.jsonl`。已同步至同一相对路径，双端 SHA-256 逐字节一致
   （`c5ef5063baf411767405d6d7b2befde078cbf3c4c87f3216a71797d4f24ac215`，334582 字节），
   并实测仍被远端 `.gitignore:51:/data/` 覆盖。**这意味着封存 holdout 内容现存于一台
   多人共用服务器上**，属于新增的数据暴露面，记录在此以便 R5 公开交付前复核。
4. 远端缺 R1 qualification build 产物，而 `serve` 的 `--input_dir` 需要它（演示任务集，
   非 holdout）。补跑安排在评测结束之后，避免评测期间给同机增加 CPU 负载而扰动延迟测量。

**执行安排**：物理 GPU 0（RTX 5090），工作目录 `/mnt/aidata/tongjiakai/retail-agent-ops`，
`TORCH_DISABLE_NATIVE_JIT=1`（沿用 R2/R3 已验证的 Triton JIT 规避），seed 0（由冻结
receipt 决定，非 0 会被 CLI 拒绝），两条流水线串行。产物：私有
`<input_dir>/sealed-eval/qwen3-4b-holdout-{base,candidate}-001/`（完整轨迹与逐任务证据）；
公开 `reports/retail_ops/v1/r3/holdout-{base,candidate}-001/sealed-report.json`
（allowlist 聚合，无 task/family 标识、prompt、真值或失败样例）。运行前后各记 GPU 快照。

**尚未发生**：任何 sealed 结果、任何 formal GO/NO-GO 结论、任何真实模型服务部署。
本条只记录决定与前置事实；运行结果与发布判定另条追加。

### LOG-20260811-02：首次 holdout 运行被 gpu-5090 重启中断——零产出，盲性未消耗；新增系统盘约束

- 日期：2026-08-11
- 阶段/任务：R3 / Task 3 收口（封存 holdout 执行）
- 状态：已恢复（已按同一授权范围重启运行，结果另条追加）
- 关联：LOG-20260811-01

**事件**：LOG-20260811-01 记录的运行于 11:13:45 启动，gpu-5090 在 **12:10 整机重启**，
运行被杀。重启同时导致 cpolar 隧道换端口
（`1.tcp.cpolar.cn:23617` → `29.tcp.cpolar.top:10537`，用 `~/.local/bin/cpolar-ssh-update`
恢复）与 `/tmp/holdout-run.log` 被清空，因此故障期间一度无法判断评测是否存活。

**核心判定：holdout 的盲性未被消耗。** 逐项核实：公开输出目录
`reports/retail_ops/v1/r3/holdout-base-001/` 存在但**完全为空**（只有 `.` 与 `..`，
由 `create_output_dir` 在 11:16 创建后即中断）；私有 `sealed-eval/` 目录**不存在**；
没有任何 `sealed-report.json`。**没有一个数字被产出，因此没有一个数字被观测**——
LOG-20260811-01 所述"从未被观测"这一属性在本次中断后仍然成立，重跑是干净的，
不构成一次已用掉的 holdout 观测。这个判定是本条最重要的内容：若误判为"已消耗"，
会平白损失该集合的一次盲性；若误判为"部分产出可用"，则会把半截运行当证据。

**清理方式**：残留空目录用 `rmdir` 删除而非 `rm -rf`——`rmdir` 对非空目录会失败，
这一性质本身就是"绝不误删已产出证据"的保证。删除前另已确认输入未受重启影响：
`holdout.jsonl` SHA-256 仍为 `c5ef5063…`（334582 字节）、adapter 7 个文件、
模型 13 个文件均在。仓库 HEAD 仍为 `90c9038`，工作树干净。

**运行环境的变化及其影响**：重启后 GPU 0 由 14892 MiB/100% 利用率变为
7196 MiB/0%（他人仅 1 个进程）。这不损害 LOG-20260811-01 的可比性论证——该论证要求的是
**base 与 candidate 之间**负载一致，而两条运行仍是同一脚本内背靠背串行；两次运行整体
处在比首次尝试更空闲的环境，只影响绝对延迟量级，不影响门禁使用的比值。绝对量级会如实
写入 sealed 报告的硬件 provenance。

**新增资源约束（用户指令）**：远端数据不得写入系统盘。核实结果：真实产物本就全部落在
`/mnt/aidata`（1.8T 可用）——私有 sealed 证据、公开报告、模型与 adapter 均在仓库内，
而仓库位于该盘；写到系统盘（`/` 321G 可用）的只有本次为防重启丢失而放置的
`holdout-run.log`（125 B）与 `run_holdout.sh`（1051 B），合计约 1.2 KB。约定：运行结束后
把日志移入 `reports/retail_ops/v1/r3/`（已被 `.gitignore` 的 `/reports/retail_ops/` 覆盖，
既在数据盘又不会让远端工作树变脏而阻塞 `_current_code_commit`）。**此后远端一切新增文件
默认落 `/mnt/aidata`。**

**留给后续的运行纪律**：远端 `/tmp` 不可用于承载跨故障的运行日志（重启即清空）。
本次重启运行已改用重启安全位置，且轮询改为**短连接重试**模式——长驻 ssh 会随隧道抖动
整体失败，而评测进程本身由 `setsid` 脱离会话、不受 ssh 断开影响，监控不应比被监控者更脆弱。

**重启后的运行**：12:25:38 启动，命令、配置、seed、产物路径与 LOG-20260811-01 完全相同，
属同一授权范围内的重试，非新决定。

### LOG-20260811-03：封存 holdout 执行完成与首个 formal 发布决策——NO-GO，回滚 baseline

- 日期：2026-08-11
- 阶段/任务：R3 / Task 3 收口（sealed holdout 运行 + `decide_formal_release`）
- 状态：解决（发布判定已产出；`serve` 演示尚未执行）
- 关联：LOG-20260811-01、LOG-20260811-02、LOG-20260807-09、LOG-20260810-03

**运行事实**（gpu-5090 物理 GPU 0，RTX 5090，GPU UUID `GPU-07af326b-…`）：
base 12:25:38→12:45:47（步骤 20m9s，评测本体 `wall_time_seconds=286.98`）；
candidate 12:45:47→12:55:07（步骤 9m19s，评测本体 `544.21`）。两条背靠背，
`code_commit` 与 `uv_lock_sha256` 逐字段相同，peak memory 2.95 GB / 2.95 GB。

**一处自我推测的纠正**：中途见到 base 步骤耗时是 candidate 的两倍，曾推测为他人负载抢占
GPU。sealed 报告的 `wall_time_seconds` 推翻了这个推测——**评测本体 base 287s、candidate
544s，candidate 确实更慢**（与 dev 上 4176 vs 2562 ms 的方向一致）。base 步骤那 20 分钟里
约 15 分钟是冷启动：首次读入 7.6 GB 权重并对 13 个文件逐一 SHA-256 校验；candidate 时页缓存
已热。教训：步骤 wall time 不是评测延迟，provenance 里的 `wall_time_seconds` 才是。

**证据核验（独立重算，非文本比对）**：两份报告 `report_id` 自哈希通过
（base `b538a6c4…`、candidate `a8cfcf38…`）；4 个私有产物 SHA-256 各自重算一致；
回传的公开副本与远端私有原件逐字段相等。holdout artifact SHA-256 两侧同为 `c5ef5063…`。

**发布判定：NO-GO / deployment=baseline，唯一失败门禁 `success_delta`。**
观测 −0.0333（base 0.7833=94/120 → candidate 0.7500=90/120），阈值 +0.05。
其余四项均通过：`policy_violation_delta` −16、`invalid_call_count` 0、
`p95_latency_ratio` 1.0870（≤1.25）、`evidence_complete` true。

**holdout 证实了 dev 的结论，并且更极端**。格式与安全类在封存集上同样彻底清零：
invalid_call 41→0、policy_violation 16→0、schema_valid_rate 0.7819→1.0000，
base 的 16 次违规全部是 `refund_without_lookup`（未查询即退款），候选一次都没有。
代价仍集中在多步执行：候选失败类型 **100% 是 `premature_final_response`（30 个）**，
其中 `refund_eligible` **20/20 全数失败**（dev 上为 10 条中 0 条成功），`refund_recovery`
20 条中失败 9 条。base 的失败则分散在 policy_violation 16 / verifier_failure 7 /
parser_format 3。LOG-20260807-09 定位的机制（训练数据 66.7% 只含 1 次工具调用 →
"调一次就写总结"）在封存集上重现，不是 dev 的偶然。

**统计口径**：两侧 CI95 大幅重叠（base [0.708, 0.850]、candidate [0.675, 0.825]），
仅凭 −3.3pp **不能**断言整体显著回退。但 `refund_eligible` 20/20 全失败是结构性崩溃而非
噪声，与格式类 41→0、16→0 的确凿改善同样应当照实陈述。**门禁不需要显著性**——它要求的是
+5pp 的实测提升，候选没有做到，因此 NO-GO 成立且无需附加解释。

**`verifier_reward` 再次与主判据背离**：0.5646 → 0.7500 上升，而 task_success 下降。
与 dev 上同向。这是 SPEC/CLAUDE.md 坚持"主判据是最终状态与政策 verifier、不是奖励值"的
第二个实例，本次发生在发布证据上，故记入。

**延迟门禁的已知限度**：gpu-5090 多人共用，运行期间他人占用在 12574→11854→10768 MiB、
利用率 56%→0%→100% 之间变动。p95 比值 1.0870 距阈值 1.25 有余量，负载噪声不足以翻转该项
结论；但该项在共享机器上的精度限度应在系统卡中写明，不得表述为精确测量。

**holdout 状态变更**：本次是该封存集合的**第一次实际观测**（LOG-20260811-02 中断那次为零
产出、未消耗）。此后其结果不得反馈进开发、调参、prompt/parser 或 checkpoint 选择；R4 改进
后的候选若要再次判定，需另行决定是否再消耗一次。

**尚未完成**：`serve` 按本决策的 baseline 回滚部署与允许/拒绝/异常恢复三条演示流程未执行，
因此 R3 验收目标仍未全部达成，阶段状态不改。

### LOG-20260811-04：serve 按 NO-GO 回滚部署并完成三条演示流程——R3 验收目标 4/5 达成

- 日期：2026-08-11
- 阶段/任务：R3 / Task 3 收口（`serve` 真实模型部署与演示）
- 状态：解决（服务已验证并关闭）
- 关联：LOG-20260811-03、LOG-20260810-03

**部署事实**：gpu-5090 物理 GPU 0，加载冻结 Qwen3-4B base，`127.0.0.1:8000`，
运行期间峰值与评测同量级。`service.json` 与 `/health` 一致声明
`release_decision=NO-GO`、`deployment=baseline`、**`adapter_loaded=false`**、
`failed_gate_ids=["success_delta"]`，`policy_id` 为
`qwen:Qwen/Qwen3-4B@8cd0101f…`——**没有 adapter 后缀**，与候选证据里的
`…+adapter:…#34544fac3ec9` 形成对照。SPEC §4「未过门禁的模型不得被服务入口加载」
在真实部署上得到验证，而不只是单元测试里的断言。

**三条演示流程全部成功，且轨迹可见**（qualification fixture，非 holdout）：
1. 允许 `refund_eligible`：`get_order`（返回 `refund_status=none`、`current_day=20`、
   `refund_deadline=30`）→ `refund_order(reason=wrong_item)` → `refunded`。
2. 拒绝 `refund_denied_ownership`：`get_order` 返回 `error_code=not_found` →
   **停止，未尝试退款**，`violations=[]`。正确拒绝与政策违规的区分在服务层可观测。
3. 异常恢复 `refund_recovery`：`get_order` → `refund_order` 遇 `transient_error`
   → **重试** `refund_order` → `refunded`。

**并发上限在真实服务上验证**：并发两个 episode 请求，先到者 200、后到者
**503「服务已达并发上限，请稍后重试」**。此前只有单元测试覆盖（`_MAX_CONCURRENT_EPISODES`
经突变验证），现在有真实 HTTP 证据。选择 503 而非排队的理由见 LOG-20260810-03。

**一个诚实的负面观察**：并发测试中作为陪衬发出的另一条 `refund_eligible`
（`6ff4f0d4…`）**失败了**——`success=false`、`termination=final_response`。
base 在 qualification fixture 上同样会"说完就停"，只是频率低于候选。演示流程挑选的三条
成功案例不代表 base 全对，holdout 上 base 的 `refund_eligible` 也有失败。记录于此，
避免后续把演示当成能力证明。

**R3 验收目标状态（4/5）**：GPU 命令均经确认并记录物理 GPU/时长/产物 ✓；正式运行目录
不可覆盖、配置与产物完整 ✓；候选未满足门禁因而诚实标 NO-GO ✓；服务完成允许/拒绝/
异常恢复三条流程并展示工具轨迹 ✓。**未达成的第五项**：「前 6 周交付可在面试中演示且
不依赖论文叙事」，其依赖的执行目标「模型卡、系统卡、演示流程与第一版简历证据」尚未产出。
**R3 阶段状态因此保持「当前」，不标已完成。**

**运行卫生**：服务已关闭、8000 端口释放、远端工作树干净；按 LOG-20260811-02 的新约束，
系统盘上的 `holdout-run.log`/`run_holdout.sh` 已移入数据盘
`reports/retail_ops/v1/r3/`（仍被 `.gitignore:72:/reports/retail_ops/` 覆盖），
`/home/tongjiakai` 下无残留。

### LOG-20260811-05：R3 交付文档收口——模型卡/系统卡/演示流程/简历证据，R4 提示词就绪

- 日期：2026-08-11
- 阶段/任务：R3 收口（交付文档）+ R4 启动准备
- 状态：解决（交付物齐备；**阶段状态待用户确认**）
- 关联：LOG-20260811-03、LOG-20260811-04、LOG-20260807-03（R2 由用户确认收口的先例）

**产出四份交付文档**，补齐 LOG-20260811-04 记录的唯一未达成验收项：

| 文件 | 内容 |
|---|---|
| `docs/MODEL_CARD.md` | 候选 `qwen3-4b-retailops-sft-001` 的身份/出处、训练过程、dev 与 holdout 双表、失败模式、NO-GO 判定、六项已知限制 |
| `docs/SYSTEM_CARD.md` | 四接口、数据治理机制、门禁与服务约束、实测资源画像、分层失败模式与恢复、八项已知限度 |
| `docs/DEMO.md` | 5 分钟讲解脚本、纯 CPU 全链路演示、真实模型服务演示、**必须一起讲的三个失败案例**、深挖问答 |
| `docs/RESUME_EVIDENCE.md` | 可用数字与出处对照、明确不可写的七类表述、简历 bullet 两个方案、面试主动交代三件事、后续阶段缺口 |

**编写原则（与 `docs/CAREER_CONTEXT.md` 证据纪律一致）**：每个数字都标出处
（`report_id`、产物路径或 LOG 编号）；把"不可写的表述"单列成表与可用数字并置，
使误用需要主动违反而不是无意越界；演示文档强制包含失败案例一节。

**一个刻意的编排决定**：`DEMO.md` 把「同批次另一条 `refund_eligible` 仍失败」
「`refund_denied_window` 曾无解、由真实采集而非 506 个 Oracle 测试暴露」
「把推测当结论后被 `wall_time_seconds` 推翻」三件事放进**主动交代**清单，而不是
藏进限制章节。理由：这三条恰好是本项目最有解释力的部分——它们证明结论来自证据而非叙事。

**简历叙述留作用户决策**：`RESUME_EVIDENCE.md` §3 给出方案 A（主语是系统与证据，
面向 Agent 平台/Evaluation 岗）与方案 B（主语是模型与归因，面向后训练/算法岗）。
两版只用同一批已核实数字，差别在强调面。取决于主投方向，**不由 agent 代选**。

**R4 执行提示词**：`docs/handoffs/2026-08-11-r4-execution-prompt.md`。它不预先批准
任何 GPU 运行、API 调用或第二次 holdout 观测；把「holdout 已消耗一次、结果不得回流开发」
写进不可违反边界，并列出五项用户决策门（改进方案选型、teacher 采集预算、预设收益门槛、
是否消耗第二次 holdout、是否安排独立重建复验）。给出两个改进方案（数据动作长度重平衡 /
改训练目标）并说明主 agent 倾向前者及理由，但要求执行方先做只读核查——包括**重新统计
66.7% 这个比例**而不是引用提示词自身。

**阶段状态未改**：`docs/EXECUTION_PLAN.md` 的 R3 仍为「当前」。R2 的先例
（LOG-20260807-03）是由用户确认后才更新阶段状态；R3 的第五项验收目标「可在面试中演示」
其成立与否取决于用户实际走读与脱稿复盘，不是 agent 产出文档即可宣告达成。

### LOG-20260811-06：R4 只读核查——根因精确化，并推翻两条改进方案的成本前提

- 日期：2026-08-11
- 阶段/任务：R4 第 0 步（只读核查，未改任何产品文件，未动 GPU/API）
- 状态：解决（核查完成；改进方案待用户裁决）
- 关联：LOG-20260807-09、LOG-20260811-03、LOG-20260811-05

**范围声明**：只使用 train(240) 与 dev(60)。**未打开任何 sealed holdout 产物**
（`sealed-eval/` 下两份 `trajectories.jsonl` 全程未读），holdout 的第二次观测未被消耗。

**66.7% 独立复算成立**（160/240 恰好 1 次工具调用），但它是粗口径。三条精确化：

1. **动作长度与场景类别完全共变**——每个场景的工具调用次数是常数（4 类各 1 次、
   `refund_eligible` 2 次、`refund_recovery` 3 次）。因此"重平衡动作长度"在本数据集上
   等价于"重平衡类别比例"，不存在只动长度不动类别的做法。
2. **训练集中「输出自然语言」与「回合结束」100% 共变**：被监督文本 29519 字符
   （字符代理，本地无 tokenizer）**全部**来自 4 个单步类别，两个多步类别贡献 0 字符。
   根源在环境而非导出——`runner.py:123` 在 `final_state == 1.0` 时立即 break，而
   `environment.py:59` 对 REFUND 类不要求终局回复，退款成功那刻轨迹即截断。
3. **真正的竞争在「get_order 已返回 + 用户以核实/检查口吻要求退款」这一族内，
   比例 120:40 = 3:1 偏向写文本**。`formal_tasks.py:516` 给 `refund_eligible` 与三个
   `refund_denied_*` 的措辞几乎不可区分，判别信号只在 get_order 返回值里。

**失败行为比"premature_final_response"这个标签具体得多**：dev 候选 17/17 失败末句均为
向用户请求确认（"请问您需要我为您办理退款吗？"）。模型**已正确读出状态并正确判定可退**，
只是不肯自己动手。这是行为倾向问题，不是能力丢失。

**模板/parser、工具 schema、verifier 三层均无缺陷**。工具 schema 与 system prompt
逐字节一致，`perturb_schema` 评测路径不启用；verifier 判定正确（候选一次都没调
`refund_order`）。assistant-only loss 不重开（LOG-20260807-06 已实测）；附一条备忘：
adapter 目录里的 `chat_template.jinja` 没有 `{% generation %}` 标记，那是
`save_pretrained` 存下的模型自带模板而非训练口径，容易被后来者误判为缺陷。

**两条被推翻的方案前提（本条的核心，直接改变 R4 成本排序）**：

1. **「给 `refund_eligible` 增采」不是 API 花销问题，是要重新冻结数据集。**
   `formal_tasks.py:118` 的 `assert_exact_quotas` 把每类别 40/10/20 写成硬契约；新增任务
   将改变 `dataset_version` 与 manifest 哈希，**已产出的 dev base、sealed holdout
   base/candidate 证据全部失去可比性**。R4 提示词第五节把该方案的代价估为"新的 teacher
   采集（有 API 成本）"，低估了。对现有 80 条多步样本做**重复采样**则不触碰任务契约。
2. **系统提示词是 sealed 配对字段。** `system_prompt_sha256` 在
   `SEALED_PAIRING_FIELDS`（`sealed_evaluation.py:307`）内。给 system prompt 补一句
   "确认符合政策后直接执行"是本次证据下最省力的干预，但它会让已有 sealed holdout base
   证据不可再用——将来任何发布判定都要**同时**重跑 base 与 candidate，一次判定消耗两侧
   观测而非一侧。

**由第 2 条追出的更强结论（适用于全部 R4 方案，不只提示词方案）**：
`code_commit` 与 `uv_lock_sha256` 同样在 `SEALED_PAIRING_FIELDS` 内，而
`_current_code_commit`（`product_cli.py:743`）取的是 git HEAD 且拒绝脏工作树。因此
**任何 R4 改进（哪怕只改导出脚本）落成提交后，已有 sealed holdout base 证据都不再可配对**，
未来的发布判定必须 base + candidate 一起重跑。这抹平了各方案在这一项上的差别：
"改提示词会额外消耗 base 侧观测"不构成选型依据，因为改代码同样会。真正的结论是
**R4 之后的任何一次 release 判定 = 封存 holdout 的第二次完整观测（两侧）**，
gate 4 的代价应按此计价。不得为规避这一点去放宽 `require_comparable_sealed_runs`。

**约束：parser 限制了改进方案的形状。** `parser.py:29-31` 把「文本 + 工具调用同时出现」
判为 `mixed_tool_call_content` 即非法调用。任何"让模型先声明再执行"的数据方案都会把
invalid_call 从 0 打回去；assistant 工具调用消息必须保持 `content` 为空。

**成本口径**：训练 134 s、dev 评测 base 154 s / candidate 251 s——一轮"改数据 → 训练 →
dev 配对"约 7 分钟 GPU。**便宜的是实验，贵的是 holdout 观测。**

**未做**：任何改进实现、任何 GPU/API 调用、任何 holdout 访问、任何阶段状态变更。
全量门禁复跑 624 passed / Ruff / mypy 65 源文件 / lock / diff 全绿，工作树干净。

### LOG-20260811-07：用户确认 R3 收口，阶段切换到 R4；第一轮方案与收益门槛已裁定

- 日期：2026-08-11
- 阶段/任务：R3 → R4 阶段变更（按 `docs/EXECUTION_PLAN.md`「阶段变更规则」1）
- 状态：解决
- 关联：LOG-20260811-04、LOG-20260811-05、LOG-20260811-06、LOG-20260807-03（R2 先例）

**R3 五项验收目标复核**（前四项证据见 LOG-20260811-03/-04，第五项见 LOG-20260811-05）：
GPU 命令均经确认并记录物理 GPU/时长/产物 ✓；正式运行目录不可覆盖、配置与产物完整 ✓；
候选未满足门禁因而诚实标 NO-GO ✓；服务完成允许/拒绝/异常恢复三条流程并展示工具轨迹 ✓；
「前 6 周交付可在面试中演示且不依赖论文叙事」——交付文档已产出，**其成立由用户确认**。
用户于本日确认该项达成。`docs/EXECUTION_PLAN.md` 的 R3 改为「已完成」、R4 改为「当前」。
沿用 R2 先例：阶段状态由用户确认后才改，agent 不自行宣告。

**用户裁定的三项 R4 决策**：

1. **第一轮方案 = 对多步家族重复采样**（不新增任务、不改冻结配额、不调 teacher API）。
   选它而不是"重新冻结数据集真增采"的依据是 LOG-20260811-06：后者会改变
   `dataset_version` 与 manifest 哈希，作废已有 dev base 与两份 sealed holdout 证据的
   可比性。选它而不是"改 system prompt"的依据是 `system_prompt_sha256` 在 dev 的
   `PAIRING_FIELDS` 内而 `code_commit` 不在——改数据/代码无需重跑 base dev，改提示词必须重跑。
2. **预设收益门槛 = 机制导向**：dev 上 `refund_eligible` 从 0/10 回到 **≥7/10**，
   同时 `invalid_call_count` 与 `policy_violation_count` 保持 0、`schema_valid_rate` 保持
   1.0。**不以 `task_success` 总数、不以 `verifier_reward`、不以 loss 作为判据**。
   理由：n=60 的 dev 上总成功率 CI 太宽，分不清小幅差异；而 20/20 全崩 → 回升是结构性
   可辨信号。**达不到即停止，不得转而扩展算法。**
3. **未裁决、留待下游的两项**：是否消耗封存 holdout 的第二次观测（按 LOG-20260811-06，
   该次判定必然是 base + candidate **两侧**重跑）；简历若要写"提升"是否安排一次独立重建复验。

**teacher API 预算门在本轮不适用**：重复采样不产生任何新的 teacher 采集。

### LOG-20260811-08：R4 Task 1 CPU 侧完成并启动首次重平衡 QLoRA-SFT（gpu-5090）

- 日期：2026-08-11
- 阶段/任务：R4 / Task 1（重复采样导出 + 首次重平衡训练）
- 状态：进行中（本条记录实现结论、前置事实与运行启动；训练与 dev 评测结果另条追加）
- 关联：LOG-20260811-06（根因精确化）、LOG-20260811-07（方案与门槛裁定）

**CPU 侧实现完成**（提交 `4942e0c`，17 个文件；624 → **636 passed**，Ruff / mypy 65 源文件 /
`uv lock --check` / `git diff --check` 全绿）。三个设计取舍值得记下：

1. **重复采样只作用于 `sft.jsonl`**。`train.jsonl` 与 `selection.json` 是 provenance，
   声称"本次导出覆盖了哪些冻结任务"；让重复漏进去会使产物声称 400 条任务而冻结契约只有
   240 条。实测两份文件与 `train-export-001` **逐字节相同**（`29f02425…` / `f60744f7…`）。
2. **`sft_oversample` 是必填配置键**。给默认值会让"忘了写"与"故意不重采样"产出同一份数据，
   事后无法从配置本身分辨这轮实验是否设置过。未知场景名与非正因子同理硬失败——静默忽略
   会产出与未重采样逐字节相同的文件，却让整轮结论挂在一个没发生的改动上。
3. **本轮不做任何消息内容改写**。"让模型先声明再执行"看似能直接治好"请求确认"这个行为，
   但 `parser.py` 把「文本+工具调用同时出现」判为 `mixed_tool_call_content` 即非法调用，
   那样是用一个已解决的失败换另一个。

**导出产物 `train-export-002`（本地 CPU）**：sft 400 行，场景计数 40/40/40/40/**120**/**120**；
去重后仍是原 240 条且集合与 001 完全相同（只重复、未改写）；单步样本占比 66.7% → **40.0%**；
「核实/检查口吻要求退款」族内 denied:eligible 由 **3:1 → 1:1**。teacher 质量门复算一致
（238/240 = 99.17%）。这些是**输入分布**的变化，不是能力证明。

**一处推迟**：候选 dev 评测 config 未写。其 `adapter.file_sha256` 是训练的运行产物，
提前写即无验证占位，等训练产出后再补并单独提交。

**远端前置**：gpu-5090 从 `90c9038` 经增量 bundle ff-only 同步到 `4942e0c`，工作树干净；
`pyproject.toml` 未变，无需重建环境。重平衡训练数据 `sft.jsonl`（957 KB）传至同一相对路径，
双端 SHA-256 一致（`53a1476e9bdf7d8d7d75b51ce1839ec6bd68606aef9267ce7ed455543bf2b86c`，400 行）。
**这是继 `train-export-001` 与 `holdout.jsonl` 之后第三份落到该多人共用服务器的私有数据**，
记录在此以便 R5 公开交付前复核暴露面。

**运行启动**：2026-08-11T20:58:50+08:00，物理 GPU 0（RTX 5090），工作目录
`/mnt/aidata/tongjiakai/retail-agent-ops`，`CUDA_VISIBLE_DEVICES=0
TORCH_DISABLE_NATIVE_JIT=1`，seed 0，config `retail_ops_v1_r4_sft_rebalanced.yaml`，
输出 `reports/retail_ops/v1/r4/sft-002/`。脚本经 `setsid` 脱离 ssh 会话，日志落
`/mnt/aidata`（按 LOG-20260811-02 的约束不写系统盘、不用 `/tmp`），轮询用短连接重试。

**资源现况与其影响**：启动时 GPU 0 已被他人两个进程占用 21125/32607 MiB、利用率 93–98%。
显存余量 11.4 GB 远高于训练峰值需求（R3 实测 5.16 GiB），因此**不影响能否完成**；
但每步实测约 5.8 s，75 步预计约 7–8 分钟，而非按 R3 线性外推的 224 s。
**此处只影响耗时，不影响本轮判据**——本轮主判据是 dev 的 `refund_eligible` 通过数与
失败 taxonomy，不含延迟门禁。若后续 dev 评测的延迟数被引用，须按共享 GPU 口径标注。

**尚未发生**：任何训练结果、任何 dev 候选评测、任何配对比较结论、任何 holdout 访问。

### LOG-20260811-09：R4 第一轮判负——重平衡使 refund_recovery +2，但 refund_eligible 纹丝不动 0/10

- 日期：2026-08-11
- 阶段/任务：R4 / Task 1（重平衡训练 + dev 配对评测）
- 状态：解决（**未达预设门槛，本轮判负并停止**）
- 关联：LOG-20260811-08（运行启动）、LOG-20260811-07（门槛裁定）、LOG-20260811-06（根因）

**运行事实**（gpu-5090 物理 GPU 0，RTX 5090，`GPU-07af326b-…`）：
训练 20:58:50→21:07:23（`train_runtime` 466.4 s，75 steps，峰值 5.54 GB，`EXIT=0`，
adapter 重载校验 `loaded: true`）；dev 候选评测 21:10:17→21:15:28
（`wall_time_seconds` 299.3 s，峰值 2.95 GB，`EXIT=0`）。
候选 `policy_id` = `qwen:Qwen/Qwen3-4B@8cd0101f…+adapter:reports/retail_ops/v1/r4/sft-002#cefbd181ae7f`。
`compare_dev_runs` 的配对契约**通过**，delta 可归因于 adapter：base
`d57654e9…`（既有 `qwen3-4b-dev-base-001`，未重跑）对候选 `8a994286…`。

**判定：未达预设门槛（LOG-20260811-07）。**

| 门槛项 | 要求 | 实测 | 结果 |
|---|---|---|---|
| `refund_eligible` | ≥7/10 | **0/10** | **未通过** |
| `invalid_call_count` | 0 | 0 | 通过 |
| `policy_violation_count` | 0 | 0 | 通过 |
| `schema_valid_rate` | 1.0 | 1.0 | 通过 |

逐场景（R3 候选 → R4 候选）：`lookup_status` 10/10→10/10、三个 `refund_denied_*` 各
10/10→10/10、`refund_recovery` **3/10→5/10**、`refund_eligible` **0/10→0/10**。
合计 43/60→45/60（0.7167→0.7500），仍低于 base 的 48/60（0.800），`task_success`
delta 为 **−0.0500**。15 条失败**全部** `termination=final_response`、`violations=[]`，
末句依旧是"请问您需要我为您办理退款吗？"这类请求确认。

**这个负结果证伪了什么（本条最有价值的部分）**：本轮把「get_order 已返回 + 用户以核实/
检查口吻要求退款」这一族内的训练比例从 **3:1 拉到 1:1**（`refund_eligible` 40→120 行），
`refund_eligible` 的通过数变化是**精确的 0**。因此
**"决策点上的条件动作比例是该行为的主要成因"这一假设，在 1:1 这个量级上不成立**。
不是"改善不显著"，是完全没动——把样本数翻三倍这件事，对这一类的作用为零。

**同一处理下两个多步家族的分化，是本轮唯一的正向信息**：两类都 ×3，
`refund_recovery` +2 而 `refund_eligible` +0。两者的区别不在样本数（都是 40→120），
而在 `_user_request`（`formal_tasks.py:516`）的措辞：`refund_recovery` 是无"核实"字样的
祈使句（"请为订单 X 按 Y 办理退款；临时失败时重试一次"），`refund_eligible` 的两个变体
**都**以核实/检查开头（"请核实订单 X 并按 Y 办理退款" / "订单 X 需要因 Y 退款，请先检查
后处理"）。据此，残余决定因素更像是**请求措辞把任务框定成"先核实再回报"**，而不是数据量。
**这是观察，不是已验证结论，本条不据此启动任何改动**——是否花掉第二轮验证它由用户决定。

**`verifier_reward` 第三次与主判据背离**：0.5792→0.7500 上升而 `task_success` 下降。
前两次分别发生在 R3 dev（LOG-20260807-09）与封存 holdout（LOG-20260811-03）。
三次同向，足以把"奖励值不能代替最终状态判据"从原则变成本项目的实测规律。

**格式/安全侧完整保住**：`invalid_call` 21→0、`policy_violation` 8→0、
`schema_valid_rate` 0.7812→1.0000，与 R3 候选持平。这验证了"重复采样而不降采 denied 三类"
这个取舍是对的——比例照样被改变，而已获得的收益一件没丢。

**训练侧的旁证**：`train_loss` 0.3722→**0.2198**、`eval_mean_token_accuracy`
0.9436→0.9468。**损失更低而目标行为没有改善**，这与 R3 记录的"loss/奖励不是判据"是同一件事的
第二种表现形式。`average_tool_calls` 1.10→1.17、`average_turns` 2.05→2.08、
`average_output_tokens` 149→156——模型确实"多调了一点、话也更多了一点"，但增量全部落在
`refund_recovery`。

**延迟数的口径限制**：本次评测期间 GPU 0 被他人占用、利用率 96–98%，
`average_latency_ms` 4176→4979、`p95` 5211→5689 的变化**不得**表述为模型差异；
本轮判据不含延迟门禁，此处只作记录。同理训练 466 s 而非按 R3 线性外推的 224 s。

**停止**：按 LOG-20260811-07 的预设停止条件，本轮判负即停止，**不转而改训练目标、
不改 system prompt、不扩展算法**。是否开第二轮、验证哪个假设，是下一个用户决策门。
未消耗封存 holdout 的第二次观测。
