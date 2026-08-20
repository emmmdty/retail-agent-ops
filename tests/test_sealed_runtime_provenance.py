"""P0（R8 第一轮独立审查 A4）：封存 holdout 路径也必须记录运行时溯源。

`uv_lock_sha256` 哈希的是仓库里的 `uv.lock` **文件**，不是实际装了什么包。
dev 和 OOD 路径在 2026-08-16 已经修过（`BaseRunEvidence.inference_engine` /
`runtime_env_sha256` + `RUNTIME_PROVENANCE_FIELDS` 的 None-排除机制），
但 R8 第一轮 MLOps persona 审查发现：**唯一产生 GO/NO-GO 判定的封存
holdout 路径（`SealedEvaluationReport`）没有这两个字段**——也就是说"用完全
不同的 venv 跑评测，证据仍逐字段声称用的是冻结依赖"这个洞在发布判定
那条路径上仍然开着。

修法与 sealed v1.1 那次同构：**版本感知的内容哈希**——v1.0/v1.1 报告看不到
v1.2 才有的字段，旧证据 `report_id` 复算逐位不变；v1.2 起把这两个字段计入哈希。
**v1.2 触发条件是 `inference_engine` 不为 None**，与 v1.1 用 `merged_from`
触发同构。这强制新报告主动声明它跑在哪个引擎、哪个环境，否则升不上 v1.2。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.helpers_sealed import build_sealed_report
from veritool_rl.retail_ops.evaluate.sealed_evaluation import (
    SEALED_HASHED_FIELDS,
    SealedEvaluationReport,
    sealed_content_id,
)

ROOT = Path(__file__).resolve().parents[1]

_ON_DISK = (
    "reports/retail_ops/v1/r3/holdout-base-001/sealed-report.json",
    "reports/retail_ops/v1/r4/holdout-base-002/sealed-report.json",
    "reports/retail_ops/v1/r4/holdout-candidate-002/sealed-report.json",
    "reports/retail_ops/v1/r45/holdout-merged-003/sealed-report.json",
)


# ---------------------------------------------------------------------------
# 字段存在与互相绑定
# ---------------------------------------------------------------------------


def test_sealed_report_has_runtime_provenance_fields() -> None:
    """封存路径不能比 dev 路径弱：必须能说它跑在哪个引擎、哪个环境。"""
    fields = SealedEvaluationReport.model_fields

    assert "inference_engine" in fields
    assert "runtime_env_sha256" in fields


def test_engine_and_env_must_be_recorded_together_or_both_absent() -> None:
    """半份记录回答不了"跑在哪里"：知道引擎却不知道环境（或反之）是自相矛盾的证据。"""
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import DeploymentForm

    base_kwargs: dict[str, Any] = {
        "schema_version": "1.2",
        "deployment_form": DeploymentForm.BASE,
        "adapter": None,
    }
    with pytest.raises(ValueError, match=r"同时记录或同时缺失"):
        build_sealed_report(
            inference_engine="vllm",
            runtime_env_sha256=None,  # 只声明一半
            **base_kwargs,
        )
    with pytest.raises(ValueError, match=r"同时记录或同时缺失"):
        build_sealed_report(
            inference_engine=None,
            runtime_env_sha256="d" * 64,  # 只声明另一半
            **base_kwargs,
        )


# ---------------------------------------------------------------------------
# 不作废旧证据（这次扩展能做的唯一前提）
# ---------------------------------------------------------------------------


def test_existing_sealed_reports_recompute_bit_identically() -> None:
    """v1.0 / v1.1 报告看不到 v1.2 才有的字段，复算结果必须与它当初落盘时逐位相同。

    做不到就等于把已产出全部封存证据（包括项目历史上唯一的 GO 那份）作废。
    """
    if not (ROOT / "reports" / "retail_ops").is_dir():
        pytest.skip("评测/发布产物是 ignored 的运行产物，不随仓库分发（见 NOTICE.md）")
    checked = 0
    for relative in _ON_DISK:
        path = ROOT / relative
        if not path.is_file():
            continue
        original: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        report = SealedEvaluationReport.model_validate(original)
        # 旧报告加载后两个新字段必须为 None，不能凭空长出值
        assert report.inference_engine is None
        assert report.runtime_env_sha256 is None
        # report_id 复算逐位不变
        assert sealed_content_id(report) == original["report_id"]
        checked += 1
    assert checked >= 1, "本地没有任何 sealed 报告可校验"


def test_synthetic_v1_0_and_v1_1_reports_recompute_bit_identically() -> None:
    """合成的 v1.0 / v1.1 报告也必须复算逐位相同——不依赖磁盘产物。

    R8 第二轮审查 A-2：上面那条测试在 reports 目录不存在时 skip，意味着
    "v1.0/v1.1 旧证据复算逐位不变"这个 A4 修复的**唯一前提**在 CI 等价物
    （干净 clone）上从未被独立验证过。这条用 `helpers_sealed.build_sealed_report`
    构造合成报告，证明 schema 演化的代数性质不依赖任何磁盘产物。
    """
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import DeploymentForm

    # v1.0 合成报告（无 deployment_form、无 inference_engine）
    v1_0 = build_sealed_report(schema_version="1.0")
    assert v1_0.schema_version == "1.0"
    assert v1_0.inference_engine is None
    assert v1_0.runtime_env_sha256 is None
    # 序列化 → 反序列化 → 复算，report_id 必须逐位相同
    # 用 model_validate_json 而不是 model_validate(dict)，因为 StrEnum 在
    # mode="json" dump 后是 str，model_validate(dict) 不自动转回枚举
    import json

    roundtrip = SealedEvaluationReport.model_validate_json(json.dumps(v1_0.model_dump(mode="json")))
    assert sealed_content_id(roundtrip) == v1_0.report_id

    # v1.1 合成报告（有 deployment_form=MERGED、有 merged_from、无 inference_engine）
    v1_1 = build_sealed_report(
        schema_version="1.1",
        deployment_form=DeploymentForm.MERGED,
        adapter=None,
        merged=True,
    )
    assert v1_1.schema_version == "1.1"
    assert v1_1.inference_engine is None
    assert v1_1.runtime_env_sha256 is None
    roundtrip_v1_1 = SealedEvaluationReport.model_validate_json(
        json.dumps(v1_1.model_dump(mode="json"))
    )
    assert sealed_content_id(roundtrip_v1_1) == v1_1.report_id

    # 关键性质：把 v1.2 字段清回 None 不改变 v1.0/v1.1 的复算结果
    # （因为 SEALED_V1_0_FIELDS / SEALED_V1_1_FIELDS 不含这两个字段）
    v1_0_with_none_fields = v1_0.model_copy(
        update={"inference_engine": None, "runtime_env_sha256": None}
    )
    assert sealed_content_id(v1_0_with_none_fields) == v1_0.report_id


# ---------------------------------------------------------------------------
# v1.2 schema：字段集合只追加，不替换
# ---------------------------------------------------------------------------


def test_v1_2_field_set_exists_and_only_grows() -> None:
    """v1.2 必须存在，且字段集合是 v1.1 的真超集——跨版本配对健全性的全部依据。"""
    assert "1.2" in SEALED_HASHED_FIELDS
    assert SEALED_HASHED_FIELDS["1.1"] < SEALED_HASHED_FIELDS["1.2"]
    assert "inference_engine" in SEALED_HASHED_FIELDS["1.2"]
    assert "runtime_env_sha256" in SEALED_HASHED_FIELDS["1.2"]
    # 旧版本的字段集合不含新字段——这是旧证据复算逐位不变的机制
    assert "inference_engine" not in SEALED_HASHED_FIELDS["1.0"]
    assert "inference_engine" not in SEALED_HASHED_FIELDS["1.1"]


def test_v1_2_report_records_runtime_provenance_in_its_hash() -> None:
    """两份只在 inference_engine / runtime_env_sha256 上不同的 v1.2 报告必须有不同 report_id。

    否则这两个字段在哈希中没有约束力——这正是 R8 第一轮审查 A4 的核心：
    "用完全不同的 venv 跑评测，证据仍逐字段声称用的是冻结依赖"。
    """
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import DeploymentForm

    base_kwargs: dict[str, Any] = {
        "schema_version": "1.2",
        "deployment_form": DeploymentForm.BASE,
        "adapter": None,
    }
    r1 = build_sealed_report(
        inference_engine="transformers",
        runtime_env_sha256="a" * 64,
        **base_kwargs,
    )
    r2 = build_sealed_report(
        inference_engine="vllm",
        runtime_env_sha256="b" * 64,
        **base_kwargs,
    )
    assert r1.report_id != r2.report_id


def test_v1_2_pairs_with_v1_2_and_keeps_legacy_pairing_intact() -> None:
    """版本演化不破坏配对：v1.2 与 v1.2 可配对，v1.0 与 v1.1 旧配对语义不变。"""
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import (
        DeploymentForm,
        require_comparable_sealed_runs,
    )

    base_v12 = build_sealed_report(
        schema_version="1.2",
        inference_engine="transformers",
        runtime_env_sha256="a" * 64,
        deployment_form=DeploymentForm.BASE,
        adapter=None,
    )
    candidate_v12 = build_sealed_report(
        schema_version="1.2",
        inference_engine="transformers",
        runtime_env_sha256="a" * 64,
        with_adapter=True,
    )
    require_comparable_sealed_runs(base_v12, candidate_v12)  # 不抛即通过

    # 旧配对语义不变
    base_v10 = build_sealed_report()
    candidate_v10 = build_sealed_report(with_adapter=True)
    require_comparable_sealed_runs(base_v10, candidate_v10)


def test_v1_2_must_declare_runtime_provenance() -> None:
    """v1.2 报告必须显式声明运行时溯源；不声明等于还在自报已修前的状态。

    与 v1.1 必须显式声明 deployment_form 同构：升版本就是承诺新字段的语义。
    """
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import DeploymentForm

    with pytest.raises(ValueError, match=r"v1\.2.*inference_engine.*runtime_env_sha256"):
        build_sealed_report(
            schema_version="1.2",
            deployment_form=DeploymentForm.BASE,
            adapter=None,
            inference_engine=None,  # 显式声明"不要"，触发 v1.2 必须声明的检查
            runtime_env_sha256=None,
        )


def test_v1_0_or_v1_1_must_not_declare_runtime_provenance() -> None:
    """v1.0 / v1.1 报告声明运行时溯源是自相矛盾：那版根本没有这个语义。"""
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import DeploymentForm

    with pytest.raises(ValueError, match=r"v1\.0.*inference_engine"):
        build_sealed_report(
            schema_version="1.0",
            inference_engine="vllm",
            runtime_env_sha256="a" * 64,
        )
    with pytest.raises(ValueError, match=r"v1\.1.*inference_engine"):
        build_sealed_report(
            schema_version="1.1",
            inference_engine="vllm",
            runtime_env_sha256="a" * 64,
            deployment_form=DeploymentForm.MERGED,
            merged=True,
        )
