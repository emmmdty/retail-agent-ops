"""RetailOps 配对发布门禁与确定性 JSON/Markdown/HTML 报告。"""

from __future__ import annotations

import html
import math
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from veritool_rl.core.artifacts import canonical_json, create_output_dir, write_json
from veritool_rl.core.metrics import (
    DIAGNOSTIC_NOTE,
    paired_bootstrap_delta_ci95,
    split_headline_and_diagnostic,
)
from veritool_rl.core.trajectory.schema import StrictModel, validate_json_value
from veritool_rl.retail_ops.domain.bundle import ReleasePolicyConfig
from veritool_rl.retail_ops.evaluate.evaluation import RunEvidence

_REQUIRED_METRICS = (
    "task_success",
    "policy_violation_count",
    "invalid_call_count",
    "p95_latency_ms",
)

#: v1.1 额外需要的两个量。它们从 R1 起就在 `compute_metrics` 的输出里，因此
#: 所有已产出的证据都能重算 v1.1 门禁，不需要重跑任何模型。
_REQUIRED_METRICS_V1_1 = (*_REQUIRED_METRICS, "average_latency_ms", "average_tool_calls")

#: **v1.0：磁盘上全部已有 release 报告的冻结契约。一个字都不能改。**
#: 就地增删这个元组会让 `formal-release-001/002` 与 R1 qualification 的 GO/NO-GO
#: 报告全部无法加载——那是不可逆的证据损失，所以新口径走版本化路径。
GATE_IDS = (
    "success_delta",
    "policy_violation_delta",
    "invalid_call_count",
    "p95_latency_ratio",
    "evidence_complete",
)

#: v1.1：把 episode 级 p95 拆成三个各自回答一个问题的量，并给 `success_delta`
#: 补一个配对统计检验。
#:
#: 旧口径的缺陷（评审 P1-4/P1-5）：
#: - episode 级 p95 把"能力提升"和"速度下降"混进同一个数。base 的典型失败是
#:   "查完就说"（1 步），正确执行的候选要 2 步——**做对事的候选必然更慢**；
#: - `success_delta` 是裸点估计与 0.05 比较，n=120 时 CI 宽度 ±7.5pp，
#:   阈值整个落在噪声带里。
#:
#: **阈值一个都没新增**：三个比值门禁复用 `p95_latency_ratio_max`（同一个"相对基座
#: 不得劣化超过 25%"的政策数，三个测量轴），CI 下界的 0 是结构性常量而不是可调阈值。
#: 这不是偷懒——`release.yaml` 在 `bundle_sha256` 的分量里，新增字段会使全部已有
#: dev/sealed 证据不可配对。
GATE_IDS_V1_1 = (
    "success_delta",
    "success_delta_ci_lower",
    "policy_violation_delta",
    "invalid_call_count",
    "per_call_latency_ratio",
    "steps_to_success_ratio",
    "latency_per_success_ratio",
    "evidence_complete",
)

GateSchemaVersion = Literal["1.0", "1.1"]

GATE_IDS_BY_SCHEMA: dict[str, tuple[str, ...]] = {
    "1.0": GATE_IDS,
    "1.1": GATE_IDS_V1_1,
}

#: 三个比值门禁共用的说明片段。`reason` 是给人读的字段，"失败任务提前终止反而更快"
#: 这个偏置正是应该写在那里的东西。
_EARLY_TERMINATION_NOTE = "注意偏置：失败任务往往提前终止，因此**更差的模型可能看起来更快**。"


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

    schema_version: GateSchemaVersion = "1.0"
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
        if tuple(gate.gate_id for gate in self.gates) != GATE_IDS_BY_SCHEMA[self.schema_version]:
            raise ValueError("发布门禁集合或顺序不符合冻结契约")
        failed = [gate.gate_id for gate in self.gates if not gate.passed]
        if failed != self.failed_gate_ids:
            raise ValueError("failed_gate_ids 与 gate 结果不一致")
        expected_decision = ReleaseDecision.NO_GO if failed else ReleaseDecision.GO
        expected_deployment = "baseline" if failed else "candidate"
        if self.decision is not expected_decision or self.deployment != expected_deployment:
            raise ValueError("发布结论、失败门禁与 deployment 不一致")
        return self


