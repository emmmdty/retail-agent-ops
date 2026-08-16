"""RetailOps R2 formal dev loader and Qwen dev-base evidence tests."""

from __future__ import annotations

import builtins
import json
import re
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import ValidationError

from veritool_rl.core.agent.qwen import (
    GeneratedText,
    GenerationSettings,
    GpuMeasurement,
    hash_local_model_files,
)
from veritool_rl.retail_ops.build.formal_manifests import (
    FormalTaskManifest,
    VerifiedFormalDataset,
    load_formal_split,
    load_verified_formal_dataset,
    write_formal_task_set,
)
from veritool_rl.retail_ops.domain.bundle import LoadedRetailOpsBundle, load_bundle
from veritool_rl.retail_ops.domain.formal_tasks import FormalTaskRecord, build_formal_task_set
from veritool_rl.retail_ops.evaluate.base_evaluation import (
    BASE_ARTIFACT_NAMES,
    BaseEvaluationConfig,
    BaseRunEvidence,
    ModelArtifact,
    evaluate_formal_dev_base,
    load_base_run_evidence,
    load_verified_formal_dev,
)
from veritool_rl.retail_ops.release.governance import EvidencePurpose

DATASET_VERSION = "retail_ops_v1_r2_20260722"
BUNDLE_DIR = Path("domains/retail_ops/v1")
MODEL_DIR_NAME = "Qwen3-1.7B-pinned"
MODEL_FILES = ("config.json", "model.safetensors", "tokenizer.json")
REVISION = "9f3b1c2d4e5a6b7c8d9e0f1a2b3c4d5e6f708192"
CODE_COMMIT = "0123456789abcdef0123456789abcdef01234567"
UV_LOCK_SHA256 = "ab" * 32
ORDER_PATTERN = re.compile(r"O-[A-Z0-9]{12}")


class ScriptedBackend:
    """确定性 fake 后端：先查一次订单，再给最终回复。"""

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_new_tokens: int,
    ) -> GeneratedText:
        del max_new_tokens
        assert tools and tools[0]["type"] == "function"
        if any(message["role"] == "assistant" for message in messages):
            return GeneratedText(
                text="已完成核实。",
                input_tokens=48,
                output_tokens=6,
                latency_ms=2.0,
            )
        match = ORDER_PATTERN.search(str(messages[-1]["content"]))
        assert match is not None
        payload = json.dumps({"name": "get_order", "arguments": {"order_id": match.group(0)}})
        return GeneratedText(
            text=f"<tool_call>{payload}</tool_call>",
            input_tokens=32,
            output_tokens=17,
            latency_ms=3.5,
        )


class PinnedBackend(ScriptedBackend):
    """声明自身模型目录、revision、adapter 与生成参数的 fake 后端。"""

    def __init__(
        self,
        model_dir: Path,
        revision: str,
        *,
        adapter_path: str | None = None,
        settings: Any = None,
    ) -> None:
        self.model_dir = model_dir
        self.revision = revision
        self.adapter_path = adapter_path
        self.settings = GenerationSettings(max_new_tokens=256) if settings is None else settings


class FakeHardwareProvider:
    """CPU 测试用硬件测量注入点；绝不触碰 CUDA。"""

    def __init__(self) -> None:
        self.resets = 0
        self.measurements = 0

    def reset_peak_memory(self) -> None:
        self.resets += 1

    def measure(self) -> GpuMeasurement:
        self.measurements += 1
        return GpuMeasurement(
            gpu_index=3,
            gpu_uuid="GPU-8f6d3c21-4b5a-4c7d-9e10-2f3a4b5c6d7e",
            gpu_name="NVIDIA GeForce RTX 5090",
            cuda_visible_devices="3",
            cuda_device="cuda:0",
            peak_memory_bytes=5_368_709_120,
        )


class ExplodingPath:
    """任何属性访问都视为过早触碰私有路径。"""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"private path was touched too early: {name}")

    def __fspath__(self) -> str:
        raise AssertionError("private path was resolved too early")


@dataclass(frozen=True)
class FormalFixture:
    """一次性构建、可复制的正式数据快照。"""

    private_dir: Path
    public_dir: Path
    dataset: VerifiedFormalDataset

    @property
    def dev_manifest(self) -> FormalTaskManifest:
        return self.dataset.dev_manifest


