"""RetailOps v3 task generator -- parameterized by tool_count for degradation curve.

For each breakpoint N in {3,6,9,12,15}, generates tasks using only the first N
tools from the v3 bundle. The model sees N tools during both training and eval;
as N increases, tool selection accuracy should degrade because there are more
distractors to confuse the model.

The {3} breakpoint's tasks are structurally identical to v1's tasks (same first
3 tools), so sft-008 trained on v1 can serve as the {3} baseline without retraining.
"""

from __future__ import annotations

import copy
import hashlib
import json
from enum import StrEnum
from typing import Any

from veritool_rl.core.trajectory import (
    ExpectedDecision,
    TaskScenario,
    TaskSpec,
    ToolCall,
)
from veritool_rl.core.trajectory.schema import StrictModel

_GENERATOR_ID = "retail_ops_v3_toolcount"
_CURRENT_DAY = 20
_MARGINS = (1, 2, 3, 5, 7, 10, 14)
_REASONS = ("damaged", "wrong_item", "not_as_described", "changed_mind")
_CANCEL_REASONS = ("changed_mind", "duplicate_order", "billing_error", "quality_concern")
_SCENARIOS = (
    TaskScenario.LOOKUP_STATUS,
    TaskScenario.REFUND_ELIGIBLE,
    TaskScenario.REFUND_DENIED_WINDOW,
    TaskScenario.REFUND_DENIED_OWNERSHIP,
    TaskScenario.REFUND_DENIED_DUPLICATE,
    TaskScenario.REFUND_RECOVERY,
    TaskScenario.CHECK_REFUND_STATUS,
    TaskScenario.CANCEL_ELIGIBLE,
    TaskScenario.CANCEL_DENIED_RECENT,
    TaskScenario.CANCEL_DENIED_IN_USE,
    TaskScenario.REFUND_THEN_CANCEL,
    TaskScenario.CANCEL_RECOVERY,
)
_QUOTAS = {"train": 40, "dev": 10}

#: Tool subsets for each breakpoint. First 3 = v1 tools.
_TOOL_SUBSETS = {
    3: ("get_order", "refund_order", "get_store_hours"),
    6: (
        "get_order",
        "refund_order",
        "get_store_hours",
        "cancel_order",
        "modify_order",
        "exchange_order",
    ),
    9: (
        "get_order",
        "refund_order",
        "get_store_hours",
        "cancel_order",
        "modify_order",
        "exchange_order",
        "get_refund_status",
        "get_order_history",
        "apply_refund_coupon",
    ),
    12: (
        "get_order",
        "refund_order",
        "get_store_hours",
        "cancel_order",
        "modify_order",
        "exchange_order",
        "get_refund_status",
        "get_order_history",
        "apply_refund_coupon",
        "get_return_policy",
        "check_warranty",
        "process_exchange",
    ),
    15: (
        "get_order",
        "refund_order",
        "get_store_hours",
        "cancel_order",
        "modify_order",
        "exchange_order",
        "get_refund_status",
        "get_order_history",
        "apply_refund_coupon",
        "get_return_policy",
        "check_warranty",
        "process_exchange",
        "escalate_refund",
        "get_payment_method",
        "get_customer_profile",
    ),
}


class ToolCountSplit(StrEnum):
    TRAIN = "train"
    DEV = "dev"


class ToolCountTaskRecord(StrictModel):
    task: TaskSpec
    content_sha256: str

    @property
    def task_fingerprint(self) -> str:
        return self.content_sha256

    @classmethod
    def from_task(cls, task: TaskSpec) -> ToolCountTaskRecord:
        payload = json.dumps(
            task.model_dump(mode="json"),
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
        return cls(
            task=task.model_copy(deep=True),
            content_sha256=hashlib.sha256(payload).hexdigest(),
        )


class ToolCountTaskSet(StrictModel):
    dataset_version: str
    seed: int
    tool_count: int
    generator_id: str = _GENERATOR_ID
    train: tuple[ToolCountTaskRecord, ...]
    dev: tuple[ToolCountTaskRecord, ...]

    def records(
        self,
        split: ToolCountSplit | str,
    ) -> tuple[ToolCountTaskRecord, ...]:
        if ToolCountSplit(split) is ToolCountSplit.TRAIN:
            return self.train
        return self.dev

    def assert_quotas(self) -> None:
        for split, expected in _QUOTAS.items():
            records = self.records(split)
            if len(records) != expected * len(_SCENARIOS):
                raise ValueError(f"{split} 任务总数不符合冻结配额")


def _sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8"),
    ).hexdigest()


