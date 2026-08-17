# 换推理引擎会不会改变模型的决策——训练过的不会，零训练基座会

**这份文件回答的是正确性问题，不是性能问题。**
[`SERVING_FORM_COMPARISON.md`](./SERVING_FORM_COMPARISON.md) 第四档量的是"bf16 + vLLM
能跑多快"（部署形态）。这里量的是"同一份权重换一个引擎，在**真实评测任务**上会不会
做出不同的决策"。两者的读数不可混用。

## 先纠正一个我此前说错的判断

我曾写过"vLLM 走完整 evaluate 路径必须把它加进项目依赖，那会让全部 sealed 证据失配"。
**这是错的，而且字段找错了**：

```
product_cli.py:1500   def _current_uv_lock_sha256() -> str:
                          return sha256_file(_repo_root() / "uv.lock")
```

`uv_lock_sha256` 哈希的是**仓库里那个文件**，不是实际装了什么包。换一个 venv 跑它纹丝
不动——**不是会失配，是根本发现不了**。这本身是个缺口：该字段声称锁定运行环境，
实际只锁定了一个文件。

真正拦住 vLLM 的是另一处，而且它是**对的**那种拦截：

```
qwen.py:60             quantization: Literal["nf4"] = "nf4"
base_evaluation.py:666 declared_settings != config.generation → 拒绝
```

于是这里的做法是**让 vLLM 也跑 bitsandbytes NF4**（两侧 `bitsandbytes` 均为 0.49.2）。
契约一个字没改，而且对照更纯：**只有引擎这一个变量在变**。

## 结果（gpu-5090 物理 GPU 0，三组 × 两引擎）

| | HF（transformers） | **vLLM** | 是否一致 |
|---|---|---|---|
| **dev 60 条 / 合并候选** | 1.0000（60/60） | **1.0000（60/60）** | ✅ 全部指标相同 |
| **OOD 60 条 / 合并候选** | 0.5833（35/60） | **0.5833（35/60）** | ✅ 逐类别、逐 kind、失败分布全同 |
| **OOD 60 条 / 零训练基座** | 0.2167（13/60） | **0.2333（14/60）** | ❌ **不一致** |

三组的 `replayable_count` 都是 60/60。

### 训练过的模型：一致到什么程度

**dev / 合并候选**——`task_success`、`policy_violation_count`、`invalid_call_count`、
`average_tool_calls`、`schema_valid_rate`、`verifier_reward` 六项逐字段相同；
唯一的差别是 `average_output_tokens` 125.9667 vs 126.0167（60 条里多了 3 个 token）。

**OOD / 合并候选**——三个类别（1.0000 / 0.0000 / 0.7500）与全部 kind 逐项相同，
`failure_kind_counts` 一字不差。差别只在 110 次调用里的**一次**：
`executable_count` 72→71、`invalid_call_count` 38→39。**它没有改变任何一条任务的结果。**

### 零训练基座：一致性破了

| | HF | vLLM |
|---|---|---|
| `task_success` | 0.2167 | **0.2333** |
| `colloquial`（口语，n=4） | 0.50 | **0.75** |
| `policy_violation_count` | 12 | 13 |
| `invalid_call_count` | 44 | 41 |
| `schema_valid_rate` | 0.5165 | 0.5444 |

差异**全部集中在 `colloquial` 一个 kind**：失败 2 条 → 1 条，其余十个 kind 的
`failure_kind_counts` 逐项相同。

**为什么是基座破而不是候选破**：基座在这个集合上约 47 次调用里有 **44 次非法**——
它的输出本来就在合法/非法的边界上晃。NF4 在两个引擎下的算子实现不同，数值上的微小
差别足以把边界上的样本推到另一侧。训练过的模型输出是决断的，同样的数值扰动推不动它。

## 由此改变的做法

**引擎替换不是普遍保行为的，必须逐模型验证，不能假定。**
"我们换了个更快的引擎，模型还是那个模型"这句话在这次实验里**一半成立一半不成立**：
对交付的候选成立，对基座不成立。而发布门禁是**比值**——base 与 candidate 两侧都要测。
因此若某天要在 vLLM 上做发布判定，**base 侧的读数会变**，不能沿用 HF 的 base 证据。

## 吞吐：同量化、真实工作负载下 ~4.85×

两侧都是 NF4，因此这是**纯引擎效应**：

| | HF tok/s | vLLM tok/s | 倍数 | wall（60 条） |
|---|---|---|---|---|
| dev / 合并候选 | 50.74 | **246.60** | 4.86× | 149.0 s → **30.7 s** |
| OOD / 合并候选 | 50.94 | **246.65** | 4.84× | 218.3 s → **44.5 s** |
| OOD / 零训练基座 | 51.05 | **249.87** | 4.89× | 158.1 s → **30.8 s** |

**这与第四档那个微基准的分解不一致，必须一起看。** 那里在 12 条单轮 fixture 上测出
"去量化 1.64× × 换引擎 2.02×"；这里在真实多轮任务上、同为 NF4，引擎单独就是 **4.85×**。
差别来自两处：(a) 那 12 条是 bf16 对 bf16，而 HF 的 bnb NF4 前向要逐次反量化，
相对代价远大于 bf16；(b) 真实任务是多轮的，上下文更长。
**"引擎快多少"不是一个数**，它取决于量化方式与工作负载，不得跨条件引用。

## 这份读数**不**声称什么

1. **它不是发布判定**，dev 与 OOD 都不是封存集合。封存 holdout 上的 vLLM 判定会是
   **再消耗一次**封存 holdout 观测，需用户单独决策。
2. **两侧不同 commit**：HF 侧 `d57f17f` / `007e506`，vLLM 侧 `b573f23` / `d1f37bc`。
   期间的改动是新增 vLLM 后端与硬件 provider，未触碰 transformers 评测路径，
   但严格说这不是同 commit 配对——按项目自己的标准，它属于**跨形态对照**而非配对判定。
3. **`peak_memory_bytes` 两侧不可比**：HF 侧是进程真实峰值（3.02 GB），vLLM 侧是
   `NvmlHardwareProvider` 读的整卡占用水位（15.65 GB），含 vLLM 按
   `gpu_memory_utilization` 预占的池子与同卡其他人的进程。见该类的文档字符串。
4. **未合并的 adapter 未测**：`VllmBackend` 对 adapter 直接 `NotImplementedError`
   ——vLLM 的 LoRA 走 `LoRARequest`，那条路径没实现也没测试，硬失败优于假装支持。
5. n = 60 每组，`colloquial` 的差异只有 1 条任务（n=4），**不足以量化"引擎会翻多少条"**，
   只足以证伪"引擎替换必然保行为"。

## 复现

```bash
# 项目 venv 之外的独立环境：Python 3.12 + vllm 0.27.1 + bitsandbytes==0.49.2
# （与项目同版本，否则 NF4 的数值就不是同一套），项目 uv.lock 不变
PYTHONPATH=<repo>/src TRITON_CACHE_DIR=<隔离目录> CC=<zig cc shim> \
  <vllm-venv>/bin/python -c 'import sys; from veritool_rl.product_cli import main; \
    sys.argv=["retail-agent-ops","evaluate","--config",...,"--engine","vllm"]; \
    raise SystemExit(main())'
```

`TRITON_CACHE_DIR` 与 `CC` 两条都是必需的，理由见 [`findings.md`](../findings.md)
「triton 缓存跨 venv 污染」——省掉会**打挂项目自己的 HF 评测路径**。
