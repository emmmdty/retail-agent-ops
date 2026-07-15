"""与具体模型解耦的 Policy 接口和确定性 Oracle。"""

from __future__ import annotations

import json
from typing import Any, Protocol

from veritool_rl.envs.base import ToolSchema
from veritool_rl.trajectory import TaskSpec, ToolCall
from veritool_rl.trajectory.schema import StrictModel


class PolicyOutput(StrictModel):
    """一次 policy 推理的标准化输出。"""

    raw_text: str
    tool_call: ToolCall | None = None
    final_response: str | None = None
    parse_error: str | None = None
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0


class Policy(Protocol):
    """AgentRunner 所需的最小 policy 协议。"""

    name: str

    def respond(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema],
    ) -> PolicyOutput:
        """根据当前消息和工具返回一个动作或最终回复。"""
        ...


class OraclePolicy:
    """按 TaskSpec 的 gold 调用序列执行，用于验证基础设施。"""

    name = "oracle"

    def __init__(self, task: TaskSpec) -> None:
        self._calls = [call.model_copy(deep=True) for call in task.expected_calls]
        self._index = 0

    def respond(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema],
    ) -> PolicyOutput:
        del messages, tools
        if self._index >= len(self._calls):
            return PolicyOutput(raw_text="任务已完成。", final_response="任务已完成。")
        call = self._calls[self._index]
        self._index += 1
        payload = {"name": call.name, "arguments": call.arguments}
        raw = f"<tool_call>\n{json.dumps(payload, ensure_ascii=False)}\n</tool_call>"
        return PolicyOutput(raw_text=raw, tool_call=call)
