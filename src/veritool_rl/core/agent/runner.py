"""task → policy → tool → observation → verifier 的 episode 循环。"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

from veritool_rl.core.agent.guardrail import Guardrail, blocked_observation
from veritool_rl.core.agent.policy import Policy
from veritool_rl.core.agent.user_simulator import UserSimulator
from veritool_rl.core.envs.base import ToolEnv
from veritool_rl.core.rewards.verifier import compute_reward_breakdown
from veritool_rl.core.trajectory import (
    Observation,
    Step,
    TaskSpec,
    TerminationReason,
    Trajectory,
)

EnvFactory = Callable[[TaskSpec], ToolEnv]

#: R4 第二轮候选 C 的唯一变量：在原有两句后追加一句**显式授权自主完成**的指令。
#: 要点不是改成祈使语气，而是解除"确认可退之后仍向用户征询"这个行为——dev 上
#: 17/17 的失败都是这一支（LOG-20260811-06）。
#:
#: 这个常量被 `base_evaluation.py` 与 `sealed_evaluation.py` 哈希成
#: `system_prompt_sha256`，而该字段同时在 dev 的 `PAIRING_FIELDS` 与
#: `SEALED_PAIRING_FIELDS` 内。改动它会使**此前所有**评测证据不再与新运行配对，
#: 因此每次改动都必须重跑对照 base，且必须发生在已有候选评测全部完成之后。
#: 旧值 sha256 = d919602e25f2c87c0d0961521a69c8ab2891e814a3180896aaaaaf5d5a3afe36
SYSTEM_PROMPT = (
    "你是订单工具助手。只能使用提供的工具处理请求；退款前必须查询订单，"
    "遇到 transient_error 时可以重试。确认符合退款政策后直接调用工具执行，"
    "不要再向用户征询确认。"
)


def run_episode(
    task: TaskSpec,
    env_factory: EnvFactory,
    policy: Policy,
    seed: int,
    *,
    system_prompt: str | None = None,
    guardrail: Guardrail | None = None,
    user_simulator: UserSimulator | None = None,
) -> Trajectory:
    """运行单个任务，模型级错误记录在轨迹中而不传播到整批评测。

    两个新参数都**默认关闭**，不传时行为与 2026-08-15 之前逐字节相同——
    全部已产出的评测证据都依赖这一点。

    - `system_prompt`：`None` 表示用模块级常量。v2 起由 bundle 渲染政策卡传入，
      使模型**读**政策而不是**记**政策。
    - `guardrail`：与环境政策校验**分层独立**的第二道防线，见
      `core/agent/guardrail.py`。它在调用触达环境之前校验，在观测进入 `messages`
      之前消毒。
    - `user_simulator`：把 episode 从单轮变成可澄清的多轮。助手发出的"最终答复"
      若被判定为提问且模拟器给出回复，对话继续；否则照常收尾。
      **只有真正收尾的那一句才算最终答复**——把一次澄清提问记成最终答复会让
      INFORM/DENY 类任务凭一句反问就判成功。
    """
    env = env_factory(task)
    tools = env.list_tools()
    prompt = SYSTEM_PROMPT if system_prompt is None else system_prompt
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompt},
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
            blocked = None if guardrail is None else guardrail.check_call(output.tool_call, tools)
            if blocked is not None:
                # 拦截产生结构化观测而不是静默丢弃：静默会让模型以为工具执行了，
                # 也会让失败 taxonomy 少掉一整类。
                observation = blocked_observation(blocked)
            else:
                observation = env.execute_tool(output.tool_call.name, output.tool_call.arguments)
                if guardrail is not None:
                    guardrail.observe(output.tool_call, observation)
                    observation = guardrail.sanitize(observation)
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

        user_reply: str | None = None
        if output.final_response is not None and user_simulator is not None:
            user_reply = user_simulator.reply(output.final_response, task)
            if user_reply is not None:
                messages.append({"role": "user", "content": user_reply})
        if output.final_response is not None and user_reply is None:
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
        if output.final_response is not None and user_reply is None:
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
            "system_prompt": prompt,
            "tools": [tool.to_transformers() for tool in tools],
        },
    )
