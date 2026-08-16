"""RetailOps R2 formal manifest and private artifact contracts."""

from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

import veritool_rl.retail_ops.build.formal_manifests as formal_manifest_module
from veritool_rl.core.artifacts import canonical_json, sha256_file
from veritool_rl.retail_ops.build.formal_manifests import (
    FormalDatasetReceipt,
    FormalHoldoutReceipt,
    FormalTaskManifest,
    VerifiedFormalDataset,
    assert_formal_split_isolation,
    load_formal_dataset_receipt,
    load_formal_split,
    load_formal_task_manifest,
    load_verified_formal_dataset,
    write_formal_task_set,
)
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.formal_tasks import build_formal_task_set

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
    "bundle_id",
    "bundle_version",
    "bundle_sha256",
    "parser_id",
    "evaluator_id",
    "seed",
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


def _refresh_public_file_hash(public_dir: Path, filename: str) -> None:
    dataset_path = public_dir / "dataset.json"
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    payload["public_files_sha256"][filename] = sha256_file(public_dir / filename)
    dataset_path.write_text(canonical_json(payload) + "\n", encoding="utf-8")


def _assert_no_output_or_staging(*targets: Path) -> None:
    for target in targets:
        assert not target.exists()
        assert not list(target.parent.glob(f".{target.name}.staging-*"))


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
        assert rows[0]["generator_id"] == "family_sha256_v1"
        assert rows[0]["bundle_id"] == "retail_ops"
        assert rows[0]["bundle_version"] == "1.0.0"
        assert rows[0]["bundle_sha256"] == bundle.bundle_sha256
        assert rows[0]["parser_id"] == "hermes-single-call-v1"
        assert rows[0]["evaluator_id"] == "retail_ops_v1"
        assert rows[0]["seed"] == 0

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


def test_writer_cleans_first_staging_if_second_staging_creation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_dir = tmp_path / "private-parent" / "private"
    public_dir = tmp_path / "public-parent" / "public"
    external = tmp_path / "external"
    external.mkdir()
    (external / "sentinel").write_text("keep", encoding="utf-8")
    calls = 0

    def fail_second_staging(target: Path) -> Path:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected second staging failure")
        target.parent.mkdir(parents=True, exist_ok=True)
        return Path(
            tempfile.mkdtemp(
                prefix=f".{target.name}.staging-",
                dir=target.parent,
            )
        )

    monkeypatch.setattr(
        formal_manifest_module,
        "_make_staging_dir",
        fail_second_staging,
        raising=False,
    )
    with pytest.raises(OSError, match="second staging"):
        write_formal_task_set(
            build_formal_task_set(DATASET_VERSION, 0),
            load_bundle(BUNDLE_DIR),
            private_dir,
            public_dir,
        )

    _assert_no_output_or_staging(private_dir, public_dir)
    assert (external / "sentinel").read_text(encoding="utf-8") == "keep"


