# Findings

## 2026-09-04 — Phase C2：同 seed 双跑实测——仍不逐位复现，方差已量化（gpu-5090）

- **设置**：sft-008 的训练配置（`retail_ops_v1_r6b_no_oversample_sft.yaml`，960 行 /
  180 步）同 seed（0）连跑两次（`reports/retail_ops/v1/r6/sft-008-determinism-{a,b}`），
  C1 的 `configure_training_determinism` 在两次里都以同一份 provenance 生效
  （两次 `metrics.json` 的 `determinism` 字段逐字段相同）。
- **判读（跑前写定，交接 §4 第 1 步）**：SHA-256 不同 → 分支 2。实测
  `adapter_model.safetensors` 哈希 `c7e7f765…` vs `4f4a4223…`。
- **方差量化**：180 个 loss 点上 mean |Δloss| = 7.4e-4、max |Δloss| = 2.8e-3；
  两条 eval_loss 曲线从第 2 次评估起分叉（0.1437 vs 0.1489，终值 0.1410 vs 0.1500）；
  adapter 权重 mean |Δw| = 2.96e-4。train_loss 终值 0.0407 vs 0.0401。
- **归因**：`determinism.provenance` 声明为不可消的 bitsandbytes NF4 /
  `paged_adamw_8bit` 内核 atomicAdd 归约（warn_only=True 放行并留痕）。
  C1 治理收窄了方差但按设计不能消除它。
- **表述治理**：`AGENTS.md`/`RESUME_EVIDENCE.md` 的「同 seed 逐位不同」从无边界表述
  收紧为「**C1 治理后、本配置 + 本卡（RTX 5090 / torch 2.13.0+cu130 / bitsandbytes 0.49.2）
  实测仍不逐位复现，loss 方差 mean 7.4e-4 / max 2.8e-3**」。dev「58–60/60」区间表述不变。
- 逐位复现不成立 → 按交接判读规则**不追加** PROJECT_LOG（方法论级结论未变更）。
- 成本：两次训练 ~20.5 min GPU，零 API 费用。

## 2026-09-04 — Phase C1：训练随机源固定（CPU 实现，GPU 验证待用户授权）

- `training/sft.py` 新增 `configure_training_determinism(torch, seed)`：在模型/优化器
  初始化**之前**固定可消随机源（cuBLAS 工作区 `:4096:8`、torch/python/numpy 种子、
  cuDNN deterministic=True + benchmark=False、`use_deterministic_algorithms(True, warn_only=True)`），
  并把 provenance 写进 `metrics.json` 的 `determinism` 字段。
- **可消**：cuBLAS 工作区、LoRA 初始化与 dropout 消费的全局 RNG、cuDNN 算法选择。
- **不可消（诚实记录）**：bitsandbytes NF4/`paged_adamw_8bit` 内核的 atomicAdd 归约
  （无确定性替代实现，warn_only 放行并留痕）；跨 GPU 型号/驱动的逐位复现。
- 测试 3 条（fake torch 注入；torch 不在 CPU venv，源码结构断言锁调用次序）。
- **C2（同 seed 双跑 adapter SHA-256 对比）需要 GPU，属决策门 #2，本轮未执行。**

## 2026-09-04 — Phase C3：二维迭代面生成器（CPU，探针 × 措辞池）

- 新模块 `retail_ops/domain/policy_boundary_phrasing_tasks.py`：任务**就是**
  `build_policy_boundary_tasks` 的产物（状态/gold/kind 逐字节相同），只换
  `user_request`（措辞池 `paraphrases_for_task` 确定性选取）与 `task_id`，
  metadata 携带 `phrasing_id`/`phrasing_partition`/`probe_task_id` 做归因。
- `ood_manifests` 登记新 dataset_version `retail_ops_policy_boundary_phrasing_v1_20260904`
  并开放组合模式（boundary=true + 交叉面措辞池）；既有互斥对 v2/v4 保持；
  scoped re-review Minor-1 修复后，交叉面版本号在 boundary=false 路径被显式拒绝
  （素材↔版本号双射不破）。
- 装置自洽：Oracle 全解 120 条零违规（措辞变化不破坏 gold 可解性）；确定性复验。
- **GPU 评测读数属另一次授权**；分片纪律沿用 OOD v2（train_aug 不得当评测面）。

## 2026-09-04 — Phase F1：测试补齐（7.2 清单）与治理测试自修复

按优先级补齐（每条都有失败先行或现状锁定说明）：
- §1.1 runner：FINAL_RESPONSE 非成功终止分支、自定义 system_prompt 进 messages、
  parse_error 不触达 guardrail 的隐含契约、user_simulator 的 `_known_order_id`/
  `clarification_metadata`（§1.7）；
- §1.2 parser：空响应、Pydantic 校验失败；**发现并记录**：`ToolCall.arguments` 有
  默认 `{}`（缺 arguments 合法）——显式写入测试；
- §1.3/§1.4 metrics：`split_headline_and_diagnostic`（DIAGNOSTIC_METRICS 只含
  verifier_reward）、bootstrap 全 True/全 False/对撞结局、全零步轨迹批、verifier
  三分量函数与 breakdown 同源；
- §1.5 schema：`validate_json_value`（非 JSON 类型/非字符串 key/NaN/Inf）、
  StrictModel 的 extra=forbid 与 allow_inf_nan（作用于 float 字段）；
- §1.8 环境：v4 的 CANCEL_ELIGIBLE/REFUND_THEN_CANCEL 环境层 Oracle 全解、
  同 idempotency_key 重放（v2 bundle schema 才接受该参数——v1/v3/v4 为严格双参数）；
- §2.2 边界：max_steps=1、max_steps=0 被 schema 拒绝、连续 unknown_tool、嵌套
  arguments；
- §3 治理测试自身：`_collected_test_count` 加收集失败护栏（不再把 import 错误误报成
  文档数字不符）；`_MUST_BE_ALLOWED` 语料跳过含当前台账值的句子（消除「当前值恰好
  不是 3」的巧合依赖，并断言跳过后仍有检验力）；故障矩阵 `>=20` 改为**每类故障
  小节至少引用 1 个真实测试**的结构绑定；e2e 硬编码值保留并写明「黄金锚」定位
  （环境有意变更时 consciously 更新）。
- 服务层 7.2 缺口（401/episode_timeout/空任务列表）经核实**已被前几轮修复覆盖**
  （test_retail_ops_service_layer:315 超时测试存在；manifest task_count ge=1 使空
  任务集不可达），本轮补普通 401 进指标的回归锚。

## 2026-09-04 — Phase A1 收尾：scoped re-review 结论

