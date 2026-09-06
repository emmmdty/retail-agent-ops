"""B-4 数据重建（v5）的任务集契约：分层切分 + margin 0 档 + reason 口径 A + max_steps 6。

预注册：`task_plan.md` Current Task（A-1，commit `ba463a6`，先于一切运行）；
A-0 裁定（2026-09-06，用户逐项确认）：沿用 v4 场景集；口径 A 映射表草案四行；
判读阈值按 A-6 草案冻结；v1.4 配对 schema 不启用。

设计要点（与 B4 提案 §二 的实现化）：
- 难度档 = margin 值本身（allow 侧网格 0/1/2/3/5/7/10/14 =「7+1 档」；deny 侧
  1/2/3/5/7/10/14 不变；lookup/check 按状态轴；cancel 按 v4 十档网格）。
- 每档在 train/dev/holdout 都出现：dev 每档 1 family、holdout 每档 1 family
  （加档外余量）、train 取余。B4 提案「每场景 family 35 不变」与「dev/holdout
  覆盖全部档位」在档数 ≥7 时算术不相容（dev=5 < 7 档），本实现按验收优先，
  配额表见 `_V5_SPLIT_QUOTAS` 并在 freeze 配置与 findings 中披露偏差。
- margin ≥10 family 占比 train:holdout ∈ [0.8, 1.25]（对照现状 5.0×）。
- reason 口径 A：请求陈述**事实**（自然语言），gold reason 为规范枚举值，
  metadata 携带 `reason_fact` + `acceptable_reasons`；verifier 按集合判定，
  仅对携带该 metadata 的任务生效（v1–v4 逐位不变）。
"""

from collections import Counter
from pathlib import Path

import pytest

from veritool_rl.core.agent.policy import OraclePolicy
from veritool_rl.core.agent.runner import run_episode
from veritool_rl.core.metrics import compute_metrics
from veritool_rl.core.trajectory import TaskScenario, ToolCall
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
from veritool_rl.retail_ops.domain.formal_tasks import (
    _V4_SCENARIOS,
    _v5_scenario_bucket_keys,
    build_v4_task_set,
    build_v5_task_set,
)

V5_VERSION = "retail_ops_v5_20260906"

#: 每场景 family 配额（train/dev/holdout）；任务数 = ×2 variant。
_V5_FAMILY_QUOTAS = {
    "lookup_status": (18, 7, 10),
    "refund_eligible": (21, 8, 11),
    "refund_denied_window": (18, 7, 10),
    "refund_denied_ownership": (18, 7, 10),
    "refund_denied_duplicate": (18, 7, 10),
    "refund_recovery": (21, 8, 11),
    "check_refund_status": (18, 7, 10),
    "cancel_eligible": (30, 10, 10),
    "cancel_denied_recent": (30, 10, 10),
    "cancel_denied_in_use": (30, 10, 10),
    "refund_then_cancel": (21, 8, 11),
    "cancel_recovery": (30, 10, 10),
}
#: rtc_stepwise 只进 train，family 数与 rtc train 相同（方案乙 1:1 派生）。
_V5_TASK_TOTALS = {"train": 588, "dev": 198, "holdout": 246}

#: 口径 A 映射表（A-0.2 用户裁定，判分契约）。
_V5_REASON_ACCEPTABLE = {
    "damaged": ("damaged",),
    "wrong_item": ("wrong_item",),
    "not_as_described": ("not_as_described", "damaged"),
    "changed_mind": ("changed_mind",),
}
_V5_REASON_FACTS = {
    "damaged": "商品存在破损",
    "wrong_item": "商家发错了货",
    "not_as_described": "商品与页面描述不符",
    "changed_mind": "不想要这件商品了",
}
#: 陈述退款事实的场景（请求携带事实从句、gold 含 refund_order 或 DENY 语义）。
_V5_FACT_SCENARIOS = {
    "refund_eligible",
    "refund_denied_window",
    "refund_denied_ownership",
    "refund_denied_duplicate",
    "refund_recovery",
    "refund_then_cancel",
}
_V5_ALLOW_MARGINS = (0, 1, 2, 3, 5, 7, 10, 14)
_V5_DENY_MARGINS = (1, 2, 3, 5, 7, 10, 14)


