# Qwen3-1.7B 单卡 MiniRetail MVP 实验报告（seed 0）

## 1. 结论

本次实验在物理 GPU 0（RTX 4090 24GB，UUID
`GPU-64808f0f-5759-df09-a63a-2e38c2ce1697`）上完成了训练前评测、128/32
小规模 4-bit QLoRA-SFT、训练后复评和 32 条任务的逐任务配对。

- Base 模型成功 16/32（0.5000），SFT adapter 成功 32/32（1.0000）。
- 成功率绝对变化为 +0.5000；配对 bootstrap 95% CI 为 [0.3125, 0.6875]。
- 16 条任务改善，0 条退化，16 条不变。
- 两侧 schema-valid rate 和 executable rate 均为 1.0000；没有无效输出、非法调用或
  policy violation。提升来自模型在查询后继续执行正确退款动作，并能在
  `transient_error` 后重试。
- 该结果完成了 MiniRetail 最小可行闭环，但只是 seed 0、32 条确定性合成任务，不能
  外推为 BFCL、ToolSandbox、tau2 或真实业务成绩。

## 2. 实验快照与输入

| 项目 | 实际值 |
|---|---|
| 实验代码 commit | `291bdb0b5b23a67ada489491a012ab09e9f0e631` |
| 原始产物 commit | `b8c5527` |
| 远程目录 | `/data/TJK/internship-projects/veritool-rl` |
| 物理 / 逻辑 GPU | GPU 0 / `cuda:0` |
| 模型引用 | `models/Qwen3-1.7B -> /data/TJK/models/Qwen3-1.7B` |
| 权重分片 SHA-256 | `169ad53ec313c3a34b06c0809216e4fc072cce444a5d4ff2b59690d064130ed5` / `912becff8d60672aa8628ef08c05898d9adf17c2ad4ae3caf99b065622fdeff9` |
| 数据 | train 128、dev 32、test 32；test `task_id` 32/32 唯一 |
| Oracle | 32/32 成功，32 条轨迹全部重放通过 |
| 训练样本长度 | train 最大 629 tokens，dev 最大 630 tokens，未触及 1024 上限 |

所有模型命令都设置了 `TRANSFORMERS_OFFLINE=1` 和 `HF_HUB_OFFLINE=1`。console
中没有下载或 Hub URL；权重加载日志来自项目内相对软链接。

## 3. 完整命令与耗时

以下命令均通过 `ssh gpu-4090` 在上述远程目录执行，且使用
`UV_CACHE_DIR=/data/TJK/uv-cache` 与显式 uv 路径。

```bash
# 单任务 smoke，20.73 秒
/usr/bin/time -v env CUDA_VISIBLE_DEVICES=0 TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 \
  UV_CACHE_DIR=/data/TJK/uv-cache /home/TJK/.local/bin/uv run --frozen \
  python scripts/evaluate.py --config configs/mvp_eval_qwen_smoke.yaml --seed 0 \
  --output_dir reports/mvp/smoke-qwen-base-seed0 \
  2>&1 | tee reports/mvp/smoke-qwen-base-seed0/console.txt

# 训练前 baseline，73.65 秒
/usr/bin/time -v env CUDA_VISIBLE_DEVICES=0 TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 \
  UV_CACHE_DIR=/data/TJK/uv-cache /home/TJK/.local/bin/uv run --frozen \
  python scripts/evaluate.py --config configs/mvp_eval_qwen_base.yaml --seed 0 \
  --output_dir reports/mvp/qwen-base-seed0 \
  2>&1 | tee reports/mvp/qwen-base-seed0/console.txt

# 4-bit QLoRA-SFT，83.47 秒（脚本内资源窗口 78.05 秒）
/usr/bin/time -v env CUDA_VISIBLE_DEVICES=0 TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 \
  UV_CACHE_DIR=/data/TJK/uv-cache /home/TJK/.local/bin/uv run --frozen \
  python scripts/train_sft.py --config configs/mvp_sft_qwen3_1_7b.yaml --seed 0 \
  --output_dir reports/mvp/sft-seed0 \
  2>&1 | tee reports/mvp/sft-seed0/console.txt

# adapter 复评，118.59 秒
/usr/bin/time -v env CUDA_VISIBLE_DEVICES=0 TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 \
  UV_CACHE_DIR=/data/TJK/uv-cache /home/TJK/.local/bin/uv run --frozen \
  python scripts/evaluate.py --config configs/mvp_eval_qwen_sft.yaml --seed 0 \
  --output_dir reports/mvp/qwen-sft-seed0 \
  2>&1 | tee reports/mvp/qwen-sft-seed0/console.txt

# CPU 配对汇总，0.36 秒
/usr/bin/time -v env CUDA_VISIBLE_DEVICES="" TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 \
  UV_CACHE_DIR=/data/TJK/uv-cache /home/TJK/.local/bin/uv run --frozen \
  python scripts/aggregate_report.py --config configs/mvp_compare.yaml --seed 0 \
  --output_dir reports/mvp/comparison-seed0 \
  2>&1 | tee reports/mvp/comparison-seed0/console.txt
```

