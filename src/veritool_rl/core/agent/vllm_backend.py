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

import os
import subprocess
import time
from pathlib import Path
from typing import Any

from veritool_rl.core.agent.qwen import GeneratedText, GenerationSettings, GpuMeasurement

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


class NvmlHardwareProvider:
    """vLLM 专用的硬件测量：读 NVML 而不是父进程的 torch CUDA 统计。

    **为什么 `CudaHardwareProvider` 在这里不能用**——两个理由，第二个才是关键：

    1. vLLM 把模型跑在**独立的 EngineCore 子进程**里，父进程从未初始化 CUDA 上下文，
       `torch.cuda.reset_peak_memory_stats(0)` 直接抛 `Invalid device argument`。
    2. 就算强行在父进程初始化，`max_memory_allocated` 量到的也是**父进程**的分配量
       ——对 vLLM 恒等于 0。把它写进证据是**一个假数**，比报错更糟。

    这里报的是 NVML 的整卡已用显存。它同样**不是**"这个模型要多少显存"：
    vLLM 按 `gpu_memory_utilization` **预先占住**一整块池子，而且这张卡是多人共用的，
    读数里含别人的进程。因此 `peak_memory_bytes` 在 vLLM 证据里只能读作
    "测量期间整卡的占用水位"，不能与 HF 那一侧的同名字段做比较。
    """

    def __init__(self, device_ordinal: int = 0) -> None:
        if device_ordinal < 0:
            msg = "device_ordinal 不得为负数"
            raise ValueError(msg)
        self._ordinal = device_ordinal

    def reset_peak_memory(self) -> None:
        """NVML 没有"峰值"概念可重置——不假装有。"""
        return

    def measure(self) -> GpuMeasurement:
        visible = os.environ.get("CUDA_VISIBLE_DEVICES", "")
        index, uuid, name, used_mib = self._query(self._physical_index(visible))
        return GpuMeasurement(
            gpu_index=index,
            gpu_uuid=uuid if uuid.startswith("GPU-") else f"GPU-{uuid}",
            gpu_name=name,
            cuda_visible_devices=visible or "unset",
            cuda_device=f"cuda:{self._ordinal}",
            peak_memory_bytes=used_mib * 1024 * 1024,
        )

    def _physical_index(self, visible: str) -> int:
        """与 `CudaHardwareProvider._physical_index` 同一套映射。

        `nvidia-smi` 报的是**物理**索引且不受 `CUDA_VISIBLE_DEVICES` 影响，
        所以直接拿逻辑 ordinal 去索引它的输出，在 `CUDA_VISIBLE_DEVICES=1` 时会记错卡
        ——证据里的 GPU 身份就成了假的。
        """
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

    def _query(self, physical_index: int) -> tuple[int, str, str, int]:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,uuid,name,memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in completed.stdout.splitlines():
            if not line.strip():
                continue
            index, uuid, name, used = (part.strip() for part in line.split(","))
            if int(index) == physical_index:
                return int(index), uuid, name, int(used)
        msg = f"nvidia-smi 没有报告物理 GPU {physical_index}"
        raise ValueError(msg)
