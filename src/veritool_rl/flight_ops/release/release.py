"""FlightOps v1 minimal release gate — paired comparison + GO/NO-GO decision.

Mirrors retail_ops's release gate structure (self-hashing report, paired
comparison, gate evaluation) but stripped to the minimum for C1's portability
proof: success_delta, policy_violation_delta, invalid_call_count,
evidence_complete. No paired bootstrap CI (that's for statistical rigor, not
needed here), no v1.1 latency splits, no Markdown/HTML reports.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field

from veritool_rl.core.artifacts import canonical_json
from veritool_rl.core.trajectory.schema import StrictModel
from veritool_rl.flight_ops.domain.bundle import ReleasePolicyConfig
from veritool_rl.flight_ops.evaluate.evaluation import FlightRunEvidence


class FlightReleaseDecision(StrEnum):
    GO = "GO"
    NO_GO = "NO-GO"


class FlightGateResult(StrictModel):
    gate_id: str
    passed: bool
    base_value: float | int | bool | None = None
    candidate_value: float | int | bool | None = None
    delta: float | int | None = None
    threshold: float | int | bool | None = None
    reason: str = ""


class FlightReleaseReport(StrictModel):
    """Self-hashing release report. report_id hashes all other fields."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, frozen=True)

    report_id: str = Field(min_length=1)
    schema_version: str = "1.0"
    base_report_id: str
    candidate_report_id: str
    decision: FlightReleaseDecision
    gates: list[FlightGateResult]
    success_delta: float
    policy_violation_delta: int
    invalid_call_count: int
    evidence_complete: bool
    base_task_success: float
    candidate_task_success: float

    @classmethod
    def compute_report_id(cls, payload: dict[str, Any]) -> str:
        content = canonical_json(payload).encode("utf-8")
        return hashlib.sha256(content).hexdigest()


def evaluate_release_gates(
    base: FlightRunEvidence,
    candidate: FlightRunEvidence,
    release_config: ReleasePolicyConfig,
) -> tuple[FlightReleaseDecision, list[FlightGateResult]]:
    """Evaluate release gates for paired base/candidate comparison."""
    gates: list[FlightGateResult] = []

    success_delta = candidate.task_success - base.task_success
    gates.append(
        FlightGateResult(
            gate_id="success_delta",
            passed=success_delta >= release_config.success_delta_min,
            base_value=base.task_success,
            candidate_value=candidate.task_success,
            delta=success_delta,
            threshold=release_config.success_delta_min,
        )
    )

    pv_delta = candidate.policy_violation_count - base.policy_violation_count
    gates.append(
        FlightGateResult(
            gate_id="policy_violation_delta",
            passed=pv_delta <= release_config.critical_policy_violation_delta_max,
            base_value=base.policy_violation_count,
            candidate_value=candidate.policy_violation_count,
            delta=pv_delta,
            threshold=release_config.critical_policy_violation_delta_max,
        )
    )

    gates.append(
        FlightGateResult(
            gate_id="invalid_call_count",
            passed=candidate.invalid_call_count <= release_config.invalid_call_count_max,
            candidate_value=candidate.invalid_call_count,
            threshold=release_config.invalid_call_count_max,
        )
    )
    evidence_complete = bool(
        base.report_id and candidate.report_id
        and base.task_count > 0 and candidate.task_count > 0
    )
    gates.append(
        FlightGateResult(
            gate_id="evidence_complete",
            passed=evidence_complete,
            base_value=bool(base.report_id),
            candidate_value=bool(candidate.report_id),
            threshold=True,
        )
    )

    all_passed = all(g.passed for g in gates)
    decision = FlightReleaseDecision.GO if all_passed else FlightReleaseDecision.NO_GO
    return decision, gates


def build_release_report(
    base: FlightRunEvidence,
    candidate: FlightRunEvidence,
    release_config: ReleasePolicyConfig,
    output_dir: Path,
) -> FlightReleaseReport:
    """Build and write a release report with self-hashing report_id."""
    decision, gates = evaluate_release_gates(base, candidate, release_config)

    success_delta = candidate.task_success - base.task_success
    pv_delta = candidate.policy_violation_count - base.policy_violation_count
    evidence_complete = bool(base.report_id and candidate.report_id)

    payload = {
        "schema_version": "1.0",
        "base_report_id": base.report_id,
        "candidate_report_id": candidate.report_id,
        "decision": decision.value,
        "gates": [g.model_dump(mode="json") for g in gates],
        "success_delta": success_delta,
        "policy_violation_delta": pv_delta,
        "invalid_call_count": candidate.invalid_call_count,
        "evidence_complete": evidence_complete,
        "base_task_success": base.task_success,
        "candidate_task_success": candidate.task_success,
    }
    report_id = FlightReleaseReport.compute_report_id(payload)

    report = FlightReleaseReport(
        report_id=report_id,
        base_report_id=base.report_id,
        candidate_report_id=candidate.report_id,
        decision=decision,
        gates=gates,
        success_delta=success_delta,
        policy_violation_delta=pv_delta,
        invalid_call_count=candidate.invalid_call_count,
        evidence_complete=evidence_complete,
        base_task_success=base.task_success,
        candidate_task_success=candidate.task_success,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "release.json"
    report_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return report
