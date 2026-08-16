"""用户措辞池：把「表面形式 → 动作」的捷径打断。

## 为什么需要它

冻结数据集的 240 条 train 全部来自 `formal_tasks._user_request` 的 **12 句模板**，
而那 12 句**全部**是「请核实 / 请检查 / 请查询…」的书面祈使句。
2026-08-16 的分布外读数把后果测了出来（LOG-20260816-01 及其子类拆分）：

| expression 子类 | 零训练基座 | 合并候选 |
|---|---|---|
| `code_switch` | 1.0 | **0.0** |
| `colloquial` | 0.5 | **0.0** |

**训练把基座本来会做的两类打没了**，20 条失败全部是 `premature_final_response`。
模型学到的是「出现这种措辞就调用工具」，不是「什么时候该调用工具」。

## 这个模块提供什么

一个 LLM 生成、经双向校验、按哈希**确定性三分**的措辞池：

- `train_aug`：用于训练增强，替换 SFT 样本里 user 的第一条消息；
- `ood_dev`：用于迭代时的分布外读数；
- `ood_sealed`：**只观测一次**的分布外判定。

## 三分为什么必须由哈希决定

如果由人挑「哪些进训练、哪些进评测」，就没有任何东西能阻止把好改的留给评测。
`assign_partition` 只看 `sha256(措辞文本 + 固定盐)`，与生成顺序、场景、风格都无关，
且 `train_aug` 与两个评测分片**逐条互斥**由 `assert_partitions_are_disjoint` 断言。

## 这个池子**不**声称什么

它由**单一 provider、单一 prompt** 生成，因此度量的是「对同一个生成器产出的、
未见过的措辞的鲁棒性」，**不是「对任意真实用户输入的鲁棒性」**。
作者手写的 OOD v1（`domain/ood_tasks.py`）是一个**不同来源**的独立迁移检查，
本轮不得用于任何候选选择。这两条边界必须与任何读数一起出现。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator

from veritool_rl.core.trajectory import TaskScenario
from veritool_rl.core.trajectory.schema import StrictModel

#: 措辞池的版本标识。它进 manifest，也进训练导出与 OOD v2 任务集的 provenance。
PHRASING_BANK_VERSION = "retail_ops_phrasing_v1_20260816"

#: 三分的固定盐。**改这个字符串会重排全部分片**，等于换一个实验，
#: 因此它和 `dataset_version` 一样属于冻结量。
PARTITION_SALT = "retail-agent-ops/phrasing-partition/v1"

Partition = Literal["train_aug", "ood_dev", "ood_sealed"]

#: 分片权重：训练拿一半，两个评测分片各四分之一。
#: 用 4 个桶而不是 3 个，是为了让「训练 : 评测」是整数比而不是取模的余数偏斜。
_PARTITION_BUCKETS: tuple[Partition, ...] = ("train_aug", "train_aug", "ood_dev", "ood_sealed")

PARTITIONS: tuple[Partition, ...] = ("train_aug", "ood_dev", "ood_sealed")

#: 每条措辞必须带的占位符。少了它，任务生成时就填不进订单号。
ORDER_ID_PLACEHOLDER = "{order_id}"

#: **按「顾客意图」而不是「场景」组织。**
#:
#: 这是本模块最容易搞错、也最要紧的一点。回去核对 `formal_tasks._user_request` 会发现：
#: 四个退款场景（eligible / denied_window / denied_ownership / denied_duplicate）的
#: 请求模板**语义完全相同**——都是「核实订单 X 并处理 Y 退款」。区别**全部在订单状态里**
#: （退款期限、归属、是否已退），顾客的话里一个字都没提。
#:
#: 所以正确行为永远是「先 `get_order`，再按状态决定」，请求本身**从不透露答案**。
#:
#: 第一版按场景写简报（「顾客要退款，但自己也提到时间已经过去挺久了」）是**错的**：
#: 那等于把答案写进用户的话，测的就不再是同一个任务，还会让模型不查订单就能猜对。
#: dry-run 也当场暴露了症状——生成的措辞把「过期」和「不是本人」互相串到了对方的场景里。
INTENT_STATUS = "status_inquiry"
INTENT_REFUND = "refund_request"
INTENT_REFUND_RETRY = "refund_request_retry"

INTENT_BRIEFS: dict[str, str] = {
    INTENT_STATUS: "顾客想知道某个订单现在到哪一步了，只是问进度，没有要退款。",
    INTENT_REFUND: "顾客要为某个订单退款。他只说自己想退，并不知道也不评论这单到底能不能退。",
    INTENT_REFUND_RETRY: ("顾客要为某个订单退款，并且额外交代一句：如果系统临时出错，就再试一次。"),
}

#: 场景 → 意图。四个退款场景共用同一个意图，这正是冻结契约的形状。
SCENARIO_INTENTS: dict[TaskScenario, str] = {
    TaskScenario.LOOKUP_STATUS: INTENT_STATUS,
    TaskScenario.REFUND_ELIGIBLE: INTENT_REFUND,
    TaskScenario.REFUND_DENIED_WINDOW: INTENT_REFUND,
    TaskScenario.REFUND_DENIED_OWNERSHIP: INTENT_REFUND,
    TaskScenario.REFUND_DENIED_DUPLICATE: INTENT_REFUND,
    TaskScenario.REFUND_RECOVERY: INTENT_REFUND_RETRY,
}

#: 措辞里**绝不能**出现的状态泄漏。顾客一旦说出「已经过期了」「不是我的单」
#: 「之前退过」，Agent 不查订单也能猜对，任务就从「查证后判断」退化成「读理解」。
LEAKAGE_PATTERN = re.compile(
    "过期|超期|过了退款期|过了时效|早就过了|超过.{0,4}期限"
    "|不是我下的|不是我的单|不是本人|不是我买的|帮朋友|帮别人下的|替.{0,3}下的"
    "|已经退过|退过一次|重复退|退过款|之前退了|退款成功过"
)

#: 生成时要求覆盖的风格谱。**刻意不包含「书面祈使句」**——那正是冻结集合已有的那一种。
PHRASING_STYLES: tuple[str, ...] = (
    "colloquial",
    "terse",
    "typo",
    "code_switch",
    "greeting_noise",
    "impatient",
    "narrative",
    "polite_long",
)

#: 措辞长度的合理区间（字符）。太短的多半丢了语义，太长的多半在讲故事。
_MIN_CHARS = 4
_MAX_CHARS = 160

#: 措辞里绝不该出现的东西：工具名与内部字段名。措辞是顾客说的话，
#: 一旦出现 `get_order` 这种词，就等于把解法直接喂给模型。
_FORBIDDEN_TOKENS = ("get_order", "refund_order", "get_store_hours", "tool_call", "refund_status")


class PhrasingRecord(StrictModel):
    """措辞池里的一条。`phrasing_id` 是文本自身的哈希，因此重复文本不可能有两个 ID。"""

    phrasing_id: str = Field(min_length=64, max_length=64)
    intent: str = Field(min_length=1)
    style: str = Field(min_length=1)
    text: str = Field(min_length=1)
    partition: str = Field(min_length=1)

    @field_validator("intent")
    @classmethod
    def _known_intent(cls, value: str) -> str:
        if value not in INTENT_BRIEFS:
            raise ValueError(f"未知意图: {value}")
        return value

    @field_validator("partition")
    @classmethod
    def _known_partition(cls, value: str) -> str:
        if value not in PARTITIONS:
            raise ValueError(f"未知分片: {value}")
        return value


def phrasing_id(text: str) -> str:
    """措辞的稳定标识：文本自身的 SHA-256。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def assign_partition(text: str, *, salt: str = PARTITION_SALT) -> Partition:
    """按 `sha256(措辞 + 盐)` 确定性地分片。

    **不看场景、不看风格、不看生成顺序**——分片必须与「这条好不好改」完全无关，
    否则「泛化到没见过的措辞」这个claim 就被人工选择污染了。
    """
    digest = hashlib.sha256(f"{salt}\x00{text}".encode()).digest()
    return _PARTITION_BUCKETS[digest[0] % len(_PARTITION_BUCKETS)]


