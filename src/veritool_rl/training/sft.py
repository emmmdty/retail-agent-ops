"""Qwen3-1.7B 单卡 4-bit QLoRA-SFT。"""

from __future__ import annotations

import gc
import math
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from veritool_rl.artifacts import write_json, write_yaml
from veritool_rl.paths import validate_project_relative_path


class ConfigModel(BaseModel):
    """训练配置允许 YAML 标量转换，但拒绝未知字段。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ModelSettings(ConfigModel):
    name: str = "models/Qwen3-1.7B"
    load_in_4bit: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        validate_project_relative_path(value, "model.name")
        return value


class LoraSettings(ConfigModel):
    r: int = Field(default=16, ge=1)
    alpha: int = Field(default=32, ge=1)
    dropout: float = Field(default=0.05, ge=0.0, lt=1.0)
    target_modules: list[str] = Field(
        default_factory=lambda: ["q_proj", "k_proj", "v_proj", "o_proj"]
    )


class DataSettings(ConfigModel):
    train_path: Path
    eval_path: Path
    train_limit: int | None = Field(default=None, ge=1)
    eval_limit: int | None = Field(default=None, ge=1)

    @field_validator("train_path", "eval_path")
    @classmethod
    def validate_data_path(cls, value: Path) -> Path:
        validate_project_relative_path(value, "data path")
        return value


class TrainingSettings(ConfigModel):
    epochs: int = Field(default=3, ge=1)
    batch_size: int = Field(default=2, ge=1)
    grad_accum: int = Field(default=8, ge=1)
    lr: float = Field(default=2.0e-4, gt=0.0)
    max_seq_len: int = Field(default=1024, ge=128)
    bf16: bool = True
    gradient_checkpointing: bool = True
    assistant_only_loss: bool = True
    max_steps: int | None = Field(default=None, ge=1)
    smoke: bool = False
    verify_adapter_reload: bool = False


class UserSFTConfig(ConfigModel):
    model: ModelSettings
    lora: LoraSettings
    data: DataSettings
    training: TrainingSettings


class ResolvedSFTConfig(UserSFTConfig):
    seed: int
    output_dir: Path
    adapter_dir: Path


def resolve_sft_config(
    config: dict[str, Any],
    seed: int,
    output_dir: Path,
) -> ResolvedSFTConfig:
    """校验配置、数据路径与本期固定的 4-bit/assistant-only 约束。"""
    parsed = UserSFTConfig.model_validate(config)
    if not parsed.model.load_in_4bit:
        msg = "MVP 公平对照固定使用 4-bit NF4"
        raise ValueError(msg)
    if not parsed.training.assistant_only_loss:
        msg = "工具调用 SFT 必须启用 assistant_only_loss"
        raise ValueError(msg)
    if parsed.training.smoke:
        if parsed.data.train_limit != 8:
            msg = "训练 smoke 必须固定使用 8 条训练样例"
            raise ValueError(msg)
        if parsed.training.max_steps is None or parsed.training.max_steps > 2:
            msg = "训练 smoke 最多 2 个 optimizer step"
            raise ValueError(msg)
        if not parsed.training.verify_adapter_reload:
            msg = "训练 smoke 必须完成 adapter reload"
            raise ValueError(msg)
    for path in (parsed.data.train_path, parsed.data.eval_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    return ResolvedSFTConfig(
        **parsed.model_dump(),
        seed=seed,
        output_dir=output_dir,
        adapter_dir=output_dir / "adapter",
    )


def validate_tokenized_sft_rows(
    rows: Iterable[dict[str, Any]],
    *,
    max_seq_len: int,
) -> None:
    """验证预 tokenized 数据未截断且只监督连续 assistant suffix。"""
    count = 0
    for index, row in enumerate(rows):
        count += 1
        task_id = row.get("task_id", f"row-{index}")
        input_ids = row.get("input_ids")
        attention_mask = row.get("attention_mask")
        labels = row.get("labels")
        if (
            not isinstance(input_ids, list)
            or not isinstance(attention_mask, list)
            or not isinstance(labels, list)
        ):
            raise ValueError(f"{task_id} tokenized 字段必须是列表")
        if (
            not input_ids
            or len(input_ids) != len(attention_mask)
            or len(input_ids) != len(labels)
        ):
            raise ValueError(f"{task_id} input/attention/labels 长度不一致")
        if len(input_ids) > max_seq_len:
            raise ValueError(
                f"{task_id} token 长度 {len(input_ids)} 超过 max_seq_len {max_seq_len}"
            )
        supervised = [position for position, label in enumerate(labels) if label != -100]
        if not supervised:
            raise ValueError(f"{task_id} 没有 assistant 监督 token")
        first = supervised[0]
        if supervised != list(range(first, len(labels))):
            raise ValueError(f"{task_id} assistant labels 必须是连续 suffix")
        if any(labels[position] != input_ids[position] for position in supervised):
            raise ValueError(f"{task_id} assistant label 与 input token 不一致")
        full_token_count = row.get("full_token_count")
        if full_token_count is not None and full_token_count != len(input_ids):
            raise ValueError(f"{task_id} full_token_count 与 input_ids 不一致")
    if count == 0:
        raise ValueError("SFT tokenized 数据不能为空")


def select_longest_rows(
    rows: Iterable[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    """按 full token 长度降序、task_id 升序选择确定性 smoke 样本。"""
    if limit < 1:
        raise ValueError("smoke limit 必须为正整数")
    ordered = sorted(
        rows,
        key=lambda row: (
            -int(row.get("full_token_count", -1)),
            str(row.get("task_id", "")),
        ),
    )
    if len(ordered) < limit:
        raise ValueError(f"smoke 至少需要 {limit} 条样本")
    return ordered[:limit]


def reload_adapter_offline(model_path: Path, adapter_path: Path) -> dict[str, Any]:
    """通过现有 NF4 backend 真实重载已保存 adapter。"""
    if not model_path.is_dir():
        raise FileNotFoundError(model_path)
    if not adapter_path.is_dir():
        raise FileNotFoundError(adapter_path)
    from veritool_rl.agent.qwen import TransformersBackend

    started = time.perf_counter()
    backend = TransformersBackend.from_pretrained(
        str(model_path),
        str(adapter_path),
    )
    elapsed = time.perf_counter() - started
    del backend
    return {
        "loaded": True,
        "model_path": str(model_path),
        "adapter_path": str(adapter_path),
        "local_files_only": True,
        "wall_time_seconds": elapsed,
    }


def run_sft(config: dict[str, Any], seed: int, output_dir: Path) -> dict[str, Any]:
    """执行 QLoRA-SFT，保存可重载 adapter、配置和有限指标。"""
    resolved = resolve_sft_config(config, seed, output_dir)
    model_path = Path(resolved.model.name)
    if not model_path.is_dir():
        raise FileNotFoundError(model_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_yaml(output_dir / "config.yaml", resolved.model_dump(mode="json"))

    import torch
    from datasets import Dataset, load_dataset
    from peft import LoraConfig
    from transformers import AutoTokenizer, BitsAndBytesConfig, DataCollatorForSeq2Seq
    from trl.trainer.sft_config import SFTConfig
    from trl.trainer.sft_trainer import SFTTrainer

    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError("QLoRA-SFT 必须看到且只看到一张 CUDA GPU")
    torch.cuda.reset_peak_memory_stats()
    started_at = time.perf_counter()
    loaded_dataset = load_dataset(
        "json",
        data_files={
            "train": str(resolved.data.train_path),
            "validation": str(resolved.data.eval_path),
        },
    )
    train_rows = [dict(row) for row in loaded_dataset["train"]]
    eval_rows = [dict(row) for row in loaded_dataset["validation"]]
    validate_tokenized_sft_rows(
        train_rows,
        max_seq_len=resolved.training.max_seq_len,
    )
    validate_tokenized_sft_rows(
        eval_rows,
        max_seq_len=resolved.training.max_seq_len,
    )
    if resolved.data.train_limit is not None:
        train_rows = select_longest_rows(
            train_rows,
            limit=resolved.data.train_limit,
        )
    if resolved.data.eval_limit is not None:
        eval_rows = select_longest_rows(
            eval_rows,
            limit=resolved.data.eval_limit,
        )
    dataset = {
        "train": Dataset.from_list(train_rows),
        "validation": Dataset.from_list(eval_rows),
    }
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    bitsandbytes_config: Any = BitsAndBytesConfig
    quantization = bitsandbytes_config(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    lora_config = LoraConfig(
        r=resolved.lora.r,
        lora_alpha=resolved.lora.alpha,
        lora_dropout=resolved.lora.dropout,
        target_modules=resolved.lora.target_modules,
        bias="none",
        task_type="CAUSAL_LM",
    )
    training_args = SFTConfig(
        output_dir=str(output_dir / "checkpoints"),
        num_train_epochs=resolved.training.epochs,
        per_device_train_batch_size=resolved.training.batch_size,
        per_device_eval_batch_size=resolved.training.batch_size,
        gradient_accumulation_steps=resolved.training.grad_accum,
        learning_rate=resolved.training.lr,
        max_length=None,
        max_steps=resolved.training.max_steps or -1,
        bf16=resolved.training.bf16,
        gradient_checkpointing=resolved.training.gradient_checkpointing,
        assistant_only_loss=True,
        completion_only_loss=False,
        packing=False,
        eval_strategy="no" if resolved.training.smoke else "epoch",
        save_strategy="no",
        logging_steps=1,
        warmup_ratio=0.1,
        optim="paged_adamw_8bit",
        report_to="none",
        seed=seed,
        data_seed=seed,
        dataset_kwargs={"skip_prepare_dataset": True},
        model_init_kwargs={
            "dtype": torch.bfloat16,
            "device_map": {"": "cuda:0"},
            "local_files_only": True,
        },
    )
    data_collator = DataCollatorForSeq2Seq(
        tokenizer=tokenizer,
        padding=True,
        label_pad_token_id=-100,
        pad_to_multiple_of=8,
    )
    trainer = SFTTrainer(
        model=str(model_path),
        args=training_args,
        train_dataset=dataset["train"],
        eval_dataset=dataset["validation"],
        processing_class=tokenizer,
        peft_config=lora_config,
        quantization_config=quantization,
        data_collator=data_collator,
    )
    train_result = trainer.train()
    eval_metrics = trainer.evaluate()
    trainer.save_model(str(resolved.adapter_dir))
    tokenizer.save_pretrained(str(resolved.adapter_dir))
    torch.cuda.synchronize()
    log_history = trainer.state.log_history
    training_finished_at = time.perf_counter()
    metrics = {
        "train": _json_metrics(train_result.metrics),
        "eval": _json_metrics(eval_metrics),
        "data": {
            "train_examples": len(train_rows),
            "eval_examples": len(eval_rows),
            "train_input_tokens_per_epoch": sum(
                len(cast(list[int], row["input_ids"])) for row in train_rows
            ),
            "train_supervised_tokens_per_epoch": sum(
                sum(label != -100 for label in cast(list[int], row["labels"]))
                for row in train_rows
            ),
            "max_seq_len": resolved.training.max_seq_len,
            "trainer_truncation_enabled": False,
        },
        "resources": _cuda_resource_metrics(
            torch.cuda,
            wall_time_seconds=training_finished_at - started_at,
        ),
    }
    _require_finite_losses(metrics)
    del trainer
    del loaded_dataset
    gc.collect()
    torch.cuda.empty_cache()
    if resolved.training.verify_adapter_reload:
        metrics["adapter_reload"] = reload_adapter_offline(
            model_path,
            resolved.adapter_dir,
        )
        gc.collect()
        torch.cuda.empty_cache()
    write_json(output_dir / "metrics.json", metrics)
    write_json(output_dir / "trainer_log_history.json", log_history)
    (output_dir / "log.txt").write_text(
        f"QLoRA-SFT 完成；adapter={resolved.adapter_dir}\n",
        encoding="utf-8",
    )
    return metrics


def _json_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        key: float(value) if isinstance(value, (int, float)) else value
        for key, value in metrics.items()
    }


def _cuda_resource_metrics(cuda: Any, wall_time_seconds: float) -> dict[str, Any]:
    return {
        "wall_time_seconds": wall_time_seconds,
        "logical_device": f"cuda:{cuda.current_device()}",
        "cuda_peak_allocated_bytes": int(cuda.max_memory_allocated()),
        "cuda_peak_reserved_bytes": int(cuda.max_memory_reserved()),
    }


def _require_finite_losses(metrics: dict[str, Any]) -> None:
    losses = [
        value
        for group in metrics.values()
        if isinstance(group, dict)
        for key, value in group.items()
        if "loss" in key and isinstance(value, (int, float))
    ]
    if not losses or not all(math.isfinite(value) for value in losses):
        msg = "训练/评测未产生有限 loss"
        raise RuntimeError(msg)
