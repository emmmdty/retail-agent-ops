"""状态增强任务：在**冻结网格之外**的 margin 上补训练素材。

## 为什么在网格外

冻结数据集只用 7 个 margin（`formal_tasks._MARGINS = (1,2,3,5,7,10,14)`），
每个场景的 35 个 family（7 margin × 5 context）已经**穷尽分配**给 train/dev/holdout。
因此任何"在网格内多造一点训练数据"的做法都会复现某个 dev 或 holdout family 的语义——
那是泄漏，不是增强。

**网格的补集是自由的**：用 `_MARGINS` 里没有的取值构造出的 family，
按构造不可能与任何冻结 family 相同。这一点由
`assert_disjoint_from_frozen_grid` 在构建时断言，不靠人记得。

## 补哪里

`docs/POLICY_BOUNDARY.md` 的读数：候选 `sft-008` 在探针的 15 个偏移量里 14 个是 1.00，
唯独 `offset = −14`（`refund_deadline = 6`）塌到 0.375，全部 5 次政策违规都在那一点；
而 `refund_denied_window` 的训练集里 margin ≥ 10 的 family 只占 10%，封存集占 50%。
所以补的是**远超期区域**。

## 为什么两侧都补

只补拒绝侧的话，"模型学会了规则"与"模型学会了多拒绝"在读数上无法区分，
而后者会在放行侧塌掉。两侧用**同一组 margin**，因此这次改动在
「窗口内 vs 已过期」这个维度上是对称的，不引入新的偏置。

## 与评测点不相交

探针在 `refund_deadline` = 6（offset −14）与 10（offset −10）上测；
增强素材一条都不用这两个值。因此复测读数是**区域内的插值/外推**，不是记忆。
`assert_disjoint_from_probe` 断言这一点。
"""

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
from veritool_rl.retail_ops.domain.formal_tasks import _CURRENT_DAY, _MARGINS

STATE_AUG_DATASET_VERSION = "retail_ops_state_aug_v1_20260819"
STATE_AUG_GENERATOR_ID = "off_grid_margin_augmentation_v1"

#: 网格外的 margin。全部 ∉ `_MARGINS`，全部落在**远离决策边界**的一侧
#: （最小 8 > 冻结网格里第二大的 7），因为要补的是远超期区域。
#: 上限 18 使拒绝侧的 `refund_deadline` 保持 ≥ 2，不产生 0 或负数日期。
OFF_GRID_MARGINS: tuple[int, ...] = (8, 9, 11, 12, 13, 16, 18)

#: 每个 (场景, margin) 的实例数。7 × 4 × 2 侧 = 56 条任务。
#: 配上 `per_task` 条措辞改写后进入训练集，量级相对既有 960 行约为 +23%。
INSTANCES_PER_MARGIN = 4

#: 两个场景：窗口内应放行、已过期应拒绝。其余四个场景本轮不动——
#: 诊断指向的是退款窗口这一条规则，动别的场景会让变量不单一。
AUGMENTED_SCENARIOS = (TaskScenario.REFUND_ELIGIBLE, TaskScenario.REFUND_DENIED_WINDOW)

_REASONS = ("damaged", "wrong_item", "not_as_described", "changed_mind")
_DISTRACTOR_COUNTS = (0, 1, 2, 3)


#: 探针实际评测的 `refund_deadline` 取值——增强素材必须避开它们。
#: 由 `policy_boundary_tasks.OFFSETS` 派生，不在这里重抄一遍。
def probe_deadlines() -> frozenset[int]:
    from veritool_rl.retail_ops.domain.policy_boundary_tasks import CURRENT_DAY, OFFSETS

    return frozenset(CURRENT_DAY + offset for offset in OFFSETS)


def assert_disjoint_from_frozen_grid() -> None:
    """网格外的 margin 不得与冻结网格相交——相交即等于复现某个 dev/holdout family。"""
    overlap = sorted(set(OFF_GRID_MARGINS) & set(_MARGINS))
    if overlap:
        raise ValueError(
            f"增强 margin {overlap} 落在冻结网格 {_MARGINS} 内——"
            f"那会复现某个 dev/holdout family 的语义，是泄漏而不是增强"
        )