def normalize_phrasing(raw: str) -> str:
    """去掉首尾空白并把连续空白压成一个空格；不做任何内容改写。"""
    return re.sub(r"\s+", " ", raw).strip()


def validate_phrasing(text: str) -> str | None:
    """结构校验。返回拒绝原因；`None` 表示通过。

    这一层**不判断语义**——语义由生成脚本的回环分类负责。
    这里只挡住那些一眼就不能用的：缺占位符、长度离谱、把工具名写进了顾客的话。
    """
    if ORDER_ID_PLACEHOLDER not in text:
        return "缺少 {order_id} 占位符"
    if text.count(ORDER_ID_PLACEHOLDER) != 1:
        return "{order_id} 占位符出现多次"
    body = text.replace(ORDER_ID_PLACEHOLDER, "")
    if len(body) < _MIN_CHARS:
        return f"正文过短（{len(body)} < {_MIN_CHARS}）"
    if len(body) > _MAX_CHARS:
        return f"正文过长（{len(body)} > {_MAX_CHARS}）"
    lowered = text.lower()
    for token in _FORBIDDEN_TOKENS:
        if token in lowered:
            return f"出现内部标识 {token!r}"
    if "{" in body or "}" in body:
        return "含 {order_id} 之外的占位符"
    leak = LEAKAGE_PATTERN.search(body)
    if leak is not None:
        # 顾客说出订单状态 = 把答案写进请求。Agent 不查订单也能猜对，
        # 任务就从「查证后判断」退化成「读理解」，与冻结契约不是同一件事。
        return f"泄漏订单状态: {leak.group(0)!r}"
    return None


