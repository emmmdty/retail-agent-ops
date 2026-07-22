"""RetailOps R2 formal private artifacts and answer-free public manifests."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from veritool_rl.artifacts import sha256_file, write_json, write_jsonl
from veritool_rl.retail_ops.bundle import LoadedRetailOpsBundle
from veritool_rl.retail_ops.formal_tasks import (
    FormalSplit,
    FormalTaskRecord,
    FormalTaskSet,
)
from veritool_rl.trajectory import TaskScenario, TaskSpec
from veritool_rl.trajectory.schema import StrictModel

_DEFAULT_PARSER_ID = "hermes-single-call-v1"
_SCENARIO_ORDER = (
    TaskScenario.LOOKUP_STATUS,
    TaskScenario.REFUND_ELIGIBLE,
    TaskScenario.REFUND_DENIED_WINDOW,
    TaskScenario.REFUND_DENIED_OWNERSHIP,
    TaskScenario.REFUND_DENIED_DUPLICATE,
    TaskScenario.REFUND_RECOVERY,
)
_EXPECTED_PER_CATEGORY = {
    FormalSplit.TRAIN: 40,
    FormalSplit.DEV: 10,
    FormalSplit.HOLDOUT: 20,
}
_FINGERPRINT_FIELDS = (
    "task_fingerprints",
    "family_fingerprints",
    "content_fingerprints",
    "source_fingerprints",
    "derivation_fingerprints",
)
_ROW_FINGERPRINT_FIELDS = (
    "task_fingerprint",
    "family_fingerprint",
    "content_fingerprint",
    "source_fingerprint",
    "derivation_fingerprint",
)
_PUBLIC_FILENAMES = ("train.json", "dev.json", "holdout-receipt.json")

Fingerprint = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class _FormalSplitEvidence(StrictModel):
    """Fields shared by answer-free split manifests and receipts."""

    schema_version: Literal["2.0"] = "2.0"
    dataset_version: str = Field(min_length=1)
    generator_id: str = Field(min_length=1)
    bundle_id: Literal["retail_ops"] = "retail_ops"
    bundle_version: Literal["1.0.0"] = "1.0.0"
    bundle_sha256: Fingerprint
    parser_id: str = Field(min_length=1)
    evaluator_id: Literal["retail_ops_v1"] = "retail_ops_v1"
    seed: int
    split: Literal["train", "dev", "holdout"]
    task_count: int = Field(ge=1)
    category_counts: dict[str, int]
    task_fingerprints: list[Fingerprint]
    family_fingerprints: list[Fingerprint]
    content_fingerprints: list[Fingerprint]
    source_fingerprints: list[Fingerprint]
    derivation_fingerprints: list[Fingerprint]
    artifact_sha256: Fingerprint

    @model_validator(mode="after")
    def validate_public_evidence(self) -> Self:
        """Enforce frozen quotas and ordered fingerprint cardinalities."""
        split = FormalSplit(self.split)
        expected_per_category = _EXPECTED_PER_CATEGORY[split]
        expected_counts = {scenario.value: expected_per_category for scenario in _SCENARIO_ORDER}
        if self.category_counts != expected_counts:
            raise ValueError(f"{split.value} category_counts 不符合冻结配额")
        expected_total = expected_per_category * len(_SCENARIO_ORDER)
        if self.task_count != expected_total:
            raise ValueError(f"{split.value} task_count 不符合冻结配额")
        for field in _FINGERPRINT_FIELDS:
            values = getattr(self, field)
            if len(values) != self.task_count:
                raise ValueError(f"{field} 数量必须等于 task_count")

        for field in ("task_fingerprints", "content_fingerprints"):
            values = getattr(self, field)
            if len(values) != len(set(values)):
                raise ValueError(f"{field} 必须全部唯一")
        for field in (
            "family_fingerprints",
            "source_fingerprints",
            "derivation_fingerprints",
        ):
            values = getattr(self, field)
            if set(Counter(values).values()) != {2}:
                raise ValueError(f"{field} 中每个指纹必须恰好出现两次")
            if any(values[index] != values[index + 1] for index in range(0, len(values), 2)):
                raise ValueError(f"{field} 必须按相邻双变体顺序排列")
        return self


class FormalTaskManifest(_FormalSplitEvidence):
    """Answer-free ordered manifest for a formal train or dev split."""

    split: Literal["train", "dev"]


class FormalHoldoutReceipt(_FormalSplitEvidence):
    """Answer-free receipt for the sealed formal holdout split."""

    split: Literal["holdout"] = "holdout"


class FormalDatasetReceipt(StrictModel):
    """Public binding across all formal split metadata files."""

    schema_version: Literal["2.0"] = "2.0"
    dataset_version: str = Field(min_length=1)
    generator_id: str = Field(min_length=1)
    bundle_id: Literal["retail_ops"] = "retail_ops"
    bundle_version: Literal["1.0.0"] = "1.0.0"
    bundle_sha256: Fingerprint
    parser_id: str = Field(min_length=1)
    evaluator_id: Literal["retail_ops_v1"] = "retail_ops_v1"
    seed: int
    split_task_counts: dict[str, int]
    split_category_counts: dict[str, dict[str, int]]
    public_files_sha256: dict[str, Fingerprint]

    @model_validator(mode="after")
    def validate_dataset_evidence(self) -> Self:
        """Require the exact three split quotas and public file bindings."""
        expected_task_counts = {
            split.value: count * len(_SCENARIO_ORDER)
            for split, count in _EXPECTED_PER_CATEGORY.items()
        }
        expected_category_counts = {
            split.value: {scenario.value: count for scenario in _SCENARIO_ORDER}
            for split, count in _EXPECTED_PER_CATEGORY.items()
        }
        if self.split_task_counts != expected_task_counts:
            raise ValueError("split_task_counts 不符合冻结配额")
        if self.split_category_counts != expected_category_counts:
            raise ValueError("split_category_counts 不符合冻结配额")
        if set(self.public_files_sha256) != set(_PUBLIC_FILENAMES):
            raise ValueError("public_files_sha256 必须精确绑定三份 split 文件")
        return self


class _FormalPrivateTaskRow(StrictModel):
    """Private line binding complete task truth to formal provenance."""

    schema_version: Literal["2.0"] = "2.0"
    dataset_version: str = Field(min_length=1)
    generator_id: str = Field(min_length=1)
    bundle_sha256: Fingerprint
    task: TaskSpec
    task_fingerprint: Fingerprint
    family_fingerprint: Fingerprint
    content_fingerprint: Fingerprint
    source_fingerprint: Fingerprint
    derivation_fingerprint: Fingerprint
    variant_index: int = Field(ge=0, le=1)

    @classmethod
    def from_record(
        cls,
        record: FormalTaskRecord,
        *,
        dataset_version: str,
        generator_id: str,
        bundle_sha256: str,
    ) -> _FormalPrivateTaskRow:
        return cls(
            dataset_version=dataset_version,
            generator_id=generator_id,
            bundle_sha256=bundle_sha256,
            task=record.task.model_copy(deep=True),
            task_fingerprint=record.task_fingerprint,
            family_fingerprint=record.family_fingerprint,
            content_fingerprint=record.content_fingerprint,
            source_fingerprint=record.source_fingerprint,
            derivation_fingerprint=record.derivation_fingerprint,
            variant_index=record.variant_index,
        )

    def to_record(self) -> FormalTaskRecord:
        return FormalTaskRecord(
            task=self.task.model_copy(deep=True),
            task_fingerprint=self.task_fingerprint,
            family_fingerprint=self.family_fingerprint,
            content_fingerprint=self.content_fingerprint,
            source_fingerprint=self.source_fingerprint,
            derivation_fingerprint=self.derivation_fingerprint,
            variant_index=self.variant_index,
        )


def write_formal_task_set(
    task_set: FormalTaskSet,
    bundle: LoadedRetailOpsBundle,
    private_output_dir: Path,
    public_output_dir: Path,
    *,
    parser_id: str = _DEFAULT_PARSER_ID,
) -> FormalDatasetReceipt:
    """Write immutable private truth and answer-free public R2 metadata."""
    task_set.assert_exact_quotas()
    if not parser_id:
        raise ValueError("parser_id 不能为空")
    if task_set.generator_id != "family_sha256_v1":
        raise ValueError("正式数据 generator_id 不符合冻结契约")
    if tuple(bundle.bundle.task_categories) != tuple(
        scenario.value for scenario in _SCENARIO_ORDER
    ):
        raise ValueError("bundle 类别顺序不符合正式数据契约")
    _create_output_pair(private_output_dir, public_output_dir)

    split_evidence: dict[FormalSplit, FormalTaskManifest | FormalHoldoutReceipt] = {}
    for split in FormalSplit:
        rows = [
            _FormalPrivateTaskRow.from_record(
                record,
                dataset_version=task_set.dataset_version,
                generator_id=task_set.generator_id,
                bundle_sha256=bundle.bundle_sha256,
            )
            for record in task_set.records(split)
        ]
        artifact_path = private_output_dir / f"{split.value}.jsonl"
        write_jsonl(artifact_path, (row.model_dump(mode="json") for row in rows))
        values = _split_evidence_values(
            task_set,
            bundle,
            split,
            parser_id=parser_id,
            artifact_sha256=sha256_file(artifact_path),
        )
        if split is FormalSplit.HOLDOUT:
            split_evidence[split] = FormalHoldoutReceipt.model_validate(values)
        else:
            split_evidence[split] = FormalTaskManifest.model_validate(values)

    assert_formal_split_isolation(tuple(split_evidence.values()))
    write_json(
        public_output_dir / "train.json",
        split_evidence[FormalSplit.TRAIN].model_dump(mode="json"),
    )
    write_json(
        public_output_dir / "dev.json",
        split_evidence[FormalSplit.DEV].model_dump(mode="json"),
    )
    write_json(
        public_output_dir / "holdout-receipt.json",
        split_evidence[FormalSplit.HOLDOUT].model_dump(mode="json"),
    )
    receipt = FormalDatasetReceipt(
        dataset_version=task_set.dataset_version,
        generator_id=task_set.generator_id,
        bundle_id=bundle.bundle.bundle_id,
        bundle_version=bundle.bundle.bundle_version,
        bundle_sha256=bundle.bundle_sha256,
        parser_id=parser_id,
        evaluator_id=bundle.bundle.evaluator_id,
        seed=task_set.seed,
        split_task_counts={split.value: split_evidence[split].task_count for split in FormalSplit},
        split_category_counts={
            split.value: split_evidence[split].category_counts for split in FormalSplit
        },
        public_files_sha256={
            filename: sha256_file(public_output_dir / filename) for filename in _PUBLIC_FILENAMES
        },
    )
    write_json(public_output_dir / "dataset.json", receipt.model_dump(mode="json"))
    return receipt


def load_formal_task_manifest(path: Path) -> FormalTaskManifest:
    """Load a strict train/dev public formal manifest."""
    return FormalTaskManifest.model_validate_json(path.read_text(encoding="utf-8"))


def load_formal_holdout_receipt(path: Path) -> FormalHoldoutReceipt:
    """Load a strict sealed-holdout public receipt."""
    return FormalHoldoutReceipt.model_validate_json(path.read_text(encoding="utf-8"))


def load_formal_dataset_receipt(path: Path) -> FormalDatasetReceipt:
    """Load a strict dataset-level public receipt."""
    receipt = FormalDatasetReceipt.model_validate_json(path.read_text(encoding="utf-8"))
    for filename, expected_sha256 in receipt.public_files_sha256.items():
        try:
            actual_sha256 = sha256_file(path.parent / filename)
        except OSError:
            raise ValueError(f"公开 split 文件无法读取: {filename}") from None
        if actual_sha256 != expected_sha256:
            raise ValueError(f"公开 split 文件 {filename} SHA-256 不匹配")
    return receipt


def load_formal_split(
    manifest: FormalTaskManifest | Path,
    artifact_path: Path,
) -> tuple[FormalTaskRecord, ...]:
    """Load and fully verify a non-holdout formal private split."""
    loaded = load_formal_task_manifest(manifest) if isinstance(manifest, Path) else manifest
    verified = FormalTaskManifest.model_validate(loaded.model_dump(mode="json"))
    content = _read_hash_verified_artifact(
        artifact_path,
        verified.artifact_sha256,
        changed_message="formal split artifact SHA-256 不匹配",
    )
    return _parse_and_validate_private_rows(verified, content)


def assert_formal_split_isolation(
    manifests: Sequence[FormalTaskManifest | FormalHoldoutReceipt],
) -> None:
    """Reject overlap across all five formal isolation dimensions."""
    seen_splits: set[str] = set()
    seen: dict[str, set[str]] = {field: set() for field in _FINGERPRINT_FIELDS}
    provenance: tuple[str, str, str, str, str, int] | None = None
    for manifest in manifests:
        validated = type(manifest).model_validate(manifest.model_dump(mode="json"))
        if validated.split in seen_splits:
            raise ValueError(f"formal split 重复: {validated.split}")
        seen_splits.add(validated.split)
        current_provenance = (
            validated.dataset_version,
            validated.generator_id,
            validated.bundle_id,
            validated.bundle_version,
            validated.bundle_sha256,
            validated.seed,
        )
        if provenance is None:
            provenance = current_provenance
        elif provenance != current_provenance:
            raise ValueError("formal split provenance 不一致")
        for field in _FINGERPRINT_FIELDS:
            values = set(getattr(validated, field))
            if overlap := seen[field] & values:
                singular = field.removesuffix("s")
                raise ValueError(f"split {singular} 交叉: {sorted(overlap)}")
            seen[field].update(values)


def _split_evidence_values(
    task_set: FormalTaskSet,
    bundle: LoadedRetailOpsBundle,
    split: FormalSplit,
    *,
    parser_id: str,
    artifact_sha256: str,
) -> dict[str, object]:
    records = task_set.records(split)
    counts = Counter(record.task.scenario.value for record in records)
    return {
        "dataset_version": task_set.dataset_version,
        "generator_id": task_set.generator_id,
        "bundle_id": bundle.bundle.bundle_id,
        "bundle_version": bundle.bundle.bundle_version,
        "bundle_sha256": bundle.bundle_sha256,
        "parser_id": parser_id,
        "evaluator_id": bundle.bundle.evaluator_id,
        "seed": task_set.seed,
        "split": split.value,
        "task_count": len(records),
        "category_counts": {scenario.value: counts[scenario.value] for scenario in _SCENARIO_ORDER},
        **{
            field: [getattr(record, field.removesuffix("s")) for record in records]
            for field in _FINGERPRINT_FIELDS
        },
        "artifact_sha256": artifact_sha256,
    }


def _create_output_pair(private_output_dir: Path, public_output_dir: Path) -> None:
    private_resolved = private_output_dir.resolve()
    public_resolved = public_output_dir.resolve()
    if (
        private_resolved == public_resolved
        or private_resolved in public_resolved.parents
        or public_resolved in private_resolved.parents
    ):
        raise ValueError("private/public 输出目录必须分离且不能互相嵌套")
    for path in (private_output_dir, public_output_dir):
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"输出目录已存在，拒绝覆盖: {path}")
    private_output_dir.mkdir(parents=True, exist_ok=False)
    public_output_dir.mkdir(parents=True, exist_ok=False)


def _read_hash_verified_artifact(
    artifact_path: Path,
    expected_sha256: str,
    *,
    changed_message: str,
) -> bytes:
    try:
        content = artifact_path.read_bytes()
    except OSError:
        raise ValueError("formal artifact 无法读取") from None
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(changed_message)
    return content


def _parse_and_validate_private_rows(
    evidence: FormalTaskManifest | FormalHoldoutReceipt,
    content: bytes,
) -> tuple[FormalTaskRecord, ...]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("formal artifact 必须是 UTF-8 JSONL") from None
    lines = text.splitlines()
    if len(lines) != evidence.task_count:
        raise ValueError("formal artifact 任务数量与公开证据不一致")
    rows = [_FormalPrivateTaskRow.model_validate_json(line) for line in lines]
    expected_scenarios = [
        scenario
        for scenario in _SCENARIO_ORDER
        for _ in range(evidence.category_counts[scenario.value])
    ]
    records: list[FormalTaskRecord] = []
    for index, (row, expected_scenario) in enumerate(zip(rows, expected_scenarios, strict=True)):
        if row.task.split != evidence.split:
            raise ValueError(f"formal artifact 第 {index} 行 split 不一致")
        if row.task.scenario is not expected_scenario:
            raise ValueError(f"formal artifact 第 {index} 行场景顺序不一致")
        if row.dataset_version != evidence.dataset_version:
            raise ValueError(f"formal artifact 第 {index} 行 dataset_version 不一致")
        if row.generator_id != evidence.generator_id:
            raise ValueError(f"formal artifact 第 {index} 行 generator_id 不一致")
        if row.bundle_sha256 != evidence.bundle_sha256:
            raise ValueError(f"formal artifact 第 {index} 行 bundle_sha256 不一致")
        if row.task.metadata.get("dataset_version") != evidence.dataset_version:
            raise ValueError(f"formal artifact 第 {index} 行 task dataset_version 不一致")
        if row.task.metadata.get("generator_id") != evidence.generator_id:
            raise ValueError(f"formal artifact 第 {index} 行 task generator_id 不一致")
        expected_record = FormalTaskRecord.from_task(row.task, row.variant_index)
        actual_record = row.to_record()
        if any(
            getattr(actual_record, field) != getattr(expected_record, field)
            for field in _ROW_FINGERPRINT_FIELDS
        ):
            raise ValueError(f"formal artifact 第 {index} 行记录指纹与 task 不一致")
        records.append(actual_record)

    actual_counts = Counter(row.task.scenario.value for row in rows)
    if actual_counts != evidence.category_counts:
        raise ValueError("formal artifact 类别配额与公开证据不一致")

    for public_field, row_field in zip(_FINGERPRINT_FIELDS, _ROW_FINGERPRINT_FIELDS, strict=True):
        if [getattr(record, row_field) for record in records] != getattr(evidence, public_field):
            raise ValueError(f"formal artifact {row_field} 顺序与公开证据不一致")
    return tuple(records)
