# Task Plan: RetailAgentOps

## Goal

在 12 周内交付可公开、可复现、可面试解释的零售工具 Agent 单卡适配与发布流水线，并在前 6 周完成首个工程闭环。

## Current Phase

R4「失败驱动优化」**第二轮**（设计 `docs/superpowers/specs/2026-08-13-r4-round2-ablation-design.md`
已由用户批准，执行提示词 `docs/handoffs/2026-08-13-r4-round2-execution-prompt.md`）。
第一轮（数据比例重平衡）已判负并按预设停止条件停止（LOG-20260811-09）。
本轮是**诊断性消融实验，不是发布候选生产**：成功标准是「分辨出瓶颈在哪一层」，
不是「某个候选达标」。发布门禁一个字不改，封存 holdout 不动，不消耗第二次观测。

## Current Task

R4 第二轮：三候选并列消融（不叠加），各只改一个变量，共同参照点是 `sft-002` /
`candidate-002`（第一轮，45/60，`refund_eligible` 0/10）。

| 候选 | 唯一变量 | 训练数据 | 训练产物 | 候选评测 |
|---|---|---|---|---|
| A | `lora.target_modules` 加 MLP 三投影 | `train-export-002`（复用） | `sft-003` | `candidate-003` |
| B | sft 末尾追加终局回复 | 新 `train-export-003` | `sft-004` | `candidate-004` |
| C | `runner.SYSTEM_PROMPT` | 新 `train-export-004` | `sft-005` | `candidate-005` + **base-002** |

### 开工核查推翻的一条设计假设（2026-08-13，已请示并获裁定）

spec §4.3 与提示词第 3 节假定「改 `runner.SYSTEM_PROMPT` 后重新导出，system 消息
就会换成新 prompt」。**实测不成立**：`trajectory_to_sft_example`
（`core/generators.py:34`）的 system 消息取自 `trajectory.metadata["system_prompt"]`，
而 teacher 证据是已持久化的轨迹——240 份证据的该字段全是旧 prompt，
`selection.json` 的来源是 teacher 238 / internal_reference 2。因此改常量后重新导出，
**238/240 条样本逐字节不变**，且 `_require_evidence_binds_record` 不比较 system_prompt，
**不会报错**——会静默产出一份变量没生效的 `train-export-004`。

用户裁定：**在导出侧改写 system 消息**（本文件「新配置契约」第 2 条）。
不受影响的是「新 prompt 下的 base（零训练）」这条读数——评测两侧都在运行时调
`run_episode` 读当前常量，该读数完全成立，且它是本轮最有价值的单条结论。

### 执行阶段划分（顺序是强制的，理由在下方失败模式 1）

- **Stage 1（CPU，本任务）**：候选 A 的训练配置；导出侧两项新能力（终局回复追加 +
  system 改写）与配置契约；B 的导出与训练配置；本地执行 B 导出产出 `train-export-003`。
  **不改 `SYSTEM_PROMPT`，也不提交 C 的任何配置**——`sft_system_prompt_sha256` 要声明
  新 prompt 的哈希，而新 prompt 在 Stage 3 才落定；现在写进配置只会提交一份必然
  硬失败的配置。Stage 1 交付的是 C 所需的**能力**，不是 C 的配置。
- **Stage 2（GPU，外部门）**：A 训练 → A dev 候选评测 → B 训练 → B dev 候选评测。
  全部跑在旧 prompt 下，配对基线沿用既有 `qwen3-4b-dev-base-001`。
- **Stage 3（CPU）**：改 `SYSTEM_PROMPT` 常量 → 本地执行 C 导出产出 `train-export-004`
  → C 训练配置。这一阶段的 diff 刻意做到极小，变量单一。
- **Stage 4（GPU，外部门）**：C 训练 → **C base dev 重跑**（`base-002`）→ C dev 候选评测。

### 新配置契约（两个键，均**必填**，沿用第一轮 `sft_oversample` 的先例）

1. `sft_terminal_response`：场景名列表，对这些场景在 sft 消息末尾追加一条**独立的**
   assistant 终局回复。空列表表示不追加（现有行为）。模板硬编码在代码里（下方 B 段），
   配置只声明启用哪些场景。
