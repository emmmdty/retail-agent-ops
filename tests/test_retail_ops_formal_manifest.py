"""RetailOps R2 formal manifest and private artifact contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from veritool_rl.artifacts import canonical_json, sha256_file
from veritool_rl.retail_ops.bundle import load_bundle
from veritool_rl.retail_ops.formal_manifests import (
    FormalDatasetReceipt,
    FormalTaskManifest,
    assert_formal_split_isolation,
    load_formal_dataset_receipt,
    load_formal_split,
    load_formal_task_manifest,
    write_formal_task_set,
)
from veritool_rl.retail_ops.formal_tasks import build_formal_task_set

DATASET_VERSION = "retail_ops_v1_r2_20260722"
BUNDLE_DIR = Path("domains/retail_ops/v1")
SCENARIOS = (
    "lookup_status",
    "refund_eligible",
    "refund_denied_window",
    "refund_denied_ownership",
    "refund_denied_duplicate",
    "refund_recovery",
)
FINGERPRINT_FIELDS = (
    "task_fingerprints",
    "family_fingerprints",
    "content_fingerprints",
    "source_fingerprints",
    "derivation_fingerprints",
)
SPLIT_MANIFEST_KEYS = {
    "schema_version",
    "dataset_version",
    "generator_id",
    "bundle_id",
    "bundle_version",
    "bundle_sha256",
    "parser_id",
    "evaluator_id",
    "seed",
    "split",
    "task_count",
    "category_counts",
    *FINGERPRINT_FIELDS,
    "artifact_sha256",
}
DATASET_RECEIPT_KEYS = {
    "schema_version",
    "dataset_version",
    "generator_id",
    "bundle_id",
    "bundle_version",
    "bundle_sha256",
    "parser_id",
    "evaluator_id",
    "seed",
    "split_task_counts",
    "split_category_counts",
    "public_files_sha256",
}
PRIVATE_ROW_KEYS = {
    "schema_version",
    "dataset_version",
    "generator_id",
    "bundle_sha256",
    "task",
    "task_fingerprint",
    "family_fingerprint",
    "content_fingerprint",
    "source_fingerprint",
    "derivation_fingerprint",
    "variant_index",
}


def _write_dataset(tmp_path: Path, name: str = "dataset") -> tuple[Path, Path]:
    private_dir = tmp_path / f"{name}-private"
    public_dir = tmp_path / f"{name}-public"
    write_formal_task_set(
        build_formal_task_set(DATASET_VERSION, seed=0),
        load_bundle(BUNDLE_DIR),
        private_dir,
        public_dir,
        parser_id="hermes-single-call-v1",
    )
    return private_dir, public_dir


def _json_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(key)
            keys.update(_json_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.update(_json_keys(item))
    return keys


def test_writer_separates_complete_private_tasks_from_answer_free_public_files(
    tmp_path: Path,
) -> None:
    task_set = build_formal_task_set(DATASET_VERSION, seed=0)
    bundle = load_bundle(BUNDLE_DIR)
    private_dir = tmp_path / "private"
    public_dir = tmp_path / "public"

    receipt = write_formal_task_set(
        task_set,
        bundle,
        private_dir,
        public_dir,
        parser_id="hermes-single-call-v1",
    )

    assert receipt.schema_version == "2.0"
    assert {path.name for path in private_dir.iterdir()} == {
        "train.jsonl",
        "dev.jsonl",
        "holdout.jsonl",
    }
    assert {path.name for path in public_dir.iterdir()} == {
        "train.json",
        "dev.json",
        "holdout-receipt.json",
        "dataset.json",
    }
    assert set(receipt.model_dump(mode="json")) == DATASET_RECEIPT_KEYS

    for split, expected_count in (("train", 240), ("dev", 60), ("holdout", 120)):
        rows = [
            json.loads(line)
            for line in (private_dir / f"{split}.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        assert len(rows) == expected_count
        assert set(rows[0]) == PRIVATE_ROW_KEYS
        assert rows[0]["task"]["initial_state"]
        assert rows[0]["task"]["target_state"]
        assert rows[0]["task"]["expected_calls"]
        assert rows[0]["dataset_version"] == DATASET_VERSION
        assert rows[0]["bundle_sha256"] == bundle.bundle_sha256

    public_values = [
        json.loads(path.read_text(encoding="utf-8")) for path in sorted(public_dir.iterdir())
    ]
    assert set(public_values[0]) in (SPLIT_MANIFEST_KEYS, DATASET_RECEIPT_KEYS)
    serialized_public = canonical_json(public_values)
    forbidden_keys = {
        "task_id",
        "family_id",
        "user_request",
        "initial_state",
        "target_state",
        "expected_calls",
        "expected_decision",
        "required_reads",
        "metadata",
        "private_path",
        "artifact_path",
    }
    assert _json_keys(public_values).isdisjoint(forbidden_keys)
    assert "data/private/" not in serialized_public
    for split in ("train", "dev", "holdout"):
        for record in task_set.records(split):
            assert record.task.task_id not in serialized_public
            assert record.task.metadata["family_id"] not in serialized_public
            assert record.task.user_request not in serialized_public
            assert record.task.metadata["order_id"] not in serialized_public
            assert record.task.metadata["customer_id"] not in serialized_public


def test_writer_is_byte_deterministic_and_refuses_either_existing_output(
    tmp_path: Path,
) -> None:
    first_private, first_public = _write_dataset(tmp_path, "first")
    second_private, second_public = _write_dataset(tmp_path, "second")

    for filename in ("train.jsonl", "dev.jsonl", "holdout.jsonl"):
        assert (first_private / filename).read_bytes() == (second_private / filename).read_bytes()
    for filename in ("train.json", "dev.json", "holdout-receipt.json", "dataset.json"):
        assert (first_public / filename).read_bytes() == (second_public / filename).read_bytes()

    untouched_public = tmp_path / "untouched-public"
    with pytest.raises(FileExistsError, match="拒绝覆盖"):
        write_formal_task_set(
            build_formal_task_set(DATASET_VERSION, 0),
            load_bundle(BUNDLE_DIR),
            first_private,
            untouched_public,
        )
    assert not untouched_public.exists()

    untouched_private = tmp_path / "untouched-private"
    with pytest.raises(FileExistsError, match="拒绝覆盖"):
        write_formal_task_set(
            build_formal_task_set(DATASET_VERSION, 0),
            load_bundle(BUNDLE_DIR),
            untouched_private,
            first_public,
        )
    assert not untouched_private.exists()


@pytest.mark.parametrize("public_suffix", [Path("."), Path("public")])
def test_writer_rejects_same_or_nested_private_and_public_roots(
    tmp_path: Path,
    public_suffix: Path,
) -> None:
    private_dir = tmp_path / "private"
    public_dir = private_dir / public_suffix

    with pytest.raises(ValueError, match="private/public 输出目录必须分离"):
        write_formal_task_set(
            build_formal_task_set(DATASET_VERSION, 0),
            load_bundle(BUNDLE_DIR),
            private_dir,
            public_dir,
        )
    assert not private_dir.exists()


def test_public_models_enforce_exact_keys_counts_order_and_file_hashes(
    tmp_path: Path,
) -> None:
    private_dir, public_dir = _write_dataset(tmp_path)
    train_path = public_dir / "train.json"
    train_payload = json.loads(train_path.read_text(encoding="utf-8"))

    manifest = load_formal_task_manifest(train_path)
    assert set(manifest.model_dump(mode="json")) == SPLIT_MANIFEST_KEYS
    assert manifest.task_count == 240
    assert manifest.category_counts == {scenario: 40 for scenario in SCENARIOS}
    assert manifest.artifact_sha256 == sha256_file(private_dir / "train.jsonl")
    assert len(manifest.task_fingerprints) == 240
    assert len(set(manifest.task_fingerprints)) == 240
    assert all(
        len(values) == 240 for field in FINGERPRINT_FIELDS for values in [getattr(manifest, field)]
    )

    train_payload["unexpected"] = True
    train_path.write_text(canonical_json(train_payload) + "\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        load_formal_task_manifest(train_path)


def test_load_formal_split_rejects_file_and_row_tampering(tmp_path: Path) -> None:
    private_dir, public_dir = _write_dataset(tmp_path)
    manifest_path = public_dir / "dev.json"
    artifact_path = private_dir / "dev.jsonl"
    manifest = load_formal_task_manifest(manifest_path)

    records = load_formal_split(manifest, artifact_path)
    assert len(records) == 60
    assert all(record.task.split == "dev" for record in records)

    rows = artifact_path.read_text(encoding="utf-8").splitlines()
    changed = json.loads(rows[0])
    changed["task"]["user_request"] = "篡改后的请求"
    rows[0] = canonical_json(changed)
    artifact_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact SHA-256 不匹配"):
        load_formal_split(manifest, artifact_path)

    refreshed = manifest.model_copy(update={"artifact_sha256": sha256_file(artifact_path)})
    with pytest.raises(ValueError, match="记录指纹"):
        load_formal_split(refreshed, artifact_path)


def test_formal_split_isolation_rejects_overlap_in_every_dimension(
    tmp_path: Path,
) -> None:
    _, public_dir = _write_dataset(tmp_path)
    train = load_formal_task_manifest(public_dir / "train.json")
    dev = load_formal_task_manifest(public_dir / "dev.json")
    assert_formal_split_isolation([train, dev])

    for field in FINGERPRINT_FIELDS:
        dev_values = list(getattr(dev, field))
        if field in {"family_fingerprints", "source_fingerprints", "derivation_fingerprints"}:
            dev_values[:2] = [getattr(train, field)[0]] * 2
        else:
            dev_values[0] = getattr(train, field)[0]
        changed = dev.model_copy(update={field: dev_values})
        with pytest.raises(ValueError, match=field.removesuffix("s")):
            assert_formal_split_isolation([train, changed])


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("task_fingerprints", "task_fingerprints.*唯一"),
        ("content_fingerprints", "content_fingerprints.*唯一"),
        ("family_fingerprints", "family_fingerprints.*恰好出现两次"),
        ("source_fingerprints", "source_fingerprints.*恰好出现两次"),
        ("derivation_fingerprints", "derivation_fingerprints.*恰好出现两次"),
    ],
)
def test_formal_manifest_rejects_internal_fingerprint_duplicates(
    tmp_path: Path,
    field: str,
    message: str,
) -> None:
    _, public_dir = _write_dataset(tmp_path)
    payload = json.loads((public_dir / "train.json").read_text(encoding="utf-8"))

    if field in {"task_fingerprints", "content_fingerprints"}:
        payload[field][1] = payload[field][0]
    else:
        payload[field][2] = payload[field][0]
        payload[field][3] = payload[field][0]
    with pytest.raises(ValidationError, match=message):
        FormalTaskManifest.model_validate(payload)


def test_dataset_receipt_binds_exact_public_files_and_rejects_unknown_keys(
    tmp_path: Path,
) -> None:
    _, public_dir = _write_dataset(tmp_path)
    dataset_path = public_dir / "dataset.json"
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))

    receipt = FormalDatasetReceipt.model_validate(payload)
    assert set(payload) == DATASET_RECEIPT_KEYS
    assert receipt.split_task_counts == {"train": 240, "dev": 60, "holdout": 120}
    assert receipt.split_category_counts == {
        "train": {scenario: 40 for scenario in SCENARIOS},
        "dev": {scenario: 10 for scenario in SCENARIOS},
        "holdout": {scenario: 20 for scenario in SCENARIOS},
    }
    assert receipt.public_files_sha256 == {
        filename: sha256_file(public_dir / filename)
        for filename in ("train.json", "dev.json", "holdout-receipt.json")
    }

    payload["private_root"] = "/tmp/private"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        FormalDatasetReceipt.model_validate(payload)


def test_dataset_receipt_loader_rejects_changed_public_split_file(tmp_path: Path) -> None:
    _, public_dir = _write_dataset(tmp_path)
    dataset_path = public_dir / "dataset.json"
    train_path = public_dir / "train.json"

    assert load_formal_dataset_receipt(dataset_path).dataset_version == DATASET_VERSION
    train_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="train.json SHA-256 不匹配"):
        load_formal_dataset_receipt(dataset_path)
