"""政策边界探针：把「退款窗口」这条规则的**决策边界**量出来。

## 为什么需要它

冻结数据集把每个场景的 35 个 family 按哈希切成 train 20 / dev 5 / holdout 10。
哈希切分**不对难度维度分层**，而 `refund_denied_window` 的难度就是一个数：
`refund_deadline − current_day` 离 0 有多远。实际落到各切分上的覆盖是：

| 场景 | dev 覆盖的 margin 档 | holdout 覆盖的 margin 档 |
|---|---|---|
| `refund_denied_window` | 4/7（缺 2、5、7） | 6/7 |
| `refund_denied_duplicate` | **2/7**（只有 2、5） | 6/7 |
| `refund_denied_ownership` | 5/7 | 5/7，与 dev 只交 3 档 |

于是 dev 那 10 条**结构上**看不见 holdout 里的一部分状态——这不是样本量问题，
是覆盖问题。项目此前从读数上观察到「dev 与封存集把两次运行排成相反顺序」
（LOG-20260817-07），这张表给出的是它的机制解释，且只用到公开的生成器代码。

## 这个集合是什么

沿 `refund_deadline − current_day` 扫一条线：**正数 = 窗口内（应放行）、
负数 = 已过期（应拒绝）、0 = 恰好到期（政策判定为放行）**。
每个偏移量取 8 个实例（退款理由 × 干扰订单数 × 请求措辞变体）。

`ood_kind` 直接写偏移量，因此 OOD 报告里现成的 `kind_success` 就是**决策曲线**：
横轴是偏移量，纵轴是该点的判定正确率。不需要任何新的报告代码。

## 它能回答什么、不能回答什么

- **能**：模型学到的边界落在哪里、边界附近是否模糊、两侧是否对称。
- **能**：`offset = 0` 这个点——**冻结数据集从未生成过它**
  （eligible 用 `20 + margin`、denied 用 `20 - margin`，`margin ≥ 1`），
  因此整个 train/dev/holdout 都没测过恰好到期这一天。
- **不能**：它不是分布外评测。措辞来自与冻结数据集同一套模板，
  状态空间是同一条轴上的加密网格。**它测的是策略边界，不是泛化。**
- **不能**：它不替代封存 holdout。它公开、可反复读、可用于迭代——
  正因如此，它的读数**不能**用来声称发布结论。
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

POLICY_BOUNDARY_DATASET_VERSION = "retail_ops_policy_boundary_v1_20260819"
POLICY_BOUNDARY_GENERATOR_ID = "policy_boundary_sweep_v1"

#: 冻结数据集里的「今天」。这里不 import `formal_tasks._CURRENT_DAY`（私有），
#: 而是重新声明并由 `test_the_probe_shares_the_frozen_calendar` 断言两者相等——
#: 若冻结数据集换了日历基准，探针必须跟着换，否则两边的偏移量不可比。
CURRENT_DAY = 20

#: 扫描网格：`refund_deadline − current_day`。
#:
#: 边界两侧刻意**非对称加密**：靠近 0 的点密（−3…+3 全取），远端稀疏。
#: 决策边界的信息全部集中在 0 附近，把预算花在 ±14 上是浪费。
#: **0 必须在网格里**——它是政策的判定分界，且冻结数据集从未生成过它。
OFFSETS: tuple[int, ...] = (-14, -10, -7, -5, -3, -2, -1, 0, 1, 2, 3, 5, 7, 10, 14)

#: 每个偏移量的实例数。8 = 4 种退款理由 × 2 种请求措辞变体，干扰订单数随实例轮转。
#: 逐点 n=8 的 95% CI 宽度约 ±35pp：**足以看曲线形状，不足以给单点排序**，
#: 这一条必须与任何逐点读数一起说。
INSTANCES_PER_OFFSET = 8

_REASONS = ("damaged", "wrong_item", "not_as_described", "changed_mind")
_DISTRACTOR_COUNTS = (0, 1, 2, 3)


def offset_kind(offset: int) -> str:
    """偏移量的稳定标签。进 `task_id` 的哈希，改它等于换数据集。"""
    return f"offset_{offset:+d}"


def expected_decision_for(offset: int) -> ExpectedDecision:
    """政策的判定：`days_past_deadline > 0` 才拒绝，因此**恰好到期仍然放行**。

    这一条不是这里定的，是 `domains/retail_ops/v2/policies.yaml` 里
    `refund_window_must_be_open` 的 `{fact: days_past_deadline, gt: 0}`。
    `test_the_probe_agrees_with_the_executable_policy` 逐点比对两者。
    """
    return ExpectedDecision.ALLOW if offset >= 0 else ExpectedDecision.DENY


def scenario_for(offset: int) -> TaskScenario:
    return TaskScenario.REFUND_ELIGIBLE if offset >= 0 else TaskScenario.REFUND_DENIED_WINDOW


def expected_category_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for offset in OFFSETS:
        counts[scenario_for(offset).value] = (
            counts.get(scenario_for(offset).value, 0) + INSTANCES_PER_OFFSET
        )
    return counts


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _user_request(order_id: str, reason: str, variant: int) -> str:
    """请求措辞与冻结数据集同源。

    **两侧用同一组措辞**：若「过期」那一侧的问法自带犹豫语气而「窗口内」那一侧
    自带祈使语气，模型就能靠语气而不是靠日期作答，探针测到的边界会是假的。
    """
    templates = (
        f"请检查订单 {order_id} 是否能因 {reason} 退款。",
        f"我想为 {order_id} 申请 {reason} 的退款，请核实。",
    )
    return templates[variant]


def build_policy_boundary_tasks(seed: int = 0) -> list[TaskSpec]:
    """沿退款窗口这条轴生成确定性探针任务集。"""
    tasks: list[TaskSpec] = []
    for offset in OFFSETS:
        scenario = scenario_for(offset)
        decision = expected_decision_for(offset)
        for instance in range(INSTANCES_PER_OFFSET):
            identity = _digest(f"boundary:{seed}:{offset}:{instance}")
            customer_id = f"C-{identity[:12].upper()}"
            order_id = f"O-{identity[24:36].upper()}"
            reason = _REASONS[instance % len(_REASONS)]
            variant = instance % 2
            distractor_count = _DISTRACTOR_COUNTS[instance % len(_DISTRACTOR_COUNTS)]

            orders: dict[str, Any] = {
                order_id: {
                    "customer_id": customer_id,
                    "status": "delivered",
                    "refund_deadline": CURRENT_DAY + offset,
                    "refund_status": "none",
                }
            }
            for distractor_index in range(distractor_count):
                distractor = _digest(f"{identity}:distractor:{distractor_index}")
                orders[f"O-{distractor[:12].upper()}"] = {
                    "customer_id": f"C-{distractor[12:24].upper()}",
                    "status": "shipped",
                    "refund_deadline": CURRENT_DAY + 30,
                    "refund_status": "none",
                }

            initial_state: dict[str, Any] = {
                "customer_id": customer_id,
                "current_day": CURRENT_DAY,
                "orders": orders,
            }
            target_state = copy.deepcopy(initial_state)

            get_order = ToolCall(name="get_order", arguments={"order_id": order_id})
            if decision is ExpectedDecision.ALLOW:
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
                    task_id=_digest(f"boundary-task:{seed}:{offset}:{instance}"),
                    split="test",
                    scenario=scenario,
                    user_request=_user_request(order_id, reason, variant),
                    initial_state=initial_state,
                    target_state=target_state,
                    expected_calls=expected_calls,
                    expected_decision=decision,
                    required_reads=[order_id],
                    transient_failures={},
                    max_steps=4,
                    metadata={
                        "dataset_version": POLICY_BOUNDARY_DATASET_VERSION,
                        "generator_id": POLICY_BOUNDARY_GENERATOR_ID,
                        # category 看「放行侧 / 拒绝侧」，kind 看**具体偏移量**——
                        # 后者就是决策曲线的横轴，OOD 报告的 kind_success 直接给出纵轴。
                        "ood_category": scenario.value,
                        "ood_kind": offset_kind(offset),
                        "deadline_offset_days": offset,
                        "order_id": order_id,
                        "reason": reason,
                        "distractor_count": distractor_count,
                    },
                )
            )
    return tasks
