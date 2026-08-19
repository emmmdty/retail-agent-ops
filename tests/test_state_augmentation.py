"""状态增强的隔离契约与导出行为。

这次改动的全部合法性建立在一句话上：**增强素材落在冻结网格之外，
因此按构造不可能复现任何 dev / holdout family。** 那句话必须是可执行的，
而不是配置注释里的一段说明——所以这里逐条断言，并种反例验证断言真的会红。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from veritool_rl.core.trajectory import ExpectedDecision, TaskScenario
from veritool_rl.retail_ops.domain import formal_tasks
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
from veritool_rl.retail_ops.domain.policy_boundary_tasks import build_policy_boundary_tasks
from veritool_rl.retail_ops.domain.state_augmentation_tasks import (
    AUGMENTED_SCENARIOS,
    INSTANCES_PER_MARGIN,
    OFF_GRID_MARGINS,
    STATE_AUG_DATASET_VERSION,
    build_state_augmentation_tasks,
    probe_deadlines,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _bundle() -> Any:
    return load_bundle(REPO_ROOT / "domains/retail_ops/v1")


def test_the_augmentation_margins_are_outside_the_frozen_grid() -> None:
    """网格内取值会复现某个 dev/holdout family 的语义——那是泄漏，不是增强。"""
    assert set(OFF_GRID_MARGINS).isdisjoint(formal_tasks._MARGINS)


def test_no_augmentation_task_shares_a_state_with_any_frozen_task() -> None:
    """**经验验证**：逐条比对增强任务与冻结数据集全部 420 条任务的关键状态。

    上一条断言的是 margin 集合不相交（构造层面）；这一条直接比对产出的
    `(scenario, refund_deadline, distractor_count)` 三元组，不依赖"构造正确"这个前提。
    两条都在，是因为它们会因不同的错误而红：改了 `_CURRENT_DAY` 只有这一条会红。
    """
    frozen: set[tuple[str, int, int]] = set()
    task_set = formal_tasks.build_formal_task_set("retail_ops_v1_r2_20260722", seed=0)
    for split in formal_tasks.FormalSplit:
        for record in task_set.records(split):
            task = record.task
            order = task.initial_state["orders"][task.metadata["order_id"]]
            frozen.add(
                (
                    task.scenario.value,
                    int(order["refund_deadline"]),
                    len(task.initial_state["orders"]) - 1,
                )
            )

    collisions = [
        task.task_id
        for task in build_state_augmentation_tasks(0)
        if (
            task.scenario.value,
            int(task.metadata["refund_deadline"]),
            int(task.metadata["distractor_count"]),
        )
        in frozen
    ]
    assert collisions == [], f"{len(collisions)} 条增强任务与冻结任务状态相同"


def test_the_augmentation_never_touches_a_probe_evaluation_point() -> None:
    """增强素材用了探针的评测点，复测就分不清「学会规则」与「背下那一格」。"""
    produced = {int(task.metadata["refund_deadline"]) for task in build_state_augmentation_tasks(0)}
    assert produced.isdisjoint(probe_deadlines())


def test_the_probe_evaluation_points_are_derived_not_restated() -> None:
    """探针评测点必须从探针本身派生——两处各写一份必然漂移。"""
    from_probe = {
        int(task.initial_state["orders"][task.metadata["order_id"]]["refund_deadline"])
        for task in build_policy_boundary_tasks(0)
    }
    assert from_probe == set(probe_deadlines())


def test_both_sides_of_the_boundary_get_the_same_margins() -> None:
    """只补拒绝侧的话，「学会了规则」与「学会了多拒绝」在读数上无法区分。"""
    by_scenario: dict[str, set[int]] = {}
    for task in build_state_augmentation_tasks(0):
        by_scenario.setdefault(task.scenario.value, set()).add(int(task.metadata["margin"]))

    assert set(by_scenario) == {scenario.value for scenario in AUGMENTED_SCENARIOS}
    assert len(set(map(frozenset, by_scenario.values()))) == 1, (
        f"两侧的 margin 集合不同：{by_scenario}"
    )


def test_the_augmentation_set_has_the_declared_shape() -> None:
    tasks = build_state_augmentation_tasks(0)
    assert len(tasks) == len(OFF_GRID_MARGINS) * INSTANCES_PER_MARGIN * len(AUGMENTED_SCENARIOS)
    assert len({task.task_id for task in tasks}) == len(tasks)
    for task in tasks:
        assert task.split == "train", "teacher 采集只接受 train split"
        assert task.metadata["dataset_version"] == STATE_AUG_DATASET_VERSION


@pytest.mark.parametrize("scenario", [s.value for s in AUGMENTED_SCENARIOS])
def test_every_augmentation_task_is_solvable_and_its_gold_is_policy_clean(scenario: str) -> None:
    """gold 调用序列必须达成终态且零违规——否则增强素材本身就是错的。"""
    bundle = _bundle()
    checked = 0
    for task in build_state_augmentation_tasks(0):
        if task.scenario.value != scenario:
            continue
        env = RetailOpsEnv(task, bundle)
        for call in task.expected_calls:
            env.execute_tool(call.name, dict(call.arguments))
        env.record_final_response("ok")
        assert env.verify_final_state() == 1.0, task.task_id
        assert env.check_policy() == [], task.task_id
        checked += 1
    assert checked > 0


def test_forcing_a_refund_on_the_denied_side_is_always_caught() -> None:
    """拒绝侧的增强任务，强行退款必须被政策规则判违规。"""
    bundle = _bundle()
    leaks = []
    for task in build_state_augmentation_tasks(0):
        if task.expected_decision is not ExpectedDecision.DENY:
            continue
        env = RetailOpsEnv(task, bundle)
        order_id = str(task.metadata["order_id"])
        env.execute_tool("get_order", {"order_id": order_id})
        env.execute_tool(
            "refund_order", {"order_id": order_id, "reason": str(task.metadata["reason"])}
        )
        if not env.check_policy():
            leaks.append(task.task_id)
    assert leaks == []


def test_a_grid_collision_is_rejected_at_construction_time() -> None:
    """种一个网格内的 margin，构建必须当场失败——否则那条隔离声称没有执行者。"""
    import veritool_rl.retail_ops.domain.state_augmentation_tasks as module

    original = module.OFF_GRID_MARGINS
    try:
        module.OFF_GRID_MARGINS = (*original, formal_tasks._MARGINS[0])
        with pytest.raises(ValueError, match="冻结网格"):
            module.build_state_augmentation_tasks(0)
    finally:
        module.OFF_GRID_MARGINS = original


def test_a_probe_point_collision_is_rejected_at_construction_time() -> None:
    """种一个会落在探针评测点上的 margin，构建必须当场失败。"""
    import veritool_rl.retail_ops.domain.state_augmentation_tasks as module

    original = module.OFF_GRID_MARGINS
    # margin 14 会让拒绝侧 deadline = 6，正是探针的 offset −14；
    # 但 14 也在冻结网格里，会先被上一条断言拦下。用 margin 0：deadline = 20，
    # 正是探针的 offset 0，而 0 不在冻结网格里。
    try:
        module.OFF_GRID_MARGINS = (*original, 0)
        with pytest.raises(ValueError, match="探针评测点"):
            module.build_state_augmentation_tasks(0)
    finally:
        module.OFF_GRID_MARGINS = original


def test_an_empty_cell_refuses_to_export() -> None:
    """某个 (场景, deadline) 一条合格轨迹都没有时必须失败。

    这是「补了这个区域」这句话的执行者：某一格薄一点是**已披露**的事实
    （报告里逐格计数），但一格为空就让那句话对它变成假的。
    """
    from veritool_rl.retail_ops.build.state_augmentation import (
        StateAugmentationGateError,
        build_augmentation_rows,
    )

    tasks = build_state_augmentation_tasks(0)
    bundle = _bundle()

    with pytest.raises(StateAugmentationGateError, match="一条合格轨迹都没有"):
        build_augmentation_rows(tasks, [], lambda task: RetailOpsEnv(task, bundle), _plan())


def test_a_collapsed_acceptance_rate_refuses_to_export() -> None:
    """整体接受率塌下去时失败——那更像采集路径坏了，而不是个别任务难。

    构造：每格留一条被接受的轨迹（因此没有空格子），其余全部失败。
    接受率 = 1/4 = 25%，远低于下限。
    """
    from veritool_rl.retail_ops.build.state_augmentation import (
        MIN_ACCEPTANCE_RATE,
        StateAugmentationGateError,
        assert_cell_coverage,
    )

    tasks = build_state_augmentation_tasks(0)
    seen: set[tuple[str, int]] = set()
    kept: set[str] = set()
    for task in tasks:
        key = (task.scenario.value, int(task.metadata["refund_deadline"]))
        if key not in seen:
            seen.add(key)
            kept.add(task.task_id)

    assert len(kept) / len(tasks) < MIN_ACCEPTANCE_RATE
    with pytest.raises(StateAugmentationGateError, match="整体接受率"):
        assert_cell_coverage(tasks, kept)


def _plan() -> Any:
    from veritool_rl.retail_ops.build.phrasing_bank import ParaphrasePlan, PhrasingRecord

    record = PhrasingRecord(
        phrasing_id="0" * 64,
        intent="refund_request",
        style="terse",
        partition="train_aug",
        text="订单 {order_id} 我要退款。",
    )
    return ParaphrasePlan(index={"refund_request": [record]}, per_task=1, bank_sha256="0" * 64)


def test_the_export_config_declares_the_same_bank_as_the_base_export() -> None:
    """增强行与基底行必须来自同一份措辞池，否则表面形式成了第二个变量。"""
    import yaml

    base = yaml.safe_load(
        (
            REPO_ROOT / "configs/retail_ops/build/retail_ops_v1_r6b_train_export_no_oversample.yaml"
        ).read_text(encoding="utf-8")
    )
    augmented = yaml.safe_load(
        (REPO_ROOT / "configs/retail_ops/build/retail_ops_v1_r8_state_aug_export.yaml").read_text(
            encoding="utf-8"
        )
    )

    assert augmented["sft_paraphrase"] == base["sft_paraphrase"]
    assert augmented["base_attempt_id"] == base["attempt_id"]


def test_the_augmentation_rows_keep_the_assistant_tool_call_content_empty() -> None:
    """assistant 工具调用消息的 content 必须为空。

    `parser.py` 把「文本 + 工具调用同时出现」判为 `mixed_tool_call_content`，
    即非法调用。任何"先声明再执行"的数据方案都会把 `invalid_call` 从 0 打回去。
    这里用 gold 轨迹走一遍导出转换来验证形状。
    """
    from veritool_rl.core.agent.policy import OraclePolicy
    from veritool_rl.core.agent.runner import run_episode
    from veritool_rl.core.generators import trajectory_to_sft_example

    bundle = _bundle()
    task = build_state_augmentation_tasks(0)[0]
    trajectory = run_episode(
        task, lambda current: RetailOpsEnv(current, bundle), OraclePolicy(task), seed=0
    )
    example = trajectory_to_sft_example(trajectory)

    for message in example["messages"]:
        if message.get("tool_calls"):
            assert message.get("content") == "", json.dumps(message, ensure_ascii=False)


def test_the_augmented_scenarios_are_only_the_two_the_diagnosis_points_at() -> None:
    """诊断指向的是退款窗口这一条规则；动别的场景会让变量不单一。"""
    assert set(AUGMENTED_SCENARIOS) == {
        TaskScenario.REFUND_ELIGIBLE,
        TaskScenario.REFUND_DENIED_WINDOW,
    }


def test_the_new_sft_config_changes_only_the_training_data() -> None:
    """相对 `sft-008` 的 SFT 配置，唯一允许变的是 `data` 一段。

    LoRA、超参、基座 pin 任何一处不同，"读数变化来自补了状态覆盖"就不再成立。
    """
    import yaml

    base = yaml.safe_load(
        (REPO_ROOT / "configs/retail_ops/build/retail_ops_v1_r6b_no_oversample_sft.yaml").read_text(
            encoding="utf-8"
        )
    )
    variant = yaml.safe_load(
        (REPO_ROOT / "configs/retail_ops/build/retail_ops_v1_r8_state_aug_sft.yaml").read_text(
            encoding="utf-8"
        )
    )

    assert set(base) == set(variant)
    differing = {key for key in base if base[key] != variant[key]}
    assert differing == {"data"}, f"除 data 外还差了：{differing - {'data'}}"
    assert variant["data"]["train_relpath"] == "train-export/train-export-008/sft.jsonl"
    assert variant["data"]["eval_relpath"] == base["data"]["eval_relpath"]


def test_the_sft_config_discloses_the_gradient_step_confound() -> None:
    """行数变了，梯度步数就跟着变——这个混淆必须写在配置里，不能只在对话里说。

    断言的是**这件事被承认了**，不是某一句原话：配置注释里要同时出现新旧行数
    与"分不开"这个判断。R6 记过同一类混淆（LOG-20260817-01 的"自变量不纯"）。
    """
    text = (REPO_ROOT / "configs/retail_ops/build/retail_ops_v1_r8_state_aug_sft.yaml").read_text(
        encoding="utf-8"
    )

    assert "960" in text and "1168" in text, "配置没有写出行数变化"
    assert "分不开" in text, "配置没有承认步数与覆盖两个变量分不开"


def test_the_new_candidate_configs_change_only_the_adapter() -> None:
    """相对 `sft-008` 的两份候选配置，允许变的只有 adapter（dev 侧再加 attempt_id）。

    基座 pin、生成参数、manifest 任何一处不同，"读数变化来自这份权重"就不成立。
    """
    import yaml

    def load(name: str) -> dict[str, Any]:
        return yaml.safe_load(
            (REPO_ROOT / "configs/retail_ops/evaluate" / name).read_text(encoding="utf-8")
        )

    dev_base = load("retail_ops_v1_r6b_candidate.yaml")
    dev_new = load("retail_ops_v1_r8_state_aug_candidate.yaml")
    assert set(dev_base) == set(dev_new)
    assert {k for k in dev_base if dev_base[k] != dev_new[k]} == {"attempt_id", "adapter"}

    ood_base = load("retail_ops_ood_r6b_candidate.yaml")
    ood_new = load("retail_ops_ood_r8_state_aug_candidate.yaml")
    assert set(ood_base) == set(ood_new)
    assert {k for k in ood_base if ood_base[k] != ood_new[k]} == {"adapter"}

    # 两份配置必须指向**同一个** adapter，否则 dev 与 OOD 读的是两份权重。
    assert dev_new["adapter"] == ood_new["adapter"]
    assert dev_new["adapter"]["run_dir"] == "reports/retail_ops/v1/r8/sft-009"
