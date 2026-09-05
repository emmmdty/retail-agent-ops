# R9 Phase B 结果存档：数据多样性扩展实验

**日期**：2026-08-22（三轮迭代完成）
**状态**：探索性结论收口；不用于发布判定，不消耗封存 holdout
**前置文档**：`docs/R9_SPEC.md`、`docs/R8_DIAGNOSIS.md`
**日志链**：LOG-20260822-01 → 02 → 03 → 04 → 05

---

## 1. 实验设计回顾

Phase B 检验 R8 诊断的主因假设：**数据多样性不足导致 OOD 泛化差**。

| 维度 | Phase A | Phase B | 变化 |
|---|---|---|---|
| 训练量 | 1600 条 | 474→1920/2240 条 | 场景数变化带动 |
| 工具 | 3 | **5** | +get_refund_status, +cancel_order |
| 场景 | 6 | **12** | +6 个新工具场景 |
| 模板 | 正式书面 ×2 | 正式模板 / +bank-v4 措辞增强 | 两轮对照 |

关键设计：新增工具与原有工具**语义重叠**
（get_refund_status vs get_order 都查退款信息；cancel_order vs refund_order
都改订单状态），模型必须学会选择。硬边界未动：parser / max_steps /
verify_final_state / 发布门禁阈值 / 封存 holdout。

## 2. 教师采集

最终一轮 **474/480 (99%)**，单轮费用 ¥1.27（含 reasoning token 按 output 计费；
累计 ~¥11 含前期 bug 重跑）。逐场景通过率 92%–100%。

采集期间修复的四个阻塞问题（每个都改变了后续实验的合法性）：

1. `_materialize_task` 对 ALLOW 决策只设 `refund_status=refunded`，
   不设 `status=cancelled`/`cancel_status=cancelled`——cancel 类场景
   target_state 全错。
2. `retail_ops/build/teacher_data.py::_to_policy_output` 拒绝多工具调用响应；
   改为取第一个 tool call 后 refund_then_cancel 从 0/40 → 37/40。
3. 环境 `cancel_order` 不检查 refund_deadline 时间窗口——DENY-recent 场景
   在环境层不可拒绝。
4. **措辞对教师行为的引导作用**：cancel_denied_recent 用户请求从「请检查…
   是否能取消」改为「请评估…是否满足取消条件」后通过率 8% → **100%**。
   可复用经验：DENY 类请求必须明确要求「评估/判断」而非「检查/执行」。

## 3. 三轮候选与三面读数

数据：sft-001 = 480 行纯正式模板；sft-002 = 2240 行（+bank-v4 措辞 ×3，
rtc oversample ×3）；sft-003 = 1920 行（+措辞 ×3，无 oversample）。

| 评测面 | sft-001 | sft-002 | sft-003 |
|---|---|---|---|
| v4 dev（120，训练分布内） | **0.95** / pv0 | 0.917 / pv0 | 0.917 / pv0 |
| OOD v2（v1 bundle，60，只换说法） | 0.8167 / pv0 | 0.8333 / pv8 | **0.8667** / pv7 |
| OOD v4（跨工具，120，新评测集） | — | — | **0.8917** / pv2 |

训练损失：eval_loss 0.292 → 0.114 → 0.107。

## 4. 五条核心结论

### 结论一：缺措辞增强是首轮 OOD 崩坏的主因（已修复并验证）

refund_eligible 同一模型：训练措辞下 10/10，新措辞下 2/10；
加 bank-v4 增强（per_task=3）后 OOD 恢复到 **1.0**。
R6 的因果在多工具场景上再次成立。

### 结论二：措辞增强的代价与 R6 同构——执行倾向

ALLOW 类全面恢复的同一轮，duplicate-deny 从 1.0 跌到 0.2–0.4
（OOD v2 上 pv 7–8，全部是对已退款订单再次执行退款）。
这不是新缺陷，是 R6 已记录机制在新数据面上的再现，规模更大。

### 结论三：oversample 用于信号不一致的场景会放大失败

refund_then_cancel 的教师轨迹存在两种合法顺序
（「先查两单再动作」396 行 vs Oracle 交错序 84 行）。
×3 oversample 使该场景占训练集 21%，dev 从 4/10 恶化到 0/10。

### 结论四：崩坏与措辞增强本身负相关（A 方案假设被证伪）

