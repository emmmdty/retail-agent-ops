"""评测入口。

示例:
    python scripts/evaluate.py --config configs/sft.example.yaml --seed 0 --output_dir reports/eval/run0
"""
from __future__ import annotations

from veritool_rl.cli import build_arg_parser, load_config


def main() -> None:
    args = build_arg_parser("VeriTool-RL 评测").parse_args()
    _config = load_config(args.config)
    # TODO: 构造 ToolEnv 与 Evaluator, 运行并写出分层报告 (见 SPEC.md「评测指标」)
    raise NotImplementedError


if __name__ == "__main__":
    main()
