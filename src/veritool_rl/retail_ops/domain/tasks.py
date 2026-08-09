"""RetailOps v1 的确定性 qualification 任务。"""

from __future__ import annotations

import copy
import hashlib
from typing import Any

from veritool_rl.core.trajectory import (
    ExpectedDecision,
    TaskScenario,
    TaskSpec,
    ToolCall,
)

_SCENARIOS = (
    TaskScenario.LOOKUP_STATUS,
    TaskScenario.REFUND_ELIGIBLE,
    TaskScenario.REFUND_DENIED_WINDOW,
    TaskScenario.REFUND_DENIED_OWNERSHIP,
    TaskScenario.REFUND_DENIED_DUPLICATE,
    TaskScenario.REFUND_RECOVERY,
)
_REASONS = ("damaged", "wrong_item", "not_as_described", "changed_mind")
_CURRENT_DAY = 20


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _make_task(seed: int, index: int) -> TaskSpec:
    scenario = _SCENARIOS[index % len(_SCENARIOS)]
    task_digest = _digest(f"retail_ops_v1:{seed}:{index}")
    family_id = _digest(f"retail_ops_v1:family:{seed}:{index}")
    customer_id = f"C-{task_digest[:12].upper()}"
    other_customer_id = f"C-{task_digest[12:24].upper()}"
    order_id = f"O-{task_digest[24:36].upper()}"
    reason = _REASONS[(seed + index) % len(_REASONS)]

    owner_id = (
        other_customer_id
        if scenario is TaskScenario.REFUND_DENIED_OWNERSHIP
        else customer_id
    )
    order = {
        "customer_id": owner_id,
        "status": "shipped" if scenario is TaskScenario.LOOKUP_STATUS else "delivered",
        "refund_deadline": (
            10 if scenario is TaskScenario.REFUND_DENIED_WINDOW else 30
        ),
        "refund_status": (
            "refunded"
            if scenario is TaskScenario.REFUND_DENIED_DUPLICATE
            else "none"
        ),
    }
    initial_state: dict[str, Any] = {
        "customer_id": customer_id,
        "current_day": _CURRENT_DAY,
        "orders": {order_id: order},
    }
    target_state = copy.deepcopy(initial_state)
    get_order = ToolCall(name="get_order", arguments={"order_id": order_id})
    refund_order = ToolCall(
        name="refund_order",
        arguments={"order_id": order_id, "reason": reason},
    )
    expected_calls = [get_order]
    expected_decision = ExpectedDecision.DENY
    transient_failures: dict[str, int] = {}
    max_steps = 4

    if scenario is TaskScenario.LOOKUP_STATUS:
        expected_decision = ExpectedDecision.INFORM
    elif scenario is TaskScenario.REFUND_ELIGIBLE:
        expected_decision = ExpectedDecision.ALLOW
        expected_calls.append(refund_order)
        target_state["orders"][order_id]["refund_status"] = "refunded"
    elif scenario is TaskScenario.REFUND_RECOVERY:
        expected_decision = ExpectedDecision.ALLOW
        expected_calls.extend([refund_order, refund_order.model_copy(deep=True)])
        transient_failures = {"refund_order": 1}
        target_state["orders"][order_id]["refund_status"] = "refunded"
        max_steps = 5

    return TaskSpec(
        task_id=task_digest,
        split="qualification",
        scenario=scenario,
        user_request=_user_request(scenario, order_id, reason),
        initial_state=initial_state,
        target_state=target_state,
        expected_calls=expected_calls,
        expected_decision=expected_decision,
        required_reads=[order_id],
        transient_failures=transient_failures,
        max_steps=max_steps,
        metadata={
            "family_id": family_id,
            "customer_id": customer_id,
            "order_id": order_id,
            "reason": reason,
        },
    )


def _user_request(scenario: TaskScenario, order_id: str, reason: str) -> str:
    if scenario is TaskScenario.LOOKUP_STATUS:
        return f"请查询订单 {order_id} 的当前状态。"
    if scenario is TaskScenario.REFUND_RECOVERY:
        return f"请为订单 {order_id} 办理退款，原因是 {reason}；临时失败时请重试。"
    return f"请核实订单 {order_id} 并按 {reason} 处理退款。"


def build_qualification_tasks(seed: int) -> list[TaskSpec]:
    """生成六类均衡、共十二条的合成 qualification fixture。"""
    return [_make_task(seed, index) for index in range(12)]