def _scenario_by_value(value: str) -> TaskScenario:
    return TaskScenario(value)


@pytest.fixture(scope="module")
def v5_task_set():
    return build_v5_task_set(V5_VERSION, 0)


def test_v5_task_totals_match_the_declared_contract(v5_task_set) -> None:
    assert len(v5_task_set.train) == _V5_TASK_TOTALS["train"]
    assert len(v5_task_set.dev) == _V5_TASK_TOTALS["dev"]
    assert len(v5_task_set.holdout) == _V5_TASK_TOTALS["holdout"]


def test_v5_per_scenario_family_quotas(v5_task_set) -> None:
    for split_name in ("train", "dev", "holdout"):
        records = getattr(v5_task_set, split_name)
        counts = Counter(record.task.scenario.value for record in records)
        for scenario_value, quotas in _V5_FAMILY_QUOTAS.items():
            index = {"train": 0, "dev": 1, "holdout": 2}[split_name]
            assert counts[_scenario_by_value(scenario_value)] == quotas[index] * 2, (
                f"{split_name}/{scenario_value}: {counts[_scenario_by_value(scenario_value)]}"
                f" != {quotas[index] * 2}"
            )


def test_v5_stepwise_is_train_only_and_derived_from_rtc_train(v5_task_set) -> None:
    train_counts = Counter(record.task.scenario for record in v5_task_set.train)
    assert train_counts[TaskScenario.RTC_STEPWISE] == 42
    assert train_counts[TaskScenario.REFUND_THEN_CANCEL] == 42
    for split in (v5_task_set.dev, v5_task_set.holdout):
        assert all(record.task.scenario is not TaskScenario.RTC_STEPWISE for record in split)


def test_v5_every_difficulty_bucket_appears_in_every_split(v5_task_set) -> None:
    """验收核心：每个场景的每个难度档在 train/dev/holdout 都有 family。"""
    for split_name in ("train", "dev", "holdout"):
        records = getattr(v5_task_set, split_name)
        by_scenario: dict[str, set[int]] = {}
        for record in records:
            task = record.task
            bucket = _difficulty_bucket(task)
            by_scenario.setdefault(task.scenario.value, set()).add(bucket)
        for scenario in _V4_SCENARIOS:
            expected_keys = set(_v5_scenario_bucket_keys(scenario))
            covered = by_scenario[scenario.value]
            assert covered == expected_keys, (
                f"{split_name}/{scenario.value}: 档覆盖 {sorted(covered)}，"
                f"缺 {sorted(expected_keys - covered)}"
            )


def _difficulty_bucket(task) -> int:
    state = task.initial_state
    primary_order_id = task.metadata["order_id"]
    order = state["orders"][primary_order_id]
    deadline = order.get("refund_deadline")
    if deadline is None or task.scenario.value in ("lookup_status", "check_refund_status"):
        return int(task.metadata["formal_family"]["state_variant"])
    return abs(int(deadline) - int(state["current_day"]))


def test_v5_margin_zero_present_in_train_dev_and_holdout(v5_task_set) -> None:
    """判定分界日（offset 0，政策判放行）必须进三个 split——根因 1 的空洞补上。"""
    for split_name in ("train", "dev", "holdout"):
        records = getattr(v5_task_set, split_name)
        for scenario_value in ("refund_eligible", "refund_recovery", "refund_then_cancel"):
            buckets = {
                _difficulty_bucket(record.task)
                for record in records
                if record.task.scenario.value == scenario_value
            }
            assert 0 in buckets, f"{split_name}/{scenario_value}: margin 0 缺席"


