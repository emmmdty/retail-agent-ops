"""偏好优化 (DPO/SimPO) 训练入口。

示例:
    python scripts/legacy/mvp/train_preference.py
    --config configs/examples/sft.example.yaml --seed 0 --output_dir reports/dpo/run0
"""
from __future__ import annotations

from veritool_rl.cli import build_arg_parser, load_config
from veritool_rl.legacy.training.preference import run_preference


def main() -> None:
    args = build_arg_parser("VeriTool-RL 偏好优化").parse_args()
    config = load_config(args.config)
    run_preference(config, seed=args.seed, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
