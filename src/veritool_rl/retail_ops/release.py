"""RetailOps 配对发布门禁与确定性 JSON/Markdown/HTML 报告。"""

from __future__ import annotations

import html
import math
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from veritool_rl.artifacts import canonical_json, create_output_dir, write_json
from veritool_rl.retail_ops.bundle import ReleasePolicyConfig
from veritool_rl.retail_ops.evaluation import RunEvidence
from veritool_rl.trajectory.schema import StrictModel, validate_json_value

_REQUIRED_METRICS = (
    "task_success",
    "policy_violation_count",
    "invalid_call_count",
    "p95_latency_ms",
)
_GATE_IDS = (
    "success_delta",
    "policy_violation_delta",
    "invalid_call_count",
    "p95_latency_ratio",
    "evidence_complete",
)


class ReleaseDecision(StrEnum):
    """候选的发布结论。"""

    GO = "GO"
    NO_GO = "NO-GO"


class GateResult(StrictModel):
    """单项发布门禁的观测、阈值和解释。"""

    gate_id: str = Field(min_length=1)
    passed: bool
    observed: float | int | bool | str
    threshold: float | int | bool
    reason: str = Field(min_length=1)


class ReleaseReport(StrictModel):
    """配对证据产生的完整 GO/NO-GO 结论。"""

    schema_version: Literal["1.0"] = "1.0"
    decision: ReleaseDecision
    baseline_run_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_run_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    baseline_policy: str = Field(min_length=1)
    candidate_policy: str = Field(min_length=1)
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    deployment: Literal["candidate", "baseline"]
    gates: list[GateResult]
    failed_gate_ids: list[str]
    baseline_metrics: dict[str, Any]
    candidate_metrics: dict[str, Any]

    _validate_metrics = field_validator("baseline_metrics", "candidate_metrics")(
        validate_json_value
    )

    @model_validator(mode="after")
    def validate_decision_consistency(self) -> Self:
        if tuple(gate.gate_id for gate in self.gates) != _GATE_IDS:
            raise ValueError("发布门禁集合或顺序不符合冻结契约")
        failed = [gate.gate_id for gate in self.gates if not gate.passed]
        if failed != self.failed_gate_ids:
            raise ValueError("failed_gate_ids 与 gate 结果不一致")
        expected_decision = ReleaseDecision.NO_GO if failed else ReleaseDecision.GO
        expected_deployment = "baseline" if failed else "candidate"
        if self.decision is not expected_decision or self.deployment != expected_deployment:
            raise ValueError("发布结论、失败门禁与 deployment 不一致")
        return self


def decide_release(
    baseline: RunEvidence,
    candidate: RunEvidence,
    policy: ReleasePolicyConfig,
) -> ReleaseReport:
    """验证同任务配对公平性并计算全部发布门禁。"""
    _validate_paired_evidence(baseline, candidate)
    baseline_metrics = _required_metrics(baseline.metrics)
    candidate_metrics = _required_metrics(candidate.metrics)

    success_delta = candidate_metrics["task_success"] - baseline_metrics["task_success"]
    violation_delta = int(candidate_metrics["policy_violation_count"]) - int(
        baseline_metrics["policy_violation_count"]
    )
    invalid_calls = int(candidate_metrics["invalid_call_count"])
    latency_observed, latency_passed = _latency_gate(
        baseline_metrics["p95_latency_ms"],
        candidate_metrics["p95_latency_ms"],
        policy.p95_latency_ratio_max,
    )
    evidence_complete = baseline.evidence_complete and candidate.evidence_complete
    gates = [
        GateResult(
            gate_id="success_delta",
            passed=success_delta >= policy.success_delta_min,
            observed=success_delta,
            threshold=policy.success_delta_min,
            reason="候选最终状态成功率相对同基座的绝对提升。",
        ),
        GateResult(
            gate_id="policy_violation_delta",
            passed=violation_delta <= policy.critical_policy_violation_delta_max,
            observed=violation_delta,
            threshold=policy.critical_policy_violation_delta_max,
            reason="候选关键政策违规数不得高于允许增量。",
        ),
        GateResult(
            gate_id="invalid_call_count",
            passed=invalid_calls <= policy.invalid_call_count_max,
            observed=invalid_calls,
            threshold=policy.invalid_call_count_max,
            reason="候选非法工具调用与参数错误总数必须满足上限。",
        ),
        GateResult(
            gate_id="p95_latency_ratio",
            passed=latency_passed,
            observed=latency_observed,
            threshold=policy.p95_latency_ratio_max,
            reason="候选 p95 episode 延迟相对同基座的比例。",
        ),
        GateResult(
            gate_id="evidence_complete",
            passed=evidence_complete is policy.require_complete_evidence,
            observed=evidence_complete,
            threshold=policy.require_complete_evidence,
            reason="基座与候选证据、重放和产物摘要必须完整。",
        ),
    ]
    failed_gate_ids = [gate.gate_id for gate in gates if not gate.passed]
    decision = ReleaseDecision.NO_GO if failed_gate_ids else ReleaseDecision.GO
    return ReleaseReport(
        decision=decision,
        baseline_run_id=baseline.run_id,
        candidate_run_id=candidate.run_id,
        baseline_policy=baseline.policy_type,
        candidate_policy=candidate.policy_type,
        bundle_sha256=baseline.bundle_sha256,
        task_manifest_sha256=baseline.task_manifest_sha256,
        deployment="baseline" if failed_gate_ids else "candidate",
        gates=gates,
        failed_gate_ids=failed_gate_ids,
        baseline_metrics=baseline.metrics,
        candidate_metrics=candidate.metrics,
    )


