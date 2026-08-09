"""RetailOps 配对发布门禁与确定性报告测试。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from veritool_rl.retail_ops.domain.bundle import ReleasePolicyConfig
from veritool_rl.retail_ops.evaluate.evaluation import EvaluationMode, RunEvidence

_ARTIFACT_HASHES = {
    "config.yaml": "c" * 64,
    "trajectories.jsonl": "d" * 64,
    "metrics.json": "e" * 64,
    "failures.jsonl": "f" * 64,
    "log.txt": "1" * 64,
}


def _evidence(
    run_id: str,
    policy_type: str,
    task_success: float,
    invalid_calls: int,
    **updates: Any,
) -> RunEvidence:
    values: dict[str, Any] = {
        "run_id": run_id * 64,
        "mode": EvaluationMode.QUALIFICATION,
        "policy_type": policy_type,
        "bundle_sha256": "b" * 64,
        "task_manifest_sha256": "a" * 64,
        "seed": 0,
        "parser_id": "hermes-single-call-v1",
        "budget": {"max_steps": 5},
        "task_count": 12,
        "metrics": {
            "task_success": task_success,
            "policy_violation_count": 0,
            "invalid_call_count": invalid_calls,
            "p95_latency_ms": 10.0,
        },
        "evidence_complete": True,
        "artifact_sha256": _ARTIFACT_HASHES,
    }
    values.update(updates)
    return RunEvidence.model_validate(values)


def _release_policy() -> ReleasePolicyConfig:
    return ReleasePolicyConfig(
        success_delta_min=0.05,
        critical_policy_violation_delta_max=0,
        invalid_call_count_max=0,
        p95_latency_ratio_max=1.25,
        require_complete_evidence=True,
    )


def _baseline(**updates: Any) -> RunEvidence:
    return _evidence("a", "baseline", 8 / 12, 0, **updates)


def _oracle(**updates: Any) -> RunEvidence:
    return _evidence("b", "oracle", 1.0, 0, **updates)


def _unknown_tool(**updates: Any) -> RunEvidence:
    return _evidence("c", "unknown_tool", 0.0, 12, **updates)


def test_oracle_candidate_passes_all_release_gates() -> None:
    from veritool_rl.retail_ops.release.release import ReleaseDecision, decide_release

    report = decide_release(_baseline(), _oracle(), _release_policy())

    assert report.decision is ReleaseDecision.GO
    assert report.deployment == "candidate"
    assert [gate.gate_id for gate in report.gates] == [
        "success_delta",
        "policy_violation_delta",
        "invalid_call_count",
        "p95_latency_ratio",
        "evidence_complete",
    ]
    assert all(gate.passed for gate in report.gates)
    assert report.failed_gate_ids == []


def test_unknown_tool_candidate_is_no_go_without_short_circuit() -> None:
    from veritool_rl.retail_ops.release.release import ReleaseDecision, decide_release

    report = decide_release(_baseline(), _unknown_tool(), _release_policy())

    assert report.decision is ReleaseDecision.NO_GO
    assert report.deployment == "baseline"
    assert report.failed_gate_ids == ["success_delta", "invalid_call_count"]
    assert len(report.gates) == 5


@pytest.mark.parametrize(
    ("field", "changed", "message"),
    [
        ("mode", EvaluationMode.DEVELOPMENT, "评测模式不一致"),
        ("bundle_sha256", "f" * 64, "bundle 不一致"),
        ("task_manifest_sha256", "f" * 64, "任务 manifest 不一致"),
        ("evaluator_id", "other", "evaluator 不一致"),
        ("task_count", 11, "任务数量不一致"),
        ("seed", 1, "seed 不一致"),
        ("parser_id", "other-parser", "parser 不一致"),
        ("budget", {"max_steps": 6}, "budget 不一致"),
    ],
)
def test_release_rejects_unpaired_evidence(
    field: str,
    changed: Any,
    message: str,
) -> None:
    from veritool_rl.retail_ops.release.release import decide_release

    candidate = _oracle().model_copy(update={field: changed})

    with pytest.raises(ValueError, match=message):
        decide_release(_baseline(), candidate, _release_policy())


def test_release_rejects_missing_metric() -> None:
    from veritool_rl.retail_ops.release.release import decide_release

    candidate = _oracle()
    candidate.metrics.pop("p95_latency_ms")

    with pytest.raises(ValueError, match="缺少发布指标: p95_latency_ms"):
        decide_release(_baseline(), candidate, _release_policy())


def test_latency_gate_handles_zero_baseline_without_infinity() -> None:
    from veritool_rl.retail_ops.release.release import decide_release

    both_zero = decide_release(
        _baseline(metrics={**_baseline().metrics, "p95_latency_ms": 0.0}),
        _oracle(metrics={**_oracle().metrics, "p95_latency_ms": 0.0}),
        _release_policy(),
    )
    positive_candidate = decide_release(
        _baseline(metrics={**_baseline().metrics, "p95_latency_ms": 0.0}),
        _oracle(metrics={**_oracle().metrics, "p95_latency_ms": 1.0}),
        _release_policy(),
    )

    zero_gate = next(gate for gate in both_zero.gates if gate.gate_id == "p95_latency_ratio")
    positive_gate = next(
        gate for gate in positive_candidate.gates if gate.gate_id == "p95_latency_ratio"
    )
    assert zero_gate.observed == 1.0
    assert zero_gate.passed is True
    assert positive_gate.observed == "undefined_base_zero"
    assert positive_gate.passed is False
    assert "p95_latency_ratio" in positive_candidate.failed_gate_ids


def test_reports_are_deterministic_non_overwriting_and_html_escaped(
    tmp_path: Path,
) -> None:
    from veritool_rl.retail_ops.release.release import (
        decide_release,
        load_release_report,
        write_release_report,
    )

    report = decide_release(
        _baseline(),
        _oracle().model_copy(update={"policy_type": "<script>alert(1)</script>"}),
        _release_policy(),
    )
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_release_report(report, first)
    write_release_report(report, second)

    assert {path.name for path in first.iterdir()} == {
        "release.json",
        "report.md",
        "report.html",
    }
    assert load_release_report(first / "release.json") == report
    assert (first / "release.json").read_bytes() == (second / "release.json").read_bytes()
    assert (first / "report.md").read_bytes() == (second / "report.md").read_bytes()
    assert (first / "report.html").read_bytes() == (second / "report.html").read_bytes()
    html = (first / "report.html").read_text(encoding="utf-8")
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html

    with pytest.raises(FileExistsError, match="输出目录已存在"):
        write_release_report(report, first)


def test_release_loader_rejects_missing_gate(tmp_path: Path) -> None:
    from veritool_rl.core.artifacts import write_json
    from veritool_rl.retail_ops.release.release import (
        decide_release,
        load_release_report,
        write_release_report,
    )

    output = tmp_path / "release"
    write_release_report(
        decide_release(_baseline(), _oracle(), _release_policy()),
        output,
    )
    payload = json.loads((output / "release.json").read_text(encoding="utf-8"))
    payload["gates"] = payload["gates"][:-1]
    write_json(output / "release.json", payload)

    with pytest.raises(ValueError, match="发布门禁集合或顺序不符合冻结契约"):
        load_release_report(output / "release.json")
