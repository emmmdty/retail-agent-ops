# CLAUDE.md — RetailAgentOps

本文件供 Claude Code 使用，也作为所有 coding agent 的共享工程协议。产品规格见 [`SPEC.md`](./SPEC.md)，阶段状态见 [`docs/EXECUTION_PLAN.md`](./docs/EXECUTION_PLAN.md)，接管步骤见 [`docs/HANDOFF.md`](./docs/HANDOFF.md)。

## 1. 开工前读取顺序

1. `docs/CAREER_CONTEXT.md`
2. `docs/PRODUCT_BRIEF.md`
3. `docs/EXECUTION_PLAN.md`
4. `task_plan.md`、`findings.md`、`progress.md`
5. `docs/PROJECT_LOG.md` 最近记录
6. 当前 git 状态和相关代码/测试

发现冲突或高影响信息缺失时，停止并询问用户，不得自行扩展方向。

## 2. 当前定位

RetailAgentOps 是零售工具 Agent 的单卡领域适配与发布流水线。它不是论文项目、通用 post-training 框架或 BFCL 刷分工程。Python 包暂保留 `veritool_rl`，不得在无独立计划时全仓重命名。

## 3. 协作分工

- 用户负责产品策略、阶段优先级、重大设计选择、资源授权和最终验收。
- Claude/Codex 可以实现全部代码、测试、配置和文档，但必须保留选择理由、失败边界和可运行证据。
- 重大产品、模型、数据、算法和部署选择先给至少两个方案，等待用户决定。
- 已确认计划内的低风险纵向切片应端到端完成，不停在接口或占位实现。
- 用户每周需要完成核心模块走读和脱稿复盘，文档应服务于解释而不是替代理解。

## 4. 环境与资源边界

- 本地：WSL/Linux，Python 3.11，`uv` 管理，只做 CPU 开发和轻量验证。
- 远程环境 1：`ssh gpu-4090`，只允许 `/data/TJK` 和 `/home/TJK`；uv 为 `/home/TJK/.local/bin/uv`，缓存 `UV_CACHE_DIR=/data/TJK/uv-cache`。该机上仅有原 VeriTool-RL 遗留目录 `/data/TJK/internship-projects/veritool-rl`，**不是本项目的远程工作区**；R2/R3 全部在远程环境 2 执行。若要启用本机，须先经确认建立独立目录，不得复用遗留目录。
- 远程环境 2：`ssh gpu-5090`，仓库路径 `/mnt/aidata/tongjiakai/retail-agent-ops`，只允许 `/mnt/aidata/tongjiakai` 和 `/home/tongjiakai`；该目录同时承载该用户其他项目，不得触碰 `retail-agent-ops` 之外的既有子目录；uv 为 `~/.local/bin/uv`。该服务器多人共用，执行前须核对 GPU 显存/进程占用与磁盘余量，模型下载优先选择满足复现要求的最小体积版本。
- 两套远程环境均为可用选项，同一任务只使用其中一个，执行前需在报告中明确当前使用的是哪一个。
- 模型、数据、checkpoint 和大运行产物不进 Git。
- 未经确认不得运行本地 GPU、远程长任务、批量评测或多 GPU 作业。
- 远程命令执行前必须报告命令、工作目录、物理 GPU、预计时长和产物。

## 5. 数据和结果边界

- 固定 BFCL 200 条 holdout 及失败不得进入开发、训练、调参、checkpoint 选择或 prompt/parser 修改。
- Base/SFT 163/200 与 167/200 只能表述为项目固定单轮 AST 子集结果，且不能声称稳定提升。
- 主结论必须来自工具执行、最终状态和政策 verifier；LLM judge 不是核心奖励或真值。
- 正式运行固定代码、依赖、数据、模型、模板、parser、seed、预算和 evaluator，并保存 manifest。
- 开发默认一个训练 seed；最终简历效果只做一次独立重建复验。
- 不因负结果降低发布门槛，不用计划目标冒充实际成绩。

## 6. 实现与测试协议

1. 在 `task_plan.md` 明确输入、输出、非目标、失败模式、影响文件和验收。
2. 行为变化先写失败测试并确认失败原因，再实现最小闭环。
3. 更新相关调用点、类型、配置和文档，不留无验证占位。
4. 每两次重要查看/检索后更新 `findings.md`；阶段进度更新 `progress.md`。
5. 每个正式运行使用新输出目录，不覆盖已有运行。
6. 运行 pytest、Ruff、mypy、配置解析和 `git diff --check`。

Review 必答：输入恶意/异常情况、状态变化、超时/重试/幂等、权限与泄漏、复杂度和成本、已有测试与未验证行为、可替代设计。

## 7. 记录协议

- `docs/EXECUTION_PLAN.md`：唯一阶段状态源。
- `task_plan.md`：当前任务清单，可在新任务开始时重写。
- `findings.md` / `progress.md`：当前任务发现和运行台账。
- `docs/PROJECT_LOG.md`：append-only 的长期决定、失败、GPU 运行和 go/no-go。
- `docs/adr/`：稳定、跨模块的架构决策。

触发重大决定、实验、失败、阻塞、资源或约束变化时，先追加 `docs/PROJECT_LOG.md`，再在最终答复中报告 LOG ID。不得改写历史条目。

## 8. 常用命令

```bash
env -u UV_INDEX_URL uv sync --extra dev --frozen
env -u UV_INDEX_URL uv sync --project tools/bfcl_eval --frozen
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy
git diff --check
```

`data/external_repos/gorilla` 是 ignored 的自包含 BFCL checkout（固定 commit `6ea5797…`，保留其自身 `.git` 供 commit 与工作树校验）。若缺失，按 `data/external_repos/BFCL_PIN.txt` 重建，不得用浮动网络版本替代。仓库目录职责见 `docs/REPO_MAP.md`。

## 9. 当前状态

- 当前阶段：R3「单卡适配与服务 v1」进行中。Task 1（首次真实 Qwen3-4B QLoRA-SFT）、
  Task 2（候选 dev 配对评测）与 Task 3（发布闭环的**代码侧**补齐）已完成。
  Task 3 打通了 formal 轨道的 `evaluate`（封存 holdout）→ `release`（GO/NO-GO）→
  `serve`（按决策加载 base+adapter 或回滚 base）。
  **代码完成不等于已经运行**：正式 120 条 holdout 至今从未执行，因此没有任何 sealed
  证据、没有 formal 发布结论、没有部署过真实模型服务。下一步是用户确认后先只跑 base 侧
  holdout（base 是固定参照，不涉及候选选择，不产生选择性泄漏）。
- 已知结论：R3 候选把格式/安全类失败清零（invalid_call 21→0、policy_violation 8→0），
  但需 ≥2 次工具调用的场景显著回退（task_success 48/60→43/60），不适合直接替换 base。
  失败机制已定位（训练数据 66.7% 只含 1 次工具调用），属 R4 输入。
- 仓库形态：唯一 `main` 分支、无 remote、对原 `veritool-rl` 工作区零依赖；
  `src/veritool_rl` 按 core / retail_ops(domain·build·evaluate·release·serve) /
  training / legacy 分层，目录职责与**四接口双轨完成度**见 `docs/REPO_MAP.md`。
- 不可逆约束：`SealedEvaluationReport` 的字段集合自 LOG-20260810-02 起冻结，
  再改会作废届时已产出的 holdout 证据（`report_id` 是全字段自哈希）。
- 当前基线：624 tests passed，Ruff/mypy/uv lock 全部通过。
- 不自动推进 R3 剩余目标、模型下载或 GPU 运行；下一任务先等待用户确认。
