"""Qwen3 Transformers 推理后端与 Policy 适配。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Protocol

from veritool_rl.agent.parser import parse_qwen_response
from veritool_rl.agent.policy import PolicyOutput
from veritool_rl.envs.base import ToolSchema
from veritool_rl.trajectory.schema import StrictModel


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
        max_new_tokens = config.get("max_new_tokens", 256)
        if not isinstance(max_new_tokens, int) or max_new_tokens < 1:
            msg = "policy.max_new_tokens 必须是正整数"
            raise ValueError(msg)
        adapter_value = config.get("adapter_path")
        if adapter_value is not None and not isinstance(adapter_value, str):
            msg = "policy.adapter_path 必须是路径字符串"
            raise ValueError(msg)
        backend = TransformersBackend.from_pretrained(model_name, adapter_value)
        return cls(backend, model_name, max_new_tokens, adapter_value)


class TransformersBackend:
    """延迟导入重依赖的单卡 Transformers 生成实现。"""

    def __init__(self, model: Any, tokenizer: Any) -> None:
        self._model = model
        self._tokenizer = tokenizer

    @classmethod
    def from_pretrained(
        cls,
        model_name: str,
        adapter_path: str | None,
    ) -> TransformersBackend:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        bitsandbytes_config: Any = BitsAndBytesConfig
        quantization = bitsandbytes_config(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
        model: Any = AutoModelForCausalLM.from_pretrained(
            model_name,
            quantization_config=quantization,
            dtype=torch.bfloat16,
            device_map={"": "cuda:0"},
            low_cpu_mem_usage=True,
        )
        if adapter_path is not None:
            path = Path(adapter_path)
            if not path.exists():
                raise FileNotFoundError(path)
            from peft import PeftModel

            model = PeftModel.from_pretrained(model, str(path))
        model.eval()
        return cls(model, tokenizer)

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
            enable_thinking=False,
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
                do_sample=False,
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
