"""FlightOps v1 teacher collection — minimal orchestration over core primitives.

Mirrors retail_ops.build.teacher_data's *collection loop* structure but uses
core.build.teacher_client (lifted 2026-08-20) and core.agent.runner /
core.trajectory.replay. This is a domain-specific orchestration that *calls*
core abstractions, not a copy of teacher_data.py.

The evidence model (FlightTaskEvidence) stores the same治理 hashes as
TeacherAttemptEvidence but drops the 5-fingerprint fields that are retail-specific
(family_fingerprint, source_fingerprint, derivation_fingerprint). flight_ops v1
uses content_sha256 instead.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field

from veritool_rl.core.agent.policy import PolicyOutput
from veritool_rl.core.agent.runner import run_episode
from veritool_rl.core.build.teacher_client import (
    TeacherClient,
    TeacherClientError,
    TeacherResponse,
)
from veritool_rl.core.build.teacher_route import TeacherRouteSnapshot, load_teacher_route
from veritool_rl.core.envs.base import ToolEnv
from veritool_rl.core.generators import trajectory_to_sft_example
from veritool_rl.core.trajectory import TaskSpec, TerminationReason, Trajectory
from veritool_rl.core.trajectory.replay import ReplayMismatch, replay_trajectory
from veritool_rl.core.trajectory.schema import StrictModel

EnvFactory = Callable[[TaskSpec], ToolEnv]


class FlightAttemptOutcome(StrEnum):
    """Outcome categories for a teacher collection attempt."""

    SUCCESS = "success"
    SCHEMA_INVALID = "schema_invalid"
    ILLEGAL_TOOL = "illegal_tool"
    POLICY_VIOLATION = "policy_violation"
    STEP_LIMIT = "step_limit"
    WRONG_FINAL_STATE = "wrong_final_state"
    TRANSPORT_EXHAUSTED = "transport_exhausted"
    REPLAY_MISMATCH = "replay_mismatch"


class FlightTransportExhausted(RuntimeError):
    """Raised after exhausting max_request_attempts on retriable transport errors."""


class FlightCollectionConfig(StrictModel):
    """治理 hashes + budget params for one collection run."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, frozen=True)

    dataset_version: str = Field(min_length=1)
    seed: int = Field(ge=0)
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    route_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    max_episodes_per_task: int = Field(default=2, ge=1, le=2)
    max_request_attempts: int = Field(default=3, ge=1, le=3)

    @property
    def config_sha256(self) -> str:
        from veritool_rl.core.artifacts import canonical_json

        payload = {
            "dataset_version": self.dataset_version,
            "seed": self.seed,
            "bundle_sha256": self.bundle_sha256,
            "manifest_sha256": self.manifest_sha256,
            "route_sha256": self.route_sha256,
            "max_episodes_per_task": self.max_episodes_per_task,
            "max_request_attempts": self.max_request_attempts,
        }
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class FlightTaskEvidence(StrictModel):
    """One task collection attempt's full private evidence."""

    task_id: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_version: str = Field(min_length=1)
    seed: int = Field(ge=0)
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    route_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: FlightAttemptOutcome
    accepted: bool
    episode_index: int = Field(ge=0)
    request_attempts: int = Field(ge=0)
    usage_prompt_tokens: int = Field(ge=0)
    usage_completion_tokens: int = Field(ge=0)
    trajectory: Trajectory | None = None


class FlightCollectionCheckpoint(StrictModel):
    """Lightweight checkpoint for resume support."""

    dataset_version: str
    seed: int
    bundle_sha256: str
    manifest_sha256: str
    route_sha256: str
    config_sha256: str
    accepted_task_ids: tuple[str, ...] = ()


def _to_policy_output(response: TeacherResponse) -> PolicyOutput:
    if len(response.tool_calls) == 1:
        call = response.tool_calls[0]
        raw = json.dumps({"name": call.name, "arguments": call.arguments}, ensure_ascii=False)
        return PolicyOutput(raw_text=raw, tool_call=call)
    if len(response.tool_calls) > 1:
        return PolicyOutput(raw_text=repr(response.tool_calls), parse_error="multiple_tool_calls")
    if response.content:
        return PolicyOutput(raw_text=response.content, final_response=response.content)
    return PolicyOutput(raw_text="", parse_error="empty_response")


class _RetryingTeacherPolicy:
    """Wraps TeacherClient as a Policy with有限 retry on retriable transport errors."""

    name = "teacher"

    def __init__(self, client: TeacherClient, *, max_attempts: int) -> None:
        self._client = client
        self._max_attempts = max_attempts
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.request_attempts = 0

    def respond(
        self,
        messages: list[dict[str, Any]],
        tools: list[Any],
    ) -> PolicyOutput:
        last_error: TeacherClientError | None = None
        # Convert ToolSchema objects to dicts for the OpenAI-compatible API.
        tool_dicts = [t.to_transformers() if hasattr(t, "to_transformers") else t for t in tools]
        for _attempt in range(1, self._max_attempts + 1):
            self.request_attempts += 1
            try:
                response = self._client.complete(messages=messages, tools=tool_dicts)
                if response.usage is not None:
                    self.total_prompt_tokens += response.usage.prompt_tokens or 0
                    self.total_completion_tokens += response.usage.completion_tokens or 0
                return _to_policy_output(response)
            except TeacherClientError as exc:
                last_error = exc
                continue
        raise FlightTransportExhausted(
            f"Exhausted {self._max_attempts} attempts: {last_error}"
        ) from last_error


