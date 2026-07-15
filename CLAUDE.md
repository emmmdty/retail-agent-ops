# CLAUDE.md — VeriTool-RL

本文件给在本仓库工作的 coding agent (Claude Code / Codex 等)。**规格以 `SPEC.md` 为准**, 本文件规定协作、实现与运行方式。

---

## 0. 项目一句话

面向 1.5B–4B 小模型的**可验证课程式后训练**: 成功轨迹 SFT + 失败轨迹偏好优化 + 校准的可验证奖励 + schema 扰动, 在 BFCL / ToolSandbox / 单个 tau2 领域上做因果消融。研究级 L1/L2, 不宣称生产上线。

## 1. 硬约束 (不可违反)

- **语言**: 所有代码注释、README、报告、文档默认**简体中文**。
- **环境**: Python 统一用 **`uv`** 管理; Python 3.11。
- **算力分工**: 本地 (WSL) 只做开发/调试/轻量评测; **正式训练与批量评测在 gpu-4090 服务器执行**。
- **服务器目录边界**: 远程只允许操作 `/data/TJK` 与 `/home/TJK`, 不在其他目录创建环境、缓存、数据或产物。
- **模型/数据边界**: 权重、checkpoint、数据集**不进 git** (见 `.gitignore`), 留在服务器 `/data`。
- **奖励边界**: 主结论由执行结果 / 最终状态 / policy verifier 支撑; **LLM-as-a-judge 仅作补充, 不作核心奖励**。
- **不依赖闭源 API** 生成核心训练数据或核心成绩 (闭源模型只作参考上限)。
- **脚本接口**: 所有训练/评测/汇总脚本必须支持 `--config` / `--seed` / `--output_dir`。

## 2. 已验证环境与当前状态

以下是 **2026-07-15** 的已验证快照。依赖精确版本以 `uv.lock` 为准; 服务器或数据状态发生变化时同步更新本节。

### 2.1 固定路径与工具

| 项目 | 路径 / 配置 |
|---|---|
| 本地 WSL 仓库 | `/home/tjk/myProjects/internship-projects/veritool-rl` |
| 远程主机 | `ssh gpu-4090` |
| 远程仓库 | `/data/TJK/internship-projects/veritool-rl` |
| 远程 uv | `/home/TJK/.local/bin/uv` (`uv 0.11.8`) |
| 远程 uv 缓存 | `UV_CACHE_DIR=/data/TJK/uv-cache` |
| Qwen3-1.7B 共享模型 | `/data/TJK/models/Qwen3-1.7B` |
| 项目内模型引用 | `models/Qwen3-1.7B` (相对软链接) |
| 外部 benchmark 源码 | `data/external_repos/` (本地与远程均已准备) |

- 远程 uv 管理的 Python 为 `3.11.15`。
- 远程已执行 `uv sync --extra train --extra dev --frozen`。
- 已验证 `torch 2.13.0+cu130`、CUDA 13.0 与 4× RTX 4090 (24GB) 可用; 不得在未重新做 CUDA smoke test 的情况下更换 torch 版本。
- 当前 lock 解析的关键训练依赖为 `transformers 5.13.1`、`trl 1.8.0`、`peft 0.19.1`、`bitsandbytes 0.49.2`。

远程命令统一使用显式路径, 例如:

```bash
ssh gpu-4090 'cd /data/TJK/internship-projects/veritool-rl && UV_CACHE_DIR=/data/TJK/uv-cache /home/TJK/.local/bin/uv run --frozen pytest -q'
```

### 2.2 已准备的数据与外部仓库

| 仓库 | 固定 commit |
|---|---|
| ToolSandbox | `165848b9a78cead7ca7fe7c89c688b58e6501219` |
| tau2-bench | `e10cffa7512157c157a29f71e5de4286cef5acb7` |
| Gorilla / BFCL | `6ea57973c7a6097fd7c5915698c54c17c5b1b6c8` |
| AppWorld | `a072b7a86e7c1d5b1d7175659d750ebb9b79f10a` |

