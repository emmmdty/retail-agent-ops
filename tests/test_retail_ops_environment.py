"""RetailOps qualification 任务与政策感知环境测试。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path


def test_qualification_tasks_are_deterministic_balanced_and_disjoint() -> None:
    from veritool_rl.retail_ops.tasks import build_qualification_tasks

    first = build_qualification_tasks(seed=0)
    second = build_qualification_tasks(seed=0)

    assert first == second
    assert len(first) == 12
    assert set(Counter(task.scenario for task in first).values()) == {2}
    assert len({task.task_id for task in first}) == 12
    assert len({task.metadata["family_id"] for task in first}) == 12
    assert all(task.split == "qualification" for task in first)


def test_correct_window_denial_requires_read_and_final_response() -> None:
    from veritool_rl.retail_ops.bundle import load_bundle
    from veritool_rl.retail_ops.environment import RetailOpsEnv
    from veritool_rl.retail_ops.tasks import build_qualification_tasks
    from veritool_rl.trajectory import TaskScenario

    bundle = load_bundle(Path("domains/retail_ops/v1"))
    task = next(
        task
        for task in build_qualification_tasks(seed=0)
        if task.scenario is TaskScenario.REFUND_DENIED_WINDOW
    )
    env = RetailOpsEnv(task, bundle)

    env.execute_tool("get_order", {"order_id": task.metadata["order_id"]})
    assert env.verify_final_state() == 0.0
    env.record_final_response("该订单已超过退款期限，无法退款。")

    assert env.verify_final_state() == 1.0
    assert env.check_policy() == []


def test_attempted_forbidden_refund_is_policy_violation() -> None:
    from veritool_rl.retail_ops.bundle import load_bundle
    from veritool_rl.retail_ops.environment import RetailOpsEnv
    from veritool_rl.retail_ops.tasks import build_qualification_tasks
    from veritool_rl.trajectory import TaskScenario

    bundle = load_bundle(Path("domains/retail_ops/v1"))
    task = next(
        task
        for task in build_qualification_tasks(seed=0)
        if task.scenario is TaskScenario.REFUND_DENIED_WINDOW
    )
    env = RetailOpsEnv(task, bundle)
    env.execute_tool("get_order", {"order_id": task.metadata["order_id"]})
    result = env.execute_tool(
        "refund_order",
        {"order_id": task.metadata["order_id"], "reason": task.metadata["reason"]},
    )

    assert result.error_code == "policy_denied"
    assert env.verify_final_state() == 0.0
    assert env.check_policy() == ["refund_not_eligible"]


def test_recovery_allows_exactly_one_transient_retry() -> None:
    from veritool_rl.retail_ops.bundle import load_bundle
    from veritool_rl.retail_ops.environment import RetailOpsEnv
    from veritool_rl.retail_ops.tasks import build_qualification_tasks
    from veritool_rl.trajectory import TaskScenario

    bundle = load_bundle(Path("domains/retail_ops/v1"))
    task = next(
        task
        for task in build_qualification_tasks(seed=0)
        if task.scenario is TaskScenario.REFUND_RECOVERY
    )
    env = RetailOpsEnv(task, bundle)
    arguments = {
        "order_id": task.metadata["order_id"],
        "reason": task.metadata["reason"],
    }
    env.execute_tool("get_order", {"order_id": task.metadata["order_id"]})
    first = env.execute_tool("refund_order", arguments)
    second = env.execute_tool("refund_order", arguments)

    assert first.error_code == "transient_error"
    assert second.ok is True
    assert env.verify_final_state() == 1.0
    assert env.check_policy() == []


def test_cross_customer_lookup_does_not_leak_order_data() -> None:
    from veritool_rl.retail_ops.bundle import load_bundle
    from veritool_rl.retail_ops.environment import RetailOpsEnv
    from veritool_rl.retail_ops.tasks import build_qualification_tasks
    from veritool_rl.trajectory import TaskScenario

    bundle = load_bundle(Path("domains/retail_ops/v1"))
    task = next(
        task
        for task in build_qualification_tasks(seed=0)
        if task.scenario is TaskScenario.REFUND_DENIED_OWNERSHIP
    )
    env = RetailOpsEnv(task, bundle)

    result = env.execute_tool("get_order", {"order_id": task.metadata["order_id"]})

    assert result.ok is False
    assert result.error_code == "not_found"
    assert result.content is None
    assert env.check_policy() == []


def test_duplicate_refund_is_denied_without_mutating_state() -> None:
    from veritool_rl.retail_ops.bundle import load_bundle
    from veritool_rl.retail_ops.environment import RetailOpsEnv
    from veritool_rl.retail_ops.tasks import build_qualification_tasks
    from veritool_rl.trajectory import TaskScenario

    bundle = load_bundle(Path("domains/retail_ops/v1"))
    task = next(
        task
        for task in build_qualification_tasks(seed=0)
        if task.scenario is TaskScenario.REFUND_DENIED_DUPLICATE
    )
    env = RetailOpsEnv(task, bundle)
    order_id = task.metadata["order_id"]
    reason = task.metadata["reason"]

    env.execute_tool("get_order", {"order_id": order_id})
    before = env.get_state()
    result = env.execute_tool("refund_order", {"order_id": order_id, "reason": reason})

    assert result.error_code == "policy_denied"
    assert env.get_state() == before
    assert env.check_policy() == ["duplicate_refund"]
