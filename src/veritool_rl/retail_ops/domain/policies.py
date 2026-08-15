"""RetailOps qualification 使用的确定性 policy。"""

from __future__ import annotations

import json
from typing import Any

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


def build_qualification_policy(policy_type: str, task: TaskSpec) -> Policy:
    """按名称构建 qualification policy。"""
    _require_qualification_task(task)
    if policy_type == "oracle":
        return OraclePolicy(task)
    if policy_type == "schema_adaptive":
        return SchemaAdaptiveOraclePolicy(task)
    if policy_type == "baseline":
        return QualificationBaselinePolicy(task)
    if policy_type == "unknown_tool":
        return UnknownToolPolicy()
    msg = f"未知 qualification policy: {policy_type}"
    raise ValueError(msg)
