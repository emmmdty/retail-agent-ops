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

- 当前阶段：**R4「失败驱动优化」**（用户于 2026-08-11 确认 R3 收口并切换阶段，
  LOG-20260811-07）。R3 四个 Task 全部完成，formal 轨道四接口已在真实模型上跑通，
  交付文档见 `docs/MODEL_CARD.md`、`docs/SYSTEM_CARD.md`、`docs/DEMO.md`、
  `docs/RESUME_EVIDENCE.md`。R4 执行提示词：`docs/handoffs/2026-08-11-r4-execution-prompt.md`
  （注意：该提示词第五节对方案一的成本估计已被 LOG-20260811-06 推翻，以后者为准）。
- **R4 第一轮已执行完毕并判负（LOG-20260811-09）**。方案是对多步家族重复采样
  （`train-export-002`，两类各 ×3，sft 240→400 行），候选 `sft-002` / `candidate-002`。
  结果：`refund_eligible` **0/10**（门槛 ≥7/10）未达成；`refund_recovery` 3/10→**5/10**；
  合计 43/60→45/60，仍低于 base 48/60。格式/安全三项保住（0 / 0 / 1.0）。
  **已按预设停止条件停止**——不改训练目标、不改 system prompt、不扩展算法。
- **被证伪的假设**：把决策点比例从 3:1 拉到 1:1，`refund_eligible` 变化**精确为 0**。
  "条件动作比例是该行为的主要成因"在该量级上不成立。残余嫌疑转向**请求措辞**：
  同样 ×3，祈使句家族 `refund_recovery` +2，而两个变体都以核实/检查开头的
  `refund_eligible` +0。**这是观察不是结论，未据此启动任何改动**。
- **R4 第二轮已启动**（用户批准设计
  `docs/superpowers/specs/2026-08-13-r4-round2-ablation-design.md`，执行提示词
  `docs/handoffs/2026-08-13-r4-round2-execution-prompt.md`）。本轮是**诊断性消融，
  不是发布候选生产**：三候选并列（不叠加）各只改一个变量，共同参照点 `sft-002`——
  A 改 `lora.target_modules`（加 MLP 三投影）、B 改训练数据（`train-export-003`，
  多步样本追加终局回复）、C 改 `runner.SYSTEM_PROMPT`。达标门槛与第一轮相同不下调；
  诊断读数是任一候选 `refund_eligible` ≥3/10 即"该层有信号"，三个均 0/10 则三类
  解释全部排除。**每个结论必须标注 n = 10 的统计限度**，3/10 与 5/10 的差异不足以排序。
- **执行顺序 A → B → C 是强制的**：`SYSTEM_PROMPT` 被 `base_evaluation.py:381` 与
  `sealed_evaluation.py:217` 哈希，且 `system_prompt_sha256` 在 dev 的 `PAIRING_FIELDS`
  内。C 一旦提交，A/B 就无法在旧 prompt 下评测且配对基线 `qwen3-4b-dev-base-001` 失效；
  又因 `_current_code_commit` 拒绝脏工作树，**C 的改动必须等 A/B 的 GPU 跑完才能进
  工作树**。C 另需重跑 base dev，其读数不可与 A/B 的 delta 直接相比，跨候选只能比
  `refund_eligible` 的绝对通过数。
- **被推翻的实现假设（2026-08-13）**：改 `runner.SYSTEM_PROMPT` 后重新导出**不会**换掉
  训练集的 system 消息。`trajectory_to_sft_example`（`core/generators.py:34`）读的是
  `trajectory.metadata["system_prompt"]`，而 teacher 证据是已持久化的轨迹（240 份全是
  旧值，来源 teacher 238 / internal_reference 2），且 `_require_evidence_binds_record`
  不比较该字段——会**静默**产出变量没生效的导出。因此导出侧新增两个**必填**配置键：
  `sft_terminal_response`（场景列表）与 `sft_system_prompt_sha256`（声明**期望哈希**
  而非布尔，使"常量忘了改"成为硬错误）。
- `verifier_reward` 已**三次**与主判据反向（R3 dev、封存 holdout、R4 dev）；
  本轮 `train_loss` 更低（0.3722→0.2198）而目标行为未改善。可优化的代理量全在改善、
  真实任务没有——这是本项目坚持"主判据是最终状态与政策 verifier"的实测依据。
