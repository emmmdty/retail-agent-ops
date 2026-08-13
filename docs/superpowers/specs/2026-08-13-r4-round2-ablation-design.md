# R4 第二轮设计：三候选并行消融

- 日期：2026-08-13
- 阶段：R4「失败驱动优化」第二轮
- 前置：LOG-20260811-06（根因精确化）、LOG-20260811-07（第一轮方案与门槛裁定）、
  LOG-20260811-09（第一轮判负）
- 状态：**设计待用户批准**；本文件不授权任何 GPU、API 或 holdout 操作

## 1. 本轮定位

本轮是**诊断性消融实验，不是发布候选生产**。

成功标准是「分辨出瓶颈在哪一层」，不是「某个候选达标」。三个候选都不达标但彼此分化
清晰，本轮照样有产出；三个都纹丝不动，那就是又排除了一整类解释，同样是硬结论。

发布门禁（`success_delta ≥ +0.05` 等五项）一个字不改。封存 holdout 不动。

## 2. 第一轮负结果的再解读

### 2.1 数据比例这一整类解释可以彻底排除

LOG-20260811-09 的口径是「族内 3:1 → 1:1，`refund_eligible` 变化精确为 0」，结论限定在
「1:1 这个量级上不成立」。本次改用**决策点口径**重算两份导出——统计每条样本在
`get_order` 已返回之后紧接的那个 assistant 消息的形状：

| 导出 | text 形状 | tool_call 形状 | 比值 |
|---|---|---|---|
| `train-export-001`（R3 输入） | 160 | 80 | 2.0 : 1 偏 text |
| `train-export-002`（R4 输入） | 160 | 240 | **1 : 1.5 偏 tool_call** |

逐场景分解（`train-export-002`）：text 侧为 `lookup_status` 40 +
`refund_denied_{window,ownership,duplicate}` 各 40；tool_call 侧为 `refund_eligible` 120 +
`refund_recovery` 120。

即：R4 不只是把比例拉到 1:1，而是**在决策点上已经把 tool_call 变成 1.5 倍的多数**，
`refund_eligible` 依然 0/10。结论应当加强为——**训练分布中该决策点的动作比例，
在已经反向过载的情况下依然不驱动该行为**。这比原记录的「量级不够」强得多，
且直接决定第二轮不应再在比例上加码。

复算命令见第 9 节，可独立重现。

### 2.2 多步路径在训练数据里没有闭环（新发现）

`train-export-002` 的样本末尾 role 分布：`assistant` 160 / `tool` **240**。
60% 的样本以 `tool` 消息结尾。

`refund_eligible` 的完整序列形状：

```
system → user → assistant(tool_call get_order) → tool
              → assistant(tool_call refund_order) → tool   ← 序列到此结束
```

对照 `refund_denied_window`：

```
system → user → assistant(tool_call get_order) → tool
              → assistant(240 字符结构化分析文本)          ← 有自然终点与 EOS
```

**模型在训练中从未见过「退款成功之后长什么样」**，只见过「分析完就结束」。
候选在 dev 上的实际行为——正确读状态、正确判定可退、产出分析文本、请求确认后停止——
正是后一种模式的照搬。

根源在 `core/agent/runner.py:123`：`final_state == 1.0` 时立即 `break`，退款成功那一刻
轨迹被截断，因此 teacher 证据里根本不存在这段终局文本。这是环境与 runner 的设计后果，
不是导出缺陷，也不是 bug——`domain/environment.py` 的 `verify_final_state` 对 REFUND 类
本就不要求 `_terminal_response`。

### 2.3 LoRA 容量从未被当作变量测试过（新发现）

`training/sft.py:71` 的 `target_modules` 默认为
`["q_proj", "k_proj", "v_proj", "o_proj"]`——**只覆盖 attention 投影，不含 MLP 的
`gate_proj`/`up_proj`/`down_proj`**，`r=16`。

R3 → R4 的「每轮只改一个主要变量」纪律由
`tests/test_retail_ops_r4_cli.py:84` 断言，把 `lora` 段逐字段锁死。因此两轮候选用的是
同一个可能不足的容量配置，而该配置从未被质疑过。

观察到的能力分裂与此吻合：**格式类改变成功**（`schema_valid_rate` 0.78 → 1.00、
`invalid_call` 41 → 0、`policy_violation` 16 → 0），**行为倾向类改变失败**
（该不该执行动作）。前者是浅层输出模式，后者需要改变条件决策。

### 2.4 措辞假设需要更精确的表述

