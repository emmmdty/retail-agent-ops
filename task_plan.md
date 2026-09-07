# Task Plan: RetailAgentOps

## Goal

在 12 周内交付可公开、可复现、可面试解释的零售工具 Agent 单卡适配与发布流水线。
R0–R10 已完成，质量收口两轮完成，DPO 主线与 B-4/v5 数据重建全链完成；
阶段状态以 `docs/EXECUTION_PLAN.md` 为准，历史任务摘要在 `progress.md`。

## Current Task: v6 迭代预注册（空生成诊断 + rtc_stepwise 请求修复 → 冲击 v1.3 GO）（2026-09-07）

**上一任务（B-4/v5 数据重建全链）已完成并收口**：观测 8（封存 246 条，v5 口径首观测）
判定 **NO-GO（11/12）**——候选 1.0000/pv0，**绝对门 `policy_violation_count_max=0`
历史首次 PASS**（B-4 根因主张被观测证实）、ci_lower +0.3699；唯一失败门
`invalid_call_count=2`（两次空生成 parse 滑步，0.8%，成功任务内恢复）。
A-6 第三分支升级后用户裁定如实收官、候选不变（sft-008）。
LOG-20260907-01；HOLDOUT_LEDGER 观测 8；RESUME_EVIDENCE §1.11。

**执行入口**：`docs/handoffs/2026-09-07-v6-iteration-execution-prompt.md`

### A-0 裁定（2026-09-07，用户逐项确认，遇到不再重开）

1. **范围**：先诊断后定——V6-1 空生成根因诊断先行（不占封存观测，**禁用封存集
   提示词作诊断输入**）；诊断指向**数据侧**可修项则一并入 v6，指向**引擎栈**则
   单独评估（不与数据修复捆绑）。v6 数据侧确认单变量 = rtc_stepwise 请求修复（V6-2）。
2. **dataset_version**：`retail_ops_v6_20260907`（按冻结日命名；冻结若顺延至次日则
   全链改用 `retail_ops_v6_20260908`，二选一后一致）。v5 冻结集逐字节不动。
3. **判读规则**：v1.3 十二门 + 探针每点 ≥ 0.875，阈值一个字不改；分支表为下方
   三分支完整划分。**v1.4 配对 schema 不启用**：观测 9 沿用
   `--gate_schema_version 1.3`（v1.4 路径已建，首用时单独决策）。

### 判读规则（v6 正式稿——冻结，一个字不改地用）

1. **GO**：v1.3 十二门全 PASS 且探针 15 偏移每点 ≥ 0.875 → 换候选 `sft-v6-001`；
   对外材料按新口径成对陈述。
2. **NO-GO**：十二门中任一 FAIL，或探针任一点 < 0.875 → 不换候选；如实收官；
   失败门按观测形状**只作事实记录**（不附加「路径穷尽」类机械解读；本分支天然
   覆盖「11/12 但非绝对门」等全部组合）；不重跑、不换素材、不向封存集重掷骰子。
3. **边界组合**：证据不完整 / 配对被拒 / 运行中断等导致判定面不成立 → 升级用户
   确认，不自动判任何分支。

无论哪种结果：台账（HOLDOUT_LEDGER 观测 9、PROJECT_LOG、EXECUTION_PLAN）同日收口；
封存结果永远不反馈进开发。

### 运行清单（产物目录逐字声明；smoke/先验审查产物先补声明再运行）

| # | 运行 | 产物目录 |
|---|---|---|
| V6-1a | 空生成静态诊断（本地 CPU：max_seq_len / 停止符 / 解析栈检查 + dev 同 family 提示词导出） | `reports/retail_ops/v1/r13-v6/emptygen-static-001` |
| V6-1b | 空生成重放诊断（gpu-5090，同权重对 dev 同 family 提示词重放 N 次统计空生成频率；命令逐条确认后执行） | `reports/retail_ops/v1/r13-v6/emptygen-replay-001` |
| V6-2 | rtc_stepwise 请求修复（TDD：请求 reason ∈ cancel 枚举且与 gold 一致；v4/v5 重建逐位不变；版本键控 v6 生效；代码+测试，无评测产物） | （无产物目录） |
| V6-3-1 | formal_freeze v6（本地 CPU）+ 覆盖表落盘验收（沿用 `assert_exact_quotas_v5` 全部断言） | `data/private/retail_ops/v1/r2/retail_ops_v6_20260907` + `manifests/retail_ops/v1/retail_ops_v6_20260907` + `reports/retail_ops/v1/r13-v6/coverage-v6-001` |
| V6-3-smoke | teacher 小样本冒烟（mimo，会话头必设；大规模采集前 1 次直连试探 ~250 tok） | `data/private/retail_ops/v1/r2/retail_ops_v6_20260907/teacher-collection/teacher-v6-smoke-001`；CLI output_dir 占位 `reports/retail_ops/v1/r13-v6/teacher-smoke-run-000`（流水线不写入） |
| V6-3-2 | teacher 全量采集（mimo，~588 任务，0.80 分桶门 + **采集前新增断言：请求陈述的 reason/fact 落在该工具枚举域内**） | `data/private/retail_ops/v1/r2/retail_ops_v6_20260907/teacher-collection/teacher-v6-001`；CLI output_dir 占位 `reports/retail_ops/v1/r13-v6/teacher-run-001`（流水线不写入） |
| V6-3-3 | train_export（本地 CPU，措辞 ×3 沿用 bank-v4） | `data/private/retail_ops/v1/r2/retail_ops_v6_20260907/train-export/train-export-v6-001` + `reports/retail_ops/v1/r13-v6/train-export-001` |
| V6-3-4 | dev_sft_export（本地 CPU，Oracle） | `data/private/retail_ops/v1/r2/retail_ops_v6_20260907/dev-sft/dev-sft-v6-001`；CLI output_dir 占位 `reports/retail_ops/v1/r13-v6/dev-sft-run-001`（流水线不写入） |
| V6-4-1 | 训练 `sft-v6-001`（gpu-5090 GPU 0，~35 min；命令清单逐条确认后执行） | `reports/retail_ops/v1/r13-v6/sft-v6-001` |
| V6-4-2 | v6 dev 评测：base + candidate（配对） | `reports/retail_ops/v1/r13-v6/dev-base-001` / `reports/retail_ops/v1/r13-v6/dev-candidate-001` |
| V6-4-3 | OOD v2 评测：candidate + base（**v6 代码 commit 变 → base 必须重跑**，配对字段含 code_commit） | `reports/retail_ops/v1/r13-v6/ood-v2-candidate-001` / `reports/retail_ops/v1/r13-v6/ood-v2-base-001` |
| V6-4-4 | OOD v4 评测：candidate + base（同上） | `reports/retail_ops/v1/r13-v6/ood-v4-candidate-001` / `reports/retail_ops/v1/r13-v6/ood-v4-base-001` |
| V6-4-5 | 探针评测（−14 曲线是绝对门的先行指标） | `reports/retail_ops/v1/r13-v6/probe-candidate-001` |
| V6-4-6 | v6 封存 holdout 观测 9：base + candidate | `reports/retail_ops/v1/r13-v6/holdout-base-009` / `reports/retail_ops/v1/r13-v6/holdout-candidate-009` |
| V6-4-7 | `release --gate_schema_version 1.3`（OOD 两门证据取 V6-4-3 的 v2 dev 分片平铺导出；v4 为辅助读数） | `reports/retail_ops/v1/r13-v6/formal-release-009` |

**输入**：交接 §5（V6-0..V6-4 规格）、`docs/PITFALLS.md` §二 #25/#26、
`docs/HOLDOUT_LEDGER.md` 观测 8、
`src/veritool_rl/retail_ops/domain/formal_tasks.py` v5 段（`_V5_*` 常量、
`_v5_bucket_allocation`、`build_v5_task_set`——v6 结构起点）、
v5 冻结配置先例（`configs/retail_ops/build/retail_ops_v5_formal_freeze.yaml`）。
**输出**：空生成根因结论 + 是否可修的判定（不可修则残差风险如实进预注册预期段）；
rtc_stepwise 请求修复（与 gold cancel reason 同源，v4/v5 重建逐位不变）；v6 生成器 +
`assert_exact_quotas_v6`（沿用 v5 全部断言）+ 覆盖表；teacher 采集（枚举域自查
前移为采集前断言）；train/dev 导出；`sft-v6-001`；全套评测读数；观测 9 + v1.3
判定落盘。
**非目标**：不改 v1–v5 冻结契约与既有数据集；探针网格、OOD v2/v2.2/v2.3/v4 任务集
逐字节不动；不动发布门禁阈值（0 / +0.02）；不碰 BFCL holdout；空生成的引擎栈修复
不在本轮捆绑（诊断指向引擎栈则单独评估）；bank-005 永不进入评测面；发布候选
`sft-008` 在判读出结果前保持不变；不启用 v1.4 配对 schema。
**影响文件**：`src/veritool_rl/retail_ops/domain/formal_tasks.py`（v6 版本常量 +
RTC_STEPWISE 请求分支版本键控修复 + v6 生成器）、
`src/veritool_rl/retail_ops/build/formal_manifests.py`（v6 登记）、
sealed/eval config 的 dataset_version 校验、`configs/retail_ops/build/`（v6 冻结配置）、
teacher 采集枚举域断言（采集侧自查，PITFALLS #26 教训前移）、
`tests/test_retail_ops_v6_tasks.py`（新）。
**验收命令**：§验收命令全量（pytest / ruff check / ruff format --check / mypy /
uv lock --check / git diff --check / qualification chain / audit）；V6-3-1 后另附
覆盖表读数；V6-4-7 后附 release.json 三件套与逐门判定。

### 上一任务：B-4/v5 数据重建全链（2026-09-06/07，已完成，判定 NO-GO 11/12）

（判定与读数见 EXECUTION_PLAN「B-4/v5 数据重建全链」节、HOLDOUT_LEDGER 观测 8、
LOG-20260907-01、findings 2026-09-07 各节。**其预注册原文（A-0 裁定、判读规则、
V5 运行清单）存档于本文件下方**——运行清单是声明守卫的绑定对象（r12-v5 目录已
落盘），不得删除；判读规则与阈值已按观测 8 履行完毕，v6 不得沿用其分支形状
（见新交接 §5 判读注意事项）。）

**A-0 裁定（2026-09-06，用户逐项确认，遇到不再重开）**：

