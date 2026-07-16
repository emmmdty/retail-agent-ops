# BFCL QLoRA-SFT 训练报告

## 数据冻结与目标验证

- BFCL commit：`6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`
- 固定 holdout manifest SHA-256：`a74a3748d3af289e8d3f808930b99b6eb5cb9c7d84ba678ff627c762e9448da9`
- SFT split manifest SHA-256：`2c77243c8fd877904af8975799c3248f05fa02ebbfcb60993a2c2c4cb937c265`
- train/dev/holdout：720/80/200，task_id 完全互斥
- train JSONL SHA-256：`f0221c6fcd5134eeb77e3ca31f12919f562d79eb11e403697492169db18a872b`
- dev JSONL SHA-256：`bcb61b85a416f9a75fd85fc60c2e79c43720fdad8b02ba2518a7459fafcb7a8c`
- 官方 AST target 验证：800/800；checker SHA-256：`2aae7a68461a8f76c0be3894c8901b66b56967a1989d3ab066051e3fb97f1538`

完整 chat 序列 token 长度 min/p50/p90/p95/p99/max 为
183/361.5/657.2/745.2/949.05/1115；prompt 最大 948，assistant target 最大
345。由此固定 `max_seq_len=1152`，目标截断数为 0。训练输入使用预分词显式
labels，非 assistant token 均为 `-100`；TRL 运行时跳过二次数据准备和截断。

## 配置

NF4 4-bit、bf16 compute、LoRA r=16、alpha=32、dropout=0.05，target modules
为 q/k/v/o；3 epochs、batch size 2、gradient accumulation 8、lr 2e-4、
gradient checkpointing、assistant-only loss。只保存最终第 3 epoch adapter，
不依据 holdout 选择 checkpoint。训练入口检测到既有配置、adapter、checkpoint
或指标时会拒绝覆盖，防止同一正式运行目录被重复使用。

## GPU smoke

远程目录 `/data/TJK/internship-projects/veritool-rl`，物理 GPU 2：

```bash
UV_CACHE_DIR=/data/TJK/uv-cache CUDA_VISIBLE_DEVICES=2 \
TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 \
/home/TJK/.local/bin/uv run --frozen --extra train python scripts/train_sft.py \
  --config configs/bfcl_v4_sft_seed0_smoke.yaml --seed 0 \
  --output_dir reports/bfcl/qwen3-1.7b-sft-smoke-seed0
```

8 条最长样例完成 2 个 optimizer steps，训练耗时 6.380 秒，总 wall time
11.114 秒，峰值 allocated/reserved 为 3654364160/3919577088 bytes；adapter
离线重载成功（1.569 秒）。首次预检在 optimizer step 0 前触发 TRL 对预分词
数据的 `assistant_only_loss` 输入形态保护并退出，没有产生 adapter；修复为显式
label 验证后，同一授权 smoke 完成上述 2 steps。

## 正式训练

远程目录 `/data/TJK/internship-projects/veritool-rl`，物理 GPU 2：

```bash
UV_CACHE_DIR=/data/TJK/uv-cache CUDA_VISIBLE_DEVICES=2 \
TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 \
/home/TJK/.local/bin/uv run --frozen --extra train python scripts/train_sft.py \
  --config configs/bfcl_v4_sft_seed0.yaml --seed 0 \
  --output_dir reports/bfcl/qwen3-1.7b-sft-seed0/training
```

- 720 train / 80 dev，135 optimizer steps，3 epochs
- 训练耗时：341.471 秒；总 wall time：348.821 秒
- train loss：0.035910；最终 dev loss：0.018945
- 训练吞吐量：6.326 samples/s、0.395 steps/s
- 峰值 allocated/reserved：3653548544/3925868544 bytes
- adapter 离线重载：成功，1.583 秒
- `adapter_model.safetensors`：12875088 bytes，SHA-256
  `d75493e22409bcd77627b40685678c85e5f30082672adcea819b9a1e83640424`

模型、派生训练数据、adapter、checkpoint 和独立 evaluator 环境不进入 git。
训练结果只支持随后固定 200 条单轮 AST holdout 的一次配对评测，不能外推为
官方 BFCL 训练、官方全量成绩、排行榜成绩或独立分布泛化结果。