LOG-20260811-09 把残余嫌疑记为「祈使句 vs 核实/检查框定」。读
`domain/formal_tasks.py:516` 的 `_user_request` 后，更精确的区分是**是否在指令层面
显式要求自主完成多步动作**：

- `refund_recovery`：「请为订单 X 按 Y 办理退款；**临时失败时重试一次**」——
  显式的多步行动指令
- `refund_eligible`：「请**核实**订单 X 并按 Y 办理退款」/「订单 X 需要因 Y 退款，
  请先**检查**后处理」——含"办理/处理"但以核实/检查开头，无自主完成的显式授权
- 三个 `refund_denied_*` 变体中也有含"处理/办理"字样的（如「请核验 X 后处理一笔 Y 退款」），
  因此**单靠 user_request 无法区分 eligible 与 denied**，判别信号只在 `get_order` 返回值里

这解释了为何 `refund_recovery` 在同等处理下 +2 而 `refund_eligible` +0，
也说明候选 C 该改的是「显式授权自主执行」而不是「换成祈使语气」。

## 3. 竞品与业界对照

| 来源 | 与本项目的关系 |
|---|---|
| QLoRA 原论文与现行实践 | 推荐 LoRA 覆盖**全部 linear layer** 才能逼近全参微调；现行共识是「rank 翻倍但只挂 attention，不如保持 r=16 并加上 MLP 投影」。精确命中 §2.3 的配置 |
| HiL-Bench（arXiv 2604.09408） | 把本项目的失败模式命名为 *excessive help-seeking*——「信息足够自主行动时仍请求确认」，与「该问却不问」并列为 calibration 的两个方向。给了失败一个业界标准名称 |
| Clarification Is Not Enough（arXiv 2605.25204） | 实测用**精选轨迹数据** SFT 可把 action accuracy 提升 10+ 点（LLaMA 与 Qwen 均然）。关键词是轨迹质量而非样本数量，与本项目「×3 无效」一致，支持候选 B 的方向 |
| τ²-bench（arXiv 2506.07982） | 同域竞品（Sierra 零售客服 agent）。`SPEC.md` §8 已列为可选外部 sanity check，`BFCL_PIN.txt` 记录其未随迁。**R5 才考虑，本轮不碰** |

竞品对照的作用是给候选排序提供外部依据，不替代本项目自己的实测。

## 4. 三候选设计

三者共用同一参照点 `sft-002` / `candidate-002`（R4 第一轮，45/60），各只改一个变量。
它们之间是**并列消融，不是叠加**。

| 候选 | 唯一变量 | 训练数据 | 新代码 | 重跑 base dev |
|---|---|---|---|---|
| A | `lora.target_modules` | `train-export-002`（复用） | 无 | 否 |
| B | `data.train_relpath` | 新 `train-export-003` | 导出侧 | 否 |
| C | `runner.SYSTEM_PROMPT` | 新 `train-export-004` | 无（改常量） | **是** |

### 4.1 候选 A：LoRA 容量

```yaml
lora:
  r: 16                      # 不变
  alpha: 32                  # 不变
  dropout: 0.05              # 不变
  target_modules:            # 唯一改动
    [q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj]
```

其余全部沿用 `retail_ops_v1_r4_sft_rebalanced.yaml`。改动落在一个已提交配置文件的
一个字段上，零新代码、零数据变化。

**风险**：可训练参数增加约 2.5–3 倍，可能同时影响已获得的格式收益。
`invalid_call` / `policy_violation` / `schema_valid_rate` 三项必须逐项报告，
退化即如实记录——不因它是"推荐方案"而淡化。

### 4.2 候选 B：数据闭环

为 `refund_eligible` 与 `refund_recovery` 的样本在末尾追加一条 assistant 终局回复，
使 tool_call 路径获得自然终点。

**模板只能使用工具真实返回的字段。** 实测 `refund_order` 的 observation 为
`{"order_id": ..., "refund_status": "refunded"}`——**没有金额字段**。任何含金额、
到账时间、工单号的模板都会教模型编造工具从未返回的信息，等于用一个新的幻觉问题
换掉当前问题。定稿模板：

```
已为订单 {order_id} 按 {reason} 办理退款，当前退款状态为 {refund_status}。
```

三个字段**全部可从样本自身的消息序列取得**，已实测确认：

