"""生成 BFCL V4 固定单轮子集 provenance manifest。"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from veritool_rl.cli import build_arg_parser, load_config
from veritool_rl.core.artifacts import write_json
from veritool_rl.legacy.data.bfcl import BFCL_CATEGORIES, build_bfcl_manifest


def build_manifest_artifact(config_path: Path, seed: int, output_dir: Path) -> Path:
    """按配置构建 manifest 并返回写入路径。"""
    config = load_config(config_path)
    commit = config.get("bfcl_commit")
    data_root = config.get("bfcl_data_root")
    filename = config.get("manifest_filename")
    quotas_value = config.get("quotas")
    if not isinstance(commit, str) or not isinstance(data_root, str):
        msg = "bfcl_commit 和 bfcl_data_root 必须是字符串"
        raise ValueError(msg)
    if not isinstance(filename, str) or Path(filename).name != filename:
        msg = "manifest_filename 必须是单个文件名"
        raise ValueError(msg)
    if not isinstance(quotas_value, dict) or set(quotas_value) != set(BFCL_CATEGORIES):
        msg = "quotas 必须精确包含四个 BFCL 固定类别"
        raise ValueError(msg)
    if not all(
        isinstance(key, str) and isinstance(value, int) for key, value in quotas_value.items()
    ):
        msg = "quotas 的类别和配额类型无效"
        raise ValueError(msg)
    quotas = cast(dict[str, int], quotas_value)
    ordered_quotas = {category: quotas[category] for category in BFCL_CATEGORIES}
    manifest = build_bfcl_manifest(
        data_root=Path(data_root),
        bfcl_commit=commit,
        seed=seed,
        quotas=ordered_quotas,
    )
    output_path = output_dir / filename
    write_json(output_path, manifest.model_dump(mode="json"))
    return output_path


def main() -> None:
    """CLI 入口。"""
    args = build_arg_parser("生成 BFCL V4 固定子集 manifest").parse_args()
    build_manifest_artifact(args.config, args.seed, args.output_dir)


if __name__ == "__main__":
    main()
