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
