"""QLoRA-SFT 配置解析测试，不在本地加载模型。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest


def test_resolve_sft_config_locks_mvp_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from veritool_rl.training.sft import resolve_sft_config

    monkeypatch.chdir(tmp_path)
    train_path = Path("train.jsonl")
    eval_path = Path("dev.jsonl")
    train_path.write_text("{}\n", encoding="utf-8")
    eval_path.write_text("{}\n", encoding="utf-8")
    config = {
        "model": _model_pin(),
        "lora": {
            "r": 16,
            "alpha": 32,
            "dropout": 0.05,
            "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj"],
        },
        "data": {"train_path": str(train_path), "eval_path": str(eval_path)},
        "training": {
            "epochs": 3,
            "batch_size": 2,
            "grad_accum": 8,
            "lr": 0.0002,
            "max_seq_len": 1024,
            "bf16": True,
            "gradient_checkpointing": True,
        },
    }

    resolved = resolve_sft_config(config, seed=7, output_dir=tmp_path / "run")

    assert resolved.model.name == "models/Qwen3-1.7B"
    assert resolved.training.max_seq_len == 1024
    assert resolved.training.assistant_only_loss is True
    assert resolved.seed == 7
    assert resolved.adapter_dir == tmp_path / "run/adapter"


def test_resolve_sft_config_rejects_missing_dataset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from veritool_rl.training.sft import resolve_sft_config

    monkeypatch.chdir(tmp_path)
    config = {
        "model": _model_pin(),
        "lora": {"target_modules": ["q_proj"]},
        "data": {
            "train_path": "missing-train.jsonl",
            "eval_path": "missing-dev.jsonl",
        },
        "training": {},
    }

    with pytest.raises(FileNotFoundError, match="missing-train"):
        resolve_sft_config(config, seed=0, output_dir=tmp_path / "run")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model", "/data/TJK/models/Qwen3-1.7B"),
        ("train_path", "/data/TJK/data/train.jsonl"),
        ("eval_path", "../shared/dev.jsonl"),
    ],
)
def test_resolve_sft_config_rejects_non_project_relative_paths(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    from pydantic import ValidationError

    from veritool_rl.training.sft import resolve_sft_config

    config = {
        "model": _model_pin(),
        "lora": {"target_modules": ["q_proj"]},
        "data": {"train_path": "train.jsonl", "eval_path": "dev.jsonl"},
        "training": {},
    }
    if field == "model":
        config["model"]["name"] = value
    else:
        config["data"][field] = value

    with pytest.raises(ValidationError, match="项目相对路径"):
        resolve_sft_config(config, seed=0, output_dir=tmp_path / "run")


def test_cuda_resource_metrics_report_wall_time_and_peak_memory() -> None:
    from veritool_rl.training.sft import _cuda_resource_metrics

    class FakeCuda:
        @staticmethod
        def current_device() -> int:
            return 0

        @staticmethod
        def max_memory_allocated() -> int:
            return 123

        @staticmethod
        def max_memory_reserved() -> int:
            return 456

    assert _cuda_resource_metrics(FakeCuda(), wall_time_seconds=12.5) == {
        "wall_time_seconds": 12.5,
        "logical_device": "cuda:0",
        "cuda_peak_allocated_bytes": 123,
        "cuda_peak_reserved_bytes": 456,
    }


def test_validate_tokenized_sft_rows_requires_assistant_only_suffix() -> None:
    from veritool_rl.training.sft import validate_tokenized_sft_rows

    rows = [
        {
            "task_id": "simple_python_0",
            "input_ids": [1, 2, 3, 4],
            "attention_mask": [1, 1, 1, 1],
            "labels": [-100, -100, 3, 4],
            "full_token_count": 4,
        }
    ]

    validate_tokenized_sft_rows(rows, max_seq_len=4)

    invalid_rows = [
        {
            **rows[0],
            "labels": [-100, 9, -100, 4],
        }
    ]
    with pytest.raises(ValueError, match="连续 suffix"):
        validate_tokenized_sft_rows(invalid_rows, max_seq_len=4)
    with pytest.raises(ValueError, match="超过 max_seq_len"):
        validate_tokenized_sft_rows(rows, max_seq_len=3)


def test_prepare_sft_rows_keeps_messages_format_for_mini_retail() -> None:
    from veritool_rl.training.sft import message_sft_runtime_options, prepare_sft_rows

    row = {
        "task_id": "train-lookup_status-0000",
        "scenario": "lookup_status",
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "question"},
            {"role": "assistant", "content": "answer"},
        ],
        "tools": [],
    }

    data_format, train_rows, eval_rows = prepare_sft_rows(
        [row],
        [row],
        max_seq_len=1024,
        train_limit=None,
        eval_limit=None,
    )

    assert data_format == "messages"
    assert train_rows == [row]
    assert eval_rows == [row]
    assert message_sft_runtime_options(max_seq_len=1024) == {
        "assistant_only_loss": True,
        "completion_only_loss": False,
        "max_length": 1024,
    }


def test_prepare_sft_rows_rejects_mixed_train_eval_formats() -> None:
    from veritool_rl.training.sft import prepare_sft_rows

    message_row = {
        "task_id": "message-row",
        "messages": [{"role": "assistant", "content": "answer"}],
        "tools": [],
    }
    tokenized_row = {
        "task_id": "tokenized-row",
        "input_ids": [1, 2],
        "attention_mask": [1, 1],
        "labels": [-100, 2],
        "full_token_count": 2,
    }

    with pytest.raises(ValueError, match="格式必须一致"):
        prepare_sft_rows(
            [message_row],
            [tokenized_row],
            max_seq_len=1024,
            train_limit=None,
            eval_limit=None,
        )


def test_select_longest_rows_for_smoke_is_deterministic() -> None:
    from veritool_rl.training.sft import select_longest_rows

    rows = [
        {"task_id": "b", "full_token_count": 10},
        {"task_id": "c", "full_token_count": 12},
        {"task_id": "a", "full_token_count": 12},
    ]

    selected = select_longest_rows(rows, limit=2)

    assert [row["task_id"] for row in selected] == ["a", "c"]


def test_resolve_sft_config_locks_smoke_scope_and_reload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from veritool_rl.training.sft import resolve_sft_config

    monkeypatch.chdir(tmp_path)
    Path("train.jsonl").write_text("{}\n", encoding="utf-8")
    Path("dev.jsonl").write_text("{}\n", encoding="utf-8")
    config = {
        "model": _model_pin(),
        "lora": {"target_modules": ["q_proj"]},
        "data": {
            "train_path": "train.jsonl",
            "eval_path": "dev.jsonl",
            "train_limit": 8,
            "eval_limit": 8,
        },
        "training": {
            "max_seq_len": 1152,
            "max_steps": 2,
            "smoke": True,
            "verify_adapter_reload": True,
        },
    }

    resolved = resolve_sft_config(config, seed=0, output_dir=tmp_path / "smoke")

    assert resolved.data.train_limit == 8
    assert resolved.training.max_steps == 2
    assert resolved.training.smoke is True
    assert resolved.training.verify_adapter_reload is True

    config["training"]["max_steps"] = 3
    with pytest.raises(ValueError, match="最多 2"):
        resolve_sft_config(config, seed=0, output_dir=tmp_path / "invalid")


def test_reload_adapter_offline_uses_base_and_saved_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from veritool_rl.core.agent.qwen import TransformersBackend
    from veritool_rl.training.sft import reload_adapter_offline

    model_path = tmp_path / "models/Qwen3-1.7B"
    adapter_path = tmp_path / "run/adapter"
    model_path.mkdir(parents=True)
    adapter_path.mkdir(parents=True)
    calls: list[tuple[str, str | None]] = []

    class FakeBackend:
        pass

    def fake_load(model_name: str, adapter_name: str | None) -> FakeBackend:
        calls.append((model_name, adapter_name))
        return FakeBackend()

    monkeypatch.setattr(TransformersBackend, "from_pretrained", fake_load)

    evidence = reload_adapter_offline(model_path, adapter_path)

    assert calls == [(str(model_path), str(adapter_path))]
    assert evidence["loaded"] is True
    assert evidence["model_path"] == str(model_path)
    assert evidence["adapter_path"] == str(adapter_path)
    assert evidence["local_files_only"] is True


def test_pretokenized_runtime_uses_explicit_labels_not_trl_auto_mask() -> None:
    from veritool_rl.training.sft import pretokenized_sft_runtime_options

    options = pretokenized_sft_runtime_options()

    assert options == {
        "assistant_only_loss": False,
        "completion_only_loss": False,
        "dataset_kwargs": {"skip_prepare_dataset": True},
        "max_length": None,
    }


def test_sft_output_guard_rejects_existing_training_artifacts(tmp_path: Path) -> None:
    from veritool_rl.training.sft import _ensure_new_training_output

    output_dir = tmp_path / "training"
    output_dir.mkdir()
    _ensure_new_training_output(output_dir)

    (output_dir / "metrics.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="拒绝覆盖"):
        _ensure_new_training_output(output_dir)


def _model_pin(model_dir: str = "models/Qwen3-1.7B") -> dict[str, object]:
    """SFT 模型 pin 的最小合法形状；具体摘要由各测试按需覆盖。"""
    return {
        "name": model_dir,
        "load_in_4bit": True,
        "revision": "8cd0101f70cac4f1efcebc979faf483558e39297",
        "file_sha256": {"config.json": "0" * 64},
    }


def test_resolve_sft_config_requires_model_provenance_pin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没有 revision/逐文件哈希的模型 pin 必须被拒绝，不允许无 provenance 训练。"""
    from pydantic import ValidationError

    from veritool_rl.training.sft import resolve_sft_config

    monkeypatch.chdir(tmp_path)
    Path("train.jsonl").write_text("{}\n", encoding="utf-8")
    Path("dev.jsonl").write_text("{}\n", encoding="utf-8")
    config: dict[str, object] = {
        "model": {"name": "models/Qwen3-1.7B", "load_in_4bit": True},
        "lora": {"target_modules": ["q_proj"]},
        "data": {"train_path": "train.jsonl", "eval_path": "dev.jsonl"},
        "training": {},
    }

    with pytest.raises(ValidationError):
        resolve_sft_config(config, seed=0, output_dir=tmp_path / "run")


