"""脚本通用 CLI 工具。

统一约定 (见 AGENTS.md): 所有训练/评测/汇总/绘图脚本必须支持
``--config`` / ``--seed`` / ``--output_dir``。
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, cast


def build_arg_parser(description: str) -> argparse.ArgumentParser:
    """构造带统一必备参数的 ArgumentParser。"""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--config", type=Path, required=True, help="YAML 配置文件路径")
    parser.add_argument("--seed", type=int, default=0, help="随机种子")
    parser.add_argument(
        "--output_dir",
        type=Path,
        required=True,
        help="产物输出目录 (写入 reports/ 分层结构)",
    )
    return parser


def load_config(path: Path) -> dict[str, Any]:
    """加载 YAML，并校验顶层为字符串 key 的 mapping。"""
    import yaml

    with open(path, encoding="utf-8") as f:
        loaded = yaml.safe_load(f)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        msg = f"配置文件必须是 YAML mapping: {path}"
        raise ValueError(msg)
    if not all(isinstance(key, str) for key in loaded):
        msg = f"配置文件顶层 key 必须是字符串: {path}"
        raise ValueError(msg)
    return cast(dict[str, Any], loaded)
