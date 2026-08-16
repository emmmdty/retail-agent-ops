"""RetailOps holdout 的公开 receipt、split 隔离与 sealed 访问门禁。"""

from __future__ import annotations

import re
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from veritool_rl.core.artifacts import sha256_file
from veritool_rl.core.paths import validate_project_relative_path
from veritool_rl.core.trajectory.schema import StrictModel
from veritool_rl.retail_ops.build.manifests import TaskManifest

_PRIVATE_RETAIL_OPS_ROOT = Path("data/private/retail_ops/v1")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class HoldoutReceipt(StrictModel):
    """不含任务真值、prompt 或失败样例的公开 holdout 指纹。"""

    schema_version: Literal["1.0"] = "1.0"
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluator_id: Literal["retail_ops_v1"] = "retail_ops_v1"
    split: Literal["holdout"] = "holdout"
    task_count: int = Field(ge=1)
    category_counts: dict[str, int]
    task_ids: list[str]
    family_ids: list[str]
    task_sha256: dict[str, str]
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_evidence_consistency(self) -> Self:
        """校验公开指纹之间的数量、标识与摘要一致性。"""
        if any(count < 0 for count in self.category_counts.values()):
            raise ValueError("类别数量不得为负数")
        if sum(self.category_counts.values()) != self.task_count:
            raise ValueError("类别数量总和必须等于 task_count")

        if len(self.task_ids) != self.task_count:
            raise ValueError("task_ids 数量必须等于 task_count")
        if any(not task_id.strip() for task_id in self.task_ids):
            raise ValueError("task_id 不得为空")
        if len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("task_id 必须唯一")

        if len(self.family_ids) != self.task_count:
            raise ValueError("family_ids 数量必须等于 task_count")
        if any(not family_id.strip() for family_id in self.family_ids):
            raise ValueError("family_id 不得为空")

        if set(self.task_sha256) != set(self.task_ids):
            raise ValueError("task_sha256 key 必须与 task_ids 一致")
        if any(_SHA256_PATTERN.fullmatch(digest) is None for digest in self.task_sha256.values()):
            raise ValueError("task_sha256 必须是小写 64 位十六进制")
        return self


class EvidencePurpose(StrEnum):
    """证据访问目的；只有 release 可以读取 sealed holdout。"""

    BUILD = "build"
    DEVELOP = "develop"
    RELEASE = "release"


def assert_split_isolation(manifests: Sequence[TaskManifest]) -> None:
    """拒绝任意两个 split manifest 之间的任务、族或内容交叉。"""
    seen_task_ids: set[str] = set()
    seen_family_ids: set[str] = set()
    seen_content_hashes: set[str] = set()

    for manifest in manifests:
        if len(manifest.task_ids) != len(set(manifest.task_ids)):
            raise ValueError("manifest 内 task_id 重复")
        content_hash_values = list(manifest.task_sha256.values())
        if len(content_hash_values) != len(set(content_hash_values)):
            raise ValueError("manifest 内内容 SHA-256 重复")

        task_ids = set(manifest.task_ids)
        family_ids = set(manifest.family_ids)
        content_hashes = set(content_hash_values)

        if overlap := seen_task_ids & task_ids:
            raise ValueError(f"split task_id 交叉: {sorted(overlap)}")
        if overlap := seen_family_ids & family_ids:
            raise ValueError(f"split family_id 交叉: {sorted(overlap)}")
        if overlap := seen_content_hashes & content_hashes:
            raise ValueError(f"split 内容 SHA-256 交叉: {sorted(overlap)}")

        seen_task_ids.update(task_ids)
        seen_family_ids.update(family_ids)
        seen_content_hashes.update(content_hashes)


def authorize_holdout(
    receipt: HoldoutReceipt,
    artifact_path: Path,
    logical_path: Path,
    purpose: EvidencePurpose,
) -> None:
    """校验 release 目的、sealed 逻辑路径和物理 artifact 摘要。"""
    if purpose is not EvidencePurpose.RELEASE:
        raise PermissionError("sealed holdout 只允许 release 目的访问")

    validate_project_relative_path(logical_path, "sealed artifact 路径")
    try:
        relative_path = logical_path.relative_to(_PRIVATE_RETAIL_OPS_ROOT)
    except ValueError:
        raise ValueError("sealed artifact 路径必须位于 data/private/retail_ops/v1/") from None
    if relative_path == Path("."):
        raise ValueError("sealed artifact 路径必须指向 private 根目录下的文件")

    try:
        artifact_exists = artifact_path.exists()
        artifact_is_file = artifact_path.is_file()
    except OSError:
        raise ValueError("holdout artifact 状态检查失败") from None
    if not artifact_exists:
        raise ValueError("holdout artifact 不存在")
    if not artifact_is_file:
        raise ValueError("holdout artifact 必须是普通文件")

    try:
        artifact_sha256 = sha256_file(artifact_path)
    except OSError:
        raise ValueError("holdout artifact 无法读取或计算 SHA-256") from None
    if artifact_sha256 != receipt.artifact_sha256:
        raise ValueError("holdout artifact SHA-256 不匹配")
