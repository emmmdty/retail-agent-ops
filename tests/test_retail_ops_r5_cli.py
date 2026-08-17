"""R5 独立重建复验的配置契约。

`docs/REBUILD_VERIFICATION.md` 的全部结论都依赖一个前提：两次重建相对原候选
**只改了 adapter**。如果配置里还悄悄动了别的（生成参数、dev manifest、基座 revision），
"重建后仍保持正向提升"就不再是关于重建的结论。这份测试把那个前提变成断言。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = REPO_ROOT / "configs" / "retail_ops" / "evaluate"

ORIGINAL = EVAL_DIR / "retail_ops_v1_r4_round3_capacity_prompt_candidate.yaml"
REBUILDS = {
    0: EVAL_DIR / "retail_ops_v1_r5_rebuild_seed0_candidate.yaml",
    1: EVAL_DIR / "retail_ops_v1_r5_rebuild_seed1_candidate.yaml",
}

#: 允许与原候选不同的键。其余每一个键都必须逐字段相同。
ALLOWED_DIFFERENCES = frozenset({"attempt_id", "adapter"})


def _load(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


@pytest.mark.parametrize("seed", sorted(REBUILDS))
def test_rebuild_config_changes_only_the_adapter(seed: int) -> None:
    original = _load(ORIGINAL)
    rebuild = _load(REBUILDS[seed])

    assert set(original) == set(rebuild), "重建配置的键集合与原候选不同"

    differing = {key for key in original if original[key] != rebuild[key]}
    assert differing <= ALLOWED_DIFFERENCES, (
        f"重建 seed{seed} 除 adapter 外还改了：{sorted(differing - ALLOWED_DIFFERENCES)}"
    )
    # 反向断言：adapter 必须**真的**换了，否则这根本不是一次重建。
    assert "adapter" in differing, f"重建 seed{seed} 的 adapter 与原候选相同，不构成重建"


@pytest.mark.parametrize("seed", sorted(REBUILDS))
def test_rebuild_config_points_at_its_own_training_run(seed: int) -> None:
    rebuild = _load(REBUILDS[seed])
    assert rebuild["adapter"]["run_dir"] == f"reports/retail_ops/v1/r5/sft-006-rebuild-seed{seed}"
    assert rebuild["attempt_id"] == f"qwen3-4b-dev-candidate-r5-rebuild-seed{seed}"


@pytest.mark.parametrize("seed", sorted(REBUILDS))
def test_rebuild_config_pins_every_adapter_file(seed: int) -> None:
    """adapter 只固定权重文件是不够的——tokenizer 变了行为就变了。"""
    original = _load(ORIGINAL)
    rebuild = _load(REBUILDS[seed])

    assert set(rebuild["adapter"]["file_sha256"]) == set(original["adapter"]["file_sha256"])
    for name, digest in rebuild["adapter"]["file_sha256"].items():
        assert isinstance(digest, str) and len(digest) == 64, name


def test_the_two_rebuilds_are_different_artifacts() -> None:
    """两次重建必须是两份不同的权重，否则第二次没有信息量。"""
    weights = {
        seed: _load(path)["adapter"]["file_sha256"]["adapter_model.safetensors"]
        for seed, path in REBUILDS.items()
    }
    original_weight = _load(ORIGINAL)["adapter"]["file_sha256"]["adapter_model.safetensors"]

    assert len(set(weights.values()) | {original_weight}) == 3, (
        "原候选与两次重建应当是三份互不相同的权重"
    )


def test_the_same_seed_rebuild_really_used_the_same_seed() -> None:
    """本项目最反直觉的一条读数是"同 seed 产不出同一份权重"。

    如果 seed0 那次其实用的不是 seed 0，这条读数就是假的。配置里没有 seed
    （seed 由 `--seed` 传入），所以这里断言的是文档把这件事说清楚了，
    并且它没有被悄悄改写成"我们换了 seed"。
    """
    doc = (REPO_ROOT / "docs" / "REBUILD_VERIFICATION.md").read_text(encoding="utf-8")
    assert "同一个 seed 产不出同一份权重" in doc
    assert "不是逐位可复现" in doc
    for digest_prefix in ("8a49251f", "c93c6698", "069cdf1c"):
        assert digest_prefix in doc, f"重建文档缺少权重摘要 {digest_prefix}"


def test_the_rebuild_doc_states_what_it_does_not_claim() -> None:
    """复验文档必须有「明确不声称」一节，且它必须谈到样本量、seed 挑选与上线边界。

    **这条测试此前钉着一句 `"没有在 holdout 上重建" in doc`。** 那句话在 2026-08-17
    第二轮复验（最终候选 `sft-008`，做到了封存 holdout 上）之后成了假的，
    而测试会强制它留在文档里——与 LOG-20260817-06 记的是同一个失败模式：
    **断言「某句话必须在场」的测试，会在那句话过期时把它焊死。**

    现在断言的是那一节必须覆盖的**三类边界**，每类给一组可接受的措辞，
    而不是某一句特定的话。
    """
    doc = (REPO_ROOT / "docs" / "REBUILD_VERIFICATION.md").read_text(encoding="utf-8")
    assert "明确不声称" in doc

    required_topics = {
        "样本量": ("n 极小", "n = 3", "不足以给出", "不是置信区间"),
        "seed 挑选": ("不做 seed 挑选",),
        "上线边界": ("不等于", "≠ 可以上线", "不是**这个结果能泛化**"),
        "不可重放": ("不能重放", "不随仓库分发"),
    }
    for topic, markers in required_topics.items():
        assert any(marker in doc for marker in markers), f"「明确不声称」没有覆盖：{topic}"


def test_spec_gate_six_is_no_longer_the_open_one() -> None:
    """SPEC §6 第 6 条一旦做掉，活动文档不得再把它列为"未做"。"""
    for name in ("README.md", "docs/RESUME_EVIDENCE.md"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        if "独立重建" not in text:
            continue
        assert "REBUILD_VERIFICATION" in text, f"{name}: 提到独立重建就必须指向复验记录"
