# Task Plan: RetailAgentOps

## Goal

在 12 周内交付可公开、可复现、可面试解释的零售工具 Agent 单卡适配与发布流水线。
R0–R6（含「R6 收口」）已完成，阶段状态以 `docs/EXECUTION_PLAN.md` 为准，
历史任务摘要在 `progress.md`。

## Current Phase

**R7 质量收口**：三件实质工作——**方差刻画**（第三个训练 seed，把「波动」从 n=2 升到 n=3）、
**测试瘦身**（删掉断言文档字符串的治理测试，测试总数下降）、
**口径实测**（干净 clone 的 pytest 读数实测，去绝对化）。

**本轮不允许通过新增治理测试 / 文档字符串扫描 / 正则守卫「提分」。**
产物前缀用 `r8`（轮次计数，比阶段标签大一，因为「R6 收口」占用了 `r7`）。

---

## Current Task A：第三个训练 seed —— 方差刻画

### 被检验的声称

项目现在最弱的一句话是「政策违规次数在运行之间波动」。它的全部证据是 **n=2**：
同配置两次运行在封存 120 上分别是 **2 次**与 **7 次**违规。两个点无法区分
「正常抖动」和「其中一次是异常」，而这个数直接支撑 `policy_violation_delta` 门禁。
头条区间 `58–60/60`、`113–117/120` 同样是两点极差，不是分布。

**本轮唯一自变量是 `--seed 2`。** 训练配置
`configs/retail_ops/build/retail_ops_v1_r6b_no_oversample_sft.yaml` 与 `sft-008`
（seed 0）、重建 seed 1 **逐字节相同**——该文件自诞生以来只有一次提交
（`79042a0`），由 `tests/test_retail_ops_r7_rebuild.py::test_the_rebuild_uses_the_untouched_training_config`
断言。评测侧 seed 由 `formal_dev_candidate` 冻结为 0，不是变量。

### 目的：方差刻画，不是候选选择

> **无论 seed 2 的读数好看还是难看，都不更换发布候选。`sft-008` 保持不变。**

这一句是本轮合规性的核心。观测次数不再是硬约束（用户 2026-08-17），
**但封存集结果永不反馈进开发、调参、候选选择或 prompt/parser 修改**——
那条限制来自统计学，不来自资源稀缺。本轮不会因为 seed 2 更好看而改 `sft-008`，
也不会因为它更难看而重跑、换 seed 或换素材。

### 输入

- 本地 HEAD 为本轮代码冻结提交，工作树干净。
- 训练配置 `configs/retail_ops/build/retail_ops_v1_r6b_no_oversample_sft.yaml`（**一个字不改**）。
- 私有训练数据根 `data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722`，
  训练分片 `train-export/train-export-007/sft.jsonl`（与 seed 0 / seed 1 同一份）。
- 配对对照：dev 侧 `qwen3-4b-dev-base-002`（零训练，54/60，5 次政策违规）；
  封存 holdout 侧**两侧重跑**（`code_commit` 在 `SEALED_PAIRING_FIELDS` 内，本轮 commit 已变）。
- `.env` 内 DeepSeek 凭据（生成措辞池 bank-004，约 $0.006）。

### 非目标

- 不下调任何发布门禁阈值；不改 `dataset_version` 的既有取值、40/10/20 配额、
  `GATE_IDS` v1.0、`SealedEvaluationReport` v1.0/v1.1 字段集、dev/sealed `PAIRING_FIELDS`。
- 不改 `runner.SYSTEM_PROMPT`、parser、prompt 模板、训练配置。
- 不创建 remote、不推送公开仓库。
- **不因为读数不好看而重跑、换 seed、换素材或换部署形态。**
- 不更换发布候选。

### 运行内容（**在看到任何读数之前固定，不得增减**）

