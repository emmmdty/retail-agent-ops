"""由可重放轨迹计算的确定性评测指标。"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

import numpy as np

from veritool_rl.trajectory import TaskScenario, Trajectory

_INVALID_CODES = {"unknown_tool", "invalid_arguments", "format_error"}


def compute_metrics(
    trajectories: Sequence[Trajectory],
    bootstrap_samples: int,
    seed: int,
) -> dict[str, Any]:
    """计算主指标、资源指标和 task success bootstrap 置信区间。"""
    if (
        not isinstance(bootstrap_samples, int)
        or isinstance(bootstrap_samples, bool)
        or bootstrap_samples < 1
    ):
        msg = "bootstrap_samples 必须是正整数"
        raise ValueError(msg)
    count = len(trajectories)
    if count == 0:
        return _empty_metrics()

    successes = np.asarray([float(trajectory.success) for trajectory in trajectories])
    final_successes = [
        float(bool(trajectory.steps) and trajectory.steps[-1].reward.final_state == 1.0)
        for trajectory in trajectories
    ]
    policy_violations = [float(bool(trajectory.violations)) for trajectory in trajectories]
    attempted = 0
    invalid = 0
    format_errors = 0
    schema_valid = 0
    executable = 0
    correct_tools = 0
    tool_denominator = 0
    correct_arguments = 0
    argument_denominator = 0

    for trajectory in trajectories:
        actual_calls = [step.tool_call for step in trajectory.steps if step.tool_call is not None]
        expected_calls = trajectory.task.expected_calls
        tool_denominator += max(len(actual_calls), len(expected_calls))
        argument_denominator += len(expected_calls)
        for index, expected in enumerate(expected_calls):
            if index >= len(actual_calls):
                continue
            actual = actual_calls[index]
            if actual.name == expected.name:
                correct_tools += 1
                if actual.arguments == expected.arguments:
                    correct_arguments += 1
        for step in trajectory.steps:
            is_attempt = step.tool_call is not None or step.parse_error is not None
            attempted += int(is_attempt)
            format_errors += int(step.parse_error is not None)
            schema_valid += int(step.tool_call is not None)
            executable += int(
                step.tool_call is not None
                and step.observation is not None
                and step.observation.error_code not in _INVALID_CODES
            )
            invalid += int(
                step.parse_error is not None
                or (
                    step.observation is not None
                    and step.observation.error_code in _INVALID_CODES
                )
            )

    recovery = [
        trajectory.success
        for trajectory in trajectories
        if trajectory.task.scenario is TaskScenario.REFUND_RECOVERY
    ]
    failure_types = Counter(
        failure_type
        for trajectory in trajectories
        if (failure_type := _failure_type(trajectory)) is not None
    )
    ci_low, ci_high = _bootstrap_ci(successes, bootstrap_samples, seed)
    return {
        "task_count": count,
        "task_success": float(successes.mean()),
        "task_success_ci95": [ci_low, ci_high],
        "final_state_success": _mean(final_successes),
        "policy_violation_rate": _mean(policy_violations),
        "policy_violation_count": sum(bool(trajectory.violations) for trajectory in trajectories),
        "schema_valid_count": schema_valid,
        "schema_valid_rate": schema_valid / attempted if attempted else 0.0,
        "executable_count": executable,
        "executable_rate": executable / attempted if attempted else 0.0,
        "invalid_output_count": format_errors,
        "invalid_call_count": invalid,
        "invalid_call_rate": invalid / attempted if attempted else 0.0,
        "format_error_rate": format_errors / sum(len(t.steps) for t in trajectories),
        "tool_selection_accuracy": correct_tools / tool_denominator if tool_denominator else 0.0,
        "argument_accuracy": (
            correct_arguments / argument_denominator if argument_denominator else 0.0
        ),
        "recovery_success": _mean([float(value) for value in recovery]),
        "average_turns": _mean([float(len(t.steps)) for t in trajectories]),
        "average_tool_calls": _mean(
            [float(sum(step.tool_call is not None for step in t.steps)) for t in trajectories]
        ),
        "average_input_tokens": _mean(
            [float(sum(step.input_tokens for step in t.steps)) for t in trajectories]
        ),
        "average_output_tokens": _mean(
            [float(sum(step.output_tokens for step in t.steps)) for t in trajectories]
        ),
        "average_latency_ms": _mean(
            [float(sum(step.latency_ms for step in t.steps)) for t in trajectories]
        ),
        "verifier_reward": _mean(
            [float(sum(step.reward.total for step in t.steps)) for t in trajectories]
        ),
        "failure_type_distribution": dict(sorted(failure_types.items())),
    }


def _failure_type(trajectory: Trajectory) -> str | None:
    if trajectory.success:
        return None
    if trajectory.violations:
        return "policy_violation"
    if any(step.parse_error is not None for step in trajectory.steps):
        return "invalid_output"
    if any(
        step.observation is not None and step.observation.error_code in _INVALID_CODES
        for step in trajectory.steps
    ):
        return "invalid_tool_call"
    if trajectory.termination.value == "step_limit":
        return "step_limit"
    if trajectory.termination.value == "final_response":
        return "premature_final_response"
    return "verifier_failure"


def _bootstrap_ci(
    values: np.ndarray[Any, np.dtype[np.float64]],
    samples: int,
    seed: int,
) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    means = rng.choice(values, size=(samples, len(values)), replace=True).mean(axis=1)
    low, high = np.quantile(means, [0.025, 0.975])
    return float(low), float(high)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _empty_metrics() -> dict[str, Any]:
    return {
        "task_count": 0,
        "task_success": 0.0,
        "task_success_ci95": [0.0, 0.0],
        "final_state_success": 0.0,
        "policy_violation_rate": 0.0,
        "policy_violation_count": 0,
        "schema_valid_count": 0,
        "schema_valid_rate": 0.0,
        "executable_count": 0,
        "executable_rate": 0.0,
        "invalid_output_count": 0,
        "invalid_call_count": 0,
        "invalid_call_rate": 0.0,
        "format_error_rate": 0.0,
        "tool_selection_accuracy": 0.0,
        "argument_accuracy": 0.0,
        "recovery_success": 0.0,
        "average_turns": 0.0,
        "average_tool_calls": 0.0,
        "average_input_tokens": 0.0,
        "average_output_tokens": 0.0,
        "average_latency_ms": 0.0,
        "verifier_reward": 0.0,
        "failure_type_distribution": {},
    }
