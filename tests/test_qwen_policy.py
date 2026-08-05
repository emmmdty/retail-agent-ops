"""Qwen policy 的后端隔离与 Hermes 解析测试。"""

from __future__ import annotations

import hashlib
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


def _install_fake_transformers(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """安装最小 fake transformers/torch，避免 CPU 测试加载真实依赖。"""
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
    return tokenizer_kwargs, model_kwargs


def _write_model_dir(tmp_path: Path) -> Path:
    model_path = tmp_path / "model"
    model_path.mkdir()
    (model_path / "config.json").write_text('{"model_type":"qwen3"}', encoding="utf-8")
    (model_path / "model.safetensors").write_bytes(b"pinned-weights")
    return model_path


def test_hash_local_model_files_matches_manual_digest(tmp_path: Path) -> None:
    from veritool_rl.agent.qwen import hash_local_model_files

    model_path = _write_model_dir(tmp_path)

    hashes = hash_local_model_files(model_path, ("config.json", "model.safetensors"))

    assert hashes == {
        "config.json": hashlib.sha256(b'{"model_type":"qwen3"}').hexdigest(),
        "model.safetensors": hashlib.sha256(b"pinned-weights").hexdigest(),
    }


def test_verify_local_model_files_detects_every_tamper_shape(tmp_path: Path) -> None:
    from veritool_rl.agent.qwen import hash_local_model_files, verify_local_model_files

    model_path = _write_model_dir(tmp_path)
    pinned = hash_local_model_files(model_path, ("config.json", "model.safetensors"))

    verify_local_model_files(model_path, pinned)

    with pytest.raises(ValueError, match="模型文件"):
        verify_local_model_files(model_path, {})
    with pytest.raises(ValueError, match="模型文件"):
        verify_local_model_files(model_path, {**pinned, "../escape.json": "ab" * 32})
    with pytest.raises(ValueError, match="模型文件"):
        verify_local_model_files(model_path, {**pinned, "config.json": "ab" * 32})
    with pytest.raises(ValueError, match="模型文件"):
        verify_local_model_files(tmp_path / "missing", pinned)

    (model_path / "extra.bin").write_bytes(b"injected")
    with pytest.raises(ValueError, match="模型文件"):
        verify_local_model_files(model_path, pinned)
    (model_path / "extra.bin").unlink()

    (model_path / "config.json").unlink()
    with pytest.raises(ValueError, match="模型文件"):
        verify_local_model_files(model_path, pinned)


def test_verify_local_model_files_rejects_symlinked_weights(tmp_path: Path) -> None:
    from veritool_rl.agent.qwen import hash_local_model_files, verify_local_model_files

    model_path = _write_model_dir(tmp_path)
    pinned = hash_local_model_files(model_path, ("config.json", "model.safetensors"))
    outside = tmp_path / "outside.safetensors"
    (model_path / "model.safetensors").rename(outside)
    (model_path / "model.safetensors").symlink_to(outside)

    with pytest.raises(ValueError, match="模型文件"):
        verify_local_model_files(model_path, pinned)


def test_transformers_backend_verifies_pins_before_loading_weights(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from veritool_rl.agent.qwen import (
        GenerationSettings,
        TransformersBackend,
        hash_local_model_files,
        verify_local_model_files,
    )

    _, model_kwargs = _install_fake_transformers(monkeypatch)
    model_path = _write_model_dir(tmp_path)
    pinned = hash_local_model_files(model_path, ("config.json", "model.safetensors"))
    (model_path / "model.safetensors").write_bytes(b"swapped-weights")

    with pytest.raises(ValueError, match="模型文件"):
        TransformersBackend.from_pretrained(
            str(model_path),
            None,
            revision="a" * 40,
            expected_file_sha256=pinned,
        )
    assert model_kwargs == {}

    refreshed = hash_local_model_files(model_path, ("config.json", "model.safetensors"))
    backend = TransformersBackend.from_pretrained(
        str(model_path),
        None,
        revision="a" * 40,
        expected_file_sha256=refreshed,
    )

    assert backend.revision == "a" * 40
    assert backend.model_dir == model_path
    assert backend.adapter_path is None
    assert backend.settings == GenerationSettings()
    assert model_kwargs["local_files_only"] is True
    verify_local_model_files(model_path, refreshed)


def test_transformers_backend_publishes_the_adapter_it_actually_loaded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """加载了 adapter 的后端必须如实声明，正式 base 评测据此拒绝它。"""
    from veritool_rl.agent.qwen import TransformersBackend

    _install_fake_transformers(monkeypatch)
    model_path = _write_model_dir(tmp_path)
    adapter_path = tmp_path / "adapter"
    adapter_path.mkdir()

    class FakePeftModel:
        @classmethod
        def from_pretrained(cls, model: Any, path: str, **kwargs: Any) -> Any:
            del cls, path, kwargs
            return model

    peft = ModuleType("peft")
    peft.PeftModel = FakePeftModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "peft", peft)

    backend = TransformersBackend.from_pretrained(str(model_path), str(adapter_path))

    assert backend.adapter_path == str(adapter_path)


def test_transformers_backend_rejects_malformed_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from veritool_rl.agent.qwen import TransformersBackend

    _install_fake_transformers(monkeypatch)
    model_path = _write_model_dir(tmp_path)

    with pytest.raises(ValueError, match="revision"):
        TransformersBackend.from_pretrained(str(model_path), None, revision="not-a-revision")


def test_cuda_hardware_provider_maps_physical_gpu_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from veritool_rl.agent.qwen import CudaHardwareProvider

    reset_calls: list[int] = []

    class FakeProperties:
        name = "NVIDIA GeForce RTX 5090"
        uuid = "8f6d3c21-4b5a-4c7d-9e10-2f3a4b5c6d7e"

    torch = ModuleType("torch")
    torch.cuda = ModuleType("torch.cuda")  # type: ignore[attr-defined]
    torch.cuda.is_available = lambda: True  # type: ignore[attr-defined]
    torch.cuda.get_device_properties = lambda index: FakeProperties()  # type: ignore[attr-defined]
    torch.cuda.max_memory_allocated = lambda index: 4_294_967_296  # type: ignore[attr-defined]
    torch.cuda.reset_peak_memory_stats = reset_calls.append  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "2,3")

    provider = CudaHardwareProvider(device_ordinal=1)
    provider.reset_peak_memory()
    measurement = provider.measure()

    assert reset_calls == [1]
    assert measurement.gpu_index == 3
    assert measurement.gpu_uuid == "GPU-8f6d3c21-4b5a-4c7d-9e10-2f3a4b5c6d7e"
    assert measurement.gpu_name == "NVIDIA GeForce RTX 5090"
    assert measurement.cuda_visible_devices == "2,3"
    assert measurement.cuda_device == "cuda:1"
    assert measurement.peak_memory_bytes == 4_294_967_296


