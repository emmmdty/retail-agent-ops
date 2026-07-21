"""RetailOps qualification 评测、证据哈希与公开失败脱敏。"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator

from veritool_rl.agent.runner import run_episode
from veritool_rl.artifacts import (
    canonical_json,
    create_output_dir,
    sha256_file,
    write_json,
    write_jsonl,
    write_yaml,
)
from veritool_rl.eval.metrics import compute_metrics
from veritool_rl.retail_ops.bundle import load_bundle
from veritool_rl.retail_ops.environment import RetailOpsEnv
from veritool_rl.retail_ops.manifests import (
    TaskManifest,
    load_built_tasks,
    load_task_manifest,
)
from veritool_rl.retail_ops.policies import build_qualification_policy
from veritool_rl.trajectory import TaskScenario, TaskSpec, TerminationReason, Trajectory
from veritool_rl.trajectory.replay import replay_trajectory
from veritool_rl.trajectory.schema import StrictModel, validate_json_value

_ARTIFACT_NAMES = (
    "config.yaml",
    "trajectories.jsonl",
    "metrics.json",
    "failures.jsonl",
    "log.txt",
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_PUBLIC_ERROR_CODES = {
    "format_error",
    "invalid_arguments",
    "not_found",
    "policy_denied",
    "transient_error",
    "unknown_tool",
}
_PUBLIC_VIOLATION_CODES = {
    "duplicate_refund",
    "refund_not_eligible",
    "refund_without_lookup",
    "unauthorized_order",
}


class EvaluationMode(StrEnum):
    """R1 允许的非 holdout 评测用途。"""

    QUALIFICATION = "qualification"
    DEVELOPMENT = "development"


class RunEvidence(StrictModel):
    """绑定 bundle、任务 manifest 与逐项产物哈希的评测清单。"""

    schema_version: Literal["1.0"] = "1.0"
    run_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    mode: EvaluationMode
    policy_type: str = Field(min_length=1)
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluator_id: Literal["retail_ops_v1"] = "retail_ops_v1"
    seed: int
    parser_id: str = Field(min_length=1)
    budget: dict[str, Any]
    task_count: int = Field(ge=1)
    metrics: dict[str, Any]
    evidence_complete: bool
    artifact_sha256: dict[str, str]

    _validate_json_fields = field_validator("budget", "metrics")(validate_json_value)

    @field_validator("artifact_sha256")
    @classmethod
    def validate_artifact_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        """产物集合固定，路径不可注入，摘要必须是 SHA-256。"""
        if set(value) != set(_ARTIFACT_NAMES):
            raise ValueError("评测证据产物集合不符合冻结契约")
        if any(_SHA256_PATTERN.fullmatch(digest) is None for digest in value.values()):
            raise ValueError("评测证据产物摘要必须是 SHA-256")
        return value


def evaluate_retail_ops(
    bundle_dir: Path,
    build_dir: Path,
    policy_type: str,
    config: dict[str, Any],
    seed: int,
    output_dir: Path,
    mode: EvaluationMode,
) -> RunEvidence:
    """运行非 holdout RetailOps 评测并写出不可覆盖、可重放证据。"""
    bundle = load_bundle(bundle_dir)
    manifest_path = build_dir / "manifest.json"
    manifest = load_task_manifest(manifest_path)
    _validate_evaluation_contract(manifest, bundle.bundle_sha256, seed, mode)

    parser_id = config.get("parser_id")
    budget = config.get("budget")
    if not isinstance(parser_id, str) or not parser_id:
        raise ValueError("parser_id 必须是非空字符串")
    if not isinstance(budget, dict):
        raise ValueError("budget 必须是 mapping")
    validate_json_value(config)

    tasks_by_id = load_built_tasks(build_dir)
    tasks = list(tasks_by_id.values())
    if any(task.split != manifest.split for task in tasks):
        raise ValueError("任务 split 与 manifest 不一致")
    _validate_task_coverage(manifest, tasks, bundle.bundle.task_categories)

    trajectories: list[Trajectory] = []
    for task in tasks:
        policy_task = (
            task
            if mode is EvaluationMode.QUALIFICATION
            else task.model_copy(update={"split": "qualification"})
        )
        trajectories.append(
            run_episode(
                task,
                lambda current: RetailOpsEnv(current, bundle),
                build_qualification_policy(policy_type, policy_task),
                seed,
            )
        )
    replayed = sum(
        replay_trajectory(
            trajectory,
            lambda current: RetailOpsEnv(current, bundle),
        ).matched
        for trajectory in trajectories
    )
    if [trajectory.task.task_id for trajectory in trajectories] != manifest.task_ids:
        raise ValueError("评测轨迹任务集合或顺序与 manifest 不一致")

    bootstrap_samples = config.get("bootstrap_samples", 1000)
    if not isinstance(bootstrap_samples, int) or isinstance(bootstrap_samples, bool):
        raise ValueError("bootstrap_samples 必须是整数")
    metrics = compute_metrics(trajectories, bootstrap_samples, seed)
    metrics["replayable_count"] = replayed
    metrics["replayable_rate"] = replayed / manifest.task_count
    evidence_complete = len(trajectories) == manifest.task_count == replayed and all(
        trajectory.steps for trajectory in trajectories
    )

    manifest_sha256 = sha256_file(manifest_path)
    run_config = {
        **config,
        "bundle_sha256": bundle.bundle_sha256,
        "mode": mode.value,
        "policy_type": policy_type,
        "seed": seed,
        "task_manifest_sha256": manifest_sha256,
    }
    create_output_dir(output_dir)
    write_yaml(output_dir / "config.yaml", run_config)
    write_jsonl(
        output_dir / "trajectories.jsonl",
        (trajectory.model_dump(mode="json") for trajectory in trajectories),
    )
    write_json(output_dir / "metrics.json", metrics)
    write_jsonl(output_dir / "failures.jsonl", redact_failure_rows(trajectories))
    (output_dir / "log.txt").write_text(
        f"完成 {len(trajectories)} 条评测；成功 {sum(t.success for t in trajectories)} 条；"
        f"重放 {replayed} 条。\n",
        encoding="utf-8",
    )
    artifact_sha256 = {name: sha256_file(output_dir / name) for name in _ARTIFACT_NAMES}
    evidence_values: dict[str, Any] = {
        "mode": mode,
        "policy_type": policy_type,
        "bundle_sha256": bundle.bundle_sha256,
        "task_manifest_sha256": manifest_sha256,
        "evaluator_id": bundle.bundle.evaluator_id,
        "seed": seed,
        "parser_id": parser_id,
        "budget": budget,
        "task_count": manifest.task_count,
        "metrics": metrics,
        "evidence_complete": evidence_complete,
        "artifact_sha256": artifact_sha256,
    }
    evidence = RunEvidence(
        run_id=_run_id(evidence_values),
        **evidence_values,
    )
    write_json(output_dir / "run.json", evidence.model_dump(mode="json"))
    return evidence


def load_run_evidence(path: Path) -> RunEvidence:
    """读取评测清单并验证清单自身及所有同目录产物。"""
    evidence = RunEvidence.model_validate_json(path.read_text(encoding="utf-8"))
    values = evidence.model_dump(mode="python", exclude={"run_id", "schema_version"})
    if _run_id(values) != evidence.run_id:
        raise ValueError("评测证据 run_id 不匹配")
    for name, expected in evidence.artifact_sha256.items():
        artifact = path.parent / name
        try:
            actual = sha256_file(artifact)
        except OSError as error:
            raise ValueError(f"无法读取评测证据产物: {name}") from error
        if actual != expected:
            raise ValueError(f"评测证据 SHA-256 不匹配: {name}")
    return evidence


def redact_failure_rows(
    trajectories: Sequence[Trajectory],
) -> list[dict[str, Any]]:
    """从固定允许列表构造公开失败摘要，不复制轨迹或任务真值。"""
    rows: list[dict[str, Any]] = []
    for trajectory in trajectories:
        if trajectory.success:
            continue
        last_error = _last_error_code(trajectory)
        rows.append(
            {
                "category": trajectory.task.scenario.value,
                "failure_type": _retail_failure_type(trajectory),
                "last_error": last_error,
                "termination": trajectory.termination.value,
                "violations": [
                    violation
                    if violation in _PUBLIC_VIOLATION_CODES
                    else "unknown_policy_violation"
                    for violation in trajectory.violations
                ],
            }
        )
    return rows


def _validate_evaluation_contract(
    manifest: TaskManifest,
    bundle_sha256: str,
    seed: int,
    mode: EvaluationMode,
) -> None:
    if manifest.split == "holdout":
        raise PermissionError("R1 evaluate 禁止读取 holdout manifest")
    expected_split = "qualification" if mode is EvaluationMode.QUALIFICATION else "dev"
    if manifest.split != expected_split:
        raise ValueError(f"{mode.value} 模式要求 {expected_split} manifest")
    if manifest.bundle_sha256 != bundle_sha256:
        raise ValueError("任务 manifest 与 bundle SHA-256 不匹配")
    if manifest.seed != seed:
        raise ValueError("评测 seed 与任务 manifest 不一致")


def _validate_task_coverage(
    manifest: TaskManifest,
    tasks: Sequence[TaskSpec],
    categories: Sequence[str],
) -> None:
    actual_counts = Counter(task.scenario.value for task in tasks)
    ordered_counts = {category: actual_counts[category] for category in categories}
    if set(actual_counts) != set(categories) or ordered_counts != manifest.category_counts:
        raise ValueError("任务类别覆盖与 manifest 不一致")
    family_ids = [task.metadata.get("family_id") for task in tasks]
    if (
        any(not isinstance(family_id, str) or not family_id for family_id in family_ids)
        or len(set(family_ids)) != len(family_ids)
        or family_ids != manifest.family_ids
    ):
        raise ValueError("任务 family_id 覆盖与 manifest 不一致")


def _run_id(values: dict[str, Any]) -> str:
    payload = canonical_json(_json_ready(values))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_ready(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    return value


def _last_error_code(trajectory: Trajectory) -> str | None:
    for step in reversed(trajectory.steps):
        if step.parse_error is not None:
            return "format_error"
        if step.observation is not None and step.observation.error_code is not None:
            code = step.observation.error_code
            return code if code in _PUBLIC_ERROR_CODES else "environment_error"
    return None


def _retail_failure_type(trajectory: Trajectory) -> str:
    if trajectory.violations:
        return "policy_violation"
    if any(step.parse_error is not None for step in trajectory.steps):
        return "parser_format"
    error_codes = {
        step.observation.error_code
        for step in trajectory.steps
        if step.observation is not None and step.observation.error_code is not None
    }
    if "unknown_tool" in error_codes:
        return "tool_selection"
    if "invalid_arguments" in error_codes:
        return "argument_schema"
    if trajectory.task.scenario is TaskScenario.REFUND_RECOVERY:
        return "recovery_failure"
    if trajectory.termination is TerminationReason.STEP_LIMIT:
        return "step_limit"
    if trajectory.termination is TerminationReason.INTERNAL_ERROR:
        return "environment_error"
    return "verifier_failure"
