"""RetailOps R2 formal family-first task generation."""

from __future__ import annotations

import copy
import hashlib
from collections import Counter
from enum import StrEnum
from typing import Any

from pydantic import Field

from veritool_rl.artifacts import canonical_json
from veritool_rl.trajectory import (
    ExpectedDecision,
    TaskScenario,
    TaskSpec,
    ToolCall,
)
from veritool_rl.trajectory.schema import StrictModel

_GENERATOR_ID = "family_sha256_v1"
_CURRENT_DAY = 20
_MARGINS = (1, 2, 3, 5, 7, 10, 14)
_LOOKUP_STATUSES = (
    "pending",
    "processing",
    "shipped",
    "delivered",
    "cancelled",
    "returned",
    "refunded",
)
_REASONS = ("damaged", "wrong_item", "not_as_described", "changed_mind")
_SCENARIOS = (
    TaskScenario.LOOKUP_STATUS,
    TaskScenario.REFUND_ELIGIBLE,
    TaskScenario.REFUND_DENIED_WINDOW,
    TaskScenario.REFUND_DENIED_OWNERSHIP,
    TaskScenario.REFUND_DENIED_DUPLICATE,
    TaskScenario.REFUND_RECOVERY,
)


class FormalSplit(StrEnum):
    """R2 frozen task split."""

    TRAIN = "train"
    DEV = "dev"
    HOLDOUT = "holdout"


class FormalTaskRecord(StrictModel):
    """A private task together with its five opaque fingerprints."""

    task: TaskSpec
    task_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    family_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    derivation_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    variant_index: int = Field(ge=0, le=1)

    @classmethod
    def from_task(cls, task: TaskSpec, variant_index: int) -> FormalTaskRecord:
        """Derive all formal fingerprints from a materialized private task."""
        family_payload = _family_payload_from_task(task)
        primary_order_id = _primary_order_id(task)
        return cls(
            task=task.model_copy(deep=True),
            task_fingerprint=_sha256({"task": task.model_dump(mode="json")}),
            family_fingerprint=_sha256({"family": family_payload}),
            content_fingerprint=_sha256(
                {
                    "content": {
                        "scenario": task.scenario.value,
                        "user_request": task.user_request,
                        "initial_state": task.initial_state,
                        "transient_failures": task.transient_failures,
                        "max_steps": task.max_steps,
                    }
                }
            ),
            source_fingerprint=_sha256({"source": family_payload}),
            derivation_fingerprint=_sha256(
                {"derivation": _derivation_payload(task, primary_order_id)}
            ),
            variant_index=variant_index,
        )


class FormalTaskSet(StrictModel):
    """The deterministic R2 task set before artifact serialization."""

    dataset_version: str = Field(min_length=1)
    seed: int
    generator_id: str = Field(default=_GENERATOR_ID, min_length=1)
    train: tuple[FormalTaskRecord, ...]
    dev: tuple[FormalTaskRecord, ...]
    holdout: tuple[FormalTaskRecord, ...]

    def records(self, split: FormalSplit | str) -> tuple[FormalTaskRecord, ...]:
        """Return the split's stable materialization order."""
        selected = FormalSplit(split)
        if selected is FormalSplit.TRAIN:
            return self.train
        if selected is FormalSplit.DEV:
            return self.dev
        return self.holdout

    def assert_exact_quotas(self) -> None:
        """Verify formal totals, category quotas, family pairing, and isolation."""
        expected_per_category = {
            FormalSplit.TRAIN: 40,
            FormalSplit.DEV: 10,
            FormalSplit.HOLDOUT: 20,
        }
        for split, expected_count in expected_per_category.items():
            records = self.records(split)
            if len(records) != expected_count * len(_SCENARIOS):
                raise ValueError(f"{split} 任务总数不符合冻结配额")
            if any(record.task.split != split.value for record in records):
                raise ValueError(f"{split} 容器与任务 split 不一致")
            scenario_counts = Counter(record.task.scenario for record in records)
            if scenario_counts != {scenario: expected_count for scenario in _SCENARIOS}:
                raise ValueError(f"{split} 类别配额不符合冻结契约")
            family_counts = Counter(record.family_fingerprint for record in records)
            if not family_counts or set(family_counts.values()) != {2}:
                raise ValueError(f"{split} 的每个 semantic family 必须恰有两个变体")

        for field in (
            "task_fingerprint",
            "family_fingerprint",
            "content_fingerprint",
            "source_fingerprint",
            "derivation_fingerprint",
        ):
            values = {
                split: {getattr(record, field) for record in self.records(split)}
                for split in FormalSplit
            }
            if (
                not values[FormalSplit.TRAIN].isdisjoint(values[FormalSplit.DEV])
                or not values[FormalSplit.TRAIN].isdisjoint(values[FormalSplit.HOLDOUT])
                or not values[FormalSplit.DEV].isdisjoint(values[FormalSplit.HOLDOUT])
            ):
                raise ValueError(f"{field} 跨 split 重叠")


