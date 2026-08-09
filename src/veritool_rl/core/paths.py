"""项目配置路径的共享校验。"""

from __future__ import annotations

from pathlib import Path


def validate_project_relative_path(value: str | Path, field: str) -> None:
    """拒绝绝对路径和离开项目目录的词法路径。"""
    raw = str(value)
    path = Path(value)
    if not raw.strip() or path.is_absolute() or ".." in path.parts:
        msg = f"{field} 必须是项目相对路径: {value}"
        raise ValueError(msg)
