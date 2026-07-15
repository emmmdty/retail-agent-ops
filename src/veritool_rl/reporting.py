"""基线与 adapter 评测的逐任务配对汇总。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from veritool_rl.artifacts import write_json, write_jsonl, write_yaml
from veritool_rl.trajectory import Trajectory


def aggregate_runs(
    baseline_dir: Path,
    adapter_dir: Path,
    output_dir: Path,
    config: dict[str, Any],
    seed: int,
) -> dict[str, Any]:
    """要求相同 task 集合，计算指标差值与逐任务改善/退化。"""
    baseline_metrics = _read_json(baseline_dir / "metrics.json")
    adapter_metrics = _read_json(adapter_dir / "metrics.json")
    baseline = _read_trajectories(baseline_dir / "trajectories.jsonl")
    adapter = _read_trajectories(adapter_dir / "trajectories.jsonl")
    if set(baseline) != set(adapter):
        missing_adapter = sorted(set(baseline) - set(adapter))
        missing_baseline = sorted(set(adapter) - set(baseline))
        msg = (
            "评测 task 集合不一致: "
            f"adapter 缺少 {missing_adapter[:5]}, baseline 缺少 {missing_baseline[:5]}"
        )
        raise ValueError(msg)

    rows: list[dict[str, Any]] = []
    outcomes = {"improved": 0, "regressed": 0, "unchanged": 0}
    for task_id in sorted(baseline):
        before = baseline[task_id]
        after = adapter[task_id]
        if not before.success and after.success:
            outcome = "improved"
        elif before.success and not after.success:
            outcome = "regressed"
        else:
            outcome = "unchanged"
        outcomes[outcome] += 1
        rows.append(
            {
                "task_id": task_id,
                "scenario": before.task.scenario.value,
                "baseline_success": before.success,
                "adapter_success": after.success,
                "baseline_termination": before.termination.value,
                "adapter_termination": after.termination.value,
                "outcome": outcome,
            }
        )

    delta = {
        key: float(adapter_metrics[key]) - float(baseline_metrics[key])
        for key in sorted(set(baseline_metrics) & set(adapter_metrics))
        if isinstance(baseline_metrics[key], (int, float))
        and isinstance(adapter_metrics[key], (int, float))
    }
    summary = {
        "paired_tasks": len(rows),
        "outcomes": outcomes,
        "baseline": baseline_metrics,
        "adapter": adapter_metrics,
        "delta": delta,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_yaml(output_dir / "config.yaml", {**config, "seed": seed})
    write_jsonl(output_dir / "comparison.jsonl", rows)
    write_json(output_dir / "metrics.json", summary)
    (output_dir / "log.txt").write_text(
        f"配对 {len(rows)} 条任务：{outcomes}\n",
        encoding="utf-8",
    )
    return summary


def _read_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        msg = f"JSON 顶层必须是 mapping: {path}"
        raise ValueError(msg)
    return loaded


def _read_trajectories(path: Path) -> dict[str, Trajectory]:
    trajectories = [
        Trajectory.from_jsonl(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    indexed = {trajectory.task.task_id: trajectory for trajectory in trajectories}
    if len(indexed) != len(trajectories):
        msg = f"trajectory 中存在重复 task_id: {path}"
        raise ValueError(msg)
    return indexed
