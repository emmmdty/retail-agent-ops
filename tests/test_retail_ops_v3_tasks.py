"""v3 tasks generator tests: parameterized by tool_count for degradation curve.

Tests CPU-only task generation for breakpoints {3, 6, 9, 12, 15}.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from veritool_rl.core.agent.policy import OraclePolicy
from veritool_rl.core.agent.runner import run_episode
from veritool_rl.core.trajectory import TaskScenario, TaskSpec
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


class TestDenyScenariosAreActuallyDenied:
    """DENY-by-window 场景的订单状态必须真的会被环境拒绝。

    2026-09-05 full 采集取证发现：`_order` 统一 `_CURRENT_DAY + margin`，
    REFUND_DENIED_WINDOW / CANCEL_DENIED_RECENT 的订单因此**永远在窗口内**——
    教师按环境正确执行退款/取消，被 wrong_final_state 判失败；评测时该场景
    变成送分题（模型「不作为」恰好匹配 target）。与 v1 formal 的
    `_CURRENT_DAY - margin`（LOG：POLICY_BOUNDARY §3）方向相反。
    Oracle 预检抓不到这个矛盾（不作为恰好匹配 target），所以必须有
    「DENY 场景在环境层真的会 deny」的正向断言。
    """

    @pytest.mark.parametrize(
        "scenario",
        [TaskScenario.REFUND_DENIED_WINDOW, TaskScenario.CANCEL_DENIED_RECENT],
    )
    def test_deny_window_scenarios_start_expired(self, scenario: TaskScenario) -> None:
        task_set = build_toolcount_task_set("v", seed=0, tool_count=15)
        tasks = [r.task for r in task_set.train if r.task.scenario is scenario]
        assert tasks, scenario
        current_day = tasks[0].initial_state["current_day"]
        for task in tasks:
            order_id = task.required_reads[0]
            order = task.initial_state["orders"][order_id]
            assert order["refund_deadline"] < current_day, (
                f"{task.task_id}: deadline={order['refund_deadline']} "
                f">= current_day={current_day}——场景叫 DENY、状态却可退/可取消"
            )

    @pytest.mark.parametrize(
        "scenario,tool",
        [
            (TaskScenario.REFUND_DENIED_WINDOW, "refund_order"),
            (TaskScenario.CANCEL_DENIED_RECENT, "cancel_order"),
        ],
    )
    def test_the_environment_actually_denies_them(self, scenario: TaskScenario, tool: str) -> None:
        """环境层正向断言：对这些任务执行被拒动作必须返回 deny（自变量生效性）。"""
        bundle = load_bundle(BUNDLE_DIR)
        task_set = build_toolcount_task_set("v", seed=0, tool_count=15)
        tasks = [r.task for r in task_set.train if r.task.scenario is scenario]
        task = tasks[0]
        env = RetailOpsEnv(task, bundle, allowed_tools=_TOOL_SUBSETS[15])
        order_id = task.required_reads[0]
        reason = "changed_mind"
        observation = env.execute_tool(tool, {"order_id": order_id, "reason": reason})
        payload = observation.model_dump()
        assert payload.get("error_code") not in (None, ""), (
            f"{scenario.value}: 环境{tool}未拒绝——{payload}"
        )


class TestUserRequestCarriesGoldParameters:
    """user_request 必须包含 gold 调用所需的全部非常量参数值。

    2026-09-05 full 采集取证：refund_eligible / refund_recovery /
    refund_then_cancel 的请求不含 reason（gold 的 refund_order/cancel_order
    需要 4 选 1 的 reason），教师（mimo）只能反问用户——行为正确却被判
    wrong_final_state（~50% 失败率，重试白白烧钱拖慢采集）。
    反问在真实产品里是对的；任务判定要求「无需澄清即可执行」，
    那么请求就必须自足。
    """

    def test_every_train_task_request_carries_its_gold_arguments(self) -> None:
        task_set = build_toolcount_task_set("v", seed=0, tool_count=15)
        for record in task_set.train:
            task = record.task
            request = task.user_request
            gold_values: set[str] = set()
            for call in task.expected_calls:
                for value in call.arguments.values():
                    if isinstance(value, str) and not value.isdigit():
                        gold_values.add(value)
            for value in gold_values:
                assert value in request, (
                    f"{task.task_id}: gold 参数 {value!r} 不在请求里：{request!r}"
                )
