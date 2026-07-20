"""BFCL base/SFT 官方结果严格配对与 bootstrap 测试。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

MODEL_DIR = "Qwen_Qwen3-1.7B-FC/non_live"
CATEGORIES = ("simple_python", "multiple", "parallel", "parallel_multiple")


def _load_manifest() -> dict[str, Any]:
    return json.loads(
        Path("manifests/bfcl_v4_single_turn_seed0.json").read_text(encoding="utf-8")
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _prepare_run(
    root: Path,
    *,
    failure_id: str,
    adapter: bool,
) -> None:
    manifest = _load_manifest()
    task_ids = [item["task_id"] for item in manifest["tasks"]]
    _write_jsonl(
        root / "raw_generations.jsonl",
        [
            {
                "task_id": task_id,
                "category": task_id.rsplit("_", 1)[0],
                "raw_output": f"output for {task_id}",
            }
            for task_id in task_ids
        ],
    )
    for category in CATEGORIES:
        ids = [
            item["task_id"]
            for item in manifest["tasks"]
            if item["category"] == category
        ]
        failures = [task_id for task_id in ids if task_id == failure_id]
        rows = [
            {
                "accuracy": (len(ids) - len(failures)) / len(ids),
                "correct_count": len(ids) - len(failures),
                "total_count": len(ids),
            },
            *[
                {
                    "id": task_id,
                    "valid": False,
                    "error_type": "value_error:others",
                    "error": ["wrong value"],
                }
                for task_id in failures
            ],
        ]
        _write_jsonl(
            root
            / "official_scores"
            / MODEL_DIR
            / f"BFCL_v4_{category}_score.json",
            rows,
        )
    _write_jsonl(
        root / "failures.jsonl",
        [
            {
                "task_id": failure_id,
                "raw_model_output": f"output for {failure_id}",
                "official_error_type": "value_error:others",
                "official_error": ["wrong value"],
                "root_cause": "参数值错误",
                "user_question": [{"role": "user", "content": "question"}],
                "function_schema": [{"name": "lookup"}],
                "expected_calls": [{"lookup": {"value": [1]}}],
            }
        ],
    )
    metrics = {
        "task_count": 200,
        "official_correct_count": 199,
        "official_error_count": 1,
        "official_ast_accuracy": 0.995,
    }
    (root / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    manifest_path = Path("manifests/bfcl_v4_single_turn_seed0.json")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "seed": 0,
                "bfcl_checkout": {"commit": manifest["bfcl_commit"]},
                "frozen_manifest": manifest,
                "frozen_manifest_sha256": hashlib.sha256(
                    manifest_path.read_bytes()
                ).hexdigest(),
                "selected_task_ids": task_ids,
                "official_evaluator": {"commit": manifest["bfcl_commit"]},
            }
        ),
        encoding="utf-8",
    )
    config = yaml.safe_load(
        Path("configs/bfcl_v4_single_turn_seed0.yaml").read_text(encoding="utf-8")
    )
    if adapter:
        config["policy"]["adapter_path"] = (
            "reports/bfcl/qwen3-1.7b-sft-seed0/training/adapter"
        )
        config["official_eval"]["project_root"] = "data/bfcl_eval_runtime/sft"
    config["seed"] = 0
    (root / "resolved_config.yaml").write_text(
        yaml.safe_dump(config),
        encoding="utf-8",
    )


def test_aggregate_bfcl_runs_pairs_exact_ids_and_repeats_bootstrap(
    tmp_path: Path,
) -> None:
    from veritool_rl.eval.bfcl_compare import aggregate_bfcl_runs

    manifest = _load_manifest()
    base_failure = manifest["tasks"][0]["task_id"]
    sft_failure = manifest["tasks"][1]["task_id"]
    baseline_dir = tmp_path / "base"
    sft_dir = tmp_path / "sft"
    _prepare_run(baseline_dir, failure_id=base_failure, adapter=False)
    _prepare_run(sft_dir, failure_id=sft_failure, adapter=True)

    first = aggregate_bfcl_runs(
        baseline_dir=baseline_dir,
        sft_dir=sft_dir,
        manifest_path=Path("manifests/bfcl_v4_single_turn_seed0.json"),
        output_dir=tmp_path / "comparison",
        bootstrap_samples=10_000,
        seed=0,
        benchmark_sensitive_ids={
            "multiple_151",
            "simple_python_267",
            "simple_python_354",
            "parallel_166",
        },
    )
    second = aggregate_bfcl_runs(
        baseline_dir=baseline_dir,
        sft_dir=sft_dir,
        manifest_path=Path("manifests/bfcl_v4_single_turn_seed0.json"),
        output_dir=tmp_path / "comparison-2",
        bootstrap_samples=10_000,
        seed=0,
        benchmark_sensitive_ids=set(),
    )

    assert first["paired_tasks"] == 200
    assert first["outcomes"] == {"improved": 1, "regressed": 1, "unchanged": 198}
    assert first["success_delta"] == 0.0
    assert first["paired_success_delta_ci95"] == second["paired_success_delta_ci95"]
    comparison_rows = [
        json.loads(line)
        for line in (tmp_path / "comparison/comparison.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(comparison_rows) == 200
    assert {row["task_id"] for row in comparison_rows} == {
        item["task_id"] for item in manifest["tasks"]
    }
    analysis_rows = [
        json.loads(line)
        for line in (tmp_path / "comparison/comparison_analysis.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert {row["task_id"] for row in analysis_rows} == {
        base_failure,
        sft_failure,
    }


def test_aggregate_bfcl_runs_rejects_missing_or_extra_raw_id(tmp_path: Path) -> None:
    from veritool_rl.eval.bfcl_compare import aggregate_bfcl_runs

    manifest = _load_manifest()
    baseline_dir = tmp_path / "base"
    sft_dir = tmp_path / "sft"
    _prepare_run(
        baseline_dir,
        failure_id=manifest["tasks"][0]["task_id"],
        adapter=False,
    )
    _prepare_run(
        sft_dir,
        failure_id=manifest["tasks"][1]["task_id"],
        adapter=True,
    )
    lines = (sft_dir / "raw_generations.jsonl").read_text(encoding="utf-8").splitlines()
    (sft_dir / "raw_generations.jsonl").write_text(
        "\n".join(lines[:-1]) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="缺失 task_id"):
        aggregate_bfcl_runs(
            baseline_dir=baseline_dir,
            sft_dir=sft_dir,
            manifest_path=Path("manifests/bfcl_v4_single_turn_seed0.json"),
            output_dir=tmp_path / "comparison",
            bootstrap_samples=10_000,
            seed=0,
            benchmark_sensitive_ids=set(),
        )


def test_aggregate_bfcl_runs_rejects_manifest_changed_after_evaluation(
    tmp_path: Path,
) -> None:
    from veritool_rl.eval.bfcl_compare import aggregate_bfcl_runs

    manifest = _load_manifest()
    baseline_dir = tmp_path / "base"
    sft_dir = tmp_path / "sft"
    _prepare_run(
        baseline_dir,
        failure_id=manifest["tasks"][0]["task_id"],
        adapter=False,
    )
    _prepare_run(
        sft_dir,
        failure_id=manifest["tasks"][1]["task_id"],
        adapter=True,
    )
    manifest["tasks"][0]["selection_sha256"] = "0" * 64
    tampered_manifest = tmp_path / "tampered-manifest.json"
    tampered_manifest.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="manifest.*哈希"):
        aggregate_bfcl_runs(
            baseline_dir=baseline_dir,
            sft_dir=sft_dir,
            manifest_path=tampered_manifest,
            output_dir=tmp_path / "comparison",
            bootstrap_samples=10_000,
            seed=0,
            benchmark_sensitive_ids=set(),
        )


def test_aggregate_bfcl_runs_requires_embedded_frozen_manifest(
    tmp_path: Path,
) -> None:
    from veritool_rl.eval.bfcl_compare import aggregate_bfcl_runs

    manifest = _load_manifest()
    baseline_dir = tmp_path / "base"
    sft_dir = tmp_path / "sft"
    _prepare_run(
        baseline_dir,
        failure_id=manifest["tasks"][0]["task_id"],
        adapter=False,
    )
    _prepare_run(
        sft_dir,
        failure_id=manifest["tasks"][1]["task_id"],
        adapter=True,
    )
    run_manifest_path = baseline_dir / "manifest.json"
    run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
    del run_manifest["frozen_manifest"]
    run_manifest_path.write_text(json.dumps(run_manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="内嵌冻结 manifest"):
        aggregate_bfcl_runs(
            baseline_dir=baseline_dir,
            sft_dir=sft_dir,
            manifest_path=Path("manifests/bfcl_v4_single_turn_seed0.json"),
            output_dir=tmp_path / "comparison",
            bootstrap_samples=10_000,
            seed=0,
            benchmark_sensitive_ids=set(),
        )
