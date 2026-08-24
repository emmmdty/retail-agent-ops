"""v3 tasks generator tests: parameterized by tool_count for degradation curve.

Tests CPU-only task generation for breakpoints {3, 6, 9, 12, 15}.
"""

from __future__ import annotations

import pytest

from veritool_rl.retail_ops.domain.v3_tasks import (
    _TOOL_SUBSETS,
    ToolCountTaskSet,
    build_toolcount_task_set,
)


class TestToolcountTaskSet:
    """Task generation for each breakpoint."""

    @pytest.mark.parametrize("tool_count", [3, 6, 9, 12, 15])
    def test_generates_correct_quotas(self, tool_count: int) -> None:
        """Each breakpoint produces 40 train + 10 dev per scenario (6 scenarios)."""
        ts = build_toolcount_task_set(f"test_v3_{tool_count}", seed=0, tool_count=tool_count)
        assert isinstance(ts, ToolCountTaskSet)
        assert ts.tool_count == tool_count
        ts.assert_quotas()
        assert len(ts.train) == 40 * 6  # 240
        assert len(ts.dev) == 10 * 6  # 60

    @pytest.mark.parametrize("tool_count", [3, 6, 9, 12, 15])
    def test_deterministic(self, tool_count: int) -> None:
        """Same inputs produce identical task sets."""
        a = build_toolcount_task_set("v", seed=0, tool_count=tool_count)
        b = build_toolcount_task_set("v", seed=0, tool_count=tool_count)
        assert a.model_dump() == b.model_dump()

    @pytest.mark.parametrize("tool_count", [3, 6, 9, 12, 15])
    def test_content_sha256_deterministic(self, tool_count: int) -> None:
        """Content SHA-256 is stable across runs."""
        a = build_toolcount_task_set("v", seed=0, tool_count=tool_count)
        b = build_toolcount_task_set("v", seed=0, tool_count=tool_count)
        for rec_a, rec_b in zip(a.train, b.train, strict=True):
            assert rec_a.content_sha256 == rec_b.content_sha256

    @pytest.mark.parametrize("tool_count", [3, 6, 9, 12, 15])
    def test_tool_subset_is_prefix(self, tool_count: int) -> None:
        """Each breakpoint uses exactly the first N tools from the v3 bundle."""
        expected = _TOOL_SUBSETS[tool_count]
        assert len(expected) == tool_count
        # The first 3 tools are always the same
        if tool_count > 3:
            assert expected[:3] == _TOOL_SUBSETS[3]

    def test_invalid_tool_count_raises(self) -> None:
        """tool_count must be in {3, 6, 9, 12, 15}."""
        with pytest.raises(ValueError, match="tool_count"):
            build_toolcount_task_set("v", seed=0, tool_count=5)

    def test_empty_dataset_version_raises(self) -> None:
        with pytest.raises(ValueError, match="dataset_version"):
            build_toolcount_task_set("", seed=0, tool_count=3)

    @pytest.mark.parametrize("tool_count", [3, 6, 9, 12, 15])
    def test_task_ids_are_unique(self, tool_count: int) -> None:
        ts = build_toolcount_task_set("v", seed=0, tool_count=tool_count)
        all_ids = [r.task.task_id for r in ts.train] + [r.task.task_id for r in ts.dev]
        assert len(all_ids) == len(set(all_ids))

    @pytest.mark.parametrize("tool_count", [3, 6, 9, 12, 15])
    def test_all_tasks_have_valid_scenarios(self, tool_count: int) -> None:
        ts = build_toolcount_task_set("v", seed=0, tool_count=tool_count)
        valid = {
            "lookup_status",
            "refund_eligible",
            "refund_denied_window",
            "refund_denied_ownership",
            "refund_denied_duplicate",
            "refund_recovery",
        }
        for rec in ts.train + ts.dev:
            assert rec.task.scenario.value in valid

    @pytest.mark.parametrize("tool_count", [3, 6, 9, 12, 15])
    def test_split_field_matches(self, tool_count: int) -> None:
        ts = build_toolcount_task_set("v", seed=0, tool_count=tool_count)
        for rec in ts.train:
            assert rec.task.split == "train"
        for rec in ts.dev:
            assert rec.task.split == "dev"

    def test_v3_subset_includes_v1_tools(self) -> None:
        """The first 3 tools must match v1 exactly."""
        assert _TOOL_SUBSETS[3] == ("get_order", "refund_order", "get_store_hours")

    def test_v15_subset_has_all_expected_tools(self) -> None:
        assert len(_TOOL_SUBSETS[15]) == 15
        # First 3 = v1
        assert _TOOL_SUBSETS[15][:3] == _TOOL_SUBSETS[3]
