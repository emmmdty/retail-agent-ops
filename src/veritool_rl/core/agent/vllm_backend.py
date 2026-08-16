"""vLLM 生成后端：与 `TransformersBackend` 可互换的另一个 `GenerationBackend` 实现。

**为什么它在仓库里，而 vLLM 不在 `uv.lock` 里。**
`uv_lock_sha256` 在 `SEALED_PAIRING_FIELDS` 内，把 vLLM 加进项目依赖会让全部已有
sealed 证据不可配对。但**运行**在另一个 venv 里并不需要改 `uv.lock`——项目代码是纯
Python，装了 vLLM 的那个 venv 把仓库放进 `sys.path` 即可。这个模块因此只在被显式
选用时才 `import vllm`，项目自身的 venv 永远不会碰到它。

**它刻意跑 NF4 而不是 bf16。** `GenerationSettings.quantization` 是冻结的
`Literal["nf4"]`，且 `_require_backend_matches_pin` 会逐字段比较后端声明的 settings
与评测契约。让 vLLM 也走 bitsandbytes NF4，契约一个字不用动，而且对照更纯：
**只有引擎这一个变量在变**。`docs/SERVING_FORM_COMPARISON.md` 第四档量的是
"bf16 + vLLM 能跑多快"（部署形态问题），这里量的是"换引擎会不会改变行为"
（正确性问题），两者是不同的问题，不要混用同一份读数。

**必须暴露 `model_dir` / `revision` / `adapter_path` / `settings` 四个属性**：
`_require_backend_matches_pin` 靠它们执行"证据里写的模型就是真正跑的模型"。
少一个都会让那条校验静默放过。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from veritool_rl.core.agent.qwen import GeneratedText, GenerationSettings

# 共享 GPU 上的克制值；限制 KV cache 因而影响批量吞吐，但评测是串行的。
DEFAULT_GPU_MEMORY_UTILIZATION = 0.35
DEFAULT_MAX_MODEL_LEN = 4096


class VllmBackend:
    """把 vLLM 的 `LLM.generate` 包成 `GenerationBackend`。"""

    def __init__(
        self,
        llm: Any,
        tokenizer: Any,
        *,
        model_dir: Path,
        revision: str | None = None,
        settings: GenerationSettings | None = None,
    ) -> None:
        self._llm = llm
        self._tokenizer = tokenizer
        self.settings = settings or GenerationSettings()
        self.model_dir = model_dir
        self.revision = revision
        # 合并版模型里没有 adapter。保持 None 是**语义正确**的：
        # dev base 通道要求它必须是 None，候选通道要求它非 None。
        self.adapter_path: str | None = None

    @classmethod
    def from_pretrained(
        cls,
        model_name: str,
        adapter_path: str | None = None,
        *,
        revision: str | None = None,
        settings: GenerationSettings | None = None,
        gpu_memory_utilization: float = DEFAULT_GPU_MEMORY_UTILIZATION,
        max_model_len: int = DEFAULT_MAX_MODEL_LEN,
    ) -> VllmBackend:
        model_path = Path(model_name)
        if not model_path.is_dir():
            raise FileNotFoundError(model_path)
        if adapter_path is not None:
            # 未实现优于假装支持：vLLM 的 LoRA 走 `LoRARequest` 而不是 PeftModel，
            # 且 `adapter_path` 必须能被 `_require_backend_matches_pin` 校验。
            # 在把那条路径实现并测试之前，这里必须硬失败。
            msg = "VllmBackend 暂不支持未合并的 adapter；请先用 merge_lora_adapter.py 合并"
            raise NotImplementedError(msg)
        generation = settings or GenerationSettings()
        if generation.quantization != "nf4":
            msg = f"评测契约冻结在 nf4，收到 {generation.quantization!r}"
            raise ValueError(msg)

        from vllm import LLM

        llm = LLM(
            model=str(model_path),
            dtype="bfloat16",
            # 与项目 HF 路径同为 NF4，这样"引擎"是唯一变量。
            quantization="bitsandbytes",
            gpu_memory_utilization=gpu_memory_utilization,
            max_model_len=max_model_len,
            enable_prefix_caching=True,
        )
        return cls(
            llm,
            llm.get_tokenizer(),
            model_dir=model_path,
            revision=revision,
            settings=generation,
        )

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_new_tokens: int,
    ) -> GeneratedText:
        from vllm import SamplingParams

        prompt = self._tokenizer.apply_chat_template(
            messages,
            tools=tools,
            add_generation_prompt=True,
            enable_thinking=self.settings.enable_thinking,
            tokenize=False,
        )
        sampling = SamplingParams(
            temperature=0.0,
            max_tokens=max_new_tokens,
            # 与 `TransformersBackend` 一致：parser 需要看到 `<|im_end|>`，
            # 而 vLLM 默认会剥掉它。不对齐这一项，两个后端的 `raw_text` 就不可比。
            skip_special_tokens=False,
        )
        started = time.perf_counter()
        outputs = self._llm.generate([prompt], sampling)
        latency_ms = (time.perf_counter() - started) * 1000
        completion = outputs[0].outputs[0]
        return GeneratedText(
            text=completion.text,
            input_tokens=len(outputs[0].prompt_token_ids),
            output_tokens=len(completion.token_ids),
            latency_ms=latency_ms,
        )
