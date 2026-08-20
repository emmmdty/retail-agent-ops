# Task Plan: RetailAgentOps

## Goal

在 12 周内交付可公开、可复现、可面试解释的零售工具 Agent 单卡适配与发布流水线。
R0–R6（含「R6 收口」）已完成，阶段状态以 `docs/EXECUTION_PLAN.md` 为准，
历史任务摘要在 `progress.md`。

## Current Phase

**R7 质量收口**：三件实质工作——**把一个候选的效果做得更好**（诊断并修复
「该拒绝却执行」这条失败模式）、**测试瘦身**（删掉断言文档字符串的治理测试，
测试总数下降）、**口径实测**（干净 clone 的 pytest 读数实测）。

原定的第一件事是「跑第三个训练 seed 做方差刻画」，用户 2026-08-19 判定
「多跑一个 seed 的意义不大，我们不是写论文」并改向，详见 Task A。

**本轮不允许通过新增治理测试 / 文档字符串扫描 / 正则守卫「提分」。**
产物前缀用 `r8`（轮次计数，比阶段标签大一，因为「R6 收口」占用了 `r7`）。

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
- [ ] 10. 任务 C：干净 clone 复跑，把文档里那个推算值换成实测值
- [x] 11. 任务 D：独立验收并签字 → **被 R8 Task A1 取代**（一个面试官升级为三轮严苛独立审查）

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
商业 API **是**（C1 的 teacher 采集）、
封存 holdout 观测**否**（本轮不消耗，结论不是发布结论）、
**C2 推翻 R4.5 时未选 B 的判定**（治理痕迹见 LOG-20260819-02）。
