"""R8 第二轮审查 A-1：ReleaseReport 必须有 self-hash，否则伪造 GO 在 load 时无法被发现。

第一轮审查的 A4 修了"换 venv 跑评测"那个洞（sealed 路径加 runtime_env_sha256），
但**判定落盘那一步本身仍是可改的**：`ReleaseReport` 没有任何内容哈希字段，
`load_release_report` 只调 `model_validate_json`。构造一份 `decision=GO /
failed_gate_ids=[] / 所有 gate.passed=True` 的 JSON，validator 会接受它，
只要 gate_id 序列命中 `GATE_IDS_BY_SCHEMA[version]`。

修法与 sealed 报告同构：给 `ReleaseReport` 加 `report_id = sha256(全字段)`，
`load_release_report` 重算并比对。**旧报告（无 report_id）加载后取 None，
不报错**——这是渐进式修复，不破坏已有磁盘产物。
"""

from __future__ import annotations

from typing import Any

import pytest

from veritool_rl.retail_ops.release.release import (
    ReleaseDecision,
    ReleaseReport,
    build_release_gates,
    finalize_release_report,
    load_release_report,
)


def _minimal_release_report(**overrides: Any) -> ReleaseReport:
    """构造一份字段自洽的 ReleaseReport（GO 判定）。"""
    from veritool_rl.retail_ops.domain.bundle import ReleasePolicyConfig

    baseline_metrics = {
        "task_success": 0.85,
        "policy_violation_count": 5,
        "invalid_call_count": 5,
        "p95_latency_ms": 3052.0,
    }
    candidate_metrics = {
        "task_success": 1.0,
        "policy_violation_count": 0,
        "invalid_call_count": 0,
        "p95_latency_ms": 3600.0,
    }
    policy = ReleasePolicyConfig(
        success_delta_min=0.05,
        critical_policy_violation_delta_max=0,
        p95_latency_ratio_max=1.25,
    )
    gates = build_release_gates(
        baseline_metrics,
        candidate_metrics,
        evidence_complete=True,
        policy=policy,
    )
    payload = {
        "schema_version": "1.0",
        "decision": ReleaseDecision.GO,
        "baseline_run_id": "a" * 64,
        "candidate_run_id": "b" * 64,
        "baseline_policy": "qwen:base",
        "candidate_policy": "qwen:candidate",
        "bundle_sha256": "c" * 64,
        "task_manifest_sha256": "d" * 64,
        "deployment": "candidate",
        "gates": [gate.model_dump(mode="json") for gate in gates],
        "failed_gate_ids": [],
        "baseline_metrics": baseline_metrics,
        "candidate_metrics": candidate_metrics,
    }
    payload.update(overrides)
    report = ReleaseReport.model_validate(payload)
    return finalize_release_report(report)


# ---------------------------------------------------------------------------
# report_id 字段存在
# ---------------------------------------------------------------------------


def test_release_report_has_report_id_field() -> None:
    """ReleaseReport 必须有 report_id 字段——sealed 报告有，release 报告也该有。"""
    fields = ReleaseReport.model_fields
    assert "report_id" in fields, "ReleaseReport 必须有 report_id 字段（self-hash）"


# ---------------------------------------------------------------------------
# 伪造 GO 在 load 时被发现
# ---------------------------------------------------------------------------


def test_a_forged_go_is_rejected_at_load(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """手改 release.json 把 NO_GO 改成 GO，load 时必须报错。

    这是 A-1 的核心：sealed 链条两端都有 self-hash，但判定落盘那一刀没有。
    """
    report = _minimal_release_report()
    # 先写一份合法报告
    import json

    report_path = tmp_path / "release.json"
    payload = report.model_dump(mode="json")
    # 如果有 report_id，先写合法的
    if payload.get("report_id") is not None:
        report_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        # 验证合法的能加载
        loaded = load_release_report(report_path)
        assert loaded.decision is ReleaseDecision.GO

        # 现在伪造：改 threshold 字段，但不改 report_id
        forged = json.loads(report_path.read_text(encoding="utf-8"))
        forged["gates"][0]["threshold"] = 999.0  # 改阈值
        report_path.write_text(
            json.dumps(forged, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        # load 时必须报错（report_id 复算不匹配）
        with pytest.raises((ValueError, Exception), match=r"report_id|自哈希|复算"):
            load_release_report(report_path)
    else:
        pytest.skip("report_id 字段还没加，跳过伪造检测")


def test_a_forged_decision_is_rejected_at_load(tmp_path: Any) -> None:
    """手改 release.json 把 decision 从 NO_GO 改成 GO，load 时必须报错。"""
    import json

    # 构造一份 NO_GO 报告
    baseline_metrics = {
        "task_success": 0.9,
        "policy_violation_count": 0,
        "invalid_call_count": 0,
        "p95_latency_ms": 1000.0,
    }
    candidate_metrics = {
        "task_success": 0.8,
        "policy_violation_count": 0,
        "invalid_call_count": 0,
        "p95_latency_ms": 2000.0,
    }
    from veritool_rl.retail_ops.domain.bundle import ReleasePolicyConfig

    gates = build_release_gates(
        baseline_metrics,
        candidate_metrics,
        evidence_complete=True,
        policy=ReleasePolicyConfig(
            success_delta_min=0.05,
            critical_policy_violation_delta_max=0,
            p95_latency_ratio_max=1.25,
        ),
    )
    failed = [g.gate_id for g in gates if not g.passed]
    payload = {
        "schema_version": "1.0",
        "decision": ReleaseDecision.NO_GO,
        "baseline_run_id": "a" * 64,
        "candidate_run_id": "b" * 64,
        "baseline_policy": "qwen:base",
        "candidate_policy": "qwen:candidate",
        "bundle_sha256": "c" * 64,
        "task_manifest_sha256": "d" * 64,
        "deployment": "baseline",
        "gates": [g.model_dump(mode="json") for g in gates],
        "failed_gate_ids": failed,
        "baseline_metrics": baseline_metrics,
        "candidate_metrics": candidate_metrics,
    }
    report = ReleaseReport.model_validate(payload)
    report = finalize_release_report(report)
    if report.report_id is None:
        pytest.skip("report_id 字段还没加")

    report_path = tmp_path / "release.json"
    report_path.write_text(
        json.dumps(report.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    # 验证合法的能加载
    loaded = load_release_report(report_path)
    assert loaded.decision is ReleaseDecision.NO_GO

    # 伪造：把 NO_GO 改成 GO，但不改 report_id
    forged = json.loads(report_path.read_text(encoding="utf-8"))
    forged["decision"] = "GO"
    forged["deployment"] = "candidate"
    forged["failed_gate_ids"] = []
    forged["gates"] = [{**g, "passed": True} if isinstance(g, dict) else g for g in forged["gates"]]
    report_path.write_text(
        json.dumps(forged, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises((ValueError, Exception), match=r"report_id|自哈希|复算|decision|不一致"):
        load_release_report(report_path)


# ---------------------------------------------------------------------------
# 旧报告（无 report_id）加载后取 None，不报错
# ---------------------------------------------------------------------------


def test_legacy_report_without_report_id_still_loads(tmp_path: Any) -> None:
    """旧报告（无 report_id 字段）加载后 report_id 取 None，不报错。

    这是渐进式修复——不破坏已有磁盘产物。
    """
    import json

    report = _minimal_release_report()
    payload = report.model_dump(mode="json")
    # 删掉 report_id 字段，模拟旧报告
    payload.pop("report_id", None)
    report_path = tmp_path / "release.json"
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    loaded = load_release_report(report_path)
    assert loaded.decision is ReleaseDecision.GO