@pytest.fixture(scope="module")
def formal_source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("formal-source")
    write_formal_task_set(
        build_formal_task_set(DATASET_VERSION, seed=0),
        load_bundle(BUNDLE_DIR),
        root / "private",
        root / "public",
    )
    return root


@pytest.fixture
def formal(formal_source: Path, tmp_path: Path) -> FormalFixture:
    target = tmp_path / "dataset"
    shutil.copytree(formal_source, target)
    public_dir = target / "public"
    return FormalFixture(
        private_dir=target / "private",
        public_dir=public_dir,
        dataset=load_verified_formal_dataset(public_dir),
    )


@pytest.fixture
def bundle() -> LoadedRetailOpsBundle:
    return load_bundle(BUNDLE_DIR)


@pytest.fixture
def models_root(tmp_path: Path) -> Path:
    model_dir = tmp_path / "models" / MODEL_DIR_NAME
    model_dir.mkdir(parents=True)
    (model_dir / "config.json").write_text('{"model_type":"qwen3"}', encoding="utf-8")
    (model_dir / "model.safetensors").write_bytes(b"pinned-weights")
    (model_dir / "tokenizer.json").write_text('{"version":"1.0"}', encoding="utf-8")
    return tmp_path / "models"


@pytest.fixture
def config(models_root: Path) -> BaseEvaluationConfig:
    return _config(models_root)


def _config(models_root: Path, **overrides: Any) -> BaseEvaluationConfig:
    values: dict[str, Any] = {
        "dataset_version": DATASET_VERSION,
        "model": ModelArtifact(
            repo="Qwen/Qwen3-1.7B",
            revision=REVISION,
            local_dir=MODEL_DIR_NAME,
            file_sha256=hash_local_model_files(models_root / MODEL_DIR_NAME, MODEL_FILES),
        ),
        "generation": GenerationSettings(max_new_tokens=256),
        "code_commit": CODE_COMMIT,
        "uv_lock_sha256": UV_LOCK_SHA256,
    }
    values.update(overrides)
    return BaseEvaluationConfig(**values)


def _dev_records(formal: FormalFixture) -> tuple[FormalTaskRecord, ...]:
    return load_verified_formal_dev(formal.private_dir, formal.dev_manifest)


def _evaluate(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    config: BaseEvaluationConfig,
    models_root: Path,
    tmp_path: Path,
    *,
    records: Sequence[FormalTaskRecord] | None = None,
    manifest: FormalTaskManifest | None = None,
    backend: Any = None,
    attempt_id: str = "base-001",
    public_report_path: Path | None = None,
    hardware_provider: Any = None,
) -> BaseRunEvidence:
    return evaluate_formal_dev_base(
        _dev_records(formal) if records is None else records,
        manifest or formal.dev_manifest,
        backend or ScriptedBackend(),
        config,
        bundle=bundle,
        models_root=models_root,
        private_root=formal.private_dir,
        attempt_id=attempt_id,
        public_report_path=public_report_path or (tmp_path / "public" / "base-report.json"),
        hardware_provider=hardware_provider or FakeHardwareProvider(),
    )


@pytest.mark.parametrize(
    "purpose",
    [EvidencePurpose.RELEASE, EvidencePurpose.BUILD, cast(EvidencePurpose, "develop")],
)
def test_dev_loader_rejects_non_develop_purpose_before_touching_filesystem(
    formal: FormalFixture,
    purpose: EvidencePurpose,
) -> None:
    with pytest.raises(PermissionError, match="develop"):
        load_verified_formal_dev(
            cast(Path, ExplodingPath()),
            formal.dev_manifest,
            purpose,
        )


def test_dev_loader_rejects_holdout_receipt_and_train_manifest_before_filesystem(
    formal: FormalFixture,
) -> None:
    with pytest.raises(ValueError, match="dev"):
        load_verified_formal_dev(
            cast(Path, ExplodingPath()),
            cast(FormalTaskManifest, formal.dataset.holdout_receipt),
        )
    with pytest.raises(ValueError, match="dev"):
        load_verified_formal_dev(
            cast(Path, ExplodingPath()),
            formal.dataset.train_manifest,
        )


def test_dev_loader_returns_sixty_fully_verified_records(formal: FormalFixture) -> None:
    records = load_verified_formal_dev(formal.private_dir, formal.dev_manifest)

    assert len(records) == 60
    assert all(record.task.split == "dev" for record in records)
    assert [record.task_fingerprint for record in records] == (
        formal.dev_manifest.task_fingerprints
    )
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
        for _ in range(10)
    ]


