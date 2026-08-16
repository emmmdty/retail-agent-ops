"""RetailOps R2 family-first formal task generation tests."""

from __future__ import annotations

import copy
import json
import re
from collections import Counter
from pathlib import Path

import pytest

from veritool_rl.core.trajectory import ExpectedDecision, TaskScenario, TaskSpec

DATASET_VERSION = "retail_ops_v1_r2_20260722"
_SPLITS = ("train", "dev", "holdout")
_FINGERPRINT_FIELDS = (
    "task_fingerprint",
    "family_fingerprint",
    "content_fingerprint",
    "source_fingerprint",
    "derivation_fingerprint",
)


def _canonical_dump(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _task_with_state_change(
    task: TaskSpec,
    *,
    initial_updates: dict[str, object] | None = None,
    target_updates: dict[str, object] | None = None,
) -> TaskSpec:
    payload = copy.deepcopy(task.model_dump(mode="python"))
    order_id = task.metadata["order_id"]
    if initial_updates:
        payload["initial_state"]["orders"][order_id].update(initial_updates)
    if target_updates:
        payload["target_state"]["orders"][order_id].update(target_updates)
    return TaskSpec.model_validate(payload)


def test_formal_task_set_is_deterministic_and_has_exact_family_quotas() -> None:
    from veritool_rl.retail_ops.domain.formal_tasks import build_formal_task_set

    first = build_formal_task_set(DATASET_VERSION, seed=0)
    second = build_formal_task_set(DATASET_VERSION, seed=0)

    assert _canonical_dump(first.model_dump(mode="json")) == _canonical_dump(
        second.model_dump(mode="json")
    )
    first.assert_exact_quotas()
    assert {split: len(first.records(split)) for split in _SPLITS} == {
        "train": 240,
        "dev": 60,
        "holdout": 120,
    }
    for split, expected_count in (("train", 40), ("dev", 10), ("holdout", 20)):
        records = first.records(split)
        assert len(records) == expected_count * 6
        assert Counter(record.task.scenario.value for record in records) == {
            "lookup_status": expected_count,
            "refund_eligible": expected_count,
            "refund_denied_window": expected_count,
            "refund_denied_ownership": expected_count,
            "refund_denied_duplicate": expected_count,
            "refund_recovery": expected_count,
        }
        family_counts = Counter(record.family_fingerprint for record in records)
        assert set(family_counts.values()) == {2}
        assert all(record.task.split == split for record in records)


def test_formal_task_fingerprints_are_stable_and_split_isolated() -> None:
    from veritool_rl.retail_ops.domain.formal_tasks import build_formal_task_set

    task_set = build_formal_task_set(DATASET_VERSION, seed=0)
    first_family = next(record.family_fingerprint for record in task_set.records("train"))
    variants = tuple(
        record for record in task_set.records("train") if record.family_fingerprint == first_family
    )

    assert len(variants) == 2
    assert {record.variant_index for record in variants} == {0, 1}
    assert variants[0].family_fingerprint == variants[1].family_fingerprint
    assert variants[0].source_fingerprint == variants[1].source_fingerprint
    assert variants[0].derivation_fingerprint == variants[1].derivation_fingerprint
    assert variants[0].task_fingerprint != variants[1].task_fingerprint
    assert variants[0].content_fingerprint != variants[1].content_fingerprint

    fingerprint_pattern = re.compile(r"[0-9a-f]{64}\Z")
    for field in _FINGERPRINT_FIELDS:
        split_values = {
            split: {getattr(record, field) for record in task_set.records(split)}
            for split in _SPLITS
        }
        assert all(
            fingerprint_pattern.fullmatch(value)
            for values in split_values.values()
            for value in values
        )
        assert split_values["train"].isdisjoint(split_values["dev"])
        assert split_values["train"].isdisjoint(split_values["holdout"])
        assert split_values["dev"].isdisjoint(split_values["holdout"])


def test_fingerprints_distinguish_policy_and_surface_changes() -> None:
    from veritool_rl.retail_ops.domain.formal_tasks import (
        FormalTaskRecord,
        build_formal_task_set,
    )

    record = next(
        record
        for record in build_formal_task_set(DATASET_VERSION, seed=0).records("train")
        if record.task.scenario is TaskScenario.REFUND_ELIGIBLE
    )
    policy_changed = FormalTaskRecord.from_task(
        record.task.model_copy(update={"expected_decision": ExpectedDecision.DENY}),
        variant_index=record.variant_index,
    )
    surface_changed = FormalTaskRecord.from_task(
        record.task.model_copy(update={"user_request": "请用另一种措辞处理此订单。"}),
        variant_index=record.variant_index,
    )
    identity_changed = FormalTaskRecord.from_task(
        record.task.model_copy(update={"task_id": "replacement-task-id", "split": "dev"}),
        variant_index=record.variant_index,
    )

    assert policy_changed.task_fingerprint != record.task_fingerprint
    assert policy_changed.derivation_fingerprint != record.derivation_fingerprint
    assert surface_changed.family_fingerprint == record.family_fingerprint
    assert surface_changed.derivation_fingerprint == record.derivation_fingerprint
    assert surface_changed.content_fingerprint != record.content_fingerprint
    assert identity_changed.content_fingerprint == record.content_fingerprint
    assert identity_changed.derivation_fingerprint == record.derivation_fingerprint


def test_derivation_fingerprint_tracks_real_policy_and_answer_state() -> None:
    from veritool_rl.retail_ops.domain.formal_tasks import (
        FormalTaskRecord,
        build_formal_task_set,
    )

    records = build_formal_task_set(DATASET_VERSION, seed=0).records("train")
    eligible = next(
        record for record in records if record.task.scenario is TaskScenario.REFUND_ELIGIBLE
    )
    lookup = next(
        record
        for record in records
        if record.task.scenario is TaskScenario.LOOKUP_STATUS
        and record.task.initial_state["orders"][record.task.metadata["order_id"]]["status"]
        != "delivered"
    )
    current_day = eligible.task.initial_state["current_day"]
    changed_tasks = (
        _task_with_state_change(
            eligible.task,
            initial_updates={"refund_deadline": current_day - 1},
        ),
        _task_with_state_change(
            eligible.task,
            initial_updates={"customer_id": "C-UNRELATED"},
        ),
        _task_with_state_change(
            eligible.task,
            initial_updates={"refund_status": "refunded"},
        ),
        _task_with_state_change(
            lookup.task,
            initial_updates={"status": "delivered"},
        ),
        _task_with_state_change(
            eligible.task,
            target_updates={"refund_status": "none"},
        ),
    )

    for task in changed_tasks[:3]:
        changed = FormalTaskRecord.from_task(task, eligible.variant_index)
        assert changed.derivation_fingerprint != eligible.derivation_fingerprint
    lookup_changed = FormalTaskRecord.from_task(changed_tasks[3], lookup.variant_index)
    assert lookup_changed.derivation_fingerprint != lookup.derivation_fingerprint
    target_changed = FormalTaskRecord.from_task(changed_tasks[4], eligible.variant_index)
    assert target_changed.derivation_fingerprint != eligible.derivation_fingerprint

    metadata_payload = copy.deepcopy(eligible.task.model_dump(mode="python"))
    metadata_payload["metadata"]["formal_family"]["primary_policy_state"] = {
        "owner": "other_customer",
        "refund_deadline": -999,
        "refund_status": "refunded",
    }
    metadata_changed = FormalTaskRecord.from_task(
        TaskSpec.model_validate(metadata_payload), eligible.variant_index
    )
    assert metadata_changed.derivation_fingerprint == eligible.derivation_fingerprint


def test_exact_quotas_reject_duplicate_variants_and_fingerprint_tampering() -> None:
    from veritool_rl.retail_ops.domain.formal_tasks import build_formal_task_set

    task_set = build_formal_task_set(DATASET_VERSION, seed=0)
    train = list(task_set.train)
    first_family = train[0].family_fingerprint
    family_positions = [
        index for index, record in enumerate(train) if record.family_fingerprint == first_family
    ]
    duplicate_train = train.copy()
    duplicate_train[family_positions[1]] = train[family_positions[0]].model_copy(deep=True)
    duplicate_set = task_set.model_copy(update={"train": tuple(duplicate_train)})

    with pytest.raises(ValueError, match="variant"):
        duplicate_set.assert_exact_quotas()

    tampered_train = train.copy()
    replacement = "0" * 64 if train[0].task_fingerprint != "0" * 64 else "1" * 64
    tampered_train[0] = train[0].model_copy(update={"task_fingerprint": replacement})
    tampered_set = task_set.model_copy(update={"train": tuple(tampered_train)})

    with pytest.raises(ValueError, match="指纹"):
        tampered_set.assert_exact_quotas()


def test_formal_catalog_matches_every_frozen_family_axis() -> None:
    from veritool_rl.retail_ops.domain.bundle import load_bundle
    from veritool_rl.retail_ops.domain.formal_tasks import _REASONS, build_formal_task_set

    scenarios = (
        TaskScenario.LOOKUP_STATUS,
        TaskScenario.REFUND_ELIGIBLE,
        TaskScenario.REFUND_DENIED_WINDOW,
        TaskScenario.REFUND_DENIED_OWNERSHIP,
        TaskScenario.REFUND_DENIED_DUPLICATE,
        TaskScenario.REFUND_RECOVERY,
    )
    lookup_statuses = (
        "pending",
        "processing",
        "shipped",
        "delivered",
        "cancelled",
        "returned",
        "refunded",
    )
    margins = (1, 2, 3, 5, 7, 10, 14)
    expected_calls = {
        TaskScenario.LOOKUP_STATUS: ["get_order"],
        TaskScenario.REFUND_ELIGIBLE: ["get_order", "refund_order"],
        TaskScenario.REFUND_DENIED_WINDOW: ["get_order"],
        TaskScenario.REFUND_DENIED_OWNERSHIP: ["get_order"],
        TaskScenario.REFUND_DENIED_DUPLICATE: ["get_order"],
        TaskScenario.REFUND_RECOVERY: [
            "get_order",
            "refund_order",
            "refund_order",
        ],
    }
    bundle = load_bundle(Path("domains/retail_ops/v1"))
    assert tuple(bundle.policies.refund_reasons) == _REASONS

    task_set = build_formal_task_set(DATASET_VERSION, seed=0)
    representatives = [
        record
        for split in _SPLITS
        for record in task_set.records(split)
        if record.variant_index == 0
    ]
    for scenario_index, scenario in enumerate(scenarios):
        scenario_records = [
            record for record in representatives if record.task.scenario is scenario
        ]
        assert len(scenario_records) == 35
        assert Counter(
            record.task.metadata["formal_family"]["state_variant"] for record in scenario_records
        ) == dict.fromkeys(range(7), 5)
        assert Counter(
            record.task.metadata["formal_family"]["context_variant"] for record in scenario_records
        ) == dict.fromkeys(range(5), 7)

        reason_counts: Counter[str] = Counter()
        for record in scenario_records:
            task = record.task
            family = task.metadata["formal_family"]
            state_variant = family["state_variant"]
            context_variant = family["context_variant"]
            order_id = task.metadata["order_id"]
            order = task.initial_state["orders"][order_id]
            distractor_count = len(task.initial_state["orders"]) - 1
            reason = _REASONS[(scenario_index + state_variant * 5 + context_variant) % 4]

            assert distractor_count == context_variant
            assert family["distractor_count"] == context_variant
            assert task.metadata["reason"] == reason
            assert [call.name for call in task.expected_calls] == expected_calls[scenario]
            assert all(call.name != "get_store_hours" for call in task.expected_calls)
            assert task.expected_calls[0].arguments == {"order_id": order_id}
            assert all(
                call.arguments == {"order_id": order_id, "reason": reason}
                for call in task.expected_calls[1:]
            )
            assert task.transient_failures == (
                {"refund_order": 1} if scenario is TaskScenario.REFUND_RECOVERY else {}
            )
            reason_counts[reason] += 1

            if scenario is TaskScenario.LOOKUP_STATUS:
                assert order["status"] == lookup_statuses[state_variant]
            else:
                actual_margin = order["refund_deadline"] - task.initial_state["current_day"]
                expected_margin = (
                    -margins[state_variant]
                    if scenario is TaskScenario.REFUND_DENIED_WINDOW
                    else margins[state_variant]
                )
                assert actual_margin == expected_margin

            if scenario is TaskScenario.REFUND_DENIED_WINDOW:
                assert order["customer_id"] == task.initial_state["customer_id"]
                assert order["refund_status"] == "none"
            elif scenario is TaskScenario.REFUND_DENIED_OWNERSHIP:
                assert order["customer_id"] != task.initial_state["customer_id"]
                assert order["refund_status"] == "none"
            elif scenario is TaskScenario.REFUND_DENIED_DUPLICATE:
                assert order["customer_id"] == task.initial_state["customer_id"]
                assert order["refund_status"] == "refunded"

            if scenario in {
                TaskScenario.REFUND_DENIED_WINDOW,
                TaskScenario.REFUND_DENIED_OWNERSHIP,
                TaskScenario.REFUND_DENIED_DUPLICATE,
            }:
                assert task.expected_decision is ExpectedDecision.DENY
                assert task.target_state == task.initial_state

        assert set(reason_counts) == set(_REASONS)
        assert set(reason_counts.values()) == {8, 9}


def test_all_formal_tasks_execute_in_the_frozen_environment() -> None:
    from veritool_rl.retail_ops.domain.bundle import load_bundle
    from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
    from veritool_rl.retail_ops.domain.formal_tasks import build_formal_task_set

    bundle = load_bundle(Path("domains/retail_ops/v1"))
    task_set = build_formal_task_set(DATASET_VERSION, seed=0)
    denied_scenarios = {
        TaskScenario.REFUND_DENIED_WINDOW,
        TaskScenario.REFUND_DENIED_OWNERSHIP,
        TaskScenario.REFUND_DENIED_DUPLICATE,
    }

    for split in _SPLITS:
        for record in task_set.records(split):
            env = RetailOpsEnv(record.task, bundle)
            initial_state = env.get_state()
            for call in record.task.expected_calls:
                env.execute_tool(call.name, call.arguments)
            if record.task.expected_decision in {
                ExpectedDecision.INFORM,
                ExpectedDecision.DENY,
            }:
                env.record_final_response("已完成核验。")

            assert env.verify_final_state() == 1.0
            assert env.check_policy() == []
            if record.task.scenario in denied_scenarios:
                assert env.get_state() == initial_state
