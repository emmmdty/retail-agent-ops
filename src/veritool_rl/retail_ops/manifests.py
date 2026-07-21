"""RetailOps qualification 构建与任务 manifest 校验。"""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import Field

from veritool_rl.artifacts import (
    canonical_json,
    create_output_dir,
    sha256_file,
    write_json,
    write_jsonl,
)
from veritool_rl.retail_ops.bundle import LoadedRetailOpsBundle, load_bundle
from veritool_rl.retail_ops.tasks import build_qualification_tasks
from veritool_rl.trajectory import TaskSpec
from veritool_rl.trajectory.schema import StrictModel


class TaskManifest(StrictModel):
    """冻结任务集合的顺序、来源和内容摘要。"""

    schema_version: Literal["1.0"] = "1.0"
    bundle_id: Literal["retail_ops"] = "retail_ops"
    bundle_version: Literal["1.0.0"] = "1.0.0"
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    split: Literal["train", "dev", "qualification", "holdout"]
    seed: int
    task_count: int = Field(ge=1)
    category_counts: dict[str, int]
    task_ids: list[str]
    family_ids: list[str]
    task_sha256: dict[str, str]
    tasks_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _validate_qualification_tasks(
    tasks: list[TaskSpec], bundle: LoadedRetailOpsBundle
) -> tuple[dict[str, int], list[str], list[str]]:
    categories = list(bundle.bundle.task_categories)
    actual_categories = [task.scenario.value for task in tasks]
    expected_categories = categories * 2
    if len(tasks) != 12 or actual_categories != expected_categories:
        raise ValueError("qualification 任务必须按冻结顺序覆盖六类各两条")
    if any(task.split != "qualification" for task in tasks):
        raise ValueError("qualification 构建只能包含 qualification 任务")

    task_ids = [task.task_id for task in tasks]
    if len(set(task_ids)) != len(task_ids):
        raise ValueError("qualification task_id 必须唯一")

    family_ids: list[str] = []
    for task in tasks:
        family_id = task.metadata.get("family_id")
        if not isinstance(family_id, str) or not family_id:
            raise ValueError(f"qualification 任务缺少 family_id: {task.task_id}")
        family_ids.append(family_id)
    if len(set(family_ids)) != len(family_ids):
        raise ValueError("qualification family_id 必须唯一")

    counts = Counter(actual_categories)
    category_counts = {category: counts[category] for category in categories}
    if set(counts) != set(categories) or set(category_counts.values()) != {2}:
        raise ValueError("qualification 任务必须覆盖六类各两条")
    return category_counts, task_ids, family_ids


def _task_digest(task: TaskSpec) -> str:
    serialized = canonical_json(task.model_dump(mode="json"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_qualification(
    bundle_dir: Path, seed: int, output_dir: Path
) -> TaskManifest:
    """从冻结 bundle 构建十二条 qualification 任务与不可变 manifest。"""
    bundle = load_bundle(bundle_dir)
    tasks = build_qualification_tasks(seed)
    category_counts, task_ids, family_ids = _validate_qualification_tasks(tasks, bundle)

    create_output_dir(output_dir)
    tasks_path = output_dir / "tasks.jsonl"
    write_jsonl(tasks_path, (task.model_dump(mode="json") for task in tasks))
    task_sha256 = {task.task_id: _task_digest(task) for task in tasks}
    manifest = TaskManifest(
        bundle_id=bundle.bundle.bundle_id,
        bundle_version=bundle.bundle.bundle_version,
        bundle_sha256=bundle.bundle_sha256,
        split="qualification",
        seed=seed,
        task_count=len(tasks),
        category_counts=category_counts,
        task_ids=task_ids,
        family_ids=family_ids,
        task_sha256=task_sha256,
        tasks_file_sha256=sha256_file(tasks_path),
    )
    write_json(output_dir / "manifest.json", manifest.model_dump(mode="json"))
    return manifest


def load_task_manifest(path: Path) -> TaskManifest:
    """读取任务 manifest 并执行严格 schema 校验。"""
    return TaskManifest.model_validate_json(path.read_text(encoding="utf-8"))


def load_built_tasks(build_dir: Path) -> dict[str, TaskSpec]:
    """按 manifest 顺序读取任务并验证文件与逐任务摘要。"""
    manifest = load_task_manifest(build_dir / "manifest.json")
    tasks_path = build_dir / "tasks.jsonl"
    if sha256_file(tasks_path) != manifest.tasks_file_sha256:
        raise ValueError("tasks.jsonl 与 manifest SHA-256 不匹配")
    tasks = [
        TaskSpec.from_jsonl(line)
        for line in tasks_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    indexed = {task.task_id: task for task in tasks}
    if list(indexed) != manifest.task_ids or len(indexed) != manifest.task_count:
        raise ValueError("tasks.jsonl 的任务集合或顺序与 manifest 不一致")
    for task_id, task in indexed.items():
        digest = _task_digest(task)
        if digest != manifest.task_sha256.get(task_id):
            raise ValueError(f"任务内容 SHA-256 不匹配: {task_id}")
    return indexed
