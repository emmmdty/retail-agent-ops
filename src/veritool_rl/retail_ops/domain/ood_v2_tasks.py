"""OOD v2：**只换说法**的分布外任务集。

## 与 v1 的分工

`ood_tasks.py`（v1）是**作者手写**的 60 条，混了三件事：表达偏离、场景做不到、对抗输入。
它回答了「120/120 是不是泛化」——答案是不是（LOG-20260816-01）。

v2 只回答一个更窄、也更能被修复的问题：**同一批业务任务，换一种说法还成不成。**

因此 v2 的构造是「六个冻结场景 × 每场景 10 条，业务语义与冻结契约逐条对应，
唯一变化是 user 的第一句话来自 LLM 措辞池」。它与 dev/holdout 是**配对**的：
同样的场景分布、同样的判定逻辑、同样的 verifier，**唯一的自变量是表面形式**。

## 为什么必须覆盖全部六个场景

只在 `refund_eligible` 上修和测，最省事的「修法」是让模型见谁都退款——
那会在四个拒绝类上崩掉，而单场景的评测集看不见这件事。
六个场景同时在场，「乱退款」这条捷径就当场暴露。

## 两个分片

`ood_dev` 用于迭代，`ood_sealed` **只观测一次**。两者的措辞由
`phrasing_bank.assign_partition` 按哈希切开，与训练增强用的 `train_aug` 逐条互斥。

## 这个集合**不**声称什么

措辞由**单一 provider、单一 prompt** 生成，因此它度量的是「对同一个生成器产出的、
未见过的措辞的鲁棒性」。**对任意真实用户输入的鲁棒性没有被测量。**
v1 那 60 条（作者手写，不同来源）因此保留为**独立迁移检查**，
且本轮不得用于任何候选选择——用它选候选就等于开始过拟合它。
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
    SCENARIO_INTENTS,
    PhrasingRecord,
)

OOD_V2_DATASET_VERSION = "retail_ops_ood_v2_20260817"

#: 第二份措辞池（`phrasing-bank-003`）构建出的分片。
#:
#: 生成器、状态空间、场景配额与判定逻辑与上一版**逐字段相同**，唯一的差别是素材。
#: 它必须有自己的版本号，否则两批内容完全不同的任务集会挂同一个 `dataset_version`——
#: 而 `task_id` 是 `sha256(f"oodv2:{seed}:{scenario}:{index}")`，**只依赖位置**，
#: 两份素材的 `task_ids` 逐条相同。仅凭这两个字段，两份评测集看起来一模一样。
#: 这与外部审阅在 v1/v2 上抓到的是同一类错误，只是发生在 v2 内部。
OOD_V2_2_DATASET_VERSION = "retail_ops_ood_v2_2_20260817"

OOD_V2_GENERATOR_ID = "ood_phrasing_bank_v2_full_state_space"

#: 每个场景的任务数。六场景 × 10 = 60，与 dev 同量级。
#: n=10 的逐场景 CI 宽度约 ±30pp——**足以看方向，不足以排序**，
#: 这一点必须与任何逐场景读数一起说。
OOD_V2_TASKS_PER_SCENARIO = 10

#: 六个冻结场景，顺序固定（进 task_id 的哈希，改顺序等于换数据集）。
OOD_V2_SCENARIOS: tuple[TaskScenario, ...] = (
    TaskScenario.LOOKUP_STATUS,
    TaskScenario.REFUND_ELIGIBLE,
    TaskScenario.REFUND_DENIED_WINDOW,
    TaskScenario.REFUND_DENIED_OWNERSHIP,
    TaskScenario.REFUND_DENIED_DUPLICATE,
    TaskScenario.REFUND_RECOVERY,
)

#: 取值域**与 `formal_tasks` 逐值相同**。
#:
#: 2026-08-17 的外部审阅发现第一版把状态空间收窄了：每条状态只有 1 个订单
#: （冻结集合是 1–5）、期限余量只有 ±6 一种（冻结集合有 7 种，含 ±1 这种边界）、
#: 订单状态只有 3 种（冻结集合有 7 种）。也就是说 OOD v2 在三个维度上都**更容易**，
#: 而四个文件都写着「唯一自变量是顾客怎么说」——**那句话是假的**。
#:
#: 这一版把三个维度全部对齐。「唯一自变量是说法」这句话现在才成立，
#: 由 `tests/test_ood_v2_tasks.py::test_the_state_space_matches_the_frozen_contract`
#: 逐维度断言——它直接构造冻结任务集来比对，而不是比对一份写死的清单。
_REASONS = ("damaged", "wrong_item", "not_as_described", "changed_mind")
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

#: 干扰订单数量的取值域，与冻结契约的 `context_variant` 相同（0–4）。
#: 干扰订单存在的意义：没有它，「退错订单」这一整类失败模式在结构上测不出来。
_DISTRACTOR_COUNTS = (0, 1, 2, 3, 4)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _identity(scenario: TaskScenario, index: int, seed: int) -> tuple[str, str]:
    token = _digest(f"{OOD_V2_DATASET_VERSION}:{seed}:{scenario.value}:{index}")
    return f"C-{token[:12].upper()}", f"O-{token[12:24].upper()}"


def _order(customer_id: str, overrides: dict[str, Any], margin: int = 6) -> dict[str, Any]:
    """默认订单 + 场景覆盖。

    `overrides` 用位置参数而不是 `**kwargs`：`refund_denied_ownership` 要覆盖的正是
    `customer_id`，用 `**overrides` 会与同名的位置参数撞车（第一版就是这么写的）。
    """
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
    reason: str,
    index: int,
    margin: int,
    status: str,
    distractor_count: int,
) -> tuple[dict[str, Any], dict[str, Any], list[ToolCall], ExpectedDecision, dict[str, int], int]:
    """返回 (initial_state, target_state, expected_calls, decision, transient, max_steps)。

    每一项都与 `formal_tasks._scenario_contract` 的同名场景语义逐条对应——
    v2 改的是**顾客怎么说**，不是**任务是什么**。
    """
    get_order = ToolCall(name="get_order", arguments={"order_id": order_id})
    refund = ToolCall(name="refund_order", arguments={"order_id": order_id, "reason": reason})

    overrides: dict[str, Any]
    transient: dict[str, int]
    if scenario is TaskScenario.LOOKUP_STATUS:
        overrides = {"status": status}
        decision, calls, transient, steps = ExpectedDecision.INFORM, [get_order], {}, 4
    elif scenario is TaskScenario.REFUND_ELIGIBLE:
        overrides = {}
        decision, calls, transient, steps = ExpectedDecision.ALLOW, [get_order, refund], {}, 4
    elif scenario is TaskScenario.REFUND_RECOVERY:
        overrides = {}
        decision = ExpectedDecision.ALLOW
        calls = [get_order, refund, copy.deepcopy(refund)]
        transient, steps = {"refund_order": 1}, 5
    elif scenario is TaskScenario.REFUND_DENIED_WINDOW:
        overrides = {"refund_deadline": _CURRENT_DAY - margin}
        decision, calls, transient, steps = ExpectedDecision.DENY, [get_order], {}, 4
    elif scenario is TaskScenario.REFUND_DENIED_OWNERSHIP:
        overrides = {"customer_id": f"{customer_id}-OTHER"}
        decision, calls, transient, steps = ExpectedDecision.DENY, [get_order], {}, 4
    elif scenario is TaskScenario.REFUND_DENIED_DUPLICATE:
        overrides = {"refund_status": "refunded"}
        decision, calls, transient, steps = ExpectedDecision.DENY, [get_order], {}, 4
    else:  # pragma: no cover - 由 OOD_V2_SCENARIOS 穷举保证
        raise ValueError(f"不支持的场景: {scenario}")

    orders: dict[str, Any] = {order_id: _order(customer_id, overrides, margin)}
    # 干扰订单：与冻结契约同构（同一个 owner 之外的订单、固定 shipped、期限充裕）。
    # 它们让「退错订单」成为一种**可能发生**的失败，没有它这一类测不出来。
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
        target["orders"][order_id]["refund_status"] = "refunded"
    return initial, target, calls, decision, transient, steps


def build_ood_v2_tasks(
    index: Mapping[str, Sequence[PhrasingRecord]],
    seed: int = 0,
) -> list[TaskSpec]:
    """按措辞池的某个分片生成 60 条任务。

    `index` 是 `phrasing_bank.intent_index(records, partition)` 的产物。
    取措辞的方式与训练增强同构：按任务哈希决定起点，在排好序的池子里连续取，
    保证确定性与铺开。
    """
    tasks: list[TaskSpec] = []
    for scenario in OOD_V2_SCENARIOS:
        intent = SCENARIO_INTENTS[scenario]
        pool = index.get(intent, ())
        if len(pool) < OOD_V2_TASKS_PER_SCENARIO:
            raise ValueError(
                f"意图 {intent} 只有 {len(pool)} 条措辞，"
                f"不足以给场景 {scenario.value} 生成 {OOD_V2_TASKS_PER_SCENARIO} 条互不相同的任务"
            )
        offset = int(_digest(f"{seed}:{scenario.value}")[:8], 16)
        for index_in_scenario in range(OOD_V2_TASKS_PER_SCENARIO):
            customer_id, order_id = _identity(scenario, index_in_scenario, seed)
            reason = _REASONS[index_in_scenario % len(_REASONS)]
            phrasing = pool[(offset + index_in_scenario) % len(pool)]
            initial, target, calls, decision, transient, steps = _contract(
                scenario,
                customer_id,
                order_id,
                reason,
                index_in_scenario,
                margin=_MARGINS[index_in_scenario % len(_MARGINS)],
                status=_LOOKUP_STATUSES[index_in_scenario % len(_LOOKUP_STATUSES)],
                distractor_count=_DISTRACTOR_COUNTS[index_in_scenario % len(_DISTRACTOR_COUNTS)],
            )
            tasks.append(
                TaskSpec(
                    task_id=_digest(f"oodv2:{seed}:{scenario.value}:{index_in_scenario}"),
                    split="test",
                    scenario=scenario,
                    user_request=phrasing.text.replace(ORDER_ID_PLACEHOLDER, order_id),
                    initial_state=initial,
                    target_state=target,
                    expected_calls=calls,
                    expected_decision=decision,
                    required_reads=[order_id],
                    transient_failures=transient,
                    max_steps=steps,
                    metadata={
                        "dataset_version": OOD_V2_DATASET_VERSION,
                        "generator_id": OOD_V2_GENERATOR_ID,
                        # 逐场景与逐风格两个切面：前者看「有没有靠乱退款作弊」，
                        # 后者看「哪一类说法还没修好」。
                        "ood_category": scenario.value,
                        "ood_kind": phrasing.style,
                        "phrasing_id": phrasing.phrasing_id,
                        "order_id": order_id,
                        "reason": reason,
                    },
                )
            )
    return tasks
