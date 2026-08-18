"""固定源码 BFCL 官方 AST evaluator 的隔离进程集成测试。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


#: 上游 BFCL 的自包含 checkout。它是 ignored 的（固定 commit，按 BFCL_PIN.txt 重建），
#: 因此在一个干净 clone 上并不存在——那时这两条应当 **skip 并说明原因**，
#: 而不是红成"测试挂了"。2026-08-17 外部审阅第六轮在干净 clone 上撞到的就是这个。
_BFCL_REPO = "data/external_repos/gorilla/berkeley-function-call-leaderboard"


def test_official_bfcl_ast_subset_runner_accepts_correct_and_rejects_wrong(
    tmp_path: Path,
) -> None:
    python = Path("tools/bfcl_eval/.venv/bin/python")
    if not python.is_file():
        pytest.skip(
            "BFCL evaluator 的独立 venv 未安装（uv sync --project tools/bfcl_eval --frozen）"
        )
    model_dir = tmp_path / "results/Qwen_Qwen3-1.7B-FC/non_live"
    model_dir.mkdir(parents=True)
    rows = [
        {
            "id": "simple_python_0",
            "result": (
                '<tool_call>\n{"name":"calculate_triangle_area","arguments":'
                '{"base":10,"height":5,"unit":"units"}}\n</tool_call>'
            ),
        },
        {
            "id": "simple_python_1",
            "result": (
                '<tool_call>\n{"name":"math.factorial","arguments":{"number":6}}\n</tool_call>'
            ),
        },
    ]
    result_path = model_dir / "BFCL_v4_simple_python_result.json"
    result_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "bfcl_commit": "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8",
                "seed": 0,
                "tasks": [
                    {"category": "simple_python", "task_id": "simple_python_0"},
                    {"category": "simple_python", "task_id": "simple_python_1"},
                ],
            }
        ),
        encoding="utf-8",
    )

    if not (ROOT / _BFCL_REPO).is_dir():
        pytest.skip(
            "上游 BFCL checkout 是 ignored 的自包含目录（按 data/external_repos/BFCL_PIN.txt 重建）"
        )

    command = [
        str(python),
        "scripts/legacy/bfcl/run_bfcl_official_ast.py",
        "--bfcl-repo",
        _BFCL_REPO,
        "--expected-commit",
        "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8",
        "--manifest",
        str(manifest_path),
        "--model",
        "Qwen/Qwen3-1.7B-FC",
        "--test-category",
        "simple_python",
        "--result-dir",
        str(tmp_path / "results"),
        "--score-dir",
        str(tmp_path / "scores"),
    ]
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )

    score_path = tmp_path / "scores/Qwen_Qwen3-1.7B-FC/non_live/BFCL_v4_simple_python_score.json"
    score_rows = [json.loads(line) for line in score_path.read_text(encoding="utf-8").splitlines()]
    assert score_rows[0] == {"accuracy": 0.5, "correct_count": 1, "total_count": 2}
    assert score_rows[1]["id"] == "simple_python_1"
    assert score_rows[1]["model_name"] == "Qwen_Qwen3-1.7B-FC"
    assert score_rows[1]["valid"] is False
    assert score_rows[1]["error_type"] == "value_error:others"
    assert "official_ast_checker_sha256=" in completed.stdout

    rows[1]["id"] = "simple_python_2"
    result_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    rejected = subprocess.run(command, check=False, capture_output=True, text=True)
    assert rejected.returncode != 0
    assert "Result task IDs do not match frozen manifest" in rejected.stderr


def test_official_bfcl_ast_runner_accepts_sft_manifest_without_holdout(
    tmp_path: Path,
) -> None:
    python = Path("tools/bfcl_eval/.venv/bin/python")
    if not python.is_file():
        pytest.skip(
            "BFCL evaluator 的独立 venv 未安装（uv sync --project tools/bfcl_eval --frozen）"
        )
    model_dir = tmp_path / "results/Qwen_Qwen3-1.7B-FC/non_live"
    model_dir.mkdir(parents=True)
    rows = [
        {
            "id": "simple_python_0",
            "result": (
                '<tool_call>\n{"name":"calculate_triangle_area","arguments":'
                '{"base":10,"height":5,"unit":"units"}}\n</tool_call>'
            ),
        },
        {
            "id": "simple_python_1",
            "result": (
                '<tool_call>\n{"name":"math.factorial","arguments":{"number":5}}\n</tool_call>'
            ),
        },
    ]
    (model_dir / "BFCL_v4_simple_python_result.json").write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "sft-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "bfcl_commit": "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8",
                "holdout_manifest_sha256": "a" * 64,
                "selection_algorithm": "fixed",
                "sources": [],
                "splits": {
                    "train": [{"category": "simple_python", "task_id": "simple_python_0"}],
                    "dev": [{"category": "simple_python", "task_id": "simple_python_1"}],
                    "holdout": [{"category": "simple_python", "task_id": "simple_python_2"}],
                },
            }
        ),
        encoding="utf-8",
    )
    if not (ROOT / _BFCL_REPO).is_dir():
        pytest.skip(
            "上游 BFCL checkout 是 ignored 的自包含目录（按 data/external_repos/BFCL_PIN.txt 重建）"
        )

    command = [
        str(python),
        "scripts/legacy/bfcl/run_bfcl_official_ast.py",
        "--bfcl-repo",
        _BFCL_REPO,
        "--expected-commit",
        "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8",
        "--manifest",
        str(manifest_path),
        "--model",
        "Qwen/Qwen3-1.7B-FC",
        "--test-category",
        "simple_python",
        "--result-dir",
        str(tmp_path / "results"),
        "--score-dir",
        str(tmp_path / "scores"),
    ]

    completed = subprocess.run(command, check=False, capture_output=True, text=True)

    assert completed.returncode == 0, completed.stderr
    score_path = tmp_path / "scores/Qwen_Qwen3-1.7B-FC/non_live/BFCL_v4_simple_python_score.json"
    summary = json.loads(score_path.read_text(encoding="utf-8").splitlines()[0])
    assert summary == {"accuracy": 1.0, "correct_count": 2, "total_count": 2}
