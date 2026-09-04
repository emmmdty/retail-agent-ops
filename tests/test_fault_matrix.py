"""`docs/FAULT_MATRIX.md` 与实际测试的绑定。

故障矩阵的失效方式不是"写错了"，而是"越写越好看、实际覆盖不动"——重命名一个测试、
删掉一个测试，文档还是那张漂亮的表。这份测试解析文档里的每一个 `文件::测试名`
引用，逐个断言它真实存在且会被 pytest 收集到。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = REPO_ROOT / "docs" / "FAULT_MATRIX.md"

#: 匹配 `tests/xxx.py::test_yyy` 形态的引用（文档里包在反引号里）。
REFERENCE_PATTERN = re.compile(r"`(tests/[A-Za-z0-9_./]+\.py)::([A-Za-z0-9_]+)`")

#: R5 与 SPEC §9 要求覆盖的五类故障。少一个小节就说明矩阵被删剩了。
REQUIRED_SECTIONS = (
    "外部 API 超时",
    "幂等",
    "策略冲突",
    "资源限制",
    "回滚故障",
)


def _matrix_text() -> str:
    return MATRIX_PATH.read_text(encoding="utf-8")


def _test_functions(path: Path) -> set[str]:
    """解析文件的 AST，取顶层测试函数名。比 grep 可靠：注释掉的定义不算数。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test")
    }


def test_the_fault_matrix_exists_and_covers_every_required_class() -> None:
    text = _matrix_text()
    missing = [section for section in REQUIRED_SECTIONS if section not in text]
    assert not missing, f"故障矩阵缺少这些必需的故障类：{missing}"


def test_every_fault_class_names_a_real_test() -> None:
    text = _matrix_text()
    # 7.2 审查指出 ">= 20" 不绑定任何设计约束：阈值改为**结构绑定**——
    # 每个必需的故障类小节必须至少引用 1 个真实测试，而不是任意全局数字。
    for section in REQUIRED_SECTIONS:
        match = re.search(rf"^#+\s*.*{re.escape(section)}.*$", text, re.MULTILINE)
        assert match is not None, f"故障矩阵缺少小节：{section}"
        start = match.end()
        next_heading = re.search(r"^#+\s", text[start:], re.MULTILINE)
        body = text[start : start + (next_heading.start() if next_heading else len(text[start:]))]
        references = REFERENCE_PATTERN.findall(body)
        assert references, f"故障类「{section}」没有引用任何真实测试"

    references = REFERENCE_PATTERN.findall(text)
    assert len(references) >= len(REQUIRED_SECTIONS), (
        f"故障矩阵只引用了 {len(references)} 个测试，少于故障类数 {len(REQUIRED_SECTIONS)}"
    )

    broken: list[str] = []
    for relpath, test_name in references:
        path = REPO_ROOT / relpath
        if not path.is_file():
            broken.append(f"{relpath}（文件不存在）")
            continue
        if test_name not in _test_functions(path):
            broken.append(f"{relpath}::{test_name}（测试不存在）")

    assert not broken, f"故障矩阵引用了不存在的测试：{broken}"


def test_the_matrix_states_what_was_not_done() -> None:
    """一张只写"都覆盖了"的矩阵是营销材料。没做的必须同样列出来。"""
    text = _matrix_text()
    assert "明确没有做的" in text
    for absent in ("混沌", "压测"):
        assert absent in text, f"未声明的缺口：{absent}"


def test_no_chaos_engineering_claim() -> None:
    """进程内故障注入不是混沌工程，文档不得这样表述。"""
    text = _matrix_text()
    assert "经过混沌工程验证" not in text.replace("不得表述为“经过混沌工程验证”", "").replace(
        '不得表述为"经过混沌工程验证"', ""
    )
