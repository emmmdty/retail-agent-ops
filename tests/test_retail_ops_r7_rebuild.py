"""最终候选 `sft-008` 的独立重建复验（R7）所需的契约。

这一轮补两个缺口：

1. **最终候选从未被独立重建过**——`SPEC.md` §6 第 6 条当初只在 `sft-006` 上做、
   且只在 dev 上做。
2. **头条读数只来自一份措辞池**——`phrasing-bank-002` 的一个分片，单一 provider、
   单一 prompt、单一批次。换一份全新素材还成不成，此前没有答案。

第 2 点逼出一个此前不存在的能力：**两份不同素材构建的 OOD v2 任务集必须可区分**。
现在不行——`dataset_version` 是模块级常量，两份素材会挂同一个版本号；而 `task_id` 是
`sha256(f"oodv2:{seed}:{scenario}:{index}")`，**只依赖位置**，两份素材的 `task_ids`
逐条相同。也就是说仅凭 manifest 的这两个字段，两份内容完全不同的评测集看起来一模一样。

这正是外部审阅在 v1/v2 上抓到的同一个问题（当时 OOD v2 的报告声称自己属于
`retail_ops_ood_v1_20260815`），只是这次发生在 v2 内部。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
import yaml

from veritool_rl.retail_ops.build.ood_manifests import OodPhrasingSpec, build_ood_task_set
from veritool_rl.retail_ops.build.phrasing_bank import (
    PhrasingRecord,
    intent_index,
    phrasing_id,
)
from veritool_rl.retail_ops.domain.ood_v2_tasks import (
    OOD_V2_2_DATASET_VERSION,
    OOD_V2_DATASET_VERSION,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = REPO_ROOT / "domains" / "retail_ops" / "v1"
BUILD = REPO_ROOT / "configs" / "retail_ops" / "build"

_INTENTS = ("status_inquiry", "refund_request", "refund_request_retry")


def _bank(marker: str) -> list[PhrasingRecord]:
    """造一份足量的假措辞池：每个意图 40 条，全部落在 `ood_sealed`。

    文本里带 `marker`，因此两份池子的 `phrasing_id` 与请求文本逐条不同——
    这正是"两份素材"该有的样子。
    """
    records: list[PhrasingRecord] = []
    for intent in _INTENTS:
        for index in range(40):
            text = f"{marker} 第{index}种说法，麻烦看下订单 {{order_id}}"
            records.append(
                PhrasingRecord(
                    phrasing_id=phrasing_id(text),
                    intent=intent,
                    style="colloquial",
                    text=text,
                    partition="ood_sealed",
                )
            )
    return records


def _spec(marker: str, dataset_version: str) -> OodPhrasingSpec:
    records = _bank(marker)
    return OodPhrasingSpec(
        index=intent_index(records, "ood_sealed"),
        partition="ood_sealed",
        bank_sha256="0" * 64,
        dataset_version=dataset_version,
    )


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _ood_build_configs() -> list[Path]:
    return sorted(
        path
        for path in BUILD.glob("retail_ops_ood_*_build.yaml")
        if _load(path).get("phrasing") is not None
    )


def test_two_phrasing_banks_produce_distinguishable_task_sets(tmp_path: Path) -> None:
    """两份不同素材构建出的任务集，manifest 必须能把它们区分开。

    区分不能靠 `task_ids`——它只依赖位置，两份逐条相同。真正携带内容的是
    `tasks_file_sha256` 与 `dataset_version`，两者都必须不同。
    """
    first = build_ood_task_set(
        BUNDLE_DIR,
        0,
        tmp_path / "first",
        phrasing=_spec("甲池", OOD_V2_DATASET_VERSION),
    )
    second = build_ood_task_set(
        BUNDLE_DIR,
        0,
        tmp_path / "second",
        phrasing=_spec("乙池", OOD_V2_2_DATASET_VERSION),
    )

    # 位置哈希逐条相同——这正是为什么只比 task_ids 什么都验证不了。
    assert first.task_ids == second.task_ids

    assert first.tasks_file_sha256 != second.tasks_file_sha256
    assert first.dataset_version != second.dataset_version
    assert first.dataset_version == OOD_V2_DATASET_VERSION
    assert second.dataset_version == OOD_V2_2_DATASET_VERSION


def test_the_manifest_dataset_version_comes_from_the_spec(tmp_path: Path) -> None:
    """版本号必须由调用方声明，不能是模块常量——否则第二份素材无处安放。"""
    manifest = build_ood_task_set(
        BUNDLE_DIR,
        0,
        tmp_path / "out",
        phrasing=_spec("丙池", OOD_V2_2_DATASET_VERSION),
    )
    assert manifest.dataset_version == OOD_V2_2_DATASET_VERSION


def test_an_unknown_dataset_version_is_rejected(tmp_path: Path) -> None:
    """随手写一个版本号就能造出"新数据集"的话，版本号就不是受控字段了。"""
    with pytest.raises(ValueError):
        build_ood_task_set(
            BUNDLE_DIR,
            0,
            tmp_path / "out",
            phrasing=_spec("丁池", "retail_ops_ood_v9_whatever"),
        )


def test_the_ood_build_config_must_declare_its_dataset_version() -> None:
    """`dataset_version` 是 `phrasing` 段的必填键。

    与项目其它必填键同一个理由："忘了写"与"故意沿用"必须在配置层可分辨。
    给默认值的话，新素材会静默挂上旧版本号，而产物看起来完全正常。
    """
    from veritool_rl.product_cli import _ood_phrasing_spec

    config = {
        "phrasing": {
            "bank_relpath": "phrasing/phrasing-bank-002/phrasings.jsonl",
            "bank_sha256": "0" * 64,
            "partition": "ood_sealed",
        }
    }
    with pytest.raises(ValueError, match="dataset_version"):
        _ood_phrasing_spec(config, Path("/nonexistent"))


def test_each_phrasing_bank_maps_to_exactly_one_dataset_version() -> None:
    """已提交的 OOD 构建配置里，措辞池与数据集版本必须是**双射**。

    一份素材两个版本号 = 同一批任务在两张表里不可比；
    两份素材一个版本号 = 两批不同任务在同一张表里被当成同一个数据集。
    两种都会让配对前提失效，而这正是外部审阅在 v1/v2 上抓到的那类错误。
    """
    configs = _ood_build_configs()
    assert len(configs) >= 3, "至少应有 v2.1 的 dev/sealed 与 v2.2 的 sealed 三份"

    bank_to_version: dict[str, str] = {}
    version_to_bank: dict[str, str] = {}
    for path in configs:
        phrasing = _load(path)["phrasing"]
        bank = str(phrasing["bank_relpath"])
        version = str(phrasing["dataset_version"])
        assert bank_to_version.setdefault(bank, version) == version, (
            f"{path.name}: 措辞池 {bank} 被两个 dataset_version 使用"
        )
        assert version_to_bank.setdefault(version, bank) == bank, (
            f"{path.name}: dataset_version {version} 被两份措辞池使用"
        )


def test_the_v22_sealed_config_differs_from_v21_only_by_the_bank() -> None:
    """新分片的构建配置相对旧的只允许差措辞池那一段。

    任何别的差异都会让"唯一自变量是素材"这句话变假——包括 bundle、pipeline。
    """
    old = _load(BUILD / "retail_ops_ood_v2_sealed_build.yaml")
    new = _load(BUILD / "retail_ops_ood_v2_2_sealed_build.yaml")
    assert set(old) == set(new)
    differing = {key for key in old if old[key] != new[key]}
    assert differing == {"phrasing"}
    assert old["phrasing"]["partition"] == new["phrasing"]["partition"] == "ood_sealed"
    assert old["phrasing"]["bank_relpath"] != new["phrasing"]["bank_relpath"]


def test_the_new_bank_is_never_used_for_training() -> None:
    """bank-003 只允许出现在评测构建配置里，绝不能进任何训练导出配置。"""
    for path in sorted(BUILD.glob("*.yaml")):
        config = _load(path)
        paraphrase = config.get("sft_paraphrase")
        if isinstance(paraphrase, dict):
            assert "phrasing-bank-003" not in str(paraphrase.get("bank_relpath", "")), (
                f"{path.name}: 训练增强引用了本轮的评测素材"
            )


def test_the_built_v22_artifacts_match_the_generator() -> None:
    """已落盘的 v2.2 任务集必须与当前代码重算的结果逐字节一致。

    比的是 `tasks_file_sha256`（覆盖每一条任务的全部内容），不是 `task_ids`
    （只依赖位置，两份素材逐条相同，比它等于什么都没比）。
    """
    import json
    import tempfile

    from veritool_rl.core.artifacts import write_jsonl
    from veritool_rl.retail_ops.build.ood_manifests import load_ood_manifest
    from veritool_rl.retail_ops.build.phrasing_bank import load_phrasing_bank
    from veritool_rl.retail_ops.domain.ood_v2_tasks import build_ood_v2_tasks

    manifest_path = REPO_ROOT / "reports/retail_ops/v1/ood-v2.2/sealed/tasks/manifest.json"
    bank_path = (
        REPO_ROOT
        / "data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722"
        / "phrasing/phrasing-bank-003/phrasings.jsonl"
    )
    if not manifest_path.is_file() or not bank_path.is_file():
        pytest.skip("v2.2 产物与措辞池是 ignored 私有/运行产物，未生成时跳过")

    manifest = load_ood_manifest(manifest_path)
    assert manifest.dataset_version == OOD_V2_2_DATASET_VERSION

    rebuilt = build_ood_v2_tasks(intent_index(load_phrasing_bank(bank_path), "ood_sealed"))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "tasks.jsonl"
        write_jsonl(path, (task.model_dump(mode="json") for task in rebuilt))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == manifest.tasks_file_sha256

    # 两份素材构建出的任务集内容必须真的不同——否则"新素材"是假的。
    old_manifest_path = REPO_ROOT / "reports/retail_ops/v1/ood-v2.1/sealed/tasks/manifest.json"
    if old_manifest_path.is_file():
        old = json.loads(old_manifest_path.read_text(encoding="utf-8"))
        assert old["tasks_file_sha256"] != manifest.tasks_file_sha256