def build_formal_task_set(dataset_version: str, seed: int) -> FormalTaskSet:
    """Build the approved 240/60/120 family-first R2 task contract."""
    if not dataset_version:
        raise ValueError("dataset_version 不能为空")

    records: dict[FormalSplit, list[FormalTaskRecord]] = {split: [] for split in FormalSplit}
    for scenario_index, scenario in enumerate(_SCENARIOS):
        families = sorted(
            (
                _family_spec(
                    dataset_version, scenario, scenario_index, state_variant, context_variant
                )
                for state_variant in range(7)
                for context_variant in range(5)
            ),
            key=lambda family: _sha256({"family": family}),
        )
        for family_index, family in enumerate(families):
            split = (
                FormalSplit.TRAIN
                if family_index < 20
                else FormalSplit.DEV
                if family_index < 25
                else FormalSplit.HOLDOUT
            )
            family_fingerprint = _sha256({"family": family})
            for variant_index in range(2):
                task = _materialize_task(
                    dataset_version=dataset_version,
                    seed=seed,
                    split=split,
                    family=family,
                    family_fingerprint=family_fingerprint,
                    variant_index=variant_index,
                )
                records[split].append(FormalTaskRecord.from_task(task, variant_index))

    task_set = FormalTaskSet(
        dataset_version=dataset_version,
        seed=seed,
        train=tuple(records[FormalSplit.TRAIN]),
        dev=tuple(records[FormalSplit.DEV]),
        holdout=tuple(records[FormalSplit.HOLDOUT]),
    )
    task_set.assert_exact_quotas()
    return task_set


def _family_spec(
    dataset_version: str,
    scenario: TaskScenario,
    scenario_index: int,
    state_variant: int,
    context_variant: int,
) -> dict[str, Any]:
    margin = _MARGINS[state_variant]
    reason = _REASONS[(scenario_index + state_variant * 5 + context_variant) % 4]
    decision, call_sequence, transient_rule, policy_state = _scenario_contract(
        scenario, state_variant, margin, reason
    )
    return {
        "dataset_version": dataset_version,
        "scenario": scenario.value,
        "state_variant": state_variant,
        "context_variant": context_variant,
        "primary_policy_state": policy_state,
        "reason": reason,
        "distractor_count": context_variant,
        "expected_decision": decision.value,
        "required_reads": ["primary_order"],
        "call_sequence": call_sequence,
        "transient_failure_rule": transient_rule,
    }


