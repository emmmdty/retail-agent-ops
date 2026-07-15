"""训练前后逐任务配对汇总测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def test_aggregate_runs_pairs_tasks_and_reports_improvement(tmp_path: Path) -> None:
    from veritool_rl.agent.policy import OraclePolicy, PolicyOutput
    from veritool_rl.agent.runner import run_episode
    from veritool_rl.artifacts import write_json, write_jsonl
    from veritool_rl.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits
    from veritool_rl.eval.metrics import compute_metrics
    from veritool_rl.reporting import aggregate_runs

    class FinalOnlyPolicy:
        name = "final-only"

        def respond(self, messages: list[dict[str, Any]], tools: list[Any]) -> PolicyOutput:
            del messages, tools
            return PolicyOutput(raw_text="无法处理", final_response="无法处理")

    tasks = build_mvp_task_splits(seed=0)["test"][:4]
    baseline = [run_episode(task, MiniRetailEnv, FinalOnlyPolicy(), seed=0) for task in tasks]
    adapter = [run_episode(task, MiniRetailEnv, OraclePolicy(task), seed=0) for task in tasks]
    baseline_dir = tmp_path / "baseline"
    adapter_dir = tmp_path / "adapter"
    for directory, trajectories in ((baseline_dir, baseline), (adapter_dir, adapter)):
        write_jsonl(
            directory / "trajectories.jsonl",
            (trajectory.model_dump(mode="json") for trajectory in trajectories),
        )
        write_json(directory / "metrics.json", compute_metrics(trajectories, 20, 0))

    summary = aggregate_runs(
        baseline_dir=baseline_dir,
        adapter_dir=adapter_dir,
        output_dir=tmp_path / "summary",
        config={"baseline_dir": str(baseline_dir), "adapter_dir": str(adapter_dir)},
        seed=0,
    )

    assert summary["paired_tasks"] == 4
    assert summary["outcomes"] == {"improved": 4, "regressed": 0, "unchanged": 0}
    assert summary["delta"]["task_success"] == 1.0
    assert (tmp_path / "summary/comparison.jsonl").exists()
    assert (tmp_path / "summary/metrics.json").exists()