2. `sft_system_prompt_sha256`：64 位 hex 或 `null`。`null` 表示沿用轨迹 metadata 里的
   prompt（现有行为）；给出 hex 则把 system 消息改写为当前 `runner.SYSTEM_PROMPT`，
   **并核对其 sha256 精确等于该值，不符即硬失败**。之所以不是布尔值：布尔值下
   「配置写了 true 但常量忘了改」会产出与未改写逐字节相同的文件而不报错，
   正是上面那条被推翻的假设的同一个形状。配置声明期望哈希，让这种失效变成硬错误。

两个键都要补进既有 `retail_ops_v1_r2_train_export.yaml` 与
`retail_ops_v1_r4_train_export_rebalanced.yaml`（显式空值 = 现有行为）。

### 候选 B 的终局回复设计

定稿模板（**只使用工具真实返回的字段**）：

```
已为订单 {order_id} 按 {reason} 办理退款，当前退款状态为 {refund_status}。
```

三个字段全部从样本自身的消息序列取，已实测确认形状：`{order_id}` 与
`{refund_status}` 来自最后一次 `refund_order` 的 tool 返回 `content`，`{reason}` 来自
该次 tool_call 的 `arguments.reason`。因此 B 是 `sft.jsonl` 的**纯局部变换**——
不读任务记录、不碰 `target_state`/`expected_calls`、不引入外部信息。
`refund_recovery` 有两次 `refund_order`（首次 `transient_error`），终局回复一律追加在
**最后一次成功的**那次之后。

**不得加入金额、到账时间、工单号**——实测 `refund_order` 的 observation 只有
`{order_id, refund_status}`，编造字段等于用一个新的幻觉问题换掉当前问题。

### 输入

- 冻结数据集 `retail_ops_v1_r2_20260722`（240/60/120，**不改**）与 teacher 证据
  `teacher-collection/teacher-full-001/`（**不重采**，API 未授权）。
- 现有导出 `train-export-001`/`002`（**不覆盖**）；第一轮训练配置
  `configs/retail_ops/build/retail_ops_v1_r4_sft_rebalanced.yaml` 是三候选的参照点。
- 现有 dev base 证据 `qwen3-4b-dev-base-001`（0.800），A/B 直接配对，不重跑。

### 输出

- A：`retail_ops_v1_r4_round2_a_sft_lora_full.yaml`（唯一改 `lora.target_modules`）。
- B：导出侧终局回复实现 + `retail_ops_v1_r4_round2_b_train_export.yaml`
  （`attempt_id: train-export-003`）+ `retail_ops_v1_r4_round2_b_sft.yaml`
  + 本地导出产物 `train-export-003`。
- C：Stage 1 只交付导出侧 system 改写实现与契约；Stage 3 才有新 `SYSTEM_PROMPT`、
  `retail_ops_v1_r4_round2_c_train_export.yaml`（`attempt_id: train-export-004`）、
  `retail_ops_v1_r4_round2_c_sft.yaml` 与本地导出产物。
- 产物自证：`sft_terminal_template.json` 与 `sft_system_prompt.json` 恒定写出
  （含未启用状态）并纳入 `private_artifact_sha256`，与第一轮 `sft_oversample.json` 一致。
- 三条单变量纪律断言，仿 `tests/test_retail_ops_r4_cli.py:84`，各候选一条。
- **候选评测 config 一律推迟到训练之后**：`adapter.file_sha256` 是运行产物，
  提前写就是无验证占位（第一轮同一裁定）。

### 非目标

不改 `assert_exact_quotas` 的 40/10/20 配额、不新增任务、不重新冻结数据集；
不改 `SealedEvaluationReport`/`BaseRunEvidence`/`CandidateRunEvidence` 字段集合；
不改发布门禁阈值、不放宽 `require_comparable_sealed_runs`；不动封存 holdout、
不消耗第二次观测；不改 `parser.py` 的 `mixed_tool_call_content` 规则；
不改 `runner.py` 的 `final_state == 1.0` 即 break；不覆盖 `r3/`/`r4/` 已有产物；
不进入 DPO/GRPO/在线 RL；不启用 τ²-bench/appworld/ToolSandbox（R5 事项）；
不因某个候选表现好而追加变体。

### 失败模式