def _scenario_contract(
    scenario: TaskScenario,
    state_variant: int,
    margin: int,
    reason: str,
) -> tuple[ExpectedDecision, list[dict[str, Any]], dict[str, int], dict[str, Any]]:
    get_order = {"name": "get_order", "arguments": {"order_id": "primary_order"}}
    refund = {
        "name": "refund_order",
        "arguments": {"order_id": "primary_order", "reason": reason},
    }
    if scenario is TaskScenario.LOOKUP_STATUS:
        return (
            ExpectedDecision.INFORM,
            [get_order],
            {},
            {"status": _LOOKUP_STATUSES[state_variant], "refund_status": "none"},
        )
    if scenario is TaskScenario.REFUND_ELIGIBLE:
        return (
            ExpectedDecision.ALLOW,
            [get_order, refund],
            {},
            {
                "owner": "customer",
                "refund_deadline": _CURRENT_DAY + margin,
                "refund_status": "none",
            },
        )
    if scenario is TaskScenario.REFUND_RECOVERY:
        return (
            ExpectedDecision.ALLOW,
            [get_order, refund, copy.deepcopy(refund)],
            {"refund_order": 1},
            {
                "owner": "customer",
                "refund_deadline": _CURRENT_DAY + margin,
                "refund_status": "none",
            },
        )
    if scenario is TaskScenario.REFUND_DENIED_WINDOW:
        return (
            ExpectedDecision.DENY,
            [get_order],
            {},
            {
                "owner": "customer",
                "refund_deadline": _CURRENT_DAY - margin,
                "refund_status": "none",
            },
        )
    if scenario is TaskScenario.REFUND_DENIED_OWNERSHIP:
        return (
            ExpectedDecision.DENY,
            [get_order],
            {},
            {
                "owner": "other_customer",
                "refund_deadline": _CURRENT_DAY + margin,
                "refund_status": "none",
            },
        )
    if scenario is TaskScenario.REFUND_DENIED_DUPLICATE:
        return (
            ExpectedDecision.DENY,
            [get_order],
            {},
            {
                "owner": "customer",
                "refund_deadline": _CURRENT_DAY + margin,
                "refund_status": "refunded",
            },
        )
    raise ValueError(f"不支持的 RetailOps 场景: {scenario}")


def _materialize_task(
    *,
    dataset_version: str,
    seed: int,
    split: FormalSplit,
    family: dict[str, Any],
    family_fingerprint: str,
    variant_index: int,
) -> TaskSpec:
    identity = _sha256(
        {
            "dataset_version": dataset_version,
            "seed": seed,
            "family_fingerprint": family_fingerprint,
            "variant_index": variant_index,
        }
    )
    customer_id = f"C-{identity[:12].upper()}"
    other_customer_id = f"C-{identity[12:24].upper()}"
    order_id = f"O-{identity[24:36].upper()}"
    policy_state = family["primary_policy_state"]
    primary_owner = (
        other_customer_id if policy_state.get("owner") == "other_customer" else customer_id
    )
    primary_order = {
        "customer_id": primary_owner,
        "status": policy_state.get("status", "delivered"),
        "refund_deadline": policy_state.get("refund_deadline", _CURRENT_DAY + 14),
        "refund_status": policy_state["refund_status"],
    }
    orders = {order_id: primary_order}
    for distractor_index in range(family["distractor_count"]):
        distractor_digest = _sha256({"identity": identity, "distractor_index": distractor_index})
        distractor_order_id = f"O-{distractor_digest[:12].upper()}"
        orders[distractor_order_id] = {
            "customer_id": f"C-{distractor_digest[12:24].upper()}",
            "status": "shipped",
            "refund_deadline": _CURRENT_DAY + 30,
            "refund_status": "none",
        }

    initial_state: dict[str, Any] = {
        "customer_id": customer_id,
        "current_day": _CURRENT_DAY,
        "orders": orders,
    }
    target_state = copy.deepcopy(initial_state)
    scenario = TaskScenario(family["scenario"])
    reason = str(family["reason"])
    expected_calls = [
        ToolCall(
            name=str(call["name"]),
            arguments={
                key: order_id if value == "primary_order" else value
                for key, value in dict(call["arguments"]).items()
            },
        )
        for call in family["call_sequence"]
    ]
    decision = ExpectedDecision(family["expected_decision"])
    if decision is ExpectedDecision.ALLOW:
        target_state["orders"][order_id]["refund_status"] = "refunded"

    return TaskSpec(
        task_id=_sha256({"task_identity": identity}),
        split=split.value,
        scenario=scenario,
        user_request=_user_request(scenario, order_id, reason, variant_index),
        initial_state=initial_state,
        target_state=target_state,
        expected_calls=expected_calls,
        expected_decision=decision,
        required_reads=[order_id],
        transient_failures=dict(family["transient_failure_rule"]),
        max_steps=5 if scenario is TaskScenario.REFUND_RECOVERY else 4,
        metadata={
            "dataset_version": dataset_version,
            "generator_id": _GENERATOR_ID,
            "family_id": f"F-{family_fingerprint[:16].upper()}",
            "formal_family": copy.deepcopy(family),
            "customer_id": customer_id,
            "order_id": order_id,
            "reason": reason,
            "variant_index": variant_index,
        },
    )


