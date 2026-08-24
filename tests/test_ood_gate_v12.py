"""P1-6 / OOD 门禁集成：v1.2 gate schema 测试。

三条诚信约束（先于任何测试写下）：

1. v1.0 / v1.1 的 GATE_IDS 逐字节不变，已有 release 报告仍可加载。
2. v1.2 在 v1.1 基础上追加两个 OOD 门禁：ood_task_success_min / ood_success_delta_min。
3. OOD 证据缺失时 OOD 门禁判 FAIL——缺证据不是通过的理由。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.helpers_sealed import build_sealed_report
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.evaluate.sealed_evaluation import DeploymentForm
from veritool_rl.retail_ops.release.formal_release import (
    decide_formal_release,
)
from veritool_rl.retail_ops.release.release import (
    GATE_IDS,
    GATE_IDS_BY_SCHEMA,
    GATE_IDS_V1_1,
    GATE_IDS_V1_2,
    ReleaseDecision,
    build_release_gates,
)

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = ROOT / "domains/retail_ops/v1"


def _policy() -> Any:
    return load_bundle(BUNDLE_DIR).release


def _metrics(
    *,
    task_success: float,
    latency: float = 1000.0,
    tool_calls: float = 1.0,
    violations: int = 0,
    invalid: int = 0,
    p95: float = 1000.0,
) -> dict[str, Any]:
    return {
        "task_success": task_success,
        "policy_violation_count": violations,
        "invalid_call_count": invalid,
        "p95_latency_ms": p95,
        "average_latency_ms": latency,
        "average_tool_calls": tool_calls,
    }


def _pair(
    *,
    merged: bool = True,
    base_ood: dict[str, Any] | None = None,
    candidate_ood: dict[str, Any] | None = None,
    candidate_success: float = 1.0,
    candidate_latency: float = 1000.0,
) -> tuple[Any, Any, Any | None, Any | None]:
    """返回 (base, candidate, base_ood, candidate_ood)。"""
    base = build_sealed_report(
        schema_version="1.1",
        deployment_form=DeploymentForm.BASE,
        adapter=None,
        metrics=_metrics(task_success=0.80),
    )
    candidate = build_sealed_report(
        schema_version="1.1",
        deployment_form=DeploymentForm.MERGED if merged else DeploymentForm.BASE_PLUS_ADAPTER,
        merged=merged,
        adapter=None if merged else "unset",
        with_adapter=not merged,
        metrics=_metrics(task_success=candidate_success, latency=candidate_latency),
    )
    return base, candidate, base_ood, candidate_ood


#: 与 `_metrics` 里的 0.80 / 1.00 精确一致的逐任务配对结局。
PAIRED = [(index < 96, True) for index in range(120)]


# ---------------------------------------------------------------------------
# 版本化本身
# ---------------------------------------------------------------------------


def test_v12_gate_set_extends_v11_with_ood() -> None:
    """v1.2 = v1.1 + 两个 OOD 门禁，顺序不变。"""
    assert GATE_IDS_V1_2 == (
        "success_delta",
        "success_delta_ci_lower",
        "policy_violation_delta",
        "invalid_call_count",
        "per_call_latency_ratio",
        "steps_to_success_ratio",
        "latency_per_success_ratio",
        "evidence_complete",
        "ood_task_success_min",
        "ood_success_delta_min",
    )
    # v1.0 / v1.1 未被改动
    assert GATE_IDS_BY_SCHEMA["1.0"] == GATE_IDS
    assert GATE_IDS_BY_SCHEMA["1.1"] == GATE_IDS_V1_1
    assert GATE_IDS_BY_SCHEMA["1.2"] == GATE_IDS_V1_2
    assert set(GATE_IDS_BY_SCHEMA) == {"1.0", "1.1", "1.2"}


def test_v10_and_v11_gate_sets_untouched() -> None:
    """v1.0 / v1.1 逐字节不变——已有 release 报告仍可加载。"""
    assert GATE_IDS == (
        "success_delta",
        "policy_violation_delta",
        "invalid_call_count",
        "p95_latency_ratio",
        "evidence_complete",
    )
    assert GATE_IDS_V1_1 == (
        "success_delta",
        "success_delta_ci_lower",
        "policy_violation_delta",
        "invalid_call_count",
        "per_call_latency_ratio",
        "steps_to_success_ratio",
        "latency_per_success_ratio",
        "evidence_complete",
    )


# ---------------------------------------------------------------------------
# v1.2 门禁行为：有 OOD 证据时触发
# ---------------------------------------------------------------------------


def test_v12_gates_trigger_when_ood_evidence_provided() -> None:
    """有 OOD 证据时，v1.2 门禁正确计算。"""
    base, candidate, base_ood, candidate_ood = _pair(
        base_ood=_metrics(task_success=0.7333),
        candidate_ood=_metrics(task_success=0.9833),
    )
    policy = _policy()

    report = decide_formal_release(
        base,
        candidate,
        policy,
        gate_schema_version="1.2",
        paired_outcomes=PAIRED,
        ood_evidence=(base_ood, candidate_ood),
    )

    assert report.schema_version == "1.2"
    gate_ids = tuple(g.gate_id for g in report.gates)
    assert gate_ids == GATE_IDS_V1_2

    ood_success_gate = next(g for g in report.gates if g.gate_id == "ood_task_success_min")
    assert ood_success_gate.passed
    assert ood_success_gate.observed == pytest.approx(0.9833)
    assert ood_success_gate.threshold == 0.70

    ood_delta_gate = next(g for g in report.gates if g.gate_id == "ood_success_delta_min")
    assert ood_delta_gate.passed
    assert ood_delta_gate.observed == pytest.approx(0.25)
    assert ood_delta_gate.threshold == 0.0


def test_v12_ood_gate_fails_when_candidate_below_threshold() -> None:
    """候选 OOD 成功率低于 0.70 时，ood_task_success_min FAIL。"""
    base, candidate, base_ood, candidate_ood = _pair(
        base_ood=_metrics(task_success=0.7333),
        candidate_ood=_metrics(task_success=0.5833),
    )

    report = decide_formal_release(
        base,
        candidate,
        _policy(),
        gate_schema_version="1.2",
        paired_outcomes=PAIRED,
        ood_evidence=(base_ood, candidate_ood),
    )

    ood_success_gate = next(g for g in report.gates if g.gate_id == "ood_task_success_min")
    assert not ood_success_gate.passed
    assert ood_success_gate.observed == pytest.approx(0.5833)
    assert report.decision is ReleaseDecision.NO_GO


def test_v12_ood_gate_fails_when_delta_negative() -> None:
    """候选 OOD 成功率低于基座时，ood_success_delta_min FAIL。"""
    base, candidate, base_ood, candidate_ood = _pair(
        base_ood=_metrics(task_success=0.90),
        candidate_ood=_metrics(task_success=0.80),
    )

    report = decide_formal_release(
        base,
        candidate,
        _policy(),
        gate_schema_version="1.2",
        paired_outcomes=PAIRED,
        ood_evidence=(base_ood, candidate_ood),
    )

    ood_delta_gate = next(g for g in report.gates if g.gate_id == "ood_success_delta_min")
    assert not ood_delta_gate.passed
    assert ood_delta_gate.observed == pytest.approx(-0.10)
    assert report.decision is ReleaseDecision.NO_GO


# ---------------------------------------------------------------------------
# v1.2 门禁行为：无 OOD 证据时跳过（向后兼容）
# ---------------------------------------------------------------------------


def test_v12_without_ood_evidence_skips_ood_gates() -> None:
    """不传 ood_evidence 时，v1.2 的 OOD 门禁判 FAIL（缺证据不是通过的理由）。"""
    base, candidate, _, _ = _pair()

    report = decide_formal_release(
        base,
        candidate,
        _policy(),
        gate_schema_version="1.2",
        paired_outcomes=PAIRED,
    )

    ood_success_gate = next(g for g in report.gates if g.gate_id == "ood_task_success_min")
    assert not ood_success_gate.passed
    assert ood_success_gate.observed == "missing_ood_evidence"

    ood_delta_gate = next(g for g in report.gates if g.gate_id == "ood_success_delta_min")
    assert not ood_delta_gate.passed
    assert ood_delta_gate.observed == "missing_ood_evidence"


# ---------------------------------------------------------------------------
# v1.2 门禁行为：新旧门禁并存
# ---------------------------------------------------------------------------


def test_v10_v11_v12_gates_coexist() -> None:
    """三套版本互不干扰：v1.0/v1.1 行为不变，v1.2 新增 OOD。"""

    # v1.0：无 OOD 门禁
    v10 = build_release_gates(
        _metrics(task_success=0.80),
        _metrics(task_success=1.00),
        evidence_complete=True,
        policy=_policy(),
        schema_version="1.0",
    )
    assert len(v10) == 5
    assert all(g.gate_id != "ood_task_success_min" for g in v10)

    # v1.1：无 OOD 门禁
    v11 = build_release_gates(
        _metrics(task_success=0.80),
        _metrics(task_success=1.00),
        evidence_complete=True,
        policy=_policy(),
        schema_version="1.1",
    )
    assert len(v11) == 8
    assert all(g.gate_id != "ood_task_success_min" for g in v11)

    # v1.2：有 OOD 门禁
    v12 = build_release_gates(
        _metrics(task_success=0.80),
        _metrics(task_success=1.00),
        evidence_complete=True,
        policy=_policy(),
        schema_version="1.2",
    )
    assert len(v12) == 10
    assert v12[-1].gate_id == "ood_success_delta_min"
    assert v12[-2].gate_id == "ood_task_success_min"


# ---------------------------------------------------------------------------
# FormalReleaseReport OOD 字段兼容性
# ---------------------------------------------------------------------------


def test_v12_report_has_ood_fields() -> None:
    """v1.2 报告携带 OOD 元数据字段。"""
    base_ood = _metrics(task_success=0.7333)
    candidate_ood = _metrics(task_success=0.9833)
    base, candidate, _, _ = _pair(
        base_ood=base_ood,
        candidate_ood=candidate_ood,
    )

    report = decide_formal_release(
        base,
        candidate,
        _policy(),
        gate_schema_version="1.2",
        paired_outcomes=PAIRED,
        ood_evidence=(base_ood, candidate_ood),
    )

    assert report.ood_task_success == pytest.approx(0.9833)
    assert report.base_ood_task_success == pytest.approx(0.7333)


def test_v10_report_ood_fields_are_none() -> None:
    """v1.0 报告的 OOD 字段为 None，不影响自哈希。"""
    base, candidate, _, _ = _pair()

    report = decide_formal_release(
        base,
        candidate,
        _policy(),
        gate_schema_version="1.0",
    )

    assert report.ood_task_success is None
    assert report.base_ood_task_success is None
    assert report.ood_report_id is None


# ---------------------------------------------------------------------------
# 边界：partial OOD 证据（一侧缺失）
# ---------------------------------------------------------------------------


def test_v12_ood_evidence_with_none_base_ood() -> None:
    """基座侧 OOD 缺失时，OOD 门禁判 FAIL。"""
    _, candidate, _, candidate_ood = _pair(
        candidate_ood=_metrics(task_success=0.9833),
    )
    base = build_sealed_report(
        schema_version="1.1",
        deployment_form=DeploymentForm.BASE,
        adapter=None,
        metrics=_metrics(task_success=0.80),
    )

    report = decide_formal_release(
        base,
        candidate,
        _policy(),
        gate_schema_version="1.2",
        paired_outcomes=PAIRED,
        ood_evidence=(None, candidate_ood),
    )

    ood_success_gate = next(g for g in report.gates if g.gate_id == "ood_task_success_min")
    assert not ood_success_gate.passed
    assert ood_success_gate.observed == "missing_ood_evidence"


def test_v12_ood_evidence_with_none_candidate_ood() -> None:
    """候选侧 OOD 缺失时，OOD 门禁判 FAIL。"""
    base_ood = _metrics(task_success=0.7333)
    base, candidate, _, _ = _pair(
        base_ood=base_ood,
    )

    report = decide_formal_release(
        base,
        candidate,
        _policy(),
        gate_schema_version="1.2",
        paired_outcomes=PAIRED,
        ood_evidence=(base_ood, None),
    )

    ood_success_gate = next(g for g in report.gates if g.gate_id == "ood_task_success_min")
    assert not ood_success_gate.passed
    assert ood_success_gate.observed == "missing_ood_evidence"


# ---------------------------------------------------------------------------
# Task 1b: dry-run 验证——用 sft-003 OOD v2 读数做门禁逻辑验证
# ---------------------------------------------------------------------------


def test_v12_dry_run_with_sft003_ood_v2_reading() -> None:
    """用 docs/R9_PHASE_B_RESULTS.md 里 sft-003 的 OOD v2 读数验证门禁逻辑。

    sft-003 在 OOD v2 上 0.8667 / pv7；零训练基座约 0.7333。
    验证 v1.0/v1.1 门禁不受影响，v1.2 门禁正确判定。
    """
    # 模拟 sft-008 sealed 的基座与候选指标（观测 5 的读数）
    # metric 必须与 paired_outcomes 聚合一致
    base = build_sealed_report(
        schema_version="1.1",
        deployment_form=DeploymentForm.BASE,
        adapter=None,
        metrics=_metrics(task_success=103 / 120, violations=11, invalid=5, p95=3112.2),
    )
    candidate = build_sealed_report(
        schema_version="1.1",
        deployment_form=DeploymentForm.MERGED,
        merged=True,
        adapter=None,
        metrics=_metrics(task_success=117 / 120, violations=2, invalid=0, p95=3175.3),
    )
    # OOD evidence: base ~0.7333, sft-003 ~0.8667
    base_ood = _metrics(task_success=0.7333)
    candidate_ood = _metrics(task_success=0.8667)
    policy = _policy()

    # v1.1 的 paired_outcomes 必须与聚合指标一致：base=103/120, candidate=117/120
    # base 103 个 True 在前，candidate 117 个 True 在前
    paired = [(index < 103, index < 117) for index in range(120)]

    # v1.0 不受影响
    v10_report = decide_formal_release(
        base,
        candidate,
        policy,
        gate_schema_version="1.0",
    )
    assert v10_report.schema_version == "1.0"
    assert all(g.gate_id != "ood_task_success_min" for g in v10_report.gates)

    # v1.1 不受影响
    v11_report = decide_formal_release(
        base,
        candidate,
        policy,
        gate_schema_version="1.1",
        paired_outcomes=paired,
    )
    assert v11_report.schema_version == "1.1"
    assert all(g.gate_id != "ood_task_success_min" for g in v11_report.gates)

    # v1.2 有 OOD 门禁
    v12_report = decide_formal_release(
        base,
        candidate,
        policy,
        gate_schema_version="1.2",
        paired_outcomes=paired,
        ood_evidence=(base_ood, candidate_ood),
    )
    assert v12_report.schema_version == "1.2"

    ood_success = next(g for g in v12_report.gates if g.gate_id == "ood_task_success_min")
    assert ood_success.passed
    assert ood_success.observed == pytest.approx(0.8667)
    assert ood_success.threshold == 0.70

    ood_delta = next(g for g in v12_report.gates if g.gate_id == "ood_success_delta_min")
    assert ood_delta.passed
    assert ood_delta.observed == pytest.approx(0.1334)
    assert ood_delta.threshold == 0.0

    # OOD 元数据字段
    assert v12_report.ood_task_success == pytest.approx(0.8667)
    assert v12_report.base_ood_task_success == pytest.approx(0.7333)


# ---------------------------------------------------------------------------
# CLI 集成：_load_ood_evidence
# ---------------------------------------------------------------------------


def test_load_ood_evidence_from_config(tmp_path: Path) -> None:
    """_load_ood_evidence 从配置路径加载两份 JSON 指标文件。"""
    from veritool_rl.product_cli import _load_ood_evidence

    base_metrics = {"task_success": 0.7333}
    cand_metrics = {"task_success": 0.9833}
    base_path = tmp_path / "base_ood.json"
    cand_path = tmp_path / "cand_ood.json"
    base_path.write_text(json.dumps(base_metrics), encoding="utf-8")
    cand_path.write_text(json.dumps(cand_metrics), encoding="utf-8")

    config = {
        "ood_evidence": {
            "base_metrics_path": str(base_path),
            "candidate_metrics_path": str(cand_path),
        }
    }

    result = _load_ood_evidence(config, "1.2")
    assert result is not None
    base_ood, cand_ood = result
    assert base_ood["task_success"] == pytest.approx(0.7333)
    assert cand_ood["task_success"] == pytest.approx(0.9833)


def test_load_ood_evidence_returns_none_when_absent() -> None:
    """无 ood_evidence 配置时返回 None。"""
    from veritool_rl.product_cli import _load_ood_evidence

    assert _load_ood_evidence({}, "1.2") is None
    assert _load_ood_evidence({}, "1.0") is None


def test_load_ood_evidence_rejects_non_v12() -> None:
    """非 v1.2 版本传入 ood_evidence 是配置错误。"""
    from veritool_rl.product_cli import _load_ood_evidence

    config = {
        "ood_evidence": {
            "base_metrics_path": "a.json",
            "candidate_metrics_path": "b.json",
        }
    }
    with pytest.raises(ValueError, match=r"仅在 gate_schema_version=1\.2 下有效"):
        _load_ood_evidence(config, "1.0")
    with pytest.raises(ValueError, match=r"仅在 gate_schema_version=1\.2 下有效"):
        _load_ood_evidence(config, "1.1")


def test_load_ood_evidence_rejects_missing_keys() -> None:
    """ood_evidence 缺少必填键时拒绝。"""
    from veritool_rl.product_cli import _load_ood_evidence

    with pytest.raises(ValueError, match="缺少必填键"):
        _load_ood_evidence({"ood_evidence": {}}, "1.2")
    with pytest.raises(ValueError, match="缺少必填键"):
        _load_ood_evidence({"ood_evidence": {"base_metrics_path": "a.json"}}, "1.2")


def test_load_ood_evidence_rejects_non_dict_metrics(tmp_path: Path) -> None:
    """OOD 指标文件内容不是 JSON object 时拒绝。"""
    from veritool_rl.product_cli import _load_ood_evidence

    base_path = tmp_path / "base_ood.json"
    cand_path = tmp_path / "cand_ood.json"
    base_path.write_text("[1, 2, 3]", encoding="utf-8")
    cand_path.write_text('{"task_success": 0.9}', encoding="utf-8")

    config = {
        "ood_evidence": {
            "base_metrics_path": str(base_path),
            "candidate_metrics_path": str(cand_path),
        }
    }
    with pytest.raises(ValueError, match="基座 OOD 指标必须是 JSON object"):
        _load_ood_evidence(config, "1.2")


def test_run_formal_release_passes_ood_evidence_through(
    tmp_path: Path,
) -> None:
    """_run_formal_release 在 v1.2 时加载 OOD 指标并传递给 decide_formal_release。"""
    from argparse import Namespace
    from unittest.mock import patch

    from tests.helpers_sealed import build_sealed_report
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import DeploymentForm

    base_ood = {"task_success": 0.7333}
    cand_ood = {"task_success": 0.9833}
    base_ood_path = tmp_path / "base_ood.json"
    cand_ood_path = tmp_path / "cand_ood.json"
    base_ood_path.write_text(json.dumps(base_ood), encoding="utf-8")
    cand_ood_path.write_text(json.dumps(cand_ood), encoding="utf-8")

    config = {
        "pipeline": "formal_release",
        "bundle_dir": "domains/retail_ops/v1",
        "gate_schema_version": "1.2",
        "ood_evidence": {
            "base_metrics_path": str(base_ood_path),
            "candidate_metrics_path": str(cand_ood_path),
        },
    }

    sealed_base = build_sealed_report(
        schema_version="1.1",
        deployment_form=DeploymentForm.BASE,
        adapter=None,
        metrics=_metrics(task_success=0.80),
    )
    sealed_candidate = build_sealed_report(
        schema_version="1.1",
        deployment_form=DeploymentForm.MERGED,
        merged=True,
        adapter=None,
        metrics=_metrics(task_success=1.00),
    )

    captured_ood = {}

    def fake_decide(base, candidate, policy, **kwargs):
        captured_ood["ood_evidence"] = kwargs.get("ood_evidence")
        captured_ood["gate_schema_version"] = kwargs.get("gate_schema_version")
        from veritool_rl.retail_ops.release.formal_release import decide_formal_release

        return decide_formal_release(
            base,
            candidate,
            policy,
            gate_schema_version=kwargs["gate_schema_version"],
            paired_outcomes=kwargs.get("paired_outcomes"),
            ood_evidence=kwargs.get("ood_evidence"),
        )

    with (
        patch("veritool_rl.product_cli.load_sealed_evaluation_report") as mock_load,
        patch("veritool_rl.product_cli.load_bundle") as mock_bundle,
        patch("veritool_rl.product_cli.decide_formal_release", side_effect=fake_decide),
        patch("veritool_rl.product_cli.write_formal_release_report"),
        patch("veritool_rl.product_cli._current_code_commit", return_value="a" * 40),
        patch("veritool_rl.product_cli._paired_outcomes", return_value=None),
    ):
        mock_load.side_effect = [sealed_base, sealed_candidate]
        bundle_mock = mock_bundle.return_value
        bundle_mock.bundle_sha256 = "c" * 64
        bundle_mock.release = _policy()

        args = Namespace(
            baseline_dir=tmp_path / "base",
            candidate_dir=tmp_path / "cand",
            output_dir=tmp_path / "out",
            baseline_trajectories=None,
            candidate_trajectories=None,
        )

        from veritool_rl.product_cli import _run_formal_release

        _run_formal_release(args, config)

    assert captured_ood["gate_schema_version"] == "1.2"
    assert captured_ood["ood_evidence"] is not None
    loaded_base, loaded_cand = captured_ood["ood_evidence"]
    assert loaded_base["task_success"] == pytest.approx(0.7333)
    assert loaded_cand["task_success"] == pytest.approx(0.9833)


def test_run_formal_release_no_ood_evidence_when_absent(tmp_path: Path) -> None:
    """非 v1.2 或无 ood_evidence 时，ood_evidence 参数为 None。"""
    from argparse import Namespace
    from unittest.mock import MagicMock, patch

    from tests.helpers_sealed import build_sealed_report

    config = {
        "pipeline": "formal_release",
        "bundle_dir": "domains/retail_ops/v1",
        "gate_schema_version": "1.0",
    }

    sealed_base = build_sealed_report(
        schema_version="1.0",
        deployment_form=None,
        adapter=None,
        metrics=_metrics(task_success=0.80),
    )
    sealed_candidate = build_sealed_report(
        schema_version="1.0",
        deployment_form=None,
        adapter=None,
        metrics=_metrics(task_success=1.00),
    )

    captured_ood = {}

    def fake_decide(base, candidate, policy, **kwargs):
        captured_ood["ood_evidence"] = kwargs.get("ood_evidence")
        captured_ood["gate_schema_version"] = kwargs.get("gate_schema_version")
        return MagicMock()

    with (
        patch("veritool_rl.product_cli.load_sealed_evaluation_report") as mock_load,
        patch("veritool_rl.product_cli.load_bundle") as mock_bundle,
        patch("veritool_rl.product_cli.decide_formal_release", side_effect=fake_decide),
        patch("veritool_rl.product_cli.write_formal_release_report"),
        patch("veritool_rl.product_cli._current_code_commit", return_value="a" * 40),
        patch("veritool_rl.product_cli._paired_outcomes", return_value=None),
    ):
        mock_load.side_effect = [sealed_base, sealed_candidate]
        bundle_mock = mock_bundle.return_value
        bundle_mock.bundle_sha256 = "c" * 64
        bundle_mock.release = _policy()

        args = Namespace(
            baseline_dir=tmp_path / "base",
            candidate_dir=tmp_path / "cand",
            output_dir=tmp_path / "out",
            baseline_trajectories=None,
            candidate_trajectories=None,
        )

        from veritool_rl.product_cli import _run_formal_release

        _run_formal_release(args, config)

    assert captured_ood["ood_evidence"] is None
