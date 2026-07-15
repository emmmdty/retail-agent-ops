"""用于打通 MVP 闭环的确定性订单与退款环境。"""

from __future__ import annotations

import copy
import hashlib
import random
from collections.abc import Mapping
from typing import Any, Literal

from veritool_rl.envs.base import ToolEnv, ToolSchema
from veritool_rl.trajectory import Observation, TaskScenario, TaskSpec, ToolCall

Split = Literal["train", "dev", "test"]

_SPLIT_COUNTS: dict[Split, int] = {"train": 128, "dev": 32, "test": 32}
_REASONS = ("damaged", "wrong_item", "not_as_described", "changed_mind")
_PHRASINGS: dict[Split, dict[TaskScenario, tuple[str, ...]]] = {
    "train": {
        TaskScenario.LOOKUP_STATUS: (
            "请查询订单 {order_id} 的状态。",
            "我的订单 {order_id} 到哪了？",
        ),
        TaskScenario.REFUND_ELIGIBLE: ("订单 {order_id} 有问题，请按 {reason} 退款。",),
        TaskScenario.REFUND_DENIED: ("我想退掉订单 {order_id}，原因是 {reason}。",),
        TaskScenario.REFUND_RECOVERY: ("请为订单 {order_id} 办理退款，原因 {reason}。",),
    },
    "dev": {
        TaskScenario.LOOKUP_STATUS: ("帮我看一下 {order_id} 当前是什么状态。",),
        TaskScenario.REFUND_ELIGIBLE: ("请检查并退款 {order_id}，商品 {reason}。",),
        TaskScenario.REFUND_DENIED: ("能否处理订单 {order_id} 的退款？理由是 {reason}。",),
        TaskScenario.REFUND_RECOVERY: ("订单 {order_id} 需要退款；若系统暂时失败请重试。",),
    },
    "test": {
        TaskScenario.LOOKUP_STATUS: ("订单号 {order_id} 的最新进度是什么？",),
        TaskScenario.REFUND_ELIGIBLE: ("核实后给 {order_id} 退款，退款理由：{reason}。",),
        TaskScenario.REFUND_DENIED: ("我要申请 {order_id} 的售后退款，原因 {reason}。",),
        TaskScenario.REFUND_RECOVERY: ("完成 {order_id} 的退款；遇到临时错误继续尝试。",),
    },
}


def _stable_identifier(seed: int, split: Split, index: int, prefix: str) -> str:
    digest = hashlib.sha256(f"{seed}:{split}:{index}:{prefix}".encode()).hexdigest()[:10]
    return f"{prefix}-{digest.upper()}"


def _make_task(seed: int, split: Split, index: int) -> TaskSpec:
    scenarios = tuple(TaskScenario)
    scenario = scenarios[index % len(scenarios)]
    order_id = _stable_identifier(seed, split, index, "O")
    customer_id = _stable_identifier(seed, split, index, "C")
    reason = _REASONS[(seed + index) % len(_REASONS)]
    current_day = 20
    refund_deadline = 40 if scenario is not TaskScenario.REFUND_DENIED else 10
    order = {
        "customer_id": customer_id,
        "status": "delivered" if scenario is not TaskScenario.LOOKUP_STATUS else "shipped",
        "refund_deadline": refund_deadline,
        "refund_status": "none",
    }
    initial_state: dict[str, Any] = {
        "customer_id": customer_id,
        "current_day": current_day,
        "orders": {order_id: order},
    }
    target_state: dict[str, Any] = copy.deepcopy(initial_state)
    expected_calls = [ToolCall(name="get_order", arguments={"order_id": order_id})]
    transient_failures: dict[str, int] = {}
    if scenario in {TaskScenario.REFUND_ELIGIBLE, TaskScenario.REFUND_RECOVERY}:
        refund_call = ToolCall(
            name="refund_order",
            arguments={"order_id": order_id, "reason": reason},
        )
        expected_calls.append(refund_call)
        target_state["orders"][order_id]["refund_status"] = "refunded"
        if scenario is TaskScenario.REFUND_RECOVERY:
            expected_calls.append(refund_call.model_copy(deep=True))
            transient_failures = {"refund_order": 1}

    phrases = _PHRASINGS[split][scenario]
    request = phrases[(seed + index) % len(phrases)].format(order_id=order_id, reason=reason)
    return TaskSpec(
        task_id=f"{split}-{scenario.value}-{index:04d}",
        split=split,
        scenario=scenario,
        user_request=request,
        initial_state=initial_state,
        target_state=target_state,
        expected_calls=expected_calls,
        transient_failures=transient_failures,
        max_steps=5 if scenario is TaskScenario.REFUND_RECOVERY else 4,
        metadata={"customer_id": customer_id, "order_id": order_id, "reason": reason},
    )


