"""封存 holdout 上的 GO/NO-GO 发布门禁。

与 R1 qualification 的 `ReleaseReport` 并行而不是替换它：`ReleaseReport` 的
`validate_decision_consistency` 断言 gate 集合与顺序精确等于该 schema 版本的
冻结集合（`GATE_IDS_BY_SCHEMA`），且
`decide_release` 的返回类型被 `serve` 与既有测试依赖，向它加 formal provenance
字段会破坏已冻结的 R1 契约。两条通道**共用** `build_release_gates`，因此同一份
`domains/retail_ops/v1/release.yaml` 只有一种阈值语义。

本模块是 SPEC §6 的执行者：它的输入只能是两份 sealed holdout 报告，且必须先
通过 `require_comparable_sealed_runs` 的配对契约校验。
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from veritool_rl.core.agent.qwen import GenerationSettings
from veritool_rl.core.artifacts import canonical_json, create_output_dir, write_json
from veritool_rl.core.metrics import DIAGNOSTIC_NOTE, split_headline_and_diagnostic
from veritool_rl.core.trajectory.schema import StrictModel, validate_json_value
from veritool_rl.retail_ops.domain.bundle import ReleasePolicyConfig
from veritool_rl.retail_ops.evaluate.base_evaluation import ModelArtifact
from veritool_rl.retail_ops.evaluate.candidate_evaluation import AdapterArtifact
from veritool_rl.retail_ops.evaluate.sealed_evaluation import (
    DeploymentForm,
    SealedEvaluationReport,
    require_comparable_sealed_runs,
)
from veritool_rl.retail_ops.release.release import (
    GATE_IDS_BY_SCHEMA,
    GateResult,
    GateSchemaVersion,
    ReleaseDecision,
    build_release_gates,
)


class FormalReleaseReport(StrictModel):
    """封存 holdout 配对证据产生的完整 GO/NO-GO 结论。

    `deployment` 是可执行的回滚指令而不是描述性字段：`serve` 按它选择加载
    base+adapter 还是回滚到冻结 base，因此它与 `decision` 的一致性由模型校验
    强制，不能被调用方单独改写。
    """

    schema_version: GateSchemaVersion = "1.0"
    decision: ReleaseDecision
    deployment: Literal["candidate", "baseline"]
    policy_version: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    split: Literal["holdout"] = "holdout"
    task_count: int = Field(ge=1)
    base_report_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_report_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    holdout_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    holdout_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_id: str = Field(min_length=1)
    evaluator_id: str = Field(min_length=1)
    code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    uv_lock_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    #: 基座模型。**回滚永远回到它**，与候选是什么形态无关。
    model: ModelArtifact
    #: 候选的 adapter。合并形态下为 `None`——合并之后已经没有 adapter 可挂。
    adapter: AdapterArtifact | None = None
    #: 候选自己的权重。只有合并形态才有：那时候选是**另一份模型**而不是
    #: "基座 + 旁路"，`serve` 必须知道 GO 时该加载哪一份。
    candidate_model: ModelArtifact | None = None
    #: 候选的部署形态。旧报告没有这个字段（`None`），语义等同 base_plus_adapter。
    deployment_form: DeploymentForm | None = None
    generation: GenerationSettings
    base_policy_id: str = Field(min_length=1)
    candidate_policy_id: str = Field(min_length=1)
    gates: list[GateResult]
    failed_gate_ids: list[str]
    base_metrics: dict[str, Any]
    candidate_metrics: dict[str, Any]

    _validate_metrics = field_validator("base_metrics", "candidate_metrics")(validate_json_value)

    @model_validator(mode="after")
    def validate_decision_consistency(self) -> Self:
        """门禁集合、失败项、结论与部署选择必须互相一致。"""
        if tuple(gate.gate_id for gate in self.gates) != GATE_IDS_BY_SCHEMA[self.schema_version]:
            raise ValueError("发布门禁集合或顺序不符合冻结契约")
        failed = [gate.gate_id for gate in self.gates if not gate.passed]
        if failed != self.failed_gate_ids:
            raise ValueError("failed_gate_ids 与 gate 结果不一致")
        expected_decision = ReleaseDecision.NO_GO if failed else ReleaseDecision.GO
        expected_deployment = "baseline" if failed else "candidate"
        if self.decision is not expected_decision or self.deployment != expected_deployment:
            raise ValueError("发布结论、失败门禁与 deployment 不一致")
        if self.deployment_form is DeploymentForm.MERGED:
            if self.adapter is not None:
                raise ValueError("合并形态的发布报告不得声明 adapter")
            if self.candidate_model is None:
                raise ValueError("合并形态必须声明 candidate_model，否则 serve 不知道加载哪份权重")
        else:
            if self.adapter is None:
                raise ValueError("base_plus_adapter 形态的发布报告必须声明 adapter")
            if self.candidate_model is not None:
                raise ValueError("只有合并形态才能声明 candidate_model")
        return self


def decide_formal_release(
    base: SealedEvaluationReport,
    candidate: SealedEvaluationReport,
    policy: ReleasePolicyConfig,
    *,
    gate_schema_version: GateSchemaVersion = "1.0",
    paired_outcomes: Sequence[tuple[bool, bool]] | None = None,
) -> FormalReleaseReport:
    """在证明两份 sealed 报告可配对后，按冻结策略给出 GO/NO-GO。

    配对校验在门禁计算**之前**：契约不一致时直接抛错，绝不产出一份带警告的
    发布报告——那种报告会被直接抄进交付材料。

    `gate_schema_version` **默认 v1.0**：磁盘上两次 NO-GO 判定就是它得出的，
    改默认值会让历史结论与新口径复算结论无法区分。v1.1 的语义见
    `release.GATE_IDS_V1_1`。
    """
    require_comparable_sealed_runs(base, candidate)

    evidence_complete = base.evidence_complete and candidate.evidence_complete
    gates = build_release_gates(
        base.metrics,
        candidate.metrics,
        evidence_complete=evidence_complete,
        policy=policy,
        schema_version=gate_schema_version,
        paired_outcomes=paired_outcomes,
    )
    failed_gate_ids = [gate.gate_id for gate in gates if not gate.passed]
    decision = ReleaseDecision.NO_GO if failed_gate_ids else ReleaseDecision.GO
    return FormalReleaseReport(
        schema_version=gate_schema_version,
        decision=decision,
        deployment="baseline" if failed_gate_ids else "candidate",
        policy_version=policy.policy_version,
        dataset_version=base.dataset_version,
        task_count=base.task_count,
        base_report_id=base.report_id,
        candidate_report_id=candidate.report_id,
        bundle_sha256=base.bundle_sha256,
        holdout_artifact_sha256=base.holdout_artifact_sha256,
        holdout_receipt_sha256=base.holdout_receipt_sha256,
        parser_id=base.parser_id,
        evaluator_id=base.evaluator_id,
        code_commit=base.code_commit,
        uv_lock_sha256=base.uv_lock_sha256,
        model=base.model,
        adapter=candidate.adapter,
        candidate_model=candidate.model if _is_merged(candidate) else None,
        deployment_form=candidate.deployment_form,
        generation=base.generation,
        base_policy_id=base.policy_id,
        candidate_policy_id=candidate.policy_id,
        gates=gates,
        failed_gate_ids=failed_gate_ids,
        base_metrics=base.metrics,
        candidate_metrics=candidate.metrics,
    )


def _is_merged(report: SealedEvaluationReport) -> bool:
    return report.deployment_form is DeploymentForm.MERGED


def write_formal_release_report(report: FormalReleaseReport, output_dir: Path) -> None:
    """向新目录写稳定的 JSON、Markdown 与 HTML 发布报告。"""
    create_output_dir(output_dir)
    write_json(output_dir / "release.json", report.model_dump(mode="json"))
    (output_dir / "report.md").write_text(_render_markdown(report), encoding="utf-8")
    (output_dir / "report.html").write_text(_render_html(report), encoding="utf-8")


def load_formal_release_report(path: Path) -> FormalReleaseReport:
    """读取并严格校验封存 holdout 的发布报告。"""
    return FormalReleaseReport.model_validate_json(path.read_text(encoding="utf-8"))


def _rollback_note(report: FormalReleaseReport) -> str:
    if report.deployment == "candidate":
        return "候选通过全部门禁，服务加载 base+adapter；回滚路径是重新部署冻结 base。"
    return "候选未通过发布门禁，服务必须回滚并只加载冻结 base，不得加载 adapter。"


def _render_markdown(report: FormalReleaseReport) -> str:
    lines = [
        "# RetailAgentOps 发布报告（封存 holdout）",
        "",
        f"- 决策：`{report.decision.value}`",
        f"- 部署：`{report.deployment}`",
        f"- 回滚：{_escape_text(_rollback_note(report))}",
        f"- 数据集：`{_escape_text(report.dataset_version)}`（{report.task_count} 条 holdout）",
        f"- 策略版本：`{_escape_text(report.policy_version)}`",
        f"- 基座策略：`{_escape_text(report.base_policy_id)}`",
        f"- 候选策略：`{_escape_text(report.candidate_policy_id)}`",
        f"- Bundle SHA-256：`{report.bundle_sha256}`",
        f"- Holdout artifact SHA-256：`{report.holdout_artifact_sha256}`",
        f"- 代码 commit：`{report.code_commit}`",
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
    base_headline, base_diagnostic = split_headline_and_diagnostic(report.base_metrics)
    candidate_headline, candidate_diagnostic = split_headline_and_diagnostic(
        report.candidate_metrics
    )
    lines.extend(
        [
            "",
            "## 配对指标",
            "",
            f"- 基座：`{_escape_text(canonical_json(base_headline))}`",
            f"- 候选：`{_escape_text(canonical_json(candidate_headline))}`",
            "",
            "## 诊断量",
            "",
            DIAGNOSTIC_NOTE,
            "",
            f"- 基座：`{_escape_text(canonical_json(base_diagnostic))}`",
            f"- 候选：`{_escape_text(canonical_json(candidate_diagnostic))}`",
            "",
        ]
    )
    return "\n".join(lines)


def _render_html(report: FormalReleaseReport) -> str:
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
    base_headline, base_diagnostic = split_headline_and_diagnostic(report.base_metrics)
    candidate_headline, candidate_diagnostic = split_headline_and_diagnostic(
        report.candidate_metrics
    )
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        "<title>RetailAgentOps 发布报告（封存 holdout）</title></head><body>"
        "<h1>RetailAgentOps 发布报告（封存 holdout）</h1>"
        f"<p>决策：<strong>{html.escape(report.decision.value)}</strong></p>"
        f"<p>部署：{html.escape(report.deployment)}</p>"
        f"<p>回滚：{html.escape(_rollback_note(report))}</p>"
        f"<p>数据集：{html.escape(report.dataset_version)}"
        f"（{report.task_count} 条 holdout）</p>"
        f"<p>基座策略：{html.escape(report.base_policy_id)}</p>"
        f"<p>候选策略：{html.escape(report.candidate_policy_id)}</p>"
        f"<p>Bundle SHA-256：<code>{report.bundle_sha256}</code></p>"
        f"<p>Holdout artifact SHA-256：<code>{report.holdout_artifact_sha256}</code></p>"
        f"<p>代码 commit：<code>{report.code_commit}</code></p>"
        "<h2>发布门禁</h2><table><thead><tr><th>门禁</th><th>通过</th>"
        "<th>观测值</th><th>阈值</th><th>说明</th></tr></thead>"
        f"<tbody>{gate_rows}</tbody></table>"
        "<h2>配对指标</h2>"
        f"<h3>基座</h3><pre>{html.escape(canonical_json(base_headline))}</pre>"
        f"<h3>候选</h3><pre>{html.escape(canonical_json(candidate_headline))}</pre>"
        "<h2>诊断量</h2>"
        f"<p>{html.escape(DIAGNOSTIC_NOTE)}</p>"
        f"<h3>基座</h3><pre>{html.escape(canonical_json(base_diagnostic))}</pre>"
        f"<h3>候选</h3><pre>{html.escape(canonical_json(candidate_diagnostic))}</pre>"
        "</body></html>\n"
    )


def _escape_text(value: str) -> str:
    return html.escape(value, quote=False).replace("|", "&#124;").replace("`", "&#96;")
