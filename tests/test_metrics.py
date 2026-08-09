"""闭环指标定义与确定性置信区间测试。"""

from __future__ import annotations

import pytest


def test_oracle_metrics_match_hand_computed_values() -> None:
    from veritool_rl.core.agent.policy import OraclePolicy
    from veritool_rl.core.agent.runner import run_episode
    from veritool_rl.core.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits
    from veritool_rl.core.metrics import compute_metrics

    tasks = build_mvp_task_splits(seed=10)["test"][:4]
    trajectories = [run_episode(task, MiniRetailEnv, OraclePolicy(task), seed=10) for task in tasks]

    first = compute_metrics(trajectories, bootstrap_samples=100, seed=3)
    second = compute_metrics(trajectories, bootstrap_samples=100, seed=3)

    assert first == second
    assert first["task_count"] == 4
    assert first["task_success"] == 1.0
    assert first["final_state_success"] == 1.0
    assert first["policy_violation_rate"] == 0.0
    assert first["invalid_call_rate"] == 0.0
    assert first["tool_selection_accuracy"] == 1.0
    assert first["argument_accuracy"] == 1.0
    assert first["recovery_success"] == 1.0
    assert first["task_success_ci95"] == [1.0, 1.0]


def test_empty_metrics_have_defined_zero_denominators() -> None:
    from veritool_rl.core.metrics import compute_metrics

    metrics = compute_metrics([], bootstrap_samples=10, seed=0)

    assert metrics["task_count"] == 0
    assert metrics["task_success"] == 0.0
    assert metrics["invalid_call_rate"] == 0.0
    assert metrics["task_success_ci95"] == [0.0, 0.0]
    assert metrics["p50_latency_ms"] == 0.0
    assert metrics["p95_latency_ms"] == 0.0


def test_metrics_reject_boolean_bootstrap_sample_count() -> None:
    from veritool_rl.core.metrics import compute_metrics

    with pytest.raises(ValueError, match="正整数"):
        compute_metrics([], bootstrap_samples=True, seed=0)


def test_metrics_separate_schema_execution_policy_and_verifier_reward() -> None:
    from typing import Any

    from veritool_rl.core.agent.policy import PolicyOutput
    from veritool_rl.core.agent.runner import run_episode
    from veritool_rl.core.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits
    from veritool_rl.core.metrics import compute_metrics
    from veritool_rl.core.trajectory import TaskScenario, ToolCall

    class UnknownToolPolicy:
        name = "unknown-tool"

        def respond(self, messages: list[dict[str, Any]], tools: list[Any]) -> PolicyOutput:
            del messages, tools
            return PolicyOutput(
                raw_text="unknown",
                tool_call=ToolCall(name="missing_tool", arguments={}),
            )

    class RefundFirstPolicy:
        name = "refund-first"

        def respond(self, messages: list[dict[str, Any]], tools: list[Any]) -> PolicyOutput:
            del messages, tools
            return PolicyOutput(
                raw_text="refund",
                tool_call=ToolCall(
                    name="refund_order",
                    arguments={
                        "order_id": eligible.metadata["order_id"],
                        "reason": eligible.metadata["reason"],
                    },
                ),
            )

    tasks = build_mvp_task_splits(seed=0)["test"]
    unknown_task = tasks[0]
    eligible = next(task for task in tasks if task.scenario is TaskScenario.REFUND_ELIGIBLE)
    trajectories = [
        run_episode(unknown_task, MiniRetailEnv, UnknownToolPolicy(), seed=0),
        run_episode(eligible, MiniRetailEnv, RefundFirstPolicy(), seed=0),
    ]

    metrics = compute_metrics(trajectories, bootstrap_samples=20, seed=0)
    attempts = unknown_task.max_steps + 1

    assert metrics["schema_valid_count"] == attempts
    assert metrics["schema_valid_rate"] == 1.0
    assert metrics["executable_count"] == 1
    assert metrics["executable_rate"] == 1 / attempts
    assert metrics["invalid_output_count"] == 0
    assert metrics["invalid_call_count"] == unknown_task.max_steps
    assert metrics["policy_violation_count"] == 1
    assert metrics["verifier_reward"] == (-0.25 * unknown_task.max_steps - 1.0) / 2
    assert metrics["failure_type_distribution"] == {
        "invalid_tool_call": 1,
        "policy_violation": 1,
    }


def test_metrics_count_parse_errors_and_transient_calls() -> None:
    from collections.abc import Iterator
    from typing import Any

    from veritool_rl.core.agent.policy import OraclePolicy, PolicyOutput
    from veritool_rl.core.agent.runner import run_episode
    from veritool_rl.core.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits
    from veritool_rl.core.metrics import compute_metrics
    from veritool_rl.core.trajectory import TaskScenario

    class InvalidPolicy:
        name = "invalid"

        def __init__(self) -> None:
            self._outputs: Iterator[PolicyOutput] = iter(
                PolicyOutput(raw_text="bad", parse_error="invalid_tool_call_json") for _ in range(8)
            )

        def respond(self, messages: list[dict[str, Any]], tools: list[Any]) -> PolicyOutput:
            del messages, tools
            return next(self._outputs)

    tasks = build_mvp_task_splits(seed=1)["test"]
    invalid_task = tasks[0]
    recovery_task = next(task for task in tasks if task.scenario is TaskScenario.REFUND_RECOVERY)
    invalid = run_episode(invalid_task, MiniRetailEnv, InvalidPolicy(), seed=1)
    recovery = run_episode(recovery_task, MiniRetailEnv, OraclePolicy(recovery_task), seed=1)

    invalid_metrics = compute_metrics([invalid], bootstrap_samples=20, seed=0)
    recovery_metrics = compute_metrics([recovery], bootstrap_samples=20, seed=0)

    assert invalid_metrics["schema_valid_rate"] == 0.0
    assert invalid_metrics["executable_rate"] == 0.0
    assert invalid_metrics["invalid_output_count"] == invalid_task.max_steps
    assert invalid_metrics["failure_type_distribution"] == {"invalid_output": 1}
    assert recovery_metrics["schema_valid_rate"] == 1.0
    assert recovery_metrics["executable_rate"] == 1.0
