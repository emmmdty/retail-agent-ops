# 执行提示词：把 RetailAgentOps 推到 8.5+

## 身份与目标

你是一个新会话的 coding agent，接手一个**已基本完成**的零售工具 Agent 工程闭环项目。
项目当前评分约 7.5/10，你的任务是补齐三个最高 ROI 的缺口，推到 8.5+。

**项目仓库**：`/home/tjk/myProjects/internship-projects/retail-agent-ops`
**远程 GPU**：`ssh gpu-5090`，仓库路径 `/mnt/aidata/tongjiakai/retail-agent-ops`，模型根 `/mnt/aidata/tongjiakai/models`
**Python 环境**：`.venv/bin/`，用 `uv` 管理
**质量门**：`.venv/bin/pytest -q` / `.venv/bin/ruff check .` / `.venv/bin/ruff format --check` / `.venv/bin/mypy` / `git diff --check`

---

## 开工前必读（按顺序）

1. `docs/CAREER_CONTEXT.md` — 求职背景与项目组合约束
2. `docs/PRODUCT_BRIEF.md` — 产品说明与竞争边界
3. `docs/EXECUTION_PLAN.md` — 阶段状态唯一事实源
4. `task_plan.md` — 当前任务
5. `docs/RESUME_EVIDENCE.md` — 简历证据与不可写表述
6. `docs/INTERVIEW_PREP.md` — 面试材料
7. `docs/HOLDOUT_LEDGER.md` — 封存 holdout 观测台账
8. `docs/R8_DIAGNOSIS.md` — OOD 泛化差的根因诊断
9. `docs/R9_PHASE_B_RESULTS.md` — 数据多样性扩展实验结果
10. 当前 git 状态

---

## 当前状态摘要（2026-08-24）

### 已完成

- R0–R9 全部完成，12 周计划走完
- `build → evaluate → release → serve` 四接口在真实模型上跑通
- 封存 holdout 6 次观测，前 3 次 NO-GO → 第 4/5/6 次 GO
- 独立重建复验：SPEC §6 六条门禁全部满足
- OOD 泛化修复（R6）：措辞池训练增强，两份独立封存分片 1.0000 / 0.9833
- 跨域 flight_ops 基础设施已建（bundle/tools/policies/environment/tasks/build/evaluate/release 模块）
- 工具面扩展 v3（15 工具）和 v4（5 工具 / 12 场景）的 bundle 与任务模块
- R9 Phase B：5 工具 / 12 场景，OOD v2 0.8667、OOD v4 0.8917
- 1226 tests / Ruff / mypy 89 / CI 真跑通过
- 面试材料：简历 bullet（两版）、5 分钟讲解、11 条失败案例库、深挖问答

### 当前评分短板（7.5 → 8.5 的三个缺口）

| 缺口 | 当前状态 | 影响 |
|---|---|---|
| **OOD 未进发布门禁** | OOD 只是诊断量，不参与 GO/NO-GO 判定 | 面试时"你的门禁只看模板内"是硬伤 |
| **跨域未跑通评测** | flight_ops 基础设施存在但没有 teacher/train/eval 数据 | "只在一个域上验证"是硬伤 |
| **工具面退化曲线不完整** | v3/v4 bundle 存在，但没有 {3,6,9,12,15} 的 dev 读数 | "工具数增加会不会崩"没有答案 |

---

## 三个任务（按优先级顺序执行）

### 任务 1：OOD 评测集成进发布门禁（最高优先）

**目标**：把 OOD 评测从"诊断量"升级为"门禁项"，让发布判定同时覆盖模板内和模板外。

**为什么最高优先**：这是 7.5→8.5 的最大单点提升。面试时"你的门禁只看模板内 120 条"是致命弱点；集成 OOD 后可以说"门禁同时覆盖分布内和分布外"。

**已有的基础设施**：
- `src/veritool_rl/retail_ops/evaluate/evaluation.py` — 评测引擎
- `src/veritool_rl/retail_ops/release/formal_release.py` — 发布门禁，`GATE_IDS` v1.0/v1.1
- `src/veritool_rl/retail_ops/domain/ood_v2_tasks.py` — OOD v2 任务生成器
- `docs/R9_PHASE_B_RESULTS.md` — OOD v4 评测集（120 条，跨工具口径）
- 封存 holdout 台账 `docs/HOLDOUT_LEDGER.md`

