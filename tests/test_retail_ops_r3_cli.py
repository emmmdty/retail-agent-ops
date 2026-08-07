"""R3 CLI 分发测试：`dev_sft_export` 与 `sft` 两条 build 流水线。

沿用 R2 CLI 测试的隔离约定：`workspace` 在 tmp_path 里铺一份真实冻结
dataset_version 的完整正式数据集与 bundle 拷贝，并 chdir 过去，绝不触碰仓库
真实的 `manifests/`/`data/`/`models/`。训练本身用 `trainer_factory` 注入缝替换
成 fake，全程不加载模型、不访问 CUDA。
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from veritool_rl.retail_ops.bundle import load_bundle
from veritool_rl.retail_ops.formal_manifests import write_formal_task_set
from veritool_rl.retail_ops.formal_tasks import build_formal_task_set

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_VERSION = "retail_ops_v1_r2_20260722"
PUBLIC_REL = Path("manifests/retail_ops/v1") / DATASET_VERSION
PRIVATE_REL = Path("data/private/retail_ops/v1/r2") / DATASET_VERSION
BUNDLE_REL = Path("domains/retail_ops/v1")
MODEL_REL = "models/Qwen3-4B-pinned"
REVISION = "8cd0101f70cac4f1efcebc979faf483558e39297"


def _poison_teacher_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    """只毒化 `load_teacher_route` 真正会读的 key；读了就炸，不读完全无感。"""
    monkeypatch.setenv("TEACHER_LLM_PROVIDER", "not a provider name!!")


@pytest.fixture(scope="module")
def _formal_source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("r3-cli-source")
    bundle_dst = root / BUNDLE_REL
    shutil.copytree(REPO_ROOT / BUNDLE_REL, bundle_dst)
    bundle = load_bundle(bundle_dst)
    task_set = build_formal_task_set(DATASET_VERSION, seed=0)
    write_formal_task_set(task_set, bundle, root / PRIVATE_REL, root / PUBLIC_REL)
    return root


@pytest.fixture
def workspace(_formal_source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shutil.copytree(_formal_source, tmp_path, dirs_exist_ok=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write_yaml(path: Path, values: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(values, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _args(**overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {
        "command": "build",
        "config": Path("config.yaml"),
        "seed": 0,
        "output_dir": Path("out"),
        "input_dir": PRIVATE_REL,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


# ---------------------------------------------------------------------------
# pipeline: dev_sft_export
# ---------------------------------------------------------------------------


def _dev_sft_export_config(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "pipeline": "dev_sft_export",
        "bundle_dir": str(BUNDLE_REL),
        "dataset_version": DATASET_VERSION,
        "dev_manifest_path": str(PUBLIC_REL / "dev.json"),
        "attempt_id": "dev-sft-001",
    }
    values.update(overrides)
    return values


def test_dev_sft_export_writes_sixty_private_rows_and_public_summary(workspace: Path) -> None:
    from veritool_rl.product_cli import _run_dev_sft_export

    _run_dev_sft_export(_args(), _dev_sft_export_config())

    artifact = workspace / PRIVATE_REL / "dev-sft/dev-sft-001/sft.jsonl"
    rows = [json.loads(line) for line in artifact.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 60
    assert all(sorted(row) == ["messages", "scenario", "task_id", "tools"] for row in rows)

    summary = json.loads((workspace / "out/dev-sft.json").read_text(encoding="utf-8"))
    assert summary["total_tasks"] == 60
    assert summary["source"] == "internal_reference"
    assert summary["dataset_version"] == DATASET_VERSION


def test_dev_sft_export_never_reads_teacher_environment(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """dev 侧导出只用 Oracle，任何 teacher 环境变量都不该被读到。"""
    from veritool_rl.product_cli import _run_dev_sft_export

    _poison_teacher_environ(monkeypatch)

    _run_dev_sft_export(_args(), _dev_sft_export_config())

    assert (workspace / PRIVATE_REL / "dev-sft/dev-sft-001/sft.jsonl").is_file()


def test_dev_sft_export_refuses_to_overwrite_existing_attempt(workspace: Path) -> None:
    from veritool_rl.product_cli import _run_dev_sft_export

    _run_dev_sft_export(_args(), _dev_sft_export_config())

    with pytest.raises(FileExistsError):
        _run_dev_sft_export(_args(output_dir=Path("out2")), _dev_sft_export_config())


@pytest.mark.parametrize(
    "config",
    [
        _dev_sft_export_config(extra_key="x"),
        {k: v for k, v in _dev_sft_export_config().items() if k != "attempt_id"},
    ],
)
def test_dev_sft_export_requires_exact_config_keys(workspace: Path, config: dict[str, Any]) -> None:
    from veritool_rl.product_cli import _run_dev_sft_export

    del workspace
    with pytest.raises(ValueError, match="配置字段不符合命令契约"):
        _run_dev_sft_export(_args(), config)


def test_dev_sft_export_requires_input_dir(workspace: Path) -> None:
    from veritool_rl.product_cli import _run_dev_sft_export

    del workspace
    with pytest.raises(ValueError, match="input_dir"):
        _run_dev_sft_export(_args(input_dir=None), _dev_sft_export_config())


def test_dev_sft_export_rejects_holdout_manifest_path(workspace: Path) -> None:
    """把 holdout manifest 塞进 dev 通道必须失败，不得产出任何 holdout 派生数据。"""
    from veritool_rl.product_cli import _run_dev_sft_export

    config = _dev_sft_export_config(dev_manifest_path=str(PUBLIC_REL / "holdout.json"))

    with pytest.raises(ValueError):
        _run_dev_sft_export(_args(), config)

    assert not (workspace / PRIVATE_REL / "dev-sft").exists()


def test_dev_sft_export_rejects_dataset_version_mismatch(workspace: Path) -> None:
    from veritool_rl.product_cli import _run_dev_sft_export

    del workspace
    config = _dev_sft_export_config(dataset_version="retail_ops_v1_r2_19700101")

    with pytest.raises(ValueError):
        _run_dev_sft_export(_args(), config)


def test_dev_sft_export_dispatches_from_main(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from veritool_rl.product_cli import main

    _poison_teacher_environ(monkeypatch)
    _write_yaml(workspace / "config.yaml", _dev_sft_export_config())

    exit_code = main(
        [
            "build",
            "--config",
            "config.yaml",
            "--seed",
            "0",
            "--output_dir",
            "out",
            "--input_dir",
            str(PRIVATE_REL),
        ]
    )

    assert exit_code == 0
    assert (workspace / "out/dev-sft.json").is_file()


# ---------------------------------------------------------------------------
# pipeline: sft
# ---------------------------------------------------------------------------


class _FakeTrainer:
    """记录被传入的训练配置，绝不加载模型或访问 CUDA。"""

    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], int, Path]] = []

    def __call__(self, config: dict[str, Any], seed: int, output_dir: Path) -> dict[str, Any]:
        self.calls.append((config, seed, output_dir))
        return {"train": {"train_loss": 0.5}, "eval": {"eval_loss": 0.6}}


def _model_pin() -> dict[str, Any]:
    return {
        "name": MODEL_REL,
        "load_in_4bit": True,
        "revision": REVISION,
        "file_sha256": {"config.json": "0" * 64},
    }


def _sft_config(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "pipeline": "sft",
        "model": _model_pin(),
        "lora": {
            "r": 16,
            "alpha": 32,
            "dropout": 0.05,
            "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj"],
        },
        "data": {
            "train_relpath": "train-export/train-export-001/sft.jsonl",
            "eval_relpath": "dev-sft/dev-sft-001/sft.jsonl",
        },
        "training": {
            "epochs": 3,
            "batch_size": 2,
            "grad_accum": 8,
            "lr": 2.0e-4,
            "max_seq_len": 1024,
        },
    }
    values.update(overrides)
    return values


@pytest.fixture
def sft_workspace(workspace: Path) -> Path:
    """铺出 SFT 需要的私有 train/dev 数据与模型目录（内容是占位，训练被 fake）。"""
    for relpath in (
        "train-export/train-export-001/sft.jsonl",
        "dev-sft/dev-sft-001/sft.jsonl",
    ):
        path = workspace / PRIVATE_REL / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"messages": [], "tools": []}\n', encoding="utf-8")
    model_dir = workspace / MODEL_REL
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    return workspace


def test_sft_passes_resolved_private_paths_and_seed_to_trainer(sft_workspace: Path) -> None:
    """config 只写私有根内的相对路径；绝对/私有根前缀由 `--input_dir` 在运行时提供。"""
    from veritool_rl.product_cli import _run_sft

    trainer = _FakeTrainer()

    _run_sft(_args(seed=7), _sft_config(), trainer_factory=trainer)

    (config, seed, output_dir) = trainer.calls[0]
    assert seed == 7
    assert output_dir == Path("out")
    assert "pipeline" not in config
    assert config["data"]["train_path"] == str(
        PRIVATE_REL / "train-export/train-export-001/sft.jsonl"
    )
    assert config["data"]["eval_path"] == str(PRIVATE_REL / "dev-sft/dev-sft-001/sft.jsonl")
    assert config["model"]["revision"] == REVISION
    assert config["lora"]["target_modules"] == ["q_proj", "k_proj", "v_proj", "o_proj"]
    del sft_workspace


def test_sft_config_handed_to_trainer_is_accepted_by_real_resolver(sft_workspace: Path) -> None:
    """CLI 组装出的 config 必须能被真实 `resolve_sft_config` 接受，形状不能漂移。"""
    from veritool_rl.product_cli import _run_sft
    from veritool_rl.training.sft import resolve_sft_config

    trainer = _FakeTrainer()
    _run_sft(_args(), _sft_config(), trainer_factory=trainer)
    (config, seed, output_dir) = trainer.calls[0]

    resolved = resolve_sft_config(config, seed, output_dir)

    assert resolved.model.name == MODEL_REL
    assert resolved.model.revision == REVISION
    assert resolved.adapter_dir == output_dir / "adapter"
    assert resolved.data.train_path == PRIVATE_REL / "train-export/train-export-001/sft.jsonl"
    del sft_workspace


def test_sft_forwards_smoke_limits(sft_workspace: Path) -> None:
    from veritool_rl.product_cli import _run_sft

    trainer = _FakeTrainer()
    config = _sft_config(
        data={
            "train_relpath": "train-export/train-export-001/sft.jsonl",
            "eval_relpath": "dev-sft/dev-sft-001/sft.jsonl",
            "train_limit": 8,
            "eval_limit": 8,
        },
        training={"max_steps": 2, "smoke": True, "verify_adapter_reload": True},
    )

    _run_sft(_args(), config, trainer_factory=trainer)

    (passed, _, _) = trainer.calls[0]
    assert passed["data"]["train_limit"] == 8
    assert passed["data"]["eval_limit"] == 8
    assert passed["training"]["smoke"] is True
    del sft_workspace


def test_sft_never_reads_teacher_environment(
    sft_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from veritool_rl.product_cli import _run_sft

    _poison_teacher_environ(monkeypatch)
    trainer = _FakeTrainer()

    _run_sft(_args(), _sft_config(), trainer_factory=trainer)

    assert len(trainer.calls) == 1
    del sft_workspace


@pytest.mark.parametrize(
    "relpath",
    ["../escape/sft.jsonl", "/etc/passwd", "train-export/../../sft.jsonl", ""],
)
def test_sft_rejects_unsafe_data_relpath(sft_workspace: Path, relpath: str) -> None:
    from veritool_rl.product_cli import _run_sft

    trainer = _FakeTrainer()
    config = _sft_config(
        data={
            "train_relpath": relpath,
            "eval_relpath": "dev-sft/dev-sft-001/sft.jsonl",
        }
    )

    with pytest.raises(ValueError):
        _run_sft(_args(), config, trainer_factory=trainer)

    assert trainer.calls == []
    del sft_workspace


@pytest.mark.parametrize(
    "config",
    [
        _sft_config(extra_key="x"),
        {k: v for k, v in _sft_config().items() if k != "lora"},
    ],
)
def test_sft_requires_exact_config_keys(sft_workspace: Path, config: dict[str, Any]) -> None:
    from veritool_rl.product_cli import _run_sft

    trainer = _FakeTrainer()
    with pytest.raises(ValueError, match="配置字段不符合命令契约"):
        _run_sft(_args(), config, trainer_factory=trainer)

    assert trainer.calls == []
    del sft_workspace


def test_sft_requires_exact_data_keys(sft_workspace: Path) -> None:
    from veritool_rl.product_cli import _run_sft

    trainer = _FakeTrainer()
    config = _sft_config(data={"train_relpath": "a/b.jsonl", "train_path": "x.jsonl"})

    with pytest.raises(ValueError):
        _run_sft(_args(), config, trainer_factory=trainer)

    assert trainer.calls == []
    del sft_workspace


def test_sft_requires_input_dir(sft_workspace: Path) -> None:
    from veritool_rl.product_cli import _run_sft

    trainer = _FakeTrainer()
    with pytest.raises(ValueError, match="input_dir"):
        _run_sft(_args(input_dir=None), _sft_config(), trainer_factory=trainer)

    assert trainer.calls == []
    del sft_workspace


def test_default_sft_trainer_is_the_real_run_sft() -> None:
    """默认工厂必须真的指向 `training.sft.run_sft`，不是测试用的占位实现。"""
    from veritool_rl.product_cli import _default_sft_trainer
    from veritool_rl.training.sft import run_sft

    assert _default_sft_trainer is run_sft


def test_sft_dispatches_from_main(sft_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import veritool_rl.product_cli as product_cli

    trainer = _FakeTrainer()
    monkeypatch.setattr(product_cli, "_default_sft_trainer", trainer)
    _write_yaml(sft_workspace / "config.yaml", _sft_config())

    exit_code = product_cli.main(
        [
            "build",
            "--config",
            "config.yaml",
            "--seed",
            "0",
            "--output_dir",
            "out",
            "--input_dir",
            str(PRIVATE_REL),
        ]
    )

    assert exit_code == 0
    assert len(trainer.calls) == 1


def test_unknown_build_pipeline_still_rejected(workspace: Path) -> None:
    from veritool_rl.product_cli import _run_build

    _write_yaml(workspace / "config.yaml", {"pipeline": "sft_v2", "model": {}})

    with pytest.raises(ValueError, match="未知 build pipeline"):
        _run_build(_args(config=Path("config.yaml")))


# ---------------------------------------------------------------------------
# 已提交 R3 config 的端到端可用性（防止 config 与 CLI 契约漂移）
# ---------------------------------------------------------------------------


def _load_committed_config(name: str) -> dict[str, Any]:
    return yaml.safe_load((REPO_ROOT / "configs" / name).read_text(encoding="utf-8"))


def test_committed_dev_sft_export_config_runs_end_to_end(workspace: Path) -> None:
    from veritool_rl.product_cli import _run_dev_sft_export

    config = _load_committed_config("retail_ops_v1_r3_dev_sft_export.yaml")

    _run_dev_sft_export(_args(), config)

    artifact = workspace / PRIVATE_REL / "dev-sft/dev-sft-001/sft.jsonl"
    assert len(artifact.read_text(encoding="utf-8").splitlines()) == 60


@pytest.mark.parametrize(
    "name",
    [
        "retail_ops_v1_r3_sft_smoke.yaml",
        "retail_ops_v1_r3_sft_overfit.yaml",
        "retail_ops_v1_r3_sft.yaml",
    ],
)
def test_committed_sft_configs_reach_the_real_resolver(sft_workspace: Path, name: str) -> None:
    """已提交的三份 SFT config 必须能穿过 CLI 组装并被真实 `resolve_sft_config` 接受。"""
    from veritool_rl.product_cli import _run_sft
    from veritool_rl.training.sft import resolve_sft_config

    trainer = _FakeTrainer()
    _run_sft(_args(), _load_committed_config(name), trainer_factory=trainer)
    (config, seed, output_dir) = trainer.calls[0]

    resolved = resolve_sft_config(config, seed, output_dir)

    assert resolved.model.name == MODEL_REL
    assert resolved.model.load_in_4bit is True
    assert resolved.training.assistant_only_loss is True
    assert len(resolved.model.file_sha256) == 13
    del sft_workspace


# ---------------------------------------------------------------------------
# pipeline: formal_dev_candidate (evaluate)
# ---------------------------------------------------------------------------


def _candidate_cli_config(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "pipeline": "formal_dev_candidate",
        "bundle_dir": str(BUNDLE_REL),
        "dataset_version": DATASET_VERSION,
        "dev_manifest_path": str(PUBLIC_REL / "dev.json"),
        "models_root": "models",
        "attempt_id": "qwen3-4b-dev-candidate-001",
        "model": _model_pin_full(),
        "adapter": {
            "run_dir": "reports/retail_ops/v1/r3/sft-001",
            "file_sha256": {"adapter_config.json": "0" * 64},
        },
        "generation": {"max_new_tokens": 256},
    }
    values.update(overrides)
    return values


def _model_pin_full() -> dict[str, Any]:
    return {
        "repo": "Qwen/Qwen3-4B",
        "revision": REVISION,
        "local_dir": "Qwen3-4B-pinned",
        "file_sha256": {"config.json": "0" * 64},
    }


def _eval_args(**overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {
        "command": "evaluate",
        "config": Path("config.yaml"),
        "seed": 0,
        "output_dir": Path("out"),
        "input_dir": PRIVATE_REL,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


@pytest.mark.parametrize(
    "config",
    [
        _candidate_cli_config(extra_key="x"),
        {k: v for k, v in _candidate_cli_config().items() if k != "adapter"},
    ],
)
def test_candidate_pipeline_requires_exact_config_keys(
    workspace: Path, config: dict[str, Any]
) -> None:
    from veritool_rl.product_cli import _run_formal_dev_candidate

    del workspace
    with pytest.raises(ValueError, match="配置字段不符合命令契约"):
        _run_formal_dev_candidate(_eval_args(), config)


def test_candidate_pipeline_rejects_nonzero_seed(workspace: Path) -> None:
    """候选必须与 base 用同一冻结 seed，否则比较无效。"""
    from veritool_rl.product_cli import _run_formal_dev_candidate

    del workspace
    with pytest.raises(ValueError, match="seed"):
        _run_formal_dev_candidate(_eval_args(seed=1), _candidate_cli_config())


def test_candidate_pipeline_never_reads_teacher_environment(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """毒化 teacher 环境后仍应因业务原因失败，而不是因为读了 env 炸掉。"""
    from veritool_rl.product_cli import _run_formal_dev_candidate

    _poison_teacher_environ(monkeypatch)
    del workspace

    with pytest.raises(ValueError, match="配置字段不符合命令契约"):
        _run_formal_dev_candidate(_eval_args(), _candidate_cli_config(extra_key="x"))


def test_candidate_pipeline_rejects_holdout_manifest(workspace: Path) -> None:
    from veritool_rl.product_cli import _run_formal_dev_candidate

    config = _candidate_cli_config(dev_manifest_path=str(PUBLIC_REL / "holdout.json"))

    with pytest.raises(ValueError):
        _run_formal_dev_candidate(_eval_args(), config)

    assert not (workspace / PRIVATE_REL / "dev-candidate").exists()


def test_default_candidate_backend_factory_mounts_the_adapter() -> None:
    """默认后端工厂必须把 adapter 目录真的传给 TransformersBackend。"""
    import veritool_rl.product_cli as product_cli
    from veritool_rl.agent.qwen import GenerationSettings, TransformersBackend
    from veritool_rl.retail_ops.base_evaluation import ModelArtifact
    from veritool_rl.retail_ops.candidate_evaluation import (
        AdapterArtifact,
        CandidateEvaluationConfig,
    )

    calls: list[tuple[str, str | None]] = []

    def fake_from_pretrained(model_name: str, adapter_name: str | None, **kwargs: Any) -> object:
        calls.append((model_name, adapter_name))
        return object()

    config = CandidateEvaluationConfig(
        dataset_version=DATASET_VERSION,
        model=ModelArtifact(**_model_pin_full()),
        adapter=AdapterArtifact(
            run_dir="reports/retail_ops/v1/r3/sft-001",
            file_sha256={"adapter_config.json": "0" * 64},
        ),
        generation=GenerationSettings(max_new_tokens=256),
        code_commit="1" * 40,
        uv_lock_sha256="0" * 64,
    )
    original = TransformersBackend.from_pretrained
    try:
        TransformersBackend.from_pretrained = staticmethod(fake_from_pretrained)  # type: ignore[method-assign]
        product_cli._default_candidate_backend(config, Path("models"))
    finally:
        TransformersBackend.from_pretrained = original  # type: ignore[method-assign]

    assert calls == [
        ("models/Qwen3-4B-pinned", "reports/retail_ops/v1/r3/sft-001/adapter"),
    ]


def test_committed_candidate_config_reaches_the_real_contract(workspace: Path) -> None:
    """已提交的候选 config 必须能被真实 CandidateEvaluationConfig 接受。"""
    from veritool_rl.agent.qwen import GenerationSettings
    from veritool_rl.retail_ops.base_evaluation import ModelArtifact
    from veritool_rl.retail_ops.candidate_evaluation import (
        AdapterArtifact,
        CandidateEvaluationConfig,
    )

    del workspace
    raw = _load_committed_config("retail_ops_v1_r3_qwen3_4b_candidate.yaml")
    config = CandidateEvaluationConfig(
        dataset_version=raw["dataset_version"],
        model=ModelArtifact(**raw["model"]),
        adapter=AdapterArtifact(**raw["adapter"]),
        generation=GenerationSettings(**raw["generation"]),
        code_commit="1" * 40,
        uv_lock_sha256="0" * 64,
    )

    assert config.seed == 0
    assert config.max_steps == 5
    assert len(config.model.file_sha256) == 13
    assert len(config.adapter.file_sha256) == 7
    assert config.adapter.adapter_dir == Path("reports/retail_ops/v1/r3/sft-001/adapter")
