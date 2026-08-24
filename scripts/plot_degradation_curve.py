"""工具数退化曲线绘图脚本。

读取 degradation_summary.json，生成退化曲线 PNG 和汇总 CSV。

Usage:
    .venv/bin/python scripts/plot_degradation_curve.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "reports" / "retail_ops" / "v1" / "r10"
SUMMARY_PATH = REPORTS_DIR / "degradation_summary.json"
PLOT_PATH = REPORTS_DIR / "degradation_curve.png"
CSV_PATH = REPORTS_DIR / "degradation_curve.csv"

TOOL_COUNTS = [3, 6, 9, 12, 15]


def _load_data() -> dict:
    with SUMMARY_PATH.open() as f:
        return json.load(f)


def _extract_series(data: dict) -> tuple[dict, dict]:
    base = {"task_success": [], "tool_selection_accuracy": [], "pv": []}
    cand = {"task_success": [], "tool_selection_accuracy": [], "pv": []}

    for tc in TOOL_COUNTS:
        entry = data.get(str(tc), {})
        b = entry.get("base", {})
        base["task_success"].append(b.get("task_success"))
        base["tool_selection_accuracy"].append(b.get("tool_selection_accuracy"))
        base["pv"].append(b.get("policy_violation_count"))

        c = entry.get("candidate")
        if c:
            cand["task_success"].append(c.get("task_success"))
            cand["tool_selection_accuracy"].append(c.get("tool_selection_accuracy"))
            cand["pv"].append(c.get("policy_violation_count"))
        else:
            cand["task_success"].append(None)
            cand["tool_selection_accuracy"].append(None)
            cand["pv"].append(None)

    return base, cand


def _to_validated(arr: list[float | None]) -> tuple[np.ndarray, np.ndarray]:
    vals = np.array([v for v in arr if v is not None], dtype=float)
    mask = np.array([v is not None for v in arr])
    return vals, mask


def plot_degradation(base: dict, cand: dict) -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Noto Sans SC", "WenQuanYi Zen Hei", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "font.size": 11,
            "axes.labelsize": 13,
            "axes.titlesize": 15,
            "xtick.labelsize": 11,
            "ytick.labelsize": 11,
            "legend.fontsize": 11,
            "figure.dpi": 150,
            "savefig.dpi": 300,
            "savefig.bbox": "tight",
            "savefig.facecolor": "white",
        }
    )

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), constrained_layout=True)

    x = np.array(TOOL_COUNTS, dtype=float)

    # --- Left panel: task_success ---
    ax = axes[0]
    b_vals, b_mask = _to_validated(base["task_success"])
    b_x = x[b_mask]
    ax.plot(
        b_x,
        b_vals,
        "o-",
        color="#2563eb",
        linewidth=2,
        markersize=7,
        label="基座模型（Qwen3-4B）",
        zorder=3,
    )

    c_vals, c_mask = _to_validated(cand["task_success"])
    c_x = x[c_mask]
    if len(c_vals) > 0:
        ax.plot(
            c_x,
            c_vals,
            "s--",
            color="#dc2626",
            linewidth=2,
            markersize=7,
            label="候选模型（sft-008）",
            zorder=3,
        )

    ax.set_xlabel("工具数量")
    ax.set_ylabel("任务成功率")
    ax.set_title("任务成功率 vs 工具数量")
    ax.set_xticks(TOOL_COUNTS)
    ax.set_xlim(1, 17)
    ax.set_ylim(0, 1.05)
    ax.yaxis.set_major_locator(mticker.MultipleLocator(0.2))
    ax.yaxis.set_minor_locator(mticker.MultipleLocator(0.1))
    ax.grid(True, which="major", alpha=0.3, linestyle="--")
    ax.grid(True, which="minor", alpha=0.15, linestyle=":")
    ax.legend(loc="lower left", framealpha=0.9)

    # Annotate flat region
    if len(b_vals) >= 4:
        mid_x = np.mean(b_x[1:])
        ax.annotate(
            "退化曲线平坦\n（工具数非瓶颈）",
            xy=(mid_x, 0.45),
            xytext=(mid_x + 1.5, 0.65),
            fontsize=9,
            ha="center",
            arrowprops={"arrowstyle": "->", "color": "gray", "lw": 1},
            bbox={"boxstyle": "round,pad=0.3", "fc": "#fef9c3", "ec": "gray", "alpha": 0.8},
        )

    # --- Right panel: tool_selection_accuracy ---
    ax2 = axes[1]
    b_ta, b_ta_mask = _to_validated(base["tool_selection_accuracy"])
    b_ta_x = x[b_ta_mask]
    ax2.plot(
        b_ta_x, b_ta, "o-", color="#2563eb", linewidth=2, markersize=7, label="基座模型", zorder=3
    )

    c_ta, c_ta_mask = _to_validated(cand["tool_selection_accuracy"])
    c_ta_x = x[c_ta_mask]
    if len(c_ta) > 0:
        ax2.plot(
            c_ta_x,
            c_ta,
            "s--",
            color="#dc2626",
            linewidth=2,
            markersize=7,
            label="候选模型（sft-008）",
            zorder=3,
        )

    ax2.set_xlabel("工具数量")
    ax2.set_ylabel("工具选择准确率")
    ax2.set_title("工具选择准确率 vs 工具数量")
    ax2.set_xticks(TOOL_COUNTS)
    ax2.set_xlim(1, 17)
    ax2.set_ylim(0, 1.05)
    ax2.yaxis.set_major_locator(mticker.MultipleLocator(0.2))
    ax2.yaxis.set_minor_locator(mticker.MultipleLocator(0.1))
    ax2.grid(True, which="major", alpha=0.3, linestyle="--")
    ax2.grid(True, which="minor", alpha=0.15, linestyle=":")
    ax2.legend(loc="lower left", framealpha=0.9)

    fig.suptitle(
        "工具数退化曲线（Tool Count Degradation Curve）", fontsize=16, fontweight="bold", y=1.02
    )

    fig.savefig(PLOT_PATH, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"Plot saved to {PLOT_PATH}")


def write_csv(base: dict, cand: dict) -> None:
    with CSV_PATH.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "工具数量",
                "基座_任务成功率",
                "基座_工具选择准确率",
                "基座_策略违规数",
                "候选_任务成功率",
                "候选_工具选择准确率",
                "候选_策略违规数",
            ]
        )
        for i, tc in enumerate(TOOL_COUNTS):
            writer.writerow(
                [
                    tc,
                    base["task_success"][i] if base["task_success"][i] is not None else "",
                    base["tool_selection_accuracy"][i]
                    if base["tool_selection_accuracy"][i] is not None
                    else "",
                    base["pv"][i] if base["pv"][i] is not None else "",
                    cand["task_success"][i] if cand["task_success"][i] is not None else "",
                    cand["tool_selection_accuracy"][i]
                    if cand["tool_selection_accuracy"][i] is not None
                    else "",
                    cand["pv"][i] if cand["pv"][i] is not None else "",
                ]
            )
    print(f"CSV saved to {CSV_PATH}")


def main() -> None:
    data = _load_data()
    base, cand = _extract_series(data)
    plot_degradation(base, cand)
    write_csv(base, cand)


if __name__ == "__main__":
    main()
