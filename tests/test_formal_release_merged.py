"""发布判定与服务入口对"合并部署形态候选"的支持。

契约扩展的最后一段：sealed 报告已经能表达 merged 形态（`test_sealed_schema_v11.py`），
但如果 `FormalReleaseReport` 仍然强制要求 adapter、`serve` 仍然只会加载
"基座 + adapter"，那个判定就落不了地——**GO 之后没有东西可以部署**。

两条不可退让的性质在这里被锁住：

1. **旧 release 报告仍然可加载**（`formal-release-001/002/003` 与 R1 qualification）。
2. **SPEC §4「没有通过发布门禁的模型不得被服务入口加载」对 merged 同样成立**，
   而且回滚时加载的必须是**基座**、不是合并权重。
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
    load_formal_release_report,
)
from veritool_rl.retail_ops.release.release import ReleaseDecision

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = ROOT / "domains/retail_ops/v1"

_ON_DISK_RELEASES = (
    "reports/retail_ops/v1/r3/formal-release-001/release.json",
    "reports/retail_ops/v1/r4/formal-release-002/release.json",
    "reports/retail_ops/v1/r45/formal-release-003-v10/release.json",
    "reports/retail_ops/v1/r45/formal-release-003-v11/release.json",
)


def _metrics(success: float, latency: float, calls: float) -> dict[str, Any]:
    return {
        "task_success": success,
        "policy_violation_count": 0,
        "invalid_call_count": 0,
        "p95_latency_ms": latency,
        "average_latency_ms": latency * 0.8,
        "average_tool_calls": calls,
    }


#: 与 `_metrics` 里的 0.80 / 1.00 精确一致的逐任务配对结局。v1.1 的
#: `success_delta_ci_lower` 会核对"配对证据与聚合指标是否自洽"，对不上直接报错。
PAIRED = [(index < 96, True) for index in range(120)]


def _pair(*, merged: bool, candidate_latency: float = 1000.0) -> tuple[Any, Any]:
    base = build_sealed_report(
        schema_version="1.1",
        deployment_form=DeploymentForm.BASE,
        adapter=None,
        metrics=_metrics(0.80, 1000.0, 1.0),
    )
    candidate = build_sealed_report(
        schema_version="1.1",
        deployment_form=DeploymentForm.MERGED if merged else DeploymentForm.BASE_PLUS_ADAPTER,
        merged=merged,
        adapter=None if merged else "unset",
        with_adapter=not merged,
        metrics=_metrics(1.00, candidate_latency, 1.0),
    )
    return base, candidate


def test_old_release_reports_still_load() -> None:
    """契约扩展不得让任何一份已产出的发布判定失效。"""
    checked = 0
    for relative in _ON_DISK_RELEASES:
        path = ROOT / relative
        if not path.is_file():
            continue
        report = load_formal_release_report(path)
        assert report.adapter is not None, "旧报告都是 base+adapter 形态"
        assert report.deployment_form is None
        assert report.candidate_model is None
        checked += 1
    assert checked >= 1


def test_a_merged_candidate_can_now_receive_a_decision() -> None:
    """这就是整条扩展的目的：合并形态终于能拿到判定，而不是只能算诊断算术。"""
    base, candidate = _pair(merged=True)
    policy = load_bundle(BUNDLE_DIR).release

    report = decide_formal_release(
        base, candidate, policy, gate_schema_version="1.1", paired_outcomes=PAIRED
    )

    assert report.decision is ReleaseDecision.GO
    assert report.deployment == "candidate"
    assert report.deployment_form is DeploymentForm.MERGED
    assert report.adapter is None, "合并后已经没有 adapter"
    assert report.candidate_model is not None
    assert report.candidate_model.revision == candidate.merged_from.merged_revision
    # 基座那一侧仍然被记录下来——回滚要用它。
    assert report.model == base.model


def test_a_merged_candidate_that_fails_a_gate_still_rolls_back_to_base() -> None:
    base, candidate = _pair(merged=True, candidate_latency=9000.0)
    policy = load_bundle(BUNDLE_DIR).release

    report = decide_formal_release(
        base, candidate, policy, gate_schema_version="1.1", paired_outcomes=PAIRED
    )

    assert report.decision is ReleaseDecision.NO_GO
    assert report.deployment == "baseline"


def test_the_legacy_adapter_path_is_unchanged() -> None:
    base, candidate = _pair(merged=False)
    policy = load_bundle(BUNDLE_DIR).release

    report = decide_formal_release(
        base, candidate, policy, gate_schema_version="1.1", paired_outcomes=PAIRED
    )

    assert report.adapter is not None
    assert report.candidate_model is None
    assert report.deployment_form is DeploymentForm.BASE_PLUS_ADAPTER


def test_a_merged_release_report_must_not_claim_an_adapter(tmp_path: Path) -> None:
    """报告字段之间必须自洽，否则 `serve` 会按一个不存在的组合去加载。"""
    from veritool_rl.retail_ops.release.formal_release import write_formal_release_report

    base, candidate = _pair(merged=True)
    policy = load_bundle(BUNDLE_DIR).release
    report = decide_formal_release(
        base, candidate, policy, gate_schema_version="1.1", paired_outcomes=PAIRED
    )
    write_formal_release_report(report, tmp_path / "release")

    payload = json.loads((tmp_path / "release" / "release.json").read_text(encoding="utf-8"))
    payload["adapter"] = {
        "run_dir": "reports/retail_ops/v1/r4/sft-006",
        "file_sha256": {"adapter_model.safetensors": "1" * 64},
    }
    (tmp_path / "release" / "release.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="adapter"):
        load_formal_release_report(tmp_path / "release" / "release.json")


# ---------------------------------------------------------------------------
# serve：GO 时加载合并权重，NO-GO 时回滚到基座
# ---------------------------------------------------------------------------


def test_serving_a_merged_go_loads_the_merged_weights(tmp_path: Path) -> None:
    seen = _serve_and_capture(tmp_path, merged=True, go=True)

    assert len(seen) == 1
    model, adapter = seen[0]
    assert adapter is None, "合并形态不得再挂 adapter"
    assert model.local_dir == "Qwen3-4B-sft-006-merged"


def test_serving_a_merged_no_go_rolls_back_to_the_base_weights(tmp_path: Path) -> None:
    """回滚必须回到**基座**，不是合并权重——后者恰恰是被拒绝的那个东西。"""
    seen = _serve_and_capture(tmp_path, merged=True, go=False)

    model, adapter = seen[0]
    assert adapter is None
    assert model.local_dir == "Qwen3-4B-pinned"


def test_a_backend_that_loads_the_wrong_model_is_rejected(tmp_path: Path) -> None:
    """只核对"有没有挂 adapter"不够：合并形态下两侧都没有 adapter，
    真正的区别在**加载了哪份权重**。工厂是注入缝，必须核对它返回了什么。"""
    with pytest.raises(ValueError, match="模型"):
        _serve_and_capture(tmp_path, merged=True, go=True, rogue_model="Qwen3-4B-pinned")


def _serve_and_capture(
    tmp_path: Path,
    *,
    merged: bool,
    go: bool,
    rogue_model: str | None = None,
) -> list[tuple[Any, Any]]:
    import shutil

    from veritool_rl.core.agent.qwen import GeneratedText
    from veritool_rl.retail_ops.build.manifests import build_qualification
    from veritool_rl.retail_ops.release.formal_release import write_formal_release_report
    from veritool_rl.retail_ops.serve.service import create_formal_app

    bundle_rel = Path("domains/retail_ops/v1")
    shutil.copytree(ROOT / bundle_rel, tmp_path / bundle_rel)
    build_qualification(tmp_path / bundle_rel, 0, tmp_path / "build")

    base, candidate = _pair(merged=merged, candidate_latency=1000.0 if go else 9000.0)
    policy = load_bundle(tmp_path / bundle_rel).release
    bundle_sha = load_bundle(tmp_path / bundle_rel).bundle_sha256
    base = base.model_copy(update={"bundle_sha256": bundle_sha})
    candidate = candidate.model_copy(update={"bundle_sha256": base.bundle_sha256})
    report = decide_formal_release(
        base, candidate, policy, gate_schema_version="1.1", paired_outcomes=PAIRED
    )
    release_dir = tmp_path / "release"
    write_formal_release_report(report, release_dir)

    seen: list[tuple[Any, Any]] = []

    class _Backend:
        def __init__(self, model_dir: str) -> None:
            self.model_dir = model_dir
            self.adapter_path: str | None = None

        def generate(self, messages: Any, tools: Any, max_new_tokens: int) -> GeneratedText:
            del messages, tools, max_new_tokens
            return GeneratedText(text="ok", input_tokens=1, output_tokens=1)

    def factory(model: Any, adapter: Any) -> _Backend:
        seen.append((model, adapter))
        local_dir = rogue_model or model.local_dir
        return _Backend(model_dir=f"models/{local_dir}")

    create_formal_app(
        release_dir,
        tmp_path / bundle_rel,
        tmp_path / "build",
        backend_factory=factory,
        api_key="k",
    )
    return seen