def build_release_gates(
    baseline_metrics: dict[str, Any],
    candidate_metrics: dict[str, Any],
    *,
    evidence_complete: bool,
    policy: ReleasePolicyConfig,
    schema_version: GateSchemaVersion = "1.0",
    paired_outcomes: Sequence[tuple[bool, bool]] | None = None,
) -> list[GateResult]:
    """按冻结策略计算发布门禁；R1 qualification 与 formal holdout 共用这一份。

    抽出来是为了让"同一份 `release.yaml` 只有一种语义"成为结构事实：两条通道
    的证据类型不同，但阈值、比较方向和门禁顺序必须逐字节同源，否则同一个候选
    在两条通道上可能得到互相矛盾的结论。

    `schema_version` 选择门禁集合。**默认仍是 v1.0**：已有的两次 NO-GO 判定就是
    用它得出的，改默认值会让历史结论与复算结论无法区分。v1.1 的动机、拆分方式与
    "阈值一个都没新增"的理由见 `GATE_IDS_V1_1` 的注释。

    `paired_outcomes` 是逐任务的 `(base_success, candidate_success)`。v1.0 不需要它；
    v1.1 的 `success_delta_ci_lower` 需要，缺失时该门禁判 **FAIL**——缺证据不是通过
    的理由。公开 sealed 报告只有聚合量，逐任务结局只能来自私有 `trajectories.jsonl`。
    """
    if schema_version == "1.0":
        return _gates_v1_0(
            baseline_metrics,
            candidate_metrics,
            evidence_complete=evidence_complete,
            policy=policy,
        )
    return _gates_v1_1(
        baseline_metrics,
        candidate_metrics,
        evidence_complete=evidence_complete,
        policy=policy,
        paired_outcomes=paired_outcomes,
    )


def _gates_v1_0(
    baseline_metrics: dict[str, Any],
    candidate_metrics: dict[str, Any],
    *,
    evidence_complete: bool,
    policy: ReleasePolicyConfig,
) -> list[GateResult]:
    baseline_checked = _required_metrics(baseline_metrics)
    candidate_checked = _required_metrics(candidate_metrics)

    success_delta = candidate_checked["task_success"] - baseline_checked["task_success"]
    latency_observed, latency_passed = _ratio_gate(
        baseline_checked["p95_latency_ms"],
        candidate_checked["p95_latency_ms"],
        policy.p95_latency_ratio_max,
    )
    return [
        GateResult(
            gate_id="success_delta",
            passed=success_delta >= policy.success_delta_min,
            observed=success_delta,
            threshold=policy.success_delta_min,
            reason="候选最终状态成功率相对同基座的绝对提升。",
        ),
        *_shared_safety_gates(baseline_checked, candidate_checked, policy),
        GateResult(
            gate_id="p95_latency_ratio",
            passed=latency_passed,
            observed=latency_observed,
            threshold=policy.p95_latency_ratio_max,
            reason="候选 p95 episode 延迟相对同基座的比例。",
        ),
        _evidence_gate(evidence_complete, policy),
    ]


