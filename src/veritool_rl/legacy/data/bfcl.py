"""BFCL V4 单轮数据加载、固定抽样与 provenance manifest。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import Field, ValidationError, field_validator

from veritool_rl.core.artifacts import canonical_json, sha256_file
from veritool_rl.core.trajectory.schema import StrictModel, validate_json_value

BFCL_CATEGORIES = (
    "simple_python",
    "multiple",
    "parallel",
    "parallel_multiple",
)
SELECTION_ALGORITHM = (
    'sort each category by sha256(f"{seed}:{task_id}".encode()) ascending; '
    "take the configured quota"
)


class BfclMessage(StrictModel):
    """BFCL question 中的一条消息。"""

    role: Literal["system", "user", "assistant"]
    content: str


class BfclFunction(StrictModel):
    """BFCL 原始 function 描述。"""

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    parameters: dict[str, Any]

    _validate_parameters = field_validator("parameters")(validate_json_value)


class BfclTask(StrictModel):
    """本阶段接受的 BFCL V4 单轮任务。"""

    id: str = Field(min_length=1)
    question: list[list[BfclMessage]]
    function: list[BfclFunction]

    @field_validator("question")
    @classmethod
    def validate_single_turn(cls, value: list[list[BfclMessage]]) -> list[list[BfclMessage]]:
        """固定子集只能包含一个非空 turn。"""
        if len(value) != 1 or not value[0]:
            msg = "BFCL 固定子集任务必须恰好包含一个非空 turn"
            raise ValueError(msg)
        return value


class BfclGroundTruth(StrictModel):
    """官方 possible-answer 中的一条 ground truth。"""

    id: str = Field(min_length=1)
    ground_truth: list[dict[str, dict[str, list[Any]]]] = Field(min_length=1)

    _validate_ground_truth = field_validator("ground_truth")(validate_json_value)


class BfclManifestTask(StrictModel):
    """manifest 中的一条冻结任务引用。"""

    category: str
    task_id: str
    selection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BfclManifestSource(StrictModel):
    """一个类别的源文件 provenance。"""

    category: str
    prompt_path: str
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    possible_answer_path: str
    possible_answer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_count: int = Field(ge=1)
    selected_count: int = Field(ge=1)
    selected_ids_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BfclManifest(StrictModel):
    """BFCL V4 固定单轮子集的完整 provenance。"""

    schema_version: Literal["1.0"] = "1.0"
    benchmark: Literal["BFCL V4"] = "BFCL V4"
    bfcl_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    seed: int
    selection_algorithm: str
    quotas: dict[str, int]
    sources: list[BfclManifestSource]
    tasks: list[BfclManifestTask]


ModelT = TypeVar("ModelT", bound=StrictModel)


def selection_sha256(seed: int, task_id: str) -> str:
    """计算任务在固定抽样中的排序哈希。"""
    return hashlib.sha256(f"{seed}:{task_id}".encode()).hexdigest()


def load_bfcl_category(
    data_root: Path,
    category: str,
) -> tuple[list[BfclTask], list[BfclGroundTruth]]:
    """加载并校验一个 BFCL 类别及其 possible answer。"""
    if category not in BFCL_CATEGORIES:
        msg = f"不支持的 BFCL 类别: {category}"
        raise ValueError(msg)
    prompt_path = data_root / f"BFCL_v4_{category}.json"
    answer_path = data_root / "possible_answer" / f"BFCL_v4_{category}.json"
    tasks = _load_jsonl(prompt_path, BfclTask)
    answers = _load_jsonl(answer_path, BfclGroundTruth)
    _ensure_unique_ids([task.id for task in tasks])
    _ensure_unique_ids([answer.id for answer in answers])
    task_ids = {task.id for task in tasks}
    answer_ids = {answer.id for answer in answers}
    if task_ids != answer_ids:
        msg = f"{category} 任务与 possible answer 的 ID 集合不一致"
        raise ValueError(msg)
    expected_prefix = f"{category}_"
    if any(not task_id.startswith(expected_prefix) for task_id in task_ids):
        msg = f"{category} 包含类别前缀错误的 task_id"
        raise ValueError(msg)
    return tasks, answers


def select_bfcl_tasks(
    tasks_by_category: dict[str, list[BfclTask]],
    seed: int,
    quotas: dict[str, int],
) -> dict[str, list[BfclTask]]:
    """按固定 SHA-256 排序为每个类别选择指定配额。"""
    selected: dict[str, list[BfclTask]] = {}
    for category, quota in quotas.items():
        if quota < 1:
            msg = f"{category} quota 必须大于 0"
            raise ValueError(msg)
        tasks = tasks_by_category.get(category, [])
        if len(tasks) < quota:
            msg = f"{category} 至少需要 {quota} 条任务，实际 {len(tasks)} 条"
            raise ValueError(msg)
        selected[category] = sorted(
            tasks,
            key=lambda task: selection_sha256(seed, task.id),
        )[:quota]
    return selected


def build_bfcl_manifest(
    data_root: Path,
    bfcl_commit: str,
    seed: int,
    quotas: dict[str, int],
) -> BfclManifest:
    """从固定 BFCL 数据构造可提交的 task-only manifest。"""
    unknown_categories = sorted(set(quotas) - set(BFCL_CATEGORIES))
    if unknown_categories:
        msg = f"不支持的 BFCL 类别: {unknown_categories}"
        raise ValueError(msg)
    ordered_quotas = {
        category: quotas[category] for category in BFCL_CATEGORIES if category in quotas
    }
    tasks_by_category: dict[str, list[BfclTask]] = {}
    for category in ordered_quotas:
        tasks_by_category[category] = load_bfcl_category(data_root, category)[0]
    selected = select_bfcl_tasks(tasks_by_category, seed, ordered_quotas)
    sources: list[BfclManifestSource] = []
    manifest_tasks: list[BfclManifestTask] = []
    for category, tasks in selected.items():
        prompt_name = f"BFCL_v4_{category}.json"
        answer_name = f"possible_answer/BFCL_v4_{category}.json"
        selected_ids = [task.id for task in tasks]
        sources.append(
            BfclManifestSource(
                category=category,
                prompt_path=prompt_name,
                prompt_sha256=sha256_file(data_root / prompt_name),
                possible_answer_path=answer_name,
                possible_answer_sha256=sha256_file(data_root / answer_name),
                source_count=len(tasks_by_category[category]),
                selected_count=len(tasks),
                selected_ids_sha256=hashlib.sha256(
                    canonical_json(selected_ids).encode()
                ).hexdigest(),
            )
        )
        manifest_tasks.extend(
            BfclManifestTask(
                category=category,
                task_id=task.id,
                selection_sha256=selection_sha256(seed, task.id),
            )
            for task in tasks
        )
    _ensure_unique_ids([task.task_id for task in manifest_tasks])
    return BfclManifest(
        bfcl_commit=bfcl_commit,
        seed=seed,
        selection_algorithm=SELECTION_ALGORITHM,
        quotas=ordered_quotas,
        sources=sources,
        tasks=manifest_tasks,
    )


def load_bfcl_manifest(manifest_path: Path, data_root: Path) -> BfclManifest:
    """加载 manifest，并从固定源数据完整重算 provenance。"""
    try:
        manifest = BfclManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        rebuilt = build_bfcl_manifest(
            data_root=data_root,
            bfcl_commit=manifest.bfcl_commit,
            seed=manifest.seed,
            quotas=manifest.quotas,
        )
    except (FileNotFoundError, ValidationError, ValueError) as error:
        msg = f"BFCL manifest provenance 校验失败: {error}"
        raise ValueError(msg) from error
    if manifest != rebuilt:
        msg = "BFCL manifest provenance 与固定源数据重算结果不一致"
        raise ValueError(msg)
    return manifest


def _load_jsonl(path: Path, model: type[ModelT]) -> list[ModelT]:
    if not path.is_file():
        raise FileNotFoundError(path)
    rows: list[ModelT] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            msg = f"无效 JSONL: {path}:{line_number} 不能为空白"
            raise ValueError(msg)
        try:
            payload = json.loads(line)
            rows.append(model.model_validate(payload))
        except (json.JSONDecodeError, ValidationError) as error:
            msg = f"无效 JSONL: {path}:{line_number}: {error}"
            raise ValueError(msg) from error
    if not rows:
        msg = f"无效 JSONL: {path} 不能为空"
        raise ValueError(msg)
    return rows


def _ensure_unique_ids(ids: list[str]) -> None:
    if len(ids) != len(set(ids)):
        msg = "BFCL 数据包含重复 task_id"
        raise ValueError(msg)
