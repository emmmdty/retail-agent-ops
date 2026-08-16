"""vLLM 后端：它必须在**不改任何评测契约**的前提下与 HF 后端可互换。

这份测试锁住四条性质，每一条都对应一个会静默产出错误证据的失败模式：

1. **暴露 `_require_backend_matches_pin` 需要的四个属性**——少一个，那条"证据里写的
   模型就是真正跑的模型"的校验就会静默放过；
2. **`adapter_path` 保持 `None`**——dev base 通道要求它是 None，一个乱填的值会让
   base 证据被当成候选证据（或反过来）；
3. **不接受未合并的 adapter**，硬失败而不是假装支持；
4. **`skip_special_tokens=False`**——vLLM 默认剥掉 `<|im_end|>`，而项目 parser 与
   `TransformersBackend` 都按"能看到它"工作，不对齐两个后端的 `raw_text` 不可比。

全部用假的 `vllm` 模块，**不需要 GPU 也不需要真装 vLLM**。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from veritool_rl.core.agent.qwen import GenerationSettings


def _install_fake_vllm(
    monkeypatch: pytest.MonkeyPatch,
    recorded: dict[str, Any],
    *,
    completion_text: str = "<tool_call>\n{}\n</tool_call><|im_end|>",
) -> None:
    class FakeTokenizer:
        def apply_chat_template(self, messages: Any, **kwargs: Any) -> str:
            recorded["template_kwargs"] = kwargs
            recorded["messages"] = messages
            return "PROMPT"

    class FakeLLM:
        def __init__(self, **kwargs: Any) -> None:
            recorded["llm_kwargs"] = kwargs

        def get_tokenizer(self) -> FakeTokenizer:
            return FakeTokenizer()

        def generate(self, prompts: list[str], sampling: Any) -> list[Any]:
            recorded["prompts"] = prompts
            recorded["sampling"] = sampling
            completion = SimpleNamespace(text=completion_text, token_ids=[1, 2, 3])
            return [SimpleNamespace(outputs=[completion], prompt_token_ids=[0] * 7)]

    def fake_sampling_params(**kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(**kwargs)

    vllm = ModuleType("vllm")
    vllm.LLM = FakeLLM  # type: ignore[attr-defined]
    vllm.SamplingParams = fake_sampling_params  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "vllm", vllm)


@pytest.fixture
def model_dir(tmp_path: Path) -> Path:
    path = tmp_path / "Qwen3-4B-merged"
    path.mkdir()
    return path


def test_it_exposes_everything_the_pin_check_reads(
    model_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_require_backend_matches_pin` 读这四个属性；缺任何一个都会让校验静默放过。"""
    from veritool_rl.core.agent.vllm_backend import VllmBackend

    recorded: dict[str, Any] = {}
    _install_fake_vllm(monkeypatch, recorded)
    settings = GenerationSettings(max_new_tokens=256)

    backend = VllmBackend.from_pretrained(
        str(model_dir), None, revision="8cd0101f", settings=settings
    )

    assert backend.model_dir == model_dir
    assert backend.revision == "8cd0101f"
    assert backend.adapter_path is None
    assert backend.settings == settings


