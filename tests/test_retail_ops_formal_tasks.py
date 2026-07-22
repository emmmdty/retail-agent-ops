"""RetailOps R2 family-first formal task generation tests."""

from __future__ import annotations

import json
import re
from collections import Counter

from veritool_rl.trajectory import ExpectedDecision, TaskScenario

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


def test_formal_task_set_is_deterministic_and_has_exact_family_quotas() -> None:
    from veritool_rl.retail_ops.formal_tasks import build_formal_task_set

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
    from veritool_rl.retail_ops.formal_tasks import build_formal_task_set

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
    from veritool_rl.retail_ops.formal_tasks import (
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
