# 交接：质量收口第二轮——v1.3 绝对门 + 方差治理 + 全面审计（执行提示词）

**日期**：2026-09-04
**性质**：R0–R10 全部完成后的质量收口第二轮。本轮任务清单由 2026-09-04 的根因分析
（`docs/PITFALLS.md`）与一次「面试官视角审查」派生，用户已批准按本文档执行。
**执行者**：新窗口的 coding agent；**允许使用 subagent**（探索、审查、可并行的独立工作），
subagent 的产出必须抽查验证后再采信。

---

## 0. 一句话背景

发布候选 `sft-008`（合并部署形态）的工程闭环与证据链已完整，但面试官审查发现
指标体系有四项**可解决**的缺口：绝对违规下界缺失、统计功效无门、v1.2 OOD 门从未
真跑过发布判定、训练不可复现带来的违规方差。本轮把这四项做掉，补一轮全面审计
与测试补齐，并把「是否迁移到更宽工具面」按**简历项目质量**产出分析供用户决策。

## 1. 先读这些（按顺序）

1. `AGENTS.md`（不可违反边界 + 固定流程）
2. `docs/CAREER_CONTEXT.md`、`docs/PRODUCT_BRIEF.md`、`docs/EXECUTION_PLAN.md`
3. **`docs/PITFALLS.md`（本轮直接输入：四层根因 + 24 条踩坑 + 8 条已证伪方向）**
4. `task_plan.md`、`findings.md`、`progress.md` 最新三节
5. `docs/PROJECT_LOG.md` 最后一条（LOG-20260827-01）
6. `docs/POLICY_BOUNDARY.md`（R7 判负机制 + 探针）、`docs/R9_PHASE_B_RESULTS.md`
7. 在途任务的两份交接：`docs/handoffs/2026-08-27-r10-degradation-rerun.md`（退化曲线重跑，
   **含故障手册 §5.1–5.8**）、`docs/handoffs/2026-08-23-r9-phase-b-round4-execution-prompt.md`
   （rtc 第四轮，判读规则已预注册）

## 2. 当前状态快照（不要重诊断，从这里出发）

- **发布候选**：`sft-008`（合并部署形态），读数全部来自 v1/v2 口径：封存 120 上
  113–117/120、政策违规 2–7 次（同配置两次运行，全部 `refund_denied_window`）、
  GO 的 `success_delta_ci_lower` = +0.0083。引用 GO 必须成对给出分布外 0.5833/0/20
  读数（有测试强制）。
- **在途**：退化曲线重跑 GPU 阶段被 gpu-5090 驱动卡死中断（2026-08-27 15:38，
  `nvidia-smi` D 状态）。小样本 teacher 采集 5 断点已全过门禁（0.8333–0.9167），
  tc=3 已训练，base 首条真读数已产出（success=0.5000 / tool_acc=0.7273 /
  distractor=0.2000 / infra_err=0）。恢复后从训练阶段续跑，teacher 不再计费。
- **本轮五项审查结论的可解性**（详见对应用户决策门）：
  | # | 缺口 | 可解性 | 本轮动作 |
  |---|---|---|---|
  | 1 | 违规门只有 delta 无绝对下界 | 能 | Phase B（v1.3 加门） |
  | 2 | 成功率含代理成分（reason 4 选 1） | 部分 | Phase C4 只做提案（评测语义变更需用户决策） |
  | 3 | 门禁无统计功效要求 | 能 | Phase B（最小效应宽度门） |
  | 4 | v1.2 OOD 门没真跑过发布判定 | 能（最便宜） | Phase D4（新措辞池封存 + 一次性判定） |
  | 5 | 训练不可复现 + 违规方差 | 半能 | Phase C1/C2（方差治理）+ Phase D2/D3（根治需用户决策） |

## 3. 总目标与非目标

**总目标**：把可解决的指标缺口落地，产出一轮含绝对安全门与 OOD 门的发布判定读数，
完成全面审计与测试补齐，并交付宽工具面迁移的质量分析。

**非目标**：
- 不产出论文；不做 GRPO/在线 RL；
- 不改 v1/v2 冻结契约与既有证据（v1.3 只加门不删门）；
- 不重试 `docs/PITFALLS.md` 第三节的 8 条已证伪方向；
- 不为了让数字好看改任务、关守卫或挑读数；
- 不改写任何历史文档结论（append-only）；
- 阶段状态变更与 PROJECT_LOG 只按 AGENTS.md 门槛执行。

## 4. 授权状态

- **subagent**：允许。建议用法：code review 用三个 persona（见 §7）；独立的小任务
  （测试补齐、文档核对）可并行派发；**结果必须抽查**——subagent 声称的读数/结论
  要么自己复核，要么用测试验证。
