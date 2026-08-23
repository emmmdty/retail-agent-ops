"""OOD v4：**跨工具泛化**的分布外任务集（Phase B 核心检验）。

## 与 v2 的分工

`ood_v2_tasks.py` 回答「同一批业务任务，换一种说法还成不成」——它只覆盖 v1 的
六个退款场景、三工具。Phase B 把工具面扩到五个（新增 get_refund_status 与
cancel_order，两者与原有工具有**语义重叠**），因此本轮要回答的问题是：

**在语义重叠的工具之间，模型能不能选对？换了说法之后还能不能选对？**

v4 任务集因此有三个与 v2 的差别：

1. **十二个场景全覆盖**：包括需要 get_refund_status / cancel_order 的六个新场景。
   「查进度却调 get_order」「要取消却调 refund_order」这类工具选错只有在新场景在场时才测得出来。
2. **措辞取自 bank-v4 的 `ood_dev` 分片**：与训练增强用的 `train_aug` 逐条互斥
   （同一哈希三分），因此它同时度量说法泛化与工具选择，两者不可分离——
   这是设计使然：真实用户既会换说法也会触发工具选择。
3. **refund_then_cancel 是双订单任务**：措辞含 `{order_id}`+`{other_order_id}`
   双占位符；gold 序列要求对第二笔订单执行 cancel_order——把「取消」做成「退款」
   正是 LOG-20260822-03/04 观察到的核心混淆，这里给它一个专门的正面计量口径。

## 这个集合不声称什么

与 v2 相同的边界照搬：单一 provider、单一 prompt 生成的措辞；
对任意真实用户输入的鲁棒性没有被测量。n=10/场景只够看方向。
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from veritool_rl.core.trajectory import (
    ExpectedDecision,
    TaskScenario,
    TaskSpec,
    ToolCall,
)
from veritool_rl.retail_ops.build.phrasing_bank import (
    ORDER_ID_PLACEHOLDER,
    OTHER_ORDER_ID_PLACEHOLDER,
    SCENARIO_INTENTS,
    PhrasingRecord,
)

OOD_V4_DATASET_VERSION = "retail_ops_ood_v4_20260823"
OOD_V4_GENERATOR_ID = "ood_phrasing_bank_v4_cross_tool"

#: 十二场景 × 每场景 10 条 = 120。n=10 的逐场景 CI 约 ±30pp——看方向，不排序，
#: 与任何逐场景读数一起说。
OOD_V4_TASKS_PER_SCENARIO = 10

#: 十二个冻结场景，顺序固定（进 task_id 哈希，改顺序等于换数据集）。
OOD_V4_SCENARIOS: tuple[TaskScenario, ...] = (
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

#: 取值域与 `formal_tasks` / `ood_v2_tasks` 逐值相同（唯一自变量仍是说法）。
_REASONS = ("damaged", "wrong_item", "not_as_described", "changed_mind")
_CANCEL_REASONS = ("changed_mind", "duplicate_order", "billing_error", "quality_concern")
_LOOKUP_STATUSES = (
    "pending",
    "processing",
    "shipped",
    "delivered",
    "cancelled",
    "returned",
    "refunded",
)
_MARGINS = (1, 2, 3, 5, 7, 10, 14)
_CURRENT_DAY = 20
_DISTRACTOR_COUNTS = (0, 1, 2, 3, 4)
#: check_refund_status 场景的退款状态取值域（与环境观测一致）。
_REFUND_STATUSES = ("processing", "completed", "denied", "pending", "none", "refunded")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _order(customer_id: str, overrides: dict[str, Any], margin: int) -> dict[str, Any]:
    order: dict[str, Any] = {
        "customer_id": customer_id,
        "status": "delivered",
        "refund_deadline": _CURRENT_DAY + margin,
        "refund_status": "none",
    }
    order.update(overrides)
    return order


def _contract(
    scenario: TaskScenario,
    customer_id: str,
    order_id: str,
    other_order_id: str,
    reason: str,
    margin: int,
    status: str,
    distractor_count: int,
) -> tuple[dict[str, Any], dict[str, Any], list[ToolCall], ExpectedDecision, dict[str, int], int]:
    """返回 (initial_state, target_state, expected_calls, decision, transient, max_steps)。

    每一项与 `formal_tasks._v4_scenario_contract_dispatch` 的同名场景语义逐条对应：
    v4 改的是顾客怎么说（以及覆盖哪些工具组合），不是任务判定本身。
    """
    get_order = ToolCall(name="get_order", arguments={"order_id": order_id})
    refund = ToolCall(name="refund_order", arguments={"order_id": order_id, "reason": reason})
    cancel_reason = _CANCEL_REASONS[_MARGINS.index(margin) % len(_CANCEL_REASONS)]

    overrides: dict[str, Any]
    transient: dict[str, int]
    steps = 4
    if scenario is TaskScenario.LOOKUP_STATUS:
        overrides = {"status": status}
        decision, calls, transient = ExpectedDecision.INFORM, [get_order], {}
    elif scenario is TaskScenario.REFUND_ELIGIBLE:
        overrides = {}
        decision, calls, transient = ExpectedDecision.ALLOW, [get_order, refund], {}
    elif scenario is TaskScenario.REFUND_RECOVERY:
        overrides = {}
        decision = ExpectedDecision.ALLOW
        calls = [get_order, refund, copy.deepcopy(refund)]
        transient, steps = {"refund_order": 1}, 5
    elif scenario is TaskScenario.REFUND_DENIED_WINDOW:
        overrides = {"refund_deadline": _CURRENT_DAY - margin}
        decision, calls, transient = ExpectedDecision.DENY, [get_order], {}
    elif scenario is TaskScenario.REFUND_DENIED_OWNERSHIP:
        overrides = {"customer_id": f"{customer_id}-OTHER"}
        decision, calls, transient = ExpectedDecision.DENY, [get_order], {}
    elif scenario is TaskScenario.REFUND_DENIED_DUPLICATE:
        overrides = {"refund_status": "refunded"}
        decision, calls, transient = ExpectedDecision.DENY, [get_order], {}
    elif scenario is TaskScenario.CHECK_REFUND_STATUS:
        status_value = _REFUND_STATUSES[_MARGINS.index(margin) % len(_REFUND_STATUSES)]
        overrides = {"refund_status": status_value}
        probe = ToolCall(name="get_refund_status", arguments={"order_id": order_id})
        decision, calls, transient = ExpectedDecision.INFORM, [probe], {}
    elif scenario is TaskScenario.CANCEL_ELIGIBLE:
        overrides = {"status": "pending"}
        cancel = ToolCall(
            name="cancel_order", arguments={"order_id": order_id, "reason": cancel_reason}
        )
        decision, calls, transient = ExpectedDecision.ALLOW, [get_order, cancel], {}
    elif scenario is TaskScenario.CANCEL_DENIED_RECENT:
        # 取消窗口已过：环境按 refund_deadline 判定（LOG-20260822-01 的修复）。
        overrides = {"status": "pending", "refund_deadline": _CURRENT_DAY - margin}
        decision, calls, transient = ExpectedDecision.DENY, [get_order], {}
    elif scenario is TaskScenario.CANCEL_DENIED_IN_USE:
        overrides = {"status": "shipped"}
        decision, calls, transient = ExpectedDecision.DENY, [get_order], {}
    elif scenario is TaskScenario.REFUND_THEN_CANCEL:
        # 双订单：先退主订单，再取消另一笔。gold 对第二笔的动作是 cancel 而非 refund
        # ——这正是语义重叠下最容易做错的那一步，本场景就是它的专门计量口径。
        overrides = {}
        get_other = ToolCall(name="get_order", arguments={"order_id": other_order_id})
        cancel_other = ToolCall(
            name="cancel_order", arguments={"order_id": other_order_id, "reason": cancel_reason}
        )
        decision = ExpectedDecision.ALLOW
        calls = [get_order, refund, get_other, cancel_other]
        transient, steps = {}, 5
    elif scenario is TaskScenario.CANCEL_RECOVERY:
        overrides = {"status": "pending"}
        cancel = ToolCall(
            name="cancel_order", arguments={"order_id": order_id, "reason": cancel_reason}
        )
        decision = ExpectedDecision.ALLOW
        calls = [get_order, cancel, copy.deepcopy(cancel)]
        transient, steps = {"cancel_order": 1}, 5
    else:  # pragma: no cover - 由 OOD_V4_SCENARIOS 穷举保证
        raise ValueError(f"不支持的场景: {scenario}")

    orders: dict[str, Any] = {order_id: _order(customer_id, overrides, margin)}
    if scenario is TaskScenario.REFUND_THEN_CANCEL:
        orders[other_order_id] = {
            "customer_id": customer_id,
            "status": "pending",
            "refund_deadline": _CURRENT_DAY + margin,
            "refund_status": "none",
        }
    for distractor_index in range(distractor_count):
        token = _digest(f"distractor:{order_id}:{distractor_index}")
        orders[f"O-{token[:12].upper()}"] = {
            "customer_id": f"C-{token[12:24].upper()}",
            "status": "shipped",
            "refund_deadline": _CURRENT_DAY + 30,
            "refund_status": "none",
        }
    initial: dict[str, Any] = {
        "customer_id": customer_id,
        "current_day": _CURRENT_DAY,
        "orders": orders,
    }
    target = copy.deepcopy(initial)
    if decision is ExpectedDecision.ALLOW:
        if scenario in (TaskScenario.CANCEL_ELIGIBLE, TaskScenario.CANCEL_RECOVERY):
            target["orders"][order_id]["status"] = "cancelled"
            target["orders"][order_id]["cancel_status"] = "cancelled"
        elif scenario is TaskScenario.REFUND_THEN_CANCEL:
            target["orders"][order_id]["refund_status"] = "refunded"
            target["orders"][other_order_id]["status"] = "cancelled"
            target["orders"][other_order_id]["cancel_status"] = "cancelled"
        else:
            target["orders"][order_id]["refund_status"] = "refunded"
    return initial, target, calls, decision, transient, steps


def build_ood_v4_tasks(
    index: Mapping[str, Sequence[PhrasingRecord]],
    seed: int = 0,
) -> list[TaskSpec]:
    """按 bank-v4 某分片生成 12×10=120 条跨工具任务。

    取措辞的方式与训练增强同构：按场景哈希决定起点，在排好序的池子里连续取，
    保证确定性与铺开。双订单场景的措辞必须含 `{other_order_id}`，
    单订单场景的措辞必须不含——填错了就抛错，绝不静默产出半截语义的任务。
    """
    tasks: list[TaskSpec] = []
    for scenario in OOD_V4_SCENARIOS:
        intent = SCENARIO_INTENTS[scenario]
        pool = index.get(intent, ())
        if len(pool) < OOD_V4_TASKS_PER_SCENARIO:
            raise ValueError(
                f"意图 {intent} 只有 {len(pool)} 条措辞，"
                f"不足以给场景 {scenario.value} 生成 {OOD_V4_TASKS_PER_SCENARIO} 条互不相同的任务"
            )
        offset = int(_digest(f"{seed}:{scenario.value}")[:8], 16)
        for index_in_scenario in range(OOD_V4_TASKS_PER_SCENARIO):
            token = _digest(f"{OOD_V4_DATASET_VERSION}:{seed}:{scenario.value}:{index_in_scenario}")
            customer_id = f"C-{token[:12].upper()}"
            order_id = f"O-{token[12:24].upper()}"
            other_order_id = f"O-{token[24:36].upper()}OTHER"
            reason = _REASONS[index_in_scenario % len(_REASONS)]
            margin = _MARGINS[index_in_scenario % len(_MARGINS)]
            status = _LOOKUP_STATUSES[index_in_scenario % len(_LOOKUP_STATUSES)]
            distractor_count = _DISTRACTOR_COUNTS[index_in_scenario % len(_DISTRACTOR_COUNTS)]
            phrasing = pool[(offset + index_in_scenario) % len(pool)]

            text = phrasing.text
            needs_other = OTHER_ORDER_ID_PLACEHOLDER in text
            if scenario is TaskScenario.REFUND_THEN_CANCEL and not needs_other:
                msg = (
                    f"refund_then_cancel 措辞缺少 {OTHER_ORDER_ID_PLACEHOLDER}: "
                    f"{phrasing.phrasing_id}"
                )
                raise ValueError(msg)
            if scenario is not TaskScenario.REFUND_THEN_CANCEL and needs_other:
                msg = f"单订单场景措辞含 {OTHER_ORDER_ID_PLACEHOLDER}: {phrasing.phrasing_id}"
                raise ValueError(msg)

            user_request = text.replace(ORDER_ID_PLACEHOLDER, order_id)
            if needs_other:
                user_request = user_request.replace(OTHER_ORDER_ID_PLACEHOLDER, other_order_id)

            initial, target, calls, decision, transient, steps = _contract(
                scenario,
                customer_id,
                order_id,
                other_order_id,
                reason,
                margin=margin,
                status=status,
                distractor_count=distractor_count,
            )
            tasks.append(
                TaskSpec(
                    task_id=_digest(f"oodv4:{seed}:{scenario.value}:{index_in_scenario}"),
                    split="test",
                    scenario=scenario,
                    user_request=user_request,
                    initial_state=initial,
                    target_state=target,
                    expected_calls=calls,
                    expected_decision=decision,
                    required_reads=[order_id],
                    transient_failures=transient,
                    max_steps=steps,
                    metadata={
                        "dataset_version": OOD_V4_DATASET_VERSION,
                        "generator_id": OOD_V4_GENERATOR_ID,
                        "ood_category": scenario.value,
                        "ood_kind": phrasing.style,
                        "phrasing_id": phrasing.phrasing_id,
                        "order_id": order_id,
                        "reason": reason,
                    },
                )
            )
    return tasks
