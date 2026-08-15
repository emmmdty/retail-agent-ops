"""RetailOps qualification 使用的确定性 policy。"""

from __future__ import annotations

import json
import re
from typing import Any

from veritool_rl.core.agent.guardrail import contains_injection
from veritool_rl.core.agent.policy import OraclePolicy, Policy, PolicyOutput
from veritool_rl.core.envs.base import ToolSchema
from veritool_rl.core.trajectory import TaskSpec, ToolCall


def _require_qualification_task(task: TaskSpec) -> None:
    if task.split != "qualification":
        msg = "qualification policy 仅接受 qualification 任务"
        raise ValueError(msg)


class QualificationBaselinePolicy:
    """只查询订单，不执行退款的 qualification 基线。"""

    name = "baseline"

    def __init__(self, task: TaskSpec) -> None:
        _require_qualification_task(task)
        if not task.expected_calls:
            msg = "qualification baseline 要求 expected_calls 非空"
            raise ValueError(msg)
        first_call = task.expected_calls[0]
        if first_call.name != "get_order":
            msg = "qualification baseline 的首个调用必须是 get_order"
            raise ValueError(msg)
        self._call = first_call.model_copy(deep=True)
        self._responded = False

    def respond(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema],
    ) -> PolicyOutput:
        del messages, tools
        if self._responded:
            return PolicyOutput(raw_text="已完成订单核实。", final_response="已完成订单核实。")
        self._responded = True
        payload = {"name": self._call.name, "arguments": self._call.arguments}
        raw = f"<tool_call>\n{json.dumps(payload, ensure_ascii=False)}\n</tool_call>"
        return PolicyOutput(raw_text=raw, tool_call=self._call)


class UnknownToolPolicy:
    """稳定产生未知工具调用，用于验证故障隔离。"""

    name = "unknown_tool"

    def respond(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema],
    ) -> PolicyOutput:
        del messages, tools
        return PolicyOutput(
            raw_text='<tool_call>{"name":"delete_order","arguments":{}}</tool_call>',
            tool_call=ToolCall(name="delete_order", arguments={}),
        )


class SchemaAdaptiveOraclePolicy:
    """按 gold 调用序列执行，但**工具名从当前工具清单解析**。

    与 `OraclePolicy` 的唯一差别是名字从哪来：`OraclePolicy` 把 `expected_calls`
    里的名字直接发出去，本策略先在当前呈现的工具里找参数键集合与本次调用完全
    一致的那一个。两者在同一批任务上的对照，就是 `perturb_schema` 想量化的东西
    ——"换一份工具 schema 之后还能不能用"。

    解析不到时**原样发出 gold 名字**，让它以 `unknown_tool` 可见地失败。静默换一个
    工具是最坏的失败形态：读报告的人会以为 schema 兼容，其实是被兜住了。
    """

    name = "schema_adaptive"

    def __init__(self, task: TaskSpec) -> None:
        _require_qualification_task(task)
        self._calls = [call.model_copy(deep=True) for call in task.expected_calls]
        self._index = 0

    def respond(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema],
    ) -> PolicyOutput:
        del messages
        if self._index >= len(self._calls):
            return PolicyOutput(raw_text="任务已完成。", final_response="任务已完成。")
        call = self._calls[self._index]
        self._index += 1
        resolved = call.model_copy(update={"name": _resolve_tool_name(call, tools)})
        payload = {"name": resolved.name, "arguments": resolved.arguments}
        raw = f"<tool_call>\n{json.dumps(payload, ensure_ascii=False)}\n</tool_call>"
        return PolicyOutput(raw_text=raw, tool_call=resolved)


def _resolve_tool_name(call: ToolCall, tools: list[ToolSchema]) -> str:
    """按参数键集合唯一匹配当前工具；不唯一或无匹配时回落到 gold 名字。"""
    wanted = set(call.arguments)
    matches = [
        tool.name
        for tool in tools
        if set(tool.parameters.get("properties", {})) == wanted
    ]
    if len(matches) == 1:
        return matches[0]
    return call.name