def _order(
    order_id: str,
    customer_id: str,
    margin: int,
    refund_status: str = "open",
    status: str = "",
) -> dict[str, Any]:
    return {
        "order_id": order_id,
        "customer_id": customer_id,
        "refund_deadline": _CURRENT_DAY + margin,
        "refund_status": refund_status,
        "status": status,
    }


def _make_task(
    scenario: TaskScenario,
    split: ToolCountSplit,
    order_id: str,
    customer_id: str,
    margin: int,
    *,
    refund_status: str = "open",
    order_status: str = "",
    transient: bool = False,
    transient_failures: dict[str, int] | None = None,
    expected_decision: ExpectedDecision | None = ExpectedDecision.ALLOW,
    expected_calls: list[ToolCall] | None = None,
    user_request: str = "",
    required_reads: list[str] | None = None,
) -> TaskSpec:
    orders = {
        order_id: _order(order_id, customer_id, margin, refund_status, order_status),
    }
    initial_state: dict[str, Any] = {
        "customer_id": customer_id,
        "current_day": _CURRENT_DAY,
        "orders": orders,
    }
    target_state = copy.deepcopy(initial_state)
    if expected_decision == ExpectedDecision.ALLOW and scenario != TaskScenario.LOOKUP_STATUS:
        cancel_scenarios = {
            TaskScenario.CANCEL_ELIGIBLE,
            TaskScenario.CANCEL_RECOVERY,
        }
        if scenario in cancel_scenarios:
            target_state["orders"][order_id]["status"] = "cancelled"
            target_state["orders"][order_id]["cancel_status"] = "cancelled"
        elif scenario is TaskScenario.REFUND_THEN_CANCEL:
            target_state["orders"][order_id]["refund_status"] = "refunded"
        else:
            target_state["orders"][order_id]["refund_status"] = "refunded"
    if expected_calls is None:
        expected_calls = []
    task_id = f"{scenario.value}-{split.value}-{order_id}-{margin}"
    return TaskSpec(
        task_id=task_id,
        split=split.value,
        scenario=scenario,
        user_request=user_request or f"Please handle order {order_id}.",
        initial_state=initial_state,
        target_state=target_state,
        expected_calls=expected_calls,
        expected_decision=expected_decision,
        required_reads=required_reads or [order_id],
        transient_failures=(
            transient_failures
            if transient_failures is not None
            else ({"refund_order": 1} if transient else {})
        ),
        max_steps=4,
        metadata={"variant_index": 0, "margin": margin},
    )