- **GPU / 商业 API**：本轮任务方向已获用户批准，但**每条远程命令执行前必须给出
  精确清单**（工作目录、物理 GPU、预计时长、产物）等待用户确认；teacher 采集记 token
  与费用。
- **封存 holdout 观测**：不限次数（用户 2026-08-17），但**结果永远不得反馈进开发**。
  本轮只在 Phase D4 消耗（v1.3 发布判定），此前所有迭代只允许用可迭代面
  （dev 60、`ood_dev`、政策边界探针、Phase C3 的二维面）。
- **需要单独用户决策才能继续的**（遇到即停，见 §8）：
  DPO 启动、难度分层重冻结、评测语义变更（max_steps / reason）、宽工具面迁移、
  v1.3 阈值数值、gpu-5090 恢复方式。

---

## 5. 任务分解（按执行顺序）

### Phase A：审计基线与高严重度缺陷修复（纯 CPU）

**A1. 全面 code review（subagent 三 persona，规程见 §7）**，范围：
`src/veritool_rl/` 全部、`scripts/`、`configs/`、`tests/` 抽样。

**A2. 修复 `findings.md`「评测脚本 Bug 审查报告」中的高/中严重度项**（该报告已存在，
不要重新审计一遍，直接修）：

| findings # | 问题 | 严重度 |
|---|---|---|
| #3 | 评测路径无超时（`run_episode`/`execute_formal_records`），模型卡死会锁死整批 GPU 评测 | 高 |
| #1/#2 | OOD config 的 `dataset_version` Literal 不完整 + CLI 不传该字段，`config_sha256` 嵌入错误默认值 | 中 |
| #5 | `evaluate_ood` 不校验 config↔manifest 的 `dataset_version` 一致性 | 中 |
| #4/#13 | `environment.py` 的 `descriptions` 硬编码 5 个工具名，v3+`perturb_schema` 会 KeyError | 中 |

低严重度项（#6/#7/#8/#9/#10/#11/#12）逐条给出「修复 / 不修及理由」的归宿，不许静默。

**验收**：修复全部带 TDD（先红后绿）；`#3` 的超时要有「慢策略被超时终止」的测试；
低严重度项归宿表写入 `findings.md` 追加节。

### Phase B：v1.3 发布门禁——绝对违规下界 + 最小效应宽度（纯 CPU，TDD）

**B1. schema 扩展**：`gate_schema_version` 加 `"1.3"`，新增两条门（沿用 `invalid_call_count_max:
Literal[0]` 的既有模式）：
- `policy_violation_count_max`（建议 `Literal[0]`）——绝对违规下界；
- `success_delta_ci_lower_min`（建议 `+0.02`）——最小效应宽度，堵 +0.0083 贴 0 过门。

**两个阈值数值是用户决策门**：先出提案（含「当前候选按 v1.3 重算的预期结果」），确认后冻结。

**B2. 纪律（全部有既有模式可抄）**：
- 加门不删门：v1.0/v1.1/v1.2 判定语义与 `GATE_IDS` 逐字节不动，旧报告仍可加载；
- `release.yaml` 进 `bundle_sha256` 的机制不动，阈值只进 YAML；
- 阈值锁测试（照 `test_thresholds_come_from_the_untouched_release_yaml`）、
  七份既有证据 `report_id` 复算逐位不变的回归测试、
  安全关键断言的突变验证（去掉断言测试必须红）。

**B3. 诊断性重算**：用既有 v1/v1.1 证据在 v1.3 口径重算当前候选，**预期 NO-GO**
（违规 2–7 > 0、ci_lower +0.0083 < +0.02）。**这是绝对门生效的证据，不是失败**；
这次重算是诊断，真正的发布判定在 Phase D4 一次性进行。
历史 GO（v1.0/v1.1 口径）保持原样不改写，两套判定并列陈述。

**验收**：新门各有正/反例测试 + 突变验证；v1.3 重算报告落盘并写入 `findings.md`。

### Phase C：方差治理与二维迭代面

**C1. 训练随机源固定（纯 CPU 实现）**：排查 `training/sft.py` 的随机性来源
（dataloader shuffle、dropout、初始化、CUDA 非确定性算子），在不过度牺牲速度的
前提下固定；产出「可消 / 不可消及原因」清单（GPU 原子操作的非确定性大概率不可消，
诚实记录）。

**C2. GPU 验证（每条命令先给清单）**：同配置同 seed 训练两次，adapter SHA-256 对比。
得到「逐位复现」或「方差收窄到 X」的实测结论，替换掉现在「同 seed 逐位不同」的
无边界表述。

**C3. 二维迭代面（CPU 生成 + 一次 GPU 评测读数）**：政策边界探针（15 个 offset）×
措辞池交叉网格——探针任务的用户话术改用措辞池的不同分片，使迭代面同时看见
边界型退化与措辞型退化。这是对 R7「同源评测面高估修复收益」失败机制的根治。
生成器复用探针 + 措辞池两条既有链路，不新造机制。