1. **结构范围**：场景集与 family 结构沿用 v4_20260905（含 rtc_stepwise train-only
   辅助场景）；切分键换难度分层。
2. **reason 口径 A 映射表（判分契约，冻结）**：受损（damaged）→ `{damaged}`；
   发错货（wrong_item）→ `{wrong_item}`；不符描述（not_as_described）→
   `{not_as_described, damaged}`；不想要（changed_mind）→ `{changed_mind}`。
   cancel 类 reason（`_V4_CANCEL_REASONS`）**保持精确匹配、不进口径 A**。
3. **判读阈值**：按 A-6 草案逐字冻结（见下表）。
4. **v1.4 配对 schema 不启用**：v5 的发布判定沿用 `--gate_schema_version 1.3`。

**轨道 B（负结果分析，本窗口已完成，不进入判读）**：B-a 简历/面试叙事
（`RESUME_EVIDENCE.md` §1.5 第 10 行 + 新增 §1.10 + §2 不可写新行 + §4 计数 9→10；
`INTERVIEW_PREP.md` §2.3 DPO 问答改写实测版 + §3 失败案例 #12）；B-b 探针三模型
平移对比图 `scripts/ops/plot_policy_boundary_shift.py`，产物
`reports/retail_ops/v1/r11-dpo/probe_shift_curve.png` + `.csv`
（文件位于已声明的 r11-dpo 命名空间内，非目录，不触发声明守卫）。

**判读规则正式稿（冻结，一个字不改地用）**：

| 分支 | 判据 | 后续 |
|---|---|---|
| **修好** | v1.3 十二门全 PASS（含绝对门 `policy_violation_count_max=0`、`success_delta_ci_lower ≥ +0.02`、OOD 两门）且探针无单点塌方（15 偏移每点 ≥ 0.875） | 换候选 `sft-v5-001`；对外材料按新口径成对陈述 |
| **修坏** | 任一门 FAIL（尤其绝对门）或探针/`ood_dev` 出现单侧塌方形状 | 不换候选；负结果入账；绝对门路径就此穷尽，如实收官 |
| **边界改善但未达标** | 十二门 PASS 但探针单点 < 0.875（或反之） | 依预注册分支细则，升级需用户确认 |

无论哪种结果：不重跑、不换素材再试；判读只用可迭代面（探针/dev/`ood_dev`）+
一次性封存观测 8；台账（`HOLDOUT_LEDGER.md` 观测 8、`PROJECT_LOG.md`、
`EXECUTION_PLAN.md`）同日收口。封存结果永远不反馈进开发。

**运行清单（产物目录逐字声明；smoke/先验审查产物先补声明再运行）**：

| # | 运行 | 产物目录 |
|---|---|---|
| V5-1 | formal_freeze v5（本地 CPU）+ 覆盖表落盘验收（5.0×→~1.0× 机器证明） | `data/private/retail_ops/v1/r2/retail_ops_v5_20260906` + `manifests/retail_ops/v1/retail_ops_v5_20260906` + `reports/retail_ops/v1/r12-v5/coverage-v5-001` |
| V5-2-smoke | teacher 小样本冒烟（mimo，措辞先验审查用） | `data/private/retail_ops/v1/r2/retail_ops_v5_20260906/teacher-collection/teacher-v5-smoke-001`；CLI output_dir 占位 `reports/retail_ops/v1/r12-v5/teacher-smoke-run-000`（流水线不写入） |
| V5-2 | teacher 全量采集（mimo，~700 任务，接受率 ≥0.80 分桶门禁） | `data/private/retail_ops/v1/r2/retail_ops_v5_20260906/teacher-collection/teacher-v5-001`；CLI output_dir 占位 `reports/retail_ops/v1/r12-v5/teacher-run-001`（流水线不写入） |
| V5-3 | train_export（本地 CPU，措辞 ×3 无 oversample） | `data/private/retail_ops/v1/r2/retail_ops_v5_20260906/train-export/train-export-v5-001` + `reports/retail_ops/v1/r12-v5/train-export-001` |
| V5-4 | dev_sft_export（本地 CPU，Oracle） | `data/private/retail_ops/v1/r2/retail_ops_v5_20260906/dev-sft/dev-sft-v5-001`；CLI output_dir 占位 `reports/retail_ops/v1/r12-v5/dev-sft-run-001`（流水线不写入） |
| V5-5 | 训练 `sft-v5-001`（gpu-5090 GPU 0，~35 min；命令清单逐条确认后执行） | `reports/retail_ops/v1/r12-v5/sft-v5-001` |
| V5-6 | v5 dev 评测：base + candidate（配对） | `reports/retail_ops/v1/r12-v5/dev-base-001` / `reports/retail_ops/v1/r12-v5/dev-candidate-001` |
| V5-7 | OOD v2 评测（既有分片，跨候选可比） | `reports/retail_ops/v1/r12-v5/ood-v2-candidate-001` |
| V5-7b | OOD v2 评测：零训练基座（**2026-09-07 补声明**：v1.3 的 `ood_success_delta_min ≥ 0` 门需要同条件 base 读数，candidate-only 清单是缺口；同 commit 配对） | `reports/retail_ops/v1/r12-v5/ood-v2-base-001` |
| V5-8 | OOD v4 评测 | `reports/retail_ops/v1/r12-v5/ood-v4-candidate-001` |
| V5-8b | OOD v4 评测：零训练基座（同上补声明） | `reports/retail_ops/v1/r12-v5/ood-v4-base-001` |
| V5-9 | 探针评测（−14 曲线是绝对门的先行指标） | `reports/retail_ops/v1/r12-v5/probe-candidate-001` |
| V5-10 | v5 封存 holdout 观测 8：base + candidate | `reports/retail_ops/v1/r12-v5/holdout-base-008` / `reports/retail_ops/v1/r12-v5/holdout-candidate-008` |
| V5-11 | `release --gate_schema_version 1.3`（OOD 两门证据取 V5-7/V5-7b 的 v2 dev 分片平铺导出；v4 为辅助读数） | `reports/retail_ops/v1/r12-v5/formal-release-008` |

**输入**：交接 §4（DPO 负结果三条设计约束）/§5（轨道 A 规格）、
`docs/PROPOSAL_DATA_REBUILD_B4.md`（分层算法/配额/断裂清单）、
`docs/POLICY_BOUNDARY.md` §2（覆盖表与 5.0× 复算测试）、
`formal_tasks.py`（v1/v4 生成器与 `assert_exact_quotas_v4`——结构起点）、
v4 冻结配置先例。
**输出**：v5 生成器 + `assert_exact_quotas_v5`（分层键 + margin 0 档 + 覆盖表断言）、
口径 A（可接受集合承载 + verifier 版本化，旧证据复算逐位不变）、max_steps 6
（sealed config Literal 同步）、`formal_manifests.py` v5 登记、Oracle 自洽 +
「措辞 → 结果」关联检查、覆盖表机器证明。
**非目标**：不改 v1–v4 冻结契约与既有数据集；探针网格、OOD v2/v2.2/v2.3 任务集
逐字节不动；不动发布门禁阈值（0 / +0.02）；bank-005 永不进入评测面；
不碰 BFCL holdout；发布候选 `sft-008` 在判读出结果前保持不变。
**影响文件**：`src/veritool_rl/retail_ops/domain/formal_tasks.py`（v5 生成器 +
`assert_exact_quotas_v5`）、`src/veritool_rl/retail_ops/build/formal_manifests.py`
（v5 Literal）、verifier 的 reason 集合判定（版本化）、sealed config Literal、
`configs/retail_ops/build/`（v5 冻结配置）、`tests/test_retail_ops_v5_tasks.py`（新）。
**验收命令**：§验收命令全量（pytest / ruff / format / mypy / lock / diff /
qualification / audit）；A-3 后另附覆盖表读数。

## 上一任务：DPO 主线（R11，已收口 = 修坏，2026-09-06）

判定修坏：候选 `sft-008` 不变、D4 的 NO-GO 维持；`sft-008-dpo-001` 不进入任何
候选比较或对外材料。负结果四层分析（事实/机制/设计/量化）见
`docs/handoffs/2026-09-06-b4-data-rebuild-execution-prompt.md` §4；
LOG-20260906-01；PITFALLS §三 #9。本窗口的叙事与可视化落点见上方「轨道 B」。

### DPO 预注册（2026-09-06 A-0 三个方案点经用户确认，先于一切运行提交）

**A-0 裁定（2026-09-06，用户确认）**：

1. **判读规则**：按 A-6 草案逐字冻结（见下表）。
2. **对冲对设计**：**门禁守卫方案**——采样确认放行侧（offset > 0）零错误后，
   偏好对为 DENY 方向单一来源；防平移由预注册的「放行侧不塌」门禁（修坏分支：
   任一放行侧偏移 < 0.90 即判负）承担。高温诱导方案被否。
3. **DPO 超参**：TRL 1.8.0 DPOTrainer、beta 0.1、lr 5e-7、**epochs 3（2026-09-06
   修订，用户裁定：R11-1 实际产出 27 对——预注册确认时按 D2 预估 100–200 对冻结的
   epochs 1 只产 ~4 个优化步，功效不足；epochs 3 ≈ 12 步。判读规则与阈值一字不动，
   修订发生在任何训练观测之前）**、per_device_batch 2 + grad_accum 4、max_length
   2048；训练前按实际渲染长度实测留余量，训练后自动断言 loss 曲线非零（smoke 只要求
   有限非零，正式运行要求末端下降——LOG-20260905-02 教训变机器守卫）。

**实现说明（预注册的一部分，先于运行声明；2026-09-06 两次修订见 Errors 表：
bank-005 生成 → bank-004 确认健在后经用户裁定回退，采样面回到原预注册）**：
- 偏好对采样器的输入任务面 = `build_policy_boundary_tasks(seed=0)`（120 条）+
  `build_policy_boundary_phrasing_tasks(seed=0, bank-004 ood_dev 分片, partition="ood_dev")`
  （120 条）；采样配置的 bank pin（relpath/sha256 `f4b14e8d…`）与 D4 sealed
  构建配置同源。bank-004 本地健在（Errors 表更正行），rsync 同步到远端后运行；
  bank-005 为多余素材永不进入评测面。
- 配对规则：DENY 任务（offset < 0）chosen = Oracle 轨迹（逐位确定）、
  rejected = 该任务采样中真实发生的 `refund_not_eligible` 违规轨迹；无此类样本
  的任务跳过；同任务内按内容去重；配对携带 `task_id` + `sample_index` 溯源。
  ALLOW 任务（offset > 0）不产对，只进前提检查与报告。