修复后复审（subagent + 主窗口 6 组独立突变复现，全部被杀）：**10 项修复全部通过，
无 Critical/Important 遗留**。3 个 Minor 的归宿：
1. 交叉面 dataset_version 在 boundary=false 路径可冒用 → **已修**（显式拒绝 + 测试）；
2. content-length 非 ASCII 数字使 int() 抛 ValueError → **已修**（非 ASCII 视同未
   声明 → 411 + 测试）；HTTP/2 可省略 content-length 的边界记录在案（当前服务是
   HTTP/1.1）；
3. backend_lock 是批内局部锁（跨批无串行化）→ **记录不修**：当前 CLI 单批用法不
   触发；同进程多批是未来场景，届时应把锁提升为 runner 级单例。

---

## 2026-09-04 — Phase B：v1.3 门禁上线与诊断性重算

### B1/B2 实现（TDD，`tests/test_release_gate_v13.py` 16 条）

- `GATE_IDS_V1_3 = (*GATE_IDS_V1_2, "policy_violation_count_max", "success_delta_ci_lower_min")`；
  v1.0/v1.1/v1.2 的 `GATE_IDS` 逐字节不动（既有测试锁定），磁盘上 11+ 份 formal 报告
  与 4 份 qualification 报告在 v1.3 代码上仍可加载，13 份 sealed 证据 report_id 复算不变。
- 两个新阈值以 `ReleasePolicyConfig` 的 `Literal[0]` / `Literal[0.02]` 类型锁钉死
  （沿用 `invalid_call_count_max` 模式）；**`domains/retail_ops/v1/release.yaml` 一个字节未动**
  （`bundle_sha256` 不变，既有证据配对前提保持），既有阈值锁测试继续成立。
  突变验证 4 处全红：Literal 放宽、门禁集合删门、违规门恒过、CI 宽度门退化为 ≥0。
- CI 下界由 `_core_gates` 单次计算、两个 CI 门禁逐位同源（重构不改变 v1.1 输出）。
- `decide_formal_release` 支持 v1.3 + OOD 证据；`_load_ood_evidence` 接受 1.2/1.3。
- **阈值数值（0 / +0.02）已于 2026-09-04 经用户确认冻结**（决策门 #1 关闭）。

### B3 诊断性重算（落盘 `reports/retail_ops/v1/r6/v13-diagnostic-obs5|obs6`）

当前候选 `sft-008`（合并部署形态）在 v1.3 口径下**两次观测都 NO-GO**——
这是绝对门生效的证据，不是失败；历史 GO（v1.0/v1.1 口径）保持原样不改写，两套判定并列：

| 观测 | 历史 v1.0/v1.1 判定 | v1.3 重算 | 被拦下的门 |
|---|---|---|---|
| 观测 5（原候选） | GO / candidate（ci_lower +0.0583） | **NO-GO** | `policy_violation_count_max`：违规 2 > 0 |
| 观测 6（重建候选） | GO / candidate（ci_lower **+0.0083**） | **NO-GO** | `policy_violation_count_max`：违规 7 > 0；`success_delta_ci_lower_min`：+0.0083 < +0.02（该次私有轨迹不在本机，报告按 fail-closed 落盘；宽度不足的结论以台账冻结读数 +0.0083 为准） |

附注：obs5 的配对轨迹哈希与 sealed 报告锚定值逐字核对通过（对抗审查 C-3 修复在真实数据上的首次验证）。
**本次重算是诊断，不消耗封存观测；真正的 v1.3 发布判定在 Phase D4 一次性进行。**

---

## 2026-09-04 — Phase A1：三 persona 全面 code review（评测基建 / SRE / 对抗审查）

三个独立 subagent persona 对 `src/veritool_rl/`、`scripts/`、`configs/`、`.github/workflows/`、
`tests/` 抽样做了书面审查；全部 Critical/Important 声称经主窗口逐条抽查复现后才采信。
共 5 Critical + 9 Important + 若干 Minor；**5C + 7I 已修复**（全部 TDD：先红后绿 + 突变验证），
2I + Minor 记录归宿。

### 已修复（Critical）

| # | persona | 问题 | 修复 |
|---|---|---|---|
| C-1 | SRE/对抗 | **FormalReleaseReport 无自哈希**——真正驱动 serve 部署的通道上，手工把 NO-GO 翻成 GO 可通过全部校验（类 docstring 声称有自哈希但实现缺失）；R1 通道的 ReleaseReport 有防护而正式通道没有 | 加 `report_id` 全字段自哈希 + `load_formal_release_report` 复算比对（旧报告 None 放行）；篡改/legacy/正例三测试，突变验证红 |
| C-2 | SRE/对抗 | **v1.2 OOD 门禁对残缺 base 证据 fail-open**：`.get("task_success", 0.0)` 把残缺 base 读成 0，`ood_success_delta_min` 恒通过，真实 delta 为负的候选可被洗成 GO | `_ood_gates` 对缺键/越界值判 FAIL（`invalid_ood_evidence`）；`_load_ood_evidence` 加载期校验必需键与 [0,1]；`decide_formal_release` 不再把越界值拷进报告字段 |
| C-1′ | 评测基建 | **episode 超时的僵尸线程与后续 episode 并发共享同一后端**：并发生成污染后续 `latency_ms`（发布门禁项）与显存峰值且无标记；serve 路径有信号量串行化而评测路径没有 | `episode_timeout` 增加 `backend_lock`（批内共享，僵尸持锁到自然结束，后续 episode 等待计入各自超时窗）；三条评测路径 + toolcount_eval 全部接入；测试编码「一个挂起毒化余下批次但整批照常返回、污染读数全部丢弃」的诚实语义 |

### 已修复（Important）

