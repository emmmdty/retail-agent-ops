"""轨迹数据结构 smoke 测试 (仅校验结构, 不触及未实现逻辑)。"""
from __future__ import annotations

from veritool_rl.trajectory import Step, Trajectory


def test_trajectory_construction() -> None:
    traj = Trajectory(
        task_id="demo-0",
        initial_state={"cart": []},
        steps=[Step(message={"role": "user", "content": "退款"})],
    )
    assert traj.task_id == "demo-0"
    assert traj.steps[0].action is None
    assert traj.violations == []
