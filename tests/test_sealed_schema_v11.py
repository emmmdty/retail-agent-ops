"""让"合并部署形态"可以获得发布判定，而不作废任何一份已有 sealed 证据。

第三次观测（LOG-20260815-03）暴露的契约限制：`require_comparable_sealed_runs` 要求
candidate = **同一基座 + adapter**，而合并版没有 adapter、且是不同的 `ModelArtifact`，
两条都不满足——于是一个在 holdout 上 120/120、门禁算术全过的部署形态**结构上拿不到
判定**。该契约在设计时假设"候选永远是 base+adapter"，而部署形态优化天然会打破它。

**这里的难点不是加字段，是加字段而不作废旧证据。** `report_id` 是全字段自哈希
（`_content_id` 只排除 `report_id` 与 `schema_version`），因此任何新字段都会改变旧报告
的复算结果，使它们永久加载失败。解法是**版本感知的内容哈希**：v1.0 报告按 v1.0 的字段
集合复算，v1.1 起才把新字段计入。

**合并候选靠血统而不是同一性配对**：`merged_revision` 必须能从「基座 revision +
adapter 逐文件哈希」**复算出来**，而不是自己声明。这样"这份合并权重确实来自那个基座
和那个 adapter"是可验证的，而不是一句话。
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any

import pytest

from tests.helpers_sealed import build_sealed_report
from veritool_rl.core.agent.qwen import derive_merged_revision
from veritool_rl.retail_ops.evaluate.candidate_evaluation import ComparisonError
from veritool_rl.retail_ops.evaluate.sealed_evaluation import (
    SEALED_V1_0_FIELDS,
    DeploymentForm,
    MergedProvenance,
    SealedEvaluationReport,
    load_sealed_evaluation_report,
    require_comparable_sealed_runs,
)

ROOT = Path(__file__).resolve().parents[1]

_ON_DISK = (
    "reports/retail_ops/v1/r3/holdout-base-001/sealed-report.json",
    "reports/retail_ops/v1/r3/holdout-candidate-001/sealed-report.json",
    "reports/retail_ops/v1/r4/holdout-base-002/sealed-report.json",
    "reports/retail_ops/v1/r4/holdout-candidate-002/sealed-report.json",
    "reports/retail_ops/v1/r45/holdout-base-003/sealed-report.json",
    "reports/retail_ops/v1/r45/holdout-candidate-003/sealed-report.json",
    "reports/retail_ops/v1/r45/holdout-merged-003/sealed-report.json",
)

ADAPTER_HASHES = {"adapter_model.safetensors": "8a49251f" + "0" * 56}


# ---------------------------------------------------------------------------
# 不作废旧证据
# ---------------------------------------------------------------------------


def test_every_sealed_report_on_disk_still_loads_and_verifies() -> None:
    """这条测试是整个版本化路径存在的理由。它红了就说明旧证据被作废了。

    `load_sealed_evaluation_report` 会**重算** report_id 并逐字比对，因此这不只是
    "能反序列化"，而是"自哈希仍然成立"。
    """
    # 产物根整个不存在 = 干净 clone，**跳过并说明**；
    # 根在、却一份都加载不出来 = 真的坏了，仍然红。
    # 这个区分是 2026-08-17 外部审阅第六轮在干净 clone 上撞到 5 red 之后加的：
    # `assert checked >= 1` 拒绝空过是对的，但它把"产物不随仓库分发"也报成了失败。
    if not (ROOT / "reports" / "retail_ops").is_dir():
        pytest.skip("评测/发布产物是 ignored 的运行产物，不随仓库分发（见 NOTICE.md）")
    checked = 0
    for relative in _ON_DISK:
        path = ROOT / relative
        if not path.is_file():
            continue
        report = load_sealed_evaluation_report(path, verify_artifacts=False)
        assert report.schema_version == "1.0"
        assert report.deployment_form is None, "v1.0 报告不得凭空长出新字段的值"
        checked += 1
    assert checked >= 1, "本地没有任何 sealed 报告可校验（产物目录是 ignored 的）"


def test_the_v1_0_field_set_is_frozen() -> None:
    """v1.0 的字段集合就是那七份已产出证据的哈希输入，逐字冻结。"""
    assert "deployment_form" not in SEALED_V1_0_FIELDS
    assert "merged_from" not in SEALED_V1_0_FIELDS
    for expected in ("report_id", "model", "adapter", "metrics", "code_commit"):
        assert expected in SEALED_V1_0_FIELDS


def test_new_fields_do_not_enter_the_v1_0_hash(tmp_path: Path) -> None:
    """把一份 v1.0 报告原样读出再写回，report_id 必须逐字节不变。"""
    source = next((ROOT / rel for rel in _ON_DISK if (ROOT / rel).is_file()), None)
    if source is None:
        pytest.skip("本地没有已产出的 sealed 报告")
    original: dict[str, Any] = json.loads(source.read_text(encoding="utf-8"))

    report = load_sealed_evaluation_report(source, verify_artifacts=False)
    roundtrip = report.model_dump(mode="json")

    assert roundtrip["report_id"] == original["report_id"]
    # 新字段可以出现在序列化结果里，但**不得**改变自哈希。
    assert roundtrip["deployment_form"] is None
    assert roundtrip["merged_from"] is None


# ---------------------------------------------------------------------------
# 合并血统必须可复算
# ---------------------------------------------------------------------------


def test_merged_revision_is_derived_not_declared() -> None:
    """`merged_revision` 由「基座 revision + adapter 逐文件哈希」确定性导出。

    自己声明一个标识等于没有证明；可复算才让"这份权重来自那个基座和那个 adapter"
    成为可验证的事实。
    """
    expected = derive_merged_revision("8cd0101f", ADAPTER_HASHES)

    provenance = MergedProvenance(
        base_repo="Qwen/Qwen3-4B",
        base_revision="8cd0101f",
        adapter_file_sha256=ADAPTER_HASHES,
        merged_revision=expected,
    )

    assert provenance.merged_revision == expected


def test_a_forged_merged_revision_is_rejected() -> None:
    with pytest.raises(ValueError, match="merged_revision"):
        MergedProvenance(
            base_repo="Qwen/Qwen3-4B",
            base_revision="8cd0101f",
            adapter_file_sha256=ADAPTER_HASHES,
            merged_revision="f" * 64,
        )


# ---------------------------------------------------------------------------
# 形态与版本必须互相绑定
# ---------------------------------------------------------------------------


def _report(**overrides: Any) -> SealedEvaluationReport:
    return build_sealed_report(**overrides)


def test_v1_0_must_not_declare_a_deployment_form() -> None:
    with pytest.raises(ValueError, match="deployment_form"):
        _report(schema_version="1.0", deployment_form=DeploymentForm.MERGED)


def test_v1_1_must_declare_a_deployment_form() -> None:
    with pytest.raises(ValueError, match="deployment_form"):
        _report(schema_version="1.1", deployment_form=None)


def test_a_merged_report_must_carry_its_lineage() -> None:
    with pytest.raises(ValueError, match="merged_from"):
        _report(
            schema_version="1.1",
            deployment_form=DeploymentForm.MERGED,
            merged_from=None,
            adapter=None,
        )


def test_a_merged_report_must_not_also_carry_an_adapter() -> None:
    """合并之后模型里已经没有 adapter；同时声明两者是自相矛盾的证据。"""
    with pytest.raises(ValueError, match="不得同时声明 adapter"):
        _report(
            schema_version="1.1",
            deployment_form=DeploymentForm.MERGED,
            merged=True,
            with_adapter=True,
            adapter="unset",
        )


def test_a_base_plus_adapter_report_must_carry_an_adapter() -> None:
    with pytest.raises(ValueError, match="adapter"):
        _report(
            schema_version="1.1",
            deployment_form=DeploymentForm.BASE_PLUS_ADAPTER,
            adapter=None,
        )


# ---------------------------------------------------------------------------
# 配对：base+adapter 走同一性，merged 走血统
# ---------------------------------------------------------------------------


def test_a_merged_candidate_pairs_with_the_base_it_derives_from() -> None:
    """合并候选的 `model` 与 base **必然不同**——它就是另一份权重。

    因此配对靠的是血统：`merged_from` 声明的基座必须就是 base 那一侧的模型，
    且 `merged_revision` 可复算。
    """
    base = _report(schema_version="1.1", deployment_form=DeploymentForm.BASE, adapter=None)
    candidate = _report(
        schema_version="1.1",
        deployment_form=DeploymentForm.MERGED,
        adapter=None,
        merged=True,
    )

    require_comparable_sealed_runs(base, candidate)  # 不抛即通过


def test_a_merged_candidate_from_a_different_base_is_rejected() -> None:
    base = _report(schema_version="1.1", deployment_form=DeploymentForm.BASE, adapter=None)
    candidate = _report(
        schema_version="1.1",
        deployment_form=DeploymentForm.MERGED,
        adapter=None,
        merged=True,
        merged_base_revision="deadbeef",
    )

    with pytest.raises(ComparisonError, match="血统"):
        require_comparable_sealed_runs(base, candidate)


def test_a_merged_candidate_whose_model_revision_is_not_the_derived_id_is_rejected() -> None:
    """模型 pin 的 revision 必须就是那个派生标识，否则报告在描述另一份权重。"""
    base = _report(schema_version="1.1", deployment_form=DeploymentForm.BASE, adapter=None)
    candidate = _report(
        schema_version="1.1",
        deployment_form=DeploymentForm.MERGED,
        adapter=None,
        merged=True,
        model_revision="a" * 64,
    )

    with pytest.raises(ComparisonError, match="派生标识"):
        require_comparable_sealed_runs(base, candidate)


def test_the_legacy_pairing_still_works_and_still_rejects_a_bare_base() -> None:
    """v1.0 的两侧配对语义一个字没改。"""
    base = _report()
    candidate = _report(with_adapter=True)

    require_comparable_sealed_runs(base, candidate)

    with pytest.raises(ComparisonError, match="adapter"):
        require_comparable_sealed_runs(base, base)


def test_base_side_must_be_a_base_form() -> None:
    merged = _report(
        schema_version="1.1", deployment_form=DeploymentForm.MERGED, adapter=None, merged=True
    )

    with pytest.raises(ComparisonError, match="base"):
        require_comparable_sealed_runs(merged, merged)


# ---------------------------------------------------------------------------
# 跨 schema 版本的配对
# ---------------------------------------------------------------------------


def test_hashed_field_sets_only_ever_grow() -> None:
    """**这条是跨版本配对健全性的全部依据。**

    允许 v1.0 的 base 与 v1.1 的候选配对，前提是新版本只**追加**字段、不改变已有
    字段的含义。这条断言把那个前提变成结构性事实：任何一版若删掉或替换字段，
    它立刻失败，跨版本配对随之被禁止。
    """
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import SEALED_HASHED_FIELDS

    ordered = sorted(SEALED_HASHED_FIELDS)
    for older, newer in itertools.pairwise(ordered):
        assert SEALED_HASHED_FIELDS[older] < SEALED_HASHED_FIELDS[newer], (older, newer)


def test_schema_version_is_not_a_pairing_field() -> None:
    """报告格式不是实验条件。

    把它当作配对字段会产生一个更糟的性质：每次 schema 升级都要重跑 base 侧——
    为一次序列化变更烧掉一次封存 holdout 观测。真正保护可比性的那些字段
    （code_commit / uv_lock / 模型 / 生成参数 / 数据集 / receipt / prompt / 工具）
    一个都没少。
    """
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import SEALED_PAIRING_FIELDS

    assert "schema_version" not in SEALED_PAIRING_FIELDS
    for expected in (
        "code_commit",
        "uv_lock_sha256",
        "system_prompt_sha256",
        "tool_schema_sha256",
        "bundle_sha256",
        "holdout_artifact_sha256",
        "seed",
    ):
        assert expected in SEALED_PAIRING_FIELDS


def test_a_v1_0_base_pairs_with_a_v1_1_merged_candidate() -> None:
    """真实场景：基座是在契约扩展之前跑的，候选是扩展之后跑的。"""
    base = _report()  # v1.0，无 adapter → 形态由 adapter 推断为 base
    candidate = _report(
        schema_version="1.1",
        deployment_form=DeploymentForm.MERGED,
        adapter=None,
        merged=True,
    )

    require_comparable_sealed_runs(base, candidate)


def test_an_unknown_schema_version_is_rejected() -> None:
    from veritool_rl.retail_ops.evaluate import sealed_evaluation

    base = _report()
    candidate = _report(with_adapter=True)
    forged = candidate.model_copy(update={"schema_version": "9.9"})

    with pytest.raises(ComparisonError, match="schema_version 未知"):
        sealed_evaluation.require_comparable_sealed_runs(base, forged)
