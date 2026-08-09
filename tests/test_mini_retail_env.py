"""MiniRetail 确定性任务与环境测试。"""

from __future__ import annotations

from collections import Counter


def test_generated_task_splits_are_deterministic_balanced_and_disjoint() -> None:
    from veritool_rl.core.envs.mini_retail import build_mvp_task_splits

    first = build_mvp_task_splits(seed=7)
    second = build_mvp_task_splits(seed=7)

    assert first == second
    assert {name: len(tasks) for name, tasks in first.items()} == {
        "train": 128,
        "dev": 32,
        "test": 32,
    }
    for tasks in first.values():
        assert set(Counter(task.scenario for task in tasks).values()) == {len(tasks) // 4}

    identifiers = {
        split: {
            (task.metadata["customer_id"], task.metadata["order_id"])
            for task in tasks
        }
        for split, tasks in first.items()
    }
    assert identifiers["train"].isdisjoint(identifiers["dev"])
    assert identifiers["train"].isdisjoint(identifiers["test"])
    assert identifiers["dev"].isdisjoint(identifiers["test"])


def test_eligible_refund_requires_lookup_and_reaches_target_state() -> None:
    from veritool_rl.core.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits
    from veritool_rl.core.trajectory import TaskScenario

    task = next(
        task
        for task in build_mvp_task_splits(seed=0)["test"]
        if task.scenario is TaskScenario.REFUND_ELIGIBLE
    )
    env = MiniRetailEnv(task)
    order_id = str(task.metadata["order_id"])

    denied = env.execute_tool("refund_order", {"order_id": order_id, "reason": "damaged"})
    assert denied.ok is False
    assert denied.error_code == "policy_denied"
    assert "refund_without_lookup" in env.check_policy()

    env = MiniRetailEnv(task)
    assert env.execute_tool("get_order", {"order_id": order_id}).ok is True
    refunded = env.execute_tool(
        "refund_order", {"order_id": order_id, "reason": task.metadata["reason"]}
    )

    assert refunded.ok is True
    assert env.verify_milestone() == 1.0
    assert env.verify_final_state() == 1.0
    assert env.check_policy() == []
    assert env.get_state() == task.target_state


def test_recovery_task_fails_once_then_succeeds() -> None:
    from veritool_rl.core.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits
    from veritool_rl.core.trajectory import TaskScenario

    task = next(
        task
        for task in build_mvp_task_splits(seed=2)["dev"]
        if task.scenario is TaskScenario.REFUND_RECOVERY
    )
    env = MiniRetailEnv(task)
    order_id = str(task.metadata["order_id"])
    arguments = {"order_id": order_id, "reason": task.metadata["reason"]}

    env.execute_tool("get_order", {"order_id": order_id})
    first = env.execute_tool("refund_order", arguments)
    second = env.execute_tool("refund_order", arguments)

    assert (first.ok, first.error_code) == (False, "transient_error")
    assert second.ok is True
    assert env.verify_final_state() == 1.0


def test_denied_refund_task_succeeds_without_state_change_after_lookup() -> None:
    from veritool_rl.core.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits
    from veritool_rl.core.trajectory import TaskScenario

    task = next(
        task
        for task in build_mvp_task_splits(seed=3)["test"]
        if task.scenario is TaskScenario.REFUND_DENIED
    )
    env = MiniRetailEnv(task)

    env.execute_tool("get_order", {"order_id": task.metadata["order_id"]})

    assert env.verify_milestone() == 1.0
    assert env.verify_final_state() == 1.0
    assert env.get_state() == task.initial_state


def test_schema_perturbation_is_deterministic_and_keeps_alias_executable() -> None:
    from veritool_rl.core.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits

    task = build_mvp_task_splits(seed=4)["test"][0]
    first = MiniRetailEnv(task)
    second = MiniRetailEnv(task)

    first.perturb_schema(seed=11)
    second.perturb_schema(seed=11)
    first_tools = first.list_tools()

    assert first_tools == second.list_tools()
    assert len(first_tools) == 3
    presented_get_order = next(tool for tool in first_tools if "订单" in tool.description)
    result = first.execute_tool(
        presented_get_order.name,
        {"order_id": task.metadata["order_id"]},
    )
    assert result.ok is True
