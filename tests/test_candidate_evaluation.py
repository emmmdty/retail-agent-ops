"""R3 Task 2: dev 候选（base+adapter）评测契约测试。

全部在 CPU 上用 fake backend / fake hardware provider 完成，不加载真实模型、
不访问 CUDA。另含一条对仓库里两份**真实** R2 base 证据的回归，用来证明为候选
评测所做的重构没有改变 base 证据的自哈希口径。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from veritool_rl.agent.qwen import GeneratedText, GenerationSettings, GpuMeasurement
from veritool_rl.retail_ops.base_evaluation import (
    BaseEvaluationConfig,
    ModelArtifact,
    evaluate_formal_dev_base,
    load_base_run_evidence,
    load_verified_formal_dev,
)
from veritool_rl.retail_ops.bundle import load_bundle
from veritool_rl.retail_ops.candidate_evaluation import (
    AdapterArtifact,
    CandidateEvaluationConfig,
    CandidateRunEvidence,
    ComparisonError,
    compare_dev_runs,
    evaluate_formal_dev_candidate,
    load_candidate_run_evidence,
)
from veritool_rl.retail_ops.formal_manifests import write_formal_task_set
from veritool_rl.retail_ops.formal_tasks import build_formal_task_set

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_VERSION = "retail_ops_v1_r2_20260722"
PUBLIC_REL = Path("manifests/retail_ops/v1") / DATASET_VERSION
PRIVATE_REL = Path("data/private/retail_ops/v1/r2") / DATASET_VERSION
BUNDLE_REL = Path("domains/retail_ops/v1")
MODEL_DIR_NAME = "Qwen3-4B-pinned"
MODEL_FILES = ("config.json", "tokenizer.json")
ADAPTER_FILES = ("adapter_config.json", "adapter_model.safetensors")
REVISION = "8cd0101f70cac4f1efcebc979faf483558e39297"


# ---------------------------------------------------------------------------
# 真实 R2 base 证据回归：重构不得改变既有证据的自哈希口径
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "attempt",
    ["qwen3-1.7b-dev-base-001", "qwen3-4b-dev-base-001"],
)
def test_existing_r2_base_reports_still_load_and_verify(attempt: str) -> None:
    """仓库里两份真实 R2 base 报告必须仍能加载且 run_id 复算一致。

    `_content_id` 把除 run_id/schema_version 外的**全部字段**算进自哈希，因此给
    `BaseRunEvidence` 加任何字段都会让这两份既有证据加载失败。这条测试是那个
    约束的机器可检查形式，不是文档承诺。
    """
    path = REPO_ROOT / "reports/retail_ops/v1/r2" / DATASET_VERSION / attempt / "base-report.json"
    if not path.is_file():
        pytest.skip(f"本地缺少 R2 base 报告（ignored 路径）: {path}")

    evidence = load_base_run_evidence(path, verify_artifacts=False)

    assert evidence.split == "dev"
    assert evidence.task_count == 60
    assert evidence.model.revision


def test_candidate_evidence_cannot_be_loaded_as_base_evidence(tmp_path: Path) -> None:
    """候选报告含 adapter 字段，base 的严格模型必须拒绝它（反向亦然）。"""
    payload = json.loads(_minimal_candidate_evidence_json())
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        load_base_run_evidence(path, verify_artifacts=False)


def _minimal_candidate_evidence_json() -> str:
    """构造一个字段齐全但内容为占位的候选证据 JSON，仅用于加载边界测试。"""
    return json.dumps(
        {
            "schema_version": "1.1",
            "run_id": "0" * 64,
            "purpose": "develop",
            "split": "dev",
            "dataset_version": DATASET_VERSION,
            "generator_id": "g",
            "bundle_id": "b",
            "bundle_version": "1",
            "bundle_sha256": "0" * 64,
            "parser_id": "p",
            "evaluator_id": "e",
            "seed": 0,
            "max_steps": 5,
            "dev_manifest_sha256": "0" * 64,
            "dev_artifact_sha256": "0" * 64,
            "system_prompt_sha256": "0" * 64,
            "tool_schema_sha256": "0" * 64,
            "config_sha256": "0" * 64,
            "code_commit": "1" * 40,
            "uv_lock_sha256": "0" * 64,
            "policy_id": "x",
            "model": {
                "repo": "Qwen/Qwen3-4B",
                "revision": REVISION,
                "local_dir": MODEL_DIR_NAME,
                "file_sha256": {"config.json": "0" * 64},
            },
            "adapter": {
                "run_dir": "reports/retail_ops/v1/r3/sft-001",
                "file_sha256": {"adapter_config.json": "0" * 64},
            },
            "generation": {"max_new_tokens": 256},
            "hardware": {
                "gpu": {
                    "gpu_index": 0,
                    "gpu_uuid": "GPU-0",
                    "gpu_name": "fake",
                    "cuda_visible_devices": "0",
                    "cuda_device": "cuda:0",
                    "peak_memory_bytes": 1,
                },
                "wall_time_seconds": 1.0,
                "tasks_per_second": 1.0,
                "output_tokens_per_second": 1.0,
            },
            "task_count": 60,
            "category_counts": {},
            "metrics": {},
            "replayable_count": 60,
            "evidence_complete": True,
            "artifact_sha256": {},
        }
    )


# ---------------------------------------------------------------------------
# 真实评测：workspace fixture（CPU / fake backend）
# ---------------------------------------------------------------------------


class _OracleTextBackend:
    """按 gold 调用序列回放的确定性后端；声明自身 pin 以通过绑定校验。"""

    def __init__(self, *, model_dir: Path, adapter_path: Path | None, settings: Any) -> None:
        self.model_dir = str(model_dir)
        self.adapter_path = None if adapter_path is None else str(adapter_path)
        self.revision = REVISION
        self.settings = settings

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_new_tokens: int,
    ) -> GeneratedText:
        # 只回一句最终答复：确定性、可重放。本测试验证的是契约与 pin 绑定，
        # 指标取值本身不重要，只要 base/candidate 两侧用同一个后端即可比较。
        del messages, tools, max_new_tokens
        return GeneratedText(text="任务已完成。", input_tokens=1, output_tokens=1)


class _FakeHardwareProvider:
    def reset_peak_memory(self) -> None:
        return None

    def measure(self) -> GpuMeasurement:
        return GpuMeasurement(
            gpu_index=0,
            gpu_uuid="GPU-8f6d3c21-4b5a-4c7d-9e10-2f3a4b5c6d7e",
            gpu_name="fake-gpu",
            cuda_visible_devices="0",
            cuda_device="cuda:0",
            peak_memory_bytes=1024,
        )


@pytest.fixture(scope="module")
def _source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("r3-candidate-source")
    shutil.copytree(REPO_ROOT / BUNDLE_REL, root / BUNDLE_REL)
    bundle = load_bundle(root / BUNDLE_REL)
    task_set = build_formal_task_set(DATASET_VERSION, seed=0)
    write_formal_task_set(task_set, bundle, root / PRIVATE_REL, root / PUBLIC_REL)
    return root


@pytest.fixture
def workspace(_source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shutil.copytree(_source, tmp_path, dirs_exist_ok=True)
    monkeypatch.chdir(tmp_path)
    model_dir = tmp_path / "models" / MODEL_DIR_NAME
    model_dir.mkdir(parents=True)
    for name in MODEL_FILES:
        (model_dir / name).write_text(f"model-{name}", encoding="utf-8")
    adapter_dir = tmp_path / "reports/retail_ops/v1/r3/sft-001/adapter"
    adapter_dir.mkdir(parents=True)
    for name in ADAPTER_FILES:
        (adapter_dir / name).write_text(f"adapter-{name}", encoding="utf-8")
    return tmp_path


def _model_artifact(workspace: Path) -> ModelArtifact:
    from veritool_rl.agent.qwen import hash_local_model_files

    return ModelArtifact(
        repo="Qwen/Qwen3-4B",
        revision=REVISION,
        local_dir=MODEL_DIR_NAME,
        file_sha256=hash_local_model_files(workspace / "models" / MODEL_DIR_NAME, MODEL_FILES),
    )


def _adapter_artifact(workspace: Path) -> AdapterArtifact:
    from veritool_rl.agent.qwen import hash_local_model_files

    run_dir = "reports/retail_ops/v1/r3/sft-001"
    return AdapterArtifact(
        run_dir=run_dir,
        file_sha256=hash_local_model_files(workspace / run_dir / "adapter", ADAPTER_FILES),
    )


def _candidate_config(workspace: Path, **overrides: Any) -> CandidateEvaluationConfig:
    values: dict[str, Any] = {
        "dataset_version": DATASET_VERSION,
        "model": _model_artifact(workspace),
        "adapter": _adapter_artifact(workspace),
        "generation": GenerationSettings(max_new_tokens=256),
        "code_commit": "1" * 40,
        "uv_lock_sha256": "0" * 64,
    }
    values.update(overrides)
    return CandidateEvaluationConfig(**values)


def _run_candidate(workspace: Path, config: CandidateEvaluationConfig, attempt: str) -> Any:
    manifest_dir = workspace / PUBLIC_REL
    from veritool_rl.retail_ops.formal_manifests import load_verified_formal_dataset

    dataset = load_verified_formal_dataset(manifest_dir)
    manifest = dataset.dev_manifest
    records = load_verified_formal_dev(workspace / PRIVATE_REL, manifest)
    adapter_dir = workspace / config.adapter.run_dir / "adapter"
    backend = _OracleTextBackend(
        model_dir=workspace / "models" / MODEL_DIR_NAME,
        adapter_path=adapter_dir,
        settings=config.generation,
    )
    return evaluate_formal_dev_candidate(
        records,
        manifest,
        backend,
        config,
        bundle=load_bundle(workspace / BUNDLE_REL),
        models_root=Path("models"),
        private_root=workspace / PRIVATE_REL,
        attempt_id=attempt,
        public_report_path=workspace / f"out-{attempt}/candidate-report.json",
        hardware_provider=_FakeHardwareProvider(),
    )


def test_candidate_run_writes_evidence_binding_the_adapter(workspace: Path) -> None:
    config = _candidate_config(workspace)

    evidence = _run_candidate(workspace, config, "cand-001")

    assert isinstance(evidence, CandidateRunEvidence)
    assert evidence.schema_version == "1.1"
    assert evidence.adapter == config.adapter
    assert evidence.task_count == 60
    assert evidence.split == "dev"
    # adapter 身份必须进 policy_id，证据不可与 base 运行混淆。
    assert "adapter" in evidence.policy_id

    private_run = workspace / PRIVATE_REL / "dev-candidate/cand-001/run.json"
    assert private_run.is_file()
    reloaded = load_candidate_run_evidence(private_run)
    assert reloaded.run_id == evidence.run_id


def test_candidate_run_rejects_tampered_adapter_files(workspace: Path) -> None:
    """adapter 逐文件哈希不符时必须在任何产物落盘前拒绝。"""
    config = _candidate_config(workspace)
    (workspace / config.adapter.run_dir / "adapter/adapter_config.json").write_text(
        "tampered", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="SHA-256"):
        _run_candidate(workspace, config, "cand-tampered")

    assert not (workspace / PRIVATE_REL / "dev-candidate/cand-tampered").exists()


def test_candidate_run_rejects_backend_without_adapter(workspace: Path) -> None:
    """config 声明了 adapter，后端却没挂——证据会谎称跑了候选，必须拒绝。"""
    config = _candidate_config(workspace)
    from veritool_rl.retail_ops.formal_manifests import load_verified_formal_dataset

    dataset = load_verified_formal_dataset(workspace / PUBLIC_REL)
    manifest = dataset.dev_manifest
    records = load_verified_formal_dev(workspace / PRIVATE_REL, manifest)
    backend = _OracleTextBackend(
        model_dir=workspace / "models" / MODEL_DIR_NAME,
        adapter_path=None,
        settings=config.generation,
    )

    with pytest.raises(ValueError, match="adapter"):
        evaluate_formal_dev_candidate(
            records,
            manifest,
            backend,
            config,
            bundle=load_bundle(workspace / BUNDLE_REL),
            models_root=Path("models"),
            private_root=workspace / PRIVATE_REL,
            attempt_id="cand-noadapter",
            public_report_path=workspace / "out/candidate-report.json",
            hardware_provider=_FakeHardwareProvider(),
        )


def test_base_path_still_rejects_backend_with_adapter(workspace: Path) -> None:
    """base 通道的既有防线不得因候选功能而放宽。"""
    from veritool_rl.retail_ops.formal_manifests import load_verified_formal_dataset

    dataset = load_verified_formal_dataset(workspace / PUBLIC_REL)
    manifest = dataset.dev_manifest
    records = load_verified_formal_dev(workspace / PRIVATE_REL, manifest)
    base_config = BaseEvaluationConfig(
        dataset_version=DATASET_VERSION,
        model=_model_artifact(workspace),
        generation=GenerationSettings(max_new_tokens=256),
        code_commit="1" * 40,
        uv_lock_sha256="0" * 64,
    )
    backend = _OracleTextBackend(
        model_dir=workspace / "models" / MODEL_DIR_NAME,
        adapter_path=workspace / "reports/retail_ops/v1/r3/sft-001/adapter",
        settings=base_config.generation,
    )

    with pytest.raises(ValueError, match="禁止 adapter"):
        evaluate_formal_dev_base(
            records,
            manifest,
            backend,
            base_config,
            bundle=load_bundle(workspace / BUNDLE_REL),
            models_root=Path("models"),
            private_root=workspace / PRIVATE_REL,
            attempt_id="base-with-adapter",
            public_report_path=workspace / "out/base-report.json",
            hardware_provider=_FakeHardwareProvider(),
        )


def test_candidate_run_refuses_to_overwrite_attempt(workspace: Path) -> None:
    config = _candidate_config(workspace)
    _run_candidate(workspace, config, "cand-001")

    with pytest.raises(FileExistsError):
        _run_candidate(workspace, config, "cand-001")


def test_candidate_public_report_leaks_no_task_identifiers(workspace: Path) -> None:
    config = _candidate_config(workspace)
    _run_candidate(workspace, config, "cand-001")

    text = (workspace / "out-cand-001/candidate-report.json").read_text(encoding="utf-8")
    from veritool_rl.retail_ops.formal_manifests import load_verified_formal_dataset

    dataset = load_verified_formal_dataset(workspace / PUBLIC_REL)
    records = load_verified_formal_dev(workspace / PRIVATE_REL, dataset.dev_manifest)
    for record in records:
        assert record.task.task_id not in text
        assert record.task.user_request not in text
        assert record.task_fingerprint not in text


# ---------------------------------------------------------------------------
# compare_dev_runs：配对校验与逐指标 delta
# ---------------------------------------------------------------------------


def _base_evidence(workspace: Path, attempt: str = "base-001") -> Any:
    from veritool_rl.retail_ops.formal_manifests import load_verified_formal_dataset

    dataset = load_verified_formal_dataset(workspace / PUBLIC_REL)
    manifest = dataset.dev_manifest
    records = load_verified_formal_dev(workspace / PRIVATE_REL, manifest)
    config = BaseEvaluationConfig(
        dataset_version=DATASET_VERSION,
        model=_model_artifact(workspace),
        generation=GenerationSettings(max_new_tokens=256),
        code_commit="1" * 40,
        uv_lock_sha256="0" * 64,
    )
    backend = _OracleTextBackend(
        model_dir=workspace / "models" / MODEL_DIR_NAME,
        adapter_path=None,
        settings=config.generation,
    )
    return evaluate_formal_dev_base(
        records,
        manifest,
        backend,
        config,
        bundle=load_bundle(workspace / BUNDLE_REL),
        models_root=Path("models"),
        private_root=workspace / PRIVATE_REL,
        attempt_id=attempt,
        public_report_path=workspace / f"out-{attempt}/base-report.json",
        hardware_provider=_FakeHardwareProvider(),
    )


def test_compare_requires_identical_evaluation_contract(workspace: Path) -> None:
    base = _base_evidence(workspace)
    candidate = _run_candidate(workspace, _candidate_config(workspace), "cand-001")

    comparison = compare_dev_runs(base, candidate)

    assert comparison.task_count == 60
    assert comparison.base_run_id == base.run_id
    assert comparison.candidate_run_id == candidate.run_id
    assert "task_success" in comparison.deltas
    for name, delta in comparison.deltas.items():
        assert delta.base == pytest.approx(base.metrics[name])
        assert delta.candidate == pytest.approx(candidate.metrics[name])
        assert delta.delta == pytest.approx(delta.candidate - delta.base)


@pytest.mark.parametrize(
    "field",
    [
        "bundle_sha256",
        "dev_manifest_sha256",
        "dev_artifact_sha256",
        "parser_id",
        "evaluator_id",
        "system_prompt_sha256",
        "tool_schema_sha256",
        "dataset_version",
    ],
)
def test_compare_rejects_mismatched_pairing_field(workspace: Path, field: str) -> None:
    """任一配对字段不一致就必须拒绝比较，而不是给出无效的 delta。"""
    base = _base_evidence(workspace)
    candidate = _run_candidate(workspace, _candidate_config(workspace), "cand-001")
    tampered = candidate.model_copy(update={field: _mutate(getattr(candidate, field))})

    with pytest.raises(ComparisonError, match=field):
        compare_dev_runs(base, tampered)


def _mutate(value: str) -> str:
    return ("1" if value[0] != "1" else "2") + value[1:]


def test_compare_rejects_base_evidence_carrying_an_adapter(workspace: Path) -> None:
    """两边都必须是各自的类型：base 位置不接受候选证据。"""
    candidate = _run_candidate(workspace, _candidate_config(workspace), "cand-001")

    with pytest.raises(ComparisonError):
        compare_dev_runs(candidate, candidate)
