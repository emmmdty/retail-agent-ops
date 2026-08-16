"""演示视频的契约。

`SPEC.md` §11 的 12 周交付清单里有「演示视频」。它此前一直是「未做」——
现在做了，就必须挡住它退化成一段与仓库脱节的营销素材：

* 视频文件必须真的存在且能被 ffprobe 读出时长；
* 渲染脚本**不得**执行任何命令或自造输出——它只读 transcript；
* 演示里跑的每条命令都必须是仓库里真实存在的入口。
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VIDEO = REPO_ROOT / "docs" / "media" / "demo.mp4"
CAPTURE = REPO_ROOT / "scripts" / "ops" / "capture_demo_transcript.py"
RENDER = REPO_ROOT / "scripts" / "ops" / "render_demo_video.py"


def test_the_video_exists_and_is_playable() -> None:
    assert VIDEO.is_file(), "docs/media/demo.mp4 不存在"
    assert VIDEO.stat().st_size > 50_000, "视频过小，多半渲染失败了"
    if shutil.which("ffprobe") is None:
        pytest.skip("本机没有 ffprobe")
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(VIDEO),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    duration = float(completed.stdout.strip())
    assert 30.0 < duration < 300.0, f"演示时长 {duration:.1f}s 不在合理区间"


def test_the_renderer_never_executes_commands() -> None:
    """渲染脚本一旦能执行命令，视频里就可能出现没真跑过的输出。

    唯一允许的子进程是 ffmpeg（把帧编码成视频），由下面的白名单断言。
    """
    tree = ast.parse(RENDER.read_text(encoding="utf-8"))
    forbidden = {"os.system", "os.popen", "eval", "exec"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            assert name not in forbidden, f"渲染脚本调用了 {name}"
    source = RENDER.read_text(encoding="utf-8")
    assert source.count("subprocess.run") == 1, "渲染脚本只应调用一次 subprocess（ffmpeg）"
    assert '"ffmpeg"' in source


def test_every_demo_command_points_at_a_real_entrypoint() -> None:
    """演示里跑的每个脚本都必须在仓库里存在——否则视频演的是不存在的东西。"""
    source = CAPTURE.read_text(encoding="utf-8")
    referenced = set(re.findall(r'"(scripts/[A-Za-z0-9_./-]+\.py)"', source))
    assert referenced, "没有解析到任何被演示的脚本路径"
    for relpath in referenced:
        assert (REPO_ROOT / relpath).is_file(), f"演示引用了不存在的脚本 {relpath}"


def test_the_demo_scripts_are_read_only_about_evidence() -> None:
    """证据摘要脚本只读已落盘的 JSON，不得自己算指标。"""
    source = (REPO_ROOT / "scripts/ops/demo_evidence_summary.py").read_text(encoding="utf-8")
    assert "json.loads" in source
    for forbidden in ("subprocess", "evaluate_", "compute_metrics"):
        assert forbidden not in source, f"证据摘要脚本不该出现 {forbidden}"


def test_docs_point_at_the_video() -> None:
    for name in ("README.md", "docs/DEMO.md"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        assert "docs/media/demo.mp4" in text or "media/demo.mp4" in text, name


def test_the_transcript_schema_is_what_the_renderer_expects() -> None:
    """两个脚本靠一份 JSON 契约连接，字段对不上时视频会静默少内容。"""
    capture = CAPTURE.read_text(encoding="utf-8")
    render = RENDER.read_text(encoding="utf-8")
    for field in ("caption", "command", "exit_code", "seconds", "lines"):
        assert f'"{field}"' in capture, field
        # 渲染侧既有 step["x"] 也有 f-string 里的 step['x']，两种引号都算
        assert f'"{field}"' in render or f"'{field}'" in render, field
