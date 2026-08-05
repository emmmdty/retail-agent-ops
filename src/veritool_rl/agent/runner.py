"""task → policy → tool → observation → verifier 的 episode 循环。"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

from veritool_rl.agent.policy import Policy
from veritool_rl.envs.base import ToolEnv
from veritool_rl.rewards.verifier import compute_reward_breakdown
from veritool_rl.trajectory import (
    Observation,
    Step,
    TaskSpec,
    TerminationReason,
    Trajectory,
)

EnvFactory = Callable[[TaskSpec], ToolEnv]

SYSTEM_PROMPT = (
    "你是订单工具助手。只能使用提供的工具处理请求；退款前必须查询订单，"
    "遇到 transient_error 时可以重试。"
)


def run_episode(
    task: TaskSpec,
    env_factory: EnvFactory,
    policy: Policy,
    seed: int,
) -> Trajectory:
    """运行单个任务，模型级错误记录在轨迹中而不传播到整批评测。"""
    env = env_factory(task)
    tools = env.list_tools()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task.user_request},
    ]
    steps: list[Step] = []
    termination = TerminationReason.STEP_LIMIT

    for index in range(task.max_steps):
        output = policy.respond(copy.deepcopy(messages), env.list_tools())
        observation: Observation | None = None

        if output.parse_error is not None:
            observation = Observation(
                ok=False,
                error_code="format_error",
                error=output.parse_error,
            )
            messages.extend(
                [
                    {"role": "assistant", "content": output.raw_text},
                    {
                        "role": "user",
                        "content": f"工具调用格式错误：{output.parse_error}。请按 schema 重试。",
                    },
                ]
            )
        elif output.tool_call is not None:
            observation = env.execute_tool(output.tool_call.name, output.tool_call.arguments)
            call_id = output.tool_call.call_id or f"call_{index}"
            messages.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": output.tool_call.name,
                                "arguments": json.dumps(
                                    output.tool_call.arguments,
                                    ensure_ascii=False,
                                    sort_keys=True,
                                ),
                            },
                        }
                    ],
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(
                        observation.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
                    ),
                }
            )
        else:
            messages.append({"role": "assistant", "content": output.final_response or ""})

        if output.final_response is not None:
            env.record_final_response(output.final_response)
        reward = compute_reward_breakdown(env, observation, output.parse_error)
        violations = env.check_policy()
        steps.append(
            Step(
                index=index,
                assistant_raw=output.raw_text,
                tool_call=output.tool_call,
                final_response=output.final_response,
                parse_error=output.parse_error,
                observation=observation,
                state_after=env.get_state(),
                reward=reward,
                violations=violations,
                latency_ms=output.latency_ms,
                input_tokens=output.input_tokens,
                output_tokens=output.output_tokens,
            )
        )

        if violations:
            termination = TerminationReason.POLICY_VIOLATION
            break
        if reward.final_state == 1.0:
            termination = TerminationReason.SUCCESS
            break
        if output.final_response is not None:
            termination = TerminationReason.FINAL_RESPONSE
            break

    success = termination is TerminationReason.SUCCESS
    return Trajectory(
        task=task,
        steps=steps,
        final_state=env.get_state(),
        violations=env.check_policy(),
        termination=termination,
        success=success,
        metadata={
            "policy": policy.name,
            "seed": seed,
            "system_prompt": SYSTEM_PROMPT,
            "tools": [tool.to_transformers() for tool in tools],
        },
    )
