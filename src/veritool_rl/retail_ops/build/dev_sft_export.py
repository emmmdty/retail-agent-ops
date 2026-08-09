"""R3 Task 1: dev 侧 internal-reference（Oracle）SFT 导出。

`teacher_collect` 按设计只碰 train split，因此 dev 从未产生过 teacher 轨迹，
也就没有 dev 侧的 `sft.jsonl`。训练要用 `SFTConfig(eval_strategy="epoch")`
监控泛化就需要一份同格式的 eval 数据，这个模块只负责这一件事。

与 train 侧的关键差别：本模块的公开接口**不接受任何 client 参数**，轨迹只能
由确定性 `OraclePolicy` 产生，因此结构上不可能对 dev 任务发起 teacher 请求，
也不会消耗任何 API 预算。落盘复用 `teacher_data.py` 里已经过独立审查的路径
安全、staging/publish 与失败回滚实现，不重新写一套（该包已有跨模块引用模块
私有名的先例，见 `formal_governance` 引用 `formal_manifests`）。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from veritool_rl.core.artifacts import sha256_file, write_jsonl
from veritool_rl.core.generators import trajectory_to_sft_example
from veritool_rl.retail_ops.build.teacher_data import (
    EnvFactory,
    _atomic_write_json,
    _build_reference_trajectory,
    _make_staging_dir,
    _publish_staging_dir,
    _remove_owned_dir,
    _resolve_within,
    _validate_export_output_pair,
    _validate_path_component,
    validate_teacher_trajectory,
)
from veritool_rl.retail_ops.domain.formal_tasks import FormalTaskRecord

DEV_SFT_SOURCE = "internal_reference"
_PUBLIC_SUMMARY_NAME = "dev-sft.json"


def build_dev_sft_rows(
    records: Sequence[FormalTaskRecord],
    env_factory: EnvFactory,
    seed: int,
) -> list[dict[str, Any]]:
    """对全部 dev 记录用 Oracle 生成轨迹并转成 train 侧同格式的 SFT 样本。

    每条轨迹在转换前都要独立 replay 校验一次；Oracle 本身失败或 replay 不一致
    时整体失败，不产出"部分可用"的 eval 集合——eval 数据不完整会让每个 epoch
    的 eval loss 悄悄换了比较基准。
    """
    if not records:
        msg = "dev SFT 导出输入不能为空"
        raise ValueError(msg)

    rows: list[dict[str, Any]] = []
    seen_task_ids: set[str] = set()
    for record in records:
        task_id = record.task.task_id
        if record.task.split != "dev":
            msg = f"dev SFT 导出只接受 dev split 任务，收到 {record.task.split!r}: {task_id}"
            raise ValueError(msg)
        if task_id in seen_task_ids:
            msg = f"dev SFT 导出发现重复 task_id: {task_id}"
            raise ValueError(msg)
        seen_task_ids.add(task_id)

        (trajectory,) = _build_reference_trajectory(record.task, env_factory, seed)
        if not validate_teacher_trajectory(trajectory, env_factory):
            msg = f"dev SFT 导出前独立 replay 校验失败: {task_id}"
            raise ValueError(msg)
        rows.append(trajectory_to_sft_example(trajectory))
    return rows


def write_dev_sft_export(
    *,
    private_root: Path,
    public_root: Path,
    attempt_id: str,
    dataset_version: str,
    rows: Sequence[dict[str, Any]],
) -> dict[str, str]:
    """把 dev SFT 样本写进 private ignored root，公开 root 只留聚合摘要。

    私有 `sft.jsonl` 经 staging 目录原子发布；公开摘要写入失败（含同名冲突）
    时已发布的私有目录整体回滚删除，不留半成品——与 `write_formal_train_export`
    同一口径。公开摘要只含计数与私有产物哈希，不含任何 task_id 或任务内容。
    """
    _validate_path_component(attempt_id, label="attempt_id")
    private_target = _resolve_within(private_root, "dev-sft", attempt_id)
    _validate_export_output_pair(private_target, public_root)

    staging = _make_staging_dir(private_target)
    private_published = False
    try:
        write_jsonl(staging / "sft.jsonl", rows)
        artifact_hashes = {"sft.jsonl": sha256_file(staging / "sft.jsonl")}
        _publish_staging_dir(staging, private_target)
        private_published = True

        public_summary_path = public_root / _PUBLIC_SUMMARY_NAME
        if public_summary_path.exists() or public_summary_path.is_symlink():
            msg = f"拒绝覆盖已有公开 {_PUBLIC_SUMMARY_NAME}: {public_summary_path}"
            raise FileExistsError(msg)
        _atomic_write_json(
            public_summary_path,
            {
                "dataset_version": dataset_version,
                "attempt_id": attempt_id,
                "total_tasks": len(rows),
                "source": DEV_SFT_SOURCE,
                "private_artifact_sha256": artifact_hashes,
            },
        )
        return artifact_hashes
    except BaseException:
        if private_published:
            _remove_owned_dir(private_target)
        else:
            _remove_owned_dir(staging)
        raise
