"""演示用：从**已落盘的运行证据**里读出两组数，一组打脸另一组。

不重新计算、不重新评测——只读 `reports/` 下已有的 JSON。
证据文件缺失时明确说「未同步到本机」，不编造。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GO_RELEASE = REPO_ROOT / "reports/retail_ops/v1/r45b/formal-release-004-v10/release.json"
OOD_BASE = REPO_ROOT / "reports/retail_ops/v1/ood/base/ood-report.json"
OOD_CAND = REPO_ROOT / "reports/retail_ops/v1/ood/merged/ood-report.json"


def main() -> int:
    for path in (GO_RELEASE, OOD_BASE, OOD_CAND):
        if not path.is_file():
            print(f"证据未同步到本机：{path.relative_to(REPO_ROOT)}")
            return 1

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
    cand = json.loads(OOD_CAND.read_text(encoding="utf-8"))
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


if __name__ == "__main__":
    sys.exit(main())
