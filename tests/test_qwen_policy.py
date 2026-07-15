"""Qwen policy 的后端隔离与 Hermes 解析测试。"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


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
    policy = QwenPolicy(backend=backend, model_name="models/Qwen3-1.7B")
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

    output = QwenPolicy(InvalidBackend(), "models/Qwen3-1.7B").respond([], [])

    assert output.parse_error == "invalid_tool_call_json"
    assert output.output_tokens == 3


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_name", "/data/TJK/models/Qwen3-1.7B"),
        ("adapter_path", "../other-run/adapter"),
    ],
)
def test_qwen_policy_config_rejects_non_project_relative_paths(
    field: str,
    value: str,
) -> None:
    from veritool_rl.agent.qwen import QwenPolicy

    config = {"model_name": "models/Qwen3-1.7B", field: value}

    with pytest.raises(ValueError, match="项目相对路径"):
        QwenPolicy.from_config(config)


def test_transformers_backend_requires_local_model_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from veritool_rl.agent.qwen import TransformersBackend

    monkeypatch.chdir(tmp_path)

    with pytest.raises(FileNotFoundError, match="models/Qwen3-1.7B"):
        TransformersBackend.from_pretrained("models/Qwen3-1.7B", None)


def test_transformers_backend_forces_local_files_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from veritool_rl.agent.qwen import TransformersBackend

    tokenizer_kwargs: dict[str, Any] = {}
    model_kwargs: dict[str, Any] = {}

    class FakeTokenizer:
        pad_token = None
        eos_token = "eos"

    class FakeModel:
        def eval(self) -> None:
            return None

    class FakeAutoTokenizer:
        @classmethod
        def from_pretrained(cls, path: Path, **kwargs: Any) -> FakeTokenizer:
            del cls, path
            tokenizer_kwargs.update(kwargs)
            return FakeTokenizer()

    class FakeAutoModel:
        @classmethod
        def from_pretrained(cls, path: Path, **kwargs: Any) -> FakeModel:
            del cls, path
            model_kwargs.update(kwargs)
            return FakeModel()

    transformers = ModuleType("transformers")
    transformers.AutoTokenizer = FakeAutoTokenizer  # type: ignore[attr-defined]
    transformers.AutoModelForCausalLM = FakeAutoModel  # type: ignore[attr-defined]
    transformers.BitsAndBytesConfig = lambda **kwargs: kwargs  # type: ignore[attr-defined]
    torch = ModuleType("torch")
    torch.bfloat16 = object()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    monkeypatch.setitem(sys.modules, "torch", torch)
    model_path = tmp_path / "model"
    model_path.mkdir()

    TransformersBackend.from_pretrained(str(model_path), None)

    assert tokenizer_kwargs["local_files_only"] is True
    assert model_kwargs["local_files_only"] is True
