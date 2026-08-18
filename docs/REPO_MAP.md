# 仓库地图

本文件说明每个目录的职责、活动/归档状态，以及 2026-08-09 目录收敛的路径对照。
产品契约见 [`SPEC.md`](../SPEC.md)，阶段状态见 [`EXECUTION_PLAN.md`](./EXECUTION_PLAN.md)。

## 1. 组织原则

仓库按**四个稳定接口**（`build` → `evaluate` → `release` → `serve`）组织，与
`SPEC.md` 第 3 节的对外契约一一对应。任何目录只属于三类之一：

| 类别 | 含义 |
|---|---|
| **活动** | RetailOps 主线，当前阶段会读写 |
| **归档** | 已完成阶段的过程记录或历史证据，只读、不删、不再演进 |
| **legacy** | 原 VeriTool-RL 研究路线的实现与产物；除 BFCL 外部回归外不再投入 |

## 2. 顶层目录

| 目录 | 状态 | 职责 |
|---|---|---|
| `src/veritool_rl/` | 活动 | 全部实现代码（导入名保留，见第 5 节） |
| `domains/retail_ops/v1/` | 活动（**冻结**） | 领域 bundle v1：工具 schema、业务政策、发布策略。四份文件都在 `bundle_sha256` 的分量里，而它同时在 dev 与 sealed 的配对字段内——**一个字节都不能改**，有测试锁定 |
| `domains/retail_ops/v2/` | 活动 | 领域 bundle v2：政策规则**可执行**、`refund_order` 增必填 `idempotency_key`。见 [`DOMAIN_BUNDLE_V2.md`](./DOMAIN_BUNDLE_V2.md)。正式数据集轨道仍只接受 v1 |
| `configs/` | 活动 | 运行配置，按四接口分层 |
| `manifests/` | 活动 | 冻结数据集的公开 manifest（answer-free，进 Git） |
| `tests/` | 活动 | 治理契约测试与领域契约测试；条数以 `README.md` 的工程基线一行为准，本表不复述 |
| `scripts/legacy/` | legacy | 旧 CLI 脚本；`legacy/bfcl/` 仍服务于 BFCL 外部回归 |
| `reports/retail_ops/` | 活动 | RetailOps 运行产物（ignored，不进 Git） |
| `reports/legacy/` | 归档 | 旧 MVP/BFCL 的历史报告（部分进 Git，作为结果可追溯性凭证） |
| `data/` | 活动 | 私有数据与外部 benchmark checkout（整体 ignored） |
| `docs/` | 活动 | 治理文档 + 交付文档（`MODEL_CARD` / `MODEL_CARD_sft-006` / `SYSTEM_CARD` / `DEMO` / `RESUME_EVIDENCE` / **`HOLDOUT_LEDGER`**）；`docs/handoffs/` 为当前有效的执行提示词，`docs/archive/` 为已完成阶段的过程文档 |
| `scripts/ci/` | 活动 | CPU 全链路复现校验（`verify_qualification_chain.py`），CI 与本地共用同一条命令 |
| `.github/workflows/` | 活动 | CPU 质量门 workflow。**仓库无 remote，尚未真正运行过** |
| `Dockerfile` | 活动 | CPU-only 镜像，刻意不含 torch（重依赖只在 GPU 主机装） |
| `tools/bfcl_eval/` | legacy | BFCL 官方 evaluator 的独立 uv 环境 |

**封存 holdout 观测次数与判定的唯一事实源是 [`HOLDOUT_LEDGER.md`](./HOLDOUT_LEDGER.md)**，
其它文档一律引用而不复述。Agent 本体的能力面、四个可注入的缝、以及**仍然缺的东西**
见 [`AGENT_LOOP.md`](./AGENT_LOOP.md)。

## 3. `src/veritool_rl/` 分层