**设计约束（不可违反）**：
1. **不改 v1.0/v1.1 的 `GATE_IDS` 字面值**——新门禁走 v1.2 新集合，v1.0/v1.1 逐字节冻结
2. **不消耗封存 holdout 观测**——OOD 门禁是独立的，用 dev/ood_dev 做迭代
3. **不改 parser / max_steps / verify_final_state**
4. **OOD 集合本身不能被过拟合**——必须有不封存的 ood_dev（迭代用）+ 封存的 ood_sealed（只观测一次）

**具体做法**：

#### 1a. 设计 OOD 门禁（纯 CPU，无 GPU）

在 `release/formal_release.py` 新增 `OOD_GATE_IDS` v1.2 集合：

```
新增门禁项（在原有 8 项之后追加，不改已有项）：
- ood_task_success_min: float = 0.70  # OOD 任务成功率下限
- ood_success_delta_min: float = 0.0  # 候选 OOD 必须不低于基座
```

关键设计：
- `FormalReleaseReport` 新增可选字段 `ood_report_id` / `ood_task_success`（取值为 None 时不入哈希，兼容旧证据）
- `decide_formal_release` 新增可选 `ood_evidence` 参数；传入时多算两个门禁，不传时跳过（向后兼容）
- 新增 `test_ood_gate_v12_*` 系列测试，覆盖：有 OOD 证据时触发、无 OOD 证据时跳过、阈值被锁、新旧门禁并存

#### 1b. 用现有 sft-008 的 OOD 读数验证门禁逻辑（纯 CPU）

用 `docs/R9_PHASE_B_RESULTS.md` 里 sft-003 的 OOD v2 读数（0.8667）做门禁逻辑的 dry-run：
- 构造 mock OOD evidence，喂给 `decide_formal_release`
- 验证 v1.0/v1.1 门禁不受影响
- 验证 v1.2 门禁正确判定

#### 1c. 在 ood_v2_tasks.py 上实现"只观测一次"的封存分片

- 新增 `ood_sealed_v2` 数据集（按 `sha256(措辞+盐)` 从 OOD v2 素材中切出，不与 ood_dev 重叠）
- 治理测试断言：ood_sealed 与 ood_dev 零重叠、与 train 零重叠
- 这个集合**只用于最终门禁验证**，不用于迭代

#### 1d. GPU 上跑基座和 sft-008 在 ood_sealed 上的读数

在 gpu-5090 上：
1. 零训练基座在 ood_sealed 上的评测
2. sft-008（合并形态）在 ood_sealed 上的评测
3. 用 v1.2 门禁做一次完整发布判定

**验收**：
- v1.0/v1.1 门禁行为不变（测试锁定）
- v1.2 门禁在有 OOD 证据时正确触发
- ood_sealed 上的读数合理（预期 0.75–0.90）
- 全量测试通过

**预计 GPU 时间**：2 次评测 × ~5min = ~10min

---

### 任务 2：跨域 flight_ops 完整评测（次高优先）

**目标**：在第二个领域（航班改签，英文）走通完整的 teacher → train → dev 评测，证明系统可移植。

**为什么重要**：当前所有结论在单一中文零售退款场景上成立。跨域验证补"只在一个域上验证"的短板。

**已有的基础设施**：
- `domains/flight_ops/v1/` — bundle/tools/policies/release.yaml
- `src/veritool_rl/flight_ops/` — 完整的 domain/build/evaluate/release 模块（环境、任务、政策规则、评测、发布）
- `tests/test_flight_ops_*.py` — 5 个测试文件（bundle/env/build/eval/release）
- `src/veritool_rl/flight_ops/build/teacher_data.py` — teacher 采集
- `src/veritool_rl/flight_ops/build/dev_sft_export.py` — SFT 数据导出

**flight_ops 域设计**（已冻结）：
- 工具 3 个：`get_reservation` / `rebook_flight` / `get_flight_schedule`
- 政策 2 条：`rebook_window_must_be_open`（起飞前 24h 内禁改签）+ `duplicate_rebook_forbidden`
- 任务类 6 个：`lookup_status` / `rebook_eligible` / `rebook_denied_window` / `rebook_denied_ownership` / `rebook_denied_duplicate` / `rebook_recovery`
- 英文场景

**具体做法**：

#### 2a. CPU 实现收口（纯 CPU）

检查 flight_ops 的 build/evaluate/release 是否完整可运行：
- 用 fake backend 跑一次 CPU 端到端（build → evaluate → release）
- 补齐缺失的配置文件（configs 下的 flight_ops YAML）
- 确保 `product_cli.py` 能通过 `--config` 分派到 flight_ops 流水线
- 补测试：flight_ops 的治理测试（flight_ops 不反向依赖 retail_ops、core 不依赖 flight_ops）

