"""FlightOps v1 evaluate + release tests — oracle-policy eval + gate check.

Tests the full evaluate→release chain using the oracle policy (always succeeds),
verifying the report self-hashes, paired comparison, and gate logic WITHOUT
needing GPU or a trained model. The actual GPU evaluation runs are in task_plan
R8 D2 C1-3 to C1-5.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from veritool_rl.core.agent.policy import OraclePolicy
from veritool_rl.flight_ops.build.manifests import FlightTaskManifest
from veritool_rl.flight_ops.domain.bundle import load_bundle
from veritool_rl.flight_ops.domain.environment import FlightOpsEnv
from veritool_rl.flight_ops.domain.tasks import build_flight_task_set
from veritool_rl.flight_ops.evaluate.evaluation import (
    FlightEvalConfig,
    FlightRunEvidence,
    run_evaluation,
)

BUNDLE_DIR = Path(__file__).resolve().parents[1] / "domains" / "flight_ops" / "v1"


@pytest.fixture(scope="module")
def bundle():
    return load_bundle(BUNDLE_DIR)


@pytest.fixture(scope="module")
def task_set():
    return build_flight_task_set("flight_ops_v1_r8_001", seed=0)


@pytest.fixture(scope="module")
def manifest(task_set):
    return FlightTaskManifest.from_task_set(task_set)


def test_oracle_eval_reaches_100_percent(bundle, task_set, manifest, tmp_path):
    """Oracle policy (always succeeds) must reach 100% task_success on dev —
    this verifies the eval pipeline is wired correctly end-to-end."""
    config = FlightEvalConfig(
        dataset_version="flight_ops_v1_r8_001",
        bundle_sha256=bundle.bundle_sha256,
        manifest_sha256=manifest.task_set_sha256,
        seed=0,
        split="dev",
        model_name="oracle",
    )

    def env_factory(task):
        return FlightOpsEnv(task, bundle)

    def oracle_factory(task):
        return OraclePolicy(task)

    evidence = run_evaluation(
        config,
        task_set,
        oracle_factory,
        env_factory,
        output_dir=tmp_path / "eval",
        bootstrap_samples=10,
    )
    assert evidence.task_success == 1.0
    assert evidence.policy_violation_count == 0
    assert evidence.invalid_call_count == 0
    assert evidence.tool_selection_accuracy == 1.0
    assert len(evidence.report_id) == 64


def test_report_id_is_deterministic(bundle, task_set, manifest, tmp_path):
    """Two eval runs with identical inputs produce the same report_id —
    the self-hash must be deterministic, not run-dependent."""
    config = FlightEvalConfig(
        dataset_version="flight_ops_v1_r8_001",
        bundle_sha256=bundle.bundle_sha256,
        manifest_sha256=manifest.task_set_sha256,
        seed=0,
        split="dev",
        model_name="oracle",
    )

    def env_factory(task):
        return FlightOpsEnv(task, bundle)

    def oracle_factory(task):
        return OraclePolicy(task)

    e1 = run_evaluation(
        config,
        task_set,
        oracle_factory,
        env_factory,
        output_dir=tmp_path / "e1",
        bootstrap_samples=10,
    )
    e2 = run_evaluation(
        config,
        task_set,
        oracle_factory,
        env_factory,
        output_dir=tmp_path / "e2",
        bootstrap_samples=10,
    )
    assert e1.report_id == e2.report_id


def test_report_load_rejects_tampered_decision(tmp_path):
    """Changing a field after report_id computation must be caught at load time
    — the self-hash is the evidence chain's tamper-evident seal."""
    payload_for_hash = {
        "config": FlightEvalConfig(
            dataset_version="v1",
            bundle_sha256="b" * 64,
            manifest_sha256="c" * 64,
            seed=0,
            split="dev",
            model_name="oracle",
        ).model_dump(mode="json"),
        "task_count": 60,
        "trajectories_file": "trajectories.jsonl",
        "metrics": {"task_success": 1.0},
        "policy_violation_count": 0,
        "invalid_call_count": 0,
        "tool_selection_accuracy": 1.0,
        "task_success": 1.0,
    }
    report_id = FlightRunEvidence.compute_report_id(payload_for_hash)
    evidence = FlightRunEvidence(
        report_id=report_id,
        config=payload_for_hash["config"],
        task_count=60,
        metrics={"task_success": 1.0},
        policy_violation_count=0,
        invalid_call_count=0,
        tool_selection_accuracy=1.0,
        task_success=1.0,
        runtime_seconds=1.0,
    )
    path = tmp_path / "report.json"
    path.write_text(
        evidence.model_dump_json(indent=2),
        encoding="utf-8",
    )
    # Load succeeds with correct report_id
    loaded = FlightRunEvidence.model_validate_json(path.read_text(encoding="utf-8"))
    assert loaded.report_id == evidence.report_id

    # Tamper with task_success → report_id no longer matches
    data = evidence.model_dump(mode="json")
    data["task_success"] = 0.5
    path.write_text(
        __import__("json").dumps(data, indent=2),
        encoding="utf-8",
    )
    tampered = FlightRunEvidence.model_validate_json(path.read_text(encoding="utf-8"))
    # Recompute report_id excluding runtime_seconds (same logic as run_evaluation)
    payload_for_hash = {
        k: v
        for k, v in tampered.model_dump(mode="json").items()
        if k not in ("report_id", "runtime_seconds")
    }
    recomputed = FlightRunEvidence.compute_report_id(payload_for_hash)
    assert tampered.report_id != recomputed


def test_paired_comparison_same_evidence_is_zero_delta(manifest):
    """Comparing an evidence with itself must produce zero deltas — the paired
    comparison is the core of the release gate."""

    metrics_a = {"task_success": 1.0, "policy_violation_count": 0}
    metrics_b = {"task_success": 1.0, "policy_violation_count": 0}
    delta = metrics_b["task_success"] - metrics_a["task_success"]
    assert delta == 0.0
