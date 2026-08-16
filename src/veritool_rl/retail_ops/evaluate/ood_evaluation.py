"""在分布外任务集上评测真实模型。

与封存 holdout 的评测**刻意不共用类型**：那条路径带两段式授权、allowlist 公开报告、
逐次观测记账——因为它的价值来自"很少被看"。分布外集合正相反：它需要被反复读、
被逐类别拆解、被讨论。把两者塞进同一条路径会让治理级别最高的那条被稀释到最低。

共用的只有真正该共用的东西：同一个 `RetailOpsEnv`、同一个 verifier、同一套模型 pin
与后端绑定校验（`_require_backend_matches_pin`）。评测条件因此与 holdout 侧逐字段
可比——否则"OOD 上掉了多少"这句话没有意义。
"""

from __future__ import annotations

import time
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from veritool_rl.core.agent.qwen import (
    GenerationBackend,
    GenerationSettings,
    HardwareProvider,
    QwenPolicy,
    verify_local_model_files,
)
from veritool_rl.core.agent.runner import SYSTEM_PROMPT, run_episode
from veritool_rl.core.artifacts import write_json
from veritool_rl.core.metrics import compute_metrics
from veritool_rl.core.trajectory import TaskSpec, Trajectory
from veritool_rl.core.trajectory.replay import replay_trajectory
from veritool_rl.core.trajectory.schema import StrictModel, validate_json_value
from veritool_rl.retail_ops.build.ood_manifests import OodTaskManifest, load_ood_tasks
from veritool_rl.retail_ops.domain.bundle import LoadedRetailOpsBundle
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
from veritool_rl.retail_ops.domain.ood_tasks import ood_category
from veritool_rl.retail_ops.evaluate.base_evaluation import (
    HardwareProvenance,
    ModelArtifact,
    _content_sha256,
    _finalize_evidence,
    _rate,
    _require_backend_matches_pin,
    _text_sha256,
    _tool_schema_sha256,
)
from veritool_rl.retail_ops.evaluate.candidate_evaluation import AdapterArtifact

_ID_PLACEHOLDER = "0" * 64


class OodEvaluationConfig(StrictModel):
    """分布外评测的运行契约。

    `adapter` 可选，`merged` 也可选：这条路径要同时承载基座、base+adapter 候选与
    合并候选三种形态——正是 R4.5 之后需要横向比较的那三档。
    """

    dataset_version: Literal["retail_ops_ood_v1_20260815"] = "retail_ops_ood_v1_20260815"
    seed: Literal[0] = 0
    model: ModelArtifact
    adapter: AdapterArtifact | None = None
    generation: GenerationSettings
    code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    bootstrap_samples: Literal[1000] = 1000

    @property
    def config_sha256(self) -> str:
        return _content_sha256(self.model_dump(mode="json"))


class OodRunEvidence(StrictModel):
    """分布外评测的完整证据。

    **逐类别指标是这份证据的核心**：整体成功率会把"表达变了就不会了"和
    "遇到做不到的请求就乱调工具"平均掉，而那正是最需要分开看的两件事。
    """

    schema_version: Literal["1.0"] = "1.0"
    run_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_version: str = Field(min_length=1)
    generator_id: str = Field(min_length=1)
    split: Literal["ood"] = "ood"
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    system_prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tool_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    policy_id: str = Field(min_length=1)
    model: ModelArtifact
    adapter: AdapterArtifact | None = None
    generation: GenerationSettings
    hardware: HardwareProvenance
    task_count: int = Field(ge=1)
    metrics: dict[str, Any]
    category_success: dict[str, float]
    category_counts: dict[str, int]
    kind_success: dict[str, float]
    failure_kind_counts: dict[str, int]
    replayable_count: int = Field(ge=0)
    evidence_complete: bool
    #: 与 `BaseRunEvidence` 同义：缺失读作"未记录"，不是 "transformers"。
    #: 取值为 None 时不参与内容哈希，因此已有 OOD 证据复算逐位不变。
    inference_engine: Literal["transformers", "vllm"] | None = None
    runtime_env_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _runtime_provenance_is_all_or_nothing(self) -> OodRunEvidence:
        recorded = [self.inference_engine is not None, self.runtime_env_sha256 is not None]
        if any(recorded) and not all(recorded):
            msg = "inference_engine 与 runtime_env_sha256 必须同时记录或同时缺失"
            raise ValueError(msg)
        return self

    _validate_metrics = field_validator("metrics")(validate_json_value)


