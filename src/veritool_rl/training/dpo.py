"""QLoRA-DPO（TRL 1.8.0 DPOTrainer）——「该拒绝却执行」的边界校准训练（r11 主线）。

## 起点与参照

- **起始权重 = `models/Qwen3-4B-sft-008-merged`**：sft-008 的确定性合并部署形态
  （`model.safetensors` SHA-256 与观测 5 逐位一致），数学上就是「NF4 基座 +
  sft-008 adapter」，也是发布判定的候选形态。在它之上加一只**新的** LoRA。
- **ref model = 初始策略冻结副本**：TRL peft 模式下不显式传 `ref_model` 时，
  参照策略取「禁用 adapter 的基座」——即未加 DPO LoRA 的合并模型 = 初始策略。
  这一条由源码结构测试锁定（`ref_model` 不得出现在 `run_dpo` 里）。

## 数据

偏好对由 `retail_ops.build.dpo_sampling` 在真实链路上采样（chosen=Oracle 拒绝轨迹、
rejected=模型自己的 `refund_not_eligible` 失败采样）。行格式是 messages（与 SFT
同一条格式链路），训练前用 Qwen chat template（带 tools）预渲染成
prompt/chosen/rejected 纯文本——同时按实际渲染长度做 max_length 守卫
（LOG-20260905-02：截断把 assistant 段切掉 → mask 全零 → LoRA 零更新且不报错）。

## 机器守卫

- 渲染长度守卫：任一侧超过 `max_length` 直接失败，不留静默截断；
- loss 守卫：训练曲线必须有限、非零、末端低于起点（`require_nonzero_declining_losses`）；
- 输出目录不可覆盖；`configure_training_determinism` 复用（metrics 含
  `determinism.provenance`）。

判读规则与运行清单见 `task_plan.md` 的 DPO 预注册（先于一切运行提交）。
"""

from __future__ import annotations

import gc
import json
import math
import re
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from veritool_rl.core.agent.qwen import verify_local_model_files
from veritool_rl.core.artifacts import write_json, write_yaml
from veritool_rl.core.paths import validate_project_relative_path
from veritool_rl.training.sft import configure_training_determinism

_MODEL_FILE_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ConfigModel(BaseModel):
    """训练配置允许 YAML 标量转换，但拒绝未知字段。"""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DpoModelSettings(ConfigModel):
    """DPO 起始权重 pin：sft-008 的合并部署形态。"""

    name: str = "models/Qwen3-4B-sft-008-merged"
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


class DpoLoraSettings(ConfigModel):
    """DPO 新增 LoRA 的形状与 sft-008 相同（R4 结论：4B 上全 linear 最好）。"""

    r: int = Field(default=16, ge=1)
    alpha: int = Field(default=32, ge=1)
    dropout: float = Field(default=0.05, ge=0.0, lt=1.0)
    target_modules: list[str] = Field(
        default_factory=lambda: [
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ]
    )


class DpoDataSettings(ConfigModel):
    train_path: Path

    @field_validator("train_path")
    @classmethod
    def validate_data_path(cls, value: Path) -> Path:
        validate_project_relative_path(value, "data path")
        return value


class DpoTrainingSettings(ConfigModel):
    """预注册超参（2026-09-06 用户确认）：beta 0.1 / lr 5e-7 / 1 epoch。"""

    beta: float = 0.1
    epochs: int = Field(default=1, ge=1)
    batch_size: int = Field(default=2, ge=1)
    grad_accum: int = Field(default=4, ge=1)
    lr: float = 5e-7
    max_length: int = Field(default=2048, ge=128)
    bf16: bool = True
    gradient_checkpointing: bool = True
    smoke: bool = False

    @field_validator("beta")
    @classmethod
    def validate_beta(cls, value: float) -> float:
        if value <= 0.0:
            msg = "beta 必须为正"
            raise ValueError(msg)
        return value


class DpoRunConfig(ConfigModel):
    model: DpoModelSettings
    lora: DpoLoraSettings
    data: DpoDataSettings
    training: DpoTrainingSettings


class ResolvedDpoConfig(DpoRunConfig):
    seed: int
    output_dir: Path
    adapter_dir: Path


def resolve_dpo_config(
    config: dict[str, Any],
    seed: int,
    output_dir: Path,
) -> ResolvedDpoConfig:
    """校验配置与数据路径，锁定 NF4 起始权重契约。"""
    parsed = DpoRunConfig.model_validate(config)
    if not parsed.model.load_in_4bit:
        msg = "DPO 与既有证据同口径，起始权重固定使用 4-bit NF4"
        raise ValueError(msg)
    if not parsed.data.train_path.is_file():
        raise FileNotFoundError(parsed.data.train_path)
    if parsed.training.smoke:
        train_rows = _read_jsonl(parsed.data.train_path)
        if len(train_rows) > 4:
            msg = "训练 smoke 最多使用 4 条偏好对"
            raise ValueError(msg)
    return ResolvedDpoConfig(
        **parsed.model_dump(),
        seed=seed,
        output_dir=output_dir,
        adapter_dir=output_dir / "adapter",
    )