| # | persona | 问题 | 修复 |
|---|---|---|---|
| I-1′ | 评测基建 | `_failure_type` 把超时（INTERNAL_ERROR）归为 `verifier_failure`，基础设施失败混进模型失败 taxonomy（episode_timeout 的 docstring 承诺从未兑现） | 新增 `infrastructure_error` 分类；全超时批 `failure_type_distribution` 有测试 |
| I-2′ | 评测基建 | 全超时批 `compute_metrics` 抛 ZeroDivisionError（`format_error_rate` 无零分母守卫，唯一漏网的一行）——GPU 跑完全批后连 fail-closed 证据都拿不到 | 零分母守卫；回归测试 |
| I-3′ | 评测基建 | sealed 路径不传 `config.episode_timeout`，配置值被静默忽略（唯一产出 GO/NO-GO 的路径落回默认 30.0） | 传入 `config.episode_timeout` |
| I-4′ | 评测基建 | toolcount_eval 只兜异常兜不住挂起——findings #3 的「一步卡死锁死整批」在这条路径原样存在 | 改用 `run_episode_with_timeout` + 批内后端锁；超时记 `infrastructure_error="episode_timeout"` |
| I-2a | SRE | CLI `_paired_outcomes` 的守卫只硬编码 v1.1，放过同样需要配对证据的 v1.2 | 从 `GATE_IDS_BY_SCHEMA` 结构化推导（含 `success_delta_ci_lower` 的口径都需要），v1.3 自动覆盖 |
| I-3a | SRE | serve 的 episode 延迟指标**结构性恒为 0**：`_finish` 在路由体内读 `duration_ms`，而它在 observe 的 finally（call_next 返回后）才写入 | `_run_guarded` 内独立计时写 `episode_ms`；测试断言分位数 > 0 |
| I-4a | SRE | 未处理异常完全绕过请求指标与结构化日志；非 ASCII key 在 `hmac.compare_digest` 抛 TypeError → 不进任何日志的 500 | observe 增加 except 分支记录后重抛；`_authorized` 两侧先编码 bytes |
| I-5a | SRE | `_require_backend_matches_deployment` 对不声明 `model_dir` 的后端整体 vacuous pass——注入一个什么都不说的后端可绕过模型/adapter 核对 | 缺声明即 ValueError；测试 fake 同步收紧 |
| I-7a | SRE | 请求大小上限只查 content-length 头，chunked 传输绕过（整个 body 进内存后才被拒） | 带体方法无 content-length 一律 411（`_request_body_verdict` 可单测） |
| I-3a′ | 对抗 | **公开审计的 holdout 真值键名与真实 schema 对不上**：只认 `expected_final_state` 等四个不存在的键，`git add -f` 一份 holdout.jsonl（真实键 `initial_state`/`target_state`/`expected_calls`）六项审计全绿；`.jsonl` 后缀根本不在扫描范围 | 键表补真实 schema 字段；`STRUCTURED_SUFFIXES` 加 `.jsonl`；legacy 前缀豁免与相邻审计对齐；种违规测试（真实键名 JSONL 必须被抓到） |

### 对抗 C-3（Critical）：配对轨迹文件锚定

`_run_formal_release` 现在核对 `--*_trajectories` 文件的 SHA-256 与 sealed 报告
`private_artifact_sha256["trajectories.jsonl"]` 锚定值：不一致即拒绝。修复前该锚在
release 路径**零消费**——攻击者可摆一份边际一致（`_paired_ci_gate` 只校验边际）、
联合分布被操纵（成功任务摆在最大重叠 task_id 上）的逐任务证据把 CI 下界洗正。

### 治理测试修复（对抗 I-1 的可落地半边）

`test_release_configs_declare_their_gate_schema_version` 的允许集从硬编码
`{"1.0", "1.1"}` 改为从 `GATE_IDS_BY_SCHEMA` 结构化推导——原集合会**阻止 v1.2/v1.3
配置落地**（提交用最新最严口径的配置反而让 CI 红）。
**「新发布必须用最新 gate schema」的选购限制是政策决定，记入用户决策清单**（与
v1.3 上线一并决定），未单方面实现。

### 记录归宿（不修或待决策）

| # | persona | 问题 | 归宿 |
|---|---|---|---|
| I-2b | 对抗 | `SEALED_PAIRING_FIELDS` 不含 `inference_engine`/`runtime_env_sha256`——「换 venv 跑」在配对层仍无声通过（v1.2 记录了字段但配对不消费） | **待用户决策**：把两个 runtime 字段纳入配对是 pairing 语义变更，可能影响历史配对可比性；建议随 v1.3 发布判定（Phase D4）一并生效——base/candidate 两侧同引擎时零影响，且正好堵住发布判定那条路径上的洞 |
| M-1a | SRE | `release.json`/`report.md`/`report.html` 三份产物间无一致性绑定（手改 md/html 不被发现） | 记录。serve 只读 json，部署不受影响；绑定属加固项 |
| M-2a | SRE | `ServiceMetrics._latencies` 无界增长 | 记录。单卡服务生命周期内量级可控 |
| M-2′ | 评测基建 | `ToolSelectionScore.accuracy` 对 `compared==0` fail-open 给 1.0，与批汇总的 0.0 反向 | 记录。改动会影响 run_v3_degradation 消费方，且该曲线读数已作废；留待重跑前统一 |
| M-3′ | 评测基建 | `policy_violation_count` 在 core（按轨迹计数）与 toolcount（按实例计数）同名不同义 | 记录。core 侧口径是冻结契约，改名牵动证据 schema；使用处已注明 |
| M-6′ | 评测基建 | 超时测试头部注释描述已废弃的 ThreadPoolExecutor 实现 | 已修（测试文件自身更新） |
| M-3a | 对抗 | GO/OOD 成对检查与双语文档同步用手写文件清单（黑名单式） | 归入 Phase F1 处理 |

---

## 2026-09-04 — 评测脚本 Bug 审查报告修复收口（Phase A2）

前置说明：报告里 4 个高/中项在 2026-08-28 的两轮修复提交（`1e00c0c`、`829bf95`）里已有
部分实现，本轮补齐其测试证据并发现**超时修复本身还有一个真 bug**（见 #3）。
全部修复按 TDD 执行（先红后绿 + 突变验证）。

### 高/中严重度项归宿

| # | 归宿 | 说明 |
|---|---|---|
| #3 | **修复有缺陷，本轮重修** | `829bf95` 的 `with ThreadPoolExecutor` + `future.result(timeout)` 有两个问题：(a) `Executor.__exit__` 会 `shutdown(wait=True)` 等卡死线程返回——超时后调用方**仍被阻塞整个卡死时长**（实测慢策略 6.01s，轨迹字段正确但批次照样被锁死）；(b) 超时轨迹（`steps=[]`、`final_state={}`）进入 `replay_trajectory` 抛 `ReplayMismatch`，整批崩溃。重修：抽共享 `core/agent/episode_timeout.py`（daemon 线程 + 异常重抛），两处评测路径改用；replay 求和跳过 `INTERNAL_ERROR` 轨迹，其不完整性由既有 `_evidence_complete` fail-closed 承接。测试 `tests/test_evaluation_timeout.py` 7 条（含批内单条慢记录不锁死整批的负例、快策略逐字节不变的边界、耗时上界断言）；突变两处均验证红→绿。 |
| #1/#2 | 已修（`1e00c0c`），本轮核验 | Literal 扩到 5 个版本；CLI 以 `manifest.dataset_version` 传入 config。既有 OOD 测试套件锁定行为。 |
| #4/#13 | 已修（`829bf95`），本轮补测试 | `descriptions.get(name, schema.description)` 回退。补 `test_perturb_schema_falls_back_to_bundle_description_for_v3_tools`（v3 全 15 工具：dict 内沿用硬编码描述、dict 外回退 bundle 描述）；突变（改回 `[]`）红→绿。 |
| #5 | **本轮修复** | `evaluate_ood` 新增 `config.dataset_version == manifest.dataset_version` 校验，不一致抛错。负例（v1 manifest + v2 config 被拒）+ 正例（显式一致版本正常评测）；突变（删校验行）红→绿。 |

### 低严重度项归宿