def build_records(
    accepted: Iterable[tuple[str, str, str]],
    *,
    salt: str = PARTITION_SALT,
) -> list[PhrasingRecord]:
    """把 (意图, 风格, 文本) 三元组转成分好片、去过重的记录，按 `phrasing_id` 排序。

    去重按**文本**：两个意图生成出同一句话时只保留第一次出现的那条，
    因为同一句话不可能既属于训练分片又属于评测分片。
    """
    seen: set[str] = set()
    records: list[PhrasingRecord] = []
    for intent, style, text in accepted:
        normalized = normalize_phrasing(text)
        if normalized in seen:
            continue
        seen.add(normalized)
        records.append(
            PhrasingRecord(
                phrasing_id=phrasing_id(normalized),
                intent=intent,
                style=style,
                text=normalized,
                partition=assign_partition(normalized, salt=salt),
            )
        )
    records.sort(key=lambda record: record.phrasing_id)
    return records


def partition_records(
    records: Sequence[PhrasingRecord], partition: Partition
) -> list[PhrasingRecord]:
    return [record for record in records if record.partition == partition]


def intent_index(
    records: Sequence[PhrasingRecord], partition: Partition
) -> dict[str, list[PhrasingRecord]]:
    """某个分片下 `意图 -> 措辞列表`，每个列表按 `phrasing_id` 排序（确定性）。"""
    index: dict[str, list[PhrasingRecord]] = {}
    for record in partition_records(records, partition):
        index.setdefault(record.intent, []).append(record)
    for bucket in index.values():
        bucket.sort(key=lambda record: record.phrasing_id)
    return index


def assert_partitions_are_disjoint(records: Sequence[PhrasingRecord]) -> None:
    """训练分片与两个评测分片**逐条互斥**。

    这是本轮方法学的核心断言：一旦训练见过评测里的某一句，
    「泛化到没见过的措辞」就不再成立，而那正是本轮要证明的东西。
    """
    buckets = {
        partition: {record.text for record in partition_records(records, partition)}
        for partition in PARTITIONS
    }
    train = buckets["train_aug"]
    for evaluation in ("ood_dev", "ood_sealed"):
        overlap = train & buckets[evaluation]
        if overlap:
            raise ValueError(f"train_aug 与 {evaluation} 有 {len(overlap)} 条重叠措辞")
    cross = buckets["ood_dev"] & buckets["ood_sealed"]
    if cross:
        raise ValueError(f"ood_dev 与 ood_sealed 有 {len(cross)} 条重叠措辞")


def assert_intent_coverage(records: Sequence[PhrasingRecord], *, minimum: int) -> None:
    """每个分片的每个意图都必须有足够多的措辞，否则任务集会被迫重复取样。"""
    for partition in PARTITIONS:
        index = intent_index(records, partition)
        for intent in INTENT_BRIEFS:
            available = len(index.get(intent, ()))
            if available < minimum:
                raise ValueError(
                    f"分片 {partition} 的意图 {intent} 只有 {available} 条措辞，"
                    f"少于要求的 {minimum} 条"
                )


