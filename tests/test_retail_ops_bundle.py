from pathlib import Path
from shutil import copytree

import pytest
import yaml


def test_load_bundle_pins_versions_tools_and_hashes() -> None:
    from veritool_rl.retail_ops.domain.bundle import load_bundle

    loaded = load_bundle(Path("domains/retail_ops/v1"))

    assert loaded.bundle.bundle_id == "retail_ops"
    assert loaded.bundle.bundle_version == "1.0.0"
    assert [tool.name for tool in loaded.tools] == [
        "get_order",
        "refund_order",
        "get_store_hours",
    ]
    assert loaded.policies.max_transient_retries == 1
    assert len(loaded.bundle_sha256) == 64
    assert set(loaded.component_sha256) == {
        "bundle.yaml",
        "tools.yaml",
        "policies.yaml",
        "release.yaml",
    }


def test_bundle_rejects_unknown_fields(tmp_path: Path) -> None:
    from veritool_rl.retail_ops.domain.bundle import load_bundle

    source = Path("domains/retail_ops/v1")
    target = tmp_path / "v1"
    target.mkdir()
    for name in ("tools.yaml", "policies.yaml", "release.yaml"):
        (target / name).write_bytes((source / name).read_bytes())
    (target / "bundle.yaml").write_text(
        (source / "bundle.yaml").read_text(encoding="utf-8") + "unknown: true\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown"):
        load_bundle(target)


def test_bundle_rejects_refund_reason_enum_drift(tmp_path: Path) -> None:
    from veritool_rl.retail_ops.domain.bundle import load_bundle

    target = tmp_path / "v1"
    copytree(Path("domains/retail_ops/v1"), target)
    tools_path = target / "tools.yaml"
    document = yaml.safe_load(tools_path.read_text(encoding="utf-8"))
    document["tools"][1]["parameters"]["properties"]["reason"]["enum"] = [
        "damaged",
        "wrong_item",
        "not_as_described",
    ]
    tools_path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="refund_reasons"):
        load_bundle(target)
