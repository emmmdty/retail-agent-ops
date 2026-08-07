# RetailAgentOps R3 Task 1 执行提示词（SFT 训练接入与首次真实 QLoRA-SFT）

## 使用方式

在项目目录启动新会话（Claude Code 或 Codex 均可）：

```bash
cd /home/tjk/myProjects/internship-projects/retail-agent-ops
```

然后把下面"可直接复制的提示词"完整发送给 agent。本提示词只覆盖 R3 的**第一个纵向切片**：
把已有的 QLoRA-SFT 训练器接入正式 CLI，并对 Qwen3-4B 完成一次真实 SFT。不包含正式 holdout
评测、release GO/NO-GO、serve 部署——那些是训练结果出来之后的独立后续提示词，因为打开正式
120 条 holdout 是不可逆的一次性动作，不应该和训练本身捆在同一批提示词里预先批准。

本提示词里"三、本阶段设计决策"一节的选择是主 agent（我）在与用户简短讨论后，按自己的工程
判断给出的默认方案，**不是已经过完整 brainstorming 流程逐项批准的设计**。执行前用户仍可以
否决或修改其中任何一条；除"目标模型"明确标了两个选项外，其余各项都在正文里写了理由，
方便用户快速复核而不是逐句盲信。

## 可直接复制的提示词

