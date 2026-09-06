#!/usr/bin/env python
"""政策边界探针：三模型平移曲线对比图（面试可视化素材）。

数据来源与 `policy_boundary_curve.py` 完全相同——报告里现成的
`kind_success` 就是曲线，本脚本只做读取、排序与渲染，不重算任何指标。
指标由评测路径产出，脚本重算等于给同一个数造第二个来源。

三条曲线：
- 零训练基座（`reports/retail_ops/v1/policy-boundary/base`）
- `sft-008`（发布候选，`reports/retail_ops/v1/policy-boundary/sft-008`）
- `sft-008-dpo-001`（R11 DPO，判读修坏，`reports/retail_ops/v1/r11-dpo/probe-dpo-001`）

图要讲的一句话：DPO 把目标格 −14 校准到 1.00 的同时，放行侧 8 点塌回
零训练基座的形状——偏好压力被均匀施加到所有 refund 决策点（边界整体左移），
而不是被状态变量调制。

用法：

    .venv/bin/python scripts/ops/plot_policy_boundary_shift.py

输出（不进入任何判读，仅可视化素材）：
- `reports/retail_ops/v1/r11-dpo/probe_shift_curve.png`
- `reports/retail_ops/v1/r11-dpo/probe_shift_curve.csv`

边界：探针不封存、逐点 n=8（95% CI 宽约 ±35pp，足以看形状、不足以给单点排序），
读数不能用来声称发布结论。
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from veritool_rl.retail_ops.domain.policy_boundary_tasks import (  # noqa: E402
    offset_kind,
)

RUNS: list[tuple[str, Path, str, str]] = [
    ("零训练基座", REPO_ROOT / "reports/retail_ops/v1/policy-boundary/base", "#6b7280", "o"),
    (
        "sft-008（发布候选）",
        REPO_ROOT / "reports/retail_ops/v1/policy-boundary/sft-008",
        "#2563eb",
        "s",
    ),
    (
        "sft-008-dpo-001（R11，修坏）",
        REPO_ROOT / "reports/retail_ops/v1/r11-dpo/probe-dpo-001",
        "#dc2626",
        "D",
    ),
]

OUT_DIR = REPO_ROOT / "reports/retail_ops/v1/r11-dpo"
PNG_PATH = OUT_DIR / "probe_shift_curve.png"
CSV_PATH = OUT_DIR / "probe_shift_curve.csv"


def _load(run_dir: Path) -> dict[str, Any]:
    report = json.loads((run_dir / "ood-report.json").read_text(encoding="utf-8"))
    assert isinstance(report, dict)
    return report


def _style() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Noto Sans SC", "WenQuanYi Zen Hei", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "font.size": 11,
            "axes.labelsize": 12,
            "axes.titlesize": 13,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.fontsize": 10,
            "figure.dpi": 150,
            "savefig.dpi": 300,
            "savefig.bbox": "tight",
            "savefig.facecolor": "white",
        }
    )


def _plot_left(ax: plt.Axes, offsets: list[int], series: dict[str, list[float]]) -> None:
    deny = [o for o in offsets if o < 0]
    ax.axvspan(deny[0] - 1, 0, color="#fee2e2", alpha=0.5, zorder=0)
    ax.axvspan(0, offsets[-1] + 1, color="#dcfce7", alpha=0.5, zorder=0)
    ax.axvline(0, color="#374151", linewidth=1, linestyle="--", zorder=1)

    for label, _, color, marker in RUNS:
        ax.plot(
            offsets,
            series[label],
            marker=marker,
            color=color,
            linewidth=2,
            markersize=6,
            label=label,
            zorder=3,
        )

    ax.annotate(
        "sft-008 唯一失败格\n（−14 = 0.375）",
        xy=(-14, 0.375),
        xytext=(-11.5, 0.52),
        fontsize=9,
        ha="center",
        arrowprops={"arrowstyle": "->", "color": "#374151", "lw": 1},
        bbox={"boxstyle": "round,pad=0.3", "fc": "#fef9c3", "ec": "gray", "alpha": 0.85},
    )
    ax.annotate(
        "DPO 修好 −14（1.00），\n但放行侧 8 点塌回基座形状",
        xy=(7, 0.0),
        xytext=(2.0, 0.30),
        fontsize=9,
        ha="center",
        arrowprops={"arrowstyle": "->", "color": "#b91c1c", "lw": 1},
        bbox={"boxstyle": "round,pad=0.3", "fc": "#fee2e2", "ec": "#b91c1c", "alpha": 0.85},
    )

    ax.text(-7.5, 1.06, "已过期 → 应拒绝", ha="center", fontsize=10, color="#b91c1c")
    ax.text(7.5, 1.06, "窗口内 → 应放行", ha="center", fontsize=10, color="#15803d")

    ax.set_xlabel("offset（refund_deadline − current_day）")
    ax.set_ylabel("判定正确率（每点 n=8）")
    ax.set_title("三模型探针曲线：DPO 把边界整体推向拒绝侧")
    ax.set_xticks(offsets)
    ax.set_xticklabels([f"{o:+d}" if o else "0" for o in offsets], rotation=45)
    ax.set_ylim(-0.05, 1.13)
    ax.yaxis.set_major_locator(mticker.MultipleLocator(0.2))
    ax.grid(True, which="major", alpha=0.3, linestyle="--")
    ax.legend(loc="lower left", framealpha=0.9)


def _plot_right(ax: plt.Axes, offsets: list[int], series: dict[str, list[float]]) -> None:
    deltas = [
        d - s
        for d, s in zip(
            series["sft-008-dpo-001（R11，修坏）"],
            series["sft-008（发布候选）"],
            strict=True,
        )
    ]
    colors = ["#15803d" if v > 0 else "#b91c1c" if v < 0 else "#9ca3af" for v in deltas]
    ax.bar(range(len(offsets)), deltas, color=colors, alpha=0.85, zorder=3)
    ax.axhline(0, color="#374151", linewidth=1)
    ax.set_xticks(range(len(offsets)))
    ax.set_xticklabels([f"{o:+d}" if o else "0" for o in offsets], rotation=45)
    ax.set_xlabel("offset")
    ax.set_ylabel("Δ（dpo-001 − sft-008）")
    ax.set_title("逐点差值：收益只有 −14 一格，代价是放行侧")
    ax.set_ylim(-1.15, 0.85)
    ax.yaxis.set_major_locator(mticker.MultipleLocator(0.2))
    ax.grid(True, which="major", alpha=0.3, linestyle="--", axis="y")
    for i, v in enumerate(deltas):
        if v:
            ax.text(i, v + (0.04 if v > 0 else -0.09), f"{v:+.2f}", ha="center", fontsize=8)


def _write_csv(
    offsets: list[int], series: dict[str, list[float]], reports: dict[str, dict[str, Any]]
) -> None:
    with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["offset", "应判"]
            + [f"{label}_判定正确率" for label, *_ in RUNS]
            + ["Δ(dpo001−sft008)"]
        )
        for i, offset in enumerate(offsets):
            expected = "拒绝" if offset < 0 else "放行"
            row = [offset, expected] + [series[label][i] for label, *_ in RUNS]
            row.append(row[-1] - row[-2])
            writer.writerow(row)
        writer.writerow([])
        writer.writerow(["汇总"] + [""] * (2 + len(RUNS)))
        for label, _, _, _ in RUNS:
            m = reports[label]["metrics"]
            writer.writerow(
                [
                    label,
                    f"总分 {m['task_success']:.4f}",
                    f"政策违规 {m['policy_violation_count']}",
                    f"失败构成 {json.dumps(m['failure_type_distribution'], ensure_ascii=False)}",
                ]
            )


def main() -> int:
    _style()
    offsets = [-14, -10, -7, -5, -3, -2, -1, 0, 1, 2, 3, 5, 7, 10, 14]
    reports = {label: _load(path) for label, path, _, _ in RUNS}
    series = {
        label: [float(reports[label]["kind_success"][offset_kind(o)]) for o in offsets]
        for label, _, _, _ in RUNS
    }

    fig, axes = plt.subplots(1, 2, figsize=(14, 5.6), constrained_layout=True)
    _plot_left(axes[0], offsets, series)
    _plot_right(axes[1], offsets, series)
    fig.suptitle(
        "政策边界探针三模型对比（base / sft-008 / dpo-001）——探针不封存，读数不用于发布判定",
        fontsize=14,
        fontweight="bold",
        y=1.03,
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(PNG_PATH, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    _write_csv(offsets, series, reports)
    print(f"PNG saved to {PNG_PATH}")
    print(f"CSV saved to {CSV_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
