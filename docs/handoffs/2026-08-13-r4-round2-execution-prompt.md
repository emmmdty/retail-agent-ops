# RetailAgentOps R4 第二轮执行提示词（三候选并行消融）

## 使用方式

在项目根目录 `/home/tjk/myProjects/internship-projects/retail-agent-ops` 开新会话，
把下一节整段复制为第一条消息。

设计依据：`docs/superpowers/specs/2026-08-13-r4-round2-ablation-design.md`（已批准）。
执行中若与本提示词冲突，以该 spec 为准；两者都没覆盖的高影响选择，停下问用户。

**本提示词不预批任何 GPU、API 或 holdout 操作。** 第 6 节列出的每个外部执行门
都要单独报告并等待确认。

---

## 可直接复制的提示词

你在 RetailAgentOps 项目上继续 R4「失败驱动优化」阶段的**第二轮**。先按 `CLAUDE.md`
第 1 节的顺序读取上下文，再读本轮设计
`docs/superpowers/specs/2026-08-13-r4-round2-ablation-design.md`。

### 1. 你接手时的状态

R4 第一轮已执行并**判负**（LOG-20260811-09）。方案是对多步家族重复采样
（`train-export-002`，两类各 ×3，sft 240→400 行），候选 `sft-002` / `candidate-002`。
结果：`refund_eligible` **0/10**（门槛 ≥7/10）未达成；`refund_recovery` 3/10→5/10；
合计 43/60→45/60，仍低于 base 48/60。格式/安全三项保住（0 / 0 / 1.0）。

第二轮设计已由用户批准，方向已定，**不要重新讨论要不要做、做哪个**。

### 2. 本轮的性质

**诊断性消融实验，不是发布候选生产。** 成功标准是「分辨出瓶颈在哪一层」，
不是「某个候选达标」。三个都不达标但彼此分化清晰，本轮照样有产出；
三个都纹丝不动，那是又排除了一整类解释，同样是硬结论。

发布门禁一个字不改。封存 holdout 不动。

### 3. 三个候选（各只改一个变量，并列消融不叠加）

共同参照点是 `sft-002` / `candidate-002`（R4 第一轮，45/60）。

**候选 A — LoRA 容量**：`lora.target_modules` 从
`[q_proj, k_proj, v_proj, o_proj]` 改为
`[q_proj, k_proj, v_proj, o_proj, gate_proj, up_proj, down_proj]`。
`r` / `alpha` / `dropout` 与其余全部段落沿用
`configs/retail_ops/build/retail_ops_v1_r4_sft_rebalanced.yaml`。
数据复用 `train-export-002`。零新代码。base dev 不重跑。

**候选 B — 数据闭环**：为 `refund_eligible` 与 `refund_recovery` 样本在末尾追加一条
独立的 assistant 终局回复，产出 `train-export-003`。定稿模板：

```
已为订单 {order_id} 按 {reason} 办理退款，当前退款状态为 {refund_status}。
```

三个字段全部从样本自身的消息序列取（已实测）：`{order_id}` 与 `{refund_status}` 来自
最后一次 `refund_order` 的 tool 返回值，`{reason}` 来自该次 tool_call 的
`arguments.reason`。因此 B 是 `sft.jsonl` 的**纯局部变换**，不读任务记录、
不碰 `target_state` / `expected_calls`。`refund_recovery` 有两次 `refund_order`
（首次 `transient_error`），终局回复追加在**最后一次成功的**那次之后。

**不得加入金额、到账时间、工单号等工具从未返回的字段**——实测 `refund_order` 只返回
`{order_id, refund_status}`，编造字段等于用一个新的幻觉问题换掉当前问题。
lora 与 training 段沿用 R4 原配置。

**候选 C — 指令框定**：改 `src/veritool_rl/core/agent/runner.py:23` 的 `SYSTEM_PROMPT`，
追加一句显式授权自主执行的指令（要点是**显式授权自主完成**，不是改成祈使语气）。
需重新导出 `train-export-004`（system 消息在 sft.jsonl 里）。
**C 必须重跑 base dev**，因为 `system_prompt_sha256` 在
`evaluate/candidate_evaluation.py:232` 的 `PAIRING_FIELDS` 内。

### 4. 执行顺序是强制的：A → B → C

`SYSTEM_PROMPT` 是全局常量，被 `evaluate/base_evaluation.py:381` 与
`evaluate/sealed_evaluation.py:217` 哈希。**C 一旦提交，A/B 的评测就不能再在旧 prompt
下产出**，其配对基线（既有 `qwen3-4b-dev-base-001`）也不再可用。

C 的对照必须是新 prompt 下重跑的 base，**不能与 A/B 的 delta 直接相比**。
跨候选比较只能用 `refund_eligible` 的绝对通过数。

C 会产出两个读数，第一个尤其重要：**新 prompt 下的 base（零训练）**——
如果纯 prompt 干预就让 `refund_eligible` 提升，说明这个行为根本不需要训练。
这是本轮可能得到的最有价值的单条结论，务必单独报告。

### 5. CPU 侧要做的事（可连续完成，无需逐条请示）

按 `CLAUDE.md` 第 6 节协议：先在 `task_plan.md` 写明输入/输出/非目标/失败模式/
影响文件/验收，行为变化先写失败测试并确认失败原因，再实现最小闭环。

1. 三份训练配置 + 三份候选评测配置（候选评测 config 里的 `adapter.file_sha256`
   是运行产物，**训练之后才写**，提前写就是无验证占位）。
