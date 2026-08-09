# RetailAgentOps R2 Task 5-7 执行提示词

## 使用方式

在项目目录启动新会话（Claude Code 或 Codex 均可）：

```bash
cd /home/tjk/myProjects/internship-projects/retail-agent-ops
```

然后把下面"可直接复制的提示词"完整发送给 agent。不要只截取任务列表；审批门、holdout 边界和停止规则同样是任务要求。

## 可直接复制的提示词

```text
你现在负责 RetailAgentOps R2"数据与评测流水线"阶段的收尾部分：Task 5（sealed evaluator
与 Qwen dev base 证据）、Task 6（CLI 分派与 CPU 端到端验收）、Task 7（整体审查并准备外部
审批命令清单）。工作目录必须是：

/home/tjk/myProjects/internship-projects/retail-agent-ops

Task 1-4（formal 任务生成、manifest/holdout 治理、provider-agnostic teacher 路由与
client、teacher 采集/质量门/train 导出）已经完成、独立审查过、并提交在当前分支
feature/r2-formal-data-and-base-eval 上。你的任务范围只到 Task 7 结束——即完成 CPU 实现、
审查，并写出"可复制执行的外部命令清单"，不得实际运行 Task 8 的任何外部操作（正式数据
生成、API 调用、模型下载、SSH、GPU 命令）。那些仍是逐条独立审批门，需要用户在看到精确
命令后单独批准，属于下一个提示词的范围。

一、不可违反的边界

1. 先读取并遵守根目录 AGENTS.md/CLAUDE.md；若与本提示词冲突，以它们和用户最新指令为准。
2. 当前 HEAD 必须是 a3c748bdad1ce6fb7ec8a838d2f1f36da0bbae60（R2 分支基线）的后代，且必须
   包含提交 dfdb8dd（Task 1）、87a65ff（Task 2）、7153c26（Task 3）、1d60af2（Task 4）。
   保留用户已有修改，不得 reset、checkout 覆盖或清理无关内容。
3. 产品名是 RetailAgentOps，Python 包暂时仍是 veritool_rl；R2 不做全仓改名。
4. R2 只交付正式数据、评测流水线、冻结 split/evaluator 和 base 证据。QLoRA-SFT、adapter、
   candidate 训练、DPO、GRPO、在线 RL 属于 R3/R4，不得提前实施。
5. 本地 WSL 只运行 CPU 开发、测试、lint、类型检查、任务构建和轻量 smoke。严禁本地 GPU
   推理或训练；Task 5 的所有测试必须用 fake backend，不得为了测试下载或加载真实模型。
6. Task 8 范围内的任何 ssh gpu-4090/gpu-5090 命令、API 调用、模型下载、正式数据生成——
   本提示词范围完全不执行；只在 Task 7 里把这些命令原样写清楚，等待另外的批准。
7. 固定 BFCL 200 条 holdout、其答案、失败样例和 evaluator 继续独立只读，不能成为
   RetailOps train/dev、prompt/parser 调整或内部指标的输入。
8. 正式 RetailOps holdout 的任务真值、prompt、target_state、expected_calls、完整轨迹和
   逐任务失败只能位于 ignored sealed 路径；不得进入 Git、planning 文件、subagent prompt、
   公开报告或开发分析输入。
9. 不自动 push、发布或创建外部仓库。

二、固定上下文恢复顺序

开始任何实质工作前，主 agent 必须完整读取：

1. docs/CAREER_CONTEXT.md
2. docs/PRODUCT_BRIEF.md
3. docs/EXECUTION_PLAN.md
4. task_plan.md、findings.md、progress.md（重点看 2026-08-05 的 R2 Task 3/4 相关条目）
5. docs/PROJECT_LOG.md 最近记录（从 LOG-20260805-05 到最新一条）
6. SPEC.md
7. docs/superpowers/specs/2026-07-22-retailops-v1-r2-formal-data-and-base-design.md
8. docs/superpowers/plans/2026-07-22-retailops-v1-r2-formal-data-and-base.md
   （本提示词只覆盖其中的 Task 5/6/7 小节）
9. 本提示词文档

主 agent 自己读取适用技能的 SKILL.md；不得把技能解释委托给 subagent。复杂任务使用
planning-with-files；设计先使用 brainstorming，实施计划使用 writing-plans，批准后优先
使用 subagent-driven-development，完成前使用 verification-before-completion。

三、只读 preflight

先执行并报告，不修改文件：

pwd
git status --short --branch
git log -10 --oneline --decorate
git merge-base --is-ancestor a3c748bdad1ce6fb7ec8a838d2f1f36da0bbae60 HEAD
git merge-base --is-ancestor 1d60af2 HEAD
.venv/bin/python --version
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy
git diff --check
env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check

预期基线是 365 passed，Ruff/mypy/lock/diff 全绿。若现有工作树不干净，先判断修改归属并
保留；若基线失败，先做证据化诊断，不得把环境问题误写成产品缺陷。

四、已完成能力与本阶段可复用的已审计模式

以下能力已经实现、独立审查过、可以直接复用，不要重新发明：

- `src/veritool_rl/retail_ops/formal_tasks.py`：formal 任务生成、五类指纹。
- `src/veritool_rl/retail_ops/formal_manifests.py`、`formal_governance.py`：manifest/
  holdout 治理，`VerifiedFormalDataset`、`load_formal_split`、`authorize_formal_holdout`、
  `load_authorized_formal_holdout`。写入正式产物时的"路径穿越/symlink 防护 + staging 目录
  + 原子 rename + 失败回滚"模式定义在 `_validate_output_pair`/`_make_staging_dir`/
  `_publish_staging_dir`/`_remove_owned_dir`（`formal_manifests.py`）；
  `teacher_data.py` 里的 `_resolve_within`/`_make_staging_dir` 是同一模式的第二次复用。
  **Task 5 写 sealed evaluation 私有证据时必须复用这个模式**，不要重新用简单的字符串
  路径检查——Task 4 独立审查已经证明字符串检查会被 `..`/绝对路径/symlink 三种方式绕过。
- `src/veritool_rl/retail_ops/teacher_route.py`、`teacher_client.py`、`teacher_data.py`：
  provider-agnostic teacher 路由、client、采集/质量门/导出全链路，含 `retryable` 传输错误
  分类。
- `src/veritool_rl/agent/runner.py::run_episode`、`src/veritool_rl/data/generators.py::
  trajectory_to_sft_example`：已修复真实 OpenAI wire format bug（`tool_calls[].function.
  arguments` 必须是 JSON 字符串、需要 `id`/`tool_call_id`），已确认 Qwen3 真实
  chat_template 原生兼容两种形式。**Task 5 的 sealed evaluator 如果要接入真实
  teacher/模型多轮对话，直接复用这两个函数，不要重新实现消息拼装。**
- `src/veritool_rl/agent/qwen.py`：`QwenPolicy`/`GenerationBackend`/`TransformersBackend`，
  已支持 4-bit NF4、`enable_thinking=False`；Task 5 Step 5 要求兼容扩展它以支持固定
  revision/本地路径和硬件测量注入，不要破坏现有 R1/BFCL 调用点。

五、本阶段实现范围（Task 5 → Task 6 → Task 7）

完整定义见 `docs/superpowers/plans/2026-07-22-retailops-v1-r2-formal-data-and-base.md`
第 213-375 行；以下是关键约束摘要，出现冲突以计划原文为准：

**Task 5：sealed evaluator 与 dev base 证据**
- `load_verified_formal_dev(private_root, public_manifest, purpose="develop")` 只开
  `dev.jsonl`，核对私有 artifact SHA-256 与公开 manifest，再校验行数/类别/顺序/split/
  五指纹。
- `evaluate_formal_dev_base` 只接受该 loader 返回的记录、对应公开 dev manifest 和一个
  `GenerationBackend`；禁止 adapter 路径。
- `evaluate_authorized_holdout` 只接受已授权的 formal holdout，完整证据留私有，公开只出
  允许列表内的聚合报告。
- base 证据必须绑定：精确模型 repo/revision/文件哈希、commit/lock/bundle/manifest/
  parser/prompt/config 哈希、生成参数、物理 GPU index/UUID/名称、CUDA 映射、峰值显存、
  耗时、吞吐、token/延迟、artifact 哈希，且要能检测篡改。
- seed 固定 0、无 adapter、非思考模式、无采样、4-bit NF4、最多 5 步；两个模型复用同一套
  policy/parser/tool schema。
- CPU 测试全部用 fake backend/fake hardware provider，不得加载真实模型或访问 CUDA。

**Task 6：CLI 分派与 CPU 端到端验收**
- 保留全部 R1 命令原样可用；`build` 新增可选 `--input_dir`；R2 build 配置按 `pipeline`
  分派到 `formal_freeze`/`teacher_collect`/`train_export`；`evaluate` 按
  `pipeline=formal_dev_base` 分派；不新增 R2 release/serve 路径。
- 无 `pipeline` 字段的配置继续走现有 R1 精确字段路径；formal freeze/train export/fake
  base/R1/release/serve 过程中不得读取 `.env`。
- CPU 端到端流程：在临时目录里跑两次 formal freeze 并逐字节比较；用受控 pass/fallback
  比例跑一次 fake teacher attempt；导出 240 条轨迹；两个模型配置都过 fake backend；校验
  全部 evidence loader 和公开脱敏允许列表——**这个测试本身不得生成仓库的正式数据集**。
- 治理扫描：确认 `.env`、`/data/`、`/models/`、`/reports/retail_ops/` 仍被忽略；已提交的
  R2 配置不含密钥或私有路径；没有代码/配置引用 BFCL holdout 的 task/failure ID；纯净的
  `uv lock --check` 通过（不依赖用户级镜像别名）。

**Task 7：整体审查并准备外部审批命令清单**
- 对每个任务基准和整个分支（`a3c748b..HEAD`）生成审查包；Critical/Important 必须补
  失败测试修复并重审；Minor 记录留最终归纳。
- 从头跑一遍完整 CPU 门禁 + 临时目录里的 formal 重复构建哈希比较 + 仓库级 secret/BFCL/
  holdout 泄漏扫描。
- 产出 `docs/handoffs/<date>-r2-external-run-commands.md`：按 formal freeze、`.env`
  preflight、6 任务 API smoke、240 任务 API full run、只读 SSH 盘点、远端代码同步、每个
  锁定模型下载、每次单任务 GPU smoke、每次 60 任务 GPU dev run 分节写清楚**未执行**的
  精确命令。远端盘点小节要明确写"在盘点命令给出实际空闲物理 index/UUID 之前，不存在任何
  GPU 命令"；拿到盘点结果后再补上带物理身份、远端 cwd、预计时长、产物和哈希的具体命令，
  每条单独等待批准。
- Task 7 结束时只更新阶段记录为"CPU 实现完成、外部证据待批准"，不得把 R2 标为已完成。
  提交信息：`docs: prepare R2 external execution gates`。

关于 gpu-5090（本会话已经新增的第二远程环境，参见 CLAUDE.md 第4节和
LOG-20260805-01/02/03）：那里已经下载并逐文件 SHA256 校验过 Qwen3-1.7B/4B（ModelScope
提交哈希见 findings.md"gpu-5090 环境扩展与 ModelScope 重新锁定"小节），`uv` 环境
（dev+train extra）已验证 `torch` 能正确识别 RTX 5090。Task 7 的命令清单里涉及模型下载的
部分应该说明这一事实并询问用户是否要复用 gpu-5090 已有的模型文件，而不是假设需要重新下载；
但 teacher extra 需要在远端重新 `uv sync`（本地已含 Task 3/4 的 teacher extra，远端当时
还没有）。

六、subagent 协作规则

用户允许使用 subagent。批准实现计划后优先采用 subagent-driven-development：

- 每个计划任务只分配一个 implementer 写代码，禁止两个 agent 同时编辑相同文件或共享正式
  产物目录；
- 每个任务结束后先由独立 spec reviewer 只读核对批准规格，再由 quality reviewer 只读核对
  代码、测试、泄漏和范围——Task 1-4 的经验是：即使全部测试通过，独立审查仍然连续在
  Task 1/2/3/4 里找到真实 Important 级别问题，不要因为"测试全绿"就跳过这一步；
- reviewer 发现 Important/阻塞问题时，回到同一任务补失败测试和修复，再重审；
- subagent 不得自行运行 API、下载、GPU、正式 holdout 或外部发布；这些权限只由主 agent 在
  用户确认后执行；
- 所有 subagent 禁止打开、搜索、打印或总结 data/private/retail_ops/v1/；
- 主 agent 必须检查实际 diff、提交和测试输出，不能把 subagent 的成功声明当作证据；
- 每项实现使用 TDD：失败测试、确认正确失败、最小实现、focused tests、完整相关回归、
  commit、双阶段审查；
- 每两次重要查看后同步 findings.md，所有错误写入 task_plan.md，阶段证据持续写入
  progress.md，触发 CLAUDE.md 第7节记录条件时追加 docs/PROJECT_LOG.md 并在回复里报告
  LOG ID。

七、硬停止条件

出现以下任一情况立即停止对应资源消耗，保留证据并向用户报告，不得绕过：

- 任意 train/dev/holdout 的 task_id、family_id、内容哈希或派生指纹交叉；
- holdout prompt、真值、完整失败、failure ID 或轨迹进入 Git、公共报告、planning、
  subagent prompt 或开发分析；
- 根据 holdout 指标/失败修改 prompt、parser、数据、阈值、模型选择或 checkpoint；
- evaluator/replay 同输入不稳定，manifest/receipt/hash 不闭合或无法重建；
- base/candidate 不同 manifest、parser、budget、seed 或 evaluator 却尝试比较；
- 固定 BFCL holdout 或其失败样例进入 RetailOps 开发；
- 私有产物写入函数只做字符串路径检查而不做 `resolve()` 逃逸校验（这是 Task 4 已经暴露
  过的真实漏洞类别，Task 5 如果重复这个错误也算硬停止级问题）；
- 多文件产物写入不是"staging + 原子发布 + 失败回滚"，而是顺序写入导致半成品风险；
- 需要改变 240/60/120 配额、六类任务、release 门槛、模型家族、训练算法或大型基础设施；
- 任何 GPU/API/下载命令尚未得到用户对精确命令的确认——本提示词范围内这类命令一律不执行，
  只允许在 Task 7 的命令清单里原样写出。

八、每个任务和最终阶段的验收

每个任务至少运行其 focused tests、相关回归、`.venv/bin/ruff check .`、`.venv/bin/mypy`
和 `git diff --check`，并形成独立提交。不要自动 push。

Task 7 结束时必须在实际最终 HEAD 运行：

.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy
git diff --check
env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check
git status --short --branch

另外必须用自动化测试或可复核命令证明：

- Task 5：dev base 证据结构在 CPU fake backend 下能正确绑定全部治理哈希与硬件字段，且
  能检测篡改；sealed evaluator 在开发/未授权输入下正确拒绝，公开输出无 task/family ID。
- Task 6：R1 全部旧命令仍原样可跑；R2 六个新配置的 CLI 分派各自精确校验字段集合；两次
  formal freeze CPU 重复构建逐字节一致；`.env` 在 formal freeze/train export/fake base/
  R1/release/serve 路径中确实未被读取。
- Task 7：整分支审查无未解决 Critical/Important；`docs/handoffs/<date>-r2-external-run-
  commands.md` 存在且每条外部命令都标注为"未执行，等待批准"；`docs/EXECUTION_PLAN.md`
  的 R2 状态保持"当前"而不是"已完成"。
- 工作树干净，最终验收在最后一个提交上重跑，而不是引用早期 green 结果。

如果任何验收目标未满足，保持阶段状态为进行中或准确标记阻塞，不得为了"完成阶段"降低阈值、
隐去缺失结果或把计划目标写成实际结果。
```