def test_run_sft_rejects_model_dir_failing_hash_verification_before_any_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """训练必须先逐文件校验模型目录，且在任何产物落盘前失败。

    这条路径完全在 CPU 上跑：校验发生在 `import torch` 之前，因此本地没有
    CUDA/torch 也能证明被篡改的模型目录不会进入训练。
    """
    from veritool_rl.training.sft import run_sft

    monkeypatch.chdir(tmp_path)
    model_dir = Path("models/Qwen3-4B-pinned")
    model_dir.mkdir(parents=True)
    (model_dir / "config.json").write_text('{"tampered": true}', encoding="utf-8")
    Path("train.jsonl").write_text("{}\n", encoding="utf-8")
    Path("dev.jsonl").write_text("{}\n", encoding="utf-8")
    config: dict[str, object] = {
        "model": _model_pin(str(model_dir)),
        "lora": {"target_modules": ["q_proj"]},
        "data": {"train_path": "train.jsonl", "eval_path": "dev.jsonl"},
        "training": {},
    }
    output_dir = tmp_path / "run"

    with pytest.raises(ValueError, match="SHA-256"):
        run_sft(config, seed=0, output_dir=output_dir)

    assert not output_dir.exists()


def test_run_sft_rejects_unlisted_extra_file_in_model_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """清单外的额外文件（例如注入的权重或代码）同样必须阻断训练。"""
    import hashlib

    from veritool_rl.training.sft import run_sft

    monkeypatch.chdir(tmp_path)
    model_dir = Path("models/Qwen3-4B-pinned")
    model_dir.mkdir(parents=True)
    payload = b'{"hidden_size": 8}'
    (model_dir / "config.json").write_bytes(payload)
    (model_dir / "inject.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    Path("train.jsonl").write_text("{}\n", encoding="utf-8")
    Path("dev.jsonl").write_text("{}\n", encoding="utf-8")
    pin = _model_pin(str(model_dir))
    pin["file_sha256"] = {"config.json": hashlib.sha256(payload).hexdigest()}
    config: dict[str, object] = {
        "model": pin,
        "lora": {"target_modules": ["q_proj"]},
        "data": {"train_path": "train.jsonl", "eval_path": "dev.jsonl"},
        "training": {},
    }
    output_dir = tmp_path / "run"

    with pytest.raises(ValueError, match="锁定清单"):
        run_sft(config, seed=0, output_dir=output_dir)

    assert not output_dir.exists()


# ---------------------------------------------------------------------------
# Phase C1：训练随机源固定（方差治理）
# ---------------------------------------------------------------------------


class _FakeCudnn:
    def __init__(self) -> None:
        self.deterministic: bool | None = None
        self.benchmark: bool | None = None


class _FakeBackends:
    def __init__(self, cudnn: _FakeCudnn) -> None:
        self.cudnn = cudnn


class _FakeTorch:
    """记录 determinism 设置调用的最小 torch 替身。"""

    def __init__(self) -> None:
        self.cudnn = _FakeCudnn()
        self.backends = _FakeBackends(self.cudnn)
        self.manual_seeds: list[int] = []
        self.deterministic_calls: list[bool] = []

    def manual_seed(self, seed: int) -> None:
        self.manual_seeds.append(seed)

    def use_deterministic_algorithms(self, value: bool, *, warn_only: bool = False) -> None:
        self.deterministic_calls.append(value)


def test_configure_training_determinism_pins_every_consumable_source(
    monkeypatch: Any,
) -> None:
    """可消随机源必须全部固定：cuBLAS 工作区、torch/python/numpy 种子、cuDNN 旗标。"""
    import random

    import veritool_rl.training.sft as sft_module

    fake = _FakeTorch()
    monkeypatch.delenv("CUBLAS_WORKSPACE_CONFIG", raising=False)
    rng_state = random.getstate()

    provenance = sft_module.configure_training_determinism(fake, seed=7)

    assert fake.manual_seeds == [7]
    assert fake.cudnn.deterministic is True
    assert fake.cudnn.benchmark is False
    assert fake.deterministic_calls == [True]
    import os

    assert os.environ["CUBLAS_WORKSPACE_CONFIG"] == ":4096:8"
    assert random.getstate() != rng_state, "python 全局 RNG 必须被重播种子"
    assert provenance["seed"] == 7
    assert provenance["cublas_workspace_config"] == ":4096:8"
    assert provenance["warn_only"] is True


def test_configure_training_determinism_never_crashes_without_numpy_or_transformers(
    monkeypatch: Any,
) -> None:
    """可选依赖缺失时不得崩溃——训练机与 CPU 开发机的依赖面不同。"""
    import sys

    import veritool_rl.training.sft as sft_module

    monkeypatch.setitem(sys.modules, "numpy", None)
    monkeypatch.setitem(sys.modules, "transformers", None)
    provenance = sft_module.configure_training_determinism(_FakeTorch(), seed=3)
    assert provenance["numpy_seeded"] is False
    assert provenance["transformers_seeded"] is False


def test_run_sft_applies_determinism_before_any_training_step() -> None:
    """结构性锁：`run_sft` 必须在构建 SFTConfig 之前调用 determinism 设置。

    torch 不在 CPU 开发环境里，因此这里用源码结构断言（与
    test_source_layers_enforce_one_way_dependency 同一先例）锁定调用次序，
    GPU 真跑时由运行时 provenance（metrics["determinism"]）二次验证。
    """
    from pathlib import Path

    source = Path(sft_module_source_path()).read_text(encoding="utf-8")
    apply_at = source.index("configure_training_determinism(torch")
    config_at = source.index("training_args = SFTConfig(")
    assert apply_at < config_at, "determinism 设置必须先于 SFTConfig 构造"
    assert '"determinism": determinism' in source, "运行时 provenance 必须写进 metrics.json"


def sft_module_source_path() -> str:
    import veritool_rl.training.sft as module

    return module.__file__
