"""Qwen3-1.7B 单卡 4-bit QLoRA-SFT。"""

from __future__ import annotations

import gc
import math
import re
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from veritool_rl.core.agent.qwen import verify_local_model_files
from veritool_rl.core.artifacts import write_json, write_yaml
from veritool_rl.core.paths import validate_project_relative_path

_MODEL_FILE_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ConfigModel(BaseModel):
    """训练配置允许 YAML 标量转换，但拒绝未知字段。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ModelSettings(ConfigModel):
    """训练侧的模型 pin：路径 + revision + 逐文件 SHA-256。

    与 `base_evaluation.py::ModelArtifact` 同一套 provenance 口径。`revision`
    只做形状校验（模型 pin 会随上游仓库变化，不在代码里硬编码），真正的
    防篡改依据是 `file_sha256` 配合 `agent/qwen.py::verify_local_model_files`
    的"清单外文件/子目录/符号链接一律拒绝"。两个字段都是必填：正式训练不
    允许跑在一个未经哈希校验的模型目录上（CLAUDE.md 第 5 节）。
    """

    name: str = "models/Qwen3-1.7B"
    load_in_4bit: bool = True
    revision: str = Field(pattern=r"^[0-9a-f]{7,64}$")
    file_sha256: dict[str, str]

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        validate_project_relative_path(value, "model.name")
        return value

    @field_validator("file_sha256")
    @classmethod
    def validate_file_sha256(cls, value: dict[str, str]) -> dict[str, str]:
        """文件名不得注入路径分隔符，摘要必须是 SHA-256。"""
        if not value:
            msg = "model.file_sha256 不得为空"
            raise ValueError(msg)
        for name, digest in value.items():
            if not name or name in {".", ".."} or _MODEL_FILE_PATTERN.fullmatch(name) is None:
                msg = f"model.file_sha256 文件名必须是安全的单一路径片段: {name!r}"
                raise ValueError(msg)
            if _SHA256_PATTERN.fullmatch(digest) is None:
                msg = f"model.file_sha256 摘要必须是 SHA-256: {name}"
                raise ValueError(msg)
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


SftDataFormat = Literal["messages", "pretokenized"]


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
        if not input_ids or len(input_ids) != len(attention_mask) or len(input_ids) != len(labels):
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


def prepare_sft_rows(
    train_rows: list[dict[str, Any]],
    eval_rows: list[dict[str, Any]],
    *,
    max_seq_len: int,
    train_limit: int | None,
    eval_limit: int | None,
) -> tuple[SftDataFormat, list[dict[str, Any]], list[dict[str, Any]]]:
    """识别并校验两种既有 SFT 数据格式，禁止跨 split 混用。"""
    train_format = _detect_sft_data_format(train_rows, "train")
    eval_format = _detect_sft_data_format(eval_rows, "eval")
    if train_format != eval_format:
        raise ValueError("SFT train/eval 数据格式必须一致")
    if train_format == "pretokenized":
        validate_tokenized_sft_rows(train_rows, max_seq_len=max_seq_len)
        validate_tokenized_sft_rows(eval_rows, max_seq_len=max_seq_len)
        if train_limit is not None:
            train_rows = select_longest_rows(train_rows, limit=train_limit)
        if eval_limit is not None:
            eval_rows = select_longest_rows(eval_rows, limit=eval_limit)
    else:
        _validate_message_sft_rows(train_rows, "train")
        _validate_message_sft_rows(eval_rows, "eval")
        if train_limit is not None:
            train_rows = _select_first_rows(train_rows, train_limit, "train")
        if eval_limit is not None:
            eval_rows = _select_first_rows(eval_rows, eval_limit, "eval")
    return train_format, train_rows, eval_rows


def _detect_sft_data_format(
    rows: list[dict[str, Any]],
    split: str,
) -> SftDataFormat:
    if not rows:
        raise ValueError(f"SFT {split} 数据不能为空")
    formats: set[SftDataFormat] = set()
    for index, row in enumerate(rows):
        has_messages = "messages" in row and "tools" in row
        has_tokens = all(field in row for field in ("input_ids", "attention_mask", "labels"))
        if has_messages == has_tokens:
            task_id = row.get("task_id", f"row-{index}")
            raise ValueError(f"{task_id} 无法唯一识别 SFT 数据格式")
        formats.add("messages" if has_messages else "pretokenized")
    if len(formats) != 1:
        raise ValueError(f"SFT {split} 内部数据格式必须一致")
    return formats.pop()


def _validate_message_sft_rows(rows: list[dict[str, Any]], split: str) -> None:
    for index, row in enumerate(rows):
        task_id = row.get("task_id", f"{split}-row-{index}")
        messages = row.get("messages")
        tools = row.get("tools")
        if not isinstance(messages, list) or not messages:
            raise ValueError(f"{task_id} messages 必须是非空列表")
        if not isinstance(tools, list):
            raise ValueError(f"{task_id} tools 必须是列表")
        if any(not isinstance(message, dict) for message in messages):
            raise ValueError(f"{task_id} messages 每项必须是 mapping")
        if not any(message.get("role") == "assistant" for message in messages):
            raise ValueError(f"{task_id} 缺少 assistant 监督消息")
        if any(not isinstance(tool, dict) for tool in tools):
            raise ValueError(f"{task_id} tools 每项必须是 mapping")


def _select_first_rows(
    rows: list[dict[str, Any]],
    limit: int,
    split: str,
) -> list[dict[str, Any]]:
    if len(rows) < limit:
        raise ValueError(f"SFT {split} 至少需要 {limit} 条样本")
    return rows[:limit]


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
    from veritool_rl.core.agent.qwen import TransformersBackend

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


def pretokenized_sft_runtime_options() -> dict[str, Any]:
    """返回显式 labels 数据对应的 TRL 运行时选项。"""
    return {
        "assistant_only_loss": False,
        "completion_only_loss": False,
        "dataset_kwargs": {"skip_prepare_dataset": True},
        "max_length": None,
    }


def message_sft_runtime_options(*, max_seq_len: int) -> dict[str, Any]:
    """返回 messages + tools 数据的 TRL assistant-only 运行时选项。"""
    return {
        "assistant_only_loss": True,
        "completion_only_loss": False,
        "max_length": max_seq_len,
    }


def _ensure_new_training_output(output_dir: Path) -> None:
    """拒绝覆盖任何已开始的训练运行。"""
    protected = (
        "config.yaml",
        "adapter",
        "checkpoints",
        "metrics.json",
        "trainer_log_history.json",
        "log.txt",
    )
    existing = [name for name in protected if (output_dir / name).exists()]
    if existing:
        msg = f"输出目录包含既有训练产物，拒绝覆盖: {existing}"
        raise FileExistsError(msg)


def run_sft(config: dict[str, Any], seed: int, output_dir: Path) -> dict[str, Any]:
    """执行 QLoRA-SFT，保存可重载 adapter、配置和有限指标。"""
    resolved = resolve_sft_config(config, seed, output_dir)
    model_path = Path(resolved.model.name)
    if not model_path.is_dir():
        raise FileNotFoundError(model_path)
    # provenance 先于任何写盘和任何重量级 import：被替换/篡改/多塞文件的模型目录
    # 必须在产生任何训练产物之前就阻断，否则输出目录会留下一个声称跑了锁定模型、
    # 实际跑了别的权重的运行记录。
    verify_local_model_files(model_path, resolved.model.file_sha256)
    _ensure_new_training_output(output_dir)
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
    data_format, train_rows, eval_rows = prepare_sft_rows(
        train_rows,
        eval_rows,
        max_seq_len=resolved.training.max_seq_len,
        train_limit=resolved.data.train_limit,
        eval_limit=resolved.data.eval_limit,
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
    runtime_options = (
        pretokenized_sft_runtime_options()
        if data_format == "pretokenized"
        else message_sft_runtime_options(max_seq_len=resolved.training.max_seq_len)
    )
    training_args = SFTConfig(
        output_dir=str(output_dir / "checkpoints"),
        num_train_epochs=resolved.training.epochs,
        per_device_train_batch_size=resolved.training.batch_size,
        per_device_eval_batch_size=resolved.training.batch_size,
        gradient_accumulation_steps=resolved.training.grad_accum,
        learning_rate=resolved.training.lr,
        max_steps=resolved.training.max_steps or -1,
        bf16=resolved.training.bf16,
        gradient_checkpointing=resolved.training.gradient_checkpointing,
        packing=False,
        eval_strategy="no" if resolved.training.smoke else "epoch",
        save_strategy="no",
        logging_steps=1,
        warmup_ratio=0.1,
        optim="paged_adamw_8bit",
        report_to="none",
        seed=seed,
        data_seed=seed,
        model_init_kwargs={
            "dtype": torch.bfloat16,
            "device_map": {"": "cuda:0"},
            "local_files_only": True,
        },
        **runtime_options,
    )
    trainer_kwargs: dict[str, Any] = {
        "model": str(model_path),
        "args": training_args,
        "train_dataset": dataset["train"],
        "eval_dataset": dataset["validation"],
        "processing_class": tokenizer,
        "peft_config": lora_config,
        "quantization_config": quantization,
    }
    if data_format == "pretokenized":
        trainer_kwargs["data_collator"] = DataCollatorForSeq2Seq(
            tokenizer=tokenizer,
            padding=True,
            label_pad_token_id=-100,
            pad_to_multiple_of=8,
        )
    trainer = SFTTrainer(**trainer_kwargs)
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
            "format": data_format,
            "train_examples": len(train_rows),
            "eval_examples": len(eval_rows),
            "train_input_tokens_per_epoch": (
                sum(len(cast(list[int], row["input_ids"])) for row in train_rows)
                if data_format == "pretokenized"
                else None
            ),
            "train_supervised_tokens_per_epoch": (
                sum(
                    sum(label != -100 for label in cast(list[int], row["labels"]))
                    for row in train_rows
                )
                if data_format == "pretokenized"
                else None
            ),
            "max_seq_len": resolved.training.max_seq_len,
            "trainer_truncation_enabled": data_format == "messages",
            "loss_mask_source": (
                "pretokenized_explicit_labels"
                if data_format == "pretokenized"
                else "trl_chat_template_assistant_mask"
            ),
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