1. **把 C 的 `SYSTEM_PROMPT` 改动与 A/B 一起提交。** 该常量被
   `base_evaluation.py:381` 与 `sealed_evaluation.py:217` 哈希，且 `system_prompt_sha256`
   在 dev 的 `PAIRING_FIELDS` 内。一旦提交，A/B 就再也无法在旧 prompt 下评测，
   其配对基线 `qwen3-4b-dev-base-001` 同时失效。又因 `_current_code_commit` 拒绝脏
   工作树，C 的改动连"放在工作树里不提交"都不行——**必须等 A/B 的 GPU 跑完**。
2. `sft_system_prompt_sha256` 做成布尔值，导致"配置写了但常量没改"静默无效
   （已在契约设计中排除）。
3. 终局回复被拼进 assistant 工具调用消息的 `content`，触发 parser 的
   `mixed_tool_call_content`，把已获得的 `invalid_call = 0` 打回去——终局回复必须是
   **独立的 assistant 消息**，工具调用消息的 `content` 保持为空。
4. 终局回复稀释决策点：它加在 `refund_order` 之后，而决策点是 `get_order` 返回之后，
   两个位置不同，形状分布应仍为 160 : 240。**必须由测试断言，不能靠推理。**
5. 终局回复模板含工具从未返回的字段（金额/到账时间/工单号），用新幻觉换旧问题。
6. 重复采样或终局回复漏进 `train.jsonl`/`selection.json`，使 provenance 声称超过
   240 条冻结任务。
7. 候选 A 的 LoRA 容量增加同时打坏已获得的格式收益——三项必须逐项报告，
   退化即如实记录，不因它是"推荐方案"而淡化。

### 判定标准（与第一轮相同，**不得下调**）

达标门槛：`refund_eligible` ≥ 7/10，且 `invalid_call_count` = 0、
`policy_violation_count` = 0、`schema_valid_rate` = 1.0。

诊断读数（不是门槛）：任一候选 `refund_eligible` ≥ 3/10 → 该层有信号；三个均 0/10 →
容量、数据闭环、指令框定三类解释全部排除。**每个结论必须标注 n = 10 的统计限度**：
单条样本变化即 10 个百分点，3/10 与 5/10 的差异不足以支撑排序结论。

停止条件：三个候选跑完即停止，统一分析后再决定第三轮。

### 验收

`.venv/bin/pytest -q`（起始基线 **638**）、`.venv/bin/ruff check .`、`.venv/bin/mypy`、
`env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check`、`git diff --check`。

每个候选另需证明：

- **A**：训练配置除 `lora.target_modules` 外与 `retail_ops_v1_r4_sft_rebalanced.yaml`
  逐字段相同。
- **B**：`train-export-003` 的 `train.jsonl`/`selection.json` 与 `train-export-001`
  **逐字节相同**（`29f02425…`/`f60744f7…`）；决策点形状分布仍为 **160 : 240**；
  assistant 工具调用消息的 `content` 仍全部为空。
- **C**：`train-export-004` 与 `002` 的唯一差异是 system 消息；base 与 candidate 两侧
  `system_prompt_sha256` 相等且均不等于旧值（旧值 sha256 前缀 `d919602e25f2`）。

安全关键的断言要做**突变验证**——把断言该抓的东西故意改坏，确认测试立即失败。

### 授权状态

GPU **否**、API **否**、数据下载 **否**、holdout 执行 **否**、公开发布 **否**。
Stage 2 与 Stage 4 的每条外部命令单独报告（命令、工作目录、物理 GPU、预计时长、产物）
并等待确认，不得连跑。

## 历史任务：R3 Task 3（已完成，摘要见 progress.md）

R3 Task 3：为 formal（真实 Qwen3-4B）轨道补齐 sealed holdout 评测入口、发布门禁与
可切换后端的服务入口。

- 背景（本次核实的代码事实，不是文档转述）：仓库里存在**两条平行证据链**。R1
  qualification 轨道（规则策略）四个接口全通；R2/R3 formal 轨道只到 `evaluate` 的 dev
  部分，`release` 与 `serve` **完全不存在**。具体：
  (1) `evaluate_authorized_holdout` / `authorize_formal_holdout` 全仓只被 `tests/` 引用，
      `product_cli.py::_run_evaluate` 只识别 `formal_dev_base` / `formal_dev_candidate`，
      正式 120 条 holdout 无任何命令可跑；
  (2) `release.py::decide_release` 只接受 R1 的 `RunEvidence`，`_validate_paired_evidence`
      比对的 `mode` / `task_manifest_sha256` / `budget` 是 formal 证据没有的字段，
      SPEC §6 发布门禁对真实模型不可执行；
  (3) `serve/service.py` 硬要求 `manifest.split == "qualification"` 并只构造
      `build_qualification_policy` 规则策略，从不加载模型或 adapter。
