"""RetailOps v1 CPU-only qualification 纵向切片验收。"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from veritool_rl.product_cli import main
from veritool_rl.retail_ops.serve.service import create_app


def _run_cli(arguments: list[str]) -> None:
    assert main(arguments) == 0


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_retail_ops_v1_cpu_vertical_slice(tmp_path: Path) -> None:
    build_dir = tmp_path / "build"
    base_dir = tmp_path / "base"
    oracle_dir = tmp_path / "oracle"
    fault_dir = tmp_path / "fault"
    go_dir = tmp_path / "release-go"
    no_go_dir = tmp_path / "release-no-go"

    _run_cli(
        [
            "build",
            "--config",
            "configs/retail_ops/build/retail_ops_v1_build.yaml",
            "--seed",
            "0",
            "--output_dir",
            str(build_dir),
        ]
    )
    for config, output in (
        ("configs/retail_ops/evaluate/retail_ops_v1_qualification_base.yaml", base_dir),
        ("configs/retail_ops/evaluate/retail_ops_v1_qualification_oracle.yaml", oracle_dir),
        ("configs/retail_ops/evaluate/retail_ops_v1_qualification_fault.yaml", fault_dir),
    ):
        _run_cli(
            [
                "evaluate",
                "--config",
                config,
                "--seed",
                "0",
                "--input_dir",
                str(build_dir),
                "--output_dir",
                str(output),
            ]
        )
    for candidate, output in ((oracle_dir, go_dir), (fault_dir, no_go_dir)):
        _run_cli(
            [
                "release",
                "--config",
                "configs/retail_ops/release/retail_ops_v1_release.yaml",
                "--seed",
                "0",
                "--baseline_dir",
                str(base_dir),
                "--candidate_dir",
                str(candidate),
                "--output_dir",
                str(output),
            ]
        )

    # 这三个值是**端到端黄金锚**，不是可推导的规格值（7.2 §3.4 审查结论的保留理由）：
    # 它们把「build → evaluate → release 全链路 + 环境/verifier/门禁语义」钉在一次
    # 快照上。环境行为变化让它们变红时，失败是**故意的**——必须人工确认这是进步
    # 还是回归，再 consciously 更新锚值；失败消息会指向这条说明。
    base_success = _read_json(base_dir / "metrics.json")["task_success"]
    assert base_success == 8 / 12, (
        f"端到端黄金锚移动：base task_success {base_success} != 8/12。"
        "若是环境/verifier 的有意变更，请更新本锚值并在 progress.md 记录；"
        "否则这是回归。"
    )
    assert _read_json(oracle_dir / "metrics.json")["task_success"] == 1.0
    assert _read_json(fault_dir / "metrics.json")["task_success"] == 0.0
    assert _read_json(go_dir / "release.json")["decision"] == "GO"
    assert _read_json(no_go_dir / "release.json")["decision"] == "NO-GO"
    for release_dir in (go_dir, no_go_dir):
        assert {path.name for path in release_dir.iterdir()} == {
            "release.json",
            "report.html",
            "report.md",
        }

    go_health = TestClient(create_app(go_dir, Path("domains/retail_ops/v1"), build_dir)).get(
        "/health"
    )
    no_go_health = TestClient(create_app(no_go_dir, Path("domains/retail_ops/v1"), build_dir)).get(
        "/health"
    )
    assert go_health.json()["deployment"] == "candidate"
    assert no_go_health.json()["deployment"] == "baseline"

    for release_dir in (go_dir, no_go_dir):
        public_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(release_dir.iterdir())
            if path.suffix in {".json", ".md", ".html"}
        )
        for forbidden in ("target_state", "expected_calls", "user_request"):
            assert forbidden not in public_text
