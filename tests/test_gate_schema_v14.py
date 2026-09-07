"""gate schema v1.4（I-2b）与发布配置治理（B-3）。

## v1.4 是什么

D4 证明 v1.3 的十二道门能拦下「该拒绝却执行」（LOG-20260905-03），但配对语义
仍有一个洞：两份 sealed 报告即便分别跑在 transformers 与 vLLM 上（同一份权重、
不同推理引擎/运行时环境），只要旧字段全部相同就能配对——引擎差异会被当成
模型效果算进 delta。I-2b 的修法**不是**改既有配对语义，而是照 `GATE_IDS`
v1.2→v1.3 的模式新增版本化集合：`SEALED_PAIRING_FIELDS_V1_4` 把
`inference_engine` / `runtime_env_sha256` 纳入配对，v1.0–v1.3 逐字节不动；
启用时机由发布配置声明 `gate_schema_version: "1.4"`（是否在 A-7 启用
由用户单独确认，不捆绑）。

## B-3 治理规则

新发布配置的 `gate_schema_version` 必须等于代码里的最新版本——历史配置
（判定已完成）逐字节保留，白名单是封闭的：出现新配置而不声明最新版本时，
治理测试变红。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers_sealed import build_sealed_report

REPO_ROOT = Path(__file__).resolve().parents[1]

#: v1.3 及更早的配对字段——**逐字节冻结**。任何漂移都等于宣布历史证据失效。
_LEGACY_PAIRING_FIELDS = (
    "purpose",
    "split",
    "dataset_version",
    "generator_id",
    "bundle_id",
    "bundle_version",
    "bundle_sha256",
    "parser_id",
    "evaluator_id",
    "seed",
    "max_steps",
    "task_count",
    "category_counts",
    "holdout_artifact_sha256",
    "holdout_receipt_sha256",
    "system_prompt_sha256",
    "tool_schema_sha256",
    "code_commit",
    "uv_lock_sha256",
)


# ---------------------------------------------------------------------------
# v1.4 配对字段集合
# ---------------------------------------------------------------------------


def test_v13_and_older_pairing_fields_stay_byte_identical() -> None:
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import SEALED_PAIRING_FIELDS

    assert SEALED_PAIRING_FIELDS == _LEGACY_PAIRING_FIELDS


def test_v14_pairing_fields_only_extend_the_legacy_set() -> None:
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import (
        SEALED_PAIRING_FIELDS,
        SEALED_PAIRING_FIELDS_V1_4,
    )

    assert (
        *_LEGACY_PAIRING_FIELDS,
        "inference_engine",
        "runtime_env_sha256",
    ) == SEALED_PAIRING_FIELDS_V1_4
    assert set(SEALED_PAIRING_FIELDS) < set(SEALED_PAIRING_FIELDS_V1_4)


def test_pairing_field_selection_follows_the_release_schema_version() -> None:
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import (
        SEALED_PAIRING_FIELDS,
        SEALED_PAIRING_FIELDS_V1_4,
        pairing_fields_for_release_schema,
    )

    for version in ("1.0", "1.1", "1.2", "1.3"):
        assert pairing_fields_for_release_schema(version) is SEALED_PAIRING_FIELDS
    assert pairing_fields_for_release_schema("1.4") is SEALED_PAIRING_FIELDS_V1_4
    with pytest.raises(ValueError, match="gate_schema_version"):
        pairing_fields_for_release_schema("9.9")


# ---------------------------------------------------------------------------
# v1.4 配对在真实比较路径上生效
# ---------------------------------------------------------------------------


def _paired_reports(engine: str, runtime_env: str) -> tuple[object, object]:
    base = build_sealed_report(
        schema_version="1.2",
        with_adapter=False,
        inference_engine=engine,
        runtime_env_sha256=runtime_env,
    )
    candidate = build_sealed_report(
        schema_version="1.2",
        merged=True,
        inference_engine=engine,
        runtime_env_sha256=runtime_env,
    )
    return base, candidate


def test_v13_pairing_still_ignores_the_engine_and_runtime_env() -> None:
    """历史口径逐字节保留：v1.3（默认）下引擎/运行时不同不拦——那是 v1.3 的真实语义。"""
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import require_comparable_sealed_runs

    base, _ = _paired_reports("transformers", "a" * 64)
    vllm_candidate = build_sealed_report(
        schema_version="1.2",
        merged=True,
        inference_engine="vllm",
        runtime_env_sha256="a" * 64,
    )

    require_comparable_sealed_runs(base, vllm_candidate)
    require_comparable_sealed_runs(base, vllm_candidate, gate_schema_version="1.3")


def test_v14_pairing_rejects_engine_mismatch() -> None:
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import (
        ComparisonError,
        require_comparable_sealed_runs,
    )

    base, _ = _paired_reports("transformers", "a" * 64)
    vllm_candidate = build_sealed_report(
        schema_version="1.2",
        merged=True,
        inference_engine="vllm",
        runtime_env_sha256="a" * 64,
    )

    with pytest.raises(ComparisonError, match="inference_engine"):
        require_comparable_sealed_runs(base, vllm_candidate, gate_schema_version="1.4")


def test_v14_pairing_rejects_runtime_env_mismatch() -> None:
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import (
        ComparisonError,
        require_comparable_sealed_runs,
    )

    base, _ = _paired_reports("transformers", "a" * 64)
    other_env = build_sealed_report(
        schema_version="1.2",
        merged=True,
        inference_engine="transformers",
        runtime_env_sha256="b" * 64,
    )

    with pytest.raises(ComparisonError, match="runtime_env_sha256"):
        require_comparable_sealed_runs(base, other_env, gate_schema_version="1.4")


def test_v14_pairing_accepts_identical_runtime_provenance() -> None:
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import require_comparable_sealed_runs

    base, candidate = _paired_reports("transformers", "a" * 64)

    require_comparable_sealed_runs(base, candidate, gate_schema_version="1.4")


# ---------------------------------------------------------------------------
# v1.4 的门禁集合与阈值不变
# ---------------------------------------------------------------------------


def test_v14_gate_ids_are_the_v13_gate_ids() -> None:
    from veritool_rl.retail_ops.release.release import (
        GATE_IDS_BY_SCHEMA,
        GATE_IDS_V1_3,
        GATE_IDS_V1_4,
    )

    assert GATE_IDS_V1_4 == GATE_IDS_V1_3
    assert GATE_IDS_BY_SCHEMA["1.4"] == GATE_IDS_V1_4


def test_build_release_gates_accepts_v14_and_matches_v13_shape() -> None:
    from veritool_rl.retail_ops.domain.bundle import ReleasePolicyConfig
    from veritool_rl.retail_ops.release.release import GATE_IDS_V1_3, build_release_gates

    policy = ReleasePolicyConfig(
        success_delta_min=0.05,
        critical_policy_violation_delta_max=0,
        p95_latency_ratio_max=1.25,
    )
    metrics = {
        "task_success": 117 / 120,
        "policy_violation_count": 0,
        "invalid_call_count": 0,
        "p95_latency_ms": 1.4,
        "average_latency_ms": 1.2,
        "average_tool_calls": 2.0,
    }
    base_metrics = {
        "task_success": 103 / 120,
        "policy_violation_count": 11,
        "invalid_call_count": 0,
        "p95_latency_ms": 1.3,
        "average_latency_ms": 1.1,
        "average_tool_calls": 2.0,
    }

    paired_outcomes = [(True, True)] * 103 + [(False, True)] * 14 + [(False, False)] * 3

    v14 = build_release_gates(
        base_metrics,
        metrics,
        evidence_complete=True,
        policy=policy,
        schema_version="1.4",
        paired_outcomes=paired_outcomes,
    )
    v13 = build_release_gates(
        base_metrics,
        metrics,
        evidence_complete=True,
        policy=policy,
        schema_version="1.3",
        paired_outcomes=paired_outcomes,
    )

    assert tuple(gate.gate_id for gate in v14) == GATE_IDS_V1_3
    assert [gate.gate_id for gate in v14] == [gate.gate_id for gate in v13]


# ---------------------------------------------------------------------------
# B-3：发布配置治理
# ---------------------------------------------------------------------------


def test_release_configs_declare_versions_consistently() -> None:
    """新发布配置的 gate_schema_version 必须等于最新版本；历史配置封闭白名单。"""
    import yaml

    from veritool_rl.retail_ops.release.release import GATE_IDS_BY_SCHEMA

    release_dir = REPO_ROOT / "configs/retail_ops/release"
    configs = sorted(release_dir.glob("*.yaml"))

    #: 已完成判定的历史配置——每个都是台账里有记录的一次性判定（或早于
    #: gate schema 系统存在的 R1 配置），历史不得改写。**只减不增**：
    #: 新配置不得加进来。
    historical = {
        "retail_ops_v1_release.yaml",
        "retail_ops_v1_r3_formal_release.yaml",
        "retail_ops_v1_r4_formal_release.yaml",
        "retail_ops_v1_r45_formal_release_v11.yaml",
        "retail_ops_v1_d4_formal_release_v13.yaml",
        # B-4/v5 一次性判定（观测 8）：A-0 用户裁定沿用 1.3（不启用 1.4），
        # 判定已完成（LOG-20260907-01，NO-GO 11/12）——与 D4 v13 同一先例。
        "retail_ops_v5_formal_release_v13.yaml",
    }
    latest = max(GATE_IDS_BY_SCHEMA, key=lambda v: tuple(int(p) for p in v.split(".")))

    declared: set[str] = set()
    for path in configs:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        version = config.get("gate_schema_version")
        if version is not None:
            assert version in GATE_IDS_BY_SCHEMA, f"{path.name}: 未知 gate_schema_version"
        declared.add(path.name)
        if path.name in historical:
            continue
        assert version == latest, (
            f"{path.name}: gate_schema_version={version!r} 不是最新版本 {latest!r}——"
            f"新发布配置必须声明最新 gate schema"
        )
    assert declared == historical, (
        "release 配置集合与治理白名单不一致——新配置必须过本测试的治理规则"
    )
