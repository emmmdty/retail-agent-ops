# Task Plan: RetailAgentOps

## Goal

在 12 周内交付可公开、可复现、可面试解释的零售工具 Agent 单卡适配与发布流水线。
R0–R6 已完成，阶段状态以 `docs/EXECUTION_PLAN.md` 为准，历史任务摘要在 `progress.md`。

## Current Phase

**R6 收口**：把 `SPEC.md` §6 第 6 条（独立重建复验）从 `sft-006` 扩展到**最终候选
`sft-008`**，然后送第五轮独立审核。

## Current Task：`sft-008` 的独立重建复验

### 为什么做这件事

独立重建复验当初只在 `sft-006` 上做、且只在 dev 上做（`docs/REBUILD_VERIFICATION.md`）。
而 **`sft-008` 才是最终候选**——它是修好分布外鲁棒性、拿到封存 holdout GO 的那一个，
却**从未被独立重建过**。「你的最终候选没被独立重建过」是一个比任何文书问题都更值得被问的缺口。

同时补一个更根本的缺口：R6 的头条读数（封存 OOD 分片 1.0000）只来自**一份**措辞池
（`phrasing-bank-002`）的**一个**分片。单一 provider、单一 prompt、单一批次。
换一份全新生成的素材还成不成，目前**没有答案**。

### 输入

- 本地 HEAD `92ae4cb`，工作树干净，**1048 tests passed**，全部质量门通过。
- 训练配置 `configs/retail_ops/build/retail_ops_v1_r6b_no_oversample_sft.yaml`（**一个字不改**）。
- 私有训练数据根 `data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722`。
- 配对对照：dev 侧 `qwen3-4b-dev-base-002`（零训练，54/60，5 次政策违规）；
  封存 holdout 侧必须**两侧重跑**（`code_commit` 在 `SEALED_PAIRING_FIELDS` 内）。
- `.env` 内 DeepSeek 凭据（生成新措辞池，约 $0.006）。

### 非目标

- 不下调任何发布门禁阈值；不改 `dataset_version` 的既有取值、40/10/20 配额、
  `GATE_IDS` v1.0、`SealedEvaluationReport` v1.0/v1.1 字段集、dev/sealed `PAIRING_FIELDS`。
- 不改 `runner.SYSTEM_PROMPT`、parser、prompt 模板。
- 不创建 remote、不推送公开仓库。
- **不因为读数不好看而重跑、换 seed、换素材或换部署形态。**

### 运行内容（**在看到任何读数之前固定，不得增减**）

| # | 运行 | 用途 | 产物目录 |
|---|---|---|---|
| R-0 | 构建 OOD v2.2 sealed 任务集（CPU，不是模型运行） | 判据 B 的评测集 | `reports/retail_ops/v1/ood-v2.2/sealed/tasks` |
| R-1 | 换 seed 重训（`--seed 1`，配置一字不改） | 重建 `sft-008` | `reports/retail_ops/v1/r6/sft-008-rebuild-seed1` |
| R-2 | dev 60 配对评测（重建候选） | 判据 A | `reports/retail_ops/v1/r6/candidate-r6-rebuild-seed1` |
| R-3 | OOD v2.2 sealed：零训练基座 | 判据 B 的对照 | `reports/retail_ops/v1/ood-v2.2/sealed/base` |
| R-4 | OOD v2.2 sealed：`sft-008`（原候选） | 判据 B 的同分片参照 | `reports/retail_ops/v1/ood-v2.2/sealed/sft-008` |
| R-5 | OOD v2.2 sealed：重建候选 | 判据 B | `reports/retail_ops/v1/ood-v2.2/sealed/rebuild-seed1` |
| R-6 | 封存 holdout base（第六次观测） | 判据 C | `reports/retail_ops/v1/r6/holdout-base-006` |
| R-7 | 封存 holdout 合并候选（第六次观测） | 判据 C | `reports/retail_ops/v1/r6/holdout-merged-candidate-006` |
| R-8 | `release` v1.0 与 v1.1 各一份 | 判据 C | `reports/retail_ops/v1/r6/formal-release-006-v10`、`reports/retail_ops/v1/r6/formal-release-006-v11` |

**候选侧为什么用合并形态**：与第五次观测同理，未合并形态的延迟代价已被归因为部署实现开销
而非模型能力（LOG-20260815-04）。**沿用第五次的形态，不是看到结果后挑的。**

**`release` 必须带 `--baseline_trajectories` / `--candidate_trajectories`**——
不提供时 v1.1 的 `success_delta_ci_lower` 判 FAIL，会产出一份**看起来像模型失败**的
NO-GO（LOG-20260817-03 踩过）。

### 判读规则（**在看到任何读数之前写定；三种结果都写明；规则里不含对结果的预期**）