去掉 oversample（sft-003）后 rtc 仍 0/10。三轮对照：
无增强 4/10，有增强两轮均 0/10。机制猜测（**未经分离验证，不得写成结论**）：
改写放大了「提到的订单 → 用主导动作处理」的先验，
而语料中退款动作频率远高于取消。

### 结论五：单订单跨工具选择已学会——Phase B 主张部分成立

sft-003 在 OOD v4 上 11/12 场景 ≥0.8：check_refund_status、cancel_eligible、
cancel_recovery 均 **1.0**。语义重叠的单向选择没有问题。
唯一硬失败集中在**双订单复合动作**（退 A 后对 B 执行 cancel_order）——
模型稳定把 B 也退款。

## 5. 新增基础设施（可复用）

| 资产 | 路径 | 说明 |
|---|---|---|
| v4 bundle | `domains/retail_ops/v4/` | 5 工具、12 场景、7 规则，受控版本 4.0.0 |
| 冻结任务集 | manifest `retail_ops_v4_20260822` | 480/120/240 |
| 教师证据 | 私有根 `teacher-v4-001` | 474 accepted |
| bank-v4 | phrasing-bank-v4（sha256 `aa6ccee3…`） | 7 意图 599 条，双占位符 |
| OOD v4 评测集 | 版本 `retail_ops_ood_v4_20260823` | 12×10=120，跨工具口径 |
| 新模块 | `domain/ood_v4_tasks.py`、`domain/v4_tasks.py` | 任务生成 |
| 配置 | `configs/retail_ops/{build,evaluate}/*v4_r9*`、`*r9_phase_b*` | 全链路 |

## 6. 判读（按 R9_SPEC §3.3）

| 结果 | 判定 |
|---|---|
| OOD ≥ 0.80 + 跨工具 ≥ 0.70 | ✅ 0.867 / 0.892 达标 → 「多样性有帮助」 |
| 任意评测集下降 | ❌ 未发生（相对前轮全部持平或改善） |

**但必须带三个限定**：
1. 这是**探索性结论**，不用于发布判定；当前发布候选仍是 sft-008（口径不同：
   3 工具、含 sealed 观测），两者不可直接比较。
2. OOD v4 是本轮新建的集合，从未用于候选选择之前的预注册——它的读数只能
   作为描述性证据，不能作为「泛化已解决」的证据。
3. 自变量不纯：三轮同时改了措辞/oversample/数据量，梯度步数也随之变化。

## 7. 遗留问题与第四轮入口

**唯一硬失败**：refund_then_cancel 双订单复合动作（全评测面 0/10）。

第四轮方向建议（详见交接提示词）：提高 cancel 动作先验
（调 cancel 类场景配比 / 构造 RTC 中间辅助任务），
而不是继续调该场景采样权重——A/B 两种采样操作已被证明无效或有害。

---

*本文档为 Phase B 收尾存档。历史细节以 LOG-20260822-01…05 为准；
读数以各 `reports/retail_ops/v1/**` 下的 run_id 自哈希报告为准。*

---

## 8. 第四轮（2026-09-05）：rtc 修复——方案甲判「方向对、力度不够」，方案乙判「修好」

**入口**：交接 `docs/handoffs/2026-08-23-r9-phase-b-round4-execution-prompt.md`
（判读规则预注册）+ 本阶段交接 §4 第 2 步。预注册：`task_plan.md`（`3db975f` 甲、
`7472c2c` 乙）。teacher 换 **mimo-v2.5**（用户指定端点；与三轮 DeepSeek 的 provider
差异如实记录——甲乙两轮各自单 teacher，无混采）。

### 8.1 方案甲（family 覆盖，`retail_ops_v4_20260904`）

CANCEL_* 4 场景 family 池 7 态 → 10 态（新增 margin 档 4/6/12），train family
20 → 35；teacher-v4-004 采集 600/600、接受率 **0.987**（592/600；8 条教师违规被
执行式 verifier 拒绝，落回 Oracle 参考轨迹），2.01M tokens；sft-004 = 2400 行。

