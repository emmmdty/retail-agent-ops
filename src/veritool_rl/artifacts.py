"""实验配置、JSON/JSONL 与摘要产物的统一写入工具。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml


def create_output_dir(path: Path) -> None:
    """创建不可覆盖的产物目录。"""
    try:
        path.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        msg = f"输出目录已存在，拒绝覆盖: {path}"
        raise FileExistsError(msg) from None


def canonical_json(value: Any) -> str:
    """返回稳定、可哈希的单行 JSON。"""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def write_json(path: Path, value: Any) -> None:
    """以稳定格式写 JSON 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Any]) -> None:
    """写入规范 JSONL；空集合产生空文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [canonical_json(row) for row in rows]
    content = "\n".join(lines) + ("\n" if lines else "")
    path.write_text(content, encoding="utf-8")


def write_yaml(path: Path, value: dict[str, Any]) -> None:
    """冻结解析后的运行配置。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=True),
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    """返回文件内容摘要。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()