- 离线归档位于 `data/downloads/external_repos-20260715.tar.zst`, 网络不稳定时优先从本地上传并解压, 不在服务器重复拉取大仓库。
- `data/`、模型权重与 checkpoint 均被 git 忽略。Qwen3-1.7B 已于 2026-07-15 从 ModelScope 的 `Qwen/Qwen3-1.7B` 下载到共享模型目录；项目配置只使用相对软链接 `models/Qwen3-1.7B`。
- 本次权重 SHA-256：分片 1 为 `169ad53ec313c3a34b06c0809216e4fc072cce444a5d4ff2b59690d064130ed5`，分片 2 为 `912becff8d60672aa8628ef08c05898d9adf17c2ad4ae3caf99b065622fdeff9`；重新下载后必须复核。
- BFCL V4 固定单轮 manifest 为 `manifests/bfcl_v4_single_turn_seed0.json`，SHA-256 为 `a74a3748d3af289e8d3f808930b99b6eb5cb9c7d84ba678ff627c762e9448da9`；四类各 50 条，按 seed 0 的稳定 SHA-256 排序选择。
- BFCL 官方 AST checker 路径为固定 Gorilla checkout 中的 `bfcl_eval/eval_checker/ast_eval/ast_checker.py`，本次 SHA-256 为 `2aae7a68461a8f76c0be3894c8901b66b56967a1989d3ab066051e3fb97f1538`。评分使用独立、无第三方依赖的 uv 进程边界，不安装 BFCL 的 vLLM/sglang 可选依赖。
- ToolSandbox 固定 `transformers==4.41.2`, 与项目主训练环境的 `transformers 5.13.1` 冲突。不得把完整 ToolSandbox 直接安装进主环境; 真实适配应使用隔离的 uv 环境或进程边界。

### 2.3 当前开发阶段

- **已完成**: 本地与远程 uv 环境、训练依赖、CUDA smoke test、外部 benchmark 源码与离线归档、基础 lint/type/test 门禁；MiniRetail 确定性闭环与 Qwen3-1.7B Base/QLoRA-SFT seed-0 实验；BFCL V4 固定 200 条单轮 AST 子集的 Qwen3-1.7B 离线 4-bit 零样本基线。BFCL 官方 AST accuracy 为 0.815（163/200），四类分别为 0.82/0.90/0.76/0.78，完整证据见 `reports/bfcl/qwen3-1.7b-base-seed0/report.md`。
- **待运行**: ToolSandbox/tau2 adapter、BFCL 后训练对照、多 seed 重复、失败轨迹偏好优化、奖励校准与消融。
- **结论边界**: 正式表述只能是“Qwen3-1.7B 在 BFCL V4 固定 200 条单轮 AST 子集上的零样本结果”；不得称为 BFCL 官方全量成绩或排行榜成绩，也不得外推到多轮、ToolSandbox、tau2、SFT、偏好优化或 GRPO。

## 3. Coding Agent 协作协议 (每个开发任务固定 8 步)

1. **明确任务规格**: 用户与 Agent 共同确认背景、输入、输出、约束、非目标、失败模式与验收测试。
2. **Agent 先给方案**: ≥2 个方案 + 权衡 + 风险 + 影响文件; 重大设计选择经用户确认后实施。
3. **Agent 端到端实现**: 可编写所有模块、调用点、测试、配置与文档, 不停在占位或脚手架。
4. **小步实现**: 一次 Diff 原则上 **≤150–250 行**; 大任务拆成多个可验证提交。
5. **可审查交付**: Agent 解释数据流、状态变化、异常分支、复杂度、安全风险与测试覆盖, 用户按需 Review。
6. **先运行再相信**: 单元测试、类型检查、lint、集成测试、最小手工案例。
7. **复核核心逻辑**: 对 verifier、奖励、状态变更与指标计算给出可追溯证据和针对性测试。
8. **口述复盘**: 回答「为什么这样设计、替代方案、在哪里会失败」。

> ⚠️ 本项目方法论明确**禁止**: 让 coding agent 一次性生成整个项目后只看最终效果。

## 4. Review 七问 (每次 Review 必答)

1. 输入是否可能为空、超长、恶意或类型错误?
2. 状态在哪里创建、修改、持久化、恢复?
3. 外部调用失败、超时、重复执行会怎样?
4. 是否存在命令注入、路径穿越、越权或 secret 泄露?
5. 时间/空间复杂度和网络/模型成本是多少?
6. 哪些行为已有测试, 哪些只是「看起来能跑」?
7. 如果不用当前框架, 我会如何自己实现?

## 5. Coding Agent 实现边界

- Coding agent 可以实现项目中的全部模块与测试, 包括 tool-calling Agent loop、环境适配器 (`envs/`)、轨迹表示 (`trajectory/`)、verifier 与 reward (`rewards/`)、评测器 (`eval/`)。
- 核心逻辑必须配套测试、类型检查和可运行样例; 不得只生成接口、伪代码或未验证的占位实现。
- 用户、Codex、Claude 或其他 coding agent 均可修改代码; 不要求特定比例由人工手写。
- 涉及研究结论的指标、奖励定义与实验配置必须保留可追溯依据, 并由实际运行结果验证。

