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
from typing import Literal, cast, get_args

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
from veritool_rl.retail_ops.domain.ood_v4_tasks import (
    OOD_V4_DATASET_VERSION,
    OOD_V4_GENERATOR_ID,
    OOD_V4_SCENARIOS,
    OOD_V4_TASKS_PER_SCENARIO,
    build_ood_v4_tasks,
)
from veritool_rl.retail_ops.domain.policy_boundary_phrasing_tasks import (
    POLICY_BOUNDARY_PHRASING_DATASET_VERSION,
    POLICY_BOUNDARY_PHRASING_GENERATOR_ID,
    build_policy_boundary_phrasing_tasks,
)
from veritool_rl.retail_ops.domain.policy_boundary_tasks import (
    POLICY_BOUNDARY_DATASET_VERSION,
    POLICY_BOUNDARY_GENERATOR_ID,
    build_policy_boundary_tasks,
    expected_category_counts,
)

#: 允许出现在 OOD manifest 里的数据集版本号。
#:
#: 每一个都对应**一份具体素材**：v1 是作者手写的模板库，v2 是 `phrasing-bank-002`，
#: v2.2 是 `phrasing-bank-003`。素材与版本号是**双射**，由
#: `test_retail_ops_r7_rebuild.py::test_each_phrasing_bank_maps_to_exactly_one_dataset_version`
#: 在已提交的构建配置上断言。
OodDatasetVersion = Literal[
    "retail_ops_ood_v1_20260815",
    "retail_ops_ood_v2_20260817",
    "retail_ops_ood_v2_2_20260817",
    # 政策边界探针。它不是"又一份分布外素材"——它沿退款窗口这条轴扫描，
    # 用的是与冻结数据集同源的措辞，因此登记在这里只是为了共用 manifest 与评测路径，
    # 不代表它能回答泛化问题。见 domain/policy_boundary_tasks.py 的模块说明。
    "retail_ops_policy_boundary_v1_20260819",
    # v4 跨工具泛化（Phase B）：bank-v4 素材、12 场景、5 工具 bundle。
    "retail_ops_ood_v4_20260823",
    # 二维迭代面（Phase C3）：探针网格 × 措辞池分片。措辞不再与冻结数据集同源，
    # 使同一次迭代同时看见边界型与措辞型退化（R7 失败机制的根治）。
    "retail_ops_policy_boundary_phrasing_v1_20260904",
]

_ALLOWED_DATASET_VERSIONS: tuple[str, ...] = get_args(OodDatasetVersion)


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
    #:
    #: **2026-08-17 再补**：v2 内部同样需要判别式。两份措辞池构建出的任务集，
    #: `task_ids` 逐条相同（那个哈希只依赖位置），若再共用一个 `dataset_version`，
    #: 两批内容完全不同的评测集在 manifest 层就无法区分。
    dataset_version: OodDatasetVersion = "retail_ops_ood_v1_20260815"
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
    """v2 用哪一份措辞池的哪个分片。`bank_sha256` 是声明值，加载时比对。

    `dataset_version` 必须由调用方给出而不是取模块常量：一份素材一个版本号是
    **双射**，而模块常量会让第二份素材静默挂上第一份的版本号。取值受
    `OodTaskManifest.dataset_version` 的 `Literal` 约束，写错会在构造 manifest 时报错。
    """

    index: Mapping[str, Sequence[PhrasingRecord]]
    partition: str
    bank_sha256: str
    dataset_version: str


def build_ood_task_set(
    bundle_dir: Path,
    seed: int,
    output_dir: Path,
    *,
    phrasing: OodPhrasingSpec | None = None,
    boundary: bool = False,
) -> OodTaskManifest:
    """生成任务集与其独立 manifest。

    任务与真值都写在同一份公开产物里——这些集合**都不封存**，没有需要藏起来的答案。

    三种模式互斥：
    - `phrasing=None, boundary=False` → **OOD v1**（作者手写模板库，三类各 20）；
    - `phrasing` 给出 → **OOD v2**（六个冻结场景 × 10，唯一自变量是说法）；
    - `boundary=True` → **政策边界探针**（沿退款窗口这条轴扫描，15 个偏移量 × 8）。

    三者是不同的 `dataset_version` 与不同的 `generator_id`，产物互不覆盖。
    **探针不是分布外集合**：它与冻结数据集同源，只是把状态空间在一条轴上加密；
    共用这条构建/评测路径是为了复用 manifest 与报告，不代表它能回答泛化问题。
    """
    crossed = (
        phrasing is not None
        and boundary
        and phrasing.dataset_version == POLICY_BOUNDARY_PHRASING_DATASET_VERSION
    )
    if phrasing is not None and boundary and not crossed:
        raise ValueError("phrasing 与 boundary 互斥：一次只能构建一种任务集")
    bundle = load_bundle(bundle_dir)
    expected_counts: dict[str, int] | None
    if crossed:
        assert phrasing is not None  # crossed 的定义式已保证；为收窄类型
        tasks = build_policy_boundary_phrasing_tasks(
            seed, phrasing.index, partition=phrasing.partition
        )
        generator_id = POLICY_BOUNDARY_PHRASING_GENERATOR_ID
        dataset_version = POLICY_BOUNDARY_PHRASING_DATASET_VERSION
        expected_counts = expected_category_counts()
    elif boundary:
        tasks = build_policy_boundary_tasks(seed)
        generator_id = POLICY_BOUNDARY_GENERATOR_ID
        dataset_version = POLICY_BOUNDARY_DATASET_VERSION
        expected_counts = expected_category_counts()
    elif phrasing is None:
        tasks = build_ood_tasks(seed)
        generator_id = OOD_GENERATOR_ID
        dataset_version = OOD_DATASET_VERSION
        expected_counts = None
    else:
        if phrasing.dataset_version == POLICY_BOUNDARY_PHRASING_DATASET_VERSION:
            # scoped re-review Minor-1：交叉面版本号只在 boundary=true 的组合模式里
            # 合法；boundary=false 时挂它等于把 v2 内容登记成另一个数据集，
            # 破坏「素材↔版本号双射」。
            raise ValueError(
                "交叉面 dataset_version 只能与 boundary=true 组合使用；"
                "boundary=false 请用 v2/v4 的版本号"
            )
        if phrasing.dataset_version == OOD_V4_DATASET_VERSION:
            tasks = build_ood_v4_tasks(phrasing.index, seed)
            generator_id = OOD_V4_GENERATOR_ID
            dataset_version = phrasing.dataset_version
            expected_counts = {
                scenario.value: OOD_V4_TASKS_PER_SCENARIO for scenario in OOD_V4_SCENARIOS
            }
        else:
            tasks = build_ood_v2_tasks(phrasing.index, seed)
            generator_id = OOD_V2_GENERATOR_ID
            dataset_version = phrasing.dataset_version
            expected_counts = {
                scenario.value: OOD_V2_TASKS_PER_SCENARIO for scenario in OOD_V2_SCENARIOS
            }
        if dataset_version not in _ALLOWED_DATASET_VERSIONS:
            raise ValueError(
                f"未知的 OOD dataset_version: {dataset_version!r}——"
                f"新素材要先在 OodDatasetVersion 里登记，"
                f"随手写一个版本号就能造出'新数据集'的话，它就不是受控字段了"
            )
    _validate(tasks, bundle, expected_counts)

    create_output_dir(output_dir)
    tasks_path = output_dir / "tasks.jsonl"
    write_jsonl(tasks_path, (task.model_dump(mode="json") for task in tasks))
    manifest = OodTaskManifest(
        dataset_version=cast(OodDatasetVersion, dataset_version),
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
