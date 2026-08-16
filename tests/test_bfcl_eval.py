"""BFCL 原始输出转换、诊断与官方结果对齐测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _task(category: str, functions: list[dict[str, object]] | None = None):
    from veritool_rl.legacy.data.bfcl import BfclTask

    default_function = {
        "name": "lookup",
        "description": "Look up one value.",
        "parameters": {
            "type": "dict",
            "properties": {
                "value": {"type": "integer"},
                "label": {"type": "string"},
            },
            "required": ["value"],
        },
    }
    return BfclTask.model_validate(
        {
            "id": f"{category}_0",
            "question": [[{"role": "user", "content": "Find values."}]],
            "function": functions or [default_function],
        }
    )


def _truth(category: str, calls: list[dict[str, dict[str, list[object]]]]):
    from veritool_rl.legacy.data.bfcl import BfclGroundTruth

    return BfclGroundTruth(id=f"{category}_0", ground_truth=calls)


@pytest.mark.parametrize(
    ("category", "raw_text", "expected_count"),
    [
        (
            "simple_python",
            '<tool_call>\n{"name":"lookup","arguments":{"value":1}}\n</tool_call>',
            1,
        ),
        (
            "multiple",
            '<tool_call>\n{"name":"lookup","arguments":{"value":1}}\n</tool_call>',
            1,
        ),
        (
            "parallel",
            '<tool_call>\n{"name":"lookup","arguments":{"value":1}}\n</tool_call>\n'
            '<tool_call>\n{"name":"lookup","arguments":{"value":2}}\n</tool_call>',
            2,
        ),
        (
            "parallel_multiple",
            '<tool_call>\n{"name":"lookup","arguments":{"value":1}}\n</tool_call>\n'
            '<tool_call>\n{"name":"other","arguments":{"value":2}}\n</tool_call>',
            2,
        ),
    ],
)
def test_parse_bfcl_tool_calls_supports_all_fixed_categories(
    category: str,
    raw_text: str,
    expected_count: int,
) -> None:
    from veritool_rl.legacy.eval.bfcl import parse_bfcl_tool_calls

    del category
    parsed = parse_bfcl_tool_calls(raw_text + "<|im_end|>")

    assert parsed.parse_error is None
    assert len(parsed.calls) == expected_count


def test_parse_bfcl_tool_calls_rejects_invalid_json() -> None:
    from veritool_rl.legacy.eval.bfcl import parse_bfcl_tool_calls

    parsed = parse_bfcl_tool_calls("<tool_call>\n{bad}\n</tool_call>")

    assert parsed.calls == []
    assert parsed.parse_error == "invalid_tool_call_json"


def test_parse_bfcl_tool_calls_mirrors_official_qwen_newline_contract() -> None:
    from veritool_rl.legacy.eval.bfcl import parse_bfcl_tool_calls

    parsed = parse_bfcl_tool_calls(
        '<tool_call>{"name":"lookup","arguments":{"value":1}}</tool_call>'
    )

    assert parsed.calls == []
    assert parsed.parse_error == "invalid_tool_call_format"


@pytest.mark.parametrize(
    ("raw_text", "field", "expected"),
    [
        (
            '<tool_call>\n{"name":"missing","arguments":{"value":1}}\n</tool_call>',
            "wrong_function_name_count",
            1,
        ),
        (
            '<tool_call>\n{"name":"lookup","arguments":{}}\n</tool_call>',
            "missing_parameter_count",
            1,
        ),
        (
            '<tool_call>\n{"name":"lookup","arguments":{"value":1,"extra":2}}\n</tool_call>',
            "extra_parameter_count",
            1,
        ),
        (
            '<tool_call>\n{"name":"lookup","arguments":{"value":"1"}}\n</tool_call>',
            "type_error_parameter_count",
            1,
        ),
    ],
)
def test_diagnose_bfcl_generation_counts_schema_errors(
    raw_text: str,
    field: str,
    expected: int,
) -> None:
    from veritool_rl.legacy.eval.bfcl import diagnose_bfcl_generation

    task = _task("simple_python")
    truth = _truth("simple_python", [{"lookup": {"value": [1], "label": [""]}}])

    diagnostic = diagnose_bfcl_generation(task, truth, raw_text)

    assert getattr(diagnostic, field) == expected
    assert diagnostic.schema_valid is False


def test_diagnose_bfcl_generation_separates_call_count_and_structure_errors() -> None:
    from veritool_rl.legacy.eval.bfcl import diagnose_bfcl_generation

    task = _task("parallel")
    truth = _truth(
        "parallel",
        [
            {"lookup": {"value": [1], "label": [""]}},
            {"lookup": {"value": [2], "label": [""]}},
        ],
    )
    raw = '<tool_call>\n{"name":"lookup","arguments":{"value":1}}\n</tool_call>'

    diagnostic = diagnose_bfcl_generation(task, truth, raw)

    assert diagnostic.schema_valid is True
    assert diagnostic.call_count_error is True
    assert diagnostic.structure_error is True


def test_diagnose_counts_offered_but_wrong_function_name() -> None:
    from veritool_rl.legacy.eval.bfcl import diagnose_bfcl_generation

    functions = [
        {
            "name": name,
            "description": f"{name} value.",
            "parameters": {
                "type": "dict",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
            },
        }
        for name in ("lookup", "other")
    ]
    task = _task("multiple", functions)
    truth = _truth("multiple", [{"lookup": {"value": [1]}}])
    raw = '<tool_call>\n{"name":"other","arguments":{"value":1}}\n</tool_call>'

    diagnostic = diagnose_bfcl_generation(task, truth, raw)

    assert diagnostic.wrong_function_name_count == 1
    assert diagnostic.schema_valid is True
    assert diagnostic.structure_error is True


def test_diagnose_parallel_structure_compares_function_name_multiset() -> None:
    from veritool_rl.legacy.eval.bfcl import diagnose_bfcl_generation

    functions = [
        {
            "name": name,
            "description": f"{name} value.",
            "parameters": {
                "type": "dict",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
            },
        }
        for name in ("lookup", "other")
    ]
    task = _task("parallel_multiple", functions)
    truth = _truth(
        "parallel_multiple",
        [{"lookup": {"value": [1]}}, {"other": {"value": [2]}}],
    )
    raw = (
        '<tool_call>\n{"name":"lookup","arguments":{"value":1}}\n</tool_call>\n'
        '<tool_call>\n{"name":"lookup","arguments":{"value":2}}\n</tool_call>'
    )

    diagnostic = diagnose_bfcl_generation(task, truth, raw)

    assert diagnostic.call_count_error is False
    assert diagnostic.structure_error is True


def test_diagnose_rejects_parameter_outside_schema_enum() -> None:
    from veritool_rl.legacy.eval.bfcl import diagnose_bfcl_generation

    task = _task(
        "simple_python",
        [
            {
                "name": "lookup",
                "description": "Look up one labeled value.",
                "parameters": {
                    "type": "dict",
                    "properties": {
                        "value": {"type": "integer"},
                        "label": {"type": "string", "enum": ["a", "b"]},
                    },
                    "required": ["value", "label"],
                },
            }
        ],
    )
    truth = _truth(
        "simple_python",
        [{"lookup": {"value": [1], "label": ["a"]}}],
    )
    raw = '<tool_call>\n{"name":"lookup","arguments":{"value":1,"label":"c"}}\n</tool_call>'

    diagnostic = diagnose_bfcl_generation(task, truth, raw)

    assert diagnostic.type_error_parameter_count == 1
    assert diagnostic.schema_valid is False


def test_build_official_result_preserves_raw_output_and_usage() -> None:
    from veritool_rl.core.agent.qwen import GeneratedText
    from veritool_rl.legacy.eval.bfcl import build_official_result_row

    raw = '<tool_call>\n{"name":"lookup","arguments":{"value":1}}\n</tool_call>'
    generated = GeneratedText(
        text=raw,
        input_tokens=100,
        output_tokens=25,
        latency_ms=1250.0,
    )

    row = build_official_result_row("simple_python_0", generated)

    assert row == {
        "id": "simple_python_0",
        "result": raw,
        "input_token_count": 100,
        "output_token_count": 25,
        "latency": 1.25,
    }


def test_validate_official_result_ids_rejects_missing_extra_and_duplicates() -> None:
    from veritool_rl.legacy.eval.bfcl import validate_official_result_ids

    validate_official_result_ids(["simple_python_0"], [{"id": "simple_python_0"}])

    with pytest.raises(ValueError, match=r"缺失.*simple_python_1"):
        validate_official_result_ids(
            ["simple_python_0", "simple_python_1"],
            [{"id": "simple_python_0"}],
        )
    with pytest.raises(ValueError, match=r"额外.*simple_python_2"):
        validate_official_result_ids(
            ["simple_python_0"],
            [{"id": "simple_python_0"}, {"id": "simple_python_2"}],
        )
    with pytest.raises(ValueError, match="重复"):
        validate_official_result_ids(
            ["simple_python_0"],
            [{"id": "simple_python_0"}, {"id": "simple_python_0"}],
        )


def test_write_official_result_files_groups_and_sorts_by_source_index(tmp_path: Path) -> None:
    from veritool_rl.legacy.eval.bfcl import write_official_result_files

    rows = [
        {"id": "parallel_10", "result": "ten"},
        {"id": "simple_python_2", "result": "two"},
        {"id": "parallel_3", "result": "three"},
    ]
    expected = {
        "simple_python": ["simple_python_2"],
        "parallel": ["parallel_3", "parallel_10"],
    }

    paths = write_official_result_files(
        tmp_path,
        model_name="Qwen/Qwen3-1.7B-FC",
        expected_ids_by_category=expected,
        rows=rows,
    )

    assert [path.name for path in paths] == [
        "BFCL_v4_simple_python_result.json",
        "BFCL_v4_parallel_result.json",
    ]
    parallel_rows = [
        json.loads(line)
        for line in (tmp_path / "Qwen_Qwen3-1.7B-FC/non_live/BFCL_v4_parallel_result.json")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [row["id"] for row in parallel_rows] == ["parallel_3", "parallel_10"]


def test_load_official_scores_validates_counts_and_failure_ids(tmp_path: Path) -> None:
    from veritool_rl.legacy.eval.bfcl import load_official_scores

    model_dir = tmp_path / "Qwen_Qwen3-1.7B-FC/non_live"
    model_dir.mkdir(parents=True)
    for category in ("simple_python", "multiple"):
        rows = [
            {"accuracy": 0.5, "correct_count": 1, "total_count": 2},
            {
                "id": f"{category}_1",
                "valid": False,
                "error_type": "simple_function_checker:wrong_func_name",
            },
        ]
        (model_dir / f"BFCL_v4_{category}_score.json").write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )

    scores = load_official_scores(
        tmp_path,
        "Qwen/Qwen3-1.7B-FC",
        {
            "simple_python": ["simple_python_0", "simple_python_1"],
            "multiple": ["multiple_0", "multiple_1"],
        },
    )

    assert scores["simple_python"].correct_count == 1
    assert scores["simple_python"].failure_ids == ["simple_python_1"]

    bad_path = model_dir / "BFCL_v4_multiple_score.json"
    bad_rows = [
        {"accuracy": 0.5, "correct_count": 1, "total_count": 2},
        {"id": "multiple_9", "valid": False, "error_type": "bad"},
    ]
    bad_path.write_text("".join(json.dumps(row) + "\n" for row in bad_rows), encoding="utf-8")
    with pytest.raises(ValueError, match="失败 ID"):
        load_official_scores(
            tmp_path,
            "Qwen/Qwen3-1.7B-FC",
            {
                "simple_python": ["simple_python_0", "simple_python_1"],
                "multiple": ["multiple_0", "multiple_1"],
            },
        )


def test_compute_bfcl_metrics_reports_official_and_diagnostic_counts() -> None:
    from veritool_rl.legacy.eval.bfcl import (
        BfclDiagnostic,
        BfclOfficialScore,
        compute_bfcl_metrics,
    )

    scores = {
        category: BfclOfficialScore(
            category=category,
            accuracy=0.5,
            correct_count=1,
            total_count=2,
            failure_ids=[f"{category}_1"],
            error_type_counts={"simple_function_checker:wrong_func_name": 1},
        )
        for category in ("simple_python", "multiple", "parallel", "parallel_multiple")
    }
    diagnostics = [
        BfclDiagnostic(
            parseable=index != 0,
            schema_valid=index > 1,
            parsed_call_count=1,
            expected_call_count=1,
            wrong_function_name_count=1 if index == 1 else 0,
            missing_parameter_count=0,
            extra_parameter_count=0,
            type_error_parameter_count=0,
            call_count_error=index == 0,
            structure_error=index == 0,
            parse_error="missing_tool_call" if index == 0 else None,
        )
        for index in range(8)
    ]

    metrics = compute_bfcl_metrics(
        scores=scores,
        diagnostics=diagnostics,
        generation_latency_ms=[100.0] * 8,
        wall_time_seconds=2.0,
        cuda_peak_allocated_bytes=123,
        cuda_peak_reserved_bytes=456,
    )

    assert metrics["task_count"] == 8
    assert metrics["official_ast_accuracy"] == 0.5
    assert metrics["official_correct_count"] == 4
    assert metrics["official_error_count"] == 4
    assert metrics["parseable_rate"] == 0.875
    assert metrics["schema_valid_rate"] == 0.75
    assert metrics["wrong_function_name_count"] == 1
    assert metrics["call_count_error_count"] == 1
    assert metrics["average_task_wall_time_seconds"] == 0.25
    assert metrics["cuda_peak_reserved_bytes"] == 456
