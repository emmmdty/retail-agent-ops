"""RetailOps R2 formal family-first task generation."""

from __future__ import annotations

import copy
import hashlib
from collections import Counter
from enum import StrEnum
from typing import Any

from pydantic import Field

from veritool_rl.core.artifacts import canonical_json
from veritool_rl.core.trajectory import (
    ExpectedDecision,
    TaskScenario,
    TaskSpec,
    ToolCall,
)
from veritool_rl.core.trajectory.schema import StrictModel

_GENERATOR_ID = "family_sha256_v1"
_CURRENT_DAY = 20
# 前 7 档是 v1/v4 冻结数据集的 margin 网格（R7 状态增强刻意落在网格之外，
# 不得改动）；第 8–10 档只被 `_V4_EXTENDED_CANCEL_VERSIONS` 版本上的
# CANCEL_* 扩展 family（state 7–9）使用，不改变任何旧版本的重建路径。
_MARGINS = (1, 2, 3, 5, 7, 10, 14)
_V4_TASK_MARGINS = (*_MARGINS, 4, 6, 12)
_LOOKUP_STATUSES = (
    "pending",
    "processing",
    "shipped",
    "delivered",
    "cancelled",
    "returned",
    "refunded",
)
_REASONS = ("damaged", "wrong_item", "not_as_described", "changed_mind")
#: gold 序列含多次工具调用的场景（v1 冻结语义：步数预算多一档）。
_MULTI_CALL_SCENARIOS = frozenset(
    {
        TaskScenario.REFUND_RECOVERY,
        TaskScenario.REFUND_THEN_CANCEL,
        TaskScenario.CANCEL_RECOVERY,
    }
)
_SCENARIOS = (
    TaskScenario.LOOKUP_STATUS,
    TaskScenario.REFUND_ELIGIBLE,
    TaskScenario.REFUND_DENIED_WINDOW,
    TaskScenario.REFUND_DENIED_OWNERSHIP,
    TaskScenario.REFUND_DENIED_DUPLICATE,
    TaskScenario.REFUND_RECOVERY,
)
_FINGERPRINT_FIELDS = (
    "task_fingerprint",
    "family_fingerprint",
    "content_fingerprint",
    "source_fingerprint",
    "derivation_fingerprint",
)


class FormalSplit(StrEnum):
    """R2 frozen task split."""

    TRAIN = "train"
    DEV = "dev"
    HOLDOUT = "holdout"


class FormalTaskRecord(StrictModel):
    """A private task together with its five opaque fingerprints."""

    task: TaskSpec
    task_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    family_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    derivation_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    variant_index: int = Field(ge=0, le=1)

    @classmethod
    def from_task(cls, task: TaskSpec, variant_index: int) -> FormalTaskRecord:
        """Derive all formal fingerprints from a materialized private task."""
        family_payload = _family_payload_from_task(task)
        primary_order_id = _primary_order_id(task)
        return cls(
            task=task.model_copy(deep=True),
            task_fingerprint=_sha256({"task": task.model_dump(mode="json")}),
            family_fingerprint=_sha256({"family": family_payload}),
            content_fingerprint=_sha256(
                {
                    "content": {
                        "scenario": task.scenario.value,
                        "user_request": task.user_request,
                        "initial_state": task.initial_state,
                        "transient_failures": task.transient_failures,
                        "max_steps": task.max_steps,
                    }
                }
            ),
            source_fingerprint=_sha256({"source": family_payload}),
            derivation_fingerprint=_sha256(
                {"derivation": _derivation_payload(task, primary_order_id)}
            ),
            variant_index=variant_index,
        )


