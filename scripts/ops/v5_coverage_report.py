#!/usr/bin/env python
"""v5（B-4）分层覆盖表：逐场景 × 难度档 × split 计数 + 难度偏移机器证明。

数据来源：`build_v5_task_set`（与冻结数据集同参重建，确定性逐位一致）与
v1 冻结生成器 `build_formal_task_set`（对照基线）。脚本不重算任何判分指标——
覆盖断言的机器守卫在 `FormalTaskSet.assert_exact_quotas_v5`，这里只把
「5.0× → ~1.0×」的证据落盘成可核对的 JSON。

用法：

    .venv/bin/python scripts/ops/v5_coverage_report.py \\
        reports/retail_ops/v1/r12-v5/coverage-v5-001
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from veritool_rl.retail_ops.domain.formal_tasks import (  # noqa: E402
    _V4_SCENARIOS,
    _V5_STATUS_AXIS_SCENARIOS,
    FormalSplit,
    _v5_scenario_bucket_keys,
    build_formal_task_set,
    build_v5_task_set,
    build_v6_task_set,
)

V1_VERSION = "retail_ops_v1_r2_20260722"
V5_VERSION = "retail_ops_v5_20260906"
V6_VERSION = "retail_ops_v6_20260907"

#: 重建版构建器（v6 与 v5 结构配额完全相同，覆盖语义共用）。
REBUILT_BUILDERS = {V5_VERSION: build_v5_task_set, V6_VERSION: build_v6_task_set}


def _bucket_key(task: Any) -> int:
    """难度档键：与 formal_tasks._v5_bucket_key 同语义（对 v1 任务同样适用）。"""
    scenario = task.scenario
    if scenario in _V5_STATUS_AXIS_SCENARIOS:
        return int(task.metadata["formal_family"]["state_variant"])
    deadline = int(task.metadata["formal_family"]["primary_policy_state"]["refund_deadline"])
    return abs(deadline - 20)


def _coverage(task_set: Any) -> dict[str, Any]:
    families_by_split: dict[str, dict[str, dict[int, int]]] = {
        split.value: defaultdict(Counter) for split in FormalSplit
    }
    for split in FormalSplit:
        for record in task_set.records(split):
            scenario = record.task.scenario.value
            families_by_split[split.value][scenario][_bucket_key(record.task)] += 1
    report: dict[str, Any] = {}
    for scenario in _V4_SCENARIOS:
        keys = _v5_scenario_bucket_keys(scenario)
        entry: dict[str, Any] = {
            "bucket_keys": list(keys),
            "family_counts_by_split": {},
            "bucket_coverage_by_split": {},
        }
        for split in FormalSplit:
            counter = families_by_split[split.value].get(scenario.value, Counter())
            entry["family_counts_by_split"][split.value] = {
                str(key): counter.get(key, 0) for key in keys
            }
            entry["bucket_coverage_by_split"][split.value] = [
                key for key in keys if counter.get(key, 0) > 0
            ]
        margin_based = scenario not in _V5_STATUS_AXIS_SCENARIOS
        if margin_based:
            shares: dict[str, float] = {}
            for split in ("train", "holdout"):
                counts = entry["family_counts_by_split"][split]
                total = sum(counts.values())
                far = sum(count for key, count in counts.items() if int(key) >= 10)
                shares[split] = far / total if total else 0.0
            entry["margin_ge10_share"] = shares
            entry["margin_ge10_share_ratio_train_vs_holdout"] = (
                round(shares["train"] / shares["holdout"], 4) if shares["holdout"] else None
            )
        report[scenario.value] = entry
    return report


def main() -> int:
    args = sys.argv[1:]
    if len(args) not in (1, 2):
        print(__doc__)
        return 2
    out_dir = Path(args[0])
    rebuilt_version = args[1] if len(args) == 2 else V5_VERSION
    builder = REBUILT_BUILDERS.get(rebuilt_version)
    if builder is None:
        print(f"未登记的重建版本: {rebuilt_version}，可选 {sorted(REBUILT_BUILDERS)}")
        return 2
    rebuilt_label = rebuilt_version.split("_")[2]
    v1 = _coverage(build_formal_task_set(V1_VERSION, 0))
    rebuilt = _coverage(builder(rebuilt_version, 0))
    ratios = {
        scenario: {
            "v1": v1[scenario].get("margin_ge10_share_ratio_train_vs_holdout"),
            rebuilt_label: rebuilt[scenario].get("margin_ge10_share_ratio_train_vs_holdout"),
        }
        for scenario in rebuilt
        if "margin_ge10_share_ratio_train_vs_holdout" in rebuilt[scenario]
    }
    payload = {
        "dataset_versions": {"baseline": V1_VERSION, "rebuilt": rebuilt_version},
        "margin_ge10_share_ratio": ratios,
        "v1": v1,
        rebuilt_label: rebuilt,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "coverage.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"coverage written to {out}")
    print(f"margin>=10 share ratio (train vs holdout), v1 -> {rebuilt_label}:")
    for scenario, pair in ratios.items():
        print(f"  {scenario:24s} {pair['v1']} -> {pair[rebuilt_label]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