def _scenario_task(
    scenario: TaskScenario,
    split: ToolCountSplit,
    order_id: str,
    customer_id: str,
    margin: int,
    index: int,
) -> TaskSpec:
    reason = _REASONS[index % len(_REASONS)]
    if scenario is TaskScenario.LOOKUP_STATUS:
        return _make_task(
            scenario,
            split,
            order_id,
            customer_id,
            margin,
            expected_decision=ExpectedDecision.INFORM,
            expected_calls=[
                ToolCall(
                    name="get_order",
                    arguments={"order_id": order_id},
                ),
            ],
            user_request=(f"What's the status of order {order_id}?"),
        )
    if scenario is TaskScenario.REFUND_ELIGIBLE:
        eligible_margin = max(margin, 10)
        return _make_task(
            scenario,
            split,
            order_id,
            customer_id,
            eligible_margin,
            expected_decision=ExpectedDecision.ALLOW,
            expected_calls=[
                ToolCall(
                    name="get_order",
                    arguments={"order_id": order_id},
                ),
                ToolCall(
                    name="refund_order",
                    arguments={
                        "order_id": order_id,
                        "reason": reason,
                    },
                ),
            ],
            user_request=(f"My order {order_id} has a problem, can you refund me?"),
        )
    if scenario is TaskScenario.REFUND_DENIED_WINDOW:
        denied_margin = min(margin, 2) if margin >= 10 else margin
        return _make_task(
            scenario,
            split,
            order_id,
            customer_id,
            denied_margin,
            expected_decision=ExpectedDecision.DENY,
            expected_calls=[
                ToolCall(
                    name="get_order",
                    arguments={"order_id": order_id},
                ),
            ],
            user_request=(f"I need to refund order {order_id}, it's urgent."),
        )
    if scenario is TaskScenario.REFUND_DENIED_OWNERSHIP:
        return _make_task(
            scenario,
            split,
            order_id,
            "CUST_OTHER",
            margin,
            expected_decision=ExpectedDecision.DENY,
            expected_calls=[
                ToolCall(
                    name="get_order",
                    arguments={"order_id": order_id},
                ),
            ],
            user_request=(f"Please refund order {order_id} for me."),
        )
    if scenario is TaskScenario.REFUND_DENIED_DUPLICATE:
        return _make_task(
            scenario,
            split,
            order_id,
            customer_id,
            margin,
            refund_status="refunded",
            expected_decision=ExpectedDecision.DENY,
            expected_calls=[
                ToolCall(
                    name="get_order",
                    arguments={"order_id": order_id},
                ),
            ],
            user_request=(f"I want to refund order {order_id} again."),
        )
    if scenario is TaskScenario.REFUND_RECOVERY:
        return _make_task(
            scenario,
            split,
            order_id,
            customer_id,
            max(margin, 10),
            transient=True,
            expected_decision=ExpectedDecision.ALLOW,
            expected_calls=[
                ToolCall(
                    name="get_order",
                    arguments={"order_id": order_id},
                ),
                ToolCall(
                    name="refund_order",
                    arguments={
                        "order_id": order_id,
                        "reason": reason,
                    },
                ),
                ToolCall(
                    name="refund_order",
                    arguments={
                        "order_id": order_id,
                        "reason": reason,
                    },
                ),
            ],
            user_request=(f"Please refund my order {order_id} due to a problem."),
        )
    if scenario is TaskScenario.CHECK_REFUND_STATUS:
        return _make_task(
            scenario,
            split,
            order_id,
            customer_id,
            margin,
            expected_decision=ExpectedDecision.INFORM,
            expected_calls=[
                ToolCall(
                    name="get_refund_status",
                    arguments={"order_id": order_id},
                ),
            ],
            user_request=(f"What is the refund status for order {order_id}?"),
        )
    if scenario is TaskScenario.CANCEL_ELIGIBLE:
        cancel_margin = max(margin, 10)
        cancel_reason = _CANCEL_REASONS[index % len(_CANCEL_REASONS)]
        return _make_task(
            scenario,
            split,
            order_id,
            customer_id,
            cancel_margin,
            expected_decision=ExpectedDecision.ALLOW,
            expected_calls=[
                ToolCall(
                    name="get_order",
                    arguments={"order_id": order_id},
                ),
                ToolCall(
                    name="cancel_order",
                    arguments={
                        "order_id": order_id,
                        "reason": cancel_reason,
                    },
                ),
            ],
            user_request=(f"Please cancel order {order_id}, reason: {cancel_reason}."),
        )
    if scenario is TaskScenario.CANCEL_DENIED_RECENT:
        denied_margin = min(margin, 2) if margin >= 10 else margin
        return _make_task(
            scenario,
            split,
            order_id,
            customer_id,
            denied_margin,
            expected_decision=ExpectedDecision.DENY,
            expected_calls=[
                ToolCall(
                    name="get_order",
                    arguments={"order_id": order_id},
                ),
            ],
            user_request=(f"I want to cancel order {order_id}."),
        )
    if scenario is TaskScenario.CANCEL_DENIED_IN_USE:
        return _make_task(
            scenario,
            split,
            order_id,
            customer_id,
            margin,
            order_status="shipped",
            expected_decision=ExpectedDecision.DENY,
            expected_calls=[
                ToolCall(
                    name="get_order",
                    arguments={"order_id": order_id},
                ),
            ],
            user_request=(f"Please cancel order {order_id} for me."),
        )
    if scenario is TaskScenario.REFUND_THEN_CANCEL:
        other_order_id = f"{order_id[:-3]}C{order_id[-3:]}"
        cancel_reason = _CANCEL_REASONS[index % len(_CANCEL_REASONS)]
        return _make_task(
            scenario,
            split,
            order_id,
            customer_id,
            max(margin, 10),
            expected_decision=ExpectedDecision.ALLOW,
            expected_calls=[
                ToolCall(
                    name="get_order",
                    arguments={"order_id": order_id},
                ),
                ToolCall(
                    name="refund_order",
                    arguments={
                        "order_id": order_id,
                        "reason": reason,
                    },
                ),
                ToolCall(
                    name="cancel_order",
                    arguments={
                        "order_id": other_order_id,
                        "reason": cancel_reason,
                    },
                ),
            ],
            user_request=(f"Refund order {order_id} and cancel order {other_order_id}."),
            required_reads=[order_id, other_order_id],
        )
    # CANCEL_RECOVERY
    cancel_reason = _CANCEL_REASONS[index % len(_CANCEL_REASONS)]
    return _make_task(
        scenario,
        split,
        order_id,
        customer_id,
        max(margin, 10),
        expected_decision=ExpectedDecision.ALLOW,
        expected_calls=[
            ToolCall(
                name="get_order",
                arguments={"order_id": order_id},
            ),
            ToolCall(
                name="cancel_order",
                arguments={
                    "order_id": order_id,
                    "reason": cancel_reason,
                },
            ),
            ToolCall(
                name="cancel_order",
                arguments={
                    "order_id": order_id,
                    "reason": cancel_reason,
                },
            ),
        ],
        user_request=(f"Please cancel order {order_id}, reason: {cancel_reason}."),
        transient_failures={"cancel_order": 1},
    )