- 发布结论（2026-08-11，封存 120 条 holdout，LOG-20260811-03）：**NO-GO / baseline**，
  唯一失败门禁 `success_delta`（−0.0333 < +0.05）。base task_success 0.7833（94/120）、
  candidate 0.7500（90/120）；候选 policy_violation 16→0、invalid_call 41→0、
  schema_valid_rate 0.7819→1.0000、p95 比值 1.0870。候选失败 100% 为
  `premature_final_response`，`refund_eligible` 20/20 全数失败。
  **holdout 已被观测一次**，其结果不得反馈进开发、调参、prompt/parser 或 checkpoint 选择；
  再次判定需另行决定是否消耗第二次。
- 已知结论：dev（LOG-20260807-09）与 holdout 一致——候选把格式/安全类失败清零，
  但需 ≥2 次工具调用的场景回退。两次评测中 `verifier_reward` 均与主判据反向，
  勿以奖励值代替最终状态判据。
- 失败根因的**精确口径**（LOG-20260811-06，只用 train/dev 得出）：66.7% 单次调用已复算成立
  但偏粗。(a) 动作长度与场景类别完全共变，"只重平衡长度不动类别"不存在；
  (b) 训练集中「输出自然语言」与「回合结束」100% 共变，多步类别贡献 0 文本字符；
  (c) 真正的竞争在「get_order 已返回 + 用户以核实/检查口吻要求退款」族内，比例
  **120:40 = 3:1** 偏向写文本；(d) dev 候选 **17/17 失败是同一行为——正确判定可退后向用户
  请求确认并停止**，不是能力丢失。模板/parser、工具 schema、verifier 三层均无缺陷。
- **改进方案的形状约束**：`parser.py` 把「文本+工具调用同时出现」判为
  `mixed_tool_call_content` 即非法调用，因此 assistant 工具调用消息必须保持 `content` 为空，
  任何"先声明再执行"的数据方案都会把 invalid_call 从 0 打回去。
- **配对可比性的连带代价**（LOG-20260811-06）：`code_commit`/`uv_lock_sha256`/
  `system_prompt_sha256` 均在 `SEALED_PAIRING_FIELDS` 内，因此**任何 R4 改进提交后，
  已有 sealed holdout base 证据不再可配对**——R4 之后的任何一次 release 判定 = 封存
  holdout 的第二次**完整**观测（base + candidate 两侧）。不得为规避这点放宽
  `require_comparable_sealed_runs`。dev 的 `PAIRING_FIELDS` 不含 `code_commit`，
  故改数据/代码不需要重跑 base dev；但它含 `system_prompt_sha256`。
- 服务（LOG-20260811-04）：按 NO-GO 回滚加载纯 base（`adapter_loaded=false`、
  `policy_id` 无 adapter 后缀），允许/拒绝/异常恢复三条流程均成功且轨迹可见，
  并发上限返回 503。演示成功不等于能力证明——同批次另一条 `refund_eligible` 仍失败。
- 仓库形态：唯一 `main` 分支、无 remote、对原 `veritool-rl` 工作区零依赖；
  `src/veritool_rl` 按 core / retail_ops(domain·build·evaluate·release·serve) /
  training / legacy 分层，目录职责与**四接口双轨完成度**见 `docs/REPO_MAP.md`。
- 不可逆约束：`SealedEvaluationReport` 的字段集合自 LOG-20260810-02 起冻结；
  两份 sealed 证据已于 2026-08-11 产出（`report_id` 是全字段自哈希），**再改即作废**。
- 资源约束：gpu-5090 的数据一律落 `/mnt/aidata`，不得写系统盘（LOG-20260811-02）。
  远端 `/tmp` 会被重启清空，不可用于承载跨故障的运行日志。
- 当前基线：665 tests passed，Ruff/mypy/uv lock 全部通过。
- 冻结契约提醒：`formal_tasks.py` 的 `assert_exact_quotas` 把 train/dev/holdout 每类别
  40/10/20 写成硬契约。新增任务需重新冻结数据集并改变 `dataset_version` 与 manifest 哈希，
  已有全部评测证据的可比性随之作废——这不是"多花点 API 钱"的事。
- 不自动推进 GPU 运行、模型下载、teacher API 采集或第二次 holdout 观测；每条外部命令单独请示。
