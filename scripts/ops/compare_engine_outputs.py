"""换引擎之后模型说的话变了没有——只测速度是不够的。

`benchmark_engines.py` 只回答"vLLM 更快多少"。但**更快的前提是它还在做同一件事**：
vLLM 用自己的 attention / sampling kernel，且这一档跑 bf16 而项目的 HF 路径跑 NF4，
两处都可能改变输出。若两侧解析出的工具调用不一致，那份吞吐数字就没有意义——
它衡量的是另一个模型。

这个脚本把**同一批提示词**在项目自己的 HF 后端上跑一遍（合并版权重 + NF4，
与正式评测逐字段相同的生成契约），再与 `--dump_outputs` 存下的 vLLM 文本
逐条比较**解析后的工具调用**（名字 + 参数），而不是比较原始字符串——
标点或措辞的差别不影响这个 agent 的行为，工具调用的差别才影响。

它跑在**项目 venv** 里（需要 `veritool_rl` 与 transformers），vLLM 那一半的输出
是从文件读进来的，因此两个 venv 不需要同时存在。

用法（项目 venv）：

    .venv/bin/python scripts/ops/compare_engine_outputs.py \\
        --model_dir models/Qwen3-4B-sft-006-merged \\
        --prompts /mnt/aidata/tongjiakai/bench-prompts-a.jsonl \\
        --vllm_outputs /mnt/aidata/tongjiakai/vllm-outputs.jsonl \\
        --output /mnt/aidata/tongjiakai/engine-agreement.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from veritool_rl.core.agent.parser import parse_qwen_response  # noqa: E402
from veritool_rl.core.agent.qwen import GenerationSettings, TransformersBackend  # noqa: E402
from veritool_rl.core.agent.runner import SYSTEM_PROMPT  # noqa: E402
from veritool_rl.retail_ops.domain.bundle import load_bundle  # noqa: E402

MAX_NEW_TOKENS = 256


def _call_signature(raw_text: str) -> dict[str, Any] | None:
    """解析成"这一步要做什么"。`None` 表示没有工具调用（自然语言回复或解析失败）。"""
    parsed = parse_qwen_response(raw_text)
    if parsed.tool_call is None:
        return None
    return {"name": parsed.tool_call.name, "arguments": parsed.tool_call.arguments}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model_dir", required=True)
    parser.add_argument("--prompts", type=Path, required=True)
    parser.add_argument("--vllm_outputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bundle_dir", type=Path, default=REPO_ROOT / "domains/retail_ops/v1")
    args = parser.parse_args()

    rows = [
        json.loads(line)
        for line in args.prompts.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    vllm_texts = [
        json.loads(line)["text"]
        for line in args.vllm_outputs.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) != len(vllm_texts):
        raise SystemExit(f"提示词 {len(rows)} 条与 vLLM 输出 {len(vllm_texts)} 条对不上")

    bundle = load_bundle(args.bundle_dir)
    tools = [tool.to_transformers() for tool in bundle.tools]
    backend = TransformersBackend.from_pretrained(
        args.model_dir, settings=GenerationSettings(max_new_tokens=MAX_NEW_TOKENS)
    )

    disagreements: list[dict[str, Any]] = []
    identical_text = 0
    for index, (row, vllm_text) in enumerate(zip(rows, vllm_texts, strict=True)):
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": row["user_request"]},
        ]
        hf_text = backend.generate(messages, tools, MAX_NEW_TOKENS).text
        if hf_text.strip() == vllm_text.strip():
            identical_text += 1
        hf_call = _call_signature(hf_text)
        vllm_call = _call_signature(vllm_text)
        if hf_call != vllm_call:
            disagreements.append(
                {
                    "index": index,
                    "task_id": row["task_id"],
                    "hf": hf_call,
                    "vllm": vllm_call,
                    "hf_text": hf_text[:400],
                    "vllm_text": vllm_text[:400],
                }
            )

    total = len(rows)
    result = {
        "model_dir": args.model_dir,
        "prompt_count": total,
        "hf_quantization": "nf4",
        "vllm_dtype": "bfloat16",
        "tool_call_agreement": (total - len(disagreements)) / total,
        "identical_text_rate": identical_text / total,
        "disagreements": disagreements,
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "disagreements"}, indent=2))
    print(f"工具调用不一致 {len(disagreements)} / {total} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
