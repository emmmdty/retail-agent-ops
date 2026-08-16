"""跑一遍演示用的命令，把**真实输出**存成一份 transcript。

演示视频的渲染（`render_demo_video.py`）只读这份 transcript，**自己不执行任何命令、
也不编造任何输出**。分成两步的理由很直接：视频里出现的每一行都必须是真跑出来的，
而渲染过程不该有机会往里加东西。

每条命令的输出都会被截断到 `max_lines` 行——终端画面放不下几百行，
截断处会显式标注省略了多少行，而不是悄悄截掉。

用法（仓库根目录）：

    .venv/bin/python scripts/ops/capture_demo_transcript.py --output <path.json>

只跑只读或写临时目录的命令；不碰 GPU、不联网、不写 `reports/`。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_BIN = REPO_ROOT / ".venv" / "bin"


@dataclass(frozen=True)
class Step:
    """演示的一步：一句旁白 + 一条真命令 + 输出保留多少行。"""

    caption: str
    command: list[str]
    max_lines: int = 14
    tail: bool = False


STEPS: tuple[Step, ...] = (
    Step(
        caption="四个接口：build → evaluate → release → serve",
        command=[str(VENV_BIN / "retail-agent-ops"), "--help"],
        max_lines=16,
    ),
    Step(
        caption="一条命令跑完 CPU 全链路，并断言内容哈希等于冻结期望值",
        command=[str(VENV_BIN / "python"), "scripts/ci/verify_qualification_chain.py"],
        max_lines=6,
    ),
    Step(
        caption="发布门禁真的会拒绝：故意送一个坏候选进去",
        command=[str(VENV_BIN / "python"), "scripts/ops/demo_release_gate.py"],
        max_lines=20,
    ),
    Step(
        caption="真实运行证据：一个 GO，和把它打掉一半的那组数",
        command=[
            str(VENV_BIN / "python"),
            "scripts/ops/demo_evidence_summary.py",
            "--section",
            "gate",
        ],
        max_lines=18,
    ),
    Step(
        caption="然后把它修好了——以及这次修复的账单",
        command=[
            str(VENV_BIN / "python"),
            "scripts/ops/demo_evidence_summary.py",
            "--section",
            "fix",
        ],
        max_lines=18,
    ),
    Step(
        caption="公开发布审计：LICENSE / 凭据 / 权重 / holdout 真值 / 绝对路径",
        command=[str(VENV_BIN / "python"), "scripts/ci/audit_public_release.py"],
        max_lines=4,
    ),
    Step(
        caption="质量门：测试、lint、格式、类型、依赖锁",
        command=[str(VENV_BIN / "pytest"), "-q", "--tb=no"],
        max_lines=4,
        tail=True,
    ),
    Step(
        caption="类型检查覆盖全部源文件",
        command=[str(VENV_BIN / "mypy")],
        max_lines=3,
        tail=True,
    ),
)


def _clip(text: str, max_lines: int, tail: bool) -> list[str]:
    # 保留**段落之间**的空行（它承载分节），只去掉首尾的空行。
    raw = [line.rstrip() for line in text.splitlines()]
    while raw and not raw[0]:
        raw.pop(0)
    while raw and not raw[-1]:
        raw.pop()
    lines = raw
    if len(lines) <= max_lines:
        return lines
    hidden = len(lines) - max_lines
    if tail:
        return [f"… （前 {hidden} 行省略）", *lines[-max_lines:]]
    return [*lines[:max_lines], f"… （另有 {hidden} 行省略）"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    captured: list[dict[str, object]] = []
    for step in STEPS:
        started = time.monotonic()
        completed = subprocess.run(
            step.command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )
        elapsed = time.monotonic() - started
        merged = completed.stdout + completed.stderr
        captured.append(
            {
                "caption": step.caption,
                "command": " ".join(
                    part.replace(str(REPO_ROOT) + "/", "") for part in step.command
                ),
                "exit_code": completed.returncode,
                "seconds": round(elapsed, 1),
                "lines": _clip(merged, step.max_lines, step.tail),
            }
        )
        print(f"[{completed.returncode}] {step.caption} （{elapsed:.1f}s）", flush=True)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(captured, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    failed = [item for item in captured if item["exit_code"] != 0]
    if failed:
        print(f"\n注意：{len(failed)} 步退出码非 0，transcript 里如实记录了。")
    print(f"\n写入 {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