def _classify_outcome(trajectory: Trajectory) -> FlightAttemptOutcome:
    if trajectory.termination == TerminationReason.SUCCESS:
        return FlightAttemptOutcome.SUCCESS
    if trajectory.termination == TerminationReason.STEP_LIMIT:
        return FlightAttemptOutcome.STEP_LIMIT
    if trajectory.termination == TerminationReason.POLICY_VIOLATION:
        return FlightAttemptOutcome.POLICY_VIOLATION
    if trajectory.termination == TerminationReason.INTERNAL_ERROR:
        return FlightAttemptOutcome.WRONG_FINAL_STATE
    if trajectory.termination == TerminationReason.FINAL_RESPONSE and not trajectory.success:
        return FlightAttemptOutcome.WRONG_FINAL_STATE
    return FlightAttemptOutcome.WRONG_FINAL_STATE


def collect_flight_attempt(
    task: TaskSpec,
    content_sha256: str,
    client: TeacherClient,
    env_factory: EnvFactory,
    config: FlightCollectionConfig,
) -> FlightTaskEvidence:
    """Collect teacher trajectories for one task, with replay validation."""
    if task.split != "train":
        msg = f"teacher collection only handles train tasks, got {task.split!r}"
        raise ValueError(msg)

    last_outcome = FlightAttemptOutcome.STEP_LIMIT
    last_trajectory: Trajectory | None = None
    total_prompt = 0
    total_completion = 0
    total_attempts = 0

    for episode_index in range(config.max_episodes_per_task):
        policy = _RetryingTeacherPolicy(client, max_attempts=config.max_request_attempts)
        try:
            trajectory = run_episode(task, env_factory, policy, seed=config.seed)
        except FlightTransportExhausted:
            total_prompt += policy.total_prompt_tokens
            total_completion += policy.total_completion_tokens
            total_attempts += policy.request_attempts
            last_outcome = FlightAttemptOutcome.TRANSPORT_EXHAUSTED
            last_trajectory = None
            continue

        total_prompt += policy.total_prompt_tokens
        total_completion += policy.total_completion_tokens
        total_attempts += policy.request_attempts
        outcome = _classify_outcome(trajectory)

        if outcome is FlightAttemptOutcome.SUCCESS:
            try:
                replay_trajectory(trajectory, env_factory)
            except ReplayMismatch:
                last_outcome = FlightAttemptOutcome.REPLAY_MISMATCH
                last_trajectory = trajectory
                continue
            return FlightTaskEvidence(
                task_id=task.task_id,
                content_sha256=content_sha256,
                dataset_version=config.dataset_version,
                seed=config.seed,
                bundle_sha256=config.bundle_sha256,
                manifest_sha256=config.manifest_sha256,
                route_sha256=config.route_sha256,
                config_sha256=config.config_sha256,
                outcome=FlightAttemptOutcome.SUCCESS,
                accepted=True,
                episode_index=episode_index,
                request_attempts=total_attempts,
                usage_prompt_tokens=total_prompt,
                usage_completion_tokens=total_completion,
                trajectory=trajectory,
            )

        last_outcome = outcome
        last_trajectory = trajectory

    return FlightTaskEvidence(
        task_id=task.task_id,
        content_sha256=content_sha256,
        dataset_version=config.dataset_version,
        seed=config.seed,
        bundle_sha256=config.bundle_sha256,
        manifest_sha256=config.manifest_sha256,
        route_sha256=config.route_sha256,
        config_sha256=config.config_sha256,
        outcome=last_outcome,
        accepted=False,
        episode_index=0,
        request_attempts=total_attempts,
        usage_prompt_tokens=total_prompt,
        usage_completion_tokens=total_completion,
        trajectory=last_trajectory,
    )


def trajectories_to_sft_jsonl(
    evidences: Sequence[FlightTaskEvidence],
    output_path: Path,
) -> int:
    """Convert accepted evidences to SFT JSONL using core's trajectory_to_sft_example."""
    count = 0
    with output_path.open("w", encoding="utf-8") as f:
        for ev in evidences:
            if not ev.accepted or ev.trajectory is None:
                continue
            example = trajectory_to_sft_example(ev.trajectory)
            f.write(json.dumps(example, ensure_ascii=False) + "\n")
            count += 1
    return count


def load_teacher_route_from_env(
    environ: dict[str, str] | None = None,
) -> tuple[TeacherRouteSnapshot, str]:
    """Load teacher route and API key from environment."""
    env = environ if environ is not None else dict(os.environ)
    return load_teacher_route(env)


def write_checkpoint(
    checkpoint: FlightCollectionCheckpoint,
    output_dir: Path,
) -> None:
    """Write checkpoint JSON for resume support."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "checkpoint.json"
    path.write_text(
        json.dumps(checkpoint.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_checkpoint(output_dir: Path) -> FlightCollectionCheckpoint | None:
    """Load checkpoint if it exists, else None."""
    path = output_dir / "checkpoint.json"
    if not path.exists():
        return None
    return FlightCollectionCheckpoint.model_validate_json(path.read_text(encoding="utf-8"))


def write_evidence(evidence: FlightTaskEvidence, output_dir: Path) -> None:
    """Write one attempt's evidence to a JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_id = evidence.task_id.replace("/", "_").replace(":", "_")
    path = output_dir / f"{safe_id}.json"
    path.write_text(
        json.dumps(evidence.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
