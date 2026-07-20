from __future__ import annotations

import json
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_codex_uses_claude_md_as_project_instruction_fallback() -> None:
    config_path = REPO_ROOT / ".codex" / "config.toml"
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))

    assert config["project_doc_fallback_filenames"] == ["CLAUDE.md"]
    assert config["project_doc_max_bytes"] >= 32_768


def test_claude_stop_hook_checks_project_log_disposition() -> None:
    settings_path = REPO_ROOT / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    stop_hooks = settings["hooks"]["Stop"]

    assert len(stop_hooks) == 1
    hook = stop_hooks[0]["hooks"][0]
    assert hook["type"] == "prompt"
    assert "$ARGUMENTS" in hook["prompt"]
    assert "docs/PROJECT_LOG.md" in hook["prompt"]
    assert "stop_hook_active" in hook["prompt"]
