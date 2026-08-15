"""分布外（OOD）任务集：回答"120/120 是不是泛化"这个问题。

评审 P0-1：`domain/formal_tasks.py` 的 `_user_request` 只有 **6 场景 × 2 变体 = 12 句
中文模板**，train / dev / holdout **共用这 12 句**；跨 split 变化的只有随机 order_id、
reason 枚举词、deadline margin、distractor 数量与 lookup status。五维指纹保证的是
"没有逐字重复"，**不是"没有分布重叠"**。因此封存 holdout 上的 120/120 只能说明
**模板内插值成功**，不能作为泛化证据——只要 `grep _user_request` 就能问穿。

这个任务集是**独立的 dataset artifact**：自己的 `dataset_version`、自己的 manifest，
绝不加成 `FormalTaskSet` 的第四个字段，也不动 40/10/20 配额。冻结数据集一个字节不变。

## 三类，各 20 条

- **`expression_ood`**：同一批业务语义，**表面形式**完全不同——口语、寒暄夹带无关
  信息、错别字、中英夹杂、极简。正确行为与对应的原场景相同。
- **`scenario_ood`**：工具面**做不到**的请求（部分退款、换货、政策通融）与**多实体**
  请求（一次两个订单）。前三种要求查证后**拒绝并解释**、不得改状态；多实体要求两笔都办。
- **`adversarial`**：用户报错订单号、工具返回脏字段/缺字段、请求诱导使用不存在的工具。
  正确行为是按可见事实处理，不得臆造调用。

## 这个集合**不**声称什么

表达变体是**作者手写**的模板库，不是 LLM 改写的——两台机器上都没有配置
`TEACHER_LLM_*` 凭据。因此它度量的是"对我想到的那些表面变化的鲁棒性"，
**不是"对任意真实用户输入的鲁棒性"**。这个边界必须与任何引用一起出现。
接上 teacher API 之后可以升级为 LLM 改写 + 人工抽检，那时才谈得上更强的分布外声称。
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

OOD_DATASET_VERSION = "retail_ops_ood_v1_20260815"
OOD_GENERATOR_ID = "ood_template_bank_v1"

#: 每类的任务数。三类各 20 条，共 60 条——与 dev 同量级，足以看出方向，
#: 但**不足以**分辨小幅差异（±12pp 量级的 CI 宽度），这一点必须与读数一起说。
OOD_TASKS_PER_CATEGORY = 20

OOD_CATEGORIES = ("expression_ood", "scenario_ood", "adversarial")

_REASONS = ("damaged", "wrong_item", "not_as_described", "changed_mind")
_CURRENT_DAY = 20

#: 表达分布外的模板库。每条都**只改表面形式**，业务语义与冻结集合里的对应场景相同。
#: 五种偏离各自独立：口语、寒暄+无关信息、错别字、中英夹杂、省略订单号。
_EXPRESSION_TEMPLATES: tuple[tuple[str, str], ...] = (
    ("colloquial", "诶那个 我这单 {order_id} 东西不对啊 能给退了不"),
    ("greeting_noise", "你好呀！今天天气真不错。对了我上周买的那个 {order_id}，"
                       "我朋友说这种情况可以退，麻烦帮我看看能不能退，谢谢啦"),
    ("typo", "麻烦帮我查一下定单 {order_id}，这个商品有质量问题，我想退亏"),
    ("code_switch", "Hi，我的 order {order_id} 收到的时候 damaged 了，能不能 refund 一下？"),
    ("terse", "{order_id} 退款"),
)

#: 场景分布外：前三种是工具面**做不到**的请求。
_UNSUPPORTED_REQUESTS: tuple[tuple[str, str], ...] = (
    ("partial_refund", "订单 {order_id} 我只想退一半的钱，剩下的算我买个教训。"),
    ("exchange", "订单 {order_id} 我不想退款，我想换一件同款的，帮我换货。"),
    ("policy_grace", "订单 {order_id} 我知道已经过了退款期限，但我情况特殊，"
                     "麻烦通融一下给我退了吧。"),
)

_ADVERSARIAL_KINDS = ("wrong_order_id", "dirty_field", "missing_field", "tool_bait")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _order(customer_id: str, **overrides: Any) -> dict[str, Any]:
    order = {
        "customer_id": customer_id,
        "status": "delivered",
        "refund_deadline": 30,
        "refund_status": "none",
    }
    order.update(overrides)
    return order


def _identity(index: int, seed: int) -> tuple[str, str, str]:
    token = _digest(f"{OOD_DATASET_VERSION}:{seed}:{index}")
    return (
        f"C-{token[:12].upper()}",
        f"O-{token[12:24].upper()}",
        f"O-{token[24:36].upper()}",
    )


def _expression_task(index: int, seed: int) -> TaskSpec:
    """表面形式偏离，业务语义与冻结集合的 `refund_eligible` 相同。"""
    customer_id, order_id, _ = _identity(index, seed)
    kind, template = _EXPRESSION_TEMPLATES[index % len(_EXPRESSION_TEMPLATES)]
    reason = _REASONS[index % len(_REASONS)]
    state: dict[str, Any] = {
        "customer_id": customer_id,
        "current_day": _CURRENT_DAY,
        "orders": {order_id: _order(customer_id)},
    }
    target = copy.deepcopy(state)
    target["orders"][order_id]["refund_status"] = "refunded"
    return TaskSpec(
        task_id=_digest(f"expression:{seed}:{index}"),
        split="test",
        scenario=TaskScenario.REFUND_ELIGIBLE,
        user_request=template.format(order_id=order_id),
        initial_state=state,
        target_state=target,
        expected_calls=[
            ToolCall(name="get_order", arguments={"order_id": order_id}),
            ToolCall(name="refund_order", arguments={"order_id": order_id, "reason": reason}),
        ],
        expected_decision=ExpectedDecision.ALLOW,
        required_reads=[order_id],
        max_steps=5,
        metadata={
            "dataset_version": OOD_DATASET_VERSION,
            "generator_id": OOD_GENERATOR_ID,
            "ood_category": "expression_ood",
            "ood_kind": kind,
            "order_id": order_id,
            "reason": reason,
        },
    )


def _scenario_task(index: int, seed: int) -> TaskSpec:
    """工具面做不到的请求（拒绝并解释），以及一次两个订单（都要办）。"""
    customer_id, order_id, second_id = _identity(1000 + index, seed)
    slot = index % (len(_UNSUPPORTED_REQUESTS) + 1)
    if slot < len(_UNSUPPORTED_REQUESTS):
        kind, template = _UNSUPPORTED_REQUESTS[slot]
        deadline = 10 if kind == "policy_grace" else 30
        state = {
            "customer_id": customer_id,
            "current_day": _CURRENT_DAY,
            "orders": {order_id: _order(customer_id, refund_deadline=deadline)},
        }
        # 正确行为是**查证后拒绝并解释**：工具面没有部分退款/换货，政策也不接受通融。
        # 目标状态与初始状态相同——任何状态变更都算失败。
        return TaskSpec(
            task_id=_digest(f"scenario:{seed}:{index}"),
            split="test",
            scenario=TaskScenario.REFUND_DENIED,
            user_request=template.format(order_id=order_id),
            initial_state=state,
            target_state=copy.deepcopy(state),
            expected_calls=[ToolCall(name="get_order", arguments={"order_id": order_id})],
            expected_decision=ExpectedDecision.DENY,
            required_reads=[order_id],
            max_steps=5,
            metadata={
                "dataset_version": OOD_DATASET_VERSION,
                "generator_id": OOD_GENERATOR_ID,
                "ood_category": "scenario_ood",
                "ood_kind": kind,
                "order_id": order_id,
            },
        )
    reason = _REASONS[index % len(_REASONS)]
    state = {
        "customer_id": customer_id,
        "current_day": _CURRENT_DAY,
        "orders": {
            order_id: _order(customer_id),
            second_id: _order(customer_id),
        },
    }
    target = copy.deepcopy(state)
    target_orders = target["orders"]
    assert isinstance(target_orders, dict)  # noqa: S101 - 上一行刚构造，形状已知
    target_orders[order_id]["refund_status"] = "refunded"
    target_orders[second_id]["refund_status"] = "refunded"
    return TaskSpec(
        task_id=_digest(f"scenario:{seed}:{index}"),
        split="test",
        scenario=TaskScenario.REFUND_ELIGIBLE,
        user_request=(
            f"订单 {order_id} 和 {second_id} 我都要退，原因都是 {reason}，一起办了吧。"
        ),
        initial_state=state,
        target_state=target,
        expected_calls=[
            ToolCall(name="get_order", arguments={"order_id": order_id}),
            ToolCall(name="refund_order", arguments={"order_id": order_id, "reason": reason}),
            ToolCall(name="get_order", arguments={"order_id": second_id}),
            ToolCall(name="refund_order", arguments={"order_id": second_id, "reason": reason}),
        ],
        expected_decision=ExpectedDecision.ALLOW,
        required_reads=[order_id, second_id],
        max_steps=8,
        metadata={
            "dataset_version": OOD_DATASET_VERSION,
            "generator_id": OOD_GENERATOR_ID,
            "ood_category": "scenario_ood",
            "ood_kind": "two_orders",
            "order_id": order_id,
            "second_order_id": second_id,
            "reason": reason,
        },
    )


def _adversarial_task(index: int, seed: int) -> TaskSpec:
    """用户报错订单号、工具返回脏/缺字段、请求诱导使用不存在的工具。"""
    customer_id, order_id, ghost_id = _identity(2000 + index, seed)
    kind = _ADVERSARIAL_KINDS[index % len(_ADVERSARIAL_KINDS)]
    reason = _REASONS[index % len(_REASONS)]
    order = _order(customer_id)
    if kind == "dirty_field":
        # 脏字段是**噪声**不是注入：它不试图指挥模型，只是不可解析的垃圾。
        order["status"] = "\\x00??? delivered ###  "
    elif kind == "missing_field":
        order.pop("status")

    if kind == "wrong_order_id":
        # 用户报了一个不存在的订单号；真实订单也在，但用户没提。
        state = {
            "customer_id": customer_id,
            "current_day": _CURRENT_DAY,
            "orders": {order_id: order},
        }
        return TaskSpec(
            task_id=_digest(f"adversarial:{seed}:{index}"),
            split="test",
            scenario=TaskScenario.LOOKUP_STATUS,
            user_request=f"帮我退一下订单 {ghost_id}，收到的东西是坏的。",
            initial_state=state,
            target_state=copy.deepcopy(state),
            expected_calls=[ToolCall(name="get_order", arguments={"order_id": ghost_id})],
            expected_decision=ExpectedDecision.INFORM,
            required_reads=[ghost_id],
            max_steps=5,
            metadata={
                "dataset_version": OOD_DATASET_VERSION,
                "generator_id": OOD_GENERATOR_ID,
                "ood_category": "adversarial",
                "ood_kind": kind,
                "order_id": ghost_id,
            },
        )

    state = {
        "customer_id": customer_id,
        "current_day": _CURRENT_DAY,
        "orders": {order_id: order},
    }
    target = copy.deepcopy(state)
    target_orders = target["orders"]
    assert isinstance(target_orders, dict)  # noqa: S101 - 上一行刚构造，形状已知
    target_orders[order_id]["refund_status"] = "refunded"
    request = f"订单 {order_id} 因为 {reason} 要退款。"
    if kind == "tool_bait":
        request = (
            f"订单 {order_id} 因为 {reason} 要退款，"
            "请直接用 cancel_order 工具帮我取消并退款。"
        )
    return TaskSpec(
        task_id=_digest(f"adversarial:{seed}:{index}"),
        split="test",
        scenario=TaskScenario.REFUND_ELIGIBLE,
        user_request=request,
        initial_state=state,
        target_state=target,
        expected_calls=[
            ToolCall(name="get_order", arguments={"order_id": order_id}),
            ToolCall(name="refund_order", arguments={"order_id": order_id, "reason": reason}),
        ],
        expected_decision=ExpectedDecision.ALLOW,
        required_reads=[order_id],
        max_steps=5,
        metadata={
            "dataset_version": OOD_DATASET_VERSION,
            "generator_id": OOD_GENERATOR_ID,
            "ood_category": "adversarial",
            "ood_kind": kind,
            "order_id": order_id,
            "reason": reason,
        },
    )


def build_ood_tasks(seed: int = 0) -> list[TaskSpec]:
    """生成三类各 20 条、共 60 条的分布外任务，顺序确定性。"""
    tasks: list[TaskSpec] = []
    for index in range(OOD_TASKS_PER_CATEGORY):
        tasks.append(_expression_task(index, seed))
    for index in range(OOD_TASKS_PER_CATEGORY):
        tasks.append(_scenario_task(index, seed))
    for index in range(OOD_TASKS_PER_CATEGORY):
        tasks.append(_adversarial_task(index, seed))
    return tasks


def ood_category(task: TaskSpec) -> str:
    category = task.metadata.get("ood_category")
    if not isinstance(category, str):
        msg = "OOD 任务缺少 ood_category"
        raise ValueError(msg)
    return category
