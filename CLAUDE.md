# CLAUDE.md — RetailAgentOps

本文件供 Claude Code 使用，也作为所有 coding agent 的共享工程协议。产品规格见 [`SPEC.md`](./SPEC.md)，阶段状态见 [`docs/EXECUTION_PLAN.md`](./docs/EXECUTION_PLAN.md)，接管步骤见 [`docs/HANDOFF.md`](./docs/HANDOFF.md)。

## 1. 开工前读取顺序

1. `docs/CAREER_CONTEXT.md`
2. `docs/PRODUCT_BRIEF.md`
3. `docs/EXECUTION_PLAN.md`
4. `task_plan.md`、`findings.md`、`progress.md`
5. `docs/PROJECT_LOG.md` 最近记录
6. 当前 git 状态和相关代码/测试

发现冲突或高影响信息缺失时，停止并询问用户，不得自行扩展方向。

## 2. 当前定位

RetailAgentOps 是零售工具 Agent 的单卡领域适配与发布流水线。它不是论文项目、通用 post-training 框架或 BFCL 刷分工程。Python 包暂保留 `veritool_rl`，不得在无独立计划时全仓重命名。

## 3. 协作分工

- 用户负责产品策略、阶段优先级、重大设计选择、资源授权和最终验收。
- Claude/Codex 可以实现全部代码、测试、配置和文档，但必须保留选择理由、失败边界和可运行证据。
- 重大产品、模型、数据、算法和部署选择先给至少两个方案，等待用户决定。
- 已确认计划内的低风险纵向切片应端到端完成，不停在接口或占位实现。
- 用户每周需要完成核心模块走读和脱稿复盘，文档应服务于解释而不是替代理解。

## 4. 环境与资源边界

- 本地：WSL/Linux，Python 3.11，`uv` 管理，只做 CPU 开发和轻量验证。
- 远程环境 1：`ssh gpu-4090`，只允许 `/data/TJK` 和 `/home/TJK`；uv 为 `/home/TJK/.local/bin/uv`，缓存 `UV_CACHE_DIR=/data/TJK/uv-cache`。该机上仅有原 VeriTool-RL 遗留目录 `/data/TJK/internship-projects/veritool-rl`，**不是本项目的远程工作区**；R2/R3 全部在远程环境 2 执行。若要启用本机，须先经确认建立独立目录，不得复用遗留目录。
- 远程环境 2：`ssh gpu-5090`，仓库路径 `/mnt/aidata/tongjiakai/retail-agent-ops`，只允许 `/mnt/aidata/tongjiakai` 和 `/home/tongjiakai`；该目录同时承载该用户其他项目，不得触碰 `retail-agent-ops` 之外的既有子目录；uv 为 `~/.local/bin/uv`。该服务器多人共用，执行前须核对 GPU 显存/进程占用与磁盘余量，模型下载优先选择满足复现要求的最小体积版本。
- 两套远程环境均为可用选项，同一任务只使用其中一个，执行前需在报告中明确当前使用的是哪一个。
- 模型、数据、checkpoint 和大运行产物不进 Git。
- 未经确认不得运行本地 GPU、远程长任务、批量评测或多 GPU 作业。
- 远程命令执行前必须报告命令、工作目录、物理 GPU、预计时长和产物。

## 5. 数据和结果边界

- 固定 BFCL 200 条 holdout 及失败不得进入开发、训练、调参、checkpoint 选择或 prompt/parser 修改。
- Base/SFT 163/200 与 167/200 只能表述为项目固定单轮 AST 子集结果，且不能声称稳定提升。
- 主结论必须来自工具执行、最终状态和政策 verifier；LLM judge 不是核心奖励或真值。
- 正式运行固定代码、依赖、数据、模型、模板、parser、seed、预算和 evaluator，并保存 manifest。
- 开发默认一个训练 seed；最终简历效果只做一次独立重建复验。
- 不因负结果降低发布门槛，不用计划目标冒充实际成绩。

## 6. 实现与测试协议

1. 在 `task_plan.md` 明确输入、输出、非目标、失败模式、影响文件和验收。
2. 行为变化先写失败测试并确认失败原因，再实现最小闭环。
3. 更新相关调用点、类型、配置和文档，不留无验证占位。
4. 每两次重要查看/检索后更新 `findings.md`；阶段进度更新 `progress.md`。
5. 每个正式运行使用新输出目录，不覆盖已有运行。
6. 运行 pytest、Ruff、mypy、配置解析和 `git diff --check`。

Review 必答：输入恶意/异常情况、状态变化、超时/重试/幂等、权限与泄漏、复杂度和成本、已有测试与未验证行为、可替代设计。

## 7. 记录协议

- `docs/EXECUTION_PLAN.md`：唯一阶段状态源。
- `task_plan.md`：当前任务清单，可在新任务开始时重写。
- `findings.md` / `progress.md`：当前任务发现和运行台账。
- `docs/PROJECT_LOG.md`：append-only 的长期档案，**只承载改变方法论选型或工程实践的事件**。
- `docs/adr/`：稳定、跨模块的架构决策。

