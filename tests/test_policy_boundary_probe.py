"""政策边界探针的构造契约。

探针的全部价值来自一件事：**它的真值来自可执行的政策规则，不是来自一张手写的期望表。**
如果这两者会漂移，那么探针量到的"模型边界与政策边界的差"里就混进了"探针自己写错了"。
因此这里逐点比对探针的期望判定与 `evaluate_refund_rules` 的实际判定。
"""

from __future__ import annotations

from collections import Counter, defaultdict

import pytest

from veritool_rl.core.trajectory import ExpectedDecision, TaskScenario
from veritool_rl.retail_ops.domain import formal_tasks
from veritool_rl.retail_ops.domain.policy_boundary_tasks import (
    CURRENT_DAY,
    INSTANCES_PER_OFFSET,
    OFFSETS,
    POLICY_BOUNDARY_DATASET_VERSION,
    POLICY_BOUNDARY_GENERATOR_ID,
    build_policy_boundary_tasks,
    expected_category_counts,
    expected_decision_for,
    offset_kind,
)
from veritool_rl.retail_ops.domain.policy_rules import (
    V1_BUILTIN_RULES,
    RefundFacts,
    evaluate_refund_rules,
)


@pytest.mark.parametrize("offset", OFFSETS)
def test_the_probe_agrees_with_the_executable_policy(offset: int) -> None:
    """探针每一点的期望判定 == 可执行规则在同一状态上的判定。

    事实投影逐字复刻 `environment._refund_facts`：`days_past_deadline = 今天 − 到期日`，
    而到期日 = `今天 + offset`，因此 `days_past_deadline = −offset`。
    规则 `refund_window_must_be_open` 的条件是 `days_past_deadline gt 0`。

    **`offset = 0` 是这条测试真正在保护的点**：`gt 0` 意味着恰好到期当天仍然放行。
    把它误写成 `gte 0`，或者探针这边把 0 当成拒绝，两边就会在整个分析里系统性错一格。
    """
    facts = RefundFacts(
        order_was_read=True,
        caller_owns_order=True,
        days_past_deadline=CURRENT_DAY - (CURRENT_DAY + offset),
        already_refunded=False,
        reason_is_approved=True,
    )
    decision = evaluate_refund_rules(V1_BUILTIN_RULES, facts)

    if expected_decision_for(offset) is ExpectedDecision.DENY:
        assert decision is not None, f"offset={offset} 探针期望拒绝，但规则不拒绝"
        assert decision.rule_id == "refund_window_must_be_open"
    else:
        assert decision is None, f"offset={offset} 探针期望放行，但规则判 {decision}"


def test_the_probe_shares_the_frozen_calendar() -> None:
    """探针与冻结数据集必须用同一个「今天」，否则两边的偏移量不可比。"""
    assert CURRENT_DAY == formal_tasks._CURRENT_DAY


def test_the_probe_covers_the_boundary_the_frozen_dataset_never_generates() -> None:
    """`offset = 0`（恰好到期）必须在探针里，且冻结数据集里确实一条都没有。

    冻结数据集的 eligible 用 `今天 + margin`、denied 用 `今天 − margin`，
    而 `margin ∈ {1,2,3,5,7,10,14}`——**判定分界那一天从来没有被测过**。
    这条测试同时钉住两件事：探针补上了它，以及"冻结集没有它"这个说法是真的。
    """
    assert 0 in OFFSETS

    task_set = formal_tasks.build_formal_task_set("retail_ops_v1_r2_20260722", seed=0)
    offsets_in_frozen_dataset = set()
    for split in formal_tasks.FormalSplit:
        for record in task_set.records(split):
            task = record.task
            if task.scenario not in (
                TaskScenario.REFUND_ELIGIBLE,
                TaskScenario.REFUND_DENIED_WINDOW,
            ):
                continue
            order = task.initial_state["orders"][task.metadata["order_id"]]
            current_day = task.initial_state["current_day"]
            offsets_in_frozen_dataset.add(int(order["refund_deadline"]) - int(current_day))

    assert 0 not in offsets_in_frozen_dataset, (
        f"冻结数据集里其实存在 offset=0 的任务，探针的立论要改：{sorted(offsets_in_frozen_dataset)}"
    )