- **偏离路径（先写定）**：放行侧采样若出现执行类错误，采样报告如实记录、
  **停止并回用户决策**——不得悄悄构造对冲对。
- DPO 起始权重 = `models/Qwen3-4B-sft-008-merged`（合并部署形态，SHA-256
  `70981220…` 与观测 5 逐位一致）——它是「NF4 基座 + sft-008 adapter」的确定性
  合并形态，也是发布候选的部署形态；在其上加新 LoRA（TRL peft 模式下
  ref model = 禁用 adapter 的基座 = 初始策略冻结副本，写测试锁定）。

**判读规则正式稿（冻结，一个字不改地用）**：

| 分支 | 判据 | 后续 |
|---|---|---|
| **修好** | 探针 `offset −14` 恢复 ≥ 0.9 且其余 14 偏移保持 1.00 且 dev 60 ≥ 58/60 且 `ood_dev` ≥ 0.95（现 0.9833） | 换候选 `sft-008-dpo-001`；代价（如有）成对报告 |
| **修坏** | 任一放行侧偏移跌破 1.00 − 0.1，或 dev/`ood_dev` 退化 | 不换候选；记录负结果 |
| **没动** | `offset −14` 仍 < 0.5 且其余不变 | 假设错（SFT 停滞假设的 DPO 版被证伪），停 |

无论哪种结果：不重跑、不换采样素材再试、判读只用可迭代面（探针/dev/`ood_dev`）。
A-7（bank-006 + 封存观测 8 + release v1.3）只在「修好」分支且**单独预注册提交后**
才执行；v1.4 schema 是否在判定启用单独问用户。

**运行清单（产物目录逐字声明）**：

| # | 运行 | 产物目录 |
|---|---|---|
| R11-1 | 偏好对 GPU 采样（探针 120 + 交叉面 120，每任务 N=8，~1.5h） | `reports/retail_ops/v1/r11-dpo/sampling-001` |
| R11-2-smoke | DPO 管线自检（4 对 1 步；**不进入任何判读**） | `reports/retail_ops/v1/r11-dpo/dpo-smoke-001` |
| R11-2 | DPO 训练（gpu-5090 GPU 0，~30–60 min；epochs 3） | `reports/retail_ops/v1/r11-dpo/dpo-001` |

（附属文件：`reports/retail_ops/v1/r11-dpo/pairs-smoke-001.jsonl` 为 R11-2-smoke 的输入子集，由 pairs.jsonl 前 4 行生成；`dpo-001.log`/`sampling-001.log` 为运行日志。均不进入判读。）
| R11-3 | 探针评测：`sft-008-dpo-001` | `reports/retail_ops/v1/r11-dpo/probe-dpo-001` |
| R11-4 | dev 60 配对评测：`sft-008-dpo-001` | `reports/retail_ops/v1/r11-dpo/dev-candidate-dpo-001` |
| R11-5 | `ood_dev` 60 评测：`sft-008-dpo-001` | `reports/retail_ops/v1/r11-dpo/ood-dev-candidate-dpo-001` |

**B-1（并行）运行清单（产物目录逐字声明）**：

| # | 运行 | 产物目录 |
|---|---|---|
| B1-0 | C3 交叉面任务集构建（远端 CPU，bank-004 `ood_dev` 分片） | `reports/retail_ops/v1/policy-boundary-phrasing/tasks` |
| B1-1 | 交叉面评测：零训练基座（GPU 0） | `reports/retail_ops/v1/policy-boundary-phrasing/base` |
| B1-2 | 交叉面评测：`sft-008` 合并形态（GPU 0） | `reports/retail_ops/v1/policy-boundary-phrasing/sft-008` |

**输入**：交接 §4/§5；`DPO_ENTRY_EVIDENCE_D2.md`（设计宪法）；POLICY_BOUNDARY §4–§6
（探针基线：`sft-008` 14/15 偏移 1.00、`offset −14` 塌 0.375）；两个装置源码。
**输出**：偏好对采样器（CPU TDD）、GPU 采样产物与采样报告（实际配对数与方向分布）、
DPO 训练产物、三面评测读数、三分支判读落盘。
**非目标**：不改 v1/v2 冻结契约；不碰 rtc（机制不同，D1 已修）；D4 读数不反馈进
DPO 的数据选择/调参/候选选择；已证伪方向 8 条不得变相复活；A-7 不在本预注册内。
**影响文件**：`src/veritool_rl/retail_ops/build/dpo_sampling.py`（新）、
`src/veritool_rl/training/dpo.py`（新）、`scripts/retail_ops/run_dpo_sampling.py`（新）、
`configs/retail_ops/build/`（dpo 配置，新）、`tests/test_dpo_*.py`（新）。

### 上一任务：GPU 执行阶段 C2/D1/E2/D4（2026-09-04 → 2026-09-06，已完成）

**纯 CPU 部分**（9 个 commit，`3121e7d` 止）：Phase A 审计与修复（5C+7I）、
Phase B v1.3 门禁上线与阈值冻结（0 / +0.02，LOG-20260904-01/02）、Phase B3 诊断重算、
Phase C1/C3 CPU 部分、Phase C4/D2/E1 决策文档、Phase F 测试补齐与治理收口。
**GPU/API 部分**（入口 `docs/handoffs/2026-09-04-gpu-phase-c2-d1-e2-d4-execution-prompt.md`）：
C2 方差验证、D1 rtc 第四轮（甲→乙，修好）、E2 退化曲线真读数（装置四层修复）、
D4 一次性 v1.3 判定（NO-GO）——读数与台账见 LOG-20260905-01/02/03 与各收口文档。
用户已批准 gpu-5090 与 mimo-v2.5 端点；决策门 #1/#4/#6 已关闭（#4 由用户于
2026-09-06 重新打开并裁定启动 DPO）。

### 已关闭的决策门（2026-09-04；#4 于 2026-09-06 重开）

| # | 决策 | 结论 |
|---|---|---|
| 1 | v1.3 阈值 | 冻结 0 / +0.02 |
| 4 | DPO | ~~D4 之后再说~~ → 2026-09-06 用户裁定启动（新窗口入口见上） |
| 6 | 宽工具面迁移 | 不迁移（发布口径维持 v1/v2） |

### D1 rtc 第四轮——方案甲实现机制（2026-09-04 用户选定：A family 覆盖）

**输入**：round4 交接 `docs/handoffs/2026-08-23-r9-phase-b-round4-execution-prompt.md`
（判读规则已预注册，一个字不改地用）+ 本阶段交接 §4 第 2 步 + 用户 2026-09-04 对
实现机制的选项 A 裁定（family 覆盖，新 dataset_version，全量 mimo 重采集）。
**输出**：新数据集 `retail_ops_v4_20260904`（CANCEL_* 4 场景 family 扩到 10 态 × 5 语境
= 50，state 7–9 使用新增 margin 档 4/6/12，train 35 / dev 5 / holdout 10；其余 8 场景
20/5/10 不变）、teacher-v4-004
（mimo，~600 train 任务）、`train-export-v4-004`（措辞 ×3，无 oversample）、候选
`sft-004`、三面评测（v4 dev / OOD v2 / OOD v4）。
**非目标**：方案乙不获确认不动工；不调 rtc oversample 权重；不改 parser /
max_steps / verify_final_state；不改发布门禁阈值；不消耗封存 holdout 观测；
v1/v2 冻结契约与 `assert_exact_quotas`（v1）不动；OOD v2 / OOD v4 任务集不动；
发布候选仍是 sft-008。
**影响文件**：`src/veritool_rl/retail_ops/domain/formal_tasks.py`（v4 family 扩展 +
`assert_exact_quotas_v4`）、`src/veritool_rl/retail_ops/build/formal_manifests.py`
（新版本 Literal）、`tests/test_retail_ops_v4_round4_tasks.py`（新）、5 份 build 配置、
3 份 eval 配置、`docs/R9_PHASE_B_RESULTS.md`、findings/progress。
**判读**：按 round4 交接第四步的预注册表执行（rtc dev ≥ 8/10 且 OOD v4 rtc ≥ 5/10
且 pv 不升 → 修好；改善但未达线 → 甲→乙升级需用户确认；无改善或 pv 恶化 → 停）。
teacher 接受率门禁 ≥ 0.80；DENY 类措辞沿用 R9「评估/判断」式先验。

**运行清单（产物目录逐字声明）**：

| # | 运行 | 产物目录 |
|---|---|---|
| R4-0 | formal_freeze（本地 CPU） | `data/private/retail_ops/v1/r2/retail_ops_v4_20260904` + `manifests/retail_ops/v1/retail_ops_v4_20260904` |
| R4-1 | teacher_collect（mimo，~600 任务） | `data/private/retail_ops/v1/r2/retail_ops_v4_20260904/teacher-collection/teacher-v4-004`；CLI output_dir 占位 `reports/retail_ops/v1/r9/round4/teacher-run-004`（流水线不写入） |
| R4-2 | train_export（本地 CPU） | `data/private/retail_ops/v1/r2/retail_ops_v4_20260904/train-export/train-export-v4-004` + 公开报告 `reports/retail_ops/v1/r9/round4/train-export-004` |
| R4-3 | dev_sft_export（本地 CPU，Oracle） | `data/private/retail_ops/v1/r2/retail_ops_v4_20260904/dev-sft/dev-sft-v4-004`；CLI output_dir 占位 `reports/retail_ops/v1/r9/round4/dev-sft-run-004`（流水线不写入） |
| R4-4 | 训练 sft-004（gpu-5090 GPU 0，~25 min） | `reports/retail_ops/v1/r9/round4/sft-004` |
| R4-5 | v4 dev 评测（GPU 0） | `reports/retail_ops/v1/r9/round4/dev-candidate-004` |
| R4-6 | OOD v2 评测（GPU 0） | `reports/retail_ops/v1/r9/round4/ood-v2-candidate-004` |
| R4-7 | OOD v4 评测（GPU 0） | `reports/retail_ops/v1/r9/round4/ood-v4-candidate-004` |

**已知坑（round4 交接第五步，逐条执行）**：远端工作树必须干净；训练前换入 SFT 格式
`dev.jsonl`、评测前换回 TaskSpec 格式；adapter `file_sha256` 从远端 `sha256sum` 现算；
输出目录不可覆盖。

