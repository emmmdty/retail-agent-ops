"""把「训练素材与评测素材零重叠」导出成**公开可核对的哈希清单**。

## 为什么需要这个

「训练与评测的措辞逐条互斥」是 R6 全部分布外结论的前提。它此前由
`tests/test_ood_v2_tasks.py::test_no_evaluation_phrasing_appears_in_the_actual_training_file`
保证——那条测试直接读**真实训练文件**比对，是本仓库最强的经验断言之一。

问题是：训练文件与措辞池都是 gitignored 私有产物。**在一个干净 clone 上，
那条测试会静默 `skip`。** 2026-08-17 外部审阅第五轮指出了这一点：
"最关键的经验性断言，外部读者恰恰验不了"。

## 这个脚本做什么

把两侧的**归一化文本 SHA-256** 导出成一份进 Git 的清单。于是：

- **干净 clone 上**：交集为空这件事变成**公开的集合算术**，任何人都能自己算
  （`test_the_committed_phrasing_digests_are_disjoint`）；
- **持有私有产物时**：清单必须与产物重算结果**逐条相同**，否则测试红
  （`test_the_committed_phrasing_digests_match_the_artifacts`）。

**哈希不泄露原文**：措辞是自由文本，SHA-256 不可逆；清单里没有任何一句原话。
换来的是"这个声称的算术部分不再需要相信作者"。

归一化规则与那条测试逐字相同：把订单号替换成 `<OID>`，其余不动。
两边用同一个函数（`normalize_request`），因此不可能一边归一化一边不归一化。

用法：

    .venv/bin/python scripts/ops/export_phrasing_exclusivity.py \\
        --input_dir data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722 \\
        --output manifests/retail_ops/v1/phrasing_exclusivity.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from veritool_rl.retail_ops.build.phrasing_bank import (  # noqa: E402
    intent_index,
    load_phrasing_bank,
)
from veritool_rl.retail_ops.domain.ood_v2_tasks import build_ood_v2_tasks  # noqa: E402

#: 训练导出用的那一份 `sft.jsonl`。换了训练集就必须重新导出这份清单。
TRAIN_EXPORT_RELPATH = "train-export/train-export-007/sft.jsonl"

#: 参与比对的评测分片：`(措辞池目录名, 分片名)`。
EVALUATION_SHARDS: tuple[tuple[str, str], ...] = (
    ("phrasing-bank-002", "ood_dev"),
    ("phrasing-bank-002", "ood_sealed"),
    ("phrasing-bank-003", "ood_sealed"),
    # D4 一次性 v1.3 发布判定的封存分片（预注册 task_plan `9b1c61b`）。
    ("phrasing-bank-004", "ood_sealed"),
    # bank-005（2026-09-06 生成，替代丢失的 bank-004；task_plan Errors 表当日条目）。
    # 只用 `ood_dev`（DPO 采样面与 B-1 交叉面）；`ood_sealed` 一并纳入比对，
    # 它在 A-7 前不得作为任何评测面出现。
    ("phrasing-bank-005", "ood_dev"),
    ("phrasing-bank-005", "ood_sealed"),
)

#: bank 的候选根目录（相对 `--input_dir`，按序找第一个存在的）：
#: bank-005 在 v1 根的 `phrasing/` 下，bank-001/002/003 在 r2 私有根的
#: `phrasing/` 下——两代素材不同布局，搜索覆盖两种。
_BANK_SEARCH_ROOTS: tuple[str, ...] = (
    "phrasing",
    "r2/retail_ops_v1_r2_20260722/phrasing",
    # 以 r2 根为 --input_dir 时，v1 根的 bank-005 落在这里。
    "../../phrasing",
)

_ORDER_ID_PATTERN = re.compile(r"O-[A-Z0-9]+")

#: 措辞池原始记录里的占位符 → 归一化标记，让「记录级摘要」与任务级摘要
#: 落进同一个 digest 空间。
_PLACEHOLDER_PATTERN = re.compile(r"\{(order_id|other_order_id)\}")


def normalize_request(text: str) -> str:
    """订单号本来就每条不同，去掉它之后剩下的才是"说法"。"""
    return _ORDER_ID_PATTERN.sub("<OID>", text)


def normalize_record(text: str) -> str:
    """措辞池原始记录的归一化：占位符与订单号统一成 `<OID>`。"""
    return _ORDER_ID_PATTERN.sub("<OID>", _PLACEHOLDER_PATTERN.sub("<OID>", text))


def digest(text: str) -> str:
    return hashlib.sha256(normalize_request(text).encode("utf-8")).hexdigest()


def digest_record(text: str) -> str:
    return hashlib.sha256(normalize_record(text).encode("utf-8")).hexdigest()


def _sorted_digests(texts: Iterable[str]) -> list[str]:
    return sorted({digest(text) for text in texts})


def _sorted_record_digests(texts: Iterable[str]) -> list[str]:
    return sorted({digest_record(text) for text in texts})


def _bank_path(private_root: Path, bank: str) -> Path:
    """bank 文件路径：在候选根里找第一个存在的；都不存在时返回默认位置
    （由调用方的「bank 缺失 → 用既往清单」分支处理）。"""
    candidates = [private_root / root / bank / "phrasings.jsonl" for root in _BANK_SEARCH_ROOTS]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def _bank_records(private_root: Path, bank: str, partition: str) -> list[str]:
    index = intent_index(load_phrasing_bank(_bank_path(private_root, bank)), partition)  # type: ignore[arg-type]
    return [record.text for bucket in index.values() for record in bucket]


def training_request_digests(private_root: Path) -> list[str]:
    path = private_root / TRAIN_EXPORT_RELPATH
    requests: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        user = next(message for message in row["messages"] if message["role"] == "user")
        requests.append(str(user["content"]))
    return _sorted_digests(requests)


def _shard_face_digests(private_root: Path, bank: str, partition: str) -> list[str]:
    """任务面级摘要（v2 构建路径，与既有清单同一 digest 空间）。"""
    bank_path = _bank_path(private_root, bank)
    if not bank_path.is_file():
        return _prior_manifest_shard_digests(bank, partition)
    index = intent_index(load_phrasing_bank(bank_path), partition)  # type: ignore[arg-type]
    tasks = build_ood_v2_tasks(index)
    return _sorted_digests(task.user_request for task in tasks)


def _shard_record_digests(private_root: Path, bank: str, partition: str) -> list[str]:
    """记录级摘要：分片里每一条措辞，不只是 v2 任务面抽到的那几条。

    DPO 采样面用整个 `ood_dev` 池（paraphrases_for_task 覆盖全池），泄漏检查
    必须覆盖全部记录；bank 文件已丢失的 shard 只有面级证据可用（如实降级）。
    """
    bank_path = _bank_path(private_root, bank)
    if not bank_path.is_file():
        return _prior_manifest_shard_digests(bank, partition)
    return _sorted_record_digests(_bank_records(private_root, bank, partition))


_PRIOR_MANIFEST = REPO_ROOT / "manifests/retail_ops/v1/phrasing_exclusivity.json"


def _prior_manifest_shard_digests(bank: str, partition: str) -> list[str]:
    """bank 文件已丢失（bank-004，task_plan Errors 2026-09-06）时，用已提交清单
    里的面级摘要作为该 shard 的参照集——互斥检查照样覆盖。"""
    prior = json.loads(_PRIOR_MANIFEST.read_text(encoding="utf-8"))
    key = f"{bank}/{partition}"
    digests = prior["evaluation_request_sha256"].get(key)
    if digests is None:
        msg = f"bank 文件缺失且既往清单里没有 {key} 的面级摘要，互斥检查无法覆盖"
        raise ValueError(msg)
    return digests


def evaluation_request_digests(private_root: Path) -> dict[str, list[str]]:
    return {
        f"{bank}/{partition}": _shard_face_digests(private_root, bank, partition)
        for bank, partition in EVALUATION_SHARDS
    }


def record_request_digests(private_root: Path) -> dict[str, list[str]]:
    return {
        f"{bank}/{partition}": _shard_record_digests(private_root, bank, partition)
        for bank, partition in EVALUATION_SHARDS
    }


def build_manifest(private_root: Path) -> dict[str, Any]:
    training = training_request_digests(private_root)
    evaluation = evaluation_request_digests(private_root)
    records = record_request_digests(private_root)
    return {
        "schema_version": "1.1",
        "normalization": (
            "sha256(order_id -> <OID>); record 级含 {order_id}/{other_order_id} -> <OID>"
        ),
        "train_export_relpath": TRAIN_EXPORT_RELPATH,
        "training_request_sha256": training,
        "evaluation_request_sha256": evaluation,
        "record_request_sha256": records,
        "missing_bank_note": (
            "phrasing-bank-004 文件已丢失（task_plan Errors 2026-09-06），"
            "其条目取自已提交清单 v1.0 的面级摘要（仅 45 条，弱于记录级）"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input_dir", type=Path, required=True, help="私有数据根目录")
    parser.add_argument("--output", type=Path, required=True, help="清单输出路径")
    args = parser.parse_args(argv)

    manifest = build_manifest(args.input_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    training = set(manifest["training_request_sha256"])
    failures: list[str] = []
    records = manifest["record_request_sha256"]
    for name, digests in manifest["evaluation_request_sha256"].items():
        overlap = training & set(digests)
        print(f"  [face]   {name}: {len(digests)} 条，与训练集交集 {len(overlap)}")
        if overlap:
            failures.append(f"face/{name}")
    for name, digests in records.items():
        overlap = training & set(digests)
        print(f"  [record] {name}: {len(digests)} 条，与训练集交集 {len(overlap)}")
        if overlap:
            failures.append(f"record/{name}")
    target_shards = [name for name in records if name.startswith("phrasing-bank-005/")]
    for target in target_shards:
        for other, digests in records.items():
            if other == target:
                continue
            overlap = set(records[target]) & set(digests)
            print(f"  [x-bank] {target} ∩ {other}: {len(overlap)}")
            if overlap:
                failures.append(f"x-bank/{target}/{other}")
    print(f"训练集不同说法 {len(training)} 条 -> {args.output}")
    if failures:
        print(f"互斥性检查失败: {failures}", file=sys.stderr)
        return 1
    print("互斥性检查通过（交集全 0）")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
