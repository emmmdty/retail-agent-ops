"""把 `capture_demo_transcript.py` 抓到的真实输出渲染成一段终端风格的 MP4。

**这个脚本不执行任何命令，也不生成任何输出文本**——它只读 transcript。
视频里出现的每一行都来自真实运行，渲染阶段没有机会往里加东西。

实现上刻意只渲染**不同的帧**，再用 ffmpeg 的 concat demuxer 给每帧一个持续时间：
终端演示里绝大多数帧是静止的，逐帧写 PNG 既慢又没必要。

依赖：Pillow（**装在独立 venv**，项目 `uv.lock` 一个字节不动，与 vLLM 那次同一个做法）
与 ffmpeg。中文字体用系统的 WenQuanYi Zen Hei Mono——它对中英文都是等宽的，
换成非等宽字体会让终端画面错位。

用法：

    <demo-venv>/bin/python scripts/ops/render_demo_video.py \\
        --transcript <path.json> --output docs/media/demo.mp4
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1280, 720
FPS = 25

#: 终端配色。深蓝黑底 + 冷灰字，强调色只有两个：命令的青、失败的红。
#: 刻意不用彩虹配色——这是一段工程演示，颜色应该只用来分区分意义。
BG = (16, 20, 28)
FG = (206, 214, 224)
DIM = (122, 134, 150)
CMD = (110, 200, 220)
OK = (126, 200, 150)
BAD = (224, 118, 106)
ACCENT = (232, 178, 92)

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)

MARGIN = 44
LINE_HEIGHT = 26
FONT_SIZE = 17
TITLE_SIZE = 34


@dataclass
class Frame:
    image: Image.Image
    seconds: float


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    raise SystemExit(f"找不到中文等宽字体，试过：{FONT_CANDIDATES}")


def _canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    # 顶栏：三个圆点 + 标题，让画面一眼是"终端"而不是"PPT"
    draw.rectangle([0, 0, WIDTH, 36], fill=(24, 29, 39))
    for index, color in enumerate(((224, 118, 106), (232, 178, 92), (126, 200, 150))):
        draw.ellipse([18 + index * 20, 13, 28 + index * 20, 23], fill=color)
    return image, draw


#: 语义配色的关键词。红色只留给「这里出问题了」，绿色只留给「这里通过了」——
#: 项目最该被看见的一行是 expression_ood 那个 0.00，它必须是红的。
_BAD_MARKERS = ("FAIL", "NO-GO", "全灭", "比不训练还差", "不是泛化")
_OK_MARKERS = ("PASS", "通过", "passed", "Success", "GO / candidate")


def _line_color(text: str) -> tuple[int, int, int]:
    if any(marker in text for marker in _BAD_MARKERS):
        return BAD
    if any(marker in text for marker in _OK_MARKERS):
        return OK
    if text.startswith("…"):
        return DIM
    return FG


def _title_frame(
    font_title: ImageFont.FreeTypeFont,
    font: ImageFont.FreeTypeFont,
    title: str,
    subtitle: list[str],
    seconds: float,
) -> Frame:
    image, draw = _canvas()
    draw.text((MARGIN, 210), title, font=font_title, fill=FG)
    for index, line in enumerate(subtitle):
        draw.text((MARGIN, 290 + index * 32), line, font=font, fill=DIM)
    return Frame(image, seconds)


def _shell_frame(
    font: ImageFont.FreeTypeFont,
    caption: str,
    command: str,
    typed: int,
    lines: list[str],
    footer: str | None,
    seconds: float,
) -> Frame:
    image, draw = _canvas()
    draw.text((MARGIN, 58), caption, font=font, fill=ACCENT)
    prompt = "$ "
    draw.text((MARGIN, 100), prompt, font=font, fill=OK)
    prompt_width = draw.textlength(prompt, font=font)
    draw.text((MARGIN + prompt_width, 100), command[:typed], font=font, fill=CMD)
    if typed < len(command):
        cursor_x = MARGIN + prompt_width + draw.textlength(command[:typed], font=font)
        draw.rectangle([cursor_x, 100, cursor_x + 9, 100 + 20], fill=DIM)
    for index, line in enumerate(lines):
        y = 140 + index * LINE_HEIGHT
        if y > HEIGHT - 80:
            break
        draw.text((MARGIN, y), line, font=font, fill=_line_color(line))
    if footer:
        draw.text((MARGIN, HEIGHT - 46), footer, font=font, fill=DIM)
    return Frame(image, seconds)


def build_frames(
    transcript: list[dict], font: ImageFont.FreeTypeFont, font_title: ImageFont.FreeTypeFont
) -> list[Frame]:
    frames: list[Frame] = [
        _title_frame(
            font_title,
            font,
            "RetailAgentOps",
            [
                "零售工具 Agent 的单卡领域适配与发布流水线",
                "",
                "以下每一行输出都是真跑出来的，渲染脚本不执行命令、也不编造输出。",
            ],
            5.0,
        )
    ]
    for step in transcript:
        command: str = step["command"]
        caption: str = step["caption"]
        lines: list[str] = step["lines"]
        # 打字动画：每 2 个字符一帧，够快也看得出是在敲命令
        for typed in range(0, len(command) + 1, 2):
            frames.append(_shell_frame(font, caption, command, typed, [], None, 0.055))
        frames.append(_shell_frame(font, caption, command, len(command), [], None, 0.7))
        for count in range(1, len(lines) + 1):
            frames.append(
                _shell_frame(font, caption, command, len(command), lines[:count], None, 0.13)
            )
        footer = f"退出码 {step['exit_code']} ｜ 耗时 {step['seconds']}s"
        # 中文读起来比英文慢，收尾停顿按行数给，短输出也至少停 4 秒
        hold = max(4.0, 0.55 * len(lines))
        frames.append(_shell_frame(font, caption, command, len(command), lines, footer, hold))
    frames.append(
        _title_frame(
            font_title,
            font,
            "边界",
            [
                "封存 holdout 只观测过四次，每次都对应一次正式发布判定。",
                "拿到 GO 的候选在分布外集合上只有 0.5833，表达变化一类 0/20。",
                "120/120 不是泛化——这一条是项目自己测出来并写进门禁文档的。",
            ],
            7.0,
        )
    )
    return frames


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if shutil.which("ffmpeg") is None:
        raise SystemExit("需要 ffmpeg")

    transcript = json.loads(args.transcript.read_text(encoding="utf-8"))
    font = _font(FONT_SIZE)
    font_title = _font(TITLE_SIZE)
    frames = build_frames(transcript, font, font_title)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        entries: list[str] = []
        for index, frame in enumerate(frames):
            path = root / f"f{index:05d}.png"
            frame.image.save(path)
            entries.append(f"file '{path}'\nduration {frame.seconds:.3f}")
        # concat demuxer 要求最后一帧重复一次，否则它的 duration 会被丢掉
        entries.append(f"file '{root / f'f{len(frames) - 1:05d}.png'}'")
        listing = root / "frames.txt"
        listing.write_text("\n".join(entries) + "\n", encoding="utf-8")

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listing),
                "-vf",
                f"fps={FPS},format=yuv420p",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "20",
                "-movflags",
                "+faststart",
                str(args.output),
            ],
            check=True,
            capture_output=True,
            timeout=1800,
        )

    total = sum(frame.seconds for frame in frames)
    size_mb = args.output.stat().st_size / 1e6
    print(f"写入 {args.output}｜{len(frames)} 帧｜时长约 {total:.1f}s｜{size_mb:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