### D4 一次性 v1.3 发布判定（2026-09-06 预注册，观测前提交）

**性质**：本阶段的收口动作。C2/D1/E2 已收口且代码全部提交（代码冻结 `39f0068`+）。
**判定口径**：v1.3 十二门逐门读（GATE_IDS_V1_2 十门 + `policy_violation_count_max=0`
+ `success_delta_ci_lower_min=+0.02`，阈值已于 2026-09-04 冻结）。
**预期结果（诚实预判，不是规则的一部分）**：NO-GO——绝对门
`policy_violation_count_max=0` 大概率拦下封存集上的政策违规（观测 5 违规 2、
观测 6 违规 7；B3 诊断性重算已在 v1.3 口径下把两次观测都判 NO-GO）。这不是流程
失败：把 v1.2 OOD 门与 v1.3 绝对门的**首次真实发布判定**写入台账、宣告当前候选
在绝对安全门下不合格，就是 D4 的目的。违规根治的路径是 DPO（用户已裁定 D4 后启动）。
**纪律**：无论结果如何不重跑、不换素材再试；结果不得反馈进任何后续开发。

**运行内容（观测之前固定）**：

| # | 运行 | 产物目录 |
|---|---|---|
| D4-0 | bank-004 生成（mimo 计费，per_intent 90，先 dry_run） | `data/private/retail_ops/v1/phrasing/phrasing-bank-004` |
| D4-1 | 互斥性实测（bank-004 `ood_sealed` vs bank-002/003 全部分片、vs `train-export-007/sft.jsonl` 说法） | 交集必须为 0，结果记 findings |
| D4-2 | 新 dataset_version `retail_ops_ood_v2_3_20260905` 登记 + sealed build config（TDD：相对 v2.2 配置只差 phrasing 段） | `configs/retail_ops/build/retail_ops_ood_v2_3_sealed_build.yaml` |
| D4-3 | OOD v2.3 sealed 分片构建（本地 CPU） | `reports/retail_ops/v1/ood-v2.3/sealed/tasks` |
| D4-4 | OOD 评测：零训练基座（GPU 0） | `reports/retail_ops/v1/ood-v2.3/sealed/base` |
| D4-5 | OOD 评测：`sft-008` 合并形态（GPU 0） | `reports/retail_ops/v1/ood-v2.3/sealed/merged-candidate` |
| D4-6 | 封存 holdout 观测 7：base（GPU 0） | `reports/retail_ops/v1/r10-d4/holdout-base-007` |
| D4-7 | 封存 holdout 观测 7：`sft-008` 合并形态（GPU 0） | `reports/retail_ops/v1/r10-d4/holdout-merged-candidate-007` |
| D4-8 | `release --gate_schema_version 1.3`（带 `--*_trajectories` 与 OOD 证据） | `reports/retail_ops/v1/r10-d4/formal-release-007-v13` |

**判读规则**：v1.3 十二门逐门 PASS/FAIL，总判定 = 全过 GO / 任一 FAIL NO-GO。
OOD 证据（v1.2 门 `ood_task_success_min ≥ 0.70`、`ood_success_delta_min ≥ 0`）
用 D4-4/D4-5 的读数。配对检验（`success_delta_ci_lower`）用 D4-6/D4-7 的私有
trajectories。**台账**：`HOLDOUT_LEDGER.md` 追加观测 7、`OOD_SEALED_LEDGER.md`
追加 v2.3 分片观测、`EXECUTION_PLAN.md` 追加记录、findings 记读数；对外材料
引用判定必须按新口径成对陈述（GO/OOD 成对出现）。观测后 v2.3 分片退役。

### D1 方案乙（2026-09-04 用户确认上乙；预注册后动工）

**方案甲判读（已执行，2026-09-05）**：第二分支「方向对，力度不够」（rtc dev 4/10、
OOD v4 rtc 5/10、OOD v2 pv 4≤7；三面对 sft-003 全面占优）。按 round4 交接，甲→乙升级。

**方案乙规格（round4 交接原文 + 用户 2026-09-04/05 确认）**：新增辅助场景
`rtc_stepwise`——RTC 同一状态拆两段的第一段，只要求「查 B 并取消 B」（复用
cancel_eligible 结构，订单号来自 RTC 的 other_order），与完整 RTC 以约 1:1 混入训练
（rtc train 任务 40 ↔ stepwise 40）。实现：新 dataset_version
`retail_ops_v4_20260905`（版本↔内容双射；dev/holdout 与 v4_20260904 同分布重抽、
task_id 不同——记录在案）；`TaskScenario.RTC_STEPWISE` 只出现在 train split
（dev/holdout 配额 0，评测面不变）；paraphrase 复用 cancel 意图 bucket。

**判读规则（阈值与 round4 表逐字相同，候选 `sft-005`）**：

| 结果 | 判定 | 后续 |
|---|---|---|
| rtc dev ≥ 8/10 且 OOD v4 rtc ≥ 5/10 且 pv 不升 | 修好 | 收口 Phase B |
| rtc 改善但 < 上述线 | 方向对，力度不够 | 甲乙已尽，按第五节限定口径收口 |
| rtc 无改善或 pv 恶化 | 假设错 | 停止，记录负结果，Phase B 就此收口 |

**运行清单（产物目录逐字声明）**：

| # | 运行 | 产物目录 |
|---|---|---|
| E-0 | formal_freeze（本地 CPU） | `data/private/retail_ops/v1/r2/retail_ops_v4_20260905` + `manifests/retail_ops/v1/retail_ops_v4_20260905` |
| E-1 | teacher_collect（mimo，640 任务） | `data/private/retail_ops/v1/r2/retail_ops_v4_20260905/teacher-collection/teacher-v4-005`；CLI output_dir 占位 `reports/retail_ops/v1/r9/round4/teacher-run-005` |
| E-2 | train_export（本地 CPU） | `data/private/retail_ops/v1/r2/retail_ops_v4_20260905/train-export/train-export-v4-005` + `reports/retail_ops/v1/r9/round4/train-export-005` |
| E-3 | dev_sft_export（本地 CPU，Oracle） | `data/private/retail_ops/v1/r2/retail_ops_v4_20260905/dev-sft/dev-sft-v4-005`；CLI output_dir 占位 `reports/retail_ops/v1/r9/round4/dev-sft-run-005` |
| E-4 | 训练 sft-005（gpu-5090 GPU 0，~35 min） | `reports/retail_ops/v1/r9/round4/sft-005` |
| E-5 | v4 dev 评测（GPU 0） | `reports/retail_ops/v1/r9/round4/dev-candidate-005` |
| E-6 | OOD v2 评测（GPU 0） | `reports/retail_ops/v1/r9/round4/ood-v2-candidate-005` |
| E-7 | OOD v4 评测（GPU 0） | `reports/retail_ops/v1/r9/round4/ood-v4-candidate-005` |

**成本预估**：teacher 重采 640 任务（mimo，~1.9M tokens，按 v4-004 实测单任务
~2.9K tok 推算）；训练 ~35 min GPU；三面评测 ~40 min GPU。

## 上一任务：质量收口第二轮——v1.3 绝对门 + 方差治理 + 全面审计（2026-09-04，CPU 部分完成）

**输入**：`docs/handoffs/2026-09-04-quality-closeout-v13-and-audit-execution-prompt.md`（用户已批准）。
**输出**：Phase A–F 中纯 CPU 可完成项；GPU/API/决策门项备料后停。
**非目标**：不重试 PITFALLS §三 8 条已证伪方向；不改 v1/v2 冻结契约；
不为了让数字好看改任务、关守卫或挑读数；不改写历史文档（append-only）。

### 执行顺序与状态（2026-09-04 收口）

- [x] **Phase A2**：findings 高/中严重度残余项 TDD 修复（#3 首版修复有两个真 bug：
      `__exit__` 仍锁死调用方、超时轨迹进 replay 崩溃——重修为 daemon 线程 + 共享
      后端锁 + replay 过滤；#5 一致性校验）；低严重度项归宿表入 findings.md。
- [x] **Phase A1**：三 persona subagent code review + 逐条抽查采信；5C+7I 修复
      （全部 TDD + 突变验证）；scoped re-review 通过（3 Minor：2 修 1 记）。
- [x] **Phase B**：v1.3 门禁 TDD（16 条测试 + 4 处突变验证）；阈值 Literal/validator 锁，
      release.yaml 未动；**阈值（0 / +0.02）已于 2026-09-04 经用户确认冻结**。
- [x] **Phase B3**：v1.3 诊断性重算落盘（obs5/obs6 都 NO-GO，符合预期）；历史 GO 并列保留。
- [x] **Phase C1（CPU 部分）**：`configure_training_determinism` + 可消/不可消清单；
      **C2 GPU 双跑验证待决策门 #2**。
- [x] **Phase C3（CPU 部分）**：二维迭代面生成器 + Oracle 自洽 + CLI 组合模式；
      **GPU 评测读数另需授权**。
- [x] **Phase C4**：`docs/PROPOSAL_EVAL_SEMANTICS_C4.md`（缓议建议）→ **停**。
- [x] **Phase D2**：`docs/DPO_ENTRY_EVIDENCE_D2.md`（四项入口条件判定满足）→ **停**。
- [x] **Phase E1**：`docs/TOOLFACE_MIGRATION_ANALYSIS_E1.md`（建议不迁移）→ **停**。
- [x] **Phase F1**：7.2 清单测试补齐 + 治理测试自身 4 处缺陷修复。
- [x] **Phase F2/F3**：治理同步（README/CLAUDE/RESUME_EVIDENCE，1435/1397+38）+
      progress/EXECUTION_PLAN/PROJECT_LOG(LOG-20260904-01) 收口；全量门禁全绿。
- [ ] **Phase D1（rtc 第四轮）/ D3（DPO 训练）/ D4（一次性 v1.3 发布判定）/ E2（退化
      曲线重跑）**：全部需要 GPU / 商业 API / 用户决策门，本轮未执行。

### 测试岗位主管计划（§6，每个功能先列四类用例）

- **#3 超时**：正例=慢策略被 `_run_episode_with_timeout` 在时限内终止并产出
  `INTERNAL_ERROR` 轨迹；反例=快策略不受影响、逐字节等于直接调用；边界=超时值
  极小/充足；突变=去掉 timeout 参数包装，测试必须红。
