# Task Plan: RetailAgentOps

## Goal

在 12 周内交付可公开、可复现、可面试解释的零售工具 Agent 单卡适配与发布流水线。
R0–R6（含「R6 收口」）已完成，阶段状态以 `docs/EXECUTION_PLAN.md` 为准，
历史任务摘要在 `progress.md`。

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