def bank_sha256(records: Sequence[PhrasingRecord]) -> str:
    """整个池子的内容哈希：逐条 `phrasing_id|partition` 的规范串再哈希。

    包含 `partition` 是有意的——重排分片就是换一个实验，必须体现在哈希上。
    """
    payload = "\n".join(f"{record.phrasing_id}|{record.partition}" for record in records)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_phrasing_bank(path: Path, records: Sequence[PhrasingRecord]) -> str:
    """写 JSONL 并返回内容哈希。目录必须已存在；不覆盖已有文件。"""
    if path.exists():
        raise FileExistsError(f"措辞池已存在，不覆盖: {path}")
    lines = [
        json.dumps(record.model_dump(), ensure_ascii=False, sort_keys=True) for record in records
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return bank_sha256(records)


def load_phrasing_bank(path: Path) -> list[PhrasingRecord]:
    """读 JSONL，并在加载时重算分片——文件里的 `partition` 被篡改会当场失败。"""
    records: list[PhrasingRecord] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        payload: dict[str, Any] = json.loads(line)
        record = PhrasingRecord.model_validate(payload)
        if record.phrasing_id != phrasing_id(record.text):
            raise ValueError(f"{path}:{line_number} phrasing_id 与文本不匹配")
        if record.partition != assign_partition(record.text):
            raise ValueError(
                f"{path}:{line_number} partition 与 sha256 分片不一致——分片不是可以手改的东西"
            )
        records.append(record)
    records.sort(key=lambda record: record.phrasing_id)
    return records


@dataclass(frozen=True, slots=True)
class ParaphrasePlan:
    """一次训练增强的完整声明：用哪一份措辞池的哪个分片、每条任务改写几次。

    `bank_sha256` 是**声明的期望值**，不是读出来的实测值——沿用
    `sft_system_prompt_sha256` 立下的形状：配置声明期望，加载时比对，
    不一致就硬失败。这样「换了措辞池却忘了改配置」不会静默产出另一份训练集。

    `partition` 固定为 `train_aug` 不是默认值而是**契约**：用评测分片做训练增强，
    本轮关于泛化的全部结论当场作废。
    """

    index: Mapping[str, Sequence[PhrasingRecord]]
    per_task: int
    bank_sha256: str
    partition: Partition = "train_aug"

    def __post_init__(self) -> None:
        if self.partition != "train_aug":
            raise ValueError(
                f"训练增强只能用 train_aug 分片，收到 {self.partition!r}——"
                f"用评测分片做增强会让泛化结论失效"
            )
        if self.per_task < 1:
            raise ValueError(f"per_task 必须 >= 1，收到 {self.per_task}")


def load_paraphrase_plan(bank_path: Path, *, declared_sha256: str, per_task: int) -> ParaphrasePlan:
    """加载措辞池、校验声明哈希、取 `train_aug` 分片，返回一次增强的计划。"""
    records = load_phrasing_bank(bank_path)
    assert_partitions_are_disjoint(records)
    actual = bank_sha256(records)
    if actual != declared_sha256:
        raise ValueError(f"措辞池哈希与配置声明不一致: declared={declared_sha256}, actual={actual}")
    return ParaphrasePlan(
        index=intent_index(records, "train_aug"),
        per_task=per_task,
        bank_sha256=actual,
    )


def paraphrases_for_task(
    index: Mapping[str, Sequence[PhrasingRecord]],
    *,
    intent: str,
    task_key: str,
    count: int,
    order_id: str,
) -> list[str]:
    """为一条任务确定性地取 `count` 条互不相同的措辞，并填入订单号。

    取法是「按 `task_key` 的哈希决定起点，然后在排好序的池子里连续取」。
    这样做的两个理由：

    * **确定性**——同一份措辞池 + 同一批任务永远得到同一份训练集，
      否则「只改了数据」这个变量声称就不成立；
    * **铺开**——起点由任务哈希决定，因此不同任务不会都从池子开头取，
      避免前几条措辞被过量使用而尾部从未出现。

    `count` 超过池子大小时抛错，而不是静默重复——重复的改写等于把同一句抄 N 遍，
    那不是增强，是把一条样本的权重调高，两者的实验含义完全不同。
    """
    pool = index.get(intent, ())
    if count > len(pool):
        raise ValueError(f"意图 {intent} 只有 {len(pool)} 条措辞，取不出 {count} 条互不相同的改写")
    offset = int(hashlib.sha256(task_key.encode("utf-8")).hexdigest()[:8], 16)
    picked = [pool[(offset + step) % len(pool)] for step in range(count)]
    if len({record.phrasing_id for record in picked}) != count:
        raise ValueError(f"任务 {task_key} 取到了重复措辞")
    return [record.text.replace(ORDER_ID_PLACEHOLDER, order_id) for record in picked]
