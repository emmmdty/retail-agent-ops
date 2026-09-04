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


# ---------------------------------------------------------------------------
# 审计修复（评测基建 persona I-1 / I-2 / M-4）：超时是基础设施失败，不是模型失败
# ---------------------------------------------------------------------------


def _timeout_trajectory() -> object:
    from veritool_rl.core.trajectory import TaskScenario, Trajectory
    from veritool_rl.core.trajectory.schema import TaskSpec, TerminationReason

    task = TaskSpec(
        task_id="t-timeout",
        split="dev",
        scenario=TaskScenario.LOOKUP_STATUS,
        user_request="查询订单。",
        initial_state={"customer_id": "C-1", "current_day": 20, "orders": {}},
        target_state={"customer_id": "C-1", "current_day": 20, "orders": {}},
    )
    return Trajectory(
        task=task,
        steps=[],
        final_state={},
        violations=[],
        termination=TerminationReason.INTERNAL_ERROR,
        success=False,
        metadata={"infrastructure_error": "episode_timeout", "timeout_s": 30.0},
    )


def test_timeout_trajectories_are_classified_as_infrastructure_error() -> None:
    """超时轨迹在失败 taxonomy 里必须与模型失败分开（episode_timeout 的承诺）。"""
    from veritool_rl.core.metrics import _failure_type

    assert _failure_type(_timeout_trajectory()) == "infrastructure_error"


def test_compute_metrics_survives_an_all_timeout_batch() -> None:
    """全超时批不得让 compute_metrics 崩溃——证据必须能带着 fail-closed 落盘。"""
    from veritool_rl.core.metrics import compute_metrics

    trajectory = _timeout_trajectory()
    metrics = compute_metrics([trajectory, trajectory], bootstrap_samples=10, seed=0)

    assert metrics["task_success"] == 0.0
    assert metrics["format_error_rate"] == 0.0
    assert metrics["failure_type_distribution"] == {"infrastructure_error": 2}


# ---------------------------------------------------------------------------
# F1 测试补齐（7.2 清单 §1.3 / §1.4）
# ---------------------------------------------------------------------------


def test_split_headline_and_diagnostic_separates_verifier_reward() -> None:
    """`split_headline_and_diagnostic` 从未被测过：verifier_reward 只能出现在诊断侧。"""
    from veritool_rl.core.metrics import DIAGNOSTIC_METRICS, split_headline_and_diagnostic

    metrics = {
        "task_success": 0.9,
        "policy_violation_count": 0,
        "verifier_reward": 0.7,
        "milestone": 0.8,
    }
    headline, diagnostic = split_headline_and_diagnostic(metrics)

    # DIAGNOSTIC_METRICS 只含 verifier_reward；milestone 留在 headline 侧
    assert headline == {"task_success": 0.9, "policy_violation_count": 0, "milestone": 0.8}
    assert diagnostic == {"verifier_reward": 0.7}
    assert "verifier_reward" in DIAGNOSTIC_METRICS
    assert "milestone" not in DIAGNOSTIC_METRICS
    # 无损：两侧合并还原输入
    assert {**headline, **diagnostic} == metrics


def test_paired_bootstrap_handles_degenerate_and_balanced_outcomes() -> None:
    """全 True / 全 False / 一半一半三种配对结局的 CI 行为。"""
    from veritool_rl.core.metrics import paired_bootstrap_delta_ci95

    identical_true = [(True, True)] * 50
    low, high = paired_bootstrap_delta_ci95(identical_true)
    assert low == 0.0 and high == 0.0  # 无差异对的 delta 恒 0

    identical_false = [(False, False)] * 50
    low, high = paired_bootstrap_delta_ci95(identical_false)
    assert low == 0.0 and high == 0.0

    balanced = [(i % 2 == 0, i % 2 == 1) for i in range(50)]
    low, high = paired_bootstrap_delta_ci95(balanced)
    assert low < 0 < high, "完全对撞的结局应当给出跨 0 的区间"


def test_all_zero_step_trajectories_produce_defined_metrics() -> None:
    """零步（超时）轨迹批：除 format_error_rate 外的其余比率也必须有定义。"""
    from veritool_rl.core.metrics import compute_metrics

    trajectory = _timeout_trajectory()
    metrics = compute_metrics([trajectory], bootstrap_samples=10, seed=0)

    for key in (
        "schema_valid_rate",
        "executable_rate",
        "invalid_call_rate",
        "tool_selection_accuracy",
        "argument_accuracy",
        "task_success",
    ):
        assert key in metrics, key
        value = metrics[key]
        assert isinstance(value, (int, float)) and 0.0 <= value <= 1.0, (key, value)


def test_verifier_component_functions_agree_with_the_breakdown() -> None:
    """7.2 §1.4：三个分量函数与 `compute_reward_breakdown` 必须同源一致。"""
    from pathlib import Path

    from veritool_rl.core.agent.policy import OraclePolicy
    from veritool_rl.core.agent.runner import run_episode
    from veritool_rl.core.rewards.verifier import (
        final_state_reward,
        milestone_reward,
        policy_reward,
    )
    from veritool_rl.core.trajectory import TaskScenario
    from veritool_rl.retail_ops.domain.bundle import load_bundle
    from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
    from veritool_rl.retail_ops.domain.tasks import build_qualification_tasks

    bundle = load_bundle(Path("domains/retail_ops/v1"))
    task = next(
        t
        for t in build_qualification_tasks(seed=0)
        if t.scenario is TaskScenario.REFUND_DENIED_WINDOW
    )
    trajectory = run_episode(
        task, lambda current: RetailOpsEnv(current, bundle), OraclePolicy(task), 0
    )
    env = RetailOpsEnv(task, bundle)

    assert final_state_reward(env, trajectory) == env.verify_final_state()
    assert policy_reward(env, trajectory) == (-1.0 if env.check_policy() else 0.0)
    assert milestone_reward(env, trajectory) == env.verify_milestone()
