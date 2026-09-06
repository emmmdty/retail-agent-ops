# 交接：DPO 主线 + 并行项（C4 数据重建立项 / I-2b / C3 读数）——新窗口执行提示词

**日期**：2026-09-06
**性质**：D4 判定 NO-GO（绝对门 `policy_violation_count_max=0` 被封存集违规 2 拦下，
LOG-20260905-03）后的下一阶段执行入口。**用户已裁定：启动 DPO（决策门 #4 关闭）；
其余并行项（C4 数据重建立项、I-2b、C3 读数、gate schema 政策）一并纳入本窗口。**
**执行者**：新窗口的 coding agent；**允许使用 subagent**（探索、审查、可并行的独立
工作），subagent 的读数与结论必须抽查验证后再采信。
**授权状态**：GPU 与商业 API 沿用既有授权（gpu-5090、mimo-v2.5 端点）；封存 holdout
观测次数不受限（用户 2026-08-17），但**结果永远不得反馈进开发**。

---

## 0. 一句话背景

D4 证明了发布候选 `sft-008` 在「封存集零政策违规」的绝对安全线下不合格
（11/12 门 PASS，唯一 FAIL 是绝对门），违规集中在 `refund_denied_window` 的
「该拒绝却执行」——SFT 补数据修不掉（R7 判负）、探针已把失败定位到单一状态格、
失败样本可稳定形成偏好对（D2 四条件全部满足）。DPO 是当前唯一未被证伪的根治路径。

## 1. 先读这些（按顺序）

1. `AGENTS.md`（不可违反边界 + 固定流程）
2. `docs/DPO_ENTRY_EVIDENCE_D2.md`（**DPO 的设计宪法**：四入口条件、偏好对形状
   约束、判读草案框架、成本与风险——本文件的 DPO 设计全部从它出发）
3. `docs/POLICY_BOUNDARY.md` §4–§6（探针基线读数：`sft-008` 14/15 偏移 1.00、
   `offset −14` 塌 0.375；R7 数据修复判负的机制「平移不是校准」）
4. `docs/PROPOSAL_EVAL_SEMANTICS_C4.md`（数据重建轨道的影响分析：两项都全价，
   建议合并立项）
5. `docs/PITFALLS.md`（根因 2「表面触发器」、根因 3「约束过紧+方差」、§三 8 条
   已证伪方向——DPO 数据构造同样不得复活它们）
6. `docs/PROJECT_LOG.md` 最后三条（LOG-20260905-01/02/03：D1 修好、E2 装置四层
   修复、D4 NO-GO——本窗口的 operational 教训全部在这三条里）
7. `task_plan.md`（D4 预注册的写法样例：运行清单逐字声明 + 判读规则先提交）
8. `src/veritool_rl/retail_ops/domain/policy_boundary_tasks.py` 与
   `policy_boundary_phrasing_tasks.py`（采样任务的装置接口）

## 2. 已冻结决策（遇到不要再问，也不要重开）

| 决策 | 结论 | 出处 |
|---|---|---|
| 发布候选 | **`sft-008`（原始 seed 0，v1 口径）**；DPO 在其上继续，产物候选暂名 `sft-008-dpo-001` | 决策门（既有台账） |
| v1.3 阈值 | `policy_violation_count_max=0`、`success_delta_ci_lower_min=+0.02` 冻结 | LOG-20260904-02 |
| D4 结果 | NO-GO 已入台账；**读数（违规 2）不得用于 DPO 的调参/数据选择/候选选择** | 预注册纪律 |
| E1 宽工具面迁移 | 不迁移 | 决策门 #6 |
| 硬边界 | 不改 v1/v2 冻结契约：`GATE_IDS` v1.0–v1.3、`SealedEvaluationReport` 字段集、`PAIRING_FIELDS`（v1.1 冻结集）、`assert_exact_quotas` 的 40/10/20、`runner.SYSTEM_PROMPT`、parser | 交接 §6 |
| C3 交叉面 | 措辞只允许 `ood_dev`/`ood_sealed` 分片（装置已强制） | 装置源码 |
| D1 经验 | rtc 已由辅助课程修复（dev 9/10）；DPO 不碰 rtc，机制不同 | LOG-20260905-01 |

