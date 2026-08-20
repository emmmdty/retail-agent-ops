"""R3 Task 2: dev 候选（base + LoRA adapter）评测与 base↔candidate 配对比较。

为什么不复用 `BaseEvaluationConfig`/`BaseRunEvidence` 直接加一个可选 adapter 字段：
`base_evaluation._content_id` 把除 `run_id`/`schema_version` 外的**全部字段**算进
自哈希，因此给这两个模型加任何字段都会让已经产出的 R2 base 证据（两份
`base-report.json`）的 `run_id` 复算失败。候选契约改用子类扩展——父模型的
dump 不受影响，既有证据继续可加载，而 adapter 身份自然进入候选自己的 `run_id`。

执行与指标机器不在这里重写：前置守卫走 `require_dev_evaluation_preconditions`，
运行与度量走 `measure_dev_run`，两者与 base 通道是同一份代码。配对比较只有在
两次运行经过同一套验证强度和同一套指标计算时才成立。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator

from veritool_rl.core.agent.qwen import (
    GenerationBackend,
    HardwareProvider,
    verify_local_model_files,
)
from veritool_rl.core.artifacts import write_json
from veritool_rl.core.paths import validate_project_relative_path
from veritool_rl.core.trajectory.schema import StrictModel
from veritool_rl.retail_ops.build.formal_manifests import FormalTaskManifest
from veritool_rl.retail_ops.domain.bundle import LoadedRetailOpsBundle
from veritool_rl.retail_ops.domain.formal_tasks import FormalTaskRecord
from veritool_rl.retail_ops.evaluate.base_evaluation import (
    _ID_PLACEHOLDER,
    _SHA256_PATTERN,
    BaseEvaluationConfig,
    BaseRunEvidence,
    _evidence_complete,
    _finalize_evidence,
    _require_backend_matches_pin,
    measure_dev_run,
    publish_run_evidence,
    require_dev_evaluation_preconditions,
    write_run_artifacts,
)

_ADAPTER_SUBDIR = "adapter"


class AdapterArtifact(StrictModel):
    """锁定的本地 LoRA adapter 身份；逐文件 SHA-256 才是真正的防篡改依据。

    `run_dir` 是产出该 adapter 的训练运行目录（项目相对路径），只用于定位和
    可追溯性——真正判定"是不是这个 adapter"的是 `file_sha256`，配合
    `verify_local_model_files` 的"清单外文件/子目录/符号链接一律拒绝"。
    """

    model_config = ConfigDict(frozen=True)

    run_dir: str = Field(min_length=1)
    file_sha256: dict[str, str]

    @field_validator("run_dir")
    @classmethod
    def validate_run_dir(cls, value: str) -> str:
        validate_project_relative_path(value, "adapter.run_dir")
        return value

    @field_validator("file_sha256")
    @classmethod
    def validate_file_sha256(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            msg = "adapter.file_sha256 不得为空"
            raise ValueError(msg)
        for name, digest in value.items():
            if not name or name in {".", ".."} or "/" in name or "\\" in name:
                msg = f"adapter.file_sha256 文件名必须是安全的单一路径片段: {name!r}"
                raise ValueError(msg)
            if _SHA256_PATTERN.fullmatch(digest) is None:
                msg = f"adapter.file_sha256 摘要必须是 SHA-256: {name}"
                raise ValueError(msg)
        return value

    @property
    def adapter_dir(self) -> Path:
        return Path(self.run_dir) / _ADAPTER_SUBDIR

    @property
    def identity(self) -> str:
        """用于 policy_id 的短标识：训练运行目录 + adapter 权重摘要前 12 位。"""
        weights = sorted(
            digest for name, digest in self.file_sha256.items() if name.endswith(".safetensors")
        )
        digest = weights[0] if weights else sorted(self.file_sha256.values())[0]
        return f"{self.run_dir}#{digest[:12]}"


class CandidateEvaluationConfig(BaseEvaluationConfig):
    """候选运行的冻结契约：与 base 完全相同，外加一个必填 adapter pin。

    继承而非新增可选字段，保证 base 的 `config_sha256` 口径不变；候选自己的
    `config_sha256` 因为多了 adapter 而必然不同，这正是我们想要的区分。
    """

    adapter: AdapterArtifact


class CandidateRunEvidence(BaseRunEvidence):
    """候选运行证据；`adapter` 必填，因此 base 的严格模型无法加载它，反之亦然。"""

    schema_version: Literal["1.1"] = "1.1"  # type: ignore[assignment]
    adapter: AdapterArtifact


def evaluate_formal_dev_candidate(
    records: Sequence[FormalTaskRecord],
    public_manifest: FormalTaskManifest,
    backend: GenerationBackend,
    config: CandidateEvaluationConfig,
    *,
    bundle: LoadedRetailOpsBundle,
    models_root: Path,
    private_root: Path,
    attempt_id: str,
    public_report_path: Path,
    hardware_provider: HardwareProvider,
    inference_engine: Literal["transformers", "vllm"] | None = None,
    runtime_env_sha256: str | None = None,
) -> CandidateRunEvidence:
    """在 60 条已验证 dev 记录上跑一次候选评测，前置守卫与 base 逐条相同。

    adapter 与 base 模型一样先逐文件哈希校验，且发生在任何产物落盘之前；随后
    要求生成后端确实挂载了**同一个** adapter 目录——否则证据会声称评测了候选而
    实际跑的是 base。完整轨迹只写私有 attempt 目录，公开报告只含聚合指标。
    """
    private_target, model_dir = require_dev_evaluation_preconditions(
        records,
        public_manifest,
        config,
        bundle=bundle,
        models_root=models_root,
        private_root=private_root,
        attempt_id=attempt_id,
        public_report_path=public_report_path,
        private_subdir="dev-candidate",
    )
    adapter_dir = config.adapter.adapter_dir
    verify_local_model_files(adapter_dir, config.adapter.file_sha256)
    _require_backend_matches_pin(backend, model_dir, config, expected_adapter=adapter_dir)

    run = measure_dev_run(
        records,
        public_manifest,
        backend,
        config,
        bundle=bundle,
        hardware_provider=hardware_provider,
        policy_id=(
            f"{config.model.repo}@{config.model.revision}+adapter:{config.adapter.identity}"
        ),
    )

    def build(staging: Path) -> CandidateRunEvidence:
        artifact_sha256 = write_run_artifacts(
            staging, run.run_config, run.trajectories, run.metrics
        )
        evidence = _finalize_evidence(
            CandidateRunEvidence(
                run_id=_ID_PLACEHOLDER,
                dataset_version=public_manifest.dataset_version,
                generator_id=public_manifest.generator_id,
                bundle_id=public_manifest.bundle_id,
                bundle_version=public_manifest.bundle_version,
                bundle_sha256=public_manifest.bundle_sha256,
                parser_id=public_manifest.parser_id,
                evaluator_id=public_manifest.evaluator_id,
                dev_manifest_sha256=run.manifest_sha256,
                dev_artifact_sha256=public_manifest.artifact_sha256,
                system_prompt_sha256=run.prompt_sha256,
                tool_schema_sha256=run.tools_sha256,
                config_sha256=config.config_sha256,
                code_commit=config.code_commit,
                uv_lock_sha256=config.uv_lock_sha256,
                policy_id=run.policy_id,
                model=config.model,
                adapter=config.adapter,
                generation=config.generation,
                hardware=run.hardware,
                task_count=len(run.trajectories),
                category_counts=run.category_counts,
                metrics=run.metrics,
                replayable_count=run.replayed,
                evidence_complete=_evidence_complete(run.trajectories, run.replayed),
                artifact_sha256=artifact_sha256,
                inference_engine=inference_engine,
                runtime_env_sha256=runtime_env_sha256,
            ),
            "run_id",
        )
        write_json(staging / "run.json", evidence.model_dump(mode="json"))
        return evidence

    return publish_run_evidence(
        private_target=private_target,
        public_report_path=public_report_path,
        build=build,
    )


def load_candidate_run_evidence(
    path: Path, *, verify_artifacts: bool = True
) -> CandidateRunEvidence:
    """读取候选证据并重算 run_id；默认同时校验同目录全部产物哈希。"""
    from veritool_rl.retail_ops.evaluate.base_evaluation import _content_id, _verify_artifact_hashes

    evidence = CandidateRunEvidence.model_validate_json(path.read_text(encoding="utf-8"))
    if _content_id(evidence, "run_id") != evidence.run_id:
        msg = "candidate 评测证据 run_id 不匹配"
        raise ValueError(msg)
    if verify_artifacts:
        _verify_artifact_hashes(path.parent, evidence.artifact_sha256)
    return evidence


# ---------------------------------------------------------------------------
# base ↔ candidate 配对比较
# ---------------------------------------------------------------------------


class ComparisonError(ValueError):
    """两次运行的评测契约不一致，配对比较无效。"""


#: 两次运行必须逐字段相同才允许比较——任何一项不同，delta 都不再归因于 adapter。
PAIRING_FIELDS = (
    "dataset_version",
    "generator_id",
    "bundle_id",
    "bundle_version",
    "bundle_sha256",
    "parser_id",
    "evaluator_id",
    "seed",
    "max_steps",
    "dev_manifest_sha256",
    "dev_artifact_sha256",
    "system_prompt_sha256",
    "tool_schema_sha256",
    "split",
    "purpose",
)


@dataclass(frozen=True)
class MetricDelta:
    base: float
    candidate: float
    delta: float


@dataclass(frozen=True)
class DevRunComparison:
    """一次 base↔candidate 的配对比较结果；只在契约完全一致时才会被构造出来。"""

    base_run_id: str
    candidate_run_id: str
    task_count: int
    deltas: dict[str, MetricDelta]
    base_generation: dict[str, Any]
    candidate_generation: dict[str, Any]


def compare_dev_runs(
    base: BaseRunEvidence,
    candidate: CandidateRunEvidence,
) -> DevRunComparison:
    """在证明两次运行契约完全一致后，给出逐指标 base→candidate 差值。

    只做算术，不做发布判定：GO/NO-GO 属于 release 门禁，不在这里。契约不一致
    时直接抛错而不是给出带警告的 delta——一个"看起来能用"的无效比较比没有比较
    更危险，它会被直接抄进报告。
    """
    if not isinstance(candidate, CandidateRunEvidence):
        msg = "candidate 位置必须是候选运行证据（含 adapter pin）"
        raise ComparisonError(msg)
    if isinstance(base, CandidateRunEvidence):
        msg = "base 位置必须是 base 运行证据，收到的是候选证据"
        raise ComparisonError(msg)

    for field in PAIRING_FIELDS:
        base_value = getattr(base, field)
        candidate_value = getattr(candidate, field)
        if base_value != candidate_value:
            msg = f"配对字段 {field} 不一致：base={base_value!r} candidate={candidate_value!r}"
            raise ComparisonError(msg)
    if base.model != candidate.model:
        msg = "配对字段 model 不一致：候选必须跑在与 base 相同的已锁定基座模型上"
        raise ComparisonError(msg)
    if base.generation != candidate.generation:
        msg = "配对字段 generation 不一致：两次运行必须使用相同的生成预算与参数"
        raise ComparisonError(msg)
    if base.task_count != candidate.task_count:
        msg = f"任务数不一致：base={base.task_count} candidate={candidate.task_count}"
        raise ComparisonError(msg)

    shared = sorted(
        name
        for name, value in base.metrics.items()
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isinstance(candidate.metrics.get(name), (int, float))
        and not isinstance(candidate.metrics.get(name), bool)
    )
    deltas = {
        name: MetricDelta(
            base=float(base.metrics[name]),
            candidate=float(candidate.metrics[name]),
            delta=float(candidate.metrics[name]) - float(base.metrics[name]),
        )
        for name in shared
    }
    return DevRunComparison(
        base_run_id=base.run_id,
        candidate_run_id=candidate.run_id,
        task_count=base.task_count,
        deltas=deltas,
        base_generation=base.generation.model_dump(mode="json"),
        candidate_generation=candidate.generation.model_dump(mode="json"),
    )
