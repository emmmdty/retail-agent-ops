"""P0-3 合并脚本的纯函数契约。

真正的合并需要 torch/peft 与 8 GB 权重，只能在 GPU 主机上跑；这里锁住的是
**不依赖重依赖的那部分**：派生标识的确定性、来源记录的完整性、以及"不可覆盖"。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "merge_lora_adapter", REPO_ROOT / "scripts/ops/merge_lora_adapter.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["merge_lora_adapter"] = module
    spec.loader.exec_module(module)
    return module


ADAPTER_HASHES = {"adapter_model.safetensors": "8a49251f" + "0" * 56}


def test_derived_revision_is_deterministic_and_hex() -> None:
    """同一对输入必须永远导出同一个标识，否则合并产物无法被 pin。"""
    module = _module()

    first = module.derive_merged_revision("8cd0101f", ADAPTER_HASHES)
    second = module.derive_merged_revision("8cd0101f", ADAPTER_HASHES)

    assert first == second
    assert len(first) == 64
    assert all(character in "0123456789abcdef" for character in first)


def test_derived_revision_changes_with_either_input() -> None:
    """换基座或换 adapter 都必须换标识——否则两个不同的合并产物会同名。"""
    module = _module()

    baseline = module.derive_merged_revision("8cd0101f", ADAPTER_HASHES)
    other_base = module.derive_merged_revision("deadbeef", ADAPTER_HASHES)
    other_adapter = module.derive_merged_revision(
        "8cd0101f", {"adapter_model.safetensors": "1" * 64}
    )

    assert len({baseline, other_base, other_adapter}) == 3


def test_provenance_records_both_inputs_and_the_numerical_caveat(tmp_path: Path) -> None:
    """来源记录必须能回答"这个权重目录由什么合成"，并写明数值不等价。"""
    module = _module()

    provenance = module.build_provenance(
        base_repo="Qwen/Qwen3-4B",
        base_revision="8cd0101f",
        base_dir=tmp_path / "Qwen3-4B-pinned",
        base_file_sha256={"config.json": "0" * 64},
        adapter_dir=tmp_path / "sft-006/adapter",
        adapter_file_sha256=ADAPTER_HASHES,
        merged_file_sha256={"model.safetensors": "2" * 64},
        library_versions={"torch": "2.13.0", "transformers": "4.44.0", "peft": "0.12.0"},
    )

    assert provenance["base"]["revision"] == "8cd0101f"
    assert provenance["adapter"]["file_sha256"] == ADAPTER_HASHES
    assert provenance["merged"]["file_sha256"] == {"model.safetensors": "2" * 64}
    assert provenance["merged_revision"] == module.derive_merged_revision(
        "8cd0101f", ADAPTER_HASHES
    )
    assert "数值不等价" in provenance["numerical_note"]
    assert set(provenance["library_versions"]) == {"torch", "transformers", "peft"}


def test_merge_refuses_to_overwrite_an_existing_output_dir(tmp_path: Path) -> None:
    """正式产物不可覆盖——这条在加载任何重依赖**之前**就必须生效。"""
    module = _module()
    existing = tmp_path / "merged"
    existing.mkdir()

    with pytest.raises(SystemExit, match="不可覆盖"):
        module.main(
            [
                "--base_dir",
                str(tmp_path / "base"),
                "--adapter_dir",
                str(tmp_path / "adapter"),
                "--output_dir",
                str(existing),
                "--base_repo",
                "Qwen/Qwen3-4B",
                "--base_revision",
                "8cd0101f",
            ]
        )