class FormalTaskSet(StrictModel):
    """The deterministic R2 task set before artifact serialization."""

    dataset_version: str = Field(min_length=1)
    seed: int
    generator_id: str = Field(default=_GENERATOR_ID, min_length=1)
    train: tuple[FormalTaskRecord, ...]
    dev: tuple[FormalTaskRecord, ...]
    holdout: tuple[FormalTaskRecord, ...]

    def records(self, split: FormalSplit | str) -> tuple[FormalTaskRecord, ...]:
        """Return the split's stable materialization order."""
        selected = FormalSplit(split)
        if selected is FormalSplit.TRAIN:
            return self.train
        if selected is FormalSplit.DEV:
            return self.dev
        return self.holdout

    def assert_exact_quotas(self) -> None:
        """Verify formal totals, category quotas, family pairing, and isolation."""
        expected_per_category = {
            FormalSplit.TRAIN: 40,
            FormalSplit.DEV: 10,
            FormalSplit.HOLDOUT: 20,
        }
        for split, expected_count in expected_per_category.items():
            records = self.records(split)
            if len(records) != expected_count * len(_SCENARIOS):
                raise ValueError(f"{split} 任务总数不符合冻结配额")
            if any(record.task.split != split.value for record in records):
                raise ValueError(f"{split} 容器与任务 split 不一致")
            scenario_counts = Counter(record.task.scenario for record in records)
            if scenario_counts != dict.fromkeys(_SCENARIOS, expected_count):
                raise ValueError(f"{split} 类别配额不符合冻结契约")

            families: dict[str, list[FormalTaskRecord]] = {}
            for record in records:
                expected = FormalTaskRecord.from_task(record.task, record.variant_index)
                if any(
                    getattr(record, field) != getattr(expected, field)
                    for field in _FINGERPRINT_FIELDS
                ):
                    raise ValueError(f"{split} 记录指纹与 task/variant 不一致")
                if record.task.metadata.get("variant_index") != record.variant_index:
                    raise ValueError(f"{split} task 与 record 的 variant_index 不一致")
                families.setdefault(record.family_fingerprint, []).append(record)

            if not families:
                raise ValueError(f"{split} 不包含 semantic family")
            for family_records in families.values():
                if len(family_records) != 2:
                    raise ValueError(f"{split} 的每个 semantic family 必须恰有两个变体")
                if {record.variant_index for record in family_records} != {0, 1}:
                    raise ValueError(f"{split} family 的 variant_index 必须精确为 0 和 1")
                for field in ("task_fingerprint", "content_fingerprint"):
                    if len({getattr(record, field) for record in family_records}) != 2:
                        raise ValueError(f"{split} family 的 {field} 必须有两个唯一值")
                for field in (
                    "family_fingerprint",
                    "source_fingerprint",
                    "derivation_fingerprint",
                ):
                    if len({getattr(record, field) for record in family_records}) != 1:
                        raise ValueError(f"{split} family 的 {field} 必须由两个变体共享")

        for field in (
            "task_fingerprint",
            "family_fingerprint",
            "content_fingerprint",
            "source_fingerprint",
            "derivation_fingerprint",
        ):
            values = {
                split: {getattr(record, field) for record in self.records(split)}
                for split in FormalSplit
            }
            if (
                not values[FormalSplit.TRAIN].isdisjoint(values[FormalSplit.DEV])
                or not values[FormalSplit.TRAIN].isdisjoint(values[FormalSplit.HOLDOUT])
                or not values[FormalSplit.DEV].isdisjoint(values[FormalSplit.HOLDOUT])
            ):
                raise ValueError(f"{field} 跨 split 重叠")

    def assert_exact_quotas_v4(self) -> None:
        """Verify v4 totals.

        默认 12 scenarios × (40/10/20) = 480/120/240；`_V4_EXTENDED_CANCEL_VERSIONS`
        上的版本（方案甲）CANCEL_* 4 场景 train 提到 70 任务（35 family × 2），
        总量 600/120/240；`_V4_STEPWISE_VERSIONS` 上的版本（方案乙）train 再加
        RTC_STEPWISE 40 任务，总量 640/120/240。
        """
        extended = self.dataset_version in _V4_EXTENDED_CANCEL_VERSIONS
        stepwise = self.dataset_version in _V4_STEPWISE_VERSIONS
        train_per_scenario = {
            scenario: (70 if extended and scenario in _V4_CANCEL_SCENARIOS else 40)
            for scenario in _V4_SCENARIOS
        }
        expected_total = {
            FormalSplit.TRAIN: sum(train_per_scenario.values()) + (40 if stepwise else 0),
            FormalSplit.DEV: 10 * len(_V4_SCENARIOS),
            FormalSplit.HOLDOUT: 20 * len(_V4_SCENARIOS),
        }
        for split in (FormalSplit.TRAIN, FormalSplit.DEV, FormalSplit.HOLDOUT):
            records = self.records(split)
            if len(records) != expected_total[split]:
                raise ValueError(f"v4 {split} 任务总数不符合冻结配额")
            if any(record.task.split != split.value for record in records):
                raise ValueError(f"v4 {split} 容器与任务 split 不一致")
            scenario_counts = Counter(record.task.scenario for record in records)
            expected_counts = (
                train_per_scenario
                if split is FormalSplit.TRAIN
                else dict.fromkeys(_V4_SCENARIOS, 10 if split is FormalSplit.DEV else 20)
            )
            if stepwise and split is FormalSplit.TRAIN:
                expected_counts = {**expected_counts, TaskScenario.RTC_STEPWISE: 40}
            if scenario_counts != expected_counts:
                raise ValueError(f"v4 {split} 类别配额不符合冻结契约")

            families: dict[str, list[FormalTaskRecord]] = {}
            for record in records:
                expected = FormalTaskRecord.from_task(record.task, record.variant_index)
                if any(
                    getattr(record, field) != getattr(expected, field)
                    for field in _FINGERPRINT_FIELDS
                ):
                    raise ValueError(f"v4 {split} 记录指纹与 task/variant 不一致")
                if record.task.metadata.get("variant_index") != record.variant_index:
                    raise ValueError(f"v4 {split} task 与 record 的 variant_index 不一致")
                families.setdefault(record.family_fingerprint, []).append(record)

            if not families:
                raise ValueError(f"v4 {split} 不包含 semantic family")
            for family_records in families.values():
                if len(family_records) != 2:
                    raise ValueError(f"v4 {split} 的每个 semantic family 必须恰有两个变体")
                if {record.variant_index for record in family_records} != {0, 1}:
                    raise ValueError(f"v4 {split} family 的 variant_index 必须精确为 0 和 1")

        for field in (
            "task_fingerprint",
            "family_fingerprint",
            "content_fingerprint",
            "source_fingerprint",
            "derivation_fingerprint",
        ):
            values = {
                split: {getattr(record, field) for record in self.records(split)}
                for split in FormalSplit
            }
            if (
                not values[FormalSplit.TRAIN].isdisjoint(values[FormalSplit.DEV])
                or not values[FormalSplit.TRAIN].isdisjoint(values[FormalSplit.HOLDOUT])
                or not values[FormalSplit.DEV].isdisjoint(values[FormalSplit.HOLDOUT])
            ):
                raise ValueError(f"v4 {field} 跨 split 重叠")

    def assert_exact_quotas_v5(self) -> None:
        """Verify v5 totals, per-scenario quotas, stratified coverage, and isolation.

        v5 契约（B-4，`retail_ops_v5_20260906`）：
        - 总量 train 588 / dev 198 / holdout 246（family 配额表 `_V5_SPLIT_QUOTAS`，
          任务数 = family × 2 variant）；
        - **分层覆盖**：每个场景的每个难度档（margin 值或状态轴下标）在三个 split
          都有 family——根因 1 的验收（对照 v1 的 dev 4/7、2/7 档覆盖缺口）；
        - **判定分界日**：allow 侧三个场景的 margin 0 档在三个 split 都在场；
        - **难度偏移**：margin ≥10 family 占比 train:holdout ∈ [0.8, 1.25]
          （对照现状 refund_denied_window 5.0×、refund_recovery 4.0×）；
        - family 指纹跨 split 互斥 + 逐记录指纹复算（与 v1/v4 同强度）。
        """
        expected_total = {
            FormalSplit.TRAIN: 588,
            FormalSplit.DEV: 198,
            FormalSplit.HOLDOUT: 246,
        }
        for split in (FormalSplit.TRAIN, FormalSplit.DEV, FormalSplit.HOLDOUT):
            records = self.records(split)
            if len(records) != expected_total[split]:
                raise ValueError(f"v5 {split} 任务总数不符合冻结配额")
            if any(record.task.split != split.value for record in records):
                raise ValueError(f"v5 {split} 容器与任务 split 不一致")
            scenario_counts = Counter(record.task.scenario for record in records)
            expected_counts = {
                scenario: _V5_SPLIT_QUOTAS[scenario][
                    {FormalSplit.TRAIN: 0, FormalSplit.DEV: 1, FormalSplit.HOLDOUT: 2}[split]
                ]
                * 2
                for scenario in _V4_SCENARIOS
            }
            if split is FormalSplit.TRAIN:
                expected_counts = {**expected_counts, TaskScenario.RTC_STEPWISE: 42}
            if scenario_counts != expected_counts:
                raise ValueError(f"v5 {split} 类别配额不符合冻结契约")

            families: dict[str, list[FormalTaskRecord]] = {}
            for record in records:
                expected = FormalTaskRecord.from_task(record.task, record.variant_index)
                if any(
                    getattr(record, field) != getattr(expected, field)
                    for field in _FINGERPRINT_FIELDS
                ):
                    raise ValueError(f"v5 {split} 记录指纹与 task/variant 不一致")
                if record.task.metadata.get("variant_index") != record.variant_index:
                    raise ValueError(f"v5 {split} task 与 record 的 variant_index 不一致")
                families.setdefault(record.family_fingerprint, []).append(record)

            if not families:
                raise ValueError(f"v5 {split} 不包含 semantic family")
            for family_records in families.values():
                if len(family_records) != 2:
                    raise ValueError(f"v5 {split} 的每个 semantic family 必须恰有两个变体")
                if {record.variant_index for record in family_records} != {0, 1}:
                    raise ValueError(f"v5 {split} family 的 variant_index 必须精确为 0 和 1")

        for field in (
            "task_fingerprint",
            "family_fingerprint",
            "content_fingerprint",
            "source_fingerprint",
            "derivation_fingerprint",
        ):
            values = {
                split: {getattr(record, field) for record in self.records(split)}
                for split in FormalSplit
            }
            if (
                not values[FormalSplit.TRAIN].isdisjoint(values[FormalSplit.DEV])
                or not values[FormalSplit.TRAIN].isdisjoint(values[FormalSplit.HOLDOUT])
                or not values[FormalSplit.DEV].isdisjoint(values[FormalSplit.HOLDOUT])
            ):
                raise ValueError(f"v5 {field} 跨 split 重叠")

        self._assert_stratified_coverage()

    def assert_exact_quotas_v6(self) -> None:
        """Verify the v6 contract: v5 结构配额 + rtc_stepwise 请求修复（单变量）。

        v6（`retail_ops_v6_20260907`）与 v5 的总量、类别配额、分层覆盖、margin 0
        三分与指纹强度完全相同——修复只改 `rtc_stepwise` 的请求文本（及其指纹），
        不动任何结构契约，因此这里逐字沿用 v5 的全部断言；请求文本的修复由
        `tests/test_retail_ops_v6_tasks.py` 锁定。
        """
        self.assert_exact_quotas_v5()

    def _assert_stratified_coverage(self) -> None:
        """分层验收：全档覆盖 + margin 0 三分 + 远超期占比比值。"""
        for scenario in _V4_SCENARIOS:
            buckets_by_split: dict[FormalSplit, set[int]] = {}
            families_by_split: dict[FormalSplit, dict[str, int]] = {}
            for split in (FormalSplit.TRAIN, FormalSplit.DEV, FormalSplit.HOLDOUT):
                buckets: set[int] = set()
                family_margins: dict[str, int] = {}
                for record in self.records(split):
                    if record.task.scenario is not scenario:
                        continue
                    buckets.add(_v5_bucket_key(record.task.metadata["formal_family"]))
                    family_margins[record.family_fingerprint] = _v5_bucket_key(
                        record.task.metadata["formal_family"]
                    )
                buckets_by_split[split] = buckets
                families_by_split[split] = family_margins
            expected_keys = set(_v5_scenario_bucket_keys(scenario))
            for split in (FormalSplit.TRAIN, FormalSplit.DEV, FormalSplit.HOLDOUT):
                if buckets_by_split[split] != expected_keys:
                    missing = sorted(expected_keys - buckets_by_split[split])
                    raise ValueError(
                        f"v5 {scenario.value} 的 {split} 未覆盖全部难度档：缺 {missing}"
                    )
            margin_based = scenario not in (
                TaskScenario.LOOKUP_STATUS,
                TaskScenario.CHECK_REFUND_STATUS,
            )
            if not margin_based:
                continue
            allow_side = scenario in _V5_ALLOW_MARGIN_SCENARIOS
            if allow_side:
                for split in (FormalSplit.TRAIN, FormalSplit.DEV, FormalSplit.HOLDOUT):
                    if 0 not in buckets_by_split[split]:
                        raise ValueError(f"v5 {scenario.value} 的 {split} 缺 margin 0 档")
            far_train = sum(1 for m in families_by_split[FormalSplit.TRAIN].values() if m >= 10)
            far_holdout = sum(1 for m in families_by_split[FormalSplit.HOLDOUT].values() if m >= 10)
            if far_holdout == 0 or far_train == 0:
                raise ValueError(f"v5 {scenario.value} 的远超期档在某侧为零")
            ratio = (far_train / len(families_by_split[FormalSplit.TRAIN])) / (
                far_holdout / len(families_by_split[FormalSplit.HOLDOUT])
            )
            if not 0.8 <= ratio <= 1.25:
                share_train = far_train / len(families_by_split[FormalSplit.TRAIN])
                share_holdout = far_holdout / len(families_by_split[FormalSplit.HOLDOUT])
                raise ValueError(
                    f"v5 {scenario.value} 的 margin≥10 占比 "
                    f"train {share_train:.3f} : holdout {share_holdout:.3f} = {ratio:.3f}"
                    " 超出 [0.8, 1.25]"
                )


