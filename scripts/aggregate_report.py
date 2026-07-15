"""配对汇总 Qwen3 基线与 QLoRA adapter 评测。"""

from __future__ import annotations

from pathlib import Path

from veritool_rl.cli import build_arg_parser, load_config
from veritool_rl.reporting import aggregate_runs


def main() -> None:
    args = build_arg_parser("VeriTool-RL 结果聚合").parse_args()
    config = load_config(args.config)
    baseline_dir = config.get("baseline_dir")
    adapter_dir = config.get("adapter_dir")
    if not isinstance(baseline_dir, str) or not isinstance(adapter_dir, str):
        msg = "baseline_dir 和 adapter_dir 必须是路径字符串"
        raise ValueError(msg)
    aggregate_runs(
        baseline_dir=Path(baseline_dir),
        adapter_dir=Path(adapter_dir),
        output_dir=args.output_dir,
        config=config,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