| # | 归宿 | 理由 |
|---|---|---|
| #6 | **不修** | formal 路径当前没有任何调用方传 guardrail/user_simulator，重放与产出条件由「同一路径同参数」构造性保证；引入参数属 speculative change（没有调用方）。qualification 路径已正确双传且有测试。若未来 formal 启用 guardrail，必须同时改 run 与 replay 两处——这一点已在本表留档。 |
| #7 | **本轮修复** | `_MAX_STEPS = BaseEvaluationConfig.model_fields["max_steps"].default` 单源绑定；config Literal 成为唯一改动点，数据集侧仍由 `_require_step_budget` 运行时校验。补绑定测试。 |
| #8 | **不修** | 正式 `metrics.json` 保持 headline 精简是刻意设计：细分诊断维度（distractor/unknown/invalid）属于 `toolcount_eval.py` 的职责且已存在。两套口径含义不同是有文档的，不是缺陷；把它们合并反而稀释 headline 的可比性（v1/v2 冻结契约）。 |
| #9 | **本轮修复** | `retail_ops_ood_v4_r9_sft003.yaml` 的两行错置注释已删，改为描述实际配置（v4 bundle + sft-003 base+adapter）。纯注释，无哈希影响。 |
| #10 | **不修** | 与 #6 同类：OOD 路径 run 与 replay 当前都不带 guardrail，条件一致。留档同 #6。 |
| #11 | **本轮修复** | `_run_ood_evaluate` 在精确匹配校验前拦截配置里的 `dataset_version`，报错直接说明「版本取自 manifest.json，不在配置里声明」。补测试。 |
| #12 | **不修** | #5 校验生效后 config 侧值恒等于 manifest 侧值，`config_dataset_version` 字段没有信息量；加字段反而制造两处真相。 |

---

## 2026-09-04 — 最终指标根因综合分析（指针）

对 R2–R10 全部评测台账、诊断文档与代码现状做了四路并行审查，把「最终指标为什么
还不到」收敛为四层根因（难度切分偏移 / SFT 表面触发器 / 训练方差与约束 / 迭代面
饱和），并整理 24 条踩坑、8 条已证伪方向与 7 条解决办法入口。
**完整内容见 `docs/PITFALLS.md`**，此处不重复。

---

# 评测脚本 Bug 审查报告

**审查范围**：`src/veritool_rl/retail_ops/evaluate/` 全部模块、`product_cli.py` 评测入口、`configs/retail_ops/evaluate/`、`scripts/run_v3_degradation.py`。

---

### 1. OOD config 的 `dataset_version` Literal 只允许 2 个版本，实际有 5 个

**文件**：`ood_evaluation.py:64-66`

```python
dataset_version: Literal["retail_ops_ood_v1_20260815", "retail_ops_ood_v2_20260817"] = (
    "retail_ops_ood_v1_20260815"
)
```

`ood_manifests.py:69-79` 注册了 5 个合法 `OodDatasetVersion`（v1、v2、v2_2、policy_boundary、v4），但 config 的 Literal 只允许前两个。v2_2、policy_boundary、v4 无法通过配置传入 config。`evaluate_ood` 用的是 `manifest.dataset_version`（正确），但 `config.dataset_version` 参与了 `config_sha256` 计算——**所有 v2_2/policy_boundary/v4 的 OOD 报告的 `config_sha256` 里都嵌入了默认值 `"retail_ops_ood_v1_20260815"`**。

---

### 2. `_run_ood_evaluate` 不从 config 传 `dataset_version`，config 侧值永远是 v1

**文件**：`product_cli.py:752-757`

```python
ood_config = OodEvaluationConfig(
    model=ModelArtifact(**_config_mapping(config, "model")),
    adapter=...,
    generation=GenerationSettings(**_config_mapping(config, "generation")),
    code_commit=...,
)
```

`_OOD_EVAL_BASE_KEYS`（`product_cli.py:628-634`）不包含 `dataset_version`。即使配置文件里有这个 key，它也不会被传入 `OodEvaluationConfig`，因此 config 的 `dataset_version` 永远是 Literal 默认值 `"retail_ops_ood_v1_20260815"`。

**后果**：所有 OOD 评测报告的 `config_sha256` 里嵌入的数据集版本始终是 v1，即使 manifest 实际是 v4。config 声明的数据集版本被静默忽略。

---

### 3. 评测路径没有超时机制

**文件**：`runner.py:76`、`base_evaluation.py:458-473`、`ood_evaluation.py:161-164`

`run_episode` 在 `for index in range(task.max_steps)` 循环里调用 `policy.respond()`，没有超时。`execute_formal_records` 逐条调用 `run_episode`，也没有超时。

`serve` 路径有 `episode_timeout_s`（`product_cli.py:397-401`，`service.py` 用 `asyncio.wait_for` 实现），但评测路径完全没有超时。

**后果**：如果模型在一个步骤上卡住（例如推理链永不停止），整批评测会挂起。GPU 资源被锁死，直到人工干预。没有任何日志或指标能区分「模型在思考」与「后端挂了」。评测可以是 60、120 或 240 条任务，一条卡住就是整批挂住。

---

### 4. `perturb_schema` 的工具描述硬编码了 5 个工具名，v3 的 15 工具子集会 KeyError

**文件**：`environment.py:130-136`

```python
descriptions = {
    "get_order": "读取指定订单的当前详情。",
    "refund_order": "核验后执行符合退款政策的订单退款。",
    "get_store_hours": "读取指定城市的门店营业时间。",
    "get_refund_status": "查询指定订单的退款处理进度。",
    "cancel_order": "核验后取消尚未发货的订单。",
}
```

`perturb_schema`（`environment.py:137-153`）遍历 `self._bundle.tools`（bundle 全量工具），用 `descriptions[schema.name]` 取描述。v3 bundle 有 15 个工具，但 descriptions 只覆盖 5 个。如果 `allowed_tools` 包含未覆盖的工具名，会抛 `KeyError`。

**后果**：v1/v2 不受影响（3 个工具全在 dict 里）。v3 评测如果同时开 `perturb_schema` 和 `allowed_tools`，会在未覆盖的工具上 KeyError。当前 v3 评测配置没开 `perturb_schema`，所以没触发，但这是一个隐藏的硬编码 bug。

---

### 5. `OodEvaluationConfig.dataset_version` 与 manifest 的 `dataset_version` 没有做一致性校验

**文件**：`ood_evaluation.py:140-179`

`evaluate_ood` 校验了 `manifest.bundle_sha256 == bundle.bundle_sha256` 和任务数，但没有校验 `config.dataset_version == manifest.dataset_version`。

**后果**：config 里写的是 v1，manifest 实际是 v4，评测会正常运行。`OodRunEvidence.dataset_version` 用 manifest 的值（正确），但 `config_sha256` 里嵌入的是 config 的值（错误）。两份报告的 `config_sha256` 不可比。