def test_it_runs_nf4_so_the_frozen_contract_needs_no_change(
    model_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """契约冻结在 nf4。跑 bf16 就得改 Literal，那会让"引擎"不再是唯一变量。"""
    from veritool_rl.core.agent.vllm_backend import VllmBackend

    recorded: dict[str, Any] = {}
    _install_fake_vllm(monkeypatch, recorded)

    VllmBackend.from_pretrained(str(model_dir), None)

    assert recorded["llm_kwargs"]["quantization"] == "bitsandbytes"
    assert recorded["llm_kwargs"]["dtype"] == "bfloat16"


def test_it_keeps_special_tokens_so_raw_text_stays_comparable(
    model_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """vLLM 默认剥掉 `<|im_end|>`；不关掉它，两个后端的 raw_text 不可比。"""
    from veritool_rl.core.agent.vllm_backend import VllmBackend

    recorded: dict[str, Any] = {}
    _install_fake_vllm(monkeypatch, recorded)
    backend = VllmBackend.from_pretrained(str(model_dir), None)

    generated = backend.generate([{"role": "user", "content": "hi"}], [], 256)

    assert recorded["sampling"].skip_special_tokens is False
    assert recorded["sampling"].temperature == 0.0
    assert recorded["sampling"].max_tokens == 256
    assert generated.text.endswith("<|im_end|>")
    assert generated.input_tokens == 7
    assert generated.output_tokens == 3


def test_it_applies_the_same_chat_template_contract(
    model_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`enable_thinking` 与 `add_generation_prompt` 必须与 HF 路径一致。"""
    from veritool_rl.core.agent.vllm_backend import VllmBackend

    recorded: dict[str, Any] = {}
    _install_fake_vllm(monkeypatch, recorded)
    backend = VllmBackend.from_pretrained(str(model_dir), None)

    backend.generate([{"role": "user", "content": "hi"}], [{"name": "get_order"}], 256)

    assert recorded["template_kwargs"]["add_generation_prompt"] is True
    assert recorded["template_kwargs"]["enable_thinking"] is False
    assert recorded["template_kwargs"]["tokenize"] is False
    assert recorded["template_kwargs"]["tools"] == [{"name": "get_order"}]


def test_an_unmerged_adapter_is_rejected_rather_than_faked(
    model_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """vLLM 的 LoRA 走 LoRARequest，没实现之前必须硬失败，不能静默忽略。"""
    from veritool_rl.core.agent.vllm_backend import VllmBackend

    _install_fake_vllm(monkeypatch, {})

    with pytest.raises(NotImplementedError, match="merge_lora_adapter"):
        VllmBackend.from_pretrained(str(model_dir), "some/adapter")


def test_a_missing_model_directory_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from veritool_rl.core.agent.vllm_backend import VllmBackend

    _install_fake_vllm(monkeypatch, {})

    with pytest.raises(FileNotFoundError):
        VllmBackend.from_pretrained(str(tmp_path / "nope"), None)


# ---------------------------------------------------------------------------
# CLI 选路：vLLM 分支绝不能绕过模型文件校验
# ---------------------------------------------------------------------------


def test_the_vllm_branch_still_verifies_the_model_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`verify_local_model_files` 平时藏在 `TransformersBackend.from_pretrained` 里。

    vLLM 不走那个构造器，所以选路函数必须**显式**补上这一步；漏掉的话
    "证据里写的模型就是磁盘上那份"这条保证会在 vLLM 路径上静默消失。
    """
    import veritool_rl.product_cli as cli
    from veritool_rl.retail_ops.evaluate.base_evaluation import ModelArtifact
    from veritool_rl.retail_ops.evaluate.ood_evaluation import OodEvaluationConfig

    _install_fake_vllm(monkeypatch, {})
    models_root = tmp_path / "models"
    (models_root / "Qwen3-4B-merged").mkdir(parents=True)
    verified: list[tuple[Path, dict[str, str]]] = []
    monkeypatch.setattr(
        cli, "verify_local_model_files", lambda d, h: verified.append((d, dict(h)))
    )
    config = OodEvaluationConfig(
        model=ModelArtifact(
            repo="local/merged",
            revision="8cd0101f",
            local_dir="Qwen3-4B-merged",
            file_sha256={"config.json": "0" * 64},
        ),
        generation=GenerationSettings(max_new_tokens=256),
        code_commit="a" * 40,
    )

    backend = cli._ood_backend_for_engine("vllm")(config, models_root)

    assert verified == [(models_root / "Qwen3-4B-merged", {"config.json": "0" * 64})]
    assert backend.adapter_path is None
    assert backend.settings == config.generation


def test_the_default_engine_is_still_transformers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """默认引擎是全部已有证据的那条路径，不得因为新增选项而改变。"""
    import veritool_rl.product_cli as cli

    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        cli.TransformersBackend,
        "from_pretrained",
        classmethod(lambda cls, *a, **k: captured.update(args=a, kwargs=k)),
    )
    from veritool_rl.retail_ops.evaluate.base_evaluation import ModelArtifact
    from veritool_rl.retail_ops.evaluate.ood_evaluation import OodEvaluationConfig

    config = OodEvaluationConfig(
        model=ModelArtifact(
            repo="Qwen/Qwen3-4B",
            revision="8cd0101f",
            local_dir="Qwen3-4B-pinned",
            file_sha256={"config.json": "0" * 64},
        ),
        generation=GenerationSettings(max_new_tokens=256),
        code_commit="a" * 40,
    )

    cli._default_ood_backend(config, tmp_path / "models")

    assert captured["kwargs"]["expected_file_sha256"] == {"config.json": "0" * 64}


# ---------------------------------------------------------------------------
# 硬件测量：vLLM 的显存在子进程里，父进程的 torch 统计是假数
# ---------------------------------------------------------------------------


def _fake_nvidia_smi(monkeypatch: pytest.MonkeyPatch, stdout: str) -> None:
    import veritool_rl.core.agent.vllm_backend as module

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout=stdout, returncode=0),
    )


