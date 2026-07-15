"""Qwen3-1.7B 单卡 4-bit QLoRA-SFT。"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from veritool_rl.artifacts import write_json, write_yaml


class ConfigModel(BaseModel):
    """训练配置允许 YAML 标量转换，但拒绝未知字段。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ModelSettings(ConfigModel):
    name: str = "Qwen/Qwen3-1.7B"
    load_in_4bit: bool = True


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


class TrainingSettings(ConfigModel):
    epochs: int = Field(default=3, ge=1)
    batch_size: int = Field(default=2, ge=1)
    grad_accum: int = Field(default=8, ge=1)
    lr: float = Field(default=2.0e-4, gt=0.0)
    max_seq_len: int = Field(default=1024, ge=128)
    bf16: bool = True
    gradient_checkpointing: bool = True
    assistant_only_loss: bool = True


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
    for path in (parsed.data.train_path, parsed.data.eval_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    return ResolvedSFTConfig(
        **parsed.model_dump(),
        seed=seed,
        output_dir=output_dir,
        adapter_dir=output_dir / "adapter",
    )


def run_sft(config: dict[str, Any], seed: int, output_dir: Path) -> dict[str, Any]:
    """执行 QLoRA-SFT，保存可重载 adapter、配置和有限指标。"""
    resolved = resolve_sft_config(config, seed, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_yaml(output_dir / "config.yaml", resolved.model_dump(mode="json"))

    import torch
    from datasets import load_dataset
    from peft import LoraConfig
    from transformers import AutoTokenizer, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer

    dataset = load_dataset(
        "json",
        data_files={
            "train": str(resolved.data.train_path),
            "validation": str(resolved.data.eval_path),
        },
    )
    tokenizer = AutoTokenizer.from_pretrained(resolved.model.name)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    quantization = BitsAndBytesConfig(
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
        max_length=resolved.training.max_seq_len,
        bf16=resolved.training.bf16,
        gradient_checkpointing=resolved.training.gradient_checkpointing,
        assistant_only_loss=True,
        packing=False,
        eval_strategy="epoch",
        save_strategy="epoch",
        save_total_limit=2,
        logging_steps=1,
        warmup_ratio=0.1,
        optim="paged_adamw_8bit",
        report_to="none",
        seed=seed,
        data_seed=seed,
        model_init_kwargs={"dtype": torch.bfloat16, "device_map": {"": "cuda:0"}},
    )
    trainer = SFTTrainer(
        model=resolved.model.name,
        args=training_args,
        train_dataset=dataset["train"],
        eval_dataset=dataset["validation"],
        processing_class=tokenizer,
        peft_config=lora_config,
        quantization_config=quantization,
    )
    train_result = trainer.train()
    eval_metrics = trainer.evaluate()
    trainer.save_model(str(resolved.adapter_dir))
    tokenizer.save_pretrained(str(resolved.adapter_dir))
    metrics = {
        "train": _json_metrics(train_result.metrics),
        "eval": _json_metrics(eval_metrics),
    }
    _require_finite_losses(metrics)
    write_json(output_dir / "metrics.json", metrics)
    write_json(output_dir / "trainer_log_history.json", trainer.state.log_history)
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
