"""MiniRetail Oracle/Qwen 评测入口。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from veritool_rl.cli import build_arg_parser, load_config
from veritool_rl.core.agent.policy import OraclePolicy, Policy
from veritool_rl.core.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits
from veritool_rl.core.trajectory import TaskSpec
from veritool_rl.legacy.eval.evaluator import Evaluator


def main() -> None:
    args = build_arg_parser("VeriTool-RL 评测").parse_args()
    config = load_config(args.config)
    if config.get("environment") != "mini_retail":
        msg = "MVP 评测仅支持 environment=mini_retail"
        raise ValueError(msg)
    split = config.get("split", "test")
    if split not in {"train", "dev", "test"}:
        msg = f"未知 split: {split}"
        raise ValueError(msg)

    policy_config = config.get("policy")
    if not isinstance(policy_config, dict):
        msg = "policy 配置必须是 mapping"
        raise ValueError(msg)
    policy_factory = _build_policy_factory(policy_config)
    tasks = build_mvp_task_splits(args.seed)[split]
    task_limit = config.get("task_limit")
    if task_limit is not None:
        if not isinstance(task_limit, int) or isinstance(task_limit, bool) or task_limit < 1:
            msg = "task_limit 必须是正整数"
            raise ValueError(msg)
        tasks = tasks[:task_limit]
    evaluator = Evaluator(tasks, MiniRetailEnv, policy_factory, config)
    evaluator.run(seed=args.seed, output_dir=args.output_dir)


def _build_policy_factory(config: dict[str, Any]) -> Callable[[TaskSpec], Policy]:
    policy_type = config.get("type")
    if policy_type == "oracle":

        def factory(task: TaskSpec) -> Policy:
            return OraclePolicy(task)

        return factory
    if policy_type == "qwen":
        from veritool_rl.core.agent.qwen import QwenPolicy

        policy = QwenPolicy.from_config(config)

        def factory(task: TaskSpec) -> Policy:
            del task
            return policy

        return factory
    msg = f"尚未支持的 policy.type: {policy_type}"
    raise ValueError(msg)


if __name__ == "__main__":
    main()
