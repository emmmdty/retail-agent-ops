"""Qwen3-1.7B 的 BFCL V4 固定单轮子集零样本评测入口。"""

from __future__ import annotations

import gc
import shlex
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from veritool_rl.agent.qwen import TransformersBackend
from veritool_rl.artifacts import sha256_file, write_json, write_yaml
from veritool_rl.cli import build_arg_parser, load_config
from veritool_rl.data.bfcl import BFCL_CATEGORIES, load_bfcl_manifest
from veritool_rl.eval.bfcl_runner import (
    finalize_bfcl_artifacts,
    generate_bfcl_records,
    inspect_local_model,
    resolve_manifest_task_answers,
    run_official_evaluator,
    validate_offline_single_gpu_environment,
    verify_bfcl_checkout,
    write_bfcl_generation_artifacts,
)
from veritool_rl.paths import validate_project_relative_path


def run_bfcl_evaluation(config_path: Path, seed: int, output_dir: Path) -> dict[str, Any]:
    """执行生成、官方评分和严格汇总，并返回真实指标。"""
    run_started = time.perf_counter()
    started_at = datetime.now(UTC).isoformat()
    config = load_config(config_path)
    parsed = _validate_config(config, seed)
    _ensure_new_output(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_yaml(output_dir / "resolved_config.yaml", {**config, "seed": seed})

    bfcl_repo = Path(parsed["bfcl_repo"])
    data_root = Path(parsed["bfcl_data_root"])
    bfcl_checkout = verify_bfcl_checkout(bfcl_repo, parsed["bfcl_commit"])
    manifest_path = Path(parsed["manifest_path"])
    manifest = load_bfcl_manifest(manifest_path, data_root)
    if manifest.bfcl_commit != parsed["bfcl_commit"] or manifest.seed != seed:
        msg = "配置、seed 与冻结 BFCL manifest 不一致"
        raise ValueError(msg)
    if manifest.quotas != parsed["quotas"]:
        msg = "配置 quotas 与冻结 BFCL manifest 不一致"
        raise ValueError(msg)
    task_answers = resolve_manifest_task_answers(
        manifest,
        data_root,
        cast(list[str] | None, parsed["task_ids"]),
    )
    _validate_run_scope(task_answers, parsed["task_ids"] is not None)
    categories = tuple(dict.fromkeys(task.id.rsplit("_", 1)[0] for task, _ in task_answers))
    if list(categories) != parsed["official_categories"]:
        msg = "official_eval.categories 与实际运行类别不一致"
        raise ValueError(msg)

    visible_gpu = validate_offline_single_gpu_environment()
    model_evidence = inspect_local_model(Path(parsed["model_name"]))
    code_commit = _git_head(Path.cwd())
    run_manifest = {
        "title": (
            f"Qwen3-1.7B 在 BFCL V4 固定 {len(task_answers)} 条单轮 AST 子集上的"
            "零样本结果"
        ),
        "started_at_utc": started_at,
        "seed": seed,
        "code_commit": code_commit,
        "bfcl_checkout": bfcl_checkout,
        "frozen_manifest_path": str(manifest_path),
        "frozen_manifest_sha256": sha256_file(manifest_path),
        "frozen_manifest": manifest.model_dump(mode="json"),
        "selected_task_ids": [task.id for task, _ in task_answers],
        "model": model_evidence,
        "offline_environment": {
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_OFFLINE": "1",
        },
        "physical_gpu": int(visible_gpu),
        "logical_device": "cuda:0",
        "official_evaluator": {
            "source": str(bfcl_repo),
            "commit": parsed["bfcl_commit"],
            "python": parsed["official_python"],
        },
    }
    write_json(output_dir / "manifest.json", run_manifest)

    import torch

    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        msg = "评测必须看到且只看到一张 CUDA GPU"
        raise RuntimeError(msg)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.cuda.reset_peak_memory_stats()
    properties = torch.cuda.get_device_properties(0)
    generation_started = time.perf_counter()
    backend = TransformersBackend.from_pretrained(parsed["model_name"], None)
    model_loaded_at = time.perf_counter()
    records = generate_bfcl_records(
        task_answers,
        backend,
        max_new_tokens=parsed["max_new_tokens"],
    )
    generation_finished = time.perf_counter()
    peak_allocated = int(torch.cuda.max_memory_allocated())
    peak_reserved = int(torch.cuda.max_memory_reserved())
    write_bfcl_generation_artifacts(
        output_dir,
        parsed["bfcl_model_name"],
        records,
    )
    del backend
    gc.collect()
    torch.cuda.empty_cache()

    evaluator_command, evaluator_output, evaluator_seconds = run_official_evaluator(
        python=Path(parsed["official_python"]),
        evaluator_script=Path("scripts/run_bfcl_official_ast.py"),
        bfcl_repo=bfcl_repo,
        expected_commit=parsed["bfcl_commit"],
        manifest_path=manifest_path,
        task_ids=tuple(cast(list[str] | None, parsed["task_ids"]) or []),
        project_root=Path(parsed["official_project_root"]),
        model_name=parsed["bfcl_model_name"],
        categories=categories,
        result_dir=output_dir / "official_results",
        score_dir=output_dir / "official_scores",
    )
    wall_time_seconds = time.perf_counter() - run_started
    metrics = finalize_bfcl_artifacts(
        output_dir=output_dir,
        model_name=parsed["bfcl_model_name"],
        records=records,
        task_answers=task_answers,
        wall_time_seconds=wall_time_seconds,
        cuda_peak_allocated_bytes=peak_allocated,
        cuda_peak_reserved_bytes=peak_reserved,
    )
    run_manifest.update(
        {
            "completed_at_utc": datetime.now(UTC).isoformat(),
            "gpu": {
                "physical_index": int(visible_gpu),
                "logical_device": "cuda:0",
                "name": properties.name,
                "total_memory_bytes": properties.total_memory,
            },
            "timings_seconds": {
                "model_load": model_loaded_at - generation_started,
                "generation": generation_finished - model_loaded_at,
                "official_evaluator": evaluator_seconds,
                "total": wall_time_seconds,
            },
            "official_evaluator": {
                **cast(dict[str, Any], run_manifest["official_evaluator"]),
                "command": evaluator_command,
                "stdout": evaluator_output,
            },
        }
    )
    write_json(output_dir / "manifest.json", run_manifest)
    (output_dir / "run.log").write_text(
        _render_run_log(run_manifest, metrics),
        encoding="utf-8",
    )
    return metrics


def _validate_config(config: dict[str, Any], seed: int) -> dict[str, Any]:
    if seed != 0:
        msg = "BFCL 固定子集只允许 seed 0"
        raise ValueError(msg)
    expected_scalars = {
        "benchmark": "bfcl_v4_single_turn",
        "bfcl_commit": "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8",
    }
    for field, expected in expected_scalars.items():
        if config.get(field) != expected:
            msg = f"{field} 必须为 {expected}"
            raise ValueError(msg)
    string_fields = ("bfcl_repo", "bfcl_data_root", "manifest_path")
    for field in string_fields:
        value = config.get(field)
        if not isinstance(value, str):
            msg = f"{field} 必须是字符串"
            raise ValueError(msg)
        validate_project_relative_path(value, field)
    quotas = config.get("quotas")
    expected_quotas = dict.fromkeys(BFCL_CATEGORIES, 50)
    if quotas != expected_quotas:
        msg = "quotas 必须精确为四个固定类别各 50 条"
        raise ValueError(msg)
    policy = config.get("policy")
    if not isinstance(policy, dict):
        msg = "policy 必须是 mapping"
        raise ValueError(msg)
    policy_expected = {
        "type": "qwen",
        "model_name": "models/Qwen3-1.7B",
        "bfcl_model_name": "Qwen/Qwen3-1.7B-FC",
        "max_new_tokens": 512,
        "do_sample": False,
        "enable_thinking": False,
        "quantization": "nf4",
        "compute_dtype": "bfloat16",
    }
    for policy_field, policy_expected_value in policy_expected.items():
        if policy.get(policy_field) != policy_expected_value:
            msg = f"policy.{policy_field} 必须为 {policy_expected_value}"
            raise ValueError(msg)
    validate_project_relative_path(cast(str, policy["model_name"]), "policy.model_name")
    official = config.get("official_eval")
    if not isinstance(official, dict):
        msg = "official_eval 必须是 mapping"
        raise ValueError(msg)
    for field in ("python", "project_root"):
        value = official.get(field)
        if not isinstance(value, str):
            msg = f"official_eval.{field} 必须是字符串"
            raise ValueError(msg)
        validate_project_relative_path(value, f"official_eval.{field}")
    categories = official.get("categories")
    if not isinstance(categories, list) or not all(
        isinstance(category, str) for category in categories
    ):
        msg = "official_eval.categories 必须是类别列表"
        raise ValueError(msg)
    task_ids = config.get("task_ids")
    if task_ids is not None and (
        not isinstance(task_ids, list)
        or not task_ids
        or not all(isinstance(task_id, str) for task_id in task_ids)
    ):
        msg = "task_ids 必须是非空字符串列表"
        raise ValueError(msg)
    return {
        "bfcl_repo": cast(str, config["bfcl_repo"]),
        "bfcl_data_root": cast(str, config["bfcl_data_root"]),
        "bfcl_commit": cast(str, config["bfcl_commit"]),
        "manifest_path": cast(str, config["manifest_path"]),
        "quotas": cast(dict[str, int], quotas),
        "task_ids": cast(list[str] | None, task_ids),
        "model_name": cast(str, policy["model_name"]),
        "bfcl_model_name": cast(str, policy["bfcl_model_name"]),
        "max_new_tokens": cast(int, policy["max_new_tokens"]),
        "official_python": cast(str, official["python"]),
        "official_project_root": cast(str, official["project_root"]),
        "official_categories": cast(list[str], categories),
    }


def _validate_run_scope(
    task_answers: list[tuple[Any, Any]],
    is_smoke: bool,
) -> None:
    ids = [task.id for task, _ in task_answers]
    if is_smoke:
        if len(ids) != 1 or not ids[0].startswith("simple_python_"):
            msg = "smoke 必须只包含 manifest 中一条 simple_python 任务"
            raise ValueError(msg)
        return
    counts = {category: 0 for category in BFCL_CATEGORIES}
    for task_id in ids:
        counts[task_id.rsplit("_", 1)[0]] += 1
    if len(ids) != 200 or counts != dict.fromkeys(BFCL_CATEGORIES, 50):
        msg = "正式 BFCL baseline 必须恰好 200 条且四类各 50 条"
        raise ValueError(msg)


def _ensure_new_output(output_dir: Path) -> None:
    protected = (
        "raw_generations.jsonl",
        "metrics.json",
        "manifest.json",
        "official_results",
        "official_scores",
    )
    existing = [name for name in protected if (output_dir / name).exists()]
    if existing:
        msg = f"输出目录包含既有 BFCL 正式产物，拒绝覆盖: {existing}"
        raise FileExistsError(msg)


def _git_head(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _render_run_log(manifest: dict[str, Any], metrics: dict[str, Any]) -> str:
    command = shlex.join(sys.argv)
    evaluator = cast(dict[str, Any], manifest["official_evaluator"])
    timings = cast(dict[str, float], manifest["timings_seconds"])
    return "\n".join(
        [
            f"command: {command}",
            f"physical_gpu: {manifest['physical_gpu']}",
            "logical_device: cuda:0",
            "offline: TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1",
            f"bfcl_commit: {manifest['bfcl_checkout']['commit']}",
            f"official_command: {shlex.join(evaluator['command'])}",
            f"model_load_seconds: {timings['model_load']:.6f}",
            f"generation_seconds: {timings['generation']:.6f}",
            f"official_evaluator_seconds: {timings['official_evaluator']:.6f}",
            f"total_seconds: {timings['total']:.6f}",
            f"official_correct: {metrics['official_correct_count']}",
            f"official_error: {metrics['official_error_count']}",
            "official_evaluator_stdout:",
            cast(str, evaluator["stdout"]),
            "",
        ]
    )


def main() -> None:
    """CLI 入口。"""
    args = build_arg_parser("BFCL V4 固定单轮子集零样本评测").parse_args()
    run_bfcl_evaluation(args.config, args.seed, args.output_dir)


if __name__ == "__main__":
    main()
