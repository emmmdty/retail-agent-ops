"""RetailOps R2 sealed formal holdout evaluator contract tests."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest

from veritool_rl.core.agent.qwen import (
    GeneratedText,
    GenerationSettings,
    GpuMeasurement,
    hash_local_model_files,
)
from veritool_rl.retail_ops.build.formal_manifests import (
    VerifiedFormalDataset,
    load_verified_formal_dataset,
    write_formal_task_set,
)
from veritool_rl.retail_ops.domain.bundle import LoadedRetailOpsBundle, load_bundle
from veritool_rl.retail_ops.domain.formal_tasks import build_formal_task_set
from veritool_rl.retail_ops.evaluate.base_evaluation import ModelArtifact
from veritool_rl.retail_ops.evaluate.sealed_evaluation import (
    SEALED_ARTIFACT_NAMES,
    SealedEvaluationConfig,
    SealedEvaluationReport,
    evaluate_authorized_holdout,
    load_sealed_evaluation_report,
)
from veritool_rl.retail_ops.release.formal_governance import (
    AuthorizedFormalHoldout,
    authorize_formal_holdout,
    load_authorized_formal_holdout,
)
from veritool_rl.retail_ops.release.governance import EvidencePurpose

DATASET_VERSION = "retail_ops_v1_r2_20260722"
BUNDLE_DIR = Path("domains/retail_ops/v1")
LOGICAL_HOLDOUT = Path(f"data/private/retail_ops/v1/r2/{DATASET_VERSION}/holdout.jsonl")
MODEL_DIR_NAME = "Qwen3-1.7B-pinned"
MODEL_FILES = ("config.json", "tokenizer.json")
REVISION = "70d244cf5c3e5b4f0d5b6a0c9b58a5b2f9a1c3d7"
ORDER_PATTERN = re.compile(r"O-[A-Z0-9]{12}")


class ScriptedBackend:
    """确定性 fake 后端：先查一次订单，再给最终回复。"""

    def __init__(self) -> None:
        self.generate_calls = 0

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_new_tokens: int,
    ) -> GeneratedText:
        del max_new_tokens
        self.generate_calls += 1
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


class ExplodingPath:
    """任何文件系统触碰都视为过早访问私有数据。"""

    def __fspath__(self) -> str:
        raise AssertionError("private path was resolved too early")

    def exists(self) -> bool:
        raise AssertionError("private path existence was checked too early")


class _FakeHardwareProvider:
    """CPU 测试用的硬件测量替身；不触碰 CUDA。"""

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


@dataclass(frozen=True)
class FormalFixture:
    """一次性构建、可复制的正式数据快照。"""

    private_dir: Path
    public_dir: Path
    models_root: Path
    dataset: VerifiedFormalDataset


@pytest.fixture(scope="module")
def formal_source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("formal-source")
    write_formal_task_set(
        build_formal_task_set(DATASET_VERSION, seed=0),
        load_bundle(BUNDLE_DIR),
        root / "private",
        root / "public",
    )
    model_dir = root / "models" / MODEL_DIR_NAME
    model_dir.mkdir(parents=True)
    for name in MODEL_FILES:
        (model_dir / name).write_text(f"model-{name}", encoding="utf-8")
    return root


@pytest.fixture
def formal(formal_source: Path, tmp_path: Path) -> FormalFixture:
    target = tmp_path / "dataset"
    shutil.copytree(formal_source, target)
    public_dir = target / "public"
    return FormalFixture(
        private_dir=target / "private",
        public_dir=public_dir,
        models_root=target / "models",
        dataset=load_verified_formal_dataset(public_dir),
    )


def _sealed_config(formal: FormalFixture) -> SealedEvaluationConfig:
    """base 侧 sealed 契约：无 adapter，模型逐文件哈希锁定。"""
    return SealedEvaluationConfig(
        dataset_version=DATASET_VERSION,
        model=ModelArtifact(
            repo="Qwen/Qwen3-1.7B",
            revision=REVISION,
            local_dir=MODEL_DIR_NAME,
            file_sha256=hash_local_model_files(formal.models_root / MODEL_DIR_NAME, MODEL_FILES),
        ),
        generation=GenerationSettings(max_new_tokens=256),
        code_commit="1" * 40,
        uv_lock_sha256="0" * 64,
    )


@pytest.fixture
def bundle() -> LoadedRetailOpsBundle:
    return load_bundle(BUNDLE_DIR)


def _authorize(formal: FormalFixture) -> AuthorizedFormalHoldout:
    return authorize_formal_holdout(
        formal.dataset,
        formal.private_dir / "holdout.jsonl",
        LOGICAL_HOLDOUT,
        EvidencePurpose.RELEASE,
        trusted_private_root=formal.private_dir,
    )


def _evaluate(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    tmp_path: Path,
    *,
    attempt_id: str = "sealed-001",
    public_report_path: Path | None = None,
) -> SealedEvaluationReport:
    return evaluate_authorized_holdout(
        _authorize(formal),
        bundle,
        ScriptedBackend(),
        _sealed_config(formal),
        models_root=formal.models_root,
        attempt_id=attempt_id,
        public_report_path=public_report_path or (tmp_path / "public" / "sealed-report.json"),
        hardware_provider=_FakeHardwareProvider(),
    )


def test_development_purpose_cannot_produce_a_sealed_authorization(
    formal: FormalFixture,
) -> None:
    with pytest.raises(PermissionError, match="只允许 release"):
        authorize_formal_holdout(
            formal.dataset,
            cast(Path, ExplodingPath()),
            LOGICAL_HOLDOUT,
            EvidencePurpose.DEVELOP,
            trusted_private_root=cast(Path, ExplodingPath()),
        )


@pytest.mark.parametrize("authorization", ["not-an-authorization", None, 0])
def test_sealed_evaluator_rejects_unauthorized_inputs(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    tmp_path: Path,
    authorization: object,
) -> None:
    with pytest.raises(PermissionError, match="授权"):
        evaluate_authorized_holdout(
            cast(AuthorizedFormalHoldout, authorization),
            bundle,
            ScriptedBackend(),
            _sealed_config(formal),
            models_root=formal.models_root,
            attempt_id="sealed-001",
            public_report_path=tmp_path / "public" / "sealed-report.json",
            hardware_provider=_FakeHardwareProvider(),
        )
    assert not (formal.private_dir / "sealed-eval").exists()


def test_sealed_evaluator_rejects_forged_authorization_capability(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    tmp_path: Path,
) -> None:
    forged = object.__new__(AuthorizedFormalHoldout)

    with pytest.raises(PermissionError, match="授权"):
        evaluate_authorized_holdout(
            forged,
            bundle,
            ScriptedBackend(),
            _sealed_config(formal),
            models_root=formal.models_root,
            attempt_id="sealed-001",
            public_report_path=tmp_path / "public" / "sealed-report.json",
            hardware_provider=_FakeHardwareProvider(),
        )


def test_sealed_evaluator_rejects_bundle_that_does_not_match_the_receipt(
    formal: FormalFixture,
    tmp_path: Path,
) -> None:
    other_bundle_dir = tmp_path / "other-bundle"
    shutil.copytree(BUNDLE_DIR, other_bundle_dir)
    policies_path = other_bundle_dir / "policies.yaml"
    policies_path.write_text(
        policies_path.read_text(encoding="utf-8") + "\n# drift\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="bundle"):
        evaluate_authorized_holdout(
            _authorize(formal),
            load_bundle(other_bundle_dir),
            ScriptedBackend(),
            _sealed_config(formal),
            models_root=formal.models_root,
            attempt_id="sealed-001",
            public_report_path=tmp_path / "public" / "sealed-report.json",
            hardware_provider=_FakeHardwareProvider(),
        )


@pytest.mark.parametrize("attempt_id", ["", ".", "..", "../escape", "a/b", "attempt id"])
def test_sealed_evaluator_rejects_unsafe_attempt_identifiers(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    tmp_path: Path,
    attempt_id: str,
) -> None:
    with pytest.raises(ValueError, match="attempt_id"):
        _evaluate(formal, bundle, tmp_path, attempt_id=attempt_id)


def test_sealed_evaluator_rejects_public_report_inside_the_private_root(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="private/public"):
        _evaluate(
            formal,
            bundle,
            tmp_path,
            public_report_path=formal.private_dir / "leaked-report.json",
        )
    assert not (formal.private_dir / "sealed-eval").exists()


def test_sealed_evaluation_keeps_full_trajectories_private(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    tmp_path: Path,
) -> None:
    public_report_path = tmp_path / "public" / "sealed-report.json"

    report = _evaluate(formal, bundle, tmp_path, public_report_path=public_report_path)

    attempt_dir = formal.private_dir / "sealed-eval" / "sealed-001"
    assert sorted(path.name for path in attempt_dir.iterdir()) == sorted(
        (*SEALED_ARTIFACT_NAMES, "report.json")
    )
    rows = [
        json.loads(line)
        for line in (attempt_dir / "trajectories.jsonl").read_text("utf-8").splitlines()
    ]
    assert len(rows) == 120
    assert all(row["task"]["target_state"] for row in rows)
    assert all(row["task"]["expected_calls"] for row in rows)
    assert report.task_count == 120
    assert report.split == "holdout"
    assert report.purpose == "release"
    assert report.evidence_complete is True
    assert report.replayable_count == 120


def test_sealed_public_report_only_exposes_allowlisted_aggregates(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    tmp_path: Path,
) -> None:
    public_report_path = tmp_path / "public" / "sealed-report.json"

    report = _evaluate(formal, bundle, tmp_path, public_report_path=public_report_path)
    payload = json.loads(public_report_path.read_text(encoding="utf-8"))

    # `_sealed_config` 默认构造 v1.0 报告（无 merged_from、无 inference_engine），
    # 因此公开 payload 必须是 v1.0 的 allowlist——不含 v1.1/v1.2 才有的字段
    # （deployment_form / merged_from / inference_engine / runtime_env_sha256）。
    # 这是 R8 第一轮独立审查 A4 修复带来的真正 allowlist 语义：v1.0 报告的
    # 公开 payload 不该出现 v1.1/v1.2 才有的字段，即使值是 None——否则下游
    # 消费者会看到一个"声称是 v1.0 却带新字段"的自相矛盾的报告。
    assert set(payload) == {
        "schema_version",
        "report_id",
        "purpose",
        "dataset_version",
        "generator_id",
        "bundle_id",
        "bundle_version",
        "bundle_sha256",
        "parser_id",
        "evaluator_id",
        "seed",
        "split",
        "policy_id",
        "max_steps",
        "task_count",
        "category_counts",
        "holdout_artifact_sha256",
        "holdout_receipt_sha256",
        "system_prompt_sha256",
        "tool_schema_sha256",
        "config_sha256",
        "code_commit",
        "uv_lock_sha256",
        "model",
        "adapter",
        "generation",
        "hardware",
        "metrics",
        "failure_type_counts",
        "failure_category_counts",
        "failure_last_error_counts",
        "failure_violation_counts",
        "replayable_count",
        "evidence_complete",
        "private_artifact_sha256",
    }
    # 显式断言：v1.0 报告的 payload 必须不含 v1.1/v1.2 字段
    assert "deployment_form" not in payload
    assert "merged_from" not in payload
    assert "inference_engine" not in payload
    assert "runtime_env_sha256" not in payload
    assert payload["report_id"] == report.report_id
    assert payload["category_counts"] == {
        "lookup_status": 20,
        "refund_eligible": 20,
        "refund_denied_window": 20,
        "refund_denied_ownership": 20,
        "refund_denied_duplicate": 20,
        "refund_recovery": 20,
    }
    assert sum(payload["failure_type_counts"].values()) == 40
    assert payload["failure_category_counts"] == {"refund_eligible": 20, "refund_recovery": 20}
    assert payload["metrics"]["task_count"] == 120
    assert set(payload["private_artifact_sha256"]) == set(SEALED_ARTIFACT_NAMES)


def test_sealed_public_report_contains_no_task_family_or_truth_identifier(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    tmp_path: Path,
) -> None:
    public_report_path = tmp_path / "public" / "sealed-report.json"
    records = load_authorized_formal_holdout(_authorize(formal))

    _evaluate(formal, bundle, tmp_path, public_report_path=public_report_path)
    text = public_report_path.read_text(encoding="utf-8")

    secrets: set[str] = set()
    for record in records:
        secrets.update(
            {
                record.task.task_id,
                record.task.user_request,
                str(record.task.metadata["family_id"]),
                str(record.task.metadata["order_id"]),
                str(record.task.metadata["customer_id"]),
                record.task_fingerprint,
                record.family_fingerprint,
                record.content_fingerprint,
                record.source_fingerprint,
                record.derivation_fingerprint,
            }
        )
    assert secrets
    assert not [secret for secret in secrets if secret in text]


def test_sealed_evidence_hashes_detect_tampering(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    tmp_path: Path,
) -> None:
    public_report_path = tmp_path / "public" / "sealed-report.json"
    _evaluate(formal, bundle, tmp_path, public_report_path=public_report_path)
    attempt_dir = formal.private_dir / "sealed-eval" / "sealed-001"

    assert load_sealed_evaluation_report(attempt_dir / "report.json").task_count == 120

    metrics_path = attempt_dir / "metrics.json"
    payload = json.loads(metrics_path.read_text(encoding="utf-8"))
    payload["task_success"] = 1.0
    metrics_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256 不匹配"):
        load_sealed_evaluation_report(attempt_dir / "report.json")

    report_payload = json.loads((attempt_dir / "report.json").read_text(encoding="utf-8"))
    report_payload["metrics"]["task_success"] = 1.0
    (attempt_dir / "report.json").write_text(json.dumps(report_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="report_id"):
        load_sealed_evaluation_report(attempt_dir / "report.json", verify_artifacts=False)


def test_sealed_evaluation_refuses_to_overwrite_an_existing_attempt(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    tmp_path: Path,
) -> None:
    first = tmp_path / "public" / "first.json"
    second = tmp_path / "public" / "second.json"
    _evaluate(formal, bundle, tmp_path, public_report_path=first)

    with pytest.raises(FileExistsError):
        _evaluate(formal, bundle, tmp_path, public_report_path=second)
    assert not second.exists()
    assert (formal.private_dir / "sealed-eval" / "sealed-001" / "report.json").exists()


def test_sealed_evaluation_rolls_back_private_evidence_when_public_write_fails(
    formal: FormalFixture,
    bundle: LoadedRetailOpsBundle,
    tmp_path: Path,
) -> None:
    public_report_path = tmp_path / "public" / "sealed-report.json"
    public_report_path.parent.mkdir(parents=True)
    public_report_path.write_text("{}", encoding="utf-8")

    with pytest.raises(FileExistsError):
        _evaluate(formal, bundle, tmp_path, public_report_path=public_report_path)

    assert public_report_path.read_text(encoding="utf-8") == "{}"
    assert not (formal.private_dir / "sealed-eval" / "sealed-001").exists()
    assert not list((formal.private_dir / "sealed-eval").glob(".*staging*"))


# ---------------------------------------------------------------------------
# findings #7：步数预算常量的单源绑定
# ---------------------------------------------------------------------------


def test_sealed_step_budget_is_bound_to_the_base_config_literal() -> None:
    """`_MAX_STEPS` 必须是 `BaseEvaluationConfig.max_steps` 的默认值本身。

    三处 5（config Literal、_MAX_STEPS、冻结数据集）曾经互相独立：改 config 而
    忘改 _MAX_STEPS 时，sealed 路径会按旧预算拒收合法任务。绑定后 config 是
    唯一改动点；数据集那一路仍由 `_require_step_budget` 运行时校验。
    """
    from veritool_rl.retail_ops.evaluate import sealed_evaluation
    from veritool_rl.retail_ops.evaluate.base_evaluation import BaseEvaluationConfig

    assert BaseEvaluationConfig.model_fields["max_steps"].default == sealed_evaluation._MAX_STEPS
    assert sealed_evaluation._MAX_STEPS == 5
