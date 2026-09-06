# 交接：B-4 数据重建（v5 分层冻结 + 口径 A + max_steps 6）执行 + DPO 负结果分析——新窗口执行提示词

**日期**：2026-09-06
**性质**：DPO 主线判读收口（修坏，LOG-20260906-01）后的下一窗口执行入口。
**决策记录**：用户 2026-09-06 授权窗口执行者自决高含金量任务方向；执行者裁定
**批准 B-4 数据重建立项**（采纳 `PROPOSAL_DATA_REBUILD_B4.md` 的建议选项：
(a) 批准独立立项、(a) mimo-v2.5 ~700 任务、(a) DPO 判读收口后再启动——已满足）。
**执行者**：新窗口的 coding agent；允许 subagent（读数与结论须抽查验证）。
**授权状态**：GPU 与 mimo API 沿用既有授权（gpu-5090、mimo-v2.5，费用逐次记账）；
封存 holdout 观测次数不受限（用户 2026-08-17），但结果永远不得反馈进开发。

---

## 0. 一句话背景

发布候选 `sft-008` 在 v1.3 绝对门（封存集零政策违规）下 NO-GO（违规 2）；
SFT 补数据（R7）与单方向 DPO（R11）两次以相同机制判负——**干预在目标区域有效、
在未干预区域产生未建模副作用**。两次共享的结构性根源是根因 1：训练分布从未
覆盖远超期区（`refund_denied_window` 的 margin ≥10 family 占比 train 10% vs
holdout 50%，5.0× 偏移；判定分界日 `offset = 0` 整个冻结集从未生成）。
B-4 = 一次 R2 量级的数据重建：**难度分层切分 + margin 0 档 + reason 口径 A +
max_steps 6**，合并付一次全价。这是绝对门唯一未证伪的根治路径。

## 1. 先读这些（按顺序）

1. `AGENTS.md`（不可违反边界 + 固定流程 + cpolar 运维入口）
2. 本文件 §5（**DPO 负结果分析**——v5 训练数据设计的三条直接约束从这里来）
3. `docs/PROPOSAL_DATA_REBUILD_B4.md`（立项方案：分层算法、配额、预算、断裂清单）
4. `docs/POLICY_BOUNDARY.md` §2（分层诊断的证据：覆盖表与 5.0× 偏移的复算测试）
5. `docs/PITFALLS.md` §三（**9 条**已证伪方向——含新追加的 #9 单方向 DPO）与 §二 #1/#2/#5/#8
6. `docs/PROJECT_LOG.md` 最后一条（LOG-20260906-01）+ `findings.md` 2026-09-06 各节
7. `task_plan.md`（Errors 表 2026-09-06 两条：bank-004 误判与更正——**私有根布局
   与 `bank_sha256` 内容哈希语义**两课直接服务本窗口）
8. `src/veritool_rl/retail_ops/domain/formal_tasks.py`（v1/v4 生成器与
   `assert_exact_quotas_v4`——v5 的结构起点）、
   `configs/retail_ops/build/retail_ops_v4_r9_planb_formal_freeze.yaml`（v4 冻结配置先例）

## 2. 已冻结决策（遇到不要再问，也不要重开）