def test_v5_far_margin_share_ratio_train_vs_holdout(v5_task_set) -> None:
    """margin ≥10 family 占比 train:holdout ∈ [0.8, 1.25]（对照现状 5.0×/4.0×）。"""
    for scenario_value in (
        "refund_denied_window",
        "refund_denied_ownership",
        "refund_denied_duplicate",
        "refund_recovery",
        "cancel_eligible",
        "cancel_denied_recent",
        "cancel_denied_in_use",
        "cancel_recovery",
    ):
        shares: dict[str, float] = {}
        for split_name in ("train", "holdout"):
            records = getattr(v5_task_set, split_name)
            families = {
                record.family_fingerprint: _difficulty_bucket(record.task)
                for record in records
                if record.task.scenario.value == scenario_value
            }
            far = sum(1 for margin in families.values() if margin >= 10)
            shares[split_name] = far / len(families)
        ratio = shares["train"] / shares["holdout"]
        assert 0.8 <= ratio <= 1.25, (
            f"{scenario_value}: train {shares['train']:.3f} "
            f"vs holdout {shares['holdout']:.3f} → {ratio:.3f}"
        )


def test_v5_family_fingerprints_are_disjoint_across_splits(v5_task_set) -> None:
    train = {record.family_fingerprint for record in v5_task_set.train}
    dev = {record.family_fingerprint for record in v5_task_set.dev}
    holdout = {record.family_fingerprint for record in v5_task_set.holdout}
    assert train.isdisjoint(dev)
    assert train.isdisjoint(holdout)
    assert dev.isdisjoint(holdout)


def test_v5_allow_grid_contains_zero_and_deny_grid_does_not(v5_task_set) -> None:
    """探针网格耦合声明：探针 offset 轴不变；v5 的 deny 侧永不生成判定分界日
    （offset 0 由政策判放行，与 DENY 语义矛盾），allow 侧必含 0。"""
    for record in v5_task_set.train:
        scenario = record.task.scenario.value
        bucket = _difficulty_bucket(record.task)
        if scenario in ("refund_eligible", "refund_recovery", "refund_then_cancel"):
            assert bucket in _V5_ALLOW_MARGINS
        elif scenario in (
            "refund_denied_window",
            "refund_denied_ownership",
            "refund_denied_duplicate",
        ):
            assert bucket in _V5_DENY_MARGINS


def test_v5_reason_acceptable_sets_are_declared_in_metadata(v5_task_set) -> None:
    checked = 0
    for split_name in ("train", "dev", "holdout"):
        for record in getattr(v5_task_set, split_name):
            task = record.task
            if task.scenario.value not in _V5_FACT_SCENARIOS:
                continue
            gold_reason = task.metadata["reason"]
            acceptable = task.metadata["acceptable_reasons"]
            fact = task.metadata["reason_fact"]
            assert _V5_REASON_FACTS[gold_reason] == fact
            assert list(acceptable) == list(_V5_REASON_ACCEPTABLE[gold_reason])
            assert gold_reason in acceptable
            refund_calls = [call for call in task.expected_calls if call.name == "refund_order"]
            for call in refund_calls:
                assert call.arguments["reason"] == gold_reason
            checked += 1
    assert checked > 0


def test_v5_requests_state_the_fact_not_the_enum(v5_task_set) -> None:
    for split_name in ("train", "dev", "holdout"):
        for record in getattr(v5_task_set, split_name):
            task = record.task
            if task.scenario.value not in _V5_FACT_SCENARIOS:
                continue
            request = task.user_request
            fact = task.metadata["reason_fact"]
            assert fact in request, f"{task.task_id}: 请求未陈述事实 {fact!r}: {request!r}"
            assert task.metadata["reason"] not in request, (
                f"{task.task_id}: 请求泄漏了枚举词 {task.metadata['reason']!r}"
            )


def test_v5_wording_does_not_pseudo_correlate_with_outcome(v5_task_set) -> None:
    """交接 §4.6 约束 2：同一事实说法必须在拒绝侧与放行侧都出现。"""
    for fact in _V5_REASON_FACTS.values():
        sides: set[str] = set()
        for split_name in ("train", "dev", "holdout"):
            for record in getattr(v5_task_set, split_name):
                task = record.task
                if (
                    task.scenario.value in _V5_FACT_SCENARIOS
                    and task.metadata.get("reason_fact") == fact
                ):
                    sides.add(task.expected_decision.value)
        assert "allow" in sides and "deny" in sides, f"事实 {fact!r} 只出现在 {sides}"