---

### 6. formal base/candidate 重放不传 guardrail 和 user_simulator

**文件**：`base_evaluation.py:458-473`

```python
def execute_formal_records(...):
    def env_factory(task): return RetailOpsEnv(task, bundle)
    trajectories = [run_episode(record.task, env_factory, policy, seed) for record in records]
    replayed = sum(
        replay_trajectory(trajectory, env_factory).matched for trajectory in trajectories
    )
```

`replay_trajectory` 只传了 `env_factory`，没有 `guardrail_factory` 和 `user_simulator_factory`。qualification 路径（`evaluation.py:184-192`）正确传了这两个参数。

**后果**：当前 formal 路径不使用 guardrail/user_simulator，所以重放恰好匹配。但如果将来 formal 路径启用 guardrail 或 user_simulator，重放会不匹配且无法发现——`replayable_count` 会假阳性为满分。这是一个违反「重放条件必须与产出条件一致」不变量的脆弱性。

---

### 7. `_MAX_STEPS` 模块常量与 `BaseEvaluationConfig.max_steps` Literal 之间没有代码级绑定

**文件**：`sealed_evaluation.py:74`、`base_evaluation.py:116`

```python
# sealed_evaluation.py
_MAX_STEPS = 5

# base_evaluation.py
max_steps: Literal[5] = 5
```

`_require_step_budget`（`sealed_evaluation.py:692-696`）用 `_MAX_STEPS` 校验，而 `run_episode` 用 `task.max_steps`（来自冻结数据集）。config 的 `max_steps` 也是 `Literal[5]`。三者值恰好相等但互相独立——改一个忘改另一个不会报错。

**后果**：当前无 bug，但将来改步数预算需要同时改三个地方（`_MAX_STEPS`、`BaseEvaluationConfig.max_steps`、冻结数据集），且没有编译期或运行时绑定保证。

---

### 8. `tool_selection_accuracy` 在 `compute_metrics` 里没有分解 distractor/unknown

**文件**：`metrics.py:98-109`

`compute_metrics` 计算 `tool_selection_accuracy` 时，分母是 `max(len(actual_calls), len(expected_calls))`，分子是逐位命中数。它不追踪 distractor calls、unknown tool calls、invalid calls——这些只在 `toolcount_eval.py` 的 `score_tool_selection` 里有。

正式评测报告（`metrics.json`）里的 `tool_selection_accuracy` 是一个粗粒度指标，无法区分「模型调了不存在的工具」与「模型多调了一次正确的工具」。toolcount_eval 有细分指标（`distractor_calls`、`unknown_tool_calls`、`invalid_calls`），但这些不会出现在正式 `metrics.json` 里。

**后果**：正式报告的 `tool_selection_accuracy` 读数比 toolcount_eval 的 `tool_selection_accuracy` 含义不同——前者不分解失败原因。两种路径的数字不能直接比较（`toolcount_eval` 的 `compared = max(len(gold), len(actual))` 与 `compute_metrics` 的公式一致，但 toolcount_eval 的 `matched` 定义与 `compute_metrics` 的 `correct_tools` 定义也一致）。没有数据错误，但正式报告缺少 toolcount_eval 里的关键诊断维度。

---

### 9. 评测配置文件有冗余注释引用已不存在的配置

**文件**：`configs/retail_ops/evaluate/retail_ops_ood_v4_r9_sft003.yaml:3-4`

```yaml
# R9 Phase B sft-003 在 OOD v4（跨工具泛化，12 场景 × 10）上的评测。
# Phase B 核心主张的正面计量：语义重叠工具选择 × 说法泛化。
# R9 Phase B 第二轮候选（sft-002）在 OOD v2 dev 上的评测。
# v1 bundle 任务集（3 工具），检验措辞增强修复后 phrasing 泛化是否恢复。
```

第 3-4 行注释说「sft-002 在 OOD v2 dev 上的评测」「v1 bundle 任务集（3 工具）」，但这个配置实际是 sft-003 在 OOD v4 上的评测，使用 v4 bundle（`bundle_dir: domains/retail_ops/v4`）。注释是从其他配置文件复制过来的，描述的是另一个配置。

**后果**：无功能影响，但注释误导。

---

### 10. OOD 评测路径的 `evaluate_ood` 不做 replay 时的 guardrail 校验

**文件**：`ood_evaluation.py:168-171`

```python
replayed = sum(
    replay_trajectory(trajectory, lambda current: RetailOpsEnv(current, bundle)).matched
    for trajectory in trajectories
)
```

重放不传 guardrail。OOD 路径的 `run_episode`（`ood_evaluation.py:161-164`）也不传 guardrail：

```python
trajectories = [
    run_episode(task, lambda current: RetailOpsEnv(current, bundle), policy, manifest.seed)
    for task in tasks
]
```

所以当前重放条件与产出条件一致（都没有 guardrail）。但如果将来 OOD 路径启用 guardrail，重放会不匹配——与 issue #6 同一类问题。

**后果**：当前无 bug。与 #6 一起，是评测系统缺少「重放条件必须与产出条件一致」的编译期或测试层保障。

---

### 11. `_require_config_keys` 做精确匹配，OOD eval 配置不允许 `dataset_version`

**文件**：`product_cli.py:748`、`product_cli.py:1931-1935`

`_require_config_keys` 用 `set(config) != expected` 做**精确匹配**（不是超集）。`_OOD_EVAL_BASE_KEYS` 不包含 `dataset_version`，因此如果配置文件里写了 `dataset_version`，`_require_config_keys` 会**拒绝**它——但错误信息是「配置字段不符合命令契约」，不会告诉操作者「dataset_version 不在这里用」。

**后果**：操作者如果按直觉在 OOD eval 配置里加了 `dataset_version`，会得到一个不指向真正原因的报错。这与 OOD build 配置（有 `dataset_version` key）形成不对称——build 有，eval 没有。

---

### 12. `OodRunEvidence` 没有 `config_dataset_version` 字段暴露 config 侧值

**文件**：`ood_evaluation.py:79-123`

`OodRunEvidence.dataset_version` 取自 manifest（正确），但没有字段记录 config 里的 `dataset_version`。读者无法从报告追溯 config 声明了什么版本。

**后果**：无法发现 config↔manifest 的 dataset_version 不一致。

---

### 13. `RetLetEnv.perturb_schema` 不校验 bundle 工具是否在 descriptions dict 中

**文件**：`environment.py:137-153`

```python
for schema in self._bundle.tools:
    if schema.name not in self._allowed_tools:
        continue
    alias = f"{schema.name}_{rng.randrange(1000, 10000)}"
    ...
    schemas.append(
        ToolSchema(
            name=alias,
            description=descriptions[schema.name],  # KeyError if not in dict
            ...
        )
    )
```

