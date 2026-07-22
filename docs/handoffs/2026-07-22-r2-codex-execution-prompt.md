# RetailAgentOps R2 Codex 全阶段执行提示词

## 使用方式

在新项目目录启动 Codex：

```bash
cd /home/tjk/myProjects/internship-projects/retail-agent-ops
codex
```

然后把下面“可直接复制的提示词”完整发送给 Codex。不要只截取任务列表；审批门、holdout 边界和停止规则同样是任务要求。

## 可直接复制的提示词

```text
你现在负责 RetailAgentOps 的 R2“数据与评测流水线”阶段。工作目录必须是：

/home/tjk/myProjects/internship-projects/retail-agent-ops

目标是在保留 R1 全部契约和证据边界的前提下，完整实现、运行并验证 R2，最终只在所有验收证据成立时把 R2 标为已完成。R2 设计选择和 CPU 实施计划已经用户批准；用户已授权本阶段使用 subagent 和连续 CPU 实现，但正式数据、API、模型下载、SSH、远端修改和每条 GPU 命令仍是独立审批门。

一、不可违反的边界

1. 先读取并遵守根目录 AGENTS.md；若与本提示词冲突，以 AGENTS.md 和用户最新指令为准。
2. 当前 R1 基线提交是 59cc1b5。当前 HEAD 必须是该提交的后代；保留用户已有修改，不得 reset、checkout 覆盖或清理无关内容。
3. 产品名是 RetailAgentOps，Python 包暂时仍是 veritool_rl；R2 不做全仓改名。
4. R2 只交付正式数据与评测流水线、冻结 split/evaluator、base 证据和数据质量报告。QLoRA-SFT、adapter、candidate 训练、DPO、GRPO、在线 RL 属于 R3/R4，不得提前实施。
5. 本地 WSL 只运行 CPU 开发、测试、lint、类型检查、任务构建和轻量 smoke。严禁本地 GPU 推理或训练。
6. 任何 ssh gpu-4090 命令执行前，必须先给用户展示：完整命令、实际远程工作目录、物理 GPU、预计时长、预期产物；等待明确确认后才能运行。不得用“逻辑 GPU 0”代替物理卡说明。
7. API、模型下载、teacher 批量生成、正式数据生成和正式 holdout 冻结前，必须先展示批准后的 route/config、数量、token/请求限制、时长和产物路径并等待确认。
8. 固定 BFCL 200 条 holdout、其答案、失败样例和 evaluator 继续独立只读。它们不能成为 RetailOps train/dev、prompt/parser 调整或内部指标的输入。
9. 正式 RetailOps holdout 的任务真值、prompt、target_state、expected_calls、完整轨迹和逐任务失败只能位于 ignored sealed 路径；不得进入 Git、planning 文件、subagent prompt、公开报告或开发分析输入。
10. 不自动 push、发布或创建外部仓库。

二、固定上下文恢复顺序

开始任何实质工作前，主 agent 必须完整读取：

1. docs/CAREER_CONTEXT.md
2. docs/PRODUCT_BRIEF.md
3. docs/EXECUTION_PLAN.md
4. task_plan.md、findings.md、progress.md
5. docs/PROJECT_LOG.md 最近一条记录
6. SPEC.md
7. docs/superpowers/specs/2026-07-20-retailops-v1-contract-design.md
8. docs/superpowers/plans/2026-07-20-retailops-v1-r1-vertical-slice.md
9. docs/superpowers/specs/2026-07-22-retailagentops-project-migration-and-r2-handoff-design.md
10. docs/superpowers/specs/2026-07-22-retailops-v1-r2-formal-data-and-base-design.md
11. docs/superpowers/plans/2026-07-22-retailops-v1-r2-formal-data-and-base.md
12. 本提示词文档

主 agent 自己读取适用技能的 SKILL.md；不得把技能解释委托给 subagent。复杂任务使用 planning-with-files；设计先使用 brainstorming，实施计划使用 writing-plans，批准后优先使用 subagent-driven-development，完成前使用 verification-before-completion。

三、只读 preflight

先执行并报告，不修改文件：

pwd
git status --short --branch
git log -5 --oneline --decorate
git merge-base --is-ancestor 59cc1b5 HEAD
git rev-parse --show-toplevel
git rev-parse --git-dir
git rev-parse --git-common-dir
git remote -v
readlink -f data/external_repos
git -C data/external_repos/gorilla rev-parse HEAD
.venv/bin/python --version
tools/bfcl_eval/.venv/bin/python --version
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy
git diff --check
UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple uv lock --check

预期迁移后 CPU 基线是 211 passed，Ruff/mypy/lock/diff 全绿；测试数量可因当前 HEAD 的迁移治理测试增加而上升，不能因数量不同就机械回退。若现有工作树不干净，先判断修改归属并保留；若基线失败，先做证据化诊断，不得把环境问题误写成产品缺陷。

四、已完成方案审批与当前执行入口

R2 设计选择和 CPU 实施计划已经用户批准，唯一正式事实源是：

- `docs/superpowers/specs/2026-07-22-retailops-v1-r2-formal-data-and-base-design.md`
- `docs/superpowers/plans/2026-07-22-retailops-v1-r2-formal-data-and-base.md`

不得重复创建平行规格或重新打开已裁决方案。继续执行前仍须确认 `task_plan.md` 已写清当前
输入、输出、非目标、影响文件、失败模式和验收命令，并复核以下代码/数据能力：

- src/veritool_rl/retail_ops/{tasks,manifests,governance,evaluation}.py
- src/veritool_rl/data/generators.py
- src/veritool_rl/eval/ 与 src/veritool_rl/agent/qwen.py
- scripts/build_trajectories.py、scripts/evaluate.py
- 相关 tests、configs、manifests 和 ignored data 路径

已批准的关键选择为：family-first `240/60/120`、动态 provider namespace、初始 DeepSeek
V4 Pro 非思考 profile、teacher 总体/单类 `70%/50%` 门、Qwen3-1.7B 与 Qwen3-4B 两份
dev-only base，以及 R2 不运行正式 holdout 模型。CPU 实现可连续推进；未经后续逐项批准，
不得生成仓库正式 `240/60/120`、调用 API、连接服务器、下载模型或运行远程推理。

五、R2 实现必须覆盖的最小闭环

最终任务拆分可以根据批准规格调整，但不得遗漏以下交付面：

1. 正式任务与 split 冻结
   - 目标配额固定为 train/dev/holdout 240/60/120；六类均衡为每类 40/10/20。
   - 先按 family 分组，再分配 split，再物化任务和派生轨迹；不得先生成后靠 task_id 随机切分。
   - task_id、family_id、任务内容哈希和派生指纹跨 split 全部无交叉。
   - 除完整任务哈希外，必须增加不含 task_id/split/答案字段的 answer-free content fingerprint，以及绑定 source/family/派生规则的 derivation fingerprint；不能靠“改 ID 或改 split 后哈希不同”掩盖派生泄漏。
   - family 数量、每族变体数、派生规则、正式 seed、dataset version 和 family-aware split algorithm ID 都要写入批准规格；若 family 边界无法精确满足配额，直接失败，不得拆 family 或复制任务补齐。
   - 固定 generator/version/seed/bundle SHA、类别顺序和 canonical JSON；同输入重复构建字节稳定。
   - 正式输出目录不可覆盖。

2. 数据 provenance 与质量流水线
   - 对 train/dev 每条源任务和轨迹记录 source/input SHA、teacher/provider/model/revision、prompt/template hash、采样参数、seed、成本/token、bundle/manifest hash、代码 commit；不适用字段也要用明确的 provider=internal、零成本 deterministic/reference provenance 表达，不能留空或伪造 API 元数据。
   - 训练候选轨迹 100% schema 合法；进入训练集的成功轨迹 100% 经真实 RetailOpsEnv 重放并通过最终状态与政策校验。
   - 报告类别覆盖、成功率、执行通过率、replay、重复率、policy violation、非法调用、失败 taxonomy 和资源字段。
   - 非成功/不可重放/泄漏/重复轨迹不得进入训练数据；过滤原因需聚合可审计，但公共报告不得泄漏 holdout 或受限原文。

3. sealed holdout 与公共 receipt
   - 默认逻辑根为 data/private/retail_ops/v1/，保持 Git ignored。
   - holdout 原始任务、答案、完整轨迹、逐任务失败和任何可反推真值的映射必须 sealed。
   - 公共 receipt 只保留版本、bundle/evaluator/generator 标识、配额、task/family 指纹和 artifact SHA；不得包含 user_request、initial_state、target_state、expected_calls、metadata 原文或失败 ID。
   - 复用并加固 HoldoutReceipt、assert_split_isolation、authorize_holdout；授权必须在读取任何 holdout truth 之前发生。
   - 授权 loader 不能只验证整文件 SHA：通过授权后仍须逐行解析并核对 task count、类别配额、task/family 顺序、逐任务哈希、bundle、split 和 receipt 内部一致性。
   - 篡改、错路径、错目的、错 bundle/evaluator/hash、跨 split 派生重复都必须硬失败。

4. 冻结 evaluator 与 base 证据
   - 开发模式只能读 train/dev；普通 evaluate/build/policy 入口继续在任何 truth 访问前拒绝 holdout。
   - sealed release evaluator 只接受匹配 receipt/hash 和 release purpose，完整输出留 sealed；公共输出只允许聚合指标、完整性、manifest/bundle/model/parser/budget/hardware provenance 和脱敏失败 taxonomy。
   - base 运行必须固定 model/provider checkpoint 与 revision、模型文件哈希、parser/system prompt/generation 参数、budget、seed、任务 manifest、代码 commit、lock SHA、GPU UUID、峰值显存、wall time、吞吐、token、延迟和成本字段。
   - CPU 单测必须使用 fake backend，不得为了测试下载或加载真实模型。Qwen3-1.7B/Qwen3-4B 在 R2 只能是无 adapter 的 base，不输出 GO/NO-GO。
   - 若用户未批准 GPU 或模型不可用，不能伪造 base 数字，也不能把 R2 标为完成；记录准确 blocker 并保留已完成的 CPU 产物。

5. CLI、配置和报告
   - 延续 retail-agent-ops 稳定命令面，配置严格拒绝未知字段和项目外逃逸路径。
   - 正式命令必须可从冻结输入重建 manifests、quality report、base evidence 和公共 receipt；每个产物含 hash/provenance 且不可覆盖。
   - 报告明确区分 synthetic qualification、dev base、sealed holdout 和 BFCL 外部回归；不得把任一内部子集称为官方全量、排行榜或生产效果。

6. R2 收口
   - 用独立新目录重复关键 CPU build，比较 manifest、receipt 和公开报告的稳定哈希。
   - 执行 secret、模型文件、holdout truth、failure ID、BFCL prompt 和路径泄漏扫描。
   - 只有全部验收成立时，才把 docs/EXECUTION_PLAN.md 的 R2 标为已完成、R3 保持待执行；更新 task_plan.md、findings.md、progress.md，并 append-only 追加 docs/PROJECT_LOG.md。

六、subagent 协作规则

用户允许使用 subagent。批准实现计划后优先采用 subagent-driven-development：

- 每个计划任务只分配一个 implementer 写代码，禁止两个 agent 同时编辑相同文件或共享正式产物目录；
- 每个任务结束后先由独立 spec reviewer 只读核对批准规格，再由 quality reviewer 只读核对代码、测试、泄漏和范围；
- reviewer 发现 Important/阻塞问题时，回到同一任务补失败测试和修复，再重审；
- subagent 不得自行运行 API、下载、GPU、正式 holdout 或外部发布；这些权限只由主 agent 在用户确认后执行；
- 所有 subagent 禁止打开、搜索、打印或总结 data/private/retail_ops/v1/；正式 holdout freeze/evaluation 只由主 agent 在审批后执行；
- 主 agent 必须检查实际 diff、提交和测试输出，不能把 subagent 的成功声明当作证据；
- 每项实现使用 TDD：失败测试、确认正确失败、最小实现、focused tests、完整相关回归、commit、双阶段审查；
- 每两次重要查看后同步 findings.md，所有错误写入 task_plan.md，阶段证据持续写入 progress.md。

七、硬停止条件

出现以下任一情况立即停止对应资源消耗，保留证据并向用户报告，不得绕过：

- 任意 train/dev/holdout 的 task_id、family_id、内容哈希或派生指纹交叉；
- holdout prompt、真值、完整失败、failure ID 或轨迹进入 Git、公共报告、planning、subagent prompt 或开发分析；
- 根据 holdout 指标/失败修改 prompt、parser、数据、阈值、模型选择或 checkpoint；
- evaluator/replay 同输入不稳定，manifest/receipt/hash 不闭合或无法重建；
- base/candidate 不同 manifest、parser、budget、seed 或 evaluator 却尝试比较；
- 固定 BFCL holdout 或其失败样例进入 RetailOps 开发；
- API credential/余额/限流失败、模型缺失、Docker/WSL/SSH/GPU 环境异常。先归类为外部环境，不得伪造结果或擅自扩大基础设施；
- 需要改变 240/60/120 配额、六类任务、release 门槛、模型家族、训练算法或大型基础设施；
- 任何 GPU/API/下载命令尚未得到用户对精确命令的确认。

八、每个任务和最终阶段的验收

每个任务至少运行其 focused tests、相关回归、.venv/bin/ruff check .、.venv/bin/mypy 和 git diff --check，并形成独立提交。不要自动 push。

阶段最终必须在实际最终 HEAD 运行：

.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy
git diff --check
UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple uv lock --check
git status --short --branch

另外必须用自动化测试或可复核命令证明：

- train/dev/holdout 恰为 240/60/120，每类恰为 40/10/20；
- task/family/content/derived fingerprint 无交叉；
- 进入训练的成功轨迹 100% schema 合法且 100% 可重放；
- holdout artifact 只在 ignored sealed 路径，公共 receipt/report 无真值和逐任务标识；
- 同一冻结输入重复构建的 manifest、receipt 和公共报告稳定；
- base report 绑定真实 model/provider revision、commit、manifest、parser、budget、硬件和实际资源指标；
- R2 原验收要求的 Qwen3-1.7B 与计划主模型两份真实 base report 均存在；若用户选择缩窄范围，则必须已有明确批准并同步修改 EXECUTION_PLAN，不能用缺失报告直接收口；
- 未生成 adapter、未训练 candidate、未进入 DPO/GRPO/在线 RL；
- 工作树干净，最终验收在最后一个提交上重跑，而不是引用早期 green 结果。

最后还要运行 BFCL 边界审计，确认相对 R1 基线没有修改固定 BFCL manifest/config/evaluator：

git diff 59cc1b5 -- manifests/bfcl_v4_single_turn_seed0.json configs/bfcl_v4_base_vs_sft_seed0.yaml configs/bfcl_v4_sft_data_seed0.yaml configs/bfcl_v4_sft_seed0.yaml configs/bfcl_v4_single_turn_seed0.yaml configs/bfcl_v4_single_turn_sft_seed0.yaml tools/bfcl_eval src/veritool_rl/eval/bfcl.py src/veritool_rl/eval/bfcl_compare.py src/veritool_rl/eval/bfcl_runner.py
git check-ignore -q data/private/retail_ops/v1/holdout/tasks.jsonl
git ls-files data/private reports/retail_ops models checkpoints weights

BFCL diff 和 git ls-files 的敏感路径输出必须为空；若迁移文档本身不涉及这些路径，不允许用“预期差异”放行。

如果任何 R2 验收目标未满足，保持 R2 为当前或准确标记阻塞，不得为了“完成阶段”降低阈值、隐去缺失结果或把计划目标写成实际结果。
```