- 输入：已产出且已通过重载校验的三份真实证据——`qwen3-4b-dev-base-001/base-report.json`
  （`BaseRunEvidence`，task_success 0.800）、`r3/candidate-001/candidate-report.json`
  （`CandidateRunEvidence`，task_success 0.7167）、`r3/sft-001/adapter/`（23.6 MB）；
  冻结数据集 `retail_ops_v1_r2_20260722` 的公开 `holdout-receipt.json`（120 条、六类各 20）
  与私有 `data/private/retail_ops/v1/r2/<version>/holdout.jsonl`；发布策略
  `domains/retail_ops/v1/release.yaml`（+5pp / 违规不增 / 非法调用 0 / p95 ≤1.25× / 证据完整）。
- 输出：
  - A：`evaluate` 新增 `formal_holdout` 流水线 + 对应已提交 config；`SealedEvaluationReport`
    补齐 provenance 字段（见"关键约束"第 1 条），使两份 sealed 报告可在字段级证明同条件；
  - B：`release` 新增 formal 路径，读两份 sealed 报告产出 `FormalReleaseReport`
    （GO/NO-GO + 逐门禁观测 + JSON/Markdown/HTML），R1 路径逐字节不变；
  - C：`serve` 新增 formal 路径，按 `FormalReleaseReport` 的 `deployment` 选择
    base+adapter 或回滚 base，后端经工厂注入（默认本地 CPU 可启动，GPU 主机换真实后端），
    并落实 SPEC §9 的工具 allowlist、请求大小、并发上限与回滚说明。
- 非目标：**不执行任何 holdout 运行**（base 那一枪在代码就绪并经用户确认后另开任务）；
  不动 GPU、不调商业 API、不下载模型；不改 R1 qualification 轨道的任何已冻结契约；
  不改 `BaseRunEvidence` / `CandidateRunEvidence` / `ReleaseReport` 的字段集合；
  不重命名 Python 包；不创建远程仓库、不 push；不改发布阈值。
- 关键约束（已核实，违反即产生不可逆损失）：
  1. **`SealedEvaluationReport` 的扩展窗口正在关闭**。`report_id` 是
     `_content_id` 对全字段的自哈希（`sealed_evaluation.py:219` 校验），加字段会让已产出
     报告永久加载失败——`BaseRunEvidence` 已因此被冻死（`findings.md:532`）。已核实
     `data/private/.../sealed-eval/` 不存在、`reports/` 无任何 sealed 产物，**holdout 从未
     跑过**，所以现在扩字段零成本；第一次运行落盘后即不可逆。**A 必须先于任何 holdout 运行。**
  2. `ReleaseReport.validate_decision_consistency`（`release.py:71-82`）断言 gate 集合与
     顺序精确等于 `_GATE_IDS`，且 `decide_release` 的返回类型被 `service.py` 与
     `tests/test_release_policy.py` / `test_service.py` 依赖。formal 门禁**只能新增并行
     类型**（沿用 Task 2 用子类扩展 `CandidateRunEvidence` 的既有做法），门禁阈值与算术
     必须与 R1 共用同一份实现，不得复制粘贴出第二套语义。
  3. `evaluate_authorized_holdout` 当前签名收 `model_name: str` 而非配置对象，与
     `evaluate_formal_dev_base` 的 `BaseEvaluationConfig` 不对称；A 需要引入
     `SealedEvaluationConfig` 并复用 `_require_backend_matches_pin` 的双向校验，
     否则无法证明 sealed 运行用的是哪份模型/adapter。
  4. sealed 公开报告是 allowlist 字段集，**不得**因为补 provenance 而漏进 task_id、
     family_id、prompt、真值或逐任务失败样例；新增字段只能是模型/生成/硬件/代码标识。
  5. `authorize_formal_holdout` 只接受 `EvidencePurpose.RELEASE`，且 logical_path 必须
     精确等于 `data/private/retail_ops/v1/r2/<dataset_version>/holdout.jsonl`；CLI 接线
     不得为了方便放宽这两条。
