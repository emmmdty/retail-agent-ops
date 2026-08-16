"""SFT 训练入口。

示例:
    python scripts/legacy/mvp/train_sft.py
    --config configs/examples/sft.example.yaml --seed 0 --output_dir reports/sft/run0
"""

from __future__ import annotations

from veritool_rl.cli import build_arg_parser, load_config
from veritool_rl.training.sft import run_sft


def main() -> None:
    args = build_arg_parser("VeriTool-RL 课程式 SFT").parse_args()
    config = load_config(args.config)
    run_sft(config, seed=args.seed, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
