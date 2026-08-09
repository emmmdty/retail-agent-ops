"""汇总 BFCL 固定 holdout 的 base/SFT 配对结果。"""

from __future__ import annotations

from pathlib import Path

from veritool_rl.cli import build_arg_parser, load_config
from veritool_rl.legacy.eval.bfcl_compare import aggregate_bfcl_runs


def main() -> None:
    """CLI 入口。"""
    args = build_arg_parser("汇总 BFCL Base/QLoRA-SFT 配对结果").parse_args()
    config = load_config(args.config)
    baseline_dir = config.get("baseline_dir")
    sft_dir = config.get("sft_dir")
    manifest_path = config.get("manifest_path")
    bootstrap_samples = config.get("bootstrap_samples")
    sensitive = config.get("benchmark_sensitive_ids", [])
    if (
        not isinstance(baseline_dir, str)
        or not isinstance(sft_dir, str)
        or not isinstance(manifest_path, str)
    ):
        raise ValueError("baseline_dir、sft_dir、manifest_path 必须是路径字符串")
    if not isinstance(bootstrap_samples, int) or isinstance(bootstrap_samples, bool):
        raise ValueError("bootstrap_samples 必须是整数")
    if not isinstance(sensitive, list) or not all(
        isinstance(task_id, str) for task_id in sensitive
    ):
        raise ValueError("benchmark_sensitive_ids 必须是字符串列表")
    aggregate_bfcl_runs(
        baseline_dir=Path(baseline_dir),
        sft_dir=Path(sft_dir),
        manifest_path=Path(manifest_path),
        output_dir=args.output_dir,
        bootstrap_samples=bootstrap_samples,
        seed=args.seed,
        benchmark_sensitive_ids=set(sensitive),
    )


if __name__ == "__main__":
    main()
