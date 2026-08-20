"""R8 第一轮审查 A2：业界工具桥接——MLflow 导出器。

`scripts/export_mlflow.py` 把 `candidate-report.json` 导成 MLflow 可消费格式。
这是桥接，不是替代——导出去的 MLflow run 仍然只有"记指标"的能力，没有"配对
可比性 + 发布判定"的能力（见 `docs/MLOPS_COMPARISON.md`）。

测试覆盖：
1. extract_metrics 从 candidate-report.json 提取核心指标
2. extract_params 提取运行条件（含运行时溯源）
3. export_to_json 降级路径（mlflow 没装时写 JSON）
4. 非 number 类型跳过
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.export_mlflow import (
    METRIC_KEYS,
    PARAM_KEYS,
    export_to_json,
    extract_metrics,
    extract_params,
)


def _minimal_payload() -> dict[str, Any]:
    """构造一份字段自洽的 candidate-report payload（只含测试需要的字段）。"""
    return {
        "schema_version": "1.0",
        "run_id": "a" * 64,
        "dataset_version": "retail_ops_v1_r2_20260722",
        "generator_id": "family_sha256_v1",
        "bundle_id": "retail_ops",
        "bundle_version": "1.0.0",
        "bundle_sha256": "c" * 64,
        "parser_id": "hermes-single-call-v1",
        "evaluator_id": "retail_ops_v1",
        "seed": 0,
        "max_steps": 5,
        "policy_id": "qwen:test",
        "task_count": 120,
        "code_commit": "3" * 40,
        "uv_lock_sha256": "4" * 64,
        "system_prompt_sha256": "f" * 64,
        "tool_schema_sha256": "1" * 64,
        "config_sha256": "2" * 64,
        "evidence_complete": True,
        "metrics": {
            "task_success": 1.0,
            "policy_violation_count": 0,
            "invalid_call_count": 0,
            "p95_latency_ms": 5730.5,
            "p50_latency_ms": 4747.0,
            "average_latency_ms": 4457.0,
            "average_tool_calls": 1.5,
            "average_turns": 2.167,
            "average_output_tokens": 131.7,
            "average_input_tokens": 92.2,
            "replayable_count": 120,
            "schema_valid_rate": 1.0,
            "executable_rate": 1.0,
            # 非 number 类型，应该被跳过
            "failure_type_distribution": {"format_error": 0, "policy_violation": 0},
            "task_success_ci95": [1.0, 1.0],
        },
        "model": {
            "repo": "Qwen/Qwen3-4B",
            "revision": "8cd0101f",
            "local_dir": "Qwen3-4B-pinned",
            "file_sha256": {"config.json": "5" * 64},
        },
        "adapter": None,
        "inference_engine": "transformers",
        "runtime_env_sha256": "a" * 64,
    }


# ---------------------------------------------------------------------------
# extract_metrics
# ---------------------------------------------------------------------------


def test_extract_metrics_pulls_all_core_indicators() -> None:
    """核心指标必须全部提取——面试官用 MLflow UI 看的就是这些。"""
    metrics = extract_metrics(_minimal_payload())

    for key in METRIC_KEYS:
        assert key in metrics, f"{key} 必须被提取"
    assert metrics["task_success"] == 1.0
    assert metrics["p95_latency_ms"] == 5730.5
    assert metrics["replayable_count"] == 120


def test_extract_metrics_skips_non_numbers() -> None:
    """非 number 类型（dict / list）必须跳过——MLflow log_metrics 只接受标量。"""
    metrics = extract_metrics(_minimal_payload())

    assert "failure_type_distribution" not in metrics
    assert "task_success_ci95" not in metrics


def test_extract_metrics_skips_missing_keys() -> None:
    """缺字段的指标跳过，不报错——不同报告的字段集合可能不同。"""
    payload = _minimal_payload()
    del payload["metrics"]["p95_latency_ms"]
    metrics = extract_metrics(payload)

    assert "p95_latency_ms" not in metrics
    assert "task_success" in metrics  # 其他字段不受影响


# ---------------------------------------------------------------------------
# extract_params
# ---------------------------------------------------------------------------


def test_extract_params_pulls_all_run_conditions() -> None:
    """运行条件必须全部提取——配对可比性靠这些。"""
    params = extract_params(_minimal_payload())

    for key in PARAM_KEYS:
        assert key in params, f"{key} 必须被提取"
    assert params["code_commit"] == "3" * 40
    assert params["seed"] == "0"  # MLflow params 是 str
    assert params["evidence_complete"] == "True"


def test_extract_params_includes_model_and_adapter() -> None:
    """模型与 adapter 信息必须提取——面试官第一句就问"用了什么模型"。"""
    params = extract_params(_minimal_payload())

    assert params["model_repo"] == "Qwen/Qwen3-4B"
    assert params["model_revision"] == "8cd0101f"
    assert params["adapter_present"] == "false"


def test_extract_params_includes_runtime_provenance() -> None:
    """运行时溯源必须提取——这是 R8 第一轮审查 A4 修的洞。"""
    params = extract_params(_minimal_payload())

    assert params["inference_engine"] == "transformers"
    assert params["runtime_env_sha256"] == "a" * 64


def test_extract_params_skips_runtime_provenance_when_absent() -> None:
    """没有运行时溯源的报告（v1.0 sealed）不提取这两个字段。"""
    payload = _minimal_payload()
    del payload["inference_engine"]
    del payload["runtime_env_sha256"]
    params = extract_params(payload)

    assert "inference_engine" not in params
    assert "runtime_env_sha256" not in params


# ---------------------------------------------------------------------------
# export_to_json（mlflow 没装时的降级路径）
# ---------------------------------------------------------------------------


def test_export_to_json_writes_metrics_params_and_original_report(tmp_path: Path) -> None:
    """降级路径必须写出完整的 metrics / params / 原始报告——后续可被 mlflow 消费。"""
    payload = _minimal_payload()
    output_path = tmp_path / "mlflow_export.json"

    export_to_json(payload, output_path)

    assert output_path.is_file()
    bundle = json.loads(output_path.read_text(encoding="utf-8"))
    assert set(bundle.keys()) == {"metrics", "params", "original_report"}
    assert bundle["metrics"]["task_success"] == 1.0
    assert bundle["params"]["code_commit"] == "3" * 40
    assert bundle["original_report"] == payload


def test_export_to_json_creates_parent_directory(tmp_path: Path) -> None:
    """输出路径的父目录不存在时必须创建——scripts 应该自给自足。"""
    payload = _minimal_payload()
    output_path = tmp_path / "deep" / "nested" / "mlflow_export.json"

    export_to_json(payload, output_path)

    assert output_path.is_file()


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------


def test_main_rejects_missing_argument(capsys: pytest.CaptureFixture[str]) -> None:
    """没有参数必须报错并退出 1。"""
    from scripts.export_mlflow import main

    exit_code = main(["export_mlflow.py"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "用法" in err


def test_main_rejects_nonexistent_file(capsys: pytest.CaptureFixture[str]) -> None:
    """文件不存在必须报错并退出 1。"""
    from scripts.export_mlflow import main

    exit_code = main(["export_mlflow.py", "/nonexistent/report.json"])
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "文件不存在" in err


def test_main_degrades_gracefully_without_mlflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """mlflow 没装时必须降级写 JSON，不崩——CI 环境通常不装 mlflow。"""
    # 模拟 mlflow 未安装
    import builtins

    real_import = builtins.__import__

    def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "mlflow":
            raise ImportError("mlflow not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    # 写一份 minimal payload 到文件
    report_path = tmp_path / "candidate-report.json"
    report_path.write_text(
        json.dumps(_minimal_payload(), ensure_ascii=False),
        encoding="utf-8",
    )

    from scripts.export_mlflow import main

    exit_code = main(["export_mlflow.py", str(report_path)])
    assert exit_code == 0
    err = capsys.readouterr().err
    assert "mlflow 未安装" in err
    assert "降级写 JSON" in err

    export_path = report_path.parent / "mlflow_export.json"
    assert export_path.is_file()