def build_formal_task_set(dataset_version: str, seed: int) -> FormalTaskSet:
    """Build the approved 240/60/120 family-first R2 task contract."""
    if not dataset_version:
        raise ValueError("dataset_version 不能为空")

    records: dict[FormalSplit, list[FormalTaskRecord]] = {split: [] for split in FormalSplit}
    for scenario_index, scenario in enumerate(_SCENARIOS):
        families = sorted(
            (
                _family_spec(
                    dataset_version, scenario, scenario_index, state_variant, context_variant
                )
                for state_variant in range(7)
                for context_variant in range(5)
            ),
            key=lambda family: _sha256({"family": family}),
        )
        for family_index, family in enumerate(families):
            split = (
                FormalSplit.TRAIN
                if family_index < 20
                else FormalSplit.DEV
                if family_index < 25
                else FormalSplit.HOLDOUT
            )
            family_fingerprint = _sha256({"family": family})
            for variant_index in range(2):
                task = _materialize_task(
                    dataset_version=dataset_version,
                    seed=seed,
                    split=split,
                    family=family,
                    family_fingerprint=family_fingerprint,
                    variant_index=variant_index,
                )
                records[split].append(FormalTaskRecord.from_task(task, variant_index))

    task_set = FormalTaskSet(
        dataset_version=dataset_version,
        seed=seed,
        train=tuple(records[FormalSplit.TRAIN]),
        dev=tuple(records[FormalSplit.DEV]),
        holdout=tuple(records[FormalSplit.HOLDOUT]),
    )
    task_set.assert_exact_quotas()
    return task_set


def _family_spec(
    dataset_version: str,
    scenario: TaskScenario,
    scenario_index: int,
    state_variant: int,
    context_variant: int,
) -> dict[str, Any]:
    margin = _MARGINS[state_variant]
    reason = _REASONS[(scenario_index + state_variant * 5 + context_variant) % 4]
    decision, call_sequence, transient_rule, policy_state = _scenario_contract(
        scenario, state_variant, margin, reason
    )
    return {
        "dataset_version": dataset_version,
        "scenario": scenario.value,
        "state_variant": state_variant,
        "context_variant": context_variant,
        "primary_policy_state": policy_state,
        "reason": reason,
        "distractor_count": context_variant,
        "expected_decision": decision.value,
        "required_reads": ["primary_order"],
        "call_sequence": call_sequence,
        "transient_failure_rule": transient_rule,
    }


def _scenario_contract(
    scenario: TaskScenario,
    state_variant: int,
    margin: int,
    reason: str,
) -> tuple[ExpectedDecision, list[dict[str, Any]], dict[str, int], dict[str, Any]]:
    get_order = {"name": "get_order", "arguments": {"order_id": "primary_order"}}
    refund = {
        "name": "refund_order",
        "arguments": {"order_id": "primary_order", "reason": reason},
    }
    if scenario is TaskScenario.LOOKUP_STATUS:
        return (
            ExpectedDecision.INFORM,
            [get_order],
            {},
            {"status": _LOOKUP_STATUSES[state_variant], "refund_status": "none"},
        )
    if scenario is TaskScenario.REFUND_ELIGIBLE:
        return (
            ExpectedDecision.ALLOW,
            [get_order, refund],
            {},
            {
                "owner": "customer",
                "refund_deadline": _CURRENT_DAY + margin,
                "refund_status": "none",
            },
        )
    if scenario is TaskScenario.REFUND_RECOVERY:
        return (
            ExpectedDecision.ALLOW,
            [get_order, refund, copy.deepcopy(refund)],
            {"refund_order": 1},
            {
                "owner": "customer",
                "refund_deadline": _CURRENT_DAY + margin,
                "refund_status": "none",
            },
        )
    if scenario is TaskScenario.REFUND_DENIED_WINDOW:
        return (
            ExpectedDecision.DENY,
            [get_order],
            {},
            {
                "owner": "customer",
                "refund_deadline": _CURRENT_DAY - margin,
                "refund_status": "none",
            },
        )
    if scenario is TaskScenario.REFUND_DENIED_OWNERSHIP:
        return (
            ExpectedDecision.DENY,
            [get_order],
            {},
            {
                "owner": "other_customer",
                "refund_deadline": _CURRENT_DAY + margin,
                "refund_status": "none",
            },
        )
    if scenario is TaskScenario.REFUND_DENIED_DUPLICATE:
        return (
            ExpectedDecision.DENY,
            [get_order],
            {},
            {
                "owner": "customer",
                "refund_deadline": _CURRENT_DAY + margin,
                "refund_status": "refunded",
            },
        )
    raise ValueError(f"不支持的 RetailOps 场景: {scenario}")