| 字段 | 来源 |
|---|---|
| `{order_id}` | 最后一次 `refund_order` 的 tool 返回值 `content.order_id` |
| `{refund_status}` | 同上，`content.refund_status`（成功时为 `refunded`） |
| `{reason}` | 最后一次 `refund_order` 的 tool_call `arguments.reason` |

因此 B 的实现是 `sft.jsonl` 的**纯局部变换**——不读任务记录、不碰 `target_state` 或
`expected_calls`、不引入任何外部信息，也就不产生新的 provenance 问题。

`refund_recovery` 有两次 `refund_order`（首次 `transient_error` 失败、第二次成功），
终局回复一律追加在**最后一次成功的** `refund_order` 返回之后。

**为什么这不会稀释决策点**：终局文本加在 `refund_order` **之后**，而决策点是
`get_order` 返回**之后**。两个位置不同，决策点的形状分布仍是 160 : 240。
这一点必须由测试断言，不能靠推理。

**为什么不触发 `mixed_tool_call_content`**：终局文本是**独立的 assistant 消息**，
不是与 tool_call 同处一条消息。`core/agent/parser.py:29-31` 约束的是后者。
assistant 工具调用消息的 `content` 仍然保持为空。

产物：`train-export-003`，模板与受影响行数写入 `sft_terminal_template.json` 并纳入
`private_artifact_sha256`，与第一轮 `sft_oversample.json` 的先例一致。
`train.jsonl` 与 `selection.json` 必须仍与 240 条冻结任务 1:1 且与 001 逐字节相同。

### 4.3 候选 C：指令框定

改 `core/agent/runner.py:23` 的 `SYSTEM_PROMPT`。定稿措辞——在现有两句后追加一句：

```
你是订单工具助手。只能使用提供的工具处理请求；退款前必须查询订单，
遇到 transient_error 时可以重试。确认符合退款政策后直接调用工具执行，
不要再向用户征询确认。
```

要点是**显式授权自主完成**，不是改成祈使语气（依据 §2.4）。
执行时允许对措辞做不改变语义的微调，但必须把最终字符串与其 SHA-256 记入
`findings.md`——它是本轮 base 与 candidate 两侧的配对字段，事后无法从产物反推。

**C 产出两个读数，比 A/B 信息量更大**：

1. **新 prompt 下的 base**（零训练，纯 prompt 干预）——如果它就让 `refund_eligible`
   提升，说明这个行为**根本不需要训练**，那么 R3/R4 两轮 SFT 在这条线上的努力
   都是在解一个 prompt 层面的问题。这是本轮可能得到的最有价值的单条结论。
2. 新 prompt 下的 candidate（prompt + 训练）。

### 4.4 执行顺序是强制的

`SYSTEM_PROMPT` 是全局常量，被 `evaluate/base_evaluation.py:381` 与
`evaluate/sealed_evaluation.py:217` 哈希，且 `system_prompt_sha256` 在 dev 的
`PAIRING_FIELDS`（`evaluate/candidate_evaluation.py:232-248`）内。

因此顺序**必须**是 **A → B → C**：C 一旦提交，A/B 的评测就不能再在旧 prompt 下产出，
其配对基线（既有 `qwen3-4b-dev-base-001`）也不再可用。

C 的对照必须是**新 prompt 下重跑的 base**，不能与 A/B 的 delta 直接相比。
跨候选比较只能用 `refund_eligible` 的**绝对通过数**，这正是本轮的诊断读数。

## 5. 门槛与停止条件

### 达标门槛（与第一轮相同，不下调）

- `refund_eligible` **≥ 7/10**
- 且 `invalid_call_count` = 0、`policy_violation_count` = 0、`schema_valid_rate` = 1.0

### 诊断读数（新增，不是门槛）

- 任一候选 `refund_eligible` **≥ 3/10** → 判定「该层有信号」，值得开第三轮
- 三个候选**均 0/10** → 容量、数据闭环、指令框定三类解释全部排除，是硬结论
- 每个结论必须标注 **n = 10** 的统计限度：单条样本变化即 10 个百分点，
  3/10 与 5/10 的差异不足以支撑排序结论

### 停止条件

三个候选跑完即停止，统一分析后再决定第三轮。**不因中途某个候选表现好而追加变体，
不改训练目标，不扩展到 DPO/GRPO/在线 RL，不消耗封存 holdout 的第二次观测。**

## 6. 成本

