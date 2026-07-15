"""构造训练轨迹数据集。

示例:
    python scripts/build_trajectories.py
    --config configs/data.example.yaml --seed 0 --output_dir data/trajectories
"""
from __future__ import annotations

from veritool_rl.cli import build_arg_parser, load_config


def main() -> None:
    args = build_arg_parser("VeriTool-RL 轨迹数据构造").parse_args()
    _config = load_config(args.config)
    # TODO: 调用 veritool_rl.data.generators 生成成功/失败轨迹并写出 (见 SPEC.md)
    raise NotImplementedError


if __name__ == "__main__":
    main()
