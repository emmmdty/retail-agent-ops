"""RetailOps holdout receipt、split 隔离与 sealed 访问契约。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from veritool_rl.artifacts import sha256_file
from veritool_rl.retail_ops.governance import (
    EvidencePurpose,
    HoldoutReceipt,
    assert_split_isolation,
    authorize_holdout,
)
from veritool_rl.retail_ops.manifests import TaskManifest

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
        "artifact_sha256": sha256_file(artifact),
    }
    values.update(updates)
    return HoldoutReceipt.model_validate(values)


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


@pytest.mark.parametrize("purpose", [EvidencePurpose.BUILD, EvidencePurpose.DEVELOP])
def test_non_release_purpose_cannot_open_holdout(
    tmp_path: Path,
    purpose: EvidencePurpose,
) -> None:
    artifact = tmp_path / "tasks.jsonl"
    artifact.write_text("{}\n", encoding="utf-8")

    with pytest.raises(PermissionError, match="只允许 release"):
        authorize_holdout(
            _receipt(artifact),
            artifact,
            PRIVATE_HOLDOUT_PATH,
            purpose,
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
    artifact.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="sealed artifact 路径"):
        authorize_holdout(
            _receipt(artifact),
            artifact,
            logical_path,
            EvidencePurpose.RELEASE,
        )


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
