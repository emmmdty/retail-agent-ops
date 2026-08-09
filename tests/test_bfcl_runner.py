"""BFCL 专用生成编排与审计产物测试。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


def _task(task_id: str) -> dict[str, Any]:
    return {
        "id": task_id,
        "question": [[{"role": "user", "content": f"question for {task_id}"}]],
        "function": [
            {
                "name": "lookup",
                "description": "Look up one value.",
                "parameters": {
                    "type": "dict",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                },
            }
        ],
    }


def _answer(task_id: str) -> dict[str, Any]:
    return {"id": task_id, "ground_truth": [{"lookup": {"value": [1]}}]}


def test_generate_bfcl_records_passes_raw_schema_and_preserves_output() -> None:
    from veritool_rl.core.agent.qwen import GeneratedText
    from veritool_rl.legacy.data.bfcl import BfclGroundTruth, BfclTask
    from veritool_rl.legacy.eval.bfcl_runner import generate_bfcl_records

    class FakeBackend:
        def __init__(self) -> None:
            self.requests: list[tuple[list[dict[str, Any]], list[dict[str, Any]], int]] = []

        def generate(
            self,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
            max_new_tokens: int,
        ) -> GeneratedText:
            self.requests.append((messages, tools, max_new_tokens))
            return GeneratedText(
                text=(
                    '<tool_call>\n{"name":"lookup","arguments":{"value":1}}\n'
                    "</tool_call>"
                ),
                input_tokens=21,
                output_tokens=9,
                latency_ms=12.5,
            )

    pairs = [
        (
            BfclTask.model_validate(_task(f"{category}_0")),
            BfclGroundTruth.model_validate(_answer(f"{category}_0")),
        )
        for category in ("simple_python", "multiple", "parallel", "parallel_multiple")
    ]
    backend = FakeBackend()

    records = generate_bfcl_records(pairs, backend, max_new_tokens=512)

    assert [record.task_id for record in records] == [task.id for task, _ in pairs]
    assert all(record.raw_output == records[0].raw_output for record in records)
    assert all(record.diagnostic.schema_valid for record in records)
    messages, tools, max_new_tokens = backend.requests[0]
    assert messages == [{"role": "user", "content": "question for simple_python_0"}]
    assert tools[0]["name"] == "lookup"
    assert tools[0]["parameters"]["type"] == "dict"
    assert "type" not in tools[0]  # 不套 MiniRetail/Transformers function wrapper
    assert max_new_tokens == 512


def test_write_bfcl_generation_artifacts_aligns_raw_and_official_text(
    tmp_path: Path,
) -> None:
    from veritool_rl.core.agent.qwen import GeneratedText
    from veritool_rl.legacy.data.bfcl import BfclGroundTruth, BfclTask
    from veritool_rl.legacy.eval.bfcl_runner import (
        generate_bfcl_records,
        write_bfcl_generation_artifacts,
    )

    class FakeBackend:
        def generate(
            self,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
            max_new_tokens: int,
        ) -> GeneratedText:
            del messages, tools, max_new_tokens
            return GeneratedText(text="  exact raw output\n", latency_ms=1.0)

    pair = (
        BfclTask.model_validate(_task("simple_python_2")),
        BfclGroundTruth.model_validate(_answer("simple_python_2")),
    )
    records = generate_bfcl_records([pair], FakeBackend(), max_new_tokens=32)

    paths = write_bfcl_generation_artifacts(
        tmp_path,
        model_name="Qwen/Qwen3-1.7B-FC",
        records=records,
    )

    raw_row = json.loads((tmp_path / "raw_generations.jsonl").read_text(encoding="utf-8"))
    official_row = json.loads(paths[0].read_text(encoding="utf-8"))
    assert raw_row["raw_output"] == "  exact raw output\n"
    assert official_row["result"] == raw_row["raw_output"]
    assert official_row["id"] == raw_row["task_id"]


def test_generate_bfcl_records_rejects_misaligned_ground_truth() -> None:
    from veritool_rl.legacy.data.bfcl import BfclGroundTruth, BfclTask
    from veritool_rl.legacy.eval.bfcl_runner import generate_bfcl_records

    task = BfclTask.model_validate(_task("simple_python_0"))
    answer = BfclGroundTruth.model_validate(_answer("simple_python_1"))

    with pytest.raises(ValueError, match="ID 不一致"):
        generate_bfcl_records([(task, answer)], object(), max_new_tokens=32)


def test_build_official_evaluator_command_uses_fixed_process_boundary(
    tmp_path: Path,
) -> None:
    from veritool_rl.legacy.eval.bfcl_runner import build_official_evaluator_command

    python = tmp_path / "tools/bfcl_eval/.venv/bin/python"
    evaluator_script = (tmp_path / "scripts/legacy/bfcl/run_bfcl_official_ast.py").resolve()
    bfcl_repo = (tmp_path / "bfcl").resolve()
    manifest_path = (tmp_path / "manifest.json").resolve()
    result_dir = (tmp_path / "results").resolve()
    score_dir = (tmp_path / "scores").resolve()

    command = build_official_evaluator_command(
        python=python,
        evaluator_script=evaluator_script,
        bfcl_repo=bfcl_repo,
        expected_commit="6ea57973c7a6097fd7c5915698c54c17c5b1b6c8",
        manifest_path=manifest_path,
        task_ids=("simple_python_0", "multiple_0"),
        model_name="Qwen/Qwen3-1.7B-FC",
        categories=("simple_python", "multiple"),
        result_dir=result_dir,
        score_dir=score_dir,
    )

    assert command == [
        str(python),
        str(evaluator_script),
        "--bfcl-repo",
        str(bfcl_repo),
        "--expected-commit",
        "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8",
        "--manifest",
        str(manifest_path),
        "--task-id",
        "simple_python_0",
        "--task-id",
        "multiple_0",
        "--model",
        "Qwen/Qwen3-1.7B-FC",
        "--test-category",
        "simple_python",
        "multiple",
        "--result-dir",
        str(result_dir),
        "--score-dir",
        str(score_dir),
    ]


def test_finalize_bfcl_artifacts_writes_metrics_and_real_failure(
    tmp_path: Path,
) -> None:
    from veritool_rl.core.agent.qwen import GeneratedText
    from veritool_rl.legacy.data.bfcl import BfclGroundTruth, BfclTask
    from veritool_rl.legacy.eval.bfcl_runner import (
        finalize_bfcl_artifacts,
        generate_bfcl_records,
    )

    class WrongBackend:
        def generate(
            self,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
            max_new_tokens: int,
        ) -> GeneratedText:
            del messages, tools, max_new_tokens
            return GeneratedText(
                text=(
                    '<tool_call>\n{"name":"wrong","arguments":{"value":1}}\n'
                    "</tool_call>"
                ),
                latency_ms=5.0,
            )

    pair = (
        BfclTask.model_validate(_task("simple_python_2")),
        BfclGroundTruth.model_validate(_answer("simple_python_2")),
    )
    records = generate_bfcl_records([pair], WrongBackend(), max_new_tokens=32)
    score_dir = (
        tmp_path
        / "official_scores/Qwen_Qwen3-1.7B-FC/non_live"
    )
    score_dir.mkdir(parents=True)
    score_rows = [
        {"accuracy": 0.0, "correct_count": 0, "total_count": 1},
        {
            "id": "simple_python_2",
            "valid": False,
            "error_type": "simple_function_checker:wrong_func_name",
            "error": ["wrong function"],
        },
    ]
    (score_dir / "BFCL_v4_simple_python_score.json").write_text(
        "".join(json.dumps(row) + "\n" for row in score_rows),
        encoding="utf-8",
    )

    metrics = finalize_bfcl_artifacts(
        output_dir=tmp_path,
        model_name="Qwen/Qwen3-1.7B-FC",
        records=records,
        task_answers=[pair],
        wall_time_seconds=1.5,
        cuda_peak_allocated_bytes=10,
        cuda_peak_reserved_bytes=20,
        is_sft=True,
    )

    assert metrics["official_ast_accuracy"] == 0.0
    failure = json.loads((tmp_path / "failures.jsonl").read_text(encoding="utf-8"))
    assert failure["task_id"] == "simple_python_2"
    assert failure["user_question"][0]["content"] == "question for simple_python_2"
    assert failure["function_schema"][0]["name"] == "lookup"
    assert failure["raw_model_output"] == records[0].raw_output
    assert failure["expected_calls"] == pair[1].ground_truth
    assert failure["official_error_type"] == "simple_function_checker:wrong_func_name"
    assert failure["root_cause"] == "模型选择了错误的函数名"
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert (
        "Qwen3-1.7B 在项目定义的 BFCL V4 非重叠公开数据划分上进行 "
        "QLoRA-SFT 后，在固定 1 条单轮 AST holdout 子集上的结果"
    ) in report
    assert "不是 BFCL 官方全量成绩或排行榜成绩" in report
    assert "总耗时：1.500 秒" in report
    assert "平均每任务耗时：1.500 秒" in report
    assert "GPU 峰值 allocated：10 bytes" in report
    assert "GPU 峰值 reserved：20 bytes" in report


def test_run_official_evaluator_creates_isolated_project_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from veritool_rl.legacy.eval.bfcl_runner import run_official_evaluator

    monkeypatch.chdir(tmp_path)
    python = Path("tools/bfcl_eval/.venv/bin/python")
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    evaluator_script = tmp_path / "scripts/legacy/bfcl/run_bfcl_official_ast.py"
    evaluator_script.parent.mkdir(parents=True)
    evaluator_script.write_text("", encoding="utf-8")
    bfcl_repo = tmp_path / "bfcl"
    bfcl_repo.mkdir()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    project_root = tmp_path / "new-runtime"

    def fake_run(command: list[str], **kwargs: Any) -> SimpleNamespace:
        assert Path(command[0]).is_absolute()
        assert Path(command[1]).is_absolute()
        assert project_root.is_dir()
        assert kwargs["cwd"] == project_root
        return SimpleNamespace(returncode=0, stdout="official ok")

    monkeypatch.setattr("veritool_rl.legacy.eval.bfcl_runner.subprocess.run", fake_run)

    _, output, _ = run_official_evaluator(
        python=python,
        evaluator_script=evaluator_script,
        bfcl_repo=bfcl_repo,
        expected_commit="6ea57973c7a6097fd7c5915698c54c17c5b1b6c8",
        manifest_path=manifest_path,
        task_ids=("simple_python_0",),
        project_root=project_root,
        model_name="Qwen/Qwen3-1.7B-FC",
        categories=("simple_python",),
        result_dir=tmp_path / "results",
        score_dir=tmp_path / "scores",
    )

    assert output == "official ok"


def test_bfcl_eval_config_accepts_only_project_relative_adapter_path() -> None:
    import yaml

    from scripts.legacy.bfcl.evaluate_bfcl import _validate_config

    config = yaml.safe_load(
        Path("configs/legacy/bfcl_v4_single_turn_seed0.yaml").read_text(encoding="utf-8")
    )
    config["policy"]["adapter_path"] = (
        "reports/legacy/bfcl/qwen3-1.7b-sft-seed0/training/adapter"
    )

    parsed = _validate_config(config, seed=0)

    assert parsed["adapter_path"] == config["policy"]["adapter_path"]

    config["policy"]["adapter_path"] = "/data/TJK/adapter"
    with pytest.raises(ValueError, match="项目相对路径"):
        _validate_config(config, seed=0)