def test_v5_step_budgets_are_six_and_seven(v5_task_set) -> None:
    multi_call = {"refund_recovery", "refund_then_cancel", "cancel_recovery"}
    for record in v5_task_set.train:
        scenario = record.task.scenario.value
        if scenario == "rtc_stepwise":
            assert record.task.max_steps == 6
        elif scenario in multi_call:
            assert record.task.max_steps == 7
        else:
            assert record.task.max_steps == 6
    for split in (v5_task_set.dev, v5_task_set.holdout):
        assert all(record.task.max_steps in (6, 7) for record in split)


def test_v4_task_budgets_are_untouched() -> None:
    task_set = build_v4_task_set("retail_ops_v4_20260905", 0)
    for record in task_set.train:
        scenario = record.task.scenario.value
        expected = (
            5 if scenario in ("refund_recovery", "refund_then_cancel", "cancel_recovery") else 4
        )
        assert record.task.max_steps == expected, scenario


def test_v5_tasks_are_oracle_solvable_with_zero_violations(v5_task_set) -> None:
    bundle = load_bundle(Path("domains/retail_ops/v4"))
    solved = 0
    for split_name in ("train", "dev", "holdout"):
        for record in getattr(v5_task_set, split_name):
            task = record.task
            trajectory = run_episode(
                task,
                lambda current: RetailOpsEnv(current, bundle),
                OraclePolicy(task),
                0,
            )
            assert trajectory.success, (
                f"{split_name}/{task.scenario.value}/{task.task_id} Oracle 解不出"
            )
            assert trajectory.violations == [], (
                f"{task.task_id}: Oracle 轨迹违规 {trajectory.violations}"
            )
            solved += 1
    assert solved == sum(_V5_TASK_TOTALS.values())


class _ReasonSwapPolicy:
    """按 gold 序列执行，但把 refund_order 的 reason 换成指定值。

    expected_calls 保持 gold 不动——这样参数判定真正检验的是
    「模型输出 vs gold」的匹配语义，而不是自己跟自己比。
    """

    name = "reason-swap"

    def __init__(self, task, reason: str) -> None:
        self._calls = [call.model_copy(deep=True) for call in task.expected_calls]
        self._reason = reason
        self._index = 0

    def respond(self, messages, tools):
        del messages, tools
        if self._index >= len(self._calls):
            from veritool_rl.core.agent.policy import PolicyOutput

            return PolicyOutput(raw_text="任务已完成。", final_response="任务已完成。")
        call = self._calls[self._index]
        self._index += 1
        if call.name == "refund_order":
            call = ToolCall(
                name="refund_order", arguments={**call.arguments, "reason": self._reason}
            )
        import json

        payload = {"name": call.name, "arguments": call.arguments}
        raw = f"<tool_call>\n{json.dumps(payload, ensure_ascii=False)}\n</tool_call>"
        from veritool_rl.core.agent.policy import PolicyOutput

        return PolicyOutput(raw_text=raw, tool_call=call)


def test_v5_alternative_reason_within_set_is_accepted_by_verifier(v5_task_set) -> None:
    """口径 A 判分：模型给出集合内另一可接受理由时，milestone/参数判定按命中计。"""
    bundle = load_bundle(Path("domains/retail_ops/v4"))
    checked = 0
    for record in v5_task_set.dev:
        task = record.task
        if task.scenario is not TaskScenario.REFUND_ELIGIBLE:
            continue
        gold_reason = task.metadata["reason"]
        alternates = [r for r in task.metadata["acceptable_reasons"] if r != gold_reason]
        if not alternates:
            continue
        assert "acceptable_reasons" in task.metadata
        trajectory = run_episode(
            task,
            lambda current: RetailOpsEnv(current, bundle),
            _ReasonSwapPolicy(task, alternates[0]),
            0,
        )
        assert trajectory.success, f"{task.task_id}: 集合内替代理由未被环境接受"
        metrics = compute_metrics([trajectory], 10, 0)
        assert metrics["argument_accuracy"] == 1.0, (
            f"{task.task_id}: 集合内替代理由应计为参数命中，got {metrics['argument_accuracy']}"
        )
        checked += 1
    assert checked > 0


