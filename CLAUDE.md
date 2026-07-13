# CLAUDE.md — VeriTool-RL

本文件给在本仓库工作的 coding agent (Claude Code / Codex 等)。**规格以 `SPEC.md` 为准**, 本文件规定「怎么协作、怎么运行、什么必须人工手写」。

---

## 0. 项目一句话

面向 1.5B–4B 小模型的**可验证课程式后训练**: 成功轨迹 SFT + 失败轨迹偏好优化 + 校准的可验证奖励 + schema 扰动, 在 BFCL / ToolSandbox / 单个 tau2 领域上做因果消融。研究级 L1/L2, 不宣称生产上线。

## 1. 硬约束 (不可违反)

- **语言**: 所有代码注释、README、报告、文档默认**简体中文**。
- **环境**: Python 统一用 **`uv`** 管理; Python 3.11。
- **算力分工**: 本地 (WSL) 只做开发/调试/轻量评测; **正式训练与批量评测在 gpu-4090 服务器执行**。
- **模型/数据边界**: 权重、checkpoint、数据集**不进 git** (见 `.gitignore`), 留在服务器 `/data`。
- **奖励边界**: 主结论由执行结果 / 最终状态 / policy verifier 支撑; **LLM-as-a-judge 仅作补充, 不作核心奖励**。
- **不依赖闭源 API** 生成核心训练数据或核心成绩 (闭源模型只作参考上限)。
- **脚本接口**: 所有训练/评测/汇总脚本必须支持 `--config` / `--seed` / `--output_dir`。

## 2. Coding Agent 协作协议 (每个开发任务固定 8 步)

1. **人写任务规格**: 背景、输入、输出、约束、非目标、失败模式、验收测试。
2. **Agent 只给方案**: ≥2 个方案 + 权衡 + 风险 + 影响文件; **此时不改代码**。
3. **人做选择**: 用自己的话说明为什么选该方案。
4. **小步实现**: 一次 Diff 原则上 **≤150–250 行**; 大任务拆成多个可验证提交。
5. **人逐行 Review**: 解释数据流、状态变化、异常分支、复杂度、安全风险与测试覆盖。
6. **先运行再相信**: 单元测试、类型检查、lint、集成测试、最小手工案例。
7. **独立复写核心**: 每天选一个 30–80 行核心函数, 关闭 AI 重新实现。
8. **口述复盘**: 回答「为什么这样设计、替代方案、在哪里会失败」。

> ⚠️ 本项目方法论明确**禁止**: 让 coding agent 一次性生成整个项目后只看最终效果。

## 3. Review 七问 (每次 Review 必答)

1. 输入是否可能为空、超长、恶意或类型错误?
2. 状态在哪里创建、修改、持久化、恢复?
3. 外部调用失败、超时、重复执行会怎样?
4. 是否存在命令注入、路径穿越、越权或 secret 泄露?
5. 时间/空间复杂度和网络/模型成本是多少?
6. 哪些行为已有测试, 哪些只是「看起来能跑」?
7. 如果不用当前框架, 我会如何自己实现?

## 4. 必须由人手写的核心模块 (不得外包给 AI)

- scaled dot-product attention 与简化 Transformer block (基础能力);
- 最小 tool-calling Agent loop;
- **环境适配器 (`envs/`)、轨迹表示 (`trajectory/`)、verifier 与 reward (`rewards/`)、评测器 (`eval/`)**;
- 至少 60% 的核心测试。

可高比例交给 agent: 重复 CRUD、脚本样板、配置模板、文档格式、机械重构 —— 但仍须人工 Review 与运行验证。

## 5. 目录结构

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
├── tests/                      # 核心测试 (≥60% 人工手写)
├── reports/                    # 分层实验记录 (见 reports/README.md)
└── docs/adr/                   # 架构决策记录
```

## 6. 常用命令

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
```

## 7. 本地 ⇄ gpu-4090 同步 (git)

本地为主编写端, 服务器为训练/评测执行端。

```bash
# 一次性: 本地已配好 remote 'gpu-4090' 指向 /data/TJK/internship-projects/veritool-rl
git push gpu-4090 main        # 下发代码到训练机 (服务器工作树自动更新)
# 在服务器跑训练/评测, 结果写入 reports/, 提交后:
git pull gpu-4090 main        # 把服务器端 reports/ 等取回本地

# 以后挂 GitHub:
#   gh repo create veritool-rl --private --source . --remote origin
#   git push -u origin main
```

## 8. 算力与降级线

- 1× 4090: QLoRA-SFT + 偏好优化 + 离线评测;
- 2× 4090: policy + rollout 分卡, 先在 1.7B 小子集验证在线 GRPO;
- **在线 RL go/no-go (48h)**: reward 非退化、无持续 OOM/NaN、优于 SFT; 不过则降级为 rejection sampling + 离线偏好 + reward calibration 分析。

## 9. 成熟度与验收

五级成熟度 L0–L4, 本项目目标 **L1/L2**。写进简历前必须通过 `SPEC.md` §15 的**非-Toy 验收门 10 条**, 否则统一降级为 prototype。**只填实际测得的数据, 不写尚未得到的指标。**