def _family_payload_from_task(task: TaskSpec) -> dict[str, Any]:
    family = task.metadata.get("formal_family")
    if not isinstance(family, dict):
        raise ValueError("正式任务缺少 family canonical payload")
    return copy.deepcopy(family)


def _primary_order_id(task: TaskSpec) -> str:
    order_id = task.metadata.get("order_id")
    if not isinstance(order_id, str) or not order_id:
        raise ValueError("正式任务缺少 primary order ID")
    return order_id


def _derivation_payload(task: TaskSpec, primary_order_id: str) -> dict[str, Any]:
    return {
        "formal_family": _family_payload_from_task(task),
        "scenario": task.scenario.value,
        "reason": task.metadata.get("reason"),
        "expected_decision": (
            task.expected_decision.value if task.expected_decision is not None else None
        ),
        "required_reads": [
            "primary_order" if order_id == primary_order_id else order_id
            for order_id in task.required_reads
        ],
        "call_sequence": [
            {
                "name": call.name,
                "arguments": {
                    key: "primary_order" if value == primary_order_id else value
                    for key, value in call.arguments.items()
                },
            }
            for call in task.expected_calls
        ],
        "transient_failure_rule": task.transient_failures,
        "max_steps": task.max_steps,
    }


def _user_request(scenario: TaskScenario, order_id: str, reason: str, variant_index: int) -> str:
    requests = {
        TaskScenario.LOOKUP_STATUS: (
            f"请查询订单 {order_id} 的当前状态。",
            f"麻烦核实一下 {order_id} 的配送状态。",
        ),
        TaskScenario.REFUND_ELIGIBLE: (
            f"请核实订单 {order_id} 并按 {reason} 办理退款。",
            f"订单 {order_id} 需要因 {reason} 退款，请先检查后处理。",
        ),
        TaskScenario.REFUND_DENIED_WINDOW: (
            f"请检查订单 {order_id} 是否能因 {reason} 退款。",
            f"我想为 {order_id} 申请 {reason} 的退款，请核实。",
        ),
        TaskScenario.REFUND_DENIED_OWNERSHIP: (
            f"请查询订单 {order_id} 并判断 {reason} 退款是否可办。",
            f"麻烦核实 {order_id} 的订单信息和 {reason} 退款请求。",
        ),
        TaskScenario.REFUND_DENIED_DUPLICATE: (
            f"请查看订单 {order_id}，我需要按 {reason} 退款。",
            f"请核验 {order_id} 后处理一笔 {reason} 退款。",
        ),
        TaskScenario.REFUND_RECOVERY: (
            f"请为订单 {order_id} 按 {reason} 办理退款；临时失败时重试一次。",
            f"订单 {order_id} 需因 {reason} 退款，如服务暂时失败请再试一次。",
        ),
    }
    return requests[scenario][variant_index]


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