def test_v4_exact_match_semantics_are_untouched() -> None:
    """旧数据集任务不携带口径 A metadata → 参数判定保持逐字精确匹配。"""
    task_set = build_v4_task_set("retail_ops_v4_20260905", 0)
    bundle = load_bundle(Path("domains/retail_ops/v4"))
    record = next(r for r in task_set.dev if r.task.scenario is TaskScenario.REFUND_ELIGIBLE)
    task = record.task
    assert "acceptable_reasons" not in task.metadata
    gold_reason = task.metadata["reason"]
    alternate = next(
        r for r in ("damaged", "wrong_item", "not_as_described", "changed_mind") if r != gold_reason
    )
    trajectory = run_episode(
        task,
        lambda current: RetailOpsEnv(current, bundle),
        _ReasonSwapPolicy(task, alternate),
        0,
    )
    metrics = compute_metrics([trajectory], 10, 0)
    assert metrics["argument_accuracy"] < 1.0, "v4 任务上集合外理由不应计为参数命中"


def test_older_versions_rejected_by_the_v5_builder() -> None:
    with pytest.raises(ValueError):
        build_v5_task_set("retail_ops_v4_20260905", 0)
    with pytest.raises(ValueError):
        build_v5_task_set("retail_ops_v1_r2_20260722", 0)


def test_eval_config_step_budget_is_version_locked() -> None:
    """v1–v4 预算冻结为 5、v5 必须为 7——两者都由 config validator 钉死。"""
    from pydantic import ValidationError

    from veritool_rl.retail_ops.evaluate.base_evaluation import BaseEvaluationConfig

    common = {
        "model": {
            "repo": "Qwen/Qwen3-4B",
            "revision": "8cd0101f70cac4f1efcebc979faf483558e39297",
            "local_dir": "Qwen3-4B-pinned",
            "file_sha256": {"model.safetensors": "0" * 64},
        },
        "generation": {"max_new_tokens": 256},
        "code_commit": "a" * 40,
        "uv_lock_sha256": "b" * 64,
    }
    v5_ok = BaseEvaluationConfig(dataset_version="retail_ops_v5_20260906", max_steps=7, **common)
    assert v5_ok.max_steps == 7
    with pytest.raises(ValidationError):
        BaseEvaluationConfig(dataset_version="retail_ops_v5_20260906", max_steps=5, **common)
    v4_ok = BaseEvaluationConfig(dataset_version="retail_ops_v4_20260905", max_steps=5, **common)
    assert v4_ok.max_steps == 5
    with pytest.raises(ValidationError):
        BaseEvaluationConfig(dataset_version="retail_ops_v4_20260905", max_steps=7, **common)


def test_sealed_report_literal_accepts_v5_budget() -> None:
    """报告 schema 放宽到 Literal[5, 7]；旧证据磁盘值 5 的加载不受影响。"""
    from typing import get_args

    from veritool_rl.retail_ops.evaluate.base_evaluation import BaseRunEvidence
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import SealedEvaluationReport

    assert get_args(BaseRunEvidence.model_fields["max_steps"].annotation) == (5, 7)
    assert get_args(SealedEvaluationReport.model_fields["max_steps"].annotation) == (5, 7)
    assert BaseRunEvidence.model_fields["max_steps"].default == 5
    assert SealedEvaluationReport.model_fields["max_steps"].default == 5


def test_manifest_expected_counts_match_the_v5_task_set(v5_task_set) -> None:
    from veritool_rl.retail_ops.build.formal_manifests import _expected_per_scenario
    from veritool_rl.retail_ops.domain.formal_tasks import FormalSplit

    for split in (FormalSplit.TRAIN, FormalSplit.DEV, FormalSplit.HOLDOUT):
        expected = _expected_per_scenario(split, V5_VERSION)
        actual = Counter(record.task.scenario.value for record in v5_task_set.records(split))
        assert expected == dict(actual), split