- **#5 一致性校验**：正例=config 与 manifest 版本一致时正常评测；反例=不一致时
  `evaluate_ood` 必须抛错（种违规必须被抓到）；突变=去掉校验行，测试必须红。
- **v1.3 门禁**：正例=违规 0 且 ci_lower ≥ +0.02 过门；反例=违规 ≥1 必 FAIL、
  ci_lower < +0.02 必 FAIL（含 +0.0083 真实读数形状）；边界=违规恰 0、ci_lower 恰
  等于阈值；突变=注释掉新门断言，测试红；阈值锁=改 `ReleasePolicyConfig` 字段值
  或绕过 YAML 构造非 0/0.02 阈值必须被 Literal 拒绝；向后兼容=v1.0/1.1/1.2 的
  GATE_IDS 逐字节断言 + 既有磁盘报告 report_id 复算。

**验收命令**：`.venv/bin/pytest -q`、`.venv/bin/ruff check .`、`.venv/bin/ruff format --check .`、
`.venv/bin/mypy`、`env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check`、`git diff --check`、
`.venv/bin/python scripts/ci/verify_qualification_chain.py`、
`.venv/bin/python scripts/ci/audit_public_release.py`。

### 上一任务：踩坑与根因总账文档（2026-09-04，已完成）

**已完成**：`docs/PITFALLS.md`（四层根因 + 24 条踩坑 + 8 条已证伪方向 + 解决办法入口）、
`findings.md` 指针条目、面试官视角审查与可解性分析（对话内，要点已收进 PITFALLS §四）。

**下一窗口执行入口**：`docs/handoffs/2026-09-04-quality-closeout-v13-and-audit-execution-prompt.md`
——v1.3 绝对门 + 最小效应宽度、方差治理、二维迭代面、rtc 第四轮、DPO 入口门证据包、
一次性 v1.3 发布判定、宽工具面迁移分析（按简历项目质量定，用户决策）、全面审计
（三 persona subagent）与测试补齐（测试岗位主管标准）。允许 subagent；决策门与
GPU 协议见该文档 §4/§8。

## Current Phase

**R10 推到 8.5+ 已完成**（2026-08-24），但**第 3 项已于 2026-08-27 作废**。

1. v1.2 OOD gate schema + dry-run 验证——新增 `OodEvaluationReport`，与 sealed v1.1 契约兼容；
2. flight_ops 跨域验证——teacher 233/240，dev GO（candidate 1.0000 vs base 0.4833）；
3. ~~工具数退化曲线 0.65 平坦无退化~~ ——**读数作废**（LOG-20260827-01）：
   `tool_count` 当时是空转参数，五个断点看到的是同一批任务和同样的 15 个工具。

探索性结论，不用于发布判定；发布候选仍是 sft-008。

### 2026-08-27 本轮（纯 CPU，已完成）

- 补 Oracle 自洽性测试（gold 序列必须可解且零违规）与断点工具限制测试；
- 撤掉 `skip_reads_gate`（政策守卫不得由任务数据关闭）；
- `RetailOpsEnv` 新增可选 `allowed_tools`，断点真的限制 `env.list_tools()`；
- `REFUND_THEN_CANCEL` 按 v4 已验证的双订单形态重建；
- 干净 clone **实跑**（关掉下面进度表第 10 项）：`88ccabb` 上 1238/46/0
  （与文档中的推算值一致），修复后工作树 1262/46/0，作者环境 1308 passed。

### 2026-08-27 下半场：重跑的装置准备（用户已批准重跑）

**2026-09-05 冒烟门禁修订（用户裁定，留痕）**：装置三轮修复（max_seq_len 1024→3072、
eval 拆分）后，candidate 侧四门全过；base（零训练基座）侧「合法调用率 ≥0.8」未过
（0.75/0.75/0.5833），且该比率随工具面单调下降（tc=3 1.00 → tc=15 0.5833）、
unknown=0/invalid=0——证据指向基座行为（不调用工具）而非装置故障，这正是曲线要测
的自变量效应。裁定：**合法调用率门只约束 candidate 侧**；base 侧低调用率作为曲线
读数如实报告。已落实进 `run_v3_degradation.py::check_smoke_gates`。

**输入**：修复后的 v3 任务集与环境。**输出**：可复现、可排障、小样本先行的重跑流程。
**非目标**：不消耗封存 holdout；不改 v1/v2 冻结契约；不改 prompt/parser；
不为了让数字好看而改任务或关守卫。

- [x] `toolcount_eval.py`：preflight 自检门 + 逐位置 tool-selection 指标 +
      干扰工具调用率 + 基础设施失败单列
- [x] `stratified_sample`：按不同 margin 取值等距抽样，最易/最难两档必在样本内
- [x] runner 重写为 `--profile smoke|full` × `--stage preflight|data|all`，可续跑
- [x] 交接文档 `docs/handoffs/2026-08-27-r10-degradation-rerun.md`（含故障定位手册）
- [x] CPU preflight 两个 profile 各 5 断点全过；全量门禁 1349 passed
- [x] **gpu-5090：小样本采集阶段**（`--stage data`）——5 断点教师接受率
      0.8333/0.9091/0.8333/0.8889/0.9167 全过门禁，导出 15/30/30/32/33 行
- [~] **gpu-5090：小样本 GPU 阶段**——tc=3 训练成功、base 首条真读数产出
      （`success=0.5000 tool_acc=0.7273 distractor=0.2000 infra_err=0`）；
      **被 gpu-5090 驱动卡死中断**（环境故障，见 `findings.md` 同日小节与交接 §5.5）。
      产物全部保留，恢复后从训练阶段续跑、teacher 不再计费。
- [ ] **gpu-5090：大样本**（`--profile full`，约 4–6 h）——**冒烟门禁全绿才做**
- [ ] 读数收口：findings / progress / PROJECT_LOG / EXECUTION_PLAN 更正记录 /
      简历与面试材料里目前写着"读数作废"的段落

**验收判据（冒烟）**：teacher 接受率 ≥0.80；`infrastructure_error_count` = 0；
`tools_presented` 逐字等于断点声明；发出过合法工具调用的 episode ≥80%。
**四条全部与模型好坏无关**——冒烟只证明装置能产出可归因的读数，不设 `task_success` 阈值。

---

## Current Task A（**已改向，原预注册作废并留档**）

### 原方案与它为什么被取消

原 Task A 是「跑第三个训练 seed 做方差刻画」，预注册已于 `0185135` 提交，
`--seed 2` 的训练也已在 gpu-5090 上跑完（产物 `reports/retail_ops/v1/r8/sft-008-rebuild-seed2`）。

**用户 2026-08-19 明确改向**：

> 「多跑一个 seed 的意义不大，我们不是写论文，复现这个的重要程度不如把一个 seed 的
> 效果做得更好。」
> 「你要专注于方法论的质量提升，不要过度局限在文档之类的细枝末节。」

因此原预注册的 R-2…R-9 **全部不执行**：不做 dev 配对评测、不做 OOD v2.3 素材、
**不消耗第七次封存 holdout 观测**。已训出的 seed 2 权重留在原处不做评测，
也不进入任何对外表述——**没有读数就不会有事后挑选的机会**。

原预注册整段保留在 git 历史里（`0185135`），不改写。取消一个预注册本身要留痕：
「跑完了但没报告」与「事先取消且没跑」是两件性质完全不同的事。

### 新方案：把「该拒绝却执行」这条失败模式修掉

**被检验的声称**：候选 `sft-008` 在拒绝类任务上的失败不是随机噪声，
而是学到的**决策边界**与政策边界不重合；这个差可以被量出来，也可以被修小。

**为什么此前修不了**：dev 60（58–60/60）与 ood_dev 60（0.9833、**政策违规 0**）
两个可迭代评测面都已饱和，而封存 120 上是 2–7 次违规、全部 `refund_denied_window`。
**失败模式在可迭代的面上不可分辨**，于是无从下手。

**诊断（只用公开生成器代码，不涉及任何读数）**：冻结数据集按 `sha256(family)`
切 20/5/10，**不对难度分层**。拒绝类场景的难度就是 margin 离边界多远，实测覆盖：

| 场景 | dev 覆盖的 margin 档 | holdout 覆盖的 margin 档 |
|---|---|---|
| `refund_denied_window` | 4/7（缺 2、5、7） | 6/7 |
| `refund_denied_duplicate` | **2/7**（只有 2、5） | 6/7 |
| `refund_denied_ownership` | 5/7 | 5/7，与 dev 只交 3 档 |

且 `offset = 0`（恰好到期）**整个冻结数据集从未生成过**，而它正是政策的判定分界。

### 运行内容

**诊断阶段**（读数决定后续是否修）：

| # | 运行 | 用途 | 产物目录 |
|---|---|---|---|
| P-0 | 构建政策边界探针（CPU） | 评测集 | `reports/retail_ops/v1/policy-boundary/tasks` |
| P-1 | 探针：零训练基座 | 边界基线 | `reports/retail_ops/v1/policy-boundary/base` |
| P-2 | 探针：`sft-008`（当前候选） | 当前边界 | `reports/retail_ops/v1/policy-boundary/sft-008` |

**修复阶段**（判读规则已于 `3cb5619` 写定并提交，早于本阶段全部运行）：

| # | 运行 | 用途 | 产物目录 |
|---|---|---|---|
| F-0 | 网格外状态增强采集与导出（CPU + DeepSeek） | 训练素材 | `reports/retail_ops/v1/r8/state-aug-001` |
| F-1 | 训练 `sft-009`（配置相对 `sft-008` 只差 `data`） | 新候选 | `reports/retail_ops/v1/r8/sft-009` |
| F-2 | 探针：`sft-008` 在**同一 commit** 上重跑 | 去掉「跑在不同代码上」这个混淆，兼作探针可重复性 | `reports/retail_ops/v1/policy-boundary/sft-008-rerun` |
| F-3 | 探针：`sft-009` | 判据主体 | `reports/retail_ops/v1/policy-boundary/sft-009` |
| F-4 | dev 60 配对评测：`sft-009` | 模板内退化检查 | `reports/retail_ops/v1/r8/dev-candidate-009` |
| F-5 | 重建当前 `ood_dev` 任务集（旧产物来自已取代的生成器） | 措辞分布外回归的评测集 | `reports/retail_ops/v1/ood-v2/dev/tasks-rebuilt` |
| F-6 | `ood_dev`：`sft-008` | 同集合对照 | `reports/retail_ops/v1/ood-v2/dev/sft-008` |
| F-7 | `ood_dev`：`sft-009` | 措辞分布外退化检查 | `reports/retail_ops/v1/ood-v2/dev/sft-009` |

