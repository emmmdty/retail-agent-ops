"""RetailOps R2 sealed formal holdout authorization and loading tests."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

import veritool_rl.retail_ops.release.formal_governance as formal_governance_module
from veritool_rl.core.artifacts import canonical_json, sha256_file
from veritool_rl.retail_ops.build.formal_manifests import (
    FormalHoldoutReceipt,
    VerifiedFormalDataset,
    load_verified_formal_dataset,
    write_formal_task_set,
)
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.formal_tasks import build_formal_task_set
from veritool_rl.retail_ops.release.formal_governance import (
    AuthorizedFormalHoldout,
    authorize_formal_holdout,
    load_authorized_formal_holdout,
)
from veritool_rl.retail_ops.release.governance import EvidencePurpose

DATASET_VERSION = "retail_ops_v1_r2_20260722"
LOGICAL_HOLDOUT = Path("data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722/holdout.jsonl")


class ExplodingArtifactPath:
    """Fail if governance touches the artifact before public gates."""

    def __fspath__(self) -> str:
        raise AssertionError("artifact path was resolved too early")

    def exists(self) -> bool:
        raise AssertionError("artifact existence was checked too early")

    def is_file(self) -> bool:
        raise AssertionError("artifact type was checked too early")

    def read_bytes(self) -> bytes:
        raise AssertionError("artifact content was read too early")


def _write_dataset(tmp_path: Path) -> tuple[Path, Path, VerifiedFormalDataset]:
    private_dir = tmp_path / "private"
    public_dir = tmp_path / "public"
    write_formal_task_set(
        build_formal_task_set(DATASET_VERSION, seed=0),
        load_bundle(Path("domains/retail_ops/v1")),
        private_dir,
        public_dir,
    )
    return private_dir, public_dir, load_verified_formal_dataset(public_dir)


def _refresh_public_hash(public_dir: Path, filename: str) -> None:
    dataset_path = public_dir / "dataset.json"
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    payload["public_files_sha256"][filename] = sha256_file(public_dir / filename)
    dataset_path.write_text(canonical_json(payload) + "\n", encoding="utf-8")


def _rewrite_holdout_receipt(
    dataset: VerifiedFormalDataset,
    **updates: object,
) -> VerifiedFormalDataset:
    receipt_path = dataset.public_dir / "holdout-receipt.json"
    payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    payload.update(updates)
    receipt_path.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    _refresh_public_hash(dataset.public_dir, "holdout-receipt.json")
    return load_verified_formal_dataset(dataset.public_dir)


def _rewrite_rows(
    artifact: Path,
    dataset: VerifiedFormalDataset,
    mutate: object,
) -> VerifiedFormalDataset:
    rows = [json.loads(line) for line in artifact.read_text(encoding="utf-8").splitlines()]
    assert callable(mutate)
    mutate(rows)
    artifact.write_text(
        "\n".join(canonical_json(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    return _rewrite_holdout_receipt(
        dataset,
        artifact_sha256=sha256_file(artifact),
    )


def _authorize(
    dataset: VerifiedFormalDataset,
    artifact: Path,
    trusted_private_root: Path,
) -> AuthorizedFormalHoldout:
    return authorize_formal_holdout(
        dataset,
        artifact,
        LOGICAL_HOLDOUT,
        EvidencePurpose.RELEASE,
        trusted_private_root=trusted_private_root,
    )


@pytest.mark.parametrize(
    "purpose",
    [EvidencePurpose.BUILD, EvidencePurpose.DEVELOP, cast(EvidencePurpose, "release")],
)
def test_non_release_purpose_fails_before_any_private_artifact_access(
    tmp_path: Path,
    purpose: EvidencePurpose,
) -> None:
    _, _, dataset = _write_dataset(tmp_path)

    with pytest.raises(PermissionError, match="只允许 release"):
        authorize_formal_holdout(
            dataset,
            cast(Path, ExplodingArtifactPath()),
            LOGICAL_HOLDOUT,
            purpose,
            trusted_private_root=cast(Path, ExplodingArtifactPath()),
        )


def test_unverified_dataset_fails_before_private_artifact_access(tmp_path: Path) -> None:
    _write_dataset(tmp_path)
    forged = object.__new__(VerifiedFormalDataset)

    with pytest.raises(PermissionError, match="verification capability"):
        authorize_formal_holdout(
            forged,
            cast(Path, ExplodingArtifactPath()),
            LOGICAL_HOLDOUT,
            EvidencePurpose.RELEASE,
            trusted_private_root=cast(Path, ExplodingArtifactPath()),
        )


@pytest.mark.parametrize(
    "logical_path",
    [
        Path("data/private/retail_ops/v1/r2/other/holdout.jsonl"),
        Path("data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722/dev.jsonl"),
        Path("reports/retail_ops/v1/holdout.jsonl"),
        Path("data/private/retail_ops/v1/r2/../holdout.jsonl"),
        Path("/data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722/holdout.jsonl"),
    ],
)
def test_invalid_logical_path_fails_before_private_artifact_access(
    tmp_path: Path,
    logical_path: Path,
) -> None:
    _, _, dataset = _write_dataset(tmp_path)

    with pytest.raises(ValueError, match="sealed formal holdout 路径"):
        authorize_formal_holdout(
            dataset,
            cast(Path, ExplodingArtifactPath()),
            logical_path,
            EvidencePurpose.RELEASE,
            trusted_private_root=cast(Path, ExplodingArtifactPath()),
        )


def test_authorized_holdout_loads_complete_verified_records(tmp_path: Path) -> None:
    private_dir, _, dataset = _write_dataset(tmp_path)
    authorization = _authorize(dataset, private_dir / "holdout.jsonl", private_dir)

    records = load_authorized_formal_holdout(authorization)

    assert len(records) == 120
    assert all(record.task.split == "holdout" for record in records)
    assert [record.task.scenario.value for record in records] == [
        scenario
        for scenario in (
            "lookup_status",
            "refund_eligible",
            "refund_denied_window",
            "refund_denied_ownership",
            "refund_denied_duplicate",
            "refund_recovery",
        )
        for _ in range(20)
    ]


def test_authorization_rejects_missing_directory_and_wrong_hash(tmp_path: Path) -> None:
    private_dir, _, dataset = _write_dataset(tmp_path)
    missing = private_dir / "missing.jsonl"
    directory = private_dir / "directory"
    directory.mkdir()

    with pytest.raises(ValueError, match="artifact 不存在"):
        _authorize(dataset, missing, private_dir)
    with pytest.raises(ValueError, match="artifact 必须是普通文件"):
        _authorize(dataset, directory, private_dir)
    wrong_hash_dataset = _rewrite_holdout_receipt(dataset, artifact_sha256="0" * 64)
    with pytest.raises(ValueError, match="artifact SHA-256 不匹配"):
        _authorize(wrong_hash_dataset, private_dir / "holdout.jsonl", private_dir)


def test_authorization_rejects_regular_file_outside_trusted_root(tmp_path: Path) -> None:
    private_dir, _, dataset = _write_dataset(tmp_path)
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes((private_dir / "holdout.jsonl").read_bytes())

    with pytest.raises(ValueError, match="trusted_private_root"):
        _authorize(dataset, outside, private_dir)


def test_authorization_rejects_final_and_ancestor_symlinks(tmp_path: Path) -> None:
    private_dir, _, dataset = _write_dataset(tmp_path)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside = outside_dir / "holdout.jsonl"
    outside.write_bytes((private_dir / "holdout.jsonl").read_bytes())
    final_link = private_dir / "final-link.jsonl"
    final_link.symlink_to(outside)

    with pytest.raises(ValueError, match="符号链接"):
        _authorize(dataset, final_link, private_dir)

    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()
    ancestor_link = trusted_root / "linked-parent"
    ancestor_link.symlink_to(outside_dir, target_is_directory=True)
    with pytest.raises(ValueError, match="符号链接"):
        _authorize(dataset, ancestor_link / "holdout.jsonl", trusted_root)


def test_authorization_rejects_symlinked_trusted_root(tmp_path: Path) -> None:
    private_dir, _, dataset = _write_dataset(tmp_path)
    root_link = tmp_path / "private-link"
    root_link.symlink_to(private_dir, target_is_directory=True)

    with pytest.raises(ValueError, match=r"trusted_private_root.*符号链接"):
        _authorize(dataset, root_link / "holdout.jsonl", root_link)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda rows: rows.reverse(), "顺序"),
        (lambda rows: rows.pop(), "数量"),
        (lambda rows: rows.append(rows[-1]), "数量"),
        (
            lambda rows: rows[0]["task"].__setitem__("scenario", "refund_eligible"),
            "场景顺序",
        ),
        (
            lambda rows: rows[0]["task"]["initial_state"].__setitem__("current_day", 999),
            "记录指纹",
        ),
        (
            lambda rows: rows[0].__setitem__("task_fingerprint", "0" * 64),
            "记录指纹",
        ),
        (
            lambda rows: rows[0].__setitem__("dataset_version", "other-dataset"),
            "dataset_version",
        ),
        (
            lambda rows: rows[0].__setitem__("bundle_sha256", "0" * 64),
            "bundle_sha256",
        ),
    ],
)
def test_authorized_loader_rejects_row_count_order_truth_and_binding_tampering(
    tmp_path: Path,
    mutator: object,
    message: str,
) -> None:
    private_dir, _, dataset = _write_dataset(tmp_path)
    artifact = private_dir / "holdout.jsonl"
    changed_dataset = _rewrite_rows(artifact, dataset, mutator)
    authorization = _authorize(changed_dataset, artifact, private_dir)

    with pytest.raises((ValueError, ValidationError), match=message):
        load_authorized_formal_holdout(authorization)


def test_authorized_loader_rechecks_hash_before_parsing(tmp_path: Path) -> None:
    private_dir, _, dataset = _write_dataset(tmp_path)
    artifact = private_dir / "holdout.jsonl"
    authorization = _authorize(dataset, artifact, private_dir)
    artifact.write_text("not-json\n", encoding="utf-8")

    with pytest.raises(ValueError, match="授权后 artifact SHA-256 已改变"):
        load_authorized_formal_holdout(authorization)


def test_authorized_loader_rejects_symlink_substitution_after_authorization(
    tmp_path: Path,
) -> None:
    private_dir, _, dataset = _write_dataset(tmp_path)
    artifact = private_dir / "holdout.jsonl"
    authorization = _authorize(dataset, artifact, private_dir)
    outside = tmp_path / "outside.jsonl"
    artifact.rename(outside)
    artifact.symlink_to(outside)

    with pytest.raises(ValueError, match="符号链接"):
        load_authorized_formal_holdout(authorization)


def test_holdout_receipt_rejects_unknown_keys_and_internal_duplicates(
    tmp_path: Path,
) -> None:
    _, public_dir, _ = _write_dataset(tmp_path)
    payload = json.loads((public_dir / "holdout-receipt.json").read_text(encoding="utf-8"))

    payload["private_path"] = "/tmp/holdout.jsonl"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        FormalHoldoutReceipt.model_validate(payload)

    payload.pop("private_path")
    payload["task_fingerprints"][1] = payload["task_fingerprints"][0]
    with pytest.raises(ValidationError, match=r"task_fingerprints.*唯一"):
        FormalHoldoutReceipt.model_validate(payload)


def test_holdout_loader_rejects_extra_private_row_key_before_task_use(
    tmp_path: Path,
) -> None:
    private_dir, _, dataset = _write_dataset(tmp_path)
    artifact = private_dir / "holdout.jsonl"

    def add_secret(rows: list[dict[str, object]]) -> None:
        rows[0]["secret"] = "not-allowed"

    changed_dataset = _rewrite_rows(artifact, dataset, add_secret)
    authorization = _authorize(changed_dataset, artifact, private_dir)

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_authorized_formal_holdout(authorization)


def test_authorized_capability_cannot_be_constructed_forged_or_replaced(
    tmp_path: Path,
) -> None:
    private_dir, _, dataset = _write_dataset(tmp_path)
    with pytest.raises(TypeError, match="只能由 authorize_formal_holdout 创建"):
        AuthorizedFormalHoldout()

    forged = object.__new__(AuthorizedFormalHoldout)
    with pytest.raises(PermissionError, match="缺少有效授权"):
        load_authorized_formal_holdout(forged)

    authorization = _authorize(dataset, private_dir / "holdout.jsonl", private_dir)
    with pytest.raises(TypeError):
        replace(authorization)


def test_authorization_hashes_regular_file_bytes_from_fstat_checked_fd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_dir, _, dataset = _write_dataset(tmp_path)
    original_open = os.open
    original_fstat = os.fstat
    original_read = os.read
    final_open_flags: dict[int, int] = {}
    fstat_fds: set[int] = set()
    read_fds: set[int] = set()

    def tracked_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        fd = original_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]
        if not flags & os.O_DIRECTORY:
            final_open_flags[fd] = flags
        return fd

    def tracked_fstat(fd: int) -> os.stat_result:
        fstat_fds.add(fd)
        return original_fstat(fd)

    def tracked_read(fd: int, length: int) -> bytes:
        read_fds.add(fd)
        return original_read(fd, length)

    monkeypatch.setattr(formal_governance_module.os, "open", tracked_open)
    monkeypatch.setattr(formal_governance_module.os, "fstat", tracked_fstat)
    monkeypatch.setattr(formal_governance_module.os, "read", tracked_read)

    authorization = _authorize(dataset, private_dir / "holdout.jsonl", private_dir)
    load_authorized_formal_holdout(authorization)

    assert final_open_flags
    assert all(flags & os.O_NOFOLLOW for flags in final_open_flags.values())
    assert set(final_open_flags).issubset(fstat_fds)
    assert set(final_open_flags).issubset(read_fds)
