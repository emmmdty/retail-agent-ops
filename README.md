# RetailAgentOps

RetailAgentOps 是面向零售订单、退款和客服操作的单卡工具 Agent 领域适配与发布流水线。它把工具 schema、业务政策和任务转换为可执行轨迹，完成数据质检、轻量后训练、状态级评测、GO/NO-GO 发布门禁和推理服务。

> **状态**：`R1`–`R3` 已完成，`R4` 失败驱动优化三轮已跑完。完整链路（QLoRA-SFT → dev
> 配对评测 → 封存 120 条 holdout 评测 → GO/NO-GO 门禁 → 真实模型服务）已在真实模型上
> 走通**两次**，**两次发布结论都是 `NO-GO`**：第一次输在 `success_delta`
> （0.7833→0.7500）；第二次候选在 120 条上做到 **120/120**、`success_delta` **+0.1417**、
> 政策违规 11→0、非法调用 5→0，但 **`p95_latency_ratio` 1.88 > 1.25** 被拒——
> 代价来自全 linear LoRA 的前向开销（单次调用 1497→2971 ms），不是多做了工具调用。
> 两次都据此回滚加载纯基座。发布门禁阈值一个字未改，有测试锁定。
> 详见 [`docs/MODEL_CARD.md`](./docs/MODEL_CARD.md) 与 [`docs/SYSTEM_CARD.md`](./docs/SYSTEM_CARD.md)。
> **封存 holdout 的两次观测均已消耗**，结果不得反馈进开发。仓库继承了原 VeriTool-RL 的 MiniRetail、BFCL、QLoRA
> 和可追溯评测基础，但旧研究路线已归档到 `legacy/`，不再是活动计划。
> 分发名与 CLI 是 `retail-agent-ops`，Python 导入名仍是 `veritool_rl`（见
> [`docs/REPO_MAP.md`](./docs/REPO_MAP.md) 的命名边界）。

## 项目价值

- 用真实工具执行和最终状态验证 Agent，而不是只比较文本。
- 将数据、训练、评测、部署和发布决策连接成可审计工程闭环。
- 在单张 RTX 4090 上验证小模型的隐私、成本、延迟和领域效果边界。
- 候选不达标时输出 `NO-GO`，不为简历数字放宽门槛。

## 文档入口

- [`AGENTS.md`](./AGENTS.md)：Codex/通用 coding agent 入口。
- [`CLAUDE.md`](./CLAUDE.md)：Claude Code 与共享工程约束。
- [`docs/CAREER_CONTEXT.md`](./docs/CAREER_CONTEXT.md)：求职背景和项目组合约束。
- [`docs/PRODUCT_BRIEF.md`](./docs/PRODUCT_BRIEF.md)：应用场景、用户价值和竞争边界。
- [`SPEC.md`](./SPEC.md)：产品契约、指标和验收原则。
- [`docs/EXECUTION_PLAN.md`](./docs/EXECUTION_PLAN.md)：R0–R5 阶段状态、执行目标和验收目标。
- [`docs/HANDOFF.md`](./docs/HANDOFF.md)：新会话接管协议和停机条件。
- [`docs/REPO_MAP.md`](./docs/REPO_MAP.md)：目录职责、四接口分层和路径对照。
- [`docs/LEGACY_INVENTORY.md`](./docs/LEGACY_INVENTORY.md)：原仓库、历史成果和未迁入生成物。
- [`task_plan.md`](./task_plan.md)、[`findings.md`](./findings.md)、[`progress.md`](./progress.md)：当前任务工作记忆。
- [`docs/PROJECT_LOG.md`](./docs/PROJECT_LOG.md)：append-only 的长期档案，只记录改变方法论选型或工程实践的事件。

## 本地验证

```bash
env -u UV_INDEX_URL uv sync --extra dev --frozen
env -u UV_INDEX_URL uv sync --project tools/bfcl_eval --frozen
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy
```

模型、benchmark checkout、数据、checkpoint 和运行产物不进入 Git。GPU 命令必须先向用户披露完整命令、工作目录、物理 GPU、预计时长和产物，并等待确认。

## RetailOps v1 CPU qualification