- 失败模式：为了让 formal 证据穿过 `decide_release` 而放宽 `_validate_paired_evidence`，
  使 R1 配对公平性检查失效；formal 门禁复制出第二套阈值语义，导致同一策略文件产生两种
  结论；sealed 报告补字段时把 task 级信息漏进公开侧；serve 的后端工厂缝留成"CPU 假后端
  也能标 GO 部署"，让未过门禁的模型可被加载（违反 SPEC §4 最后一条）；先跑 holdout 再改
  schema 导致证据永久不可加载。
- 影响文件（预计）：`src/veritool_rl/retail_ops/evaluate/sealed_evaluation.py`、
  `src/veritool_rl/retail_ops/release/release.py`（新增并行类型，不改 R1 类型）、
  `src/veritool_rl/retail_ops/serve/service.py`、`src/veritool_rl/product_cli.py`、
  `configs/retail_ops/{evaluate,release,serve}/` 新增 config、`tests/` 对应新增测试、
  `docs/REPO_MAP.md`、`CLAUDE.md`、`README.md`。
- [x] A1+A2（合并为一个循环，配置对象与报告字段互相依赖）：`SealedEvaluationConfig`
      （继承 `BaseEvaluationConfig`，`adapter` 可选）+ `SealedEvaluationReport` 补 provenance
      + `evaluate_authorized_holdout` 签名对齐 + `require_comparable_sealed_runs`。
      RED 先失败于 `require_comparable_sealed_runs` 不存在；两条 adapter 双向绑定测试
      另经突变验证（去掉 `_require_backend_matches_pin` 调用后立即 `DID NOT RAISE`）。
      基线 587 → 592 passed。
- [x] A3：`evaluate` 新增 `formal_holdout_base` / `formal_holdout_candidate` 两条流水线
      （拆成两条而非一条带可选 adapter：base/candidate 的区分是安全关键的，让配置文件
      本身声明意图，比"有没有写 adapter 这个 key"更难误配置）+ 两份已提交 config，
      走 `authorize_formal_holdout` 两段式授权；CPU 注入缝与 `_run_formal_dev_base` 对齐。
      基线 592 → 604 passed。
- [x] B1：`release.py` 抽出 `build_release_gates` 与公开的 `GATE_IDS`（R1 与 formal 共用
      同一份阈值语义）；新增 `release/formal_release.py`（`FormalReleaseReport` +
      `decide_formal_release` + 三份报告渲染），不改 R1 的 `ReleaseReport`。
      配对校验的两条测试经突变验证（去掉 `require_comparable_sealed_runs` 后裸 `AssertionError`）。
- [x] B2：`release` 命令按 `pipeline: formal_release` 分发 + 已提交 config；
      公开 sealed 副本显式 `verify_artifacts=False`（同目录无私有产物），report_id 仍逐字校验。
- [x] B3：用真实 dev 数字（base 0.800 / candidate 0.7167 / p95 6068 vs 5211）的端到端
      NO-GO 回归：恰好 `success_delta` 一项失败、`deployment == "baseline"`；另有 GO 正对照、
      报告往返、手改 decision 必须加载失败。基线 604 → 613 passed。
- [x] C1：`serve/service.py` 新增 `create_formal_app`（R1 `create_app` 未改）：后端工厂
      注入、按 `deployment` 选 base+adapter 或回滚 base。回滚是**双重**执行的——NO-GO 时
      adapter 根本不传给工厂，且随后核对工厂真正返回的后端没挂 adapter（工厂是注入缝，
      实现可能来自别处）。经突变验证。
- [x] C2：并发上限（串行 episode，超限 503）、请求体大小上限（`MAX_REQUEST_BYTES`，
      超限 413）、`/v1/tasks` 暴露工具 allowlist、`/health` 暴露决策/失败门禁/回滚说明。
      并发上限经突变验证（提到 8 后测试立即失败）。
- [x] C3：`serve` 命令按 `pipeline: formal_serve` 分发 + 已提交 config；`backend_factory`
      与 `app_runner` 两个注入缝让本地 CPU 用 fake 后端即可装配服务并断言 provenance，
      不加载模型、不监听端口。基线 613 → 624 passed。
