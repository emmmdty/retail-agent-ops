"""P1-4 / P1-5 / §6.3：发布门禁语义的**版本化**升级。

三条诚信约束（先于任何新读数写下）：

1. 新口径在看到任何新读数**之前**定稿并提交。本文件里的门禁定义与阈值来源不依赖
   任何一次已有观测的数值。
2. 旧口径下的两次 NO-GO 结论保留，不删除、不改写。v1.0 的门禁集合与判定逻辑
   逐字节不变，磁盘上已有的全部 release 报告仍必须能被加载。
3. 阈值本身一个字不改。v1.1 的新门禁只能复用 `release.yaml` 已有的五个阈值，或使用
   schema 语义自带的结构性常量（CI 下界 ≥ 0）——因为 `release.yaml` 也在
   `bundle_sha256` 的分量里，改它会使全部已有 dev/sealed 证据不可配对。

拆分的动机（P1-4）：episode 级 p95 把"能力提升"和"速度下降"混进同一个数。
base 的典型失败是"查完就说"（1 步），正确执行的候选要 2 步——**做对事的候选必然更慢**。
v1.1 把它拆成三个各自回答一个问题的量：单次调用有多快（部署速度）、每成功一条任务
要几次调用（规划效率）、每成功一条任务花多少端到端时间（归一化成本）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from veritool_rl.retail_ops.domain.bundle import ReleasePolicyConfig, load_bundle
from veritool_rl.retail_ops.release.release import (
    GATE_IDS,
    GATE_IDS_BY_SCHEMA,
    GATE_IDS_V1_1,
    build_release_gates,
)

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = ROOT / "domains/retail_ops/v1"


def _policy() -> ReleasePolicyConfig:
    return load_bundle(BUNDLE_DIR).release


def _metrics(
    *,
    task_success: float,
    latency: float,
    tool_calls: float,
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


def _gates(
    base: dict[str, Any],
    candidate: dict[str, Any],
    *,
    paired_outcomes: list[tuple[bool, bool]] | None = None,
) -> dict[str, Any]:
    results = build_release_gates(
        base,
        candidate,
        evidence_complete=True,
        policy=_policy(),
        schema_version="1.1",
        paired_outcomes=paired_outcomes,
    )
    return {gate.gate_id: gate for gate in results}


# ---------------------------------------------------------------------------
# 版本化本身
# ---------------------------------------------------------------------------


def test_v10_gate_set_is_untouched() -> None:
    """v1.0 是磁盘上全部已有 release 报告的契约，一个字都不能动。"""
    assert GATE_IDS == (
        "success_delta",
        "policy_violation_delta",
        "invalid_call_count",
        "p95_latency_ratio",
        "evidence_complete",
    )
    assert GATE_IDS_BY_SCHEMA["1.0"] == GATE_IDS
    assert GATE_IDS_BY_SCHEMA["1.1"] == GATE_IDS_V1_1
    assert set(GATE_IDS_BY_SCHEMA) == {"1.0", "1.1"}


def test_v11_splits_the_latency_gate_and_adds_a_paired_test() -> None:
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
    # 拆分后 episode 级 p95 不再是门禁项；三个继任者各自有明确语义。
    assert "p95_latency_ratio" not in GATE_IDS_V1_1


def test_thresholds_come_from_the_untouched_release_yaml() -> None:
    """v1.1 不得引入新阈值：`release.yaml` 在 `bundle_sha256` 的分量里。"""
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
    assert raw["success_delta_min"] == 0.05
    assert raw["p95_latency_ratio_max"] == 1.25

    gates = _gates(
        _metrics(task_success=0.5, latency=1000.0, tool_calls=1.0),
        _metrics(task_success=0.6, latency=1000.0, tool_calls=1.0),
    )
    for gate_id in (
        "per_call_latency_ratio",
        "steps_to_success_ratio",
        "latency_per_success_ratio",
    ):
        assert gates[gate_id].threshold == 1.25
    assert gates["success_delta"].threshold == 0.05
    assert gates["success_delta_ci_lower"].threshold == 0.0


# ---------------------------------------------------------------------------
# P1-4：延迟拆分
# ---------------------------------------------------------------------------


def test_per_call_latency_isolates_deployment_speed_from_doing_more_work() -> None:
    """候选每次调用一样快、只是多做了一步——部署速度门禁必须通过。

    这正是旧口径惩罚"正确地多做一步"的那个场景。
    """
    base = _metrics(task_success=0.5, latency=1000.0, tool_calls=1.0)
    candidate = _metrics(task_success=1.0, latency=2000.0, tool_calls=2.0)

    gates = _gates(base, candidate)

    assert gates["per_call_latency_ratio"].observed == pytest.approx(1.0)
    assert gates["per_call_latency_ratio"].passed


def test_per_call_latency_catches_a_genuinely_slower_forward_pass() -> None:
    """调用次数不变而单次变慢，就是纯部署开销，必须被拦下。"""
    base = _metrics(task_success=0.5, latency=1000.0, tool_calls=1.0)
    candidate = _metrics(task_success=0.5, latency=2000.0, tool_calls=1.0)

    gates = _gates(base, candidate)

    assert gates["per_call_latency_ratio"].observed == pytest.approx(2.0)
    assert not gates["per_call_latency_ratio"].passed


def test_steps_to_success_normalises_planning_effort_by_success() -> None:
    """多做一步但成功率翻倍 → 每成功一条任务的调用数不变 → 规划效率没有劣化。"""
    base = _metrics(task_success=0.5, latency=1000.0, tool_calls=1.0)
    candidate = _metrics(task_success=1.0, latency=2000.0, tool_calls=2.0)

    gates = _gates(base, candidate)

    assert gates["steps_to_success_ratio"].observed == pytest.approx(1.0)
    assert gates["steps_to_success_ratio"].passed
    assert gates["latency_per_success_ratio"].observed == pytest.approx(1.0)
    assert gates["latency_per_success_ratio"].passed


def test_the_latency_reason_records_the_early_termination_bias() -> None:
    """`reason` 是给人读的字段，"失败任务提前终止反而更快"必须写在那里。"""
    gates = _gates(
        _metrics(task_success=0.5, latency=1000.0, tool_calls=1.0),
        _metrics(task_success=1.0, latency=2000.0, tool_calls=2.0),
    )

    assert "提前终止" in gates["per_call_latency_ratio"].reason
    assert "归一化" in gates["latency_per_success_ratio"].reason


def test_undefined_ratios_fail_closed() -> None:
    """分母为零时判 FAIL，而不是给一个看起来能用的数。"""
    gates = _gates(
        _metrics(task_success=0.0, latency=1000.0, tool_calls=1.0),
        _metrics(task_success=0.0, latency=1000.0, tool_calls=1.0),
    )

    assert gates["steps_to_success_ratio"].observed == "undefined_no_success"
    assert not gates["steps_to_success_ratio"].passed
    assert not gates["latency_per_success_ratio"].passed


# ---------------------------------------------------------------------------
# P1-5：配对统计检验
# ---------------------------------------------------------------------------


def test_paired_ci_gate_fails_when_there_is_no_paired_evidence() -> None:
    """公开 sealed 报告只有聚合量，拿不到逐任务配对结局时必须判 FAIL。

    保守方向与"不因缺证据放宽门禁"一致：缺证据不是通过的理由。
    """
    gates = _gates(
        _metrics(task_success=0.5, latency=1000.0, tool_calls=1.0),
        _metrics(task_success=1.0, latency=1000.0, tool_calls=1.0),
    )

    assert gates["success_delta_ci_lower"].observed == "insufficient_paired_evidence"
    assert not gates["success_delta_ci_lower"].passed


def test_paired_ci_gate_passes_on_a_uniform_improvement() -> None:
    paired = [(False, True)] * 40
    gates = _gates(
        _metrics(task_success=0.0, latency=1000.0, tool_calls=1.0),
        _metrics(task_success=1.0, latency=1000.0, tool_calls=1.0),
        paired_outcomes=paired,
    )

    assert gates["success_delta_ci_lower"].observed == pytest.approx(1.0)
    assert gates["success_delta_ci_lower"].passed


def test_paired_ci_gate_rejects_a_point_estimate_inside_the_noise_band() -> None:
    """点估计为正、但配对 CI 下界跨 0 —— 正是 n=120 时 ±7.5pp 噪声带的情形。"""
    paired = [(False, True)] * 7 + [(True, False)] * 5 + [(True, True)] * 28
    gates = _gates(
        _metrics(task_success=33 / 40, latency=1000.0, tool_calls=1.0),
        _metrics(task_success=35 / 40, latency=1000.0, tool_calls=1.0),
        paired_outcomes=paired,
    )

    assert isinstance(gates["success_delta_ci_lower"].observed, float)
    assert gates["success_delta_ci_lower"].observed < 0.0
    assert not gates["success_delta_ci_lower"].passed
    # 点估计仍然保留展示，两者是不同的问题。
    assert gates["success_delta"].observed == pytest.approx(0.05)


def test_paired_bootstrap_is_deterministic() -> None:
    """门禁必须可复现：同一份配对证据两次调用给出逐位相同的下界。"""
    paired = [(False, True)] * 9 + [(True, False)] * 4 + [(True, True)] * 27
    base = _metrics(task_success=31 / 40, latency=1000.0, tool_calls=1.0)
    candidate = _metrics(task_success=36 / 40, latency=1000.0, tool_calls=1.0)

    first = _gates(base, candidate, paired_outcomes=paired)["success_delta_ci_lower"].observed
    second = _gates(base, candidate, paired_outcomes=paired)["success_delta_ci_lower"].observed

    assert first == second


def test_paired_outcomes_must_match_the_reported_deltas() -> None:
    """配对证据与聚合指标对不上时直接拒绝，而不是各算各的。"""
    with pytest.raises(ValueError, match="配对"):
        _gates(
            _metrics(task_success=0.5, latency=1000.0, tool_calls=1.0),
            _metrics(task_success=1.0, latency=1000.0, tool_calls=1.0),
            paired_outcomes=[(False, False)] * 4,
        )


# ---------------------------------------------------------------------------
# §6.3：旧报告必须仍然可加载
# ---------------------------------------------------------------------------

_ON_DISK_REPORTS = (
    "reports/retail_ops/v1/qualification-r1-final/release-go/release.json",
    "reports/retail_ops/v1/qualification-r1-final/release-no-go/release.json",
    "reports/retail_ops/v1/qualification-r1-repeat/release-go/release.json",
    "reports/retail_ops/v1/qualification-r1-repeat/release-no-go/release.json",
)
_ON_DISK_FORMAL_REPORTS = (
    "reports/retail_ops/v1/r3/formal-release-001/release.json",
    "reports/retail_ops/v1/r4/formal-release-002/release.json",
)


def test_existing_v10_reports_on_disk_still_load() -> None:
    """就地增删 `GATE_IDS` 会让磁盘上全部已有 release 报告无法加载。

    这条测试是版本化路径存在的唯一理由；它红了就说明旧证据被作废了。
    """
    from veritool_rl.retail_ops.release.formal_release import load_formal_release_report
    from veritool_rl.retail_ops.release.release import load_release_report

    checked = 0
    for relative in _ON_DISK_REPORTS:
        path = ROOT / relative
        if not path.is_file():
            continue
        report = load_release_report(path)
        assert report.schema_version == "1.0"
        assert tuple(gate.gate_id for gate in report.gates) == GATE_IDS
        checked += 1
    for relative in _ON_DISK_FORMAL_REPORTS:
        path = ROOT / relative
        if not path.is_file():
            continue
        report_formal = load_formal_release_report(path)
        assert report_formal.schema_version == "1.0"
        assert tuple(gate.gate_id for gate in report_formal.gates) == GATE_IDS
        checked += 1
    assert checked >= 1, "本地没有任何已产出的 release 报告可校验（产物目录是 ignored 的）"


def test_a_v11_report_rejects_the_v10_gate_set() -> None:
    """版本与门禁集合必须互相绑定，否则版本号只是装饰。"""
    from veritool_rl.retail_ops.release.release import (
        GateResult,
        ReleaseDecision,
        ReleaseReport,
    )

    gates = [
        GateResult(gate_id=gate_id, passed=True, observed=0, threshold=0, reason="x")
        for gate_id in GATE_IDS
    ]
    with pytest.raises(ValueError, match="冻结契约"):
        ReleaseReport(
            schema_version="1.1",
            decision=ReleaseDecision.GO,
            baseline_run_id="a" * 64,
            candidate_run_id="b" * 64,
            baseline_policy="baseline",
            candidate_policy="oracle",
            bundle_sha256="c" * 64,
            task_manifest_sha256="d" * 64,
            deployment="candidate",
            gates=gates,
            failed_gate_ids=[],
            baseline_metrics={},
            candidate_metrics={},
        )


def test_v10_decisions_recorded_on_disk_are_not_rewritten() -> None:
    """两次 NO-GO 的原始判定必须原样留在磁盘上。"""
    for relative, expected in (
        ("reports/retail_ops/v1/r3/formal-release-001/release.json", ["success_delta"]),
        ("reports/retail_ops/v1/r4/formal-release-002/release.json", ["p95_latency_ratio"]),
    ):
        path = ROOT / relative
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["decision"] == "NO-GO"
        assert payload["failed_gate_ids"] == expected
