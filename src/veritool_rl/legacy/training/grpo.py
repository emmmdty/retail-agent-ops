"""可选 verifier-guided GRPO (占位)。

仅在算力与稳定性 go/no-go 通过后启用 (见 SPEC.md「算力与降级线」):
48 小时内完成可重复 smoke run, reward 非退化、无持续 OOM/NaN 且优于 SFT。
未通过则降级为 rejection sampling + 离线偏好优化。
在线 RL 只使用确定性 final-state/policy reward, 不用通用 LLM judge 作核心奖励。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def run_grpo(config: dict[str, Any], seed: int, output_dir: Path) -> None:
    """执行 verifier-guided GRPO 训练 (占位)。"""
    raise NotImplementedError
