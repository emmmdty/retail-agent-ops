#!/usr/bin/env python
"""把政策边界探针的 OOD 报告渲染成决策曲线。

报告里现成的 `kind_success` 就是曲线：键是偏移量标签（`offset_-3`），
值是该偏移量上判定正确的比例。这里只做排序、对齐与对比，不重新计算任何指标——
指标由评测路径产出，脚本重算等于给同一个数造第二个来源。

用法：

    python scripts/ops/policy_boundary_curve.py \\
        reports/retail_ops/v1/policy-boundary/base \\
        reports/retail_ops/v1/policy-boundary/sft-008
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from veritool_rl.retail_ops.domain.policy_boundary_tasks import (  # noqa: E402
    INSTANCES_PER_OFFSET,
    OFFSETS,
    expected_decision_for,
    offset_kind,
)


def _load(run_dir: Path) -> dict[str, Any]:
    report = json.loads((run_dir / "ood-report.json").read_text(encoding="utf-8"))
    assert isinstance(report, dict)
    return report


def _bar(value: float, width: int = 20) -> str:
    filled = round(value * width)
    return "█" * filled + "·" * (width - filled)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2

    runs = [(Path(path).name, _load(Path(path))) for path in argv]

    print(f"政策边界探针：每点 n={INSTANCES_PER_OFFSET}，95% CI 宽约 ±35pp")
    print(
        "负偏移 = 已过期（应拒绝）；0 = 恰好到期（政策判定为**放行**）；正偏移 = 窗口内（应放行）"
    )
    print()
    header = f"{'offset':>7s} {'应判':>4s}"
    for name, _ in runs:
        header += f"  {name[:22]:>22s}"
    print(header)

    for offset in OFFSETS:
        kind = offset_kind(offset)
        expected = "拒绝" if expected_decision_for(offset).value == "deny" else "放行"
        line = f"{offset:>+7d} {expected:>4s}"
        for _, report in runs:
            score = float(report["kind_success"].get(kind, float("nan")))
            line += f"  {_bar(score, 14)} {score:5.2f}"
        print(line)

    print()
    for name, report in runs:
        metrics = report["metrics"]
        print(
            f"{name}: 总分 {metrics['task_success']:.4f}  "
            f"政策违规 {metrics['policy_violation_count']}  "
            f"非法调用 {metrics['invalid_call_count']}  "
            f"逐类 {json.dumps(report['category_success'], ensure_ascii=False)}"
        )
        print(
            f"    失败构成 {json.dumps(metrics['failure_type_distribution'], ensure_ascii=False)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
