"""分布外任务集的**独立** manifest 与产物。

这是评审 P0-1 要求的形状：新任务集必须作为独立 dataset artifact 存在——自己的
`dataset_version`、自己的 manifest——**绝不**加成 `FormalTaskSet` 的第四个字段，
也不动 40/10/20 配额。冻结数据集 `retail_ops_v1_r2_20260722` 因此一个字节不变，
建立在它上面的全部评测证据保持可比。

与封存 holdout 的另一处根本差异：**这个集合不封存**。它的用途是回答"模板外还成不成"，
需要被反复读、被分析、被讨论；而封存 holdout 的价值恰恰来自"只被观测过几次"。
两者的治理级别不同，因此走两条完全独立的代码路径，共用的只有环境与 verifier。
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import Field

from veritool_rl.core.artifacts import (
    canonical_json,
    create_output_dir,
    sha256_file,
    write_json,
    write_jsonl,
)
from veritool_rl.core.trajectory import TaskSpec
from veritool_rl.core.trajectory.schema import StrictModel
from veritool_rl.retail_ops.build.phrasing_bank import PhrasingRecord
from veritool_rl.retail_ops.domain.bundle import LoadedRetailOpsBundle, load_bundle
from veritool_rl.retail_ops.domain.ood_tasks import (
    OOD_CATEGORIES,
    OOD_DATASET_VERSION,
    OOD_GENERATOR_ID,
    OOD_TASKS_PER_CATEGORY,
    build_ood_tasks,
    ood_category,
)
from veritool_rl.retail_ops.domain.ood_v2_tasks import (
    OOD_V2_GENERATOR_ID,
    OOD_V2_SCENARIOS,
    OOD_V2_TASKS_PER_SCENARIO,
    build_ood_v2_tasks,
)


class OodTaskManifest(StrictModel):
    """分布外任务集的公开 manifest。

    与冻结数据集的 manifest 刻意不共用类型：那一份的 `dataset_version` 是
    `Literal["retail_ops_v1_r2_20260722"]`，配额硬编码为 40/10/20。把 OOD 塞进去
    需要放宽那些 Literal，而它们正是"数据集不可悄悄改动"的执行者。
    """

    schema_version: Literal["1.0"] = "1.0"
    #: **2026-08-17 修正**：这个字段此前被写死成 v1 的字面量，于是 OOD v2 的报告
    #: 也声称自己属于 `retail_ops_ood_v1_20260815`——两个不同数据集的读数
    #: （v1 的 0.8667 与 v2 的 1.0000）在同一张表里挂着同一个数据集版本号，
    #: 恰好违反项目自己的配对前提。外部审阅指出后改为两个版本并存的判别式。
    dataset_version: Literal["retail_ops_ood_v1_20260815", "retail_ops_ood_v2_20260817"] = (
        "retail_ops_ood_v1_20260815"
    )
    generator_id: str = Field(min_length=1)
    bundle_id: str = Field(min_length=1)
    bundle_version: str = Field(min_length=1)
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    split: Literal["ood"] = "ood"
    seed: int = Field(ge=0)
    task_count: int = Field(ge=1)
    category_counts: dict[str, int]
    kind_counts: dict[str, int]
    task_ids: list[str]
    task_sha256: dict[str, str]
    tasks_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _task_digest(task: TaskSpec) -> str:
    return hashlib.sha256(canonical_json(task.model_dump(mode="json")).encode("utf-8")).hexdigest()


def _validate(
    tasks: list[TaskSpec],
    bundle: LoadedRetailOpsBundle,
    expected_counts: dict[str, int] | None = None,
) -> None:
    """三类必须各 20 条，且任务只能用 bundle 里真实存在的工具。

    第二条是防"任务集自己发明了一个工具"——那会让整份评测测的是别的东西。
    唯一的例外是 `tool_bait` 一类：它在**用户请求文本**里提到不存在的工具，
    但 gold 调用序列仍然只用真实工具，正确行为就是不上钩。
    """
    counts = Counter(ood_category(task) for task in tasks)
    if expected_counts is None:
        if set(counts) != set(OOD_CATEGORIES) or set(counts.values()) != {OOD_TASKS_PER_CATEGORY}:
            raise ValueError(f"OOD 任务类别分布不符合契约: {dict(counts)}")
    elif dict(counts) != expected_counts:
        raise ValueError(f"OOD 任务类别分布不符合契约: {dict(counts)} != {expected_counts}")
    allowed = {tool.name for tool in bundle.tools}
    for task in tasks:
        unknown = {call.name for call in task.expected_calls} - allowed
        if unknown:
            raise ValueError(f"OOD 任务 {task.task_id} 的 gold 调用引用了不存在的工具 {unknown}")
        if task.split != "test":
            raise ValueError("OOD 任务必须使用 test split，与冻结三分集合区分开")


@dataclass(frozen=True, slots=True)
class OodPhrasingSpec:
    """v2 用哪一份措辞池的哪个分片。`bank_sha256` 是声明值，加载时比对。"""

    index: Mapping[str, Sequence[PhrasingRecord]]
    partition: str
    bank_sha256: str


def build_ood_task_set(
    bundle_dir: Path,
    seed: int,
    output_dir: Path,
    *,
    phrasing: OodPhrasingSpec | None = None,
) -> OodTaskManifest:
    """生成分布外任务集与其独立 manifest。

    任务与真值都写在同一份公开产物里——这个集合**不封存**，没有需要藏起来的答案。

    `phrasing` 为 `None` 时走 v1（作者手写模板库，三类各 20）；给出时走 **v2**
    （六个冻结场景 × 10，唯一自变量是 user 第一句话的说法，来自 LLM 措辞池的指定分片）。
    两者是不同的 `dataset_version` 与不同的 `generator_id`，产物互不覆盖。
    """
    bundle = load_bundle(bundle_dir)
    if phrasing is None:
        tasks = build_ood_tasks(seed)
        generator_id = OOD_GENERATOR_ID
    else:
        tasks = build_ood_v2_tasks(phrasing.index, seed)
        generator_id = OOD_V2_GENERATOR_ID
    _validate(
        tasks,
        bundle,
        None
        if phrasing is None
        else {scenario.value: OOD_V2_TASKS_PER_SCENARIO for scenario in OOD_V2_SCENARIOS},
    )

    create_output_dir(output_dir)
    tasks_path = output_dir / "tasks.jsonl"
    write_jsonl(tasks_path, (task.model_dump(mode="json") for task in tasks))
    manifest = OodTaskManifest(
        dataset_version=(
            "retail_ops_ood_v1_20260815" if phrasing is None else "retail_ops_ood_v2_20260817"
        ),
        generator_id=generator_id,
        bundle_id=bundle.bundle.bundle_id,
        bundle_version=bundle.bundle.bundle_version,
        bundle_sha256=bundle.bundle_sha256,
        seed=seed,
        task_count=len(tasks),
        category_counts=dict(sorted(Counter(ood_category(t) for t in tasks).items())),
        kind_counts=dict(sorted(Counter(str(t.metadata["ood_kind"]) for t in tasks).items())),
        task_ids=[task.task_id for task in tasks],
        task_sha256={task.task_id: _task_digest(task) for task in tasks},
        tasks_file_sha256=sha256_file(tasks_path),
    )
    write_json(output_dir / "manifest.json", manifest.model_dump(mode="json"))
    return manifest


def load_ood_manifest(path: Path) -> OodTaskManifest:
    return OodTaskManifest.model_validate_json(path.read_text(encoding="utf-8"))


def load_ood_tasks(build_dir: Path) -> list[TaskSpec]:
    """按 manifest 顺序读取任务，并逐项核对文件与任务摘要。"""
    manifest = load_ood_manifest(build_dir / "manifest.json")
    tasks_path = build_dir / "tasks.jsonl"
    if sha256_file(tasks_path) != manifest.tasks_file_sha256:
        raise ValueError("OOD tasks.jsonl 与 manifest SHA-256 不匹配")
    tasks = [
        TaskSpec.model_validate_json(line)
        for line in tasks_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if [task.task_id for task in tasks] != manifest.task_ids:
        raise ValueError("OOD 任务集合或顺序与 manifest 不一致")
    for task in tasks:
        if _task_digest(task) != manifest.task_sha256[task.task_id]:
            raise ValueError(f"OOD 任务内容与 manifest 摘要不一致: {task.task_id}")
    return tasks


OOD_DATASET_VERSION_LITERAL = OOD_DATASET_VERSION