def generate_mini_retail_tasks(split: Split, count: int, seed: int) -> list[TaskSpec]:
    """按固定顺序生成场景均衡且可重复的任务。"""
    if count < 1 or count % len(TaskScenario) != 0:
        msg = f"任务数必须为正数且能被 {len(TaskScenario)} 整除: {count}"
        raise ValueError(msg)
    return [_make_task(seed, split, index) for index in range(count)]


def build_mvp_task_splits(seed: int) -> dict[Split, list[TaskSpec]]:
    """生成默认 128/32/32 的冻结数据切分。"""
    return {
        split: generate_mini_retail_tasks(split, count, seed)
        for split, count in _SPLIT_COUNTS.items()
    }


def _base_schemas() -> list[ToolSchema]:
    return [
        ToolSchema(
            name="get_order",
            description="查询订单详情与当前状态。",
            parameters={
                "type": "object",
                "properties": {"order_id": {"type": "string", "description": "订单号"}},
                "required": ["order_id"],
                "additionalProperties": False,
            },
        ),
        ToolSchema(
            name="refund_order",
            description="为符合政策的订单办理退款；调用前必须先查询订单。",
            parameters={
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单号"},
                    "reason": {
                        "type": "string",
                        "enum": list(_REASONS),
                        "description": "退款原因",
                    },
                },
                "required": ["order_id", "reason"],
                "additionalProperties": False,
            },
        ),
    ]