```
src/veritool_rl/
├── product_cli.py          # build / evaluate / release / serve 命令面（唯一入口）
├── cli.py                  # 配置加载
├── core/                   # 跨领域基础设施，不含 RetailOps 业务语义
│   ├── trajectory/         #   轨迹契约与可重放性（schema, replay）
│   ├── agent/              #   执行层（policy, parser, runner, guardrail, user_simulator, qwen backend）
│   ├── envs/               #   工具环境抽象与 MiniRetail 本地回归环境
│   ├── rewards/            #   verifier
│   ├── artifacts.py        #   canonical JSON、内容哈希、不可覆盖输出目录
│   ├── paths.py            #   项目相对路径校验（防路径逃逸）
│   ├── metrics.py          #   由可重放轨迹计算的确定性指标
│   ├── generators.py       #   Oracle 成功轨迹生成与 SFT 数据转换
│   └── reporting.py        #   报告渲染
├── retail_ops/             # RetailOps 领域，按四接口分层
│   ├── domain/             #   领域事实来源：bundle, tasks, ood_tasks, policies, policy_rules, policy_card, environment, formal_tasks
│   ├── build/              #   数据侧：manifests, formal_manifests, ood_manifests, teacher_*, dev_sft_export
│   ├── evaluate/           #   评测侧：evaluation, base_/candidate_/sealed_/ood_evaluation
│   ├── release/            #   决策侧：release(R1), formal_release(holdout), governance, formal_governance
│   └── serve/              #   服务侧：service（R1 规则策略 + formal 真实模型两条通道）
├── training/sft.py         # 单卡 QLoRA-SFT
└── legacy/                 # 旧 VeriTool-RL 路线（bfcl 数据与评测、MVP evaluator、grpo/preference）
```

**依赖方向**：`product_cli → retail_ops.* → core.*`。`core` 不反向依赖 `retail_ops`，
`legacy` 不被主线依赖。这条约束让"领域可替换"这一产品主张在代码结构上可验证。

## 4. `configs/` 分层

| 路径 | 消费命令 |
|---|---|
| `configs/retail_ops/build/` | `retail-agent-ops build`（R1 qualification 有**必填**键 `inject`——间接 prompt injection 变体与欠指定澄清变体（`inject` / `clarify`）都是独立评测子集而非默认行为；另含 formal_freeze / teacher_collect / train_export / dev_sft_export / sft 五条流水线）。`train_export` 有**三个必填**的变换键，都不给默认值——目的是让"忘了写"与"故意不启用"在配置层可分辨：`sft_oversample`（按场景重复 sft 行，空 mapping = 不重采样）、`sft_terminal_response`（按场景在多步样本末尾追加一条**独立的** assistant 终局回复，空列表 = 不追加）、`sft_system_prompt_sha256`（把 system 消息改写为当前 `runner.SYSTEM_PROMPT`，`null` = 沿用轨迹里的 prompt）。最后一个刻意声明**期望哈希**而非布尔值：teacher 证据持久化了 `metadata["system_prompt"]`，改常量不会追溯改写它，布尔值下"配置写了 true 但常量忘了改"会静默产出逐字节相同的训练集 |
| `configs/retail_ops/evaluate/` | `retail-agent-ops evaluate`（qualification、formal_dev_base、formal_dev_candidate、formal_holdout_base、formal_holdout_candidate）。qualification 侧有一个**必填**键 `perturb_schema`：它改变评测条件（工具别名 + 参数顺序扰动），"忘了写"与"故意不启用"必须在配置层可分辨；`..._schema_{clean,perturbed}.yaml` 是只差这一个开关的对照。另有必填键 `guardrail`：开不开独立于环境的第二道防线同样是评测条件，`retail_ops_v2_injection_{unguarded,guarded}.yaml` 是只差这一个开关的对照。第三个必填键 `user_simulator` 决定 episode 是单轮还是可澄清多轮，`retail_ops_v2_clarify_{singleturn,multiturn}.yaml` 是只差这一个开关的对照 |
| `configs/retail_ops/release/` | `retail-agent-ops release`（R1 配对门禁、formal_release）。`formal_release` 有一个**必填**键 `gate_schema_version`（`"1.0"` / `"1.1"`）——"这份判定用的是哪套门禁语义"是证据最重要的元数据之一，不能靠"没写就是旧的" |
| `configs/retail_ops/serve/` | `retail-agent-ops serve`（R1 qualification、formal_serve） |
| `configs/examples/` | 模板 |
| `configs/legacy/` | 旧 MVP/BFCL 配置 |

