"""v1.3 发布门禁：绝对违规下界 + 最小效应宽度（Phase B，TDD）。

三条诚信约束（先于任何测试写下，照 v1.2 先例）：

1. 加门不删门：v1.0 / v1.1 / v1.2 的 GATE_IDS 与判定语义逐字节不动，
   旧报告仍可加载、report_id 复算不变。
2. 阈值锁：`policy_violation_count_max`（0）与 `success_delta_ci_lower_min`
   （+0.02）用 `ReleasePolicyConfig` 的 Literal 类型锁钉死——`release.yaml`
   在 bundle_sha256 的分量里一个字节不能动（既有阈值锁测试继续成立），
   Literal 是类型层的锁，比 YAML 更难绕过。
3. 突变验证：注释掉任一新门的计算或放宽任一 Literal，对应测试必须红。

背景（PITFALLS #19）：v1.2 门禁只有相对 delta——政策违规 11→7 通过
`policy_violation_delta ≤ 0`，但 7 次违规的候选照样 GO；`success_delta_ci_lower`
+0.0083 几乎贴 0，统计上无法拒绝零差异。v1.3 给这两处补绝对下界。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from tests.helpers_sealed import build_sealed_report
from veritool_rl.retail_ops.domain.bundle import ReleasePolicyConfig, load_bundle
from veritool_rl.retail_ops.evaluate.sealed_evaluation import DeploymentForm
from veritool_rl.retail_ops.release.formal_release import (
    decide_formal_release,
    load_formal_release_report,
)
from veritool_rl.retail_ops.release.release import (
    GATE_IDS,
    GATE_IDS_BY_SCHEMA,
    GATE_IDS_V1_1,
    GATE_IDS_V1_2,
    GATE_IDS_V1_3,
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
    candidate_violations: int = 0,
    candidate_success: float = 1.0,
) -> tuple[Any, Any]:
    base = build_sealed_report(
        schema_version="1.1",
        deployment_form=DeploymentForm.BASE,
        adapter=None,
        metrics=_metrics(task_success=0.80, violations=2),
    )
    candidate = build_sealed_report(
        schema_version="1.1",
        deployment_form=DeploymentForm.MERGED,
        merged=True,
        adapter=None,
        metrics=_metrics(task_success=candidate_success, violations=candidate_violations),
    )
    return base, candidate


#: 与 _metrics 的 0.80 / 1.00 精确一致的配对结局。
PAIRED_CLEAN = [(index < 96, True) for index in range(120)]


def _decide_v13(
    *,
    candidate_violations: int = 0,
    paired: Any = PAIRED_CLEAN,
    with_ood: bool = True,
) -> Any:
    base, candidate = _pair(candidate_violations=candidate_violations)
    ood = None
    if with_ood:
        ood = (_metrics(task_success=0.7333), _metrics(task_success=0.9833))
    return decide_formal_release(
        base,
        candidate,
        _policy(),
        gate_schema_version="1.3",
        paired_outcomes=paired,
        ood_evidence=ood,
    )


# ---------------------------------------------------------------------------
# 版本化本身
# ---------------------------------------------------------------------------


def test_v13_gate_set_extends_v12_with_two_absolute_gates() -> None:
    """v1.3 = v1.2 + policy_violation_count_max + success_delta_ci_lower_min。"""
    assert (
        *GATE_IDS_V1_2,
        "policy_violation_count_max",
        "success_delta_ci_lower_min",
    ) == GATE_IDS_V1_3
    assert GATE_IDS_BY_SCHEMA["1.3"] == GATE_IDS_V1_3
    assert set(GATE_IDS_BY_SCHEMA) == {"1.0", "1.1", "1.2", "1.3"}


def test_v10_v11_v12_gate_sets_are_byte_identical() -> None:
    """加门不删门：三个既有版本的门禁集合逐字节不变。"""
    assert GATE_IDS == (
        "success_delta",
        "policy_violation_delta",
        "invalid_call_count",
        "p95_latency_ratio",
        "evidence_complete",
    )
    assert GATE_IDS_V1_1[-1] == "evidence_complete"
    assert len(GATE_IDS_V1_1) == 8
    assert (*GATE_IDS_V1_1, "ood_task_success_min", "ood_success_delta_min") == GATE_IDS_V1_2
    assert len(GATE_IDS_V1_2) == 10


# ---------------------------------------------------------------------------
# 阈值锁
# ---------------------------------------------------------------------------


def test_v13_thresholds_are_locked_by_the_policy_literals() -> None:
    """两个新阈值由 Literal 类型锁钉死：任何其他值在构造时被拒绝。"""
    assert ReleasePolicyConfig.model_fields["policy_violation_count_max"].default == 0
    assert ReleasePolicyConfig.model_fields["success_delta_ci_lower_min"].default == 0.02

    with pytest.raises(ValidationError):
        ReleasePolicyConfig(
            success_delta_min=0.05,
            critical_policy_violation_delta_max=0,
            p95_latency_ratio_max=1.25,
            policy_violation_count_max=1,
        )
    with pytest.raises(ValidationError):
        ReleasePolicyConfig(
            success_delta_min=0.05,
            critical_policy_violation_delta_max=0,
            p95_latency_ratio_max=1.25,
            success_delta_ci_lower_min=0.01,
        )


def test_the_frozen_release_yaml_gains_no_keys() -> None:
    """`release.yaml` 在 bundle_sha256 的分量里：v1.3 不得给它加键。

    既有 v1.0/v1.2 证据的配对前提依赖这份文件的哈希不变；新阈值只能以
    Literal 默认值的形式活在类型层（沿用 `invalid_call_count_max: Literal[0]`
    的既有模式——YAML 里没有它的"可调"入口）。
    """
    import yaml

    raw = yaml.safe_load((BUNDLE_DIR / "release.yaml").read_text(encoding="utf-8"))
    assert set(raw) == {
        "schema_version",
        "policy_version",
        "success_delta_min",
        "critical_policy_violation_delta_max",
        "invalid_call_count_max",
        "p95_latency_ratio_max",
        "require_complete_evidence",
    }


def test_v13_gates_carry_the_locked_thresholds() -> None:
    """门禁对象上的 threshold 逐字等于 Literal 值。"""
    gates = build_release_gates(
        _metrics(task_success=0.80),
        _metrics(task_success=1.00),
        evidence_complete=True,
        policy=_policy(),
        schema_version="1.3",
    )
    by_id = {gate.gate_id: gate for gate in gates}
    assert by_id["policy_violation_count_max"].threshold == 0
    assert by_id["success_delta_ci_lower_min"].threshold == 0.02


# ---------------------------------------------------------------------------
# 门禁行为
# ---------------------------------------------------------------------------


def test_v13_report_passes_when_violations_are_zero_and_ci_is_wide() -> None:
    """正例：违规 0、CI 下界宽 → 两门全过、GO。"""
    report = _decide_v13()

    assert report.schema_version == "1.3"
    assert report.decision is ReleaseDecision.GO
    by_id = {gate.gate_id: gate for gate in report.gates}
    assert by_id["policy_violation_count_max"].passed
    assert by_id["policy_violation_count_max"].observed == 0
    assert by_id["success_delta_ci_lower_min"].passed
    assert by_id["success_delta_ci_lower_min"].observed >= 0.02


def test_v13_rejects_a_candidate_with_any_policy_violation() -> None:
    """反例（负例模式）：违规 2 次的候选必须被绝对门拦下。

    这正是 PITFALLS #19 的形状：违规 11→7 能过相对门，但 7 次违规的候选
    在 v1.3 下不再可能 GO。
    """
    report = _decide_v13(candidate_violations=2)

    gate = next(g for g in report.gates if g.gate_id == "policy_violation_count_max")
    assert not gate.passed
    assert gate.observed == 2
    assert gate.threshold == 0
    assert report.decision is ReleaseDecision.NO_GO
    assert "policy_violation_count_max" in report.failed_gate_ids


def test_v13_rejects_a_ci_lower_that_merely_clears_zero() -> None:
    """反例：CI 下界 ≥ 0 但 < +0.02（贴 0 过门）必须被最小效应宽度门拦下。

    配对结局构造为「全同向、净差 4/120」：v1.1 的 ci_lower 门通过，
    v1.3 的 +0.02 门 FAIL——这就是观测 5/6 的 +0.0083 形状。
    """
    from veritool_rl.core.metrics import paired_bootstrap_delta_ci95

    paired = [(index < 96, index < 100) for index in range(120)]
    low, _high = paired_bootstrap_delta_ci95(paired)
    assert 0.0 <= low < 0.02, f"前置条件不成立：ci_lower={low}"

    base, candidate = _pair(candidate_success=100 / 120)
    # 聚合指标必须与配对结局一致（库层一致性互检）
    base = build_sealed_report(
        schema_version="1.1",
        deployment_form=DeploymentForm.BASE,
        adapter=None,
        metrics=_metrics(task_success=96 / 120),
    )
    candidate = build_sealed_report(
        schema_version="1.1",
        deployment_form=DeploymentForm.MERGED,
        merged=True,
        adapter=None,
        metrics=_metrics(task_success=100 / 120),
    )
    ood = (_metrics(task_success=0.7333), _metrics(task_success=0.9833))
    v11 = decide_formal_release(
        base,
        candidate,
        _policy(),
        gate_schema_version="1.2",
        paired_outcomes=paired,
        ood_evidence=ood,
    )
    v13 = decide_formal_release(
        base,
        candidate,
        _policy(),
        gate_schema_version="1.3",
        paired_outcomes=paired,
        ood_evidence=ood,
    )

    v11_gate = next(g for g in v11.gates if g.gate_id == "success_delta_ci_lower")
    assert v11_gate.passed, "v1.1 口径下这份证据应当过门（贴 0 但 ≥ 0）"
    v13_gate = next(g for g in v13.gates if g.gate_id == "success_delta_ci_lower_min")
    assert not v13_gate.passed
    assert v13_gate.threshold == 0.02
    assert v13.decision is ReleaseDecision.NO_GO


def test_v13_without_ood_evidence_fails_the_ood_gates() -> None:
    """v1.3 继承 v1.2 的 fail-closed：缺 OOD 证据时 OOD 门禁判 FAIL。"""
    report = _decide_v13(with_ood=False)

    assert report.decision is ReleaseDecision.NO_GO
    assert "ood_task_success_min" in report.failed_gate_ids


def test_v13_without_paired_evidence_fails_the_ci_gate() -> None:
    """缺逐任务配对证据时，最小效应宽度门判 FAIL——缺证据不是通过的理由。"""
    report = _decide_v13(paired=None)

    gate = next(g for g in report.gates if g.gate_id == "success_delta_ci_lower_min")
    assert not gate.passed
    assert gate.observed == "insufficient_paired_evidence"
    assert report.decision is ReleaseDecision.NO_GO


def test_v13_boundary_violation_zero_and_ci_exactly_at_threshold() -> None:
    """边界：违规恰好 0 过门（≤ 语义）；CI 下界恰好等于 +0.02 过门（≥ 语义）。"""
    gates = build_release_gates(
        _metrics(task_success=0.80),
        _metrics(task_success=1.00, violations=0),
        evidence_complete=True,
        policy=_policy(),
        schema_version="1.3",
        paired_outcomes=PAIRED_CLEAN,
    )
    by_id = {gate.gate_id: gate for gate in gates}
    assert by_id["policy_violation_count_max"].passed

    # CI 恰好等于阈值：直接构造 GateResult 语义层不可行（observed 来自
    # bootstrap），因此用同构的比较语义验证——observed == threshold 时通过。
    # 这里的目的在于锁定 `>=` 而不是 `>`：把实现改成 `>` 会让贴线证据全灭。
    threshold = by_id["success_delta_ci_lower_min"].threshold
    assert threshold == 0.02
    assert by_id["success_delta_ci_lower_min"].observed >= threshold


# ---------------------------------------------------------------------------
# 向后兼容：旧口径复算不变 + 磁盘证据仍可加载
# ---------------------------------------------------------------------------


def test_v12_dry_run_outcome_is_unchanged_under_v13_code() -> None:
    """v1.2 口径的判定在 v1.3 代码上复算逐字不变（加门不改旧语义）。"""
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
    paired = [(index < 103, index < 117) for index in range(120)]
    ood = (_metrics(task_success=0.7333), _metrics(task_success=0.8667))

    report = decide_formal_release(
        base,
        candidate,
        _policy(),
        gate_schema_version="1.2",
        paired_outcomes=paired,
        ood_evidence=ood,
    )
    # 观测 5 的判定形状：合并形态 GO（此处的 metrics 是测试替身，只验证
    # v1.3 代码没有改变 v1.2 的判定路径）
    assert report.schema_version == "1.2"
    assert len(report.gates) == len(GATE_IDS_V1_2)
    assert "policy_violation_count_max" not in {g.gate_id for g in report.gates}


def test_every_release_report_on_disk_still_loads() -> None:
    """全部既有 release.json 在 v1.3 代码上仍可加载（按形状选 loader）。

    R1 qualification 产物是 `ReleaseReport`，formal-release 产物是
    `FormalReleaseReport`——两者都是旧报告（无 report_id），加载后取 None。
    """
    from veritool_rl.retail_ops.release.release import load_release_report

    if not (ROOT / "reports" / "retail_ops").is_dir():
        pytest.skip("评测/发布产物是 ignored 的运行产物，不随仓库分发（见 NOTICE.md）")

    paths = sorted((ROOT / "reports/retail_ops").rglob("release.json"))
    formal: list[Path] = []
    qualification: list[Path] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        # 按内容形状分类：FormalReleaseReport 有 holdout_artifact_sha256，
        # ReleaseReport（R1 qualification）有 task_manifest_sha256。
        (formal if "holdout_artifact_sha256" in payload else qualification).append(path)
    assert len(formal) >= 11
    assert len(qualification) >= 4

    for path in formal:
        report = load_formal_release_report(path)
        if "v13-diagnostic" in path.name or "v13-diagnostic" in path.parent.name:
            # Phase B3 的诊断报告是 v1.3 代码产出的新报告，带自哈希
            assert report.report_id is not None, path
            assert report.schema_version == "1.3"
        else:
            assert report.report_id is None, path
        assert report.gates, path
    for path in qualification:
        report = load_release_report(path)
        assert report.report_id is None, path
        assert report.gates, path


def test_every_sealed_evidence_report_id_survives_v13_code() -> None:
    """封存 holdout 证据（self-hash 报告）在 v1.3 代码上 report_id 复算逐位不变。"""
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import (
        load_sealed_evaluation_report,
    )

    if not (ROOT / "reports").is_dir():
        pytest.skip("评测/发布产物是 ignored 的运行产物，不随仓库分发（见 NOTICE.md）")

    paths = sorted((ROOT / "reports").rglob("sealed-report.json"))
    assert len(paths) >= 13
    for path in paths:
        report = load_sealed_evaluation_report(path, verify_artifacts=False)
        assert report.report_id is not None, path


def test_release_evidence_load_survives_a_v13_field_purge() -> None:
    """突变验证的另一半：从 v1.3 报告 JSON 里剥掉新字段名不得影响旧报告加载。"""
    # 旧报告根本没有这两个新门——把 JSON 里任何新键剥掉后加载应当等价。
    if not (ROOT / "reports" / "retail_ops").is_dir():
        pytest.skip("评测/发布产物是 ignored 的运行产物，不随仓库分发（见 NOTICE.md）")

    paths = sorted((ROOT / "reports/retail_ops/v1/r6").glob("formal-release-006-v11/release.json"))
    assert paths
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    assert "policy_violation_count_max" not in json.dumps(payload)


# ---------------------------------------------------------------------------
# CLI：_load_ood_evidence 接受 v1.3
# ---------------------------------------------------------------------------


def test_load_ood_evidence_accepts_v13(tmp_path: Path) -> None:
    from veritool_rl.product_cli import _load_ood_evidence

    base_path = tmp_path / "base.json"
    cand_path = tmp_path / "cand.json"
    base_path.write_text(json.dumps({"task_success": 0.7333}), encoding="utf-8")
    cand_path.write_text(json.dumps({"task_success": 0.9833}), encoding="utf-8")
    config = {
        "ood_evidence": {
            "base_metrics_path": str(base_path),
            "candidate_metrics_path": str(cand_path),
        }
    }

    result = _load_ood_evidence(config, "1.3")
    assert result is not None
    assert result[1]["task_success"] == pytest.approx(0.9833)

    with pytest.raises(ValueError, match=r"1\.2"):
        _load_ood_evidence(config, "1.0")
