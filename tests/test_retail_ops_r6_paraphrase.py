"""R6 训练增强：导出侧的 paraphrase 行为契约。

这一层要挡住的是「改写把任务改了」。paraphrase 只允许动 user 的**第一句话**；
assistant 的工具调用、tool 观测与最终状态一个字都不能变——否则改的就不是「说法」
而是「任务」，而数据集里的 `target_state` / `expected_calls` 不会跟着变，
等于往训练集里掺标注错误的样本。
"""

from __future__ import annotations

import pytest

from tests.test_teacher_data import (  # 复用已有的记录/证据/环境夹具
    _config,
    _env_factory,
    _evidence,
    _real_train_records,
)
from veritool_rl.core.trajectory import TaskScenario
from veritool_rl.retail_ops.build.phrasing_bank import (
    INTENT_REFUND,
    INTENT_STATUS,
    ParaphrasePlan,
    PhrasingRecord,
    assign_partition,
    build_records,
    intent_index,
    phrasing_id,
)
from veritool_rl.retail_ops.build.teacher_data import export_formal_train

_PER_TASK = 3


def _plan(per_task: int = _PER_TASK) -> ParaphrasePlan:
    """构造一个只含 train_aug 分片的计划。

    直接按分片过滤而不是硬编码文本，是为了让这份夹具与真实加载路径走同一套规则。
    """
    accepted = [
        (intent, "s", f"{marker} 第 {index} 种说法 {{order_id}} 谢谢")
        for intent, marker in ((INTENT_REFUND, "退"), (INTENT_STATUS, "查"))
        for index in range(400)
    ]
    records = build_records(accepted)
    return ParaphrasePlan(
        index=intent_index(records, "train_aug"),
        per_task=per_task,
        bank_sha256="0" * 64,
    )


def _export(plan: ParaphrasePlan | None):  # type: ignore[no-untyped-def]
    records = _real_train_records([TaskScenario.LOOKUP_STATUS])[:6]
    evidences = [_evidence(record.task.task_id, accepted=True) for record in records]
    scenarios = {record.task.task_id: record.task.scenario.value for record in records}
    return records, export_formal_train(
        records,
        evidences,
        _env_factory,
        _config(),
        scenarios,
        seed=0,
        sft_paraphrase=plan,
    )


def test_paraphrase_multiplies_only_the_sft_rows() -> None:
    """`train_rows` 是 provenance，声称「本次覆盖了哪些冻结任务」，不得被增强撑大。"""
    records, (_, _, train_rows, sft_rows) = _export(_plan())
    assert len(train_rows) == len(records)
    assert len(sft_rows) == len(records) * (1 + _PER_TASK)


def test_disabling_paraphrase_reproduces_the_old_behaviour() -> None:
    records, (_, _, _, baseline) = _export(None)
    assert len(baseline) == len(records)


def test_only_the_first_user_message_changes() -> None:
    """逐条比对：除首条 user 的 content 外，消息序列必须逐字段相同。"""
    _, (_, _, _, sft_rows) = _export(_plan())
    original = sft_rows[0]
    variants = [row for row in sft_rows if row["task_id"] == original["task_id"]]
    assert len(variants) == 1 + _PER_TASK

    for variant in variants[1:]:
        assert len(variant["messages"]) == len(original["messages"])
        first_user = next(
            index for index, message in enumerate(original["messages"]) if message["role"] == "user"
        )
        for index, (before, after) in enumerate(
            zip(original["messages"], variant["messages"], strict=True)
        ):
            if index == first_user:
                assert before["content"] != after["content"], "改写没生效"
                assert before["role"] == after["role"]
            else:
                assert before == after, f"第 {index} 条消息被改动了：{before} != {after}"


def test_tool_calls_and_observations_survive_untouched() -> None:
    """把「工具调用与观测不变」单独断言一次——这是改写与换任务的分界线。"""
    _, (_, _, _, sft_rows) = _export(_plan())
    by_task: dict[str, list[dict]] = {}
    for row in sft_rows:
        by_task.setdefault(row["task_id"], []).append(row)

    for rows in by_task.values():
        signatures = {
            tuple(
                (message["role"], message.get("tool_calls") and str(message["tool_calls"]))
                for message in row["messages"]
                if message["role"] in {"assistant", "tool"}
            )
            for row in rows
        }
        assert len(signatures) == 1, "同一任务的不同改写产生了不同的工具调用序列"


def test_the_order_id_is_filled_in() -> None:
    _, (_, _, _, sft_rows) = _export(_plan())
    for row in sft_rows:
        user = next(m for m in row["messages"] if m["role"] == "user")
        assert "{order_id}" not in user["content"]


def test_variants_of_one_task_are_distinct() -> None:
    _, (_, _, _, sft_rows) = _export(_plan())
    by_task: dict[str, set[str]] = {}
    for row in sft_rows:
        user = next(m for m in row["messages"] if m["role"] == "user")
        by_task.setdefault(row["task_id"], set()).add(user["content"])
    for texts in by_task.values():
        assert len(texts) == 1 + _PER_TASK, "同一任务出现了重复的改写"


def test_plan_refuses_an_evaluation_partition() -> None:
    """用评测分片做训练增强 = 本轮全部泛化结论作废。必须是硬错误。"""
    with pytest.raises(ValueError, match="只能用 train_aug"):
        ParaphrasePlan(index={}, per_task=1, bank_sha256="0" * 64, partition="ood_sealed")


def test_plan_refuses_a_non_positive_per_task() -> None:
    with pytest.raises(ValueError, match="per_task"):
        ParaphrasePlan(index={}, per_task=0, bank_sha256="0" * 64)


def test_export_fails_loudly_when_the_pool_is_too_small() -> None:
    """池子不够时必须报错而不是重复取样——重复是加权，不是增强。"""
    text = "退一下 {order_id} 谢谢"
    tiny = ParaphrasePlan(
        index={
            INTENT_STATUS: [
                PhrasingRecord(
                    phrasing_id=phrasing_id(text),
                    intent=INTENT_STATUS,
                    style="s",
                    text=text,
                    partition=assign_partition(text),
                )
            ]
        },
        per_task=3,
        bank_sha256="0" * 64,
    )
    with pytest.raises(ValueError, match="取不出"):
        _export(tiny)
