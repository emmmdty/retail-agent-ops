"""Two-stage authorization and loading for the sealed R2 formal holdout."""

from __future__ import annotations

import contextlib
import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from weakref import WeakSet

from veritool_rl.core.paths import validate_project_relative_path
from veritool_rl.retail_ops.build.formal_manifests import (
    VerifiedFormalDataset,
    _parse_and_validate_private_rows,
    _require_verified_dataset,
)
from veritool_rl.retail_ops.domain.formal_tasks import FormalTaskRecord
from veritool_rl.retail_ops.release.governance import EvidencePurpose

_PRIVATE_R2_ROOT = Path("data/private/retail_ops/v1/r2")
_READ_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True, init=False, eq=False, slots=True, weakref_slot=True)
class AuthorizedFormalHoldout:
    """Registered capability issued only after release/path/hash authorization."""

    dataset: VerifiedFormalDataset
    artifact_path: Path
    logical_path: Path
    trusted_private_root: Path
    artifact_sha256: str

    def __new__(cls) -> AuthorizedFormalHoldout:
        raise TypeError("AuthorizedFormalHoldout 只能由 authorize_formal_holdout 创建")

    @classmethod
    def _issue(
        cls,
        *,
        dataset: VerifiedFormalDataset,
        artifact_path: Path,
        logical_path: Path,
        trusted_private_root: Path,
        artifact_sha256: str,
    ) -> AuthorizedFormalHoldout:
        instance = object.__new__(cls)
        object.__setattr__(instance, "dataset", dataset)
        object.__setattr__(instance, "artifact_path", artifact_path)
        object.__setattr__(instance, "logical_path", logical_path)
        object.__setattr__(instance, "trusted_private_root", trusted_private_root)
        object.__setattr__(instance, "artifact_sha256", artifact_sha256)
        _AUTHORIZED_HOLDOUTS.add(instance)
        return instance


_AUTHORIZED_HOLDOUTS: WeakSet[AuthorizedFormalHoldout] = WeakSet()


def authorize_formal_holdout(
    dataset: VerifiedFormalDataset,
    artifact_path: Path,
    logical_path: Path,
    purpose: EvidencePurpose,
    *,
    trusted_private_root: Path,
) -> AuthorizedFormalHoldout:
    """Authorize a trusted-root artifact without parsing any task content."""
    if purpose is not EvidencePurpose.RELEASE:
        raise PermissionError("sealed formal holdout 只允许 release 目的访问")
    _require_verified_dataset(dataset)

    validate_project_relative_path(logical_path, "sealed formal holdout 路径")
    expected_logical_path = _PRIVATE_R2_ROOT / dataset.receipt.dataset_version / "holdout.jsonl"
    if logical_path != expected_logical_path:
        raise ValueError("sealed formal holdout 路径必须精确指向冻结数据版本的 holdout.jsonl")

    content = _read_trusted_regular_file(artifact_path, trusted_private_root)
    artifact_sha256 = hashlib.sha256(content).hexdigest()
    if artifact_sha256 != dataset.holdout_receipt.artifact_sha256:
        raise ValueError("formal holdout artifact SHA-256 不匹配")
    return AuthorizedFormalHoldout._issue(
        dataset=dataset,
        artifact_path=artifact_path,
        logical_path=logical_path,
        trusted_private_root=trusted_private_root,
        artifact_sha256=artifact_sha256,
    )


def load_authorized_formal_holdout(
    authorization: AuthorizedFormalHoldout,
) -> tuple[FormalTaskRecord, ...]:
    """Safely reopen, rehash, then parse every authorized private row."""
    if (
        not isinstance(authorization, AuthorizedFormalHoldout)
        or authorization not in _AUTHORIZED_HOLDOUTS
    ):
        raise PermissionError("formal holdout 缺少有效授权")
    _require_verified_dataset(authorization.dataset)
    content = _read_trusted_regular_file(
        authorization.artifact_path,
        authorization.trusted_private_root,
    )
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if (
        actual_sha256 != authorization.artifact_sha256
        or actual_sha256 != authorization.dataset.holdout_receipt.artifact_sha256
    ):
        raise ValueError("formal holdout 授权后 artifact SHA-256 已改变")
    return _parse_and_validate_private_rows(
        authorization.dataset.holdout_receipt,
        content,
    )


def _read_trusted_regular_file(
    artifact_path: Path,
    trusted_private_root: Path,
) -> bytes:
    """Read a root-confined non-symlink regular file from one fstat-checked fd."""
    root_absolute = Path(os.path.abspath(os.fspath(trusted_private_root)))
    artifact_absolute = Path(os.path.abspath(os.fspath(artifact_path)))
    try:
        relative = artifact_absolute.relative_to(root_absolute)
    except ValueError:
        raise ValueError("formal holdout artifact 必须位于 trusted_private_root 内") from None
    if relative == Path(".") or not relative.parts:
        raise ValueError("formal holdout artifact 必须指向 trusted_private_root 内的文件")

    try:
        root_status = os.lstat(root_absolute)
    except FileNotFoundError:
        raise ValueError("trusted_private_root 不存在") from None
    except OSError:
        raise ValueError("trusted_private_root 状态检查失败") from None
    if stat.S_ISLNK(root_status.st_mode):
        raise ValueError("trusted_private_root 不得是符号链接")
    if not stat.S_ISDIR(root_status.st_mode):
        raise ValueError("trusted_private_root 必须是目录")

    opened_fds: list[int] = []
    try:
        root_fd = os.open(
            root_absolute,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
        opened_fds.append(root_fd)
        parent_fd = root_fd
        for part in relative.parts[:-1]:
            component_status = os.stat(part, dir_fd=parent_fd, follow_symlinks=False)
            if stat.S_ISLNK(component_status.st_mode):
                raise ValueError("formal holdout artifact 的祖先不得是符号链接")
            if not stat.S_ISDIR(component_status.st_mode):
                raise ValueError("formal holdout artifact 的祖先必须是目录")
            parent_fd = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=parent_fd,
            )
            opened_fds.append(parent_fd)

        filename = relative.parts[-1]
        try:
            file_status = os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            raise ValueError("formal holdout artifact 不存在") from None
        if stat.S_ISLNK(file_status.st_mode):
            raise ValueError("formal holdout artifact 不得是符号链接")
        if not stat.S_ISREG(file_status.st_mode):
            raise ValueError("formal holdout artifact 必须是普通文件")
        artifact_fd = os.open(
            filename,
            os.O_RDONLY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        opened_fds.append(artifact_fd)
        opened_status = os.fstat(artifact_fd)
        if not stat.S_ISREG(opened_status.st_mode):
            raise ValueError("formal holdout artifact 必须是普通文件")

        chunks: list[bytes] = []
        while chunk := os.read(artifact_fd, _READ_CHUNK_SIZE):
            chunks.append(chunk)
        return b"".join(chunks)
    except ValueError:
        raise
    except FileNotFoundError:
        raise ValueError("formal holdout artifact 不存在") from None
    except OSError:
        raise ValueError("formal holdout artifact 安全读取失败") from None
    finally:
        for fd in reversed(opened_fds):
            with contextlib.suppress(OSError):
                os.close(fd)