def _gates_v1_1(
    baseline_metrics: dict[str, Any],
    candidate_metrics: dict[str, Any],
    *,
    evidence_complete: bool,
    policy: ReleasePolicyConfig,
    paired_outcomes: Sequence[tuple[bool, bool]] | None,
) -> list[GateResult]:
    baseline_checked = _required_metrics(baseline_metrics, _REQUIRED_METRICS_V1_1)
    candidate_checked = _required_metrics(candidate_metrics, _REQUIRED_METRICS_V1_1)

    success_delta = candidate_checked["task_success"] - baseline_checked["task_success"]
    ci_observed, ci_passed = _paired_ci_gate(
        paired_outcomes,
        baseline_checked["task_success"],
        candidate_checked["task_success"],
    )
    per_call_observed, per_call_passed = _ratio_gate(
        _per_call_latency(baseline_checked),
        _per_call_latency(candidate_checked),
        policy.p95_latency_ratio_max,
        undefined="undefined_no_tool_calls",
    )
    steps_observed, steps_passed = _ratio_gate(
        _per_success(baseline_checked, "average_tool_calls"),
        _per_success(candidate_checked, "average_tool_calls"),
        policy.p95_latency_ratio_max,
        undefined="undefined_no_success",
    )
    cost_observed, cost_passed = _ratio_gate(
        _per_success(baseline_checked, "average_latency_ms"),
        _per_success(candidate_checked, "average_latency_ms"),
        policy.p95_latency_ratio_max,
        undefined="undefined_no_success",
    )
    return [
        GateResult(
            gate_id="success_delta",
            passed=success_delta >= policy.success_delta_min,
            observed=success_delta,
            threshold=policy.success_delta_min,
            reason="候选最终状态成功率相对同基座的绝对提升（点估计，保留展示）。",
        ),
        GateResult(
            gate_id="success_delta_ci_lower",
            passed=ci_passed,
            observed=ci_observed,
            threshold=0.0,
            reason=(
                "逐任务配对 bootstrap 的 delta CI95 下界必须 ≥ 0。"
                "点估计单独与阈值比较无法区分真实提升与抽样噪声；"
                "缺少逐任务配对证据时本门禁判 FAIL，缺证据不是通过的理由。"
            ),
        ),
        *_shared_safety_gates(baseline_checked, candidate_checked, policy),
        GateResult(
            gate_id="per_call_latency_ratio",
            passed=per_call_passed,
            observed=per_call_observed,
            threshold=policy.p95_latency_ratio_max,
            reason=(
                "单次工具调用平均耗时的比值，衡量**部署速度**而非规划质量："
                "它对「候选多做了一步」免疫，只对前向变慢敏感。" + _EARLY_TERMINATION_NOTE
            ),
        ),
        GateResult(
            gate_id="steps_to_success_ratio",
            passed=steps_passed,
            observed=steps_observed,
            threshold=policy.p95_latency_ratio_max,
            reason=(
                "每成功一条任务所需工具调用次数的比值，衡量**规划效率**："
                "多做一步但成功率同比提升时，这个数不变。" + _EARLY_TERMINATION_NOTE
            ),
        ),
        GateResult(
            gate_id="latency_per_success_ratio",
            passed=cost_passed,
            observed=cost_observed,
            threshold=policy.p95_latency_ratio_max,
            reason=(
                "端到端 episode 耗时**按成功任务归一化**后的比值，衡量单位产出成本。"
                + _EARLY_TERMINATION_NOTE
            ),
        ),
        _evidence_gate(evidence_complete, policy),
    ]


def _shared_safety_gates(
    baseline_checked: dict[str, float | int],
    candidate_checked: dict[str, float | int],
    policy: ReleasePolicyConfig,
) -> list[GateResult]:
    """两个版本逐字节共用的安全类门禁；不允许出现第二套语义。"""
    violation_delta = int(candidate_checked["policy_violation_count"]) - int(
        baseline_checked["policy_violation_count"]
    )
    invalid_calls = int(candidate_checked["invalid_call_count"])
    return [
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
    ]


def _evidence_gate(evidence_complete: bool, policy: ReleasePolicyConfig) -> GateResult:
    return GateResult(
        gate_id="evidence_complete",
        passed=evidence_complete is policy.require_complete_evidence,
        observed=evidence_complete,
        threshold=policy.require_complete_evidence,
        reason="基座与候选证据、重放和产物摘要必须完整。",
    )


def _per_call_latency(metrics: dict[str, float | int]) -> float | None:
    """单次工具调用平均耗时；一次调用都没有时该量无定义，返回 None。"""
    calls = float(metrics["average_tool_calls"])
    if calls == 0.0:
        return None
    return float(metrics["average_latency_ms"]) / calls


def _per_success(metrics: dict[str, float | int], name: str) -> float | None:
    """按成功任务归一化；一条都没成功时该量无定义，返回 None。

    这里**不能**沿用"两侧都为零 → 比值 1.0 通过"的例外：两个模型都从不成功
    并不意味着它们的单位产出成本相同，那个数根本不存在。
    """
    success = float(metrics["task_success"])
    if success == 0.0:
        return None
    return float(metrics[name]) / success


