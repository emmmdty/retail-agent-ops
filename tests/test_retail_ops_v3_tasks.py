"""v3 tasks generator tests: parameterized by tool_count for degradation curve.

Tests CPU-only task generation for breakpoints {3, 6, 9, 12, 15}.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from veritool_rl.core.agent.policy import OraclePolicy
from veritool_rl.core.agent.runner import run_episode
from veritool_rl.core.trajectory import TaskSpec
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
from veritool_rl.retail_ops.domain.v3_tasks import (
    _SCENARIO_TOOLS,
    _TOOL_SUBSETS,
    ToolCountTaskSet,
    build_toolcount_task_set,
    common_scenarios,
    scenarios_for,
)


class TestToolcountTaskSet:
    """Task generation for each breakpoint."""

    @pytest.mark.parametrize("tool_count", [3, 6, 9, 12, 15])
    def test_generates_correct_quotas(self, tool_count: int) -> None:
        """每断点每场景 40 train + 10 dev；场景数随该断点可解的场景变化。"""
        ts = build_toolcount_task_set(f"test_v3_{tool_count}", seed=0, tool_count=tool_count)
        assert isinstance(ts, ToolCountTaskSet)
        assert ts.tool_count == tool_count
        ts.assert_quotas()
        expected_scenarios = len(scenarios_for(tool_count))
        assert len(ts.train) == 40 * expected_scenarios
        assert len(ts.dev) == 10 * expected_scenarios

    def test_scenarios_grow_with_the_tool_subset(self) -> None:
        """工具越多，可解的场景越多；共有场景是曲线唯一可比的读数面。"""
        counts = [len(scenarios_for(n)) for n in (3, 6, 9, 12, 15)]
        assert counts == sorted(counts)
        assert counts[0] < counts[-1]
        assert set(common_scenarios()) == set(scenarios_for(3))

    @pytest.mark.parametrize("tool_count", [3, 6, 9, 12, 15])
    def test_every_scenario_has_its_tools_available(self, tool_count: int) -> None:
        """任务集里不得出现所需工具没被呈现的场景。"""
        available = set(_TOOL_SUBSETS[tool_count])
        for scenario in scenarios_for(tool_count):
            assert set(_SCENARIO_TOOLS[scenario]) <= available

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
            "check_refund_status",
            "cancel_eligible",
            "cancel_denied_recent",
            "cancel_denied_in_use",
            "refund_then_cancel",
            "cancel_recovery",
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


BUNDLE_DIR = Path(__file__).resolve().parents[1] / "domains" / "retail_ops" / "v3"


def _env_factory(tool_count: int) -> Callable[[TaskSpec], RetailOpsEnv]:
    bundle = load_bundle(BUNDLE_DIR)
    allowed = _TOOL_SUBSETS[tool_count]

    def factory(task: TaskSpec) -> RetailOpsEnv:
        return RetailOpsEnv(task, bundle, allowed_tools=allowed)

    return factory


class TestTaskSetIsSelfConsistent:
    """gold 调用序列必须在环境里真的可解。

    Oracle 拿不到满分说明评测集自身不自洽——此时任何模型读数都无法归因，
    因为分不清"模型没做到"和"这个任务做不到"。`4b2044e..88ccabb` 三次提交
    把 110/120 改成了 90/120，而当时的结构化测试全部通过，正是因为缺这条。
    """

    @pytest.mark.parametrize("tool_count", [3, 6, 9, 12, 15])
    def test_oracle_solves_every_dev_task(self, tool_count: int) -> None:
        factory = _env_factory(tool_count)
        failures: list[str] = []
        for rec in build_toolcount_task_set("v", seed=0, tool_count=tool_count).dev:
            task = rec.task
            traj = run_episode(task, factory, OraclePolicy(task), seed=0)
            if not traj.success:
                failures.append(f"{task.task_id}({traj.termination.value})")
        assert not failures, f"Oracle 未能完成 {len(failures)} 条 dev 任务: {failures[:5]}"

    @pytest.mark.parametrize("tool_count", [3, 6, 9, 12, 15])
    def test_oracle_never_violates_policy(self, tool_count: int) -> None:
        """gold 序列自己违反政策，等于把政策写进了「正确答案」的反面。"""
        factory = _env_factory(tool_count)
        violations: dict[str, list[str]] = {}
        for rec in build_toolcount_task_set("v", seed=0, tool_count=tool_count).dev:
            task = rec.task
            traj = run_episode(task, factory, OraclePolicy(task), seed=0)
            if traj.violations:
                violations[task.task_id] = list(traj.violations)
        assert not violations, f"gold 序列触发政策违规: {list(violations.items())[:5]}"


class TestToolCountActuallyRestrictsTools:
    """断点必须真的改变模型看到的工具数，否则退化曲线的自变量根本没变。"""

    @pytest.mark.parametrize("tool_count", [3, 6, 9, 12, 15])
    def test_env_exposes_exactly_the_breakpoint_subset(self, tool_count: int) -> None:
        factory = _env_factory(tool_count)
        task = build_toolcount_task_set("v", seed=0, tool_count=tool_count).dev[0].task
        names = tuple(schema.name for schema in factory(task).list_tools())
        assert names == _TOOL_SUBSETS[tool_count]

    def test_tool_outside_the_subset_is_unknown(self) -> None:
        """没展示给模型的工具被调用时必须报 unknown_tool，不能静默执行。"""
        factory = _env_factory(3)
        task = build_toolcount_task_set("v", seed=0, tool_count=3).dev[0].task
        observation = factory(task).execute_tool(
            "cancel_order",
            {"order_id": "X", "reason": "changed_mind"},
        )
        assert observation.ok is False
        assert observation.error_code == "unknown_tool"

    def test_full_bundle_is_the_default(self) -> None:
        """不传 allowed_tools 时行为与既有全部证据逐字节一致。"""
        bundle = load_bundle(BUNDLE_DIR)
        task = build_toolcount_task_set("v", seed=0, tool_count=15).dev[0].task
        names = [schema.name for schema in RetailOpsEnv(task, bundle).list_tools()]
        assert names == [tool.name for tool in bundle.tools]


class TestPolicyGateIsNotTaskData:
    """政策守卫必须由代码强制，任务数据不得关掉它。

    `97ff796` 让 `metadata["skip_reads_gate"]` 能关掉 `cancel_requires_lookup`。
    评测任务是数据，数据能关政策，等于政策不再是判据。
    """

    def test_metadata_cannot_disable_the_cancel_reads_gate(self) -> None:
        bundle = load_bundle(BUNDLE_DIR)
        task = build_toolcount_task_set("v", seed=0, tool_count=15).dev[0].task
        order_id = next(iter(task.initial_state["orders"]))
        tampered = task.model_copy(
            update={"metadata": {**task.metadata, "skip_reads_gate": True}},
            deep=True,
        )
        env = RetailOpsEnv(tampered, bundle)
        observation = env.execute_tool(
            "cancel_order",
            {"order_id": order_id, "reason": "changed_mind"},
        )
        assert observation.error_code == "policy_denied"
        assert env.check_policy() == ["cancel_requires_lookup"]
