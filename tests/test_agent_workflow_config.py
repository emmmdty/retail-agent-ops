from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

def _stop_hook_entries(settings: dict[str, Any]) -> list[Any]:
    return list(settings.get("hooks", {}).get("Stop", []))

def test_project_settings_declare_no_stop_hook() -> None:
    """记录协议由 CLAUDE.md 第 7 节承载，不由 Stop hook 强制。

    原先的 prompt hook（LLM 裁判）在 2026-08-12 被删除：它把纯状态汇报误判为
    "material event"，且在复述已记录事件时反复触发。若要重新引入自动检查，
    应先更新本测试，使这个选择保持显式。
    """
    settings_path = REPO_ROOT / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))

    assert _stop_hook_entries(settings) == []
