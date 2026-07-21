"""RetailOps qualification 使用的确定性 policy。"""

from __future__ import annotations

import json
from typing import Any

from veritool_rl.agent.policy import OraclePolicy, Policy, PolicyOutput
from veritool_rl.envs.base import ToolSchema
from veritool_rl.trajectory import TaskSpec, ToolCall


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


def build_qualification_policy(policy_type: str, task: TaskSpec) -> Policy:
    """按名称构建 qualification policy。"""
    _require_qualification_task(task)
    if policy_type == "oracle":
        return OraclePolicy(task)
    if policy_type == "baseline":
        return QualificationBaselinePolicy(task)
    if policy_type == "unknown_tool":
        return UnknownToolPolicy()
    msg = f"未知 qualification policy: {policy_type}"
    raise ValueError(msg)