#### 2b. GPU：teacher 采集（~240 条，DeepSeek）

在 gpu-5090 上：
- 用 DeepSeek `deepseek-v4-flash` 为 flight_ops 采集 teacher 轨迹
- 质量门：通过率 ≥ 70%（与 retail_ops 同标准）
- 产物：`reports/flight_ops/v1/r10/teacher-001/`

**预计 GPU/API 时间**：~$0.05，~5 分钟

#### 2c. GPU：SFT 数据导出 + 训练（Qwen3-4B QLoRA）

在 gpu-5090 上：
- 从 teacher 轨迹导出 SFT 数据
- 训练一个 QLoRA 候选（r=16, alpha=32, 3 epoch）
- 产物：`reports/flight_ops/v1/r10/sft-001/`

**预计 GPU 时间**：训练 ~5min

#### 2d. GPU：dev 60 条配对评测（基座 vs 候选）

在 gpu-5090 上：
- 基座 dev 评测
- 候选 dev 评测
- 配对比较
- 产物：`reports/flight_ops/v1/r10/base-001/` 和 `dev-candidate-001/`

**预计 GPU 时间**：2 × ~5min = ~10min

#### 2e. 收口：证据链与门禁

- 验证 flight_ops 的证据链与 retail_ops 同构（report_id 自哈希 + 逐产物 SHA-256 + 配对可比性）
- 跑一次完整发布判定（GO/NO-GO）
- 不做封存 holdout（本轮不是发布结论，是跨域可移植性实证）

**验收**：
- flight_ops dev 评测完成，有配对读数
- 证据链自洽（report_id 自哈希通过）
- 发布判定输出 GO 或 NO-GO（有诚实结论即可）
- 全量测试通过

**预计 GPU 总时间**：~25min（teacher 5min + 训练 5min + 评测 10min + 门禁 5min）

---

### 任务 3：工具面退化曲线补全（第三个优先）

**目标**：补全 {3, 6, 9, 12, 15} 工具的 dev 读数，画出 tool selection 准确率随工具数的退化曲线。

**为什么重要**：面试时"工具数增加会不会崩"需要有数据回答。R8 诊断说退化曲线平坦（N=6/9/12/15 全部 0.45），但那个数据来自旧的评测集，需要在当前 v4 评测集上重新验证。

**已有的基础设施**：
- `domains/retail_ops/v3/` — 15 工具的 bundle（前 3 = v1，后 12 全订单/退款族）
- `src/veritool_rl/retail_ops/domain/v3_tasks.py` — v3 任务生成器
- `src/veritool_rl/retail_ops/domain/ood_v4_tasks.py` — OOD v4 评测集（120 条，跨工具口径）
- R9 Phase B 已有 5 工具的读数

**具体做法**：

#### 3a. 确认 v3 任务生成器可用（纯 CPU）

- 用 fake backend 跑一次 v3 的 build（生成任务集）
- 验证 15 工具的任务集生成正确
- 验证 {3, 6, 9, 12, 15} 断点可以正确切分（前 N 个工具的子集）

#### 3b. GPU：补齐缺失断点的 teacher + train + eval

已有的读数：
- 3 工具 = sft-008（复用 retail_ops v1 的候选）
- 5 工具 = sft-003（R9 Phase B）

需要新跑的：
- 6 工具：teacher + train + dev eval
- 9 工具：teacher + train + dev eval
- 12 工具：teacher + train + dev eval
- 15 工具：teacher + train + dev eval

每个断点：
1. teacher 采集（DeepSeek，~240 条）
2. SFT 导出 + 训练（Qwen3-4B QLoRA，~5min）
3. dev 评测（~5min）

**预计 GPU/API 时间**：4 断点 × (teacher $0.05 + 训练 5min + 评测 5min) ≈ $0.20 + 40min GPU

#### 3c. 画退化曲线

- 横轴：工具数 {3, 5, 6, 9, 12, 15}
- 纵轴：tool selection 准确率 + task_success
- 同时画 policy_violation 和 invalid_call_count
- 结论按「只在该工具面规模上成立」陈述

**验收**：
- 5 个断点的 dev 读数完整
- 退化曲线有图有数据
- 全量测试通过

---

## 执行顺序

