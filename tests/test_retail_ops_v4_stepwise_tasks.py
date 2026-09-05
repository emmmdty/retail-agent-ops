"""R9 Phase B 第四轮方案乙（rtc_stepwise 辅助课程）的任务集契约。

round4 交接方案乙（用户 2026-09-04 确认上乙）+ `task_plan.md` 预注册（`7472c2c`）：
`retail_ops_v4_20260905` 上为每个 rtc train family 派生一个 `rtc_stepwise` 辅助 family
（复用 cancel_eligible 结构，gold = 查 B + 取消 B，订单号取 RTC 的 other_order），
只进 train split（dev/holdout 为 0，评测面不变），rtc 40 ↔ stepwise 40（1:1）。
旧版本（v4_20260822 / v4_20260904）不产 rtc_stepwise。
"""

from collections import Counter
from pathlib import Path

from veritool_rl.core.agent.policy import OraclePolicy
from veritool_rl.core.agent.runner import run_episode
from veritool_rl.core.trajectory import TaskScenario
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
from veritool_rl.retail_ops.domain.formal_tasks import (
    _V4_SCENARIOS,
    build_v4_task_set,
)

STEPWISE_VERSION = "retail_ops_v4_20260905"


def test_stepwise_tasks_are_train_only_and_paired_one_to_one() -> None:
    task_set = build_v4_task_set(STEPWISE_VERSION, 0)
    train_counts = Counter(record.task.scenario for record in task_set.train)
    assert train_counts[TaskScenario.RTC_STEPWISE] == 40
    assert train_counts[TaskScenario.REFUND_THEN_CANCEL] == 40
    assert len(task_set.train) == 640
    dev_counts = Counter(record.task.scenario for record in task_set.dev)
    holdout_counts = Counter(record.task.scenario for record in task_set.holdout)
    assert TaskScenario.RTC_STEPWISE not in dev_counts
    assert TaskScenario.RTC_STEPWISE not in holdout_counts
    assert len(task_set.dev) == 120
    assert len(task_set.holdout) == 240


def test_older_versions_never_produce_stepwise() -> None:
    for version in ("retail_ops_v4_20260822", "retail_ops_v4_20260904"):
        task_set = build_v4_task_set(version, 0)
        for split in (task_set.train, task_set.dev, task_set.holdout):
            assert all(record.task.scenario is not TaskScenario.RTC_STEPWISE for record in split), (
                version
            )


def test_stepwise_gold_cancels_only_b() -> None:
    """辅助任务 gold = get_order(B) → cancel_order(B)；target 只把 B 置 cancelled，A 不动。"""
    task_set = build_v4_task_set(STEPWISE_VERSION, 0)
    checked = 0
    for record in task_set.train:
        task = record.task
        if task.scenario is not TaskScenario.RTC_STEPWISE:
            continue
        assert [call.name for call in task.expected_calls] == ["get_order", "cancel_order"]
        assert (
            task.expected_calls[0].arguments["order_id"]
            == task.expected_calls[1].arguments["order_id"]
        )
        other_ids = {
            order_id
            for order_id, order in task.initial_state["orders"].items()
            if order.get("status") == "pending" and order.get("refund_status") == "none"
        }
        assert task.expected_calls[0].arguments["order_id"] in other_ids
        cancelled_id = task.expected_calls[0].arguments["order_id"]
        assert task.target_state["orders"][cancelled_id]["cancel_status"] == "cancelled"
        assert task.required_reads == [cancelled_id]
        checked += 1
    assert checked == 40


def test_stepwise_tasks_are_oracle_solvable() -> None:
    bundle = load_bundle(Path("domains/retail_ops/v4"))
    task_set = build_v4_task_set(STEPWISE_VERSION, 0)
    solved = 0
    for record in task_set.train:
        task = record.task
        if task.scenario is not TaskScenario.RTC_STEPWISE:
            continue
        trajectory = run_episode(
            task,
            lambda current: RetailOpsEnv(current, bundle),
            OraclePolicy(task),
            0,
        )
        assert trajectory.success, f"{task.task_id} Oracle 解不出"
        assert trajectory.violations == []
        solved += 1
    assert solved == 40


def test_stepwise_does_not_disturb_other_scenarios() -> None:
    """stepwise 版本上非 rtc/stepwise 场景的 train 配额与 v4r4 完全一致。"""
    task_set = build_v4_task_set(STEPWISE_VERSION, 0)
    train_counts = Counter(record.task.scenario for record in task_set.train)
    for scenario in _V4_SCENARIOS:
        expected = (
            70
            if scenario.value.startswith("cancel")
            and scenario is not TaskScenario.REFUND_THEN_CANCEL
            else 40
        )
        assert train_counts[scenario] == expected, scenario
