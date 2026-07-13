"""轨迹数据生成器 (占位)。

数据设计 (见 SPEC.md「数据设计」「训练数据」):
- 成功轨迹: 基准参考轨迹 + 规则规划器 + 验证通过的本地模型 rollout;
- 失败轨迹: 错误工具、错误参数、遗漏信息、policy violation、冗余循环、错误恢复;
- schema 扰动: 训练时随机改名/改写描述/打乱参数/插入 distractor (H4)。
"""
from __future__ import annotations

from veritool_rl.envs.base import ToolEnv
from veritool_rl.trajectory.schema import Trajectory


def build_success_trajectories(env: ToolEnv, seed: int) -> list[Trajectory]:
    """生成成功轨迹 (占位)。"""
    raise NotImplementedError


def build_failure_trajectories(env: ToolEnv, seed: int) -> list[Trajectory]:
    """生成带类型标注的失败轨迹, 用于偏好优化 (占位)。"""
    raise NotImplementedError


def perturb_schema(trajectory: Trajectory, seed: int) -> Trajectory:
    """对轨迹中的工具 schema 施加扰动 (占位)。"""
    raise NotImplementedError
