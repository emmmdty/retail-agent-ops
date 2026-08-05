"""RetailOps R2 sealed formal holdout evaluator contract.

唯一入口 `evaluate_authorized_holdout` 只接受 `AuthorizedFormalHoldout`——
该能力对象只能由 release 目的的两段式授权签发，因此这里不存在任何开发用途
的 holdout 入口。完整轨迹与逐任务证据只写入授权时使用的受信私有根，公开侧
只输出固定 allowlist 的聚合指标、运行 provenance 和失败 taxonomy 计数。

评测机器（路径防护、staging 原子发布、产物哈希、episode/replay 执行）与
`base_evaluation` 共享同一份实现，模块私有名的跨模块复用沿用本包既有约定
（参见 `formal_governance` 复用 `formal_manifests._parse_and_validate_private_rows`）。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator

from veritool_rl.agent.qwen import GenerationBackend, QwenPolicy
from veritool_rl.agent.runner import SYSTEM_PROMPT
from veritool_rl.artifacts import write_json
from veritool_rl.eval.metrics import compute_metrics
from veritool_rl.paths import validate_project_relative_path
from veritool_rl.retail_ops.base_evaluation import (
    _ID_PLACEHOLDER,
    BASE_ARTIFACT_NAMES,
    _category_counts,
    _content_id,
    _content_sha256,
    _evidence_complete,
    _finalize_evidence,
    _require_matching_bundle,
    _resolve_within,
    _text_sha256,
    _tool_schema_sha256,
    _validate_artifact_hashes,
    _validate_output_pair,
    _validate_path_component,
    _verify_artifact_hashes,
    execute_formal_records,
    publish_run_evidence,
    write_run_artifacts,
)
from veritool_rl.retail_ops.bundle import LoadedRetailOpsBundle
from veritool_rl.retail_ops.evaluation import redact_failure_rows
from veritool_rl.retail_ops.formal_governance import (
    AuthorizedFormalHoldout,
    load_authorized_formal_holdout,
)
from veritool_rl.retail_ops.formal_tasks import FormalTaskRecord
from veritool_rl.trajectory.schema import StrictModel, validate_json_value

# sealed 评测写出与 dev base 完全相同的四份私有产物。
SEALED_ARTIFACT_NAMES = BASE_ARTIFACT_NAMES

_MAX_STEPS = 5
_BOOTSTRAP_SAMPLES = 1000
_SEALED_EVIDENCE_DIR = "sealed-eval"


class SealedEvaluationReport(StrictModel):
    """sealed holdout 运行的公开 allowlist 报告。

    字段集合是固定白名单：只有聚合指标、运行 provenance 和失败 taxonomy 计数。
    这里不存在 task/family 标识、任何 opaque 指纹、prompt、真值或逐任务失败样例。
    """

    schema_version: Literal["1.0"] = "1.0"
    report_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    purpose: Literal["release"] = "release"
    split: Literal["holdout"] = "holdout"
    dataset_version: str = Field(min_length=1)
    generator_id: str = Field(min_length=1)
    bundle_id: str = Field(min_length=1)
    bundle_version: str = Field(min_length=1)
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_id: str = Field(min_length=1)
    evaluator_id: str = Field(min_length=1)
    seed: int = Field(ge=0)
    policy_id: str = Field(min_length=1)
    max_new_tokens: int = Field(ge=1)
    max_steps: Literal[5] = 5
    task_count: int = Field(ge=1)
    category_counts: dict[str, int]
    holdout_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    holdout_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    system_prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tool_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    metrics: dict[str, Any]
    failure_type_counts: dict[str, int]
    failure_category_counts: dict[str, int]
    failure_last_error_counts: dict[str, int]
    failure_violation_counts: dict[str, int]
    replayable_count: int = Field(ge=0)
    evidence_complete: bool
    private_artifact_sha256: dict[str, str]

    _validate_json_fields = field_validator("metrics")(validate_json_value)

    @field_validator("private_artifact_sha256")
    @classmethod
    def validate_artifact_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        """产物集合固定，路径不可注入，摘要必须是 SHA-256。"""
        return _validate_artifact_hashes(value, SEALED_ARTIFACT_NAMES)


def evaluate_authorized_holdout(
    authorization: AuthorizedFormalHoldout,
    bundle: LoadedRetailOpsBundle,
    backend: GenerationBackend,
    *,
    model_name: str,
    attempt_id: str,
    public_report_path: Path,
    max_new_tokens: int = 256,
) -> SealedEvaluationReport:
    """在已授权的 sealed formal holdout 上运行一次评测并写出双侧证据。

    私有证据固定写到授权时使用的 `trusted_private_root` 下的
    `sealed-eval/<attempt_id>/`：调用方无法把完整轨迹重定向到公开路径。
    公开报告只写 `SealedEvaluationReport` 的 allowlist 字段。
    """
    records = load_authorized_formal_holdout(authorization)
    receipt = authorization.dataset.holdout_receipt
    _require_matching_bundle(bundle, receipt)
    _require_step_budget(records)

    if not model_name:
        msg = "sealed 评测 model_name 不得为空"
        raise ValueError(msg)
    validate_project_relative_path(model_name, "sealed 评测 model_name")
    _validate_path_component(attempt_id, label="attempt_id")
    private_target = _resolve_within(
        authorization.trusted_private_root,
        _SEALED_EVIDENCE_DIR,
        attempt_id,
    )
    _validate_output_pair(authorization.trusted_private_root, public_report_path)

    policy = QwenPolicy(backend, model_name, max_new_tokens)
    trajectories, replayed = execute_formal_records(records, bundle, policy, receipt.seed)
    metrics = compute_metrics(trajectories, _BOOTSTRAP_SAMPLES, receipt.seed)
    failure_rows = redact_failure_rows(trajectories)
    receipt_sha256 = _content_sha256(receipt.model_dump(mode="json"))
    prompt_sha256 = _text_sha256(SYSTEM_PROMPT)
    tools_sha256 = _tool_schema_sha256(bundle)
    run_config = {
        "dataset_version": receipt.dataset_version,
        "split": receipt.split,
        "seed": receipt.seed,
        "purpose": "release",
        "policy_id": policy.name,
        "max_new_tokens": max_new_tokens,
        "max_steps": _MAX_STEPS,
        "bundle_sha256": bundle.bundle_sha256,
        "holdout_artifact_sha256": authorization.artifact_sha256,
        "holdout_receipt_sha256": receipt_sha256,
        "parser_id": receipt.parser_id,
        "system_prompt_sha256": prompt_sha256,
        "tool_schema_sha256": tools_sha256,
    }

    def build(staging: Path) -> SealedEvaluationReport:
        artifact_sha256 = write_run_artifacts(staging, run_config, trajectories, metrics)
        report = _finalize_evidence(
            SealedEvaluationReport(
                report_id=_ID_PLACEHOLDER,
                dataset_version=receipt.dataset_version,
                generator_id=receipt.generator_id,
                bundle_id=receipt.bundle_id,
                bundle_version=receipt.bundle_version,
                bundle_sha256=receipt.bundle_sha256,
                parser_id=receipt.parser_id,
                evaluator_id=receipt.evaluator_id,
                seed=receipt.seed,
                policy_id=policy.name,
                max_new_tokens=max_new_tokens,
                task_count=len(trajectories),
                category_counts=_category_counts(trajectories, receipt),
                holdout_artifact_sha256=authorization.artifact_sha256,
                holdout_receipt_sha256=receipt_sha256,
                system_prompt_sha256=prompt_sha256,
                tool_schema_sha256=tools_sha256,
                metrics=metrics,
                failure_type_counts=_count_rows(failure_rows, "failure_type"),
                failure_category_counts=_count_rows(failure_rows, "category"),
                failure_last_error_counts=_count_rows(failure_rows, "last_error"),
                failure_violation_counts=_count_violations(failure_rows),
                replayable_count=replayed,
                evidence_complete=_evidence_complete(trajectories, replayed),
                private_artifact_sha256=artifact_sha256,
            ),
            "report_id",
        )
        write_json(staging / "report.json", report.model_dump(mode="json"))
        return report

    return publish_run_evidence(
        private_target=private_target,
        public_report_path=public_report_path,
        build=build,
    )


def load_sealed_evaluation_report(
    path: Path,
    *,
    verify_artifacts: bool = True,
) -> SealedEvaluationReport:
    """读取 sealed 报告并重算 report_id；默认同时校验同目录私有产物哈希。

    公开侧只有报告副本、没有私有产物，加载公开副本时应显式传入
    `verify_artifacts=False`，不要静默跳过校验。
    """
    report = SealedEvaluationReport.model_validate_json(path.read_text(encoding="utf-8"))
    if _content_id(report, "report_id") != report.report_id:
        msg = "sealed 评测报告 report_id 不匹配"
        raise ValueError(msg)
    if verify_artifacts:
        _verify_artifact_hashes(path.parent, report.private_artifact_sha256)
    return report


def _require_step_budget(records: Sequence[FormalTaskRecord]) -> None:
    for index, record in enumerate(records):
        if record.task.max_steps > _MAX_STEPS:
            msg = f"sealed 评测记录 {index} 的 max_steps 超出冻结预算"
            raise ValueError(msg)


def _count_rows(rows: Sequence[dict[str, Any]], field: str) -> dict[str, int]:
    counts = Counter(str(row.get(field) or "none") for row in rows)
    return dict(sorted(counts.items()))


def _count_violations(rows: Sequence[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts.update(str(violation) for violation in row.get("violations", ()))
    return dict(sorted(counts.items()))
