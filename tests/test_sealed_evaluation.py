"""RetailOps R2 sealed formal holdout evaluator contract tests."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest

from veritool_rl.core.agent.qwen import GeneratedText
from veritool_rl.retail_ops.build.formal_manifests import (
    VerifiedFormalDataset,
    load_verified_formal_dataset,
    write_formal_task_set,
)
from veritool_rl.retail_ops.domain.bundle import LoadedRetailOpsBundle, load_bundle
from veritool_rl.retail_ops.domain.formal_tasks import build_formal_task_set
from veritool_rl.retail_ops.evaluate.sealed_evaluation import (
    SEALED_ARTIFACT_NAMES,
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
MODEL_NAME = "models/Qwen3-1.7B-pinned"
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


@dataclass(frozen=True)
class FormalFixture:
    """一次性构建、可复制的正式数据快照。"""

    private_dir: Path
    public_dir: Path
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
        model_name=MODEL_NAME,
        attempt_id=attempt_id,
        public_report_path=public_report_path or (tmp_path / "public" / "sealed-report.json"),
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
            model_name=MODEL_NAME,
            attempt_id="sealed-001",
            public_report_path=tmp_path / "public" / "sealed-report.json",
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
            model_name=MODEL_NAME,
            attempt_id="sealed-001",
            public_report_path=tmp_path / "public" / "sealed-report.json",
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
            model_name=MODEL_NAME,
            attempt_id="sealed-001",
            public_report_path=tmp_path / "public" / "sealed-report.json",
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
        "max_new_tokens",
        "max_steps",
        "task_count",
        "category_counts",
        "holdout_artifact_sha256",
        "holdout_receipt_sha256",
        "system_prompt_sha256",
        "tool_schema_sha256",
        "metrics",
        "failure_type_counts",
        "failure_category_counts",
        "failure_last_error_counts",
        "failure_violation_counts",
        "replayable_count",
        "evidence_complete",
        "private_artifact_sha256",
    }
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
