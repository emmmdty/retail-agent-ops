"""RetailOps qualification 任务与政策感知环境测试。"""

from __future__ import annotations

from collections import Counter
from pathlib import Path


def test_qualification_tasks_are_deterministic_balanced_and_disjoint() -> None:
    from veritool_rl.retail_ops.domain.tasks import build_qualification_tasks

    first = build_qualification_tasks(seed=0)
    second = build_qualification_tasks(seed=0)

    assert first == second
    assert len(first) == 12
    assert set(Counter(task.scenario for task in first).values()) == {2}
    assert len({task.task_id for task in first}) == 12
    assert len({task.metadata["family_id"] for task in first}) == 12
    assert all(task.split == "qualification" for task in first)


def test_correct_window_denial_requires_read_and_final_response() -> None:
    from veritool_rl.core.trajectory import TaskScenario
    from veritool_rl.retail_ops.domain.bundle import load_bundle
    from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
    from veritool_rl.retail_ops.domain.tasks import build_qualification_tasks

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
    from veritool_rl.core.trajectory import TaskScenario
    from veritool_rl.retail_ops.domain.bundle import load_bundle
    from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
    from veritool_rl.retail_ops.domain.tasks import build_qualification_tasks

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
    from veritool_rl.core.trajectory import TaskScenario
    from veritool_rl.retail_ops.domain.bundle import load_bundle
    from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
    from veritool_rl.retail_ops.domain.tasks import build_qualification_tasks

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
    from veritool_rl.core.trajectory import TaskScenario
    from veritool_rl.retail_ops.domain.bundle import load_bundle
    from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
    from veritool_rl.retail_ops.domain.tasks import build_qualification_tasks

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
    from veritool_rl.core.trajectory import TaskScenario
    from veritool_rl.retail_ops.domain.bundle import load_bundle
    from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
    from veritool_rl.retail_ops.domain.tasks import build_qualification_tasks

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


def test_get_order_exposes_current_day_so_window_denial_is_inferable() -> None:
    """`get_order` 必须同时返回 `refund_deadline` 与 `current_day`，否则一个只能看
    工具响应、不能读内部状态的推理式 agent 无法判断退款窗口是否已过期——`refund_deadline`
    是一个没有参照系的裸整数，只有和 `current_day` 并列出现才可比较。"""
    from veritool_rl.core.trajectory import TaskScenario
    from veritool_rl.retail_ops.domain.bundle import load_bundle
    from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
    from veritool_rl.retail_ops.domain.tasks import build_qualification_tasks

    bundle = load_bundle(Path("domains/retail_ops/v1"))
    task = next(
        task
        for task in build_qualification_tasks(seed=0)
        if task.scenario is TaskScenario.REFUND_DENIED_WINDOW
    )
    env = RetailOpsEnv(task, bundle)
    order_id = task.metadata["order_id"]

    result = env.execute_tool("get_order", {"order_id": order_id})

    assert result.ok is True
    assert result.content is not None
    assert result.content["current_day"] == task.initial_state["current_day"]
    assert (
        result.content["refund_deadline"]
        == task.initial_state["orders"][order_id]["refund_deadline"]
    )


def test_get_order_current_day_matches_env_state_for_every_scenario() -> None:
    """`current_day` 暴露不区分场景：eligible/recovery/denied_* 都应看到同一环境状态。"""
    from veritool_rl.core.trajectory import TaskScenario
    from veritool_rl.retail_ops.domain.bundle import load_bundle
    from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
    from veritool_rl.retail_ops.domain.tasks import build_qualification_tasks

    bundle = load_bundle(Path("domains/retail_ops/v1"))
    task = next(
        task
        for task in build_qualification_tasks(seed=0)
        if task.scenario is TaskScenario.REFUND_ELIGIBLE
    )
    env = RetailOpsEnv(task, bundle)
    order_id = task.metadata["order_id"]

    result = env.execute_tool("get_order", {"order_id": order_id})

    assert result.content is not None
    assert result.content["current_day"] == env.get_state()["current_day"]


# ---------------------------------------------------------------------------
# findings #4/#13：perturb_schema 对 descriptions 之外的工具必须回退到 bundle 描述
# ---------------------------------------------------------------------------


def test_perturb_schema_falls_back_to_bundle_description_for_v3_tools() -> None:
    """v3 bundle 的 15 工具远多于硬编码 descriptions 的 5 个。

    修复前（829bf95 之前）：`descriptions[schema.name]` 对 modify_order 等工具
    直接 KeyError。修复后回退到 bundle 里的原始描述；这条测试锁定回退行为，
    突变（把 `.get` 改回 `[]`）必须让本测试红。
    """
    from pathlib import Path

    from veritool_rl.core.trajectory import TaskScenario
    from veritool_rl.retail_ops.domain.bundle import load_bundle
    from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
    from veritool_rl.retail_ops.domain.tasks import build_qualification_tasks

    bundle = load_bundle(Path("domains/retail_ops/v3"))
    task = next(
        t for t in build_qualification_tasks(seed=0) if t.scenario is TaskScenario.LOOKUP_STATUS
    )
    env = RetailOpsEnv(task, bundle)
    env.perturb_schema(seed=0)

    schemas = env.list_tools()
    original = {tool.name: tool for tool in bundle.tools}

    def canonical_of(alias: str) -> str:
        return alias.rsplit("_", 1)[0]

    assert len(schemas) == len(original)
    by_canonical = {canonical_of(tool.name): tool for tool in schemas}
    assert set(by_canonical) == set(original)

    # dict 内的工具沿用原硬编码描述（get_order 的描述与 v3 bundle 的不同）
    assert by_canonical["get_order"].description == "读取指定订单的当前详情。"
    # dict 外的工具回退到 bundle 描述——修复前（descriptions[...]）这里 KeyError
    for name in ("modify_order", "exchange_order", "get_order_history"):
        assert by_canonical[name].description == original[name].description
    assert all(tool.description for tool in schemas)  # 不得静默空描述


