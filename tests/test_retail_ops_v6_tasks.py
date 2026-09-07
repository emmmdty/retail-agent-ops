"""V6-2：rtc_stepwise 请求修复 + v6 任务集（预注册 A-0 裁定 1/2，2026-09-07）。

缺陷（PITFALLS #26，继承自 v4_20260905）：`rtc_stepwise` 的用户请求把 rtc 家族的
**退款枚举** reason 写进**取消**任务（「请取消订单 B，原因是 not_as_described。」），
而 gold `cancel_other` 硬编码 `_V4_CANCEL_REASONS[0]="changed_mind"`——teacher 按请求
陈述的 reason 发起取消 → 环境拒绝（枚举域外）→ 13 wrong_final_state + 2 schema_invalid。

修复（交接 V6-2）：v6 起该请求的 reason 与 gold 同源（`_V4_CANCEL_REASONS[0]`），
版本键控——**v4/v5 的重建路径逐字节不变**（它们的请求文本是冻结数据的一部分），
缺陷只在 v6 dataset_version 上生效。

本文件锁定：
1. v6 全部 `rtc_stepwise` 任务的请求 reason ∈ cancel 枚举且与 gold cancel reason 一致；
2. v5/v4 重建仍产出**缺陷形状**的请求文本（旧版本逐字节不变的负面锚点）；
3. v6 结构配额 = v5（单变量修复不改结构），`assert_exact_quotas_v6` 全部断言通过；
4. v6 任务集 Oracle 全解零违规（措辞变化不影响可解性）；
5. 版本互斥：v5 builder 拒绝 v6 版本名，反之亦然；v6 构建确定性。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from veritool_rl.core.agent.policy import OraclePolicy
from veritool_rl.core.agent.runner import run_episode
from veritool_rl.core.trajectory import TaskScenario
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
from veritool_rl.retail_ops.domain.formal_tasks import (
    _V4_CANCEL_REASONS,
    build_v4_task_set,
    build_v5_task_set,
    build_v6_task_set,
)

_V6_VERSION = "retail_ops_v6_20260907"
_V5_VERSION = "retail_ops_v5_20260906"
_V4_STEPWISE_VERSION = "retail_ops_v4_20260905"

#: 退款枚举（`_REASONS`）里不属于 cancel 枚举的值——v4/v5 缺陷形状的指纹。
_REFUND_ONLY_REASONS = {"damaged", "wrong_item", "not_as_described"}


@pytest.fixture(scope="module")
def v6_task_set():
    return build_v6_task_set(_V6_VERSION, 0)


def _stepwise_tasks(task_set, split: str | None = None) -> list:
    splits = ("train", "dev", "holdout") if split is None else (split,)
    return [
        record.task
        for split_name in splits
        for record in task_set.records(split_name)
        if record.task.scenario is TaskScenario.RTC_STEPWISE
    ]


def _stated_reason(request: str) -> str:
    assert "原因是 " in request, f"请求缺少 reason 从句: {request!r}"
    return request.split("原因是 ", 1)[1].rstrip("。")


def test_v6_stepwise_request_reason_is_in_cancel_enum_and_matches_gold(
    v6_task_set,
) -> None:
    tasks = _stepwise_tasks(v6_task_set)
    assert tasks, "v6 必须包含 rtc_stepwise 辅助任务"
    for task in tasks:
        stated = _stated_reason(task.user_request)
        assert stated in _V4_CANCEL_REASONS, f"请求 reason 不在 cancel 枚举域: {stated!r}"
        cancel_calls = [call for call in task.expected_calls if call.name == "cancel_order"]
        assert len(cancel_calls) == 1
        gold_reason = cancel_calls[0].arguments["reason"]
        assert stated == gold_reason, f"请求陈述的 reason {stated!r} 与 gold {gold_reason!r} 不一致"


def test_v6_stepwise_request_reason_is_the_gold_source_constant(v6_task_set) -> None:
    """交接 V6-2 的字面要求：与 gold 同源（`_V4_CANCEL_REASONS[0]`），不是轮转。"""
    reasons = {_stated_reason(task.user_request) for task in _stepwise_tasks(v6_task_set)}
    assert reasons == {_V4_CANCEL_REASONS[0]}


def test_v5_rebuild_keeps_the_defective_request_shape() -> None:
    """旧版本逐字节不变的负面锚点：v5 的 stepwise 请求仍是退款枚举 reason。

    v5 冻结集的内容指纹绑定这段文本；任何「顺手修好旧版本」的行为都会破坏
    版本↔内容双射。缺陷只在 v6 生效。
    """
    task_set = build_v5_task_set(_V5_VERSION, 0)
    tasks = _stepwise_tasks(task_set, "train")
    assert tasks
    defective = [
        task for task in tasks if _stated_reason(task.user_request) in _REFUND_ONLY_REASONS
    ]
    assert defective, "v5 重建必须保留缺陷形状（版本键控的负面锚点）"


def test_v4_stepwise_rebuild_is_untouched() -> None:
    """v4_20260905 的重建路径不受 v6 修复影响（独立 builder，版本键控）。"""
    task_set = build_v4_task_set(_V4_STEPWISE_VERSION, 0)
    tasks = [
        record.task
        for record in task_set.records("train")
        if record.task.scenario is TaskScenario.RTC_STEPWISE
    ]
    assert tasks
    reasons = {_stated_reason(task.user_request) for task in tasks}
    assert reasons & _REFUND_ONLY_REASONS


def test_v6_structure_quotas_match_v5(v6_task_set) -> None:
    """单变量修复：v6 的总量/类别/分层覆盖契约与 v5 完全相同。"""
    v6_task_set.assert_exact_quotas_v6()


def test_v6_tasks_are_oracle_solvable_with_zero_violations(v6_task_set) -> None:
    """措辞变化不影响可解性：1032 条任务 Oracle 全解零违规（与 v5 同强度验收）。"""
    bundle = load_bundle(Path("domains/retail_ops/v4"))
    solved = 0
    for split_name in ("train", "dev", "holdout"):
        for record in getattr(v6_task_set, split_name):
            task = record.task
            trajectory = run_episode(
                task,
                lambda current: RetailOpsEnv(current, bundle),
                OraclePolicy(task),
                0,
            )
            assert trajectory.success, (
                f"{split_name}/{task.scenario.value}/{task.task_id} Oracle 解不出"
            )
            assert trajectory.violations == [], (
                f"{task.task_id}: Oracle 轨迹违规 {trajectory.violations}"
            )
            solved += 1
    assert solved == 1032


def test_version_names_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="v5"):
        build_v5_task_set(_V6_VERSION, 0)
    with pytest.raises(ValueError, match="v6"):
        build_v6_task_set(_V5_VERSION, 0)


def test_v6_builder_is_deterministic(v6_task_set) -> None:
    rebuilt = build_v6_task_set(_V6_VERSION, 0)
    assert rebuilt == v6_task_set


# ---------------------------------------------------------------------------
# manifest 层：v6 冻结清单携带 v2 parser_id；v5 清单保持 v1
# ---------------------------------------------------------------------------


def test_v6_freeze_round_trip_binds_v2_parser_id(tmp_path: Path, v6_task_set) -> None:
    """v6 清单在写入侧即钉 hermes-single-call-v2-unterminated，且可完整回读。"""
    from veritool_rl.retail_ops.build.formal_manifests import (
        load_verified_formal_dataset,
        write_formal_task_set,
    )

    bundle = load_bundle(Path("domains/retail_ops/v4"))
    private_dir = tmp_path / "v6-private"
    public_dir = tmp_path / "v6-public"
    write_formal_task_set(v6_task_set, bundle, private_dir, public_dir)
    verified = load_verified_formal_dataset(public_dir)
    assert verified.receipt.dataset_version == _V6_VERSION
    assert verified.receipt.parser_id == "hermes-single-call-v2-unterminated"
    dev_manifest = load_verified_formal_dataset(public_dir).dev_manifest
    assert dev_manifest.parser_id == "hermes-single-call-v2-unterminated"


def test_v5_freeze_receipt_keeps_v1_parser_id(tmp_path: Path) -> None:
    """v5/v4/v1 清单的 parser_id 逐字节不变（V6-2b 不触碰冻结证据口径）。"""
    from veritool_rl.retail_ops.build.formal_manifests import (
        load_verified_formal_dataset,
        write_formal_task_set,
    )

    bundle = load_bundle(Path("domains/retail_ops/v4"))
    task_set = build_v5_task_set(_V5_VERSION, 0)
    private_dir = tmp_path / "v5-private"
    public_dir = tmp_path / "v5-public"
    write_formal_task_set(task_set, bundle, private_dir, public_dir)
    verified = load_verified_formal_dataset(public_dir)
    assert verified.receipt.dataset_version == _V5_VERSION
    assert verified.receipt.parser_id == "hermes-single-call-v1"