def _materialize_task(
    *,
    dataset_version: str,
    seed: int,
    split: FormalSplit,
    family: dict[str, Any],
    family_fingerprint: str,
    variant_index: int,
    max_steps: int | None = None,
) -> TaskSpec:
    identity = _sha256(
        {
            "dataset_version": dataset_version,
            "seed": seed,
            "family_fingerprint": family_fingerprint,
            "variant_index": variant_index,
        }
    )
    customer_id = f"C-{identity[:12].upper()}"
    other_customer_id = f"C-{identity[12:24].upper()}"
    order_id = f"O-{identity[24:36].upper()}"
    policy_state = family["primary_policy_state"]
    scenario = TaskScenario(family["scenario"])
    primary_owner = (
        other_customer_id if policy_state.get("owner") == "other_customer" else customer_id
    )
    margin = (
        family.get("primary_policy_state", {}).get("refund_deadline", _CURRENT_DAY + 14)
        - _CURRENT_DAY
    )
    primary_order = {
        "customer_id": primary_owner,
        "status": policy_state.get("status", "delivered"),
        "refund_deadline": policy_state.get("refund_deadline", _CURRENT_DAY + 14),
        "refund_status": policy_state["refund_status"],
    }
    orders = {order_id: primary_order}
    # REFUND_THEN_CANCEL / RTC_STEPWISE 需要第二个订单（other_order）
    other_short = identity[36:48].upper() if len(identity) > 48 else identity[:12].upper()
    other_order_id = f"O-{other_short}OTHER"
    if scenario in (TaskScenario.REFUND_THEN_CANCEL, TaskScenario.RTC_STEPWISE):
        orders[other_order_id] = {
            "customer_id": primary_owner,
            "status": "pending",
            "refund_deadline": _CURRENT_DAY + margin,
            "refund_status": "none",
        }
    for distractor_index in range(family["distractor_count"]):
        distractor_digest = _sha256({"identity": identity, "distractor_index": distractor_index})
        distractor_order_id = f"O-{distractor_digest[:12].upper()}"
        orders[distractor_order_id] = {
            "customer_id": f"C-{distractor_digest[12:24].upper()}",
            "status": "shipped",
            "refund_deadline": _CURRENT_DAY + 30,
            "refund_status": "none",
        }

    initial_state: dict[str, Any] = {
        "customer_id": customer_id,
        "current_day": _CURRENT_DAY,
        "orders": orders,
    }
    target_state = copy.deepcopy(initial_state)
    reason = str(family["reason"])
    expected_calls = [
        ToolCall(
            name=str(call["name"]),
            arguments={
                key: order_id
                if value == "primary_order"
                else other_order_id
                if value == "other_order"
                else value
                for key, value in dict(call["arguments"]).items()
            },
        )
        for call in family["call_sequence"]
    ]
    decision = ExpectedDecision(family["expected_decision"])
    if decision is ExpectedDecision.ALLOW:
        cancel_scenarios = {
            TaskScenario.CANCEL_ELIGIBLE,
            TaskScenario.CANCEL_RECOVERY,
        }
        if scenario in cancel_scenarios:
            target_state["orders"][order_id]["status"] = "cancelled"
            target_state["orders"][order_id]["cancel_status"] = "cancelled"
        elif scenario is TaskScenario.REFUND_THEN_CANCEL:
            target_state["orders"][order_id]["refund_status"] = "refunded"
            target_state["orders"][other_order_id]["status"] = "cancelled"
            target_state["orders"][other_order_id]["cancel_status"] = "cancelled"
        elif scenario is TaskScenario.RTC_STEPWISE:
            # 辅助任务只触碰第二订单 B；主单 A 保持 initial 状态（同一状态的第一段）
            target_state["orders"][other_order_id]["status"] = "cancelled"
            target_state["orders"][other_order_id]["cancel_status"] = "cancelled"
        else:
            target_state["orders"][order_id]["refund_status"] = "refunded"

    _multi_call_scenarios = _MULTI_CALL_SCENARIOS
    metadata: dict[str, Any] = {
        "dataset_version": dataset_version,
        "generator_id": _GENERATOR_ID,
        "family_id": f"F-{family_fingerprint[:16].upper()}",
        "formal_family": copy.deepcopy(family),
        "customer_id": customer_id,
        "order_id": order_id,
        "reason": reason,
        "variant_index": variant_index,
    }
    if "reason_fact" in family:
        metadata["reason_fact"] = str(family["reason_fact"])
        metadata["acceptable_reasons"] = list(family["acceptable_reasons"])
    return TaskSpec(
        task_id=_sha256({"task_identity": identity}),
        split=split.value,
        scenario=scenario,
        user_request=_user_request_for(
            family, scenario, order_id, reason, variant_index, other_order_id
        ),
        initial_state=initial_state,
        target_state=target_state,
        expected_calls=expected_calls,
        expected_decision=decision,
        required_reads=[other_order_id if scenario is TaskScenario.RTC_STEPWISE else order_id],
        transient_failures=dict(family["transient_failure_rule"]),
        max_steps=max_steps
        if max_steps is not None
        else (5 if scenario in _multi_call_scenarios else 4),
        metadata=metadata,
    )


def _family_payload_from_task(task: TaskSpec) -> dict[str, Any]:
    family = task.metadata.get("formal_family")
    if not isinstance(family, dict):
        raise ValueError("正式任务缺少 family canonical payload")
    return copy.deepcopy(family)


def _primary_order_id(task: TaskSpec) -> str:
    order_id = task.metadata.get("order_id")
    if not isinstance(order_id, str) or not order_id:
        raise ValueError("正式任务缺少 primary order ID")
    return order_id


def _derivation_payload(task: TaskSpec, primary_order_id: str) -> dict[str, Any]:
    return {
        "scenario": task.scenario.value,
        "initial_state": _normalized_policy_state(task.initial_state, primary_order_id),
        "target_state": _normalized_policy_state(task.target_state, primary_order_id),
        "expected_decision": (
            task.expected_decision.value if task.expected_decision is not None else None
        ),
        "required_reads": [
            "primary_order" if order_id == primary_order_id else "other_order"
            for order_id in task.required_reads
        ],
        "call_sequence": [
            {
                "name": call.name,
                "arguments": {
                    key: _normalized_argument(key, value, primary_order_id)
                    for key, value in call.arguments.items()
                },
            }
            for call in task.expected_calls
        ],
        "transient_failure_rule": task.transient_failures,
        "max_steps": task.max_steps,
    }


def _normalized_policy_state(state: dict[str, Any], primary_order_id: str) -> dict[str, Any]:
    customer_id = state.get("customer_id")
    current_day = state.get("current_day")
    orders = state.get("orders")
    if not isinstance(customer_id, str) or not isinstance(current_day, int):
        raise ValueError("正式任务状态缺少 customer_id/current_day")
    if not isinstance(orders, dict) or primary_order_id not in orders:
        raise ValueError("正式任务状态缺少 primary order")
    primary_order = orders[primary_order_id]
    if not isinstance(primary_order, dict):
        raise ValueError("正式任务 primary order 必须是 object")
    distractors = [
        _normalized_order(order, customer_id, current_day)
        for order_id, order in orders.items()
        if order_id != primary_order_id
    ]
    return {
        "primary_order": _normalized_order(primary_order, customer_id, current_day),
        "distractor_orders": sorted(distractors, key=canonical_json),
    }


def _normalized_order(order: Any, customer_id: str, current_day: int) -> dict[str, Any]:
    if not isinstance(order, dict):
        raise ValueError("正式任务 order 必须是 object")
    refund_deadline = order.get("refund_deadline")
    if not isinstance(refund_deadline, int):
        raise ValueError("正式任务 order 缺少 refund_deadline")
    return {
        "relative_ownership": (
            "customer" if order.get("customer_id") == customer_id else "other_customer"
        ),
        "status": order.get("status"),
        "refund_deadline_offset": refund_deadline - current_day,
        "refund_status": order.get("refund_status"),
    }


def _normalized_argument(key: str, value: Any, primary_order_id: str) -> Any:
    if key != "order_id":
        return value
    return "primary_order" if value == primary_order_id else "other_order"


def _user_request(
    scenario: TaskScenario,
    order_id: str,
    reason: str,
    variant_index: int,
    other_order_id: str = "",
) -> str:
    requests = {
        TaskScenario.LOOKUP_STATUS: (
            f"请查询订单 {order_id} 的当前状态。",
            f"麻烦核实一下 {order_id} 的配送状态。",
        ),
        TaskScenario.REFUND_ELIGIBLE: (
            f"请核实订单 {order_id} 并按 {reason} 办理退款。",
            f"订单 {order_id} 需要因 {reason} 退款，请先检查后处理。",
        ),
        TaskScenario.REFUND_DENIED_WINDOW: (
            f"请检查订单 {order_id} 是否能因 {reason} 退款。",
            f"我想为 {order_id} 申请 {reason} 的退款，请核实。",
        ),
        TaskScenario.REFUND_DENIED_OWNERSHIP: (
            f"请查询订单 {order_id} 并判断 {reason} 退款是否可办。",
            f"麻烦核实 {order_id} 的订单信息和 {reason} 退款请求。",
        ),
        TaskScenario.REFUND_DENIED_DUPLICATE: (
            f"请查看订单 {order_id}，我需要按 {reason} 退款。",
            f"请核验 {order_id} 后处理一笔 {reason} 退款。",
        ),
        TaskScenario.REFUND_RECOVERY: (
            f"请为订单 {order_id} 按 {reason} 办理退款；临时失败时重试一次。",
            f"订单 {order_id} 需因 {reason} 退款，如服务暂时失败请再试一次。",
        ),
    }
    if scenario in requests:
        return requests[scenario][variant_index]
    return _v4_user_request_fallback(scenario, order_id, reason, other_order_id)