```
任务 1（OOD 门禁，纯 CPU + 少量 GPU）
  ↓ 完成后
任务 2（flight_ops 跨域，CPU + GPU）
  ↓ 完成后
任务 3（工具面曲线，CPU + GPU）
  ↓ 全部完成后
更新简历证据 + 面试材料
```

任务 1 和任务 2 的 CPU 部分可以并行。GPU 部分串行（gpu-5090 只有一张卡）。

---

## 非目标（不可做）

- 不改发布门禁 v1.0/v1.1 的阈值或字段集
- 不改 parser / max_steps / verify_final_state
- 不消耗封存 holdout 观测（6 次已够，结论不是发布结论）
- 不创建 remote / push（用户单独授权）
- 不新增产品方向或业务领域（flight_ops 已批准，不加第三个域）
- 不做 DPO / GRPO / 在线 RL
- 不调 LoRA 超参（r=16/alpha=32/lr=2e-4/3epoch 全程固定）
- 不在简历上写"泛化已解决"——只能说"在特定条件下改善"
- 不改 `runner.SYSTEM_PROMPT`（改了会让已有 sealed 证据不可比）

---

## 授权状态

- GPU **是**（gpu-5090，每条命令先给精确清单）
- 商业 API **是**（DeepSeek teacher 采集）
- 封存 holdout 观测 **否**（本轮不消耗）
- 新依赖 **允许**（中国镜像）
- subagent **允许**

---

## 每条 GPU 命令的格式要求

执行前必须报告：

```
工作目录：/mnt/aidata/tongjiakai/retail-agent-ops
物理 GPU：gpu-5090 GPU 0（RTX 5090 32GB）
预计时长：X min
产物目录：reports/.../xxx/
具体命令：uv run python -m ... --config ...
```

等用户确认后才执行。

---

## 质量门（每轮改动后必须跑）

```bash
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy
git diff --check
```

---

## 完成后的交付物

1. **代码**：OOD 门禁 v1.2、flight_ops 完整评测链路、工具面退化曲线数据
2. **证据**：flight_ops dev 评测报告、工具面退化曲线图、OOD 门禁 dry-run 结果
3. **文档更新**：
   - `docs/RESUME_EVIDENCE.md` — 加入跨域和 OOD 门禁数据
   - `docs/INTERVIEW_PREP.md` — 加入跨域叙事
   - `docs/EXECUTION_PLAN.md` — 新增 R10 阶段状态
   - `task_plan.md` / `progress.md` / `findings.md` — 同步更新
4. **面试叙事升级**：从"单一域的发布判定系统"升级为"可移植的、OOD 感知的发布判定系统"

---

## 面试叙事目标（完成后的理想状态）

> 我做了一条 LLM 候选发布的可审计判定系统。它跑在两个完全不同的域上——
> 中文零售退款和英文航班改签——用同一套 core 模块、同一套证据链、同一套门禁结构。
> 门禁同时覆盖分布内和分布外：候选在模板内 120 条上 117/120，但在分布外
> 只有 0.8667——我把这个读数集成进了发布判定，而不是只当诊断量看。
> 工具面从 3 扩到 15，退化曲线是平坦的——工具数不是瓶颈，任务多样性才是。
> 我的门禁三次输出 NO-GO，其中一次候选 120/120 只因延迟被拒——
> 我没有改阈值，改的是部署形态。

---

## 关键文件索引

| 用途 | 文件 |
|---|---|
| 发布门禁 | `src/veritool_rl/retail_ops/release/formal_release.py` |
| OOD 任务生成 | `src/veritool_rl/retail_ops/domain/ood_v2_tasks.py`, `ood_v4_tasks.py` |
| flight_ops 域 | `src/veritool_rl/flight_ops/` (domain/build/evaluate/release) |
| flight_ops bundle | `domains/flight_ops/v1/` |
| v3 任务（15 工具） | `src/veritool_rl/retail_ops/domain/v3_tasks.py` |
| v4 任务（5 工具 12 场景） | `src/veritool_rl/retail_ops/domain/v4_tasks.py` |
| 封存 holdout 台账 | `docs/HOLDOUT_LEDGER.md` |
| 简历证据 | `docs/RESUME_EVIDENCE.md` |
| 面试材料 | `docs/INTERVIEW_PREP.md` |
| OOD 根因诊断 | `docs/R8_DIAGNOSIS.md` |
| R9 实验结果 | `docs/R9_PHASE_B_RESULTS.md` |
| CLAUDE.md | `CLAUDE.md`（工程协议与硬约束） |
| AGENTS.md | `AGENTS.md`（agent 入口） |
