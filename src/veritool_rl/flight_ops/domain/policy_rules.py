"""Executable declarative rebooking policy rules for FlightOps v1.

Mirrors `retail_ops.domain.policy_rules` so the FlightOps domain reuses the same
policy-rule engine shape (facts + predicate + rule). This is deliberately a
parallel implementation, not an import of retail_ops: the one-way dependency
governance test asserts ``flight_ops`` depends only on ``core`` (not on
``retail_ops``), which is what makes this a real portability proof rather than a
shared-module convenience.

The 24h rebooking window is structurally identical to the retail refund window:
``hours_to_departure`` plays the role ``days_past_deadline`` plays for refunds.
A reservation is ineligible for rebooking when fewer than 24 hours remain
before departure — the policy boundary probe instrument therefore transfers
unchanged (scan a margin axis, compare the decision curve against an executable
policy rule).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

#: All adjudicable facts for one rebooking attempt. Rules may only reference
#: these names, so "a rule references a fact that does not exist" fails at
#: bundle-load time rather than at rebooking time.
#:
#: ``hours_to_departure`` is the hours remaining before the flight departs. The
#: rebooking window is "at least 24h before departure"; the rule expresses the
#: policy ("fewer than 24h → deny") rather than the implementation.
REBOOK_FACT_NAMES = (
    "reservation_was_read",
    "caller_owns_reservation",
    "hours_to_departure",
    "already_rebooked",
    "reason_is_approved",
)

_COMPARISONS = ("is", "gt", "gte", "lt", "lte")


@dataclass(frozen=True)
class RebookFacts:
    """Fact set computed by the environment and consumed by the rules."""

    reservation_was_read: bool
    caller_owns_reservation: bool
    hours_to_departure: int
    already_rebooked: bool
    reason_is_approved: bool

    def value(self, name: str) -> Any:
        return getattr(self, name)


@dataclass(frozen=True)
class Predicate:
    """A single ``<fact> <op> <operand>`` comparison."""

    fact: str
    operator: str
    operand: Any

    def holds(self, facts: RebookFacts) -> bool:
        value = facts.value(self.fact)
        if self.operator == "is":
            return bool(value == self.operand)
        # bool is a subclass of int; numeric comparison rejects booleans so that
        # True is not silently treated as 1.
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            msg = f"事实 {self.fact} 不是数值，无法用 {self.operator} 比较"
            raise ValueError(msg)
        operand = float(self.operand)
        if self.operator == "gt":
            return float(value) > operand
        if self.operator == "gte":
            return float(value) >= operand
        if self.operator == "lt":
            return float(value) < operand
        return float(value) <= operand


@dataclass(frozen=True)
class PolicyRule:
    """An executable denial rule: when the condition holds, deny with this rule's
    own violation type."""

    rule_id: str
    violation: str
    error: str
    when: Predicate


@dataclass(frozen=True)
class PolicyDecision:
    """The result of a rule firing; the violation type comes from the rule id,
    not from a string literal."""

    rule_id: str
    violation: str
    error: str


def parse_predicate(spec: Mapping[str, Any]) -> Predicate:
    """Parse a predicate; referencing an unknown fact or operator fails here."""
    fact = spec.get("fact")
    if not isinstance(fact, str):
        msg = "谓词必须声明 fact"
        raise ValueError(msg)
    if fact not in REBOOK_FACT_NAMES:
        msg = f"未知事实 {fact!r}，可用：{list(REBOOK_FACT_NAMES)}"
        raise ValueError(msg)
    operators = [name for name in _COMPARISONS if name in spec]
    unknown = set(spec) - {"fact"} - set(_COMPARISONS)
    if unknown:
        msg = f"谓词含未知算子 {sorted(unknown)}，可用：{list(_COMPARISONS)}"
        raise ValueError(msg)
    if len(operators) != 1:
        msg = f"谓词必须且只能声明一个算子，得到 {operators}"
        raise ValueError(msg)
    return Predicate(fact=fact, operator=operators[0], operand=spec[operators[0]])


def parse_rule_spec(spec: Mapping[str, Any]) -> PolicyRule:
    """Parse a declarative rule. All four fields are required — missing any
    leaves a rule whose meaning is incomplete."""
    missing = [name for name in ("id", "violation", "error", "when") if name not in spec]
    if missing:
        msg = f"规则缺少必填字段 {missing}"
        raise ValueError(msg)
    when = spec["when"]
    if not isinstance(when, Mapping):
        msg = "规则的 when 必须是 mapping"
        raise ValueError(msg)
    for name in ("id", "violation", "error"):
        if not isinstance(spec[name], str) or not spec[name]:
            msg = f"规则字段 {name} 必须是非空字符串"
            raise ValueError(msg)
    return PolicyRule(
        rule_id=spec["id"],
        violation=spec["violation"],
        error=spec["error"],
        when=parse_predicate(when),
    )


def evaluate_rebook_rules(
    rules: Sequence[PolicyRule],
    facts: RebookFacts,
) -> PolicyDecision | None:
    """Evaluate in **declaration order**, return the first rule that fires; None
    if none fire.

    Order is contract, not coincidence: violation types feed the failure
    taxonomy and the policy-violation count; changing the order changes the
    failure classification for the same candidate and breaks comparability.
    """
    for rule in rules:
        if rule.when.holds(facts):
            return PolicyDecision(rule_id=rule.rule_id, violation=rule.violation, error=rule.error)
    return None


#: The six names in v1 ``policies.yaml``'s ``rules:``, frozen verbatim.
V1_RULE_NAMES = (
    "rebook_requires_lookup",
    "caller_must_own_reservation",
    "rebook_window_must_be_open",
    "duplicate_rebook_forbidden",
    "transient_retry_is_bounded",
    "tool_schema_is_strict",
)

#: The first four are engine-enforceable rebooking denial rules; the last two
#: (retry bound, schema strictness) describe behaviour that is not "when to
#: deny a rebook", enforced elsewhere with their own tests. Folding them into
#: the denial set would muddy the "rule = denial condition" semantics.
V1_BUILTIN_RULES: tuple[PolicyRule, ...] = (
    PolicyRule(
        rule_id="rebook_requires_lookup",
        violation="rebook_without_lookup",
        error="Rebooking requires looking up the reservation first",
        when=Predicate(fact="reservation_was_read", operator="is", operand=False),
    ),
    PolicyRule(
        rule_id="caller_must_own_reservation",
        violation="unauthorized_reservation",
        error="Caller does not own this reservation",
        when=Predicate(fact="caller_owns_reservation", operator="is", operand=False),
    ),
    PolicyRule(
        rule_id="rebook_window_must_be_open",
        violation="rebook_not_eligible",
        error="Reservation is within 24h of departure and cannot be rebooked",
        when=Predicate(fact="hours_to_departure", operator="lt", operand=24),
    ),
    PolicyRule(
        rule_id="duplicate_rebook_forbidden",
        violation="duplicate_rebook",
        error="Reservation has already been rebooked",
        when=Predicate(fact="already_rebooked", operator="is", operand=True),
    ),
)


def resolve_rules(raw_rules: Sequence[Any]) -> tuple[PolicyRule, ...]:
    """Resolve ``policies.yaml``'s ``rules:`` into executable rules.

    - all strings → v1 form, resolved by name to the built-in frozen set
      (the YAML does not need to change);
    - all mappings → v2 form, rules inlined in the YAML, threshold changes need
      no Python change.

    Mixing is forbidden: half names half inlined means "who defines this
    policy" has no single answer.
    """
    if not raw_rules:
        msg = "policies.rules 不得为空"
        raise ValueError(msg)
    if all(isinstance(entry, str) for entry in raw_rules):
        if tuple(raw_rules) != V1_RULE_NAMES:
            msg = "名字形态的 rules 必须逐字等于 v1 冻结集合"
            raise ValueError(msg)
        return V1_BUILTIN_RULES
    if all(isinstance(entry, Mapping) for entry in raw_rules):
        return tuple(parse_rule_spec(entry) for entry in raw_rules)
    msg = "policies.rules 不得混用名字与内联规则"
    raise ValueError(msg)
