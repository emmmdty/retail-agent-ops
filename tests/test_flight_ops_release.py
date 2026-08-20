"""FlightOps v1 release gate tests — GO/NO-GO logic + self-hash + tamper detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from veritool_rl.flight_ops.domain.bundle import load_bundle
from veritool_rl.flight_ops.evaluate.evaluation import FlightEvalConfig, FlightRunEvidence
from veritool_rl.flight_ops.release.release import (
    FlightReleaseDecision,
    FlightReleaseReport,
    build_release_report,
    evaluate_release_gates,
)

BUNDLE_DIR = Path(__file__).resolve().parents[1] / "domains" / "flight_ops" / "v1"


@pytest.fixture(scope="module")
def release_config():
    return load_bundle(BUNDLE_DIR).release


def _make_evidence(task_success: float, pv_count: int = 0, ic_count: int = 0) -> FlightRunEvidence:
    return FlightRunEvidence(
        report_id="a" * 64,
        config=FlightEvalConfig(
            dataset_version="v1",
            bundle_sha256="b" * 64,
            manifest_sha256="c" * 64,
            seed=0,
            split="dev",
            model_name="test",
        ),
        task_count=60,
        metrics={"task_success": task_success},
        policy_violation_count=pv_count,
        invalid_call_count=ic_count,
        tool_selection_accuracy=task_success,
        task_success=task_success,
        runtime_seconds=1.0,
    )


def test_go_when_candidate_improves(release_config):
    base = _make_evidence(0.8)
    candidate = _make_evidence(0.9)
    decision, gates = evaluate_release_gates(base, candidate, release_config)
    assert decision == FlightReleaseDecision.GO
    assert all(g.passed for g in gates)


def test_no_go_when_success_delta_below_threshold(release_config):
    base = _make_evidence(0.8)
    candidate = _make_evidence(0.82)  # delta=0.02 < 0.05 threshold
    decision, gates = evaluate_release_gates(base, candidate, release_config)
    assert decision == FlightReleaseDecision.NO_GO
    sg = next(g for g in gates if g.gate_id == "success_delta")
    assert not sg.passed


def test_no_go_when_policy_violation_increases(release_config):
    base = _make_evidence(0.9, pv_count=0)
    candidate = _make_evidence(0.95, pv_count=2)
    decision, gates = evaluate_release_gates(base, candidate, release_config)
    assert decision == FlightReleaseDecision.NO_GO
    pg = next(g for g in gates if g.gate_id == "policy_violation_delta")
    assert not pg.passed


def test_no_go_when_invalid_calls_present(release_config):
    base = _make_evidence(0.9)
    candidate = _make_evidence(0.95, ic_count=3)
    decision, _ = evaluate_release_gates(base, candidate, release_config)
    assert decision == FlightReleaseDecision.NO_GO


def test_report_id_is_self_hashing(release_config, tmp_path):
    base = _make_evidence(0.8)
    candidate = _make_evidence(0.9)
    report = build_release_report(base, candidate, release_config, tmp_path / "release")
    assert len(report.report_id) == 64
    assert report.decision == FlightReleaseDecision.GO


def test_report_tamper_detection(release_config, tmp_path):
    base = _make_evidence(0.8)
    candidate = _make_evidence(0.9)
    report = build_release_report(base, candidate, release_config, tmp_path / "release")

    # Load, tamper with decision, recompute report_id → mismatch
    data = report.model_dump(mode="json")
    data["decision"] = "GO"
    data["candidate_task_success"] = 0.5  # tamper
    recomputed = FlightReleaseReport.compute_report_id(
        {k: v for k, v in data.items() if k != "report_id"}
    )
    assert recomputed != report.report_id


def test_gate_result_fields_are_populated(release_config):
    base = _make_evidence(0.8, pv_count=5)
    candidate = _make_evidence(0.95, pv_count=0)
    _, gates = evaluate_release_gates(base, candidate, release_config)
    sg = next(g for g in gates if g.gate_id == "success_delta")
    assert sg.base_value == 0.8
    assert sg.candidate_value == 0.95
    assert sg.delta == pytest.approx(0.15)
    assert sg.threshold == release_config.success_delta_min