## 3. 资源与凭据

### 3.1 gpu-5090

- 远端仓库：`/mnt/aidata/tongjiakai/retail-agent-ops`（与 origin 同步）。
- **`sft-008` 资产**：adapter 在 `reports/retail_ops/v1/r6/sft-008/adapter/`；
  合并模型 `models/Qwen3-4B-sft-008-merged`（`model.safetensors` SHA-256
  `70981220…`，与观测 5 逐位一致）。DPO 起始权重 = NF4 基座 + sft-008 adapter。
- **训练栈**：TRL 1.8.0（远端 venv 有，**本地 venv 没有**——本地测试用依赖注入与
  源码结构断言，照 Phase C1 的测试模式）。
- 多人共用卡：跑之前重看 `nvidia-smi`；长任务 nohup；驱动故障照 E2 交接 §5.5。

### 3.2 LLM API（mimo-v2.5）

- 仅在新封存素材生成（A-7 的 bank-005）时需要；采样/DPO 本身不用 teacher。
- 每次调用前 `--dry_run` 估量；费用记 progress.md 命令表。

### 3.3 本窗口的 operational 教训（全部真实踩过，逐条仍在生效）

1. **训练后必查 loss 曲线**：max_seq_len 过小会截断 assistant 段 → mask 全零 →
   loss/grad 恒 0 → LoRA 零更新且**不报错**（LOG-20260905-02）。DPO 训练同理：
   每轮训练后第一步查 loss 曲线非零、末端下降。
2. **pkill 后必须 `pgrep -af` 验证进程真死**（裸 pgrep 会自匹配误判）；启动后
   `ps -eo pid,args` 确认单实例（双进程并行采集曾污染证据并作废重采）。
3. 输出目录不可覆盖；重跑前删旧目录或换 attempt_id。
4. `dev.jsonl` 的 SFT/TaskSpec 双格式互斥换入换出（若复用 v1 私有根做评测）。
5. 新素材生成的分片覆盖断言（`min_per_partition_intent=12`）与回环分类丢弃率——
   mimo 对 retry 语义的生成-分类失配需 brief 强化（bank-004 的先例）。
6. 预注册里的产物路径要能逐字匹配（shell 简写会让「声明过」无法机械核对）。

---

## 4. 轨道 A（主线）：DPO

### A-0 执行前与用户确认的三个方案点（本文件给出建议，正式稿确认后才能动）

1. **判读规则正式稿**（草案见 A-6，阈值数字需用户逐个确认后提交）。
2. **对冲对设计**（防「平移不是校准」，D2 §二.3）——两个选项：
   - (a) **门禁守卫方案**（建议）：若采样时放行侧（offset > 0）零错误，则偏好对
     为 DENY 方向单一来源 + 预注册的「放行侧不塌」门禁做防平移守卫；
   - (b) **高温诱导方案**：提高采样温度（1.0–1.2）专门放大 ALLOW 侧错误以构造
     对冲对——风险是 rejected 质量更差、配对噪声更大。
3. **DPO 超参预算**（建议：TRL DPOTrainer，beta 0.1、lr 5e-7、epochs 1、
   per_device_batch 2 + grad_accum 4、max_length 2048——**注意 LOG-20260905-02：
   偏好对文本含工具 schema 时按实际渲染长度留余量，训练后必查 loss**）。

### A-1 预注册（先于一切运行）

判读规则正式稿 + 运行清单（产物目录逐字声明）写进 `task_plan.md` 并提交。
产物前缀 `reports/retail_ops/v1/r11-dpo/`（新前缀，避免激活历史命名空间）。

### A-2 偏好对采样器（CPU 实现 + TDD，零 GPU/API）

- **输入任务面**（两个都 TDD 挂进采样器）：
  - 政策边界探针 `build_policy_boundary_tasks(seed=0)`（15 偏移 × 8 = 120，确定性）；
  - C3 交叉面 `build_policy_boundary_phrasing_tasks(seed, index, partition="ood_dev")`
    （措辞 = bank-004 的 `ood_dev` 分片 247 条——**未用于任何训练与评测**；
    `index` 由 `load_phrasing_bank` + 按分片过滤得到，装置会校验池深度）。