2. 候选 B 的导出侧实现：终局回复追加逻辑 + `sft_terminal_template.json`
   纳入 `private_artifact_sha256`（沿用第一轮 `sft_oversample.json` 的先例）。
3. 单变量纪律的可执行断言，仿
   `tests/test_retail_ops_r4_cli.py:84` 的
   `test_r4_sft_config_changes_exactly_one_variable`，为三个候选各写一条。
4. 治理测试把新配置纳入既有扫描（secret / 绝对路径 / 私有根 / BFCL / holdout /
   模型 pin），并断言新导出与新报告目录仍被 `.gitignore` 覆盖。
5. 本地 CPU 执行 B、C 两次导出并核验（见第 7 节）。

安全关键的断言要做**突变验证**——把断言该抓的东西故意改坏，确认测试立即失败。

### 6. 外部执行门（每条单独报告并等待确认，不得连跑）

报告格式：命令、工作目录、物理 GPU、预计时长、产物路径。

1. 提交 CPU 侧改动（`_current_code_commit` 拒绝脏工作树）
2. 同步 gpu-5090（git bundle → ff-only；这一条属既有例行同步）
3. A 训练（预计 600–800 s，LoRA 参数增至约 2.5–3 倍）
4. A dev 候选评测（~300 s）
5. B 训练（~500 s）
6. B dev 候选评测（~300 s）
7. C 训练（~470 s）
8. **C base dev 重跑**（~200 s）
9. C dev 候选评测（~300 s）
10. 产物回传与哈希核对

GPU 合计约 50 分钟。远端仓库路径 `/mnt/aidata/tongjiakai/retail-agent-ops`，
数据一律落 `/mnt/aidata`，不得写系统盘。该服务器多人共用，执行前核对显存与磁盘余量。

### 7. 每个候选必须证明的事

- **A**：训练配置除 `lora.target_modules` 外与 `retail_ops_v1_r4_sft_rebalanced.yaml`
  逐字段相同。
- **B**：`train-export-003` 的 `train.jsonl` / `selection.json` 与 `train-export-001`
  **逐字节相同**（`29f02425…` / `f60744f7…`）；决策点形状分布仍为 **160 : 240**；
  assistant 工具调用消息的 `content` 仍全部为空。
- **C**：`train-export-004` 与 `002` 的唯一差异是 system 消息；base 与 candidate 两侧
  `system_prompt_sha256` 相等且均不等于旧值。

决策点形状的复算脚本见 spec 第 9 节，可直接复制。

### 8. 判定标准

**达标门槛**（与第一轮相同，**不得下调**）：`refund_eligible` ≥ 7/10，
且 `invalid_call_count` = 0、`policy_violation_count` = 0、`schema_valid_rate` = 1.0。

**诊断读数**（不是门槛）：任一候选 `refund_eligible` ≥ 3/10 → 「该层有信号」；
三个均 0/10 → 三类解释全部排除。

**每个结论必须标注 n = 10 的统计限度**：单条样本变化即 10 个百分点，
3/10 与 5/10 的差异不足以支撑排序结论。不要把噪声写成趋势。

**停止条件**：三个候选跑完即停止，统一分析后再决定第三轮。
不因某个候选表现好而追加变体，不改训练目标，不扩展算法。

### 9. 硬约束（违反即产生永久损失）

- 不改 `assert_exact_quotas` 的 40/10/20 配额，不新增任务，不重新冻结数据集
- 不改 `SealedEvaluationReport` / `BaseRunEvidence` / `CandidateRunEvidence` 字段集合
- 不改发布门禁阈值，不放宽 `require_comparable_sealed_runs`
- 不动封存 holdout；**不消耗第二次观测**
- 不改 `parser.py` 的 `mixed_tool_call_content` 规则（放宽它会让已取得的
  `invalid_call = 0` 含义改变，且与本轮三个假设都无关）
- 不改 `runner.py` 的 `final_state == 1.0` 即 break（那会改变评测语义并使全部已有证据失效）
- 每个正式运行用新输出目录，不覆盖 `r3/` 与 `r4/` 已有产物
- 不进入 DPO / GRPO / 在线 RL；不启用 τ²-bench / appworld / ToolSandbox（R5 事项）

### 10. 记录要求

- `task_plan.md`：开工时重写 Current Task。
- `findings.md` / `progress.md`：按 `CLAUDE.md` 第 7 节更新。
- `docs/PROJECT_LOG.md`：**只在**本轮产出改变后续做法的结论时追加——
  三候选的判定结果达到这个门槛，逐个 config 与测试的增删不达到。
  触发时先追加再在最终答复中报告 LOG ID，不得改写历史条目。

### 11. 验收

`.venv/bin/pytest -q`（起始基线 **638**）、`.venv/bin/ruff check .`、`.venv/bin/mypy`、
`env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check`、`git diff --check`。

### 12. 授权状态

GPU **否**、API **否**、数据下载 **否**、holdout 执行 **否**、公开发布 **否**。

---

## 附：本提示词未覆盖的事项

- **第三轮开什么**：等本轮三个读数出来后另行决定，不在本轮范围内。
- **是否消耗封存 holdout 的第二次观测**：独立的用户决策门。注意 R4 之后任何一次
  release 判定都等于 base + candidate 两侧的**完整**第二次观测，这一点对三个候选
  同等成立，因此**不能**用作候选间的选型理由。
- **简历 bullet 选 A 还是 B 方案**：`docs/RESUME_EVIDENCE.md` 里的待决项，与本轮无关。
- **R5 跨 benchmark 验证**：τ²-bench 等外部 checkout 需先固定 commit，本轮不启用。
