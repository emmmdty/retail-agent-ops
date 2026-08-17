"""演示用：从**已落盘的运行证据**里读出两组数，一组打脸另一组。

不重新计算、不重新评测——只读 `reports/` 下已有的 JSON。
证据文件缺失时明确说「未同步到本机」，不编造。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
GO_RELEASE = REPO_ROOT / "reports/retail_ops/v1/r45b/formal-release-004-v10/release.json"
OOD_BASE = REPO_ROOT / "reports/retail_ops/v1/ood/base/ood-report.json"
OOD_CAND = REPO_ROOT / "reports/retail_ops/v1/ood/merged/ood-report.json"
SEALED = {
    "零训练基座": REPO_ROOT / "reports/retail_ops/v1/r6/oodv21-sealed-base/ood-report.json",
    "旧候选": REPO_ROOT / "reports/retail_ops/v1/r6/oodv21-sealed-sft006/ood-report.json",
    "新候选": REPO_ROOT / "reports/retail_ops/v1/r6/oodv21-sealed-sft008/ood-report.json",
}
GATE5 = REPO_ROOT / "reports/retail_ops/v1/r6/formal-release-005-v11/release.json"
TRANSFER = REPO_ROOT / "reports/retail_ops/v1/r6/oodv1-sft008/ood-report.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # 拆成两段是为了让每一段都能在一屏里读完，不是为了把坏消息藏到第二屏——
    # 第一段的最后两行就是那条打脸的读数。
    parser.add_argument("--section", choices=("gate", "fix"), default="gate")
    args = parser.parse_args()

    for path in (GO_RELEASE, OOD_BASE, OOD_CAND):
        if not path.is_file():
            print(f"证据未同步到本机：{path.relative_to(REPO_ROOT)}")
            return 1

    cand = json.loads(OOD_CAND.read_text(encoding="utf-8"))
    if args.section == "fix":
        return _print_fix(cand)

    release = json.loads(GO_RELEASE.read_text(encoding="utf-8"))
    print("封存 120 条 holdout｜第四次观测（合并部署形态）")
    for gate in release["gates"]:
        mark = "PASS" if gate["passed"] else "FAIL"
        observed = gate["observed"]
        shown = f"{observed:.4f}" if isinstance(observed, float) else str(observed)
        print(f"  {gate['gate_id']:<24}{shown:>10}   {mark}")
    print(f"  -> 判定 {release['decision']} / {release['deployment']}   本项目第一个 GO")
    print()

    base = json.loads(OOD_BASE.read_text(encoding="utf-8"))
    print("同一个候选，换到分布外任务集（模板外 60 条）")
    print(f"  {'类别':<20}{'零训练基座':>12}{'该候选':>10}")
    for key in sorted(base["category_success"]):
        print(
            f"  {key:<20}{base['category_success'][key]:>12.2f}"
            f"{cand['category_success'][key]:>10.2f}"
        )
    print(
        f"  {'总计':<20}{base['metrics']['final_state_success']:>12.4f}"
        f"{cand['metrics']['final_state_success']:>10.4f}"
    )
    print()
    print("  expression_ood 0.00：换个说法就全灭，比不训练还差。")
    print("  120/120 不是泛化——这一条是项目自己测出来的，且有测试强制它与 GO 成对出现。")
    return 0


def _print_fix(cand: dict[str, Any]) -> int:
    if not all(path.is_file() for path in (*SEALED.values(), TRANSFER)):
        print("R6 证据未同步到本机，跳过。")
        return 0

    print("然后把它修好了：措辞增强 + 只观测一次的封存分片")
    for label, path in SEALED.items():
        d = json.loads(path.read_text(encoding="utf-8"))
        print(f"  {label:<12}{d['metrics']['final_state_success']:>10.4f}")
    transfer = json.loads(TRANSFER.read_text(encoding="utf-8"))
    print()
    print("独立迁移检查（作者手写、生成过程不同、从未用于选择）")
    print(
        f"  expression_ood  旧候选 {cand['category_success']['expression_ood']:.2f}"
        f"  ->  新候选 {transfer['category_success']['expression_ood']:.2f}"
    )
    print()
    if GATE5.is_file():
        gate = json.loads(GATE5.read_text(encoding="utf-8"))
        print()
        print(f"它也通过了发布门禁（第五次、最后一次封存 holdout 观测）：{gate['decision']}")
        print(f"  失败门禁 {gate['failed_gate_ids']}，两套口径都是 GO")
    print()
    print("代价：模型变得更倾向执行，于是不该动手时也动手")
    print("  封存 holdout 上 117/120，且有 2 次政策违规（旧候选那次是 120/120、0 违规）")
    print(
        f"  做不到的请求一类 {cand['category_success']['scenario_ood']:.2f}"
        f" -> {transfer['category_success']['scenario_ood']:.2f}"
    )
    print("  收益与代价来自同一个改动，不能只报一半。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
