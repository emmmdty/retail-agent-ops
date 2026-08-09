"""确定性 verifier 及可追溯奖励分量。"""

from __future__ import annotations

from veritool_rl.core.envs.base import ToolEnv
from veritool_rl.core.trajectory import Observation, RewardBreakdown, Trajectory

_INVALID_ERROR_CODES = {"unknown_tool", "invalid_arguments", "format_error"}


def compute_reward_breakdown(
    env: ToolEnv,
    observation: Observation | None,
    parse_error: str | None = None,
) -> RewardBreakdown:
    """计算当前状态的稀疏奖励；milestone 只报告，不混入总奖励。"""
    final_state = env.verify_final_state()
    policy_penalty = -1.0 if env.check_policy() else 0.0
    invalid = parse_error is not None or (
        observation is not None and observation.error_code in _INVALID_ERROR_CODES
    )
    invalid_call = -0.25 if invalid else 0.0
    return RewardBreakdown(
        final_state=final_state,
        milestone=env.verify_milestone(),
        policy_penalty=policy_penalty,
        invalid_call=invalid_call,
        total=final_state + policy_penalty + invalid_call,
    )


def final_state_reward(env: ToolEnv, traj: Trajectory) -> float:
    """返回环境的确定性最终状态分数。"""
    del traj
    return env.verify_final_state()


def policy_reward(env: ToolEnv, traj: Trajectory) -> float:
    """每条轨迹只施加一次政策违规惩罚。"""
    del traj
    return -1.0 if env.check_policy() else 0.0


def milestone_reward(env: ToolEnv, traj: Trajectory) -> float:
    """返回已完成 gold 调用的比例。"""
    del traj
    return env.verify_milestone()
