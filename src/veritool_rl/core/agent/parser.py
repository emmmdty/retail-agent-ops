"""Qwen3 Hermes 工具调用输出的严格解析器。"""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from veritool_rl.core.agent.policy import PolicyOutput
from veritool_rl.core.trajectory import ToolCall

_TOOL_CALL_PATTERN = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)


def parse_qwen_response(raw_text: str) -> PolicyOutput:
    """解析一个工具调用；多调用和混合文本均视为协议错误。"""
    matches = _TOOL_CALL_PATTERN.findall(raw_text)
    if len(matches) > 1:
        return PolicyOutput(raw_text=raw_text, parse_error="multiple_tool_calls")
    if not matches:
        if "<tool_call>" in raw_text or "</tool_call>" in raw_text:
            return PolicyOutput(raw_text=raw_text, parse_error="invalid_tool_call_json")
        final = raw_text.replace("<|im_end|>", "").strip()
        if not final:
            return PolicyOutput(raw_text=raw_text, parse_error="empty_response")
        return PolicyOutput(raw_text=raw_text, final_response=final)

    outside = _TOOL_CALL_PATTERN.sub("", raw_text).replace("<|im_end|>", "").strip()
    if outside:
        return PolicyOutput(raw_text=raw_text, parse_error="mixed_tool_call_content")
    try:
        payload = json.loads(matches[0])
        call = ToolCall.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError):
        return PolicyOutput(raw_text=raw_text, parse_error="invalid_tool_call_json")
    return PolicyOutput(raw_text=raw_text, tool_call=call)
