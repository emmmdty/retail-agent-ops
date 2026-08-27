"""RetailOps v3 任务生成器——按 tool_count 参数化，用于工具数退化曲线。

断点 N ∈ {3,6,9,12,15} 决定**呈现给模型的工具子集**（v3 bundle 的前 N 个），
采集与评测都必须用 `ToolCountTaskSet.tool_names` 构造环境
（`RetailOpsEnv(..., allowed_tools=...)`）。直接用整份 v3 bundle 会让 5 个断点
看到同样的 15 个工具，自变量根本没变，曲线平坦就是恒真而不是读数——
2026-08-24 那轮 R10 曲线正是这样产生的（LOG-20260827-01）。

任务集也随断点变化：所需工具没被呈现的场景在该断点上无解，因此被排除
（`scenarios_for`）。代价是**总体 task_success 不可跨断点比较**，曲线只能读
`common_scenarios()`——它恰好是 v1 的 6 类，因此 {3} 断点仍可复用 v1 上训练的
`sft-008` 作左端点。
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Sequence
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

#: 每个场景真正需要呈现给模型的工具。断点若没呈现这些工具，该场景在那个断点上
#: 无解——把它留在任务集里只会让读数掺进「工具根本不在」造成的失败。
#: `cancel_denied_*` 的 gold 序列只有 `get_order`，但拒绝的对象是取消动作，
#: 不呈现 `cancel_order` 时这个判断没有意义，因此一并要求。
_SCENARIO_TOOLS: dict[TaskScenario, tuple[str, ...]] = {
    TaskScenario.LOOKUP_STATUS: ("get_order",),
    TaskScenario.REFUND_ELIGIBLE: ("get_order", "refund_order"),
    TaskScenario.REFUND_DENIED_WINDOW: ("get_order", "refund_order"),
    TaskScenario.REFUND_DENIED_OWNERSHIP: ("get_order", "refund_order"),
    TaskScenario.REFUND_DENIED_DUPLICATE: ("get_order", "refund_order"),
    TaskScenario.REFUND_RECOVERY: ("get_order", "refund_order"),
    TaskScenario.CHECK_REFUND_STATUS: ("get_refund_status",),
    TaskScenario.CANCEL_ELIGIBLE: ("get_order", "cancel_order"),
    TaskScenario.CANCEL_DENIED_RECENT: ("get_order", "cancel_order"),
    TaskScenario.CANCEL_DENIED_IN_USE: ("get_order", "cancel_order"),
    TaskScenario.REFUND_THEN_CANCEL: ("get_order", "refund_order", "cancel_order"),
    TaskScenario.CANCEL_RECOVERY: ("get_order", "cancel_order"),
}


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


def scenarios_for(tool_count: int) -> tuple[TaskScenario, ...]:
    """该断点上可解的场景。

    断点之间任务集不同，因此**总体 task_success 不可跨断点比较**；退化曲线
    只能读所有断点共有的那几个场景（`common_scenarios()`），此时自变量就是
    干扰工具的数量。
    """
    available = set(_TOOL_SUBSETS[tool_count])
    return tuple(s for s in _SCENARIOS if set(_SCENARIO_TOOLS[s]) <= available)


def common_scenarios() -> tuple[TaskScenario, ...]:
    """在全部断点上都可解的场景——退化曲线唯一可比的读数面。"""
    shared = set(_SCENARIOS)
    for tool_count in _TOOL_SUBSETS:
        shared &= set(scenarios_for(tool_count))
    return tuple(s for s in _SCENARIOS if s in shared)


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

    @property
    def tool_names(self) -> tuple[str, ...]:
        """该断点呈现给模型的工具，评测与采集都必须按它构造环境。"""
        return _TOOL_SUBSETS[self.tool_count]

    @property
    def scenarios(self) -> tuple[TaskScenario, ...]:
        return scenarios_for(self.tool_count)

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
            if len(records) != expected * len(self.scenarios):
                raise ValueError(f"{split} 任务总数不符合该断点配额")


def stratified_sample(
    records: Sequence[ToolCountTaskRecord],
    per_scenario: int,
) -> tuple[ToolCountTaskRecord, ...]:
    """按「场景 × 难度」分层抽样，供小样本冒烟使用。

    两条性质由测试保证：

    1. **类型分布严格一致**——每个场景抽同样条数，而全量本身也是每场景等量，
       因此场景占比逐字相等；
    2. **难度按 `metadata["margin"]` 轴等距抽样**——生成器把 margin 按
       `_MARGINS` 循环铺开，等距下标取样因此覆盖 margin 全域（含最小与最大值）。
       场景内部把 margin 变换成实际期限的规则（如 `max(margin, 10)`）是
       `(scenario, margin)` 的确定性函数，所以保住这两维就保住了实际难度。

    小样本**无法**复现精确的 margin 直方图（`refund_denied_window` 的 10 条是
    1×2 / 2×4 / 3×2 / 5×1 / 7×1，抽 2 条时任何方案都做不到成比例）。这里保证的是
    **跨度**而不是比例：`per_scenario ≥ 2` 时最易与最难两档一定在样本里，
    中间档按不同取值等距铺开；某档取空了就按 margin 距离就近回填。
    抽样结果的实际直方图由 `sample_distribution` 给出，写进运行 manifest 备查
    ——不假装它等于全量。
    """
    if per_scenario < 1:
        msg = "per_scenario 必须 ≥ 1"
        raise ValueError(msg)
    by_scenario: dict[TaskScenario, list[ToolCountTaskRecord]] = {}
    for record in records:
        by_scenario.setdefault(record.task.scenario, []).append(record)
    sampled: list[ToolCountTaskRecord] = []
    for scenario, group in by_scenario.items():
        if per_scenario > len(group):
            msg = f"{scenario.value} 只有 {len(group)} 条，取不出 {per_scenario} 条"
            raise ValueError(msg)
        sampled.extend(_sample_one_scenario(group, per_scenario))
    return tuple(sampled)


def _margin_of(record: ToolCountTaskRecord) -> int:
    return int(record.task.metadata["margin"])


def _sample_one_scenario(
    group: Sequence[ToolCountTaskRecord],
    per_scenario: int,
) -> list[ToolCountTaskRecord]:
    by_margin: dict[int, list[ToolCountTaskRecord]] = {}
    for record in group:
        by_margin.setdefault(_margin_of(record), []).append(record)
    values = sorted(by_margin)
    if per_scenario == 1:
        wanted = [values[0]]
    else:
        span = len(values) - 1
        wanted = [values[round(index * span / (per_scenario - 1))] for index in range(per_scenario)]

    taken: list[ToolCountTaskRecord] = []
    used: set[str] = set()
    for margin in wanted:
        pool = [r for r in by_margin[margin] if r.task.task_id not in used]
        if not pool:
            # 该档取空——按 margin 距离就近回填，保持确定性
            remaining = [r for r in group if r.task.task_id not in used]
            pool = sorted(remaining, key=lambda r: (abs(_margin_of(r) - margin), r.task.task_id))
        chosen = pool[0]
        used.add(chosen.task.task_id)
        taken.append(chosen)
    return taken


def sample_distribution(
    records: Sequence[ToolCountTaskRecord],
) -> dict[str, dict[str, int]]:
    """场景 → margin 直方图。写进运行 manifest，让抽样是否有偏可被事后核对。"""
    distribution: dict[str, dict[str, int]] = {}
    for record in records:
        scenario = record.task.scenario.value
        margin = str(record.task.metadata.get("margin"))
        distribution.setdefault(scenario, {})
        distribution[scenario][margin] = distribution[scenario].get(margin, 0) + 1
    return {
        name: dict(sorted(hist.items(), key=lambda kv: int(kv[0])))
        for name, hist in distribution.items()
    }


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
    other_order_id: str = "",
) -> TaskSpec:
    orders = {
        order_id: _order(order_id, customer_id, margin, refund_status, order_status),
    }
    # REFUND_THEN_CANCEL 是双订单复合动作：退 A、取消 B。B 必须真的存在于
    # 环境里，否则这个场景永远不可解，而读数会被误读成"模型学不会复合动作"。
    if other_order_id:
        orders[other_order_id] = _order(other_order_id, customer_id, max(margin, 10), "none")
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
            target_state["orders"][other_order_id]["status"] = "cancelled"
            target_state["orders"][other_order_id]["cancel_status"] = "cancelled"
        else:
            target_state["orders"][order_id]["refund_status"] = "refunded"
    if expected_calls is None:
        expected_calls = []
    task_id = f"{scenario.value}-{split.value}-{order_id}-{margin}"
    # 多次调用的场景要留一步给收尾答复，否则 gold 序列正好用光步数。
    multi_call_scenarios = {
        TaskScenario.REFUND_RECOVERY,
        TaskScenario.REFUND_THEN_CANCEL,
        TaskScenario.CANCEL_RECOVERY,
    }
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
        max_steps=5 if scenario in multi_call_scenarios else 4,
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
        cancel_reason = _CANCEL_REASONS[index % len(_CANCEL_REASONS)]
        other_order_id = f"{order_id}-B"
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
                    name="get_order",
                    arguments={"order_id": other_order_id},
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
            other_order_id=other_order_id,
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
    for scenario in scenarios_for(tool_count):
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
