"""工具数退化曲线的评测装置：自检门 + 指标。

这个模块存在的理由是 LOG-20260827-01：2026-08-24 那轮曲线之所以「平坦」，
是因为自变量从未生效，而当时没有任何东西检查这件事。这里把三件事做成代码：

1. **跑 GPU 之前先证明装置是对的**（`preflight_breakpoint`）——Oracle 解不开的
   任务集、没真的限制住工具的环境，一律在花掉第一分钟 GPU 之前硬失败；
2. **指标对位置敏感**（`score_tool_selection`）——旧实现是「gold 工具名出现在
   轨迹任意位置就算对」，一个把 15 个工具全调一遍的模型能拿满分；
3. **区分模型失败与基础设施失败**（`EpisodeOutcome.infrastructure_error`）——
   旧实现把 CUDA OOM 之类的异常记成 `success=False`，读报告的人无从分辨。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from veritool_rl.core.agent.policy import OraclePolicy, Policy
from veritool_rl.core.agent.runner import run_episode
from veritool_rl.core.envs.base import ToolEnv
from veritool_rl.core.trajectory import TaskSpec, Trajectory

EnvFactory = Callable[[TaskSpec], ToolEnv]


class PreflightError(RuntimeError):
    """装置自检失败。抛出时**不得**继续消耗 GPU / API 预算。"""


@dataclass(frozen=True)
class ToolSelectionScore:
    """一条 episode 上的工具选择读数。"""

    matched: int
    compared: int
    #: 调用了没被呈现给模型的工具（环境按 `unknown_tool` 拒绝）
    unknown_tool_calls: int
    #: 调用了呈现了、但这条任务的 gold 序列里用不到的工具
    distractor_calls: int
    #: 参数不合 schema
    invalid_calls: int

    @property
    def accuracy(self) -> float:
        return self.matched / self.compared if self.compared else 1.0


def score_tool_selection(
    task: TaskSpec,
    trajectory: Trajectory,
    presented_tools: Sequence[str],
) -> ToolSelectionScore:
    """逐位置比较实际调用序列与 gold 调用序列。

    `accuracy = 逐位命中数 / max(len(gold), len(actual))`。分母取两者较大值，
    因此**漏调用和多调用同样扣分**——这正是旧的成员判定漏掉的两种失败。

    `distractor_calls` 才是这个实验真正想量的东西：随着呈现的工具变多，
    模型是否更容易伸手去碰这条任务用不到的工具。
    """
    gold = [call.name for call in task.expected_calls]
    actual = [step.tool_call.name for step in trajectory.steps if step.tool_call is not None]
    compared = max(len(gold), len(actual))
    matched = sum(1 for a, b in zip(gold, actual, strict=False) if a == b)

    presented = set(presented_tools)
    needed = set(gold)
    unknown = 0
    distractor = 0
    invalid = 0
    for step in trajectory.steps:
        call = step.tool_call
        if call is None:
            continue
        if call.name not in presented:
            unknown += 1
        elif call.name not in needed:
            distractor += 1
        observation = step.observation
        if observation is not None and observation.error_code == "invalid_arguments":
            invalid += 1
    return ToolSelectionScore(
        matched=matched,
        compared=compared,
        unknown_tool_calls=unknown,
        distractor_calls=distractor,
        invalid_calls=invalid,
    )


@dataclass
class EpisodeOutcome:
    task_id: str
    scenario: str
    success: bool
    violations: list[str]
    score: ToolSelectionScore | None
    #: 非 None 表示这条 episode **没有产生有效读数**（后端异常、OOM 等）
    infrastructure_error: str | None = None


@dataclass
class BreakpointMetrics:
    tool_count: int
    tools_presented: tuple[str, ...]
    task_count: int
    scenarios: tuple[str, ...]
    task_success: float
    policy_violation_count: int
    invalid_call_count: int
    unknown_tool_call_count: int
    distractor_call_count: int
    distractor_call_rate: float
    tool_selection_accuracy: float
    episodes_with_a_valid_call: int
    infrastructure_error_count: int
    per_scenario_success: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "tool_count": self.tool_count,
            "tools_presented": list(self.tools_presented),
            "task_count": self.task_count,
            "scenarios": list(self.scenarios),
            "task_success": self.task_success,
            "policy_violation_count": self.policy_violation_count,
            "invalid_call_count": self.invalid_call_count,
            "unknown_tool_call_count": self.unknown_tool_call_count,
            "distractor_call_count": self.distractor_call_count,
            "distractor_call_rate": self.distractor_call_rate,
            "tool_selection_accuracy": self.tool_selection_accuracy,
            "episodes_with_a_valid_call": self.episodes_with_a_valid_call,
            "infrastructure_error_count": self.infrastructure_error_count,
            "per_scenario_success": self.per_scenario_success,
        }


def summarise(
    tool_count: int,
    tools_presented: Sequence[str],
    outcomes: Sequence[EpisodeOutcome],
) -> BreakpointMetrics:
    """把逐条 outcome 汇总成一个断点的读数。

    基础设施失败的 episode **不计入** `task_success` 的分母——把 OOM 摊进成功率
    会让一次环境故障看起来像模型退化。它单独计数，且冒烟门禁要求它为 0。
    """
    valid = [outcome for outcome in outcomes if outcome.infrastructure_error is None]
    scored = [outcome.score for outcome in valid if outcome.score is not None]
    total_calls = sum(
        score.matched + score.unknown_tool_calls + score.distractor_calls for score in scored
    )
    distractor_calls = sum(score.distractor_calls for score in scored)
    compared = sum(score.compared for score in scored)
    matched = sum(score.matched for score in scored)

    per_scenario: dict[str, list[bool]] = {}
    for outcome in valid:
        per_scenario.setdefault(outcome.scenario, []).append(outcome.success)

    return BreakpointMetrics(
        tool_count=tool_count,
        tools_presented=tuple(tools_presented),
        task_count=len(valid),
        scenarios=tuple(sorted(per_scenario)),
        task_success=(sum(o.success for o in valid) / len(valid)) if valid else 0.0,
        policy_violation_count=sum(len(o.violations) for o in valid),
        invalid_call_count=sum(score.invalid_calls for score in scored),
        unknown_tool_call_count=sum(score.unknown_tool_calls for score in scored),
        distractor_call_count=distractor_calls,
        distractor_call_rate=(distractor_calls / total_calls) if total_calls else 0.0,
        tool_selection_accuracy=(matched / compared) if compared else 0.0,
        episodes_with_a_valid_call=sum(
            1 for score in scored if score.matched + score.distractor_calls > 0
        ),
        infrastructure_error_count=len(outcomes) - len(valid),
        per_scenario_success={
            name: f"{sum(values)}/{len(values)}" for name, values in sorted(per_scenario.items())
        },
    )


def evaluate_tasks(
    tasks: Sequence[TaskSpec],
    env_factory: EnvFactory,
    policy_factory: Callable[[TaskSpec], Policy],
    presented_tools: Sequence[str],
    tool_count: int,
    *,
    seed: int = 0,
) -> tuple[BreakpointMetrics, list[EpisodeOutcome]]:
    """跑一批 episode 并汇总。异常记为基础设施失败，不伪装成模型失败。"""
    outcomes: list[EpisodeOutcome] = []
    for task in tasks:
        try:
            trajectory = run_episode(task, env_factory, policy_factory(task), seed=seed)
        except Exception as error:  # 故意兜住并如实标记来源，不伪装成模型失败
            outcomes.append(
                EpisodeOutcome(
                    task_id=task.task_id,
                    scenario=task.scenario.value,
                    success=False,
                    violations=[],
                    score=None,
                    infrastructure_error=f"{type(error).__name__}: {error}",
                )
            )
            continue
        outcomes.append(
            EpisodeOutcome(
                task_id=task.task_id,
                scenario=task.scenario.value,
                success=trajectory.success,
                violations=list(trajectory.violations),
                score=score_tool_selection(task, trajectory, presented_tools),
            )
        )
    return summarise(tool_count, presented_tools, outcomes), outcomes


def preflight_breakpoint(
    tasks: Sequence[TaskSpec],
    env_factory: EnvFactory,
    expected_tools: Sequence[str],
) -> None:
    """跑任何 GPU / API 之前的装置自检。任一条不成立就硬失败。

    1. 环境呈现的工具**恰好**是这个断点声明的子集（自变量真的动了）；
    2. Oracle 能解开每一条任务且零政策违规（gold 序列在环境里走得通）。

    第 2 条就是 2026-08-24 那轮缺的东西。它是 CPU 上零点几秒的事，
    却能在花掉 GPU 之前挡住「读数其实测不出任何东西」。
    """
    if not tasks:
        msg = "任务集为空"
        raise PreflightError(msg)

    presented = tuple(schema.name for schema in env_factory(tasks[0]).list_tools())
    if presented != tuple(expected_tools):
        msg = (
            f"环境呈现的工具与断点声明不符：\n"
            f"  期望 {list(expected_tools)}\n"
            f"  实际 {list(presented)}\n"
            f"自变量没有生效，读数不会测到工具数效应（见 LOG-20260827-01）"
        )
        raise PreflightError(msg)

    unsolved: list[str] = []
    violating: list[str] = []
    for task in tasks:
        trajectory = run_episode(task, env_factory, OraclePolicy(task), seed=0)
        if not trajectory.success:
            unsolved.append(f"{task.task_id}({trajectory.termination.value})")
        if trajectory.violations:
            violating.append(f"{task.task_id}{trajectory.violations}")
    if unsolved or violating:
        msg = (
            f"gold 调用序列在环境里走不通，评测集不自洽——此时任何模型读数都无法归因。\n"
            f"  Oracle 未能完成 {len(unsolved)} 条: {unsolved[:5]}\n"
            f"  gold 序列触发政策违规 {len(violating)} 条: {violating[:5]}"
        )
        raise PreflightError(msg)