def evaluate_ood(
    *,
    config: OodEvaluationConfig,
    bundle: LoadedRetailOpsBundle,
    manifest: OodTaskManifest,
    build_dir: Path,
    models_root: Path,
    output_dir: Path,
    backend_factory: Any,
    hardware_provider: HardwareProvider,
    inference_engine: Literal["transformers", "vllm"] | None = None,
    runtime_env_sha256: str | None = None,
) -> OodRunEvidence:
    """在分布外集合上跑一次评测并写出证据。"""
    if manifest.bundle_sha256 != bundle.bundle_sha256:
        raise ValueError("OOD manifest 与 bundle SHA-256 不匹配")
    tasks = load_ood_tasks(build_dir)
    if len(tasks) != manifest.task_count:
        raise ValueError("OOD 任务数与 manifest 不一致")

    model_dir = models_root / config.model.local_dir
    verify_local_model_files(model_dir, config.model.file_sha256)
    adapter_dir: Path | None = None
    adapter = config.adapter
    if adapter is not None:
        adapter_dir = adapter.adapter_dir
        verify_local_model_files(adapter_dir, adapter.file_sha256)
    backend: GenerationBackend = backend_factory(config, models_root)
    _require_backend_matches_pin(backend, model_dir, config, expected_adapter=adapter_dir)

    policy_id = _policy_id(config)
    policy = QwenPolicy(backend, policy_id, config.generation.max_new_tokens)

    hardware_provider.reset_peak_memory()
    started = time.perf_counter()
    trajectories = [
        run_episode(task, lambda current: RetailOpsEnv(current, bundle), policy, manifest.seed)
        for task in tasks
    ]
    wall_time_seconds = time.perf_counter() - started
    measurement = hardware_provider.measure()

    replayed = sum(
        replay_trajectory(
            trajectory, lambda current: RetailOpsEnv(current, bundle)
        ).matched
        for trajectory in trajectories
    )
    metrics = compute_metrics(trajectories, config.bootstrap_samples, manifest.seed)

    evidence = _finalize_evidence(
        OodRunEvidence(
            run_id=_ID_PLACEHOLDER,
            inference_engine=inference_engine,
            runtime_env_sha256=runtime_env_sha256,
            dataset_version=manifest.dataset_version,
            generator_id=manifest.generator_id,
            bundle_sha256=bundle.bundle_sha256,
            manifest_sha256=_content_sha256(manifest.model_dump(mode="json")),
            system_prompt_sha256=_text_sha256(SYSTEM_PROMPT),
            tool_schema_sha256=_tool_schema_sha256(bundle),
            config_sha256=config.config_sha256,
            code_commit=config.code_commit,
            policy_id=policy_id,
            model=config.model,
            adapter=config.adapter,
            generation=config.generation,
            hardware=HardwareProvenance(
                gpu=measurement,
                wall_time_seconds=wall_time_seconds,
                tasks_per_second=_rate(len(trajectories), wall_time_seconds),
                output_tokens_per_second=_rate(
                    sum(
                        step.output_tokens
                        for trajectory in trajectories
                        for step in trajectory.steps
                    ),
                    wall_time_seconds,
                ),
            ),
            task_count=len(trajectories),
            metrics=metrics,
            category_success=_group_success(trajectories, ood_category),
            category_counts=dict(
                sorted(Counter(ood_category(t.task) for t in trajectories).items())
            ),
            kind_success=_group_success(trajectories, _ood_kind),
            failure_kind_counts=dict(
                sorted(
                    Counter(
                        _ood_kind(t.task) for t in trajectories if not t.success
                    ).items()
                )
            ),
            replayable_count=replayed,
            evidence_complete=replayed == len(trajectories),
        ),
        "run_id",
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "ood-report.json", evidence.model_dump(mode="json"))
    return evidence


def _policy_id(config: OodEvaluationConfig) -> str:
    base = f"{config.model.repo}@{config.model.revision}"
    if config.adapter is None:
        return base
    return f"{base}+adapter:{config.adapter.identity}"


def _ood_kind(task: TaskSpec) -> str:
    kind = task.metadata.get("ood_kind")
    if not isinstance(kind, str):
        raise ValueError("OOD 任务缺少 ood_kind")
    return kind


def _group_success(
    trajectories: list[Trajectory],
    key: Any,
) -> dict[str, float]:
    """按任意分组键计算成功率。整体成功率会把不同失败原因平均掉，逐组才看得见。"""
    totals: Counter[str] = Counter()
    hits: Counter[str] = Counter()
    for trajectory in trajectories:
        group = key(trajectory.task)
        totals[group] += 1
        hits[group] += int(trajectory.success)
    return {group: hits[group] / totals[group] for group in sorted(totals)}
