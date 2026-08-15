"""可执行的声明式退款政策规则。

`SPEC.md` §2 把"版本化业务政策"列为流水线的输入之一，但在 2026-08-15 之前那只是
一句话：`policies.yaml` 的 `rules:` 是六个字符串名字、`src/` 里零处引用，真正的语义
硬编码在 `domain/environment.py` 的 if 链里。于是"退款窗口从 14 天改成 7 天"这种
最普通的业务变更，答案是"改 Python + 重训模型"。

**这里只有一条求值路径。** 规则可以有两种来源：

- **v1**：`policies.yaml` 只有名字，解析到本模块的内置冻结规则集 `V1_BUILTIN_RULES`。
  v1 的 YAML 因此**一个字节都不用改**——它在 `bundle_sha256` 的分量里，改它会让全部
  已有 dev/sealed 证据不可配对。
- **v2 起**：规则直接内联在 YAML 里，改阈值不需要碰任何 Python。

两种来源产出同一种 `PolicyRule`，由同一个 `evaluate_refund_rules` 求值。这不是
"两套实现"，是同一个引擎的两个规则来源。

**故意不引入表达式语言。** 谓词只有五种形式、事实只有一张固定表，因此
"规则引用了不存在的东西"在**加载 bundle 时**就会失败。一个通用表达式求值器换来的
灵活性，代价是把配置错误推迟到运行时——在一条会决定退款是否放行的路径上，
这个交换不划算。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

#: 一次退款尝试的全部可判定事实。规则只能引用这里的名字。
#:
#: `days_past_deadline` 用「已超期天数」而不是「current_day / refund_deadline 两个原始
#: 字段」，是为了让规则表达的是**政策**（超期即拒）而不是**实现**（怎么算超期）。
REFUND_FACT_NAMES = (
    "order_was_read",
    "caller_owns_order",
    "days_past_deadline",
    "already_refunded",
    "reason_is_approved",
)

_COMPARISONS = ("is", "gt", "gte", "lt", "lte")


@dataclass(frozen=True)
class RefundFacts:
    """由环境计算、供规则求值的事实集合。"""

    order_was_read: bool
    caller_owns_order: bool
    days_past_deadline: int
    already_refunded: bool
    reason_is_approved: bool

    def value(self, name: str) -> Any:
        return getattr(self, name)


@dataclass(frozen=True)
class Predicate:
    """`<fact> <op> <operand>` 形式的单一比较。"""

    fact: str
    operator: str
    operand: Any

    def holds(self, facts: RefundFacts) -> bool:
        value = facts.value(self.fact)
        if self.operator == "is":
            return bool(value == self.operand)
        # 布尔是 int 的子类，直接比大小会把 True 当 1；数值比较只接受真数值事实。
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
    """一条可执行的拒绝规则：条件成立即拒绝，并产出该规则自己的违规类型。"""

    rule_id: str
    violation: str
    error: str
    when: Predicate


@dataclass(frozen=True)
class PolicyDecision:
    """规则命中的结果；违规类型来自规则 ID 而不是字符串字面量。"""

    rule_id: str
    violation: str
    error: str


def parse_predicate(spec: Mapping[str, Any]) -> Predicate:
    """解析一个谓词；引用未知事实或未知算子都在这里失败。"""
    fact = spec.get("fact")
    if not isinstance(fact, str):
        msg = "谓词必须声明 fact"
        raise ValueError(msg)
    if fact not in REFUND_FACT_NAMES:
        msg = f"未知事实 {fact!r}，可用：{list(REFUND_FACT_NAMES)}"
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
    """解析一条声明式规则。四个字段全部必填——缺一个都会让规则含义不完整。"""
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


def evaluate_refund_rules(
    rules: Sequence[PolicyRule],
    facts: RefundFacts,
) -> PolicyDecision | None:
    """按**声明顺序**求值，返回第一条命中的规则；全不命中返回 None。

    顺序是契约而不是巧合：违规类型会进失败 taxonomy 与政策违规计数，顺序变了，
    同一个候选的失败分类就变了，历史读数不再可比。
    """
    for rule in rules:
        if rule.when.holds(facts):
            return PolicyDecision(
                rule_id=rule.rule_id, violation=rule.violation, error=rule.error
            )
    return None


#: v1 `policies.yaml` 里 `rules:` 的六个名字，逐字冻结。
V1_RULE_NAMES = (
    "refund_requires_lookup",
    "customer_must_own_order",
    "refund_window_must_be_open",
    "duplicate_refund_forbidden",
    "transient_retry_is_bounded",
    "tool_schema_is_strict",
)

#: 前四条是引擎可强制的退款拒绝规则；后两条（重试上限、schema 严格性）描述的不是
#: "什么时候拒绝退款"，由环境的其它部分强制，各自有独立的测试。把它们塞进拒绝规则集
#: 会让「规则 = 拒绝条件」这个语义变浑。
#:
#: 条件、顺序与错误文案逐字复刻 2026-08-15 之前 `_refund_order` 的 if 链——
#: 全部已有评测证据都依赖这个行为，它必须**逐字节**不变。
V1_BUILTIN_RULES: tuple[PolicyRule, ...] = (
    PolicyRule(
        rule_id="refund_requires_lookup",
        violation="refund_without_lookup",
        error="退款前必须查询订单",
        when=Predicate(fact="order_was_read", operator="is", operand=False),
    ),
    PolicyRule(
        rule_id="customer_must_own_order",
        violation="unauthorized_order",
        error="无权操作该订单",
        when=Predicate(fact="caller_owns_order", operator="is", operand=False),
    ),
    PolicyRule(
        rule_id="refund_window_must_be_open",
        violation="refund_not_eligible",
        error="订单已超过退款期限",
        when=Predicate(fact="days_past_deadline", operator="gt", operand=0),
    ),
    PolicyRule(
        rule_id="duplicate_refund_forbidden",
        violation="duplicate_refund",
        error="订单已经退款",
        when=Predicate(fact="already_refunded", operator="is", operand=True),
    ),
)


def resolve_rules(raw_rules: Sequence[Any]) -> tuple[PolicyRule, ...]:
    """把 `policies.yaml` 的 `rules:` 解析成可执行规则。

    - 全是字符串 → v1 形态，按名字解析到内置冻结规则集（YAML 不需要改）；
    - 全是 mapping → v2 形态，规则内联在 YAML 里，改阈值不需要碰 Python。

    **不允许混用**：一半名字一半内联意味着"这份政策到底由谁定义"没有唯一答案。
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
