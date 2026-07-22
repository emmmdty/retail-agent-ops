"""RetailOps R2 sealed formal holdout authorization and loading tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from veritool_rl.artifacts import canonical_json, sha256_file
from veritool_rl.retail_ops.bundle import load_bundle
from veritool_rl.retail_ops.formal_governance import (
    authorize_formal_holdout,
    load_authorized_formal_holdout,
)
from veritool_rl.retail_ops.formal_manifests import (
    FormalHoldoutReceipt,
    load_formal_holdout_receipt,
    write_formal_task_set,
)
from veritool_rl.retail_ops.formal_tasks import build_formal_task_set
from veritool_rl.retail_ops.governance import EvidencePurpose

DATASET_VERSION = "retail_ops_v1_r2_20260722"
LOGICAL_HOLDOUT = Path("data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722/holdout.jsonl")


class ExplodingArtifactPath:
    """Fail if governance touches the artifact before purpose/path gates."""

    def exists(self) -> bool:
        raise AssertionError("artifact existence was checked too early")

    def is_file(self) -> bool:
        raise AssertionError("artifact type was checked too early")

    def read_bytes(self) -> bytes:
        raise AssertionError("artifact content was read too early")


def _write_dataset(tmp_path: Path) -> tuple[Path, Path, FormalHoldoutReceipt]:
    private_dir = tmp_path / "private"
    public_dir = tmp_path / "public"
    write_formal_task_set(
        build_formal_task_set(DATASET_VERSION, seed=0),
        load_bundle(Path("domains/retail_ops/v1")),
        private_dir,
        public_dir,
    )
    return (
        private_dir,
        public_dir,
        load_formal_holdout_receipt(public_dir / "holdout-receipt.json"),
    )


def _rewrite_rows(
    artifact: Path,
    receipt: FormalHoldoutReceipt,
    mutate: object,
) -> FormalHoldoutReceipt:
    rows = [json.loads(line) for line in artifact.read_text(encoding="utf-8").splitlines()]
    cast_mutate = cast("object", mutate)
    assert callable(cast_mutate)
    cast_mutate(rows)
    artifact.write_text(
        "\n".join(canonical_json(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    return receipt.model_copy(update={"artifact_sha256": sha256_file(artifact)})


@pytest.mark.parametrize(
    "purpose",
    [EvidencePurpose.BUILD, EvidencePurpose.DEVELOP, cast(EvidencePurpose, "release")],
)
def test_non_release_purpose_fails_before_any_artifact_access(
    tmp_path: Path,
    purpose: EvidencePurpose,
) -> None:
    _, _, receipt = _write_dataset(tmp_path)

    with pytest.raises(PermissionError, match="只允许 release"):
        authorize_formal_holdout(
            receipt,
            cast(Path, ExplodingArtifactPath()),
            LOGICAL_HOLDOUT,
            purpose,
        )


def test_malformed_receipt_fails_before_private_artifact_access(tmp_path: Path) -> None:
    _, _, receipt = _write_dataset(tmp_path)
    malformed = receipt.model_copy(update={"task_count": 119})

    with pytest.raises(ValidationError, match="task_count"):
        authorize_formal_holdout(
            malformed,
            cast(Path, ExplodingArtifactPath()),
            LOGICAL_HOLDOUT,
            EvidencePurpose.RELEASE,
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
def test_invalid_logical_path_fails_before_artifact_access(
    tmp_path: Path,
    logical_path: Path,
) -> None:
    _, _, receipt = _write_dataset(tmp_path)

    with pytest.raises(ValueError, match="sealed formal holdout 路径"):
        authorize_formal_holdout(
            receipt,
            cast(Path, ExplodingArtifactPath()),
            logical_path,
            EvidencePurpose.RELEASE,
        )


def test_authorized_holdout_loads_complete_verified_records(tmp_path: Path) -> None:
    private_dir, _, receipt = _write_dataset(tmp_path)
    artifact = private_dir / "holdout.jsonl"

    authorization = authorize_formal_holdout(
        receipt,
        artifact,
        LOGICAL_HOLDOUT,
        EvidencePurpose.RELEASE,
    )
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
    private_dir, _, receipt = _write_dataset(tmp_path)
    missing = tmp_path / "missing.jsonl"
    directory = tmp_path / "directory"
    directory.mkdir()

    with pytest.raises(ValueError, match="artifact 不存在"):
        authorize_formal_holdout(receipt, missing, LOGICAL_HOLDOUT, EvidencePurpose.RELEASE)
    with pytest.raises(ValueError, match="artifact 必须是普通文件"):
        authorize_formal_holdout(receipt, directory, LOGICAL_HOLDOUT, EvidencePurpose.RELEASE)
    with pytest.raises(ValueError, match="artifact SHA-256 不匹配"):
        authorize_formal_holdout(
            receipt.model_copy(update={"artifact_sha256": "0" * 64}),
            private_dir / "holdout.jsonl",
            LOGICAL_HOLDOUT,
            EvidencePurpose.RELEASE,
        )


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
    private_dir, _, receipt = _write_dataset(tmp_path)
    artifact = private_dir / "holdout.jsonl"
    changed_receipt = _rewrite_rows(artifact, receipt, mutator)
    authorization = authorize_formal_holdout(
        changed_receipt,
        artifact,
        LOGICAL_HOLDOUT,
        EvidencePurpose.RELEASE,
    )

    with pytest.raises(ValueError, match=message):
        load_authorized_formal_holdout(authorization)


def test_authorized_loader_rechecks_hash_before_parsing(tmp_path: Path) -> None:
    private_dir, _, receipt = _write_dataset(tmp_path)
    artifact = private_dir / "holdout.jsonl"
    authorization = authorize_formal_holdout(
        receipt,
        artifact,
        LOGICAL_HOLDOUT,
        EvidencePurpose.RELEASE,
    )
    artifact.write_text("not-json\n", encoding="utf-8")

    with pytest.raises(ValueError, match="授权后 artifact SHA-256 已改变"):
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
    with pytest.raises(ValidationError, match="task_fingerprints.*唯一"):
        FormalHoldoutReceipt.model_validate(payload)


def test_holdout_loader_rejects_extra_private_row_key_before_task_use(
    tmp_path: Path,
) -> None:
    private_dir, _, receipt = _write_dataset(tmp_path)
    artifact = private_dir / "holdout.jsonl"

    def add_secret(rows: list[dict[str, object]]) -> None:
        rows[0]["secret"] = "not-allowed"

    changed_receipt = _rewrite_rows(artifact, receipt, add_secret)
    authorization = authorize_formal_holdout(
        changed_receipt,
        artifact,
        LOGICAL_HOLDOUT,
        EvidencePurpose.RELEASE,
    )

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_authorized_formal_holdout(authorization)
