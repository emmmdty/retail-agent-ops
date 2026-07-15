"""在冻结任务集合上运行 policy 并写出可复现实验记录。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from veritool_rl.agent.policy import Policy
from veritool_rl.agent.runner import EnvFactory, run_episode
from veritool_rl.artifacts import write_json, write_jsonl, write_yaml
from veritool_rl.eval.metrics import compute_metrics
from veritool_rl.trajectory import TaskSpec, Trajectory
from veritool_rl.trajectory.replay import replay_trajectory

PolicyFactory = Callable[[TaskSpec], Policy]


class Evaluator:
    """顺序评测 policy，并保留逐任务可重放证据。"""

    def __init__(
        self,
        tasks: Sequence[TaskSpec],
        env_factory: EnvFactory,
        policy_factory: PolicyFactory,
        config: dict[str, Any],
    ) -> None:
        self._tasks = list(tasks)
        self._env_factory = env_factory
        self._policy_factory = policy_factory
        self._config = config

    def run(self, seed: int, output_dir: Path) -> dict[str, Any]:
        """运行评测并写出 config、trajectory、metrics、failure 与日志。"""
        trajectories = [
            run_episode(task, self._env_factory, self._policy_factory(task), seed)
            for task in self._tasks
        ]
        for trajectory in trajectories:
            replay_trajectory(trajectory, self._env_factory)

        bootstrap_samples = self._config.get("bootstrap_samples", 1000)
        if not isinstance(bootstrap_samples, int):
            msg = "bootstrap_samples 必须是整数"
            raise ValueError(msg)
        metrics = compute_metrics(trajectories, bootstrap_samples, seed)
        output_dir.mkdir(parents=True, exist_ok=True)
        write_yaml(output_dir / "config.yaml", {**self._config, "seed": seed})
        write_jsonl(
            output_dir / "trajectories.jsonl",
            (trajectory.model_dump(mode="json") for trajectory in trajectories),
        )
        write_json(output_dir / "metrics.json", metrics)
        write_jsonl(output_dir / "failures.jsonl", _failure_rows(trajectories))
        (output_dir / "log.txt").write_text(
            f"完成 {len(trajectories)} 条评测；成功 {sum(t.success for t in trajectories)} 条。\n",
            encoding="utf-8",
        )
        return metrics


def _failure_rows(trajectories: Sequence[Trajectory]) -> list[dict[str, Any]]:
    return [
        {
            "task_id": trajectory.task.task_id,
            "scenario": trajectory.task.scenario.value,
            "termination": trajectory.termination.value,
            "violations": trajectory.violations,
            "last_error": (
                trajectory.steps[-1].observation.error_code
                if trajectory.steps and trajectory.steps[-1].observation is not None
                else None
            ),
        }
        for trajectory in trajectories
        if not trajectory.success
    ]
