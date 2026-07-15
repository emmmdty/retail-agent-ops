"""可版本化、可重放的严格轨迹数据结构。"""

from __future__ import annotations

import json
import math
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    """禁止未知字段和非有限浮点数的公共模型基类。"""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


def validate_json_value(value: Any) -> Any:
    """递归拒绝非 JSON 类型、非字符串 object key 和非有限浮点数。"""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if math.isfinite(value):
            return value
        msg = "字段必须是有限 JSON number"
        raise ValueError(msg)
    if isinstance(value, list):
        for item in value:
            validate_json_value(item)
        return value
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            msg = "JSON object 的 key 必须是字符串"
            raise ValueError(msg)
        for item in value.values():
            validate_json_value(item)
        return value
    msg = f"字段必须是 JSON value，收到 {type(value).__name__}"
    raise ValueError(msg)


class TaskScenario(StrEnum):
    """MiniRetail MVP 覆盖的任务场景。"""

    LOOKUP_STATUS = "lookup_status"
    REFUND_ELIGIBLE = "refund_eligible"
    REFUND_DENIED = "refund_denied"
    REFUND_RECOVERY = "refund_recovery"


class TerminationReason(StrEnum):
    """Agent episode 的终止原因。"""

    SUCCESS = "success"
    FINAL_RESPONSE = "final_response"
    STEP_LIMIT = "step_limit"
    POLICY_VIOLATION = "policy_violation"
    INTERNAL_ERROR = "internal_error"


class ToolCall(StrictModel):
    """一次结构化工具调用。"""

    name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    call_id: str | None = None

    _validate_arguments = field_validator("arguments")(validate_json_value)


class Observation(StrictModel):
    """执行工具后的结构化观测。"""

    ok: bool
    content: Any = None
    error_code: str | None = None
    error: str | None = None

    _validate_content = field_validator("content")(validate_json_value)


class RewardBreakdown(StrictModel):
    """所有分量均可追溯到环境状态或确定性规则。"""

    final_state: float = Field(default=0.0, ge=0.0, le=1.0)
    milestone: float = Field(default=0.0, ge=0.0, le=1.0)
    policy_penalty: float = Field(default=0.0, le=0.0)
    invalid_call: float = Field(default=0.0, le=0.0)
    total: float = 0.0


class TaskSpec(StrictModel):
    """创建新环境实例所需的全部冻结任务输入。"""

    task_id: str = Field(min_length=1)
    split: Literal["train", "dev", "test"]
    scenario: TaskScenario
    user_request: str = Field(min_length=1)
    initial_state: dict[str, Any]
    target_state: dict[str, Any]
    expected_calls: list[ToolCall] = Field(default_factory=list)
    transient_failures: dict[str, int] = Field(default_factory=dict)
    max_steps: int = Field(default=4, ge=1, le=32)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _validate_json_fields = field_validator(
        "initial_state", "target_state", "metadata"
    )(validate_json_value)

    @field_validator("transient_failures")
    @classmethod
    def validate_failure_counts(cls, value: dict[str, int]) -> dict[str, int]:
        """故障注入次数必须为正数。"""
        if any(count < 1 for count in value.values()):
            msg = "transient_failures 的次数必须大于 0"
            raise ValueError(msg)
        return value


class Step(StrictModel):
    """一个 assistant turn 及其可选工具执行结果。"""

    index: int = Field(ge=0)
    assistant_raw: str
    tool_call: ToolCall | None = None
    final_response: str | None = None
    parse_error: str | None = None
    observation: Observation | None = None
    state_after: dict[str, Any]
    reward: RewardBreakdown
    violations: list[str] = Field(default_factory=list)
    latency_ms: float = Field(default=0.0, ge=0.0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)

    _validate_state = field_validator("state_after")(validate_json_value)


class Trajectory(StrictModel):
    """一条自包含、可精确重放的完整轨迹。"""

    schema_version: Literal["1.0"] = "1.0"
    task: TaskSpec
    steps: list[Step] = Field(default_factory=list)
    final_state: dict[str, Any]
    violations: list[str] = Field(default_factory=list)
    termination: TerminationReason
    success: bool
    metadata: dict[str, Any] = Field(default_factory=dict)

    _validate_json_fields = field_validator("final_state", "metadata")(validate_json_value)

    def to_jsonl(self) -> str:
        """返回不含换行的规范 JSON。"""
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @classmethod
    def from_jsonl(cls, line: str) -> Self:
        """从单行 JSON 解析并执行严格校验。"""
        if not line.strip():
            msg = "轨迹 JSONL 行不能为空白"
            raise ValueError(msg)
        return cls.model_validate_json(line)
