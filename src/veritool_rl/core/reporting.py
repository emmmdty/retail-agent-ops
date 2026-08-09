"""基线与 adapter 评测的逐任务配对汇总。"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from veritool_rl.core.artifacts import write_json, write_jsonl, write_yaml
from veritool_rl.core.trajectory import Trajectory


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
    _validate_fair_configs(
        _read_yaml(baseline_dir / "config.yaml"),
        _read_yaml(adapter_dir / "config.yaml"),
    )
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
                "baseline_verifier_reward": sum(step.reward.total for step in before.steps),
                "adapter_verifier_reward": sum(step.reward.total for step in after.steps),
                "outcome": outcome,
            }
        )

    delta = {
        key: float(adapter_metrics[key]) - float(baseline_metrics[key])
        for key in sorted(set(baseline_metrics) & set(adapter_metrics))
        if isinstance(baseline_metrics[key], (int, float))
        and isinstance(adapter_metrics[key], (int, float))
    }
    bootstrap_samples = config.get("bootstrap_samples", 1000)
    if (
        not isinstance(bootstrap_samples, int)
        or isinstance(bootstrap_samples, bool)
        or bootstrap_samples < 1
    ):
        msg = "bootstrap_samples 必须是正整数"
        raise ValueError(msg)
    paired_deltas = [float(row["adapter_success"]) - float(row["baseline_success"]) for row in rows]
    summary = {
        "paired_tasks": len(rows),
        "outcomes": outcomes,
        "paired_task_success_delta_ci95": _paired_bootstrap_ci(
            paired_deltas, bootstrap_samples, seed
        ),
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


def _read_yaml(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        msg = f"YAML 顶层必须是 mapping: {path}"
        raise ValueError(msg)
    return loaded


def _validate_fair_configs(
    baseline_config: dict[str, Any], adapter_config: dict[str, Any]
) -> None:
    baseline = copy.deepcopy(baseline_config)
    adapter = copy.deepcopy(adapter_config)
    baseline_policy = baseline.get("policy")
    adapter_policy = adapter.get("policy")
    if not isinstance(baseline_policy, dict) or not isinstance(adapter_policy, dict):
        msg = "评测冻结配置不公平: policy 必须是 mapping"
        raise ValueError(msg)
    baseline_adapter = baseline_policy.pop("adapter_path", None)
    adapter_path = adapter_policy.pop("adapter_path", None)
    if baseline_adapter is not None or not isinstance(adapter_path, str) or not adapter_path:
        msg = "评测冻结配置不公平: 仅 adapter 评测可设置 adapter_path"
        raise ValueError(msg)
    if baseline != adapter:
        msg = "评测冻结配置不公平: 除 adapter_path 外必须完全一致"
        raise ValueError(msg)


def _paired_bootstrap_ci(values: list[float], samples: int, seed: int) -> list[float]:
    if not values:
        return [0.0, 0.0]
    array = np.asarray(values, dtype=np.float64)
    rng = np.random.default_rng(seed)
    means = rng.choice(array, size=(samples, len(array)), replace=True).mean(axis=1)
    low, high = np.quantile(means, [0.025, 0.975])
    return [float(low), float(high)]


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