| 步骤 | 位置 | 预计 |
|---|---|---|
| A 训练（LoRA 参数 ~2.5–3×） | gpu-5090 GPU 0 | 600–800 s |
| A dev 候选评测 | 同 | ~300 s |
| B 导出 | 本地 CPU | ~1 s |
| B 训练 | gpu-5090 GPU 0 | ~500 s |
| B dev 候选评测 | 同 | ~300 s |
| C 导出 | 本地 CPU | ~1 s |
| C 训练 | gpu-5090 GPU 0 | ~470 s |
| C **base** dev 重跑 | 同 | ~200 s |
| C dev 候选评测 | 同 | ~300 s |

GPU 合计约 **2900 s ≈ 50 分钟**，一个用户决策门，封存 holdout 观测消耗 **0**。

对照第一轮：单变量串行每轮 ~13 分钟 GPU 但各占一个决策门。本轮用一个门换三倍信息量，
符合 `findings.md` 已记录的成本结构——**便宜的是实验，贵的是 holdout 观测**。

## 7. 非目标

- 不改 `assert_exact_quotas` 的 40/10/20 冻结配额，不新增任务，不重新冻结数据集
- 不改 `SealedEvaluationReport` / `BaseRunEvidence` / `CandidateRunEvidence` 字段集合
- 不改发布门禁阈值，不放宽 `require_comparable_sealed_runs`
- 不动封存 holdout；不进入 DPO / GRPO / 在线 RL
- 不改 `parser.py` 的 `mixed_tool_call_content` 规则——放宽它会让 R3/R4 已取得的
  `invalid_call = 0` 含义改变，且与本轮三个假设都无关
- 不改 `runner.py` 的 `final_state == 1.0` 即 break——那会改变评测语义并使全部已有证据失效
- 不启用 τ²-bench / appworld / ToolSandbox（R5 事项）
- 不自动执行任何 GPU 训练或评测；每条外部命令单独请示

## 8. 不可逆约束（违反即产生永久损失）

1. **`SealedEvaluationReport` 字段集合自 LOG-20260810-02 冻结**，两份 sealed 证据已产出，
   `report_id` 是全字段自哈希，再改即作废。
2. **R4 之后任何一次 release 判定 = 封存 holdout 的第二次完整观测**（base + candidate 两侧）。
   `code_commit` / `uv_lock_sha256` / `system_prompt_sha256` 均在 `SEALED_PAIRING_FIELDS`
   内，任何改进提交后已有 sealed base 证据不再可配对。本轮三个候选都会触发这一点，
   因此它**不能**用作候选间的选型理由。
3. 每个正式运行使用新输出目录，不覆盖 `r3/` 与 `r4/` 已有产物。
4. C 提交后 A/B 的旧 prompt 评测不可再产出（§4.4）。

## 9. 验收

### 复算命令（本设计的证据可独立重现）

```bash
python3 -c "
import json,collections
for name in ['001','002']:
    p=f'data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722/train-export/train-export-{name}/sft.jsonl'
    rows=[json.loads(l) for l in open(p)]
    shape=collections.Counter(); endswith=collections.Counter()
    for r in rows:
        ms=r['messages']; endswith[ms[-1]['role']]+=1
        for i,m in enumerate(ms):
            if m['role']=='tool':
                nxt=ms[i+1] if i+1<len(ms) else None
                shape['NONE' if nxt is None else ('tool_call' if nxt.get('tool_calls') else 'text')]+=1
                break
    print(name, dict(endswith), dict(shape))
"
```

期望输出：`001 {'assistant': 160, 'tool': 80} {'text': 160, 'tool_call': 80}` 与
`002 {'assistant': 160, 'tool': 240} {'text': 160, 'tool_call': 240}`。

### 质量门

`.venv/bin/pytest -q`（起始基线 **638**）、`.venv/bin/ruff check .`、`.venv/bin/mypy`、
`env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check`、`git diff --check`。

### 每个候选必须证明的事

- A：训练配置除 `lora.target_modules` 外与 `retail_ops_v1_r4_sft_rebalanced.yaml` 逐字段相同
- B：`train-export-003` 的 `train.jsonl` / `selection.json` 与 001 逐字节相同；
  决策点形状分布仍为 160 : 240；assistant 工具调用消息 `content` 仍全为空
- C：`train-export-004` 与 002 的唯一差异是 system 消息；base 与 candidate 两侧
  `system_prompt_sha256` 相等且均不等于旧值

## 10. 授权状态

GPU **否**、API **否**、数据下载 **否**、holdout 执行 **否**、公开发布 **否**。
每一条外部命令在执行前单独报告命令、工作目录、物理 GPU、预计时长与产物，并等待确认。