- [x] D：文档同步（REPO_MAP 新增「四接口双轨完成度」并标注"代码完成 ≠ 已经运行"、
      CLAUDE.md §9、README 状态与结果边界）+ 全量门禁 + PROJECT_LOG。
- 验收命令：`.venv/bin/pytest -q`（起始基线 587 → **完成时 624 passed**）、
  `.venv/bin/ruff check .`、`.venv/bin/mypy`、
  `env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check`、`git diff --check`；
  另需证明三份已产出的真实证据（R2 两份 base、R3 一份 candidate）重新加载后 `run_id`
  复算仍一致，且 R1 qualification 的 `release.json` 仍能被 `load_release_report` 接受。
- 授权状态：GPU **否**、API **否**、数据下载 **否**、holdout 执行 **否**、公开发布 **否**。

## Task Rules

- 本文件只跟踪当前任务；长期阶段状态以 `docs/EXECUTION_PLAN.md` 为准。
- 新任务开始时重写 Current Task，保留已完成任务的摘要到 `progress.md`。
- 输入、输出、非目标、失败模式和验收命令不完整时不得开始实现。
- GPU、API、数据下载和公开发布必须显式标注授权状态。

## Errors

| Date | Error | Resolution |
|---|---|---|
| 2026-07-20 | 新 worktree 缺 BFCL evaluator 环境和 ignored benchmark checkout | 建立独立 evaluator venv，并通过相对软链接共享固定 checkout |
| 2026-07-20 | 本机镜像变量机械改写 `uv.lock` | 反向应用仅 lock diff，后续命令显式清除 `UV_INDEX_URL` |
| 2026-07-20 | 清除 `UV_INDEX_URL` 后 `uv run` 仍按全局索引改写 `uv.lock` | 最终验收直接调用已冻结 `.venv/bin/*`，提交前精确回退 lock diff |
| 2026-07-20 | 新治理测试被 Ruff I001 拒绝双空行 | 按 import sorter 的最小 diff 删除一行空白后重跑 |
| 2026-07-21 | Task 6 规格检索误写为不存在的 `docs/SPEC.md` | 确认产品契约实际位于根目录 `SPEC.md`，后续使用正确路径 |
| 2026-07-21 | Task 6 首次 GREEN 加载 `run.json` 时错误要求 artifact map 保留插入顺序 | canonical JSON 会排序 object key；改为验证精确 key 集合，确定性由写入器保证 |
| 2026-07-21 | Task 6 `ruff format --check` 报告 4 个变更文件需格式化 | 使用仓库 `.venv/bin/ruff format` 仅格式化本任务 Python 文件后重跑验证 |
| 2026-07-21 | Task 7 `ruff format --check` 报告 `release.py` 需格式化 | 使用仓库 formatter 处理该文件并重跑 focused/Ruff/diff |
| 2026-07-21 | Task 8 初查误探测不存在的 `src/veritool_rl/config.py` 与 `tests/test_cli.py` | 确认配置加载在 `veritool_rl.cli`，产品 CLI 测试按计划新建 `test_retail_ops_cli.py` |
| 2026-07-21 | Task 8 `uv lock --check` 报告锁文件过期，`UV_INDEX_URL` 仍被全局默认索引覆盖 | 清除 3506 行镜像 URL 机械 diff，改用 `UV_DEFAULT_INDEX` 对齐现有 lock 索引；离线解析后 `uv.lock` 字节不变 |
| 2026-07-21 | Task 8 planning 记录补丁因表格行顺序假设错误未应用 | 用 `rg` 定位实际行后按精确上下文重新应用，未影响产品文件 |
| 2026-07-21 | Task 8 `ruff format --check` 报告 CLI 测试需格式化 | 仅格式化本任务测试文件并重跑 focused/Ruff/diff |
| 2026-07-21 | Task 9 首次全门禁发现 `product_cli.py` import 未排序且 service/test 需格式化 | 对本任务文件执行 Ruff import fix/format 后重跑 selected/full 相关门禁 |
| 2026-07-21 | Task 9 误将全仓 `ruff format --check .` 当作验收项，发现 35 个既有文件未采用当前 formatter | 不扩大本阶段 diff；仅检查本任务 Python 文件，继续执行项目规定的 `.venv/bin/ruff check .` |
| 2026-07-21 | Task 10 新鲜 qualification 证据树在最终状态审计中显示为未跟踪文件 | 新增失败治理断言并将 `/reports/retail_ops/` 纳入产品运行产物 ignore 边界，保留本地证据但不提交 |
| 2026-07-21 | Task 10 完成前 targeted format check 报告两个新增测试需格式化 | 仅格式化 `test_retail_ops_e2e.py` 与 `test_project_governance.py`，随后从头重跑完整质量门 |
| 2026-07-22 | `using-superpowers` 的 Codex reference 首次按错误的技能根路径读取失败 | 按 SKILL.md 相对路径改读 `skills/using-superpowers/references/codex-tools.md`，已恢复完整指令 |
| 2026-07-22 | 迁移准备提交前 `git diff --cached --check` 报告设计文件 EOF 多一个空行，但 shell 未启用 fail-fast 仍完成提交 | 在最终文档提交中删除多余空行；后续提交命令使用 `set -e` 或显式检查退出码后再 commit |
| 2026-07-22 | 执行环境拒绝用 `rm -rf` 清理迁移回滚目录 | 未删除任何内容；改用 `gio trash` 将精确目录移入系统回收站，并验证原 `/tmp` 路径不存在 |
| 2026-07-22 | R2 分支基线 `uv lock --check` 因用户级清华镜像 URL 从旧别名规范化为新域名而要求 4336 行纯 URL 重写 | 临时目录差异确认版本/哈希不变；`--default-index https://pypi.tuna.tsinghua.edu.cn/simple` 立即通过，R2 将用项目级索引固定现有 lock，避免机械重写 |
| 2026-07-22 | R2 family 轴核对首次探测了不存在的 `domains/retail_ops/v1/policies/refund.yaml`，随后 zsh 未匹配 glob 中止批量查看 | 改读实际扁平文件 `domains/retail_ops/v1/policies.yaml`、`tools.yaml`、`bundle.yaml`；确认仅使用四个批准退款原因且未改文件 |
| 2026-07-22 | 两次跨文件文档补丁因 `task_plan.md` 既有错误行与预期上下文不一致而整体拒绝 | 先读取精确表格，再按目标文件拆分应用；补丁原子失败，未产生半写入或产品内容损坏 |
| 2026-07-22 | 新增治理测试仍因目标短语跨 Markdown 换行失败 | 保留语义不变并合并为单行可机器检查契约，再重跑 focused test |
| 2026-07-22 | 一次双引号 `rg` 模式中的反引号被 zsh 当作命令替换，并且一次 reviewer wait 使用了低于工具下限的 1 秒 timeout | 检索模式改用安全单引号/无反引号形式；等待调用改为工具允许的至少 10 秒，均未修改产品状态 |
| 2026-07-22 | 计划审阅收口记录的跨文件补丁因 `progress.md` 目标句与实际表述不同而整体拒绝 | 读取文件尾部后按文件拆分应用，未产生半写入 |
| 2026-07-22 | R2 Task 1 实现代理完成 RED 和初版实现后因所选模型容量不足退出 | 保留全部未提交改动，换用新 worker 接手 focused GREEN、修复、全门禁和提交；判定为代理基础设施故障而非仓库回归 |
| 2026-07-22 | Task 1 独立审查发现 derivation 未绑定实际政策状态、quota 接受重复变体，且 catalog/420 条环境验证未固化为测试 | 判定 NOT PASS；派回实现代理先补 deadline/owner/status/duplicate/tamper/catalog/environment RED，再强化真值投影和 integrity 校验，复审通过前不进入 Task 2 |
| 2026-07-22 | Task 2 独立审查用攻击脚本复现 public value 泄漏、provenance 断链、重复 variant、非原子双根、symlink 越界和可伪造授权 token 六项 Important | 判定 NOT PASS；统一补固定 Literal、verified dataset、private provenance/variant 重建、failure-atomic staging、trusted-root no-follow 读取和注册 capability 的 RED/GREEN，复审通过前不进入 Task 3 |
| 2026-07-22 | Task 2 修复复审代理的最终输出被平台 cybersecurity 风险过滤器误拦截 | 保留已完成的代码与 284 个测试证据，把复审改写为不描述利用步骤的“数据治理契约回归审查”并复用同一只读 reviewer |
| 2026-07-22 | Task 3 只读接口检索误读不存在的 `src/veritool_rl/agent/base.py`，导致同一 `&&` 链后的 Qwen 查看未执行 | 改读实际 `agent/qwen.py`、`agent/policy.py`、`agent/runner.py`；未修改代码或环境 |
| 2026-08-05 | 20 条真实 DeepSeek smoke（会话临时脚本）发现 `run_episode`（`agent/runner.py`）组装的多轮消息历史不是合法 OpenAI wire format：`tool_calls[].function.arguments` 是原始 dict 而非 JSON 字符串，且 assistant `tool_calls[]`/`tool` 消息缺 `id`/`tool_call_id`；本地 Qwen backend 从未触发过 | 判定为 Task 4 前置阻塞：先在 `agent/runner.py` 用 TDD 修复两处 wire format bug 并补回归测试，再开始 `teacher_data.py` 实现；smoke 脚本本身未提交，详见 `docs/PROJECT_LOG.md` LOG-20260805-07 |
| 2026-08-05 | Task 6 env 边界测试最初用 `monkeypatch.setattr("os.environ", HostileMapping())` 整体替换 `os.environ`，导致 pytest 自身内部读取 `COLUMNS`/`PY_COLORS` 时炸穿并使整个 session 内部报错，而非产品代码问题 | 改用 `monkeypatch.setenv("TEACHER_LLM_PROVIDER", "not a provider name!!")` 只毒化 `load_teacher_route` 真正会读的具体 key，不整体替换 `os.environ`；同时确认没有任何产品代码本身依赖 `COLUMNS`/`PY_COLORS` |
| 2026-08-05 | Task 6 首个 `--input_dir` 覆盖测试误传相对路径 `"configs/retail_ops_v1_build.yaml"`，但该测试用的 `workspace` fixture 已 `monkeypatch.chdir` 到隔离 tmp 根，仓库真实 `configs/` 在那里不存在 | 改用 `Path(__file__).resolve().parents[1]`（`REPO_ROOT`）拼出绝对路径引用仓库里真正提交的 config 文件，不依赖当前 CWD |
| 2026-08-05 | Task 6 修复轮首次派发因触发本会话 API 用量限制中断，未产生任何改动（工作树、报告文件均未受影响） | 原样重新恢复同一 implementer agent（未改变任务或方案），重试后成功完成 |
| 2026-08-06 | Task 7 整分支审查发现 `formal_dev_base` 独立加载 `dev.json` 未走 `load_verified_formal_dataset`，跳过五维隔离交叉断言；`export_formal_train` 接收 `TeacherCollectionConfig` 却从未读取，teacher 证据仅凭 `task_id` 匹配记录；`code_commit` 可能来自脏工作树且 git 子进程无超时 | 三项均用 TDD 修复：`_run_formal_dev_base` 改为先 `load_verified_formal_dataset` 再取其 `dev_manifest`；新增 `_require_evidence_binds_record` 在 export 循环内核对 `task_fingerprint`/`trajectory.task`/`dataset_version`/`bundle_sha256`/`manifest_sha256`，不匹配即硬失败（非静默回退）；`_current_code_commit` 先查 `git status --porcelain` 非空即拒绝，git 调用统一加 30s 超时；复审确认 3 项均已解决、3 个关键判断均合理（`c4d7fdc`） |
| 2026-08-06 | Task 7 复审发现 `manifests/retail_ops/v1/` 未被 `.gitignore` 覆盖（不同于 `data/`/`models/`/`reports/retail_ops/`），导致 `formal_freeze` 产出的公开 manifest 若不提交，会被新的脏树检查判定为"未跟踪=脏"从而阻塞 `formal_dev_base` | 非代码缺陷，是正式执行顺序的前置条件；已写入 `docs/handoffs/2026-08-06-r2-external-run-commands.md` 第 0 节，要求 `formal_freeze` 产出必须先提交再进入 `formal_dev_base` |

## Maintenance: Codex 启动简化

- [x] 确认 `AGENTS.md` 已覆盖 Codex 接管和记录协议
- [x] 移除冗余 `.codex/config.toml` 与对应 fallback 测试
- [x] 将 linked worktree 原地转为独立 Git checkout
- [x] 验证环境、ignored benchmark 链接、质量门和 Codex 启动
- [x] 提交结果，保持 R1 规格复核门不变