def test_writer_cleans_both_staging_roots_after_file_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_dir = tmp_path / "private"
    public_dir = tmp_path / "public"
    original_write_jsonl = formal_manifest_module.write_jsonl
    calls = 0

    def fail_second_write(path: Path, rows: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected write failure")
        original_write_jsonl(path, rows)  # type: ignore[arg-type]

    monkeypatch.setattr(formal_manifest_module, "write_jsonl", fail_second_write)
    with pytest.raises(OSError, match="write failure"):
        write_formal_task_set(
            build_formal_task_set(DATASET_VERSION, 0),
            load_bundle(BUNDLE_DIR),
            private_dir,
            public_dir,
        )

    _assert_no_output_or_staging(private_dir, public_dir)


def test_writer_removes_first_published_root_if_second_publish_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_dir = tmp_path / "private"
    public_dir = tmp_path / "public"
    calls = 0

    def fail_second_publish(staging: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected publish failure")
        staging.rename(target)

    monkeypatch.setattr(
        formal_manifest_module,
        "_publish_staging_dir",
        fail_second_publish,
        raising=False,
    )
    with pytest.raises(OSError, match="publish failure"):
        write_formal_task_set(
            build_formal_task_set(DATASET_VERSION, 0),
            load_bundle(BUNDLE_DIR),
            private_dir,
            public_dir,
        )

    _assert_no_output_or_staging(private_dir, public_dir)


def test_writer_removes_root_when_publish_raises_after_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_dir = tmp_path / "private"
    public_dir = tmp_path / "public"

    def publish_then_fail(staging: Path, target: Path) -> None:
        staging.rename(target)
        raise OSError("injected post-rename publish failure")

    monkeypatch.setattr(
        formal_manifest_module,
        "_publish_staging_dir",
        publish_then_fail,
    )
    with pytest.raises(OSError, match="post-rename"):
        write_formal_task_set(
            build_formal_task_set(DATASET_VERSION, 0),
            load_bundle(BUNDLE_DIR),
            private_dir,
            public_dir,
        )

    _assert_no_output_or_staging(private_dir, public_dir)


def test_public_models_enforce_exact_keys_counts_order_and_file_hashes(
    tmp_path: Path,
) -> None:
    private_dir, public_dir = _write_dataset(tmp_path)
    train_path = public_dir / "train.json"
    train_payload = json.loads(train_path.read_text(encoding="utf-8"))

    manifest = load_formal_task_manifest(train_path)
    assert set(manifest.model_dump(mode="json")) == SPLIT_MANIFEST_KEYS
    assert manifest.task_count == 240
    assert manifest.category_counts == dict.fromkeys(SCENARIOS, 40)
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


@pytest.mark.parametrize(
    ("field", "value_source"),
    [
        ("dataset_version", "request"),
        ("generator_id", "order"),
        ("bundle_id", "request"),
        ("bundle_version", "order"),
        ("parser_id", "private_path"),
        ("evaluator_id", "request"),
        ("seed", "seed"),
    ],
)
def test_all_public_models_reject_identifier_value_injection(
    tmp_path: Path,
    field: str,
    value_source: str,
) -> None:
    private_dir, public_dir = _write_dataset(tmp_path)
    first_row = json.loads(
        (private_dir / "train.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    injected_values: dict[str, object] = {
        "request": first_row["task"]["user_request"],
        "order": first_row["task"]["metadata"]["order_id"],
        "private_path": str(private_dir / "holdout.jsonl"),
        "seed": 1,
    }
    model_files = (
        (FormalTaskManifest, "train.json"),
        (FormalTaskManifest, "dev.json"),
        (FormalHoldoutReceipt, "holdout-receipt.json"),
        (FormalDatasetReceipt, "dataset.json"),
    )

    for model, filename in model_files:
        payload = json.loads((public_dir / filename).read_text(encoding="utf-8"))
        payload[field] = injected_values[value_source]
        with pytest.raises(ValidationError):
            model.model_validate(payload)


@pytest.mark.parametrize(
    "provenance",
    ["dataset_version", "generator_id", "parser_id", "evaluator_id", "seed"],
)
def test_writer_rejects_non_frozen_provenance_before_creating_outputs(
    tmp_path: Path,
    provenance: str,
) -> None:
    task_set = build_formal_task_set(DATASET_VERSION, 0)
    bundle = load_bundle(BUNDLE_DIR)
    parser_id = "hermes-single-call-v1"
    if provenance == "dataset_version":
        task_set = task_set.model_copy(update={"dataset_version": "data/private/leak"})
    elif provenance == "generator_id":
        task_set = task_set.model_copy(update={"generator_id": "O-LEAKED"})
    elif provenance == "seed":
        task_set = task_set.model_copy(update={"seed": 1})
    elif provenance == "parser_id":
        parser_id = "真实用户请求"
    else:
        bundle = replace(
            bundle,
            bundle=bundle.bundle.model_copy(update={"evaluator_id": "真实用户请求"}),
        )
    private_dir = tmp_path / "private"
    public_dir = tmp_path / "public"

    with pytest.raises(ValueError, match="冻结"):
        write_formal_task_set(
            task_set,
            bundle,
            private_dir,
            public_dir,
            parser_id=parser_id,
        )
    assert not private_dir.exists()
    assert not public_dir.exists()


def test_load_formal_split_rejects_file_and_row_tampering(tmp_path: Path) -> None:
    private_dir, public_dir = _write_dataset(tmp_path)
    artifact_path = private_dir / "dev.jsonl"
    dataset = load_verified_formal_dataset(public_dir)

    records = load_formal_split(dataset, "dev", artifact_path)
    assert len(records) == 60
    assert all(record.task.split == "dev" for record in records)

    rows = artifact_path.read_text(encoding="utf-8").splitlines()
    changed = json.loads(rows[0])
    changed["task"]["user_request"] = "篡改后的请求"
    rows[0] = canonical_json(changed)
    artifact_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact SHA-256 不匹配"):
        load_formal_split(dataset, "dev", artifact_path)

    dev_path = public_dir / "dev.json"
    dev_payload = json.loads(dev_path.read_text(encoding="utf-8"))
    dev_payload["artifact_sha256"] = sha256_file(artifact_path)
    dev_path.write_text(canonical_json(dev_payload) + "\n", encoding="utf-8")
    _refresh_public_file_hash(public_dir, "dev.json")
    refreshed = load_verified_formal_dataset(public_dir)
    with pytest.raises(ValueError, match="记录指纹"):
        load_formal_split(refreshed, "dev", artifact_path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("variant_index", 1, "variant_index"),
        ("parser_id", "真实用户请求", "parser_id"),
        ("seed", 1, "seed"),
    ],
)
def test_private_loader_rejects_variant_or_provenance_tampering(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    private_dir, public_dir = _write_dataset(tmp_path)
    artifact_path = private_dir / "dev.jsonl"
    rows = artifact_path.read_text(encoding="utf-8").splitlines()
    row = json.loads(rows[0])
    if field == "variant_index":
        assert row["variant_index"] == 0
    row[field] = value
    rows[0] = canonical_json(row)
    artifact_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    dev_path = public_dir / "dev.json"
    dev_payload = json.loads(dev_path.read_text(encoding="utf-8"))
    dev_payload["artifact_sha256"] = sha256_file(artifact_path)
    dev_path.write_text(canonical_json(dev_payload) + "\n", encoding="utf-8")
    _refresh_public_file_hash(public_dir, "dev.json")
    dataset = load_verified_formal_dataset(public_dir)

    with pytest.raises((ValueError, ValidationError), match=message):
        load_formal_split(dataset, "dev", artifact_path)


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
        "train": dict.fromkeys(SCENARIOS, 40),
        "dev": dict.fromkeys(SCENARIOS, 10),
        "holdout": dict.fromkeys(SCENARIOS, 20),
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

    with pytest.raises(ValueError, match=r"train\.json SHA-256 不匹配"):
        load_formal_dataset_receipt(dataset_path)


def test_verified_dataset_reads_each_public_file_once_and_cross_checks_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, public_dir = _write_dataset(tmp_path)
    original_read_bytes = Path.read_bytes
    reads: dict[Path, int] = {}

    def counted_read_bytes(path: Path) -> bytes:
        reads[path] = reads.get(path, 0) + 1
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", counted_read_bytes)
    verified = load_verified_formal_dataset(public_dir)

    assert isinstance(verified, VerifiedFormalDataset)
    assert verified.receipt.parser_id == "hermes-single-call-v1"
    assert verified.train_manifest.split == "train"
    assert verified.dev_manifest.split == "dev"
    assert verified.holdout_receipt.split == "holdout"
    assert reads == {
        public_dir / filename: 1
        for filename in (
            "dataset.json",
            "train.json",
            "dev.json",
            "holdout-receipt.json",
        )
    }

    monkeypatch.undo()
    train_path = public_dir / "train.json"
    train_payload = json.loads(train_path.read_text(encoding="utf-8"))
    train_payload["bundle_sha256"] = "0" * 64
    train_path.write_text(canonical_json(train_payload) + "\n", encoding="utf-8")
    _refresh_public_file_hash(public_dir, "train.json")
    with pytest.raises(ValueError, match="provenance"):
        load_verified_formal_dataset(public_dir)


def test_verified_dataset_and_nested_public_models_are_not_mutable(tmp_path: Path) -> None:
    _, public_dir = _write_dataset(tmp_path)
    verified = load_verified_formal_dataset(public_dir)

    with pytest.raises(TypeError, match="只能由 load_verified_formal_dataset 创建"):
        VerifiedFormalDataset()
    with pytest.raises(ValidationError, match="frozen"):
        verified.holdout_receipt.artifact_sha256 = "0" * 64


def test_verified_dataset_detects_nested_public_model_mutation_before_private_read(
    tmp_path: Path,
) -> None:
    private_dir, public_dir = _write_dataset(tmp_path)
    verified = load_verified_formal_dataset(public_dir)
    verified.dev_manifest.task_fingerprints[0] = "0" * 64

    with pytest.raises(PermissionError, match="capability 内容已改变"):
        load_formal_split(verified, "dev", private_dir / "dev.jsonl")


def test_verified_dataset_translates_public_file_os_errors(tmp_path: Path) -> None:
    _, public_dir = _write_dataset(tmp_path)
    (public_dir / "dev.json").unlink()

    with pytest.raises(ValueError, match=r"公开 formal 文件无法读取: dev\.json"):
        load_verified_formal_dataset(public_dir)