**C4. 提案（不实现）**：`max_steps` 4→6 放宽与 `reason` 语义等价判定的影响分析
（都是评测语义变更：动冻结任务集/verifier → 历史可比性断裂 → 新评测版本全价）。
写成决策文档，停，等用户裁决。

### Phase D：违规根治候选 + 一次性 v1.3 发布判定

**D1. rtc 第四轮**（预注册已存在，照 `docs/handoffs/2026-08-23-r9-phase-b-round4-execution-prompt.md`
执行）：方案甲单变量（cancel 类 family 20→30–35），判读规则一个字不改；
已证伪方向（调 oversample 权重、统一调用顺序）不得重试。

**D2. DPO 入口门证据包（只备料，不训练）**：整理失败类别稳定性证据
（`refund_denied_window`、探针 `offset −14`）、可形成的偏好对形状（同一状态
拒绝 vs 执行）、SFT 停滞证据（R7 判负 + Phase C3 二维面读数），对照执行计划
R4 的 DPO 入口条件写一份提案 → **停，等用户决策**。

**D3.（仅当用户批准）DPO 训练**：只允许用可迭代面迭代；判读规则先写定并提交。

**D4. 一次性 v1.3 发布判定**：
- 生成新措辞池 `phrasing-bank-004`（DeepSeek，费用记 token/金额），按哈希切分出
  可迭代分片与**封存分片**（照 `docs/OOD_SEALED_LEDGER.md` 规则 4：新测量 = 新池）；
- 所有代码冻结并提交之后，一次性跑：封存分片 OOD + 封存 holdout + v1.3 release
  （base + candidate），判读规则先写定并提交；
- 判定后：`HOLDOUT_LEDGER.md` 追加、`EXECUTION_PLAN.md` 追加记录、`findings.md`
  记读数、`docs/PITFALLS.md` 追加本轮新踩坑（若有）；
- **无论结果如何不重跑、不换素材再试**；结果不得反馈进任何后续开发。

### Phase E：宽工具面迁移分析（纯 CPU，**按简历项目质量定**）

**E1. 对照分析**（用户原话：「是否迁移到更宽工作面按照简历项目质量定」）：
- 现状 A：v1 口径发布闭环（sft-008，2-3 工具/6 场景）+ v3（15 工具）与 v4
  （5 工具/12 场景）探索性结论；
- 选项 B：rtc 修好后把发布候选迁到 v4 口径（5 工具/12 场景）重走一次正式冻结；
- 选项 C：迁到 v3 口径（15 工具，退化曲线真读数出来之后）。
- 评估维度：MLOps/评测岗叙事强度、证据链深度（封存集、配对、OOD 门是否仍成立）、
  面试可解释性、全部成本（新 dataset_version 冻结、teacher 采集、新封存集、
  全部证据链重做）、风险（历史读数不可比）。
- **产出书面建议并停**，由用户决策。**不得自行迁移、不得提前动 v3/v4 冻结契约。**

**E2. 退化曲线重跑（在途任务续接）**：按 `docs/handoffs/2026-08-27-r10-degradation-rerun.md`
从训练阶段续跑（gpu-5090 恢复后），故障定位照其 §5。收口时同步
`RESUME_EVIDENCE.md` / `INTERVIEW_PREP.md` 里写着「读数作废」的段落。

### Phase F：测试补齐与收口

**F1. 按 `findings.md`「7.2 测试覆盖盲区审查」补齐测试**（该清单已存在，按优先级做，
不重新盘点）。优先级建议：
1. 高价值行为路径：runner 非成功终止分支、parser 空响应/Pydantic 校验失败、
   环境未知工具名拒绝、v3/v4 场景的环境层执行；
2. 服务与安全：401 鉴权失败、`episode_timeout_s` 超时终止、空任务列表；
3. 边界条件：`max_steps=0/1`、连续 unknown_tool、嵌套 arguments、`idempotency_key` 重复；
4. 治理测试自身的 bug（`_collected_test_count` 脆弱性、`_MUST_BE_ALLOWED` 依赖
   台账当前值、故障矩阵 `>=20` 任意阈值、e2e 硬编码期望值）——逐条修复或写明保留理由。

**F2. 治理同步**：测试数变化必须同步 `README.md` / `README.en.md` / `CLAUDE.md` /
`docs/RESUME_EVIDENCE.md`（有治理测试检查），并按 Task C 模式重测干净 clone 实数。

**F3. 文档收口**：`PITFALLS.md` 追加、`progress.md`、`EXECUTION_PLAN.md`；
PROJECT_LOG 仅当出现方法论级事件（v1.3 门禁语义上线、方差治理结论、发布判定）时追加。

---

