"""固定源码 BFCL 官方 AST evaluator 的隔离进程集成测试。"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def test_official_bfcl_ast_evaluator_accepts_correct_and_rejects_wrong(
    tmp_path: Path,
) -> None:
    python = Path("tools/bfcl_eval/.venv/bin/python")
    assert python.is_file(), "请先运行 uv sync --project tools/bfcl_eval --frozen"
    script = r"""
import json
from bfcl_eval.constants.enums import Language, ReturnFormat
from bfcl_eval.eval_checker.ast_eval.ast_checker import ast_checker
from bfcl_eval.model_handler.local_inference.qwen_fc import QwenFCHandler

handler = QwenFCHandler(
    model_name="Qwen/Qwen3-1.7B",
    temperature=0,
    registry_name="Qwen/Qwen3-1.7B-FC",
    is_fc_model=True,
)
functions = [{
    "name": "lookup",
    "description": "Look up one value.",
    "parameters": {
        "type": "dict",
        "properties": {"value": {"type": "integer"}},
        "required": ["value"],
    },
}]
possible = [{"lookup": {"value": [1]}}]

def evaluate(value):
    raw = f'<tool_call>\n{{"name":"lookup","arguments":{{"value":{value}}}}}\n</tool_call>'
    decoded = handler.decode_ast(raw, ReturnFormat.PYTHON, False)
    return ast_checker(
        functions,
        decoded,
        possible,
        Language.PYTHON,
        "simple_python",
        "Qwen/Qwen3-1.7B-FC",
    )

print(json.dumps({"correct": evaluate(1), "wrong": evaluate(2)}))
"""
    env = os.environ.copy()
    env["BFCL_PROJECT_ROOT"] = str(tmp_path)

    completed = subprocess.run(
        [str(python), "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    result = json.loads(completed.stdout)
    assert result["correct"]["valid"] is True
    assert result["wrong"]["valid"] is False
    assert result["wrong"]["error_type"]
