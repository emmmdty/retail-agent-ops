"""构建并验证 BFCL V4 QLoRA-SFT train/dev 数据。"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

import numpy as np

from veritool_rl.cli import build_arg_parser, load_config
from veritool_rl.core.artifacts import sha256_file, write_json, write_jsonl, write_yaml
from veritool_rl.core.paths import validate_project_relative_path
from veritool_rl.legacy.data.bfcl import BFCL_CATEGORIES
from veritool_rl.legacy.data.bfcl_sft import (
    BfclSftManifest,
    BfclTokenizedSftExample,
    build_bfcl_sft_manifest,
    resolve_bfcl_sft_task_answers,
    tokenize_bfcl_sft_example,
)
from veritool_rl.legacy.eval.bfcl import load_official_scores

EXPECTED_BFCL_COMMIT = "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8"
EXPECTED_MODEL_NAME = "Qwen/Qwen3-1.7B-FC"


def build_bfcl_sft_data(
    config_path: Path,
    seed: int,
    output_dir: Path,
) -> dict[str, Any]:
    """构造 720/80 数据，完成 token 与官方 AST 审计并写出 provenance。"""
    config = load_config(config_path)
    parsed = _validate_config(config, seed)
    _ensure_new_output(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_yaml(output_dir / "resolved_config.yaml", {**config, "seed": seed})

    data_root = Path(parsed["bfcl_data_root"])
    holdout_manifest_path = Path(parsed["holdout_manifest_path"])
    split_manifest_path = Path(parsed["split_manifest_path"])
    manifest = build_bfcl_sft_manifest(data_root, holdout_manifest_path)
    if manifest.bfcl_commit != parsed["bfcl_commit"]:
        msg = "SFT split manifest 与配置 BFCL commit 不一致"
        raise ValueError(msg)
    write_json(split_manifest_path, manifest.model_dump(mode="json"))

    tokenizer = _load_tokenizer(Path(parsed["model_name"]))
    examples_by_split: dict[str, list[BfclTokenizedSftExample]] = {}
    for split in ("train", "dev"):
        pairs = resolve_bfcl_sft_task_answers(
            manifest,
            data_root,
            cast(Any, split),
        )
        examples = [
            tokenize_bfcl_sft_example(
                task,
                answer,
                tokenizer,
                max_seq_len=parsed["max_seq_len"],
            )
            for task, answer in pairs
        ]
        examples_by_split[split] = examples
        write_jsonl(
            output_dir / f"{split}.jsonl",
            (example.model_dump(mode="json") for example in examples),
        )

    all_examples = [*examples_by_split["train"], *examples_by_split["dev"]]
    target_validation = _run_official_target_validation(
        examples=all_examples,
        python=Path(parsed["official_python"]),
        bfcl_repo=Path(parsed["bfcl_repo"]),
        expected_commit=parsed["bfcl_commit"],
        manifest_path=split_manifest_path,
        model_name=parsed["official_model_name"],
        output_dir=output_dir / "official_target_validation",
    )
    audit = _build_audit(
        manifest=manifest,
        split_manifest_path=split_manifest_path,
        examples_by_split=examples_by_split,
        target_validation=target_validation,
        max_seq_len=parsed["max_seq_len"],
        output_dir=output_dir,
    )
    write_json(output_dir / "audit.json", audit)
    write_json(Path(parsed["audit_report_path"]), audit)
    (output_dir / "run.log").write_text(
        "\n".join(
            [
                f"command: {shlex.join(sys.argv)}",
                f"split_manifest_sha256: {audit['split_manifest_sha256']}",
                "official_target_validation: "
                f"{target_validation['correct_count']}/{target_validation['checked_count']}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return audit


def _validate_config(config: dict[str, Any], seed: int) -> dict[str, Any]:
    if seed != 0:
        raise ValueError("BFCL SFT 数据冻结只允许 seed 0")
    if config.get("benchmark") != "bfcl_v4_sft":
        raise ValueError("benchmark 必须为 bfcl_v4_sft")
    if config.get("bfcl_commit") != EXPECTED_BFCL_COMMIT:
        raise ValueError(f"bfcl_commit 必须为 {EXPECTED_BFCL_COMMIT}")
    path_fields = (
        "bfcl_repo",
        "bfcl_data_root",
        "holdout_manifest_path",
        "split_manifest_path",
        "audit_report_path",
    )
    parsed: dict[str, Any] = {"bfcl_commit": EXPECTED_BFCL_COMMIT}
    for field in path_fields:
        value = config.get(field)
        if not isinstance(value, str):
            raise ValueError(f"{field} 必须是路径字符串")
        validate_project_relative_path(value, field)
        parsed[field] = value
    model = config.get("model")
    if not isinstance(model, dict):
        raise ValueError("model 必须是 mapping")
    model_name = model.get("name")
    max_seq_len = model.get("max_seq_len")
    if not isinstance(model_name, str):
        raise ValueError("model.name 必须是路径字符串")
    validate_project_relative_path(model_name, "model.name")
    if not isinstance(max_seq_len, int) or isinstance(max_seq_len, bool) or max_seq_len < 1:
        raise ValueError("model.max_seq_len 必须是正整数")
    parsed["model_name"] = model_name
    parsed["max_seq_len"] = max_seq_len
    official = config.get("official_eval")
    if not isinstance(official, dict):
        raise ValueError("official_eval 必须是 mapping")
    official_python = official.get("python")
    official_model_name = official.get("model_name")
    if not isinstance(official_python, str):
        raise ValueError("official_eval.python 必须是路径字符串")
    validate_project_relative_path(official_python, "official_eval.python")
    if official_model_name != EXPECTED_MODEL_NAME:
        raise ValueError(f"official_eval.model_name 必须为 {EXPECTED_MODEL_NAME}")
    parsed["official_python"] = official_python
    parsed["official_model_name"] = official_model_name
    return parsed


def _load_tokenizer(model_path: Path) -> Any:
    if not model_path.is_dir():
        raise FileNotFoundError(model_path)
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(model_path, local_files_only=True)


def _run_official_target_validation(
    *,
    examples: list[BfclTokenizedSftExample],
    python: Path,
    bfcl_repo: Path,
    expected_commit: str,
    manifest_path: Path,
    model_name: str,
    output_dir: Path,
) -> dict[str, Any]:
    if not python.is_file():
        raise FileNotFoundError(python)
    expected_by_category = {
        category: [example.task_id for example in examples if example.category == category]
        for category in BFCL_CATEGORIES
    }
    result_root = output_dir / "results"
    result_dir = result_root / model_name.replace("/", "_") / "non_live"
    for category, expected_ids in expected_by_category.items():
        rows_by_id = {
            example.task_id: {"id": example.task_id, "result": example.target_text}
            for example in examples
            if example.category == category
        }
        write_jsonl(
            result_dir / f"BFCL_v4_{category}_result.json",
            (rows_by_id[task_id] for task_id in expected_ids),
        )
    score_root = output_dir / "scores"
    command = [
        str(python.resolve()),
        str(Path("scripts/legacy/bfcl/run_bfcl_official_ast.py").resolve()),
        "--bfcl-repo",
        str(bfcl_repo.resolve()),
        "--expected-commit",
        expected_commit,
        "--manifest",
        str(manifest_path.resolve()),
        "--model",
        model_name,
        "--test-category",
        *BFCL_CATEGORIES,
        "--result-dir",
        str(result_root.resolve()),
        "--score-dir",
        str(score_root.resolve()),
    ]
    started = time.perf_counter()
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    elapsed = time.perf_counter() - started
    if completed.returncode != 0:
        msg = f"BFCL SFT target 官方 AST 进程失败:\n{completed.stderr}"
        raise RuntimeError(msg)
    scores = load_official_scores(score_root, model_name, expected_by_category)
    checked_count = sum(score.total_count for score in scores.values())
    correct_count = sum(score.correct_count for score in scores.values())
    if checked_count != 800 or correct_count != checked_count:
        failure = _first_official_failure(score_root, model_name)
        msg = (
            "BFCL SFT target 未通过固定官方 AST checker: "
            f"task_id={failure.get('id')}, input={failure.get('prompt')}, "
            f"target={failure.get('model_result_raw')}, "
            f"official_error={failure.get('error')}"
        )
        raise RuntimeError(msg)
    checker_path = bfcl_repo / "bfcl_eval/eval_checker/ast_eval/ast_checker.py"
    return {
        "checked_count": checked_count,
        "correct_count": correct_count,
        "accuracy": correct_count / checked_count,
        "checker_sha256": sha256_file(checker_path),
        "wall_time_seconds": elapsed,
        "command": command,
        "stdout": completed.stdout,
    }


def _first_official_failure(score_root: Path, model_name: str) -> dict[str, Any]:
    score_dir = score_root / model_name.replace("/", "_") / "non_live"
    for category in BFCL_CATEGORIES:
        path = score_dir / f"BFCL_v4_{category}_score.json"
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > 1:
            loaded = json.loads(lines[1])
            if isinstance(loaded, dict):
                return cast(dict[str, Any], loaded)
    return {}


def _build_audit(
    *,
    manifest: BfclSftManifest,
    split_manifest_path: Path,
    examples_by_split: dict[str, list[BfclTokenizedSftExample]],
    target_validation: dict[str, Any],
    max_seq_len: int,
    output_dir: Path,
) -> dict[str, Any]:
    all_examples = [*examples_by_split["train"], *examples_by_split["dev"]]
    return {
        "bfcl_commit": manifest.bfcl_commit,
        "holdout_manifest_sha256": manifest.holdout_manifest_sha256,
        "split_manifest_sha256": sha256_file(split_manifest_path),
        "split_counts": {
            "train": len(manifest.splits.train),
            "dev": len(manifest.splits.dev),
            "holdout": len(manifest.splits.holdout),
        },
        "max_seq_len": max_seq_len,
        "token_lengths": {
            "prompt": _length_summary([example.prompt_token_count for example in all_examples]),
            "target": _length_summary([example.target_token_count for example in all_examples]),
            "full": _length_summary([example.full_token_count for example in all_examples]),
        },
        "truncation_count": sum(example.full_token_count > max_seq_len for example in all_examples),
        "target_validation": target_validation,
        "data_sha256": {
            split: sha256_file(output_dir / f"{split}.jsonl") for split in ("train", "dev")
        },
    }


def _length_summary(values: list[int]) -> dict[str, float | int]:
    if not values:
        raise ValueError("token 长度审计不能为空")
    array = np.asarray(values, dtype=np.int64)
    return {
        "min": int(array.min()),
        "p50": float(np.quantile(array, 0.50)),
        "p90": float(np.quantile(array, 0.90)),
        "p95": float(np.quantile(array, 0.95)),
        "p99": float(np.quantile(array, 0.99)),
        "max": int(array.max()),
    }


def _ensure_new_output(output_dir: Path) -> None:
    protected = ("train.jsonl", "dev.jsonl", "audit.json")
    existing = [name for name in protected if (output_dir / name).exists()]
    if existing:
        raise FileExistsError(f"BFCL SFT 数据输出目录包含既有产物: {existing}")


def main() -> None:
    """CLI 入口。"""
    args = build_arg_parser("构建 BFCL V4 QLoRA-SFT 数据").parse_args()
    build_bfcl_sft_data(args.config, args.seed, args.output_dir)


if __name__ == "__main__":
    main()
