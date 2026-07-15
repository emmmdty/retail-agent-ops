"""聚合 reports/ 下多次运行, 生成汇总表与图表。

示例:
    python scripts/aggregate_report.py
    --config configs/sft.example.yaml --seed 0 --output_dir reports/summary
"""
from __future__ import annotations

from veritool_rl.cli import build_arg_parser, load_config


def main() -> None:
    args = build_arg_parser("VeriTool-RL 结果聚合").parse_args()
    _config = load_config(args.config)
    # TODO: 汇总均值/方差/置信区间, 生成消融对照表与成本-质量 Pareto 图 (见 SPEC.md)
    raise NotImplementedError


if __name__ == "__main__":
    main()
