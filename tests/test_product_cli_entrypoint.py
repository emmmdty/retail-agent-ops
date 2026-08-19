"""`python -m veritool_rl.product_cli` 必须真的是一个入口。

在 2026-08-19 之前它不是：模块没有 `__main__` 守卫，于是这条命令**静默退出 0**，
既不报错也不做事。文档里的调用方式一直是 console script `.venv/bin/retail-agent-ops`，
所以这不是行为回归；但"能跑、不报错、什么都没发生"是最难被发现的一类失败，
而按直觉试 `python -m` 的人（包括写这行字的这次会话）会直接被它误导。
"""

from __future__ import annotations

import subprocess
import sys

MODULE = "veritool_rl.product_cli"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", MODULE, *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def test_module_execution_prints_usage_instead_of_exiting_silently() -> None:
    """不带参数时必须报"缺子命令"并非零退出，而不是安静地成功。"""
    completed = _run()

    assert completed.returncode != 0, (
        f"`python -m {MODULE}` 无参数时退出 0——这正是那个静默空跑的形态："
        f"stdout={completed.stdout!r} stderr={completed.stderr!r}"
    )
    assert "usage" in (completed.stdout + completed.stderr).lower()


def test_module_execution_exposes_the_four_stable_interfaces() -> None:
    """`--help` 必须列出四个稳定接口，否则这个入口只是能退出而已。"""
    completed = _run("--help")

    assert completed.returncode == 0, completed.stderr
    for interface in ("build", "evaluate", "release", "serve"):
        assert interface in completed.stdout, f"--help 没有列出 {interface}"


def test_an_unknown_subcommand_fails_loudly() -> None:
    completed = _run("definitely-not-a-command")

    assert completed.returncode != 0
    assert "invalid choice" in (completed.stdout + completed.stderr).lower()