- **采样协议**：每个任务从当前策略（NF4 基座 + sft-008 adapter）temperature 0.8
  采 N=8 条轨迹；逐条过环境执行 + verifier。
- **配对规则**（TDD 断言）：
  - DENY 任务（offset < 0）：chosen = Oracle 轨迹（get_order → 拒绝答复，逐位确定）；
    rejected = 该任务采样中**真实发生**的「执行退款」轨迹（violation
    `refund_not_eligible`）；无此类样本的任务跳过；
  - ALLOW 任务（offset > 0）：按 A-0 第 2 点的用户裁定执行（建议 a：跳过并报告）；
  - 同任务内去重；配对必须带 `task_id` + `sample_index` 溯源。
- **规模**：预期 100–200 对（D2 §二.4）；实际配对数与方向分布写进采样报告。

### A-3 GPU 采样（~1.5h，零 API）

`run_dpo_sampling.py`（新脚本，mypy 覆盖）或复用评测路径 + 采样包装；断点续跑
（done.json 按任务）。产物：`reports/retail_ops/v1/r11-dpo/sampling-001/`。

### A-4 DPO 训练管线（TDD）

- 新 build pipeline `dpo`（config-driven，照 `pipeline: sft` 的模式）或独立脚本；
  `DPOTrainer`（TRL 1.8.0）+ QLoRA NF4 基座 + **sft-008 adapter 起始**；
  ref model = 初始策略冻结副本（TRL peft 模式自动处理，写测试锁定）；
  `configure_training_determinism` 复用；`metrics.json` 含 `determinism.provenance`；
  输出目录不可覆盖；训练后自动断言 loss 曲线非零（把 LOG-20260905-02 的教训
  变成机器守卫）。
- 产物：`reports/retail_ops/v1/r11-dpo/dpo-001/`（~30–60 min GPU）。

### A-5 三面评测（~40 min GPU）

探针（确定性仪器）+ dev 60 + `ood_dev` 60（措辞分布外）。配置照既有评测形态；
产物 `reports/retail_ops/v1/r11-dpo/eval-*/`。

### A-6 判读（预注册草案——正式稿经用户确认后提交，一个字不改地用）

| 分支 | 判据 | 后续 |
|---|---|---|
| **修好** | 探针 `offset −14` 恢复 ≥ 0.9 且其余 14 偏移保持 1.00 且 dev 60 ≥ 58/60 且 `ood_dev` ≥ 0.95（现 0.9833） | 换候选 `sft-008-dpo-001`；代价（如有）成对报告 |
| **修坏** | 任一放行侧偏移跌破 1.00 − 0.1，或 dev/`ood_dev` 退化 | 不换候选；记录负结果 |
| **没动** | `offset −14` 仍 < 0.5 且其余不变 | 假设错（SFT 停滞假设的 DPO 版被证伪），停 |

**无论哪种结果**：不重跑、不换采样素材再试、判读只用可迭代面（探针/dev/`ood_dev`）。

### A-7 若「修好」→ 发布判定（独立小节，单独提交预注册）

1. 新 OOD 封存分片 **bank-005**（mimo 生成，`retail_ops_ood_v2_4_20260906`，照 v2.3
   先例逐字段；只观测一次）；
2. 封存 holdout **观测 8**（base + `sft-008-dpo-001` merged 两份 sealed 评测）；
3. `release --gate_schema_version 1.3`（带 `--*_trajectories` 与 OOD 证据）——
   **绝对门 `policy_violation_count_max=0` 是否从 2 变 0 是最终判据**；
4. 台账追加（HOLDOUT_LEDGER 观测 8、OOD_SEALED_LEDGER v2.4、LOG、EXECUTION_PLAN）；
   对外材料按新口径成对陈述。
5. 若 A-7 时启用了轨道 B-2 的 v1.4 schema（见下），release 配置声明 `1.4`——
   两个变更**不要**悄悄捆绑：v1.4 是否在这次判定启用，单独问用户。