def test_the_frozen_split_does_not_stratify_by_difficulty() -> None:
    """**探针存在的理由本身要可核对。**

    冻结数据集按 `sha256(family)` 排序后切 20/5/10，切分**不看难度**，
    而拒绝类场景的难度就是 margin 离边界多远。结果是 dev 在这些场景上只覆盖
    margin 网格的一部分，且与 holdout 覆盖的档位不同。

    这条测试断言的是那个结构事实（dev 覆盖的档位数 < 网格档位数），
    **不是某一组具体档位**——换 `dataset_version` 会换一组档位，但只要切分仍不分层，
    覆盖不全这件事就成立。若将来真的改成按难度分层，这条会红，
    那时探针的立论需要重写，而不是悄悄失效。
    """
    denial_scenarios = (
        TaskScenario.REFUND_DENIED_WINDOW,
        TaskScenario.REFUND_DENIED_DUPLICATE,
        TaskScenario.REFUND_DENIED_OWNERSHIP,
    )
    task_set = formal_tasks.build_formal_task_set("retail_ops_v1_r2_20260722", seed=0)
    grid_size = len(formal_tasks._MARGINS)

    coverage: dict[TaskScenario, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
    for split in formal_tasks.FormalSplit:
        for record in task_set.records(split):
            task = record.task
            if task.scenario not in denial_scenarios:
                continue
            family = task.metadata["formal_family"]
            margin = formal_tasks._MARGINS[int(family["state_variant"])]
            coverage[task.scenario][split.value].add(margin)

    for scenario in denial_scenarios:
        dev_buckets = coverage[scenario]["dev"]
        holdout_buckets = coverage[scenario]["holdout"]
        assert len(dev_buckets) < grid_size, (
            f"{scenario.value}: dev 已经覆盖了全部 {grid_size} 个 margin 档，"
            f"切分似乎已按难度分层——探针的立论需要重写"
        )
        assert holdout_buckets - dev_buckets, (
            f"{scenario.value}: holdout 没有任何 dev 看不到的 margin 档，"
            f"「dev 结构上看不见 holdout 的一部分状态」这句话不再成立"
        )


def test_the_probe_task_set_has_the_declared_shape() -> None:
    tasks = build_policy_boundary_tasks(seed=0)

    assert len(tasks) == len(OFFSETS) * INSTANCES_PER_OFFSET
    assert len({task.task_id for task in tasks}) == len(tasks), "task_id 有重复"
    assert Counter(str(task.metadata["ood_kind"]) for task in tasks) == {
        offset_kind(offset): INSTANCES_PER_OFFSET for offset in OFFSETS
    }
    assert (
        Counter(str(task.metadata["ood_category"]) for task in tasks) == expected_category_counts()
    )
    for task in tasks:
        assert task.metadata["dataset_version"] == POLICY_BOUNDARY_DATASET_VERSION
        assert task.metadata["generator_id"] == POLICY_BOUNDARY_GENERATOR_ID


def test_the_two_sides_of_the_boundary_share_their_request_templates() -> None:
    """放行侧与拒绝侧必须用**同一组**措辞。

    若"过期"那一侧的问法自带犹豫语气、"窗口内"那一侧自带祈使语气，模型就能靠语气
    而不是靠日期作答——探针量到的会是一条假的边界，而且是**偏乐观**的假边界。
    这里把订单号抹掉之后比较模板集合。
    """
    tasks = build_policy_boundary_tasks(seed=0)
    templates: dict[ExpectedDecision, set[str]] = defaultdict(set)
    for task in tasks:
        order_id = str(task.metadata["order_id"])
        reason = str(task.metadata["reason"])
        normalised = task.user_request.replace(order_id, "<ORDER>").replace(reason, "<REASON>")
        templates[task.expected_decision].add(normalised)

    assert templates[ExpectedDecision.ALLOW] == templates[ExpectedDecision.DENY], (
        "两侧的请求模板不同，模型可以靠措辞而不是靠日期作答"
    )


def test_the_probe_is_deterministic() -> None:
    """同一个 seed 必须逐字段产出同一份任务集——否则读数不可比。"""
    first = build_policy_boundary_tasks(seed=0)
    second = build_policy_boundary_tasks(seed=0)

    assert [task.model_dump(mode="json") for task in first] == [
        task.model_dump(mode="json") for task in second
    ]


def test_every_probe_task_only_uses_tools_the_bundle_declares() -> None:
    """任务集不得自己发明工具——那会让整份评测测的是别的东西。"""
    from pathlib import Path

    from veritool_rl.retail_ops.domain.bundle import load_bundle

    bundle = load_bundle(Path(__file__).resolve().parents[1] / "domains/retail_ops/v1")
    declared = {tool.name for tool in bundle.tools}

    for task in build_policy_boundary_tasks(seed=0):
        for call in task.expected_calls:
            assert call.name in declared, f"{task.task_id}: 未声明的工具 {call.name}"


def test_the_frozen_quota_guards_actually_reject_a_violation() -> None:
    """**冻结配额的两条守卫本身必须会红。**

    `CLAUDE.md` 把 40/10/20 与 `dataset_version` 列为「改它会让已有全部评测证据的
    可比性作废」的冻结契约，执行者是 `FormalTaskSet.assert_exact_quotas`。
    真实数据当然满足配额，所以这两条守卫**平时永远不会触发**——
    外部评审 2026-08-19 用变异测试证明：把总数校验或分类配额校验整个删掉，全仓全绿。
    一条只在未来某次改动时才有价值的断言，如果它自己坏了没人知道，它就不存在。

    这里不改被测代码，而是构造一个**确实违反配额**的任务集喂给它。
    """
    task_set = formal_tasks.build_formal_task_set("retail_ops_v1_r2_20260722", seed=0)
    task_set.assert_exact_quotas()  # 真实数据先确认是通过的

    # 1) 总数不足：dev 少一条
    short = task_set.model_copy(update={"dev": task_set.dev[:-1]})
    with pytest.raises(ValueError, match="任务总数"):
        short.assert_exact_quotas()

    # 2) 总数对但**分类配额**错：把 dev 的最后一条换成第一条的复制品，
    #    于是某个场景多一条、另一个少一条，而总数不变。
    skewed = task_set.model_copy(update={"dev": (*task_set.dev[:-1], task_set.dev[0])})
    assert len(skewed.dev) == len(task_set.dev)
    with pytest.raises(ValueError):
        skewed.assert_exact_quotas()
