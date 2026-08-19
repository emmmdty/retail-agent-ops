"""R6 配置的单变量契约。

本轮全部结论的形式都是「换了 X，读数从 A 变成 B」。只要配置里悄悄多改了一样东西，
这些结论就全部退化成「换了一堆东西，读数变了」。所以每一对配置的差异集合都被逐字段钉死。
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD = REPO_ROOT / "configs" / "retail_ops" / "build"
EVAL = REPO_ROOT / "configs" / "retail_ops" / "evaluate"


def _load(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _diff(left: dict[str, Any], right: dict[str, Any]) -> set[str]:
    assert set(left) == set(right), f"键集合不同：{set(left) ^ set(right)}"
    return {key for key in left if left[key] != right[key]}


# --- 训练数据导出 -------------------------------------------------------------


def test_r6_export_changes_exactly_one_variable() -> None:
    """train-export-006 相对 004 只多了 sft_paraphrase。"""
    baseline = _load(BUILD / "retail_ops_v1_r4_round2_c_train_export.yaml")
    r6 = _load(BUILD / "retail_ops_v1_r6_train_export_paraphrase.yaml")
    assert _diff(baseline, r6) == {"attempt_id", "sft_paraphrase"}
    assert baseline["sft_paraphrase"] is None
    assert set(r6["sft_paraphrase"]) == {"bank_relpath", "bank_sha256", "per_task"}


def test_r6_export_uses_only_the_training_partition() -> None:
    """训练增强只能取 train_aug——配置里没有分片键，是因为加载器把它写死了。"""
    from veritool_rl.retail_ops.build.phrasing_bank import ParaphrasePlan

    assert ParaphrasePlan(index={}, per_task=1, bank_sha256="0" * 64).partition == "train_aug"


def test_r6b_export_changes_exactly_one_variable() -> None:
    """train-export-007 相对 006 只去掉了 sft_oversample。"""
    r6 = _load(BUILD / "retail_ops_v1_r6_train_export_paraphrase.yaml")
    r6b = _load(BUILD / "retail_ops_v1_r6b_train_export_no_oversample.yaml")
    assert _diff(r6, r6b) == {"attempt_id", "sft_oversample"}
    assert r6["sft_oversample"] == {"refund_eligible": 3, "refund_recovery": 3}
    assert r6b["sft_oversample"] == {}


def test_the_no_oversample_hypothesis_was_written_before_the_reading() -> None:
    """假设必须写在配置里，且写明三种判读——否则「事后解释」与「事先预测」无法区分。"""
    text = (BUILD / "retail_ops_v1_r6b_train_export_no_oversample.yaml").read_text(encoding="utf-8")
    assert "在看到 sft-008 任何读数之前写定" in text
    assert "假设被证伪" in text
    assert "同时出现在文档里" in text


# --- SFT 超参 -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("candidate", "expected_relpath"),
    [
        ("retail_ops_v1_r6_paraphrase_sft.yaml", "train-export/train-export-006/sft.jsonl"),
        ("retail_ops_v1_r6b_no_oversample_sft.yaml", "train-export/train-export-007/sft.jsonl"),
    ],
)
def test_r6_sft_changes_exactly_one_variable(candidate: str, expected_relpath: str) -> None:
    """相对 sft-006 的配置，唯一差别是训练数据路径；LoRA 与超参一个字不动。"""
    baseline = _load(BUILD / "retail_ops_v1_r4_round3_capacity_prompt_sft.yaml")
    variant = _load(BUILD / candidate)
    assert _diff(baseline, variant) == {"data"}
    assert variant["data"]["train_relpath"] == expected_relpath
    assert variant["data"]["eval_relpath"] == baseline["data"]["eval_relpath"]
    assert variant["lora"] == baseline["lora"]
    assert variant["training"] == baseline["training"]
    assert variant["model"] == baseline["model"]


# --- 评测配置 -----------------------------------------------------------------


def test_r6_dev_candidate_changes_only_the_adapter() -> None:
    baseline = _load(EVAL / "retail_ops_v1_r4_round3_capacity_prompt_candidate.yaml")
    r6 = _load(EVAL / "retail_ops_v1_r6_candidate.yaml")
    assert _diff(baseline, r6) == {"attempt_id", "adapter"}


def test_the_ood_v2_configs_differ_only_by_partition() -> None:
    dev = _load(BUILD / "retail_ops_ood_v2_dev_build.yaml")
    sealed = _load(BUILD / "retail_ops_ood_v2_sealed_build.yaml")
    assert _diff(dev, sealed) == {"phrasing"}
    assert dev["phrasing"]["partition"] == "ood_dev"
    assert sealed["phrasing"]["partition"] == "ood_sealed"
    assert dev["phrasing"]["bank_sha256"] == sealed["phrasing"]["bank_sha256"]


def test_the_sealed_config_says_it_is_observed_once() -> None:
    """「只观测一次」必须写在配置里，不能只在对话里说过。"""
    text = (BUILD / "retail_ops_ood_v2_sealed_build.yaml").read_text(encoding="utf-8")
    assert "只观测一次" in text
    assert "退化成第二个 dev" in text


def test_the_ood_candidate_configs_pin_the_same_base_model() -> None:
    """两个候选与基座必须用同一份已哈希校验的基座，否则读数不可比。"""
    base = _load(EVAL / "retail_ops_ood_v1_base.yaml")
    for name in ("retail_ops_ood_r6_candidate.yaml", "retail_ops_ood_sft006_unmerged.yaml"):
        candidate = _load(EVAL / name)
        assert candidate["model"] == base["model"], name
        assert candidate["generation"] == base["generation"], name


def test_the_unmerged_control_exists_and_says_why() -> None:
    """去掉合并/未合并这个混淆的对照必须存在，且写明它为什么存在。"""
    text = (EVAL / "retail_ops_ood_sft006_unmerged.yaml").read_text(encoding="utf-8")
    assert "去掉混淆" in text
    assert "ood_candidate" in text


# --- 第五次封存 holdout 观测 --------------------------------------------------


def test_the_fifth_observation_base_matches_the_fourth_field_by_field() -> None:
    """base 侧必须重跑（commit 变了就不可配对），但除 attempt_id 外一个字段不能动。"""
    fourth = _load(EVAL / "retail_ops_v1_r45b_holdout_base.yaml")
    fifth = _load(EVAL / "retail_ops_v1_r6_holdout_base.yaml")
    assert _diff(fourth, fifth) == {"attempt_id"}
    assert fifth["attempt_id"] == "qwen3-4b-holdout-base-005"


def test_the_fifth_observation_candidate_changes_only_the_model() -> None:
    """候选侧相对第四次只换模型与血统；生成参数、receipt、bundle、seed 全部不动。"""
    fourth = _load(EVAL / "retail_ops_v1_r45b_holdout_merged_candidate.yaml")
    fifth = _load(EVAL / "retail_ops_v1_r6_holdout_merged_candidate.yaml")
    assert _diff(fourth, fifth) == {"attempt_id", "merged_from", "model"}
    assert fifth["generation"] == fourth["generation"]
    assert fifth["holdout_receipt_path"] == fourth["holdout_receipt_path"]


def test_the_fifth_candidate_lineage_is_recomputable() -> None:
    """自己声明一个 merged_revision 等于没有证明——它必须能从基座与 adapter 复算。"""
    from veritool_rl.core.agent.qwen import derive_merged_revision

    config = _load(EVAL / "retail_ops_v1_r6_holdout_merged_candidate.yaml")
    lineage = config["merged_from"]
    assert (
        derive_merged_revision(lineage["base_revision"], lineage["adapter_file_sha256"])
        == lineage["merged_revision"]
    )
    assert config["model"]["revision"] == lineage["merged_revision"]


def test_the_fifth_candidate_is_sft_008_not_sft_006() -> None:
    """第五次观测的候选必须是 R6 的最终候选，不是此前拿过 GO 的那个。"""
    fifth = _load(EVAL / "retail_ops_v1_r6_holdout_merged_candidate.yaml")
    sft008 = _load(EVAL / "retail_ops_ood_r6b_candidate.yaml")
    assert fifth["merged_from"]["adapter_file_sha256"] == sft008["adapter"]["file_sha256"]


def test_the_pending_observation_is_declared_before_it_runs() -> None:
    """内容与判读必须写在跑之前，且至少三种结果都要预先写明。

    **这条测试此前钉的是第五次观测的那几句原话**（"运行内容（三个，固定，不得增减）"
    等等）。第六次观测把那一节换掉之后，它就在强制一段已经不再描述当前边界的措辞——
    与 2026-08-17 外部审阅抓到的 `test_r6_never_claims_a_release_decision` 是同一个
    失败模式：**断言"某句话必须在场"的测试，会在那句话过期时把它焊死。**

    现在断言的是**结构**而不是措辞：判读规则一节里至少有三个加粗的结果分支。
    结果叫什么名字（GO / NO-GO / 复现 / 不复现 / …）由当轮决定，
    "必须预先写明三种以上结果"这条纪律不由当轮决定。
    """
    plan = (REPO_ROOT / "task_plan.md").read_text(encoding="utf-8")

    section = re.search(r"^###+ 判读规则.*?$(.*?)^###? ", plan, re.MULTILINE | re.DOTALL)
    assert section is not None, "task_plan.md 缺少「判读规则」一节"

    branches = re.findall(r"^\d+\.\s+\*\*(.+?)\*\*", section.group(1), re.MULTILINE)
    assert len(branches) >= 3, f"判读规则只写了 {len(branches)} 种结果：{branches}"


def test_every_declared_run_directory_is_actually_declared() -> None:
    """跑了但没在计划里声明过的运行 = 事后挑选的机会。

    **本轮已落盘的运行目录，每一个都必须出现在 `task_plan.md` 里。**
    目录还没生成时这条自动为真（没有运行 = 没有未声明的运行），
    生成之后它才开始有约束力——这正是"先写定再跑"在文件系统上的可验证投影。

    **扫描范围从计划本身派生**，不再是测试里手写的一组 glob。此前每开一轮都要
    改这几行（R6 那版写死了 `ood-v2.2` 与 `r6/*-006`），而"忘了改"的表现是
    **测试仍然全绿**——它去检查上一轮的目录，对本轮零约束。
    现在的做法是：把计划声明的每个产物目录的**父目录**当作本轮命名空间，
    该命名空间下的每个子目录都必须被声明。

    **边界**：命名空间若与旧轮次共用一个父目录（R6 的 `reports/.../r6/` 下就住着
    上一轮的 `train-export-006`），这条会把旧产物也要求进计划。本轮起每轮用自己的
    前缀（`r8`、`ood-v2.3`）来避免，这是约定而非机器保证。
    """
    plan = (REPO_ROOT / "task_plan.md").read_text(encoding="utf-8")

    declared = {
        match.group(1) for match in re.finditer(r"`(reports/retail_ops/[A-Za-z0-9._/-]+)`", plan)
    }
    assert declared, "task_plan.md 里一个产物目录都没声明"

    namespaces = {PurePosixPath(name).parent.as_posix() for name in declared}
    for namespace in sorted(namespaces):
        root = REPO_ROOT / namespace
        if not root.is_dir():
            continue
        for path in sorted(root.iterdir()):
            if not path.is_dir():
                continue
            relative = path.relative_to(REPO_ROOT).as_posix()
            assert relative in declared, (
                f"{relative} 已落盘，但 task_plan.md 的运行清单里没有声明过它"
            )