def _v4_user_request_fallback(
    scenario: TaskScenario,
    order_id: str,
    reason: str,
    other_order_id: str = "",
) -> str:
    """v4 新增场景的用户请求（固定书面正式口吻）。"""
    if scenario is TaskScenario.CHECK_REFUND_STATUS:
        return f"请查询订单 {order_id} 的退款处理进度。"
    if scenario is TaskScenario.CANCEL_ELIGIBLE:
        return f"请取消订单 {order_id}，原因是 {reason}。"
    if scenario is TaskScenario.CANCEL_DENIED_RECENT:
        return f"请评估订单 {order_id} 是否满足取消条件，告诉我能否取消以及原因。"
    if scenario is TaskScenario.CANCEL_DENIED_IN_USE:
        return f"请查询订单 {order_id} 并判断 {reason} 取消是否可办。"
    if scenario is TaskScenario.REFUND_THEN_CANCEL:
        return f"请先为订单 {order_id} 办理退款，再取消订单 {other_order_id}。"
    if scenario is TaskScenario.RTC_STEPWISE:
        # 辅助任务的请求实体是 RTC 的第二订单 B（复用 cancel_eligible 措辞形状）
        return f"请取消订单 {other_order_id}，原因是 {reason}。"
    if scenario is TaskScenario.CANCEL_RECOVERY:
        return f"请取消订单 {order_id}，原因是 {reason}；临时失败时重试一次。"
    msg = f"不支持的场景: {scenario}"
    raise ValueError(msg)


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# v4 Phase B: 12-scenario task generation
# ---------------------------------------------------------------------------

_V4_SCENARIOS = (
    TaskScenario.LOOKUP_STATUS,
    TaskScenario.REFUND_ELIGIBLE,
    TaskScenario.REFUND_DENIED_WINDOW,
    TaskScenario.REFUND_DENIED_OWNERSHIP,
    TaskScenario.REFUND_DENIED_DUPLICATE,
    TaskScenario.REFUND_RECOVERY,
    TaskScenario.CHECK_REFUND_STATUS,
    TaskScenario.CANCEL_ELIGIBLE,
    TaskScenario.CANCEL_DENIED_RECENT,
    TaskScenario.CANCEL_DENIED_IN_USE,
    TaskScenario.REFUND_THEN_CANCEL,
    TaskScenario.CANCEL_RECOVERY,
)

_V4_CANCEL_REASONS = ("changed_mind", "duplicate_order", "billing_error", "quality_concern")

# CANCEL_* 四场景：R9 Phase B 第四轮（方案甲 family 覆盖）的对象。
_V4_CANCEL_SCENARIOS = frozenset(
    {
        TaskScenario.CANCEL_ELIGIBLE,
        TaskScenario.CANCEL_DENIED_RECENT,
        TaskScenario.CANCEL_DENIED_IN_USE,
        TaskScenario.CANCEL_RECOVERY,
    }
)

# 方案甲（用户 2026-09-04 选项 A）：这些版本上 CANCEL_* 场景 family 池从
# 7 态 × 5 语境扩到 10 态 × 5 语境（state 7–9 使用新增 margin 档 4/6/12，
# 语义上与 state 0–6 不重叠），train family 20 → 35；dev/holdout 配额不变。
# 版本键控保证 `retail_ops_v4_20260822` 的重建路径与冻结时逐位同构
# （版本↔内容双射不破）。
_V4_EXTENDED_CANCEL_VERSIONS = frozenset({"retail_ops_v4_20260904", "retail_ops_v4_20260905"})

# 方案乙（用户 2026-09-04 确认上乙）：这些版本上为 rtc 的每个 train family 派生
# `rtc_stepwise` 辅助 family（同 state/context/reason，gold = 查 B + 取消 B），
# 40 任务只进 train（dev/holdout 无此场景，评测面不变）；train 总量 640。
_V4_STEPWISE_VERSIONS = frozenset({"retail_ops_v4_20260905"})


def _v4_scenario_contract(
    scenario: TaskScenario,
    state_variant: int,
    margin: int,
    reason: str,
) -> tuple[ExpectedDecision, list[dict[str, Any]], dict[str, int], dict[str, Any]]:
    """v4 新增6 场景的合约。原有 6 场景复用 _scenario_contract。"""
    get_order: dict[str, Any] = {"name": "get_order", "arguments": {"order_id": "primary_order"}}
    get_refund_status: dict[str, Any] = {
        "name": "get_refund_status",
        "arguments": {"order_id": "primary_order"},
    }
    cancel: dict[str, Any] = {
        "name": "cancel_order",
        "arguments": {"order_id": "primary_order", "reason": reason},
    }
    cancel_other: dict[str, Any] = {
        "name": "cancel_order",
        "arguments": {"order_id": "other_order", "reason": _V4_CANCEL_REASONS[0]},
    }
    refund: dict[str, Any] = {
        "name": "refund_order",
        "arguments": {"order_id": "primary_order", "reason": reason},
    }

    if scenario is TaskScenario.CHECK_REFUND_STATUS:
        refund_statuses = (
            "processing",
            "completed",
            "denied",
            "pending",
            "none",
            "refunded",
            "processing",
        )
        return (
            ExpectedDecision.INFORM,
            [get_refund_status],
            {},
            {
                "refund_status": refund_statuses[state_variant],
                "refund_deadline": _CURRENT_DAY + margin,
            },
        )
    if scenario is TaskScenario.CANCEL_ELIGIBLE:
        return (
            ExpectedDecision.ALLOW,
            [get_order, cancel],
            {},
            {
                "owner": "customer",
                "status": "pending",
                "refund_deadline": _CURRENT_DAY + margin,
                "refund_status": "none",
            },
        )
    if scenario is TaskScenario.CANCEL_DENIED_RECENT:
        return (
            ExpectedDecision.DENY,
            [get_order],
            {},
            {
                "owner": "customer",
                "status": "pending",
                "refund_deadline": _CURRENT_DAY - margin,
                "refund_status": "none",
            },
        )
    if scenario is TaskScenario.CANCEL_DENIED_IN_USE:
        return (
            ExpectedDecision.DENY,
            [get_order],
            {},
            {
                "owner": "customer",
                "status": "shipped",
                "refund_deadline": _CURRENT_DAY + margin,
                "refund_status": "none",
            },
        )
    get_order_other: dict[str, Any] = {
        "name": "get_order",
        "arguments": {"order_id": "other_order"},
    }
    if scenario is TaskScenario.REFUND_THEN_CANCEL:
        return (
            ExpectedDecision.ALLOW,
            [get_order, refund, get_order_other, cancel_other],
            {},
            {
                "owner": "customer",
                "refund_deadline": _CURRENT_DAY + margin,
                "refund_status": "none",
            },
        )
    if scenario is TaskScenario.RTC_STEPWISE:
        # 方案乙辅助任务：RTC 同一状态的第一段——只「查 B 并取消 B」。
        # policy_state 描述主单 A（与对应 rtc 任务同源，A 在本任务里不被触碰）。
        return (
            ExpectedDecision.ALLOW,
            [get_order_other, cancel_other],
            {},
            {
                "owner": "customer",
                "refund_deadline": _CURRENT_DAY + margin,
                "refund_status": "none",
            },
        )
    if scenario is TaskScenario.CANCEL_RECOVERY:
        return (
            ExpectedDecision.ALLOW,
            [get_order, copy.deepcopy(cancel), copy.deepcopy(cancel)],
            {"cancel_order": 1},
            {
                "owner": "customer",
                "status": "pending",
                "refund_deadline": _CURRENT_DAY + margin,
                "refund_status": "none",
            },
        )
    msg = f"不支持的 v4 场景: {scenario}"
    raise ValueError(msg)


def _v4_scenario_contract_dispatch(
    scenario: TaskScenario,
    state_variant: int,
    margin: int,
    reason: str,
) -> tuple[ExpectedDecision, list[dict[str, Any]], dict[str, int], dict[str, Any]]:
    """根据场景分派到 v1 或 v4 合约。"""
    v4_new = {
        TaskScenario.CHECK_REFUND_STATUS,
        TaskScenario.CANCEL_ELIGIBLE,
        TaskScenario.CANCEL_DENIED_RECENT,
        TaskScenario.CANCEL_DENIED_IN_USE,
        TaskScenario.REFUND_THEN_CANCEL,
        TaskScenario.CANCEL_RECOVERY,
        TaskScenario.RTC_STEPWISE,
    }
    if scenario in v4_new:
        return _v4_scenario_contract(scenario, state_variant, margin, reason)
    return _scenario_contract(scenario, state_variant, margin, reason)