安装开发依赖后，以下六条命令会在 CPU 上依次生成固定任务、三组配对评测和两份发布结论：
输出目录采用不可覆盖语义；重复验收时请把命令中的 `qualification-r1-final` 整体替换为新的 `qualification-*` 名称。

```bash
.venv/bin/retail-agent-ops build --config configs/retail_ops/build/retail_ops_v1_build.yaml --seed 0 --output_dir reports/retail_ops/v1/qualification-r1-final/build
.venv/bin/retail-agent-ops evaluate --config configs/retail_ops/evaluate/retail_ops_v1_qualification_base.yaml --seed 0 --input_dir reports/retail_ops/v1/qualification-r1-final/build --output_dir reports/retail_ops/v1/qualification-r1-final/base
.venv/bin/retail-agent-ops evaluate --config configs/retail_ops/evaluate/retail_ops_v1_qualification_oracle.yaml --seed 0 --input_dir reports/retail_ops/v1/qualification-r1-final/build --output_dir reports/retail_ops/v1/qualification-r1-final/oracle
.venv/bin/retail-agent-ops evaluate --config configs/retail_ops/evaluate/retail_ops_v1_qualification_fault.yaml --seed 0 --input_dir reports/retail_ops/v1/qualification-r1-final/build --output_dir reports/retail_ops/v1/qualification-r1-final/fault
.venv/bin/retail-agent-ops release --config configs/retail_ops/release/retail_ops_v1_release.yaml --seed 0 --baseline_dir reports/retail_ops/v1/qualification-r1-final/base --candidate_dir reports/retail_ops/v1/qualification-r1-final/oracle --output_dir reports/retail_ops/v1/qualification-r1-final/release-go
.venv/bin/retail-agent-ops release --config configs/retail_ops/release/retail_ops_v1_release.yaml --seed 0 --baseline_dir reports/retail_ops/v1/qualification-r1-final/base --candidate_dir reports/retail_ops/v1/qualification-r1-final/fault --output_dir reports/retail_ops/v1/qualification-r1-final/release-no-go
```

产物目录如下：

| 目录 | 内容 |
|---|---|
| `build/` | 12 条固定 qualification 任务及其 manifest |
| `base/`、`oracle/`、`fault/` | 配置、本地完整轨迹、指标、脱敏失败摘要、日志和 run evidence |
| `release-go/`、`release-no-go/` | `release.json`、`report.md`、`report.html` 发布报告 |

可用 GO 报告启动本地 qualification 服务；服务启动前会核对 release、bundle 和 task manifest 哈希：

```bash
.venv/bin/retail-agent-ops serve --config configs/retail_ops/serve/retail_ops_v1_serve.yaml --release_dir reports/retail_ops/v1/qualification-r1-final/release-go --input_dir reports/retail_ops/v1/qualification-r1-final/build --output_dir reports/retail_ops/v1/qualification-r1-final/service
```

这套数据是用于验证工程契约的合成 qualification；R1 未生成正式 holdout，也没有读取 holdout 真值。BFCL 只保留为独立外部回归，现有 BFCL 成绩不是 RetailOps 内部指标。

### 自动化复现与容器

上面六条命令由 `scripts/ci/verify_qualification_chain.py` 自动跑一遍，并断言两份
`release.json` 的决策、失败门禁、`bundle_sha256` / `task_manifest_sha256` 与确定性
指标等于冻结期望值——这是 `SPEC.md` §11「新环境能按文档完成 CPU smoke」的唯一自动化
证明。GitHub Actions workflow 见 `.github/workflows/ci.yml`；**仓库当前无 remote，
该 workflow 尚未真正运行过**。CPU-only 镜像见 `Dockerfile`（刻意不含 torch）。

```bash
.venv/bin/python scripts/ci/verify_qualification_chain.py
```

### 工具 schema 鲁棒性对照

`perturb_schema` 会给工具改别名并打乱参数顺序（参数**键集合**不变）。两份只差一个
开关的配置构成对照，回答"换一份客户的工具 schema 还能不能用"：

