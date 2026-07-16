"""BFCL V4 公开数据重划分、SFT target 与显式 loss mask。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import Field

from veritool_rl.artifacts import sha256_file
from veritool_rl.data.bfcl import (
    BFCL_CATEGORIES,
    BfclGroundTruth,
    BfclTask,
    load_bfcl_category,
    load_bfcl_manifest,
)
from veritool_rl.trajectory.schema import StrictModel

BFCL_SOURCE_COUNTS = {
    "simple_python": 400,
    "multiple": 200,
    "parallel": 200,
    "parallel_multiple": 200,
}
BFCL_SFT_DEV_QUOTAS = {
    "simple_python": 35,
    "multiple": 15,
    "parallel": 15,
    "parallel_multiple": 15,
}
BFCL_SFT_TRAIN_QUOTAS = {
    "simple_python": 315,
    "multiple": 135,
    "parallel": 135,
    "parallel_multiple": 135,
}
BFCL_HOLDOUT_QUOTAS = dict.fromkeys(BFCL_CATEGORIES, 50)
BFCL_SFT_SELECTION_ALGORITHM = (
    'exclude every task_id in the fixed holdout manifest; sort each category by '
    'sha256(f"bfcl-sft-dev:0:{task_id}".encode()) ascending; take dev quotas '
    "simple_python=35, multiple=15, parallel=15, parallel_multiple=15; assign "
    "the ordered remainder to train"
)


class ChatTemplateTokenizer(Protocol):
    """本模块使用的最小 tokenizer chat-template 接口。"""

    def apply_chat_template(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> Any:
        ...


class BfclSftSplitTask(StrictModel):
    """SFT split 中不含答案的一条任务引用。"""

    task_id: str = Field(min_length=1)
    category: str = Field(min_length=1)


class BfclSftSource(StrictModel):
    """一个 BFCL 类别的源文件哈希。"""

    category: str = Field(min_length=1)
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    possible_answer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BfclSftSplits(StrictModel):
    """冻结的 train/dev/holdout 任务引用。"""

    train: list[BfclSftSplitTask]
    dev: list[BfclSftSplitTask]
    holdout: list[BfclSftSplitTask]


class BfclSftManifest(StrictModel):
    """可提交且不含 BFCL 原文/答案的 SFT provenance。"""

    bfcl_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    holdout_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    selection_algorithm: str
    sources: list[BfclSftSource]
    splits: BfclSftSplits


class BfclTokenizedSftExample(StrictModel):
    """已显式遮蔽 prompt 的单条 BFCL SFT 样本。"""

    task_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    input_ids: list[int]
    attention_mask: list[int]
    labels: list[int]
    prompt_token_count: int = Field(ge=1)
    target_token_count: int = Field(ge=1)
    full_token_count: int = Field(ge=1)
    target_text: str


def sft_dev_selection_sha256(task_id: str) -> str:
    """计算 seed-0 BFCL SFT dev 排序哈希。"""
    return hashlib.sha256(f"bfcl-sft-dev:0:{task_id}".encode()).hexdigest()


def build_bfcl_sft_manifest(
    data_root: Path,
    holdout_manifest_path: Path,
) -> BfclSftManifest:
    """从固定 1000 条源任务和固定 holdout 构造 720/80/200 provenance。"""
    holdout = load_bfcl_manifest(holdout_manifest_path, data_root)
    if holdout.seed != 0 or holdout.quotas != BFCL_HOLDOUT_QUOTAS:
        msg = "BFCL SFT 必须使用 seed 0 且四类各 50 条的固定 holdout"
        raise ValueError(msg)
    holdout_by_category = {
        category: {
            item.task_id for item in holdout.tasks if item.category == category
        }
        for category in BFCL_CATEGORIES
    }

    train: list[BfclSftSplitTask] = []
    dev: list[BfclSftSplitTask] = []
    sources: list[BfclSftSource] = []
    for category in BFCL_CATEGORIES:
        tasks, _ = load_bfcl_category(data_root, category)
        if len(tasks) != BFCL_SOURCE_COUNTS[category]:
            msg = (
                f"{category} 源任务数必须为 {BFCL_SOURCE_COUNTS[category]}，"
                f"实际 {len(tasks)}"
            )
            raise ValueError(msg)
        holdout_ids = holdout_by_category[category]
        if len(holdout_ids) != BFCL_HOLDOUT_QUOTAS[category]:
            msg = f"{category} holdout 配额不为 50"
            raise ValueError(msg)
        candidates = sorted(
            (task for task in tasks if task.id not in holdout_ids),
            key=lambda task: sft_dev_selection_sha256(task.id),
        )
        dev_count = BFCL_SFT_DEV_QUOTAS[category]
        dev.extend(
            BfclSftSplitTask(task_id=task.id, category=category)
            for task in candidates[:dev_count]
        )
        train.extend(
            BfclSftSplitTask(task_id=task.id, category=category)
            for task in candidates[dev_count:]
        )
        prompt_path = data_root / f"BFCL_v4_{category}.json"
        answer_path = data_root / "possible_answer" / f"BFCL_v4_{category}.json"
        sources.append(
            BfclSftSource(
                category=category,
                prompt_sha256=sha256_file(prompt_path),
                possible_answer_sha256=sha256_file(answer_path),
            )
        )

    holdout_tasks = [
        BfclSftSplitTask(task_id=item.task_id, category=item.category)
        for item in holdout.tasks
    ]
    _validate_sft_splits(train, dev, holdout_tasks)
    return BfclSftManifest(
        bfcl_commit=holdout.bfcl_commit,
        holdout_manifest_sha256=sha256_file(holdout_manifest_path),
        selection_algorithm=BFCL_SFT_SELECTION_ALGORITHM,
        sources=sources,
        splits=BfclSftSplits(train=train, dev=dev, holdout=holdout_tasks),
    )


def ground_truth_to_tool_calls(
    task: BfclTask,
    ground_truth: BfclGroundTruth,
) -> list[dict[str, Any]]:
    """把 possible answer 确定性转换为 Qwen tool_calls。"""
    if task.id != ground_truth.id:
        msg = f"任务与 ground truth ID 不一致: {task.id} != {ground_truth.id}"
        raise ValueError(msg)
    tool_calls: list[dict[str, Any]] = []
    for expected_call in ground_truth.ground_truth:
        if len(expected_call) != 1:
            msg = f"{task.id} ground truth 调用必须恰好包含一个函数"
            raise ValueError(msg)
        function_name, possible_arguments = next(iter(expected_call.items()))
        function = next(
            (item for item in task.function if item.name == function_name),
            None,
        )
        if function is None:
            msg = f"{task.id} ground truth 函数不在 schema 中: {function_name}"
            raise ValueError(msg)
        properties = function.parameters.get("properties", {})
        required = set(function.parameters.get("required", []))
        if not isinstance(properties, dict):
            msg = f"{task.id}/{function_name} parameters.properties 必须是 mapping"
            raise ValueError(msg)
        arguments: dict[str, Any] = {}
        for name, possible_values in possible_arguments.items():
            if name not in required and "" in possible_values:
                continue
            schema = properties.get(name, {})
            arguments[name] = _choose_possible_value(possible_values, schema)
        tool_calls.append(
            {
                "type": "function",
                "function": {"name": function_name, "arguments": arguments},
            }
        )
    return tool_calls


def resolve_bfcl_sft_task_answers(
    manifest: BfclSftManifest,
    data_root: Path,
    split: Literal["train", "dev"],
) -> list[tuple[BfclTask, BfclGroundTruth]]:
    """按冻结 manifest 顺序解析 train 或 dev，拒绝任何缺失/额外 ID。"""
    references = getattr(manifest.splits, split)
    tasks_by_id: dict[str, BfclTask] = {}
    answers_by_id: dict[str, BfclGroundTruth] = {}
    for category in BFCL_CATEGORIES:
        category_ids = {
            item.task_id for item in references if item.category == category
        }
        if not category_ids:
            continue
        tasks, answers = load_bfcl_category(data_root, category)
        tasks_by_id.update(
            (task.id, task) for task in tasks if task.id in category_ids
        )
        answers_by_id.update(
            (answer.id, answer) for answer in answers if answer.id in category_ids
        )
    expected_ids = [item.task_id for item in references]
    if set(tasks_by_id) != set(expected_ids) or set(answers_by_id) != set(expected_ids):
        msg = f"BFCL SFT {split} 的 task/answer ID 与 provenance 不一致"
        raise ValueError(msg)
    return [(tasks_by_id[task_id], answers_by_id[task_id]) for task_id in expected_ids]


def render_qwen_tool_call_target(tool_calls: list[dict[str, Any]]) -> str:
    """按固定 Qwen newline contract 渲染 assistant target。"""
    blocks = []
    for tool_call in tool_calls:
        function = tool_call["function"]
        payload = {
            "name": function["name"],
            "arguments": function["arguments"],
        }
        blocks.append(
            "<tool_call>\n"
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            + "\n</tool_call>"
        )
    return "\n".join(blocks)


def tokenize_bfcl_sft_example(
    task: BfclTask,
    ground_truth: BfclGroundTruth,
    tokenizer: ChatTemplateTokenizer,
    *,
    max_seq_len: int,
) -> BfclTokenizedSftExample:
    """使用真实 Qwen template 构造不允许 target 截断的显式 labels。"""
    if max_seq_len < 1:
        msg = "max_seq_len 必须为正整数"
        raise ValueError(msg)
    tool_calls = ground_truth_to_tool_calls(task, ground_truth)
    messages = [message.model_dump(mode="json") for message in task.question[0]]
    tools = [function.model_dump(mode="json") for function in task.function]
    full_messages = [
        *messages,
        {"role": "assistant", "content": "", "tool_calls": tool_calls},
    ]
    prompt = tokenizer.apply_chat_template(
        messages,
        tools=tools,
        add_generation_prompt=True,
        enable_thinking=False,
        tokenize=True,
        return_dict=True,
    )
    full = tokenizer.apply_chat_template(
        full_messages,
        tools=tools,
        add_generation_prompt=False,
        enable_thinking=False,
        tokenize=True,
        return_dict=True,
    )
    prompt_ids = _token_ids(prompt, task.id)
    full_ids = _token_ids(full, task.id)
    if full_ids[: len(prompt_ids)] != prompt_ids:
        msg = f"{task.id} Qwen prompt token 不是完整序列的严格前缀"
        raise ValueError(msg)
    if len(full_ids) > max_seq_len:
        msg = (
            f"{task.id} full token 长度 {len(full_ids)} 超过 max_seq_len "
            f"{max_seq_len}，禁止截断 assistant target"
        )
        raise ValueError(msg)
    target_count = len(full_ids) - len(prompt_ids)
    if target_count < 1:
        msg = f"{task.id} assistant target token 不能为空"
        raise ValueError(msg)
    attention_mask = _attention_mask(full, len(full_ids), task.id)
    return BfclTokenizedSftExample(
        task_id=task.id,
        category=task.id.rsplit("_", 1)[0],
        input_ids=full_ids,
        attention_mask=attention_mask,
        labels=[-100] * len(prompt_ids) + full_ids[len(prompt_ids) :],
        prompt_token_count=len(prompt_ids),
        target_token_count=target_count,
        full_token_count=len(full_ids),
        target_text=render_qwen_tool_call_target(tool_calls),
    )


def _choose_possible_value(possible_values: list[Any], schema: Any) -> Any:
    if not possible_values:
        raise ValueError("possible answer 候选不能为空")
    selected = next((value for value in possible_values if value != ""), "")
    if not isinstance(schema, dict):
        return selected
    value_type = schema.get("type")
    if value_type == "dict" and isinstance(selected, dict):
        return _choose_dict_value(selected, schema)
    items = schema.get("items", {})
    if (
        value_type == "array"
        and isinstance(selected, list)
        and isinstance(items, dict)
        and items.get("type") == "dict"
    ):
        return [
            _choose_dict_value(item, items) if isinstance(item, dict) else item
            for item in selected
        ]
    return selected


def _choose_dict_value(
    possible_value: dict[str, Any],
    schema: dict[str, Any],
) -> dict[str, Any]:
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        properties = {}
    selected: dict[str, Any] = {}
    for name, possible_values in possible_value.items():
        if not isinstance(possible_values, list) or not possible_values:
            msg = f"nested possible answer {name} 候选必须是非空列表"
            raise ValueError(msg)
        if "" in possible_values:
            continue
        selected[name] = _choose_possible_value(
            possible_values,
            properties.get(name, {}),
        )
    return selected


def _token_ids(encoded: Any, task_id: str) -> list[int]:
    try:
        value = encoded["input_ids"]
    except (KeyError, TypeError) as error:
        msg = f"{task_id} tokenizer 未返回 input_ids"
        raise ValueError(msg) from error
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, int) for item in value)
    ):
        msg = f"{task_id} tokenizer input_ids 必须是非空整数列表"
        raise ValueError(msg)
    return value


def _attention_mask(encoded: Any, length: int, task_id: str) -> list[int]:
    try:
        value = encoded["attention_mask"]
    except (KeyError, TypeError):
        return [1] * length
    if (
        not isinstance(value, list)
        or len(value) != length
        or not all(item in (0, 1) for item in value)
    ):
        msg = f"{task_id} tokenizer attention_mask 无效"
        raise ValueError(msg)
    return value


def _validate_sft_splits(
    train: list[BfclSftSplitTask],
    dev: list[BfclSftSplitTask],
    holdout: list[BfclSftSplitTask],
) -> None:
    expected_counts = (720, 80, 200)
    if (len(train), len(dev), len(holdout)) != expected_counts:
        msg = f"BFCL SFT split 数量必须为 {expected_counts}"
        raise ValueError(msg)
    id_sets = [
        {item.task_id for item in split}
        for split in (train, dev, holdout)
    ]
    if any(
        len(ids) != len(split)
        for ids, split in zip(id_sets, (train, dev, holdout), strict=True)
    ):
        msg = "BFCL SFT split 内存在重复 task_id"
        raise ValueError(msg)
    if id_sets[0] & id_sets[1] or id_sets[0] & id_sets[2] or id_sets[1] & id_sets[2]:
        msg = "BFCL SFT train/dev/holdout 存在 task_id 泄漏"
        raise ValueError(msg)
    train_counts = {
        category: sum(item.category == category for item in train)
        for category in BFCL_CATEGORIES
    }
    dev_counts = {
        category: sum(item.category == category for item in dev)
        for category in BFCL_CATEGORIES
    }
    if train_counts != BFCL_SFT_TRAIN_QUOTAS or dev_counts != BFCL_SFT_DEV_QUOTAS:
        msg = "BFCL SFT train/dev 分类配额不一致"
        raise ValueError(msg)