与 issue #4 相同：`descriptions` dict 只覆盖 5 个工具名，`self._bundle.tools` 可能包含更多。

**后果**：v3 bundle + `perturb_schema` + `allowed_tools` 包含非前 5 工具 → KeyError。

---

### 14. sealed 路径的 `SealedEvaluationReport` 的 `config_sha256` 不包含 `adapter` 字段

**文件**：`sealed_evaluation.py:373-374`

```python
config_sha256=config.config_sha256,
```

`SealedEvaluationConfig` 继承自 `BaseEvaluationConfig`（`max_steps: Literal[5]`），外加 `adapter` 和 `merged_from`。`config_sha256` 是 `_content_sha256(self.model_dump(mode="json"))`（`base_evaluation.py:124-125`），包含全部字段（包括 adapter）。

**后果**：无 bug，config_sha256 正确包含了 adapter 信息。

---

### 15. `toolcount_eval.preflight_breakpoint` 用 `OraclePolicy` 但不传 seed

**文件**：`toolcount_eval.py:253`

```python
trajectory = run_episode(task, env_factory, OraclePolicy(task), seed=0)
```

Oracle 是确定性的（按 gold 序列执行），seed 不影响其行为。`run_episode` 把 seed 存入 metadata，不用于 Oracle。

**后果**：无 bug，seed 对 Oracle 无意义。

---

### 总结

| # | 严重程度 | 类型 | 文件 |
|---|---|---|---|
| 1 | 中 | Literal 不完整 | `ood_evaluation.py:64` |
| 2 | 中 | config 传参遗漏 | `product_cli.py:752` |
| 3 | 高 | 缺失超时 | `runner.py:76` |
| 4 | 中 | 硬编码 bug | `environment.py:130` |
| 5 | 中 | 缺失校验 | `ood_evaluation.py:140` |
| 6 | 低 | 脆弱性 | `base_evaluation.py:458` |
| 7 | 低 | 冗余常量 | `sealed_evaluation.py:74` |
| 8 | 低 | 指标粒度 | `metrics.py:98` |
| 9 | 低 | 注释错误 | `retail_ops_ood_v4_r9_sft003.yaml:3` |
| 10 | 低 | 脆弱性 | `ood_evaluation.py:168` |
| 11 | 低 | 配置校验 | `product_cli.py:748` |
| 12 | 低 | 可追溯性 | `ood_evaluation.py:79` |
| 13 | 中 | 硬编码 bug | `environment.py:137` |

---

# 7.2 测试覆盖盲区审查

**审查日期**：2026-08-28
**审查范围**：`tests/` 全部 90 个文件（1352 条测试）、`src/veritool_rl/` 全部源模块

---

## 1. 核心路径的测试覆盖

### 1.1 Agent 执行循环 (`core/agent/runner.py`)

`test_agent_runner.py` 有 8 条测试覆盖了 oracle 完成、格式错误消耗步数、政策违规终止、工具调用历史格式、终端响应记录。以下分支无测试：

- **user_simulator 分支 (runner.py:139-143)**：`test_retail_ops_user_simulator.py` 通过端到端测试间接覆盖了 `clarify=True, simulator=True` 的组合，但没有单元测试验证 `user_reply` 追加到 messages 后下一步 policy 收到的是带澄清内容的 messages。端到端测试只看到最终 `success=1.0`，看不到中间 messages 的形状。
- **非成功最终答复终止 (runner.py:171-173)**：`test_runner_records_terminal_response_before_verification` 覆盖了 `success` 路径，但没有测试 `final_response is not None and user_reply is None` 且 `reward.final_state != 1.0` 的路径（agent 说了结束语但任务没做完）。
- **system_prompt 参数 (runner.py:48, 68)**：没有单元测试验证传入自定义 `system_prompt` 后 messages 的 system 段确实被替换。`test_v2_prompt_carries_the_policy` 只验证了 prompt 文本生成，没有验证 `run_episode` 里它被放进了 messages。
- **guardrail 在 parse_error 路径的行为**：`test_retail_ops_guardrail.py` 测试了 guardrail 拦截 tool_call 的路径，但没有测试当 `parse_error is not None` 时 guardrail 是否仍参与（代码里 parse_error 路径跳过了 guardrail 检查——这是正确的，但没有测试确认这个隐含契约）。

### 1.2 Tool Parser (`core/agent/parser.py`)

5 条测试覆盖了主要路径。遗漏：

- **空响应 (parser.py:29-30)**：`parse_error="empty_response"` 分支无测试。当输入是空字符串时的行为未验证。
- **Pydantic ValidationError 路径 (parser.py:39)**：`json.loads` 成功但 `ToolCall.model_validate` 失败时（例如 arguments 里有非法类型），当前只测了 JSON 解析失败，没测 Pydantic 验证失败。

### 1.3 Metrics (`core/metrics.py`)

`test_metrics.py` 有 4 条测试。遗漏：

- **`split_headline_and_diagnostic` 函数 (metrics.py:32-36)**：完全没有测试。这个函数把 `verifier_reward` 分离出来，但没有任何测试验证分离逻辑。
- **`paired_bootstrap_delta_ci95` 的边界情况**：没有测试全 True、全 False、一半一半的配对结果。当前只在 `test_release_gate_schema_v11.py` 中间接覆盖了均匀改善和噪声带内的场景。
- **`compute_metrics` 中 `recovery_success` 和 `tool_selection_accuracy` 在零步轨迹上的行为**：`test_empty_metrics_have_defined_zero_denominators` 测试了空列表，但没有测试有轨迹但所有轨迹都是零步（`steps=[]`）的情况。

### 1.4 Verifier Rewards (`core/rewards/verifier.py`)

`compute_reward_breakdown` 在 `test_agent_runner.py` 和 `test_metrics.py` 中被间接覆盖。但：

- **`final_state_reward`、`policy_reward`、`milestone_reward` 三个独立函数 (verifier.py:32-47)**：完全没有独立测试。它们只是 `compute_reward_breakdown` 的分量包装，但没有任何测试验证它们与 `compute_reward_breakdown` 的一致性。

### 1.5 Trajectory Schema (`core/trajectory/schema.py`)

- **`validate_json_value` 函数 (schema.py:19-40)**：完全没有测试。这个递归验证器拒绝非 JSON 类型、非字符串 object key 和非有限浮点数，但没有任何测试覆盖。`test_trajectory_schema.py` 只测了 schema 零字段校验，没测这个验证器。
- **`StrictModel` 基类的 `extra="forbid"` 和 `allow_inf_nan=False`**：没有专门测试传入未知字段或 NaN/Inf 时是否被拒绝。

### 1.6 Replay (`core/trajectory/replay.py`)

`test_replay.py` 有 6 条测试。覆盖良好。遗漏：

