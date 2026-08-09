"""RetailOps qualification 构建与不可变 manifest 测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_build_writes_stable_qualification_manifest(tmp_path: Path) -> None:
    from veritool_rl.retail_ops.build.manifests import build_qualification

    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    first = build_qualification(
        Path("domains/retail_ops/v1"), seed=0, output_dir=first_dir
    )
    second = build_qualification(
        Path("domains/retail_ops/v1"), seed=0, output_dir=second_dir
    )

    assert first == second
    assert first.split == "qualification"
    assert first.task_count == 12
    assert set(first.category_counts.values()) == {2}
    assert len(first.task_sha256) == 12
    assert {path.name for path in first_dir.iterdir()} == {
        "tasks.jsonl",
        "manifest.json",
    }
    assert (first_dir / "tasks.jsonl").read_bytes() == (
        second_dir / "tasks.jsonl"
    ).read_bytes()
    assert (first_dir / "manifest.json").read_bytes() == (
        second_dir / "manifest.json"
    ).read_bytes()


def test_build_rejects_existing_output_directory(tmp_path: Path) -> None:
    from veritool_rl.retail_ops.build.manifests import build_qualification

    output = tmp_path / "run"
    output.mkdir()

    with pytest.raises(FileExistsError, match="输出目录已存在"):
        build_qualification(Path("domains/retail_ops/v1"), 0, output)


def test_load_built_tasks_verifies_manifest_and_task_hashes(tmp_path: Path) -> None:
    from veritool_rl.retail_ops.build.manifests import (
        build_qualification,
        load_built_tasks,
        load_task_manifest,
    )

    output = tmp_path / "run"
    built = build_qualification(Path("domains/retail_ops/v1"), 7, output)

    assert load_task_manifest(output / "manifest.json") == built
    tasks = load_built_tasks(output)
    assert list(tasks) == built.task_ids
    assert all(task.split == "qualification" for task in tasks.values())

    rows = (output / "tasks.jsonl").read_text(encoding="utf-8").splitlines()
    changed = json.loads(rows[0])
    changed["user_request"] = "已篡改的请求"
    rows[0] = json.dumps(changed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    (output / "tasks.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="tasks.jsonl 与 manifest SHA-256 不匹配"):
        load_built_tasks(output)


def test_load_built_tasks_rejects_changed_task_with_refreshed_file_hash(
    tmp_path: Path,
) -> None:
    from veritool_rl.core.artifacts import canonical_json, sha256_file
    from veritool_rl.retail_ops.build.manifests import build_qualification, load_built_tasks

    output = tmp_path / "run"
    build_qualification(Path("domains/retail_ops/v1"), 11, output)
    tasks_path = output / "tasks.jsonl"
    manifest_path = output / "manifest.json"

    rows = tasks_path.read_text(encoding="utf-8").splitlines()
    changed = json.loads(rows[0])
    changed["user_request"] = "已篡改的请求"
    rows[0] = canonical_json(changed)
    tasks_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["tasks_file_sha256"] = sha256_file(tasks_path)
    manifest_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")

    expected_task_id = changed["task_id"]
    with pytest.raises(ValueError, match=f"任务内容 SHA-256 不匹配: {expected_task_id}"):
        load_built_tasks(output)