def test_dev_loader_rejects_artifact_hash_mismatch_and_row_tampering(
    formal: FormalFixture,
) -> None:
    artifact = formal.private_dir / "dev.jsonl"
    rows = artifact.read_text(encoding="utf-8").splitlines()
    artifact.write_text("\n".join(rows[:-1]) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256 不匹配"):
        load_verified_formal_dev(formal.private_dir, formal.dev_manifest)


def test_dev_loader_rejects_symlinked_artifact(formal: FormalFixture, tmp_path: Path) -> None:
    artifact = formal.private_dir / "dev.jsonl"
    outside = tmp_path / "outside-dev.jsonl"
    artifact.rename(outside)
    artifact.symlink_to(outside)

    with pytest.raises(ValueError, match="逃逸出受信根目录"):
        load_verified_formal_dev(formal.private_dir, formal.dev_manifest)

    artifact.unlink()
    inside = formal.private_dir / "inside-dev.jsonl"
    shutil.copyfile(outside, inside)
    artifact.symlink_to(inside)

    with pytest.raises(ValueError, match="符号链接"):
        load_verified_formal_dev(formal.private_dir, formal.dev_manifest)


def test_dev_loader_never_opens_the_holdout_artifact(formal: FormalFixture) -> None:
    (formal.private_dir / "holdout.jsonl").chmod(0o000)
    try:
        assert len(load_verified_formal_dev(formal.private_dir, formal.dev_manifest)) == 60
    finally:
        (formal.private_dir / "holdout.jsonl").chmod(0o644)


def test_base_config_has_no_adapter_surface() -> None:
    assert "adapter_path" not in BaseEvaluationConfig.model_fields
    assert "adapter_path" not in ModelArtifact.model_fields
    assert "adapter_path" not in BaseRunEvidence.model_fields


@pytest.mark.parametrize(
    "overrides",
    [
        {"seed": 1},
        {"max_steps": 4},
        {"max_steps": 6},
        {"generation": {"max_new_tokens": 256, "do_sample": True}},
        {"generation": {"max_new_tokens": 256, "enable_thinking": True}},
        {"generation": {"max_new_tokens": 256, "quantization": "int8"}},
        {"generation": {"max_new_tokens": 0}},
        {"code_commit": "not-a-commit"},
        {"uv_lock_sha256": "abc"},
        {"dataset_version": ""},
        {"bootstrap_samples": 500},
    ],
)
def test_base_config_rejects_contract_violations(
    models_root: Path,
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        _config(models_root, **overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"repo": "Qwen3-1.7B"},
        {"repo": ""},
        {"revision": "not-hex"},
        {"revision": ""},
        {"local_dir": "../escape"},
        {"local_dir": "nested/dir"},
        {"local_dir": ""},
        {"file_sha256": {}},
        {"file_sha256": {"../escape.json": "ab" * 32}},
        {"file_sha256": {"config.json": "short"}},
    ],
)
def test_model_artifact_rejects_unsafe_pins(overrides: dict[str, Any]) -> None:
    values: dict[str, Any] = {
        "repo": "Qwen/Qwen3-1.7B",
        "revision": REVISION,
        "local_dir": MODEL_DIR_NAME,
        "file_sha256": {"config.json": "ab" * 32},
    }
    values.update(overrides)

    with pytest.raises(ValidationError):
        ModelArtifact(**values)


