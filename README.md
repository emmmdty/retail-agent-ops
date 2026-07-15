# VeriTool-RL

**Verifier-Guided Curriculum Post-Training for Small Tool-Using Agents**

面向小型工具智能体的可验证课程式后训练方法。

当前已实现 MiniRetail 最小可行闭环，以及 BFCL V4 固定单轮子集的数据冻结、
Qwen3-1.7B 离线 4-bit 推理、官方 AST 评分和失败分析。研究级 L1/L2，
不宣称生产上线。

> Qwen3-1.7B 在 BFCL V4 固定 200 条单轮 AST 子集上的零样本结果：官方
> BFCL AST accuracy 为 0.815（163/200）；`simple_python`、`multiple`、
> `parallel`、`parallel_multiple` 分别为 0.82、0.90、0.76、0.78。
> 这是 seed 0 固定子集结果，不是 BFCL 官方全量成绩或排行榜成绩。

> 当前 MiniRetail seed-0 证据：Qwen3-1.7B Base 成功 16/32（50%），128/32
> 小规模 QLoRA-SFT 后成功 32/32（100%）；16 条改善、0 条退化，配对 success
> delta 的 bootstrap 95% CI 为 [0.3125, 0.6875]。这是确定性合成 MVP 结果，
> 不是 BFCL、ToolSandbox 或 tau2 成绩。

## 文档

- [`SPEC.md`](./SPEC.md)：研究问题、假设、评测与非-Toy 验收门。
- [`CLAUDE.md`](./CLAUDE.md)：环境快照、服务器边界与执行规则。
- [`docs/adr/0002-mini-retail-mvp.md`](./docs/adr/0002-mini-retail-mvp.md)：MVP 架构决策。
- [`reports/mvp/comparison-seed0/report.md`](./reports/mvp/comparison-seed0/report.md)：
  单卡训练前后指标、命令、资源与失败轨迹分析。
- [`reports/bfcl/qwen3-1.7b-base-seed0/report.md`](./reports/bfcl/qwen3-1.7b-base-seed0/report.md)：
  BFCL 固定 200 条单轮 AST 子集的零样本指标、资源与失败分析。
- [`manifests/bfcl_v4_single_turn_seed0.json`](./manifests/bfcl_v4_single_turn_seed0.json)：
  200 个 task_id、固定 BFCL commit、源文件哈希与 SHA-256 选择 provenance。

## 本地闭环

```bash
uv sync --extra dev

# 生成 128/32/32 的任务、Oracle 轨迹和 TRL SFT 数据，并逐条重放验证
uv run --frozen python scripts/build_trajectories.py \
  --config configs/mvp_data.yaml --seed 0 --output_dir data/mvp/seed0

# Oracle 基础设施验收
uv run --frozen python scripts/evaluate.py \
  --config configs/mvp_eval_oracle.yaml --seed 0 \
  --output_dir reports/mvp/oracle-seed0

uv run --frozen pytest -q
uv run --frozen ruff check .
uv run --frozen mypy
```

## BFCL V4 固定单轮基线

冻结集合使用 BFCL commit `6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`，
四类各 50 条；每类按 `sha256(f"0:{task_id}".encode())` 升序取前 50 条。
评分进程直接导入该 commit 的官方 `ast_checker.py`，checker SHA-256 为
`2aae7a68461a8f76c0be3894c8901b66b56967a1989d3ab066051e3fb97f1538`。
自定义解析率和 schema-valid rate 仅作补充诊断。

正式运行只允许在远程单张空闲 RTX 4090 上执行：

```bash
UV_CACHE_DIR=/data/TJK/uv-cache \
CUDA_VISIBLE_DEVICES=<physical_gpu> \
TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 \
/home/TJK/.local/bin/uv run --frozen --extra train \
  python scripts/evaluate_bfcl.py \
  --config configs/bfcl_v4_single_turn_seed0.yaml \
  --seed 0 \
  --output_dir reports/bfcl/qwen3-1.7b-base-seed0
```

本次运行使用物理 GPU 1，总耗时 581.326 秒；输出可解析率 0.96，
function-call schema-valid rate 0.945，共 37 个官方失败。含原始 prompt、schema
和 possible answer 的官方 score 与 `failures.jsonl` 作为本地/远程审计产物保留，
不进入 git。

## 单卡 Qwen3 前后对照

模型由 ModelScope 下载到服务器共享目录，再通过项目内相对软链接加载。仓库配置
只引用 `models/Qwen3-1.7B`，不使用服务器绝对模型路径或 Hub ID：

```bash
cd /data/TJK
UV_CACHE_DIR=uv-cache /home/TJK/.local/bin/uvx --from modelscope \
  modelscope download --model Qwen/Qwen3-1.7B \
  --local_dir models/Qwen3-1.7B
cd internship-projects/veritool-rl
mkdir -p models
ln -s ../../../models/Qwen3-1.7B models/Qwen3-1.7B
```

以下命令只在 `gpu-4090` 上、经用户确认具体 GPU 后执行：

```bash
# 训练前基线
uv run --frozen python scripts/evaluate.py \
  --config configs/mvp_eval_qwen_base.yaml --seed 0 \
  --output_dir reports/mvp/qwen-base-seed0

# 4-bit QLoRA-SFT
uv run --frozen python scripts/train_sft.py \
  --config configs/mvp_sft_qwen3_1_7b.yaml --seed 0 \
  --output_dir reports/mvp/sft-seed0

# 挂载 adapter 后以相同配置复评
uv run --frozen python scripts/evaluate.py \
  --config configs/mvp_eval_qwen_sft.yaml --seed 0 \
  --output_dir reports/mvp/qwen-sft-seed0

# 按 task_id 配对汇总改善、退化和指标差值
uv run --frozen python scripts/aggregate_report.py \
  --config configs/mvp_compare.yaml --seed 0 \
  --output_dir reports/mvp/comparison-seed0
```

模型权重、adapter、checkpoint 和 `data/` 不进入 git；运行记录保留冻结配置、
日志、逐任务 trajectory、失败清单和 `metrics.json`。
