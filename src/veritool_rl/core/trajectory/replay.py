"""在全新环境实例中精确重放轨迹。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from veritool_rl.core.agent.guardrail import Guardrail, blocked_observation
from veritool_rl.core.envs.base import ToolEnv
from veritool_rl.core.rewards.verifier import compute_reward_breakdown
from veritool_rl.core.trajectory.schema import (
    Observation,
    StrictModel,
    TaskSpec,
    TerminationReason,
    Trajectory,
)


class ReplayMismatch(AssertionError):
    """轨迹记录与确定性重放结果不一致。"""


class ReplayResult(StrictModel):
    """成功重放的摘要。"""

    matched: bool
    steps_replayed: int


def replay_trajectory(
    trajectory: Trajectory,
    env_factory: Callable[[TaskSpec], ToolEnv],
    guardrail_factory: Callable[[], Guardrail] | None = None,
) -> ReplayResult:
    """重放工具调用并核对每个可验证字段。

    `guardrail_factory` 必须与产出该轨迹时**同一套** guardrail：guardrail 会消毒观测
    内容，也会拦下调用，这两件事都写进了轨迹。用不带 guardrail 的环境去重放一条
    带 guardrail 的轨迹必然不一致——那不是证据损坏，是重放条件没对齐。
    每次重放构造一个新实例：guardrail 持有会话级作用域状态，复用会把上一次的授权带进来。
    """
    env = env_factory(trajectory.task)
    guardrail = None if guardrail_factory is None else guardrail_factory()
    for index, step in enumerate(trajectory.steps):
        _assert_equal(trajectory.task.task_id, index, "index", index, step.index)
        if step.tool_call is not None:
            blocked = (
                None
                if guardrail is None
                else guardrail.check_call(step.tool_call, env.list_tools())
            )
            if blocked is not None:
                observation = blocked_observation(blocked)
            else:
                observation = env.execute_tool(step.tool_call.name, step.tool_call.arguments)
                if guardrail is not None:
                    guardrail.observe(step.tool_call, observation)
                    observation = guardrail.sanitize(observation)
        elif step.parse_error is not None:
            observation = Observation(
                ok=False,
                error_code="format_error",
                error=step.parse_error,
            )
        else:
            observation = None

        if step.final_response is not None:
            env.record_final_response(step.final_response)
        _assert_equal(trajectory.task.task_id, index, "observation", observation, step.observation)
        _assert_equal(
            trajectory.task.task_id, index, "state_after", env.get_state(), step.state_after
        )
        _assert_equal(
            trajectory.task.task_id, index, "violations", env.check_policy(), step.violations
        )
        reward = compute_reward_breakdown(env, observation, step.parse_error)
        _assert_equal(trajectory.task.task_id, index, "reward", reward, step.reward)

    _assert_equal(
        trajectory.task.task_id,
        len(trajectory.steps),
        "final_state",
        env.get_state(),
        trajectory.final_state,
    )
    _assert_equal(
        trajectory.task.task_id,
        len(trajectory.steps),
        "violations",
        env.check_policy(),
        trajectory.violations,
    )
    derived_termination = _derive_termination(trajectory, env)
    _assert_equal(
        trajectory.task.task_id,
        len(trajectory.steps),
        "termination",
        derived_termination,
        trajectory.termination,
    )
    _assert_equal(
        trajectory.task.task_id,
        len(trajectory.steps),
        "success",
        derived_termination is TerminationReason.SUCCESS,
        trajectory.success,
    )
    return ReplayResult(matched=True, steps_replayed=len(trajectory.steps))


def _derive_termination(trajectory: Trajectory, env: ToolEnv) -> TerminationReason:
    if env.check_policy():
        return TerminationReason.POLICY_VIOLATION
    if env.verify_final_state() == 1.0:
        return TerminationReason.SUCCESS
    if trajectory.steps and trajectory.steps[-1].final_response is not None:
        return TerminationReason.FINAL_RESPONSE
    return TerminationReason.STEP_LIMIT


def _assert_equal(task_id: str, step: int, field: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        msg = f"轨迹重放不一致: task={task_id} step={step} field={field}"
        raise ReplayMismatch(msg)