def test_dev_base_evidence_binds_full_provenance_and_hardware(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    config: BaseEvaluationConfig,
    models_root: Path,
    tmp_path: Path,
) -> None:
    hardware_provider = FakeHardwareProvider()
    public_report_path = tmp_path / "public" / "base-report.json"

    evidence = _evaluate(
        formal,
        bundle,
        config,
        models_root,
        tmp_path,
        public_report_path=public_report_path,
        hardware_provider=hardware_provider,
    )

    assert evidence.purpose == "develop"
    assert evidence.split == "dev"
    assert evidence.seed == 0
    assert evidence.max_steps == 5
    assert evidence.task_count == 60
    assert evidence.dataset_version == DATASET_VERSION
    assert evidence.parser_id == "hermes-single-call-v1"
    assert evidence.evaluator_id == "retail_ops_v1"
    assert evidence.bundle_sha256 == bundle.bundle_sha256
    assert evidence.dev_artifact_sha256 == formal.dev_manifest.artifact_sha256
    assert evidence.code_commit == CODE_COMMIT
    assert evidence.uv_lock_sha256 == UV_LOCK_SHA256
    assert evidence.config_sha256 == config.config_sha256
    assert evidence.model.repo == "Qwen/Qwen3-1.7B"
    assert evidence.model.revision == REVISION
    assert evidence.model.file_sha256 == hash_local_model_files(
        models_root / MODEL_DIR_NAME, MODEL_FILES
    )
    assert evidence.generation.do_sample is False
    assert evidence.generation.enable_thinking is False
    assert evidence.generation.quantization == "nf4"
    assert evidence.hardware.gpu.gpu_index == 3
    assert evidence.hardware.gpu.gpu_uuid.startswith("GPU-")
    assert evidence.hardware.gpu.gpu_name == "NVIDIA GeForce RTX 5090"
    assert evidence.hardware.gpu.cuda_visible_devices == "3"
    assert evidence.hardware.gpu.cuda_device == "cuda:0"
    assert evidence.hardware.gpu.peak_memory_bytes == 5_368_709_120
    assert evidence.hardware.wall_time_seconds > 0.0
    assert evidence.hardware.tasks_per_second > 0.0
    assert evidence.hardware.output_tokens_per_second > 0.0
    assert hardware_provider.resets == 1
    assert hardware_provider.measurements == 1
    assert evidence.metrics["average_output_tokens"] > 0.0
    assert evidence.metrics["average_latency_ms"] > 0.0
    assert evidence.replayable_count == 60
    assert evidence.evidence_complete is True
    assert len(evidence.system_prompt_sha256) == 64
    assert len(evidence.tool_schema_sha256) == 64
    assert len(evidence.dev_manifest_sha256) == 64
    assert set(evidence.artifact_sha256) == set(BASE_ARTIFACT_NAMES)

    attempt_dir = formal.private_dir / "dev-base" / "base-001"
    assert sorted(path.name for path in attempt_dir.iterdir()) == sorted(
        (*BASE_ARTIFACT_NAMES, "run.json")
    )
    trajectories = (attempt_dir / "trajectories.jsonl").read_text("utf-8").splitlines()
    assert len(trajectories) == 60
    assert json.loads(public_report_path.read_text(encoding="utf-8")) == evidence.model_dump(
        mode="json"
    )


def test_dev_base_public_report_carries_no_task_or_family_identifier(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    config: BaseEvaluationConfig,
    models_root: Path,
    tmp_path: Path,
) -> None:
    public_report_path = tmp_path / "public" / "base-report.json"
    records = _dev_records(formal)

    _evaluate(
        formal,
        bundle,
        config,
        models_root,
        tmp_path,
        public_report_path=public_report_path,
    )
    text = public_report_path.read_text(encoding="utf-8")

    secrets: set[str] = set()
    for record in records:
        secrets.update(
            {
                record.task.task_id,
                record.task.user_request,
                str(record.task.metadata["family_id"]),
                str(record.task.metadata["order_id"]),
                record.task_fingerprint,
                record.family_fingerprint,
                record.content_fingerprint,
                record.source_fingerprint,
                record.derivation_fingerprint,
            }
        )
    assert secrets
    assert not [secret for secret in secrets if secret in text]


def test_dev_base_rejects_unverified_or_reordered_records(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    config: BaseEvaluationConfig,
    models_root: Path,
    tmp_path: Path,
) -> None:
    records = list(_dev_records(formal))
    train_records = load_formal_split(formal.dataset, "train", formal.private_dir / "train.jsonl")

    with pytest.raises(ValueError, match="数量"):
        _evaluate(formal, bundle, config, models_root, tmp_path, records=records[:-1])
    with pytest.raises(ValueError, match="数量"):
        _evaluate(formal, bundle, config, models_root, tmp_path, records=train_records)
    with pytest.raises(ValueError, match="指纹"):
        _evaluate(
            formal,
            bundle,
            config,
            models_root,
            tmp_path,
            records=list(reversed(records)),
        )
    assert not (formal.private_dir / "dev-base").exists()


def test_dev_base_revalidates_the_private_dev_artifact_itself(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    config: BaseEvaluationConfig,
    models_root: Path,
    tmp_path: Path,
) -> None:
    records = _dev_records(formal)
    artifact = formal.private_dir / "dev.jsonl"
    lines = artifact.read_text(encoding="utf-8").splitlines()
    artifact.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256 不匹配"):
        _evaluate(formal, bundle, config, models_root, tmp_path, records=records)
    assert not (formal.private_dir / "dev-base").exists()


