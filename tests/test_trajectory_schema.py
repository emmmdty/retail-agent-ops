"""轨迹 schema 的序列化与校验测试。"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError


def test_trajectory_jsonl_round_trip_is_canonical() -> None:
    from veritool_rl.core.trajectory import (
        Observation,
        RewardBreakdown,
        Step,
        TaskScenario,
        TaskSpec,
        TerminationReason,
        ToolCall,
        Trajectory,
    )

    task = TaskSpec(
        task_id="train-status-0000",
        split="train",
        scenario=TaskScenario.LOOKUP_STATUS,
        user_request="请查询订单 O-1。",
        initial_state={"orders": {"O-1": {"status": "shipped"}}},
        target_state={"orders": {"O-1": {"status": "shipped"}}},
        expected_calls=[ToolCall(name="get_order", arguments={"order_id": "O-1"})],
        max_steps=3,
    )
    trajectory = Trajectory(
        task=task,
        steps=[
            Step(
                index=0,
                assistant_raw='<tool_call>{"name":"get_order"}</tool_call>',
                tool_call=ToolCall(name="get_order", arguments={"order_id": "O-1"}),
                observation=Observation(ok=True, content={"status": "shipped"}),
                state_after=task.initial_state,
                reward=RewardBreakdown(final_state=1.0, milestone=1.0, total=1.0),
            )
        ],
        final_state=task.target_state,
        termination=TerminationReason.SUCCESS,
        success=True,
    )

    line = trajectory.to_jsonl()

    assert "\n" not in line
    assert line == trajectory.to_jsonl()
    assert json.loads(line)["schema_version"] == "1.0"
    assert Trajectory.from_jsonl(line) == trajectory


def test_trajectory_rejects_unknown_fields_and_non_finite_reward() -> None:
    from veritool_rl.core.trajectory import Observation, RewardBreakdown, ToolCall, Trajectory

    with pytest.raises(ValidationError):
        RewardBreakdown(final_state=float("nan"))

    with pytest.raises(ValidationError, match="JSON"):
        ToolCall(name="bad", arguments={"values": {1, 2}})

    with pytest.raises(ValidationError, match="JSON"):
        Observation(ok=True, content={"score": float("inf")})

    with pytest.raises(ValidationError):
        Trajectory.from_jsonl(
            '{"schema_version":"1.0","task":{},"final_state":{},'
            '"termination":"success","success":true,"unknown":1}'
        )


def test_trajectory_rejects_blank_jsonl_line() -> None:
    from veritool_rl.core.trajectory import Trajectory

    with pytest.raises(ValueError, match="空白"):
        Trajectory.from_jsonl("  \n")


def test_task_spec_jsonl_round_trip_is_canonical() -> None:
    from veritool_rl.core.trajectory import TaskSpec
    from veritool_rl.retail_ops.domain.tasks import build_qualification_tasks

    task = build_qualification_tasks(seed=0)[0]
    line = task.to_jsonl()

    assert "\n" not in line
    assert line == task.to_jsonl()
    assert TaskSpec.from_jsonl(line) == task


def test_task_spec_rejects_blank_jsonl_line() -> None:
    from veritool_rl.core.trajectory import TaskSpec

    with pytest.raises(ValueError, match="空白"):
        TaskSpec.from_jsonl("  \n")


def test_task_spec_supports_retail_ops_decisions_and_qualification_split() -> None:
    from veritool_rl.core.trajectory import ExpectedDecision, TaskScenario, TaskSpec

    task = TaskSpec(
        task_id="opaque-task",
        split="qualification",
        scenario=TaskScenario.REFUND_DENIED_WINDOW,
        user_request="请查询并处理订单。",
        initial_state={"orders": {}},
        target_state={"orders": {}},
        expected_decision=ExpectedDecision.DENY,
        required_reads=["order-1"],
    )

    assert task.expected_decision is ExpectedDecision.DENY
    assert task.required_reads == ["order-1"]


# ---------------------------------------------------------------------------
# F1 测试补齐（7.2 清单 §1.5）：validate_json_value 与 StrictModel
# ---------------------------------------------------------------------------


def test_validate_json_value_rejects_non_json_types_and_non_finite_floats() -> None:
    """递归验证器：拒绝非 JSON 类型、非字符串 key、NaN/Inf。"""
    from veritool_rl.core.trajectory.schema import validate_json_value

    # 通过时原样返回该值（不是 None）
    payload = {"a": [1, "x", None, True, {"b": 1.5}]}
    assert validate_json_value(payload) == payload

    with pytest.raises(ValueError):
        validate_json_value({1: "int-key"})
    with pytest.raises(ValueError):
        validate_json_value({("t", 1): "tuple-key"})
    with pytest.raises(ValueError):
        validate_json_value({"x": float("nan")})
    with pytest.raises(ValueError):
        validate_json_value({"x": float("inf")})
    with pytest.raises(ValueError):
        validate_json_value({"x": float("-inf")})
    with pytest.raises(ValueError):
        validate_json_value({"x": object()})


def test_strict_models_reject_unknown_fields_and_non_finite_values() -> None:
    """`StrictModel` 的 extra=forbid 与 allow_inf_nan=False 是全仓契约的基座。"""
    from typing import Any

    from pydantic import ValidationError

    from veritool_rl.core.trajectory.schema import StrictModel

    class _Probe(StrictModel):
        value: Any
        ratio: float

    with pytest.raises(ValidationError):
        _Probe.model_validate({"value": 1.0, "ratio": 0.5, "unknown": "field"})
    # allow_inf_nan=False 作用于 float 字段（Any 字段不校验数值性）
    with pytest.raises(ValidationError):
        _Probe.model_validate({"value": 1.0, "ratio": float("nan")})
    assert _Probe.model_validate({"value": 1.0, "ratio": 0.5}).ratio == 0.5
