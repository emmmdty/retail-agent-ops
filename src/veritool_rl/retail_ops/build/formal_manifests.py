"""RetailOps R2 formal private artifacts and answer-free public manifests."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Self
from weakref import WeakSet

from pydantic import ConfigDict, Field, model_validator

from veritool_rl.core.artifacts import canonical_json, sha256_file, write_json, write_jsonl
from veritool_rl.core.trajectory import TaskScenario, TaskSpec
from veritool_rl.core.trajectory.schema import StrictModel
from veritool_rl.retail_ops.domain.bundle import LoadedRetailOpsBundle
from veritool_rl.retail_ops.domain.formal_tasks import (
    FormalSplit,
    FormalTaskRecord,
    FormalTaskSet,
)

_DATASET_VERSION = "retail_ops_v1_r2_20260722"
_GENERATOR_ID = "family_sha256_v1"
_PARSER_ID = "hermes-single-call-v1"
_EVALUATOR_ID = "retail_ops_v1"
_SEED = 0
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

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["2.0"] = "2.0"
    dataset_version: Literal["retail_ops_v1_r2_20260722"] = "retail_ops_v1_r2_20260722"
    generator_id: Literal["family_sha256_v1"] = "family_sha256_v1"
    bundle_id: Literal["retail_ops"] = "retail_ops"
    bundle_version: Literal["1.0.0"] = "1.0.0"
    bundle_sha256: Fingerprint
    parser_id: Literal["hermes-single-call-v1"] = "hermes-single-call-v1"
    evaluator_id: Literal["retail_ops_v1"] = "retail_ops_v1"
    seed: Literal[0] = 0
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

    model_config = ConfigDict(frozen=True)

    schema_version: Literal["2.0"] = "2.0"
    dataset_version: Literal["retail_ops_v1_r2_20260722"] = "retail_ops_v1_r2_20260722"
    generator_id: Literal["family_sha256_v1"] = "family_sha256_v1"
    bundle_id: Literal["retail_ops"] = "retail_ops"
    bundle_version: Literal["1.0.0"] = "1.0.0"
    bundle_sha256: Fingerprint
    parser_id: Literal["hermes-single-call-v1"] = "hermes-single-call-v1"
    evaluator_id: Literal["retail_ops_v1"] = "retail_ops_v1"
    seed: Literal[0] = 0
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


@dataclass(frozen=True, init=False, eq=False, slots=True, weakref_slot=True)
class VerifiedFormalDataset:
    """Factory-issued capability for one cross-checked public formal dataset."""

    receipt: FormalDatasetReceipt
    train_manifest: FormalTaskManifest
    dev_manifest: FormalTaskManifest
    holdout_receipt: FormalHoldoutReceipt
    public_dir: Path
    _snapshot_sha256: str

    def __new__(cls) -> VerifiedFormalDataset:
        raise TypeError("VerifiedFormalDataset 只能由 load_verified_formal_dataset 创建")

    @classmethod
    def _issue(
        cls,
        *,
        receipt: FormalDatasetReceipt,
        train_manifest: FormalTaskManifest,
        dev_manifest: FormalTaskManifest,
        holdout_receipt: FormalHoldoutReceipt,
        public_dir: Path,
    ) -> VerifiedFormalDataset:
        instance = object.__new__(cls)
        object.__setattr__(instance, "receipt", receipt)
        object.__setattr__(instance, "train_manifest", train_manifest)
        object.__setattr__(instance, "dev_manifest", dev_manifest)
        object.__setattr__(instance, "holdout_receipt", holdout_receipt)
        object.__setattr__(instance, "public_dir", public_dir)
        object.__setattr__(
            instance,
            "_snapshot_sha256",
            _public_models_sha256(
                receipt,
                train_manifest,
                dev_manifest,
                holdout_receipt,
            ),
        )
        _VERIFIED_DATASETS.add(instance)
        return instance


_VERIFIED_DATASETS: WeakSet[VerifiedFormalDataset] = WeakSet()


class _FormalPrivateTaskRow(StrictModel):
    """Private line binding complete task truth to formal provenance."""

    schema_version: Literal["2.0"] = "2.0"
    dataset_version: Literal["retail_ops_v1_r2_20260722"] = "retail_ops_v1_r2_20260722"
    generator_id: Literal["family_sha256_v1"] = "family_sha256_v1"
    bundle_id: Literal["retail_ops"] = "retail_ops"
    bundle_version: Literal["1.0.0"] = "1.0.0"
    bundle_sha256: Fingerprint
    parser_id: Literal["hermes-single-call-v1"] = "hermes-single-call-v1"
    evaluator_id: Literal["retail_ops_v1"] = "retail_ops_v1"
    seed: Literal[0] = 0
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
        bundle_sha256: str,
    ) -> _FormalPrivateTaskRow:
        return cls(
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
    parser_id: str = _PARSER_ID,
) -> FormalDatasetReceipt:
    """Write immutable private truth and answer-free public R2 metadata."""
    task_set.assert_exact_quotas()
    if task_set.dataset_version != _DATASET_VERSION:
        raise ValueError("正式数据 dataset_version 不符合冻结契约")
    if task_set.generator_id != _GENERATOR_ID:
        raise ValueError("正式数据 generator_id 不符合冻结契约")
    if task_set.seed != _SEED:
        raise ValueError("正式数据 seed 不符合冻结契约")
    if parser_id != _PARSER_ID:
        raise ValueError("正式数据 parser_id 不符合冻结契约")
    if (
        bundle.bundle.bundle_id != "retail_ops"
        or bundle.bundle.bundle_version != "1.0.0"
        or bundle.bundle.evaluator_id != _EVALUATOR_ID
    ):
        raise ValueError("正式数据 bundle/evaluator provenance 不符合冻结契约")
    if tuple(bundle.bundle.task_categories) != tuple(
        scenario.value for scenario in _SCENARIO_ORDER
    ):
        raise ValueError("bundle 类别顺序不符合正式数据契约")
    _validate_output_pair(private_output_dir, public_output_dir)

    private_staging: Path | None = None
    public_staging: Path | None = None
    private_publish_attempted = False
    public_publish_attempted = False
    private_published = False
    public_published = False
    try:
        private_staging = _make_staging_dir(private_output_dir)
        public_staging = _make_staging_dir(public_output_dir)
        receipt = _write_staged_task_set(
            task_set,
            bundle,
            private_staging,
            public_staging,
            parser_id=parser_id,
        )
        verified = load_verified_formal_dataset(public_staging)
        load_formal_split(verified, "train", private_staging / "train.jsonl")
        load_formal_split(verified, "dev", private_staging / "dev.jsonl")
        holdout_content = _read_hash_verified_artifact(
            private_staging / "holdout.jsonl",
            verified.holdout_receipt.artifact_sha256,
            changed_message="formal holdout staging SHA-256 不匹配",
        )
        _parse_and_validate_private_rows(verified.holdout_receipt, holdout_content)

        private_publish_attempted = True
        _publish_staging_dir(private_staging, private_output_dir)
        private_staging = None
        private_published = True
        public_publish_attempted = True
        _publish_staging_dir(public_staging, public_output_dir)
        public_staging = None
        public_published = True
        return receipt
    except BaseException:
        private_moved = (
            private_publish_attempted
            and private_staging is not None
            and not private_staging.exists()
        )
        public_moved = (
            public_publish_attempted and public_staging is not None and not public_staging.exists()
        )
        _remove_owned_dir(private_staging)
        _remove_owned_dir(public_staging)
        if private_published or private_moved:
            _remove_owned_dir(private_output_dir)
        if public_published or public_moved:
            _remove_owned_dir(public_output_dir)
        raise


def _write_staged_task_set(
    task_set: FormalTaskSet,
    bundle: LoadedRetailOpsBundle,
    private_output_dir: Path,
    public_output_dir: Path,
    *,
    parser_id: str,
) -> FormalDatasetReceipt:
    """Populate already-created staging roots and return their public receipt."""

    split_evidence: dict[FormalSplit, FormalTaskManifest | FormalHoldoutReceipt] = {}
    for split in FormalSplit:
        rows = [
            _FormalPrivateTaskRow.from_record(
                record,
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
    # 正式数据集轨道是 v1 专属的：`_require_formal_contract` 已拒绝其它 bundle 版本，
    # 这里把那条运行期保证收窄成类型事实。v2 的任务集必须作为**独立 dataset artifact**
    # 存在（自己的 version、自己的 manifest），不能挂在这份冻结 receipt 下。
    if bundle.bundle.bundle_version != "1.0.0":
        raise ValueError("正式数据集 receipt 只接受 v1 bundle")
    receipt = FormalDatasetReceipt(
        dataset_version="retail_ops_v1_r2_20260722",
        generator_id="family_sha256_v1",
        bundle_id=bundle.bundle.bundle_id,
        bundle_version=bundle.bundle.bundle_version,
        bundle_sha256=bundle.bundle_sha256,
        parser_id="hermes-single-call-v1",
        evaluator_id=bundle.bundle.evaluator_id,
        seed=0,
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
    return FormalTaskManifest.model_validate_json(_read_public_bytes(path))


def load_formal_holdout_receipt(path: Path) -> FormalHoldoutReceipt:
    """Load a strict sealed-holdout public receipt."""
    return FormalHoldoutReceipt.model_validate_json(_read_public_bytes(path))


def load_formal_dataset_receipt(path: Path) -> FormalDatasetReceipt:
    """Compatibility loader delegated to unified public dataset verification."""
    if path.name != "dataset.json":
        raise ValueError("formal dataset receipt 路径必须指向 dataset.json")
    return load_verified_formal_dataset(path.parent).receipt


def load_verified_formal_dataset(public_dir: Path) -> VerifiedFormalDataset:
    """Hash and parse the exact four public files from one batch of bytes."""
    dataset_bytes = _read_public_bytes(public_dir / "dataset.json")
    receipt = FormalDatasetReceipt.model_validate_json(dataset_bytes)
    split_bytes = {
        filename: _read_public_bytes(public_dir / filename) for filename in _PUBLIC_FILENAMES
    }
    for filename, content in split_bytes.items():
        actual_sha256 = hashlib.sha256(content).hexdigest()
        if actual_sha256 != receipt.public_files_sha256[filename]:
            raise ValueError(f"公开 split 文件 {filename} SHA-256 不匹配")

    train = FormalTaskManifest.model_validate_json(split_bytes["train.json"])
    dev = FormalTaskManifest.model_validate_json(split_bytes["dev.json"])
    holdout = FormalHoldoutReceipt.model_validate_json(split_bytes["holdout-receipt.json"])
    manifests: tuple[FormalTaskManifest | FormalHoldoutReceipt, ...] = (
        train,
        dev,
        holdout,
    )
    expected_provenance = _dataset_provenance(receipt)
    for manifest in manifests:
        if _split_provenance(manifest) != expected_provenance:
            raise ValueError(f"formal {manifest.split} public provenance 不一致")
        if receipt.split_task_counts[manifest.split] != manifest.task_count:
            raise ValueError(f"formal {manifest.split} task_count 与 dataset 不一致")
        if receipt.split_category_counts[manifest.split] != manifest.category_counts:
            raise ValueError(f"formal {manifest.split} category_counts 与 dataset 不一致")
    if (train.split, dev.split, holdout.split) != ("train", "dev", "holdout"):
        raise ValueError("formal dataset 必须精确包含 train/dev/holdout")
    assert_formal_split_isolation(manifests)
    return VerifiedFormalDataset._issue(
        receipt=receipt,
        train_manifest=train,
        dev_manifest=dev,
        holdout_receipt=holdout,
        public_dir=public_dir,
    )


def load_formal_split(
    dataset: VerifiedFormalDataset,
    split: Literal["train", "dev"],
    artifact_path: Path,
) -> tuple[FormalTaskRecord, ...]:
    """Load and fully verify a non-holdout formal private split."""
    _require_verified_dataset(dataset)
    if split == "train":
        manifest = dataset.train_manifest
    elif split == "dev":
        manifest = dataset.dev_manifest
    else:
        raise ValueError("formal private split loader 只允许 train/dev")
    content = _read_hash_verified_artifact(
        artifact_path,
        manifest.artifact_sha256,
        changed_message="formal split artifact SHA-256 不匹配",
    )
    return _parse_and_validate_private_rows(manifest, content)


def assert_formal_split_isolation(
    manifests: Sequence[FormalTaskManifest | FormalHoldoutReceipt],
) -> None:
    """Reject overlap across all five formal isolation dimensions."""
    seen_splits: set[str] = set()
    seen: dict[str, set[str]] = {field: set() for field in _FINGERPRINT_FIELDS}
    provenance: tuple[str, str, str, str, str, str, str, int] | None = None
    for manifest in manifests:
        validated = type(manifest).model_validate(manifest.model_dump(mode="json"))
        if validated.split in seen_splits:
            raise ValueError(f"formal split 重复: {validated.split}")
        seen_splits.add(validated.split)
        current_provenance = _split_provenance(validated)
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


def _validate_output_pair(private_output_dir: Path, public_output_dir: Path) -> None:
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


def _make_staging_dir(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    return Path(
        tempfile.mkdtemp(
            prefix=f".{target.name}.staging-",
            dir=target.parent,
        )
    )


def _publish_staging_dir(staging: Path, target: Path) -> None:
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"输出目录已存在，拒绝覆盖: {target}")
    staging.rename(target)


def _remove_owned_dir(path: Path | None) -> None:
    if path is None:
        return
    try:
        if path.is_symlink():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path)
    except FileNotFoundError:
        return


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


def _read_public_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError:
        raise ValueError(f"公开 formal 文件无法读取: {path.name}") from None


def _dataset_provenance(
    receipt: FormalDatasetReceipt,
) -> tuple[str, str, str, str, str, str, str, int]:
    return (
        receipt.dataset_version,
        receipt.generator_id,
        receipt.bundle_id,
        receipt.bundle_version,
        receipt.bundle_sha256,
        receipt.parser_id,
        receipt.evaluator_id,
        receipt.seed,
    )


def _split_provenance(
    evidence: FormalTaskManifest | FormalHoldoutReceipt,
) -> tuple[str, str, str, str, str, str, str, int]:
    return (
        evidence.dataset_version,
        evidence.generator_id,
        evidence.bundle_id,
        evidence.bundle_version,
        evidence.bundle_sha256,
        evidence.parser_id,
        evidence.evaluator_id,
        evidence.seed,
    )


def _require_verified_dataset(dataset: VerifiedFormalDataset) -> None:
    if not isinstance(dataset, VerifiedFormalDataset) or dataset not in _VERIFIED_DATASETS:
        raise PermissionError("formal dataset 缺少统一 public verification capability")
    current_snapshot = _public_models_sha256(
        dataset.receipt,
        dataset.train_manifest,
        dataset.dev_manifest,
        dataset.holdout_receipt,
    )
    if current_snapshot != dataset._snapshot_sha256:
        raise PermissionError("formal dataset verification capability 内容已改变")


def _public_models_sha256(
    receipt: FormalDatasetReceipt,
    train_manifest: FormalTaskManifest,
    dev_manifest: FormalTaskManifest,
    holdout_receipt: FormalHoldoutReceipt,
) -> str:
    payload = [
        receipt.model_dump(mode="json"),
        train_manifest.model_dump(mode="json"),
        dev_manifest.model_dump(mode="json"),
        holdout_receipt.model_dump(mode="json"),
    ]
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


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
        if row.bundle_id != evidence.bundle_id:
            raise ValueError(f"formal artifact 第 {index} 行 bundle_id 不一致")
        if row.bundle_version != evidence.bundle_version:
            raise ValueError(f"formal artifact 第 {index} 行 bundle_version 不一致")
        if row.bundle_sha256 != evidence.bundle_sha256:
            raise ValueError(f"formal artifact 第 {index} 行 bundle_sha256 不一致")
        if row.parser_id != evidence.parser_id:
            raise ValueError(f"formal artifact 第 {index} 行 parser_id 不一致")
        if row.evaluator_id != evidence.evaluator_id:
            raise ValueError(f"formal artifact 第 {index} 行 evaluator_id 不一致")
        if row.seed != evidence.seed:
            raise ValueError(f"formal artifact 第 {index} 行 seed 不一致")
        if row.task.metadata.get("dataset_version") != evidence.dataset_version:
            raise ValueError(f"formal artifact 第 {index} 行 task dataset_version 不一致")
        if row.task.metadata.get("generator_id") != evidence.generator_id:
            raise ValueError(f"formal artifact 第 {index} 行 task generator_id 不一致")
        metadata_variant = row.task.metadata.get("variant_index")
        if type(metadata_variant) is not int or metadata_variant != row.variant_index:
            raise ValueError(f"formal artifact 第 {index} 行 variant_index 不一致")
        expected_record = FormalTaskRecord.from_task(row.task, row.variant_index)
        actual_record = row.to_record()
        if any(
            getattr(actual_record, field) != getattr(expected_record, field)
            for field in _ROW_FINGERPRINT_FIELDS
        ):
            raise ValueError(f"formal artifact 第 {index} 行记录指纹与 task 不一致")
        records.append(actual_record)

    for index in range(0, len(records), 2):
        first, second = records[index : index + 2]
        if {first.variant_index, second.variant_index} != {0, 1}:
            raise ValueError(f"formal artifact family {index // 2} 必须包含变体 0 和 1")
        if (
            first.task_fingerprint == second.task_fingerprint
            or first.content_fingerprint == second.content_fingerprint
        ):
            raise ValueError(f"formal artifact family {index // 2} task/content 指纹必须不同")
        if any(
            getattr(first, field) != getattr(second, field)
            for field in (
                "family_fingerprint",
                "source_fingerprint",
                "derivation_fingerprint",
            )
        ):
            raise ValueError(f"formal artifact family {index // 2} 派生指纹必须共享")

    actual_counts = Counter(row.task.scenario.value for row in rows)
    if actual_counts != evidence.category_counts:
        raise ValueError("formal artifact 类别配额与公开证据不一致")

    for public_field, row_field in zip(_FINGERPRINT_FIELDS, _ROW_FINGERPRINT_FIELDS, strict=True):
        if [getattr(record, row_field) for record in records] != getattr(evidence, public_field):
            raise ValueError(f"formal artifact {row_field} 顺序与公开证据不一致")
    return tuple(records)
