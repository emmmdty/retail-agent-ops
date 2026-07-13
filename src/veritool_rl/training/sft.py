"""课程式监督微调 (占位)。

H1: 渐进难度 single-call -> stateful multi-step -> multi-turn,
先学格式与局部动作, 再学多步完整轨迹。首选 Qwen3 1.7B/4B + LoRA/QLoRA。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def run_sft(config: dict[str, Any], seed: int, output_dir: Path) -> None:
    """执行课程式 SFT 训练 (占位)。"""
    raise NotImplementedError
