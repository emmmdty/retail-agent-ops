"""OpenAI-compatible teacher client 的结构化传译与脱敏测试。"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

import pytest

from veritool_rl.retail_ops.teacher_client import (
    OpenAICompatibleTeacherClient,
    TeacherClientError,
)
from veritool_rl.retail_ops.teacher_route import load_teacher_route

API_KEY = "teacher-api-key-material"


def _route():  # type: ignore[no-untyped-def]
    return load_teacher_route(
        {
            "TEACHER_LLM_PROVIDER": "fake",
            "TEACHER_LLM_FAKE_BASE_URL": "https://teacher.example.test/v1",
            "TEACHER_LLM_FAKE_API_KEY": API_KEY,
            "TEACHER_LLM_FAKE_MODEL": "teacher-model",
            "TEACHER_LLM_FAKE_EXTRA_BODY_JSON": (
                '{"thinking":{"type":"disabled"},"metadata":{"mode":"test"}}'
            ),
        }
    )


def _response(
    *,
    arguments: str = '{"order_id":"O-1"}',
    usage: Any = None,
) -> SimpleNamespace:
    if usage is None:
        usage = SimpleNamespace(prompt_tokens=17, completion_tokens=5, total_tokens=22)
    return SimpleNamespace(
        id="completion-1",
        model="teacher-model-20260722",
        system_fingerprint="fp-runtime-1",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call-1",
                            function=SimpleNamespace(
                                name="get_order",
                                arguments=arguments,
                            ),
                        )
                    ],
                )
            )
        ],
        usage=usage,
    )


class _FakeCompletions:
    def __init__(self, result: object) -> None:
        self._result = result
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result


class _FakeOpenAIClient:
    def __init__(self, result: object) -> None:
        self.completions = _FakeCompletions(result)
        self.chat = SimpleNamespace(completions=self.completions)


def test_client_translates_request_and_normalizes_tool_call_and_usage() -> None:
    route, _ = _route()
    fake = _FakeOpenAIClient(_response())
    client = OpenAICompatibleTeacherClient(route, client=fake)
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "查询订单"},
    ]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_order",
                "description": "查询订单",
                "parameters": {
                    "type": "object",
                    "properties": {"order_id": {"type": "string"}},
                    "required": ["order_id"],
                    "additionalProperties": False,
                },
            },
        }
    ]

    response = client.complete(messages, tools, temperature=0.0)

    assert fake.completions.calls == [
        {
            "model": "teacher-model",
            "messages": messages,
            "tools": tools,
            "temperature": 0.0,
            "extra_body": {
                "metadata": {"mode": "test"},
                "thinking": {"type": "disabled"},
            },
        }
    ]
    assert response.response_id == "completion-1"
    assert response.content is None
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "get_order"
    assert response.tool_calls[0].arguments == {"order_id": "O-1"}
    assert response.tool_calls[0].call_id == "call-1"
    assert response.model == "teacher-model-20260722"
    assert response.system_fingerprint == "fp-runtime-1"
    assert response.usage is not None
    assert response.usage.prompt_tokens == 17
    assert response.usage.completion_tokens == 5
    assert response.usage.total_tokens == 22


def test_absent_usage_remains_none() -> None:
    route, _ = _route()
    raw = _response()
    del raw.usage
    client = OpenAICompatibleTeacherClient(route, client=_FakeOpenAIClient(raw))

    response = client.complete([], [], temperature=0.0)

    assert response.usage is None


@pytest.mark.parametrize(
    "raw_response",
    [
        SimpleNamespace(
            id="missing-choices",
            model="model",
            system_fingerprint=None,
            usage=None,
        ),
        SimpleNamespace(
            id="empty-choices",
            model="model",
            system_fingerprint=None,
            choices=[],
            usage=None,
        ),
    ],
)
def test_missing_or_empty_choices_are_rejected(raw_response: object) -> None:
    route, _ = _route()
    client = OpenAICompatibleTeacherClient(route, client=_FakeOpenAIClient(raw_response))

    with pytest.raises(TeacherClientError, match="choices"):
        client.complete([], [], temperature=0.0)


@pytest.mark.parametrize(
    "arguments",
    ["not-json", "[]", "null", '{"order_id":NaN}', "[" * 4000 + "]" * 4000],
)
def test_malformed_tool_arguments_are_rejected(arguments: str) -> None:
    route, _ = _route()
    client = OpenAICompatibleTeacherClient(
        route,
        client=_FakeOpenAIClient(_response(arguments=arguments)),
    )

    with pytest.raises(TeacherClientError, match="tool arguments"):
        client.complete([], [], temperature=0.0)


def test_sdk_errors_redact_key_authorization_and_bearer_values() -> None:
    route, _ = _route()
    raw_error = RuntimeError(
        f"request failed api_key={API_KEY}; Authorization: Bearer auth-token-value; "
        "Bearer standalone-token"
    )
    client = OpenAICompatibleTeacherClient(
        route,
        client=_FakeOpenAIClient(raw_error),
        sensitive_values=(API_KEY,),
    )

    with pytest.raises(TeacherClientError) as error:
        client.complete([], [], temperature=0.0)

    rendered = f"{error.value!r}\n{error.value}"
    assert API_KEY not in rendered
    assert "auth-token-value" not in rendered
    assert "standalone-token" not in rendered
    assert "Bearer [REDACTED]" in rendered


@pytest.mark.parametrize(
    "error_factory",
    [
        lambda: type("RateLimitError", (RuntimeError,), {"status_code": 429})("rl"),
        lambda: type("InternalServerError", (RuntimeError,), {"status_code": 500})("500"),
        lambda: type("BadGateway", (RuntimeError,), {"status_code": 502})("502"),
        lambda: type("APITimeoutError", (RuntimeError,), {})("timeout"),
        lambda: type("APIConnectionError", (RuntimeError,), {})("conn"),
    ],
)
def test_transport_errors_are_marked_retryable(error_factory: Any) -> None:
    route, _ = _route()
    client = OpenAICompatibleTeacherClient(route, client=_FakeOpenAIClient(error_factory()))

    with pytest.raises(TeacherClientError) as error:
        client.complete([], [], temperature=0.0)

    assert error.value.retryable is True


@pytest.mark.parametrize(
    "error_factory",
    [
        lambda: type("AuthenticationError", (RuntimeError,), {"status_code": 401})("auth"),
        lambda: type("BadRequestError", (RuntimeError,), {"status_code": 400})("bad"),
        lambda: type("NotFoundError", (RuntimeError,), {"status_code": 404})("nf"),
        lambda: RuntimeError("generic failure"),
    ],
)
def test_non_transport_errors_are_not_retryable(error_factory: Any) -> None:
    route, _ = _route()
    client = OpenAICompatibleTeacherClient(route, client=_FakeOpenAIClient(error_factory()))

    with pytest.raises(TeacherClientError) as error:
        client.complete([], [], temperature=0.0)

    assert error.value.retryable is False


def test_production_factory_lazy_imports_sdk_without_making_a_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route, api_key = _route()
    constructor_calls: list[dict[str, str]] = []
    fake_sdk_client = _FakeOpenAIClient(_response())

    def fake_openai(**kwargs: str) -> _FakeOpenAIClient:
        constructor_calls.append(kwargs)
        return fake_sdk_client

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=fake_openai))

    client = OpenAICompatibleTeacherClient.from_route(route, api_key)

    assert constructor_calls == [{"base_url": route.base_url, "api_key": API_KEY}]
    assert fake_sdk_client.completions.calls == []
    assert API_KEY not in repr(client)
