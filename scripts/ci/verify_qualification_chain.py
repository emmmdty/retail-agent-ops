"""CPU 全链路复现校验：`build → evaluate ×3 → release ×2`。

`SPEC.md` §11 声称"新环境能按文档完成 CPU smoke"，在 2026-08-15 之前没有任何
自动化在证明这句话。这个脚本就是那个证明：它跑 README 里逐字相同的六条命令，
然后断言产出的 **决策与内容哈希**等于本文件里冻结的期望值。

为什么断言哈希而不只断言"命令退出码为 0"：本项目的核心主张是"同一份输入
逐字节可复现"。退出码为 0 只说明没崩，`bundle_sha256` / `task_manifest_sha256`
与确定性指标相等才说明链条真的没漂。断言范围的边界见下方 `EXPECTED` 的注释。

用法（仓库根目录）：

    .venv/bin/python scripts/ci/verify_qualification_chain.py

不接受任何参数；产物写进临时目录，不污染 `reports/`。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

#: R1 qualification 轨道的冻结期望值。这些数字来自 2026-07-21 的首次正式运行，
#: 此后每次代码改动都必须让它们保持不变；变了就说明确定性链条断了，而不是
#: "把期望值改一下就好"。
#:
#: **不断言 `run_id`**：它是 `RunEvidence` 的全字段自哈希，而 `metrics` 里含
#: p50/p95 延迟与 token 计数，是机器相关的。`run_id` 因此只保证"同一份证据文件
#: 没被改过"，不保证跨机器可复现——这条区分必须写清楚，否则 CI 会把一台更快的
#: 机器报成"链条漂移"。跨机器可复现的是**内容哈希与确定性指标**，下面断言的正是它们。
EXPECTED = {
    "bundle_sha256": "8c158a3068731e7015adfde790f9917ddb924fcd5243195a9640c833cca20eeb",
    "task_manifest_sha256": "6f510a699c33a5ec9c7df3ef4310a36165b4acff270425b6bfc8c6fd39124f6e",
    "go": {
        "decision": "GO",
        "deployment": "candidate",
        "failed_gate_ids": [],
    },
    "no_go": {
        "decision": "NO-GO",
        "deployment": "baseline",
        "failed_gate_ids": ["success_delta", "invalid_call_count"],
    },
}

#: 与延迟/token 无关、必须逐位复现的指标。基座那一侧在两份报告里必须完全相同
#: （同一次运行的证据被配对了两次）。
DETERMINISTIC_METRICS = ("task_success", "policy_violation_count", "invalid_call_count")

EXPECTED_METRICS = {
    "baseline": {
        "task_success": 8 / 12,
        "policy_violation_count": 0,
        "invalid_call_count": 0,
    },
    "go_candidate": {
        "task_success": 1.0,
        "policy_violation_count": 0,
        "invalid_call_count": 0,
    },
    "no_go_candidate": {
        "task_success": 0.0,
        "policy_violation_count": 0,
        "invalid_call_count": 50,
    },
}

GATE_IDS = (
    "success_delta",
    "policy_violation_delta",
    "invalid_call_count",
    "p95_latency_ratio",
    "evidence_complete",
)


class ChainError(AssertionError):
    """链路校验失败；消息里带上实际值，便于直接判断是漂移还是环境问题。"""


def _run(command: list[str]) -> None:
    result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        raise ChainError(
            f"命令失败（exit={result.returncode}）：{' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


def _cli() -> list[str]:
    """用与 README 相同的 console script；它不存在时说明环境没装好，直接失败。"""
    executable = Path(sys.executable).parent / "retail-agent-ops"
    if not executable.is_file():
        raise ChainError(f"未找到 retail-agent-ops 命令：{executable}（先跑 uv sync）")
    return [str(executable)]


def _equal(label: str, actual: object, expected: object) -> None:
    if actual != expected:
        raise ChainError(f"{label} 漂移：actual={actual!r} expected={expected!r}")


def run_chain(out: Path) -> dict[str, dict[str, Any]]:
    """跑完六条命令并返回两份 release 报告。"""
    build = out / "build"
    base = out / "base"
    oracle = out / "oracle"
    fault = out / "fault"
    release_go = out / "release-go"
    release_no_go = out / "release-no-go"

    _run(
        [
            *_cli(),
            "build",
            "--config",
            "configs/retail_ops/build/retail_ops_v1_build.yaml",
            "--seed",
            "0",
            "--output_dir",
            str(build),
        ]
    )
    for config, output in (
        ("retail_ops_v1_qualification_base.yaml", base),
        ("retail_ops_v1_qualification_oracle.yaml", oracle),
        ("retail_ops_v1_qualification_fault.yaml", fault),
    ):
        _run(
            [
                *_cli(),
                "evaluate",
                "--config",
                f"configs/retail_ops/evaluate/{config}",
                "--seed",
                "0",
                "--input_dir",
                str(build),
                "--output_dir",
                str(output),
            ]
        )
    for candidate, output in ((oracle, release_go), (fault, release_no_go)):
        _run(
            [
                *_cli(),
                "release",
                "--config",
                "configs/retail_ops/release/retail_ops_v1_release.yaml",
                "--seed",
                "0",
                "--baseline_dir",
                str(base),
                "--candidate_dir",
                str(candidate),
                "--output_dir",
                str(output),
            ]
        )

    manifest_sha = hashlib.sha256((build / "manifest.json").read_bytes()).hexdigest()
    _equal("task_manifest_sha256（重新计算）", manifest_sha, EXPECTED["task_manifest_sha256"])
    return {
        "go": json.loads((release_go / "release.json").read_text(encoding="utf-8")),
        "no_go": json.loads((release_no_go / "release.json").read_text(encoding="utf-8")),
    }


def _deterministic(metrics: dict[str, Any]) -> dict[str, Any]:
    return {name: metrics[name] for name in DETERMINISTIC_METRICS}


def verify(reports: dict[str, dict[str, Any]]) -> None:
    for key in ("go", "no_go"):
        report = reports[key]
        expected = EXPECTED[key]
        assert isinstance(expected, dict)
        _equal(f"{key}.decision", report["decision"], expected["decision"])
        _equal(f"{key}.deployment", report["deployment"], expected["deployment"])
        _equal(f"{key}.failed_gate_ids", report["failed_gate_ids"], expected["failed_gate_ids"])
        _equal(f"{key}.bundle_sha256", report["bundle_sha256"], EXPECTED["bundle_sha256"])
        _equal(
            f"{key}.task_manifest_sha256",
            report["task_manifest_sha256"],
            EXPECTED["task_manifest_sha256"],
        )
        _equal(
            f"{key}.gate_ids",
            tuple(gate["gate_id"] for gate in report["gates"]),
            GATE_IDS,
        )
        _equal(
            f"{key}.baseline_metrics",
            _deterministic(report["baseline_metrics"]),
            EXPECTED_METRICS["baseline"],
        )
        _equal(
            f"{key}.candidate_metrics",
            _deterministic(report["candidate_metrics"]),
            EXPECTED_METRICS[f"{key}_candidate"],
        )
        _equal(f"{key}.run_id 形态", len(report["baseline_run_id"]), 64)

    # 两份报告共用同一个 baseline：证明配对比较真的用了同一次运行的证据，
    # 而不是各自跑了一次基座。
    _equal(
        "两份 release 报告的 baseline_run_id",
        reports["go"]["baseline_run_id"],
        reports["no_go"]["baseline_run_id"],
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="retail-agent-ops-ci-") as tmp:
        reports = run_chain(Path(tmp))
        verify(reports)
    print("CPU qualification 全链路复现校验通过：决策与内容哈希均与冻结期望一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