## 6. 测试岗位主管职责（用户点名，全轮生效）

本窗口在写测试时**扮演严苛的测试岗位主管**，对每个新功能执行：

1. **先测试计划后实现**：每个功能动手前列出正例 / 反例 / 边界 / 突变四类用例清单
   （写进 `task_plan.md` 对应任务），实现完成后逐条对照；
2. **安全关键断言必须突变验证**：注释掉被测的保护行，对应测试必须变红——
   这是仓库既有惯例（R2/R3/R4 多处先例），不是新要求；
3. **反例模式**：「种一个违规必须被抓到」——每个新的治理/门禁检查都要有一个
   故意违规且必须被拦住的负例测试；
4. **阈值锁**：v1.3 两个新阈值要有 YAML 来源锁测试，改阈值必须让测试红；
5. **向后兼容**：七份既有 release 证据在 v1.3 代码上加载与 `report_id` 复算不变的回归；
6. **不许做的事**：为让测试通过而弱化断言；删覆盖真实行为的测试凑数；
   写只在自己语料上验证过的检测器（仓库在 R7 抓过这个缺陷：声称的机制不是部署的机制）；
7. **行为变更先写失败测试**，再实现最小闭环（AGENTS.md 固定流程第 3 条）。

## 7. 全面审计与 code review 规程（用户点名）

- **范围**：`src/veritool_rl/`（core / retail_ops / flight_ops / training / legacy 边界）、
  `scripts/`、`configs/`、`.github/workflows/`、`tests/` 抽样。
- **方法**：派三个独立 subagent persona，各出一份书面意见：
  1. **评测基建工程师**：指标定义、统计方法（bootstrap、配对、CI）、fail-closed 完整性；
  2. **发布工程师（SRE）**：门禁演进、回滚路径、证据链可复算、服务可靠性与超时；
  3. **对抗审查**：绕过路径（怎么让不合格候选拿 GO）、篡改检测、泄漏路径、
     治理测试的盲区。
- **分级与归宿**：Critical / Important / Minor；Critical 与 Important 必须修复，
  修不了的写明理由与替代方案（「修实质问题，不加约束项」）；Minor 记录到 `findings.md`。
- **与既有审查的关系**：R4.5 的 13 条评审与 `findings.md` 已有两份审查**不重做**，
  只验证其闭环状态（修复是否仍有效、是否被后续改动破坏）。
- 每轮审查后**修复 → scoped re-review**（照 R2/R4.5 的流程），不得只修不复审。

## 8. 用户决策门清单（遇到即停，给出选项与建议）

| # | 决策 | 触发点 |
|---|---|---|
| 1 | v1.3 两个阈值数值（建议 0 与 +0.02） | Phase B 冻结前 |
| 2 | gpu-5090 恢复方式（`--gpu-reset` 或重启整机，影响其他用户） | Phase C2 / E2 前 |
| 3 | max_steps 放宽 / reason 语义化（评测语义变更） | Phase C4 |
| 4 | DPO 是否启动 | Phase D2 证据包后 |
| 5 | 难度分层重冻结（新 dataset_version） | 若 Phase D 判定后违规仍未归零且用户要求根治 |
| 6 | 宽工具面迁移（按简历质量分析） | Phase E1 书面建议后 |
| 7 | 每一条 GPU / 商业 API 命令 | 执行前 |

## 9. 固定流程与验收命令

- 每个任务开工前在 `task_plan.md` 写输入/输出/非目标/影响文件/验收命令；
- 每两次重要查看/检索后把发现写进 `findings.md`；
- 文档、注释默认简体中文；Python 统一用 `uv`；
- 最终每轮收口必须全绿：

```bash
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy
env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check
git diff --check
.venv/bin/python scripts/ci/verify_qualification_chain.py
.venv/bin/python scripts/ci/audit_public_release.py
```

## 10. 已证伪方向（不得重复，摘要见 `docs/PITFALLS.md` 第三节）

调 rtc oversample 权重；统一调用顺序假设；「违规是措辞增强的确定代价」；
LoRA 容量越大越好；提示词干预普适；「去 oversample 消违规」；加数据量修 OOD；
切分难度均匀假设。

## 11. 故障手册指针

- gpu-5090 驱动卡死（`nvidia-smi` D 状态）与续跑方法：`docs/handoffs/2026-08-27-r10-degradation-rerun.md` §5.5；
- preflight 自检门（自变量生效性、gold 可解性）：同上 §5.1–5.2；
- cpolar 隧道 host key 变更：`task_plan.md` Errors 表（核对指纹后 `ssh-keyscan -H` 追加，**不关** `StrictHostKeyChecking`）；
- Triton JIT 缺系统编译器：`TORCH_DISABLE_NATIVE_JIT=1`；
- teacher 无响应：先查 client 超时设置（Phase A 修复后应有显式超时）。