- **`replay_trajectory` 对 `user_simulator` 产生的多轮轨迹的重放**：当前只测了单轮 oracle 轨迹和 retail_ops denial 轨迹的重放，没有测多轮（带 user simulator）轨迹的重放。

### 1.7 User Simulator (`core/agent/user_simulator.py`)

`test_retail_ops_user_simulator.py` 覆盖良好（提问识别、终端答复、回复上限、确定性、端到端三组对照）。遗漏：

- **`_known_order_id` 函数 (user_simulator.py:84-91)**：当 `task.metadata["order_id"]` 不是字符串或为空时返回 None，但没有直接测试。
- **`clarification_metadata` 函数 (user_simulator.py:94-97)**：完全没有测试。这个函数解析任务的 clarification 元数据，但没有任何测试覆盖。

### 1.8 RetailOps Environment (`retail_ops/domain/environment.py`)

`test_retail_ops_environment.py` 有 7 条测试，覆盖了主要场景。遗漏：

- **v3 任务（CANCEL/REFUND_THEN_CANCEL）在环境中的执行**：环境代码里有 `CANCEL_ELIGIBLE`、`REFUND_THEN_CANCEL` 等场景的处理逻辑，但环境层面的测试只覆盖了 v1 的 7 个场景。v4 新增场景（v3_tasks.py/v4_tasks.py）的行为没有在环境层面被测试。
- **`execute_tool` 传入不存在的 tool name 时的行为**：没有测试环境对未知工具名的拒绝。

### 1.9 Flight Ops

`test_flight_ops_eval.py` 有 4 条测试，覆盖了 oracle 评测、report ID 确定性、篡改检测、paired comparison。但：

- **FlightOps Environment 的政策拒绝路径**：`test_flight_ops_env.py` 的覆盖范围没有检查。FlightOps 有独立的 `policy_rules.py`，但没有测试验证其规则引擎与 RetailOps 的同构性。
- **FlightOps 的 guardrail 层**：完全没有 flight_ops 版本的 guardrail 测试。

### 1.10 Service Layer (`retail_ops/serve/service.py`)

`test_formal_service.py` 有 10 条测试，覆盖了 GO/NO-GO 回滚、health 端点、episode 运行、并发限制、请求大小限制。遗漏：

- **`/v1/tasks` 端点的分页或空任务列表行为**：没有测试当 build 目录为空时的行为。
- **鉴权失败路径**：没有测试 `api_key` 缺失或错误时返回 401 的行为。`test_project_governance.py` 只验证了参数签名，没有测试实际的 HTTP 401 响应。
- **`episode_timeout_s` 超时行为**：配置里有 `episode_timeout_s` 参数，但没有测试验证超时后 episode 被终止。

### 1.11 Product CLI (`product_cli.py`)

`test_product_cli_entrypoint.py` 和 `test_retail_ops_cli.py` 覆盖了主要 CLI 命令。遗漏：

- **`serve` 命令在无 API key 环境变量时的行为**：`test_formal_service.py` 里 `monkeypatch.setenv` 设了 key，但没有测试缺少 key 时报错的行为。
- **`build` / `evaluate` / `release` 命令传入不存在的 config 文件时的行为**：没有测试 config 文件缺失时的错误消息。

---

## 2. 边界条件测试

### 2.1 有测试的边界条件

- 最大步数（`test_format_errors_consume_steps_without_crashing_episode`）
- 空输入/空轨迹（`test_empty_metrics_have_defined_zero_denominators`）
- 格式错误输入（`test_qwen_parser_rejects_malformed_tool_call`）
- 不安全路径名（`test_sealed_evaluator_rejects_unsafe_attempt_identifiers`）
- 并发限制（`test_concurrent_episodes_are_capped_instead_of_queueing`）
- 请求大小上限（`test_oversized_request_body_is_rejected`）
- 配对证据缺失（`test_paired_ci_gate_fails_when_there_is_no_paired_evidence`）
- 分母为零（`test_undefined_ratios_fail_closed`）

### 2.2 缺失的边界条件

- **`max_steps=0` 或 `max_steps=1` 的 TaskSpec**：没有测试零步或一步的 episode 行为。runner.py 的 `for index in range(task.max_steps)` 在 `max_steps=0` 时直接返回空 steps 列表，但没有测试确认。
- **所有工具调用都失败时的轨迹**：没有测试连续 N 次 `unknown_tool` 后轨迹的 termination 和 metrics。
- **`bootstrap_samples` 大于轨迹数时的行为**：`compute_metrics` 里 bootstrap 采样在样本数大于轨迹数时的行为没有测试。
- **tool_call 的 `arguments` 包含嵌套对象、数组、null 值**：parser 测了 JSON 解析失败，但没测合法但深层嵌套的 arguments。
- **`idempotency_key` 重复时的环境行为**：`test_retail_ops_environment.py` 测了 `duplicate_refund`，但没有专门测 idempotency_key 相同的两次 refund_order 调用。

---

## 3. 测试本身的 Bug

### 3.1 `test_project_governance.py` 中 `_collected_test_count` 的脆弱性

`test_documented_test_count_matches_reality` (line 1463) 和 `test_the_author_environment_baseline_never_appears_without_the_clean_clone_one` (line 1493) 都调用 `_collected_test_count()`，该函数跑 `pytest --collect-only` 来获取当前测试数。这意味着 **测试在运行自身时会递归收集自己**，如果收集过程出错（比如 import 失败），报错信息会像是"文档数字对不上"而不是"import 失败"。docstring 里已经提到了这个风险（clone 上的 python 找不到），但没有 try/except 保护。

### 3.2 `test_the_total_count_detector_catches_what_it_claims_to` 的断言方向

`test_project_governance.py:1074-1089` 里 `_MUST_BE_CAUGHT` 语料库用的是当前观测次数的值（从 ledger 现算）。但 `_MUST_BE_ALLOWED` 里的句子如"封存 holdout 上前三次观测都是 NO-GO"——如果将来观测次数变成 3，`_count_offenders` 会因为它包含了数字 "3" 且在封存 holdout 作用域内而误判。当前 ledger 有 5+ 次观测所以 "3" 不是当前值，但这依赖于 ledger 的当前状态。**测试通过不是因为逻辑正确，而是因为当前那个数字恰好不是 3。**

### 3.3 `test_fault_matrix.py` 的最低引用数断言

`test_every_fault_class_names_a_real_test` (line 52) 断言 `len(references) >= 20`。如果故障矩阵被缩减到 19 个引用但仍然覆盖了所有五类故障，测试会失败——而 19 个引用可能比 20 个更精炼。这个阈值是任意的，没有绑定到任何设计约束。

### 3.4 `test_retail_ops_e2e.py` 的硬编码期望值

`test_retail_ops_v1_cpu_vertical_slice` (line 76-80) 硬编码了 `task_success == 8/12`（base）和 `task_success == 0.0`（fault）。如果环境行为变化（例如修复了一个 bug 让 base 从 8/12 变成 9/12），这条测试会失败——但它不是因为回归，而是因为进步。这些值没有绑定到任何规格文档。