被检验的声称是：**R6 的结论（模板内不退化 + 分布外鲁棒）是这条流水线可重建的性质，
不是某一个 seed 的彩票，也不是某一份措辞池的巧合。**

- **判据 A（模板内可重建）**：R-2 的 `task_success` **严格高于**零训练基座 `base-002`
  的 0.9000（54/60），**且** `policy_violation_count` **不高于** base-002 的 5。
  （与 R5 复验同一口径：下限取零训练基座，不取原候选——原候选是被检验对象，
  拿它当下限等于假设结论成立。）
- **判据 B（分布外可重建）**：在**从未观测过**的 OOD v2.2 sealed 分片上，
  B1 = R-5 总分 − R-3 总分 ≥ **+0.15**；B2 = |R-5 总分 − R-4 总分| ≤ **0.10**。
  - +0.15 的来处：v2.1 sealed 上 `sft-008` 与基座之差是 +0.2333，取其约三分之二作为
    「方向明确且幅度可观」的下限。0.10 的等价带在 n=60 上约等于 6 条。
  - **B1 与 B2 分别回答两件事**：B1 是「重建出来的权重比不训练强」，
    B2 是「重建与原候选没有实质差别」。两条都要报，缺一条结论就是残的。
- **判据 C（发布门禁）**：R-8 的两套判定**照写**，但**不参与「是否复现」的认定**——
  `p95_latency_ratio` 受共享 GPU 上他人占用影响，把它写进复现判据等于让科学结论
  依赖别人的负载。它单独记录为「重建出的权重能不能过项目自己的门禁」。

**三种结果分别怎么写**：

1. **复现**（A 与 B 都成立）：`REBUILD_VERIFICATION.md` 从 `sft-006`/dev 扩展到
   `sft-008`/dev+OOD，`SPEC §6` 第 6 条的适用对象改为最终候选。
   同时把 OOD 头条读数的表述从单点改为「两份独立措辞池上各一次」。
2. **不复现**（A 或 B 任一不成立）：**这是比复现更重要的发现。** R6 的结论按不成立的那一条
   降级——A 不成立则「模板内不退化」改为含 seed 波动的区间表述；B 不成立则
   **「扛得住分布漂移」这个声称必须撤回或降级为「在 `bank-002` 那一份素材上成立」**，
   并同步改 `README.md` / `README.en.md` / `docs/GENERALIZATION_FIX.md` /
   `docs/RESUME_EVIDENCE.md` / `docs/INTERVIEW_PREP.md` 的正文，**不是只在附录提一句**。
3. **部分复现**（A 成立 B 不成立，或反之）：两件事分开陈述，明确指出哪一个声称降级、
   哪一个保留，不得用成立的那一半掩盖不成立的那一半。

**无论哪种结果**：

- bank-003 的 `ood_sealed` 分片**只观测这一次**，读数写进 `docs/OOD_SEALED_LEDGER.md`；
  **不得因为读数不好看而再生成 bank-004 重测**——那就是对着封存集调参。
- 第六次封存 holdout 观测写进 `docs/HOLDOUT_LEDGER.md`。观测次数已不受限
  （用户 2026-08-17），**但结果永远不得反馈进开发、调参、候选选择或 prompt/parser 修改**。
- **只跑 `--seed 1` 这一个 seed**，不跑第三个再挑好看的。

### 失败模式（实施时主动防御）

1. **新素材与训练集重叠** → `test_no_evaluation_phrasing_appears_in_the_actual_training_file`
   必须扩展到 bank-003，比对**真实 `sft.jsonl`** 而不是分片构造。
2. **两份 OOD v2 数据集共用一个 `dataset_version`** → 那正是外部审阅在 v1/v2 上抓到的问题；
   bank-003 的分片必须有自己的版本号，且 `task_id` 只依赖位置这件事要靠
   `tasks_file_sha256` 而不是 `task_ids` 来区分。
3. **配置漂移** → 新评测配置相对既有配置只允许差 `attempt_id` 与 `adapter`/`model` 段，
   由治理测试逐字段断言。
4. **证据只留在 GPU 机器上** → 跑完同步回本地，`load_candidate_run_evidence(..., verify_artifacts=True)`
   逐产物校验，并做一次篡改测试。
5. **治理测试钉住一句会过期的话** → 断言当前边界的**语义**（如「台账声称的次数 == 台账里
   观测小节的数量」），不要断言某段特定措辞。

### 验收命令

```bash
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy
env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check
git diff --check
.venv/bin/python scripts/ci/verify_qualification_chain.py
.venv/bin/python scripts/ci/audit_public_release.py
```

### 授权状态

GPU **是**、商业 API **是**、封存 holdout 观测**不限次数**（用户 2026-08-17）、
新依赖 **允许**（中国镜像）、公开仓库推送 **否**（用户的动作）。

