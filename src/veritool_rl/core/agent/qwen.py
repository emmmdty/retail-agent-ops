"""Qwen3 Transformers 推理后端与 Policy 适配。"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import ConfigDict, Field

from veritool_rl.core.agent.parser import parse_qwen_response
from veritool_rl.core.agent.policy import PolicyOutput
from veritool_rl.core.envs.base import ToolSchema
from veritool_rl.core.paths import validate_project_relative_path
from veritool_rl.core.trajectory.schema import StrictModel

_MODEL_FILE_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_REVISION_PATTERN = re.compile(r"^[0-9a-f]{7,64}$")
_HASH_CHUNK_SIZE = 1024 * 1024


class GeneratedText(StrictModel):
    """生成后端返回的文本及资源计数。"""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0


class GenerationBackend(Protocol):
    """QwenPolicy 可替换的文本生成边界。"""

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_new_tokens: int,
    ) -> GeneratedText:
        ...


class GenerationSettings(StrictModel):
    """正式评测冻结的确定性生成契约；不开放采样/思考/其他量化。"""

    model_config = ConfigDict(frozen=True)

    max_new_tokens: int = Field(default=256, ge=1, le=4096)
    do_sample: Literal[False] = False
    enable_thinking: Literal[False] = False
    quantization: Literal["nf4"] = "nf4"


class GpuMeasurement(StrictModel):
    """一次运行结束时记录的物理 GPU 身份与显存峰值。"""

    model_config = ConfigDict(frozen=True)

    gpu_index: int = Field(ge=0)
    gpu_uuid: str = Field(pattern=r"^GPU-[0-9A-Za-z-]{8,}$")
    gpu_name: str = Field(min_length=1)
    cuda_visible_devices: str = Field(min_length=1)
    cuda_device: str = Field(pattern=r"^cuda:\d+$")
    peak_memory_bytes: int = Field(ge=0)


class HardwareProvider(Protocol):
    """可注入的硬件测量边界；CPU 测试用 fake 实现替换。"""

    def reset_peak_memory(self) -> None:
        ...

    def measure(self) -> GpuMeasurement:
        ...


class CudaHardwareProvider:
    """真实单卡测量实现；torch 只在方法内部按需导入。"""

    def __init__(self, device_ordinal: int = 0) -> None:
        if device_ordinal < 0:
            msg = "device_ordinal 不得为负数"
            raise ValueError(msg)
        self._ordinal = device_ordinal

    def reset_peak_memory(self) -> None:
        import torch

        torch.cuda.reset_peak_memory_stats(self._ordinal)

    def measure(self) -> GpuMeasurement:
        import torch

        visible = os.environ.get("CUDA_VISIBLE_DEVICES", "")
        gpu_index = self._physical_index(visible)
        properties: Any = torch.cuda.get_device_properties(self._ordinal)
        raw_uuid = str(getattr(properties, "uuid", "")).strip()
        if not raw_uuid:
            msg = "CUDA 设备未提供 UUID，无法记录物理 GPU 身份"
            raise ValueError(msg)
        return GpuMeasurement(
            gpu_index=gpu_index,
            gpu_uuid=raw_uuid if raw_uuid.startswith("GPU-") else f"GPU-{raw_uuid}",
            gpu_name=str(properties.name),
            cuda_visible_devices=visible or "unset",
            cuda_device=f"cuda:{self._ordinal}",
            peak_memory_bytes=int(torch.cuda.max_memory_allocated(self._ordinal)),
        )

    def _physical_index(self, visible: str) -> int:
        """把逻辑 ordinal 映射回 CUDA_VISIBLE_DEVICES 指定的物理编号。"""
        if not visible:
            return self._ordinal
        entries = [entry.strip() for entry in visible.split(",") if entry.strip()]
        if self._ordinal >= len(entries):
            msg = "device_ordinal 超出 CUDA_VISIBLE_DEVICES 范围"
            raise ValueError(msg)
        entry = entries[self._ordinal]
        if not entry.isdigit():
            msg = "CUDA_VISIBLE_DEVICES 必须使用数字物理索引才能记录 GPU 身份"
            raise ValueError(msg)
        return int(entry)


def hash_local_model_files(model_dir: Path, filenames: Sequence[str]) -> dict[str, str]:
    """逐个哈希锁定的本地模型文件；不导入 torch/transformers，可在 CPU 上使用。"""
    return {name: _sha256_model_file(model_dir, name) for name in sorted(set(filenames))}


def verify_local_model_files(model_dir: Path, expected_sha256: Mapping[str, str]) -> None:
    """核对锁定模型文件集合与逐文件 SHA-256，检测替换、增删和篡改。

    只忽略点号开头的条目（下载工具的缓存/元数据）；其余任何未列入清单的
    文件、子目录或符号链接都会导致失败，避免注入额外权重或代码。
    """
    if not expected_sha256:
        msg = "模型文件哈希清单不得为空"
        raise ValueError(msg)
    for name in expected_sha256:
        _validate_model_file_name(name)
    try:
        present = sorted(
            entry.name for entry in model_dir.iterdir() if not entry.name.startswith(".")
        )
    except OSError:
        msg = f"模型文件目录不可读: {model_dir}"
        raise ValueError(msg) from None
    if present != sorted(expected_sha256):
        msg = "模型文件集合与锁定清单不一致"
        raise ValueError(msg)
    for name, expected in expected_sha256.items():
        if _sha256_model_file(model_dir, name) != expected:
            msg = f"模型文件 SHA-256 不匹配: {name}"
            raise ValueError(msg)


def _validate_model_file_name(name: str) -> str:
    if not name or name in {".", ".."} or _MODEL_FILE_PATTERN.fullmatch(name) is None:
        msg = f"模型文件名必须是安全的单一路径片段: {name!r}"
        raise ValueError(msg)
    return name


def _sha256_model_file(model_dir: Path, name: str) -> str:
    path = model_dir / _validate_model_file_name(name)
    try:
        status = path.lstat()
    except OSError:
        msg = f"模型文件不存在: {name}"
        raise ValueError(msg) from None
    if stat.S_ISLNK(status.st_mode):
        msg = f"模型文件不得是符号链接: {name}"
        raise ValueError(msg)
    if not stat.S_ISREG(status.st_mode):
        msg = f"模型文件必须是普通文件: {name}"
        raise ValueError(msg)
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(_HASH_CHUNK_SIZE):
                digest.update(chunk)
    except OSError:
        msg = f"模型文件无法读取: {name}"
        raise ValueError(msg) from None
    return digest.hexdigest()


class QwenPolicy:
    """将 Transformers 生成结果转换为 AgentRunner 的 PolicyOutput。"""

    def __init__(
        self,
        backend: GenerationBackend,
        model_name: str,
        max_new_tokens: int = 256,
        adapter_path: str | None = None,
    ) -> None:
        self._backend = backend
        self._max_new_tokens = max_new_tokens
        suffix = f"+{adapter_path}" if adapter_path else ""
        self.name = f"qwen:{model_name}{suffix}"

    def respond(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema],
    ) -> PolicyOutput:
        generated = self._backend.generate(
            messages,
            [tool.to_transformers() for tool in tools],
            self._max_new_tokens,
        )
        parsed = parse_qwen_response(generated.text)
        return parsed.model_copy(
            update={
                "latency_ms": generated.latency_ms,
                "input_tokens": generated.input_tokens,
                "output_tokens": generated.output_tokens,
            }
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> QwenPolicy:
        """按单卡 4-bit NF4 公平评测配置加载模型和可选 adapter。"""
        model_name = config.get("model_name")
        if not isinstance(model_name, str) or not model_name:
            msg = "policy.model_name 必须是非空字符串"
            raise ValueError(msg)
        validate_project_relative_path(model_name, "policy.model_name")
        max_new_tokens = config.get("max_new_tokens", 256)
        if not isinstance(max_new_tokens, int) or max_new_tokens < 1:
            msg = "policy.max_new_tokens 必须是正整数"
            raise ValueError(msg)
        adapter_value = config.get("adapter_path")
        if adapter_value is not None and not isinstance(adapter_value, str):
            msg = "policy.adapter_path 必须是路径字符串"
            raise ValueError(msg)
        if adapter_value is not None:
            validate_project_relative_path(adapter_value, "policy.adapter_path")
        backend = TransformersBackend.from_pretrained(model_name, adapter_value)
        return cls(backend, model_name, max_new_tokens, adapter_value)


class TransformersBackend:
    """延迟导入重依赖的单卡 Transformers 生成实现。"""

    def __init__(
        self,
        model: Any,
        tokenizer: Any,
        *,
        model_dir: Path | None = None,
        revision: str | None = None,
        adapter_path: str | None = None,
        settings: GenerationSettings | None = None,
    ) -> None:
        self._model = model
        self._tokenizer = tokenizer
        self.settings = settings or GenerationSettings()
        self.model_dir = model_dir
        self.revision = revision
        # 公开声明本实例真正加载了什么：正式评测据此拒绝与锁定不符的后端。
        # adapter_path 非 None 表示模型被 PEFT 包装过，不再是 base 模型。
        self.adapter_path = adapter_path

    @classmethod
    def from_pretrained(
        cls,
        model_name: str,
        adapter_path: str | None = None,
        *,
        revision: str | None = None,
        expected_file_sha256: Mapping[str, str] | None = None,
        settings: GenerationSettings | None = None,
    ) -> TransformersBackend:
        """按固定本地路径加载；给定 revision/文件哈希时先做防篡改校验。"""
        model_path = Path(model_name)
        if not model_path.is_dir():
            raise FileNotFoundError(model_path)
        if revision is not None and _REVISION_PATTERN.fullmatch(revision) is None:
            msg = f"模型 revision 必须是 7-64 位小写十六进制: {revision!r}"
            raise ValueError(msg)
        if expected_file_sha256 is not None:
            verify_local_model_files(model_path, expected_file_sha256)
        generation = settings or GenerationSettings()

        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        bitsandbytes_config: Any = BitsAndBytesConfig
        quantization = bitsandbytes_config(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
        tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        model: Any = AutoModelForCausalLM.from_pretrained(
            model_path,
            quantization_config=quantization,
            dtype=torch.bfloat16,
            device_map={"": "cuda:0"},
            low_cpu_mem_usage=True,
            local_files_only=True,
        )
        if adapter_path is not None:
            path = Path(adapter_path)
            if not path.is_dir():
                raise FileNotFoundError(path)
            from peft import PeftModel

            model = PeftModel.from_pretrained(
                model,
                str(path),
                local_files_only=True,
            )
        model.eval()
        return cls(
            model,
            tokenizer,
            model_dir=model_path,
            revision=revision,
            adapter_path=adapter_path,
            settings=generation,
        )

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_new_tokens: int,
    ) -> GeneratedText:
        import torch

        inputs = self._tokenizer.apply_chat_template(
            messages,
            tools=tools,
            add_generation_prompt=True,
            enable_thinking=self.settings.enable_thinking,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        ).to(self._model.device)
        input_length = int(inputs["input_ids"].shape[-1])
        started = time.perf_counter()
        with torch.inference_mode():
            output = self._model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=self.settings.do_sample,
                use_cache=True,
                pad_token_id=self._tokenizer.eos_token_id,
            )
        latency_ms = (time.perf_counter() - started) * 1000
        generated_ids = output[0][input_length:]
        text = self._tokenizer.decode(generated_ids, skip_special_tokens=False)
        return GeneratedText(
            text=text,
            input_tokens=input_length,
            output_tokens=int(generated_ids.shape[-1]),
            latency_ms=latency_ms,
        )
