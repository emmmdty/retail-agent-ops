"""统一轨迹数据结构。

    Trajectory = task + initial_state + messages + actions + observations
                 + rewards + final_state + violations

约束 (见 SPEC.md「方法」一节):
- 每条轨迹必须可重放;
- 每个奖励分量必须可追溯到环境状态或政策规则。

本文件仅定义数据结构与序列化签名, 序列化实现待补。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Step:
    """一轮交互: 消息 + (可选) 动作 + (可选) 观测 + (可选) 奖励。"""

    message: dict[str, Any]
    action: dict[str, Any] | None = None       # 工具调用: {"name": ..., "arguments": {...}}
    observation: dict[str, Any] | None = None  # execute_tool 返回的结构化观测
    reward: float | None = None


@dataclass
class Trajectory:
    """一条可重放的完整轨迹。"""

    task_id: str
    initial_state: dict[str, Any]
    steps: list[Step] = field(default_factory=list)
    final_state: dict[str, Any] | None = None
    violations: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_jsonl(self) -> str:
        """序列化为一行 JSON (占位, 待实现)。"""
        raise NotImplementedError

    @classmethod
    def from_jsonl(cls, line: str) -> Trajectory:
        """从一行 JSON 反序列化 (占位, 待实现)。"""
        raise NotImplementedError