def validate_dpo_pairs(rows: Sequence[Mapping[str, Any]]) -> None:
    """偏好对结构校验：字段齐、pair_id 唯一、chosen 与 rejected 必须不同。"""
    if not rows:
        msg = "DPO 偏好对数据不能为空"
        raise ValueError(msg)
    seen_pair_ids: set[str] = set()
    for index, row in enumerate(rows):
        label = str(row.get("pair_id", f"row-{index}"))
        missing = [
            field
            for field in (
                "pair_id",
                "task_id",
                "sample_index",
                "prompt",
                "chosen",
                "rejected",
                "tools",
            )
            if field not in row
        ]
        if missing:
            msg = f"{label} 缺少偏好对字段: {missing}"
            raise ValueError(msg)
        if label in seen_pair_ids:
            msg = f"pair_id 重复: {label}"
            raise ValueError(msg)
        seen_pair_ids.add(label)
        prompt = row["prompt"]
        if not isinstance(prompt, list) or not prompt or prompt[0].get("role") != "system":
            msg = f"{label} 的 prompt 必须以 system 开头（评测条件含政策卡/工具说明）"
            raise ValueError(msg)
        if json.dumps(row["chosen"], ensure_ascii=False, sort_keys=True) == json.dumps(
            row["rejected"], ensure_ascii=False, sort_keys=True
        ):
            msg = f"{label} 的 chosen 与 rejected 完全相同——DPO 无法从零对比学习"
            raise ValueError(msg)


def render_dpo_pairs(
    rows: Sequence[Mapping[str, Any]],
    tokenizer: Any,
    *,
    max_length: int,
) -> list[dict[str, Any]]:
    """把 messages 形式的偏好对渲染成 TRL 文本三列（prompt/chosen/rejected）。

    渲染契约：prompt 带 tools 与 `add_generation_prompt=True`；chosen/rejected 渲染
    完整对话后**剥离 prompt 前缀**——前缀不一致直接失败（模板静默漂移会让
    completion 错位，那比训练失败更糟）。任一侧 token 长度超过 max_length 直接
    失败：静默截断正是 LOG-20260905-02 里「LoRA 零更新且不报错」的根源。
    """
    rendered: list[dict[str, Any]] = []
    for row in rows:
        label = str(row["pair_id"])
        prompt_messages = list(row["prompt"])
        tools = list(row["tools"])
        prompt_text = str(
            tokenizer.apply_chat_template(
                prompt_messages,
                tools=tools,
                add_generation_prompt=True,
                tokenize=False,
            )
        )
        token_lengths: dict[str, int] = {"prompt": _token_count(tokenizer, prompt_text)}
        side_texts: dict[str, str] = {}
        for side in ("chosen", "rejected"):
            full_text = str(
                tokenizer.apply_chat_template(
                    prompt_messages + list(row[side]),
                    tools=tools,
                    tokenize=False,
                )
            )
            if not full_text.startswith(prompt_text):
                msg = (
                    f"{label}/{side} 的 chat template 渲染不以 prompt 前缀开头，"
                    f"前缀剥离会错位——拒绝渲染"
                )
                raise ValueError(msg)
            side_text = full_text[len(prompt_text) :]
            side_tokens = _token_count(tokenizer, prompt_text + side_text)
            if side_tokens > max_length:
                msg = (
                    f"{label}/{side} 渲染长度 {side_tokens} 超过 max_length {max_length}"
                    f"——预注册要求按实际渲染长度留余量，不得静默截断"
                )
                raise ValueError(msg)
            token_lengths[side] = side_tokens
            side_texts[side] = side_text
        rendered.append(
            {
                "pair_id": label,
                "task_id": str(row["task_id"]),
                "sample_index": int(row["sample_index"]),
                "prompt": prompt_text,
                "chosen": side_texts["chosen"],
                "rejected": side_texts["rejected"],
                "token_lengths": token_lengths,
            }
        )
    return rendered


def _token_count(tokenizer: Any, text: str) -> int:
    encoded = tokenizer(text)
    input_ids = encoded.get("input_ids")
    if input_ids is None:
        msg = "tokenizer 未返回 input_ids，无法核对渲染长度"
        raise ValueError(msg)
    return len(input_ids)


