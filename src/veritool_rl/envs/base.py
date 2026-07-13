"""工具环境抽象接口。

统一封装 BFCL / ToolSandbox / tau2 等评测环境, 向 Agent 暴露一致的接口。
所有方法均为占位, 核心逻辑待按 SPEC.md「必须实现的工具」一节实现。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolSchema:
    """工具的 JSON schema 描述。"""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class Observation:
    """执行工具后的结构化观测。"""

    ok: bool
    content: Any
    error: str | None = None


class ToolEnv(ABC):
    """有状态工具环境的统一适配器接口。

    实现类负责把某个具体基准 (BFCL / ToolSandbox / tau2) 适配到该接口,
    使训练与评测代码与具体环境解耦。
    """

    @abstractmethod
    def list_tools(self) -> list[ToolSchema]:
        """返回当前可用工具及其 JSON schema。"""
        raise NotImplementedError

    @abstractmethod
    def execute_tool(self, name: str, arguments: dict[str, Any]) -> Observation:
        """执行工具并返回结构化 observation。"""
        raise NotImplementedError

    @abstractmethod
    def get_state(self) -> dict[str, Any]:
        """返回当前环境可见状态 (用于回放与 verifier)。"""
        raise NotImplementedError

    @abstractmethod
    def verify_milestone(self) -> float:
        """计算中间里程碑得分。"""
        raise NotImplementedError

    @abstractmethod
    def verify_final_state(self) -> float:
        """根据目标状态计算确定性成功奖励。"""
        raise NotImplementedError

    @abstractmethod
    def check_policy(self) -> list[str]:
        """识别越权、顺序错误与 minefield, 返回违规项列表 (空表示合规)。"""
        raise NotImplementedError

    @abstractmethod
    def perturb_schema(self, seed: int) -> None:
        """对工具名称/描述/参数顺序/无关工具做扰动 (用于 H4 鲁棒性实验)。"""
        raise NotImplementedError
