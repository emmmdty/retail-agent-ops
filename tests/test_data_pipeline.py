"""轨迹数据、SFT 转换与 CLI 产物测试。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml


def test_success_trajectory_converts_to_trl_tool_call_example() -> None:
    from veritool_rl.agent.policy import OraclePolicy
    from veritool_rl.agent.runner import run_episode
    from veritool_rl.data.generators import trajectory_to_sft_example
    from veritool_rl.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits

    task = build_mvp_task_splits(seed=0)["train"][1]
    trajectory = run_episode(task, MiniRetailEnv, OraclePolicy(task), seed=0)

    example = trajectory_to_sft_example(trajectory)

    assert example["task_id"] == task.task_id
    assert example["messages"][0]["role"] == "system"
    assert example["messages"][1] == {"role": "user", "content": task.user_request}
    assert example["messages"][2]["tool_calls"][0]["function"]["name"] == "get_order"
    assert example["messages"][3]["role"] == "tool"
    assert example["tools"][0]["type"] == "function"


def test_build_trajectories_cli_is_reproducible(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    config = tmp_path / "data.yaml"
    config.write_text("environment: mini_retail\n", encoding="utf-8")
    first = tmp_path / "first"
    second = tmp_path / "second"

    for output_dir in (first, second):
        subprocess.run(
            [
                sys.executable,
                str(root / "scripts/build_trajectories.py"),
                "--config",
                str(config),
                "--seed",
                "13",
                "--output_dir",
                str(output_dir),
            ],
            cwd=root,
            check=True,
        )

    assert (first / "trajectories/train.jsonl").read_bytes() == (
        second / "trajectories/train.jsonl"
    ).read_bytes()
    assert len((first / "trajectories/train.jsonl").read_text(encoding="utf-8").splitlines()) == 128
    assert len((first / "sft/dev.jsonl").read_text(encoding="utf-8").splitlines()) == 32
    manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"] == {"dev": 32, "test": 32, "train": 128}
    assert manifest["replay_verified"] == 192
    assert (first / "config.yaml").exists()
    assert (first / "log.txt").exists()


def test_evaluate_cli_writes_oracle_metrics(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    config = tmp_path / "eval.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "environment": "mini_retail",
                "split": "test",
                "policy": {"type": "oracle"},
                "bootstrap_samples": 100,
            },
            allow_unicode=True,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "eval"

    subprocess.run(
        [
            sys.executable,
            str(root / "scripts/evaluate.py"),
            "--config",
            str(config),
            "--seed",
            "0",
            "--output_dir",
            str(output_dir),
        ],
        cwd=root,
        check=True,
    )

    metrics = json.loads((output_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["task_count"] == 32
    assert metrics["task_success"] == 1.0
    assert metrics["policy_violation_rate"] == 0.0
    assert metrics["recovery_success"] == 1.0
    assert (output_dir / "trajectories.jsonl").exists()
    assert (output_dir / "failures.jsonl").read_text(encoding="utf-8") == ""
    assert (output_dir / "config.yaml").exists()
    assert (output_dir / "log.txt").exists()


def test_evaluate_cli_respects_task_limit(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    config = tmp_path / "eval.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "environment": "mini_retail",
                "split": "test",
                "task_limit": 1,
                "policy": {"type": "oracle"},
                "bootstrap_samples": 20,
            },
            allow_unicode=True,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "eval"

    subprocess.run(
        [
            sys.executable,
            str(root / "scripts/evaluate.py"),
            "--config",
            str(config),
            "--seed",
            "0",
            "--output_dir",
            str(output_dir),
        ],
        cwd=root,
        check=True,
    )

    metrics = json.loads((output_dir / "metrics.json").read_text(encoding="utf-8"))
    trajectories = (output_dir / "trajectories.jsonl").read_text(encoding="utf-8").splitlines()
    assert metrics["task_count"] == 1
    assert len(trajectories) == 1


def test_evaluate_cli_rejects_non_positive_task_limit(tmp_path: Path) -> None:
    root = Path(__file__).parents[1]
    config = tmp_path / "eval.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "environment": "mini_retail",
                "split": "test",
                "task_limit": 0,
                "policy": {"type": "oracle"},
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/evaluate.py"),
            "--config",
            str(config),
            "--seed",
            "0",
            "--output_dir",
            str(tmp_path / "eval"),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "task_limit 必须是正整数" in result.stderr
