"""确定性成功轨迹生成与 TRL tool-calling 数据转换。"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

from veritool_rl.core.agent.policy import OraclePolicy
from veritool_rl.core.agent.runner import run_episode
from veritool_rl.core.envs.base import ToolEnv
from veritool_rl.core.trajectory import TaskSpec, Trajectory


def build_success_trajectories(
    tasks: Sequence[TaskSpec],
    env_factory: Callable[[TaskSpec], ToolEnv],
    seed: int,
) -> list[Trajectory]:
    """用 Oracle 生成并验证成功轨迹。"""
    trajectories = [run_episode(task, env_factory, OraclePolicy(task), seed=seed) for task in tasks]
    failed = [trajectory.task.task_id for trajectory in trajectories if not trajectory.success]
    if failed:
        msg = f"Oracle 轨迹生成失败: {failed[:5]}"
        raise RuntimeError(msg)
    return trajectories


def trajectory_to_sft_example(trajectory: Trajectory) -> dict[str, Any]:
    """转换为 TRL 原生 messages + tools 的 tool-calling 样本。"""
    if not trajectory.success:
        msg = f"SFT 只接受 verifier 通过的成功轨迹: {trajectory.task.task_id}"
        raise ValueError(msg)
    system_prompt = trajectory.metadata.get("system_prompt")
    tools = trajectory.metadata.get("tools")
    if not isinstance(system_prompt, str) or not isinstance(tools, list):
        msg = f"轨迹缺少训练所需的 system_prompt/tools: {trajectory.task.task_id}"
        raise ValueError(msg)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": trajectory.task.user_request},
    ]
    for step in trajectory.steps:
        if step.tool_call is not None:
            call_id = step.tool_call.call_id or f"call_{step.index}"
            messages.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": step.tool_call.name,
                                "arguments": json.dumps(
                                    step.tool_call.arguments,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                ),
                            },
                        }
                    ],
                }
            )
            if step.observation is None:
                msg = f"工具调用缺少 observation: {trajectory.task.task_id}/{step.index}"
                raise ValueError(msg)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(
                        step.observation.model_dump(mode="json"),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                }
            )
        elif step.final_response is not None:
            messages.append({"role": "assistant", "content": step.final_response})

    return {
        "task_id": trajectory.task.task_id,
        "scenario": trajectory.task.scenario.value,
        "messages": messages,
        "tools": tools,
    }
