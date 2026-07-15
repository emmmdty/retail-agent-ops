"""Run the fixed-source BFCL AST checker on an explicit single-turn subset."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
import types
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

MODEL_NAME = "Qwen/Qwen3-1.7B-FC"
SUPPORTED_CATEGORIES = (
    "simple_python",
    "multiple",
    "parallel",
    "parallel_multiple",
)
_TOOL_CALL_PATTERN = re.compile(r"<tool_call>\n(.*?)\n</tool_call>", re.DOTALL)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score a frozen BFCL V4 single-turn subset with official ast_checker",
    )
    parser.add_argument("--bfcl-repo", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument("--model", required=True, choices=(MODEL_NAME,))
    parser.add_argument(
        "--test-category",
        nargs="+",
        required=True,
        choices=SUPPORTED_CATEGORIES,
    )
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--score-dir", type=Path, required=True)
    return parser.parse_args()


def _run_git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _verify_checkout(repo: Path, expected_commit: str) -> None:
    actual_commit = _run_git(repo, "rev-parse", "HEAD").strip()
    if actual_commit != expected_commit:
        raise ValueError(f"BFCL commit mismatch: {actual_commit} != {expected_commit}")
    status = _run_git(repo, "status", "--porcelain")
    if status.strip():
        raise ValueError(f"BFCL checkout is modified:\n{status}")


def _read_model_underscore_to_dot(model_config_path: Path, model_name: str) -> bool:
    """Read the one checker-relevant model flag without importing heavy handlers."""
    tree = ast.parse(model_config_path.read_text(encoding="utf-8"))
    values: list[bool] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            if not isinstance(key, ast.Constant) or key.value != model_name:
                continue
            if not isinstance(value, ast.Call):
                raise ValueError(f"Invalid BFCL model config entry for {model_name}")
            for keyword in value.keywords:
                if keyword.arg == "underscore_to_dot" and isinstance(
                    keyword.value, ast.Constant
                ):
                    values.append(keyword.value.value)
    if values != [False]:
        raise ValueError(
            f"Expected one {model_name} config with underscore_to_dot=False, got {values}"
        )
    return values[0]


def _load_official_checker(
    repo: Path,
    model_name: str,
) -> tuple[Callable[..., dict[str, Any]], Any, Path]:
    model_config_path = repo / "bfcl_eval/constants/model_config.py"
    underscore_to_dot = _read_model_underscore_to_dot(model_config_path, model_name)
    module_name = "bfcl_eval.constants.model_config"
    model_config_stub = types.ModuleType(module_name)
    model_config_stub.MODEL_CONFIG_MAPPING = {
        model_name: SimpleNamespace(underscore_to_dot=underscore_to_dot)
    }
    sys.modules[module_name] = model_config_stub
    sys.path.insert(0, str(repo))

    from bfcl_eval.constants.enums import Language
    from bfcl_eval.eval_checker.ast_eval.ast_checker import ast_checker

    checker_path = repo / "bfcl_eval/eval_checker/ast_eval/ast_checker.py"
    return ast_checker, Language, checker_path


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"Expected JSON object at {path}:{line_number}")
        rows.append(row)
    if not rows:
        raise ValueError(f"Empty JSONL file: {path}")
    return rows


def _index_unique(rows: list[dict[str, Any]], source: Path) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        task_id = row.get("id")
        if not isinstance(task_id, str):
            raise ValueError(f"Non-string task ID in {source}")
        if task_id in indexed:
            raise ValueError(f"Duplicate task ID {task_id} in {source}")
        indexed[task_id] = row
    return indexed


def _load_expected_ids(
    manifest_path: Path,
    expected_commit: str,
    categories: list[str],
    requested_task_ids: list[str],
) -> dict[str, list[str]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError(f"Invalid frozen manifest: {manifest_path}")
    if manifest.get("bfcl_commit") != expected_commit or manifest.get("seed") != 0:
        raise ValueError("Frozen manifest commit or seed does not match the evaluation")
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("Frozen manifest has no tasks")
    manifest_categories: dict[str, str] = {}
    ordered_ids: list[str] = []
    for item in tasks:
        if not isinstance(item, dict):
            raise ValueError("Frozen manifest task entry is not an object")
        category = item.get("category")
        task_id = item.get("task_id")
        if category not in SUPPORTED_CATEGORIES or not isinstance(task_id, str):
            raise ValueError("Frozen manifest task entry has invalid category or task_id")
        if task_id in manifest_categories:
            raise ValueError(f"Duplicate task ID in frozen manifest: {task_id}")
        manifest_categories[task_id] = category
        ordered_ids.append(task_id)

    if len(requested_task_ids) != len(set(requested_task_ids)):
        raise ValueError("Requested task IDs contain duplicates")
    selected = set(requested_task_ids or ordered_ids)
    unknown = sorted(selected - set(manifest_categories))
    if unknown:
        raise ValueError(f"Requested task IDs are outside the frozen manifest: {unknown}")
    expected_by_category = {
        category: [
            task_id
            for task_id in ordered_ids
            if task_id in selected and manifest_categories[task_id] == category
        ]
        for category in categories
    }
    empty_categories = [
        category for category, task_ids in expected_by_category.items() if not task_ids
    ]
    selected_categories = {manifest_categories[task_id] for task_id in selected}
    if empty_categories or selected_categories != set(categories):
        raise ValueError(
            "Requested categories and frozen manifest task IDs do not match: "
            f"empty={empty_categories}, selected={sorted(selected_categories)}"
        )
    return expected_by_category


def _decode_qwen_ast(raw_result: Any) -> list[dict[Any, dict[str, Any]]]:
    """Mirror the fixed QwenFCHandler.decode_ast contract for result conversion."""
    matches = _TOOL_CALL_PATTERN.findall(raw_result)
    tool_calls: list[Any] = []
    for match in matches:
        try:
            tool_calls.append(json.loads(match))
        except Exception:  # noqa: BLE001 - official handler skips malformed blocks.
            pass
    if any(type(item) is not dict for item in tool_calls):
        raise ValueError(f"Model did not return a list of function calls: {raw_result}")
    return [
        {call["name"]: {key: value for key, value in call["arguments"].items()}}
        for call in tool_calls
    ]


def _is_function_calling_output(decoded: Any) -> bool:
    if type(decoded) is not list:
        return False
    return all(
        type(item) is dict
        and len(item) == 1
        and type(next(iter(item.values()))) is dict
        for item in decoded
    )


def _evaluate_entry(
    *,
    ast_checker: Callable[..., dict[str, Any]],
    language: Any,
    result: dict[str, Any],
    prompt: dict[str, Any],
    possible_answer: dict[str, Any],
    model_name: str,
    category: str,
) -> dict[str, Any]:
    task_id = result["id"]
    raw_result = result.get("result")
    ground_truth = possible_answer["ground_truth"]
    try:
        decoded = _decode_qwen_ast(raw_result)
    except Exception as error:  # noqa: BLE001 - mirrors official decoder boundary.
        return {
            "id": task_id,
            "model_name": model_name,
            "test_category": category,
            "valid": False,
            "error": [f"Invalid syntax. Failed to decode AST. {error}"],
            "error_type": "ast_decoder:decoder_failed",
            "prompt": prompt,
            "model_result_raw": raw_result,
            "possible_answer": ground_truth,
        }
    if not _is_function_calling_output(decoded):
        return {
            "id": task_id,
            "model_name": model_name,
            "test_category": category,
            "valid": False,
            "error": [
                "Did not output in the specified format. Note: the model_result is "
                "wrapped in a string to ensure json serializability."
            ],
            "error_type": "ast_decoder:decoder_wrong_output_format",
            "prompt": prompt,
            "model_result_raw": str(raw_result),
            "model_result_decoded": str(decoded),
            "possible_answer": ground_truth,
        }
    checker_result = ast_checker(
        prompt["function"],
        decoded,
        ground_truth,
        language.PYTHON,
        category,
        model_name,
    )
    if checker_result["valid"]:
        return {"valid": True}
    return {
        "id": task_id,
        "model_name": model_name,
        "test_category": category,
        "valid": False,
        "error": checker_result["error"],
        "error_type": checker_result["error_type"],
        "prompt": prompt,
        "model_result_raw": raw_result,
        "model_result_decoded": decoded,
        "possible_answer": ground_truth,
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _score_category(
    *,
    repo: Path,
    result_root: Path,
    score_root: Path,
    model_name: str,
    category: str,
    expected_ids: list[str],
    ast_checker: Callable[..., dict[str, Any]],
    language: Any,
) -> dict[str, Any]:
    escaped_model = model_name.replace("/", "_")
    data_root = repo / "bfcl_eval/data"
    prompt_path = data_root / f"BFCL_v4_{category}.json"
    answer_path = data_root / "possible_answer" / f"BFCL_v4_{category}.json"
    result_path = (
        result_root
        / escaped_model
        / "non_live"
        / f"BFCL_v4_{category}_result.json"
    )
    prompts = _index_unique(_read_jsonl(prompt_path), prompt_path)
    answers = _index_unique(_read_jsonl(answer_path), answer_path)
    results = _read_jsonl(result_path)
    result_index = _index_unique(results, result_path)
    result_ids = set(result_index)
    expected_id_set = set(expected_ids)
    if result_ids != expected_id_set:
        missing = sorted(expected_id_set - result_ids)
        extra = sorted(result_ids - expected_id_set)
        raise ValueError(
            "Result task IDs do not match frozen manifest: "
            f"category={category}, missing={missing}, extra={extra}"
        )
    if set(prompts) != set(answers):
        raise ValueError(f"Prompt/answer task IDs differ for {category}")
    unknown_ids = sorted(result_ids - set(prompts))
    if unknown_ids:
        raise ValueError(f"Result has unknown task IDs for {category}: {unknown_ids}")

    failures: list[dict[str, Any]] = []
    for result in results:
        task_id = result["id"]
        entry = _evaluate_entry(
            ast_checker=ast_checker,
            language=language,
            result=result,
            prompt=prompts[task_id],
            possible_answer=answers[task_id],
            model_name=escaped_model,
            category=category,
        )
        if not entry["valid"]:
            failures.append(entry)
    correct_count = len(results) - len(failures)
    header = {
        "accuracy": correct_count / len(results),
        "correct_count": correct_count,
        "total_count": len(results),
    }
    score_path = (
        score_root
        / escaped_model
        / "non_live"
        / f"BFCL_v4_{category}_score.json"
    )
    _write_jsonl(score_path, [header, *failures])
    return header


def main() -> None:
    args = _parse_args()
    repo = args.bfcl_repo.resolve()
    _verify_checkout(repo, args.expected_commit)
    ast_checker, language, checker_path = _load_official_checker(repo, args.model)
    expected_ids = _load_expected_ids(
        args.manifest.resolve(),
        args.expected_commit,
        args.test_category,
        args.task_id,
    )
    checker_sha256 = hashlib.sha256(checker_path.read_bytes()).hexdigest()
    print(f"bfcl_commit={args.expected_commit}")
    print(f"official_ast_checker={checker_path}")
    print(f"official_ast_checker_sha256={checker_sha256}")
    for category in args.test_category:
        header = _score_category(
            repo=repo,
            result_root=args.result_dir.resolve(),
            score_root=args.score_dir.resolve(),
            model_name=args.model,
            category=category,
            expected_ids=expected_ids[category],
            ast_checker=ast_checker,
            language=language,
        )
        print(
            f"category={category} correct={header['correct_count']} "
            f"total={header['total_count']} accuracy={header['accuracy']:.12f}"
        )


if __name__ == "__main__":
    main()