def _v4_user_request(scenario: TaskScenario, order_id: str, reason: str, variant_index: int) -> str:
    """返回 v4 场景的用户请求。新场景使用固定口吻（书面正式）。"""
    if scenario is TaskScenario.CHECK_REFUND_STATUS:
        return f"请查询订单 {order_id} 的退款处理进度。"
    if scenario is TaskScenario.CANCEL_ELIGIBLE:
        return f"请取消订单 {order_id}，原因是 {reason}。"
    if scenario is TaskScenario.CANCEL_DENIED_RECENT:
        return f"请评估订单 {order_id} 是否满足取消条件，告诉我能否取消以及原因。"
    if scenario is TaskScenario.CANCEL_DENIED_IN_USE:
        return f"请查询订单 {order_id} 并判断 {reason} 取消是否可办。"
    if scenario is TaskScenario.REFUND_THEN_CANCEL:
        other = f"O-OTHER{order_id[1:]}" if len(order_id) > 1 else "O-OTHER"
        return f"请先为订单 {order_id} 办理退款，再取消关联订单 {other}。"
    if scenario is TaskScenario.CANCEL_RECOVERY:
        return f"请取消订单 {order_id}，原因是 {reason}；临时失败时重试一次。"
    return _user_request(scenario, order_id, reason, variant_index)


def _v4_family_spec(
    dataset_version: str,
    scenario: TaskScenario,
    scenario_index: int,
    state_variant: int,
    context_variant: int,
) -> dict[str, Any]:
    margin = _V4_TASK_MARGINS[state_variant]
    if scenario in _V4_CANCEL_SCENARIOS:
        idx = (scenario_index + state_variant * 5 + context_variant) % len(_V4_CANCEL_REASONS)
        reason = _V4_CANCEL_REASONS[idx]
    elif scenario is TaskScenario.REFUND_THEN_CANCEL:
        reason = _REASONS[(scenario_index + state_variant * 5 + context_variant) % 4]
    else:
        reason = _REASONS[(scenario_index + state_variant * 5 + context_variant) % 4]
    decision, call_sequence, transient_rule, policy_state = _v4_scenario_contract_dispatch(
        scenario, state_variant, margin, reason
    )
    return {
        "dataset_version": dataset_version,
        "scenario": scenario.value,
        "state_variant": state_variant,
        "context_variant": context_variant,
        "primary_policy_state": policy_state,
        "reason": reason,
        "distractor_count": context_variant,
        "expected_decision": decision.value,
        "required_reads": ["primary_order"],
        "call_sequence": call_sequence,
        "transient_failure_rule": transient_rule,
    }


def build_v4_task_set(dataset_version: str, seed: int) -> FormalTaskSet:
    """Build v4 Phase B task set: 12 scenarios × 35 families × 2 variants = 840 tasks.

    Quotas per scenario: train=20 families (40 tasks), dev=5 families (10 tasks),
    holdout=10 families (20 tasks).

    第四轮扩展（`_V4_EXTENDED_CANCEL_VERSIONS`）：CANCEL_* 4 场景 family 池
    10 态 × 5 语境 = 50，train=35 families（70 tasks），dev/holdout 不变；
    总量 600/120/240。

    方案乙（`_V4_STEPWISE_VERSIONS`）：为 rtc 的每个 train family 派生一个
    `rtc_stepwise` 辅助 family（同 state/context/reason，gold = 查 B + 取消 B），
    40 任务只进 train；总量 640/120/240。
    """
    if not dataset_version:
        raise ValueError("dataset_version 不能为空")

    extended = dataset_version in _V4_EXTENDED_CANCEL_VERSIONS
    stepwise = dataset_version in _V4_STEPWISE_VERSIONS
    records: dict[FormalSplit, list[FormalTaskRecord]] = {split: [] for split in FormalSplit}
    rtc_train_families: list[dict[str, Any]] = []
    rtc_scenario_index = -1
    for scenario_index, scenario in enumerate(_V4_SCENARIOS):
        state_count = 10 if extended and scenario in _V4_CANCEL_SCENARIOS else 7
        train_families = 35 if state_count == 10 else 20
        families = sorted(
            (
                _v4_family_spec(
                    dataset_version, scenario, scenario_index, state_variant, context_variant
                )
                for state_variant in range(state_count)
                for context_variant in range(5)
            ),
            key=lambda family: _sha256({"family": family}),
        )
        for family_index, family in enumerate(families):
            split = (
                FormalSplit.TRAIN
                if family_index < train_families
                else FormalSplit.DEV
                if family_index < train_families + 5
                else FormalSplit.HOLDOUT
            )
            family_fingerprint = _sha256({"family": family})
            for variant_index in range(2):
                task = _materialize_task(
                    dataset_version=dataset_version,
                    seed=seed,
                    split=split,
                    family=family,
                    family_fingerprint=family_fingerprint,
                    variant_index=variant_index,
                )
                records[split].append(FormalTaskRecord.from_task(task, variant_index))
        if scenario is TaskScenario.REFUND_THEN_CANCEL:
            rtc_scenario_index = scenario_index
            rtc_train_families = families[:train_families]
    if stepwise and rtc_train_families:
        # 方案乙：stepwise 块追加在全部场景块之后（行序 = 12 场景块 + stepwise 块，
        # 与 manifest 校验的 expected 序列一致）
        for family in rtc_train_families:
            stepwise_family = _v4_family_spec(
                dataset_version,
                TaskScenario.RTC_STEPWISE,
                rtc_scenario_index,
                int(family["state_variant"]),
                int(family["context_variant"]),
            )
            stepwise_fingerprint = _sha256({"family": stepwise_family})
            for variant_index in range(2):
                task = _materialize_task(
                    dataset_version=dataset_version,
                    seed=seed,
                    split=FormalSplit.TRAIN,
                    family=stepwise_family,
                    family_fingerprint=stepwise_fingerprint,
                    variant_index=variant_index,
                )
                records[FormalSplit.TRAIN].append(FormalTaskRecord.from_task(task, variant_index))

    task_set = FormalTaskSet(
        dataset_version=dataset_version,
        seed=seed,
        train=tuple(records[FormalSplit.TRAIN]),
        dev=tuple(records[FormalSplit.DEV]),
        holdout=tuple(records[FormalSplit.HOLDOUT]),
    )
    task_set.assert_exact_quotas_v4()
    return task_set


# ---------------------------------------------------------------------------
# v5 (B-4): difficulty-stratified rebuild — margin 0 bucket + reason set
# semantics + max_steps 6/7. See `assert_exact_quotas_v5` for the contract.
# ---------------------------------------------------------------------------

_V5_VERSIONS = frozenset({"retail_ops_v5_20260906"})

#: allow 侧 margin 网格：v1 的 7 档 + 判定分界日 0（「7+1 档」）。
_V5_ALLOW_MARGINS = (0, 1, 2, 3, 5, 7, 10, 14)
#: deny 侧网格不变：offset 0 由政策判放行，与 DENY 语义矛盾，永不生成。
_V5_DENY_MARGINS = _MARGINS
#: allow 侧 margin 网格的场景（含 rtc：退款项 A 的 deadline 是任务状态的一部分）。
#: RTC_STEPWISE 与 rtc 同参派生，网格随 rtc（state 0–7）；它不进 margin-0 覆盖
#: 断言（train-only 辅助场景，dev/holdout 无此场景）。
_V5_ALLOW_MARGIN_GRIDS = frozenset(
    {
        TaskScenario.REFUND_ELIGIBLE,
        TaskScenario.REFUND_RECOVERY,
        TaskScenario.REFUND_THEN_CANCEL,
        TaskScenario.RTC_STEPWISE,
    }
)
_V5_ALLOW_MARGIN_SCENARIOS = frozenset(
    {
        TaskScenario.REFUND_ELIGIBLE,
        TaskScenario.REFUND_RECOVERY,
        TaskScenario.REFUND_THEN_CANCEL,
    }
)
#: 状态轴分档的场景（deadline 是装饰性的，难度档 = 状态下标）。
_V5_STATUS_AXIS_SCENARIOS = frozenset(
    {TaskScenario.LOOKUP_STATUS, TaskScenario.CHECK_REFUND_STATUS}
)

