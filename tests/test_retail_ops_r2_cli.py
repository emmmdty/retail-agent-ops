"""R2 CLI/config 严格分发测试：解析、精确 schema、input_dir 语义与拒绝路径。

`workspace` fixture 预先铺好一份完整的正式数据集（真实冻结 dataset_version，因为
`write_formal_task_set` 硬编码只接受该值）与 bundle 拷贝，全部写在隔离的 tmp_path
CWD 下——绝不触碰仓库真实的 `manifests/`/`data/` 目录。`bare_workspace` 只提供
bundle 拷贝，用于需要"从零开始"跑 formal_freeze 的测试。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from veritool_rl.agent.qwen import GpuMeasurement, HardwareProvider, hash_local_model_files
from veritool_rl.retail_ops.bundle import load_bundle
from veritool_rl.retail_ops.formal_manifests import write_formal_task_set
from veritool_rl.retail_ops.formal_tasks import build_formal_task_set
from veritool_rl.retail_ops.teacher_client import TeacherResponse
from veritool_rl.retail_ops.teacher_route import TeacherRouteSnapshot

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_VERSION = "retail_ops_v1_r2_20260722"
PUBLIC_REL = Path("manifests/retail_ops/v1") / DATASET_VERSION
PRIVATE_REL = Path("data/private/retail_ops/v1/r2") / DATASET_VERSION
BUNDLE_REL = Path("domains/retail_ops/v1")
MODEL_DIR_NAME = "Qwen3-1.7B-pinned"
MODEL_FILES = ("config.json", "model.safetensors", "tokenizer.json")
REVISION = "9f3b1c2d4e5a6b7c8d9e0f1a2b3c4d5e6f708192"

_VALID_ENVIRON = {
    "TEACHER_LLM_PROVIDER": "acme",
    "TEACHER_LLM_ACME_BASE_URL": "https://teacher.example.com/v1",
    "TEACHER_LLM_ACME_API_KEY": "sk-test-not-a-real-key",
    "TEACHER_LLM_ACME_MODEL": "acme-teacher-1",
}


def _poison_teacher_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 `os.environ` 里 teacher 相关变量设成读了就会立刻报错的毒值。

    不整体替换 `os.environ`（那会连 pytest 自身的终端宽度等内部读取都一起
    炸掉）；只毒化 `load_teacher_route` 实际会读的那几个 key，读了就在
    `TeacherRouteSnapshot` 校验阶段炸得清清楚楚，不读就完全无感。
    """
    monkeypatch.setenv("TEACHER_LLM_PROVIDER", "not a provider name!!")
    for suffix in ("BASE_URL", "API_KEY", "MODEL"):
        monkeypatch.delenv(f"TEACHER_LLM_ACME_{suffix}", raising=False)


class _FakeHardwareProvider:
    def __init__(self) -> None:
        self.resets = 0
        self.measurements = 0

    def reset_peak_memory(self) -> None:
        self.resets += 1

    def measure(self) -> GpuMeasurement:
        self.measurements += 1
        return GpuMeasurement(
            gpu_index=0,
            gpu_uuid="GPU-8f6d3c21-4b5a-4c7d-9e10-2f3a4b5c6d7e",
            gpu_name="fake-gpu",
            cuda_visible_devices="0",
            cuda_device="cuda:0",
            peak_memory_bytes=1024,
        )


def _hardware_provider_factory() -> HardwareProvider:
    return _FakeHardwareProvider()


class _AlwaysFailTeacherClient:
    """任意消息都返回非法工具调用——快速产出 ILLEGAL_TOOL/未接受证据。"""

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        temperature: float = 0.0,
    ) -> TeacherResponse:
        del messages, tools, temperature
        return TeacherResponse(
            model="fake-teacher",
            content=None,
            tool_calls=(),
        )


def _fake_client_factory(route: TeacherRouteSnapshot, api_key: str) -> _AlwaysFailTeacherClient:
    del route, api_key
    return _AlwaysFailTeacherClient()


