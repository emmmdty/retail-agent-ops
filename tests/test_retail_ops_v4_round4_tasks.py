"""R9 Phase B 第四轮（方案甲 family 覆盖）的 v4 任务集扩展契约。

round4 交接预注册（`docs/handoffs/2026-08-23-r9-phase-b-round4-execution-prompt.md`）
+ 用户 2026-09-04 选项 A 裁定：`retail_ops_v4_20260904` 上 CANCEL_* 4 场景 family
池从 7 态 × 5 语境扩到 10 态 × 5 语境 = 50（state 7–9 使用新增 margin 档 4/6/12），
train family 20 → 35，dev/holdout 配额不变；其余 8 场景与旧版本完全一致。
`retail_ops_v4_20260822` 必须保持原配额可重建（版本↔内容双射不破）。
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
    FormalSplit,
    _materialize_task,
    _sha256,
    _v4_family_spec,
    build_v4_task_set,
)

_V4_CANCEL_SCENARIOS = (
    TaskScenario.CANCEL_ELIGIBLE,
    TaskScenario.CANCEL_DENIED_RECENT,
    TaskScenario.CANCEL_DENIED_IN_USE,
    TaskScenario.CANCEL_RECOVERY,
)


def test_round4_cancel_scenarios_get_extended_train_families() -> None:
    """方案甲单变量：CANCEL_* 4 场景 train 35 family（70 任务），其余 8 场景不变。"""
    task_set = build_v4_task_set("retail_ops_v4_20260904", 0)
    assert len(task_set.train) == 8 * 40 + 4 * 70
    assert len(task_set.dev) == 120
    assert len(task_set.holdout) == 240

    train_counts = Counter(record.task.scenario for record in task_set.train)
    for scenario in _V4_CANCEL_SCENARIOS:
        assert train_counts[scenario] == 70
    for scenario in set(_V4_SCENARIOS) - set(_V4_CANCEL_SCENARIOS):
        assert train_counts[scenario] == 40

    dev_counts = Counter(record.task.scenario for record in task_set.dev)
    holdout_counts = Counter(record.task.scenario for record in task_set.holdout)
    for scenario in _V4_SCENARIOS:
        assert dev_counts[scenario] == 10
        assert holdout_counts[scenario] == 20


def test_frozen_v4_version_keeps_original_quotas() -> None:
    """版本键控：`retail_ops_v4_20260822` 的重建路径必须与冻结时逐位同构。"""
    task_set = build_v4_task_set("retail_ops_v4_20260822", 0)
    assert len(task_set.train) == 480
    assert len(task_set.dev) == 120
    assert len(task_set.holdout) == 240
    train_counts = Counter(record.task.scenario for record in task_set.train)
    for scenario in _V4_SCENARIOS:
        assert train_counts[scenario] == 40


def test_round4_build_is_deterministic() -> None:
    first = build_v4_task_set("retail_ops_v4_20260904", 0)
    second = build_v4_task_set("retail_ops_v4_20260904", 0)
    for split in (FormalSplit.TRAIN, FormalSplit.DEV, FormalSplit.HOLDOUT):
        assert [record.task.task_id for record in first.records(split)] == [
            record.task.task_id for record in second.records(split)
        ]


def test_extended_cancel_states_are_oracle_solvable() -> None:
    """扩出的 state 7–9 family 必须在环境里可解且零违规（Oracle 自洽门）。"""
    bundle = load_bundle(Path("domains/retail_ops/v4"))
    dataset_version = "retail_ops_v4_20260904"
    solved = 0
    for scenario_index, scenario in enumerate(_V4_SCENARIOS):
        if scenario not in _V4_CANCEL_SCENARIOS:
            continue
        for state_variant in (7, 8, 9):
            for context_variant in range(5):
                family = _v4_family_spec(
                    dataset_version, scenario, scenario_index, state_variant, context_variant
                )
                for variant_index in range(2):
                    task = _materialize_task(
                        dataset_version=dataset_version,
                        seed=0,
                        split=FormalSplit.TRAIN,
                        family=family,
                        family_fingerprint=_sha256({"family": family}),
                        variant_index=variant_index,
                    )
                    trajectory = run_episode(
                        task,
                        lambda current: RetailOpsEnv(current, bundle),
                        OraclePolicy(task),
                        0,
                    )
                    assert trajectory.success, f"{scenario.value} {task.task_id} Oracle 解不出"
                    assert trajectory.violations == []
                    solved += 1
    assert solved == 4 * 3 * 5 * 2
