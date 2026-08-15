"""推理引擎基准：HF `generate` vs vLLM，同一份权重、同一批提示词。

`docs/handoffs/2026-08-15-architecture-hardening-execution-prompt.md` §7.2 要的四档里，
前三档（base 4bit / adapter 未合并 / 合并后重新量化）已经由正式评测产出，
这一档是 **merged + vLLM**。

**它跑在独立 venv 里，不进项目依赖**：`uv_lock_sha256` 在 `SEALED_PAIRING_FIELDS` 内，
把 vLLM 装进项目环境会让全部已有 sealed 证据不可配对。因此这份读数是**旁证**，
不是评测证据链的一部分——它不产出 run evidence，也不进任何发布判定。

两个**必须分开报告**的量：

- **单流延迟**：一次请求从头到尾多久。发布门禁测的就是这个（服务串行跑 episode，
  并发上限为 1，见 `docs/SYSTEM_CARD.md` §4.2）。
- **批量吞吐**：并发时每秒多少 token。这是 vLLM 的主场，但**当前的服务契约拿不到**
  ——它刻意串行，因为并发会让延迟测量失真而延迟是门禁项。

把两者混成一个"vLLM 快 N 倍"的说法是不诚实的：快的是当前架构不使用的那一半。

用法（vLLM venv）：

    /mnt/aidata/tongjiakai/vllm-venv/bin/python scripts/ops/benchmark_engines.py \\
        --model_dir models/Qwen3-4B-sft-006-merged --prompts /tmp/prompts.jsonl \\
        --output /tmp/vllm-bench.json --gpu_memory_utilization 0.35
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

MAX_NEW_TOKENS = 256


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(quantile * len(ordered) + 0.5) - 1))
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model_dir", required=True)
    parser.add_argument("--prompts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gpu_memory_utilization", type=float, default=0.35)
    parser.add_argument("--max_model_len", type=int, default=4096)
    args = parser.parse_args()

    prompts = [
        json.loads(line)["prompt"]
        for line in args.prompts.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    from vllm import LLM, SamplingParams

    # 与正式评测逐字段相同的生成契约：贪心、不思考、256 上限。
    sampling = SamplingParams(temperature=0.0, max_tokens=MAX_NEW_TOKENS)
    llm = LLM(
        model=args.model_dir,
        dtype="bfloat16",
        gpu_memory_utilization=args.gpu_memory_utilization,
        max_model_len=args.max_model_len,
        enforce_eager=False,
        enable_prefix_caching=True,
    )

    # 预热：第一次请求包含 CUDA graph 捕获与缓存预热，计入延迟会高估稳态。
    llm.generate(prompts[:1], sampling)

    single: list[float] = []
    single_tokens = 0
    for prompt in prompts:
        started = time.perf_counter()
        outputs = llm.generate([prompt], sampling)
        single.append((time.perf_counter() - started) * 1000)
        single_tokens += len(outputs[0].outputs[0].token_ids)

    batch_started = time.perf_counter()
    batch_outputs = llm.generate(prompts, sampling)
    batch_seconds = time.perf_counter() - batch_started
    batch_tokens = sum(len(output.outputs[0].token_ids) for output in batch_outputs)

    result: dict[str, Any] = {
        "engine": "vllm",
        "model_dir": args.model_dir,
        "dtype": "bfloat16",
        "prompt_count": len(prompts),
        "max_new_tokens": MAX_NEW_TOKENS,
        "single_stream": {
            "mean_latency_ms": statistics.fmean(single),
            "p50_latency_ms": _percentile(single, 0.50),
            "p95_latency_ms": _percentile(single, 0.95),
            "output_tokens": single_tokens,
            "output_tokens_per_second": single_tokens / (sum(single) / 1000),
        },
        "batched": {
            "wall_seconds": batch_seconds,
            "output_tokens": batch_tokens,
            "output_tokens_per_second": batch_tokens / batch_seconds,
        },
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
