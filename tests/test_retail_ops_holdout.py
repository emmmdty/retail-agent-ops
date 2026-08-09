"""RetailOps holdout receipt、split 隔离与 sealed 访问契约。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

import pytest
from pydantic import ValidationError

from veritool_rl.core.artifacts import sha256_file
from veritool_rl.retail_ops.build.manifests import TaskManifest
from veritool_rl.retail_ops.release.governance import (
    EvidencePurpose,
    HoldoutReceipt,
    assert_split_isolation,
    authorize_holdout,
)

PRIVATE_HOLDOUT_PATH = Path(
    "data/private/retail_ops/v1/holdout/tasks.jsonl"
)


def _manifest(
    split: Literal["train", "dev", "qualification", "holdout"],
    task_id: str,
    family_id: str,
    content_hash: str,
) -> TaskManifest:
    return TaskManifest(
        bundle_sha256="c" * 64,
        split=split,
        seed=0,
        task_count=1,
        category_counts={"lookup_status": 1},
        task_ids=[task_id],
        family_ids=[family_id],
        task_sha256={task_id: content_hash},
        tasks_file_sha256="d" * 64,
    )


def _receipt(artifact: Path, **updates: object) -> HoldoutReceipt:
    values: dict[str, object] = {
        "bundle_sha256": "c" * 64,
        "task_count": 1,
        "category_counts": {"lookup_status": 1},
        "task_ids": ["H1"],
        "family_ids": ["HF1"],
        "task_sha256": {"H1": "d" * 64},
        "artifact_sha256": sha256_file(artifact) if artifact.is_file() else "0" * 64,
    }
    values.update(updates)
    return HoldoutReceipt.model_validate(values)


def _malformed_manifest(
    task_ids: list[str],
    family_ids: list[str],
    task_sha256: dict[str, str],
) -> TaskManifest:
    return TaskManifest(
        bundle_sha256="c" * 64,
        split="train",
        seed=0,
        task_count=len(task_ids),
        category_counts={"lookup_status": len(task_ids)},
        task_ids=task_ids,
        family_ids=family_ids,
        task_sha256=task_sha256,
        tasks_file_sha256="d" * 64,
    )


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"category_counts": {"lookup_status": -1}}, "类别数量不得为负数"),
        ({"category_counts": {"lookup_status": 2}}, "类别数量总和必须等于 task_count"),
        ({"task_ids": [""]}, "task_id 不得为空"),
        (
            {
                "task_count": 2,
                "category_counts": {"lookup_status": 2},
                "task_ids": ["H1", "H1"],
                "family_ids": ["HF1", "HF2"],
            },
            "task_id 必须唯一",
        ),
        (
            {
                "task_count": 2,
                "category_counts": {"lookup_status": 2},
                "family_ids": ["HF1", "HF2"],
            },
            "task_ids 数量必须等于 task_count",
        ),
        ({"family_ids": [""]}, "family_id 不得为空"),
        (
            {
                "task_count": 2,
                "category_counts": {"lookup_status": 2},
                "task_ids": ["H1", "H2"],
                "task_sha256": {"H1": "d" * 64, "H2": "e" * 64},
            },
            "family_ids 数量必须等于 task_count",
        ),
        ({"task_sha256": {"OTHER": "d" * 64}}, "task_sha256 key 必须与 task_ids 一致"),
        ({"task_sha256": {"H1": "D" * 64}}, "task_sha256 必须是小写 64 位十六进制"),
        ({"task_sha256": {"H1": "d" * 63}}, "task_sha256 必须是小写 64 位十六进制"),
        ({"task_sha256": {"H1": "z" * 64}}, "task_sha256 必须是小写 64 位十六进制"),
    ],
)
def test_holdout_receipt_rejects_contradictory_or_malformed_evidence(
    tmp_path: Path,
    updates: dict[str, object],
    message: str,
) -> None:
    artifact = tmp_path / "tasks.jsonl"
    artifact.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValidationError, match=message):
        _receipt(artifact, **updates)


def test_holdout_receipt_allows_repeated_family_fingerprints(tmp_path: Path) -> None:
    artifact = tmp_path / "tasks.jsonl"
    artifact.write_text("{}\n", encoding="utf-8")

    receipt = _receipt(
        artifact,
        task_count=2,
        category_counts={"lookup_status": 2},
        task_ids=["H1", "H2"],
        family_ids=["HF1", "HF1"],
        task_sha256={"H1": "d" * 64, "H2": "e" * 64},
    )

    assert receipt.family_ids == ["HF1", "HF1"]


@pytest.mark.parametrize(
    ("field", "second", "message"),
    [
        ("task_id", "T1", "task_id 交叉"),
        ("family_id", "F1", "family_id 交叉"),
        ("content_hash", "a" * 64, "内容 SHA-256 交叉"),
    ],
)
def test_split_isolation_rejects_cross_manifest_duplicates(
    field: str,
    second: str,
    message: str,
) -> None:
    train = _manifest("train", task_id="T1", family_id="F1", content_hash="a" * 64)
    holdout_values = {
        "task_id": "H1",
        "family_id": "HF1",
        "content_hash": "b" * 64,
    }
    holdout_values[field] = second
    holdout = _manifest("holdout", **holdout_values)

    with pytest.raises(ValueError, match=message):
        assert_split_isolation([train, holdout])


def test_split_isolation_allows_distinct_manifests() -> None:
    train = _manifest("train", task_id="T1", family_id="F1", content_hash="a" * 64)
    holdout = _manifest("holdout", task_id="H1", family_id="HF1", content_hash="b" * 64)

    assert_split_isolation([train, holdout])


def test_split_isolation_rejects_duplicate_task_ids_inside_manifest() -> None:
    manifest = _malformed_manifest(
        task_ids=["T1", "T1"],
        family_ids=["F1", "F2"],
        task_sha256={"T1": "a" * 64},
    )

    with pytest.raises(ValueError, match="manifest 内 task_id 重复"):
        assert_split_isolation([manifest])


def test_split_isolation_rejects_duplicate_content_hashes_inside_manifest() -> None:
    manifest = _malformed_manifest(
        task_ids=["T1", "T2"],
        family_ids=["F1", "F2"],
        task_sha256={"T1": "a" * 64, "T2": "a" * 64},
    )

    with pytest.raises(ValueError, match="manifest 内内容 SHA-256 重复"):
        assert_split_isolation([manifest])


def test_split_isolation_allows_repeated_family_ids_inside_manifest() -> None:
    manifest = _malformed_manifest(
        task_ids=["T1", "T2"],
        family_ids=["F1", "F1"],
        task_sha256={"T1": "a" * 64, "T2": "b" * 64},
    )

    assert_split_isolation([manifest])


@pytest.mark.parametrize("purpose", [EvidencePurpose.BUILD, EvidencePurpose.DEVELOP])
def test_non_release_purpose_cannot_open_holdout(
    tmp_path: Path,
    purpose: EvidencePurpose,
) -> None:
    artifact = tmp_path / "tasks.jsonl"

    with pytest.raises(PermissionError, match="只允许 release"):
        authorize_holdout(
            _receipt(artifact),
            artifact,
            PRIVATE_HOLDOUT_PATH,
            purpose,
        )


def test_raw_release_string_is_not_an_authorized_purpose(tmp_path: Path) -> None:
    artifact = tmp_path / "tasks.jsonl"

    with pytest.raises(PermissionError, match="只允许 release"):
        authorize_holdout(
            _receipt(artifact),
            artifact,
            PRIVATE_HOLDOUT_PATH,
            cast(EvidencePurpose, "release"),
        )


@pytest.mark.parametrize(
    "logical_path",
    [
        Path("reports/retail_ops/v1/holdout/tasks.jsonl"),
        Path("data/private/retail_ops/v10/holdout/tasks.jsonl"),
        Path("data/private/retail_ops/v1/../public/tasks.jsonl"),
        Path("/data/private/retail_ops/v1/holdout/tasks.jsonl"),
    ],
)
def test_release_rejects_logical_path_outside_private_root(
    tmp_path: Path,
    logical_path: Path,
) -> None:
    artifact = tmp_path / "tasks.jsonl"

    with pytest.raises(ValueError, match="sealed artifact 路径"):
        authorize_holdout(
            _receipt(artifact),
            artifact,
            logical_path,
            EvidencePurpose.RELEASE,
        )


def test_release_rejects_missing_artifact_with_stable_error(tmp_path: Path) -> None:
    artifact = tmp_path / "missing.jsonl"

    with pytest.raises(ValueError, match="holdout artifact 不存在"):
        authorize_holdout(
            _receipt(artifact),
            artifact,
            PRIVATE_HOLDOUT_PATH,
            EvidencePurpose.RELEASE,
        )


def test_release_rejects_non_regular_artifact_with_stable_error(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact-directory"
    artifact.mkdir()

    with pytest.raises(ValueError, match="holdout artifact 必须是普通文件"):
        authorize_holdout(
            _receipt(artifact),
            artifact,
            PRIVATE_HOLDOUT_PATH,
            EvidencePurpose.RELEASE,
        )


def test_release_translates_artifact_read_failure(tmp_path: Path) -> None:
    artifact = tmp_path / "unreadable.jsonl"
    artifact.write_text("{}\n", encoding="utf-8")
    receipt = _receipt(artifact)
    artifact.chmod(0)

    try:
        with pytest.raises(ValueError, match="holdout artifact 无法读取或计算 SHA-256"):
            authorize_holdout(
                receipt,
                artifact,
                PRIVATE_HOLDOUT_PATH,
                EvidencePurpose.RELEASE,
            )
    finally:
        artifact.chmod(0o600)


def test_release_rejects_tampered_holdout(tmp_path: Path) -> None:
    artifact = tmp_path / "tasks.jsonl"
    artifact.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ValueError, match="artifact SHA-256 不匹配"):
        authorize_holdout(
            _receipt(artifact, artifact_sha256="0" * 64),
            artifact,
            PRIVATE_HOLDOUT_PATH,
            EvidencePurpose.RELEASE,
        )


def test_release_authorizes_matching_private_holdout(tmp_path: Path) -> None:
    artifact = tmp_path / "tasks.jsonl"
    artifact.write_text("{}\n", encoding="utf-8")

    authorize_holdout(
        _receipt(artifact),
        artifact,
        PRIVATE_HOLDOUT_PATH,
        EvidencePurpose.RELEASE,
    )


@pytest.mark.parametrize("private_field", ["target_state", "prompt", "failure_ids"])
def test_public_receipt_rejects_private_evidence_fields(
    tmp_path: Path,
    private_field: str,
) -> None:
    artifact = tmp_path / "tasks.jsonl"
    artifact.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _receipt(artifact, **{private_field: []})