### 规则的实际应用（2026-08-17，读数落地后）

| 判据 | 阈值 | 实测 | 结论 |
|---|---|---|---|
| **A** dev `task_success` > 0.9000，政策违规 ≤ 5 | — | **1.0000（60/60）**，违规 **0** | ✅ 成立 |
| **B1** 重建 − 基座 ≥ +0.15 | +0.15 | 0.9833 − 0.7333 = **+0.2500** | ✅ 成立 |
| **B2** \|重建 − 原候选\| ≤ 0.10 | 0.10 | \|0.9833 − 0.9833\| = **0.0000** | ✅ 成立 |
| **C** 封存 120 门禁判定（不参与复现认定） | — | **GO，两套口径**；113/120、**7 次政策违规**、`ci_lower` **+0.0083** | 照写 |

**按事先写定的规则 → 结果 1「复现」。** 本文件不改规则、不挪阈值。

**但复现之外，这一轮有三条比"复现了"更重要的发现，全部照写**（详见
`docs/REBUILD_VERIFICATION.md` §6）：

1. **R6 那 2 次政策违规的归因被修正了。** 原论据是「`sft-007` 与 `sft-008` 失败签名完全相同」
   ——**但两者共用一个训练 seed**。换 seed 后 dev 上的违规是 0。
   能支持的表述只剩「措辞增强让这类违规变得可能，次数在运行间波动」。
2. **代价没消失，反而更大**：重建候选在 dev 上零违规，在封存 120 条上 **7 次**，
   且全部是同一签名 `refund_denied_window`。**dev 的那一类只有 10 条，看不见这个量级。**
   此前文档写的「2 次」是两次运行里较好的那一次。
3. **dev 与封存集把这两次运行排成了相反的顺序。** 这是「dev 不能替代封存集」的事后证据。

**头条读数的表述据此改为区间**：dev「58–60/60」、封存 120「113–117/120」、
分布外封存分片「0.9833–1.0000（两份独立素材）」。

### 进度

- [x] 1. 预注册（本文件）提交（`2c2c73b`）
- [x] 2. `dataset_version` 可区分两份 OOD v2 素材（TDD，`d9e3da5`）
- [x] 3. 生成 `phrasing-bank-003` + 构建 OOD v2.2 sealed + 互斥性经验验证（交集全 0）
- [x] 4. R-1 换 seed 重训（`1a2c3d16…`，配置 diff 只差三行）
- [x] 5. R-2 dev 60 配对评测（60/60，0 违规）
- [x] 6. R-3/R-4/R-5 OOD v2.2 sealed 三次运行（0.7333 / 0.9833 / 0.9833，该分片只此一次）
- [x] 7. R-6/R-7/R-8 第六次封存 holdout 观测 + 两套 release 判定（**GO**，113/120、7 违规）
- [x] 8. 证据同步回本地（13 份逐位一致）+ 逐产物校验 + 篡改测试
- [x] 9. 台账、文档、`PROJECT_LOG` 按判读规则落地
- [ ] 10. 第五轮独立审核并签字

## Task Rules

- 本文件只跟踪当前任务；长期阶段状态以 `docs/EXECUTION_PLAN.md` 为准。
- 新任务开始时重写 Current Task，保留已完成任务的摘要到 `progress.md`。
- 输入、输出、非目标、失败模式和验收命令不完整时不得开始实现。
- GPU、API、数据下载和公开发布必须显式标注授权状态。

## Errors

| Date | Error | Resolution |
|---|---|---|
| 2026-08-16 | R5 重建复验首次起跑漏了 `--input_dir`，CLI 硬失败退出 | 私有训练数据根是 `data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722`；补参数后重跑 |
| 2026-08-16 | 按外部审阅修 teacher/训练数字时只改了主表，漏了 5 处 | 手工同步同一组数字必然漏；改为绑到可执行校验（`test_the_two_teacher_batches_are_never_conflated` 等） |
| 2026-08-17 | 规则第 3 条的括号里写了对结果的预期，预期落空导致规则自相矛盾 | 判读规则只写判据与阈值，不写「预计会怎样」；偏离规则时把事实与理由写进本文件而不是只在对话里说 |
| 2026-08-17 | 预注册的 R-8 产物目录写成 shell brace 简写 `formal-release-006{,-v11}`，与实际目录名 `-v10`/`-v11` 不字面相等 | `test_every_declared_run_directory_is_actually_declared` 当场变红。**已把两个目录名逐字写全**——这是措辞修正，不是运行内容变更（v1.0/v1.1 各一份，与预注册一致）。教训：预注册里的路径要写成能被逐字匹配的形式，简写会让「声明过」这件事无法机械核对 |

（R0–R4.5 的历史错误台账已归档到 `progress.md`。）
