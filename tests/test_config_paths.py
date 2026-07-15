"""仓库运行配置的项目相对路径契约。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).parents[1]
MODEL_PATH = "models/Qwen3-1.7B"


@pytest.mark.parametrize("config_name", ["mvp_eval_qwen_base.yaml", "mvp_eval_qwen_sft.yaml"])
def test_qwen_eval_configs_use_local_model_symlink(config_name: str) -> None:
    config = _load_config(config_name)

    assert config["policy"]["model_name"] == MODEL_PATH


@pytest.mark.parametrize("config_name", ["mvp_sft_qwen3_1_7b.yaml", "sft.example.yaml"])
def test_sft_configs_use_local_model_symlink(config_name: str) -> None:
    config = _load_config(config_name)

    assert config["model"]["name"] == MODEL_PATH


def test_smoke_config_limits_one_local_qwen_task() -> None:
    config = _load_config("mvp_eval_qwen_smoke.yaml")

    assert config["task_limit"] == 1
    assert config["policy"]["model_name"] == MODEL_PATH


def test_git_ignores_report_adapters_and_checkpoints() -> None:
    paths = [
        "reports/mvp/sft-seed0/adapter/adapter_config.json",
        "reports/mvp/sft-seed0/adapter/tokenizer.json",
        "reports/mvp/sft-seed0/checkpoints/checkpoint-1/trainer_state.json",
    ]

    for path in paths:
        result = subprocess.run(
            ["git", "check-ignore", "-q", path],
            cwd=ROOT,
            check=False,
        )
        assert result.returncode == 0, f"未忽略训练大产物路径: {path}"


def test_all_config_file_references_are_project_relative() -> None:
    path_keys = {
        "model_name",
        "adapter_path",
        "train_path",
        "eval_path",
        "baseline_dir",
        "adapter_dir",
    }
    references: list[tuple[str, str]] = []
    for config_path in sorted((ROOT / "configs").glob("*.yaml")):
        config = _load_yaml(config_path)
        references.extend(_collect_paths(config, path_keys, prefix=config_path.name))
        model = config.get("model")
        if isinstance(model, dict) and isinstance(model.get("name"), str):
            references.append((f"{config_path.name}.model.name", model["name"]))

    assert references
    for field, value in references:
        path = Path(value)
        assert not path.is_absolute(), f"{field} 必须使用项目相对路径: {value}"
        assert ".." not in path.parts, f"{field} 不得离开项目目录: {value}"


def _load_config(name: str) -> dict[str, Any]:
    return _load_yaml(ROOT / "configs" / name)


def _load_yaml(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _collect_paths(
    value: Any,
    path_keys: set[str],
    prefix: str,
) -> list[tuple[str, str]]:
    if not isinstance(value, dict):
        return []
    found: list[tuple[str, str]] = []
    for key, child in value.items():
        field = f"{prefix}.{key}"
        if key in path_keys and isinstance(child, str):
            found.append((field, child))
        else:
            found.extend(_collect_paths(child, path_keys, field))
    return found