| 评测面 | sft-003 | sft-004（甲） |
|---|---|---|
| v4 dev (120) | 0.9167 / pv 0 | 0.95 / pv 0 |
| OOD v2 (60) | 0.8667 / pv 7 | 0.9333 / **pv 4** |
| OOD v4 (120) | 0.8917 / pv 2 | 0.9417 / pv 2 |
| **rtc dev** | 0/10 | **4/10** |
| **rtc OOD v4** | 0/10 | **5/10** |

判读（预注册表）：rtc dev 4 < 8 → **第二分支「方向对，力度不够」**。cancel 单订单
场景全部满分（dev 四场景 10/10）——「cancel 先验不足」假设方向被证实，但 family
覆盖不足以修复复合任务。失败签名与三轮一致：`get_order(A)→get_order(B)→refund(A)→refund(B)`。

### 8.2 方案乙（RTC 中间辅助任务课程，`retail_ops_v4_20260905`）

按 round4 交接规格：新增 `rtc_stepwise` 辅助场景——RTC 同一状态拆两段的第一段，
只要求「查 B 并取消 B」（复用 cancel_eligible 结构，实体取 RTC 的 other_order）；
**只进 train split**（dev/holdout 无此场景，评测面不变），rtc 40 ↔ stepwise 40（1:1）。
teacher-v4-005 采集 640/640、接受率 **0.980**（627/640；rtc 4 条 + stepwise 7 条
`wrong_final_state`、2 条政策违规均被 verifier 拒绝），2.01M tokens；sft-005 = 2560 行。
**判读规则与甲同一张表，阈值一个字未改**（预注册 `7472c2c`）。

| 评测面 | sft-003 | sft-004（甲） | **sft-005（乙）** |
|---|---|---|---|
| v4 dev (120)* | 0.9167 / pv 0 | 0.95 / pv 0 | **0.9833 / pv 1** |
| OOD v2 (60) | 0.8667 / pv 7 | 0.9333 / pv 4 | **1.0000 / pv 0**（invalid 1，schema 0.9899） |
| OOD v4 (120) | 0.8917 / pv 2 | 0.9417 / pv 2 | **0.9583 / pv 3** |
| **rtc dev** | 0/10 | 4/10 | **9/10** |
| **rtc OOD v4** | 0/10 | 5/10 | **8/10** |

\* sft-005 的 dev face 是 `v4_20260905`（同分布重抽、task_id 不同），与 sft-003/004
的 dev 不可逐位比较；OOD v2 / OOD v4 任务集与前三轮逐字节相同。

**判定：修好**——rtc dev 9/10 ≥ 8、OOD v4 rtc 8/10 ≥ 5、OOD v2 pv 0 ≤ 7（三条全过）。
rtc 失败从三轮全败的 0/10 修复到 dev 9/10、OOD v4 8/10。

### 8.3 如实记录的边界与代价

1. **OOD v4 pv 2 → 3**（sft-005 vs sft-004）：判读口径是 OOD v2（0 ≤ 7 ✓），但 v4
   的政策违规多了一次，如实报告。cancel_denied_recent OOD v4 0.8 → 0.7。
2. **OOD v2 invalid_call = 1**（sft-003/004 为 0）：一次非法调用，schema 0.9899。
3. **自变量不纯**：乙相对甲同时变了训练行数（2400 → 2560）与数据构成（+40 辅助
   任务）；「辅助课程有效」的结论建立在甲（family 覆盖不足）与乙（甲 + 课程）的
   顺序对照上，n=1。
4. **仍然探索性**：不用于发布判定，发布候选仍是 sft-008（v1 口径、含 sealed 观测），
   sft-005 未经过任何封存评测。
5. teacher provider 从 DeepSeek（三轮）换为 mimo-v2.5（四轮）——甲乙内部单 teacher，
   但与前三轮的数据不可归因到单一 provider 差异。

### 8.4 方法论结论（进 LOG）

**动作先验失衡（rtc 双订单复合动作 0/10）的三条修复路径中，只有中间辅助任务课程
生效**：调该场景 oversample 权重（×3 恶化到 0/10，三轮已证伪）、提高 cancel 类
family 覆盖（20→35，dev 4/10 部分改善）都不足以修复；把复合动作拆成「同一状态的
第一段」单独训练（1:1 混入）后修复到 9/10。机制解读（未单独消融验证）：辅助任务
提供了「第二订单的请求 → cancel」的**干净梯度**，而完整 RTC 的梯度被「提到的订单 →
主导动作（退款）」的强先验淹没。
