"""演示用：把一个故意做坏的候选送进发布门禁，把逐条门禁打印出来。

这是整个项目最值得看的一件事——**门禁真的会拒绝**。用 R1 qualification 轨道
（纯 CPU、合成任务、不碰 holdout）跑一遍 `build → evaluate ×2 → release`，
候选侧用 `fault` 策略（刻意产生非法调用与政策违规）。

产物写进临时目录，跑完即删；不污染 `reports/`。
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / ".venv" / "bin" / "retail-agent-ops"
CONFIGS = REPO_ROOT / "configs" / "retail_ops"


def _fmt(value: object) -> str:
    return f"{value:.4f}" if isinstance(value, float) else str(value)


def _run(*args: str) -> None:
    subprocess.run([str(CLI), *args], cwd=REPO_ROOT, check=True, capture_output=True, timeout=900)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _run(
            "build",
            "--config",
            str(CONFIGS / "build/retail_ops_v1_build.yaml"),
            "--seed",
            "0",
            "--output_dir",
            str(root / "build"),
        )
        for name in ("base", "fault"):
            _run(
                "evaluate",
                "--config",
                str(CONFIGS / f"evaluate/retail_ops_v1_qualification_{name}.yaml"),
                "--seed",
                "0",
                "--input_dir",
                str(root / "build"),
                "--output_dir",
                str(root / name),
            )
        _run(
            "release",
            "--config",
            str(CONFIGS / "release/retail_ops_v1_release.yaml"),
            "--seed",
            "0",
            "--baseline_dir",
            str(root / "base"),
            "--candidate_dir",
            str(root / "fault"),
            "--output_dir",
            str(root / "release"),
        )
        report = json.loads((root / "release" / "release.json").read_text(encoding="utf-8"))

    print(f"{'门禁':<26}{'观测':>12}{'阈值':>12}   结果")
    print("-" * 62)
    for gate in report["gates"]:
        mark = "PASS" if gate["passed"] else "FAIL  <<<"
        print(
            f"{gate['gate_id']:<26}{_fmt(gate['observed']):>12}"
            f"{_fmt(gate['threshold']):>12}   {mark}"
        )
    print("-" * 62)
    print(f"判定：{report['decision']} / deployment={report['deployment']}")
    print(f"失败门禁：{report['failed_gate_ids']}")
    print("服务据此加载冻结基座，adapter_loaded=false，可在 /health 核对。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
