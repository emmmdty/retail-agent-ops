# RetailAgentOps R2 Task 8 执行提示词

## 使用方式

在项目目录启动新会话（Claude Code 或 Codex 均可）：

```bash
cd /home/tjk/myProjects/internship-projects/retail-agent-ops
```

然后把下面"可直接复制的提示词"完整发送给 agent。不要只截取任务列表；逐条审批门、
holdout 边界和停止规则同样是任务要求。本提示词与前一个（Task 5-7 的 CPU 实现提示词）
性质不同：Task 8 **允许执行真实外部操作**（本地 API 调用、远端 SSH、模型下载、GPU
评测），但只允许在用户对每一条精确命令单独确认后执行，不得批量批准、不得预先假设批准。

## 可直接复制的提示词

```text
你现在负责 RetailAgentOps R2"数据与评测流水线"阶段的最后一个任务：Task 8（审批门控的正式
运行与最终收口）。工作目录必须是：

/home/tjk/myProjects/internship-projects/retail-agent-ops

Task 1-7（formal 任务生成、manifest/holdout 治理、provider-agnostic teacher 路由与
client、teacher 采集/质量门/train 导出、sealed evaluator、Qwen dev base 证据、CLI
pipeline 分派、CPU 端到端验收、整分支审查与修复）已经全部完成、独立审查通过、并提交在
当前分支 `feature/r2-formal-data-and-base-eval` 上，HEAD 为
`7f77f0a7fa9eae2fcd312d88663513226641b7ff` 的后代。你的任务范围是执行
`docs/handoffs/2026-08-06-r2-external-run-commands.md` 里列出的外部命令并完成 R2 最终
收口——但**逐条单独获得用户批准之前，一条都不能执行**。

一、不可违反的边界

1. 先读取并遵守根目录 AGENTS.md/CLAUDE.md；若与本提示词冲突，以它们和用户最新指令为准。
2. 当前 HEAD 必须是 `7f77f0a7fa9eae2fcd312d88663513226641b7ff`（R2 Task 7 收口提交）的
   后代，且必须包含提交 `06a41f9`（Task 5）、`bea052c`（Task 5 修复）、`07da971`（Task 6）、
   `96536c9`（Task 6 修复）、`c4d7fdc`（整分支审查修复）。保留用户已有修改，不得 reset、
   checkout 覆盖或清理无关内容。
3. **每一条外部命令（本地 API 调用、SSH、模型下载、GPU 命令）都必须单独展示精确命令、
   实际工作目录、预计时长和产物，并等待用户明确批准后才能执行。禁止把
   `docs/handoffs/2026-08-06-r2-external-run-commands.md` 当作"已批准清单"一次性顺序
   执行——那份文档本身写明"未执行"，只是把命令准备好，批准仍需逐条进行。**
4. 产品名是 RetailAgentOps，Python 包暂时仍是 `veritool_rl`；不做全仓改名。
5. QLoRA-SFT、adapter 训练、DPO、GRPO、在线 RL 不属于本任务范围，即使 dev base 结果看起来
   "值得训练"也不得提前进入 R3。
6. 本地 WSL 只运行 CPU（formal freeze、`.env` preflight、teacher API 调用）；模型下载、
   GPU smoke、GPU dev run 只能在批准后的远端环境（`gpu-4090` 或 `gpu-5090`，二选一，
   CLAUDE.md 第4节要求同一任务只用其中一个并在报告中注明）执行。
7. 固定 BFCL 200 条 holdout、其答案、失败样例和 evaluator 继续独立只读，不能成为
   RetailOps train/dev、prompt/parser 调整或内部指标的输入。
8. 正式 RetailOps holdout（120 条）的任务真值、prompt、target_state、expected_calls、
   完整轨迹和逐任务失败只能位于 ignored sealed 路径；R2 不得在正式 holdout 上运行任何
   模型评测（`evaluate_authorized_holdout`/`sealed_evaluation.py` 在本任务范围内不得被
   调用）；不得进入 Git、planning 文件、subagent prompt、公开报告或开发分析输入。
9. 不自动 push、发布或创建外部仓库。分支处置（是否/何时 merge）在全部证据回收并最终
   验收通过后由用户决定，agent 不得自行合并。

二、固定上下文恢复顺序

开始任何操作前，主 agent 必须完整读取：

1. docs/CAREER_CONTEXT.md
2. docs/PRODUCT_BRIEF.md
3. docs/EXECUTION_PLAN.md
4. task_plan.md、findings.md、progress.md（重点看 2026-08-05/06 的 R2 Task 5-7 相关条目）
5. docs/PROJECT_LOG.md 最近记录（从 LOG-20260805-10 到 LOG-20260806-02）
6. SPEC.md
7. docs/superpowers/specs/2026-07-22-retailops-v1-r2-formal-data-and-base-design.md
8. docs/superpowers/plans/2026-07-22-retailops-v1-r2-formal-data-and-base.md
   （本提示词只覆盖其中的 Task 8 小节，第 340-375 行）
9. **docs/handoffs/2026-08-06-r2-external-run-commands.md**——本任务的主要命令来源，
   逐节写明了 formal freeze、`.env` preflight、6/240 任务 teacher API 调用、只读 SSH
   盘点、远端代码同步、模型下载、单任务/60 任务 GPU dev run、证据同步与最终验收的精确
   命令；第 0 节写明了整分支修复引入的真实执行顺序前提（`formal_freeze` 公开产物须先
   提交才能进入 `formal_dev_base`；两份 dev-base config 的真实 `model.revision`/
   `file_sha256` 须提交而非远端临时编辑；所有 `--output_dir` 须指向已忽略路径）——这些
   前提不是建议，是代码里真实存在的检查（`_current_code_commit` 会在工作树不干净时
   直接拒绝运行）。
10. 本提示词文档。

主 agent 自己读取适用技能的 SKILL.md；不得把技能解释委托给 subagent。

三、只读 preflight

先执行并报告，不修改文件：

```bash
pwd
git status --short --branch
git log -10 --oneline --decorate
git merge-base --is-ancestor 7f77f0a7fa9eae2fcd312d88663513226641b7ff HEAD
git merge-base --is-ancestor c4d7fdc HEAD
.venv/bin/python --version
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy
git diff --check
env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check
stat -c "%a %n" .env
grep -o '^[A-Z_]*=' .env
```

预期基线是 506 passed，Ruff/mypy/lock/diff 全绿，`.env` 权限 600、变量名精确为
`TEACHER_LLM_PROVIDER`/`TEACHER_LLM_DEEPSEEK_{BASE_URL,API_KEY,MODEL,EXTRA_BODY_JSON}`。
若现有工作树不干净，先判断修改归属并保留；若基线失败，先做证据化诊断，不得把环境问题
误写成产品缺陷或跳过 preflight 直接执行外部命令。

四、本阶段执行范围（对应计划 Task 8 Step 1-6，精确命令均在
`docs/handoffs/2026-08-06-r2-external-run-commands.md`）

严格按顺序推进，每一步都是独立审批门，前一步未被用户确认完成前不得进入下一步：

**Step 1：formal freeze（本地 CPU）**
展示命令清单第 1 节的精确命令、工作目录、预计产物，等待批准后执行一次；随后建议
（非强制）在临时目录独立重跑一次做逐字节比较。**批准执行后必须立刻把公开产物
（`manifests/retail_ops/v1/retail_ops_v1_r2_20260722/`）提交到 Git**——命令清单第 0 节
已经解释了原因：这个目录不在 `.gitignore` 覆盖范围，不提交会导致后续 `formal_dev_base`
被脏工作树检查拒绝。

**Step 2：`.env` preflight + 六任务 API smoke（本地，真实网络调用）**
先展示命令清单第 2 节的只读检查结果（不打印密钥值），用户确认无误后，展示第 3 节的
6 任务 smoke 精确命令、预计费用（<$0.01）和预计耗时，批准后执行。执行后报告 route
snapshot、结构/环境成功率、总请求数、token 用量、错误分类，不得访问 dev/holdout。

**Step 3：240 任务 API 全量采集 + train 导出（本地，真实网络调用）**
必须在用户对 Step 2 的 smoke 结果单独确认"符合预期"之后才请求批准。展示命令清单第 4 节
的精确命令、预计 8-40 分钟耗时区间、预计 $0.05-0.10 费用、质量门阈值（整体≥70%、每类
≥50%）、checkpoint 续跑边界。批准后执行；质量门不达标时停止并报告，不得自动改
prompt/模型/provider。执行后报告 teacher 总/逐类别通过率、teacher/internal_reference
条数、总请求数、总费用、总耗时。

**Step 4：远端各审批门（每个都单独批准）**
先获得只读盘点批准（命令清单第 5 节），报告结果前不得写出任何 GPU 命令。拿到物理
GPU index/UUID/空闲显存/其他用户占用/磁盘余量后，依次单独展示并等待批准：远端代码同步
（第 6 节，含确认远端工作树干净）、模型下载（第 7 节——**先问用户是否复用 gpu-5090
已下载并校验过的 Qwen3-1.7B/4B，而不是默认重新下载**）、单任务 GPU smoke（第 8 节，
每个模型一次）、60 任务 GPU dev run（第 9 节，每个模型一次）。任何一条都不得替对方
默认"顺便"执行；物理 GPU 身份必须来自 `nvidia-smi`，禁止把逻辑 `cuda:0` 当作物理身份
报告。

**Step 5：证据同步与核对**
按命令清单第 10 节，只同步已批准的公开安全产物和私有产物摘要哈希回本地；私有完整证据
留在产出环境的 ignored 路径。逐份产物核对本地/远端 SHA-256 一致，重新加载证据校验
（`load_run_evidence`/`load_base_run_evidence` 等），拒绝任何在相关 commit 之后产出的
陈旧运行。

**Step 6：最终验证与收口**
在实际最终 HEAD 跑一遍完整 CPU 门禁，执行整分支审查（可复用 Task 7 的方法：生成
`a3c748b..HEAD` 的审查包并派发独立审查），更新全部 planning/log 文档。只有正式数据、
teacher 全量质量、两份真实 dev base、泄漏扫描和哈希证据全部到位，才能把 R2 标记为
已完成；否则保持"当前"并准确记录阻塞原因。使用 `superpowers:finishing-a-development-branch`
展示分支处置选项，不自动 merge。

五、已完成能力与本阶段可复用的已审计模式

Task 1-7 已经实现、独立审查过、可以直接复用，不要重新发明：

- `formal_tasks.py`/`formal_manifests.py`/`formal_governance.py`：formal 任务生成、
  manifest/holdout 治理、两阶段 sealed holdout 授权（`authorize_formal_holdout`/
  `load_authorized_formal_holdout`）、`load_verified_formal_dataset`（五维隔离交叉校验，
  Task 7 修复后 `formal_dev_base` 也经过这条路径）。
- `teacher_route.py`/`teacher_client.py`/`teacher_data.py`：provider-agnostic teacher
  路由、client、采集/质量门/导出全链路，`_require_evidence_binds_record`（Task 7 新增，
  export 时核对证据与任务记录的 fingerprint/trajectory/治理哈希一致）。
- `sealed_evaluation.py`/`base_evaluation.py`：sealed evaluator、Qwen dev base 评测，
  `evaluate_formal_dev_base` 现在要求工作树干净（`_current_code_commit` 会拒绝脏树）、
  要求 backend 声明的 adapter/生成参数与冻结 config 一致。
- `product_cli.py`：`retail-agent-ops build/evaluate` 的 `pipeline` 分派
  （`formal_freeze`/`teacher_collect`/`train_export`/`formal_dev_base`），R1
  `build/evaluate/release/serve` 原样可用。
- gpu-5090（第二远程环境，CLAUDE.md 第4节、LOG-20260805-01/02/03）：Qwen3-1.7B/4B 已
  下载并逐文件 SHA256 校验通过，`uv` 环境（dev+train extra）已验证 `torch` 正确识别
  RTX 5090；`teacher` extra 尚未在远端同步过。DeepSeek `deepseek-v4-flash`
  （非思考模式，需要 `extra_body={"thinking":{"type":"disabled"}}`）已验证真实可用。

六、执行方式：主 agent 独占，不使用 subagent 执行外部操作

与 Task 5-7 不同，Task 8 不适合 subagent-driven-development：这里没有"实现任务"，只有
"逐条获批后执行外部命令并如实报告"。因此：

- 所有 API 调用、SSH、模型下载、GPU 命令必须由主 agent 直接执行，不得委托给 subagent——
  subagent 无法在执行中途向用户请求单条命令批准。
- 如果某个子步骤纯粹是只读分析/证据核对且不涉及执行新的外部命令（例如 Step 6 的整分支
  复审），可以复用 Task 5-7 建立的 subagent-driven-development 模式派发独立审查。
- 所有 subagent（如果使用）禁止打开、搜索、打印或总结 `data/private/retail_ops/v1/`
  下的任何内容。

七、硬停止条件

出现以下任一情况立即停止对应资源消耗，保留证据并向用户报告，不得绕过：

- 任意 train/dev/holdout 的 task_id、family_id、内容哈希或派生指纹交叉；
- holdout prompt、真值、完整失败、failure ID 或轨迹进入 Git、公共报告、planning、
  subagent prompt 或开发分析；
- 根据 holdout 指标/失败修改 prompt、parser、数据、阈值、模型选择或 checkpoint；
- evaluator/replay 同输入不稳定，manifest/receipt/hash 不闭合或无法重建；
- base/candidate 不同 manifest、parser、budget、seed 或 evaluator 却尝试比较；
- 固定 BFCL holdout 或其失败样例进入 RetailOps 开发；
- teacher 总通过率 <70% 或任一类别 <50%——停止并报告，不自动换 provider/model/prompt；
- `formal_dev_base` 因工作树不干净被拒绝——不得绕过检查（如临时改代码跳过校验），
  按命令清单第 0 节的顺序先提交必要文件；
- 任何一条命令清单里的操作在没有用户对**那一条精确命令**明确批准前被执行；
- 物理 GPU 盘点结果显示显存/进程占用不足以安全运行，或磁盘余量不足；
- 需要改变 240/60/120 配额、六类任务、release 门槛、模型家族或训练算法。

八、每一步和最终阶段的验收

每个 Step 至少记录：实际执行的命令、实际耗时、实际产物路径与哈希、任何错误与处理方式。
触发 CLAUDE.md 第7节记录条件时先追加 `docs/PROJECT_LOG.md` 再在回复中报告 LOG ID。

Step 6 结束时必须在实际最终 HEAD 运行：

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy
git diff --check
env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check
git status --short --branch
```

另外必须用可复核的产物证明：

- 正式 train/dev/holdout 各 240/60/120 条，五维隔离通过，manifest/receipt 哈希闭合；
- teacher 全量采集通过质量门，240 条 train 全部 schema/environment/policy/replay 有效；
- 两份 Qwen dev base（1.7B/4B）证据完整绑定模型/硬件/代码/配置 provenance，可重新加载
  验证且未被篡改；
- 仓库级 secret/BFCL/holdout 泄漏扫描干净；
- 工作树干净，最终验收在最后一个提交上重跑，而不是引用早期 green 结果。

如果任何验收目标未满足，保持阶段状态为进行中或准确标记阻塞，不得为了"完成阶段"降低阈值、
隐去缺失结果或把计划目标写成实际结果。
```
