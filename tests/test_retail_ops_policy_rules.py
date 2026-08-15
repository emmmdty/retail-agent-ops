"""P0-2：把业务政策从 Python if 链变成可执行的声明式规则。

评审口径：`domains/retail_ops/v1/policies.yaml` 的 `rules:` 六条名字在 `src/` 里
**零处引用**，`max_transient_retries` 只被解析成 `Literal[1]`、从不驱动逻辑；真正的
政策语义硬编码在 `domain/environment.py` 的 `_refund_order` if 链里。这与 `SPEC.md` §2
「输入：版本化业务政策」是契约级不一致。面试必问："退款窗口从 14 天改成 7 天，
你的流水线怎么响应？"当时的答案是"改 Python + 重训模型"。

**引擎只有一条求值路径。** v1 的六条名字解析到内置冻结规则集，v2 的规则直接内联在
YAML 里——不是两套实现，是同一个引擎的两种规则来源。这样 v1 的 `policies.yaml`
一个字节都不用改（它在 `bundle_sha256` 的分量里），而 v2 做到真正的政策外置。
"""

from __future__ import annotations

from typing import Any

import pytest

from veritool_rl.retail_ops.domain.policy_rules import (
    V1_BUILTIN_RULES,
    PolicyRule,
    RefundFacts,
    evaluate_refund_rules,
    parse_rule_spec,
)


def _facts(**overrides: Any) -> RefundFacts:
    base: dict[str, Any] = {
        "order_was_read": True,
        "caller_owns_order": True,
        "days_past_deadline": -10,
        "already_refunded": False,
        "reason_is_approved": True,
    }
    base.update(overrides)
    return RefundFacts(**base)


# ---------------------------------------------------------------------------
# 引擎语义
# ---------------------------------------------------------------------------


def test_a_compliant_refund_matches_no_rule() -> None:
    assert evaluate_refund_rules(V1_BUILTIN_RULES, _facts()) is None


@pytest.mark.parametrize(
    ("override", "violation"),
    [
        ({"order_was_read": False}, "refund_without_lookup"),
        ({"caller_owns_order": False}, "unauthorized_order"),
        ({"days_past_deadline": 1}, "refund_not_eligible"),
        ({"already_refunded": True}, "duplicate_refund"),
    ],
)
def test_each_v1_rule_fires_on_its_own_fact(override: dict[str, Any], violation: str) -> None:
    decision = evaluate_refund_rules(V1_BUILTIN_RULES, _facts(**override))

    assert decision is not None
    assert decision.violation == violation


def test_rule_order_is_the_contract_not_an_accident() -> None:
    """多条同时成立时，判定必须是**声明顺序**里的第一条。

    这不是美学问题：违规类型会进失败 taxonomy 和政策违规计数，顺序变了，
    同一个候选的失败分类就变了，历史读数不再可比。
    """
    decision = evaluate_refund_rules(
        V1_BUILTIN_RULES,
        _facts(order_was_read=False, caller_owns_order=False, already_refunded=True),
    )

    assert decision is not None
    assert decision.violation == "refund_without_lookup"
    assert [rule.rule_id for rule in V1_BUILTIN_RULES] == [
        "refund_requires_lookup",
        "customer_must_own_order",
        "refund_window_must_be_open",
        "duplicate_refund_forbidden",
    ]


def test_violation_type_comes_from_the_rule_not_a_string_literal() -> None:
    """违规类型由规则产生——这正是"政策外置"要兑现的那一点。"""
    rule = parse_rule_spec(
        {
            "id": "refund_window_must_be_open",
            "violation": "refund_not_eligible",
            "error": "订单已超过退款期限",
            "when": {"fact": "days_past_deadline", "gt": 0},
        }
    )

    assert isinstance(rule, PolicyRule)
    assert evaluate_refund_rules([rule], _facts(days_past_deadline=1)) is not None
    assert evaluate_refund_rules([rule], _facts(days_past_deadline=0)) is None