def test_cuda_hardware_provider_reports_unset_visible_devices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from veritool_rl.agent.qwen import CudaHardwareProvider

    class FakeProperties:
        name = "NVIDIA GeForce RTX 4090"
        uuid = "GPU-11112222-3333-4444-5555-666677778888"

    torch = ModuleType("torch")
    torch.cuda = ModuleType("torch.cuda")  # type: ignore[attr-defined]
    torch.cuda.get_device_properties = lambda index: FakeProperties()  # type: ignore[attr-defined]
    torch.cuda.max_memory_allocated = lambda index: 0  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)

    measurement = CudaHardwareProvider().measure()

    assert measurement.gpu_index == 0
    assert measurement.cuda_visible_devices == "unset"
    assert measurement.gpu_uuid == "GPU-11112222-3333-4444-5555-666677778888"


@pytest.mark.parametrize(
    ("visible", "ordinal", "message"),
    [("GPU-8f6d3c21", 0, "CUDA_VISIBLE_DEVICES"), ("2,3", 5, "device_ordinal")],
)
def test_cuda_hardware_provider_rejects_unmappable_physical_identity(
    monkeypatch: pytest.MonkeyPatch,
    visible: str,
    ordinal: int,
    message: str,
) -> None:
    from veritool_rl.agent.qwen import CudaHardwareProvider

    torch = ModuleType("torch")
    torch.cuda = ModuleType("torch.cuda")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", visible)

    with pytest.raises(ValueError, match=message):
        CudaHardwareProvider(device_ordinal=ordinal).measure()

    with pytest.raises(ValueError, match="device_ordinal"):
        CudaHardwareProvider(device_ordinal=-1)


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
