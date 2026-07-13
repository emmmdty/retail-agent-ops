"""评测编排器 (占位)。

对固定 backbone、prompt 预算、采样参数、硬件与超时下的任务集合运行评测,
支持多次运行 + bootstrap 置信区间 (见 SPEC.md「非 Toy 验收门」第 6 条)。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from veritool_rl.envs.base import ToolEnv


class Evaluator:
    """在给定环境与任务集合上评测某个 policy。"""

    def __init__(self, env: ToolEnv, config: dict[str, Any]) -> None:
        self.env = env
        self.config = config

    def run(self, seed: int, output_dir: Path) -> dict[str, Any]:
        """运行评测并写出分层报告 (占位)。"""
        raise NotImplementedError
