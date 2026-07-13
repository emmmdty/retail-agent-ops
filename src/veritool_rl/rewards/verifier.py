"""确定性可验证奖励与校准 (占位)。

奖励原则 (见 SPEC.md「假设 H3」「评测指标」):
- 主奖励由执行结果、数据库最终状态与 policy verifier 支撑;
- LLM-as-a-judge 只作补充, 不作核心奖励;
- 朴素 dense per-turn reward 可能劣于稀疏奖励, 需按区分度/优势信号校准。
"""
from __future__ import annotations

from veritool_rl.envs.base import ToolEnv
from veritool_rl.trajectory.schema import Trajectory


def final_state_reward(env: ToolEnv, traj: Trajectory) -> float:
    """最终状态正确性奖励 (占位)。"""
    raise NotImplementedError


def policy_reward(env: ToolEnv, traj: Trajectory) -> float:
    """政策遵循奖励 / 违规惩罚 (占位)。"""
    raise NotImplementedError


def milestone_reward(env: ToolEnv, traj: Trajectory) -> float:
    """中间里程碑奖励 (占位)。"""
    raise NotImplementedError


def calibrate_reward(rewards: list[float]) -> list[float]:
    """按区分度/优势信号校准每轮奖励 (H3, 占位)。"""
    raise NotImplementedError