```bash
.venv/bin/retail-agent-ops evaluate --config configs/retail_ops/evaluate/retail_ops_v1_qualification_schema_clean.yaml     --seed 0 --input_dir <build> --output_dir <out-clean>
.venv/bin/retail-agent-ops evaluate --config configs/retail_ops/evaluate/retail_ops_v1_qualification_schema_perturbed.yaml --seed 0 --input_dir <build> --output_dir <out-perturbed>
```

从工具清单按参数形状解析工具名的 `schema_adaptive` 策略在两侧都是 12/12；把
`policy_type` 换成硬编码工具名的 `oracle`，扰动侧会**全灭**（测试锁定这个对照）。
这条只用规则策略在 CPU 上跑，不涉及任何模型。

## 仓库结构

按 `build → evaluate → release → serve` 四个稳定接口组织，详见
[`docs/REPO_MAP.md`](./docs/REPO_MAP.md)：

```
src/veritool_rl/
├── product_cli.py    四接口命令面
├── core/             跨领域基础设施（轨迹契约、环境抽象、agent 执行、指标、产物哈希）
├── retail_ops/       RetailOps 领域：domain / build / evaluate / release / serve
├── training/         单卡 QLoRA-SFT
└── legacy/           原 VeriTool-RL 路线（BFCL 外部回归仍在用）
configs/retail_ops/{build,evaluate,release,serve}/   与命令一一对应的运行配置
domains/retail_ops/v1/                               工具 schema、业务政策、发布策略
```

依赖方向恒为 `product_cli → retail_ops.* → core.*`；`core` 不反向依赖领域，
`legacy` 不被主线依赖。

## 结果边界

R3 候选（Qwen3-4B QLoRA-SFT）在 60 条冻结 dev 任务上：非法工具调用 21→0、
关键政策违规 8→0、schema 合规率 0.781→1.000（精确 McNemar `p<0.0001` / `p=0.0078`）；
但任务成功率 48/60→43/60，回退全部集中在需 ≥2 次工具调用的场景。

封存 120 条 holdout 已消耗**两次**观测，两次判定**都是 `NO-GO` / `deployment=baseline`**，
且阈值一个字未改。逐次读数、失败门禁与判定口径边界见
[`docs/HOLDOUT_LEDGER.md`](docs/HOLDOUT_LEDGER.md)——**那是唯一事实源，本文件不复述**。

- 观测 1（2026-08-11，R3 候选）复现了 dev 的同一模式且更极端：非法调用 41→0、
  政策违规 16→0、schema 合规率 0.7819→1.0000，而任务成功率 0.7833→0.7500。
  唯一失败门禁 `success_delta` −0.0333 < +0.05；候选失败 100% 是
  `premature_final_response`，`refund_eligible` 20/20 全数失败。
- 观测 2（2026-08-14，R4 候选 `sft-006`）任务指标全面达标：**120/120**、
  `success_delta` +0.1417、违规与非法调用清零。唯一失败门禁是
  `p95_latency_ratio` 1.8774 > 1.25，判定仍是 `NO-GO`。**这个数字是部署形态的代价
  而不是模型能力的结论**：单次调用耗时 1.985×，而调用次数只增 1.146×。

**120/120 不构成泛化证据**：train/dev/holdout 共用同一批 12 句请求模板，
holdout 落在 train 的模板空间内，见 `docs/HOLDOUT_LEDGER.md` 的"判定口径的边界"。

两侧 CI95 大幅重叠，仅凭 −3.3pp **不能**断言整体显著回退；但门禁要求的是实测 +5pp 的
提升，候选没有做到，NO-GO 因此成立。另有一条必须一起说的观察：候选的
`verifier_reward` 从 0.5646 升到 0.7500 而任务成功率下降——复合奖励里的格式分量会掩盖
执行能力退化，所以主判据是最终状态与政策 verifier，不是奖励值。

现有 Qwen3-1.7B BFCL 固定 200 条单轮 AST holdout 上，Base/SFT 为 163/200 与 167/200；差值置信区间跨 0，不能声称稳定改善，也不能称为官方 BFCL 全量或排行榜成绩。

项目不产出论文，不以 SOTA、ablation 数量或三 seed 作为完成标准。正式简历指标必须来自冻结任务、实际运行产物和明确发布门禁。
