"""Phase C3：二维迭代面——政策边界探针 × 措辞池交叉网格（CPU 生成器）。

## 为什么需要它（R7 失败机制的根治）

R7 的教训（`POLICY_BOUNDARY.md` §6、PITFALLS #8）：探针措辞与训练同源，
「同源评测面高估修复收益」——修复在同源探针与 dev 上改善、在措辞分布外的
`ood_dev` 上退化，判负。二维面让**同一次迭代**同时看见两类退化：

- **边界型**：`offset` 轴（探针的 15 格）；
- **措辞型**：探针任务的用户话术改用措辞池分片（`ood_dev` 等评测分片），
  不再与冻结数据集的 12 句模板同源。

生成器**只复用两条既有链路**：探针的状态/gold/kind 语义原样保留，
措辞经 `paraphrases_for_task` 的确定性选取与占位符填充——不新造机制。

三条诚信约束（先于测试写定）：

1. 措辞必须真的来自措辞池：任何任务的用户请求都不得与探针的同源模板相同
   （突变「回退到模板」必须让本测试红）；
2. 装置自洽：Oracle 必须解出全部任务且零政策违规——措辞变化不得让 gold 序列
   失去可解性；
3. 确定性：同一 bank + 同一 seed 逐字节相同；不同 bank 版本号必须产生不同的
   `dataset_version`（素材↔版本号双射）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from veritool_rl.retail_ops.build.phrasing_bank import (
    INTENT_REFUND,
    build_records,
)
from veritool_rl.retail_ops.domain.policy_boundary_phrasing_tasks import (
    POLICY_BOUNDARY_PHRASING_DATASET_VERSION,
    POLICY_BOUNDARY_PHRASING_GENERATOR_ID,
    build_policy_boundary_phrasing_tasks,
    expected_phrasing_category_counts,
)
from veritool_rl.retail_ops.domain.policy_boundary_tasks import (
    INSTANCES_PER_OFFSET,
    OFFSETS,
    POLICY_BOUNDARY_DATASET_VERSION,
    build_policy_boundary_tasks,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = REPO_ROOT / "domains/retail_ops/v1"


def _bank_index(partition: str, count: int) -> dict[str, Any]:
    """构造指定分片下恰好 `count` 条 refund 意图措辞的合成索引。

    分片由文本哈希决定，因此迭代生成候选直到目标分片攒够数量——
    与真实加载路径走同一套 assign_partition 规则。
    """
    accepted = [
        (INTENT_REFUND, "test-style", f"麻烦帮我处理第 {index} 号形态的退款请求 {{order_id}}。")
        for index in range(2000)
    ]
    records = build_records(accepted)
    in_partition = [r for r in records if r.partition == partition]
    if len(in_partition) < count:
        raise AssertionError(f"夹具不足：{partition} 只有 {len(in_partition)} 条")
    return {INTENT_REFUND: in_partition[:count]}


# ---------------------------------------------------------------------------
# 正例：交叉面长什么样
# ---------------------------------------------------------------------------


def test_crossed_face_has_probe_grid_with_bank_wording() -> None:
    index = _bank_index("ood_dev", 12)
    tasks = build_policy_boundary_phrasing_tasks(0, index, partition="ood_dev")

    assert len(tasks) == len(OFFSETS) * INSTANCES_PER_OFFSET
    probes = {task.task_id: task for task in build_policy_boundary_tasks(0)}
    assert len(probes) == len(tasks)

    # kind/category 语义与探针逐字相同——决策曲线的横轴不变
    for task in tasks:
        probe = probes[task.metadata["probe_task_id"]]
        assert task.metadata["ood_kind"] == probe.metadata["ood_kind"]
        assert task.metadata["ood_category"] == probe.metadata["ood_category"]
        assert task.initial_state == probe.initial_state
        assert task.expected_calls == probe.expected_calls
        assert task.expected_decision == probe.expected_decision


def test_wording_comes_from_the_bank_not_from_the_same_source_templates() -> None:
    """反例模式的镜像：措辞若回退到探针模板，交叉面就退化成 R7 的同源探针。"""
    index = _bank_index("ood_dev", 12)
    tasks = build_policy_boundary_phrasing_tasks(0, index, partition="ood_dev")
    probe_requests = {task.user_request for task in build_policy_boundary_tasks(0)}

    for task in tasks:
        assert task.user_request not in probe_requests
        assert "{order_id}" not in task.user_request
        # metadata 必须携带措辞侧的归因字段——没有它，措辞型退化无从定位
        assert len(task.metadata["phrasing_id"]) == 64
        assert task.metadata["phrasing_partition"] == "ood_dev"


def test_wording_is_spread_across_the_pool() -> None:
    """不同实例取到不同措辞（起点由任务哈希决定），避免池头过采样。"""
    index = _bank_index("ood_dev", 12)
    tasks = build_policy_boundary_phrasing_tasks(0, index, partition="ood_dev")

    used = {task.metadata["phrasing_id"] for task in tasks}
    assert len(used) >= 6, f"120 条任务只用了 {len(used)} 条措辞——铺开机制失效"


# ---------------------------------------------------------------------------
# 装置自洽与确定性
# ---------------------------------------------------------------------------


def test_oracle_solves_every_crossed_task_with_zero_violations() -> None:
    """措辞变化不得破坏 gold 序列的可解性——这是装置自洽，不是模型读数。"""
    from veritool_rl.core.agent.policy import OraclePolicy
    from veritool_rl.core.agent.runner import run_episode
    from veritool_rl.retail_ops.domain.bundle import load_bundle
    from veritool_rl.retail_ops.domain.environment import RetailOpsEnv

    index = _bank_index("ood_dev", 12)
    tasks = build_policy_boundary_phrasing_tasks(0, index, partition="ood_dev")
    bundle = load_bundle(BUNDLE_DIR)

    failures = [
        task.task_id
        for task in tasks
        if not run_episode(
            task,
            lambda current: RetailOpsEnv(current, bundle),
            OraclePolicy(task),
            0,
        ).success
    ]
    assert failures == [], f"这些任务的 gold 序列解不出来: {failures[:5]}"


def test_crossed_face_is_deterministic() -> None:
    index = _bank_index("ood_dev", 12)
    first = build_policy_boundary_phrasing_tasks(0, index, partition="ood_dev")
    second = build_policy_boundary_phrasing_tasks(0, index, partition="ood_dev")

    assert [task.model_dump(mode="json") for task in first] == [
        task.model_dump(mode="json") for task in second
    ]


def test_crossed_face_has_its_own_dataset_version() -> None:
    """素材↔版本号双射：交叉面不是探针，也不是 v2，必须有自己的登记号。"""
    assert POLICY_BOUNDARY_PHRASING_DATASET_VERSION != POLICY_BOUNDARY_DATASET_VERSION
    assert POLICY_BOUNDARY_PHRASING_GENERATOR_ID == "policy_boundary_phrasing_sweep_v1"
    assert expected_phrasing_category_counts() == {
        "refund_eligible": 8 * 8,
        "refund_denied_window": 7 * 8,
    }


# ---------------------------------------------------------------------------
# 边界：池太小 / 分片为空必须显式失败
# ---------------------------------------------------------------------------


def test_a_partition_without_enough_phrasings_fails_loudly() -> None:
    index = _bank_index("ood_sealed", 3)
    with pytest.raises(ValueError, match="措辞"):
        build_policy_boundary_phrasing_tasks(0, index, partition="ood_sealed")


# ---------------------------------------------------------------------------
# build_ood_task_set 的组合模式
# ---------------------------------------------------------------------------


def test_build_ood_task_set_accepts_boundary_plus_phrasing(tmp_path: Path) -> None:
    """组合模式：boundary=True + 交叉面 dataset_version → 生成交叉面任务集。"""
    from veritool_rl.retail_ops.build.ood_manifests import (
        OodPhrasingSpec,
        build_ood_task_set,
        load_ood_manifest,
    )

    index = _bank_index("ood_dev", 12)
    spec = OodPhrasingSpec(
        index=index,
        partition="ood_dev",
        bank_sha256="0" * 64,
        dataset_version=POLICY_BOUNDARY_PHRASING_DATASET_VERSION,
    )
    manifest = build_ood_task_set(BUNDLE_DIR, 0, tmp_path / "face", phrasing=spec, boundary=True)

    assert manifest.dataset_version == POLICY_BOUNDARY_PHRASING_DATASET_VERSION
    assert manifest.generator_id == POLICY_BOUNDARY_PHRASING_GENERATOR_ID
    assert manifest.task_count == 120
    assert load_ood_manifest(tmp_path / "face" / "manifest.json").task_count == 120


def test_build_ood_task_set_keeps_the_v2_boundary_exclusion(tmp_path: Path) -> None:
    """既有互斥不放松：v2 素材 + boundary=True 仍然拒绝。"""
    from veritool_rl.retail_ops.build.ood_manifests import (
        OodPhrasingSpec,
        build_ood_task_set,
    )
    from veritool_rl.retail_ops.domain.ood_v2_tasks import OOD_V2_DATASET_VERSION

    index = _bank_index("ood_dev", 12)
    spec = OodPhrasingSpec(
        index=index,
        partition="ood_dev",
        bank_sha256="0" * 64,
        dataset_version=OOD_V2_DATASET_VERSION,
    )
    with pytest.raises(ValueError, match="互斥"):
        build_ood_task_set(BUNDLE_DIR, 0, tmp_path / "x", phrasing=spec, boundary=True)


# ---------------------------------------------------------------------------
# CLI：ood_build 的组合模式
# ---------------------------------------------------------------------------


def _write_bank(tmp_path: Path) -> tuple[Path, str]:
    """把合成措辞池写成真实 bank 文件，返回 (bank 相对路径, sha256)。"""
    from veritool_rl.retail_ops.build.phrasing_bank import bank_sha256

    accepted = [
        (INTENT_REFUND, "test-style", f"麻烦帮我处理第 {index} 号形态的退款请求 {{order_id}}。")
        for index in range(2000)
    ]
    records = [r for r in build_records(accepted) if r.partition == "ood_dev"][:12]
    digest = bank_sha256(records)
    private_root = tmp_path / "private"
    bank_dir = private_root / "banks"
    bank_dir.mkdir(parents=True)
    from veritool_rl.retail_ops.build.phrasing_bank import write_phrasing_bank

    write_phrasing_bank(bank_dir / "crossed-bank.jsonl", records)
    return Path("banks/crossed-bank.jsonl"), digest


def test_cli_ood_build_accepts_the_crossed_mode(tmp_path: Path, monkeypatch: Any) -> None:
    """boundary=true + 交叉面措辞池 → CLI 走组合构建（原互斥检查放行交叉面）。"""
    import json
    from argparse import Namespace

    from veritool_rl.product_cli import _run_ood_build

    bank_relpath, digest = _write_bank(tmp_path)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "domains/retail_ops").mkdir(parents=True, exist_ok=True)
    import shutil

    shutil.copytree(REPO_ROOT / "domains/retail_ops/v1", tmp_path / "domains/retail_ops/v1")

    config = {
        "pipeline": "ood_build",
        "bundle_dir": "domains/retail_ops/v1",
        "boundary": True,
        "phrasing": {
            "bank_relpath": str(bank_relpath),
            "bank_sha256": digest,
            "partition": "ood_dev",
            "dataset_version": POLICY_BOUNDARY_PHRASING_DATASET_VERSION,
        },
    }
    args = Namespace(seed=0, output_dir=tmp_path / "face", input_dir=tmp_path / "private")

    _run_ood_build(args, config)

    manifest = json.loads((tmp_path / "face" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset_version"] == POLICY_BOUNDARY_PHRASING_DATASET_VERSION
    assert manifest["task_count"] == 120


def test_cli_ood_build_still_rejects_v2_plus_boundary(tmp_path: Path, monkeypatch: Any) -> None:
    """既有互斥对 v2 素材仍然生效。"""
    from argparse import Namespace

    from veritool_rl.product_cli import _run_ood_build
    from veritool_rl.retail_ops.domain.ood_v2_tasks import OOD_V2_DATASET_VERSION

    bank_relpath, digest = _write_bank(tmp_path)
    monkeypatch.chdir(tmp_path)
    import shutil

    shutil.copytree(REPO_ROOT / "domains/retail_ops/v1", tmp_path / "domains/retail_ops/v1")

    config = {
        "pipeline": "ood_build",
        "bundle_dir": "domains/retail_ops/v1",
        "boundary": True,
        "phrasing": {
            "bank_relpath": str(bank_relpath),
            "bank_sha256": digest,
            "partition": "ood_dev",
            "dataset_version": OOD_V2_DATASET_VERSION,
        },
    }
    args = Namespace(seed=0, output_dir=tmp_path / "face", input_dir=tmp_path / "private")

    with pytest.raises(ValueError, match="互斥"):
        _run_ood_build(args, config)


def test_crossed_version_is_rejected_without_boundary(tmp_path: Path) -> None:
    """scoped re-review Minor-1：交叉面版本号不得在 boundary=false 路径冒用。"""
    from veritool_rl.retail_ops.build.ood_manifests import (
        OodPhrasingSpec,
        build_ood_task_set,
    )

    index = _bank_index("ood_dev", 12)
    spec = OodPhrasingSpec(
        index=index,
        partition="ood_dev",
        bank_sha256="0" * 64,
        dataset_version=POLICY_BOUNDARY_PHRASING_DATASET_VERSION,
    )
    with pytest.raises(ValueError, match="boundary=true"):
        build_ood_task_set(BUNDLE_DIR, 0, tmp_path / "x", phrasing=spec, boundary=False)
