"""QLoRA-SFT 配置解析测试，不在本地加载模型。"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_resolve_sft_config_locks_mvp_defaults(tmp_path: Path) -> None:
    from veritool_rl.training.sft import resolve_sft_config

    train_path = tmp_path / "train.jsonl"
    eval_path = tmp_path / "dev.jsonl"
    train_path.write_text("{}\n", encoding="utf-8")
    eval_path.write_text("{}\n", encoding="utf-8")
    config = {
        "model": {"name": "Qwen/Qwen3-1.7B", "load_in_4bit": True},
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

    assert resolved.model.name == "Qwen/Qwen3-1.7B"
    assert resolved.training.max_seq_len == 1024
    assert resolved.training.assistant_only_loss is True
    assert resolved.seed == 7
    assert resolved.adapter_dir == tmp_path / "run/adapter"


def test_resolve_sft_config_rejects_missing_dataset(tmp_path: Path) -> None:
    from veritool_rl.training.sft import resolve_sft_config

    config = {
        "model": {"name": "Qwen/Qwen3-1.7B", "load_in_4bit": True},
        "lora": {"target_modules": ["q_proj"]},
        "data": {
            "train_path": str(tmp_path / "missing-train.jsonl"),
            "eval_path": str(tmp_path / "missing-dev.jsonl"),
        },
        "training": {},
    }

    with pytest.raises(FileNotFoundError, match="missing-train"):
        resolve_sft_config(config, seed=0, output_dir=tmp_path / "run")
