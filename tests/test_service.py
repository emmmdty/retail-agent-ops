"""RetailAgentOps qualification FastAPI 服务与 base fallback 测试。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from veritool_rl.core.artifacts import sha256_file, write_json
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.evaluate.evaluation import EvaluationMode, RunEvidence

_ARTIFACT_HASHES = {
    "config.yaml": "c" * 64,
    "trajectories.jsonl": "d" * 64,
    "metrics.json": "e" * 64,
    "failures.jsonl": "f" * 64,
    "log.txt": "1" * 64,
}


def _service_evidence(
    run_id: str,
    policy_type: str,
    task_success: float,
    invalid_calls: int,
    bundle_hash: str,
    manifest_hash: str,
) -> RunEvidence:
    return RunEvidence(
        run_id=hashlib.sha256(run_id.encode()).hexdigest(),
        mode=EvaluationMode.QUALIFICATION,
        policy_type=policy_type,
        bundle_sha256=bundle_hash,
        task_manifest_sha256=manifest_hash,
        seed=0,
        parser_id="hermes-single-call-v1",
        budget={"max_steps": 5},
        task_count=12,
        metrics={
            "task_success": task_success,
            "policy_violation_count": 0,
            "invalid_call_count": invalid_calls,
            "p95_latency_ms": 10.0,
        },
        evidence_complete=True,
        artifact_sha256=_ARTIFACT_HASHES,
    )


def _release_fixture(
    tmp_path: Path,
    policy_type: str,
    success: float,
    invalid: int,
) -> tuple[Path, Path]:
    from veritool_rl.retail_ops.build.manifests import build_qualification
    from veritool_rl.retail_ops.release.release import decide_release, write_release_report

    build_dir = tmp_path / f"build-{policy_type}"
    release_dir = tmp_path / f"release-{policy_type}"
    build_qualification(Path("domains/retail_ops/v1"), 0, build_dir)
    bundle = load_bundle(Path("domains/retail_ops/v1"))
    manifest_hash = sha256_file(build_dir / "manifest.json")
    report = decide_release(
        _service_evidence(
            "baseline",
            "baseline",
            8 / 12,
            0,
            bundle.bundle_sha256,
            manifest_hash,
        ),
        _service_evidence(
            policy_type,
            policy_type,
            success,
            invalid,
            bundle.bundle_sha256,
            manifest_hash,
        ),
        bundle.release,
    )
    write_release_report(report, release_dir)
    return build_dir, release_dir


def _app(tmp_path: Path, policy_type: str, success: float, invalid: int) -> FastAPI:
    from veritool_rl.retail_ops.serve.service import create_app

    build_dir, release_dir = _release_fixture(
        tmp_path,
        policy_type,
        success,
        invalid,
    )
    return create_app(release_dir, Path("domains/retail_ops/v1"), build_dir)


def test_serve_parser_requires_release_and_built_input_dirs() -> None:
    from veritool_rl.product_cli import build_product_parser

    parsed = build_product_parser().parse_args(
        [
            "serve",
            "--config",
            "configs/retail_ops/serve/retail_ops_v1_serve.yaml",
            "--release_dir",
            "reports/retail_ops/v1/release",
            "--input_dir",
            "reports/retail_ops/v1/build",
            "--output_dir",
            "reports/retail_ops/v1/service",
        ]
    )

    assert parsed.command == "serve"


def test_health_reports_candidate_for_go_release(tmp_path: Path) -> None:
    response = TestClient(_app(tmp_path, "oracle", 1.0, 0)).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "bundle_version": "1.0.0",
        "release_decision": "GO",
        "deployment": "candidate",
    }


def test_no_go_release_falls_back_to_baseline(tmp_path: Path) -> None:
    response = TestClient(_app(tmp_path, "unknown_tool", 0.0, 12)).get("/health")

    assert response.status_code == 200
    assert response.json()["release_decision"] == "NO-GO"
    assert response.json()["deployment"] == "baseline"


def test_service_runs_allowed_denied_and_recovery_without_truth_leak(
    tmp_path: Path,
) -> None:
    from veritool_rl.retail_ops.domain.tasks import build_qualification_tasks

    client = TestClient(_app(tmp_path, "oracle", 1.0, 0))
    tasks = build_qualification_tasks(seed=0)
    for category in ("refund_eligible", "refund_denied_window", "refund_recovery"):
        task_id = next(task.task_id for task in tasks if task.scenario.value == category)
        response = client.post(f"/v1/tasks/{task_id}/run")
        payload = response.json()

        assert response.status_code == 200
        assert payload["success"] is True
        assert payload["category"] == category
        assert payload["steps"]
        public_text = json.dumps(payload, ensure_ascii=False)
        for forbidden in ("target_state", "expected_calls", "user_request"):
            assert forbidden not in public_text


def test_service_returns_404_for_unknown_task(tmp_path: Path) -> None:
    response = TestClient(_app(tmp_path, "oracle", 1.0, 0)).post("/v1/tasks/not-a-task/run")

    assert response.status_code == 404
    assert response.json() == {"detail": "未知 qualification task"}


def test_service_rejects_release_bundle_mismatch(tmp_path: Path) -> None:
    from veritool_rl.retail_ops.serve.service import create_app

    build_dir, release_dir = _release_fixture(tmp_path, "oracle", 1.0, 0)
    release_path = release_dir / "release.json"
    payload = json.loads(release_path.read_text(encoding="utf-8"))
    payload["bundle_sha256"] = "0" * 64
    write_json(release_path, payload)

    # R8 第二轮审查 A-1 后，report_id 自哈希检查比 bundle_sha256 检查更早抓到
    # 篡改——改了 bundle_sha256 但没重算 report_id，load_release_report 会先报
    # "report_id 自哈希不匹配"。两个错误都说明 release 报告被篡改，service 拒绝加载。
    with pytest.raises(ValueError, match=r"report_id 自哈希不匹配|bundle SHA-256 不匹配"):
        create_app(release_dir, Path("domains/retail_ops/v1"), build_dir)


def test_serve_cli_writes_manifest_before_uvicorn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from veritool_rl.product_cli import main

    build_dir, release_dir = _release_fixture(tmp_path, "oracle", 1.0, 0)
    calls: list[dict[str, Any]] = []

    def fake_run(app: FastAPI, *, host: str, port: int) -> None:
        calls.append({"app": app, "host": host, "port": port})

    monkeypatch.setattr("veritool_rl.product_cli.uvicorn.run", fake_run)
    output_dir = tmp_path / "service"
    assert (
        main(
            [
                "serve",
                "--config",
                "configs/retail_ops/serve/retail_ops_v1_serve.yaml",
                "--release_dir",
                str(release_dir),
                "--input_dir",
                str(build_dir),
                "--output_dir",
                str(output_dir),
            ]
        )
        == 0
    )

    assert len(calls) == 1
    assert calls[0]["host"] == "127.0.0.1"
    assert calls[0]["port"] == 8000
    service = json.loads((output_dir / "service.json").read_text(encoding="utf-8"))
    assert service["deployment"] == "candidate"
    assert service["host"] == "127.0.0.1"
    assert service["port"] == 8000
