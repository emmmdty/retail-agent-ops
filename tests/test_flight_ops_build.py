"""FlightOps v1 build layer tests — manifests, teacher evidence, SFT export.

These tests verify the build pipeline produces valid artifacts WITHOUT needing
GPU or API access. The actual teacher collection (which costs API calls) is
tested via the remote GPU run manifests in task_plan R8 D2.
"""

from __future__ import annotations

import json

import pytest

from veritool_rl.flight_ops.build.dev_sft_export import export_sft_from_evidences
from veritool_rl.flight_ops.build.manifests import (
    FlightTaskManifest,
    load_manifest,
    write_manifest,
)
from veritool_rl.flight_ops.build.teacher_data import (
    FlightAttemptOutcome,
    FlightCollectionCheckpoint,
    FlightTaskEvidence,
    load_checkpoint,
    write_checkpoint,
    write_evidence,
)
from veritool_rl.flight_ops.domain.tasks import build_flight_task_set


@pytest.fixture(scope="module")
def task_set():
    return build_flight_task_set("flight_ops_v1_r8_001", seed=0)


def test_manifest_from_task_set(task_set) -> None:
    manifest = FlightTaskManifest.from_task_set(task_set)
    assert manifest.train_count == 240
    assert manifest.dev_count == 60
    assert manifest.dataset_version == "flight_ops_v1_r8_001"
    assert len(manifest.task_set_sha256) == 64


def test_manifest_deterministic(task_set) -> None:
    m1 = FlightTaskManifest.from_task_set(task_set)
    m2 = FlightTaskManifest.from_task_set(task_set)
    assert m1.task_set_sha256 == m2.task_set_sha256


def test_manifest_write_load_roundtrip(tmp_path, task_set) -> None:
    manifest = FlightTaskManifest.from_task_set(task_set)
    path = write_manifest(manifest, tmp_path / "manifests")
    loaded = load_manifest(path)
    assert loaded.model_dump() == manifest.model_dump()


def test_teacher_evidence_roundtrip() -> None:
    """FlightTaskEvidence serializes/deserializes cleanly (the evidence model
    is what enters the evidence chain — it must survive the JSON boundary)."""
    ev = FlightTaskEvidence(
        task_id="test:dev:001",
        content_sha256="a" * 64,
        dataset_version="v1",
        seed=0,
        bundle_sha256="b" * 64,
        manifest_sha256="c" * 64,
        route_sha256="d" * 64,
        config_sha256="e" * 64,
        outcome=FlightAttemptOutcome.SUCCESS,
        accepted=True,
        episode_index=0,
        request_attempts=1,
        usage_prompt_tokens=100,
        usage_completion_tokens=50,
        trajectory=None,
    )
    data = ev.model_dump(mode="json")
    restored = FlightTaskEvidence.model_validate_json(json.dumps(data))
    assert restored.task_id == ev.task_id
    assert restored.outcome == FlightAttemptOutcome.SUCCESS


def test_checkpoint_write_load_roundtrip(tmp_path) -> None:
    cp = FlightCollectionCheckpoint(
        dataset_version="v1",
        seed=0,
        bundle_sha256="a" * 64,
        manifest_sha256="b" * 64,
        route_sha256="c" * 64,
        config_sha256="d" * 64,
        accepted_task_ids=("task1", "task2"),
    )
    write_checkpoint(cp, tmp_path)
    loaded = load_checkpoint(tmp_path)
    assert loaded is not None
    assert loaded.accepted_task_ids == ("task1", "task2")


def test_checkpoint_load_returns_none_for_empty(tmp_path) -> None:
    assert load_checkpoint(tmp_path) is None


def test_write_evidence_creates_file(tmp_path) -> None:
    ev = FlightTaskEvidence(
        task_id="test:dev:001",
        content_sha256="a" * 64,
        dataset_version="v1",
        seed=0,
        bundle_sha256="b" * 64,
        manifest_sha256="c" * 64,
        route_sha256="d" * 64,
        config_sha256="e" * 64,
        outcome=FlightAttemptOutcome.SUCCESS,
        accepted=True,
        episode_index=0,
        request_attempts=1,
        usage_prompt_tokens=100,
        usage_completion_tokens=50,
    )
    write_evidence(ev, tmp_path / "evidence")
    expected_path = tmp_path / "evidence" / "test_dev_001.json"
    assert expected_path.exists()


def test_export_sft_empty_when_no_accepted(tmp_path) -> None:
    output = tmp_path / "sft.jsonl"
    total, written = export_sft_from_evidences(tmp_path / "empty", output)
    assert total == 0
    assert written == 0
    assert not output.exists()


def test_export_sft_skips_rejected(tmp_path) -> None:
    ev = FlightTaskEvidence(
        task_id="test:dev:001",
        content_sha256="a" * 64,
        dataset_version="v1",
        seed=0,
        bundle_sha256="b" * 64,
        manifest_sha256="c" * 64,
        route_sha256="d" * 64,
        config_sha256="e" * 64,
        outcome=FlightAttemptOutcome.STEP_LIMIT,
        accepted=False,
        episode_index=1,
        request_attempts=3,
        usage_prompt_tokens=200,
        usage_completion_tokens=100,
        trajectory=None,
    )
    evidence_dir = tmp_path / "evidence"
    write_evidence(ev, evidence_dir)
    output = tmp_path / "sft.jsonl"
    total, written = export_sft_from_evidences(evidence_dir, output)
    assert total == 1
    assert written == 0