#: 口径 A（A-0.2 用户裁定，判分契约）：用户事实 → 可接受理由集合。
#: cancel 类 reason（`_V4_CANCEL_REASONS`）保持精确匹配，不进口径 A。
_V5_REASON_ACCEPTABLE: dict[str, tuple[str, ...]] = {
    "damaged": ("damaged",),
    "wrong_item": ("wrong_item",),
    "not_as_described": ("not_as_described", "damaged"),
    "changed_mind": ("changed_mind",),
}
#: 用户事实从句（自然语言；同一从句跨 allow/deny 场景复用，
#: 打断「措辞 → 结果」伪相关——交接 §4.6 约束 2）。
_V5_REASON_FACTS: dict[str, str] = {
    "damaged": "商品存在破损",
    "wrong_item": "商家发错了货",
    "not_as_described": "商品与页面描述不符",
    "changed_mind": "不想要这件商品了",
}
#: 请求携带退款事实从句的场景。
_V5_FACT_SCENARIOS = frozenset(
    {
        TaskScenario.REFUND_ELIGIBLE,
        TaskScenario.REFUND_DENIED_WINDOW,
        TaskScenario.REFUND_DENIED_OWNERSHIP,
        TaskScenario.REFUND_DENIED_DUPLICATE,
        TaskScenario.REFUND_RECOVERY,
        TaskScenario.REFUND_THEN_CANCEL,
    }
)

#: 每场景 family 配额 (train/dev/holdout)。任务数 = family × 2 variant。
#:
#: 与 B4 提案「每场景 family 35 不变」的偏差（已披露）：「dev/holdout 覆盖全部
#: 难度档」要求 dev family ≥ 档数（7–10），dev=5 在算术上不可能。本表按验收
#: 优先：dev 每档 1 family、holdout 每档 1 family（余量按降档序分配，≥10 档
#: 至多 1 个余量）、train 取余。总量 588/198/246。
_V5_SPLIT_QUOTAS: dict[TaskScenario, tuple[int, int, int]] = {
    TaskScenario.LOOKUP_STATUS: (18, 7, 10),
    TaskScenario.REFUND_ELIGIBLE: (21, 8, 11),
    TaskScenario.REFUND_DENIED_WINDOW: (18, 7, 10),
    TaskScenario.REFUND_DENIED_OWNERSHIP: (18, 7, 10),
    TaskScenario.REFUND_DENIED_DUPLICATE: (18, 7, 10),
    TaskScenario.REFUND_RECOVERY: (21, 8, 11),
    TaskScenario.CHECK_REFUND_STATUS: (18, 7, 10),
    TaskScenario.CANCEL_ELIGIBLE: (30, 10, 10),
    TaskScenario.CANCEL_DENIED_RECENT: (30, 10, 10),
    TaskScenario.CANCEL_DENIED_IN_USE: (30, 10, 10),
    TaskScenario.REFUND_THEN_CANCEL: (21, 8, 11),
    TaskScenario.CANCEL_RECOVERY: (30, 10, 10),
}

#: v5 任务步数预算：默认 6（多步场景 7）——C4 提案 1（B4 §三「6（rtc 7）」）。
_V5_MAX_STEPS_DEFAULT = 6
_V5_MAX_STEPS_MULTI_CALL = 7


def _v5_scenario_margins(scenario: TaskScenario) -> tuple[int, ...]:
    if scenario in _V5_ALLOW_MARGIN_GRIDS:
        return _V5_ALLOW_MARGINS
    if scenario in _V5_STATUS_AXIS_SCENARIOS:
        return _MARGINS
    if scenario in _V4_CANCEL_SCENARIOS:
        return _V4_TASK_MARGINS
    return _V5_DENY_MARGINS


def _v5_scenario_bucket_keys(scenario: TaskScenario) -> tuple[int, ...]:
    """场景的难度档键全集（分层验收与配额推演的共同来源）。

    状态轴场景（lookup/check）的档键是状态的下标 0–6，不是装饰性 deadline 的
    margin 值；其余场景的档键 = margin 值本身。
    """
    if scenario in _V5_STATUS_AXIS_SCENARIOS:
        return tuple(range(7))
    return _v5_scenario_margins(scenario)


def _v5_bucket_key(family: dict[str, Any]) -> int:
    scenario = TaskScenario(str(family["scenario"]))
    if scenario in _V5_STATUS_AXIS_SCENARIOS:
        return int(family["state_variant"])
    deadline = int(family["primary_policy_state"].get("refund_deadline", _CURRENT_DAY))
    return abs(deadline - _CURRENT_DAY)


def _v5_holdout_extras(bucket_keys: tuple[int, ...], extras: int) -> dict[int, int]:
    """holdout 档外余量的确定性分配：降档序，≥10 档至多 1 个余量。

    ≥10 cap 让 margin≥10 占比 train:holdout 落进 [0.8, 1.25]
    （对照现状 refund_denied_window 5.0×）。
    """
    assigned: dict[int, int] = {}
    ge10_extras = 0
    for key in sorted(bucket_keys, reverse=True):
        if extras <= 0:
            break
        if key >= 10 and ge10_extras >= 1:
            continue
        assigned[key] = 1
        extras -= 1
        if key >= 10:
            ge10_extras += 1
    if extras > 0:
        raise ValueError("holdout 余量分配不完（≥10 cap 过紧）")
    return assigned


def _v5_bucket_allocation(
    scenario: TaskScenario,
) -> dict[int, tuple[int, int, int]]:
    """每难度档的 (train, dev, holdout) family 配数。

    dev 每档 1（全档覆盖进入迭代面）、holdout 每档 1 + 降档序余量、
    train 取余；逐档合计等于 `_V5_SPLIT_QUOTAS[scenario]`。
    """
    keys = _v5_scenario_bucket_keys(scenario)
    train_total, dev_total, holdout_total = _V5_SPLIT_QUOTAS[scenario]
    per_bucket = 5  # 每档 context_variant 数（v1 冻结生成器沿袭）
    extras = holdout_total - len(keys)
    holdout_extra = _v5_holdout_extras(keys, extras)
    allocation: dict[int, tuple[int, int, int]] = {}
    train_sum = dev_sum = holdout_sum = 0
    for key in keys:
        dev = 1
        holdout = 1 + holdout_extra.get(key, 0)
        train = per_bucket - dev - holdout
        if train <= 0:
            raise ValueError(f"v5 {scenario.value} 档 {key} 的 train 配数非正")
        allocation[key] = (train, dev, holdout)
        train_sum += train
        dev_sum += dev
        holdout_sum += holdout
    if (train_sum, dev_sum, holdout_sum) != (train_total, dev_total, holdout_total):
        raise ValueError(
            f"v5 {scenario.value} 档级配数合计 "
            f"({train_sum}, {dev_sum}, {holdout_sum}) != {_V5_SPLIT_QUOTAS[scenario]}"
        )
    return allocation


def _v5_reason_for(
    scenario: TaskScenario, scenario_index: int, state_variant: int, context_variant: int
) -> str:
    if scenario in _V4_CANCEL_SCENARIOS:
        return _V4_CANCEL_REASONS[
            (scenario_index + state_variant * 5 + context_variant) % len(_V4_CANCEL_REASONS)
        ]
    return _REASONS[(scenario_index + state_variant * 5 + context_variant) % 4]


def _v5_family_spec(
    dataset_version: str,
    scenario: TaskScenario,
    scenario_index: int,
    state_variant: int,
    context_variant: int,
) -> dict[str, Any]:
    margins = _v5_scenario_margins(scenario)
    margin = margins[state_variant]
    reason = _v5_reason_for(scenario, scenario_index, state_variant, context_variant)
    decision, call_sequence, transient_rule, policy_state = _v4_scenario_contract_dispatch(
        scenario, state_variant, margin, reason
    )
    family: dict[str, Any] = {
        "dataset_version": dataset_version,
        "scenario": scenario.value,
        "state_variant": state_variant,
        "context_variant": context_variant,
        "primary_policy_state": policy_state,
        "reason": reason,
        "distractor_count": context_variant,
        "expected_decision": decision.value,
        "required_reads": ["primary_order"],
        "call_sequence": call_sequence,
        "transient_failure_rule": transient_rule,
    }
    if scenario in _V5_FACT_SCENARIOS:
        family["reason_fact"] = _V5_REASON_FACTS[reason]
        family["acceptable_reasons"] = list(_V5_REASON_ACCEPTABLE[reason])
    return family


def _user_request_for(
    family: dict[str, Any],
    scenario: TaskScenario,
    order_id: str,
    reason: str,
    variant_index: int,
    other_order_id: str = "",
) -> str:
    if "reason_fact" in family:
        return _v5_user_request(
            scenario,
            order_id,
            str(family["reason_fact"]),
            variant_index,
            other_order_id,
        )
    return _user_request(scenario, order_id, reason, variant_index, other_order_id)


