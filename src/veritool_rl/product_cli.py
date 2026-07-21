"""RetailAgentOps 稳定 build/evaluate/release/serve 产品命令面。"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import uvicorn

from veritool_rl.artifacts import create_output_dir, sha256_file, write_json
from veritool_rl.cli import load_config
from veritool_rl.paths import validate_project_relative_path
from veritool_rl.retail_ops.bundle import load_bundle
from veritool_rl.retail_ops.evaluation import (
    EvaluationMode,
    evaluate_retail_ops,
    load_run_evidence,
)
from veritool_rl.retail_ops.manifests import build_qualification
from veritool_rl.retail_ops.release import decide_release, load_release_report, write_release_report
from veritool_rl.retail_ops.service import create_app


def build_product_parser() -> argparse.ArgumentParser:
    """构造稳定的 RetailAgentOps 产品 CLI parser。"""
    parser = argparse.ArgumentParser(description="RetailAgentOps 产品流水线")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="构建 qualification 任务与 manifest")
    _add_common_arguments(build)

    evaluate = subparsers.add_parser("evaluate", help="运行固定任务评测")
    _add_common_arguments(evaluate)
    evaluate.add_argument("--input_dir", type=Path, required=True, help="build 产物目录")

    release = subparsers.add_parser("release", help="执行配对发布门禁")
    _add_common_arguments(release)
    release.add_argument(
        "--baseline_dir",
        type=Path,
        required=True,
        help="基座 run evidence 目录",
    )
    release.add_argument(
        "--candidate_dir",
        type=Path,
        required=True,
        help="候选 run evidence 目录",
    )

    serve = subparsers.add_parser("serve", help="按发布结论启动 qualification 服务")
    _add_common_arguments(serve)
    serve.add_argument(
        "--release_dir",
        type=Path,
        required=True,
        help="release report 目录",
    )
    serve.add_argument("--input_dir", type=Path, required=True, help="build 产物目录")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """解析命令并同步执行一个不可覆盖的产品流水线步骤。"""
    parser = build_product_parser()
    args = parser.parse_args(argv)
    handlers: dict[str, Callable[[argparse.Namespace], None]] = {
        "build": _run_build,
        "evaluate": _run_evaluate,
        "release": _run_release,
        "serve": _run_serve,
    }
    handlers[args.command](args)
    return 0


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, required=True, help="已提交的 YAML 配置")
    parser.add_argument("--seed", type=int, default=0, help="运行随机种子")
    parser.add_argument("--output_dir", type=Path, required=True, help="新产物目录")


def _run_build(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    _require_config_keys(config, {"bundle_dir", "split"})
    if config["split"] != "qualification":
        raise ValueError("R1 build 只允许 qualification split")
    bundle_dir = _bundle_dir(config)
    build_qualification(bundle_dir, args.seed, args.output_dir)


def _run_evaluate(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    _require_config_keys(
        config,
        {
            "bundle_dir",
            "mode",
            "policy_type",
            "bootstrap_samples",
            "parser_id",
            "budget",
        },
    )
    bundle_dir = _bundle_dir(config)
    try:
        mode = EvaluationMode(str(config["mode"]))
    except ValueError as error:
        raise ValueError(f"未知 RetailOps evaluation mode: {config['mode']}") from error
    policy_type = config["policy_type"]
    if not isinstance(policy_type, str) or not policy_type:
        raise ValueError("policy_type 必须是非空字符串")
    evaluate_retail_ops(
        bundle_dir=bundle_dir,
        build_dir=args.input_dir,
        policy_type=policy_type,
        config=config,
        seed=args.seed,
        output_dir=args.output_dir,
        mode=mode,
    )


def _run_release(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    _require_config_keys(config, {"bundle_dir"})
    bundle = load_bundle(_bundle_dir(config))
    baseline = load_run_evidence(args.baseline_dir / "run.json")
    candidate = load_run_evidence(args.candidate_dir / "run.json")
    if (
        baseline.bundle_sha256 != bundle.bundle_sha256
        or candidate.bundle_sha256 != bundle.bundle_sha256
    ):
        raise ValueError("run evidence 与 release bundle SHA-256 不匹配")
    report = decide_release(baseline, candidate, bundle.release)
    write_release_report(report, args.output_dir)


def _run_serve(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    _require_config_keys(config, {"bundle_dir", "host", "port"})
    bundle_dir = _bundle_dir(config)
    host = config["host"]
    port = config["port"]
    if not isinstance(host, str) or not host:
        raise ValueError("host 必须是非空字符串")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port 必须是 1 到 65535 的整数")

    app = create_app(args.release_dir, bundle_dir, args.input_dir)
    release = load_release_report(args.release_dir / "release.json")
    create_output_dir(args.output_dir)
    write_json(
        args.output_dir / "service.json",
        {
            "release_sha256": sha256_file(args.release_dir / "release.json"),
            "bundle_sha256": load_bundle(bundle_dir).bundle_sha256,
            "deployment": release.deployment,
            "host": host,
            "port": port,
        },
    )
    uvicorn.run(app, host=host, port=port)


def _bundle_dir(config: dict[str, Any]) -> Path:
    value = config.get("bundle_dir")
    if not isinstance(value, str):
        raise ValueError("bundle_dir 必须是字符串")
    bundle_dir = Path(value)
    validate_project_relative_path(bundle_dir, "bundle_dir")
    return bundle_dir


def _require_config_keys(config: dict[str, Any], expected: set[str]) -> None:
    if set(config) != expected:
        raise ValueError(
            f"配置字段不符合命令契约: expected={sorted(expected)}, actual={sorted(config)}"
        )