```text
你现在负责 RetailAgentOps R3"单卡适配与服务 v1"阶段的第一个任务：把已有的 QLoRA-SFT 训练器
接入正式 CLI，并对 Qwen3-4B 完成一次真实的单卡 QLoRA-SFT。工作目录必须是：

/home/tjk/myProjects/internship-projects/retail-agent-ops

R0-R2 已经全部完成并通过独立审查，当前分支 `feature/r2-formal-data-and-base-eval` 的 HEAD
是 R2 收口提交（`docs/EXECUTION_PLAN.md` 里 R2 已标记"已完成"，R3 为"当前"）。你的任务范围
是本文档"五、TDD 实施任务"与"六、外部执行审批门"两节，其他 R3 子任务（正式 holdout 评测、
release、serve）不在本次范围内。

一、不可违反的边界

1. 先读取并遵守根目录 AGENTS.md/CLAUDE.md；若与本提示词冲突，以它们和用户最新指令为准。
2. 产品名是 RetailAgentOps，Python 包名暂时仍是 `veritool_rl`；不做全仓改名。
3. 本任务**不得**打开或读取正式 RetailOps holdout（120 条，ignored sealed 路径）、不得调用
   `evaluate_authorized_holdout`/`sealed_evaluation.py`；也不得触碰固定 BFCL 200 条 holdout
   及其失败样例。SFT 训练只允许使用已冻结的 train（240 条）和 dev（60 条）split。
4. 每一条外部命令（SSH、远端 GPU 训练命令）都必须单独展示精确命令、实际工作目录、预计
   时长和产物，并等待用户明确批准后才能执行；不得把本文档"六、外部执行审批门"当作已批准
   清单一次性顺序执行。
5. 本地 WSL 只运行 CPU（CLI 分派逻辑、dev-sft 导出、config 校验的 TDD）；GPU 训练只能在
   批准后的远端环境执行。
6. 正式训练目录不可覆盖（`training/sft.py::_ensure_new_training_output` 已经实现这一点，
   不要绕过）。
7. 不自动进入正式 holdout 评测、release 或 serve；SFT 训练本身完成、产出可复现的 adapter
   证据即为本任务终点。
8. 不自动 push、发布或创建外部仓库；分支处置仍由用户决定。

二、固定上下文恢复顺序

1. `docs/CAREER_CONTEXT.md`、`docs/PRODUCT_BRIEF.md`、`SPEC.md`（尤其第 7 节训练策略）
2. `docs/EXECUTION_PLAN.md`（R3 执行/验收目标）
3. `task_plan.md`、`findings.md`、`progress.md`（R2 收口状态与 Task 8 的 GPU 环境经验，
   尤其是 `TORCH_DISABLE_NATIVE_JIT=1`、模型必须真实复制而非符号链接这两条教训）
4. `docs/PROJECT_LOG.md` 最近记录（R2 收口到本提示词之间的条目）
5. `src/veritool_rl/training/sft.py`、`tests/test_sft_config.py`（已有 SFT 训练器全文，
   不要重新发明）
6. `src/veritool_rl/data/generators.py::trajectory_to_sft_example`、
   `src/veritool_rl/retail_ops/teacher_data.py`（train 的 sft.jsonl 已经用这个函数生成）
7. `src/veritool_rl/product_cli.py`（R2 Task 6 建立的 `pipeline` 字段分派 + factory 注入缝
   模式，本次原样复用）
8. 本提示词文档。

三、本阶段设计决策

**目标模型（需要用户在开工前二选一确认，其余各项已按推荐方案定案）**：

- **方案 A（推荐）：直接对 Qwen3-4B 做 SFT。** `SPEC.md` 第 7 节已经明确"Qwen3-4B 是计划
  主模型"，R2 Task 8 已经在 gpu-5090 上验证过 4B 的下载、校验、真实 GPU 推理全链路（dev base
  task_success=0.80），基础设施没有额外风险。1.7B 的 dev base（task_success=0.70，
  policy_violation_rate=0）留作系统卡里的成本/延迟对照基线，本轮不重复训练。
- **方案 B：先对 Qwen3-1.7B 做一次 SFT 作为便宜的全链路验证，再决定是否对 4B 重复。**
  好处是训练更快、更便宜，坏处是 1.7B 的推理链路已经在 R2 验证过，没有新的基础设施不确定性
  需要用低成本模型去"探路"，多一轮训练只是重复劳动。
- 如果用户不确认，默认按方案 A 执行；如需要方案 B，把下文所有 `configs/retail_ops_v1_r3_sft.yaml`
  里的 `model.name`/`local_dir` 换成 1.7B 路径即可，代码逻辑不受影响。

**数据**：复用 R2 Task 8 已产出的私有
`data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722/train-export/train-export-001/sft.jsonl`
（240 条，`messages+tools` 格式，已用 `trajectory_to_sft_example` 生成，与 `training/sft.py`
的数据格式检测直接兼容，不需要转换）。**dev 侧目前没有对应的 sft 格式导出**——`teacher_collect`
按设计只碰 train，dev 从未产生过 teacher 轨迹；需要新增一个只用 `internal_reference`
（Oracle policy，`teacher_data.py` 里已有的 `_build_reference_trajectory`/等价逻辑）跑通 60
条 dev 任务、转 `trajectory_to_sft_example` 格式、写一份 dev 侧私有 `sft.jsonl` 的函数，作为
训练时 `SFTConfig(eval_strategy="epoch")` 监控用的 eval_path。这是本阶段除 CLI 接入外唯一
的新增产品代码。

**超参**：沿用 `training/sft.py` 现有默认值（`LoraSettings`: r=16/alpha=32/dropout=0.05/
target_modules=[q,k,v,o]_proj；`TrainingSettings`: epochs=3/batch_size=2/grad_accum=8
→ 有效 batch 16/lr=2e-4/max_seq_len=1024/bf16/gradient_checkpointing/
assistant_only_loss=True/optim=paged_adamw_8bit/warmup_ratio=0.1）作为起点，这些值已经在
该训练器早先（MiniRetail 时期）的用法里验证过结构正确，不是凭空猜的。**唯一需要在真实训练
前核实的是 `max_seq_len=1024` 是否够用**：对已产出 `sft.jsonl` 做过一次粗略字符数统计
（p95≈1025 字符、max≈1037 字符，只含 `messages` 不含 `tools` schema），大概率在预算内，
但字符数不等于 token 数，必须用 Qwen3 真实 tokenizer 跑一次 token 长度审计（纯 CPU，不需要
GPU）作为实施任务的第一步，而不是直接相信这个粗估。

**模型 provenance 缺口（需要补齐，不是可选项）**：`training/sft.py::ModelSettings` 目前只有
`name: str`（一个路径），**没有** `base_evaluation.py::ModelArtifact` 那样的
`revision`/`file_sha256` 逐文件哈希锁定。按 CLAUDE.md 第 5 节"正式运行固定代码、依赖、
数据/模型标识...并保存 manifest"的要求，正式训练前必须先用 `verify_local_model_files`
（已存在于 `agent/qwen.py`）校验模型目录完整性，不能让训练悄悄跑在一个未经哈希校验的模型
目录上。实现时给 `ModelSettings` 加 `revision`/`file_sha256` 字段并在 `run_sft` 开头调用
`verify_local_model_files`，复用 R2 dev-base config 里已经算好的真实哈希
（`configs/retail_ops_v1_r2_qwen3_4b_dev.yaml` 里的 `model.file_sha256`，同一份模型文件）。

**CLI 接入**：在 `product_cli.py` 新增 `pipeline: sft` 分派（挂在 `build` 下，和
`formal_freeze`/`teacher_collect`/`train_export` 同级），复用已经建立的 config `pipeline`
字段分派 + 可选 `trainer_factory` 关键字参数注入缝模式（同 `client_factory`/
`backend_factory` 那一套，默认工厂真正调用 `veritool_rl.training.sft.run_sft`，CPU 测试
传 fake）。新增两份 config：
- `configs/retail_ops_v1_r3_sft_smoke.yaml`（`training.smoke: true`，8 条固定样本，
  ≤2 optimizer step，`verify_adapter_reload: true`）
- `configs/retail_ops_v1_r3_sft.yaml`（真实全量：240 条 train + 60 条 dev-sft）

**验证阶梯**（对应 `docs/EXECUTION_PLAN.md` R3"先做小样本 overfit/格式验证，再执行一次固定
QLoRA-SFT"）：
1. GPU smoke（`configs/retail_ops_v1_r3_sft_smoke.yaml`）——验证管线跑得通、adapter 能保存
   和重载，不验证数据是否"可学"。
2. 真实小样本 overfit 检查——用一份新的临时 config（比如 `train_limit=16`、更多 epoch、
   关掉 smoke 的 8 条/2 step 限制），观察 train loss 是否显著下降到接近 0；这一步和 smoke
   目的不同，smoke 测的是管线，overfit 测的是这批 label/mask 有没有系统性 bug（比如 assistant
   mask 覆盖错了 token，loss 会稳定在高位不动）。
3. 真实全量 SFT（240 train + 60 dev），产出正式 adapter 和训练指标。

**远端环境**：复用 gpu-5090（R2 Task 8 同一环境，模型文件已是真实复制、已逐文件哈希校验，
不需要重新处理符号链接问题）。**需要在 smoke 阶段验证训练时是否也会触发 R2 Task 8 遇到的
`torch._native` Triton JIT 编译器缺失问题**——训练调用的算子路径和纯推理不完全一样，不能
假设 `TORCH_DISABLE_NATIVE_JIT=1` 一定同样适用，必须重新观察一次真实报错（如果有）再决定。

四、只读 preflight

先执行并报告，不修改文件：

```bash
pwd
git status --short --branch
git log -5 --oneline --decorate
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy
git diff --check
env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check
```

预期基线是 R2 收口时的测试数（`docs/PROJECT_LOG.md` 最新记录里的数字），Ruff/mypy/lock/diff
全绿。若不一致，先做证据化诊断，不得直接开始实现。

五、TDD 实施任务（本地 CPU，不需要外部批准）

严格按 TDD：先写失败测试并确认失败原因，再实现最小闭环，每个子任务完成后跑
focused + 全量 + Ruff + mypy + diff。

1. **Token 长度审计**（脚本或临时测试均可，不需要 GPU）：用 Qwen3 tokenizer（gpu-5090 上
   已有的模型文件，或本地如果有缓存的 tokenizer 文件）跑一遍
   `train-export-001/sft.jsonl` 全部 240 条的 `apply_chat_template` 后 token 长度，报告
   p50/p95/max，确认是否超过 1024；超过则回来跟用户讨论是调大 `max_seq_len` 还是接受截断
   风险，不要静默截断。
2. **`ModelSettings` 补齐 provenance 锁定**：加 `revision: str`、`file_sha256: dict[str, str]`
   字段（同 `base_evaluation.py::ModelArtifact` 的 pattern），`run_sft` 开头调用
   `verify_local_model_files`，先写失败测试（未校验时接受被篡改的模型目录）证明当前代码有
   这个洞，再补上校验。
3. **dev 侧 sft.jsonl 导出**：新函数（放在 `teacher_data.py` 或新模块，按实际代码结构决定），
   对 60 条 dev 任务全部用 `internal_reference`（Oracle）生成轨迹并转
   `trajectory_to_sft_example` 格式，写入私有 `dev-sft/<attempt_id>/sft.jsonl`
   （ignored 路径，复用已审计的 staging/publish 模式）。测试需要覆盖：dev 任务不会意外
   调用 teacher client、输出格式与 train 侧 `sft.jsonl` 一致、不可覆盖已有产物。
4. **CLI `pipeline: sft` 分派**：`_run_build` 新增分支，`_require_config_keys` 校验精确
   key 集合，`trainer_factory` 注入缝（默认工厂调用 `run_sft`），CPU 测试传 fake trainer
   验证配置传递正确，不实际跑训练。
5. **两份 R3 config**：`retail_ops_v1_r3_sft_smoke.yaml`、`retail_ops_v1_r3_sft.yaml`，
   `model.name`/`revision`/`file_sha256` 填真实值（按"三、目标模型"最终选定的模型）。
6. **`tests/test_project_governance.py` 补充**：新 config 不含绝对路径/私有根路径字面量/
   凭据标记；`dev-sft`/训练产物路径仍被 `.gitignore` 覆盖。

六、外部执行审批门（每一条单独展示命令、等待批准）

1. 远端代码同步（同 R2 Task 8 已验证的 `git bundle`/`scp`/`fetch`/`ff-only merge` 流程，
   工作树必须干净）。
2. GPU smoke（`configs/retail_ops_v1_r3_sft_smoke.yaml`，8 条样本，预计数十秒到几分钟）——
   报告是否复现 Triton JIT 问题、adapter reload 是否成功。
3. 真实小样本 overfit 检查——报告 train loss 曲线趋势。
4. 真实全量 SFT（`configs/retail_ops_v1_r3_sft.yaml`）——展示预计时长（未实测，参考 dev
   base 60 任务推理耗时按训练 epoch 数量级外推，不得预先声称具体数字）、预计产物
   （adapter + metrics.json + 训练日志）。批准后执行，执行后报告真实 train/eval loss、
   wall time、峰值显存、adapter 大小。
5. 训练产物同步回本地并核对哈希（同 R2 Task 8 Step 5 模式）。

七、已完成能力与可复用的已审计模式

- `training/sft.py::run_sft`：完整 QLoRA-SFT 执行器，4-bit NF4、assistant-only loss、
  smoke 模式、adapter reload 验证、不可覆盖输出目录——直接复用，不重新实现。
- `data/generators.py::trajectory_to_sft_example`：轨迹转 SFT 样本，train 侧已经在用。
- `product_cli.py` 的 `pipeline` 字段分派 + factory 注入缝模式（R2 Task 6 建立）。
- `agent/qwen.py::verify_local_model_files`/`hash_local_model_files`：模型文件哈希校验，
  R2 dev-base 已经在用，直接复用同一套函数给训练侧加 provenance 锁定。
- gpu-5090（CLAUDE.md 第4节远程环境 2）：`train`/`teacher`/`dev` extra 已同步，Qwen3-4B
  已下载、逐文件哈希校验、真实复制进受信根目录（不是符号链接）；`TORCH_DISABLE_NATIVE_JIT=1`
  已知能绕开推理阶段的 Triton JIT 编译器缺失问题，训练阶段需要重新验证是否同样适用。

八、硬停止条件

- 任何尝试读取或评测正式 120 条 holdout；
- 固定 BFCL holdout 或其失败样例进入本任务；
- 训练在未校验模型文件哈希的情况下开始；
- `_ensure_new_training_output` 的不可覆盖检查被绕过；
- train/eval loss 出现非有限值（NaN/Inf）而流程继续往下跑；
- 任何一条外部命令在没有用户对**那一条精确命令**明确批准前被执行；
- 需要改变 240/60 训练数据配额、LoRA 目标模块、损失口径或模型选择的做法却未经用户确认。

九、验收

- Token 长度审计报告、`ModelSettings` provenance 锁定的失败测试与修复、dev-sft 导出、
  CLI 分派、两份 config：CPU 全量测试 + Ruff + mypy + diff 全绿。
- GPU smoke 与 overfit 检查证据（不需要正式归档，但要在 `docs/PROJECT_LOG.md` 记录真实结果）。
- 真实全量 SFT 完成后：adapter 目录、`metrics.json`（含有限 train/eval loss、资源用量）、
  可重载性证据（`reload_adapter_offline` 或等价校验），全部路径正确落在 ignored 私有目录。
- 不产生任何正式 holdout 评测结果、不做 release 决策、不部署 serve——这些留给下一个提示词。
```
