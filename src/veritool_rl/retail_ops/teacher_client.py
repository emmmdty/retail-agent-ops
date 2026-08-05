"""OpenAI-compatible teacher Chat Completions 传输边界。"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from pydantic import ConfigDict, Field, ValidationError

from veritool_rl.retail_ops.teacher_route import TeacherRouteSnapshot
from veritool_rl.trajectory import ToolCall
from veritool_rl.trajectory.schema import StrictModel

_RETRYABLE_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504})
_RETRYABLE_ERROR_CLASS_NAMES = frozenset(
    {"APITimeoutError", "APIConnectionError", "RateLimitError", "InternalServerError"}
)


class TeacherClientError(RuntimeError):
    """不携带请求凭据或原始敏感响应的 teacher client 错误。

    ``retryable`` 只标记底层传输/限流/服务端错误（超时、429、5xx），供调用方
    （Task 4 采集循环）决定是否重试；鉴权、schema 等 4xx 错误一律不可重试。
    """

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class TeacherUsage(StrictModel):
    """服务端实际返回的 token usage；缺失字段不做推断。"""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )

    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class TeacherResponse(StrictModel):
    """一次 Chat Completions 响应的稳定结构化投影。"""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )

    response_id: str | None = None
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    model: str = Field(min_length=1)
    system_fingerprint: str | None = None
    usage: TeacherUsage | None = None


class TeacherClient(Protocol):
    """Teacher collection 依赖的最小结构化调用协议。"""

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        temperature: float = 0.0,
    ) -> TeacherResponse: ...


class OpenAICompatibleTeacherClient:
    """把注入的 OpenAI-style SDK client 适配为 TeacherClient。"""

    def __init__(
        self,
        route: TeacherRouteSnapshot,
        *,
        client: Any,
        sensitive_values: tuple[str, ...] = (),
    ) -> None:
        self._route = route
        self._client = client
        self._sensitive_values = tuple(value for value in sensitive_values if value)

    @classmethod
    def from_route(
        cls,
        route: TeacherRouteSnapshot,
        api_key: str,
    ) -> OpenAICompatibleTeacherClient:
        """延迟导入可选 SDK 并创建 production transport；不发起请求。"""
        try:
            from openai import OpenAI
        except ImportError:
            msg = "未安装 teacher 可选依赖，请使用 uv sync --extra teacher"
            raise TeacherClientError(msg) from None

        try:
            client = OpenAI(base_url=route.base_url, api_key=api_key)
        except Exception as error:
            message = _redact_error(str(error), (api_key,))
            raise TeacherClientError(message) from None
        return cls(route, client=client, sensitive_values=(api_key,))

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        temperature: float = 0.0,
    ) -> TeacherResponse:
        try:
            raw_response = self._client.chat.completions.create(
                model=self._route.model,
                messages=messages,
                tools=tools,
                temperature=temperature,
                extra_body=self._route.extra_body,
            )
        except Exception as error:
            message = _redact_error(str(error), self._sensitive_values)
            raise TeacherClientError(message, retryable=_classify_retryable(error)) from None

        try:
            return _normalize_response(raw_response)
        except TeacherClientError:
            raise
        except Exception:
            msg = "teacher response 结构无效"
            raise TeacherClientError(msg) from None


def _normalize_response(raw_response: Any) -> TeacherResponse:
    choices = getattr(raw_response, "choices", None)
    if not isinstance(choices, (list, tuple)) or not choices:
        msg = "teacher response 缺少 choices"
        raise TeacherClientError(msg)

    message = getattr(choices[0], "message", None)
    if message is None:
        msg = "teacher response choice 缺少 message"
        raise TeacherClientError(msg)

    content = getattr(message, "content", None)
    if content is not None and not isinstance(content, str):
        msg = "teacher response content 类型无效"
        raise TeacherClientError(msg)

    raw_tool_calls = getattr(message, "tool_calls", None)
    tool_calls = () if raw_tool_calls is None else _normalize_tool_calls(raw_tool_calls)
    model = getattr(raw_response, "model", None)
    if not isinstance(model, str) or not model:
        msg = "teacher response 缺少实际 model"
        raise TeacherClientError(msg)

    response_id = getattr(raw_response, "id", None)
    if response_id is not None and not isinstance(response_id, str):
        msg = "teacher response id 类型无效"
        raise TeacherClientError(msg)
    system_fingerprint = getattr(raw_response, "system_fingerprint", None)
    if system_fingerprint is not None and not isinstance(system_fingerprint, str):
        msg = "teacher response system_fingerprint 类型无效"
        raise TeacherClientError(msg)

    return TeacherResponse(
        response_id=response_id,
        content=content,
        tool_calls=tool_calls,
        model=model,
        system_fingerprint=system_fingerprint,
        usage=_normalize_usage(getattr(raw_response, "usage", None)),
    )


def _normalize_tool_calls(raw_tool_calls: Any) -> tuple[ToolCall, ...]:
    if not isinstance(raw_tool_calls, (list, tuple)):
        msg = "teacher response tool_calls 类型无效"
        raise TeacherClientError(msg)
    normalized: list[ToolCall] = []
    for raw_call in raw_tool_calls:
        function = getattr(raw_call, "function", None)
        name = getattr(function, "name", None)
        arguments_json = getattr(function, "arguments", None)
        call_id = getattr(raw_call, "id", None)
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(arguments_json, str)
            or (call_id is not None and not isinstance(call_id, str))
        ):
            msg = "teacher response tool call 结构无效"
            raise TeacherClientError(msg)
        try:
            arguments = json.loads(
                arguments_json,
                parse_constant=lambda _: _reject_json_constant(),
            )
        except (json.JSONDecodeError, TypeError, ValueError, RecursionError):
            msg = "teacher response tool arguments 不是有限 JSON object"
            raise TeacherClientError(msg) from None
        if not isinstance(arguments, dict):
            msg = "teacher response tool arguments 不是有限 JSON object"
            raise TeacherClientError(msg)
        try:
            normalized.append(ToolCall(name=name, arguments=arguments, call_id=call_id))
        except ValidationError:
            msg = "teacher response tool arguments 不是有限 JSON object"
            raise TeacherClientError(msg) from None
    return tuple(normalized)


def _normalize_usage(raw_usage: Any) -> TeacherUsage | None:
    if raw_usage is None:
        return None
    values = {
        "prompt_tokens": getattr(raw_usage, "prompt_tokens", None),
        "completion_tokens": getattr(raw_usage, "completion_tokens", None),
        "total_tokens": getattr(raw_usage, "total_tokens", None),
    }
    try:
        return TeacherUsage.model_validate(values)
    except ValidationError:
        msg = "teacher response usage 结构无效"
        raise TeacherClientError(msg) from None


def _classify_retryable(error: Exception) -> bool:
    """Duck-type against the openai SDK's exception shape without importing it.

    Retryable: request timeouts, connection failures, rate limits, and 5xx.
    Never retryable: auth/schema/other 4xx and any unrecognized error.
    """
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int) and status_code in _RETRYABLE_STATUS_CODES:
        return True
    return type(error).__name__ in _RETRYABLE_ERROR_CLASS_NAMES


def _reject_json_constant() -> None:
    msg = "JSON constant 不允许"
    raise ValueError(msg)


def _redact_error(message: str, sensitive_values: tuple[str, ...]) -> str:
    redacted = message
    for value in sensitive_values:
        redacted = redacted.replace(value, "[REDACTED]")
    redacted = re.sub(
        r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+",
        r"\1[REDACTED]",
        redacted,
    )
    redacted = re.sub(
        r"(?i)\bbearer\s+[^\s,;]+",
        "Bearer [REDACTED]",
        redacted,
    )
    redacted = re.sub(
        r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+",
        r"\1[REDACTED]",
        redacted,
    )
    return redacted or "teacher client 请求失败"