上一轮留在同一命名空间下的 `reports/retail_ops/v1/ood-v2/dev/tasks` 也一并声明：它是**被取代**的旧任务集，本轮只用来说明历史读数为什么不可比，不产生新读数。

**F-2 为什么要做**：`sft-008` 的探针读数产生于 `1e9e137`，`sft-009` 的产生于其后。
评测路径在两次之间一个字节未改（`git diff --stat 1e9e137..HEAD -- src/veritool_rl/retail_ops/evaluate/`
为空），但整个结论压在这一次对比上，值得用 15 分钟 GPU 把这个质疑彻底去掉。

**F-5/F-6 为什么要做**：历史上 `ood_dev` 的 `sft-008 = 0.9833` 跑在
`generator_id: ood_phrasing_bank_v2` 的旧任务集上，而当前生成器是
`..._full_state_space`（LOG-20260817-05 的状态空间修正）。**两者不可比**，
因此在重建后的当前集合上重跑两侧。

已训出但**不评测**的：`reports/retail_ops/v1/r8/sft-008-rebuild-seed2`（原预注册作废，见上）。

### 判读规则（**在跑修复后的评测之前写定**，细节见 `docs/POLICY_BOUNDARY.md` §5）

三种结果分别怎么落地，逐条写死在那份文档的表里；这里只列分支名，
**刻意不复制阈值**——同一组数字写两遍必然漂移，那是本项目反复踩过的坑。

1. **修好**：`offset −14` 达标、放行侧不塌、dev 60 与 `ood_dev` 60 不退化 → 换候选，代价一并写明。
2. **修坏**：放行侧任一点掉下来，或 dev / `ood_dev` 退化 → **不换候选**，照写「补覆盖把模型推向多拒绝」。
3. **没动**：`offset −14` 仍不达标而其余不变 → **不换候选**，假设被证伪，照写「覆盖不是唯一原因」。

**无论哪种结果**：不重跑、不换增强素材再试一次、不消耗封存 holdout 观测；
同一个干预只报告第一次复测的读数。

### 边界

- 探针**不封存**、可反复读、可用于迭代，因此它的读数**不能**用来声称发布结论。
- 探针**不是**分布外评测：措辞与冻结数据集同源，只是把状态空间在一条轴上加密。
- 逐点 n=8，95% CI 宽约 ±35pp：**足以看曲线形状，不足以给单点排序**。
- 任何修复都必须同时报告 dev 60 与 ood_dev 60 上有没有退化——
  「让模型见谁都拒绝」能把探针刷满分，而那会在放行侧崩掉。探针两侧同时在场正是为此。

### 非目标

- 不下调任何发布门禁阈值；不改 `dataset_version` 既有取值、40/10/20 配额、
  `GATE_IDS` v1.0、`SealedEvaluationReport` 字段集、dev/sealed `PAIRING_FIELDS`。
- 不改 `runner.SYSTEM_PROMPT`、parser、prompt 模板。
- 不创建 remote、不推送公开仓库。
- **本轮不消耗封存 holdout 观测**（原预注册里的第七次已取消）。

## Current Task B：精简治理测试

**做法**：把「断言某句手挑的话必须在文档里」这一类删掉；把六份手工维护的 config
扫描列表换成**从 `git ls-files` 派生**的单条检查（覆盖面 52 → 99 份 config）；
把只在自己语料上验证过、**从未扫过任何真实文档**的观测次数检测器真正接到文档上，
并删掉它本该替换掉的那张手写黑名单。

**保留判据**：一条文档测试断言的若是**从产物派生的关系**（台账 ↔ 文档、pytest ↔ 文档、
表格 ↔ 标题、config ↔ config、代码 ↔ 文档），或是最高风险文本上的
「好消息必须带坏消息」配对，就留；若断言的是**一句手挑的话必须在场**，就删。

**验收**：测试总数低于 1094，`pytest` / `ruff` / `ruff format --check` / `mypy` 全绿，
真实行为测试一条不少。**不得为了降数字删掉覆盖真实代码路径的测试。**

---

## Current Task C：干净 clone 实测 + 去绝对化

`README.md` / `README.en.md` / `docs/RESUME_EVIDENCE.md` 声称干净 clone 上
**1049 passed / 45 skipped / 0 failed**——**这个数是 1094 − 45 算出来的，没有实测**。
本轮在 scratchpad 里 clone 当前提交实跑，记录真实数字；与文档不符就改文档。
任务 A/B 改完代码后**必须重跑一次**，最终文档里的数字对应最后一个提交。

同时把「全绿」「一律」「永远」「唯一」「零误报」这类绝对化表述逐条降级为
有界陈述（写清在哪种环境、跑了哪几项、什么时候、挡不住什么）。

---

## Current Task D：独立验收

任务 A/B/C 全部落盘、全门禁绿之后，起一个零上下文的 `general-purpose` subagent，
角色为资深技术面试官，按 10 分制打分，**≥9 分才算通过**并签字。
判分 < 9 则修阻塞项再送一轮，直到签字。**修实质问题，不加约束项**；
若某条阻塞项本身要求「再加一层守卫」，说明为什么不做并给实质替代方案。

---

## Task Rules

- 本文件只跟踪当前任务；长期阶段状态以 `docs/EXECUTION_PLAN.md` 为准。
- 新任务开始时重写 Current Task，保留已完成任务的摘要到 `progress.md`。
- 输入、输出、非目标、失败模式和验收命令不完整时不得开始实现。
- GPU、API、数据下载和公开发布必须显式标注授权状态。

## 验收命令

```bash
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy
env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check
git diff --check
.venv/bin/python scripts/ci/verify_qualification_chain.py
.venv/bin/python scripts/ci/audit_public_release.py
```

## 授权状态

GPU **是**、商业 API **是**、封存 holdout 观测**不限次数**（用户 2026-08-17）、
新依赖 **允许**（中国镜像）、subagent **允许**、
创建 remote / 推送公开仓库 **否**（用户的动作）。

## Errors

| Date | Error | Resolution |
|---|---|---|
| 2026-08-16 | R5 重建复验首次起跑漏了 `--input_dir`，CLI 硬失败退出 | 私有训练数据根是 `data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722`；补参数后重跑 |
| 2026-08-16 | 按外部审阅修 teacher/训练数字时只改了主表，漏了 5 处 | 手工同步同一组数字必然漏；改为绑到可执行校验（`test_the_two_teacher_batches_are_never_conflated` 等） |
| 2026-08-17 | 规则第 3 条的括号里写了对结果的预期，预期落空导致规则自相矛盾 | 判读规则只写判据与阈值，不写「预计会怎样」；偏离规则时把事实与理由写进本文件而不是只在对话里说 |
| 2026-08-17 | 预注册的 R-8 产物目录写成 shell brace 简写，与实际目录名不字面相等 | `test_every_declared_run_directory_is_actually_declared` 当场变红。预注册里的路径要写成能被逐字匹配的形式，简写会让「声明过」这件事无法机械核对 |
| 2026-08-19 | cpolar 隧道换端口后 `ssh gpu-5090` 报 `Host key verification failed` | 新地址的三把主机密钥与 `known_hosts` 里旧隧道地址的指纹逐一相同（同一台机器），核对后再 `ssh-keyscan -H` 追加；不是关掉 `StrictHostKeyChecking` |
| 2026-09-06 | **bank-004 丢失**：R11-1 采样预检发现 `phrasing-bank-004` 在本地与 gpu-5090 均不存在（本地 `phrasing/` 目录为空，mtime 当日 11:50；全盘/回收站/远端 `/mnt/aidata` 均无备份）。`ood_dev` 247 条内容不可恢复；ood_sealed 226 条中 60 条任务文本留存于已退役的 v2.3 任务集 | 用户裁定（2026-09-06）：照原配方（mimo、per_intent 150、retry brief 强化）生成新素材 **bank-005**，DPO 采样面与 B-1 交叉面改用其 `ood_dev` 分片，预注册在此修订留痕；**A-7 的封存素材顺延为 bank-006**。生成后跑与全部分片及训练集的互斥实测（机器断言）。教训：私有根里的已声明素材是预注册的组成部分，收口清理不得触碰 `data/private` |
| 2026-09-06 | **（上一条的更正）bank-004 从未丢失**：bank-005 互斥实测时发现 bank-004 健在于本地 `r2/retail_ops_v1_r2_20260722/phrasing/phrasing-bank-004/`（932 条，`bank_sha256` = `f4b14e8d…` 与 D4 配置声明逐位吻合）。误判根源：本地搜索 `find` 的 maxdepth 7 不够深（实际 ~10 层）+ 只看了 `v1/phrasing/` 一处布局，未查 r2 根；远端确实缺该文件但本地一直有。bank-005 已生成（$0.0244，mimo），与 bank-002/ood_dev 有 1 条 status_inquiry 记录级重叠、与 bank-004 有 3 条 ood_sealed 重叠、与训练集零重叠 | 用户裁定（2026-09-06）：**回退到 bank-004**（原预注册恢复，采样/交叉面配置本就 pin 它，零变更）；bank-005 定性为**多余素材**，永不进入任何评测面（互斥清单 `phrasing_exclusivity_bank005.json` 留档）；rsync bank-004 本地→远端。教训：宣告素材丢失前必须先用**内容哈希**（`bank_sha256`，非文件字节 sha）逐目录核对两台机器的全部私有根布局；深度受限的 find 不是全盘搜索 |

（R0–R4.5 的历史错误台账已归档到 `progress.md`。）

### 进度

- [x] 1. 原预注册提交（`0185135`）——**已按用户指令作废，见 Task A**
- [x] 2. `--seed 2` 重训跑完；**不评测、不报告**（改向后没有它的位置）
- [x] 3. 任务 B：测试瘦身（`a8539cc`，1094 → 1082）
- [x] 4. 任务 C1：干净 clone 首次实测（1035 passed / 45 skipped / 2 failed）
- [x] 5. 切分难度覆盖诊断 + 政策边界探针（`1e9e137`）
- [x] 6. P-1/P-2：探针上的基座与 `sft-008` 读数（失败只在 `offset −14`）
- [x] 7. 按曲线写修复方案与三分支判读并提交（`3cb5619`，早于全部修复运行）
- [x] 8. 训练侧修复 + 复测 → **分支 2「修坏」，候选不变**（`docs/POLICY_BOUNDARY.md` §6）
- [x] 9. 台账、阶段状态源、`PROJECT_LOG`（LOG-20260819-01）落地
- [x] 10. 任务 C：干净 clone 复跑，把文档里那个推算值换成实测值（2026-08-27 完成：
      `88ccabb` 上实测 1238/46/0，与推算值一致；修复后 1262/46/0）
