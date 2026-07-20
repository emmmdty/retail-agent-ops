"""BFCL 固定 holdout 的 base/SFT 配对比较与真实失败分析。"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from veritool_rl.artifacts import sha256_file, write_json, write_jsonl, write_yaml
from veritool_rl.data.bfcl import BFCL_CATEGORIES, BfclManifest
from veritool_rl.eval.bfcl import BfclOfficialScore, load_official_scores

BFCL_MODEL_NAME = "Qwen/Qwen3-1.7B-FC"
CONCLUSION = (
    "Qwen3-1.7B 在项目定义的 BFCL V4 非重叠公开数据划分上进行 QLoRA-SFT 后，"
    "在固定 200 条单轮 AST holdout 子集上的结果。"
)


def aggregate_bfcl_runs(
    *,
    baseline_dir: Path,
    sft_dir: Path,
    manifest_path: Path,
    output_dir: Path,
    bootstrap_samples: int,
    seed: int,
    benchmark_sensitive_ids: set[str],
) -> dict[str, Any]:
    """严格配对 base/SFT 200 条官方结果并生成审计产物。"""
    if seed != 0:
        raise ValueError("BFCL 配对比较只允许 seed 0")
    if bootstrap_samples != 10_000:
        raise ValueError("BFCL 配对比较固定使用 10000 次 bootstrap")
    manifest = BfclManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    if manifest.seed != 0 or manifest.quotas != dict.fromkeys(BFCL_CATEGORIES, 50):
        raise ValueError("BFCL 配对 manifest 必须是 seed 0 且四类各 50 条")
    expected_ids = [item.task_id for item in manifest.tasks]
    if len(expected_ids) != 200 or len(set(expected_ids)) != 200:
        raise ValueError("BFCL 配对 manifest 必须恰好包含 200 个唯一 task_id")
    expected_by_category = {
        category: [
            item.task_id for item in manifest.tasks if item.category == category
        ]
        for category in BFCL_CATEGORIES
    }
    manifest_sha256 = sha256_file(manifest_path)
    _validate_run_manifest(
        _read_json(baseline_dir / "manifest.json"),
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        expected_ids=expected_ids,
        label="base",
    )
    _validate_run_manifest(
        _read_json(sft_dir / "manifest.json"),
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        expected_ids=expected_ids,
        label="SFT",
    )
    _validate_fair_configs(
        _read_yaml(baseline_dir / "resolved_config.yaml"),
        _read_yaml(sft_dir / "resolved_config.yaml"),
    )
    baseline_raw = _load_raw_generations(
        baseline_dir / "raw_generations.jsonl",
        expected_ids,
    )
    sft_raw = _load_raw_generations(
        sft_dir / "raw_generations.jsonl",
        expected_ids,
    )
    baseline_scores = load_official_scores(
        baseline_dir / "official_scores",
        BFCL_MODEL_NAME,
        expected_by_category,
    )
    sft_scores = load_official_scores(
        sft_dir / "official_scores",
        BFCL_MODEL_NAME,
        expected_by_category,
    )
    baseline_failures = _load_failures(
        baseline_dir / "failures.jsonl",
        _failure_ids(baseline_scores),
    )
    sft_failures = _load_failures(
        sft_dir / "failures.jsonl",
        _failure_ids(sft_scores),
    )
    _validate_metrics(
        _read_json(baseline_dir / "metrics.json"),
        baseline_scores,
        "base",
    )
    _validate_metrics(
        _read_json(sft_dir / "metrics.json"),
        sft_scores,
        "SFT",
    )

    baseline_failure_ids = set(baseline_failures)
    sft_failure_ids = set(sft_failures)
    comparison_rows: list[dict[str, Any]] = []
    outcomes = {"improved": 0, "regressed": 0, "unchanged": 0}
    deltas: list[float] = []
    for item in manifest.tasks:
        baseline_success = item.task_id not in baseline_failure_ids
        sft_success = item.task_id not in sft_failure_ids
        if not baseline_success and sft_success:
            outcome = "improved"
        elif baseline_success and not sft_success:
            outcome = "regressed"
        else:
            outcome = "unchanged"
        outcomes[outcome] += 1
        delta = float(sft_success) - float(baseline_success)
        deltas.append(delta)
        comparison_rows.append(
            {
                "task_id": item.task_id,
                "category": item.category,
                "baseline_success": baseline_success,
                "sft_success": sft_success,
                "outcome": outcome,
                "benchmark_sensitive": item.task_id in benchmark_sensitive_ids,
            }
        )

    baseline_correct = len(expected_ids) - len(baseline_failure_ids)
    sft_correct = len(expected_ids) - len(sft_failure_ids)
    summary = {
        "paired_tasks": len(expected_ids),
        "outcomes": outcomes,
        "baseline_correct_count": baseline_correct,
        "baseline_error_count": len(baseline_failure_ids),
        "baseline_accuracy": baseline_correct / len(expected_ids),
        "sft_correct_count": sft_correct,
        "sft_error_count": len(sft_failure_ids),
        "sft_accuracy": sft_correct / len(expected_ids),
        "success_delta": float(np.mean(deltas)),
        "paired_success_delta_ci95": _paired_bootstrap_ci(
            deltas,
            samples=bootstrap_samples,
            seed=seed,
        ),
        "bootstrap_samples": bootstrap_samples,
        "seed": seed,
        "category_results": _category_comparison(
            baseline_scores,
            sft_scores,
        ),
        "failure_analysis": {
            "sft_failure_count": len(sft_failure_ids),
            "improved_count": outcomes["improved"],
            "regressed_count": outcomes["regressed"],
        },
    }
    analysis_rows = _build_analysis_rows(
        comparison_rows=comparison_rows,
        baseline_raw=baseline_raw,
        sft_raw=sft_raw,
        baseline_failures=baseline_failures,
        sft_failures=sft_failures,
        benchmark_sensitive_ids=benchmark_sensitive_ids,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_yaml(
        output_dir / "resolved_config.yaml",
        {
            "baseline_dir": str(baseline_dir),
            "sft_dir": str(sft_dir),
            "manifest_path": str(manifest_path),
            "bootstrap_samples": bootstrap_samples,
            "seed": seed,
            "benchmark_sensitive_ids": sorted(benchmark_sensitive_ids),
        },
    )
    write_jsonl(output_dir / "comparison.jsonl", comparison_rows)
    write_jsonl(output_dir / "comparison_analysis.jsonl", analysis_rows)
    write_json(output_dir / "metrics.json", summary)
    (output_dir / "report.md").write_text(
        _render_report(summary, comparison_rows),
        encoding="utf-8",
    )
    (output_dir / "run.log").write_text(
        f"paired_tasks=200 outcomes={outcomes}\n",
        encoding="utf-8",
    )
    return summary


def _load_raw_generations(
    path: Path,
    expected_ids: list[str],
) -> dict[str, dict[str, Any]]:
    rows = _read_jsonl(path)
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        task_id = row.get("task_id")
        if not isinstance(task_id, str):
            raise ValueError(f"raw generation task_id 必须是字符串: {path}")
        if task_id in indexed:
            raise ValueError(f"raw generation 包含重复 task_id: {task_id}")
        indexed[task_id] = row
    expected = set(expected_ids)
    actual = set(indexed)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        raise ValueError(f"raw generation 缺失 task_id: {missing}")
    if extra:
        raise ValueError(f"raw generation 包含额外 task_id: {extra}")
    return indexed


def _load_failures(
    path: Path,
    expected_failure_ids: set[str],
) -> dict[str, dict[str, Any]]:
    rows = _read_jsonl(path)
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        task_id = row.get("task_id")
        if not isinstance(task_id, str):
            raise ValueError(f"failure task_id 必须是字符串: {path}")
        if task_id in indexed:
            raise ValueError(f"failure 包含重复 task_id: {task_id}")
        indexed[task_id] = row
    if set(indexed) != expected_failure_ids:
        missing = sorted(expected_failure_ids - set(indexed))
        extra = sorted(set(indexed) - expected_failure_ids)
        raise ValueError(f"failure 与官方 score 不一致: missing={missing}, extra={extra}")
    return indexed


def _failure_ids(scores: dict[str, BfclOfficialScore]) -> set[str]:
    return {
        task_id
        for score in scores.values()
        for task_id in score.failure_ids
    }


def _validate_metrics(
    metrics: dict[str, Any],
    scores: dict[str, BfclOfficialScore],
    label: str,
) -> None:
    total = sum(score.total_count for score in scores.values())
    correct = sum(score.correct_count for score in scores.values())
    expected = {
        "task_count": total,
        "official_correct_count": correct,
        "official_error_count": total - correct,
        "official_ast_accuracy": correct / total,
    }
    for key, value in expected.items():
        if metrics.get(key) != value:
            raise ValueError(f"{label} metrics.{key} 与官方 score 不一致")


def _validate_run_manifest(
    run_manifest: dict[str, Any],
    *,
    manifest: BfclManifest,
    manifest_sha256: str,
    expected_ids: list[str],
    label: str,
) -> None:
    """确认配对输入仍对应生成时冻结的 manifest 与 evaluator commit。"""
    if run_manifest.get("frozen_manifest_sha256") != manifest_sha256:
        raise ValueError(f"{label} run manifest 的冻结 manifest 哈希不一致")
    if run_manifest.get("selected_task_ids") != expected_ids:
        raise ValueError(f"{label} run manifest 的 task_id 顺序与冻结集合不一致")
    if run_manifest.get("seed") != manifest.seed:
        raise ValueError(f"{label} run manifest 的 seed 与冻结集合不一致")
    if run_manifest.get("frozen_manifest") != manifest.model_dump(mode="json"):
        raise ValueError(f"{label} run manifest 的内嵌冻结 manifest 不一致")
    checkout = run_manifest.get("bfcl_checkout")
    evaluator = run_manifest.get("official_evaluator")
    if (
        not isinstance(checkout, dict)
        or checkout.get("commit") != manifest.bfcl_commit
        or not isinstance(evaluator, dict)
        or evaluator.get("commit") != manifest.bfcl_commit
    ):
        raise ValueError(f"{label} run manifest 的 BFCL/evaluator commit 不一致")


def _validate_fair_configs(
    baseline_config: dict[str, Any],
    sft_config: dict[str, Any],
) -> None:
    baseline = copy.deepcopy(baseline_config)
    sft = copy.deepcopy(sft_config)
    baseline_policy = baseline.get("policy")
    sft_policy = sft.get("policy")
    if not isinstance(baseline_policy, dict) or not isinstance(sft_policy, dict):
        raise ValueError("BFCL 公平配置 policy 必须是 mapping")
    if baseline_policy.pop("adapter_path", None) is not None:
        raise ValueError("BFCL base 配置不得包含 adapter_path")
    adapter_path = sft_policy.pop("adapter_path", None)
    if not isinstance(adapter_path, str) or not adapter_path:
        raise ValueError("BFCL SFT 配置必须包含 adapter_path")
    for config in (baseline, sft):
        official = config.get("official_eval")
        if not isinstance(official, dict):
            raise ValueError("BFCL 公平配置 official_eval 必须是 mapping")
        official.pop("project_root", None)
    if baseline != sft:
        raise ValueError("BFCL 评测除 adapter_path/隔离目录外必须完全一致")


def _paired_bootstrap_ci(
    values: list[float],
    *,
    samples: int,
    seed: int,
) -> list[float]:
    array = np.asarray(values, dtype=np.float64)
    rng = np.random.default_rng(seed)
    means = rng.choice(array, size=(samples, len(array)), replace=True).mean(axis=1)
    low, high = np.quantile(means, [0.025, 0.975])
    return [float(low), float(high)]


def _category_comparison(
    baseline_scores: dict[str, BfclOfficialScore],
    sft_scores: dict[str, BfclOfficialScore],
) -> dict[str, dict[str, float | int]]:
    return {
        category: {
            "total_count": baseline_scores[category].total_count,
            "baseline_correct_count": baseline_scores[category].correct_count,
            "baseline_accuracy": baseline_scores[category].accuracy,
            "sft_correct_count": sft_scores[category].correct_count,
            "sft_accuracy": sft_scores[category].accuracy,
            "success_delta": (
                sft_scores[category].accuracy - baseline_scores[category].accuracy
            ),
        }
        for category in BFCL_CATEGORIES
    }


def _build_analysis_rows(
    *,
    comparison_rows: list[dict[str, Any]],
    baseline_raw: dict[str, dict[str, Any]],
    sft_raw: dict[str, dict[str, Any]],
    baseline_failures: dict[str, dict[str, Any]],
    sft_failures: dict[str, dict[str, Any]],
    benchmark_sensitive_ids: set[str],
) -> list[dict[str, Any]]:
    outcomes = {row["task_id"]: row["outcome"] for row in comparison_rows}
    analysis_ids = set(sft_failures) | {
        task_id for task_id, outcome in outcomes.items() if outcome == "improved"
    }
    rows: list[dict[str, Any]] = []
    for task_id in sorted(analysis_ids):
        detail = copy.deepcopy(
            sft_failures.get(task_id) or baseline_failures[task_id]
        )
        detail.update(
            {
                "task_id": task_id,
                "comparison_outcome": outcomes[task_id],
                "baseline_raw_output": baseline_raw[task_id].get("raw_output"),
                "sft_raw_output": sft_raw[task_id].get("raw_output"),
                "benchmark_sensitive": task_id in benchmark_sensitive_ids,
            }
        )
        rows.append(detail)
    return rows


def _render_report(
    summary: dict[str, Any],
    comparison_rows: list[dict[str, Any]],
) -> str:
    category_rows = [
        "| 类别 | Base | SFT | Delta |",
        "|---|---:|---:|---:|",
    ]
    category_results = summary["category_results"]
    for category in BFCL_CATEGORIES:
        row = category_results[category]
        category_rows.append(
            f"| {category} | {row['baseline_accuracy']:.6f} | "
            f"{row['sft_accuracy']:.6f} | {row['success_delta']:+.6f} |"
        )
    improved = [
        row["task_id"] for row in comparison_rows if row["outcome"] == "improved"
    ]
    regressed = [
        row["task_id"] for row in comparison_rows if row["outcome"] == "regressed"
    ]
    ci = summary["paired_success_delta_ci95"]
    return "\n".join(
        [
            "# Qwen3-1.7B BFCL Base 与 QLoRA-SFT 配对比较",
            "",
            "## 结论",
            "",
            CONCLUSION,
            "",
            f"- Base：{summary['baseline_correct_count']}/200 "
            f"({summary['baseline_accuracy']:.6f})",
            f"- SFT：{summary['sft_correct_count']}/200 "
            f"({summary['sft_accuracy']:.6f})",
            f"- Success delta：{summary['success_delta']:+.6f}",
            f"- 配对 bootstrap 95% CI：[{ci[0]:.6f}, {ci[1]:.6f}]",
            f"- 改善/退化/不变：{summary['outcomes']}",
            "",
            "## 分类别结果",
            "",
            *category_rows,
            "",
            "## 逐任务变化",
            "",
            f"- 改善：{improved}",
            f"- 退化：{regressed}",
            "",
            "完整真实问题、schema、原始输出、期望调用和官方错误保存在 "
            "comparison_analysis.jsonl，该文件不进入 git。",
            "",
            "## 适用范围",
            "",
            "这是项目定义的 BFCL V4 公开数据重新划分实验，不是官方训练、"
            "官方全量成绩、排行榜成绩或独立分布泛化结果。",
            "",
        ]
    )


def _read_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"JSON 顶层必须是 mapping: {path}")
    return loaded


def _read_yaml(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"YAML 顶层必须是 mapping: {path}")
    return loaded


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        loaded = json.loads(line)
        if not isinstance(loaded, dict):
            raise ValueError(f"JSONL 行必须是 mapping: {path}:{line_number}")
        rows.append(loaded)
    return rows