**PROJECT_LOG.md 的门槛**（三条同时成立才写）：

1. 该结论会**改变后续做法**——方法、数据、评测、发布口径的选型，或一个被证伪后不再重试的假设；
2. 半年后重看，需要它才能解释"为什么现在是这样"；
3. 无法从代码、测试、git history、`findings.md`/`progress.md` 复原。

该写：方法论选型及其被推翻（如某类改进方案判负并据此停止）、正式 GPU/长任务运行的口径与结果、go/no-go、数据集或契约冻结、资源与边界约束变化。

**不该写**：代码 bug 及其修复、测试增删、重构、配置微调、依赖升级、文档调整、常规成功的执行步骤、单条命令的输出——这些由 git history 和 `findings.md`/`progress.md` 承载，进不了长期档案。

宁可漏记，不可灌水。不确定是否达标时，在对话里讲清楚即可，不写条目；不要按"写了更安全"行事。触发时先追加，再在最终答复中报告 LOG ID。不得改写历史条目。

## 8. 常用命令

```bash
env -u UV_INDEX_URL uv sync --extra dev --frozen
env -u UV_INDEX_URL uv sync --project tools/bfcl_eval --frozen
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy
git diff --check
```

`data/external_repos/gorilla` 是 ignored 的自包含 BFCL checkout（固定 commit `6ea5797…`，保留其自身 `.git` 供 commit 与工作树校验）。若缺失，按 `data/external_repos/BFCL_PIN.txt` 重建，不得用浮动网络版本替代。仓库目录职责见 `docs/REPO_MAP.md`。

## 9. 当前状态

**阶段状态的唯一事实源是 `docs/EXECUTION_PLAN.md`；封存 holdout 观测次数的唯一事实源是
`docs/HOLDOUT_LEDGER.md`。本节只做摘要，两者冲突时以它们为准。**

- **R0–R6 全部已完成**（R5 于 2026-08-16 收口，R6 泛化修复于 2026-08-17 收口）。12 周计划走完，
  `build → evaluate → release → serve` 四接口在真实模型上跑通，
  对外交付物见 `README.md` / `README.en.md` / `docs/INTERVIEW_PREP.md`。
- 当前基线：**1093 tests passed**（作者环境）／干净 clone 上 1047 passed、44 skipped、**0 failed**；
  `ruff check`、**`ruff format --check`**、`mypy`(86)、
  `uv lock --check`、`git diff --check`、`scripts/ci/audit_public_release.py` 全部通过。

### 结论摘要（引用时必须带条件）

- **封存 holdout 的观测次数以 `docs/HOLDOUT_LEDGER.md` 为准**：前三次 `NO-GO`（第一次输在 `success_delta` −0.0333，
  第二、三次候选做到 120/120、`success_delta` +0.1417 但输在延迟），
  **第四次 `GO` / candidate**——候选是同一份权重的**合并部署形态**，p95 比值 2.03 → 1.13。
  **GO 归因于部署形态，不是模型**：未合并形态对同一 base 重算仍 FAIL 1.9219。
  阈值一个字未改（`test_release_config_does_not_touch_the_gates`）。
  **第五次（2026-08-17）用 R6 的最终候选 `sft-008` 拿到 GO，两套口径都是**（117/120、
  政策违规 11→2、`p95_latency_ratio` 1.0203）。**观测次数不再是硬约束**（用户 2026-08-17），但**结果永远不得反馈进开发、调参、
  候选选择或 prompt/parser 修改**——那条限制来自统计学，不来自资源稀缺。
- **引用那个 GO 必须同时给出分布外读数**（有测试强制）：同一候选在模板外 60 条上
  只有 0.5833、`expression_ood` 0/20 且**比零训练基座差**。**120/120 不是泛化**——
  冻结 holdout 与训练集共用同一批 12 句请求模板。这次 SFT 是**用表面形式鲁棒性
  换来了任务结构与安全性**（LOG-20260816-01）。
- **SPEC §6 六条门禁已全部满足**；第 6 条「独立重建复验」于 R5 完成
  （LOG-20260816-05，`docs/REBUILD_VERIFICATION.md`）：换 seed 重训两次，
  58/60 与 60/60，都显著高于零训练 base 的 54/60。
  **但同时发现训练不可逐位复现**——同 seed 重跑产出逐位不同的 adapter，
  代码/数据/配置全同。**dev 读数一律表述为「58–60/60，三次同配置运行」，不写单点 60/60。**
  「六条满足」**不等于「可以上线」**：复验证明流程能重现结果，不证明结果能泛化。
- **LoRA 容量必须与模型规模匹配，不存在"越大越好"**（LOG-20260814-05）。
  4B：零训练 54/60、attention-only 55/60、全 linear **60/60**；
  1.7B：零训练 44/60、attention-only **58/60**、全 linear 45/60（**方向相反**，
  15 条失败全部是"该拒绝却没拒绝"）。**数据配比与容量耦合**，不是两个独立旋钮。
