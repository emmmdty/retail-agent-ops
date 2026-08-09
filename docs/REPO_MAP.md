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
| `domains/retail_ops/v1/` | 活动 | 领域 bundle：工具 schema、业务政策、发布策略（版本化输入） |
| `configs/` | 活动 | 运行配置，按四接口分层 |
| `manifests/` | 活动 | 冻结数据集的公开 manifest（answer-free，进 Git） |
| `tests/` | 活动 | 585 项测试，含治理契约测试 |
| `scripts/legacy/` | legacy | 旧 CLI 脚本；`legacy/bfcl/` 仍服务于 BFCL 外部回归 |
| `reports/retail_ops/` | 活动 | RetailOps 运行产物（ignored，不进 Git） |
| `reports/legacy/` | 归档 | 旧 MVP/BFCL 的历史报告（部分进 Git，作为结果可追溯性凭证） |
| `data/` | 活动 | 私有数据与外部 benchmark checkout（整体 ignored） |
| `docs/` | 活动 | 治理文档；`docs/archive/` 为已完成阶段的过程文档 |
| `tools/bfcl_eval/` | legacy | BFCL 官方 evaluator 的独立 uv 环境 |

## 3. `src/veritool_rl/` 分层

```
src/veritool_rl/
├── product_cli.py          # build / evaluate / release / serve 命令面（唯一入口）
├── cli.py                  # 配置加载
├── core/                   # 跨领域基础设施，不含 RetailOps 业务语义
│   ├── trajectory/         #   轨迹契约与可重放性（schema, replay）
│   ├── agent/              #   执行层（policy, parser, runner, qwen backend）
│   ├── envs/               #   工具环境抽象与 MiniRetail 本地回归环境
│   ├── rewards/            #   verifier
│   ├── artifacts.py        #   canonical JSON、内容哈希、不可覆盖输出目录
│   ├── paths.py            #   项目相对路径校验（防路径逃逸）
│   ├── metrics.py          #   由可重放轨迹计算的确定性指标
│   ├── generators.py       #   Oracle 成功轨迹生成与 SFT 数据转换
│   └── reporting.py        #   报告渲染
├── retail_ops/             # RetailOps 领域，按四接口分层
│   ├── domain/             #   领域事实来源：bundle, tasks, policies, environment, formal_tasks
│   ├── build/              #   数据侧：manifests, formal_manifests, teacher_*, dev_sft_export
│   ├── evaluate/           #   评测侧：evaluation, base_/candidate_/sealed_evaluation
│   ├── release/            #   决策侧：release, governance, formal_governance
│   └── serve/              #   服务侧：service
├── training/sft.py         # 单卡 QLoRA-SFT
└── legacy/                 # 旧 VeriTool-RL 路线（bfcl 数据与评测、MVP evaluator、grpo/preference）
```

**依赖方向**：`product_cli → retail_ops.* → core.*`。`core` 不反向依赖 `retail_ops`，
`legacy` 不被主线依赖。这条约束让"领域可替换"这一产品主张在代码结构上可验证。

## 4. `configs/` 分层

| 路径 | 消费命令 |
|---|---|
| `configs/retail_ops/build/` | `retail-agent-ops build`（含 formal_freeze / teacher_collect / train_export / dev_sft_export / sft 五条流水线） |
| `configs/retail_ops/evaluate/` | `retail-agent-ops evaluate`（qualification、formal_dev_base、formal_dev_candidate） |
| `configs/retail_ops/release/` | `retail-agent-ops release` |
| `configs/retail_ops/serve/` | `retail-agent-ops serve` |
| `configs/examples/` | 模板 |
| `configs/legacy/` | 旧 MVP/BFCL 配置 |

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