def test_dev_base_rejects_non_dev_manifest_and_mismatched_bundle(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    config: BaseEvaluationConfig,
    models_root: Path,
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="dev"):
        _evaluate(
            formal,
            bundle,
            config,
            models_root,
            tmp_path,
            manifest=formal.dataset.train_manifest,
        )
    with pytest.raises(ValueError, match="dev"):
        _evaluate(
            formal,
            bundle,
            config,
            models_root,
            tmp_path,
            manifest=cast(FormalTaskManifest, formal.dataset.holdout_receipt),
        )

    other_bundle_dir = tmp_path / "other-bundle"
    shutil.copytree(BUNDLE_DIR, other_bundle_dir)
    policies_path = other_bundle_dir / "policies.yaml"
    policies_path.write_text(
        policies_path.read_text(encoding="utf-8") + "\n# drift\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="bundle"):
        _evaluate(formal, load_bundle(other_bundle_dir), config, models_root, tmp_path)


def test_dev_base_rejects_tasks_above_the_five_step_budget(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    config: BaseEvaluationConfig,
    models_root: Path,
    tmp_path: Path,
) -> None:
    records = list(_dev_records(formal))
    over_budget = records[0].task.model_copy(update={"max_steps": 6})
    records[0] = FormalTaskRecord.from_task(over_budget, records[0].variant_index)

    with pytest.raises(ValueError, match="max_steps"):
        _evaluate(formal, bundle, config, models_root, tmp_path, records=records)


@pytest.mark.parametrize("attempt_id", ["", "..", "../escape", "a/b"])
def test_dev_base_rejects_unsafe_attempt_identifiers(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    config: BaseEvaluationConfig,
    models_root: Path,
    tmp_path: Path,
    attempt_id: str,
) -> None:
    with pytest.raises(ValueError, match="attempt_id"):
        _evaluate(formal, bundle, config, models_root, tmp_path, attempt_id=attempt_id)


def test_dev_base_rejects_public_report_inside_the_private_root(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    config: BaseEvaluationConfig,
    models_root: Path,
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="private/public"):
        _evaluate(
            formal,
            bundle,
            config,
            models_root,
            tmp_path,
            public_report_path=formal.private_dir / "leaked.json",
        )
    assert not (formal.private_dir / "dev-base").exists()


@pytest.mark.parametrize("tamper", ["change", "remove", "extra"])
def test_dev_base_detects_tampered_pinned_model_files(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    config: BaseEvaluationConfig,
    models_root: Path,
    tmp_path: Path,
    tamper: str,
) -> None:
    model_dir = models_root / MODEL_DIR_NAME
    if tamper == "change":
        (model_dir / "model.safetensors").write_bytes(b"swapped-weights")
    elif tamper == "remove":
        (model_dir / "tokenizer.json").unlink()
    else:
        (model_dir / "extra_weights.safetensors").write_bytes(b"injected")

    with pytest.raises(ValueError, match="模型文件"):
        _evaluate(formal, bundle, config, models_root, tmp_path)
    assert not (formal.private_dir / "dev-base").exists()


def test_dev_base_rejects_backend_pinned_to_another_model(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    config: BaseEvaluationConfig,
    models_root: Path,
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="revision"):
        _evaluate(
            formal,
            bundle,
            config,
            models_root,
            tmp_path,
            backend=PinnedBackend(models_root / MODEL_DIR_NAME, "f" * 40),
        )
    with pytest.raises(ValueError, match="模型目录"):
        _evaluate(
            formal,
            bundle,
            config,
            models_root,
            tmp_path,
            backend=PinnedBackend(models_root / "another-model", REVISION),
        )


def test_dev_base_rejects_backend_that_loaded_an_adapter(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    config: BaseEvaluationConfig,
    models_root: Path,
    tmp_path: Path,
) -> None:
    """带 adapter 的后端会产出与真实 base 运行难以区分的证据，必须先被拒绝。"""
    with pytest.raises(ValueError, match="adapter"):
        _evaluate(
            formal,
            bundle,
            config,
            models_root,
            tmp_path,
            backend=PinnedBackend(
                models_root / MODEL_DIR_NAME,
                REVISION,
                adapter_path="adapters/sft-run-3",
            ),
        )
    assert not (formal.private_dir / "dev-base").exists()


@pytest.mark.parametrize(
    "settings",
    [
        GenerationSettings(max_new_tokens=512),
        SimpleNamespace(
            max_new_tokens=256,
            do_sample=True,
            enable_thinking=False,
            quantization="nf4",
        ),
        SimpleNamespace(
            max_new_tokens=256,
            do_sample=False,
            enable_thinking=True,
            quantization="nf4",
        ),
        SimpleNamespace(
            max_new_tokens=256,
            do_sample=False,
            enable_thinking=False,
            quantization="int8",
        ),
    ],
)
def test_dev_base_rejects_backend_with_non_frozen_generation_settings(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    config: BaseEvaluationConfig,
    models_root: Path,
    tmp_path: Path,
    settings: Any,
) -> None:
    with pytest.raises(ValueError, match="生成参数"):
        _evaluate(
            formal,
            bundle,
            config,
            models_root,
            tmp_path,
            backend=PinnedBackend(models_root / MODEL_DIR_NAME, REVISION, settings=settings),
        )
    assert not (formal.private_dir / "dev-base").exists()


def test_dev_base_accepts_backend_declaring_the_frozen_pin(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    config: BaseEvaluationConfig,
    models_root: Path,
    tmp_path: Path,
) -> None:
    """完全一致的声明必须通过，避免新增校验把合法 base 运行也挡掉。"""
    evidence = _evaluate(
        formal,
        bundle,
        config,
        models_root,
        tmp_path,
        backend=PinnedBackend(models_root / MODEL_DIR_NAME, REVISION),
    )

    assert evidence.task_count == 60
    assert evidence.generation == config.generation


def test_dev_base_evidence_detects_tampering(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    config: BaseEvaluationConfig,
    models_root: Path,
    tmp_path: Path,
) -> None:
    _evaluate(formal, bundle, config, models_root, tmp_path)
    attempt_dir = formal.private_dir / "dev-base" / "base-001"

    assert load_base_run_evidence(attempt_dir / "run.json").task_count == 60

    trajectories_path = attempt_dir / "trajectories.jsonl"
    trajectories_path.write_text(
        trajectories_path.read_text(encoding="utf-8").replace("delivered", "shipped", 1),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="SHA-256 不匹配"):
        load_base_run_evidence(attempt_dir / "run.json")

    run_path = attempt_dir / "run.json"
    payload = json.loads(run_path.read_text(encoding="utf-8"))
    payload["metrics"]["task_success"] = 1.0
    run_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="run_id"):
        load_base_run_evidence(run_path, verify_artifacts=False)


