"""BFCL V4 固定子集数据与 provenance 测试。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

CATEGORIES = ("simple_python", "multiple", "parallel", "parallel_multiple")


def _task(task_id: str) -> dict[str, object]:
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


def _answer(task_id: str) -> dict[str, object]:
    return {"id": task_id, "ground_truth": [{"lookup": {"value": [1]}}]}


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _write_category(root: Path, category: str, ids: list[str]) -> None:
    _write_jsonl(root / f"BFCL_v4_{category}.json", [_task(task_id) for task_id in ids])
    _write_jsonl(
        root / "possible_answer" / f"BFCL_v4_{category}.json",
        [_answer(task_id) for task_id in ids],
    )


def test_load_bfcl_category_validates_jsonl_and_id_alignment(tmp_path: Path) -> None:
    from veritool_rl.legacy.data.bfcl import load_bfcl_category

    _write_category(tmp_path, "simple_python", ["simple_python_0", "simple_python_1"])

    tasks, answers = load_bfcl_category(tmp_path, "simple_python")

    assert [task.id for task in tasks] == ["simple_python_0", "simple_python_1"]
    assert [answer.id for answer in answers] == ["simple_python_0", "simple_python_1"]
    assert tasks[0].question[0][0].content == "question for simple_python_0"


def test_load_bfcl_category_rejects_duplicate_or_misaligned_ids(tmp_path: Path) -> None:
    from veritool_rl.legacy.data.bfcl import load_bfcl_category

    _write_category(tmp_path, "multiple", ["multiple_0", "multiple_0"])
    with pytest.raises(ValueError, match="重复 task_id"):
        load_bfcl_category(tmp_path, "multiple")

    _write_category(tmp_path, "multiple", ["multiple_0", "multiple_1"])
    _write_jsonl(
        tmp_path / "possible_answer/BFCL_v4_multiple.json",
        [_answer("multiple_0"), _answer("multiple_2")],
    )
    with pytest.raises(ValueError, match="ID 集合不一致"):
        load_bfcl_category(tmp_path, "multiple")


def test_load_bfcl_category_rejects_invalid_json(tmp_path: Path) -> None:
    from veritool_rl.legacy.data.bfcl import load_bfcl_category

    source = tmp_path / "BFCL_v4_parallel.json"
    source.write_text("{not-json}\n", encoding="utf-8")
    _write_jsonl(
        tmp_path / "possible_answer/BFCL_v4_parallel.json",
        [_answer("parallel_0")],
    )

    with pytest.raises(ValueError, match="无效 JSONL"):
        load_bfcl_category(tmp_path, "parallel")


def test_stable_hash_selection_is_repeatable_and_enforces_quotas(tmp_path: Path) -> None:
    from veritool_rl.legacy.data.bfcl import load_bfcl_category, select_bfcl_tasks

    tasks_by_category = {}
    expected_ids: dict[str, list[str]] = {}
    for category in CATEGORIES:
        ids = [f"{category}_{index}" for index in range(7)]
        _write_category(tmp_path, category, ids)
        tasks_by_category[category] = load_bfcl_category(tmp_path, category)[0]
        expected_ids[category] = sorted(
            ids,
            key=lambda task_id: hashlib.sha256(f"0:{task_id}".encode()).hexdigest(),
        )[:3]

    first = select_bfcl_tasks(tasks_by_category, seed=0, quotas=dict.fromkeys(CATEGORIES, 3))
    second = select_bfcl_tasks(tasks_by_category, seed=0, quotas=dict.fromkeys(CATEGORIES, 3))

    assert first == second
    assert {
        category: [task.id for task in tasks] for category, tasks in first.items()
    } == expected_ids

    with pytest.raises(ValueError, match="至少需要 8 条"):
        select_bfcl_tasks(tasks_by_category, seed=0, quotas={"simple_python": 8})


def test_build_manifest_records_sources_selection_and_file_hash(tmp_path: Path) -> None:
    from veritool_rl.core.artifacts import sha256_file, write_json
    from veritool_rl.legacy.data.bfcl import build_bfcl_manifest

    for category in CATEGORIES:
        _write_category(tmp_path, category, [f"{category}_{index}" for index in range(3)])

    manifest = build_bfcl_manifest(
        data_root=tmp_path,
        bfcl_commit="6ea57973c7a6097fd7c5915698c54c17c5b1b6c8",
        seed=0,
        quotas=dict.fromkeys(CATEGORIES, 2),
    )
    output = tmp_path / "manifest.json"
    write_json(output, manifest.model_dump(mode="json"))

    assert len(manifest.tasks) == 8
    assert len({task.task_id for task in manifest.tasks}) == 8
    assert {source.selected_count for source in manifest.sources} == {2}
    assert all(len(source.prompt_sha256) == 64 for source in manifest.sources)
    assert all(len(task.selection_sha256) == 64 for task in manifest.tasks)
    assert sha256_file(output) == hashlib.sha256(output.read_bytes()).hexdigest()


def test_build_manifest_cli_writes_named_artifact(tmp_path: Path) -> None:
    from scripts.legacy.bfcl.build_bfcl_manifest import build_manifest_artifact

    for category in CATEGORIES:
        _write_category(tmp_path, category, [f"{category}_0", f"{category}_1"])
    config = {
        "bfcl_commit": "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8",
        "bfcl_data_root": str(tmp_path),
        "manifest_filename": "frozen.json",
        "quotas": dict.fromkeys(CATEGORIES, 1),
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")

    output = build_manifest_artifact(config_path, seed=0, output_dir=tmp_path / "out")

    assert output == tmp_path / "out/frozen.json"
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["seed"] == 0
    assert len(payload["tasks"]) == 4


def test_load_bfcl_manifest_recomputes_provenance(tmp_path: Path) -> None:
    from veritool_rl.core.artifacts import write_json
    from veritool_rl.legacy.data.bfcl import build_bfcl_manifest, load_bfcl_manifest

    for category in CATEGORIES:
        _write_category(tmp_path, category, [f"{category}_{index}" for index in range(3)])
    manifest = build_bfcl_manifest(
        data_root=tmp_path,
        bfcl_commit="6ea57973c7a6097fd7c5915698c54c17c5b1b6c8",
        seed=0,
        quotas=dict.fromkeys(CATEGORIES, 2),
    )
    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, manifest.model_dump(mode="json"))

    loaded = load_bfcl_manifest(manifest_path, tmp_path)

    assert loaded == manifest

    prompt_path = tmp_path / "BFCL_v4_simple_python.json"
    prompt_path.write_text(prompt_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="provenance"):
        load_bfcl_manifest(manifest_path, tmp_path)
