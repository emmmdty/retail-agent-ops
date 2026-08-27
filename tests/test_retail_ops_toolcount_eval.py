"""工具数退化曲线的评测装置测试。

这些测试守的是 LOG-20260827-01 那一类缺陷：装置本身失效，而读数照样产出。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from veritool_rl.core.agent.policy import OraclePolicy, PolicyOutput
from veritool_rl.core.envs.base import ToolSchema
from veritool_rl.core.trajectory import TaskSpec, ToolCall
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
from veritool_rl.retail_ops.domain.v3_tasks import (
    _TOOL_SUBSETS,
    build_toolcount_task_set,
    sample_distribution,
    stratified_sample,
)
from veritool_rl.retail_ops.evaluate.toolcount_eval import (
    PreflightError,
    evaluate_tasks,
    preflight_breakpoint,
    score_tool_selection,
    summarise,
)

BUNDLE_DIR = Path(__file__).resolve().parents[1] / "domains" / "retail_ops" / "v3"


def _factory(tool_count: int):
    bundle = load_bundle(BUNDLE_DIR)
    allowed = _TOOL_SUBSETS[tool_count]

    def make(task: TaskSpec) -> RetailOpsEnv:
        return RetailOpsEnv(task, bundle, allowed_tools=allowed)

    return make


def _dev_tasks(tool_count: int, per_scenario: int | None = None) -> list[TaskSpec]:
    records = build_toolcount_task_set("v", seed=0, tool_count=tool_count).dev
    if per_scenario is not None:
        records = stratified_sample(records, per_scenario)
    return [record.task for record in records]


class TestStratifiedSample:
    """小样本与大样本的类型/难度分布必须可核对。"""

    @pytest.mark.parametrize("tool_count", [3, 6, 9, 12, 15])
    @pytest.mark.parametrize("per_scenario", [1, 2, 5])
    def test_scenario_proportions_are_exactly_preserved(
        self, tool_count: int, per_scenario: int
    ) -> None:
        full = build_toolcount_task_set("v", seed=0, tool_count=tool_count).dev
        sample = stratified_sample(full, per_scenario)
        full_counts = {name: len(hist) for name, hist in sample_distribution(full).items()}
        sample_counts = {
            scenario: sum(1 for r in sample if r.task.scenario.value == scenario)
            for scenario in full_counts
        }
        assert set(sample_counts) == set(full_counts)
        assert set(sample_counts.values()) == {per_scenario}

    @pytest.mark.parametrize("per_scenario", [2, 3, 5])
    @pytest.mark.parametrize("split", ["train", "dev"])
    def test_both_difficulty_extremes_are_always_sampled(
        self, per_scenario: int, split: str
    ) -> None:
        """最易与最难两档必须在样本里，否则小样本只测了中间难度。"""
        full = build_toolcount_task_set("v", seed=0, tool_count=15).records(split)
        sample = stratified_sample(full, per_scenario)
        full_hist = sample_distribution(full)
        for scenario, hist in sample_distribution(sample).items():
            margins = {int(m) for m in hist}
            reference = {int(m) for m in full_hist[scenario]}
            assert min(margins) == min(reference), scenario
            assert max(margins) == max(reference), scenario

    @pytest.mark.parametrize("tool_count", [3, 15])
    def test_sampling_everything_returns_the_full_set(self, tool_count: int) -> None:
        """抽满时必须逐条等于全量——这条把「小样本是大样本的子集」钉死。"""
        full = build_toolcount_task_set("v", seed=0, tool_count=tool_count).dev
        sample = stratified_sample(full, 10)
        assert sorted(r.task.task_id for r in sample) == sorted(r.task.task_id for r in full)

    def test_the_sample_is_a_subset_of_the_full_set(self) -> None:
        full = build_toolcount_task_set("v", seed=0, tool_count=15).dev
        sample = stratified_sample(full, 3)
        full_ids = {record.task.task_id for record in full}
        assert {record.task.task_id for record in sample} <= full_ids

    def test_sampling_is_deterministic(self) -> None:
        full = build_toolcount_task_set("v", seed=0, tool_count=15).dev
        first = [r.task.task_id for r in stratified_sample(full, 3)]
        second = [r.task.task_id for r in stratified_sample(full, 3)]
        assert first == second

    def test_asking_for_more_than_exists_raises(self) -> None:
        full = build_toolcount_task_set("v", seed=0, tool_count=15).dev
        with pytest.raises(ValueError, match="取不出"):
            stratified_sample(full, 11)

    def test_zero_per_scenario_raises(self) -> None:
        full = build_toolcount_task_set("v", seed=0, tool_count=15).dev
        with pytest.raises(ValueError, match="per_scenario"):
            stratified_sample(full, 0)


class TestPreflight:
    """跑 GPU 之前必须挡住的两类装置故障。"""

    @pytest.mark.parametrize("tool_count", [3, 6, 9, 12, 15])
    def test_a_correct_breakpoint_passes(self, tool_count: int) -> None:
        preflight_breakpoint(
            _dev_tasks(tool_count, per_scenario=2),
            _factory(tool_count),
            _TOOL_SUBSETS[tool_count],
        )

    def test_an_environment_that_ignores_the_breakpoint_is_rejected(self) -> None:
        """自变量没生效——2026-08-24 那轮曲线的成因，必须硬失败。"""
        bundle = load_bundle(BUNDLE_DIR)

        def full_bundle_factory(task: TaskSpec) -> RetailOpsEnv:
            return RetailOpsEnv(task, bundle)  # 忘了传 allowed_tools

        with pytest.raises(PreflightError, match="自变量没有生效"):
            preflight_breakpoint(
                _dev_tasks(6, per_scenario=1),
                full_bundle_factory,
                _TOOL_SUBSETS[6],
            )

    def test_an_unsolvable_task_set_is_rejected(self) -> None:
        """gold 序列走不通时不能开跑——读数无法归因。"""
        tasks = _dev_tasks(15, per_scenario=1)
        broken = [
            tasks[0].model_copy(
                update={"expected_calls": [ToolCall(name="get_store_hours", arguments={})]},
                deep=True,
            )
        ]
        with pytest.raises(PreflightError, match=r"走不通|不自洽"):
            preflight_breakpoint(broken, _factory(15), _TOOL_SUBSETS[15])

    def test_an_empty_task_set_is_rejected(self) -> None:
        with pytest.raises(PreflightError, match="为空"):
            preflight_breakpoint([], _factory(15), _TOOL_SUBSETS[15])


class TestToolSelectionScore:
    """指标必须对位置敏感，并惩罚多余调用。"""

    def _run(self, task: TaskSpec, tool_count: int):
        from veritool_rl.core.agent.runner import run_episode

        return run_episode(task, _factory(tool_count), OraclePolicy(task), seed=0)

    def test_oracle_scores_one(self) -> None:
        task = _dev_tasks(15, per_scenario=1)[1]
        score = score_tool_selection(task, self._run(task, 15), _TOOL_SUBSETS[15])
        assert score.accuracy == 1.0
        assert score.distractor_calls == 0
        assert score.unknown_tool_calls == 0

    def test_calling_every_tool_does_not_score_one(self) -> None:
        """旧实现的成员判定会给这种行为满分。"""
        task = _dev_tasks(15, per_scenario=1)[1]
        trajectory = self._run(task, 15)
        padded = trajectory.model_copy(deep=True)
        extra = [
            step.model_copy(
                update={"tool_call": ToolCall(name=name, arguments={})},
                deep=True,
            )
            for name, step in zip(_TOOL_SUBSETS[15], [padded.steps[0]] * 15, strict=False)
            if name not in {call.name for call in task.expected_calls}
        ]
        padded = padded.model_copy(update={"steps": [*padded.steps, *extra]}, deep=True)
        score = score_tool_selection(task, padded, _TOOL_SUBSETS[15])
        assert score.accuracy < 1.0
        assert score.distractor_calls == len(extra)

    def test_a_tool_outside_the_subset_is_counted_as_unknown(self) -> None:
        task = _dev_tasks(3, per_scenario=1)[0]
        trajectory = self._run(task, 3)
        tampered = trajectory.model_copy(
            update={
                "steps": [
                    *trajectory.steps,
                    trajectory.steps[0].model_copy(
                        update={"tool_call": ToolCall(name="cancel_order", arguments={})},
                        deep=True,
                    ),
                ]
            },
            deep=True,
        )
        score = score_tool_selection(task, tampered, _TOOL_SUBSETS[3])
        assert score.unknown_tool_calls == 1


class TestSummarise:
    def test_infrastructure_errors_do_not_become_model_failures(self) -> None:
        """OOM 摊进成功率会让环境故障看起来像模型退化。"""

        class Exploding:
            def respond(self, messages: list[dict], tools: list[ToolSchema]) -> PolicyOutput:
                del messages, tools
                raise RuntimeError("CUDA out of memory")

        tasks = _dev_tasks(15, per_scenario=1)
        metrics, outcomes = evaluate_tasks(
            tasks,
            _factory(15),
            lambda _task: Exploding(),
            _TOOL_SUBSETS[15],
            tool_count=15,
        )
        assert metrics.infrastructure_error_count == len(tasks)
        assert metrics.task_count == 0
        assert all(o.infrastructure_error is not None for o in outcomes)

    def test_oracle_run_summarises_to_a_perfect_breakpoint(self) -> None:
        tasks = _dev_tasks(15, per_scenario=2)
        metrics, _ = evaluate_tasks(
            tasks,
            _factory(15),
            OraclePolicy,
            _TOOL_SUBSETS[15],
            tool_count=15,
        )
        assert metrics.task_success == 1.0
        assert metrics.policy_violation_count == 0
        assert metrics.infrastructure_error_count == 0
        assert metrics.tool_selection_accuracy == 1.0
        assert metrics.distractor_call_rate == 0.0
        assert metrics.tools_presented == _TOOL_SUBSETS[15]

    def test_empty_outcomes_do_not_divide_by_zero(self) -> None:
        metrics = summarise(15, _TOOL_SUBSETS[15], [])
        assert metrics.task_success == 0.0
        assert metrics.distractor_call_rate == 0.0