---

## 4. 测试的确定性

### 4.1 确定性良好的部分

- `test_retail_ops_evaluation.py` 的 `test_identical_qualification_runs_write_identical_evidence` 直接验证了两次运行产生逐字节相同的结果。
- `test_metrics.py` 的 `test_oracle_metrics_match_hand_computed_values` 验证了同一份输入两次计算结果相同。
- `test_release_gate_schema_v11.py` 的 `test_paired_bootstrap_is_deterministic` 验证了 bootstrap 的可复现性。
- 所有使用 `seed` 参数的地方都使用了固定 seed。

### 4.2 潜在不确定性的来源

- **`_collected_test_count()` 依赖 pytest 收集顺序**：如果测试文件被重命名或新增，收集数变化会导致 `test_documented_test_count_matches_reality` 失败。这不是 flaky test，但是高维护成本的测试。
- **`test_gitignore_covers_every_class_of_artefact_that_must_not_ship` 依赖 `git ls-files` 和 `git check-ignore`**：如果开发者有未提交的 `.gitignore` 变更，这条测试的结果会不同。但因为用的是 `git ls-files`（只看已提交的），这个风险较低。
- **`test_the_documented_test_count_matches_reality` 在不同环境下可能给出不同数字**：`pytest --collect-only` 的结果取决于当前 Python 环境安装的依赖（某些测试可能被 skip 或 conditional skip）。

---

## 5. 治理测试的有效性

### 5.1 有效且深入的部分

- **`test_gitignore_covers_every_class_of_artefact_that_must_not_ship`**：双向验证——既验"该忽略的被忽略了"，也验"该进 Git 的没被忽略"。这是防止 `.gitignore` 规则过宽的唯一机制。有效。
- **`test_source_layers_enforce_one_way_dependency`**：通过 grep import 语句验证层间依赖方向。虽然不覆盖动态 import 和 `__import__`，但对当前代码库足够。
- **`test_service_credentials_never_live_in_the_repo`**：验证配置文件里没有凭据字段、`create_formal_app` 的 `api_key` 参数没有默认值。有效。
- **`test_the_config_governance_scan_catches_a_planted_violation`**：反向验证——种一个违规必须被抓到。这证明治理扫描不是空操作。

### 5.2 有效性不足或表面化的部分

- **`test_holdout_ledger_is_the_single_source_of_truth`**：断言了台账里有特定字符串（`"唯一事实源"`, `"LOG-20260811-03"` 等），但这只是在检查**措辞在场**，不是在检查**机制有效**。台账的"唯一事实源"地位实际上由 `test_no_active_doc_restates_the_sealed_holdout_observation_count` 扫描全部 Markdown 来保障——但那条测试的检测器自己有明确记录的漏检（docstring 里写了四种挡不住的写法）。
- **`test_v1_domain_bundle_is_byte_identical_to_the_frozen_evidence`**：断言了一个特定的 SHA-256 哈希值。这是有效的冻结检查，但哈希值本身是硬编码的——如果 bundle 内容被合法修改（比如修复一个拼写错误），测试会失败，而失败的原因是"旧哈希不对"而不是"你改了不该改的东西"。测试没有区分"合法修改"和"非法篡改"。
- **`test_the_r3_candidate_shares_the_base_model_with_its_control`**：只验证了 `retail_ops_v1_r3_qwen3_4b_candidate.yaml` 与 `retail_ops_v1_r2_qwen3_4b_dev.yaml` 的 model 段相同。但如果有人新增了一个候选配置而没有配对 base 配置，这条测试不会捕捉到——它只检查已列出的两份配置。
- **`test_release_configs_declare_their_gate_schema_version`**：只验证 `gate_schema_version in {"1.0", "1.1"}`，不验证这个版本号是否与实际使用的门禁集合匹配。一份声明了 `"1.1"` 但实际用 v1.0 门禁的配置不会被这条测试抓到。

### 5.3 治理测试的结构性盲区

- **配置的 `file_sha256` 内容是否真实**：`test_every_committed_config_holds_the_governance_line` 验证了 `file_sha256` 是 64 位十六进制，但不验证它是否与实际模型文件匹配。一个写了正确长度但错误值的哈希会通过。
- **`model.revision` 是否可解析**：测试验证了 `revision` 长度 >= 7，但不验证这个 revision 在模型仓库中是否存在。
- **configs 和 domains 的一致性**：没有测试验证配置文件引用的 `bundle_dir` 是否存在且包含有效 bundle。配置引用了一个不存在的路径不会被测试抓到。

---

## 6. 测试的维护成本

### 6.1 测试数量

1352 条测试，90 个测试文件。

### 6.2 高维护成本的测试

- **`test_project_governance.py` (1823 行)**：这是全仓最大的测试文件，包含 ~30 条测试。它承担了文档一致性、数字配对、双语同步、观测次数单一来源、简历 bullet 审计等多个不相关的职责。每次修改 README、RESUME_EVIDENCE、MODEL_CARD、GENERALIZATION_FIX 等文档都可能触发多条测试失败。这些测试的失败消息通常很长且难以快速定位根因。
- **`test_fault_matrix.py`**：虽然只有 79 行，但它解析故障矩阵的 AST 来验证引用存在性。这种"测试文档里的测试引用"的元测试维护成本高——改一个测试名就要同步更新文档。
- **`test_sealed_evaluation.py` (491 行)**：使用了 `module` 级 fixture (`formal_source`)，这意味着如果 fixture 构建失败，整个模块的所有测试都会失败，而不是单条失败。`formal_source` 调用了 `write_formal_task_set` 和 `load_bundle`，这些操作在测试环境不存在私有数据时会跳过。

### 6.3 测试运行时间

大部分测试是纯 CPU 逻辑测试，应该很快。但以下测试可能较慢：

- `test_retail_ops_e2e.py`：跑完整的 build → evaluate → release 全链路。
- `test_sealed_evaluation.py`：构建 120 条形式化任务并重放。
- `test_retail_ops_guardrail.py` 的端到端注入评测：构建 12 条注入任务并跑两轮。
- `test_retail_ops_user_simulator.py` 的端到端三组对照：构建 36 条任务。
- `_collected_test_count()` 在每条调用时都会跑一次 `pytest --collect-only`。

### 6.4 测试与文档的耦合

`test_project_governance.py` 里大量测试直接读取并断言特定文档的内容（README、RESUME_EVIDENCE、MODEL_CARD 等）。这意味着**文档修改和代码修改会互相触发测试失败**。AGENTS.md 里的规则（如"候选结论一律以 dev 或 holdout 口径分别陈述"）由这些测试执行，但测试的失败消息通常引用的是文档字符串而不是规则本身。
