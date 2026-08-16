"""构造合法 `SealedEvaluationReport` 的测试夹具。

只在测试里用。`report_id` 由 `sealed_content_id` 按报告自身的 schema 版本回填，
因此这里造出来的报告与真实产出的报告走同一条自哈希路径。
"""

from __future__ import annotations

from typing import Any

from veritool_rl.core.agent.qwen import (
    GenerationSettings,
    GpuMeasurement,
    derive_merged_revision,
)
from veritool_rl.retail_ops.evaluate.base_evaluation import (
    HardwareProvenance,
    ModelArtifact,
)
from veritool_rl.retail_ops.evaluate.candidate_evaluation import AdapterArtifact
from veritool_rl.retail_ops.evaluate.sealed_evaluation import (
    SEALED_ARTIFACT_NAMES,
    MergedProvenance,
    SealedEvaluationReport,
    sealed_content_id,
)

BASE_REPO = "Qwen/Qwen3-4B"
BASE_REVISION = "8cd0101f70cac4f1efcebc979faf483558e39297"
ADAPTER_HASHES = {"adapter_model.safetensors": "8a49251f" + "0" * 56}


def merged_provenance(base_revision: str = BASE_REVISION) -> MergedProvenance:
    return MergedProvenance(
        base_repo=BASE_REPO,
        base_revision=base_revision,
        adapter_file_sha256=dict(ADAPTER_HASHES),
        merged_revision=derive_merged_revision(base_revision, ADAPTER_HASHES),
    )


def build_sealed_report(
    *,
    schema_version: str = "1.0",
    deployment_form: Any = None,
    adapter: Any = "unset",
    with_adapter: bool = False,
    merged: bool = False,
    merged_base_revision: str = BASE_REVISION,
    model_revision: str | None = None,
    **overrides: Any,
) -> SealedEvaluationReport:
    """造一份字段自洽的 sealed 报告。

    `adapter="unset"` 表示"按 `with_adapter` 推断"，显式传 `None` 表示"确实没有"。
    这个区分是必要的：多条测试正是要断言"该有 adapter 却没有"会被拒绝。
    """
    lineage = merged_provenance(merged_base_revision) if merged else None
    if model_revision is None:
        model_revision = lineage.merged_revision if merged else BASE_REVISION
    resolved_adapter = adapter
    if resolved_adapter == "unset":
        resolved_adapter = (
            AdapterArtifact(
                run_dir="reports/retail_ops/v1/r4/sft-006",
                file_sha256=dict(ADAPTER_HASHES),
            )
            if with_adapter
            else None
        )
    payload: dict[str, Any] = {
        "schema_version": schema_version,
        "report_id": "0" * 64,
        "dataset_version": "retail_ops_v1_r2_20260722",
        "generator_id": "family_sha256_v1",
        "bundle_id": "retail_ops",
        "bundle_version": "1.0.0",
        "bundle_sha256": "c" * 64,
        "parser_id": "hermes-single-call-v1",
        "evaluator_id": "retail_ops_v1",
        "seed": 0,
        "policy_id": "qwen:test",
        "task_count": 120,
        "category_counts": {"lookup_status": 20},
        "holdout_artifact_sha256": "d" * 64,
        "holdout_receipt_sha256": "e" * 64,
        "system_prompt_sha256": "f" * 64,
        "tool_schema_sha256": "1" * 64,
        "config_sha256": "2" * 64,
        "code_commit": "3" * 40,
        "uv_lock_sha256": "4" * 64,
        "model": ModelArtifact(
            repo="local/Qwen3-4B-sft-006-merged" if merged else BASE_REPO,
            revision=model_revision,
            # 合并产物是**另一个目录**里的另一份权重——这正是 serve 必须能区分的东西。
            local_dir="Qwen3-4B-sft-006-merged" if merged else "Qwen3-4B-pinned",
            file_sha256={"config.json": "5" * 64},
        ),
        "adapter": resolved_adapter,
        "generation": GenerationSettings(max_new_tokens=256),
        "hardware": HardwareProvenance(
            gpu=GpuMeasurement(
                gpu_index=0,
                gpu_uuid="GPU-00000000-0000-0000-0000-000000000000",
                gpu_name="test",
                cuda_visible_devices="0",
                cuda_device="cuda:0",
                peak_memory_bytes=1,
            ),
            wall_time_seconds=1.0,
            tasks_per_second=1.0,
            output_tokens_per_second=1.0,
        ),
        "metrics": {"task_success": 1.0},
        "failure_type_counts": {},
        "failure_category_counts": {},
        "failure_last_error_counts": {},
        "failure_violation_counts": {},
        "replayable_count": 120,
        "evidence_complete": True,
        "private_artifact_sha256": dict.fromkeys(SEALED_ARTIFACT_NAMES, "6" * 64),
        "deployment_form": deployment_form,
        "merged_from": lineage,
    }
    payload.update(overrides)
    report = SealedEvaluationReport.model_validate(payload)
    return report.model_copy(update={"report_id": sealed_content_id(report)})
