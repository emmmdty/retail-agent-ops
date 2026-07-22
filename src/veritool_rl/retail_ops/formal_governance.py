"""Two-stage authorization and loading for the sealed R2 formal holdout."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from veritool_rl.artifacts import sha256_file
from veritool_rl.paths import validate_project_relative_path
from veritool_rl.retail_ops.formal_manifests import (
    FormalHoldoutReceipt,
    _parse_and_validate_private_rows,
)
from veritool_rl.retail_ops.formal_tasks import FormalTaskRecord
from veritool_rl.retail_ops.governance import EvidencePurpose

_PRIVATE_R2_ROOT = Path("data/private/retail_ops/v1/r2")
_AUTHORIZATION_SEAL = object()


@dataclass(frozen=True)
class AuthorizedFormalHoldout:
    """Opaque result of release-purpose path and hash authorization."""

    receipt: FormalHoldoutReceipt
    artifact_path: Path
    logical_path: Path
    artifact_sha256: str
    _seal: object = field(repr=False, compare=False)


def authorize_formal_holdout(
    receipt: FormalHoldoutReceipt,
    artifact_path: Path,
    logical_path: Path,
    purpose: EvidencePurpose,
) -> AuthorizedFormalHoldout:
    """Authorize a formal holdout without parsing any task content."""
    if purpose is not EvidencePurpose.RELEASE:
        raise PermissionError("sealed formal holdout 只允许 release 目的访问")

    validated_receipt = FormalHoldoutReceipt.model_validate(receipt.model_dump(mode="json"))
    validate_project_relative_path(logical_path, "sealed formal holdout 路径")
    expected_logical_path = _PRIVATE_R2_ROOT / validated_receipt.dataset_version / "holdout.jsonl"
    if logical_path != expected_logical_path:
        raise ValueError("sealed formal holdout 路径必须精确指向冻结数据版本的 holdout.jsonl")

    try:
        artifact_exists = artifact_path.exists()
        artifact_is_file = artifact_path.is_file()
    except OSError:
        raise ValueError("formal holdout artifact 状态检查失败") from None
    if not artifact_exists:
        raise ValueError("formal holdout artifact 不存在")
    if not artifact_is_file:
        raise ValueError("formal holdout artifact 必须是普通文件")
    try:
        artifact_sha256 = sha256_file(artifact_path)
    except OSError:
        raise ValueError("formal holdout artifact 无法读取或计算 SHA-256") from None
    if artifact_sha256 != validated_receipt.artifact_sha256:
        raise ValueError("formal holdout artifact SHA-256 不匹配")
    return AuthorizedFormalHoldout(
        receipt=validated_receipt,
        artifact_path=artifact_path,
        logical_path=logical_path,
        artifact_sha256=artifact_sha256,
        _seal=_AUTHORIZATION_SEAL,
    )


def load_authorized_formal_holdout(
    authorization: AuthorizedFormalHoldout,
) -> tuple[FormalTaskRecord, ...]:
    """Recheck an authorization's hash, then parse and verify every private row."""
    if (
        not isinstance(authorization, AuthorizedFormalHoldout)
        or authorization._seal is not _AUTHORIZATION_SEAL
    ):
        raise PermissionError("formal holdout 缺少有效授权")
    try:
        content = authorization.artifact_path.read_bytes()
    except OSError:
        raise ValueError("formal holdout artifact 授权后无法读取") from None
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if (
        actual_sha256 != authorization.artifact_sha256
        or actual_sha256 != authorization.receipt.artifact_sha256
    ):
        raise ValueError("formal holdout 授权后 artifact SHA-256 已改变")
    return _parse_and_validate_private_rows(authorization.receipt, content)