# ---------------------------------------------------------------------------
# 声明式规则的解析
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("predicate", "facts", "expected"),
    [
        ({"fact": "order_was_read", "is": False}, {"order_was_read": False}, True),
        ({"fact": "order_was_read", "is": False}, {"order_was_read": True}, False),
        ({"fact": "days_past_deadline", "gt": 0}, {"days_past_deadline": 1}, True),
        ({"fact": "days_past_deadline", "gt": 0}, {"days_past_deadline": 0}, False),
        ({"fact": "days_past_deadline", "gte": 0}, {"days_past_deadline": 0}, True),
        ({"fact": "days_past_deadline", "lt": 0}, {"days_past_deadline": -1}, True),
        ({"fact": "days_past_deadline", "lte": -1}, {"days_past_deadline": -1}, True),
    ],
)
def test_predicate_forms(predicate: dict[str, Any], facts: dict[str, Any], expected: bool) -> None:
    rule = parse_rule_spec({"id": "r", "violation": "v", "error": "e", "when": predicate})

    fired = evaluate_refund_rules([rule], _facts(**facts)) is not None

    assert fired is expected


def test_unknown_fact_is_rejected_at_parse_time() -> None:
    """引用不存在的事实必须在**加载 bundle 时**失败，而不是运行时静默为假。

    静默为假是最坏的形态：一条政策规则会永远不触发，而没有任何信号。
    """
    with pytest.raises(ValueError, match="未知事实"):
        parse_rule_spec(
            {
                "id": "r",
                "violation": "v",
                "error": "e",
                "when": {"fact": "no_such_fact", "is": True},
            }
        )


def test_unknown_operator_is_rejected_at_parse_time() -> None:
    with pytest.raises(ValueError, match="谓词"):
        parse_rule_spec(
            {
                "id": "r",
                "violation": "v",
                "error": "e",
                "when": {"fact": "already_refunded", "matches_regex": ".*"},
            }
        )


def test_a_predicate_must_declare_exactly_one_operator() -> None:
    with pytest.raises(ValueError, match="谓词"):
        parse_rule_spec(
            {
                "id": "r",
                "violation": "v",
                "error": "e",
                "when": {"fact": "days_past_deadline", "gt": 0, "lt": 5},
            }
        )


def test_rule_spec_requires_every_field() -> None:
    with pytest.raises(ValueError):
        parse_rule_spec(
            {"id": "r", "violation": "v", "when": {"fact": "already_refunded", "is": True}}
        )


# ---------------------------------------------------------------------------
# v1 兼容：内置规则集必须与 v1 的六个名字对应，且语义与既有 if 链一致
# ---------------------------------------------------------------------------


def test_v1_builtin_rules_cover_exactly_the_enforceable_names() -> None:
    """v1 的 `rules:` 有六个名字，其中四条是可由引擎强制的退款拒绝规则。

    另外两条（`transient_retry_is_bounded` / `tool_schema_is_strict`）描述的是
    重试上限与 schema 严格性，由环境的其它部分强制；把它们塞进拒绝规则集会让
    「规则 = 拒绝条件」这个语义变浑。它们各自有独立的强制点与测试。
    """
    from veritool_rl.retail_ops.domain.policy_rules import V1_RULE_NAMES

    assert V1_RULE_NAMES == (
        "refund_requires_lookup",
        "customer_must_own_order",
        "refund_window_must_be_open",
        "duplicate_refund_forbidden",
        "transient_retry_is_bounded",
        "tool_schema_is_strict",
    )
    assert [rule.rule_id for rule in V1_BUILTIN_RULES] == list(V1_RULE_NAMES[:4])


def test_v1_builtin_rules_reproduce_the_frozen_error_messages() -> None:
    """错误文案进模型上下文，改动会改变模型看到的东西——因此逐字冻结。"""
    messages = {rule.rule_id: rule.error for rule in V1_BUILTIN_RULES}

    assert messages == {
        "refund_requires_lookup": "退款前必须查询订单",
        "customer_must_own_order": "无权操作该订单",
        "refund_window_must_be_open": "订单已超过退款期限",
        "duplicate_refund_forbidden": "订单已经退款",
    }