def assert_disjoint_from_probe() -> None:
    """增强素材的 `refund_deadline` 不得与探针的评测点相交。

    相交的话，复测读数就分不清是"学会了规则"还是"背下了那一格"。
    """
    produced = {
        _deadline_for(scenario, margin)
        for scenario in AUGMENTED_SCENARIOS
        for margin in OFF_GRID_MARGINS
    }
    overlap = sorted(produced & probe_deadlines())
    if overlap:
        raise ValueError(
            f"增强素材的 refund_deadline {overlap} 与探针评测点相交——"
            f"复测就分不清学会了规则还是背下了那一格"
        )


def _deadline_for(scenario: TaskScenario, margin: int) -> int:
    if scenario is TaskScenario.REFUND_ELIGIBLE:
        return _CURRENT_DAY + margin
    return _CURRENT_DAY - margin


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _user_request(order_id: str, reason: str, variant: int) -> str:
    """与冻结数据集同源的两条模板，两侧共用。

    这里刻意**不**做措辞多样化：多样化由 `sft_paraphrase` 的 `train_aug` 分片承担，
    与既有 960 行走的是同一条路径。在这里另造一套措辞会引入第二个变量。
    """
    templates = (
        f"请检查订单 {order_id} 是否能因 {reason} 退款。",
        f"我想为 {order_id} 申请 {reason} 的退款，请核实。",
    )
    return templates[variant]


def build_state_augmentation_tasks(seed: int = 0) -> list[TaskSpec]:
    """构造网格外的训练增强任务。两个断言在产出任何任务之前先跑。"""
    assert_disjoint_from_frozen_grid()
    assert_disjoint_from_probe()

    tasks: list[TaskSpec] = []
    for scenario in AUGMENTED_SCENARIOS:
        allow = scenario is TaskScenario.REFUND_ELIGIBLE
        decision = ExpectedDecision.ALLOW if allow else ExpectedDecision.DENY
        for margin in OFF_GRID_MARGINS:
            deadline = _deadline_for(scenario, margin)
            for instance in range(INSTANCES_PER_MARGIN):
                identity = _digest(f"stateaug:{seed}:{scenario.value}:{margin}:{instance}")
                customer_id = f"C-{identity[:12].upper()}"
                order_id = f"O-{identity[24:36].upper()}"
                reason = _REASONS[instance % len(_REASONS)]
                distractor_count = _DISTRACTOR_COUNTS[instance % len(_DISTRACTOR_COUNTS)]

                orders: dict[str, Any] = {
                    order_id: {
                        "customer_id": customer_id,
                        "status": "delivered",
                        "refund_deadline": deadline,
                        "refund_status": "none",
                    }
                }
                for distractor_index in range(distractor_count):
                    distractor = _digest(f"{identity}:distractor:{distractor_index}")
                    orders[f"O-{distractor[:12].upper()}"] = {
                        "customer_id": f"C-{distractor[12:24].upper()}",
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
                get_order = ToolCall(name="get_order", arguments={"order_id": order_id})
                if allow:
                    expected_calls = [
                        get_order,
                        ToolCall(
                            name="refund_order",
                            arguments={"order_id": order_id, "reason": reason},
                        ),
                    ]
                    target_state["orders"][order_id]["refund_status"] = "refunded"
                else:
                    expected_calls = [get_order]

                tasks.append(
                    TaskSpec(
                        task_id=_digest(
                            f"stateaug-task:{seed}:{scenario.value}:{margin}:{instance}"
                        ),
                        # teacher 采集只接受 train split——这些确实是训练素材。
                        split="train",
                        scenario=scenario,
                        user_request=_user_request(order_id, reason, instance % 2),
                        initial_state=initial_state,
                        target_state=target_state,
                        expected_calls=expected_calls,
                        expected_decision=decision,
                        required_reads=[order_id],
                        transient_failures={},
                        max_steps=4,
                        metadata={
                            "dataset_version": STATE_AUG_DATASET_VERSION,
                            "generator_id": STATE_AUG_GENERATOR_ID,
                            "margin": margin,
                            "refund_deadline": deadline,
                            "order_id": order_id,
                            "reason": reason,
                            "distractor_count": distractor_count,
                        },
                    )
                )
    return tasks
