"""导出用于推理引擎基准的提示词（**只用公开 fixture，不碰 holdout**）。

`docs/SERVING_FORM_COMPARISON.md` 的第四档（merged + vLLM）需要在项目 venv 之外跑，
而那个 venv 里没有 `veritool_rl`。因此把"构造提示词"与"跑引擎"拆成两步：
这里用项目自己的代码把 **R1 qualification 的 12 条公开 fixture** 渲染成聊天模板字符串，
基准脚本只消费一个 JSONL。

**刻意不用 holdout 或 dev 的请求**：那些是评测输入，把它们复制进一个临时基准文件
会绕开公开/私有边界的全部治理。qualification fixture 是提交进 Git 的合成数据，
用它做延迟基准不泄漏任何东西，而提示词长度分布与真实评测同量级。

用法（项目 venv）：

    .venv/bin/python scripts/ops/export_benchmark_prompts.py \\
        --model_dir models/Qwen3-4B-pinned --output /tmp/prompts.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from veritool_rl.core.agent.runner import SYSTEM_PROMPT  # noqa: E402
from veritool_rl.retail_ops.build.manifests import (  # noqa: E402
    build_qualification,
    load_built_tasks,
)
from veritool_rl.retail_ops.domain.bundle import load_bundle  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model_dir", type=Path, required=True, help="用于应用聊天模板的分词器")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bundle_dir", type=Path, default=REPO_ROOT / "domains/retail_ops/v1")
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="不同 seed 产出不同订单号，因而是**不同的提示词**——冷启吞吐需要没被缓存过的输入",
    )
    args = parser.parse_args()

    bundle = load_bundle(args.bundle_dir)
    with tempfile.TemporaryDirectory() as tmp:
        build_qualification(args.bundle_dir, args.seed, Path(tmp) / "build")
        tasks = list(load_built_tasks(Path(tmp) / "build").values())

    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.model_dir, local_files_only=True)
    tools = [tool.to_transformers() for tool in bundle.tools]

    rows = []
    for task in tasks:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task.user_request},
        ]
        text = tokenizer.apply_chat_template(
            messages,
            tools=tools,
            add_generation_prompt=True,
            enable_thinking=False,
            tokenize=False,
        )
        # 同时留下 `user_request`：`compare_engine_outputs.py` 要用它重建 messages
        # 走项目自己的 HF 后端，而后端吃的是 messages 不是渲染好的字符串。
        rows.append(
            {"task_id": task.task_id, "prompt": text, "user_request": task.user_request}
        )

    args.output.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    lengths = [len(tokenizer(row["prompt"]).input_ids) for row in rows]
    print(f"导出 {len(rows)} 条提示词 → {args.output}")
    mean = sum(lengths) / len(lengths)
    print(f"提示词 token 数：min={min(lengths)} max={max(lengths)} mean={mean:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