def test_it_records_the_physical_gpu_that_cuda_visible_devices_selects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """nvidia-smi 报物理索引且不受 CUDA_VISIBLE_DEVICES 影响。

    拿逻辑 ordinal 直接索引它的输出，在 `CUDA_VISIBLE_DEVICES=1` 时会把证据里的
    GPU 身份写成另一张卡——而 GPU 身份正是硬件溯源的全部意义。
    """
    from veritool_rl.core.agent.vllm_backend import NvmlHardwareProvider

    _fake_nvidia_smi(
        monkeypatch,
        "0, GPU-aaaaaaaa-1111, NVIDIA A, 100\n1, GPU-bbbbbbbb-2222, NVIDIA B, 2048\n",
    )
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "1")

    measurement = NvmlHardwareProvider(device_ordinal=0).measure()

    assert measurement.gpu_index == 1
    assert measurement.gpu_uuid == "GPU-bbbbbbbb-2222"
    assert measurement.gpu_name == "NVIDIA B"
    assert measurement.peak_memory_bytes == 2048 * 1024 * 1024


def test_reset_peak_memory_is_a_no_op_rather_than_a_torch_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """父进程从未初始化 CUDA 上下文，torch 那条路径会直接抛 Invalid device argument。"""
    from veritool_rl.core.agent.vllm_backend import NvmlHardwareProvider

    assert NvmlHardwareProvider().reset_peak_memory() is None


def test_an_absent_physical_gpu_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    from veritool_rl.core.agent.vllm_backend import NvmlHardwareProvider

    _fake_nvidia_smi(monkeypatch, "0, GPU-aaaaaaaa-1111, NVIDIA A, 100\n")
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "3")

    with pytest.raises(ValueError, match="没有报告物理 GPU 3"):
        NvmlHardwareProvider().measure()


def test_the_engine_also_selects_the_hardware_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """后端与硬件测量必须一起换。只换后端的话，证据里会带一个恒为 0 的显存假数。"""
    import veritool_rl.product_cli as cli
    from veritool_rl.core.agent.qwen import CudaHardwareProvider
    from veritool_rl.core.agent.vllm_backend import NvmlHardwareProvider

    assert isinstance(cli._hardware_provider_for_engine("vllm"), NvmlHardwareProvider)
    assert isinstance(cli._hardware_provider_for_engine("transformers"), CudaHardwareProvider)


def test_the_dev_base_channel_also_honours_the_engine_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """回归测试：`--engine` 最初只接进了 OOD 通道，dev 通道**静默**回落到 transformers。

    静默回落最坏：产出的证据看起来完全正常，却根本不是那个引擎跑出来的。
    """
    import veritool_rl.product_cli as cli
    from veritool_rl.core.agent.vllm_backend import VllmBackend
    from veritool_rl.retail_ops.evaluate.base_evaluation import (
        BaseEvaluationConfig,
        ModelArtifact,
    )

    _install_fake_vllm(monkeypatch, {})
    models_root = tmp_path / "models"
    (models_root / "Qwen3-4B-merged").mkdir(parents=True)
    monkeypatch.setattr(cli, "verify_local_model_files", lambda d, h: None)
    config = BaseEvaluationConfig(
        dataset_version="retail_ops_v1_r2_20260722",
        model=ModelArtifact(
            repo="local/merged",
            revision="8cd0101f",
            local_dir="Qwen3-4B-merged",
            file_sha256={"config.json": "0" * 64},
        ),
        generation=GenerationSettings(max_new_tokens=256),
        code_commit="a" * 40,
        uv_lock_sha256="b" * 64,
    )

    backend = cli._generation_backend_for_engine("vllm")(config, models_root)

    assert isinstance(backend, VllmBackend)
    assert backend.adapter_path is None