@pytest.fixture(scope="module")
def _formal_source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("r2-cli-source")
    bundle_dst = root / BUNDLE_REL
    shutil.copytree(Path("domains/retail_ops/v1"), bundle_dst)
    bundle = load_bundle(bundle_dst)
    task_set = build_formal_task_set(DATASET_VERSION, seed=0)
    write_formal_task_set(task_set, bundle, root / PRIVATE_REL, root / PUBLIC_REL)
    return root


@pytest.fixture
def workspace(_formal_source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shutil.copytree(_formal_source, tmp_path, dirs_exist_ok=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def bare_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shutil.copytree(Path("domains/retail_ops/v1"), tmp_path / BUNDLE_REL)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write_yaml(path: Path, values: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(values, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _formal_freeze_config(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "pipeline": "formal_freeze",
        "bundle_dir": str(BUNDLE_REL),
        "dataset_version": DATASET_VERSION,
    }
    values.update(overrides)
    return values


def _teacher_collect_config(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "pipeline": "teacher_collect",
        "bundle_dir": str(BUNDLE_REL),
        "public_dir": str(PUBLIC_REL),
        "dataset_version": DATASET_VERSION,
        "attempt_id": "teacher-attempt-001",
        "max_episodes_per_task": 2,
        "max_request_attempts": 3,
    }
    values.update(overrides)
    return values


def _train_export_config(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "pipeline": "train_export",
        "bundle_dir": str(BUNDLE_REL),
        "public_dir": str(PUBLIC_REL),
        "dataset_version": DATASET_VERSION,
        "teacher_attempt_id": "teacher-attempt-001",
        "attempt_id": "train-export-001",
    }
    values.update(overrides)
    return values


def _formal_dev_base_config(models_root: Path, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "pipeline": "formal_dev_base",
        "bundle_dir": str(BUNDLE_REL),
        "dataset_version": DATASET_VERSION,
        "dev_manifest_path": str(PUBLIC_REL / "dev.json"),
        "models_root": str(models_root),
        "attempt_id": "dev-base-001",
        "model": {
            "repo": "Qwen/Qwen3-1.7B",
            "revision": REVISION,
            "local_dir": MODEL_DIR_NAME,
            "file_sha256": {"config.json": "ab" * 32},
        },
        "generation": {"max_new_tokens": 64},
    }
    values.update(overrides)
    return values


def _make_model_files(workspace_root: Path, models_root_name: str) -> dict[str, str]:
    model_dir = workspace_root / models_root_name / MODEL_DIR_NAME
    model_dir.mkdir(parents=True)
    (model_dir / "config.json").write_text('{"model_type":"qwen3"}', encoding="utf-8")
    (model_dir / "model.safetensors").write_bytes(b"fake-weights")
    (model_dir / "tokenizer.json").write_text('{"version":"1.0"}', encoding="utf-8")
    return hash_local_model_files(model_dir, MODEL_FILES)


# ---------------------------------------------------------------------------
# parser: --input_dir on build
# ---------------------------------------------------------------------------


def test_build_parser_input_dir_is_optional_and_defaults_to_none() -> None:
    from veritool_rl.product_cli import build_product_parser

    parser = build_product_parser()
    args = parser.parse_args(["build", "--config", "x", "--output_dir", "y"])

    assert args.input_dir is None


def test_build_parser_input_dir_accepts_explicit_value() -> None:
    from veritool_rl.product_cli import build_product_parser

    parser = build_product_parser()
    args = parser.parse_args(["build", "--config", "x", "--input_dir", "z", "--output_dir", "y"])

    assert args.input_dir == Path("z")


# ---------------------------------------------------------------------------
# R1 unaffected
# ---------------------------------------------------------------------------


def test_r1_build_config_without_pipeline_still_runs(tmp_path: Path) -> None:
    from veritool_rl.product_cli import main

    exit_code = main(
        [
            "build",
            "--config",
            "configs/retail_ops_v1_build.yaml",
            "--output_dir",
            str(tmp_path / "build"),
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "build" / "manifest.json").is_file()


def test_r1_build_rejects_input_dir_when_config_has_no_pipeline(tmp_path: Path) -> None:
    from veritool_rl.product_cli import main

    with pytest.raises(ValueError, match="input_dir"):
        main(
            [
                "build",
                "--config",
                "configs/retail_ops_v1_build.yaml",
                "--input_dir",
                str(tmp_path / "nope"),
                "--output_dir",
                str(tmp_path / "build"),
            ]
        )


# ---------------------------------------------------------------------------
# unknown pipeline
# ---------------------------------------------------------------------------


def test_build_rejects_unknown_pipeline(bare_workspace: Path, tmp_path: Path) -> None:
    from veritool_rl.product_cli import main

    config_path = bare_workspace / "bogus.yaml"
    _write_yaml(config_path, _formal_freeze_config(pipeline="not_a_real_pipeline"))

    with pytest.raises(ValueError, match="pipeline"):
        main(
            [
                "build",
                "--config",
                str(config_path),
                "--output_dir",
                str(tmp_path / "out"),
            ]
        )


def test_evaluate_rejects_unknown_pipeline(workspace: Path, tmp_path: Path) -> None:
    from veritool_rl.product_cli import main

    models_root = "models"
    config_path = workspace / "bogus_eval.yaml"
    _write_yaml(
        config_path,
        _formal_dev_base_config(Path(models_root), pipeline="not_a_real_pipeline"),
    )

    with pytest.raises(ValueError, match="pipeline"):
        main(
            [
                "evaluate",
                "--config",
                str(config_path),
                "--input_dir",
                str(PRIVATE_REL),
                "--output_dir",
                str(tmp_path / "out"),
            ]
        )


# ---------------------------------------------------------------------------
# formal_freeze
# ---------------------------------------------------------------------------


def test_formal_freeze_rejects_missing_key(bare_workspace: Path, tmp_path: Path) -> None:
    from veritool_rl.product_cli import main

    config = _formal_freeze_config()
    del config["dataset_version"]
    config_path = bare_workspace / "freeze.yaml"
    _write_yaml(config_path, config)

    with pytest.raises(ValueError, match="配置字段不符合命令契约"):
        main(
            [
                "build",
                "--config",
                str(config_path),
                "--output_dir",
                str(tmp_path / "out"),
            ]
        )


def test_formal_freeze_rejects_extra_key(bare_workspace: Path, tmp_path: Path) -> None:
    from veritool_rl.product_cli import main

    config_path = bare_workspace / "freeze.yaml"
    _write_yaml(config_path, _formal_freeze_config(unexpected_key="nope"))

    with pytest.raises(ValueError, match="配置字段不符合命令契约"):
        main(
            [
                "build",
                "--config",
                str(config_path),
                "--output_dir",
                str(tmp_path / "out"),
            ]
        )


def test_formal_freeze_rejects_input_dir(bare_workspace: Path, tmp_path: Path) -> None:
    from veritool_rl.product_cli import main

    config_path = bare_workspace / "freeze.yaml"
    _write_yaml(config_path, _formal_freeze_config())

    with pytest.raises(ValueError, match="input_dir"):
        main(
            [
                "build",
                "--config",
                str(config_path),
                "--input_dir",
                str(tmp_path / "nope"),
                "--output_dir",
                str(tmp_path / "out"),
            ]
        )


def test_formal_freeze_rejects_absolute_bundle_dir(bare_workspace: Path, tmp_path: Path) -> None:
    from veritool_rl.product_cli import main

    config_path = bare_workspace / "freeze.yaml"
    _write_yaml(
        config_path, _formal_freeze_config(bundle_dir=str((bare_workspace / BUNDLE_REL).resolve()))
    )

    with pytest.raises(ValueError, match="项目相对路径"):
        main(
            [
                "build",
                "--config",
                str(config_path),
                "--output_dir",
                str(tmp_path / "out"),
            ]
        )


def test_formal_freeze_rejects_wrong_dataset_version(bare_workspace: Path, tmp_path: Path) -> None:
    from veritool_rl.product_cli import main

    config_path = bare_workspace / "freeze.yaml"
    _write_yaml(config_path, _formal_freeze_config(dataset_version="not-the-frozen-version"))

    with pytest.raises(ValueError, match="dataset_version"):
        main(
            [
                "build",
                "--config",
                str(config_path),
                "--output_dir",
                str(tmp_path / "out"),
            ]
        )


def test_formal_freeze_rejects_wrong_seed(bare_workspace: Path, tmp_path: Path) -> None:
    from veritool_rl.product_cli import main

    config_path = bare_workspace / "freeze.yaml"
    _write_yaml(config_path, _formal_freeze_config())

    with pytest.raises(ValueError, match="seed"):
        main(
            [
                "build",
                "--config",
                str(config_path),
                "--seed",
                "1",
                "--output_dir",
                str(tmp_path / "out"),
            ]
        )


def test_formal_freeze_succeeds_once_then_rejects_overwrite(
    bare_workspace: Path, tmp_path: Path
) -> None:
    from veritool_rl.product_cli import main

    config_path = bare_workspace / "freeze.yaml"
    _write_yaml(config_path, _formal_freeze_config())

    exit_code = main(
        [
            "build",
            "--config",
            str(config_path),
            "--output_dir",
            str(bare_workspace / PUBLIC_REL),
        ]
    )
    assert exit_code == 0
    assert (bare_workspace / PUBLIC_REL / "dataset.json").is_file()
    assert (bare_workspace / PRIVATE_REL / "train.jsonl").is_file()

    with pytest.raises(FileExistsError):
        main(
            [
                "build",
                "--config",
                str(config_path),
                "--output_dir",
                str(tmp_path / "second-public-out"),
            ]
        )


# ---------------------------------------------------------------------------
# teacher_collect
# ---------------------------------------------------------------------------


def test_teacher_collect_requires_input_dir(workspace: Path, tmp_path: Path) -> None:
    from veritool_rl.product_cli import main

    config_path = workspace / "teacher.yaml"
    _write_yaml(config_path, _teacher_collect_config())

    with pytest.raises(ValueError, match="input_dir"):
        main(
            [
                "build",
                "--config",
                str(config_path),
                "--output_dir",
                str(tmp_path / "out"),
            ]
        )


def test_teacher_collect_rejects_missing_key(workspace: Path, tmp_path: Path) -> None:
    from veritool_rl.product_cli import main

    config = _teacher_collect_config()
    del config["attempt_id"]
    config_path = workspace / "teacher.yaml"
    _write_yaml(config_path, config)

    with pytest.raises(ValueError, match="配置字段不符合命令契约"):
        main(
            [
                "build",
                "--config",
                str(config_path),
                "--input_dir",
                str(PRIVATE_REL),
                "--output_dir",
                str(tmp_path / "out"),
            ]
        )


def test_teacher_collect_rejects_extra_key(workspace: Path, tmp_path: Path) -> None:
    from veritool_rl.product_cli import main

    config_path = workspace / "teacher.yaml"
    _write_yaml(config_path, _teacher_collect_config(adapter_path="adapters/x"))

    with pytest.raises(ValueError, match="配置字段不符合命令契约"):
        main(
            [
                "build",
                "--config",
                str(config_path),
                "--input_dir",
                str(PRIVATE_REL),
                "--output_dir",
                str(tmp_path / "out"),
            ]
        )


def test_teacher_collect_rejects_absolute_public_dir(workspace: Path, tmp_path: Path) -> None:
    from veritool_rl.product_cli import main

    config_path = workspace / "teacher.yaml"
    _write_yaml(
        config_path,
        _teacher_collect_config(public_dir=str((workspace / PUBLIC_REL).resolve())),
    )

    with pytest.raises(ValueError, match="项目相对路径"):
        main(
            [
                "build",
                "--config",
                str(config_path),
                "--input_dir",
                str(PRIVATE_REL),
                "--output_dir",
                str(tmp_path / "out"),
            ]
        )


def test_teacher_collect_rejects_wrong_dataset_version_before_touching_env(
    workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from veritool_rl.product_cli import main

    _poison_teacher_environ(monkeypatch)
    config_path = workspace / "teacher.yaml"
    _write_yaml(config_path, _teacher_collect_config(dataset_version="wrong-version"))

    with pytest.raises(ValueError, match="dataset_version"):
        main(
            [
                "build",
                "--config",
                str(config_path),
                "--input_dir",
                str(PRIVATE_REL),
                "--output_dir",
                str(tmp_path / "out"),
            ]
        )


def test_teacher_collect_reads_env_and_calls_injected_client_factory(
    workspace: Path, tmp_path: Path
) -> None:
    from veritool_rl.product_cli import _run_teacher_collect, build_product_parser

    parser = build_product_parser()
    config_path = workspace / "teacher.yaml"
    config = _teacher_collect_config()
    _write_yaml(config_path, config)
    args = parser.parse_args(
        [
            "build",
            "--config",
            str(config_path),
            "--input_dir",
            str(PRIVATE_REL),
            "--output_dir",
            str(tmp_path / "out"),
        ]
    )

    _run_teacher_collect(
        args,
        config,
        environ=_VALID_ENVIRON,
        client_factory=_fake_client_factory,
    )

    summary_path = tmp_path / "out" / "summary.json"
    assert summary_path.is_file()
    attempt_dir = PRIVATE_REL / "teacher-collection" / "teacher-attempt-001"
    assert attempt_dir.is_dir()
    evidence_files = [p for p in attempt_dir.glob("*.json") if p.name != "checkpoint.json"]
    assert len(evidence_files) == 240
    assert (attempt_dir / "checkpoint.json").is_file()


def test_non_teacher_collect_pipelines_never_touch_hostile_environ(
    workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from veritool_rl.product_cli import main

    _poison_teacher_environ(monkeypatch)

    # R1 build path
    assert (
        main(
            [
                "build",
                "--config",
                str(REPO_ROOT / "configs" / "retail_ops_v1_build.yaml"),
                "--output_dir",
                str(tmp_path / "r1-build"),
            ]
        )
        == 0
    )

    # train_export path (empty evidence -> quality gate fails, but that must
    # happen without ever touching os.environ)
    export_config_path = workspace / "export.yaml"
    _write_yaml(export_config_path, _train_export_config())
    with pytest.raises(Exception):  # noqa: B017 - quality gate error, not an env leak
        main(
            [
                "build",
                "--config",
                str(export_config_path),
                "--input_dir",
                str(PRIVATE_REL),
                "--output_dir",
                str(tmp_path / "export-out"),
            ]
        )


# ---------------------------------------------------------------------------
# train_export
# ---------------------------------------------------------------------------


def test_train_export_requires_input_dir(workspace: Path, tmp_path: Path) -> None:
    from veritool_rl.product_cli import main

    config_path = workspace / "export.yaml"
    _write_yaml(config_path, _train_export_config())

    with pytest.raises(ValueError, match="input_dir"):
        main(
            [
                "build",
                "--config",
                str(config_path),
                "--output_dir",
                str(tmp_path / "out"),
            ]
        )


def test_train_export_rejects_missing_key(workspace: Path, tmp_path: Path) -> None:
    from veritool_rl.product_cli import main

    config = _train_export_config()
    del config["teacher_attempt_id"]
    config_path = workspace / "export.yaml"
    _write_yaml(config_path, config)

    with pytest.raises(ValueError, match="配置字段不符合命令契约"):
        main(
            [
                "build",
                "--config",
                str(config_path),
                "--input_dir",
                str(PRIVATE_REL),
                "--output_dir",
                str(tmp_path / "out"),
            ]
        )


def test_train_export_fails_gate_with_no_prior_teacher_evidence(
    workspace: Path, tmp_path: Path
) -> None:
    from veritool_rl.product_cli import main
    from veritool_rl.retail_ops.teacher_data import TeacherQualityGateError

    config_path = workspace / "export.yaml"
    _write_yaml(config_path, _train_export_config(teacher_attempt_id="never-ran"))

    with pytest.raises(TeacherQualityGateError):
        main(
            [
                "build",
                "--config",
                str(config_path),
                "--input_dir",
                str(PRIVATE_REL),
                "--output_dir",
                str(tmp_path / "out"),
            ]
        )
    assert not (tmp_path / "out").exists()


# ---------------------------------------------------------------------------
# formal_dev_base (evaluate)
# ---------------------------------------------------------------------------


def _dev_base_backend_factory(config: Any, models_root: Path) -> Any:
    del config, models_root

    class _FakeBackend:
        def generate(
            self,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
            max_new_tokens: int,
        ) -> Any:
            from veritool_rl.agent.qwen import GeneratedText

            del max_new_tokens
            assert tools
            if any(message.get("role") == "assistant" for message in messages):
                return GeneratedText(text="已完成核实。", input_tokens=10, output_tokens=4)
            import json
            import re

            match = re.search(r"O-[A-Z0-9]{12}", str(messages[-1]["content"]))
            assert match is not None
            payload = json.dumps({"name": "get_order", "arguments": {"order_id": match.group(0)}})
            return GeneratedText(
                text=f"<tool_call>{payload}</tool_call>", input_tokens=10, output_tokens=6
            )

    return _FakeBackend()


def test_formal_dev_base_rejects_missing_key(workspace: Path, tmp_path: Path) -> None:
    from veritool_rl.product_cli import main

    config = _formal_dev_base_config(Path("models"))
    del config["attempt_id"]
    config_path = workspace / "dev.yaml"
    _write_yaml(config_path, config)

    with pytest.raises(ValueError, match="配置字段不符合命令契约"):
        main(
            [
                "evaluate",
                "--config",
                str(config_path),
                "--input_dir",
                str(PRIVATE_REL),
                "--output_dir",
                str(tmp_path / "out"),
            ]
        )


def test_formal_dev_base_rejects_extra_adapter_key(workspace: Path, tmp_path: Path) -> None:
    from veritool_rl.product_cli import main

    config = _formal_dev_base_config(Path("models"), adapter_path="adapters/x")
    config_path = workspace / "dev.yaml"
    _write_yaml(config_path, config)

    with pytest.raises(ValueError, match="配置字段不符合命令契约"):
        main(
            [
                "evaluate",
                "--config",
                str(config_path),
                "--input_dir",
                str(PRIVATE_REL),
                "--output_dir",
                str(tmp_path / "out"),
            ]
        )


def test_formal_dev_base_rejects_adapter_nested_in_model(workspace: Path, tmp_path: Path) -> None:
    from veritool_rl.product_cli import main

    config = _formal_dev_base_config(Path("models"))
    config["model"]["adapter_path"] = "adapters/x"
    config_path = workspace / "dev.yaml"
    _write_yaml(config_path, config)

    with pytest.raises(ValidationError):
        main(
            [
                "evaluate",
                "--config",
                str(config_path),
                "--input_dir",
                str(PRIVATE_REL),
                "--output_dir",
                str(tmp_path / "out"),
            ]
        )


def test_formal_dev_base_rejects_wrong_model_revision(workspace: Path, tmp_path: Path) -> None:
    from veritool_rl.product_cli import main

    config = _formal_dev_base_config(Path("models"))
    config["model"]["revision"] = "not-hex"
    config_path = workspace / "dev.yaml"
    _write_yaml(config_path, config)

    with pytest.raises(ValidationError):
        main(
            [
                "evaluate",
                "--config",
                str(config_path),
                "--input_dir",
                str(PRIVATE_REL),
                "--output_dir",
                str(tmp_path / "out"),
            ]
        )


def test_formal_dev_base_rejects_holdout_receipt_as_dev_manifest(
    workspace: Path, tmp_path: Path
) -> None:
    from veritool_rl.product_cli import main

    config = _formal_dev_base_config(
        Path("models"), dev_manifest_path=str(PUBLIC_REL / "holdout-receipt.json")
    )
    config_path = workspace / "dev.yaml"
    _write_yaml(config_path, config)

    with pytest.raises(ValidationError):
        main(
            [
                "evaluate",
                "--config",
                str(config_path),
                "--input_dir",
                str(PRIVATE_REL),
                "--output_dir",
                str(tmp_path / "out"),
            ]
        )


def test_formal_dev_base_rejects_wrong_dataset_version(workspace: Path, tmp_path: Path) -> None:
    from veritool_rl.product_cli import main

    config = _formal_dev_base_config(Path("models"), dataset_version="wrong-version")
    config_path = workspace / "dev.yaml"
    _write_yaml(config_path, config)

    with pytest.raises(ValueError, match="dataset_version"):
        main(
            [
                "evaluate",
                "--config",
                str(config_path),
                "--input_dir",
                str(PRIVATE_REL),
                "--output_dir",
                str(tmp_path / "out"),
            ]
        )


def test_formal_dev_base_rejects_non_zero_seed(workspace: Path, tmp_path: Path) -> None:
    from veritool_rl.product_cli import main

    config = _formal_dev_base_config(Path("models"))
    config_path = workspace / "dev.yaml"
    _write_yaml(config_path, config)

    with pytest.raises(ValueError, match="seed"):
        main(
            [
                "evaluate",
                "--config",
                str(config_path),
                "--seed",
                "1",
                "--input_dir",
                str(PRIVATE_REL),
                "--output_dir",
                str(tmp_path / "out"),
            ]
        )


def test_formal_dev_base_rejects_absolute_models_root(workspace: Path, tmp_path: Path) -> None:
    from veritool_rl.product_cli import main

    config = _formal_dev_base_config((workspace / "models").resolve())
    config_path = workspace / "dev.yaml"
    _write_yaml(config_path, config)

    with pytest.raises(ValueError, match="项目相对路径"):
        main(
            [
                "evaluate",
                "--config",
                str(config_path),
                "--input_dir",
                str(PRIVATE_REL),
                "--output_dir",
                str(tmp_path / "out"),
            ]
        )


def test_formal_dev_base_runs_through_injected_fake_backend_and_hardware(
    workspace: Path, tmp_path: Path
) -> None:
    from veritool_rl.product_cli import _run_formal_dev_base, build_product_parser

    parser = build_product_parser()
    file_sha256 = _make_model_files(workspace, "models")
    config = _formal_dev_base_config(Path("models"))
    config["model"]["file_sha256"] = file_sha256
    config_path = workspace / "dev.yaml"
    _write_yaml(config_path, config)
    args = parser.parse_args(
        [
            "evaluate",
            "--config",
            str(config_path),
            "--input_dir",
            str(PRIVATE_REL),
            "--output_dir",
            str(tmp_path / "out"),
        ]
    )

    _run_formal_dev_base(
        args,
        config,
        backend_factory=_dev_base_backend_factory,
        hardware_provider_factory=_hardware_provider_factory,
    )

    report_path = tmp_path / "out" / "base-report.json"
    assert report_path.is_file()


def test_formal_dev_base_rejects_output_overwrite(workspace: Path, tmp_path: Path) -> None:
    from veritool_rl.product_cli import _run_formal_dev_base, build_product_parser

    parser = build_product_parser()
    file_sha256 = _make_model_files(workspace, "models")
    config = _formal_dev_base_config(Path("models"))
    config["model"]["file_sha256"] = file_sha256
    config_path = workspace / "dev.yaml"
    _write_yaml(config_path, config)
    args = parser.parse_args(
        [
            "evaluate",
            "--config",
            str(config_path),
            "--input_dir",
            str(PRIVATE_REL),
            "--output_dir",
            str(tmp_path / "out"),
        ]
    )

    _run_formal_dev_base(
        args,
        config,
        backend_factory=_dev_base_backend_factory,
        hardware_provider_factory=_hardware_provider_factory,
    )

    with pytest.raises(FileExistsError):
        _run_formal_dev_base(
            args,
            config,
            backend_factory=_dev_base_backend_factory,
            hardware_provider_factory=_hardware_provider_factory,
        )