class MiniRetailEnv(ToolEnv):
    """一个 TaskSpec 对应一个全新、无外部副作用的环境实例。"""

    def __init__(self, task: TaskSpec) -> None:
        self._task = task.model_copy(deep=True)
        self._state = copy.deepcopy(task.initial_state)
        self._schemas = _base_schemas()
        self._aliases = {schema.name: schema.name for schema in self._schemas}
        self._violations: list[str] = []
        self._looked_up: set[str] = set()
        self._matched_calls = 0
        self._remaining_failures = dict(task.transient_failures)

    @property
    def task(self) -> TaskSpec:
        return self._task.model_copy(deep=True)

    def list_tools(self) -> list[ToolSchema]:
        return [schema.model_copy(deep=True) for schema in self._schemas]

    def execute_tool(self, name: str, arguments: dict[str, Any]) -> Observation:
        canonical_name = self._aliases.get(name)
        if canonical_name is None:
            return Observation(
                ok=False,
                error_code="unknown_tool",
                error=f"未知工具: {name}",
            )
        if canonical_name == "get_store_hours":
            if not self._valid_arguments(arguments, {"city"}):
                return self._invalid_arguments("get_store_hours")
            return Observation(ok=True, content={"city": arguments["city"], "hours": "09:00-18:00"})
        if canonical_name == "get_order":
            return self._get_order(arguments)
        return self._refund_order(arguments)

    def get_state(self) -> dict[str, Any]:
        return copy.deepcopy(self._state)

    def verify_milestone(self) -> float:
        expected = len(self._task.expected_calls)
        return self._matched_calls / expected if expected else 1.0

    def verify_final_state(self) -> float:
        complete = self._matched_calls == len(self._task.expected_calls)
        return float(complete and self._state == self._task.target_state and not self._violations)

    def check_policy(self) -> list[str]:
        return list(dict.fromkeys(self._violations))

    def perturb_schema(self, seed: int) -> None:
        rng = random.Random(seed)
        aliases: dict[str, str] = {}
        perturbed: list[ToolSchema] = []
        descriptions = {
            "get_order": "读取指定订单的详细信息与配送状态。",
            "refund_order": "在完成订单核验后，执行符合规则的退款操作。",
        }
        for schema in _base_schemas():
            alias = f"{schema.name}_{rng.randrange(1000, 10000)}"
            properties = list(schema.parameters["properties"].items())
            rng.shuffle(properties)
            parameters = copy.deepcopy(schema.parameters)
            parameters["properties"] = dict(properties)
            perturbed.append(
                ToolSchema(name=alias, description=descriptions[schema.name], parameters=parameters)
            )
            aliases[alias] = schema.name
        distractor_name = f"get_store_hours_{rng.randrange(1000, 10000)}"
        perturbed.append(
            ToolSchema(
                name=distractor_name,
                description="查询指定城市门店的营业时间，与订单操作无关。",
                parameters={
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                    "required": ["city"],
                    "additionalProperties": False,
                },
            )
        )
        aliases[distractor_name] = "get_store_hours"
        self._schemas = perturbed
        self._aliases = aliases

    def _get_order(self, arguments: dict[str, Any]) -> Observation:
        if not self._valid_arguments(arguments, {"order_id"}):
            return self._invalid_arguments("get_order")
        order_id = arguments["order_id"]
        order = self._state["orders"].get(order_id)
        if order is None:
            return Observation(ok=False, error_code="not_found", error=f"订单不存在: {order_id}")
        self._looked_up.add(order_id)
        self._record_expected_call("get_order", arguments)
        return Observation(ok=True, content=copy.deepcopy(order))

    def _refund_order(self, arguments: dict[str, Any]) -> Observation:
        if not self._valid_arguments(arguments, {"order_id", "reason"}):
            return self._invalid_arguments("refund_order")
        order_id = arguments["order_id"]
        reason = arguments["reason"]
        if reason not in _REASONS:
            return self._invalid_arguments("refund_order")
        order = self._state["orders"].get(order_id)
        if order is None:
            return Observation(ok=False, error_code="not_found", error=f"订单不存在: {order_id}")
        if order_id not in self._looked_up:
            return self._deny("refund_without_lookup", "退款前必须查询订单")
        if order["customer_id"] != self._state["customer_id"]:
            return self._deny("unauthorized_order", "无权操作其他客户的订单")
        if self._state["current_day"] > order["refund_deadline"]:
            return self._deny("refund_not_eligible", "订单已超过退款期限")
        if order["refund_status"] == "refunded":
            return self._deny("duplicate_refund", "订单已经退款")

        self._record_expected_call("refund_order", arguments)
        remaining = self._remaining_failures.get("refund_order", 0)
        if remaining:
            self._remaining_failures["refund_order"] = remaining - 1
            return Observation(
                ok=False,
                error_code="transient_error",
                error="退款服务暂时不可用，请重试",
            )
        order["refund_status"] = "refunded"
        return Observation(ok=True, content={"order_id": order_id, "refund_status": "refunded"})

    def _record_expected_call(self, name: str, arguments: Mapping[str, Any]) -> None:
        if self._matched_calls >= len(self._task.expected_calls):
            return
        expected = self._task.expected_calls[self._matched_calls]
        if expected.name == name and expected.arguments == dict(arguments):
            self._matched_calls += 1

    def _deny(self, violation: str, error: str) -> Observation:
        self._violations.append(violation)
        return Observation(ok=False, error_code="policy_denied", error=error)

    @staticmethod
    def _valid_arguments(arguments: Mapping[str, Any], required: set[str]) -> bool:
        return set(arguments) == required and all(
            isinstance(arguments[key], str) for key in required
        )

    @staticmethod
    def _invalid_arguments(tool_name: str) -> Observation:
        return Observation(
            ok=False,
            error_code="invalid_arguments",
            error=f"{tool_name} 的参数不符合 schema",
        )
