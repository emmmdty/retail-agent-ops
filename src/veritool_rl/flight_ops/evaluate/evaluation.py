"""FlightOps v1 dev evaluation — run model on dev tasks, compute metrics, write report.

Uses core.metrics.compute_metrics (generic) and core.agent.runner.run_episode
for model inference. The report structure mirrors retail_ops: a self-hashing
``report_id`` binds all fields so any tampering is detectable at load time.

This module runs on CPU but calls the model (which needs GPU for inference).
The GPU runs are orchestrated remotely with precise manifests per task_plan R8 D2.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field

from veritool_rl.core.agent.runner import run_episode
from veritool_rl.core.artifacts import canonical_json
from veritool_rl.core.envs.base import ToolEnv
from veritool_rl.core.metrics import compute_metrics
from veritool_rl.core.trajectory import TaskSpec, Trajectory
from veritool_rl.core.trajectory.schema import StrictModel
from veritool_rl.flight_ops.domain.tasks import FlightTaskSet

EnvFactory = Callable[[TaskSpec], ToolEnv]
PolicyFactory = Callable[[TaskSpec], Any]


class FlightEvalConfig(StrictModel):
    """Config for a single evaluation run."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, frozen=True)

    dataset_version: str = Field(min_length=1)
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    seed: int = Field(ge=0)
    split: str = "dev"
    model_name: str = Field(min_length=1)
    adapter_path: str | None = None
    inference_engine: str = "transformers"


class FlightRunEvidence(StrictModel):
    """Evaluation run evidence with self-hashing report_id."""

    report_id: str = Field(min_length=1)
    config: FlightEvalConfig
    task_count: int = Field(ge=0)
    trajectories_file: str | None = None
    metrics: dict[str, Any]
    policy_violation_count: int = Field(ge=0)
    invalid_call_count: int = Field(ge=0)
    tool_selection_accuracy: float = Field(ge=0.0, le=1.0)
    task_success: float = Field(ge=0.0, le=1.0)
    runtime_seconds: float = Field(ge=0.0)

    @classmethod
    def compute_report_id(cls, payload: dict[str, Any]) -> str:
        content = canonical_json(payload).encode("utf-8")
        return hashlib.sha256(content).hexdigest()


def run_evaluation(
    config: FlightEvalConfig,
    task_set: FlightTaskSet,
    policy_factory: PolicyFactory,
    env_factory: EnvFactory,
    *,
    output_dir: Path,
    bootstrap_samples: int = 1000,
    bootstrap_seed: int = 42,
) -> FlightRunEvidence:
    """Run evaluation on the specified split, compute metrics, write evidence.

    Returns the FlightRunEvidence with a self-hashing report_id.
    """
    records = task_set.records(config.split)
    trajectories: list[Trajectory] = []
    policy_violations = 0
    invalid_calls = 0
    t0 = time.monotonic()

    for record in records:
        policy = policy_factory(record.task)
        traj = run_episode(record.task, env_factory, policy, seed=config.seed)
        trajectories.append(traj)
        if traj.violations:
            policy_violations += 1
        for step in traj.steps:
            if step.observation is not None and step.observation.error_code in {
                "unknown_tool",
                "invalid_arguments",
                "format_error",
            }:
                invalid_calls += 1

    elapsed = time.monotonic() - t0

    metrics = compute_metrics(
        trajectories, bootstrap_samples=bootstrap_samples, seed=bootstrap_seed
    )
    task_success = float(metrics.get("task_success", 0.0))

    # Tool selection accuracy: expected_calls matched correctly / total expected_calls
    correct_tools = 0
    total_expected = 0
    for traj in trajectories:
        expected = traj.task.expected_calls
        actual_calls = [s.tool_call for s in traj.steps if s.tool_call is not None]
        total_expected += max(len(actual_calls), len(expected))
        for i, exp in enumerate(expected):
            if i < len(actual_calls) and actual_calls[i].name == exp.name:
                correct_tools += 1
    tool_selection_accuracy = correct_tools / total_expected if total_expected > 0 else 0.0

    # Write trajectories JSONL
    output_dir.mkdir(parents=True, exist_ok=True)
    traj_path = output_dir / "trajectories.jsonl"
    with traj_path.open("w", encoding="utf-8") as f:
        for traj in trajectories:
            f.write(traj.model_dump_json() + "\n")

    # Build evidence payload for report_id (exclude runtime_seconds — wall clock
    # is not reproducible, so it must not enter the tamper-evident hash).
    evidence_payload = {
        "config": config.model_dump(mode="json"),
        "task_count": len(records),
        "trajectories_file": "trajectories.jsonl",
        "metrics": metrics,
        "policy_violation_count": policy_violations,
        "invalid_call_count": invalid_calls,
        "tool_selection_accuracy": tool_selection_accuracy,
        "task_success": task_success,
    }
    report_id = FlightRunEvidence.compute_report_id(evidence_payload)

    evidence = FlightRunEvidence(
        report_id=report_id,
        config=config,
        task_count=len(records),
        trajectories_file="trajectories.jsonl",
        metrics=metrics,
        policy_violation_count=policy_violations,
        invalid_call_count=invalid_calls,
        tool_selection_accuracy=tool_selection_accuracy,
        task_success=task_success,
        runtime_seconds=elapsed,
    )

    # Write report JSON
    report_path = output_dir / "report.json"
    report_path.write_text(
        json.dumps(evidence.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return evidence
