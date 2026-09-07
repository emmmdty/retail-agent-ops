"""Qwen3 Hermes 工具调用输出的严格解析器。"""

from __future__ import annotations

import json
import logging
import re

from pydantic import ValidationError

from veritool_rl.core.agent.policy import PolicyOutput
from veritool_rl.core.trajectory import ToolCall

_TOOL_CALL_PATTERN = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_TOOL_CALL_GREEDY_PATTERN = re.compile(r"<tool_call>\s*(.*)\s*</tool_call>", re.DOTALL)
_logger = logging.getLogger(__name__)


def _extract_payload(raw_text: str, greedy: bool = False) -> str | None:
    """
    Extract JSON payload from a tool_call block.

    greedy=False: non-greedy match (standard path).
    greedy=True: greedy match, take last closing tag,
    defends against nested tags causing non-greedy to truncate valid payload.
    """
    pattern = _TOOL_CALL_GREEDY_PATTERN if greedy else _TOOL_CALL_PATTERN
    m = pattern.search(raw_text)
    if m is None:
        return None
    return m.group(1).strip()


def _parse_json_payload(raw_text: str, payload: str) -> PolicyOutput:
    """Try to parse JSON + Pydantic validation from payload."""
    try:
        obj = json.loads(payload)
        call = ToolCall.model_validate(obj)
        return PolicyOutput(raw_text=raw_text, tool_call=call)
    except (json.JSONDecodeError, ValidationError, TypeError):
        return PolicyOutput(raw_text=raw_text, parse_error="invalid_tool_call_json")


def parse_qwen_response(raw_text: str) -> PolicyOutput:
    """Parse a tool call; multiple calls and mixed text are protocol errors.

    Defends against nested closing tags: try non-greedy first,
    fall back to greedy matching to extract the last payload.
    """
    payload = _extract_payload(raw_text, greedy=False)
    if payload is not None:
        outside = (
            _TOOL_CALL_PATTERN.sub("", raw_text)
            .replace("</tool_call>", "")
            .replace("<|im_end|>", "")
            .replace("<|im_start|>", "")
            .strip()
        )
        if outside:
            return PolicyOutput(raw_text=raw_text, parse_error="mixed_tool_call_content")
        return _parse_json_payload(raw_text, payload)

    # Non-greedy found nothing. If tags exist at all, try greedy fallback.
    if "<tool_call>" in raw_text or "</tool_call>" in raw_text:
        greedy_payload = _extract_payload(raw_text, greedy=True)
        if greedy_payload is not None:
            _logger.warning("parser: greedy fallback extracted payload from malformed tags")
            return _parse_json_payload(raw_text, greedy_payload)
        return PolicyOutput(raw_text=raw_text, parse_error="invalid_tool_call_json")

    final = raw_text.replace("</tool_call>", "").strip()
    if not final:
        return PolicyOutput(raw_text=raw_text, parse_error="empty_response")
    return PolicyOutput(raw_text=raw_text, final_response=final)


_EOS_MARKERS = ("<|im_end|>", "<|im_start|>")


def parse_qwen_response_v2(raw_text: str) -> PolicyOutput:
    """`hermes-single-call-v2-unterminated`：在 v1 之上容忍 eos 前未闭合的 tool_call。

    诊断依据（findings 2026-09-07「V6-1 空生成诊断」）：观测 8 两次
    `invalid_tool_call_json` 的实录是「有效 JSON 缺 `\\n</tool_call>` 闭合标签」——
    tokenizer 边界退化（`"}}\\n` 合并 token 与裸 `"​}}` 的近僵持），JSON 本身完整。
    容忍条件取**最窄**：恰好一个 `<tool_call>` 开标签、无闭标签、开标签前无散文、
    剥离 eos 标记后剩余部分**恰好是合法 JSON**。其余一切（闭合但 JSON 非法、
    尾部散文、多重开标签、前置散文）维持 v1 的拒绝判定；v1 的全部正常路径
    （闭合调用 / 终局答复 / 空响应）逐字节不变。
    """
    result = parse_qwen_response(raw_text)
    if result.parse_error != "invalid_tool_call_json" or "</tool_call>" in raw_text:
        return result
    head, marker, tail = raw_text.partition("<tool_call>")
    if not marker or head.strip() or "<tool_call>" in tail:
        return result
    payload = tail
    for eos in _EOS_MARKERS:
        payload = payload.split(eos, 1)[0]
    payload = payload.strip()
    if not payload:
        return result
    try:
        call = ToolCall.model_validate(json.loads(payload))
    except (json.JSONDecodeError, ValidationError, TypeError):
        return result
    return PolicyOutput(raw_text=raw_text, tool_call=call)