def _v5_user_request(
    scenario: TaskScenario,
    order_id: str,
    fact: str,
    variant_index: int,
    other_order_id: str = "",
) -> str:
    """v5 用户请求：陈述**事实**，不出现枚举词（口径 A 的任务侧前提）。"""
    if scenario is TaskScenario.REFUND_ELIGIBLE:
        return (
            f"订单 {order_id} 需要退款：{fact}，请先检查后处理。"
            if variant_index == 0
            else f"我想为 {order_id} 申请退款，{fact}，请核实。"
        )
    if scenario is TaskScenario.REFUND_DENIED_WINDOW:
        return (
            f"请检查订单 {order_id} 是否能办理退款：{fact}。"
            if variant_index == 0
            else f"请核实订单 {order_id}，{fact}，我需要办理退款。"
        )
    if scenario is TaskScenario.REFUND_DENIED_OWNERSHIP:
        return (
            f"请查询订单 {order_id} 并判断能否退款：{fact}。"
            if variant_index == 0
            else f"麻烦核实 {order_id} 的订单信息，{fact}，我想办理退款。"
        )
    if scenario is TaskScenario.REFUND_DENIED_DUPLICATE:
        return (
            f"请查看订单 {order_id}，我需要办理退款：{fact}。"
            if variant_index == 0
            else f"请核验 {order_id} 后处理一笔退款：{fact}。"
        )
    if scenario is TaskScenario.REFUND_RECOVERY:
        return (
            f"请为订单 {order_id} 办理退款：{fact}；临时失败时重试一次。"
            if variant_index == 0
            else f"订单 {order_id} 需要退款：{fact}；如服务暂时失败请再试一次。"
        )
    if scenario is TaskScenario.REFUND_THEN_CANCEL:
        return (
            f"请先为订单 {order_id} 办理退款（{fact}），再取消订单 {other_order_id}。"
            if variant_index == 0
            else f"订单 {order_id} 需要先退款（{fact}），退款完成后请取消订单 {other_order_id}。"
        )
    msg = f"v5 场景不携带退款事实从句: {scenario}"
    raise ValueError(msg)


def build_v5_task_set(dataset_version: str, seed: int) -> FormalTaskSet:
    """Build the v5 difficulty-stratified task set (B-4, `retail_ops_v5_20260906`)."""
    if dataset_version not in _V5_VERSIONS:
        raise ValueError(f"dataset_version 不是 v5 版本: {dataset_version}")
    return _build_v5_stratified_task_set(dataset_version, seed)


_V6_VERSIONS = frozenset({"retail_ops_v6_20260907"})


def build_v6_task_set(dataset_version: str, seed: int) -> FormalTaskSet:
    """Build the v6 task set (`retail_ops_v6_20260907`): v5 结构 + rtc_stepwise 请求修复。

    单变量修复（交接 V6-2、PITFALLS #26）：v5 结构、配额与分层切分逐字节同构，
    唯一差异是 `rtc_stepwise` 辅助任务的请求 reason 与 gold `cancel_other` 同源
    （`_V4_CANCEL_REASONS[0]`），不再从退款枚举轮转。版本键控：v4/v5 的重建路径
    不受影响（它们的请求文本是冻结数据的一部分，缺陷形状由测试负面锁定）。
    """
    if dataset_version not in _V6_VERSIONS:
        raise ValueError(f"dataset_version 不是 v6 版本: {dataset_version}")
    return _build_v5_stratified_task_set(
        dataset_version,
        seed,
        stepwise_request_reason=_V4_CANCEL_REASONS[0],
    )


def _build_v5_stratified_task_set(
    dataset_version: str,
    seed: int,
    *,
    stepwise_request_reason: str | None = None,
) -> FormalTaskSet:
    """分层切分构建主体（v5 与 v6 共用；v6 只覆盖 stepwise 请求 reason）。

    分层切分键：难度档 = margin 值（allow 侧 0–14 八档；deny 侧 1–14 七档；
    状态轴场景 = 状态下标；cancel = v4 十档）。档内按 `sha256(family)` 排序，
    按档级配数（`_v5_bucket_allocation`）确定性分配 train/dev/holdout——
    无人工挑选，消除 v1 哈希切分的 5.0× 难度偏移。
    """

    records: dict[FormalSplit, list[FormalTaskRecord]] = {split: [] for split in FormalSplit}
    rtc_train_specs: list[dict[str, Any]] = []
    rtc_scenario_index = -1
    for scenario_index, scenario in enumerate(_V4_SCENARIOS):
        margins = _v5_scenario_margins(scenario)
        allocation = _v5_bucket_allocation(scenario)
        families_by_bucket: dict[int, list[dict[str, Any]]] = {}
        for state_variant in range(len(margins)):
            for context_variant in range(5):
                family = _v5_family_spec(
                    dataset_version, scenario, scenario_index, state_variant, context_variant
                )
                families_by_bucket.setdefault(_v5_bucket_key(family), []).append(family)
        for bucket_key in sorted(families_by_bucket):
            ordered = sorted(
                families_by_bucket[bucket_key],
                key=lambda family: _sha256({"family": family}),
            )
            train_count, dev_count, _ = allocation[bucket_key]
            assigned: list[tuple[dict[str, Any], FormalSplit]] = []
            assigned.extend((family, FormalSplit.TRAIN) for family in ordered[:train_count])
            assigned.extend(
                (family, FormalSplit.DEV)
                for family in ordered[train_count : train_count + dev_count]
            )
            assigned.extend(
                (family, FormalSplit.HOLDOUT) for family in ordered[train_count + dev_count :]
            )
            for family, split in assigned:
                if scenario is TaskScenario.REFUND_THEN_CANCEL and split is FormalSplit.TRAIN:
                    rtc_train_specs.append(
                        _v5_family_spec(
                            dataset_version,
                            TaskScenario.REFUND_THEN_CANCEL,
                            scenario_index,
                            int(family["state_variant"]),
                            int(family["context_variant"]),
                        )
                    )
                family_fingerprint = _sha256({"family": family})
                for variant_index in range(2):
                    task = _materialize_task(
                        dataset_version=dataset_version,
                        seed=seed,
                        split=split,
                        family=family,
                        family_fingerprint=family_fingerprint,
                        variant_index=variant_index,
                        max_steps=(
                            _V5_MAX_STEPS_MULTI_CALL
                            if scenario in _MULTI_CALL_SCENARIOS
                            else _V5_MAX_STEPS_DEFAULT
                        ),
                    )
                    records[split].append(FormalTaskRecord.from_task(task, variant_index))
        if scenario is TaskScenario.REFUND_THEN_CANCEL:
            rtc_scenario_index = scenario_index

    # 方案乙沿袭：每个 rtc train family 派生一个 rtc_stepwise 辅助 family
    # （同 state/context/reason，gold = 查 B + 取消 B），只进 train。
    # v6 修复：请求 reason 覆写为 gold 同源的 cancel 枚举值（PITFALLS #26），
    # 覆写发生在指纹计算之前，指纹如实反映最终内容。
    for family in rtc_train_specs:
        stepwise_family = _v5_family_spec(
            dataset_version,
            TaskScenario.RTC_STEPWISE,
            rtc_scenario_index,
            int(family["state_variant"]),
            int(family["context_variant"]),
        )
        if stepwise_request_reason is not None:
            stepwise_family["reason"] = stepwise_request_reason
        stepwise_fingerprint = _sha256({"family": stepwise_family})
        for variant_index in range(2):
            task = _materialize_task(
                dataset_version=dataset_version,
                seed=seed,
                split=FormalSplit.TRAIN,
                family=stepwise_family,
                family_fingerprint=stepwise_fingerprint,
                variant_index=variant_index,
                max_steps=_V5_MAX_STEPS_DEFAULT,
            )
            records[FormalSplit.TRAIN].append(FormalTaskRecord.from_task(task, variant_index))

    task_set = FormalTaskSet(
        dataset_version=dataset_version,
        seed=seed,
        train=tuple(records[FormalSplit.TRAIN]),
        dev=tuple(records[FormalSplit.DEV]),
        holdout=tuple(records[FormalSplit.HOLDOUT]),
    )
    task_set.assert_exact_quotas_v5()
    return task_set
