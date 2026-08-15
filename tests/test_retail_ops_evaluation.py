"""RetailOps 评测证据、重放完整性与公开脱敏测试。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from veritool_rl.core.trajectory import Trajectory


def _latency_trajectories(values: list[float]) -> list[Trajectory]:
    from typing import Any

    from veritool_rl.core.agent.policy import PolicyOutput
    from veritool_rl.core.agent.runner import run_episode
    from veritool_rl.core.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits

    class TimedFinalPolicy:
        name = "timed-final"

        def __init__(self, latency_ms: float) -> None:
            self._latency_ms = latency_ms

        def respond(self, messages: list[dict[str, Any]], tools: list[Any]) -> PolicyOutput:
            del messages, tools
            return PolicyOutput(
                raw_text="无法处理",
                final_response="无法处理",
                latency_ms=self._latency_ms,
            )

    tasks = build_mvp_task_splits(seed=0)["test"][: len(values)]
    return [
        run_episode(task, MiniRetailEnv, TimedFinalPolicy(value), seed=0)
        for task, value in zip(tasks, values, strict=True)
    ]


def _evaluate(tmp_path: Path, policy_type: str, suffix: str = ""):
    from veritool_rl.retail_ops.build.manifests import build_qualification
    from veritool_rl.retail_ops.evaluate.evaluation import (
        EvaluationMode,
        RunEvidence,
        evaluate_retail_ops,
    )

    build_dir = tmp_path / f"build{suffix}"
    build_qualification(Path("domains/retail_ops/v1"), 0, build_dir)
    evidence = evaluate_retail_ops(
        bundle_dir=Path("domains/retail_ops/v1"),
        build_dir=build_dir,
        policy_type=policy_type,
        config={
            "bootstrap_samples": 1000,
            "parser_id": "hermes-single-call-v1",
            "budget": {"max_steps": 5},
            "perturb_schema": False,
        },
        seed=0,
        output_dir=tmp_path / f"{policy_type}{suffix}",
        mode=EvaluationMode.QUALIFICATION,
    )
    assert isinstance(evidence, RunEvidence)
    return evidence, build_dir, tmp_path / f"{policy_type}{suffix}"


def _rewrite_build_as_development(build_dir: Path) -> None:
    from veritool_rl.core.artifacts import canonical_json, sha256_file, write_json, write_jsonl

    tasks_path = build_dir / "tasks.jsonl"
    manifest_path = build_dir / "manifest.json"
    rows = [
        json.loads(line)
        for line in tasks_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for row in rows:
        row["split"] = "dev"
    write_jsonl(tasks_path, rows)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["split"] = "dev"
    manifest["task_sha256"] = {
        str(row["task_id"]): hashlib.sha256(canonical_json(row).encode("utf-8")).hexdigest()
        for row in rows
    }
    manifest["tasks_file_sha256"] = sha256_file(tasks_path)
    write_json(manifest_path, manifest)


def test_metrics_report_episode_latency_percentiles() -> None:
    from veritool_rl.core.metrics import compute_metrics

    metrics = compute_metrics(_latency_trajectories([10.0, 20.0, 40.0]), 20, 0)

    assert metrics["p50_latency_ms"] == 20.0
    assert metrics["p95_latency_ms"] == pytest.approx(38.0)


def test_qualification_evidence_is_complete_replayable_and_hash_bound(
    tmp_path: Path,
) -> None:
    from veritool_rl.core.artifacts import sha256_file
    from veritool_rl.retail_ops.evaluate.evaluation import load_run_evidence

    evidence, build_dir, output_dir = _evaluate(tmp_path, policy_type="oracle")

    assert evidence.task_count == 12
    assert evidence.evidence_complete is True
    assert evidence.metrics["task_success"] == 1.0
    assert evidence.metrics["replayable_count"] == 12
    assert evidence.metrics["replayable_rate"] == 1.0
    assert evidence.task_manifest_sha256 == sha256_file(build_dir / "manifest.json")
    assert set(evidence.artifact_sha256) == {
        "config.yaml",
        "trajectories.jsonl",
        "metrics.json",
        "failures.jsonl",
        "log.txt",
    }
    assert {path.name for path in output_dir.iterdir()} == {
        *evidence.artifact_sha256,
        "run.json",
    }
    assert load_run_evidence(output_dir / "run.json") == evidence


def test_identical_qualification_runs_write_identical_evidence(tmp_path: Path) -> None:
    first, _, first_dir = _evaluate(tmp_path, "baseline", suffix="-first")
    second, _, second_dir = _evaluate(tmp_path, "baseline", suffix="-second")

    assert first == second
    for name in (*first.artifact_sha256, "run.json"):
        assert (first_dir / name).read_bytes() == (second_dir / name).read_bytes()


def test_development_mode_runs_dev_manifest_with_same_reference_policy(
    tmp_path: Path,
) -> None:
    from veritool_rl.retail_ops.build.manifests import build_qualification
    from veritool_rl.retail_ops.evaluate.evaluation import EvaluationMode, evaluate_retail_ops

    build_dir = tmp_path / "build"
    build_qualification(Path("domains/retail_ops/v1"), 0, build_dir)
    _rewrite_build_as_development(build_dir)

    evidence = evaluate_retail_ops(
        Path("domains/retail_ops/v1"),
        build_dir,
        "oracle",
        {
            "bootstrap_samples": 20,
            "parser_id": "p",
            "budget": {"max_steps": 5},
            "perturb_schema": False,
        },
        0,
        tmp_path / "dev-evidence",
        EvaluationMode.DEVELOPMENT,
    )

    assert evidence.mode is EvaluationMode.DEVELOPMENT
    assert evidence.metrics["task_success"] == 1.0


def test_evaluation_rejects_manifest_category_coverage_tamper(tmp_path: Path) -> None:
    from veritool_rl.core.artifacts import write_json
    from veritool_rl.retail_ops.build.manifests import build_qualification
    from veritool_rl.retail_ops.evaluate.evaluation import EvaluationMode, evaluate_retail_ops

    build_dir = tmp_path / "build"
    manifest = build_qualification(Path("domains/retail_ops/v1"), 0, build_dir)
    write_json(
        build_dir / "manifest.json",
        manifest.model_copy(update={"category_counts": {"lookup_status": 12}}).model_dump(
            mode="json"
        ),
    )

    with pytest.raises(ValueError, match="类别覆盖与 manifest 不一致"):
        evaluate_retail_ops(
            Path("domains/retail_ops/v1"),
            build_dir,
            "oracle",
            {"bootstrap_samples": 20, "parser_id": "p", "budget": {}, "perturb_schema": False},
            0,
            tmp_path / "evidence",
            EvaluationMode.QUALIFICATION,
        )


def test_redacted_failures_use_allowlist_and_exclude_nested_truth() -> None:
    from veritool_rl.core.agent.runner import run_episode
    from veritool_rl.core.artifacts import canonical_json
    from veritool_rl.retail_ops.domain.bundle import load_bundle
    from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
    from veritool_rl.retail_ops.domain.policies import UnknownToolPolicy
    from veritool_rl.retail_ops.domain.tasks import build_qualification_tasks
    from veritool_rl.retail_ops.evaluate.evaluation import redact_failure_rows

    bundle = load_bundle(Path("domains/retail_ops/v1"))
    task = build_qualification_tasks(seed=0)[0]
    trajectory = run_episode(
        task,
        lambda current: RetailOpsEnv(current, bundle),
        UnknownToolPolicy(),
        seed=0,
    ).model_copy(
        deep=True,
        update={
            "metadata": {
                "nested": {
                    "Target_State": {"secret": True},
                    "EXPECTED_CALLS": ["secret"],
                    "userRequest": "secret",
                }
            }
        },
    )

    rows = redact_failure_rows([trajectory])
    public_text = canonical_json(rows)

    assert len(rows) == 1
    assert set(rows[0]) == {
        "category",
        "failure_type",
        "last_error",
        "termination",
        "violations",
    }
    assert rows[0]["failure_type"] == "tool_selection"
    for forbidden in (
        "target_state",
        "Target_State",
        "expected_calls",
        "EXPECTED_CALLS",
        "user_request",
        "userRequest",
        "task_id",
        task.task_id,
    ):
        assert forbidden not in public_text


def test_evaluation_rejects_holdout_before_policy_execution(tmp_path: Path) -> None:
    from veritool_rl.core.artifacts import write_json
    from veritool_rl.retail_ops.build.manifests import build_qualification
    from veritool_rl.retail_ops.evaluate.evaluation import EvaluationMode, evaluate_retail_ops

    build_dir = tmp_path / "build"
    manifest = build_qualification(Path("domains/retail_ops/v1"), 0, build_dir)
    write_json(
        build_dir / "manifest.json",
        manifest.model_copy(update={"split": "holdout"}).model_dump(mode="json"),
    )

    with pytest.raises(PermissionError, match="holdout"):
        evaluate_retail_ops(
            Path("domains/retail_ops/v1"),
            build_dir,
            "unsupported-policy-must-not-run",
            {"bootstrap_samples": 10, "parser_id": "p", "budget": {}, "perturb_schema": False},
            0,
            tmp_path / "evidence",
            EvaluationMode.QUALIFICATION,
        )
    assert not (tmp_path / "evidence").exists()


def test_evaluation_rejects_manifest_bundle_mismatch(tmp_path: Path) -> None:
    from veritool_rl.core.artifacts import write_json
    from veritool_rl.retail_ops.build.manifests import build_qualification
    from veritool_rl.retail_ops.evaluate.evaluation import EvaluationMode, evaluate_retail_ops

    build_dir = tmp_path / "build"
    manifest = build_qualification(Path("domains/retail_ops/v1"), 0, build_dir)
    write_json(
        build_dir / "manifest.json",
        manifest.model_copy(update={"bundle_sha256": "0" * 64}).model_dump(mode="json"),
    )

    with pytest.raises(ValueError, match="bundle SHA-256 不匹配"):
        evaluate_retail_ops(
            Path("domains/retail_ops/v1"),
            build_dir,
            "oracle",
            {"bootstrap_samples": 10, "parser_id": "p", "budget": {}, "perturb_schema": False},
            0,
            tmp_path / "evidence",
            EvaluationMode.QUALIFICATION,
        )


def test_evaluation_refuses_to_overwrite_run_and_loader_detects_tamper(
    tmp_path: Path,
) -> None:
    from veritool_rl.retail_ops.evaluate.evaluation import (
        EvaluationMode,
        evaluate_retail_ops,
        load_run_evidence,
    )

    evidence, build_dir, output_dir = _evaluate(tmp_path, "baseline")
    with pytest.raises(FileExistsError, match="输出目录已存在"):
        evaluate_retail_ops(
            Path("domains/retail_ops/v1"),
            build_dir,
            "baseline",
            {
                "bootstrap_samples": 1000,
                "parser_id": evidence.parser_id,
                "budget": evidence.budget,
                "perturb_schema": False,
            },
            0,
            output_dir,
            EvaluationMode.QUALIFICATION,
        )

    metrics_path = output_dir / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics["task_success"] = 0.0
    metrics_path.write_text(json.dumps(metrics) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="评测证据 SHA-256 不匹配: metrics.json"):
        load_run_evidence(output_dir / "run.json")
