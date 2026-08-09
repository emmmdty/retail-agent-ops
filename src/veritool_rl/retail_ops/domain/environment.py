"""RetailOps v1 的政策感知确定性工具环境。"""

from __future__ import annotations

import copy
import random
from collections.abc import Mapping
from typing import Any

from veritool_rl.core.envs.base import ToolEnv, ToolSchema
from veritool_rl.core.trajectory import ExpectedDecision, Observation, TaskSpec
from veritool_rl.retail_ops.domain.bundle import LoadedRetailOpsBundle


class RetailOpsEnv(ToolEnv):
    """以冻结 bundle 执行单条 RetailOps 任务。"""

    def __init__(self, task: TaskSpec, bundle: LoadedRetailOpsBundle) -> None:
        self._task = task.model_copy(deep=True)
        self._bundle = bundle
        self._state = copy.deepcopy(task.initial_state)
        self._schemas = [tool.model_copy(deep=True) for tool in bundle.tools]
        self._aliases = {tool.name: tool.name for tool in bundle.tools}
        self._violations: list[str] = []
        self._reads: set[str] = set()
        self._matched_calls = 0
        self._remaining_failures = dict(task.transient_failures)
        self._terminal_response = False
        self._refund_applied = False

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
        if canonical_name == "get_order":
            return self._get_order(arguments)
        if canonical_name == "refund_order":
            return self._refund_order(arguments)
        return self._get_store_hours(arguments)

    def get_state(self) -> dict[str, Any]:
        return copy.deepcopy(self._state)

    def verify_milestone(self) -> float:
        expected = len(self._task.expected_calls)
        return self._matched_calls / expected if expected else 1.0

    def verify_final_state(self) -> float:
        reads_complete = set(self._task.required_reads) <= self._reads
        state_matches = self._state == self._task.target_state
        clean = not self._violations
        if self._task.expected_decision in {
            ExpectedDecision.INFORM,
            ExpectedDecision.DENY,
        }:
            return float(reads_complete and self._terminal_response and state_matches and clean)
        return float(reads_complete and state_matches and clean and self._refund_applied)

    def check_policy(self) -> list[str]:
        return list(self._violations)

    def record_final_response(self, response: str) -> None:
        self._terminal_response = bool(response.strip())

    def perturb_schema(self, seed: int) -> None:
        rng = random.Random(seed)
        aliases: dict[str, str] = {}
        schemas: list[ToolSchema] = []
        descriptions = {
            "get_order": "读取指定订单的当前详情。",
            "refund_order": "核验后执行符合退款政策的订单退款。",
            "get_store_hours": "读取指定城市的门店营业时间。",
        }
        for schema in self._bundle.tools:
            alias = f"{schema.name}_{rng.randrange(1000, 10000)}"
            parameters = copy.deepcopy(schema.parameters)
            properties = list(parameters["properties"].items())
            rng.shuffle(properties)
            parameters["properties"] = dict(properties)
            schemas.append(
                ToolSchema(
                    name=alias,
                    description=descriptions[schema.name],
                    parameters=parameters,
                )
            )
            aliases[alias] = schema.name
        self._schemas = schemas
        self._aliases = aliases

    def _get_order(self, arguments: dict[str, Any]) -> Observation:
        if not self._valid_arguments(arguments, {"order_id"}):
            return self._invalid_arguments("get_order")
        order_id = arguments["order_id"]
        self._reads.add(order_id)
        self._record_expected_call("get_order", arguments)
        order = self._orders().get(order_id)
        if order is None or order.get("customer_id") != self._state.get("customer_id"):
            return Observation(
                ok=False,
                error_code="not_found",
                error="订单不存在或不可见",
            )
        content = copy.deepcopy(order)
        content["current_day"] = self._state.get("current_day")
        return Observation(ok=True, content=content)

    def _refund_order(self, arguments: dict[str, Any]) -> Observation:
        if not self._valid_arguments(arguments, {"order_id", "reason"}):
            return self._invalid_arguments("refund_order")
        order_id = arguments["order_id"]
        reason = arguments["reason"]
        if order_id not in self._reads:
            return self._deny("refund_without_lookup", "退款前必须查询订单")
        order = self._orders().get(order_id)
        if order is None:
            return Observation(
                ok=False,
                error_code="not_found",
                error="订单不存在或不可见",
            )
        if order.get("customer_id") != self._state.get("customer_id"):
            return self._deny("unauthorized_order", "无权操作该订单")
        if self._state.get("current_day", 0) > order.get("refund_deadline", 0):
            return self._deny("refund_not_eligible", "订单已超过退款期限")
        if order.get("refund_status") == "refunded":
            return self._deny("duplicate_refund", "订单已经退款")
        if reason not in self._bundle.policies.refund_reasons:
            return self._invalid_arguments("refund_order")

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
        self._refund_applied = True
        return Observation(
            ok=True,
            content={"order_id": order_id, "refund_status": "refunded"},
        )

    def _get_store_hours(self, arguments: dict[str, Any]) -> Observation:
        if not self._valid_arguments(arguments, {"city"}):
            return self._invalid_arguments("get_store_hours")
        return Observation(
            ok=True,
            content={"city": arguments["city"], "hours": "09:00-18:00"},
        )

    def _orders(self) -> dict[str, dict[str, Any]]:
        orders = self._state.get("orders")
        if not isinstance(orders, dict):
            return {}
        return orders

    def _record_expected_call(self, name: str, arguments: Mapping[str, Any]) -> None:
        if self._matched_calls >= len(self._task.expected_calls):
            return
        expected = self._task.expected_calls[self._matched_calls]
        if expected.name == name and expected.arguments == dict(arguments):
            self._matched_calls += 1

    def _deny(self, violation: str, error: str) -> Observation:
        if violation not in self._violations:
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
