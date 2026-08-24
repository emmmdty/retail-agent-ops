"""Task 1d: v1.2 门禁 dry-run——用 ood_sealed 读数做完整发布判定。

在 GPU 服务器上执行：
  python scripts/task1d_ood_gate_dryrun.py
"""

from __future__ import annotations

import json
from pathlib import Path

from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.evaluate.sealed_evaluation import (
    SealedEvaluationReport,
    sealed_content_id,
)
from veritool_rl.retail_ops.release.formal_release import (
    decide_formal_release,
    write_formal_release_report,
)

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = ROOT / "domains/retail_ops/v1"


def _load_sealed(path: Path) -> SealedEvaluationReport:
    report = SealedEvaluationReport.model_validate_json(path.read_text(encoding="utf-8"))
    expected = sealed_content_id(report)
    if report.report_id != expected:
        raise ValueError(f"report_id mismatch: {report.report_id} != {expected}")
    return report


def main() -> None:
    # 1. 加载 sealed holdout 报告（观测 5 的 base + sft-008 merged candidate）
    base_path = ROOT / "reports/retail_ops/v1/r6/holdout-base-005/sealed-report.json"
    cand_path = ROOT / "reports/retail_ops/v1/r6/holdout-merged-candidate-005/sealed-report.json"

    if not base_path.exists() or not cand_path.exists():
        print("ERROR: sealed holdout reports not found")
        print(f"  base: {base_path} exists={base_path.exists()}")
        print(f"  cand: {cand_path} exists={cand_path.exists()}")
        return

    base = _load_sealed(base_path)
    candidate = _load_sealed(cand_path)
    print(f"Loaded base: task_success={base.metrics['task_success']:.4f}")
    print(f"Loaded candidate: task_success={candidate.metrics['task_success']:.4f}")

    # 2. 加载 ood_sealed 评测结果
    ood_base_path = ROOT / "reports/retail_ops/v1/ood-v2.2/sealed/base/ood-report.json"
    ood_cand_path = ROOT / "reports/retail_ops/v1/ood-v2.2/sealed/sft-008/ood-report.json"

    if not ood_base_path.exists() or not ood_cand_path.exists():
        print("ERROR: ood_sealed eval reports not found")
        return

    ood_base = json.loads(ood_base_path.read_text(encoding="utf-8"))
    ood_cand = json.loads(ood_cand_path.read_text(encoding="utf-8"))
    ood_base_metrics = ood_base.get("metrics", {})
    ood_cand_metrics = ood_cand.get("metrics", {})
    print(f"OOD base: task_success={ood_base_metrics.get('task_success'):.4f}")
    print(f"OOD candidate: task_success={ood_cand_metrics.get('task_success'):.4f}")

    # 3. 加载策略配置
    policy = load_bundle(BUNDLE_DIR).release

    # 4. 用 v1.2 门禁做发布判定
    report = decide_formal_release(
        base,
        candidate,
        policy,
        gate_schema_version="1.2",
        ood_evidence=(ood_base_metrics, ood_cand_metrics),
    )

    # 5. 输出结果
    print(f"\n{'=' * 60}")
    print(f"v1.2 Release Decision: {report.decision.value}")
    print(f"Deployment: {report.deployment}")
    print(f"Schema: {report.schema_version}")
    print(f"OOD task_success: {report.ood_task_success}")
    print(f"Base OOD task_success: {report.base_ood_task_success}")
    print("\nGate results:")
    for gate in report.gates:
        status = "PASS" if gate.passed else "FAIL"
        print(f"  [{status}] {gate.gate_id}: observed={gate.observed}, threshold={gate.threshold}")
    print(f"\nFailed gates: {report.failed_gate_ids}")

    # 6. 写出报告
    output_dir = ROOT / "reports/retail_ops/v1/r10/ood-sealed-v12"
    write_formal_release_report(report, output_dir)
    print(f"\nReport written to {output_dir}")


if __name__ == "__main__":
    main()