每个模型作业前均重新执行 `nvidia-smi`。GPU 0 当时为 15 MiB、0% 利用率且无
计算进程；GPU 2/3 在初始预检时被其他任务占用，因此没有使用。

## 4. 训练与评测指标

### 4.1 QLoRA-SFT

| 指标 | 实际值 |
|---|---:|
| epochs / optimizer steps | 3 / 24 |
| train loss | 0.0439486 |
| 最终 eval loss | 0.00677816 |
| 第一 / 最后 step loss | 0.341138 / 0.000341969 |
| train runtime | 69.5959 秒 |
| 脚本墙钟 | 78.0504 秒 |
| CUDA peak allocated | 3,523,116,032 bytes（约 3.28 GiB） |
| CUDA peak reserved | 3,919,577,088 bytes（约 3.65 GiB） |

24 个 step loss、train loss 和 eval loss 均为有限值，没有 NaN、Inf 或 OOM。adapter
文件 `adapter_model.safetensors` 为 12,875,088 bytes；`PeftConfig` 可重新读取，
`base_model_name_or_path` 仍为 `models/Qwen3-1.7B`。训练后评测的 trajectory metadata
统一记录 `qwen:models/Qwen3-1.7B+reports/mvp/sft-seed0/adapter`，证明实际挂载并运行了
adapter。

### 4.2 训练前后对照

| 指标 | Base | SFT | 差值 |
|---|---:|---:|---:|
| task success / final-state success | 0.5000 | 1.0000 | +0.5000 |
| schema-valid rate | 1.0000 | 1.0000 | 0.0000 |
| executable rate | 1.0000 | 1.0000 | 0.0000 |
| verifier reward | 0.5000 | 1.0000 | +0.5000 |
| tool selection accuracy | 0.571429 | 1.0000 | +0.428571 |
| argument accuracy | 0.571429 | 1.0000 | +0.428571 |
| recovery success | 0.0000 | 1.0000 | +1.0000 |
| 平均工具调用数 | 1.0000 | 1.7500 | +0.7500 |
| 平均 turns | 1.5000 | 1.7500 | +0.2500 |
| 平均 input tokens | 555.094 | 685.250 | +130.156 |
| 平均 output tokens | 50.531 | 59.438 | +8.906 |
| 平均模型延迟 | 2061.99 ms | 3464.24 ms | +1402.24 ms |
| invalid output / invalid call | 0 / 0 | 0 / 0 | 0 / 0 |
| policy violation | 0 | 0 | 0 |

Base 的 16 条失败全部属于 `premature_final_response`；SFT 没有失败。调用数、token 和
延迟上升并非隐藏成本，而是模型从“查询后提前结束”变为执行完整退款或重试序列的直接
结果。

## 5. 代表性失败轨迹

1. `test-refund_eligible-0001`：Base 正确调用 `get_order`，observation 明确给出
   `refund_status=none`，随后却文本声称“退款已成功处理”，没有调用
   `refund_order`，final-state reward 为 0。SFT 按相同查询后调用
   `refund_order(order_id=O-9FEFA7DA1C, reason=wrong_item)`，状态变为 `refunded`。
2. `test-refund_eligible-0029`：Base 把 `status=delivered` 错误解释为不可退款，文本拒绝
   一个 `refund_deadline=40` 且应退款的订单。SFT 使用 gold 参数完成第二步退款。
3. `test-refund_recovery-0003`：Base 查询后把 `delivered` 误述为“退款已经完成”，完全
   没有进入退款和错误恢复。SFT 先调用 `refund_order`，收到真实
   `transient_error` 后以相同参数重试，第二次成功并通过 final-state verifier。

这三条失败都不是 JSON/schema/tool executor 错误，而是 observation 语义理解和后续动作
选择错误。SFT 后没有成功转失败的退化样本。

## 6. 产物与版本控制边界

- Smoke：`reports/mvp/smoke-qwen-base-seed0/`
- Baseline：`reports/mvp/qwen-base-seed0/`
- SFT 记录：`reports/mvp/sft-seed0/`
- Adapter 复评：`reports/mvp/qwen-sft-seed0/`
- 配对结果：`reports/mvp/comparison-seed0/`

评测目录包含冻结配置、metrics、trajectories、failures、摘要日志和清理过终端控制符的
完整 console。SFT 目录保留 metrics、trainer history 和 console；`adapter/` 与
`checkpoints/` 留在远程并由 `.gitignore` 排除。`data/`、`models/`、adapter、checkpoint
和所有权重文件均未进入 git。

## 7. 限制

- 只有一个 seed 和 32 条测试任务；bootstrap CI 反映这组任务的配对不确定性，不替代
  多 seed 方差。
- train/dev/test 的实体 ID 不重叠，但来自同一 MiniRetail 生成规则；接近零的训练 loss
  和 100% 测试成功可能包含明显的模板分布拟合，不能证明真实工具泛化。
- 没有执行 BFCL、ToolSandbox 或 tau2 adapter，也没有做 schema 扰动、偏好优化、GRPO
  或多模型规模对照。
- SFT 提高成功率的同时增加了调用数、token 和延迟；本阶段只证明小规模可验证闭环，
  尚未证明真实 benchmark 上的质量-成本优势。