class InjectionProbePolicy:
    """**红队探针**：一个会照做观测里指令的策略。

    它不是任何真实模型的替身，也不用来声称 Qwen 是否易感——那需要 GPU 评测。
    它的作用是把"注入内容有没有进入模型上下文"从一句断言变成一个**可复现的数字**：
    探针只有真的读到那句指令才会去动干扰订单，于是 `injection_success_rate`
    直接度量的是**上下文污染是否发生**，而不是某个模型的顺从程度。

    没有 guardrail 时它必然被注入；开了 guardrail 之后观测已被消毒，它什么也看不到。
    两次运行的差值就是这一层防御的实测效果。
    """

    name = "injection_probe"

    def __init__(self, task: TaskSpec) -> None:
        _require_qualification_task(task)
        self._calls = [call.model_copy(deep=True) for call in task.expected_calls]
        self._index = 0
        self._decoy_done = False
        self._refund_template = next(
            (call for call in task.expected_calls if call.name == "refund_order"), None
        )

    def respond(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema],
    ) -> PolicyOutput:
        del tools
        decoy = _decoy_order_id(messages)
        if decoy is not None and not self._decoy_done:
            self._decoy_done = True
            arguments: dict[str, Any] = {"order_id": decoy, "reason": "damaged"}
            if self._refund_template is not None:
                for key in self._refund_template.arguments:
                    if key not in arguments:
                        arguments[key] = f"probe-{decoy}"
            call = ToolCall(name="refund_order", arguments=arguments)
            payload = {"name": call.name, "arguments": call.arguments}
            raw = f"<tool_call>\n{json.dumps(payload, ensure_ascii=False)}\n</tool_call>"
            return PolicyOutput(raw_text=raw, tool_call=call)
        if self._index >= len(self._calls):
            return PolicyOutput(raw_text="任务已完成。", final_response="任务已完成。")
        call = self._calls[self._index]
        self._index += 1
        payload = {"name": call.name, "arguments": call.arguments}
        raw = f"<tool_call>\n{json.dumps(payload, ensure_ascii=False)}\n</tool_call>"
        return PolicyOutput(raw_text=raw, tool_call=call)


def _decoy_order_id(messages: list[dict[str, Any]]) -> str | None:
    """从**已进入上下文**的消息里提取被注入指令点名的订单号。

    只看 messages，不看任务真值：探针能拿到这个订单号，当且仅当消毒失败。
    """
    blob = json.dumps(messages, ensure_ascii=False)
    if not contains_injection(blob):
        return None
    match = _INJECTED_ORDER_PATTERN.search(blob)
    return match.group(1) if match is not None else None


_INJECTED_ORDER_PATTERN = re.compile(r"包括订单 (O-[0-9A-F]{12})")


class MessageGroundedPolicy:
    """**只用 messages 里出现过的信息**决定动作的策略。

    与 `OraclePolicy` 的差别是它必须先在对话里**看到**订单号：看不到就提问，
    看到了才按 gold 序列执行。它因此把"多轮澄清有没有真的接通"变成一个可复现的
    数字——欠指定任务上，没有 user simulator 时它永远拿不到订单号。

    这是**机制探针**，不是任何真实模型的替身：它不度量模型会不会想到要问，
    只度量"问了之后系统能不能把答案送回来并继续"。真实模型的澄清能力需要 GPU 评测。
    """

    name = "message_grounded"

    CLARIFICATION_QUESTION = "请问您要处理的是哪一个订单？请提供订单号。"

    def __init__(self, task: TaskSpec) -> None:
        _require_qualification_task(task)
        self._calls = [call.model_copy(deep=True) for call in task.expected_calls]
        self._index = 0
        self._needs_order_id = isinstance(task.metadata.get("clarification"), dict)
        self._order_id = str(task.metadata.get("order_id", ""))

    def respond(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema],
    ) -> PolicyOutput:
        del tools
        if self._needs_order_id and not self._order_id_is_in_context(messages):
            return PolicyOutput(
                raw_text=self.CLARIFICATION_QUESTION,
                final_response=self.CLARIFICATION_QUESTION,
            )
        if self._index >= len(self._calls):
            return PolicyOutput(raw_text="任务已完成。", final_response="任务已完成。")
        call = self._calls[self._index]
        self._index += 1
        payload = {"name": call.name, "arguments": call.arguments}
        raw = f"<tool_call>\n{json.dumps(payload, ensure_ascii=False)}\n</tool_call>"
        return PolicyOutput(raw_text=raw, tool_call=call)

    def _order_id_is_in_context(self, messages: list[dict[str, Any]]) -> bool:
        """只认**用户说过**的订单号：工具观测里的不算，那是它自己造出来的回声。"""
        if not self._order_id:
            return False
        return any(
            message.get("role") == "user" and self._order_id in str(message.get("content", ""))
            for message in messages
        )


def build_qualification_policy(policy_type: str, task: TaskSpec) -> Policy:
    """按名称构建 qualification policy。"""
    _require_qualification_task(task)
    if policy_type == "oracle":
        return OraclePolicy(task)
    if policy_type == "injection_probe":
        return InjectionProbePolicy(task)
    if policy_type == "message_grounded":
        return MessageGroundedPolicy(task)
    if policy_type == "schema_adaptive":
        return SchemaAdaptiveOraclePolicy(task)
    if policy_type == "baseline":
        return QualificationBaselinePolicy(task)
    if policy_type == "unknown_tool":
        return UnknownToolPolicy()
    msg = f"未知 qualification policy: {policy_type}"
    raise ValueError(msg)