| # | 运行 | 用途 | 产物目录 |
|---|---|---|---|
| R-0 | 生成措辞池 `phrasing-bank-004` + 构建 OOD v2.3 sealed 任务集（CPU + DeepSeek API） | 判据 B 的评测集 | `reports/retail_ops/v1/ood-v2.3/sealed/tasks` |
| R-1 | `--seed 2` 重训（配置一字不改） | 第三份权重 | `reports/retail_ops/v1/r8/sft-008-rebuild-seed2` |
| R-2 | dev 60 配对评测（seed 2 候选，未合并形态） | 判据 A | `reports/retail_ops/v1/r8/candidate-rebuild-seed2` |
| R-3 | OOD v2.3 sealed：零训练基座 | 判据 B 的对照 | `reports/retail_ops/v1/ood-v2.3/sealed/base` |
| R-4 | OOD v2.3 sealed：`sft-008`（seed 0，原候选） | 判据 B 的同分片参照 | `reports/retail_ops/v1/ood-v2.3/sealed/sft-008` |
| R-5 | OOD v2.3 sealed：重建 seed 1 | 判据 B | `reports/retail_ops/v1/ood-v2.3/sealed/rebuild-seed1` |
| R-6 | OOD v2.3 sealed：重建 seed 2 | 判据 B | `reports/retail_ops/v1/ood-v2.3/sealed/rebuild-seed2` |
| R-7 | 封存 holdout base（第七次观测） | 判据 C | `reports/retail_ops/v1/r8/holdout-base-007` |
| R-8 | 封存 holdout 合并候选（第七次观测，seed 2 权重） | 判据 C | `reports/retail_ops/v1/r8/holdout-merged-candidate-007` |
| R-9 | `release` v1.0 与 v1.1 各一份 | 判据 C | `reports/retail_ops/v1/r8/formal-release-007-v10`、`reports/retail_ops/v1/r8/formal-release-007-v11` |

**为什么 OOD v2.3 值得做**：现有的分布外头条是「0.9833–1.0000，**两份**独立素材」，
而那两个读数来自**不同素材上的不同 seed**——素材差异与 seed 差异完全混在一起。
一份从未观测过的新素材上同时跑**四侧**（基座 + 三个 seed），第一次把这两者分开。
这不是凑数，是把现有头条的证据结构改好。

**候选侧为什么用合并形态**（R-8）：与第五、六次观测同理，未合并形态的延迟代价已被
归因为部署实现开销而非模型能力（LOG-20260815-04）。**沿用前两次的形态，不是看到结果后挑的。**

**`release` 必须带 `--baseline_trajectories` / `--candidate_trajectories`**——
不提供时 v1.1 的 `success_delta_ci_lower` 判 FAIL，会产出一份**看起来像模型失败**的
NO-GO（LOG-20260817-03 踩过）。

### 判读规则（**在看到任何读数之前写定；不含对结果的预期**）

被检验的声称是：**「同配置只换 seed，读数会波动」这句话的波动幅度有多大，
以及现有头条区间是否需要改。**

- **判据 A（模板内）**：R-2 的 `task_success` 与 `policy_violation_count` 照写，
  与 seed 0（58/60、2 次违规<sup>dev</sup>）、seed 1（60/60、0 次）并列成 n=3。
  **不设通过/不通过阈值**——本轮目的是刻画分布，不是判定候选。
- **判据 B（分布外）**：在从未观测过的 OOD v2.3 sealed 分片上给出四个总分
  （基座 / seed 0 / seed 1 / seed 2）。**三个 seed 的极差**是本轮要的量；
  基座是「训练确实起作用」的对照。同样不设通过阈值。
- **判据 C（发布门禁）**：R-9 的两套判定**照写**。它单独记录为「第三份权重能不能过
  项目自己的门禁」，`p95_latency_ratio` 受共享 GPU 上他人占用影响，不作为方差结论的依据。

**三种结果分别怎么处理**（写在看到读数之前，因此不是事后解释）：

1. **落在现有两点之间**（seed 2 的三组数都不超出 `58–60/60`、`113–117/120`、`2–7` 次）：
   区间端点不动，**但 n 从 2 改成 3**，且全仓凡写「同配置两次运行」的地方改为「三次」。
   这是「波动被量到了」而不是「波动消失了」——不得据此弱化任何风险表述。