- **提示词干预是规模依赖的**：新 prompt 使 4B 的 `refund_eligible` 5/10→9/10，
  对 1.7B **完全无效**（0/10）。"prompt 与训练分工"的结论**只在 4B 成立**。
- **`verifier_reward` 已四次与主判据反向**，现已降级为诊断量。
  主判据只有最终状态与政策 verifier。
- BFCL 163/200 与 167/200 属 legacy 轨道的**项目自划固定单轮 AST 子集**，
  差值置信区间跨 0，不得声称稳定提升，不是官方全量或排行榜成绩。

- **最终候选的独立重建复验（LOG-20260817-07）**：`sft-008` 换 seed 重训，
  判据 A/B 事先写定并成立 → **复现**（dev 60/60、分布外封存分片 0.9833 vs 原候选 0.9833）。
  **但这一轮真正的产出是三条修正**：①R6「那 2 次政策违规是措辞增强的确定代价」
  **归因不成立**——原论据的两个候选共用一个训练 seed；②代价更大且集中在
  `refund_denied_window` 一条规则上（dev 0 次 → 封存 120 上 **7** 次）；
  ③**dev 与封存集把这两次运行排成了相反的顺序**。
  头条数字一律改区间：dev **58–60/60**、封存 120 **113–117/120**、
  分布外封存分片 **0.9833–1.0000（两份独立素材）**。
  第六次封存观测同样 `GO`，但 `success_delta_ci_lower` 只有 **+0.0083**。
- **R6 泛化修复（LOG-20260817-01）**：诊断出「表面形式 → 动作」的捷径后，
  用 LLM 措辞池做训练增强。**封存分片只观测一次**：零训练基座 0.7167、
  旧候选 0.7333、**新候选 `sft-008` 1.0000**；**独立迁移检查**（作者手写的 OOD v1，
  从未用于选择）`expression_ood` **0.00 → 1.00**、总分 0.5833 → 0.8667。
  **代价必须一起说**：dev 新增 2 次政策违规、OOD v1 的 `scenario_ood` 0.75 → 0.60
  （`partial_refund` 1.00 → 0.00）——模型更倾向执行，两处同一机制。
  **R6 那一轮的 OOD 结论不依赖封存 holdout；它随后才被单独观测。**
- **评测集的新纪律（ADR 0005）**：判断泛化的评测集必须①素材按哈希切分不由人挑、
  ②训练与评测素材逐条互斥且代码断言、③留一个只观测一次的分片、
  ④素材经语义回环校验。手写的 OOD v1 已退出选择流程，只作独立迁移检查。

### 硬约束提醒

- **冻结契约**：`GATE_IDS` v1.0 逐字节冻结（就地增删会让磁盘上全部 release 报告无法加载，
  新口径走 v1.1）；`SealedEvaluationReport` v1.0/v1.1 字段集；dev `PAIRING_FIELDS`、
  `SEALED_PAIRING_FIELDS`；`formal_tasks.assert_exact_quotas` 的 40/10/20 与
  `dataset_version`——改它会让已有全部评测证据的可比性作废，不是"多花点 API 钱"的事。
- **形状约束**：`parser.py` 把「文本 + 工具调用同时出现」判为 `mixed_tool_call_content`
  即非法调用，因此 assistant 工具调用消息必须保持 `content` 为空；任何"先声明再执行"
  的数据方案都会把 `invalid_call` 从 0 打回去。
- **导出侧必填键**：`sft_terminal_response` 与 `sft_system_prompt_sha256`（声明**期望哈希**
  而非布尔）。改 `runner.SYSTEM_PROMPT` 后重新导出**不会**换掉训练集的 system 消息——
  `trajectory_to_sft_example` 读的是已持久化轨迹的 `metadata["system_prompt"]`。
- **运行环境溯源**：`uv_lock_sha256` 哈希的是仓库里的 `uv.lock` **文件**，不是实际装了什么包。
  运行证据另有 `inference_engine` 与 `runtime_env_sha256`；**缺失读作"未记录"，
  不是 "transformers"**。往运行证据加字段一律用"取值为 None 即不入哈希"，
  并登记进 `RUNTIME_PROVENANCE_FIELDS`。
- **资源约束**：gpu-5090 的数据一律落 `/mnt/aidata`，不得写系统盘；远端 `/tmp` 会被重启清空；
  该机**没有 C 编译器**，且在此机引入任何第二个 Python 版本的深度学习环境，
  必须先隔离其 `TRITON_CACHE_DIR`（否则会覆盖项目自己的 triton 缓存，
  错误信息完全不指向真正原因，LOG-20260816-02）。
- 仓库形态：唯一 `main` 分支、**无 remote**（CI workflow 已提交但从未真正跑过，
  任何文档不得声称它跑绿了）、对原 `veritool-rl` 工作区零依赖。
- 不自动推进 GPU 运行、模型下载、teacher API 采集或第五次 holdout 观测；
  每条外部命令单独请示。**推送公开仓库是用户的动作。**
