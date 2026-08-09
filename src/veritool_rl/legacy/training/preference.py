"""失败轨迹偏好优化 (占位)。

H2: 用「最终状态正确、无违规、调用更短」构造偏好对, 做 DPO/SimPO,
以降低 invalid call、policy violation 与重复循环。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def run_preference(config: dict[str, Any], seed: int, output_dir: Path) -> None:
    """执行 DPO/SimPO 偏好优化 (占位)。"""
    raise NotImplementedError