## 6. 目录结构

```
veritool-rl/
├── SPEC.md                     # 规格 (single source of truth)
├── CLAUDE.md                   # 本文件
├── pyproject.toml              # uv 管理
├── src/veritool_rl/
│   ├── cli.py                  # --config/--seed/--output_dir 通用解析
│   ├── envs/base.py            # ToolEnv 抽象接口 (BFCL/ToolSandbox/tau2 适配)
│   ├── trajectory/schema.py    # Trajectory 数据结构
│   ├── data/generators.py      # 成功/失败轨迹 + schema 扰动
│   ├── rewards/verifier.py     # 分层可验证奖励 + 校准
│   ├── training/               # sft / preference / grpo
│   └── eval/                   # metrics / evaluator
├── scripts/                    # build_trajectories/train_sft/train_preference/evaluate/aggregate_report
├── configs/                    # *.example.yaml
├── tests/                      # 单元、集成与回归测试
├── reports/                    # 分层实验记录 (见 reports/README.md)
└── docs/adr/                   # 架构决策记录
```

## 7. 常用命令

```bash
# 环境 (首次)
uv sync                                   # 生成 .venv 与 uv.lock (uv.lock 需提交)
uv sync --extra dev                       # 加开发工具
uv sync --extra train                     # 训练重依赖 (torch 需匹配 CUDA, 建议在服务器执行)

# 质量门
uv run pytest                             # 测试
uv run ruff check .                        # lint
uv run mypy                                # 类型检查

# 典型流程 (脚本均需 --config --seed --output_dir)
uv run python scripts/build_trajectories.py --config configs/data.example.yaml --seed 0 --output_dir data/trajectories
uv run python scripts/train_sft.py         --config configs/sft.example.yaml  --seed 0 --output_dir reports/sft/run0
uv run python scripts/evaluate.py          --config configs/sft.example.yaml  --seed 0 --output_dir reports/eval/run0

# BFCL 固定 200 条单轮零样本基线（仅远程单卡）
TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 CUDA_VISIBLE_DEVICES=<physical_gpu> \
uv run --frozen --extra train python scripts/evaluate_bfcl.py \
  --config configs/bfcl_v4_single_turn_seed0.yaml --seed 0 \
  --output_dir reports/bfcl/qwen3-1.7b-base-seed0
```

## 8. 本地 ⇄ gpu-4090 同步与执行

本地为主编写端, 服务器为训练/评测执行端。

远程执行规则:

- 运行任何 GPU 命令前, 先向用户给出**精确命令、工作目录、目标 GPU、预期输出与预计耗时**。
- 可执行短时 CUDA smoke、基线推理和用户已授权的小规模训练; 未经明确授权不得自动启动长时间训练、批量推理或多 GPU 作业。
- 先用 `nvidia-smi` 选择空闲 GPU, 不默认占用 GPU 0; 用 `CUDA_VISIBLE_DEVICES` 明确限制设备。
- 服务器网络一般。依赖和模型优先使用已有缓存、镜像或本地上传; 不修改系统 Python, 不使用 Conda 或裸 `pip` 污染全局环境。
- 同步代码时保留服务器上的 `data/`、模型、checkpoint 与报告产物, 不使用可能删除这些目录的 `rsync --delete`。

```bash
# 一次性: 本地已配好 remote 'gpu-4090' 指向 /data/TJK/internship-projects/veritool-rl
git push gpu-4090 main        # 下发代码到训练机 (服务器工作树自动更新)
# 在服务器跑训练/评测, 结果写入 reports/, 提交后:
git pull gpu-4090 main        # 把服务器端 reports/ 等取回本地

# 以后挂 GitHub:
#   gh repo create veritool-rl --private --source . --remote origin
#   git push -u origin main
```

## 9. 算力与降级线

- 1× 4090: QLoRA-SFT + 偏好优化 + 离线评测;
- 2× 4090: policy + rollout 分卡, 先在 1.7B 小子集验证在线 GRPO;
- **在线 RL go/no-go (48h)**: reward 非退化、无持续 OOM/NaN、优于 SFT; 不过则降级为 rejection sampling + 离线偏好 + reward calibration 分析。

## 10. 成熟度与验收

五级成熟度 L0–L4, 本项目目标 **L1/L2**。写进简历前必须通过 `SPEC.md` §15 的**非-Toy 验收门 10 条**, 否则统一降级为 prototype。**只填实际测得的数据, 不写尚未得到的指标。**
