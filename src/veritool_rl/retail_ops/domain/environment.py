"""RetailOps v1 的政策感知确定性工具环境。"""

from __future__ import annotations

import copy
import random
from collections.abc import Mapping
from typing import Any

from veritool_rl.core.envs.base import ToolEnv, ToolSchema
from veritool_rl.core.trajectory import ExpectedDecision, Observation, TaskSpec
from veritool_rl.retail_ops.domain.bundle import LoadedRetailOpsBundle
from veritool_rl.retail_ops.domain.policy_rules import RefundFacts, evaluate_refund_rules


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
        # `max_transient_retries` 从这里开始**真正驱动逻辑**：任务声明的瞬时故障
        # 次数被政策上限截断。此前它只被解析成一个 Literal，从不影响任何行为。
        # v1 的上限是 1、任务也只注入 1 次，因此 v1 行为逐字节不变。
        retry_cap = bundle.policies.max_transient_retries
        self._remaining_failures = {
            tool: min(count, retry_cap) for tool, count in task.transient_failures.items()
        }
        self._terminal_response = False
        self._refund_applied = False
        self._refund_results: dict[str, dict[str, Any]] = {}
        self._refund_parameters = self._required_parameters(bundle, "refund_order")

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
        if not self._valid_arguments(arguments, self._refund_parameters):
            return self._invalid_arguments("refund_order")
        order_id = arguments["order_id"]
        reason = arguments["reason"]
        order = self._orders().get(order_id)
        facts = self._refund_facts(order_id, order, reason)

        # 政策规则按**声明顺序**求值，判定与错误文案都来自规则本身。
        # 「订单不存在」不是政策判断而是可见性事实，它插在依赖订单内容的规则之前：
        # 没读过订单 → 先按未查询拒绝；读过但订单不存在 → not_found。
        # 这个交错顺序与 2026-08-15 之前的 if 链逐字相同，v1 的全部已有证据依赖它。
        if not facts.order_was_read:
            decision = evaluate_refund_rules(self._bundle.policy_rules, facts)
            if decision is not None:
                return self._deny(decision.violation, decision.error)
        if order is None:
            return Observation(
                ok=False,
                error_code="not_found",
                error="订单不存在或不可见",
            )

        # 幂等重放**先于**政策规则求值：同 key 的重复调用不是一次新的退款请求，
        # 而是同一次请求的重试。放在规则之后会被 `duplicate_refund_forbidden` 拦下，
        # 那正是 v1 分不清"客户端重试"与"再退一次"的那个缺口。
        # 缓存里只会有**已经成功**的 key，因此重放不可能绕过任何一条当初通过了的规则。
        replayed = self._replay_same_idempotency_key(arguments)
        if replayed is not None:
            return replayed

        decision = evaluate_refund_rules(self._bundle.policy_rules, facts)
        if decision is not None:
            return self._deny(decision.violation, decision.error)
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
        result = {"order_id": order_id, "refund_status": "refunded"}
        key = arguments.get("idempotency_key")
        if isinstance(key, str):
            self._refund_results[key] = dict(result)
        return Observation(ok=True, content=result)

    def _refund_facts(
        self,
        order_id: str,
        order: dict[str, Any] | None,
        reason: str,
    ) -> RefundFacts:
        """把环境状态投影成规则可求值的事实。

        订单不存在时给出**合规**默认值：那一步只会用到"是否查询过"，其余事实没有
        判断对象。给不合规默认值会让某条规则凭空命中，把 not_found 报成政策违规。
        """
        if order is None:
            return RefundFacts(
                order_was_read=order_id in self._reads,
                caller_owns_order=True,
                days_past_deadline=-1,
                already_refunded=False,
                reason_is_approved=reason in self._bundle.policies.refund_reasons,
            )
        current_day = int(self._state.get("current_day", 0))
        deadline = int(order.get("refund_deadline", 0))
        return RefundFacts(
            order_was_read=order_id in self._reads,
            caller_owns_order=order.get("customer_id") == self._state.get("customer_id"),
            days_past_deadline=current_day - deadline,
            already_refunded=order.get("refund_status") == "refunded",
            reason_is_approved=reason in self._bundle.policies.refund_reasons,
        )

    def _replay_same_idempotency_key(self, arguments: dict[str, Any]) -> Observation | None:
        """同一个 idempotency_key 的重复调用返回**同一结果**，且只退一次款。

        这是动钱接口的基本要求，也是 `refund_recovery` 场景一直缺的那一半：那个场景
        整个就是"瞬时失败后重试"，而去重此前只靠环境内部的 `refund_status`——
        客户端重试与"再退一次"在协议层无法区分。

        没有 `idempotency_key` 的 bundle（v1）走不到这里，行为逐字节不变。
        """
        key = arguments.get("idempotency_key")
        if not isinstance(key, str):
            return None
        cached = self._refund_results.get(key)
        if cached is None:
            return None
        return Observation(ok=True, content=dict(cached))

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
    def _required_parameters(bundle: LoadedRetailOpsBundle, tool_name: str) -> set[str]:
        """必填参数集合来自**工具 schema 本身**，不在代码里再写一遍。

        v2 给 `refund_order` 加了必填 `idempotency_key`；如果这里硬编码
        `{"order_id", "reason"}`，schema 与执行就会各说各话。
        """
        for tool in bundle.tools:
            if tool.name == tool_name:
                required = tool.parameters.get("required", [])
                return {str(name) for name in required}
        msg = f"bundle 中不存在工具 {tool_name}"
        raise ValueError(msg)

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
