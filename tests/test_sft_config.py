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
        "model": {"name": "models/Qwen3-1.7B", "load_in_4bit": True},
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
    from veritool_rl.agent.qwen import TransformersBackend
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