def _paired_ci_gate(
    paired_outcomes: Sequence[tuple[bool, bool]] | None,
    baseline_success: float,
    candidate_success: float,
) -> tuple[float | str, bool]:
    if paired_outcomes is None:
        return "insufficient_paired_evidence", False
    total = len(paired_outcomes)
    if total == 0:
        return "insufficient_paired_evidence", False
    observed_base = sum(1 for base, _ in paired_outcomes if base) / total
    observed_candidate = sum(1 for _, candidate in paired_outcomes if candidate) / total
    if not math.isclose(observed_base, baseline_success, abs_tol=1e-9) or not math.isclose(
        observed_candidate, candidate_success, abs_tol=1e-9
    ):
        msg = (
            "逐任务配对证据与聚合指标不一致："
            f"配对得到 base={observed_base!r} candidate={observed_candidate!r}，"
            f"指标声明 base={baseline_success!r} candidate={candidate_success!r}"
        )
        raise ValueError(msg)
    low, _high = paired_bootstrap_delta_ci95(paired_outcomes)
    return low, low >= 0.0


def decide_release(
    baseline: RunEvidence,
    candidate: RunEvidence,
    policy: ReleasePolicyConfig,
) -> ReleaseReport:
    """验证同任务配对公平性并计算全部发布门禁。"""
    _validate_paired_evidence(baseline, candidate)
    evidence_complete = baseline.evidence_complete and candidate.evidence_complete
    gates = build_release_gates(
        baseline.metrics,
        candidate.metrics,
        evidence_complete=evidence_complete,
        policy=policy,
    )
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


def _required_metrics(
    metrics: dict[str, Any],
    names: tuple[str, ...] = _REQUIRED_METRICS,
) -> dict[str, float | int]:
    checked: dict[str, float | int] = {}
    for name in names:
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


def _ratio_gate(
    baseline_value_raw: float | int | None,
    candidate_value_raw: float | int | None,
    threshold: float,
    *,
    undefined: str = "undefined_base_zero",
) -> tuple[float | str, bool]:
    """候选/基座的比值门禁。无定义或分母为零时判 FAIL，而不是给一个看起来能用的数。

    唯一的例外是两侧都为零：那是"两边都没有可测量的量"（如两侧延迟都是 0），
    比值定义为 1.0 且通过，与 R1 起的既有行为一致。`None` 表示该量**根本没有定义**，
    不适用这个例外。
    """
    if baseline_value_raw is None or candidate_value_raw is None:
        return undefined, False
    baseline_value = float(baseline_value_raw)
    candidate_value = float(candidate_value_raw)
    if baseline_value == 0.0:
        if candidate_value == 0.0:
            return 1.0, True
        return undefined, False
    if candidate_value == 0.0:
        return undefined, False
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
    baseline_headline, baseline_diagnostic = split_headline_and_diagnostic(report.baseline_metrics)
    candidate_headline, candidate_diagnostic = split_headline_and_diagnostic(
        report.candidate_metrics
    )
    lines.extend(
        [
            "",
            "## 配对指标",
            "",
            f"- 基座：`{_escape_text(canonical_json(baseline_headline))}`",
            f"- 候选：`{_escape_text(canonical_json(candidate_headline))}`",
            "",
            "## 诊断量",
            "",
            DIAGNOSTIC_NOTE,
            "",
            f"- 基座：`{_escape_text(canonical_json(baseline_diagnostic))}`",
            f"- 候选：`{_escape_text(canonical_json(candidate_diagnostic))}`",
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
    baseline_headline, baseline_diagnostic = split_headline_and_diagnostic(report.baseline_metrics)
    candidate_headline, candidate_diagnostic = split_headline_and_diagnostic(
        report.candidate_metrics
    )
    baseline_metrics = html.escape(canonical_json(baseline_headline))
    candidate_metrics = html.escape(canonical_json(candidate_headline))
    diagnostics = (
        "<h2>诊断量</h2>"
        f"<p>{html.escape(DIAGNOSTIC_NOTE)}</p>"
        f"<h3>基座</h3><pre>{html.escape(canonical_json(baseline_diagnostic))}</pre>"
        f"<h3>候选</h3><pre>{html.escape(canonical_json(candidate_diagnostic))}</pre>"
    )
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
        f"{diagnostics}"
        "</body></html>\n"
    )


def _escape_text(value: str) -> str:
    return html.escape(value, quote=False).replace("|", "&#124;").replace("`", "&#96;")
