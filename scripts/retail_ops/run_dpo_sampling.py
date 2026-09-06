#!/usr/bin/env python
"""DPO 偏好对 GPU 采样（r11 主线 A-3）。

在真实链路（`run_episode` + `RetailOpsEnv`）上，用当前策略（NF4 基座 + sft-008
adapter）对采样任务面逐任务采 N=8 条轨迹（temperature 0.8，逐样本确定性播种），
再按预注册配对规则产出偏好对。任务面 = 政策边界探针（120）+ C3 交叉面
（120，bank-004 `ood_dev` 分片）。

用法（gpu-5090，GPU 0）：

    .venv/bin/python scripts/retail_ops/run_dpo_sampling.py \
        --config configs/retail_ops/build/retail_ops_dpo_sampling.yaml \
        --input-dir data/private/retail_ops/v1 \
        --output-dir reports/retail_ops/v1/r11-dpo/sampling-001

断点续跑：每任务一个样本文件（`samples/<task_id>.json`），已存在且任务指纹一致
的任务直接复用；完成态以 `sampling-report.json` 为准（存在即拒绝重跑）。

**门禁守卫前提**：放行侧（offset > 0）出现执行类违规时 `premise_ok=false`，
脚本以退出码 3 结束——按预注册必须停下回用户决策，不得继续训练。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Literal

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

import yaml  # noqa: E402
from pydantic import Field, field_validator  # noqa: E402

from veritool_rl.core.agent.episode_timeout import run_episode_with_timeout  # noqa: E402
from veritool_rl.core.agent.qwen import (  # noqa: E402
    QwenPolicy,
    TransformersBackend,
    verify_local_model_files,
)
from veritool_rl.core.artifacts import (  # noqa: E402
    canonical_json,
    write_json,
    write_jsonl,
)
from veritool_rl.core.paths import validate_project_relative_path  # noqa: E402
from veritool_rl.core.trajectory import TaskSpec, Trajectory  # noqa: E402
from veritool_rl.core.trajectory.schema import StrictModel  # noqa: E402
from veritool_rl.retail_ops.build.dpo_sampling import (  # noqa: E402
    SamplingSettings,
    build_preference_pairs,
    build_sampling_face,
    oracle_reference,
    sample_seed,
)
from veritool_rl.retail_ops.build.phrasing_bank import (  # noqa: E402
    PhrasingRecord,
    bank_sha256,
    intent_index,
    load_phrasing_bank,
)
from veritool_rl.retail_ops.domain.bundle import load_bundle  # noqa: E402
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv  # noqa: E402

_EXIT_PREMISE_VIOLATED = 3

_SHA256_LENGTH = 64


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


class ModelPin(StrictModel):
    """NF4 基座 pin：与评测侧 `ModelArtifact` 同一套 provenance 口径。"""

    repo: str = Field(min_length=1)
    revision: str = Field(pattern=r"^[0-9a-f]{7,64}$")
    local_dir: str = Field(min_length=1)
    file_sha256: dict[str, str]

    @field_validator("local_dir")
    @classmethod
    def _validate_local_dir(cls, value: str) -> str:
        validate_project_relative_path(value, "model.local_dir")
        return value


class AdapterPin(StrictModel):
    """sft-008 adapter pin：`run_dir/adapter` 下逐文件 SHA-256。"""

    run_dir: str = Field(min_length=1)
    file_sha256: dict[str, str]

    @field_validator("run_dir")
    @classmethod
    def _validate_run_dir(cls, value: str) -> str:
        validate_project_relative_path(value, "adapter.run_dir")
        return value


class PhrasingSpec(StrictModel):
    """交叉面素材声明：bank 文件、声明哈希与评测分片。"""

    bank_relpath: str = Field(min_length=1)
    bank_sha256: str = Field(min_length=1)
    partition: Literal["ood_dev", "ood_sealed"] = "ood_dev"

    @field_validator("bank_relpath")
    @classmethod
    def _validate_bank_relpath(cls, value: str) -> str:
        validate_project_relative_path(value, "phrasing.bank_relpath")
        return value

    @field_validator("bank_sha256")
    @classmethod
    def _validate_bank_sha256(cls, value: str) -> str:
        if len(value) != _SHA256_LENGTH or any(c not in "0123456789abcdef" for c in value):
            msg = f"phrasing.bank_sha256 必须是 64 位小写十六进制: {value!r}"
            raise ValueError(msg)
        return value


class SamplingRun(StrictModel):
    max_new_tokens: int = Field(default=256, ge=1, le=4096)
    samples_per_task: int = Field(default=8, ge=1, le=32)
    episode_timeout: float = Field(default=30.0, gt=0.0)


class DpoSamplingConfig(StrictModel):
    pipeline: Literal["dpo_sampling"]
    bundle_dir: str = Field(min_length=1)
    models_root: str = Field(min_length=1)
    model: ModelPin
    adapter: AdapterPin
    phrasing: PhrasingSpec
    sampling: SamplingRun
    seed: Literal[0] = 0

    @field_validator("bundle_dir", "models_root")
    @classmethod
    def _validate_project_paths(cls, value: str) -> str:
        validate_project_relative_path(value, "config path")
        return value


def _task_digest(task: TaskSpec) -> str:
    return sha256_text(canonical_json(task.model_dump(mode="json")))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _verify_bank_sha256(bank_path: Path, declared: str) -> tuple[list[PhrasingRecord], str]:
    """bank 声明哈希校验——与 `_run_ood_build`/`OodPhrasingSpec` **同一语义**：
    `bank_sha256(records)` 的内容规范化哈希（逐条 `phrasing_id|partition`），
    **不是**文件字节哈希。返回 (records, actual)。"""
    records = load_phrasing_bank(bank_path)
    actual = bank_sha256(records)
    if actual != declared:
        msg = f"bank 内容哈希与声明不一致：actual={actual} declared={declared}"
        raise ValueError(msg)
    return records, actual


def _load_samples_for(
    task: TaskSpec,
    samples_dir: Path,
    *,
    policy: QwenPolicy,
    env_factory: Any,
    samples_per_task: int,
    episode_timeout: float,
) -> list[Trajectory]:
    """读取或采集一个任务的 N 条采样轨迹；文件即断点。"""
    task_path = samples_dir / f"{task.task_id}.json"
    expected_digest = _task_digest(task)
    if task_path.exists():
        data = json.loads(task_path.read_text(encoding="utf-8"))
        if data.get("task_sha256") != expected_digest:
            msg = f"采样文件与当前任务不一致（任务面变了就要重采）: {task_path}"
            raise ValueError(msg)
        # strict 模式下 model_validate 不做枚举/字面量回落，JSON 往返必须走
        # model_validate_json（与 load_ood_tasks 的 TaskSpec 同一条纪律）。
        return [Trajectory.model_validate_json(json.dumps(item)) for item in data["samples"]]

    import torch

    samples: list[Trajectory] = []
    for sample_index in range(samples_per_task):
        # 逐样本确定性播种：同一权重 + 同一任务 + 同一序号 → 同一条轨迹。
        torch.manual_seed(sample_seed(task.task_id, sample_index))
        samples.append(
            run_episode_with_timeout(
                task,
                env_factory,
                policy,
                sample_seed(task.task_id, sample_index),
                episode_timeout,
            )
        )
    payload = {
        "task_id": task.task_id,
        "task_sha256": expected_digest,
        "samples": [sample.model_dump(mode="json") for sample in samples],
    }
    tmp_path = task_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(tmp_path, task_path)
    return samples


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="采样运行配置（YAML）")
    parser.add_argument("--input-dir", required=True, help="私有数据根（含 phrasing bank）")
    parser.add_argument("--output-dir", required=True, help="产物目录（不可覆盖完成态）")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    config = DpoSamplingConfig.model_validate(
        yaml.safe_load(config_path.read_text(encoding="utf-8"))
    )
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    report_path = output_dir / "sampling-report.json"
    if report_path.exists():
        msg = f"采样已完成，拒绝覆盖完成态: {report_path}"
        raise FileExistsError(msg)
    output_dir.mkdir(parents=True, exist_ok=True)

    bank_path = input_dir / config.phrasing.bank_relpath
    records, actual_bank_sha256 = _verify_bank_sha256(bank_path, config.phrasing.bank_sha256)
    index: dict[str, list[PhrasingRecord]] = intent_index(
        records,
        config.phrasing.partition,
    )

    face = build_sampling_face(seed=config.seed, phrasing_index=index)
    if len(face) != 240:
        msg = f"采样任务面应为探针 120 + 交叉面 120 = 240 条，收到 {len(face)}"
        raise ValueError(msg)

    bundle = load_bundle(REPO_ROOT / config.bundle_dir)
    model_dir = REPO_ROOT / config.models_root / config.model.local_dir
    verify_local_model_files(model_dir, config.model.file_sha256)
    adapter_dir = REPO_ROOT / config.adapter.run_dir / "adapter"
    verify_local_model_files(adapter_dir, config.adapter.file_sha256)

    settings = SamplingSettings(max_new_tokens=config.sampling.max_new_tokens)
    backend = TransformersBackend.from_pretrained(
        str(model_dir),
        str(adapter_dir),
        revision=config.model.revision,
        expected_file_sha256=config.model.file_sha256,
        generate_kwargs=settings.generate_kwargs(),
    )
    policy = QwenPolicy(
        backend,
        f"{config.model.local_dir}+{config.adapter.run_dir}",
        settings.max_new_tokens,
        adapter_path=config.adapter.run_dir,
    )
    env_factory = lambda task: RetailOpsEnv(task, bundle)  # noqa: E731

    samples_dir = output_dir / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    samples: dict[str, list[Trajectory]] = {}
    for position, task in enumerate(face):
        samples[task.task_id] = _load_samples_for(
            task,
            samples_dir,
            policy=policy,
            env_factory=env_factory,
            samples_per_task=config.sampling.samples_per_task,
            episode_timeout=config.sampling.episode_timeout,
        )
        if (position + 1) % 20 == 0:
            elapsed = time.perf_counter() - started
            print(f"[sampling] {position + 1}/{len(face)} tasks, {elapsed:.0f}s", flush=True)

    oracle = {task.task_id: oracle_reference(task, env_factory) for task in face}
    report = build_preference_pairs(tasks=face, samples=samples, oracle=oracle)
    wall_time_seconds = time.perf_counter() - started

    provenance = {
        "code_commit": _git_commit(),
        "model": config.model.model_dump(mode="json"),
        "adapter": config.adapter.model_dump(mode="json"),
        "sampling_settings": settings.model_dump(mode="json"),
        "samples_per_task": config.sampling.samples_per_task,
        "episode_timeout": config.sampling.episode_timeout,
        "seed": config.seed,
        "phrasing": {
            **config.phrasing.model_dump(mode="json"),
            "record_count": len(records),
            "actual_bank_sha256": actual_bank_sha256,
        },
        "face_task_count": len(face),
        "wall_time_seconds": wall_time_seconds,
    }

    pairs_path = output_dir / "pairs.jsonl"
    if pairs_path.exists():
        msg = f"拒绝覆盖既有产物: {pairs_path}"
        raise FileExistsError(msg)
    write_jsonl(
        pairs_path,
        (pair.model_dump(mode="json") for pair in report.pairs),
    )
    write_json(
        report_path,
        {**report.model_dump(mode="json"), "provenance": provenance},
    )

    print(
        f"[pairs] total={report.pairs_total} "
        f"deny_tasks={report.deny_tasks_with_pairs}/{report.deny_tasks} "
        f"per_offset={json.dumps(report.pairs_per_offset, ensure_ascii=False)}"
    )
    print(
        f"[premise] allow_side_violation_samples={report.allow_side_violation_samples} "
        f"allow_side_failed_samples={report.allow_side_failed_samples} "
        f"premise_ok={report.premise_ok}"
    )
    if not report.premise_ok:
        print(
            "[premise] 放行侧出现执行类错误——按预注册停下回用户决策，"
            "不得构造对冲对、不得继续训练。",
            flush=True,
        )
        return _EXIT_PREMISE_VIOLATED
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
