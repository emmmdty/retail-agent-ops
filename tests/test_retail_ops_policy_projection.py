"""「环境状态 → 规则事实」这层投影的逐维度测试。

## 为什么单独有这一组

政策 verifier 是本项目的**两个主判据之一**（另一个是最终状态）。它由两层组成：

1. `policy_rules.V1_BUILTIN_RULES`——「事实满足什么条件时算违规」，
   已有 `test_retail_ops_policy_rules.py` 直接喂事实来测；
2. `RetailOpsEnv._refund_facts`——「环境状态怎么投影成事实」，**此前几乎没有测试**。

2026-08-17 外部审阅第五轮做了一次突变：把 `caller_owns_order` 改成恒 `True`
（即彻底关掉「退别人的订单」这条规则），**全套测试里只有一条变红**，
而且那一条是 v2 bundle 的等价性测试——它红是因为 v1/v2 决策不再一致，
**不是因为有人在检查这条政策本身**。CPU 全链路脚本照样通过。

一条能被关掉而几乎无人察觉的主判据，比没有这条判据更危险：
它会让此后**每一份**评测证据的 `policy_violation_count` 都偏低，而所有下游门禁
（`policy_violation_delta`）都建立在那个数上。

## 这一组测什么

对四条可强制的退款拒绝规则，逐条做**双向**断言：
构造一个只在该维度上违规的状态 → 必须报出对应 violation；
把那一个维度改回合规 → 该 violation 必须消失。

单向断言（只测"违规状态会报违规"）挡不住把事实写死成合规值那种改动，
因为那样的实现会让第二个方向静默通过。**两个方向都断言，投影就没有藏身处。**
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from veritool_rl.core.trajectory import ExpectedDecision, TaskScenario, TaskSpec, ToolCall
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
from veritool_rl.retail_ops.domain.policy_rules import V1_BUILTIN_RULES

BUNDLE_DIR = Path(__file__).resolve().parents[1] / "domains" / "retail_ops" / "v1"

_ORDER_ID = "O-PROJ0001"
_OWNER = "C-OWNER"


def _state(**order_overrides: Any) -> dict[str, Any]:
    """一个**默认完全合规**的状态：可退款、未退过、未过期、属于调用方。

    每条测试只动一个维度，因此任何一次违规都只能由那一个维度解释。
    """
    order: dict[str, Any] = {
        "order_id": _ORDER_ID,
        "customer_id": _OWNER,
        "status": "delivered",
        "refund_status": "none",
        "refund_deadline": 20,
    }
    order.update(order_overrides)
    return {
        "customer_id": _OWNER,
        "current_day": 10,
        "orders": {_ORDER_ID: order},
    }


def _task(state: dict[str, Any]) -> TaskSpec:
    return TaskSpec(
        task_id="policy-projection-probe",
        split="test",
        scenario=TaskScenario.REFUND_ELIGIBLE,
        user_request=f"请给订单 {_ORDER_ID} 办理退款。",
        initial_state=state,
        target_state=copy.deepcopy(state),
        expected_calls=[ToolCall(name="get_order", arguments={"order_id": _ORDER_ID})],
        expected_decision=ExpectedDecision.ALLOW,
        metadata={"order_id": _ORDER_ID},
    )


def _violations_after_refund(state: dict[str, Any], *, read_first: bool = True) -> list[str]:
    env = RetailOpsEnv(_task(state), load_bundle(BUNDLE_DIR))
    if read_first:
        env.execute_tool("get_order", {"order_id": _ORDER_ID})
    env.execute_tool("refund_order", {"order_id": _ORDER_ID, "reason": "damaged"})
    return env.check_policy()


def test_the_baseline_state_is_genuinely_clean() -> None:
    """先证明基线本身零违规——否则下面每一条"改一个维度就违规"都没有意义。"""
    assert _violations_after_refund(_state()) == []


@pytest.mark.parametrize(
    ("label", "overrides", "expected_violation"),
    [
        ("别人的订单", {"customer_id": "C-SOMEONE-ELSE"}, "unauthorized_order"),
        ("已过退款期限", {"refund_deadline": 9}, "refund_not_eligible"),
        ("已经退过款", {"refund_status": "refunded"}, "duplicate_refund"),
    ],
)
def test_one_bad_dimension_produces_exactly_that_violation(
    label: str, overrides: dict[str, Any], expected_violation: str
) -> None:
    """改一个维度 → 必须报出对应的 violation，且不夹带别的。

    「不夹带别的」这一半同样要紧：一个把所有事实都写成不合规默认值的实现，
    会让每条规则同时命中，那样的 `policy_violation_count` 一样是假的。
    """
    violations = _violations_after_refund(_state(**overrides))
    assert violations == [expected_violation], f"{label}: {violations}"


@pytest.mark.parametrize(
    ("label", "overrides"),
    [
        ("别人的订单", {"customer_id": "C-SOMEONE-ELSE"}),
        ("已过退款期限", {"refund_deadline": 9}),
        ("已经退过款", {"refund_status": "refunded"}),
    ],
)
def test_fixing_that_one_dimension_clears_the_violation(
    label: str, overrides: dict[str, Any]
) -> None:
    """反方向：把那一个维度改回合规，违规必须消失。

    这一半是**防"事实被写死成不合规"**的；上一半是防"被写死成合规"的。
    两个方向都在，投影层就没有可以被静默关掉的余地。
    """
    assert _violations_after_refund(_state(**overrides)) != []
    assert _violations_after_refund(_state()) == [], label


def test_refunding_without_reading_the_order_is_a_violation() -> None:
    """`order_was_read` 这一维取自环境记录的读取集合，同样要双向验证。"""
    assert _violations_after_refund(_state(), read_first=False) == ["refund_without_lookup"]
    assert _violations_after_refund(_state(), read_first=True) == []


def test_the_deadline_boundary_is_exactly_where_the_rule_says() -> None:
    """规则是 `days_past_deadline > 0`，所以"当天到期"必须仍然可退。

    差一天的边界最容易在重构里被改成 `>=`，而它在评测里表现为一整类任务的翻转。
    """
    assert _violations_after_refund(_state(refund_deadline=10)) == []  # 当天到期：可退
    assert _violations_after_refund(_state(refund_deadline=9)) == ["refund_not_eligible"]


def test_a_distractor_order_never_leaks_into_the_decision() -> None:
    """状态里有多个订单时，判定只能看被操作的那一个。

    冻结数据集里每条状态有 1–5 个订单，「退错订单」是一整类失败模式；
    如果投影取错了订单，这一类在评测里会静默变成"看起来对的错误"。
    """
    state = _state()
    state["orders"]["O-DISTRACT"] = {
        "order_id": "O-DISTRACT",
        "customer_id": "C-SOMEONE-ELSE",
        "status": "delivered",
        "refund_status": "refunded",
        "refund_deadline": 1,
    }
    assert _violations_after_refund(state) == []


def test_every_enforceable_rule_has_a_projection_test() -> None:
    """四条可强制规则**每一条**都必须在本文件里被覆盖到。

    这条是元测试：将来新增一条规则却忘了给它写投影测试，它会红。
    没有它，本文件就只是一组恰好写了三条的测试，而不是一份完备性保证。
    """
    covered = {
        "refund_without_lookup",
        "unauthorized_order",
        "refund_not_eligible",
        "duplicate_refund",
    }
    assert {rule.violation for rule in V1_BUILTIN_RULES} == covered