def require_nonzero_declining_losses(losses: Sequence[float], *, smoke: bool = False) -> None:
    """训练曲线守卫：有限、非零、末端低于起点。

    全零/恒零 = mask 全零 = LoRA 零更新（LOG-20260905-02 的静默失败签名）；
    末端高于起点 = 本轮没有正向信号，都不允许落盘成「完成」。

    `smoke=True`（≤4 对的管线自检）只要求有限且非零——单/双步的 smoke 曲线
    没有「趋势」可言，把下降判据加在 smoke 上会让自检必然失败。
    """
    if not losses:
        msg = "训练未产生任何 loss 读数"
        raise RuntimeError(msg)
    if not all(math.isfinite(value) for value in losses):
        msg = "训练 loss 曲线包含非有限值"
        raise RuntimeError(msg)
    if all(value == 0.0 for value in losses):
        msg = "训练 loss 全零（mask 全零/LoRA 零更新的失败签名）"
        raise RuntimeError(msg)
    if any(value <= 0.0 for value in losses):
        msg = "训练 loss 必须全为正数"
        raise RuntimeError(msg)
    if not smoke and losses[-1] >= losses[0]:
        msg = f"训练 loss 末端未下降（首 {losses[0]} → 末 {losses[-1]}）"
        raise RuntimeError(msg)


def run_dpo(config: dict[str, Any], seed: int, output_dir: Path) -> dict[str, Any]:
    """执行 QLoRA-DPO，保存可重载 adapter、配置和有限指标。"""
    resolved = resolve_dpo_config(config, seed, output_dir)
    model_path = Path(resolved.model.name)
    if not model_path.is_dir():
        raise FileNotFoundError(model_path)
    verify_local_model_files(model_path, resolved.model.file_sha256)
    _ensure_new_training_output(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_yaml(output_dir / "config.yaml", resolved.model_dump(mode="json"))

    import torch
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import AutoTokenizer, BitsAndBytesConfig
    from trl.trainer.dpo_config import DPOConfig
    from trl.trainer.dpo_trainer import DPOTrainer

    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError("QLoRA-DPO 必须看到且只看到一张 CUDA GPU")
    torch.cuda.reset_peak_memory_stats()
    determinism = configure_training_determinism(torch, seed=seed)
    started_at = time.perf_counter()

    pairs = _read_jsonl(resolved.data.train_path)
    validate_dpo_pairs(pairs)
    tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    rendered = render_dpo_pairs(
        pairs,
        tokenizer,
        max_length=resolved.training.max_length,
    )

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
    training_args = DPOConfig(
        output_dir=str(output_dir / "checkpoints"),
        beta=resolved.training.beta,
        num_train_epochs=resolved.training.epochs,
        per_device_train_batch_size=resolved.training.batch_size,
        gradient_accumulation_steps=resolved.training.grad_accum,
        learning_rate=resolved.training.lr,
        max_length=resolved.training.max_length,
        bf16=resolved.training.bf16,
        gradient_checkpointing=resolved.training.gradient_checkpointing,
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
            "quantization_config": quantization,
        },
    )
    # ref model 刻意不传：TRL peft 模式自动把参照策略取为「禁用 adapter 的基座」，
    # 即未加 DPO LoRA 的合并模型 = 初始策略冻结副本（源码结构测试锁定此契约）。
    trainer = DPOTrainer(
        model=str(model_path),
        args=training_args,
        train_dataset=Dataset.from_list(rendered),
        processing_class=tokenizer,
        peft_config=lora_config,
    )
    train_result = trainer.train()
    trainer.save_model(str(resolved.adapter_dir))
    tokenizer.save_pretrained(str(resolved.adapter_dir))
    torch.cuda.synchronize()
    log_history = trainer.state.log_history
    training_finished_at = time.perf_counter()
    losses = [
        float(entry["loss"])
        for entry in log_history
        if isinstance(entry, Mapping) and "loss" in entry
    ]
    require_nonzero_declining_losses(losses, smoke=resolved.training.smoke)
    metrics = {
        "train": _json_metrics(train_result.metrics),
        "losses": losses,
        "data": {
            "pairs": len(rendered),
            "max_length": resolved.training.max_length,
            "max_rendered_tokens": max(
                max(int(row["token_lengths"]["chosen"]), int(row["token_lengths"]["rejected"]))
                for row in rendered
            ),
            "pairs_file_sha256": _pairs_file_sha256(resolved.data.train_path),
        },
        "resources": {
            "wall_time_seconds": training_finished_at - started_at,
            "logical_device": f"cuda:{torch.cuda.current_device()}",
            "cuda_peak_allocated_bytes": int(torch.cuda.max_memory_allocated()),
            "cuda_peak_reserved_bytes": int(torch.cuda.max_memory_reserved()),
        },
        "determinism": determinism,
    }
    del trainer
    gc.collect()
    torch.cuda.empty_cache()
    write_json(output_dir / "metrics.json", metrics)
    write_json(output_dir / "trainer_log_history.json", log_history)
    (output_dir / "log.txt").write_text(
        f"QLoRA-DPO 完成；adapter={resolved.adapter_dir}\n",
        encoding="utf-8",
    )
    return metrics


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


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    return [cast(dict[str, Any], row) for row in rows]


def _pairs_file_sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        key: float(value) if isinstance(value, (int, float)) else value
        for key, value in metrics.items()
    }