def build_toolcount_task_set(
    dataset_version: str,
    seed: int,
    tool_count: int,
) -> ToolCountTaskSet:
    """Build tasks using only the first `tool_count` tools from v3."""
    if tool_count not in _TOOL_SUBSETS:
        msg = f"tool_count 必须是 {_TOOL_SUBSETS.keys()} 之一, 得到 {tool_count}"
        raise ValueError(msg)
    if not dataset_version:
        raise ValueError("dataset_version 不能为空")
    train: list[ToolCountTaskRecord] = []
    dev: list[ToolCountTaskRecord] = []
    for scenario in _SCENARIOS:
        for index in range(_QUOTAS["train"]):
            margin = _MARGINS[index % len(_MARGINS)]
            order_id = f"{scenario.value[:4].upper()}T{index:03d}"
            task = _scenario_task(
                scenario,
                ToolCountSplit.TRAIN,
                order_id,
                "CUST001",
                margin,
                index,
            )
            train.append(ToolCountTaskRecord.from_task(task))
        for index in range(_QUOTAS["dev"]):
            margin = _MARGINS[index % len(_MARGINS)]
            order_id = f"{scenario.value[:4].upper()}D{index:03d}"
            task = _scenario_task(
                scenario,
                ToolCountSplit.DEV,
                order_id,
                "CUST001",
                margin,
                index,
            )
            dev.append(ToolCountTaskRecord.from_task(task))
    task_set = ToolCountTaskSet(
        dataset_version=dataset_version,
        seed=seed,
        tool_count=tool_count,
        train=tuple(train),
        dev=tuple(dev),
    )
    task_set.assert_quotas()
    return task_set
