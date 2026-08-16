"""措辞池的契约测试。

本轮（R6）的全部结论都建立在两条性质上，它们必须由测试挡着：

1. **分片由哈希决定，与「这条好不好改」无关**——否则「泛化到没见过的措辞」
   就被人工选择污染了；
2. **措辞不得透露订单状态**——顾客一旦说出「已经过期了」「不是我的单」，
   Agent 不查订单也能猜对，任务就从「查证后判断」退化成「读理解」，
   与冻结契约不再是同一件事。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from veritool_rl.retail_ops.build.phrasing_bank import (
    INTENT_BRIEFS,
    INTENT_REFUND,
    INTENT_STATUS,
    PARTITION_SALT,
    PARTITIONS,
    PhrasingRecord,
    assert_intent_coverage,
    assert_partitions_are_disjoint,
    assign_partition,
    bank_sha256,
    build_records,
    intent_index,
    load_phrasing_bank,
    normalize_phrasing,
    paraphrases_for_task,
    partition_records,
    phrasing_id,
    validate_phrasing,
    write_phrasing_bank,
)


def _text(index: int) -> str:
    return f"帮我看看 {{order_id}} 这单，第 {index} 次问了"


# --- 分片 ---------------------------------------------------------------------


def test_partition_is_deterministic() -> None:
    text = "退 {order_id} 这单谢谢"
    assert assign_partition(text) == assign_partition(text)


def test_partition_ignores_intent_style_and_order() -> None:
    """同一句话在任何上下文里都必须落到同一个分片。"""
    text = "{order_id} 退款"
    first = build_records([(INTENT_REFUND, "terse", text)])
    second = build_records([(INTENT_STATUS, "colloquial", text)])
    assert first[0].partition == second[0].partition == assign_partition(text)


def test_partition_changes_with_the_salt() -> None:
    """盐是冻结量：换盐等于换一个实验，必须能看出来。"""
    texts = [_text(index) for index in range(200)]
    default = [assign_partition(text) for text in texts]
    other = [assign_partition(text, salt="another-salt") for text in texts]
    assert default != other


def test_partition_split_is_roughly_two_one_one() -> None:
    """训练拿一半、两个评测分片各四分之一。偏斜过大意味着桶设计出了问题。"""
    records = build_records([(INTENT_REFUND, "colloquial", _text(index)) for index in range(1200)])
    counts = {partition: len(partition_records(records, partition)) for partition in PARTITIONS}
    assert sum(counts.values()) == 1200
    assert 0.45 < counts["train_aug"] / 1200 < 0.55
    for evaluation in ("ood_dev", "ood_sealed"):
        assert 0.20 < counts[evaluation] / 1200 < 0.30


def test_partitions_are_disjoint_on_a_real_bank() -> None:
    records = build_records([(INTENT_REFUND, "colloquial", _text(index)) for index in range(300)])
    assert_partitions_are_disjoint(records)


def test_disjointness_assertion_actually_catches_an_overlap() -> None:
    """把同一句话手工塞进两个分片，断言必须失败——否则这条守则形同虚设。"""
    text = _text(1)
    shared = PhrasingRecord(
        phrasing_id=phrasing_id(text),
        intent=INTENT_REFUND,
        style="s",
        text=text,
        partition="train_aug",
    )
    leaked = shared.model_copy(update={"partition": "ood_sealed"})
    with pytest.raises(ValueError, match="重叠措辞"):
        assert_partitions_are_disjoint([shared, leaked])


# --- 结构与泄漏校验 -----------------------------------------------------------


def test_a_good_phrasing_passes() -> None:
    assert validate_phrasing("帮我退一下 {order_id} 这个单，谢谢") is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("帮我退一下这个单", "缺少"),
        ("{order_id} 和 {order_id} 都退", "多次"),
        ("{order_id}", "过短"),
        ("{order_id} " + "非常" * 90, "过长"),
        ("对 {order_id} 调用 get_order", "内部标识"),
        ("{order_id} 退款，理由 {reason}", "占位符"),
    ],
)
def test_structural_rejections(text: str, expected: str) -> None:
    reason = validate_phrasing(text)
    assert reason is not None and expected in reason


@pytest.mark.parametrize(
    "text",
    [
        "{order_id} 这单已经过期了吧，还能退吗",
        "{order_id} 不是我下的单，帮朋友问的",
        "{order_id} 我之前退过一次了",
        "{order_id} 超过退款期限了我也想退",
    ],
)
def test_state_leakage_is_rejected(text: str) -> None:
    """顾客说破订单状态 = 把答案写进请求。这是本轮最要紧的一条过滤。"""
    reason = validate_phrasing(text)
    assert reason is not None and "泄漏订单状态" in reason


def test_normalization_collapses_whitespace_without_rewriting() -> None:
    assert normalize_phrasing("  退  {order_id}\n 谢谢 ") == "退 {order_id} 谢谢"


# --- 记录与持久化 -------------------------------------------------------------


def test_duplicate_texts_are_dropped() -> None:
    text = _text(7)
    records = build_records([(INTENT_REFUND, "a", text), (INTENT_STATUS, "b", text)])
    assert len(records) == 1


def test_records_are_sorted_by_id_for_determinism() -> None:
    records = build_records([(INTENT_REFUND, "s", _text(index)) for index in range(50)])
    assert [record.phrasing_id for record in records] == sorted(
        record.phrasing_id for record in records
    )


def test_bank_hash_changes_when_a_partition_moves() -> None:
    """分片进内容哈希：重排分片就是换一个实验，不能悄悄发生。"""
    records = build_records([(INTENT_REFUND, "s", _text(index)) for index in range(20)])
    moved = list(records)
    moved[0] = moved[0].model_copy(
        update={"partition": "ood_dev" if moved[0].partition != "ood_dev" else "ood_sealed"}
    )
    assert bank_sha256(records) != bank_sha256(moved)


def test_roundtrip_write_and_load(tmp_path: Path) -> None:
    records = build_records([(INTENT_REFUND, "s", _text(index)) for index in range(40)])
    path = tmp_path / "phrasings.jsonl"
    digest = write_phrasing_bank(path, records)
    loaded = load_phrasing_bank(path)
    assert digest == bank_sha256(loaded)
    assert [record.model_dump() for record in loaded] == [record.model_dump() for record in records]


def test_write_refuses_to_overwrite(tmp_path: Path) -> None:
    records = build_records([(INTENT_REFUND, "s", _text(1))])
    path = tmp_path / "phrasings.jsonl"
    write_phrasing_bank(path, records)
    with pytest.raises(FileExistsError):
        write_phrasing_bank(path, records)


def test_load_rejects_a_hand_edited_partition(tmp_path: Path) -> None:
    """分片不是可以手改的东西——加载时重算，对不上就失败。"""
    records = build_records([(INTENT_REFUND, "s", _text(index)) for index in range(10)])
    path = tmp_path / "phrasings.jsonl"
    write_phrasing_bank(path, records)

    lines = path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[0])
    payload["partition"] = "ood_sealed" if payload["partition"] != "ood_sealed" else "train_aug"
    lines[0] = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="partition 与 sha256 分片不一致"):
        load_phrasing_bank(path)


def test_load_rejects_a_hand_edited_text(tmp_path: Path) -> None:
    records = build_records([(INTENT_REFUND, "s", _text(index)) for index in range(10)])
    path = tmp_path / "phrasings.jsonl"
    write_phrasing_bank(path, records)

    lines = path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[0])
    payload["text"] = payload["text"] + "（偷偷改一下）"
    lines[0] = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="phrasing_id 与文本不匹配"):
        load_phrasing_bank(path)


# --- 覆盖度 -------------------------------------------------------------------


def test_intent_coverage_passes_when_every_bucket_is_full() -> None:
    accepted = [
        (intent, "s", f"{intent} 的第 {index} 句 {{order_id}}")
        for intent in INTENT_BRIEFS
        for index in range(200)
    ]
    records = build_records(accepted)
    assert_intent_coverage(records, minimum=12)


def test_intent_coverage_fails_when_one_bucket_is_thin() -> None:
    accepted = [(intent, "s", f"{intent} 唯一一句 {{order_id}}") for intent in INTENT_BRIEFS]
    records = build_records(accepted)
    with pytest.raises(ValueError, match="少于要求的"):
        assert_intent_coverage(records, minimum=12)


def test_intent_index_is_sorted_and_partition_scoped() -> None:
    records = build_records(
        [(INTENT_REFUND, "s", _text(index)) for index in range(120)]
        + [(INTENT_STATUS, "s", f"查一下 {{order_id}} 第 {index} 次") for index in range(120)]
    )
    index = intent_index(records, "ood_sealed")
    assert set(index) <= {INTENT_REFUND, INTENT_STATUS}
    for bucket in index.values():
        assert [record.phrasing_id for record in bucket] == sorted(
            record.phrasing_id for record in bucket
        )
        assert all(record.partition == "ood_sealed" for record in bucket)


def test_the_salt_is_frozen() -> None:
    """盐一旦改动，此前全部分片与读数都作废。它和 dataset_version 同级。"""
    assert PARTITION_SALT == "retail-agent-ops/phrasing-partition/v1"


# --- 任务级取样 ---------------------------------------------------------------


def _bank(count: int) -> dict[str, list[PhrasingRecord]]:
    records = build_records(
        [(INTENT_REFUND, "s", f"第 {index} 种说法 {{order_id}} 谢谢") for index in range(count)]
    )
    return {INTENT_REFUND: records}


def test_paraphrases_are_deterministic_and_fill_the_order_id() -> None:
    index = _bank(40)
    first = paraphrases_for_task(
        index, intent=INTENT_REFUND, task_key="task-1", count=3, order_id="O-ABC"
    )
    second = paraphrases_for_task(
        index, intent=INTENT_REFUND, task_key="task-1", count=3, order_id="O-ABC"
    )
    assert first == second
    assert all("O-ABC" in text and "{order_id}" not in text for text in first)


def test_paraphrases_within_a_task_are_distinct() -> None:
    index = _bank(40)
    picked = paraphrases_for_task(
        index, intent=INTENT_REFUND, task_key="task-2", count=5, order_id="O-X"
    )
    assert len(set(picked)) == 5


def test_different_tasks_start_at_different_offsets() -> None:
    """所有任务都从池子开头取的话，尾部的措辞永远不会进训练集。"""
    index = _bank(60)
    starts = {
        paraphrases_for_task(
            index, intent=INTENT_REFUND, task_key=f"task-{n}", count=1, order_id="O"
        )[0]
        for n in range(30)
    }
    assert len(starts) > 10


def test_asking_for_more_than_the_pool_is_an_error_not_a_silent_repeat() -> None:
    """重复的改写不是增强，是给一条样本加权——含义完全不同，必须硬失败。"""
    index = _bank(3)
    with pytest.raises(ValueError, match="取不出"):
        paraphrases_for_task(index, intent=INTENT_REFUND, task_key="t", count=5, order_id="O")


def test_the_real_bank_supports_the_planned_augmentation() -> None:
    """真实措辞池必须撑得起本轮计划的每任务改写数，否则计划本身不成立。"""
    bank_path = (
        Path(__file__).resolve().parents[1]
        / "data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722"
        / "phrasing/phrasing-bank-001/phrasings.jsonl"
    )
    if not bank_path.is_file():
        pytest.skip("措辞池是 ignored 私有产物，未同步到本机时跳过")
    records = load_phrasing_bank(bank_path)
    assert_partitions_are_disjoint(records)
    assert_intent_coverage(records, minimum=12)
    train_index = intent_index(records, "train_aug")
    for intent in INTENT_BRIEFS:
        assert len(train_index[intent]) >= 3, intent
