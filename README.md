# VeriTool-RL

**Verifier-Guided Curriculum Post-Training for Small Tool-Using Agents**

面向小型工具智能体的可验证课程式后训练方法。

当前已实现 MiniRetail 最小可行闭环：确定性任务生成、Hermes tool call、结构化
observation、final-state/policy verifier、版本化 trajectory、精确 replay、指标、
Qwen3-1.7B 推理适配、4-bit QLoRA-SFT 和训练前后配对汇总。研究级 L1/L2，
不宣称生产上线。

> 当前证据：Oracle 本地闭环可运行；Qwen3 基线、QLoRA 和训练后评测需按
> `CLAUDE.md` 的单卡确认门在 `gpu-4090` 执行。未运行前不填写模型成绩。

## 文档

- [`SPEC.md`](./SPEC.md)：研究问题、假设、评测与非-Toy 验收门。
- [`CLAUDE.md`](./CLAUDE.md)：环境快照、服务器边界与执行规则。
- [`docs/adr/0002-mini-retail-mvp.md`](./docs/adr/0002-mini-retail-mvp.md)：MVP 架构决策。

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

## 单卡 Qwen3 前后对照

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
