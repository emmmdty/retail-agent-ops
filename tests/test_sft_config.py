"""QLoRA-SFT 配置解析测试，不在本地加载模型。"""

from __future__ import annotations

from pathlib import Path

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
        "model": {"name": "models/Qwen3-1.7B", "load_in_4bit": True},
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
        "model": {"name": "models/Qwen3-1.7B", "load_in_4bit": True},
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
        "model": {"name": "models/Qwen3-1.7B", "load_in_4bit": True},
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