2. **超出现有区间**（任一组数落在区间之外）：**头条区间按实测放宽到包含 seed 2**，
   并重写 `policy_violation_delta` 门禁裕度的说明——一个能被 seed 抖动打穿的门禁，
   其裕度必须按实测最差值陈述，不是按最好的那次。
3. **seed 2 与另两个 seed 明显分离**（政策违规数与另两次相差 ≥ 5，或 dev 掉出 55/60）：
   **不得剔除它，也不得跑第四个 seed 去「确认」**——那就是挑 seed。
   照写三点，并明确写「n=3 不足以判断哪一个是异常点」。

**三种情况共同的约束**：`sft-008` 仍是发布候选；不重跑、不换素材、不换部署形态。

### 报告口径（**事先写死，不许事后挑口径**）

三次运行落地后，以下三组数一律用 **`min–max`（n=3，同配置仅换 seed）** 表述，
**并同时给出三个点值**：

1. dev 60 条 `task_success`；
2. 封存 120 条 `task_success`；
3. 封存 120 条 `policy_violation_count`。

OOD v2.3 分片的四个读数逐个列出，三个 seed 另给极差。
**不得只报好看的那一次，不得在看到读数后改用别的统计量。**

### 无论结果如何

- OOD v2.3 的 `ood_sealed` 分片**只观测这一次**，读数写进 `docs/OOD_SEALED_LEDGER.md`；
  **不得因为读数不好看而再生成 bank-005 重测**——那就是对着封存集调参。
- 第七次封存 holdout 观测写进 `docs/HOLDOUT_LEDGER.md`（**不得改写历史条目**）。
- `docs/REBUILD_VERIFICATION.md` 增第三轮，并重写「明确不声称」一节
  （现有那句「`sft-006` 的 0 违规是单次运行对比 2 次分布」在 n=3 后不再准确）。
- **观测必须发生在代码冻结提交之后**（`SEALED_PAIRING_FIELDS` 含 `code_commit`，
  两侧必须在同一 commit 上重算）。

### 失败模式（实施时主动防御）

1. **新素材与训练集重叠** → 互斥性必须比对**真实 `sft.jsonl`**，而不是分片构造。
2. **两份 OOD v2 数据集共用一个 `dataset_version`** → bank-004 的分片必须有自己的版本号，
   区分靠 `tasks_file_sha256` 而不是 `task_ids`。
3. **配置漂移** → 新评测配置相对既有配置只允许差 `attempt_id` 与 `adapter`/`model` 段，
   由治理测试逐字段断言。
4. **证据只留在 GPU 机器上** → 跑完同步回本地，
   `load_candidate_run_evidence(..., verify_artifacts=True)` 逐产物校验。
5. **把方差刻画写成候选选择** → 报告里不得出现「seed 2 更好所以…」这类句子。

---

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

（R0–R4.5 的历史错误台账已归档到 `progress.md`。）

### 进度

- [ ] 1. 预注册（本文件）提交
- [ ] 2. R-1 `--seed 2` 重训
- [ ] 3. 任务 B：测试瘦身
- [ ] 4. 任务 C1：干净 clone 实测
- [ ] 5. 任务 C2：去绝对化
- [ ] 6. 代码冻结提交
- [ ] 7. R-0 措辞池 bank-004 + OOD v2.3 sealed 构建
- [ ] 8. R-2 dev 60 配对评测
- [ ] 9. R-3/R-4/R-5/R-6 OOD v2.3 sealed 四次运行（该分片只此一次）
- [ ] 10. R-7/R-8/R-9 第七次封存 holdout 观测 + 两套 release 判定
- [ ] 11. 证据同步回本地 + 逐产物校验
- [ ] 12. 台账、文档、`PROJECT_LOG` 按报告口径落地
- [ ] 13. 任务 C1 复跑（对应最后一个提交）
- [ ] 14. 任务 D：独立验收并签字
