"""闭环指标定义与确定性置信区间测试。"""

from __future__ import annotations


def test_oracle_metrics_match_hand_computed_values() -> None:
    from veritool_rl.agent.policy import OraclePolicy
    from veritool_rl.agent.runner import run_episode
    from veritool_rl.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits
    from veritool_rl.eval.metrics import compute_metrics

    tasks = build_mvp_task_splits(seed=10)["test"][:4]
    trajectories = [
        run_episode(task, MiniRetailEnv, OraclePolicy(task), seed=10) for task in tasks
    ]

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
    from veritool_rl.eval.metrics import compute_metrics

    metrics = compute_metrics([], bootstrap_samples=10, seed=0)

    assert metrics["task_count"] == 0
    assert metrics["task_success"] == 0.0
    assert metrics["invalid_call_rate"] == 0.0
    assert metrics["task_success_ci95"] == [0.0, 0.0]
