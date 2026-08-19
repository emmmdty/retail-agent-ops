"""把网格外的增强任务变成可训练的 SFT 行，并与既有训练集合并。

## 为什么是独立的一条流水线，而不是改 `train_export`

`train_export` 的契约是「为**冻结的 240 条 train 任务**逐条选轨迹并导出」，
它的产物同时是 provenance：`train_rows` 声称"本次导出覆盖了哪些冻结任务"。
把网格外的新任务塞进去会让那份声称超出冻结契约，而那正是它存在的意义。

因此这里的形状是：**读一份已导出的 `sft.jsonl` 作为基底，追加增强行，写成新的导出**。
基底 attempt 与增强 attempt 的哈希都进报告，"这份训练集由哪两部分构成"可机械核对。

## 质量口径与既有导出一致

- 每条增强轨迹都必须来自 teacher，且**独立 replay 校验通过**；
  不接受 `internal_reference` 回退——Oracle 轨迹的终局回复是"任务已完成。"，
  与既有 960 行的自然解释不是同一个分布，混进去会让"只改了数据覆盖"这个变量不成立。
- 措辞多样化走**同一条** `sft_paraphrase` 路径、同一个 `train_aug` 分片，
  因此增强行与既有行在表面形式上同分布。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import Field

from veritool_rl.core.artifacts import canonical_json, create_output_dir, write_json, write_jsonl
from veritool_rl.core.trajectory import TaskSpec, Trajectory
from veritool_rl.core.trajectory.schema import StrictModel
from veritool_rl.retail_ops.build.phrasing_bank import (
    SCENARIO_INTENTS,
    ParaphrasePlan,
    paraphrases_for_task,
)
from veritool_rl.retail_ops.build.teacher_data import (
    TeacherAttemptEvidence,
    validate_teacher_trajectory,
)
from veritool_rl.retail_ops.domain.state_augmentation_tasks import (
    STATE_AUG_DATASET_VERSION,
    STATE_AUG_GENERATOR_ID,
)

EnvFactory = Callable[[TaskSpec], Any]


@dataclass(frozen=True)
class AugmentationRecord:
    """满足 `TeacherCollectable` 的最小载体。

    状态增强任务落在冻结网格之外，按定义没有 family canonical payload，
    因此不能构造 `FormalTaskRecord`。采集路径实际只需要任务与它的指纹。
    """

    task: TaskSpec
    task_fingerprint: str

    @classmethod
    def from_task(cls, task: TaskSpec) -> AugmentationRecord:
        digest = hashlib.sha256(
            canonical_json({"task": task.model_dump(mode="json")}).encode("utf-8")
        ).hexdigest()
        return cls(task=task, task_fingerprint=digest)


class StateAugmentationReport(StrictModel):
    """一次状态增强导出的公开报告。私有训练数据不进 Git，这份进。"""

    schema_version: str = "1.0"
    dataset_version: str = Field(min_length=1)
    generator_id: str = Field(min_length=1)
    base_attempt_id: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    #: 增强任务数、被接受的 teacher 轨迹数。两者不等即说明有任务没采到合格轨迹。
    augmentation_task_count: int = Field(ge=1)
    accepted_trajectory_count: int = Field(ge=0)
    #: 逐场景 / 逐 `refund_deadline` 的增强行数——"补在哪里"必须可核对，
    #: 否则"补了远超期区域"只是一句声称。
    augmentation_rows_by_scenario: dict[str, int]
    augmentation_rows_by_deadline: dict[str, int]
    base_row_count: int = Field(ge=1)
    augmentation_row_count: int = Field(ge=1)
    total_row_count: int = Field(ge=1)
    base_sft_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    augmented_sft_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    phrasing_bank_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    paraphrases_per_task: int = Field(ge=1)


class StateAugmentationGateError(RuntimeError):
    """增强素材的覆盖没有达到闸门要求。"""


#: 整体接受率下限。低于它说明采集这条路本身出了问题（凭据、路由、环境），
#: 而不是个别任务难——那种情况下继续导出只会把一份残缺的训练集送进训练。
MIN_ACCEPTANCE_RATE = 0.85


def load_persisted_evidence(private_root: Path, attempt_id: str) -> list[TeacherAttemptEvidence]:
    """读出已落盘的采集证据，用于断点续采。

    teacher 采集是**付费**动作。第一版把证据只留在内存里，于是一次闸门失败
    会连同已经成功的部分一起丢掉——重跑要再付一次钱。既有的 `teacher_collect`
    有 checkpoint，这条路径此前没有，是实现漏了，不是设计如此。
    """
    attempt_dir = private_root / "state-augmentation" / attempt_id
    if not attempt_dir.is_dir():
        return []
    evidences: list[TeacherAttemptEvidence] = []
    for path in sorted(attempt_dir.glob("*.json")):
        evidences.append(
            TeacherAttemptEvidence.model_validate_json(path.read_text(encoding="utf-8"))
        )
    return evidences


def persist_evidence(evidence: TeacherAttemptEvidence, private_root: Path, attempt_id: str) -> None:
    """落盘一条证据。目录名与 `teacher-collection/` 分开，两批素材不混。"""
    attempt_dir = private_root / "state-augmentation" / attempt_id
    attempt_dir.mkdir(parents=True, exist_ok=True)
    target = attempt_dir / f"{evidence.task_id}.json"
    if target.exists():
        return
    # 先写临时文件再改名：采集中途被打断时，目录里不会留下半条 JSON，
    # 而半条 JSON 会让下一次续采在加载阶段直接崩掉。
    staging = target.with_suffix(".json.partial")
    staging.write_text(canonical_json(evidence.model_dump(mode="json")), encoding="utf-8")
    staging.replace(target)


def assert_cell_coverage(tasks: Sequence[TaskSpec], accepted_task_ids: set[str]) -> dict[str, int]:
    """逐 (场景, deadline) 统计被接受数，任一格低于下限即失败。"""
    per_cell: dict[tuple[str, int], int] = {}
    for task in tasks:
        key = (task.scenario.value, int(task.metadata["refund_deadline"]))
        per_cell.setdefault(key, 0)
        if task.task_id in accepted_task_ids:
            per_cell[key] += 1

    counts = {
        f"{scenario}@{deadline}": count for (scenario, deadline), count in sorted(per_cell.items())
    }
    empty = sorted(cell for cell, count in counts.items() if count == 0)
    if empty:
        raise StateAugmentationGateError(
            f"这些格子一条合格轨迹都没有，「补了这个区域」对它们是假话：{empty}"
        )
    rate = len(accepted_task_ids & {task.task_id for task in tasks}) / len(tasks)
    if rate < MIN_ACCEPTANCE_RATE:
        raise StateAugmentationGateError(
            f"整体接受率 {rate:.1%} 低于 {MIN_ACCEPTANCE_RATE:.0%}——"
            f"这更像采集路径本身出了问题，而不是个别任务难"
        )
    return counts


def build_augmentation_rows(
    tasks: Sequence[TaskSpec],
    evidences: Sequence[TeacherAttemptEvidence],
    env_factory: EnvFactory,
    paraphrase: ParaphrasePlan,
) -> list[dict[str, Any]]:
    """把被接受的 teacher 轨迹转成 SFT 行（含措辞改写）。

    未被接受的任务直接跳过——但**逐格覆盖下限先过一遍**（`assert_cell_coverage`），
    因此"某一格其实几乎没补上"不会静默通过。实际补了多少行、补在哪个 deadline，
    逐格写进公开报告。
    """
    from veritool_rl.core.generators import trajectory_to_sft_example

    accepted: dict[str, Trajectory] = {
        evidence.task_id: evidence.trajectory
        for evidence in evidences
        if evidence.accepted and evidence.trajectory is not None
    }
    assert_cell_coverage(tasks, set(accepted))

    rows: list[dict[str, Any]] = []
    for task in tasks:
        trajectory = accepted.get(task.task_id)
        if trajectory is None:
            continue
        if not validate_teacher_trajectory(trajectory, env_factory):
            raise StateAugmentationGateError(f"导出前独立 replay 校验失败: {task.task_id}")
        example = trajectory_to_sft_example(trajectory)
        rows.append(example)
        for text in paraphrases_for_task(
            paraphrase.index,
            intent=SCENARIO_INTENTS[task.scenario],
            task_key=task.task_id,
            count=paraphrase.per_task,
            order_id=str(task.metadata["order_id"]),
        ):
            rewritten = json.loads(canonical_json(example))
            for message in rewritten["messages"]:
                if message.get("role") == "user":
                    message["content"] = text
                    break
            rows.append(rewritten)
    return rows


def write_state_augmented_export(
    *,
    private_root: Path,
    public_root: Path,
    base_attempt_id: str,
    attempt_id: str,
    tasks: Sequence[TaskSpec],
    evidences: Sequence[TeacherAttemptEvidence],
    augmentation_rows: Sequence[dict[str, Any]],
    paraphrase: ParaphrasePlan,
) -> StateAugmentationReport:
    """写出合并后的 `sft.jsonl`（私有）与报告（公开）。"""
    import hashlib

    base_path = private_root / "train-export" / base_attempt_id / "sft.jsonl"
    base_text = base_path.read_text(encoding="utf-8")
    base_rows = [json.loads(line) for line in base_text.splitlines() if line.strip()]

    target_dir = private_root / "train-export" / attempt_id
    if target_dir.exists():
        raise ValueError(f"导出目录已存在，不覆盖已有运行: {target_dir}")
    target_dir.mkdir(parents=True)
    merged = [*base_rows, *augmentation_rows]
    sft_path = target_dir / "sft.jsonl"
    write_jsonl(sft_path, merged)

    deadline_by_task = {task.task_id: int(task.metadata["refund_deadline"]) for task in tasks}
    rows_by_scenario: dict[str, int] = {}
    rows_by_deadline: dict[str, int] = {}
    for row in augmentation_rows:
        scenario = str(row["scenario"])
        rows_by_scenario[scenario] = rows_by_scenario.get(scenario, 0) + 1
        deadline = str(deadline_by_task[str(row["task_id"])])
        rows_by_deadline[deadline] = rows_by_deadline.get(deadline, 0) + 1

    report = StateAugmentationReport(
        dataset_version=STATE_AUG_DATASET_VERSION,
        generator_id=STATE_AUG_GENERATOR_ID,
        base_attempt_id=base_attempt_id,
        attempt_id=attempt_id,
        augmentation_task_count=len(tasks),
        accepted_trajectory_count=sum(1 for evidence in evidences if evidence.accepted),
        augmentation_rows_by_scenario=dict(sorted(rows_by_scenario.items())),
        augmentation_rows_by_deadline=dict(
            sorted(rows_by_deadline.items(), key=lambda item: int(item[0]))
        ),
        base_row_count=len(base_rows),
        augmentation_row_count=len(augmentation_rows),
        total_row_count=len(merged),
        base_sft_sha256=hashlib.sha256(base_text.encode("utf-8")).hexdigest(),
        augmented_sft_sha256=hashlib.sha256(
            sft_path.read_text(encoding="utf-8").encode("utf-8")
        ).hexdigest(),
        phrasing_bank_sha256=paraphrase.bank_sha256,
        paraphrases_per_task=paraphrase.per_task,
    )
    create_output_dir(public_root)
    write_json(public_root / "quality.json", report.model_dump(mode="json"))
    return report