---

## 5. 轨道 B（并行项）

### B-1 C3 交叉面 GPU 读数（~40 min；可与 A-3 共会话）

`retail_ops_policy_boundary_phrasing_v1_20260904` 交叉面（120 任务，Oracle 自洽
已完成）上的 base + `sft-008` 评测读数——装置就绪后一直没取数。读数写 findings
并按「该迭代面同时看见边界型与措辞型退化」的口径陈述。

### B-2 I-2b → gate schema **v1.4** 路径（TDD；小）

`inference_engine` / `runtime_env_sha256` 纳入配对 = pairing 语义变更。**合规路径
只有新增版本化集合**（照 `GATE_IDS` v1.2→v1.3 的模式）：`SEALED_PAIRING_FIELDS_V1_4`，
v1.0–v1.3 逐字节不动；启用时机 = A-7 的发布判定（需用户单独确认，不捆绑）。

### B-3 gate schema 政策明文化（TDD；小）

治理测试固化：「新发布配置的 `gate_schema_version` 必须等于最新版本」——D4 实践
上已如此，补机器守卫。

### B-4 C4 + 难度分层 → 合并数据重建（**R2 量级，本窗口只立项不出工**）

C4 两项（max_steps 4→6、reason 口径 A）与难度分层切分（PITFALLS 入口 7）的
证据链成本都是「新 dataset_version + 全部重跑」，C4 自己的建议是**合并成一次
数据重建**。本窗口的交付物 = 一份立项方案（分层算法、新配额、teacher 预算、
判读规则、与既有口径的可比性断裂清单），**经用户确认预算后独立立项**——不与
DPO 混在同一窗口执行（它会让 DPO 的预注册判读失效）。

### B-5 （可选，低优先）去 NF4 过延迟门

D4 的 per_call 已 1.112 PASS；该问题的边际价值小。若做：消耗观测 9（sft-008
未合并 + fp16 形态）。**建议缓**——DPO 产生新候选后该问题要在新候选上重问。

---

## 6. subagent 使用规范（沿用）

探索 / code review / 可并行独立小任务可用；读数与结论必须抽查（自己复算或测试
验证）。阶段性 scoped re-review：A-7 判定落盘后，对「预注册符合性、台账追加、
新口径成对陈述」做一次。

## 7. 硬边界（全部沿用）

- 封存 holdout 与 OOD 封存分片的结果**永远不得反馈进开发**——D4 的违规 2 与
  观测 7 全部读数，不得出现在 DPO 的数据选择、调参、候选选择里；
- 已证伪方向 8 条不得重试（`PITFALLS.md` §三）；DPO 数据构造不得变相复活它们；
- 不改 v1/v2 冻结契约（§2 表）；I-2b 只能走 v1.4 新版本路径；
- 不为了让数字好看改任务、关守卫或挑读数；历史文档 append-only；
- 判读规则与运行内容**必须在观测之前写定并提交**；观测必须在代码冻结提交之后；
- 每条远程 GPU 命令给出工作目录 / 物理 GPU / 预计时长 / 产物；偏离清单先停下
  确认；API 费用逐次记账；
- Python 统一 `uv`；文档默认简体中文；origin push 是已批准的同步手段。

## 8. 验收（每轮收口全绿）

```bash
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy
env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check
git diff --check
.venv/bin/python scripts/ci/verify_qualification_chain.py
.venv/bin/python scripts/ci/audit_public_release.py
```

## 9. 故障手册指针

- 训练 loss 全零（截断/mask 问题）：LOG-20260905-02 + `run_v3_degradation.py`
  的 max_seq_len 注释；
- gpu-5090 驱动卡死：E2 交接 §5.5；
- preflight 自检门：E2 交接 §5.1–5.2；
- teacher/bank 生成失败（分片覆盖、回环丢弃）：LOG-20260905-03 与 bank-004 先例；
- cpolar 隧道 host key 变更：`task_plan.md` Errors 表；
- 双进程并行事故：LOG-20260905-02 事件三（单实例验证流程）。