| 决策 | 结论 | 出处 |
|---|---|---|
| 发布候选 | **`sft-008`（原始 seed 0 合并形态）不变**；D4 NO-GO 维持；`sft-008-dpo-001` 判修坏、不进入任何候选比较或对外材料 | A-6 判读（LOG-20260906-01） |
| B-4 立项 | **批准**（用户授权自决）；mimo-v2.5 ~700 任务；DPO 收口后启动（已满足） | 用户 2026-09-06 授权 + 本文件 §0 |
| v1.3 阈值 | `policy_violation_count_max=0`、`success_delta_ci_lower_min=+0.02` 冻结不变——**v5 的发布判定沿用同一套门**，变的只是数据集 | LOG-20260904-02 |
| v1.4 配对 schema | 已就绪未启用；是否在 v5 判定启用**单独问用户**（不捆绑） | B-2（`SEALED_PAIRING_FIELDS_V1_4`） |
| PITFALLS §三 #9 | 单方向（DENY-only）偏好对 DPO 不得原样重试；重试前置条件见 §5.6 | LOG-20260906-01 |
| bank-005 | **多余素材，永不进入任何评测面**（与 bank-002/004 有记录级重叠；留档 `phrasing_exclusivity_bank005.json`） | task_plan Errors 2026-09-06 |
| 探针与 OOD 面 | 探针网格、OOD v2/v2.2/v2.3 任务集**逐字节不动**（跨候选可比性保留）；v5 只换冻结数据集与训练分布 | B-4 提案 §五 |

## 3. 资源与凭据

### 3.1 gpu-5090

- 远端仓库 `/mnt/aidata/tongjiakai/retail-agent-ops`；**远端访问 GitHub 不稳定**，
  同步走本地 `git push ssh://gpu-5090/mnt/aidata/tongjiakai/retail-agent-ops main:refs/heads/<tmp>` +
  远端 `git merge --ff-only <tmp>`（today 验证可用）。
- cpolar 隧道拒连时：本地命令 **`cpolar-ssh-update`**（AGENTS.md 已记录），再重试。
- `models/Qwen3-4B-pinned`、`models/Qwen3-4B-sft-008-merged`（70981220…）、
  bank-001..004（`data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722/phrasing/`）
  均在远端；**bank-004 本地/远端双份**（2026-09-06 rsync，哈希已核）。

### 3.2 LLM API（mimo-v2.5）

- 本地 `.env` 也有 mimo 凭据（bank-005 生成本地跑通，$0.0244/947 条可作单价参照）。
- teacher 全量采集前**必须** `--dry_run` 估量；分场景审措辞先验（PITFALLS #5）；
  分片覆盖断言与回环分类丢弃率盯 LOG-20260905-03 的 bank-004 先例。

### 3.3 本窗口的 operational 教训（全部真实踩过，逐条生效）

1. **每次推送前必须跑全量门禁**：`pytest | tail` 会吞退出码，管道后必须 `echo $?`
   或用 `set -o pipefail`。82fa8c2 加测后漏跑全量门禁 → CI 连红 6 轮（基线算术守卫）。
2. **新产物目录（含 smoke/自检）先写进 task_plan 运行清单再跑**——声明守卫
   （`test_every_declared_run_directory_is_actually_declared`）事后补会红一轮。
3. **声明哈希的语义**：`bank_sha256` = 内容规范化哈希（`bank_sha256(records)`），
   不是文件字节 sha（R11-1 首启被拦）。
4. **宣告素材丢失前**：用内容哈希逐目录核对两台机器的全部私有根布局——
   `find` 深度限制与单布局假设导致 bank-004 误判丢失（ Errors 表有更正行）。
5. **sha256sum 的 glob 盲区**：pin 逐文件清单前先 `ls` 实际文件集
   （adapter 的 README.md/training_args.bin 被 glob 漏掉 → 评测首启被守卫拦）。
6. `pkill` 后 `pgrep -af` 验证真死；启动后 `ps -eo args` 确认单实例
   （pgrep 自匹配误判有过事故）；输出目录不可覆盖；重跑前删旧目录。

## 4. 负结果分析：DPO 修坏（本轮主交付之一，v5 的设计输入）

### 4.1 事实层

27 对偏好对（全部 `offset −14`、chosen=Oracle 拒绝、rejected=模型自身真实失败
采样）+ 12 优化步后：目标格 −14 从 0.375 → **1.00**（完全校准）；**放行侧 8 点
全部 < 0.90（7 点 ≤ 0.25：+0/+7/+10/+14 = 0.00）**；dev 58–60 → **53/60**；
ood_dev 0.9833 → **0.6333**。探针失败构成从混合变为纯边界型
（premature_final_response 58 条 = 放行侧直接拒绝收尾 + policy_violation 5）。