def test_environment_rejects_unknown_tool_names() -> None:
    """编造的工具名必须得到 unknown_tool 结构化错误，而不是崩溃或静默成功。"""
    from pathlib import Path

    from veritool_rl.retail_ops.domain.bundle import load_bundle
    from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
    from veritool_rl.retail_ops.domain.tasks import build_qualification_tasks

    bundle = load_bundle(Path("domains/retail_ops/v1"))
    task = next(t for t in build_qualification_tasks(seed=0))
    env = RetailOpsEnv(task, bundle)

    observation = env.execute_tool("delete_all_orders", {})
    assert observation.ok is False
    assert observation.error_code == "unknown_tool"


def test_allowed_tools_restriction_returns_unknown_tool() -> None:
    """断点限制工具面后，被排除的工具按 unknown_tool 处理（R10 装置语义）。"""
    from pathlib import Path

    from veritool_rl.retail_ops.domain.bundle import load_bundle
    from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
    from veritool_rl.retail_ops.domain.tasks import build_qualification_tasks

    bundle = load_bundle(Path("domains/retail_ops/v3"))
    task = next(t for t in build_qualification_tasks(seed=0))
    env = RetailOpsEnv(task, bundle, allowed_tools=("get_order",))

    assert [tool.name for tool in env.list_tools()] == ["get_order"]
    observation = env.execute_tool("refund_order", {"order_id": "O-X"})
    assert observation.ok is False
    assert observation.error_code == "unknown_tool"


# ---------------------------------------------------------------------------
# F1 测试补齐（7.2 清单 §1.8 / §2.2）：v4 场景的环境层执行 + idempotency
# ---------------------------------------------------------------------------


def test_v4_cancel_and_refund_then_cancel_scenarios_execute_at_env_layer() -> None:
    """v4 新增场景（CANCEL_ELIGIBLE / REFUND_THEN_CANCEL）在环境层必须 Oracle 可解。

    7.2 的缺口：环境层测试此前只覆盖 v1 的 7 个场景；v4 逻辑
    （cancel_order 处理、双订单 gold）没有环境层证据。
    """
    from veritool_rl.core.agent.policy import OraclePolicy
    from veritool_rl.core.agent.runner import run_episode
    from veritool_rl.core.trajectory import TaskScenario
    from veritool_rl.retail_ops.domain.bundle import load_bundle
    from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
    from veritool_rl.retail_ops.domain.formal_tasks import build_v4_task_set

    bundle = load_bundle(Path("domains/retail_ops/v4"))
    task_set = build_v4_task_set("retail_ops_v4_20260822", 0)
    dev_records = task_set.dev

    by_scenario = {}
    for record in dev_records:
        by_scenario.setdefault(record.task.scenario, []).append(record.task)

    for scenario in (TaskScenario.CANCEL_ELIGIBLE, TaskScenario.REFUND_THEN_CANCEL):
        tasks = by_scenario[scenario]
        assert tasks, f"{scenario} 在 v4 dev 里没有任务"
        for task in tasks:
            trajectory = run_episode(
                task, lambda current: RetailOpsEnv(current, bundle), OraclePolicy(task), 0
            )
            assert trajectory.success, f"{scenario} 的 {task.task_id} Oracle 解不出来"
            assert trajectory.violations == []


def test_duplicate_idempotency_key_replays_the_same_result_and_refunds_once() -> None:
    """同一 idempotency_key 的两次 refund_order：重放同一观测，且只退一次款。

    只有 v2 bundle 的 refund_order schema 接受 idempotency_key（v1/v3/v4 是
    additionalProperties 语义下的严格双参数）。
    """
    from veritool_rl.core.trajectory import TaskScenario
    from veritool_rl.retail_ops.domain.bundle import load_bundle
    from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
    from veritool_rl.retail_ops.domain.tasks import build_qualification_tasks

    bundle = load_bundle(Path("domains/retail_ops/v2"))
    task = next(
        t for t in build_qualification_tasks(seed=0) if t.scenario is TaskScenario.REFUND_ELIGIBLE
    )
    env = RetailOpsEnv(task, bundle)
    order_id = task.metadata["order_id"]
    # 政策要求退款前先查询订单
    lookup = env.execute_tool("get_order", {"order_id": order_id})
    assert lookup.ok

    first = env.execute_tool(
        "refund_order", {"order_id": order_id, "reason": "damaged", "idempotency_key": "K-1"}
    )
    state_after_first = env.get_state()
    second = env.execute_tool(
        "refund_order", {"order_id": order_id, "reason": "damaged", "idempotency_key": "K-1"}
    )

    assert first.ok
    assert second == first, "同 key 重放必须返回同一观测"
    assert env.get_state() == state_after_first, "重放不得再次改变状态"
    assert env.get_state()["orders"][order_id]["refund_status"] == "refunded"
