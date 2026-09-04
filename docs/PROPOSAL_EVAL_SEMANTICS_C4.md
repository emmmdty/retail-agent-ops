# 提案（Phase C4）：`max_steps` 4→6 放宽与 `reason` 语义等价判定

**日期**：2026-09-04
**性质**：评测语义变更提案。**本文档只做影响分析，不实现任何代码；两项都需要用户裁决后才立项。**
**关联**：`docs/PITFALLS.md` 根因 3（约束过紧）、`docs/R8_DIAGNOSIS.md`（R8 P1）、
交接 `2026-09-04-quality-closeout` §5 Phase C4。

---

## 提案 1：`max_steps` 4 → 6

### 现状与证据

- 冻结数据集与 sealed 评测把步数预算钉在 `max_steps=5`（sealed config `Literal[5]`），
  训练数据由冻结任务集生成（`TaskSpec.max_steps` 默认 4，`REFUND_THEN_CANCEL` 为 5）。
- R8 根因 3：`refund_recovery` 需要 3 次工具调用（get_order → refund 失败重试 → refund），
  只剩 1 步余量；模型多说一句澄清话就被 `STEP_LIMIT` 判失败。
- dev 60 上 `step_limit` 类失败有真实占比（`OOD_EVALUATION.md` 的失败分布），
  其中一部分是「行为对、预算不够」的假阴性。

### 变更内容（若批准）

1. `BaseEvaluationConfig.max_steps`、`sealed_evaluation._MAX_STEPS`（已单源绑定）、
   冻结任务集的 `TaskSpec.max_steps` 同步放宽；
2. 历史可比性：dev/sealed 的全部既有读数**不可与新口径比较**——配对前提
   （`budget` 字段在 `_validate_paired_evidence` 里逐字比较）会直接拒绝混用，
   这是结构保护，不是需要额外纪律的地方。

### 成本与风险

| 维度 | 评估 |
|---|---|
| 工程成本 | 低。单源绑定后只改 config Literal 与数据集生成参数；评测/报告代码零改动 |
| 证据链成本 | **全价**。新 dataset_version + 重新冻结 + base/candidate 全部重跑 + 新封存集；约等于一次 R2 量级的数据重建（teacher 费用另计） |
| 收益 | 消除一类假阴性；`refund_recovery` 的失败更可归因 |
| 风险 | 放宽预算会**同时**放宽违规机会（多一步 = 多一次违规窗口）；v1.3 的绝对违规门（0 容忍）下，预算放宽可能让发布判定更严而不是更松——这个二阶效应在 R8 的分析里没有评估过 |
| 时机 | 建议**不在 rtc 第四轮 / D4 判定之前做**——它改变任务集，会让 D1（rtc 第四轮）与 D4（一次性 v1.3 判定）的预注册判读规则失效 |

### 建议

**缓议**。先跑完 D1/D4（判读规则已预注册），拿到 v1.3 判定的完整读数后，
若 `step_limit` 假阴性仍显著，再以新 dataset_version 立项。

---

## 提案 2：`refund_order.reason` 语义等价判定

### 现状与证据

- `refund_order.reason` 是 4 选 1 精确匹配（`damaged` / `wrong_item` / `not_as_described` / `changed_mind`），
  verifier 对 `arguments` 逐字段精确比较（`R8_DIAGNOSIS.md` 根因 3）。
- 后果：模型选了一个**语义可接受但不在 gold 枚举里**的理由（如用户描述磨损、
  模型选 `damaged` 而 gold 是 `not_as_described`）会被判 `invalid_call`，
  `invalid_call_count_max: Literal[0]`（v1.3 后仍是硬门）让整份判定 NO-GO。
- 这是一类「行为可辩护、判分器不容忍」的假阴性。

### 变更内容（若批准）

verifier 对 `reason` 增加**语义等价判定**：gold 理由与模型理由按用户请求中的
事实标签（受损/错发/不符描述/不想要了）做等价映射，等价即通过。
实现层面有两种口径：

- **口径 A（任务侧）**：冻结任务集的 `expected_calls` 里把 reason 从「标准枚举」
  改成「可接受集合」（`list[str]`）；verifier 按集合判定。需要新 dataset_version。
- **口径 B（verifier 侧）**：不动数据，在 verifier 里内置「用户事实 → 可接受理由集合」
  映射。不动数据集，但 verifier 语义变化同样破坏历史可比性
  （`evidence_complete` 与重放都会受影响）。

### 成本与风险

| 维度 | 评估 |
|---|---|
| 工程成本 | 中。口径 A 动数据集 + verifier；口径 B 只动 verifier 但引入「判分器知道答案分布」的新形状 |
| 证据链成本 | 全价（同提案 1：新 dataset_version 或 verifier 版本化 + 全部重跑） |
| 收益 | 消除 `invalid_call` 里的理由类假阴性；对 DPO 路线也有利——偏好对里「该拒绝却执行」是核心，理由误判会污染偏好对 |
| 风险 | **口径 B 有「判分器替模型说话」的味道**：把判分标准改成模型容易通过的形式，即使动机正当，也会被面试官追问「你的 verifier 是不是为结果服务的」。口径 A 把模糊性显式放进任务契约，诚实得多 |
| 与 v1.3 的交互 | `invalid_call_count` 是绝对门（Literal[0]）；理由等价化会减少它的触发，方向上与「假阴性清零」一致 |

### 建议

**若要做，选口径 A 并作为新 dataset_version 的一部分，与提案 1、难度分层重冻结
（决策门 #5）合并成一次数据重建**，避免冻结两次。单独做不值得付全价。

---

## 决策门

| # | 问题 | 选项 |
|---|---|---|
| 1 | max_steps 是否放宽 | (a) 缓议（建议）；(b) 与数据重建合并做 |
| 2 | reason 语义等价是否做 | (a) 不做；(b) 口径 A 与数据重建合并（建议，若做）；(c) 口径 B（不建议） |

在用户裁决前，本提案不进入实现，不改动任何冻结契约。