- [x] 11. 任务 D：独立验收并签字 → **被 R8 Task A1 取代**（一个面试官升级为三轮严苛独立审查）

### R8 D1 运行清单（seed2 方差刻画，推翻 R7 时判 D1 价值不足的判定）

| # | 运行 | 用途 | 产物目录 |
|---|---|---|---|
| D1-0 | OOD v2.2 封存分片任务集 | 评测集（R7 已有，同步回本地） | `reports/retail_ops/v1/ood-v2.2/sealed/tasks` |
| D1-1 | OOD v2.2 封存分片：seed2 候选 | 方差刻画 | `reports/retail_ops/v1/ood-v2.2/sealed/rebuild-seed2` |
| D1-2 | dev 60：seed2 候选 | dev 方差区间 | `reports/retail_ops/v1/r8/dev-candidate-seed2-run` |

---

## R8 元方法论补强与岗位重定位（进行中，2026-08-19 启动）

**总体目标**：把项目从「LLM 应用工程师岗」的方法论重定位为
「MLOps / LLM Evaluation Infra / Release Engineering 岗」的方法论，
经历三轮严苛独立审查（MLOps → SRE → ML 论文 reviewer）到 9/10，
并补齐该岗位的硬扣分项。**核心方法论不动**：自我证伪纪律、版本化门禁、
配对可比性、封存 holdout 台账——这些是项目已有且定稿的卖点，本轮**扩展其成立范围**，
**不重写其内容**。

**输入**：R7 已完成的 `sft-008` 候选、1146 tests、22 份治理/交付文档、
两台远程 GPU（gpu-4090/gpu-5090）、已训出未评测的 `sft-008-rebuild-seed2` 权重。

**输出**：
- 三份独立审查书面意见（每轮一份）+ 逐条修复的 commit 与 LOG
- 证据系统可移植性实证（第二个 toy 域走通 core 模块）
- 业界工具对照矩阵 + MLflow 导出器
- CI 真跑或等价物（`verify_qualification_chain.py`）顶到简历
- 第二个领域跨域验证（英文 + 不同政策域）
- 工具面扩到 15+ 与 tool selection 退化曲线
- 简历与面试材料按"投 MLOps 岗"重写

**非目标**：
- 不动 R7 判定（多 seed 方差刻画 D1 不做，`sft-008-rebuild-seed2` 不评测不报告）
- 不动核心方法论：自我证伪纪律、版本化门禁契约、配对可比性、封存 holdout 台账
- 不改 BFCL holdout 与失败样例不得进入开发的边界
- 不创建 remote、不 push、不发布（仍由用户单独授权）
- 不下调任何发布门禁阈值

**产物前缀**：`r9`（R7 用 r8，因为「R6 收口」占用 r7）

### Task A1：三轮严苛独立审查（元方法论，纯 CPU）

取代 R7 Task D 的「一个面试官 9 分签字」，升级为**三个 persona 各一轮**，
每轮出书面意见，我针对意见逐条修复并写 LOG。**这条本身就是方法论补强**：
把"自我证伪"从一次性事件升级为可重复的工程实践。

**persona 顺序**（用户 2026-08-19 拍板）：
1. MLOps 工程师视角：发现岗位硬扣分项（CI、业界工具对照、可移植性、证据系统成本）
2. SRE / Release Eng 视角：发现证据链漏洞与可靠性边界
3. ML 论文 reviewer 视角：发现方法论统计强度问题（n 太小、单 seed、单一场景）

**判分**：每轮 10 分制，<9 分则修阻塞项再送下一轮。三轮全部 ≥9 才算 A1 完成。

### Task A2：证据系统可移植性实证（纯 CPU）

把 `src/veritool_rl/core/` 抽出来，在第二个 toy 域（例如 DevOps 工单：
2-3 个工具 + 1-2 条政策）走一遍 build→evaluate→release。
**强化"分层成立"这条已有断言**：现在 `core → retail_ops` 的依赖方向有治理测试锁定，
但没有第二个域实证过它能换。

**验收**：toy 域 build/evaluate/release 三接口跑通，至少 30 条测试覆盖，
治理测试断言 toy 域不反向依赖 `retail_ops`。

### Task B1：业界工具对照矩阵 + MLflow 导出器（纯 CPU）

写 `docs/MLOPS_COMPARISON.md`：与 MLflow / W&B / Evidently / DVC 的功能对照
（各能做什么、不能做什么、本项目补在哪）。再加一个 `scripts/export_mlflow.py`
把现有 `candidate-report.json` 导成 MLflow 可消费格式（`mlflow.metrics` + 自定义 artifact）。

**验收**：对照矩阵覆盖 5 个工具 × 8 个能力维度，导出器有测试覆盖。

### Task B2：CI 真跑或等价物顶上来（纯 CPU，公开发布门单独授权）

当前诚实写"workflow 提交但从未运行，无 remote"。
两条路：
- (a) 用户授权 push 到公开仓库，让 GitHub Actions 真跑一次 CPU smoke
- (b) 不公开，但把 `scripts/ci/verify_qualification_chain.py` 顶到简历第一段
   作为"等价物已可复现"

**验收**：(a) 路径有 Actions 真跑绿的证据；或 (b) 路径有简历第一段已更新的证据。
默认走 (b)，(a) 需用户单独授权公开发布门。

### Task C1：第二个领域跨域验证（CPU + GPU）

加一个英文域（例如 IT 工单或航班改签），写 domain bundle、任务集、teacher 采集、
训一个 Qwen3-4B QLoRA 候选，跑 dev + OOD 评测。**扩展结论成立范围**：
现在所有结论在单一中文零售退款场景上成立，跨域验证补这条。

**GPU 需求**：1 次训练（~5min, 5.65GB）+ 1 次 dev 评测（~10min）+ teacher 采集（~$0.05）。
用户已批准全部 GPU 任务，每条命令我仍会先给精确清单再执行。

**验收**：第二个域 dev/holdout 配对评测跑通，证据链与零售域同构。

### Task C2：工具面扩到 15+（CPU + GPU，**推翻 R4.5 时未选 B 的判定**）

R4.5 时用户在 A（user simulator）/ B（扩工具面 15+）二选一中未选 B。
本轮**明确推翻该判定**（治理痕迹见 LOG-20260819-02），授权启动 C2。
把工具扩到 15+ 含语义相近易混工具，画 tool selection 准确率随工具数的退化曲线。

**GPU 需求**：训练多个候选（~5min × 3-5）+ 多轮评测。

**验收**：15+ 工具的 domain bundle 落地，退化曲线有读数，结论按"只在该工具面规模上成立"陈述。

### Task D：简历与面试材料重写（在 A1 三轮审查完后）

按上一轮面试官视角分析时提出的「四段骨架」（系统 → 证据 → 门禁 → 自我证伪）
重写 `docs/RESUME_EVIDENCE.md` 与 `docs/INTERVIEW_PREP.md`，
主语从「Agent」改成「判定系统」。两版方案不再分 A/B，投 MLOps 岗一版就够。

**验收**：简历 bullet 主语是「判定系统」不是「Agent」，五分钟讲解从「证据链 → 门禁 →
三次 NO-GO → 自我证伪」展开，不提「提示词与后训练功劳分离」「LoRA 容量与规模匹配」
作为头条（被问到再讲）。

---

## R8 授权状态（追加在 R7 授权状态之上）

GPU **是**（用户 2026-08-19 批准全部 GPU 任务，每条命令仍先给精确清单）、
商业 API **是**（C1 的 teacher 采集、C2 的 teacher 采集）、
封存 holdout 观测**否**（本轮不消耗，结论不是发布结论）、
**C2 推翻 R4.5 时未选 B 的判定**（治理痕迹见 LOG-20260819-02）、
**B2 公开发布门已授权**（用户 2026-08-20 提供 remote
`https://github.com/emmmdty/retail-agent-ops.git`，CI 真跑启动）。

---

## R8 D2 运行清单（C1 跨域 + C2 工具面扩容 + B2 CI 真跑）

**决策记录（2026-08-20）**：用户对 C1 域、C2 工具布点、C2 候选数、B2 授权
四项叉路回复「你判断 / 工具全面 / 5 断点 / 授权」。据此落地：
- **C1 域 = 航班改签（flight_ops）**：政策边界是 24h 时间窗口，
  与 `refund_deadline` 同构，政策边界探针仪器可复用；英文消费者场景。
- **C2 工具布点 = 全订单/退款族**：15 工具，前 3 个 = 现有
  `get_order/refund_order/get_store_hours`（让 {3} 断点复用 `sft-008`），
  后 12 个全在订单/退款族最大化语义混淆。
- **C2 候选 = 5 断点 {3,6,9,12,15}**：{3} 复用 `sft-008`，新训 {6,9,12,15}
  共 4 个候选。
- **B2**：remote `https://github.com/emmmdty/retail-agent-ops.git`，CI 真跑。

### Task B2：CI 真跑（纯 CPU，公开发布门已授权）

**输入**：HEAD `596eee8` 本地全门禁绿（1171 passed / ruff / format / mypy 89 /
lock 105 / audit 437 文件 / qualification / diff）。**运行**：
1. `git remote add origin https://github.com/emmmdty/retail-agent-ops.git`
2. `git push -u origin main`
3. GitHub Actions workflow `.github/workflows/ci.yml` 真跑一次 CPU smoke。
**产物**：`docs/CI_EVIDENCE.md`（运行 URL、commit SHA、各步状态、首次运行日期）。
**非目标**：不改 CI workflow 逻辑（只更新头部注释「尚未运行」→「首次运行于…」）；
不下调任何门禁；不删 git 历史。

### Task C1：第二个领域跨域验证（CPU 实现 + GPU 训练 + 评测）

