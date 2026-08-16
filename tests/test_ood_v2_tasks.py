"""OOD v2 任务集的契约测试。

最要紧的一条是 **oracle 可解性**：把 `expected_calls` 在环境里执行一遍，
最终状态必须等于 `target_state`。这一条不过，整份评测测的就不是模型而是我的真值写错了——
而且会在花掉 GPU 之后才发现。
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from veritool_rl.core.trajectory import ExpectedDecision, TaskScenario
from veritool_rl.retail_ops.build.phrasing_bank import (
    LEAKAGE_PATTERN,
    intent_index,
    load_phrasing_bank,
)
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
from veritool_rl.retail_ops.domain.ood_v2_tasks import (
    OOD_V2_SCENARIOS,
    OOD_V2_TASKS_PER_SCENARIO,
    build_ood_v2_tasks,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = REPO_ROOT / "domains" / "retail_ops" / "v1"
BANK_PATH = (
    REPO_ROOT
    / "data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722"
    / "phrasing/phrasing-bank-001/phrasings.jsonl"
)


def _index(partition: str):  # type: ignore[no-untyped-def]
    if not BANK_PATH.is_file():
        pytest.skip("措辞池是 ignored 私有产物，未同步到本机时跳过")
    return intent_index(load_phrasing_bank(BANK_PATH), partition)  # type: ignore[arg-type]


@pytest.mark.parametrize("partition", ["ood_dev", "ood_sealed"])
def test_oracle_reaches_the_target_state(partition: str) -> None:
    """按 gold 调用序列执行，最终状态必须等于 `target_state`。

    `refund_recovery` 的第一次 refund 会被注入的瞬时故障挡掉，第二次才成功——
    这正是 `expected_calls` 里有两次 refund 的原因。
    """
    bundle = load_bundle(BUNDLE_DIR)
    tasks = build_ood_v2_tasks(_index(partition))
    for task in tasks:
        env = RetailOpsEnv(task, bundle)
        for call in task.expected_calls:
            env.execute_tool(call.name, call.arguments)
        # INFORM / DENY 两类的成功条件包含「给出最终答复」——查完不说话不算完成。
        env.record_final_response("已按订单实际状态给出结论。")
        assert env.verify_final_state() == 1.0, (
            f"{task.metadata['ood_category']} 任务 {task.task_id[:8]} 的 gold 序列没有到达目标状态"
        )
        assert env.check_policy() == [], (
            f"{task.metadata['ood_category']} 任务 {task.task_id[:8]} 的 gold 序列触发了政策违规"
        )


@pytest.mark.parametrize("partition", ["ood_dev", "ood_sealed"])
def test_deny_scenarios_must_not_change_state(partition: str) -> None:
    """拒绝类的 `target_state` 必须与 `initial_state` 相同——正确行为是不动状态。"""
    tasks = build_ood_v2_tasks(_index(partition))
    for task in tasks:
        if task.expected_decision in (ExpectedDecision.DENY, ExpectedDecision.INFORM):
            assert task.target_state == task.initial_state, task.metadata["ood_category"]


@pytest.mark.parametrize("partition", ["ood_dev", "ood_sealed"])
def test_six_scenarios_ten_each(partition: str) -> None:
    """六个场景同时在场，是为了让「见谁都退款」这条捷径当场暴露。"""
    tasks = build_ood_v2_tasks(_index(partition))
    counts: dict[str, int] = {}
    for task in tasks:
        counts[str(task.metadata["ood_category"])] = (
            counts.get(str(task.metadata["ood_category"]), 0) + 1
        )
    assert counts == {scenario.value: OOD_V2_TASKS_PER_SCENARIO for scenario in OOD_V2_SCENARIOS}


@pytest.mark.parametrize("partition", ["ood_dev", "ood_sealed"])
def test_no_user_request_leaks_the_order_state(partition: str) -> None:
    """顾客说破订单状态 = 不查订单也能猜对。整份评测会因此变成读理解。"""
    for task in build_ood_v2_tasks(_index(partition)):
        assert LEAKAGE_PATTERN.search(task.user_request) is None, task.user_request


@pytest.mark.parametrize("partition", ["ood_dev", "ood_sealed"])
def test_generation_is_deterministic(partition: str) -> None:
    first = build_ood_v2_tasks(_index(partition))
    second = build_ood_v2_tasks(_index(partition))
    assert [task.model_dump(mode="json") for task in first] == [
        task.model_dump(mode="json") for task in second
    ]


def test_dev_and_sealed_share_no_phrasing() -> None:
    """两个评测分片逐条互斥——否则「只观测一次」的那一份早就被看过了。"""
    dev = {task.metadata["phrasing_id"] for task in build_ood_v2_tasks(_index("ood_dev"))}
    sealed = {task.metadata["phrasing_id"] for task in build_ood_v2_tasks(_index("ood_sealed"))}
    assert dev & sealed == set()


def test_evaluation_sets_never_use_the_training_partition() -> None:
    """拿训练增强用过的措辞当评测集，测的是有没有背下训练数据。"""
    train = {record.phrasing_id for record in _index("train_aug").get("refund_request", ())}
    for partition in ("ood_dev", "ood_sealed"):
        used = {task.metadata["phrasing_id"] for task in build_ood_v2_tasks(_index(partition))}
        assert used & train == set(), partition


@pytest.mark.parametrize("partition", ["ood_dev", "ood_sealed"])
def test_only_real_tools_appear_in_gold_calls(partition: str) -> None:
    bundle = load_bundle(BUNDLE_DIR)
    allowed = {tool.name for tool in bundle.tools}
    for task in build_ood_v2_tasks(_index(partition)):
        assert {call.name for call in task.expected_calls} <= allowed


@pytest.mark.parametrize("partition", ["ood_dev", "ood_sealed"])
def test_the_business_contract_matches_the_frozen_one(partition: str) -> None:
    """逐场景核对状态形状，确认 v2 改的是说法而不是任务。"""
    tasks = {
        str(task.metadata["ood_category"]): task for task in build_ood_v2_tasks(_index(partition))
    }
    order = lambda task: next(iter(task.initial_state["orders"].values()))  # noqa: E731

    assert order(tasks[TaskScenario.REFUND_ELIGIBLE.value])["refund_status"] == "none"
    assert order(tasks[TaskScenario.REFUND_DENIED_DUPLICATE.value])["refund_status"] == "refunded"
    assert (
        order(tasks[TaskScenario.REFUND_DENIED_WINDOW.value])["refund_deadline"]
        < tasks[TaskScenario.REFUND_DENIED_WINDOW.value].initial_state["current_day"]
    )
    ownership = tasks[TaskScenario.REFUND_DENIED_OWNERSHIP.value]
    assert order(ownership)["customer_id"] != ownership.initial_state["customer_id"]
    assert tasks[TaskScenario.REFUND_RECOVERY.value].transient_failures == {"refund_order": 1}


@pytest.mark.parametrize("partition", ["ood_dev", "ood_sealed"])
def test_user_requests_are_distinct_within_a_set(partition: str) -> None:
    tasks = build_ood_v2_tasks(_index(partition))
    requests = {task.user_request for task in tasks}
    assert len(requests) == len(tasks)


def test_the_built_artifacts_match_the_generator() -> None:
    """已落盘的两份任务集必须与当前代码重算的结果一致。"""
    from veritool_rl.retail_ops.build.ood_manifests import load_ood_manifest

    for partition, name in (("ood_dev", "dev"), ("ood_sealed", "sealed")):
        manifest_path = REPO_ROOT / f"reports/retail_ops/v1/ood-v2/{name}/tasks/manifest.json"
        if not manifest_path.is_file():
            pytest.skip("OOD v2 产物是 ignored 运行产物，未生成时跳过")
        manifest = load_ood_manifest(manifest_path)
        rebuilt = build_ood_v2_tasks(_index(partition))
        assert manifest.task_ids == [task.task_id for task in rebuilt]


def test_recovery_target_state_is_refunded() -> None:
    """`refund_recovery` 的正确终局是退款成功，不是「试过了就算」。"""
    tasks = build_ood_v2_tasks(_index("ood_dev"))
    recovery = next(
        task
        for task in tasks
        if task.metadata["ood_category"] == TaskScenario.REFUND_RECOVERY.value
    )
    target_order = next(iter(recovery.target_state["orders"].values()))
    assert target_order["refund_status"] == "refunded"
    assert copy.deepcopy(recovery.initial_state) != recovery.target_state