### 4.2 机制层（为什么单向 DPO 平移了边界）

DPO 的梯度 = 拉开 chosen 与 rejected 的相对 logprob。27 对中「拒绝 vs 执行」
标签与真实语义状态**完全相关**（全部 DENY 格）：模型能提取的最省力特征不是
「订单过期才拒绝」（需读 `refund_deadline` 并与 `current_day` 比较——真正的
决策变量），而是「拒绝退款本身受偏好」的低维捷径。偏好压力因此被均匀施加到
所有 refund 决策点，而不是被状态变量调制。**−14 修到 1.00 同时放行侧塌方，
正是这条捷径的指纹**：压力有效（目标格满）且无差别（其余全动）。

### 4.3 设计层（门禁守卫方案错在哪）

门禁守卫的前提「放行侧采样零错误 → 无需对冲对」在采样时确实成立，但
**前提成立 ≠ 对冲不必要**：放行侧零错误只说明当前策略没有可采样的失败，
不说明 DPO 的压力不会把策略推离当前状态。对冲对的价值从来不是「修正已有
错误」，而是「锚定不应动的区域」。把它从数据侧（对冲对）挪到判读侧（事后
拦截门禁）的代价 = 烧掉一轮完整训练才确认平移。D2 §四 的预警（「DPO 在
拒绝/执行二元边界上容易整体平移；对冲对设计是关键」）被实测命中。

### 4.4 量化边界

- **能确定**：本设计（DENY-only、27 对、12 步、本配置）修坏；n=1 无消融。
- **不能确定**：功效不足与方向性平移不可分离（但「没动」被 −14=1.00 排除）；
  对冲对能否既校准目标格又锚定放行侧（未试，预注册禁止本轮重试）；100–200 对
  是否不同（未试）。
- **不声称**：DPO 方法对此失败模式一般化无效。若未来重试，前置条件 =
  **放行侧对冲对**（chosen=放行侧执行、rejected=放行侧拒绝，锚定对）+ ≥100 对
  + 双侧判读面不变。

### 4.5 方法论衔接（简历/面试叙事素材）

R7（SFT 补数据）与 R11（DPO 单向对）**两次以同一机制判负**：干预在目标区有效、
在未干预区有未建模的副作用——「单侧/同源评测面高估收益」的普适版。两次都被
**事先写定的判读规则**拦下而非事后自觉（预注册纪律第三次实证）；探针连续
第三次把模糊失败定位成可读曲线（R7 定位单格，R11 画出平移形状）。**负结果
不是流程失败：它以一次 ~2.5h GPU 的成本，证伪了一个看似合理的设计并产出
可复用的前置条件清单。**

### 4.6 对 v5 训练数据设计的三条直接约束

1. **双侧对称覆盖是数据分布的属性，不是干预的属性**：分层切分必须让每个
   margin 档（含 0）在 train/dev/holdout 同时出现、拒绝侧与放行侧同覆盖
   ——R7 的「两侧对称补」是干预层补丁，v5 把它变成切分层的结构性质。
2. **措辞 × 状态不得再产生伪相关**：增强/采集素材的 user request 必须取自
   被增强场景自己的模板（R7 §6.4 自查的教训），冻结前跑「措辞 → 结果」
   关联检查（同一说法在拒绝侧与放行侧都应出现，除非语义本身禁止）。
3. **评测面纪律不变**：v5 判读仍是三面成对（探针/dev/ood_dev）+ 分布外退化
   优先；新封存集只观测一次。

## 5. 轨道 A：v5 数据重建执行（本窗口主线）

**dataset_version = `retail_ops_v5_20260906`**（版本↔内容双射；结构起点 =
`retail_ops_v4_20260905` 的场景/family 结构）。

### A-0 与用户确认的方案点（正式稿确认后才能动）

