"""构造 MiniRetail 成功轨迹与 TRL SFT 数据集。"""

from __future__ import annotations

from veritool_rl.artifacts import sha256_file, write_json, write_jsonl, write_yaml
from veritool_rl.cli import build_arg_parser, load_config
from veritool_rl.data.generators import build_success_trajectories, trajectory_to_sft_example
from veritool_rl.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits
from veritool_rl.trajectory.replay import replay_trajectory


def main() -> None:
    args = build_arg_parser("VeriTool-RL 轨迹数据构造").parse_args()
    config = load_config(args.config)
    if config.get("environment") != "mini_retail":
        msg = "MVP 数据构造仅支持 environment=mini_retail"
        raise ValueError(msg)

    output_dir = args.output_dir
    splits = build_mvp_task_splits(args.seed)
    trajectories = {
        split: build_success_trajectories(tasks, MiniRetailEnv, args.seed)
        for split, tasks in splits.items()
    }
    replay_count = 0
    for split, tasks in splits.items():
        write_jsonl(
            output_dir / f"tasks/{split}.jsonl",
            (task.model_dump(mode="json") for task in tasks),
        )
        trajectory_path = output_dir / f"trajectories/{split}.jsonl"
        write_jsonl(
            trajectory_path,
            (trajectory.model_dump(mode="json") for trajectory in trajectories[split]),
        )
        for trajectory in trajectories[split]:
            replay_trajectory(trajectory, MiniRetailEnv)
            replay_count += 1
        if split != "test":
            write_jsonl(
                output_dir / f"sft/{split}.jsonl",
                (trajectory_to_sft_example(t) for t in trajectories[split]),
            )

    write_yaml(output_dir / "config.yaml", {**config, "seed": args.seed})
    files = sorted((output_dir / "trajectories").glob("*.jsonl"))
    manifest = {
        "counts": {split: len(tasks) for split, tasks in splits.items()},
        "replay_verified": replay_count,
        "sha256": {path.name: sha256_file(path) for path in files},
    }
    write_json(output_dir / "manifest.json", manifest)
    (output_dir / "log.txt").write_text(
        f"生成并重放验证 {replay_count} 条成功轨迹。\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