## 4.1 四个接口的双轨完成度

仓库里有**两条平行证据链**，读代码时必须先分清在看哪一条：

| 接口 | R1 qualification 轨道（规则策略） | formal 轨道（真实 Qwen3-4B） |
|---|---|---|
| `build` | 完成 | 完成（formal_freeze / teacher_collect / train_export / dev_sft_export / sft） |
| `evaluate` | 完成 | 完成（dev base/candidate + 封存 holdout base/candidate） |
| `release` | 完成（`release.py`） | 完成（`formal_release.py`，与 R1 共用 `build_release_gates`） |
| `serve` | 完成（`create_app`） | 完成（`create_formal_app`，后端工厂注入） |

`release` 的门禁语义是**版本化**的：`GATE_IDS_BY_SCHEMA` 把 v1.0（R1 起的五项冻结
集合）与 v1.1（拆分延迟门禁 + 配对统计检验）分开，两个 report 模型按各自
`schema_version` 断言集合与顺序。就地增删 `GATE_IDS` 会让磁盘上全部已有 release 报告
无法加载，因此新口径只能走版本化路径；有测试断言旧报告仍能被加载。

**sealed 证据契约同样已版本化**（v1.1）：`SEALED_HASHED_FIELDS` 按 schema 版本投影
自哈希输入，使"新增字段"与"作废旧证据"解耦——磁盘上七份 v1.0 sealed 报告的
`report_id` 复算后逐位不变。v1.1 新增 `deployment_form` 与 `merged_from`，让**合并
部署形态**的候选可以进配对：它靠**可复算的血统**（`merged_revision` 由基座 revision
与 adapter 逐文件哈希导出）而不是同一性与 base 配对。

**分布外任务集**（`retail_ops_ood_v1_20260815`，60 条）走完全独立的
build/evaluate 路径：它公开、可反复读、不封存，治理级别与封存 holdout 不同。
读数见 [`OOD_EVALUATION.md`](./OOD_EVALUATION.md)——**引用第四次那个 GO 时必须
同时给出它**。

`serve` 的 formal 通道在 2026-08-15 从演示夹具补成服务：`POST /v1/chat` 自由请求、
`/v1` 全面 Bearer 鉴权（key 只从环境变量读）、请求级 trace_id 与结构化 JSON 日志
（只落请求摘要不落原文）、`GET /metrics`（Prometheus 文本，无新依赖）、
episode 超时结构化降级。并发上限仍是 1 且保留 503 语义。

两条轨道**共用一份阈值语义**：`domains/retail_ops/v1/release.yaml` 经
`release.build_release_gates` 同时服务于两者，因此同一个候选不可能在两条通道上
得到互相矛盾的结论。R1 的 `ReleaseReport` 契约已冻结（gate 集合与顺序被
`validate_decision_consistency` 断言），formal 侧是并行类型而不是它的扩展。

四接口在 formal 轨道上均已实际运行，且完整走通**两次**：2026-08-11 完成第一次封存
holdout 的 base/candidate 背靠背评测、首个 formal 发布判定（**NO-GO / baseline**）
与按该判定回滚基座的服务演示（LOG-20260811-03、-04）；2026-08-14 完成第二次完整观测
与第二次判定（同样 **NO-GO / baseline**，候选 120/120 但 `p95_latency_ratio`
1.8774 > 1.25，LOG-20260814-04）；2026-08-15 完成第三次观测与第三次判定（同样
**NO-GO / baseline**，LOG-20260815-03）。**不再有"未观测"状态**；结果不得反馈进开发、
调参、prompt/parser 或 checkpoint 选择。
逐次读数与判定的唯一事实源是 [`HOLDOUT_LEDGER.md`](./HOLDOUT_LEDGER.md)。