**域**：`flight_ops` v1（航班改签，英文）。
**工具（3）**：`get_reservation` / `rebook_flight` / `get_flight_schedule`。
**政策（2）**：`rebook_window_must_be_open`（起飞前 24h 内禁改签，与
`refund_window_must_be_open` 同构）+ `duplicate_rebook_forbidden`（与
`duplicate_refund_forbidden` 同构）。
**任务类（6，镜像 retail_ops 的失败形态）**：`lookup_status` /
`rebook_eligible` / `rebook_denied_window` / `rebook_denied_ownership` /
`rebook_denied_duplicate` / `rebook_recovery`。
**输入**：零售域的 build/evaluate/release 接口形状；DeepSeek teacher。
**输出**：flight_ops domain bundle + tasks + environment + policies + 评测，
证据链与零售域同构（`report_id` 自哈希 + 逐产物 SHA-256 + 配对可比性）。
**影响文件**：`domains/flight_ops/v1/{bundle,tools,policies,release}.yaml`、
`src/veritool_rl/flight_ops/{__init__,domain/{bundle,environment,tasks,policies,policy_rules},build/,evaluate/,release/}.py`、
`tests/test_flight_ops_*.py`、治理测试扩展（`flight_ops` 不反向依赖 `retail_ops`、
`core` 不依赖 `flight_ops`）。
**GPU 运行清单**（每条命令执行前另给精确清单：工作目录、物理 GPU、预计时长、产物）：

| # | 运行 | 用途 | 产物目录 |
|---|---|---|---|
| C1-0 | teacher 采集（DeepSeek，~240 条） | 训练素材 | `reports/flight_ops/v1/r9/teacher-001` |
| C1-1 | SFT 数据导出 | 训练数据 | `reports/flight_ops/v1/r9/train-export-001` |
| C1-2 | 训练 `sft-001`（Qwen3-4B QLoRA，~5min） | 候选 | `reports/flight_ops/v1/r9/sft-001` |
| C1-3 | dev 60 评测：零训练基座 | 基线 | `reports/flight_ops/v1/r9/base-001` |
| C1-4 | dev 60 评测：`sft-001` | 候选读数 | `reports/flight_ops/v1/r9/dev-candidate-001` |
| C1-5 | OOD dev 评测：`sft-001` | 分布外读数 | `reports/flight_ops/v1/r9/ood-dev-001` |

**非目标**：不改 retail_ops v1/v2 冻结契约；不在 flight_ops 上跑封存 holdout
（本轮不是发布结论，是跨域可移植性实证）；不创建第三个域。

### Task C2：工具面扩到 15+（CPU 实现 + GPU 训练 + 评测）

**域**：`retail_ops` v3（15 工具，新 bundle 版本，v1/v2 逐字节不动）。
**15 工具**（前 3 = v1，后 12 全订单/退款族）：`get_order` / `refund_order` /
`get_store_hours` / `cancel_order` / `modify_order` / `exchange_order` /
`get_refund_status` / `get_order_history` / `apply_refund_coupon` /
`get_return_policy` / `check_warranty` / `process_exchange` / `escalate_refund` /
`get_payment_method` / `get_customer_profile`。
**断点**：{3,6,9,12,15}。{3} 复用 `sft-008`（v1 = v3 前 3 工具，可比）。
**输入**：retail_ops build/evaluate 接口；DeepSeek teacher（每断点 ~240 条）。
**输出**：v3 domain bundle + 断点任务生成器 + 4 个新候选 + tool selection
准确率随工具数的退化曲线。
**影响文件**：`domains/retail_ops/v3/{bundle,tools,policies,release}.yaml`、
`src/veritool_rl/retail_ops/domain/bundle.py`（`_FROZEN_TOOL_NAMES` 改版本键控、
`_SUPPORTED_BUNDLE_VERSIONS` 加 `"3.0.0"`）、
`src/veritool_rl/retail_ops/domain/v3_tasks.py`、`tests/test_retail_ops_v3_*.py`。
**GPU 运行清单**（每条命令执行前另给精确清单）：

| # | 运行 | 用途 | 产物目录 |
|---|---|---|---|
| C2-6t | teacher 采集 + 导出（6 工具） | 训练素材 | `reports/retail_ops/v1/r9/toolcount-6/train` |
| C2-6s | 训练 6 工具候选（~5min） | 候选 | `reports/retail_ops/v1/r9/toolcount-6/sft-001` |
| C2-6d | dev 评测：6 工具候选 | tool selection 读数 | `reports/retail_ops/v1/r9/toolcount-6/dev` |
| C2-9t | teacher 采集 + 导出（9 工具） | 训练素材 | `reports/retail_ops/v1/r9/toolcount-9/train` |
| C2-9s | 训练 9 工具候选（~5min） | 候选 | `reports/retail_ops/v1/r9/toolcount-9/sft-001` |
| C2-9d | dev 评测：9 工具候选 | tool selection 读数 | `reports/retail_ops/v1/r9/toolcount-9/dev` |
| C2-12t | teacher 采集 + 导出（12 工具） | 训练素材 | `reports/retail_ops/v1/r9/toolcount-12/train` |
| C2-12s | 训练 12 工具候选（~5min） | 候选 | `reports/retail_ops/v1/r9/toolcount-12/sft-001` |
| C2-12d | dev 评测：12 工具候选 | tool selection 读数 | `reports/retail_ops/v1/r9/toolcount-12/dev` |
| C2-15t | teacher 采集 + 导出（15 工具） | 训练素材 | `reports/retail_ops/v1/r9/toolcount-15/train` |
| C2-15s | 训练 15 工具候选（~5min） | 候选 | `reports/retail_ops/v1/r9/toolcount-15/sft-001` |
| C2-15d | dev 评测：15 工具候选 | tool selection 读数 | `reports/retail_ops/v1/r9/toolcount-15/dev` |
| C2-3d | dev 评测：3 工具（`sft-008` 在 v3 前 3 工具任务集） | 曲线左端点 | `reports/retail_ops/v1/r9/toolcount-3/dev` |

**判读**：退化曲线横轴 = 工具数（3/6/9/12/15），纵轴 = tool selection 准确率。
结论按「只在该工具面规模上成立」陈述；不在 flight_ops 上引用此结论。
**非目标**：不动 v1/v2 冻结契约与已有证据；不消耗封存 holdout；
不在 15 工具面做封存（本轮是 tool selection 退化测量，不是发布判定）。

### 顺序

B2（最快、已授权、独立）→ C1 CPU 实现 → C1 GPU 运行 → C2 CPU 实现 →
C2 GPU 运行 → 简历与面试材料补 C1/C2/B2 读数（Task D 后置）。

---

## R9 数据多样性扩展实验（进行中，2026-08-21 启动）

**总体目标**：分两阶段做扩展实验，验证"数据量"与"数据多样性"的独立贡献。
- Phase A：只增加数据量（240→2000），保持工具/场景/模板不变 → 验证"数据量"的独立贡献
- Phase B：增加数据多样性（3→5 工具，6→12 场景，12→60+ 模板） → 验证"多样性"的独立贡献

**核心问题**：OOD 泛化差，究竟是数据不够多，还是数据不够多样？

**非目标**：
- 不换模型（仍是 Qwen3-4B + QLoRA）
- 不换训练方法（仍是 SFT）
- 不做封存 holdout 观测
- 不改发布门禁阈值
- 不改 parser / max_steps / verify_final_state（Phase A+B 均不改）

---

### Phase A：数据量消融（纯 volume effect）

**设计**：唯一变量是训练样本数。工具、场景、模板、口吻、工程约束全部不变。

| 维度 | baseline | Phase A | 变化 |
|---|---|---|---|
| 训练量 | 240 条 | **1,600 条** | ×6.7 |
| 工具 | 2 个 | 2 个 | 不变 |
| 场景 | 6 类 | 6 类 | 不变 |
| 模板 | 12 句 | 12 句 | 不变 |
| 口吻 | 书面正式 | 书面正式 | 不变 |
| epoch | 3 | 3 | 不变 |
| 梯度步数 | ~75 | ~600 | ×8（由数据量自然增长） |

**实现方式**：对现有 240 条训练数据做 oversampling：
- 每条原始样本通过 **不同的 order_id/reason/margin 组合** 生成变体
- 保持 user_request 模板不变（仍是那 12 句），只替换其中的实体
- 目标 2,000 条，去重后保留唯一模板+实体组合
- 按 sha256 切分 train/dev/holdout = 80/10/10

**评测**：
- dev（模板内）：原有 60 条，不变
- OOD v2（模板外）：原有 60 条，不变
- oversampled OOD：新增 60 条，用与训练集相同的 12 模板但不同的实体组合

**判读规则**：
| 结果 | 判定 |
|---|---|
| OOD ≥ 0.70 | 数据量是重要因素，继续 Phase B |
| OOD 改善但 < 0.70 | 数据量有帮助但不够，Phase B 必须做 |
| OOD 无改善 | 数据量不是瓶颈，需重新诊断 |

**Phase A 运行清单**（每条命令执行前另给精确清单：工作目录、物理 GPU、预计时长、产物）：

| # | 运行 | 用途 | 产物目录 |
|---|---|---|---|
| A-0 | Oversample 240→2000 条（CPU，实体替换，不改模板） | 训练数据 | `data/private/retail_ops/v1/r9/phase-a` |
| A-1 | 训练 `sft-001`（Qwen3-4B QLoRA，~15min） | 候选 | `reports/retail_ops/v1/r9/phase-a/sft-001` |
| A-2 | Dev 评测（原有 60 条） | 模板内退化检查 | `reports/retail_ops/v1/r9/phase-a/dev-001` |
| A-3 | OOD 评测（原有 60 条） | 核心对比 | `reports/retail_ops/v1/r9/phase-a/ood-001` |
| A-4 | Oversampled OOD 评测（新增 60 条） | 实体泛化 | `reports/retail_ops/v1/r9/phase-a/ood-oversampled-001` |

**判读**：Phase A 结果写入 `findings.md` 和 `progress.md`，然后请求用户确认是否进入 Phase B。

**当前状态**：A-0 完成（2000 条 oversampled 数据已生成），A-1~A-4 待执行。

---

## Agent 执行循环边界审查（纯代码审查，不产生读数）

**输入**：`core/agent/{runner,parser,policy,guardrail,qwen,vllm_backend}.py`、
`core/envs/{base,mini_retail}.py`、`retail_ops/domain/environment.py`、
`retail_ops/serve/service.py`、`core/rewards/verifier.py`。
**输出**：逐项问题清单，写入 findings.md。
**非目标**：不评分、不给建议、不改代码、不跑测试。
