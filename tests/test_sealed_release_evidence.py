"""R3 Task 3 A：sealed holdout 证据的 provenance 与配对契约。

sealed 报告是 release 门禁的唯一输入。dev 侧的 `compare_dev_runs` 能证明 base 与
candidate 跑在同一条件下，靠的是 `BaseRunEvidence` 里的 model/generation/code_commit
等字段；sealed 报告原本没有这些字段，因此两份 sealed 报告放在一起无法在字段级证明
可比。本模块把"可比性必须可验证"固化为测试。

全部在 CPU 上用 fake backend / fake hardware provider 完成，不加载真实模型、不访问
CUDA、不读取仓库里的真实 holdout。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from veritool_rl.core.agent.qwen import (
    GeneratedText,
    GenerationSettings,
    GpuMeasurement,
    hash_local_model_files,
)
from veritool_rl.retail_ops.build.formal_manifests import (
    load_verified_formal_dataset,
    write_formal_task_set,
)
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.formal_tasks import build_formal_task_set
from veritool_rl.retail_ops.evaluate.base_evaluation import ModelArtifact
from veritool_rl.retail_ops.evaluate.candidate_evaluation import ComparisonError
from veritool_rl.retail_ops.evaluate.sealed_evaluation import SEALED_PAIRING_FIELDS
from veritool_rl.retail_ops.release.governance import EvidencePurpose

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_VERSION = "retail_ops_v1_r2_20260722"
PUBLIC_REL = Path("manifests/retail_ops/v1") / DATASET_VERSION
PRIVATE_REL = Path("data/private/retail_ops/v1/r2") / DATASET_VERSION
BUNDLE_REL = Path("domains/retail_ops/v1")
LOGICAL_HOLDOUT = PRIVATE_REL / "holdout.jsonl"
MODEL_FILES = ("config.json", "tokenizer.json")
ADAPTER_FILES = ("adapter_config.json", "adapter_model.safetensors")
ADAPTER_RUN_DIR = "reports/retail_ops/v1/r3/sft-001"
REVISION = "8cd0101f70cac4f1efcebc979faf483558e39297"


class _FinalReplyBackend:
    """确定性 fake 后端：只回一句最终答复，并声明自身 pin 以通过绑定校验。"""

    def __init__(self, *, model_dir: Path, adapter_path: Path | None, settings: Any) -> None:
        self.model_dir = str(model_dir)
        self.adapter_path = None if adapter_path is None else str(adapter_path)
        self.revision = REVISION
        self.settings = settings

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_new_tokens: int,
    ) -> GeneratedText:
        del messages, tools, max_new_tokens
        return GeneratedText(text="任务已完成。", input_tokens=1, output_tokens=1)


class _FakeHardwareProvider:
    def reset_peak_memory(self) -> None:
        return None

    def measure(self) -> GpuMeasurement:
        return GpuMeasurement(
            gpu_index=0,
            gpu_uuid="GPU-8f6d3c21-4b5a-4c7d-9e10-2f3a4b5c6d7e",
            gpu_name="fake-gpu",
            cuda_visible_devices="0",
            cuda_device="cuda:0",
            peak_memory_bytes=2048,
        )


@pytest.fixture(scope="module")
def _source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("r3-sealed-source")
    shutil.copytree(REPO_ROOT / BUNDLE_REL, root / BUNDLE_REL)
    bundle = load_bundle(root / BUNDLE_REL)
    task_set = build_formal_task_set(DATASET_VERSION, seed=0)
    write_formal_task_set(task_set, bundle, root / PRIVATE_REL, root / PUBLIC_REL)
    return root


@pytest.fixture
def workspace(_source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shutil.copytree(_source, tmp_path, dirs_exist_ok=True)
    monkeypatch.chdir(tmp_path)
    _write_model_dir(tmp_path, "Qwen3-4B-pinned", "primary")
    _write_model_dir(tmp_path, "Qwen3-4B-other", "other")
    adapter_dir = tmp_path / ADAPTER_RUN_DIR / "adapter"
    adapter_dir.mkdir(parents=True)
    for name in ADAPTER_FILES:
        (adapter_dir / name).write_text(f"adapter-{name}", encoding="utf-8")
    return tmp_path


def _write_model_dir(workspace: Path, local_dir: str, marker: str) -> None:
    model_dir = workspace / "models" / local_dir
    model_dir.mkdir(parents=True)
    for name in MODEL_FILES:
        (model_dir / name).write_text(f"{marker}-{name}", encoding="utf-8")


def _adapter_artifact(workspace: Path) -> Any:
    from veritool_rl.retail_ops.evaluate.candidate_evaluation import AdapterArtifact

    return AdapterArtifact(
        run_dir=ADAPTER_RUN_DIR,
        file_sha256=hash_local_model_files(workspace / ADAPTER_RUN_DIR / "adapter", ADAPTER_FILES),
    )


def _model_artifact(workspace: Path, local_dir: str = "Qwen3-4B-pinned") -> ModelArtifact:
    return ModelArtifact(
        repo="Qwen/Qwen3-4B",
        revision=REVISION,
        local_dir=local_dir,
        file_sha256=hash_local_model_files(workspace / "models" / local_dir, MODEL_FILES),
    )


def _sealed_config(workspace: Path, **overrides: Any) -> Any:
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import SealedEvaluationConfig

    values: dict[str, Any] = {
        "dataset_version": DATASET_VERSION,
        "model": _model_artifact(workspace),
        "generation": GenerationSettings(max_new_tokens=256),
        "code_commit": "1" * 40,
        "uv_lock_sha256": "0" * 64,
    }
    values.update(overrides)
    return SealedEvaluationConfig(**values)


def _run_sealed(workspace: Path, config: Any, attempt_id: str) -> Any:
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import evaluate_authorized_holdout
    from veritool_rl.retail_ops.release.formal_governance import authorize_formal_holdout

    private_root = workspace / PRIVATE_REL
    dataset = load_verified_formal_dataset(workspace / PUBLIC_REL)
    authorization = authorize_formal_holdout(
        dataset,
        private_root / "holdout.jsonl",
        LOGICAL_HOLDOUT,
        EvidencePurpose.RELEASE,
        trusted_private_root=private_root,
    )
    adapter_dir = None if config.adapter is None else workspace / config.adapter.adapter_dir
    backend = _FinalReplyBackend(
        model_dir=workspace / "models" / config.model.local_dir,
        adapter_path=adapter_dir,
        settings=config.generation,
    )
    return evaluate_authorized_holdout(
        authorization,
        load_bundle(workspace / BUNDLE_REL),
        backend,
        config,
        models_root=Path("models"),
        attempt_id=attempt_id,
        public_report_path=workspace / f"out-{attempt_id}" / "sealed-report.json",
        hardware_provider=_FakeHardwareProvider(),
    )


def test_sealed_runs_on_different_base_models_are_rejected_as_incomparable(
    workspace: Path,
) -> None:
    """两次 sealed 运行只要基座模型不同，就必须拒绝配对而不是给出 delta。

    这是 sealed 报告必须携带 `model` provenance 的理由：没有这个字段，两份只在
    基座上不同的报告在字段级完全一致，release 门禁会把模型差异当成 adapter 效果。
    """
    from veritool_rl.retail_ops.evaluate.candidate_evaluation import ComparisonError
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import require_comparable_sealed_runs

    base = _run_sealed(workspace, _sealed_config(workspace), "sealed-base-001")
    drifted_candidate = _run_sealed(
        workspace,
        _sealed_config(
            workspace,
            model=_model_artifact(workspace, "Qwen3-4B-other"),
            adapter=_adapter_artifact(workspace),
        ),
        "sealed-candidate-001",
    )

    with pytest.raises(ComparisonError, match="model"):
        require_comparable_sealed_runs(base, drifted_candidate)


def test_sealed_base_run_rejects_a_backend_that_secretly_carries_an_adapter(
    workspace: Path,
) -> None:
    """base 侧 sealed 证据没有 adapter 声明，因此必须拒绝任何挂了 adapter 的后端。

    否则一次候选运行会产出一份与真正基座运行逐字段难以区分的 base 证据，
    release 门禁的分母就被悄悄换掉了。
    """
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import evaluate_authorized_holdout
    from veritool_rl.retail_ops.release.formal_governance import authorize_formal_holdout

    config = _sealed_config(workspace)
    private_root = workspace / PRIVATE_REL
    authorization = authorize_formal_holdout(
        load_verified_formal_dataset(workspace / PUBLIC_REL),
        private_root / "holdout.jsonl",
        LOGICAL_HOLDOUT,
        EvidencePurpose.RELEASE,
        trusted_private_root=private_root,
    )
    smuggled = _FinalReplyBackend(
        model_dir=workspace / "models" / config.model.local_dir,
        adapter_path=workspace / ADAPTER_RUN_DIR / "adapter",
        settings=config.generation,
    )

    with pytest.raises(ValueError, match="adapter"):
        evaluate_authorized_holdout(
            authorization,
            load_bundle(workspace / BUNDLE_REL),
            smuggled,
            config,
            models_root=Path("models"),
            attempt_id="sealed-smuggled-001",
            public_report_path=workspace / "out-smuggled" / "sealed-report.json",
            hardware_provider=_FakeHardwareProvider(),
        )
    assert not (private_root / "sealed-eval" / "sealed-smuggled-001").exists()


def test_sealed_candidate_run_rejects_a_backend_without_the_pinned_adapter(
    workspace: Path,
) -> None:
    """候选侧若拿到未挂 adapter 的后端，证据会谎称评测了候选而实际跑的是基座。"""
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import evaluate_authorized_holdout
    from veritool_rl.retail_ops.release.formal_governance import authorize_formal_holdout

    config = _sealed_config(workspace, adapter=_adapter_artifact(workspace))
    private_root = workspace / PRIVATE_REL
    authorization = authorize_formal_holdout(
        load_verified_formal_dataset(workspace / PUBLIC_REL),
        private_root / "holdout.jsonl",
        LOGICAL_HOLDOUT,
        EvidencePurpose.RELEASE,
        trusted_private_root=private_root,
    )
    bare = _FinalReplyBackend(
        model_dir=workspace / "models" / config.model.local_dir,
        adapter_path=None,
        settings=config.generation,
    )

    with pytest.raises(ValueError, match="adapter"):
        evaluate_authorized_holdout(
            authorization,
            load_bundle(workspace / BUNDLE_REL),
            bare,
            config,
            models_root=Path("models"),
            attempt_id="sealed-bare-001",
            public_report_path=workspace / "out-bare" / "sealed-report.json",
            hardware_provider=_FakeHardwareProvider(),
        )
    assert not (private_root / "sealed-eval" / "sealed-bare-001").exists()


def test_a_genuine_base_candidate_pair_is_accepted_for_comparison(workspace: Path) -> None:
    """正对照：同基座、同生成参数、只多一个 adapter 的两次运行必须被接受。

    没有这条，前面几条拒绝测试可能只是因为校验器无条件拒绝一切。
    """
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import require_comparable_sealed_runs

    base = _run_sealed(workspace, _sealed_config(workspace), "pair-base-001")
    candidate = _run_sealed(
        workspace,
        _sealed_config(workspace, adapter=_adapter_artifact(workspace)),
        "pair-candidate-001",
    )

    require_comparable_sealed_runs(base, candidate)

    assert base.adapter is None
    assert candidate.adapter is not None
    assert base.model == candidate.model
    assert base.policy_id != candidate.policy_id
    assert base.config_sha256 != candidate.config_sha256


def test_sealed_report_id_covers_the_model_provenance(workspace: Path) -> None:
    """新增的 provenance 字段必须落在 report_id 自哈希内，否则可被静默改写。"""
    import json

    from veritool_rl.retail_ops.evaluate.sealed_evaluation import load_sealed_evaluation_report

    _run_sealed(workspace, _sealed_config(workspace), "tamper-001")
    report_path = workspace / PRIVATE_REL / "sealed-eval" / "tamper-001" / "report.json"

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["model"]["revision"] = "0" * 40
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="report_id"):
        load_sealed_evaluation_report(report_path, verify_artifacts=False)


# ---------------------------------------------------------------------------
# CLI pipeline: formal_holdout_base / formal_holdout_candidate (evaluate)
# ---------------------------------------------------------------------------


def _holdout_cli_config(workspace: Path, *, candidate: bool, **overrides: Any) -> dict[str, Any]:
    model = _model_artifact(workspace)
    values: dict[str, Any] = {
        "pipeline": "formal_holdout_candidate" if candidate else "formal_holdout_base",
        "bundle_dir": str(BUNDLE_REL),
        "dataset_version": DATASET_VERSION,
        "holdout_receipt_path": str(PUBLIC_REL / "holdout-receipt.json"),
        "models_root": "models",
        "attempt_id": "holdout-candidate-001" if candidate else "holdout-base-001",
        "model": model.model_dump(mode="json"),
        "generation": {"max_new_tokens": 256},
    }
    if candidate:
        values["adapter"] = _adapter_artifact(workspace).model_dump(mode="json")
    values.update(overrides)
    return values


def _eval_args(workspace: Path, **overrides: Any) -> Any:
    import argparse

    values: dict[str, Any] = {
        "command": "evaluate",
        "config": Path("config.yaml"),
        "seed": 0,
        "output_dir": workspace / "out-holdout",
        "input_dir": PRIVATE_REL,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _cli_backend_factory(workspace: Path) -> Any:
    def factory(config: Any, models_root: Path) -> Any:
        adapter = None if config.adapter is None else workspace / config.adapter.adapter_dir
        return _FinalReplyBackend(
            model_dir=models_root / config.model.local_dir,
            adapter_path=adapter,
            settings=config.generation,
        )

    return factory


def test_holdout_base_pipeline_writes_sealed_evidence_through_the_cli(workspace: Path) -> None:
    """`evaluate` 必须有一条能真正跑正式 holdout 的流水线。

    在此之前 `evaluate_authorized_holdout` 全仓只被测试引用，正式 120 条 holdout
    没有任何命令可以运行——发布门禁因此是不可执行的。
    """
    from veritool_rl.product_cli import _run_formal_holdout

    args = _eval_args(workspace)
    _run_formal_holdout(
        args,
        _holdout_cli_config(workspace, candidate=False),
        backend_factory=_cli_backend_factory(workspace),
        hardware_provider_factory=_FakeHardwareProvider,
        code_commit_factory=lambda: "1" * 40,
    )

    public_report = args.output_dir / "sealed-report.json"
    assert public_report.is_file()
    private_dir = workspace / PRIVATE_REL / "sealed-eval" / "holdout-base-001"
    assert (private_dir / "trajectories.jsonl").is_file()

    from veritool_rl.retail_ops.evaluate.sealed_evaluation import load_sealed_evaluation_report

    report = load_sealed_evaluation_report(public_report, verify_artifacts=False)
    assert report.task_count == 120
    assert report.split == "holdout"
    assert report.purpose == "release"
    assert report.adapter is None


def test_holdout_candidate_pipeline_binds_the_adapter_into_the_evidence(
    workspace: Path,
) -> None:
    """候选流水线产出的 sealed 证据必须锁定 adapter，且与 base 可配对。"""
    from veritool_rl.product_cli import _run_formal_holdout
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import (
        load_sealed_evaluation_report,
        require_comparable_sealed_runs,
    )

    base_args = _eval_args(workspace, output_dir=workspace / "out-base")
    _run_formal_holdout(
        base_args,
        _holdout_cli_config(workspace, candidate=False),
        backend_factory=_cli_backend_factory(workspace),
        hardware_provider_factory=_FakeHardwareProvider,
        code_commit_factory=lambda: "1" * 40,
    )
    candidate_args = _eval_args(workspace, output_dir=workspace / "out-candidate")
    _run_formal_holdout(
        candidate_args,
        _holdout_cli_config(workspace, candidate=True),
        backend_factory=_cli_backend_factory(workspace),
        hardware_provider_factory=_FakeHardwareProvider,
        code_commit_factory=lambda: "1" * 40,
    )

    base = load_sealed_evaluation_report(
        base_args.output_dir / "sealed-report.json", verify_artifacts=False
    )
    candidate = load_sealed_evaluation_report(
        candidate_args.output_dir / "sealed-report.json", verify_artifacts=False
    )

    assert candidate.adapter is not None
    assert candidate.adapter.run_dir == ADAPTER_RUN_DIR
    require_comparable_sealed_runs(base, candidate)


@pytest.mark.parametrize("candidate", [False, True])
def test_holdout_pipeline_requires_exact_config_keys(workspace: Path, candidate: bool) -> None:
    """多一个 key 或少 adapter 都必须硬失败，不得静默走成另一条通道。"""
    from veritool_rl.product_cli import _run_formal_holdout

    config = _holdout_cli_config(workspace, candidate=candidate, extra_key="x")
    with pytest.raises(ValueError, match="配置字段不符合命令契约"):
        _run_formal_holdout(_eval_args(workspace), config)


def test_holdout_base_pipeline_rejects_an_adapter_key(workspace: Path) -> None:
    """base 配置里出现 adapter 必须被 key 契约挡住，而不是被忽略。"""
    from veritool_rl.product_cli import _run_formal_holdout

    config = _holdout_cli_config(workspace, candidate=False)
    config["adapter"] = _adapter_artifact(workspace).model_dump(mode="json")

    with pytest.raises(ValueError, match="配置字段不符合命令契约"):
        _run_formal_holdout(_eval_args(workspace), config)


def test_holdout_pipeline_rejects_nonzero_seed(workspace: Path) -> None:
    """holdout 的 seed 由冻结 receipt 决定，命令行不得覆盖。"""
    from veritool_rl.product_cli import _run_formal_holdout

    with pytest.raises(ValueError, match="seed"):
        _run_formal_holdout(
            _eval_args(workspace, seed=1),
            _holdout_cli_config(workspace, candidate=False),
        )


def test_holdout_pipeline_rejects_dataset_version_mismatch(workspace: Path) -> None:
    """配置声明的数据版本必须与公开 receipt 绑定的一致。"""
    from veritool_rl.product_cli import _run_formal_holdout

    config = _holdout_cli_config(workspace, candidate=False, dataset_version="wrong_version")

    with pytest.raises(ValueError, match="dataset_version"):
        _run_formal_holdout(
            _eval_args(workspace),
            config,
            backend_factory=_cli_backend_factory(workspace),
            hardware_provider_factory=_FakeHardwareProvider,
            code_commit_factory=lambda: "1" * 40,
        )
    assert not (workspace / PRIVATE_REL / "sealed-eval").exists()


@pytest.mark.parametrize(
    ("name", "candidate"),
    [
        ("retail_ops_v1_r3_qwen3_4b_holdout_base.yaml", False),
        ("retail_ops_v1_r3_qwen3_4b_holdout_candidate.yaml", True),
    ],
)
def test_committed_holdout_configs_match_the_cli_contract(name: str, candidate: bool) -> None:
    """已提交的两份 holdout config 必须穿过 CLI key 契约并构造出真实的冻结配置。

    这是防漂移测试：key 集合改了、pin 段掉了字段，都会在这里失败，而不是等到
    真正要跑 holdout 的那一刻——那时窗口已经关闭。
    """
    import yaml

    from veritool_rl.core.agent.qwen import GenerationSettings
    from veritool_rl.product_cli import (
        _FORMAL_HOLDOUT_BASE_KEYS,
        _FORMAL_HOLDOUT_CANDIDATE_KEYS,
    )
    from veritool_rl.retail_ops.evaluate.base_evaluation import ModelArtifact
    from veritool_rl.retail_ops.evaluate.candidate_evaluation import AdapterArtifact
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import SealedEvaluationConfig

    config = yaml.safe_load(
        (REPO_ROOT / "configs/retail_ops/evaluate" / name).read_text(encoding="utf-8")
    )
    expected_keys = _FORMAL_HOLDOUT_CANDIDATE_KEYS if candidate else _FORMAL_HOLDOUT_BASE_KEYS
    assert set(config) == expected_keys

    sealed = SealedEvaluationConfig(
        dataset_version=config["dataset_version"],
        model=ModelArtifact(**config["model"]),
        adapter=AdapterArtifact(**config["adapter"]) if candidate else None,
        generation=GenerationSettings(**config["generation"]),
        code_commit="1" * 40,
        uv_lock_sha256="0" * 64,
    )

    assert sealed.seed == 0
    assert sealed.max_steps == 5
    assert len(sealed.model.file_sha256) == 13
    assert (sealed.adapter is not None) is candidate


def test_committed_holdout_configs_pin_the_same_base_model_as_the_dev_runs() -> None:
    """holdout 的 base/candidate 与已产出的 dev 运行必须锁定同一份基座模型文件。

    R2 dev base、R3 dev candidate 与两条 holdout 通道共用一个 model pin，是"delta
    可归因于 adapter"这一主张在配置层面的前提；逐字段比对让它可机器检查。
    """
    import yaml

    def _model_of(name: str) -> Any:
        path = REPO_ROOT / "configs/retail_ops/evaluate" / name
        return yaml.safe_load(path.read_text(encoding="utf-8"))["model"]

    dev_base = _model_of("retail_ops_v1_r2_qwen3_4b_dev.yaml")

    assert _model_of("retail_ops_v1_r3_qwen3_4b_candidate.yaml") == dev_base
    assert _model_of("retail_ops_v1_r3_qwen3_4b_holdout_base.yaml") == dev_base
    assert _model_of("retail_ops_v1_r3_qwen3_4b_holdout_candidate.yaml") == dev_base


def test_committed_holdout_candidate_config_pins_the_same_adapter_as_the_dev_candidate() -> None:
    """holdout 候选必须评测与 dev 候选完全相同的 adapter，否则两处结论无法互相解释。"""
    import yaml

    def _adapter_of(name: str) -> Any:
        path = REPO_ROOT / "configs/retail_ops/evaluate" / name
        return yaml.safe_load(path.read_text(encoding="utf-8"))["adapter"]

    assert _adapter_of("retail_ops_v1_r3_qwen3_4b_holdout_candidate.yaml") == _adapter_of(
        "retail_ops_v1_r3_qwen3_4b_candidate.yaml"
    )


def test_holdout_pipeline_rejects_a_tampered_private_holdout_artifact(workspace: Path) -> None:
    """私有 holdout 被改动后，两段式授权必须在任何执行之前拒绝。"""
    from veritool_rl.product_cli import _run_formal_holdout

    artifact = workspace / PRIVATE_REL / "holdout.jsonl"
    artifact.write_text(artifact.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256"):
        _run_formal_holdout(
            _eval_args(workspace),
            _holdout_cli_config(workspace, candidate=False),
            backend_factory=_cli_backend_factory(workspace),
            hardware_provider_factory=_FakeHardwareProvider,
            code_commit_factory=lambda: "1" * 40,
        )
    assert not (workspace / PRIVATE_REL / "sealed-eval").exists()


# ---------------------------------------------------------------------------
# formal release 门禁：sealed base ↔ sealed candidate
# ---------------------------------------------------------------------------

#: R3 候选在 60 条 dev 上的真实观测值（LOG-20260807-09）。holdout 尚未运行，
#: 这里用它们驱动门禁算术，是为了让"4/5 通过、唯一重要的那项失败"成为可执行回归。
_REAL_BASE_METRICS = {
    "task_success": 0.8,
    "policy_violation_count": 8,
    "invalid_call_count": 21,
    "p95_latency_ms": 6068.4763287950755,
}
_REAL_CANDIDATE_METRICS = {
    "task_success": 0.7166666666666667,
    "policy_violation_count": 0,
    "invalid_call_count": 0,
    "p95_latency_ms": 5211.318145302357,
}


def _with_metrics(report: Any, metrics: dict[str, Any]) -> Any:
    """替换报告的 metrics，其余配对字段保持真实运行产出的值。"""
    return report.model_copy(update={"metrics": {**report.metrics, **metrics}})


def test_formal_release_returns_no_go_when_only_the_success_gate_fails(
    workspace: Path,
) -> None:
    """R3 候选的真实形状：格式/违规/延迟三项都改善，唯独最终状态成功率退步。

    这正是本项目要证明的能力——复合指标里的改善不能掩盖任务成功率下降，
    发布结论必须是 NO-GO 且部署回滚到 base。
    """
    from veritool_rl.retail_ops.release.formal_release import decide_formal_release

    base = _with_metrics(
        _run_sealed(workspace, _sealed_config(workspace), "gate-base-001"),
        _REAL_BASE_METRICS,
    )
    candidate = _with_metrics(
        _run_sealed(
            workspace,
            _sealed_config(workspace, adapter=_adapter_artifact(workspace)),
            "gate-candidate-001",
        ),
        _REAL_CANDIDATE_METRICS,
    )
    policy = load_bundle(workspace / BUNDLE_REL).release

    report = decide_formal_release(base, candidate, policy)

    assert report.decision.value == "NO-GO"
    assert report.deployment == "baseline"
    assert report.failed_gate_ids == ["success_delta"]
    passed = {gate.gate_id: gate.passed for gate in report.gates}
    assert passed == {
        "success_delta": False,
        "policy_violation_delta": True,
        "invalid_call_count": True,
        "p95_latency_ratio": True,
        "evidence_complete": True,
    }
    assert report.base_report_id == base.report_id
    assert report.candidate_report_id == candidate.report_id


def test_formal_release_refuses_a_pair_that_is_not_comparable(workspace: Path) -> None:
    """候选跑在另一个基座上时必须抛错，绝不产出一份"带警告"的发布报告。

    一份看起来能用的无效发布结论比没有结论更危险——它会被直接抄进交付材料。
    """
    from veritool_rl.retail_ops.evaluate.candidate_evaluation import ComparisonError
    from veritool_rl.retail_ops.release.formal_release import decide_formal_release

    base = _run_sealed(workspace, _sealed_config(workspace), "drift-base-001")
    drifted = _run_sealed(
        workspace,
        _sealed_config(
            workspace,
            model=_model_artifact(workspace, "Qwen3-4B-other"),
            adapter=_adapter_artifact(workspace),
        ),
        "drift-candidate-001",
    )
    policy = load_bundle(workspace / BUNDLE_REL).release

    with pytest.raises(ComparisonError, match="model"):
        decide_formal_release(base, drifted, policy)


def test_formal_release_refuses_two_base_runs_as_a_pair(workspace: Path) -> None:
    """两份都没挂 adapter 时不存在"候选"，门禁必须拒绝而不是判出 GO。"""
    from veritool_rl.retail_ops.evaluate.candidate_evaluation import ComparisonError
    from veritool_rl.retail_ops.release.formal_release import decide_formal_release

    first = _run_sealed(workspace, _sealed_config(workspace), "two-base-001")
    second = _run_sealed(workspace, _sealed_config(workspace), "two-base-002")
    policy = load_bundle(workspace / BUNDLE_REL).release

    with pytest.raises(ComparisonError, match="adapter"):
        decide_formal_release(first, second, policy)


def test_formal_release_returns_go_when_every_gate_passes(workspace: Path) -> None:
    """正对照：候选满足全部门禁时必须判 GO 并把部署指向 candidate。

    没有这条，前面的 NO-GO 测试可能只是因为门禁无条件失败。
    """
    from veritool_rl.retail_ops.release.formal_release import decide_formal_release

    base = _with_metrics(
        _run_sealed(workspace, _sealed_config(workspace), "go-base-001"),
        _REAL_BASE_METRICS,
    )
    candidate = _with_metrics(
        _run_sealed(
            workspace,
            _sealed_config(workspace, adapter=_adapter_artifact(workspace)),
            "go-candidate-001",
        ),
        {**_REAL_CANDIDATE_METRICS, "task_success": 0.9},
    )
    policy = load_bundle(workspace / BUNDLE_REL).release

    report = decide_formal_release(base, candidate, policy)

    assert report.decision.value == "GO"
    assert report.deployment == "candidate"
    assert report.failed_gate_ids == []


def test_formal_release_report_round_trips_and_records_the_rollback_path(
    workspace: Path,
) -> None:
    """NO-GO 报告必须落盘为 JSON/Markdown/HTML 三份，并写明回滚到冻结 base。"""
    from veritool_rl.retail_ops.release.formal_release import (
        decide_formal_release,
        load_formal_release_report,
        write_formal_release_report,
    )

    base = _with_metrics(
        _run_sealed(workspace, _sealed_config(workspace), "rt-base-001"),
        _REAL_BASE_METRICS,
    )
    candidate = _with_metrics(
        _run_sealed(
            workspace,
            _sealed_config(workspace, adapter=_adapter_artifact(workspace)),
            "rt-candidate-001",
        ),
        _REAL_CANDIDATE_METRICS,
    )
    policy = load_bundle(workspace / BUNDLE_REL).release
    report = decide_formal_release(base, candidate, policy)
    output_dir = workspace / "release-no-go"

    write_formal_release_report(report, output_dir)

    reloaded = load_formal_release_report(output_dir / "release.json")
    assert reloaded == report
    markdown = (output_dir / "report.md").read_text(encoding="utf-8")
    assert "NO-GO" in markdown
    assert "回滚" in markdown
    assert "不得加载 adapter" in markdown
    assert (output_dir / "report.html").read_text(encoding="utf-8").startswith("<!doctype html>")


def test_formal_release_report_rejects_a_hand_edited_decision(workspace: Path) -> None:
    """把 NO-GO 报告的 decision 改成 GO 必须在加载时失败，不能靠人工改字段放行。"""
    import json

    from veritool_rl.retail_ops.release.formal_release import (
        decide_formal_release,
        load_formal_release_report,
        write_formal_release_report,
    )

    base = _with_metrics(
        _run_sealed(workspace, _sealed_config(workspace), "edit-base-001"),
        _REAL_BASE_METRICS,
    )
    candidate = _with_metrics(
        _run_sealed(
            workspace,
            _sealed_config(workspace, adapter=_adapter_artifact(workspace)),
            "edit-candidate-001",
        ),
        _REAL_CANDIDATE_METRICS,
    )
    policy = load_bundle(workspace / BUNDLE_REL).release
    output_dir = workspace / "release-edited"
    write_formal_release_report(decide_formal_release(base, candidate, policy), output_dir)

    path = output_dir / "release.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["decision"] = "GO"
    payload["deployment"] = "candidate"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="发布结论"):
        load_formal_release_report(path)


def test_r1_and_formal_gates_share_one_threshold_semantics(workspace: Path) -> None:
    """同一份 release.yaml 在两条通道上必须给出逐字段相同的门禁结果。

    R1 与 formal 的证据类型不同，但阈值、比较方向和门禁顺序必须同源，否则同一个
    候选可能在两条通道上得到互相矛盾的结论。
    """
    from veritool_rl.retail_ops.release.release import build_release_gates

    policy = load_bundle(workspace / BUNDLE_REL).release

    gates = build_release_gates(
        _REAL_BASE_METRICS,
        _REAL_CANDIDATE_METRICS,
        evidence_complete=True,
        policy=policy,
    )

    assert [gate.gate_id for gate in gates] == [
        "success_delta",
        "policy_violation_delta",
        "invalid_call_count",
        "p95_latency_ratio",
        "evidence_complete",
    ]
    assert [gate.passed for gate in gates] == [False, True, True, True, True]


def test_release_cli_dispatches_the_formal_holdout_gate(workspace: Path) -> None:
    """`release` 必须有一条消费 sealed 报告的通道，否则发布门禁仍然跑不起来。"""
    import argparse

    import yaml

    from veritool_rl.product_cli import _run_release
    from veritool_rl.retail_ops.release.formal_release import load_formal_release_report

    base_dir = workspace / "out-gate-base-001"
    candidate_dir = workspace / "out-gate-candidate-001"
    _run_sealed(workspace, _sealed_config(workspace), "gate-base-001")
    _run_sealed(
        workspace,
        _sealed_config(workspace, adapter=_adapter_artifact(workspace)),
        "gate-candidate-001",
    )

    config_path = workspace / "formal-release.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "pipeline": "formal_release",
                "bundle_dir": str(BUNDLE_REL),
                "gate_schema_version": "1.0",
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    output_dir = workspace / "release-cli"

    _run_release(
        argparse.Namespace(
            command="release",
            config=config_path,
            seed=0,
            output_dir=output_dir,
            baseline_dir=base_dir,
            candidate_dir=candidate_dir,
        )
    )

    report = load_formal_release_report(output_dir / "release.json")
    assert report.split == "holdout"
    assert report.task_count == 120
    assert (output_dir / "report.md").is_file()
    assert (output_dir / "report.html").is_file()


def test_release_cli_rejects_a_bundle_that_differs_from_the_sealed_evidence(
    workspace: Path,
) -> None:
    """release config 声明的 bundle 必须与两份 sealed 证据绑定的一致。"""
    import argparse

    import yaml

    from veritool_rl.product_cli import _run_release

    _run_sealed(workspace, _sealed_config(workspace), "bad-bundle-base-001")
    _run_sealed(
        workspace,
        _sealed_config(workspace, adapter=_adapter_artifact(workspace)),
        "bad-bundle-candidate-001",
    )

    other_bundle = workspace / "other-bundle"
    shutil.copytree(workspace / BUNDLE_REL, other_bundle)
    policies = other_bundle / "policies.yaml"
    policies.write_text(policies.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")

    config_path = workspace / "bad-bundle-release.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "pipeline": "formal_release",
                "bundle_dir": "other-bundle",
                "gate_schema_version": "1.0",
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="SHA-256 不匹配"):
        _run_release(
            argparse.Namespace(
                command="release",
                config=config_path,
                seed=0,
                output_dir=workspace / "release-bad-bundle",
                baseline_dir=workspace / "out-bad-bundle-base-001",
                candidate_dir=workspace / "out-bad-bundle-candidate-001",
            )
        )


def _mutated(value: Any) -> Any:
    """给任意配对字段造一个"确实不同"的值，类型保持不变。

    字段类型混杂（str / int / dict），因此不能沿用 dev 侧那个只处理字符串的
    `_mutate`。类型不变是有意的：这里要检验的是**值不同就拒绝**，
    而不是"塞一个类型错误的东西进去会不会炸"。
    """
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, str):
        return ("1" if value[:1] != "1" else "2") + value[1:]
    if isinstance(value, dict):
        return {**value, "__drifted__": 1}
    if isinstance(value, tuple | list):
        return [*value, "__drifted__"]
    raise AssertionError(f"没有为类型 {type(value)!r} 定义变异方式：{value!r}")


@pytest.mark.parametrize("field", SEALED_PAIRING_FIELDS)
def test_sealed_comparison_rejects_every_mismatched_pairing_field(
    workspace: Path, field: str
) -> None:
    """**封存侧的每一个配对字段**，不一致就必须拒绝比较。

    这条补的是一个由外部评审的变异测试实证出来的缺口：把
    `require_comparable_sealed_runs` 里那个逐字段比较循环整个短路掉
    （`if base_value != candidate_value:` → `if False:`），全仓测试**全绿**。

    dev 侧一直有对应的参数化测试（`test_candidate_evaluation.py`），
    封存侧却没有——而封存侧才是全部 GO/NO-GO 判定的来源。此前覆盖到的
    `model` / adapter 在场性 / merged 血统三项都在**循环之外**，所以循环失效不会红。

    参数从 `SEALED_PAIRING_FIELDS` **派生**，不是手抄一份清单：
    往那个常量里加字段时，这条测试自动跟上；dev 侧那份手写清单没有这个性质。
    """
    from veritool_rl.retail_ops.evaluate.sealed_evaluation import require_comparable_sealed_runs

    base = _run_sealed(workspace, _sealed_config(workspace), "sealed-base-pairing")
    candidate = _run_sealed(
        workspace,
        _sealed_config(workspace, adapter=_adapter_artifact(workspace)),
        "sealed-candidate-pairing",
    )
    # 形态校验（`_require_valid_forms`）在字段循环之前，所以候选侧必须是真的候选形态；
    # 拿 base 去冒充候选只会先撞上形态检查，那样这条测试就测不到循环本身。
    assert require_comparable_sealed_runs(base, candidate) is None
    drifted = candidate.model_copy(update={field: _mutated(getattr(candidate, field))})

    with pytest.raises(ComparisonError, match=field):
        require_comparable_sealed_runs(base, drifted)
