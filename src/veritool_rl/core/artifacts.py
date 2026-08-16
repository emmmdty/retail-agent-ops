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


def _installed_distributions() -> Iterable[Any]:
    """**只扫这个解释器的 site-packages，不扫 `sys.path`。**

    `importlib.metadata.distributions()` 默认沿 `sys.path` 搜索，量的是"当前能
    import 到什么"——那会随 `PYTHONPATH`、cwd、以及任何在运行中改过 `sys.path` 的库
    而变。同一个 venv 因此可能在一次运行里算出两个不同的摘要，那样这个字段就不是
    环境身份而是噪声（2026-08-16 实测踩到过：同一 venv 的两次评测记下了不同的值）。

    改成按 `sysconfig` 给出的 purelib/platlib 扫描后，摘要只取决于"装了什么"。
    抽成函数还为了可注入——测试要能在不新建 venv 的前提下断言"换环境会变"。
    """
    import sysconfig
    from importlib.metadata import distributions

    paths = sysconfig.get_paths()
    roots = sorted({paths[key] for key in ("purelib", "platlib") if key in paths})
    return distributions(path=roots)


def current_runtime_env_sha256() -> str:
    """**实际装了什么包**的摘要。

    与 `uv_lock_sha256` 的区别是这次扩展的全部理由：后者哈希的是仓库里的 `uv.lock`
    **文件**，因此换一个 venv 跑评测它纹丝不动——不是会失配，是**发现不了**。
    2026-08-16 的三次 vLLM 评测正是跑在另一个环境（Python 3.12 + vLLM）里的。

    只取 (名字, 版本) 并排序去重：路径、安装顺序、解析器版本都不该影响摘要，
    否则同一个环境两次算出的值会不同，这个字段就没法用来判定"是不是同一个环境"。
    """
    seen = {
        (str(dist.metadata["Name"] or ""), str(dist.version))
        for dist in _installed_distributions()
    }
    return hashlib.sha256(canonical_json(sorted(seen)).encode("utf-8")).hexdigest()
