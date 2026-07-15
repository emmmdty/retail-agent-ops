"""Qwen policy 的后端隔离与 Hermes 解析测试。"""

from __future__ import annotations

from typing import Any


def test_qwen_policy_passes_tools_and_records_usage() -> None:
    from veritool_rl.agent.qwen import GeneratedText, QwenPolicy
    from veritool_rl.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits

    class FakeBackend:
        def __init__(self) -> None:
            self.tools: list[dict[str, Any]] = []

        def generate(
            self,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
            max_new_tokens: int,
        ) -> GeneratedText:
            assert messages[-1]["role"] == "user"
            assert max_new_tokens == 256
            self.tools = tools
            return GeneratedText(
                text=(
                    '<tool_call>{"name":"get_order",'
                    '"arguments":{"order_id":"O-1"}}</tool_call><|im_end|>'
                ),
                input_tokens=41,
                output_tokens=17,
                latency_ms=12.5,
            )

    backend = FakeBackend()
    policy = QwenPolicy(backend=backend, model_name="Qwen/Qwen3-1.7B")
    task = build_mvp_task_splits(seed=0)["test"][0]
    tools = MiniRetailEnv(task).list_tools()

    output = policy.respond([{"role": "user", "content": "查询 O-1"}], tools)

    assert backend.tools[0]["type"] == "function"
    assert output.tool_call is not None
    assert output.tool_call.name == "get_order"
    assert output.input_tokens == 41
    assert output.output_tokens == 17
    assert output.latency_ms == 12.5


def test_qwen_policy_preserves_parser_error_and_usage() -> None:
    from veritool_rl.agent.qwen import GeneratedText, QwenPolicy

    class InvalidBackend:
        def generate(
            self,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
            max_new_tokens: int,
        ) -> GeneratedText:
            del messages, tools, max_new_tokens
            return GeneratedText(text="<tool_call>bad</tool_call>", output_tokens=3)

    output = QwenPolicy(InvalidBackend(), "Qwen/Qwen3-1.7B").respond([], [])

    assert output.parse_error == "invalid_tool_call_json"
    assert output.output_tokens == 3
