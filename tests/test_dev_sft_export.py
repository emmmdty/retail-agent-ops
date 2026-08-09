"""R3 Task 1: dev 侧 Oracle-only SFT 导出测试（不涉及 teacher、模型或 GPU）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from veritool_rl.retail_ops.build.dev_sft_export import (
    build_dev_sft_rows,
    write_dev_sft_export,
)
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
from veritool_rl.retail_ops.domain.formal_tasks import FormalTaskRecord, build_formal_task_set

_DATASET_VERSION = "test-dataset-r3-dev-sft"
_BUNDLE = load_bundle(Path("domains/retail_ops/v1"))


def _env_factory(task: Any) -> RetailOpsEnv:
    return RetailOpsEnv(task, _BUNDLE)


def _records(split: str, limit: int | None = None) -> list[FormalTaskRecord]:
    task_set = build_formal_task_set(_DATASET_VERSION, seed=0)
    records = list(task_set.records(split))
    return records if limit is None else records[:limit]


# ---------------------------------------------------------------------------
# build_dev_sft_rows：Oracle-only 轨迹与 SFT 样本形状
# ---------------------------------------------------------------------------


def test_dev_sft_rows_match_train_side_sft_example_shape() -> None:
    """dev 侧样本必须与 train 侧 `sft.jsonl` 同结构，训练器才能同格式加载。"""
    records = _records("dev", limit=6)

    rows = build_dev_sft_rows(records, _env_factory, seed=0)

    assert len(rows) == len(records)
    for row, record in zip(rows, records, strict=True):
        assert sorted(row) == ["messages", "scenario", "task_id", "tools"]
        assert row["task_id"] == record.task.task_id
        assert row["scenario"] == record.task.scenario.value
        assert isinstance(row["tools"], list) and row["tools"]
        roles = [message["role"] for message in row["messages"]]
        assert roles[:2] == ["system", "user"]
        assert "assistant" in roles[2:]


def test_dev_sft_rows_cover_every_dev_scenario_deterministically() -> None:
    """同一 seed 重跑必须逐字节一致，并覆盖全部六类 dev 场景。"""
    records = _records("dev")

    first = build_dev_sft_rows(records, _env_factory, seed=0)
    second = build_dev_sft_rows(records, _env_factory, seed=0)

    assert first == second
    assert len({row["scenario"] for row in first}) == 6


@pytest.mark.parametrize("split", ["train", "holdout"])
def test_dev_sft_rows_reject_non_dev_split(split: str) -> None:
    """train/holdout 记录不得从这条 dev 通道产出训练数据。"""
    records = _records(split, limit=2)

    with pytest.raises(ValueError, match="dev"):
        build_dev_sft_rows(records, _env_factory, seed=0)


def test_dev_sft_rows_reject_duplicate_task_ids() -> None:
    record = _records("dev", limit=1)[0]

    with pytest.raises(ValueError, match="重复"):
        build_dev_sft_rows([record, record], _env_factory, seed=0)


def test_dev_sft_rows_reject_empty_records() -> None:
    with pytest.raises(ValueError, match="不能为空"):
        build_dev_sft_rows([], _env_factory, seed=0)


# ---------------------------------------------------------------------------
# write_dev_sft_export：私有落盘、公开摘要、不可覆盖与失败原子性
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, rows: list[dict[str, Any]], attempt_id: str = "dev-sft-001") -> Any:
    return write_dev_sft_export(
        private_root=tmp_path / "private",
        public_root=tmp_path / "public",
        attempt_id=attempt_id,
        dataset_version=_DATASET_VERSION,
        rows=rows,
    )


def test_write_dev_sft_export_puts_rows_private_and_summary_public(tmp_path: Path) -> None:
    rows = build_dev_sft_rows(_records("dev", limit=4), _env_factory, seed=0)
    (tmp_path / "private").mkdir()
    (tmp_path / "public").mkdir()

    hashes = _write(tmp_path, rows)

    artifact = tmp_path / "private/dev-sft/dev-sft-001/sft.jsonl"
    written = [json.loads(line) for line in artifact.read_text(encoding="utf-8").splitlines()]
    assert written == rows
    assert sorted(hashes) == ["sft.jsonl"]

    summary = json.loads((tmp_path / "public/dev-sft.json").read_text(encoding="utf-8"))
    assert summary["dataset_version"] == _DATASET_VERSION
    assert summary["attempt_id"] == "dev-sft-001"
    assert summary["total_tasks"] == 4
    assert summary["source"] == "internal_reference"
    assert summary["private_artifact_sha256"] == hashes

    # 公开摘要不得携带任何任务级真值。
    text = (tmp_path / "public/dev-sft.json").read_text(encoding="utf-8")
    for row in rows:
        assert row["task_id"] not in text


def test_write_dev_sft_export_refuses_to_overwrite_existing_attempt(tmp_path: Path) -> None:
    rows = build_dev_sft_rows(_records("dev", limit=2), _env_factory, seed=0)
    (tmp_path / "private").mkdir()
    (tmp_path / "public").mkdir()
    _write(tmp_path, rows)
    original = (tmp_path / "private/dev-sft/dev-sft-001/sft.jsonl").read_bytes()

    with pytest.raises(FileExistsError):
        _write(tmp_path, rows)

    assert (tmp_path / "private/dev-sft/dev-sft-001/sft.jsonl").read_bytes() == original


def test_write_dev_sft_export_rolls_back_private_when_public_summary_conflicts(
    tmp_path: Path,
) -> None:
    """公开摘要冲突时不得留下已发布的私有目录（与 train 导出同一原子性口径）。"""
    rows = build_dev_sft_rows(_records("dev", limit=2), _env_factory, seed=0)
    (tmp_path / "private").mkdir()
    (tmp_path / "public").mkdir()
    (tmp_path / "public/dev-sft.json").write_text("{}", encoding="utf-8")

    with pytest.raises(FileExistsError):
        _write(tmp_path, rows)

    # attempt 目录必须整体消失；残留的空 `dev-sft/` 父目录不含任何产物，
    # 与 `write_formal_train_export` 的回滚口径一致。
    assert not (tmp_path / "private/dev-sft/dev-sft-001").exists()
    assert list((tmp_path / "private/dev-sft").iterdir()) == []


@pytest.mark.parametrize("attempt_id", ["../escape", "a/b", "", ".."])
def test_write_dev_sft_export_rejects_unsafe_attempt_id(tmp_path: Path, attempt_id: str) -> None:
    rows = build_dev_sft_rows(_records("dev", limit=1), _env_factory, seed=0)
    (tmp_path / "private").mkdir()
    (tmp_path / "public").mkdir()

    with pytest.raises(ValueError, match="attempt_id"):
        _write(tmp_path, rows, attempt_id=attempt_id)


def test_write_dev_sft_export_rejects_public_root_inside_private_artifact_tree(
    tmp_path: Path,
) -> None:
    """公开摘要目录不得落在私有 attempt 产物树内部，否则聚合摘要会与真值同目录。"""
    rows = build_dev_sft_rows(_records("dev", limit=1), _env_factory, seed=0)
    root = tmp_path / "private"
    (root / "dev-sft").mkdir(parents=True)

    with pytest.raises(ValueError, match="分离"):
        write_dev_sft_export(
            private_root=root,
            public_root=root / "dev-sft",
            attempt_id="dev-sft-001",
            dataset_version=_DATASET_VERSION,
            rows=rows,
        )
