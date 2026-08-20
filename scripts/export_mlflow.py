"""把本项目的 candidate-report.json 导出成 MLflow 可消费格式。

R8 第一轮独立审查 A2 的硬扣分项：业界工具零对照。这个导出器是桥接，不是替代——
导出去的 MLflow run 仍然只有"记指标"的能力，没有"配对可比性 + 发布判定"的能力。
面试官用 MLflow UI 看指标，用本项目的 `release` 命令看判定。

用法（仓库根目录）：

    .venv/bin/python scripts/export_mlflow.py <candidate-report.json>

输出：
- 如果装了 mlflow，把指标 / 参数 / artifact log 进一个 MLflow run
- 如果没装 mlflow，把同等内容写成一个 `mlflow_export.json`（可以后续被
  `mlflow.log_artifact` 消费）

不修改任何输入文件；不依赖项目代码（只读 JSON）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

#: 从 candidate-report.json 提取出来 log 进 MLflow metrics 的字段。
#: 选的是"跨候选可比 + 面试官会问"的核心指标。
METRIC_KEYS = (
    "task_success",
    "policy_violation_count",
    "invalid_call_count",
    "p95_latency_ms",
    "p50_latency_ms",
    "average_latency_ms",
    "average_tool_calls",
    "average_turns",
    "average_output_tokens",
    "average_input_tokens",
    "replayable_count",
    "schema_valid_rate",
    "executable_rate",
)

#: 从 candidate-report.json 提取出来 log 进 MLflow params 的字段。
#: 选的是"运行条件"——配对可比性需要的那些字段。
PARAM_KEYS = (
    "schema_version",
    "dataset_version",
    "generator_id",
    "bundle_id",
    "bundle_version",
    "parser_id",
    "evaluator_id",
    "seed",
    "max_steps",
    "policy_id",
    "task_count",
    "code_commit",
    "uv_lock_sha256",
    "system_prompt_sha256",
    "tool_schema_sha256",
    "config_sha256",
    "evidence_complete",
)

#: 从 candidate-report.json 的 model / adapter 字段提取的运行条件。
MODEL_PARAM_KEYS = (
    "repo",
    "revision",
    "local_dir",
)


def extract_metrics(payload: dict[str, Any]) -> dict[str, float | int]:
    """从 candidate-report.json 的 metrics 子字段提取核心指标。

    返回的是 MLflow `log_metrics` 可消费的 flat dict（key → number）。
    非 number 类型（如 failure_type_distribution dict）跳过。
    """
    metrics_field = payload.get("metrics", {})
    result: dict[str, float | int] = {}
    for key in METRIC_KEYS:
        value = metrics_field.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result[key] = value
    return result


def extract_params(payload: dict[str, Any]) -> dict[str, str]:
    """从 candidate-report.json 提取运行条件作为 MLflow params。

    返回的是 MLflow `log_params` 可消费的 flat dict（key → str）。
    """
    result: dict[str, str] = {}
    for key in PARAM_KEYS:
        value = payload.get(key)
        if value is not None:
            result[key] = str(value)
    # 模型与 adapter 信息
    model = payload.get("model", {})
    for key in MODEL_PARAM_KEYS:
        value = model.get(key)
        if value is not None:
            result[f"model_{key}"] = str(value)
    adapter = payload.get("adapter")
    if adapter is not None:
        result["adapter_present"] = "true"
        for key in MODEL_PARAM_KEYS:
            value = adapter.get(key)
            if value is not None:
                result[f"adapter_{key}"] = str(value)
    else:
        result["adapter_present"] = "false"
    # 运行时溯源（如果有）
    for key in ("inference_engine", "runtime_env_sha256"):
        value = payload.get(key)
        if value is not None:
            result[key] = str(value)
    return result


def export_to_json(payload: dict[str, Any], output_path: Path) -> None:
    """把提取出来的 metrics / params / 原始报告写成一个 JSON 文件。

    这是 mlflow 没装时的降级路径；文件可以后续被 `mlflow.log_artifact` 消费。
    """
    bundle = {
        "metrics": extract_metrics(payload),
        "params": extract_params(payload),
        "original_report": payload,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def export_to_mlflow(
    payload: dict[str, Any],
    *,
    experiment_name: str = "retail-agent-ops",
) -> str:
    """把 metrics / params / artifact log 进一个 MLflow run。

    返回 run URL（如果 mlflow tracking URI 是本地文件 store，是 file:// URL）。
    """
    import mlflow  # 软依赖：调用方负责处理 ImportError

    mlflow.set_experiment(experiment_name)
    run_id: str
    with mlflow.start_run() as run:
        mlflow.log_metrics(extract_metrics(payload))
        mlflow.log_params(extract_params(payload))
        # 把完整原始报告作为一个不可篡改 artifact 记下
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(payload, f, ensure_ascii=False, sort_keys=True)
            tmp_path = f.name
        mlflow.log_artifact(tmp_path, artifact_path="reports")
        run_id = run.info.run_id
    return run_id


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"用法: {argv[0]} <candidate-report.json>", file=sys.stderr)
        return 1
    report_path = Path(argv[1])
    if not report_path.is_file():
        print(f"文件不存在: {report_path}", file=sys.stderr)
        return 1
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    # 软依赖 mlflow：装了就用 mlflow API，没装就降级写 JSON
    try:
        import mlflow  # noqa: F401
    except ImportError:
        output_path = report_path.parent / "mlflow_export.json"
        export_to_json(payload, output_path)
        print(
            f"mlflow 未安装，降级写 JSON 到 {output_path}\n"
            f"（可以后续用 `mlflow.log_artifact('{output_path}')` 消费）",
            file=sys.stderr,
        )
        return 0

    run_id = export_to_mlflow(payload)
    print(f"已 log 进 MLflow run: {run_id}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
