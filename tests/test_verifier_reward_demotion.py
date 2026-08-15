"""P2-10：`verifier_reward` 降级为诊断量。

它已**三次**与主判据反向（R3 dev、封存 holdout、R4 dev），却一直和 `task_success`
并排出现在报告的同一张表里。"知道它是错的但保留原样"是最差的状态——读报告的人
没有任何信号知道这一列不能用来选候选。

**只改呈现层。** `core/rewards/verifier.py` 的计算、`core/metrics.py` 产出的
`metrics` 字典、以及 `release.json` 里的 `base_metrics`/`candidate_metrics` 全部
逐字节不变——改计算会动 trajectory 字段并牵连已有产物的可重放性。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from veritool_rl.core.metrics import DIAGNOSTIC_METRICS, DIAGNOSTIC_NOTE
from veritool_rl.retail_ops.release.release import (
    GATE_IDS,
    GateResult,
    ReleaseDecision,
    ReleaseReport,
    write_release_report,
)


def _metrics(success: float, reward: float) -> dict[str, Any]:
    return {
        "task_success": success,
        "policy_violation_count": 0,
        "invalid_call_count": 0,
        "p95_latency_ms": 1000.0,
        "verifier_reward": reward,
        "average_tool_calls": 1.5,
    }


def _release_report() -> ReleaseReport:
    gates = [
        GateResult(
            gate_id=gate_id,
            passed=True,
            observed=0,
            threshold=0,
            reason="测试用门禁结果。",
        )
        for gate_id in GATE_IDS
    ]
    return ReleaseReport(
        decision=ReleaseDecision.GO,
        baseline_run_id="a" * 64,
        candidate_run_id="b" * 64,
        baseline_policy="baseline",
        candidate_policy="oracle",
        bundle_sha256="c" * 64,
        task_manifest_sha256="d" * 64,
        deployment="candidate",
        gates=gates,
        failed_gate_ids=[],
        baseline_metrics=_metrics(0.60, 0.90),
        candidate_metrics=_metrics(0.50, 0.99),
    )


def test_diagnostic_metric_set_names_verifier_reward() -> None:
    assert "verifier_reward" in DIAGNOSTIC_METRICS
    assert "task_success" not in DIAGNOSTIC_METRICS
    assert "三次" in DIAGNOSTIC_NOTE
    assert "不得用作候选选择依据" in DIAGNOSTIC_NOTE


def test_release_markdown_keeps_verifier_reward_out_of_the_headline_table(
    tmp_path: Path,
) -> None:
    write_release_report(_release_report(), tmp_path / "release")

    markdown = (tmp_path / "release" / "report.md").read_text(encoding="utf-8")
    headline, _, diagnostics = markdown.partition("## 诊断量")

    assert diagnostics, "报告必须有独立的诊断量分区"
    assert "verifier_reward" not in headline, "verifier_reward 不得出现在主指标表"
    assert "verifier_reward" in diagnostics
    assert DIAGNOSTIC_NOTE in diagnostics
    assert "task_success" in headline, "主判据必须留在主表"


def test_release_html_keeps_verifier_reward_out_of_the_headline_table(tmp_path: Path) -> None:
    write_release_report(_release_report(), tmp_path / "release")

    page = (tmp_path / "release" / "report.html").read_text(encoding="utf-8")
    headline, _, diagnostics = page.partition("诊断量")

    assert diagnostics
    assert "verifier_reward" not in headline
    assert "verifier_reward" in diagnostics
    assert DIAGNOSTIC_NOTE in diagnostics


def test_release_json_still_carries_the_full_metric_dict(tmp_path: Path) -> None:
    """降级只在呈现层：机器可读证据一个字段都不能少，否则旧产物不再可比。"""
    write_release_report(_release_report(), tmp_path / "release")

    payload = json.loads((tmp_path / "release" / "release.json").read_text(encoding="utf-8"))

    assert payload["baseline_metrics"] == _metrics(0.60, 0.90)
    assert payload["candidate_metrics"] == _metrics(0.50, 0.99)


def test_metrics_computation_is_unchanged() -> None:
    """`compute_metrics` 仍然产出 verifier_reward——降级的是呈现，不是计算。"""
    from veritool_rl.core.metrics import compute_metrics

    empty = compute_metrics([], bootstrap_samples=8, seed=0)

    assert "verifier_reward" in empty


def test_aggregate_comparison_rows_separate_the_diagnostic(tmp_path: Path) -> None:
    """`core/reporting.py` 的逐任务配对行也要把它挪进 diagnostics 子对象。"""
    from veritool_rl.core.agent.policy import OraclePolicy, PolicyOutput
    from veritool_rl.core.agent.runner import run_episode
    from veritool_rl.core.artifacts import write_json, write_jsonl, write_yaml
    from veritool_rl.core.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits
    from veritool_rl.core.metrics import compute_metrics
    from veritool_rl.core.reporting import aggregate_runs

    class FinalOnlyPolicy:
        name = "final-only"

        def respond(self, messages: list[dict[str, Any]], tools: list[Any]) -> PolicyOutput:
            del messages, tools
            return PolicyOutput(raw_text="无法处理", final_response="无法处理")

    tasks = build_mvp_task_splits(seed=0)["test"][:4]
    baseline = [run_episode(task, MiniRetailEnv, FinalOnlyPolicy(), seed=0) for task in tasks]
    adapter = [run_episode(task, MiniRetailEnv, OraclePolicy(task), seed=0) for task in tasks]
    baseline_dir = tmp_path / "baseline"
    adapter_dir = tmp_path / "adapter"
    for directory, trajectories in ((baseline_dir, baseline), (adapter_dir, adapter)):
        write_jsonl(
            directory / "trajectories.jsonl",
            (trajectory.model_dump(mode="json") for trajectory in trajectories),
        )
        write_json(directory / "metrics.json", compute_metrics(trajectories, 20, 0))
    baseline_config = {
        "environment": "mini_retail",
        "policy": {"type": "qwen", "model_name": "models/Qwen3-1.7B"},
    }
    write_yaml(baseline_dir / "config.yaml", baseline_config)
    write_yaml(
        adapter_dir / "config.yaml",
        {
            **baseline_config,
            "policy": {**baseline_config["policy"], "adapter_path": "reports/x/adapter"},
        },
    )

    summary = aggregate_runs(
        baseline_dir,
        adapter_dir,
        tmp_path / "out",
        {"bootstrap_samples": 8},
        seed=0,
    )

    rows = [
        json.loads(line)
        for line in (tmp_path / "out" / "comparison.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows
    for row in rows:
        assert "baseline_verifier_reward" not in row
        assert "adapter_verifier_reward" not in row
        assert set(row["diagnostics"]) == {"baseline_verifier_reward", "adapter_verifier_reward"}
    assert summary["diagnostics_note"] == DIAGNOSTIC_NOTE
