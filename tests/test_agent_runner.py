"""Policy 解析与 AgentRunner 闭环测试。"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any


def test_qwen_parser_accepts_one_hermes_tool_call() -> None:
    from veritool_rl.agent.parser import parse_qwen_response

    output = parse_qwen_response(
        '<tool_call>\n{"name":"get_order","arguments":{"order_id":"O-1"}}\n</tool_call>'
        "<|im_end|>"
    )

    assert output.parse_error is None
    assert output.tool_call is not None
    assert output.tool_call.name == "get_order"
    assert output.tool_call.arguments == {"order_id": "O-1"}


def test_qwen_parser_rejects_multiple_or_malformed_tool_calls() -> None:
    from veritool_rl.agent.parser import parse_qwen_response

    multiple = parse_qwen_response(
        '<tool_call>{"name":"get_order","arguments":{}}</tool_call>'
        '<tool_call>{"name":"refund_order","arguments":{}}</tool_call>'
    )
    malformed = parse_qwen_response("<tool_call>{not-json}</tool_call>")

    assert multiple.parse_error == "multiple_tool_calls"
    assert malformed.parse_error == "invalid_tool_call_json"


def test_oracle_runner_completes_all_scenarios() -> None:
    from veritool_rl.agent.policy import OraclePolicy
    from veritool_rl.agent.runner import run_episode
    from veritool_rl.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits
    from veritool_rl.trajectory import TaskScenario, TerminationReason

    tasks = build_mvp_task_splits(seed=9)["test"][:4]
    trajectories = [
        run_episode(task, MiniRetailEnv, OraclePolicy(task), seed=9) for task in tasks
    ]

    assert {trajectory.task.scenario for trajectory in trajectories} == set(TaskScenario)
    assert all(trajectory.success for trajectory in trajectories)
    assert all(trajectory.termination is TerminationReason.SUCCESS for trajectory in trajectories)
    recovery = next(
        trajectory
        for trajectory in trajectories
        if trajectory.task.scenario is TaskScenario.REFUND_RECOVERY
    )
    assert any(
        step.observation is not None and step.observation.error_code == "transient_error"
        for step in recovery.steps
    )


def test_format_errors_consume_steps_without_crashing_episode() -> None:
    from veritool_rl.agent.policy import PolicyOutput
    from veritool_rl.agent.runner import run_episode
    from veritool_rl.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits
    from veritool_rl.trajectory import TerminationReason

    class InvalidPolicy:
        name = "invalid"

        def __init__(self) -> None:
            self._outputs: Iterator[PolicyOutput] = iter(
                PolicyOutput(
                    raw_text="<tool_call>bad</tool_call>",
                    parse_error="invalid_tool_call_json",
                )
                for _ in range(8)
            )

        def respond(self, messages: list[dict[str, Any]], tools: list[Any]) -> PolicyOutput:
            return next(self._outputs)

    task = build_mvp_task_splits(seed=1)["test"][0]
    trajectory = run_episode(task, MiniRetailEnv, InvalidPolicy(), seed=1)

    assert trajectory.success is False
    assert trajectory.termination is TerminationReason.STEP_LIMIT
    assert len(trajectory.steps) == task.max_steps
    assert all(step.observation is not None for step in trajectory.steps)
    assert all(step.reward.invalid_call < 0 for step in trajectory.steps)


def test_policy_violation_terminates_episode() -> None:
    from veritool_rl.agent.policy import PolicyOutput
    from veritool_rl.agent.runner import run_episode
    from veritool_rl.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits
    from veritool_rl.trajectory import TaskScenario, TerminationReason, ToolCall

    class RefundFirstPolicy:
        name = "refund-first"

        def respond(self, messages: list[dict[str, Any]], tools: list[Any]) -> PolicyOutput:
            return PolicyOutput(
                raw_text="refund",
                tool_call=ToolCall(
                    name="refund_order",
                    arguments={
                        "order_id": task.metadata["order_id"],
                        "reason": task.metadata["reason"],
                    },
                ),
            )

    task = next(
        task
        for task in build_mvp_task_splits(seed=5)["test"]
        if task.scenario is TaskScenario.REFUND_ELIGIBLE
    )
    trajectory = run_episode(task, MiniRetailEnv, RefundFirstPolicy(), seed=5)

    assert trajectory.termination is TerminationReason.POLICY_VIOLATION
    assert trajectory.violations == ["refund_without_lookup"]
    assert trajectory.steps[0].reward.policy_penalty == -1.0