def write_release_report(report: ReleaseReport, output_dir: Path) -> None:
    """向新目录写稳定的 JSON、Markdown 与 HTML 发布报告。"""
    create_output_dir(output_dir)
    write_json(output_dir / "release.json", report.model_dump(mode="json"))
    (output_dir / "report.md").write_text(_render_markdown(report), encoding="utf-8")
    (output_dir / "report.html").write_text(_render_html(report), encoding="utf-8")


def load_release_report(path: Path) -> ReleaseReport:
    """读取并严格校验发布报告。"""
    return ReleaseReport.model_validate_json(path.read_text(encoding="utf-8"))


def _validate_paired_evidence(
    baseline: RunEvidence,
    candidate: RunEvidence,
) -> None:
    comparisons = (
        ("mode", "评测模式不一致"),
        ("bundle_sha256", "bundle 不一致"),
        ("task_manifest_sha256", "任务 manifest 不一致"),
        ("evaluator_id", "evaluator 不一致"),
        ("task_count", "任务数量不一致"),
        ("seed", "seed 不一致"),
        ("parser_id", "parser 不一致"),
        ("budget", "budget 不一致"),
    )
    for field, message in comparisons:
        if getattr(baseline, field) != getattr(candidate, field):
            raise ValueError(message)


def _required_metrics(metrics: dict[str, Any]) -> dict[str, float | int]:
    checked: dict[str, float | int] = {}
    for name in _REQUIRED_METRICS:
        if name not in metrics:
            raise ValueError(f"缺少发布指标: {name}")
        value = metrics[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"发布指标必须是有限数字: {name}")
        if not math.isfinite(float(value)) or value < 0:
            raise ValueError(f"发布指标必须是非负有限数字: {name}")
        checked[name] = value
    if checked["task_success"] > 1:
        raise ValueError("task_success 必须位于 [0, 1]")
    for name in ("policy_violation_count", "invalid_call_count"):
        if not isinstance(checked[name], int):
            raise ValueError(f"发布计数指标必须是整数: {name}")
    return checked


def _latency_gate(
    baseline_latency: float | int,
    candidate_latency: float | int,
    threshold: float,
) -> tuple[float | str, bool]:
    baseline_value = float(baseline_latency)
    candidate_value = float(candidate_latency)
    if baseline_value == 0.0:
        if candidate_value == 0.0:
            return 1.0, True
        return "undefined_base_zero", False
    ratio = candidate_value / baseline_value
    return ratio, ratio <= threshold


def _render_markdown(report: ReleaseReport) -> str:
    lines = [
        "# RetailAgentOps 发布报告",
        "",
        f"- 决策：`{report.decision.value}`",
        f"- 部署：`{report.deployment}`",
        f"- 基座策略：`{_escape_text(report.baseline_policy)}`",
        f"- 候选策略：`{_escape_text(report.candidate_policy)}`",
        f"- Bundle SHA-256：`{report.bundle_sha256}`",
        f"- Task manifest SHA-256：`{report.task_manifest_sha256}`",
        "",
        "## 发布门禁",
        "",
        "| 门禁 | 通过 | 观测值 | 阈值 | 说明 |",
        "|---|---:|---:|---:|---|",
    ]
    lines.extend(
        "| {gate} | {passed} | `{observed}` | `{threshold}` | {reason} |".format(
            gate=_escape_text(gate.gate_id),
            passed="是" if gate.passed else "否",
            observed=_escape_text(str(gate.observed)),
            threshold=_escape_text(str(gate.threshold)),
            reason=_escape_text(gate.reason),
        )
        for gate in report.gates
    )
    lines.extend(
        [
            "",
            "## 配对指标",
            "",
            f"- 基座：`{_escape_text(canonical_json(report.baseline_metrics))}`",
            f"- 候选：`{_escape_text(canonical_json(report.candidate_metrics))}`",
            "",
        ]
    )
    return "\n".join(lines)


def _render_html(report: ReleaseReport) -> str:
    gate_rows = "".join(
        "<tr>"
        f"<td>{html.escape(gate.gate_id)}</td>"
        f"<td>{'是' if gate.passed else '否'}</td>"
        f"<td>{html.escape(str(gate.observed))}</td>"
        f"<td>{html.escape(str(gate.threshold))}</td>"
        f"<td>{html.escape(gate.reason)}</td>"
        "</tr>"
        for gate in report.gates
    )
    baseline_metrics = html.escape(canonical_json(report.baseline_metrics))
    candidate_metrics = html.escape(canonical_json(report.candidate_metrics))
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        "<title>RetailAgentOps 发布报告</title></head><body>"
        "<h1>RetailAgentOps 发布报告</h1>"
        f"<p>决策：<strong>{html.escape(report.decision.value)}</strong></p>"
        f"<p>部署：{html.escape(report.deployment)}</p>"
        f"<p>基座策略：{html.escape(report.baseline_policy)}</p>"
        f"<p>候选策略：{html.escape(report.candidate_policy)}</p>"
        f"<p>Bundle SHA-256：<code>{report.bundle_sha256}</code></p>"
        f"<p>Task manifest SHA-256：<code>{report.task_manifest_sha256}</code></p>"
        "<h2>发布门禁</h2><table><thead><tr><th>门禁</th><th>通过</th>"
        "<th>观测值</th><th>阈值</th><th>说明</th></tr></thead>"
        f"<tbody>{gate_rows}</tbody></table>"
        "<h2>配对指标</h2>"
        f"<h3>基座</h3><pre>{baseline_metrics}</pre>"
        f"<h3>候选</h3><pre>{candidate_metrics}</pre>"
        "</body></html>\n"
    )


def _escape_text(value: str) -> str:
    return html.escape(value, quote=False).replace("|", "&#124;").replace("`", "&#96;")
