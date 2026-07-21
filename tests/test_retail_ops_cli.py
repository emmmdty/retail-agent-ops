"""RetailAgentOps 稳定产品 CLI 的解析与纵向分发测试。"""

from __future__ import annotations

import json
import shutil
import tomllib
from pathlib import Path

import pytest


def test_product_cli_exposes_three_nonblocking_commands() -> None:
    from veritool_rl.product_cli import build_product_parser

    parser = build_product_parser()
    build = parser.parse_args(["build", "--config", "x", "--output_dir", "y"])
    evaluate = parser.parse_args(
        [
            "evaluate",
            "--config",
            "x",
            "--input_dir",
            "build",
            "--output_dir",
            "y",
        ]
    )
    release = parser.parse_args(
        [
            "release",
            "--config",
            "x",
            "--baseline_dir",
            "base",
            "--candidate_dir",
            "candidate",
            "--output_dir",
            "y",
        ]
    )

    assert (build.command, evaluate.command, release.command) == (
        "build",
        "evaluate",
        "release",
    )
    assert (build.seed, evaluate.seed, release.seed) == (0, 0, 0)


def test_build_cli_writes_manifest_and_rejects_absolute_config_path(
    tmp_path: Path,
) -> None:
    from veritool_rl.product_cli import main

    exit_code = main(
        [
            "build",
            "--config",
            "configs/retail_ops_v1_build.yaml",
            "--seed",
            "0",
            "--output_dir",
            str(tmp_path / "build"),
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "build/manifest.json").is_file()

    bad_config = tmp_path / "bad.yaml"
    bad_config.write_text("bundle_dir: /tmp/retail-ops\nsplit: qualification\n")
    with pytest.raises(ValueError, match="bundle_dir 必须是项目相对路径"):
        main(
            [
                "build",
                "--config",
                str(bad_config),
                "--output_dir",
                str(tmp_path / "bad-build"),
            ]
        )


def test_evaluate_and_release_cli_dispatch(tmp_path: Path) -> None:
    from veritool_rl.product_cli import main

    build_dir = tmp_path / "build"
    baseline_dir = tmp_path / "baseline"
    candidate_dir = tmp_path / "candidate"
    release_dir = tmp_path / "release"
    assert (
        main(
            [
                "build",
                "--config",
                "configs/retail_ops_v1_build.yaml",
                "--output_dir",
                str(build_dir),
            ]
        )
        == 0
    )
    for config, output in (
        ("configs/retail_ops_v1_qualification_base.yaml", baseline_dir),
        ("configs/retail_ops_v1_qualification_oracle.yaml", candidate_dir),
    ):
        assert (
            main(
                [
                    "evaluate",
                    "--config",
                    config,
                    "--input_dir",
                    str(build_dir),
                    "--output_dir",
                    str(output),
                ]
            )
            == 0
        )
    assert (
        main(
            [
                "release",
                "--config",
                "configs/retail_ops_v1_release.yaml",
                "--baseline_dir",
                str(baseline_dir),
                "--candidate_dir",
                str(candidate_dir),
                "--output_dir",
                str(release_dir),
            ]
        )
        == 0
    )

    report = json.loads((release_dir / "release.json").read_text(encoding="utf-8"))
    assert report["decision"] == "GO"
    assert report["deployment"] == "candidate"


def test_pyproject_registers_product_command_without_package_rename() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["name"] == "veritool-rl"
    assert pyproject["project"]["scripts"]["retail-agent-ops"] == ("veritool_rl.product_cli:main")


def test_release_cli_rejects_config_bundle_different_from_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from veritool_rl.product_cli import main

    build_dir = tmp_path / "build"
    baseline_dir = tmp_path / "baseline"
    candidate_dir = tmp_path / "candidate"
    main(
        [
            "build",
            "--config",
            "configs/retail_ops_v1_build.yaml",
            "--output_dir",
            str(build_dir),
        ]
    )
    for config, output in (
        ("configs/retail_ops_v1_qualification_base.yaml", baseline_dir),
        ("configs/retail_ops_v1_qualification_oracle.yaml", candidate_dir),
    ):
        main(
            [
                "evaluate",
                "--config",
                config,
                "--input_dir",
                str(build_dir),
                "--output_dir",
                str(output),
            ]
        )

    copied_bundle = tmp_path / "bundle"
    shutil.copytree(Path("domains/retail_ops/v1"), copied_bundle)
    release_yaml = copied_bundle / "release.yaml"
    release_yaml.write_text(
        release_yaml.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    release_config = tmp_path / "release.yaml"
    release_config.write_text("bundle_dir: bundle\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="release bundle SHA-256 不匹配"):
        main(
            [
                "release",
                "--config",
                str(release_config),
                "--baseline_dir",
                str(baseline_dir),
                "--candidate_dir",
                str(candidate_dir),
                "--output_dir",
                str(tmp_path / "release"),
            ]
        )
