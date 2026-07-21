"""RetailOps qualification policy 的端到端结果测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from veritool_rl.trajectory import Trajectory


def _run_policy(policy_type: str) -> list[Trajectory]:
    from veritool_rl.agent.runner import run_episode
    from veritool_rl.retail_ops.bundle import load_bundle
    from veritool_rl.retail_ops.environment import RetailOpsEnv
    from veritool_rl.retail_ops.policies import build_qualification_policy
    from veritool_rl.retail_ops.tasks import build_qualification_tasks

    bundle = load_bundle(Path("domains/retail_ops/v1"))
    tasks = build_qualification_tasks(seed=0)
    return [
        run_episode(
            task,
            lambda current: RetailOpsEnv(current, bundle),
            build_qualification_policy(policy_type, task),
            seed=0,
        )
        for task in tasks
    ]


def test_qualification_oracle_completes_all_twelve_tasks() -> None:
    trajectories = _run_policy("oracle")

    assert len(trajectories) == 12
    assert all(trajectory.success for trajectory in trajectories)


def test_baseline_only_completes_read_or_deny_tasks() -> None:
    from veritool_rl.trajectory import TaskScenario

    trajectories = _run_policy("baseline")
    successful_scenarios = {
        TaskScenario.LOOKUP_STATUS,
        TaskScenario.REFUND_DENIED_WINDOW,
        TaskScenario.REFUND_DENIED_OWNERSHIP,
        TaskScenario.REFUND_DENIED_DUPLICATE,
    }

    assert sum(trajectory.success for trajectory in trajectories) == 8
    assert all(
        trajectory.success is (trajectory.task.scenario in successful_scenarios)
        for trajectory in trajectories
    )
    assert all(not trajectory.violations for trajectory in trajectories)


def test_fault_policy_produces_invalid_calls_without_batch_crash() -> None:
    trajectories = _run_policy("unknown_tool")

    assert not any(trajectory.success for trajectory in trajectories)
    assert all(
        any(
            step.observation is not None
            and step.observation.error_code == "unknown_tool"
            for step in trajectory.steps
        )
        for trajectory in trajectories
    )


def test_qualification_policy_rejects_unknown_type() -> None:
    from veritool_rl.retail_ops.policies import build_qualification_policy
    from veritool_rl.retail_ops.tasks import build_qualification_tasks

    task = build_qualification_tasks(seed=0)[0]

    with pytest.raises(ValueError, match="未知 qualification policy: unsupported"):
        build_qualification_policy("unsupported", task)


@pytest.mark.parametrize("policy_type", ["oracle", "baseline", "unknown_tool"])
def test_qualification_factory_rejects_holdout_before_policy_construction(
    policy_type: str,
) -> None:
    from veritool_rl.retail_ops.policies import build_qualification_policy
    from veritool_rl.retail_ops.tasks import build_qualification_tasks

    task = build_qualification_tasks(seed=0)[0].model_copy(
        deep=True,
        update={"split": "holdout", "expected_calls": []},
    )

    with pytest.raises(ValueError) as exc_info:
        build_qualification_policy(policy_type, task)

    assert str(exc_info.value) == "qualification policy 仅接受 qualification 任务"


def test_qualification_baseline_rejects_empty_expected_calls() -> None:
    from veritool_rl.retail_ops.policies import build_qualification_policy
    from veritool_rl.retail_ops.tasks import build_qualification_tasks

    task = build_qualification_tasks(seed=0)[0].model_copy(
        deep=True,
        update={"expected_calls": []},
    )

    with pytest.raises(ValueError) as exc_info:
        build_qualification_policy("baseline", task)

    assert str(exc_info.value) == "qualification baseline 要求 expected_calls 非空"


def test_qualification_baseline_rejects_non_get_order_first_call() -> None:
    from veritool_rl.retail_ops.policies import build_qualification_policy
    from veritool_rl.retail_ops.tasks import build_qualification_tasks
    from veritool_rl.trajectory import TaskScenario

    task = next(
        task
        for task in build_qualification_tasks(seed=0)
        if task.scenario is TaskScenario.REFUND_ELIGIBLE
    )
    task = task.model_copy(
        deep=True,
        update={"expected_calls": [task.expected_calls[1].model_copy(deep=True)]},
    )

    with pytest.raises(ValueError) as exc_info:
        build_qualification_policy("baseline", task)

    assert str(exc_info.value) == "qualification baseline 的首个调用必须是 get_order"
