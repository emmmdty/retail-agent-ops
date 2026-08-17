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
)

_ORDER_ID_PATTERN = re.compile(r"O-[A-Z0-9]+")


def normalize_request(text: str) -> str:
    """订单号本来就每条不同，去掉它之后剩下的才是"说法"。"""
    return _ORDER_ID_PATTERN.sub("<OID>", text)


def digest(text: str) -> str:
    return hashlib.sha256(normalize_request(text).encode("utf-8")).hexdigest()


def _sorted_digests(texts: Iterable[str]) -> list[str]:
    return sorted({digest(text) for text in texts})


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


def evaluation_request_digests(private_root: Path) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for bank, partition in EVALUATION_SHARDS:
        bank_path = private_root / "phrasing" / bank / "phrasings.jsonl"
        index = intent_index(load_phrasing_bank(bank_path), partition)  # type: ignore[arg-type]
        tasks = build_ood_v2_tasks(index)
        result[f"{bank}/{partition}"] = _sorted_digests(task.user_request for task in tasks)
    return result


def build_manifest(private_root: Path) -> dict[str, Any]:
    training = training_request_digests(private_root)
    evaluation = evaluation_request_digests(private_root)
    return {
        "schema_version": "1.0",
        "normalization": "sha256(order_id -> <OID>)",
        "train_export_relpath": TRAIN_EXPORT_RELPATH,
        "training_request_sha256": training,
        "evaluation_request_sha256": evaluation,
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
    for name, digests in manifest["evaluation_request_sha256"].items():
        overlap = training & set(digests)
        print(f"  {name}: {len(digests)} 条，与训练集交集 {len(overlap)}")
    print(f"训练集不同说法 {len(training)} 条 -> {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
