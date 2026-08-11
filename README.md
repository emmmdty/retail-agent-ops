# RetailAgentOps

RetailAgentOps 是面向零售订单、退款和客服操作的单卡工具 Agent 领域适配与发布流水线。它把工具 schema、业务政策和任务转换为可执行轨迹，完成数据质检、轻量后训练、状态级评测、GO/NO-GO 发布门禁和推理服务。

> **状态**：`R1` 产品契约与 v0.1、`R2` 数据与评测流水线已完成；`R3` 单卡适配与服务 v1
> 进行中——首次真实 Qwen3-4B QLoRA-SFT、候选 dev 配对评测，以及封存 holdout 评测 →
> GO/NO-GO 门禁 → 真实模型服务这条链路的**代码**均已完成并有测试覆盖。
> **但正式 120 条 holdout 至今从未执行**，因此不存在任何 sealed 证据、任何发布结论，
> 也没有部署过真实模型服务。仓库继承了原 VeriTool-RL 的 MiniRetail、BFCL、QLoRA
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
- [`docs/PROJECT_LOG.md`](./docs/PROJECT_LOG.md)：append-only 的长期执行与决策记录。

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
但任务成功率 48/60→43/60，回退全部集中在需 ≥2 次工具调用的场景。据此该候选**不适合
直接替换 base**，尚未进入 release 门禁判定。这些是 dev 结论，不是发布结论。

发布门禁的代码已就绪但**尚未对该候选执行**。按上述 dev 数字套用
`domains/retail_ops/v1/release.yaml` 的阈值，五项门禁里只有 `success_delta` 会失败
（违规数、非法调用、p95 延迟三项都改善）——这是**预期**，不是已产生的发布结论；
真正的结论必须来自封存 holdout 上的 sealed 证据。

现有 Qwen3-1.7B BFCL 固定 200 条单轮 AST holdout 上，Base/SFT 为 163/200 与 167/200；差值置信区间跨 0，不能声称稳定改善，也不能称为官方 BFCL 全量或排行榜成绩。

项目不产出论文，不以 SOTA、ablation 数量或三 seed 作为完成标准。正式简历指标必须来自冻结任务、实际运行产物和明确发布门禁。