def test_dev_base_refuses_to_overwrite_an_existing_attempt(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    config: BaseEvaluationConfig,
    models_root: Path,
    tmp_path: Path,
) -> None:
    _evaluate(
        formal,
        bundle,
        config,
        models_root,
        tmp_path,
        public_report_path=tmp_path / "public" / "first.json",
    )

    with pytest.raises(FileExistsError):
        _evaluate(
            formal,
            bundle,
            config,
            models_root,
            tmp_path,
            public_report_path=tmp_path / "public" / "second.json",
        )
    assert not (tmp_path / "public" / "second.json").exists()


def test_dev_base_rolls_back_private_evidence_when_public_write_fails(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    config: BaseEvaluationConfig,
    models_root: Path,
    tmp_path: Path,
) -> None:
    public_report_path = tmp_path / "public" / "base-report.json"
    public_report_path.parent.mkdir(parents=True)
    public_report_path.write_text("{}", encoding="utf-8")

    with pytest.raises(FileExistsError):
        _evaluate(
            formal,
            bundle,
            config,
            models_root,
            tmp_path,
            public_report_path=public_report_path,
        )

    assert public_report_path.read_text(encoding="utf-8") == "{}"
    assert not (formal.private_dir / "dev-base" / "base-001").exists()


def test_dev_base_never_imports_cuda_or_model_runtime(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    config: BaseEvaluationConfig,
    models_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden = {"torch", "transformers", "peft", "bitsandbytes", "pynvml"}
    real_import = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.split(".")[0] in forbidden:
            raise AssertionError(f"CPU dev base 路径导入了 {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    evidence = _evaluate(formal, bundle, config, models_root, tmp_path)

    assert evidence.task_count == 60