1. **v5 结构范围**：场景集与 family 结构沿用 v4_20260905（含 rtc_stepwise
   train-only 辅助场景）——建议沿用（避免同时改两个变量）；若用户希望收窄到
   v1 8 场景，重建成本不变但 rtc 成果丢一次重训验证。
2. **reason 口径 A 的可接受集合定义**：每个 `refund_order` gold 的 reason 从
   单一枚举改为「用户事实标签 → 可接受集合」（如 受损 → {damaged}、不符描述 →
   {not_as_described, damaged}）——具体映射表需用户逐条确认（这是判分契约，
   不是实现细节）。
3. **判读阈值正式稿**（§A-6 草案的数字经用户逐个确认后冻结提交）。

### A-1 预注册（先于一切运行）

判读规则正式稿 + 运行清单（产物目录逐字声明，**含 smoke/自检目录**）写进
task_plan.md 并提交。产物前缀 `reports/retail_ops/v1/r12-v5/`。

### A-2 CPU 实现（TDD，零 GPU/API）

| # | 任务 | 要点 |
|---|---|---|
| A-2.1 | `formal_tasks.py` v5 生成器 | 分层切分键（难度标量 → 7+1 档，档内 sha256 排序轮转分配 20/5/10）；margin 网格 +0（放行侧 `20+margin` 含 0）；反泄漏断言（family 身份跨 split 互斥、评测 margin 值不入 train 同格同措辞） |
| A-2.2 | `assert_exact_quotas_v5` | 每场景配额 + **覆盖表断言**：每场景 dev/holdout 覆盖全部难度档；margin ≥10 family 占比 train:holdout ∈ [0.8, 1.25]（对照现状 5.0×） |
| A-2.3 | reason 可接受集合（口径 A） | `TaskSpec.expected_calls` 的 reason 参数承载集合（新字段或编码约定，**向后兼容 v1–v4**）；verifier 按集合判定（版本化：仅对声明口径 A 的 dataset_version 生效，旧证据复算逐位不变） |
| A-2.4 | max_steps 6 | sealed config Literal 同步（单源绑定处）；旧数据集的 Literal 不动 |
| A-2.5 | `formal_manifests.py` 登记 | `retail_ops_v5_20260906` 版本 Literal + 冻结配置 |
| A-2.6 | Oracle 自洽测试 | gold 序列全可解零违规（含 margin 0 档、口径 A 集合）；「措辞 → 结果」关联检查（§4.6 约束 2） |

### A-3 freeze + 覆盖验收（本地 CPU，确定性）

`formal_freeze` v5 → 覆盖表落盘（逐场景 × 难度档 × split 计数）→ 与 §2 的
覆盖断言比对 → **5.0× → ~1.0× 的机器证明**写 findings。产物：
`data/private/retail_ops/v1/r2/retail_ops_v5_20260906` +
`manifests/retail_ops/v1/retail_ops_v5_20260906`。

### A-4 teacher 采集 + 训练导出（mimo，~700 任务）

dry_run → 分场景措辞先验审查 → 全量采集（接受率 ≥0.80 分桶门禁）→
train_export（措辞 ×3，无 oversample）。产物：
`data/private/retail_ops/v1/r2/retail_ops_v5_20260906/teacher-collection/teacher-v5-001`
与 `train-export-v5-001`。

### A-5 训练 + 三面评测 + 新封存集（GPU 0；命令清单逐条确认后执行）

