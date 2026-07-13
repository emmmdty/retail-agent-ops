"""评测指标 (占位)。

见 SPEC.md「评测指标」: 主结论必须由执行结果、数据库状态与 policy verifier
支撑, LLM-as-a-judge 仅作补充。
"""
from __future__ import annotations

from veritool_rl.trajectory.schema import Trajectory


def ast_accuracy(trajs: list[Trajectory]) -> float:
    """BFCL AST / 可执行调用准确率 (占位)。"""
    raise NotImplementedError


def final_state_success(trajs: list[Trajectory]) -> float:
    """最终状态任务成功率 / resolution rate (占位)。"""
    raise NotImplementedError


def invalid_call_rate(trajs: list[Trajectory]) -> float:
    """无效工具调用率 (占位)。"""
    raise NotImplementedError


def recovery_success_rate(trajs: list[Trajectory]) -> float:
    """工具报错后的恢复成功率 (占位)。"""
    raise NotImplementedError
