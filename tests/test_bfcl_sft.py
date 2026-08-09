"""BFCL QLoRA-SFT 数据冻结、target 和显式 loss mask 测试。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

CATEGORIES = ("simple_python", "multiple", "parallel", "parallel_multiple")
SOURCE_COUNTS = {
    "simple_python": 400,
    "multiple": 200,
    "parallel": 200,
    "parallel_multiple": 200,
}
HOLDOUT_QUOTAS = dict.fromkeys(CATEGORIES, 50)


def _task(task_id: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": task_id,
        "question": [[{"role": "user", "content": f"question for {task_id}"}]],
        "function": [
            {
                "name": "lookup",
                "description": "Look up one value.",
                "parameters": parameters
                or {
                    "type": "dict",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                },
            }
        ],
    }


def _answer(task_id: str) -> dict[str, Any]:
    return {"id": task_id, "ground_truth": [{"lookup": {"value": [1]}}]}


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_full_sources(root: Path) -> dict[str, list[str]]:
    ids_by_category: dict[str, list[str]] = {}
    for category, count in SOURCE_COUNTS.items():
        ids = [f"{category}_{index}" for index in range(count)]
        ids_by_category[category] = ids
        _write_jsonl(root / f"BFCL_v4_{category}.json", [_task(task_id) for task_id in ids])
        _write_jsonl(
            root / "possible_answer" / f"BFCL_v4_{category}.json",
            [_answer(task_id) for task_id in ids],
        )
    return ids_by_category


def test_build_bfcl_sft_manifest_freezes_disjoint_exact_splits(tmp_path: Path) -> None:
    from veritool_rl.core.artifacts import sha256_file
    from veritool_rl.legacy.data.bfcl import build_bfcl_manifest
    from veritool_rl.legacy.data.bfcl_sft import build_bfcl_sft_manifest

    data_root = tmp_path / "data"
    _write_full_sources(data_root)
    holdout = build_bfcl_manifest(
        data_root=data_root,
        bfcl_commit="6ea57973c7a6097fd7c5915698c54c17c5b1b6c8",
        seed=0,
        quotas=HOLDOUT_QUOTAS,
    )
    holdout_path = tmp_path / "holdout.json"
    holdout_path.write_text(
        json.dumps(holdout.model_dump(mode="json"), sort_keys=True),
        encoding="utf-8",
    )

    first = build_bfcl_sft_manifest(data_root, holdout_path)
    second = build_bfcl_sft_manifest(data_root, holdout_path)

    assert first == second
    assert first.holdout_manifest_sha256 == sha256_file(holdout_path)
    assert {category: 0 for category in CATEGORIES} == {
        category: sum(item.category == category for item in first.splits.holdout)
        - HOLDOUT_QUOTAS[category]
        for category in CATEGORIES
    }
    assert len(first.splits.train) == 720
    assert len(first.splits.dev) == 80
    assert len(first.splits.holdout) == 200
    assert {
        category: sum(item.category == category for item in first.splits.train)
        for category in CATEGORIES
    } == {
        "simple_python": 315,
        "multiple": 135,
        "parallel": 135,
        "parallel_multiple": 135,
    }
    assert {
        category: sum(item.category == category for item in first.splits.dev)
        for category in CATEGORIES
    } == {
        "simple_python": 35,
        "multiple": 15,
        "parallel": 15,
        "parallel_multiple": 15,
    }
    split_ids = [
        {item.task_id for item in split}
        for split in (first.splits.train, first.splits.dev, first.splits.holdout)
    ]
    assert not (split_ids[0] & split_ids[1])
    assert not (split_ids[0] & split_ids[2])
    assert not (split_ids[1] & split_ids[2])
    assert len(set().union(*split_ids)) == 1000
    expected_first_dev = min(
        set(range(400))
        - {
            int(item.task_id.rsplit("_", 1)[1])
            for item in first.splits.holdout
            if item.category == "simple_python"
        },
        key=lambda index: hashlib.sha256(
            f"bfcl-sft-dev:0:simple_python_{index}".encode()
        ).hexdigest(),
    )
    assert first.splits.dev[0].task_id == f"simple_python_{expected_first_dev}"


def test_ground_truth_to_tool_calls_handles_optional_nested_and_variable_values() -> None:
    from veritool_rl.legacy.data.bfcl import BfclGroundTruth, BfclTask
    from veritool_rl.legacy.data.bfcl_sft import ground_truth_to_tool_calls

    task = BfclTask.model_validate(
        _task(
            "parallel_multiple_999",
            {
                "type": "dict",
                "properties": {
                    "required_value": {"type": "integer"},
                    "optional_value": {"type": "string"},
                    "nested": {
                        "type": "dict",
                        "properties": {
                            "kept": {"type": "integer"},
                            "omitted": {"type": "string"},
                        },
                    },
                    "variable": {"type": "array", "items": {"type": "number"}},
                },
                "required": ["required_value", "nested", "variable"],
            },
        )
    )
    answer = BfclGroundTruth.model_validate(
        {
            "id": task.id,
            "ground_truth": [
                {
                    "lookup": {
                        "required_value": [0, ""],
                        "optional_value": ["unused", ""],
                        "nested": [{"kept": [7], "omitted": ["unused", ""]}],
                        "variable": ["dataset['column']"],
                    }
                }
            ],
        }
    )

    calls = ground_truth_to_tool_calls(task, answer)

    assert calls == [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "arguments": {
                    "required_value": 0,
                    "nested": {"kept": 7},
                    "variable": "dataset['column']",
                },
            },
        }
    ]


def test_ground_truth_to_tool_calls_preserves_parallel_call_order() -> None:
    from veritool_rl.legacy.data.bfcl import BfclGroundTruth, BfclTask
    from veritool_rl.legacy.data.bfcl_sft import ground_truth_to_tool_calls

    payload = _task("parallel_999")
    payload["function"].append(
        {
            "name": "other",
            "description": "Other function.",
            "parameters": {
                "type": "dict",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
            },
        }
    )
    task = BfclTask.model_validate(payload)
    answer = BfclGroundTruth.model_validate(
        {
            "id": task.id,
            "ground_truth": [
                {"other": {"value": [2]}},
                {"lookup": {"value": [1]}},
            ],
        }
    )

    calls = ground_truth_to_tool_calls(task, answer)

    assert [call["function"]["name"] for call in calls] == ["other", "lookup"]


class _FakeTokenizer:
    def __init__(self, *, bad_prefix: bool = False, full_length: int = 5) -> None:
        self.bad_prefix = bad_prefix
        self.full_length = full_length
        self.requests: list[dict[str, Any]] = []

    def apply_chat_template(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        self.requests.append({"messages": messages, **kwargs})
        if kwargs["add_generation_prompt"]:
            return {"input_ids": [1, 2, 3], "attention_mask": [1, 1, 1]}
        prefix = [1, 8, 3] if self.bad_prefix else [1, 2, 3]
        input_ids = [*prefix, *range(10, 10 + self.full_length - len(prefix))]
        return {"input_ids": input_ids, "attention_mask": [1] * len(input_ids)}


def test_tokenize_bfcl_sft_example_uses_qwen_template_and_assistant_only_labels() -> None:
    from veritool_rl.legacy.data.bfcl import BfclGroundTruth, BfclTask
    from veritool_rl.legacy.data.bfcl_sft import tokenize_bfcl_sft_example

    task = BfclTask.model_validate(_task("simple_python_999"))
    answer = BfclGroundTruth.model_validate(_answer(task.id))
    tokenizer = _FakeTokenizer()

    example = tokenize_bfcl_sft_example(task, answer, tokenizer, max_seq_len=8)

    assert example.input_ids == [1, 2, 3, 10, 11]
    assert example.labels == [-100, -100, -100, 10, 11]
    assert example.prompt_token_count == 3
    assert example.target_token_count == 2
    assert example.full_token_count == 5
    assert all(
        request["tools"] == [function.model_dump() for function in task.function]
        for request in tokenizer.requests
    )
    assert all(request["enable_thinking"] is False for request in tokenizer.requests)
    assistant = tokenizer.requests[1]["messages"][-1]
    assert assistant["role"] == "assistant"
    assert assistant["tool_calls"][0]["function"] == {
        "name": "lookup",
        "arguments": {"value": 1},
    }


@pytest.mark.parametrize(
    ("tokenizer", "error"),
    [
        (_FakeTokenizer(bad_prefix=True), "严格前缀"),
        (_FakeTokenizer(full_length=9), "超过 max_seq_len"),
    ],
)
def test_tokenize_bfcl_sft_example_rejects_prefix_mismatch_or_truncation(
    tokenizer: _FakeTokenizer,
    error: str,
) -> None:
    from veritool_rl.legacy.data.bfcl import BfclGroundTruth, BfclTask
    from veritool_rl.legacy.data.bfcl_sft import tokenize_bfcl_sft_example

    task = BfclTask.model_validate(_task("simple_python_999"))
    answer = BfclGroundTruth.model_validate(_answer(task.id))

    with pytest.raises(ValueError, match=error):
        tokenize_bfcl_sft_example(task, answer, tokenizer, max_seq_len=8)


def test_build_bfcl_sft_data_writes_only_non_holdout_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from veritool_rl.core.artifacts import sha256_file, write_json
    from veritool_rl.legacy.data.bfcl import build_bfcl_manifest

    monkeypatch.chdir(tmp_path)
    data_root = Path("data/bfcl")
    _write_full_sources(data_root)
    holdout = build_bfcl_manifest(
        data_root=data_root,
        bfcl_commit="6ea57973c7a6097fd7c5915698c54c17c5b1b6c8",
        seed=0,
        quotas=HOLDOUT_QUOTAS,
    )
    holdout_path = Path("manifests/holdout.json")
    write_json(holdout_path, holdout.model_dump(mode="json"))
    model_path = Path("models/Qwen3-1.7B")
    model_path.mkdir(parents=True)
    evaluator_python = Path("tools/bfcl_eval/.venv/bin/python")
    evaluator_python.parent.mkdir(parents=True)
    evaluator_python.write_text("", encoding="utf-8")
    config = {
        "benchmark": "bfcl_v4_sft",
        "bfcl_repo": "data/external/bfcl",
        "bfcl_data_root": str(data_root),
        "bfcl_commit": "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8",
        "holdout_manifest_path": str(holdout_path),
        "split_manifest_path": "manifests/sft-split.json",
        "audit_report_path": "reports/legacy/bfcl/data-audit.json",
        "model": {"name": str(model_path), "max_seq_len": 8},
        "official_eval": {
            "python": str(evaluator_python),
            "model_name": "Qwen/Qwen3-1.7B-FC",
        },
    }
    config_path = Path("configs/sft.yaml")
    config_path.parent.mkdir()
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    seen_ids: set[str] = set()

    def fake_validate(**kwargs: Any) -> dict[str, Any]:
        examples = kwargs["examples"]
        seen_ids.update(example.task_id for example in examples)
        return {
            "checked_count": len(examples),
            "correct_count": len(examples),
            "accuracy": 1.0,
            "checker_sha256": "b" * 64,
            "command": ["official-checker"],
            "stdout": "800/800",
        }

    monkeypatch.setattr(
        "scripts.legacy.bfcl.build_bfcl_sft_data._load_tokenizer",
        lambda path: _FakeTokenizer(),
    )
    monkeypatch.setattr(
        "scripts.legacy.bfcl.build_bfcl_sft_data._run_official_target_validation",
        fake_validate,
    )
    from scripts.legacy.bfcl.build_bfcl_sft_data import build_bfcl_sft_data

    audit = build_bfcl_sft_data(config_path, seed=0, output_dir=Path("data/output"))

    train_rows = [
        json.loads(line)
        for line in Path("data/output/train.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    dev_rows = [
        json.loads(line)
        for line in Path("data/output/dev.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    holdout_ids = {item.task_id for item in holdout.tasks}
    assert len(train_rows) == 720
    assert len(dev_rows) == 80
    assert len(seen_ids) == 800
    assert not (seen_ids & holdout_ids)
    assert train_rows[0]["labels"] == [-100, -100, -100, 10, 11]
    assert audit["target_validation"]["checked_count"] == 800
    assert audit["token_lengths"]["full"]["max"] == 5
    assert audit["truncation_count"] == 0
    assert audit["split_manifest_sha256"] == sha256_file(Path("manifests/sft-split.json"))
    assert json.loads(Path("reports/legacy/bfcl/data-audit.json").read_text()) == audit