| # | 运行 | 产物目录 |
|---|---|---|
| A-5.1 | 训练 `sft-v5-001`（QLoRA，~35 min） | `reports/retail_ops/v1/r12-v5/sft-v5-001` |
| A-5.2 | v5 dev 评测（配对 base 另跑或沿用同批） | `reports/retail_ops/v1/r12-v5/dev-base-001` / `dev-candidate-001` |
| A-5.3 | OOD v2 评测（既有分片，跨候选可比） | `reports/retail_ops/v1/r12-v5/ood-v2-candidate-001` |
| A-5.4 | OOD v4 评测 | `reports/retail_ops/v1/r12-v5/ood-v4-candidate-001` |
| A-5.5 | 探针评测（−14 曲线是绝对门的先行指标） | `reports/retail_ops/v1/r12-v5/probe-candidate-001` |
| A-5.6 | v5 封存 holdout 观测 8：base + candidate | `reports/retail_ops/v1/r12-v5/holdout-base-008` / `holdout-candidate-008` |
| A-5.7 | `release --gate_schema_version 1.3`（v1.4 与否单独确认） | `reports/retail_ops/v1/r12-v5/formal-release-008` |

### A-6 判读（草案——阈值经用户确认后冻结，一个字不改地用）

| 分支 | 判据 | 后续 |
|---|---|---|
| **修好** | v1.3 十二门全 PASS（含绝对门违规 0、ci_lower ≥ +0.02、OOD 两门）且探针无单点塌方（15 偏移每点 ≥ 0.875） | 换候选 `sft-v5-001`；对外材料按新口径成对陈述 |
| **修坏** | 任一门 FAIL（尤其绝对门）或探针/ood_dev 出现单侧塌方形状 | 不换候选；负结果入账；绝对门路径就此穷尽，如实收官 |
| **边界改善但未达标** | 十二门 PASS 但探针单点 < 0.875（或反之） | 依预注册分支细则，升级需用户确认 |

无论哪种结果：不重跑、不换素材再试；判读只用可迭代面 + 一次性封存观测；
台账（HOLDOUT_LEDGER 观测 8、LOG、EXECUTION_PLAN）同日收口。

## 6. 轨道 B（可选并行，均为小项）

- **B-a**：`INTERVIEW_PREP.md`/`RESUME_EVIDENCE.md` 补 DPO 负结果叙事
  （§4.5 的四段骨架：假设 → 偏好工程 → 守卫拦截 → 机制归因）——**高含金量、
  零风险，建议随 A-3 收口一起做**。
- **B-b**：`scripts/ops/plot_degradation_curve.py` 之外补一张探针三模型对比图
  （base / sft-008 / dpo-001 的平移曲线）——面试可视化素材。

## 7. 硬边界（全部沿用）

- 封存结果永远不反馈进开发；已证伪方向（PITFALLS §三 **9 条**，含 #9 单方向
  DPO）不得原样重试；不为数字好看改任务/关守卫/挑读数；历史文档 append-only；
- 不改 v1–v4 冻结契约与既有数据集；v5 一切新契约走新 dataset_version；
- 判读规则与运行内容先于观测提交；观测在代码冻结提交之后；
- 每条远程 GPU 命令给出工作目录 / 物理 GPU / 预计时长 / 产物，偏离先停下确认；
  API 费用逐次记账；Python 统一 uv；文档默认简体中文；origin push 已批准
  （远端同步走 ssh 临时分支 + `--ff-only` merge）。

## 8. 验收（每轮收口全绿）

```bash
.venv/bin/pytest -q                    # 全量，必须先于 push（见 §3.3 教训 1）
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy
env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check
git diff --check
.venv/bin/python scripts/ci/verify_qualification_chain.py
.venv/bin/python scripts/ci/audit_public_release.py
# 干净 clone 实跑 + 文档基线同步（测试数变了必须四个文档同步，算术守卫会算总账）
```

## 9. 故障手册指针

- 训练 loss 全零（截断/mask）：LOG-20260905-02 + 渲染长度守卫（dpo.py 先例）
- gpu-5090 驱动卡死：E2 交接 §5.5；cpolar 拒连：`cpolar-ssh-update`（AGENTS.md）
- teacher/bank 生成失败（分片覆盖、回环丢弃）：LOG-20260905-03 与 bank-004/005 先例
- GitHub 不可达：ssh 临时分支 + `--ff-only` merge（本文件 §3.1）
- 双进程并行事故：LOG-20260905-02 事件三
