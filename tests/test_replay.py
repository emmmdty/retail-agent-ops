"""轨迹精确重放测试。"""

from __future__ import annotations

import pytest


def test_oracle_trajectory_replays_exactly() -> None:
    from veritool_rl.agent.policy import OraclePolicy
    from veritool_rl.agent.runner import run_episode
    from veritool_rl.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits
    from veritool_rl.trajectory.replay import replay_trajectory

    task = build_mvp_task_splits(seed=6)["dev"][3]
    trajectory = run_episode(task, MiniRetailEnv, OraclePolicy(task), seed=6)

    result = replay_trajectory(trajectory, MiniRetailEnv)

    assert result.matched is True
    assert result.steps_replayed == len(trajectory.steps)


def test_replay_reports_tampered_observation_step() -> None:
    from veritool_rl.agent.policy import OraclePolicy
    from veritool_rl.agent.runner import run_episode
    from veritool_rl.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits
    from veritool_rl.trajectory import Observation
    from veritool_rl.trajectory.replay import ReplayMismatch, replay_trajectory

    task = build_mvp_task_splits(seed=8)["dev"][1]
    trajectory = run_episode(task, MiniRetailEnv, OraclePolicy(task), seed=8)
    tampered = trajectory.model_copy(deep=True)
    tampered.steps[0].observation = Observation(ok=True, content={"tampered": True})

    with pytest.raises(ReplayMismatch, match=r"step=0.*observation"):
        replay_trajectory(tampered, MiniRetailEnv)


def test_replay_rejects_tampered_action() -> None:
    from veritool_rl.agent.policy import OraclePolicy
    from veritool_rl.agent.runner import run_episode
    from veritool_rl.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits
    from veritool_rl.trajectory.replay import ReplayMismatch, replay_trajectory

    task = build_mvp_task_splits(seed=8)["dev"][1]
    trajectory = run_episode(task, MiniRetailEnv, OraclePolicy(task), seed=8)
    tampered = trajectory.model_copy(deep=True)
    assert tampered.steps[0].tool_call is not None
    tampered.steps[0].tool_call.arguments["order_id"] = "O-TAMPERED"

    with pytest.raises(ReplayMismatch, match=r"step=0"):
        replay_trajectory(tampered, MiniRetailEnv)


def test_replay_rejects_tampered_final_state_and_reward() -> None:
    from veritool_rl.agent.policy import OraclePolicy
    from veritool_rl.agent.runner import run_episode
    from veritool_rl.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits
    from veritool_rl.trajectory.replay import ReplayMismatch, replay_trajectory

    task = build_mvp_task_splits(seed=8)["dev"][1]
    trajectory = run_episode(task, MiniRetailEnv, OraclePolicy(task), seed=8)

    final_state_tampered = trajectory.model_copy(deep=True)
    final_state_tampered.final_state["current_day"] = 999
    with pytest.raises(ReplayMismatch, match="final_state"):
        replay_trajectory(final_state_tampered, MiniRetailEnv)

    reward_tampered = trajectory.model_copy(deep=True)
    reward_tampered.steps[0].reward.total = 99.0
    with pytest.raises(ReplayMismatch, match=r"step=0.*reward"):
        replay_trajectory(reward_tampered, MiniRetailEnv)


def test_replay_rejects_non_contiguous_recorded_step_index() -> None:
    from veritool_rl.agent.policy import OraclePolicy
    from veritool_rl.agent.runner import run_episode
    from veritool_rl.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits
    from veritool_rl.trajectory.replay import ReplayMismatch, replay_trajectory

    task = build_mvp_task_splits(seed=8)["dev"][1]
    trajectory = run_episode(task, MiniRetailEnv, OraclePolicy(task), seed=8)
    tampered = trajectory.model_copy(deep=True)
    tampered.steps[0].index = 7

    with pytest.raises(ReplayMismatch, match=r"step=0.*index"):
        replay_trajectory(tampered, MiniRetailEnv)


def test_retail_ops_denial_trajectory_replays_terminal_response() -> None:
    from pathlib import Path

    from veritool_rl.agent.policy import OraclePolicy
    from veritool_rl.agent.runner import run_episode
    from veritool_rl.retail_ops.bundle import load_bundle
    from veritool_rl.retail_ops.environment import RetailOpsEnv
    from veritool_rl.retail_ops.tasks import build_qualification_tasks
    from veritool_rl.trajectory import TaskScenario
    from veritool_rl.trajectory.replay import replay_trajectory

    bundle = load_bundle(Path("domains/retail_ops/v1"))
    task = next(
        task
        for task in build_qualification_tasks(seed=0)
        if task.scenario is TaskScenario.REFUND_DENIED_WINDOW
    )
    trajectory = run_episode(
        task,
        lambda current: RetailOpsEnv(current, bundle),
        OraclePolicy(task),
        seed=0,
    )

    result = replay_trajectory(
        trajectory,
        lambda current: RetailOpsEnv(current, bundle),
    )

    assert result.matched is True
