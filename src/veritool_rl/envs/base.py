"""确定性工具环境的公共接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import Field, field_validator

from veritool_rl.trajectory.schema import (
    Observation,
    StrictModel,
    TaskSpec,
    validate_json_value,
)


class ToolSchema(StrictModel):
    """工具的 JSON schema 描述。"""

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    parameters: dict[str, Any]

    _validate_parameters = field_validator("parameters")(validate_json_value)

    def to_transformers(self) -> dict[str, Any]:
        """转换为 Transformers chat template 接受的函数格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolEnv(ABC):
    """单个冻结任务对应的有状态确定性环境。"""

    @property
    @abstractmethod
    def task(self) -> TaskSpec:
        """返回创建该环境的任务规格。"""
        raise NotImplementedError

    @abstractmethod
    def list_tools(self) -> list[ToolSchema]:
        """返回当前向 policy 展示的工具 schema。"""
        raise NotImplementedError

    @abstractmethod
    def execute_tool(self, name: str, arguments: dict[str, Any]) -> Observation:
        """执行一次工具调用；模型错误应返回 observation 而不是抛异常。"""
        raise NotImplementedError

    @abstractmethod
    def get_state(self) -> dict[str, Any]:
        """返回当前状态的深拷贝。"""
        raise NotImplementedError

    @abstractmethod
    def verify_milestone(self) -> float:
        """返回已完成预期调用的比例。"""
        raise NotImplementedError

    @abstractmethod
    def verify_final_state(self) -> float:
        """返回确定性最终成功分数 0 或 1。"""
        raise NotImplementedError

    @abstractmethod
    def check_policy(self) -> list[str]:
        """返回按首次出现顺序去重的违规代码。"""
        raise NotImplementedError

    @abstractmethod
    def perturb_schema(self, seed: int) -> None:
        """确定性施加改名、描述、参数顺序和 distractor 扰动。"""
        raise NotImplementedError
