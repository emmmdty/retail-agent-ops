"""RetailOps v2 bundle：政策外置 + 幂等键。

用户裁定（2026-08-15）：`refund_order` 加必填 `idempotency_key` 会让现有 240 条 teacher
轨迹的调用参数不再合法，因此**给 bundle 打新版本号、新旧并存**——v1 逐字节不动，
全部已有 dev/sealed 证据保持可加载、可解释、可配对。

本文件锁住三件事：v1 没有被顺手改动、v2 的政策真的可执行（改 YAML 就改判定）、
幂等键的语义正确（同 key 重试只退一次且返回同一结果，换 key 才算重复退款）。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from veritool_rl.core.trajectory import ExpectedDecision, TaskScenario, TaskSpec
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv

REPO_ROOT = Path(__file__).resolve().parents[1]
V1_DIR = REPO_ROOT / "domains/retail_ops/v1"
V2_DIR = REPO_ROOT / "domains/retail_ops/v2"

#: v1 首次正式运行时的 bundle 内容哈希。它在 dev 的 `PAIRING_FIELDS` 与
#: `SEALED_PAIRING_FIELDS` 内，变了就等于把全部已有证据判为不可配对。
V1_FROZEN_SHA256 = "8c158a3068731e7015adfde790f9917ddb924fcd5243195a9640c833cca20eeb"


def _order(**overrides: Any) -> dict[str, Any]:
    order = {
        "customer_id": "C-1",
        "status": "delivered",
        "refund_deadline": 30,
        "refund_status": "none",
    }
    order.update(overrides)
    return order


def _task(bundle_dir: Path, **order_overrides: Any) -> TaskSpec:
    del bundle_dir
    state = {
        "customer_id": "C-1",
        "current_day": 20,
        "orders": {"O-1": _order(**order_overrides)},
    }
    return TaskSpec(
        task_id="t-1",
        split="qualification",
        scenario=TaskScenario.REFUND_ELIGIBLE,
        user_request="请为订单 O-1 办理退款。",
        initial_state=state,
        target_state=state,
        expected_decision=ExpectedDecision.ALLOW,
        required_reads=["O-1"],
        max_steps=5,
    )


def _env(bundle_dir: Path, **order_overrides: Any) -> RetailOpsEnv:
    bundle = load_bundle(bundle_dir)
    return RetailOpsEnv(_task(bundle_dir, **order_overrides), bundle)


def _refund(env: RetailOpsEnv, key: str, reason: str = "damaged") -> Any:
    return env.execute_tool(
        "refund_order", {"order_id": "O-1", "reason": reason, "idempotency_key": key}
    )


# ---------------------------------------------------------------------------
# v1 未被顺手改动
# ---------------------------------------------------------------------------


def test_v1_bundle_hash_is_unchanged() -> None:
    """政策引擎接入不得改变 v1 的任何一个字节。"""
    assert load_bundle(V1_DIR).bundle_sha256 == V1_FROZEN_SHA256


def test_v1_still_uses_the_two_parameter_refund_schema() -> None:
    bundle = load_bundle(V1_DIR)
    refund = next(tool for tool in bundle.tools if tool.name == "refund_order")

    assert refund.parameters["required"] == ["order_id", "reason"]
    assert bundle.policies.rules == list(
        (
            "refund_requires_lookup",
            "customer_must_own_order",
            "refund_window_must_be_open",
            "duplicate_refund_forbidden",
            "transient_retry_is_bounded",
            "tool_schema_is_strict",
        )
    )


def test_v1_and_v2_are_different_bundles() -> None:
    assert load_bundle(V1_DIR).bundle_sha256 != load_bundle(V2_DIR).bundle_sha256


# ---------------------------------------------------------------------------
# v2 政策外置
# ---------------------------------------------------------------------------


def test_v2_rules_are_executable_not_names() -> None:
    bundle = load_bundle(V2_DIR)

    assert [rule.rule_id for rule in bundle.policy_rules] == [
        "refund_requires_lookup",
        "customer_must_own_order",
        "refund_window_must_be_open",
        "duplicate_refund_forbidden",
    ]
    assert all(isinstance(entry, dict) for entry in bundle.policies.rules)


def test_v2_reproduces_v1_policy_decisions() -> None:
    """v2 的基线语义必须与 v1 一致——否则"只改了表达形式"这句话不成立。"""
    for overrides, violation in (
        ({"customer_id": "C-OTHER"}, "unauthorized_order"),
        ({"refund_deadline": 10}, "refund_not_eligible"),
        ({"refund_status": "refunded"}, "duplicate_refund"),
    ):
        env = _env(V2_DIR, **overrides)
        env.execute_tool("get_order", {"order_id": "O-1"})
        _refund(env, "k-1")
        assert env.check_policy() == [violation], overrides


def test_v2_still_denies_a_refund_that_skipped_the_lookup() -> None:
    env = _env(V2_DIR)

    _refund(env, "k-1")

    assert env.check_policy() == ["refund_without_lookup"]


def test_changing_only_the_yaml_threshold_changes_the_verdict(tmp_path: Path) -> None:
    """**P0-2 是否真的完成，只由这一条判定。**

    把退款窗口从"到期即止"改成"宽限 3 天"，只改 `policies.yaml` 里的一个数字，
    不碰任何 Python，同一条超期订单的判定必须从"拒绝"变成"放行"。
    """
    bundle_dir = tmp_path / "v2"
    shutil.copytree(V2_DIR, bundle_dir)

    strict = _env(bundle_dir, refund_deadline=18)  # current_day=20 → 已超期 2 天
    strict.execute_tool("get_order", {"order_id": "O-1"})
    _refund(strict, "k-1")
    assert strict.check_policy() == ["refund_not_eligible"]

    policies_path = bundle_dir / "policies.yaml"
    policies = yaml.safe_load(policies_path.read_text(encoding="utf-8"))
    window = next(r for r in policies["rules"] if r["id"] == "refund_window_must_be_open")
    window["when"]["gt"] = 3  # 宽限 3 天
    policies_path.write_text(yaml.safe_dump(policies, allow_unicode=True), encoding="utf-8")

    lenient = _env(bundle_dir, refund_deadline=18)
    lenient.execute_tool("get_order", {"order_id": "O-1"})
    observation = _refund(lenient, "k-1")

    assert lenient.check_policy() == []
    assert observation.ok is True
    assert lenient.get_state()["orders"]["O-1"]["refund_status"] == "refunded"


def test_a_rule_referencing_an_unknown_fact_fails_at_load_time(tmp_path: Path) -> None:
    """配置错误必须在加载 bundle 时暴露，而不是让一条政策永远不触发。"""
    bundle_dir = tmp_path / "v2"
    shutil.copytree(V2_DIR, bundle_dir)
    policies_path = bundle_dir / "policies.yaml"
    policies = yaml.safe_load(policies_path.read_text(encoding="utf-8"))
    policies["rules"][0]["when"] = {"fact": "moon_phase", "is": True}
    policies_path.write_text(yaml.safe_dump(policies, allow_unicode=True), encoding="utf-8")

    with pytest.raises(ValueError, match="未知事实"):
        load_bundle(bundle_dir)


# ---------------------------------------------------------------------------
# 幂等键
# ---------------------------------------------------------------------------


def test_v2_refund_requires_an_idempotency_key() -> None:
    """缺 key 必须是**非法调用**而不是静默放行——动钱接口不接受"忘了传"。"""
    env = _env(V2_DIR)
    env.execute_tool("get_order", {"order_id": "O-1"})

    observation = env.execute_tool("refund_order", {"order_id": "O-1", "reason": "damaged"})

    assert observation.ok is False
    assert observation.error_code == "invalid_arguments"
    assert env.get_state()["orders"]["O-1"]["refund_status"] == "none"


def test_same_key_retry_returns_the_same_result_and_refunds_once() -> None:
    """同 key 重试是客户端重试，不是第二笔退款。"""
    env = _env(V2_DIR)
    env.execute_tool("get_order", {"order_id": "O-1"})

    first = _refund(env, "k-1")
    second = _refund(env, "k-1")

    assert first.ok is True and second.ok is True
    assert first.content == second.content
    assert env.check_policy() == [], "同 key 重试不得记违规"
    assert env.get_state()["orders"]["O-1"]["refund_status"] == "refunded"


def test_a_new_key_on_an_already_refunded_order_is_a_duplicate_refund() -> None:
    """换一个新 key 就是在要求"再退一次"——必须按重复退款拒绝。"""
    env = _env(V2_DIR)
    env.execute_tool("get_order", {"order_id": "O-1"})

    _refund(env, "k-1")
    second = _refund(env, "k-2")

    assert second.ok is False
    assert env.check_policy() == ["duplicate_refund"]


def test_same_key_retry_after_a_transient_failure_still_refunds_once() -> None:
    """`refund_recovery` 的正确形态：瞬时失败后用同一个 key 重试，只退一次。"""
    bundle = load_bundle(V2_DIR)
    task = _task(V2_DIR).model_copy(update={"transient_failures": {"refund_order": 1}})
    env = RetailOpsEnv(task, bundle)
    env.execute_tool("get_order", {"order_id": "O-1"})

    first = _refund(env, "k-1")
    second = _refund(env, "k-1")
    third = _refund(env, "k-1")

    assert first.ok is False and first.error_code == "transient_error"
    assert second.ok is True
    assert third.content == second.content
    assert env.check_policy() == []


def test_max_transient_retries_actually_caps_the_injected_failures() -> None:
    """`max_transient_retries` 不再只是被解析：任务注入次数被政策上限截断。"""
    bundle = load_bundle(V2_DIR)
    assert bundle.policies.max_transient_retries == 1
    task = _task(V2_DIR).model_copy(update={"transient_failures": {"refund_order": 5}})
    env = RetailOpsEnv(task, bundle)
    env.execute_tool("get_order", {"order_id": "O-1"})

    first = _refund(env, "k-1")
    second = _refund(env, "k-1")

    assert first.ok is False and first.error_code == "transient_error"
    assert second.ok is True, "政策上限为 1，第二次必须成功而不是继续失败"
