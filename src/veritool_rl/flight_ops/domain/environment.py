"""FlightOps v1 policy-aware deterministic tool environment.

Mirrors ``retail_ops.domain.environment.RetailOpsEnv`` so the FlightOps domain
reuses the same environment contract (``ToolEnv``) and the same policy-rule
enforcement shape. The 24h rebooking window plays the role of the refund
window: ``hours_to_departure`` is the structural twin of
``days_past_deadline``.

v1 has no idempotency key on ``rebook_flight`` (mirroring retail_ops v1); the
replay path is therefore absent and behaviour is byte-identical to a
plain "rebook once" semantics.
"""

from __future__ import annotations

import copy
import random
from collections.abc import Mapping
from typing import Any

from veritool_rl.core.envs.base import ToolEnv, ToolSchema
from veritool_rl.core.trajectory import ExpectedDecision, Observation, TaskSpec
from veritool_rl.flight_ops.domain.bundle import LoadedFlightOpsBundle
from veritool_rl.flight_ops.domain.policy_rules import RebookFacts, evaluate_rebook_rules


class FlightOpsEnv(ToolEnv):
    """Execute a single FlightOps task against the frozen bundle."""

    def __init__(self, task: TaskSpec, bundle: LoadedFlightOpsBundle) -> None:
        self._task = task.model_copy(deep=True)
        self._bundle = bundle
        self._state = copy.deepcopy(task.initial_state)
        self._schemas = [tool.model_copy(deep=True) for tool in bundle.tools]
        self._aliases = {tool.name: tool.name for tool in bundle.tools}
        self._violations: list[str] = []
        self._reads: set[str] = set()
        self._matched_calls = 0
        retry_cap = bundle.policies.max_transient_retries
        self._remaining_failures = {
            tool: min(count, retry_cap) for tool, count in task.transient_failures.items()
        }
        self._terminal_response = False
        self._rebook_applied = False
        self._rebook_parameters = self._required_parameters(bundle, "rebook_flight")

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
        if canonical_name == "get_reservation":
            return self._get_reservation(arguments)
        if canonical_name == "rebook_flight":
            return self._rebook_flight(arguments)
        return self._get_flight_schedule(arguments)

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
        return float(reads_complete and state_matches and clean and self._rebook_applied)

    def check_policy(self) -> list[str]:
        return list(self._violations)

    def record_final_response(self, response: str) -> None:
        self._terminal_response = bool(response.strip())

    def perturb_schema(self, seed: int) -> None:
        rng = random.Random(seed)
        aliases: dict[str, str] = {}
        schemas: list[ToolSchema] = []
        descriptions = {
            "get_reservation": "Read the current details of a reservation.",
            "rebook_flight": "Rebook a reservation onto a new flight after policy checks.",
            "get_flight_schedule": "Read scheduled flights for an origin.",
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

    def _get_reservation(self, arguments: dict[str, Any]) -> Observation:
        if not self._valid_arguments(arguments, {"reservation_id"}):
            return self._invalid_arguments("get_reservation")
        reservation_id = arguments["reservation_id"]
        self._reads.add(reservation_id)
        self._record_expected_call("get_reservation", arguments)
        reservation = self._reservations().get(reservation_id)
        if reservation is None or reservation.get("customer_id") != self._state.get("customer_id"):
            return Observation(
                ok=False,
                error_code="not_found",
                error="Reservation does not exist or is not visible",
            )
        content = copy.deepcopy(reservation)
        content["current_hour"] = self._state.get("current_hour")
        return Observation(ok=True, content=content)

    def _rebook_flight(self, arguments: dict[str, Any]) -> Observation:
        if not self._valid_arguments(arguments, self._rebook_parameters):
            return self._invalid_arguments("rebook_flight")
        reservation_id = arguments["reservation_id"]
        reason = arguments["reason"]
        reservation = self._reservations().get(reservation_id)
        facts = self._rebook_facts(reservation_id, reservation, reason)

        # Policy rules evaluate in declaration order. "Reservation does not exist"
        # is a visibility fact, not a policy judgement; it interleaves before the
        # rules that depend on reservation content: not read → deny for no
        # lookup; read but absent → not_found. Mirrors RetailOpsEnv exactly.
        if not facts.reservation_was_read:
            decision = evaluate_rebook_rules(self._bundle.policy_rules, facts)
            if decision is not None:
                return self._deny(decision.violation, decision.error)
        if reservation is None:
            return Observation(
                ok=False,
                error_code="not_found",
                error="Reservation does not exist or is not visible",
            )

        decision = evaluate_rebook_rules(self._bundle.policy_rules, facts)
        if decision is not None:
            return self._deny(decision.violation, decision.error)
        if reason not in self._bundle.policies.rebook_reasons:
            return self._invalid_arguments("rebook_flight")

        self._record_expected_call("rebook_flight", arguments)
        remaining = self._remaining_failures.get("rebook_flight", 0)
        if remaining:
            self._remaining_failures["rebook_flight"] = remaining - 1
            return Observation(
                ok=False,
                error_code="transient_error",
                error="Rebooking service is temporarily unavailable, please retry",
            )
        reservation["rebook_status"] = "rebooked"
        self._rebook_applied = True
        return Observation(
            ok=True,
            content={"reservation_id": reservation_id, "rebook_status": "rebooked"},
        )

    def _rebook_facts(
        self,
        reservation_id: str,
        reservation: dict[str, Any] | None,
        reason: str,
    ) -> RebookFacts:
        """Project environment state into rule-evaluable facts.

        When the reservation does not exist, give **compliant** defaults: only
        "was it read" is adjudicable; the other facts have no object to judge.
        Non-compliant defaults would let a rule fire spuriously and report a
        not_found as a policy violation.
        """
        if reservation is None:
            return RebookFacts(
                reservation_was_read=reservation_id in self._reads,
                caller_owns_reservation=True,
                hours_to_departure=72,
                already_rebooked=False,
                reason_is_approved=reason in self._bundle.policies.rebook_reasons,
            )
        current_hour = int(self._state.get("current_hour", 0))
        departure_hour = int(reservation.get("departure_hour", 0))
        return RebookFacts(
            reservation_was_read=reservation_id in self._reads,
            caller_owns_reservation=reservation.get("customer_id")
            == self._state.get("customer_id"),
            hours_to_departure=departure_hour - current_hour,
            already_rebooked=reservation.get("rebook_status") == "rebooked",
            reason_is_approved=reason in self._bundle.policies.rebook_reasons,
        )

    def _get_flight_schedule(self, arguments: dict[str, Any]) -> Observation:
        if not self._valid_arguments(arguments, {"origin"}):
            return self._invalid_arguments("get_flight_schedule")
        return Observation(
            ok=True,
            content={"origin": arguments["origin"], "flights": "FL123, FL456"},
        )

    def _reservations(self) -> dict[str, dict[str, Any]]:
        reservations = self._state.get("reservations")
        if not isinstance(reservations, dict):
            return {}
        return reservations

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
    def _required_parameters(bundle: LoadedFlightOpsBundle, tool_name: str) -> set[str]:
        """Required parameters come from the **tool schema itself**, not
        re-declared in code — otherwise schema and execution disagree."""
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