**配对可比性的连带约束**（R4 起必须知道）：`code_commit`、`uv_lock_sha256`、
`system_prompt_sha256` 都在 `SEALED_PAIRING_FIELDS` 内，因此任何后续改动提交后，
已有的 sealed holdout base 证据都不再可与新候选配对——下一次发布判定必然是
base + candidate **两侧**重跑。dev 侧的 `PAIRING_FIELDS` 不含 `code_commit`，
所以改数据/代码不需要重跑 base dev，只有改 system prompt 才需要。

## 5. 命名边界

- **产品名 / 分发名 / CLI 名**：`retail-agent-ops`
- **Python 导入名**：`veritool_rl`（未改）

导入名保留是刻意选择：已提交的 `reports/` 产物与 manifest 记录了产出它们的代码标识，
重命名会切断"代码 commit ↔ 运行产物"的可追溯链，而可追溯性正是本项目的核心主张。
重命名若要进行，必须作为独立任务，并单独处理 provenance 断层的解释。

## 6. 2026-08-09 路径对照

本次收敛只做移动与引用重写，**未改任何函数体**；证明方式是 585 项测试逐项通过，
且已产出的三份真实运行证据（两份 R2 base、一份 R3 candidate）重新加载后 `run_id`
自哈希与逐产物哈希复算全部一致。

| 旧路径 | 新路径 |
|---|---|
| `src/veritool_rl/{artifacts,paths,reporting}.py` | `src/veritool_rl/core/` 同名文件 |
| `src/veritool_rl/{agent,envs,rewards,trajectory}/` | `src/veritool_rl/core/` 下同名子包 |
| `src/veritool_rl/eval/metrics.py` | `src/veritool_rl/core/metrics.py` |
| `src/veritool_rl/data/generators.py` | `src/veritool_rl/core/generators.py` |
| `src/veritool_rl/retail_ops/{bundle,tasks,policies,environment,formal_tasks}.py` | `src/veritool_rl/retail_ops/domain/` |
| `src/veritool_rl/retail_ops/{manifests,formal_manifests,teacher_*,dev_sft_export}.py` | `src/veritool_rl/retail_ops/build/` |
| `src/veritool_rl/retail_ops/{evaluation,base_evaluation,candidate_evaluation,sealed_evaluation}.py` | `src/veritool_rl/retail_ops/evaluate/` |
| `src/veritool_rl/retail_ops/{release,governance,formal_governance}.py` | `src/veritool_rl/retail_ops/release/` |
| `src/veritool_rl/retail_ops/service.py` | `src/veritool_rl/retail_ops/serve/service.py` |
| `src/veritool_rl/{data/bfcl*,eval/bfcl*,eval/evaluator,training/grpo,training/preference}.py` | `src/veritool_rl/legacy/` 下同结构 |
| `configs/retail_ops_v1_*.yaml` | `configs/retail_ops/{build,evaluate,release,serve}/` 同名文件 |
| `configs/{mvp_*,bfcl_*}.yaml` | `configs/legacy/` |
| `configs/{data,sft}.example.yaml` | `configs/examples/` |
| `scripts/*.py` | `scripts/legacy/{bfcl,mvp}/` |
| `reports/{bfcl,mvp}/` | `reports/legacy/{bfcl,mvp}/` |
| `docs/{handoffs,superpowers}/` | `docs/archive/{handoffs,superpowers}/` |

`docs/PROJECT_LOG.md`、`findings.md`、`progress.md` 与 `reports/legacy/**` 内的历史
路径**未被改写**——它们记录的是当时的事实，用本表回溯即可。

## 7. 独立性

本项目对原 `veritool-rl` 工作区零依赖：单一 `main` 分支、0 remote、无 submodule、
无 linked worktree、无 Git alternates、无跨仓库软链接；`data/external_repos/gorilla`
是自包含的 BFCL 固定 checkout（见 `data/external_repos/BFCL_PIN.txt`）。
删除原工作区不会影响本项目的任何命令。
