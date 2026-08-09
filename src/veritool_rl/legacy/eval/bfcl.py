"""BFCL 单轮生成结果转换与补充诊断。"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import Field, ValidationError, field_validator

from veritool_rl.core.agent.qwen import GeneratedText
from veritool_rl.core.artifacts import write_jsonl
from veritool_rl.core.trajectory.schema import StrictModel, validate_json_value
from veritool_rl.legacy.data.bfcl import BfclGroundTruth, BfclTask

_TOOL_CALL_PATTERN = re.compile(r"<tool_call>\n(.*?)\n</tool_call>", re.DOTALL)


class BfclToolCall(StrictModel):
    """从 Qwen 原始输出解析的一次 BFCL 调用。"""

    name: str = Field(min_length=1)
    arguments: dict[str, Any]

    _validate_arguments = field_validator("arguments")(validate_json_value)


class ParsedBfclOutput(StrictModel):
    """原始输出的确定性解析结果。"""

    calls: list[BfclToolCall] = Field(default_factory=list)
    parse_error: str | None = None


class BfclDiagnostic(StrictModel):
    """不替代官方 AST 指标的逐任务补充诊断。"""

    parseable: bool
    schema_valid: bool
    parsed_call_count: int = Field(ge=0)
    expected_call_count: int = Field(ge=0)
    wrong_function_name_count: int = Field(ge=0)
    missing_parameter_count: int = Field(ge=0)
    extra_parameter_count: int = Field(ge=0)
    type_error_parameter_count: int = Field(ge=0)
    call_count_error: bool
    structure_error: bool
    parse_error: str | None = None


class BfclOfficialScore(StrictModel):
    """固定类别的 BFCL 官方 AST evaluator 摘要。"""

    category: str = Field(min_length=1)
    accuracy: float = Field(ge=0.0, le=1.0)
    correct_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    failure_ids: list[str] = Field(default_factory=list)
    error_type_counts: dict[str, int] = Field(default_factory=dict)


def parse_bfcl_tool_calls(raw_text: str) -> ParsedBfclOutput:
    """解析一个响应中的全部 Hermes ``tool_call`` 标签。"""
    blocks = _TOOL_CALL_PATTERN.findall(raw_text)
    if not blocks:
        error = (
            "invalid_tool_call_format" if "<tool_call>" in raw_text else "missing_tool_call"
        )
        return ParsedBfclOutput(parse_error=error)
    calls: list[BfclToolCall] = []
    for block in blocks:
        try:
            payload = json.loads(block)
            calls.append(BfclToolCall.model_validate(payload))
        except json.JSONDecodeError:
            return ParsedBfclOutput(parse_error="invalid_tool_call_json")
        except ValidationError:
            return ParsedBfclOutput(parse_error="invalid_tool_call_schema")
    return ParsedBfclOutput(calls=calls)


def diagnose_bfcl_generation(
    task: BfclTask,
    ground_truth: BfclGroundTruth,
    raw_text: str,
) -> BfclDiagnostic:
    """按模型可见 schema 统计解析和参数类型错误。"""
    if task.id != ground_truth.id:
        msg = f"任务与 ground truth ID 不一致: {task.id} != {ground_truth.id}"
        raise ValueError(msg)
    parsed = parse_bfcl_tool_calls(raw_text)
    functions = {function.name: function for function in task.function}
    expected_names = [
        function_name
        for expected_call in ground_truth.ground_truth
        for function_name in expected_call
    ]
    expected_name_set = set(expected_names)
    wrong_names = sum(call.name not in expected_name_set for call in parsed.calls)
    unknown_schema_functions = sum(call.name not in functions for call in parsed.calls)
    missing = 0
    extra = 0
    type_errors = 0
    for call in parsed.calls:
        function = functions.get(call.name)
        if function is None:
            continue
        properties = function.parameters.get("properties", {})
        required = function.parameters.get("required", [])
        if not isinstance(properties, dict) or not isinstance(required, list):
            type_errors += 1
            continue
        missing += sum(name not in call.arguments for name in required)
        extra += sum(name not in properties for name in call.arguments)
        for name, value in call.arguments.items():
            schema = properties.get(name)
            if isinstance(schema, dict) and not _matches_schema_type(value, schema):
                type_errors += 1
    expected_count = len(ground_truth.ground_truth)
    call_count_error = len(parsed.calls) != expected_count
    function_name_structure_error = Counter(call.name for call in parsed.calls) != Counter(
        expected_names
    )
    schema_error_count = unknown_schema_functions + missing + extra + type_errors
    category = task.id.rsplit("_", 1)[0]
    structure_error = category in {"multiple", "parallel", "parallel_multiple"} and (
        parsed.parse_error is not None
        or call_count_error
        or function_name_structure_error
    )
    return BfclDiagnostic(
        parseable=parsed.parse_error is None,
        schema_valid=(
            parsed.parse_error is None and bool(parsed.calls) and schema_error_count == 0
        ),
        parsed_call_count=len(parsed.calls),
        expected_call_count=expected_count,
        wrong_function_name_count=wrong_names,
        missing_parameter_count=missing,
        extra_parameter_count=extra,
        type_error_parameter_count=type_errors,
        call_count_error=call_count_error,
        structure_error=structure_error,
        parse_error=parsed.parse_error,
    )


def build_official_result_row(task_id: str, generated: GeneratedText) -> dict[str, Any]:
    """把未修改的模型输出封装为 BFCL 官方 result 行。"""
    return {
        "id": task_id,
        "result": generated.text,
        "input_token_count": generated.input_tokens,
        "output_token_count": generated.output_tokens,
        "latency": generated.latency_ms / 1000,
    }


def validate_official_result_ids(expected_ids: list[str], rows: list[dict[str, Any]]) -> None:
    """要求官方 result 与冻结任务 ID 完全一一对应。"""
    actual_ids: list[str] = []
    for row in rows:
        task_id = row.get("id")
        if not isinstance(task_id, str):
            msg = "official result 的 task_id 必须是字符串"
            raise ValueError(msg)
        actual_ids.append(task_id)
    if len(actual_ids) != len(set(actual_ids)):
        msg = "official result 包含重复 task_id"
        raise ValueError(msg)
    expected = set(expected_ids)
    actual = set(actual_ids)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        msg = f"official result 缺失 task_id: {missing}"
        raise ValueError(msg)
    if extra:
        msg = f"official result 包含额外 task_id: {extra}"
        raise ValueError(msg)


def write_official_result_files(
    result_root: Path,
    model_name: str,
    expected_ids_by_category: dict[str, list[str]],
    rows: list[dict[str, Any]],
) -> list[Path]:
    """按 BFCL 类别写入官方 evaluator 使用的 result JSONL。"""
    validate_official_result_ids(
        [task_id for ids in expected_ids_by_category.values() for task_id in ids],
        rows,
    )
    output_dir = result_root / model_name.replace("/", "_") / "non_live"
    paths: list[Path] = []
    for category, expected_ids in expected_ids_by_category.items():
        category_rows = [row for row in rows if row.get("id") in set(expected_ids)]
        validate_official_result_ids(expected_ids, category_rows)
        category_rows.sort(key=lambda row: int(str(row["id"]).rsplit("_", 1)[1]))
        path = output_dir / f"BFCL_v4_{category}_result.json"
        write_jsonl(path, category_rows)
        paths.append(path)
    return paths


def load_official_scores(
    score_root: Path,
    model_name: str,
    expected_ids_by_category: dict[str, list[str]],
) -> dict[str, BfclOfficialScore]:
    """读取官方 score JSONL，并严格校验汇总计数与失败 ID。"""
    score_dir = score_root / model_name.replace("/", "_") / "non_live"
    scores: dict[str, BfclOfficialScore] = {}
    for category, expected_ids in expected_ids_by_category.items():
        path = score_dir / f"BFCL_v4_{category}_score.json"
        rows = _read_jsonl(path)
        if not rows:
            msg = f"官方 score 文件为空: {path}"
            raise ValueError(msg)
        summary = rows[0]
        total_count = summary.get("total_count")
        correct_count = summary.get("correct_count")
        accuracy = summary.get("accuracy")
        if (
            not isinstance(total_count, int)
            or isinstance(total_count, bool)
            or not isinstance(correct_count, int)
            or isinstance(correct_count, bool)
            or not isinstance(accuracy, (int, float))
            or isinstance(accuracy, bool)
        ):
            msg = f"官方 score 汇总格式无效: {path}"
            raise ValueError(msg)
        if total_count != len(expected_ids) or not 0 <= correct_count <= total_count:
            msg = f"官方 score 计数与冻结任务不一致: {path}"
            raise ValueError(msg)
        expected_accuracy = correct_count / total_count if total_count else 0.0
        if abs(float(accuracy) - expected_accuracy) > 1e-12:
            msg = f"官方 score accuracy 与计数不一致: {path}"
            raise ValueError(msg)
        failure_rows = rows[1:]
        failure_ids = [row.get("id") for row in failure_rows]
        if (
            any(not isinstance(task_id, str) for task_id in failure_ids)
            or len(failure_ids) != len(set(failure_ids))
            or len(failure_ids) != total_count - correct_count
            or not set(failure_ids).issubset(expected_ids)
        ):
            msg = f"官方 score 失败 ID 与冻结任务不一致: {path}"
            raise ValueError(msg)
        error_types = Counter(
            str(row.get("error_type", "unknown")) for row in failure_rows
        )
        scores[category] = BfclOfficialScore(
            category=category,
            accuracy=float(accuracy),
            correct_count=correct_count,
            total_count=total_count,
            failure_ids=[str(task_id) for task_id in failure_ids],
            error_type_counts=dict(sorted(error_types.items())),
        )
    return scores


def compute_bfcl_metrics(
    *,
    scores: dict[str, BfclOfficialScore],
    diagnostics: list[BfclDiagnostic],
    generation_latency_ms: list[float],
    wall_time_seconds: float,
    cuda_peak_allocated_bytes: int,
    cuda_peak_reserved_bytes: int,
) -> dict[str, Any]:
    """汇总官方 AST 指标及不替代官方评分的解析诊断。"""
    task_count = sum(score.total_count for score in scores.values())
    if len(diagnostics) != task_count or len(generation_latency_ms) != task_count:
        msg = "诊断、生成耗时与官方 score 的任务数量不一致"
        raise ValueError(msg)
    correct_count = sum(score.correct_count for score in scores.values())
    error_type_counts: Counter[str] = Counter()
    for score in scores.values():
        error_type_counts.update(score.error_type_counts)
    parseable_count = sum(item.parseable for item in diagnostics)
    schema_valid_count = sum(item.schema_valid for item in diagnostics)
    total_generation_seconds = sum(generation_latency_ms) / 1000
    return {
        "task_count": task_count,
        "category_counts": {
            category: score.total_count for category, score in scores.items()
        },
        "official_ast_accuracy": correct_count / task_count if task_count else 0.0,
        "official_ast_accuracy_by_category": {
            category: score.accuracy for category, score in scores.items()
        },
        "official_correct_count": correct_count,
        "official_correct_count_by_category": {
            category: score.correct_count for category, score in scores.items()
        },
        "official_error_count": task_count - correct_count,
        "official_error_count_by_category": {
            category: score.total_count - score.correct_count
            for category, score in scores.items()
        },
        "official_error_type_counts": dict(sorted(error_type_counts.items())),
        "parseable_count": parseable_count,
        "parseable_rate": parseable_count / task_count if task_count else 0.0,
        "schema_valid_count": schema_valid_count,
        "schema_valid_rate": schema_valid_count / task_count if task_count else 0.0,
        "wrong_function_name_count": sum(
            item.wrong_function_name_count for item in diagnostics
        ),
        "missing_parameter_count": sum(
            item.missing_parameter_count for item in diagnostics
        ),
        "extra_parameter_count": sum(
            item.extra_parameter_count for item in diagnostics
        ),
        "type_error_parameter_count": sum(
            item.type_error_parameter_count for item in diagnostics
        ),
        "call_count_error_count": sum(item.call_count_error for item in diagnostics),
        "structure_error_count": sum(item.structure_error for item in diagnostics),
        "wall_time_seconds": wall_time_seconds,
        "average_task_wall_time_seconds": (
            wall_time_seconds / task_count if task_count else 0.0
        ),
        "generation_latency_seconds": total_generation_seconds,
        "average_generation_latency_seconds": (
            total_generation_seconds / task_count if task_count else 0.0
        ),
        "cuda_peak_allocated_bytes": cuda_peak_allocated_bytes,
        "cuda_peak_reserved_bytes": cuda_peak_reserved_bytes,
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as error:
        msg = f"文件不存在: {path}"
        raise ValueError(msg) from error
    for line_number, line in enumerate(lines, start=1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            msg = f"无效 JSONL: {path}:{line_number}"
            raise ValueError(msg) from error
        if not isinstance(row, dict):
            msg = f"JSONL 行必须是对象: {path}:{line_number}"
            raise ValueError(msg)
        rows.append(row)
    return rows


def _matches_schema_type(value: Any, schema: dict[str, Any]) -> bool:
    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and value not in enum_values:
        return False
    type_name = schema.get("type")
    if type_name == "any":
        return True
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name in {"array", "tuple"}:
        if not isinstance(value, (list, tuple)):
            return False
        item_schema = schema.get("items")
        return not isinstance(item_schema, dict) or all(
            _matches_schema_type(item, item_schema) for item in value
        )
    if type_name == "dict":
        if not isinstance(value, dict):
            return False
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return True
        required = schema.get("required", [])
        return (
            isinstance(required, list)
            and all(name in value for name in required)
            and all(name in properties for name in value)
            and all(
                not isinstance(properties[name], dict)
                or _matches_schema_type(item, properties[name])
                for name, item in value.items()
            )
        )
    return False
