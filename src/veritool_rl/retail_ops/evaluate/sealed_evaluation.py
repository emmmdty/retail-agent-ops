"""RetailOps R2 sealed formal holdout evaluator contract.

唯一入口 `evaluate_authorized_holdout` 只接受 `AuthorizedFormalHoldout`——
该能力对象只能由 release 目的的两段式授权签发，因此这里不存在任何开发用途
的 holdout 入口。完整轨迹与逐任务证据只写入授权时使用的受信私有根，公开侧
只输出固定 allowlist 的聚合指标、运行 provenance 和失败 taxonomy 计数。

评测机器（路径防护、staging 原子发布、产物哈希、episode/replay 执行）与
`base_evaluation` 共享同一份实现，模块私有名的跨模块复用沿用本包既有约定
（参见 `formal_governance` 复用 `formal_manifests._parse_and_validate_private_rows`）。
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator

from veritool_rl.core.agent.qwen import (
    GenerationBackend,
    GenerationSettings,
    HardwareProvider,
    QwenPolicy,
    verify_local_model_files,
)
from veritool_rl.core.agent.runner import SYSTEM_PROMPT
from veritool_rl.core.artifacts import write_json
from veritool_rl.core.metrics import compute_metrics
from veritool_rl.core.trajectory.schema import StrictModel, validate_json_value
from veritool_rl.retail_ops.domain.bundle import LoadedRetailOpsBundle
from veritool_rl.retail_ops.domain.formal_tasks import FormalTaskRecord
from veritool_rl.retail_ops.evaluate.base_evaluation import (
    _ID_PLACEHOLDER,
    BASE_ARTIFACT_NAMES,
    BaseEvaluationConfig,
    HardwareProvenance,
    ModelArtifact,
    _category_counts,
    _content_id,
    _content_sha256,
    _evidence_complete,
    _finalize_evidence,
    _rate,
    _require_backend_matches_pin,
    _require_matching_bundle,
    _resolve_within,
    _text_sha256,
    _tool_schema_sha256,
    _validate_artifact_hashes,
    _validate_output_pair,
    _validate_path_component,
    _verify_artifact_hashes,
    execute_formal_records,
    publish_run_evidence,
    write_run_artifacts,
)
from veritool_rl.retail_ops.evaluate.candidate_evaluation import (
    AdapterArtifact,
    ComparisonError,
)
from veritool_rl.retail_ops.evaluate.evaluation import redact_failure_rows
from veritool_rl.retail_ops.release.formal_governance import (
    AuthorizedFormalHoldout,
    load_authorized_formal_holdout,
)

# sealed 评测写出与 dev base 完全相同的四份私有产物。
SEALED_ARTIFACT_NAMES = BASE_ARTIFACT_NAMES

_MAX_STEPS = 5
_SEALED_EVIDENCE_DIR = "sealed-eval"


class SealedEvaluationConfig(BaseEvaluationConfig):
    """sealed holdout 运行的冻结契约：与 dev base 完全相同，外加一个可选 adapter。

    与 dev 侧刻意不同的一点：这里的 `adapter` 是**可选**的。同一条 sealed 通道要
    同时承载 base（`adapter=None`）与 candidate（`adapter` 必填）两次运行，两次
    必须经过逐条相同的守卫，否则 release 门禁的 delta 就建立在不同的验证强度上。
    base/candidate 的区分由 `require_comparable_sealed_runs` 显式断言，而不是靠
    两个类型——sealed 报告是对外的单一 allowlist schema，不宜分裂成两个版本。
    """

    adapter: AdapterArtifact | None = None


class SealedEvaluationReport(StrictModel):
    """sealed holdout 运行的公开 allowlist 报告。

    字段集合是固定白名单：只有聚合指标、运行 provenance 和失败 taxonomy 计数。
    这里不存在 task/family 标识、任何 opaque 指纹、prompt、真值或逐任务失败样例。

    `model`/`adapter`/`generation`/`hardware`/`config_sha256`/`code_commit`/
    `uv_lock_sha256` 是**配对可比性**所必需的：没有它们，两份只在基座模型或生成
    参数上不同的报告在字段级完全一致，release 门禁会把环境差异当成 adapter 效果。
    这些字段只描述模型与运行环境，不含任何任务侧信息，因此不破坏 allowlist 语义。
    """

    schema_version: Literal["1.0"] = "1.0"
    report_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    purpose: Literal["release"] = "release"
    split: Literal["holdout"] = "holdout"
    dataset_version: str = Field(min_length=1)
    generator_id: str = Field(min_length=1)
    bundle_id: str = Field(min_length=1)
    bundle_version: str = Field(min_length=1)
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_id: str = Field(min_length=1)
    evaluator_id: str = Field(min_length=1)
    seed: int = Field(ge=0)
    policy_id: str = Field(min_length=1)
    max_steps: Literal[5] = 5
    task_count: int = Field(ge=1)
    category_counts: dict[str, int]
    holdout_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    holdout_receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    system_prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tool_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    uv_lock_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model: ModelArtifact
    adapter: AdapterArtifact | None = None
    generation: GenerationSettings
    hardware: HardwareProvenance
    metrics: dict[str, Any]
    failure_type_counts: dict[str, int]
    failure_category_counts: dict[str, int]
    failure_last_error_counts: dict[str, int]
    failure_violation_counts: dict[str, int]
    replayable_count: int = Field(ge=0)
    evidence_complete: bool
    private_artifact_sha256: dict[str, str]

    _validate_json_fields = field_validator("metrics")(validate_json_value)

    @field_validator("private_artifact_sha256")
    @classmethod
    def validate_artifact_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        """产物集合固定，路径不可注入，摘要必须是 SHA-256。"""
        return _validate_artifact_hashes(value, SEALED_ARTIFACT_NAMES)


def evaluate_authorized_holdout(
    authorization: AuthorizedFormalHoldout,
    bundle: LoadedRetailOpsBundle,
    backend: GenerationBackend,
    config: SealedEvaluationConfig,
    *,
    models_root: Path,
    attempt_id: str,
    public_report_path: Path,
    hardware_provider: HardwareProvider,
) -> SealedEvaluationReport:
    """在已授权的 sealed formal holdout 上运行一次评测并写出双侧证据。

    私有证据固定写到授权时使用的 `trusted_private_root` 下的
    `sealed-eval/<attempt_id>/`：调用方无法把完整轨迹重定向到公开路径。
    公开报告只写 `SealedEvaluationReport` 的 allowlist 字段。

    模型与 adapter 在任何产物落盘之前先逐文件哈希校验，随后要求真正跑评测的那个
    后端确实加载了同一份模型/adapter——这条绑定是双向的：base 侧（`config.adapter`
    为 None）拒绝任何带 adapter 的后端，candidate 侧拒绝缺失或不符的 adapter。
    没有它，一份 sealed 证据可能声称评测了候选而实际跑的是基座。
    """
    records = load_authorized_formal_holdout(authorization)
    receipt = authorization.dataset.holdout_receipt
    _require_matching_bundle(bundle, receipt)
    _require_step_budget(records)

    if config.dataset_version != receipt.dataset_version:
        msg = "sealed 评测 config 与 holdout receipt 的 dataset_version 不一致"
        raise ValueError(msg)
    if config.seed != receipt.seed:
        msg = "sealed 评测 config 与 holdout receipt 的 seed 不一致"
        raise ValueError(msg)

    _validate_path_component(attempt_id, label="attempt_id")
    private_target = _resolve_within(
        authorization.trusted_private_root,
        _SEALED_EVIDENCE_DIR,
        attempt_id,
    )
    _validate_output_pair(authorization.trusted_private_root, public_report_path)

    model_dir = _resolve_within(models_root, config.model.local_dir)
    verify_local_model_files(model_dir, config.model.file_sha256)
    adapter_dir: Path | None = None
    if (adapter := config.adapter) is not None:
        adapter_dir = adapter.adapter_dir
        verify_local_model_files(adapter_dir, adapter.file_sha256)
    _require_backend_matches_pin(backend, model_dir, config, expected_adapter=adapter_dir)

    policy = QwenPolicy(backend, _policy_id(config), config.generation.max_new_tokens)
    hardware_provider.reset_peak_memory()
    started = time.perf_counter()
    trajectories, replayed = execute_formal_records(records, bundle, policy, receipt.seed)
    wall_time_seconds = time.perf_counter() - started
    measurement = hardware_provider.measure()

    metrics = compute_metrics(trajectories, config.bootstrap_samples, receipt.seed)
    failure_rows = redact_failure_rows(trajectories)
    hardware = HardwareProvenance(
        gpu=measurement,
        wall_time_seconds=wall_time_seconds,
        tasks_per_second=_rate(len(trajectories), wall_time_seconds),
        output_tokens_per_second=_rate(
            sum(step.output_tokens for trajectory in trajectories for step in trajectory.steps),
            wall_time_seconds,
        ),
    )
    receipt_sha256 = _content_sha256(receipt.model_dump(mode="json"))
    prompt_sha256 = _text_sha256(SYSTEM_PROMPT)
    tools_sha256 = _tool_schema_sha256(bundle)
    run_config = {
        "config": config.model_dump(mode="json"),
        "split": receipt.split,
        "purpose": "release",
        "policy_id": policy.name,
        "max_steps": _MAX_STEPS,
        "bundle_sha256": bundle.bundle_sha256,
        "holdout_artifact_sha256": authorization.artifact_sha256,
        "holdout_receipt_sha256": receipt_sha256,
        "parser_id": receipt.parser_id,
        "system_prompt_sha256": prompt_sha256,
        "tool_schema_sha256": tools_sha256,
    }

    def build(staging: Path) -> SealedEvaluationReport:
        artifact_sha256 = write_run_artifacts(staging, run_config, trajectories, metrics)
        report = _finalize_evidence(
            SealedEvaluationReport(
                report_id=_ID_PLACEHOLDER,
                dataset_version=receipt.dataset_version,
                generator_id=receipt.generator_id,
                bundle_id=receipt.bundle_id,
                bundle_version=receipt.bundle_version,
                bundle_sha256=receipt.bundle_sha256,
                parser_id=receipt.parser_id,
                evaluator_id=receipt.evaluator_id,
                seed=receipt.seed,
                policy_id=policy.name,
                task_count=len(trajectories),
                category_counts=_category_counts(trajectories, receipt),
                holdout_artifact_sha256=authorization.artifact_sha256,
                holdout_receipt_sha256=receipt_sha256,
                system_prompt_sha256=prompt_sha256,
                tool_schema_sha256=tools_sha256,
                config_sha256=config.config_sha256,
                code_commit=config.code_commit,
                uv_lock_sha256=config.uv_lock_sha256,
                model=config.model,
                adapter=config.adapter,
                generation=config.generation,
                hardware=hardware,
                metrics=metrics,
                failure_type_counts=_count_rows(failure_rows, "failure_type"),
                failure_category_counts=_count_rows(failure_rows, "category"),
                failure_last_error_counts=_count_rows(failure_rows, "last_error"),
                failure_violation_counts=_count_violations(failure_rows),
                replayable_count=replayed,
                evidence_complete=_evidence_complete(trajectories, replayed),
                private_artifact_sha256=artifact_sha256,
            ),
            "report_id",
        )
        write_json(staging / "report.json", report.model_dump(mode="json"))
        return report

    return publish_run_evidence(
        private_target=private_target,
        public_report_path=public_report_path,
        build=build,
    )


def _policy_id(config: SealedEvaluationConfig) -> str:
    """与 dev 侧同口径的策略标识：基座身份，候选另附 adapter 身份。"""
    base = f"{config.model.repo}@{config.model.revision}"
    if config.adapter is None:
        return base
    return f"{base}+adapter:{config.adapter.identity}"


#: 两份 sealed 报告必须逐字段相同才允许配对——任何一项不同，delta 都不再归因于 adapter。
SEALED_PAIRING_FIELDS = (
    "schema_version",
    "purpose",
    "split",
    "dataset_version",
    "generator_id",
    "bundle_id",
    "bundle_version",
    "bundle_sha256",
    "parser_id",
    "evaluator_id",
    "seed",
    "max_steps",
    "task_count",
    "category_counts",
    "holdout_artifact_sha256",
    "holdout_receipt_sha256",
    "system_prompt_sha256",
    "tool_schema_sha256",
    "code_commit",
    "uv_lock_sha256",
)


def require_comparable_sealed_runs(
    base: SealedEvaluationReport,
    candidate: SealedEvaluationReport,
) -> None:
    """证明两份 sealed 报告确实跑在同一条件下，否则拒绝把它们放进发布门禁。

    契约不一致时直接抛错而不是给出带警告的 delta：一个"看起来能用"的无效比较
    比没有比较更危险，它会被直接抄进发布报告。这里只校验可比性，不做 GO/NO-GO
    判定——发布判定属于 release 门禁。
    """
    if base.adapter is not None:
        msg = "base 位置必须是未挂 adapter 的基座 sealed 报告"
        raise ComparisonError(msg)
    if candidate.adapter is None:
        msg = "candidate 位置必须是挂载了 adapter 的候选 sealed 报告"
        raise ComparisonError(msg)

    for field in SEALED_PAIRING_FIELDS:
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


def load_sealed_evaluation_report(
    path: Path,
    *,
    verify_artifacts: bool = True,
) -> SealedEvaluationReport:
    """读取 sealed 报告并重算 report_id；默认同时校验同目录私有产物哈希。

    公开侧只有报告副本、没有私有产物，加载公开副本时应显式传入
    `verify_artifacts=False`，不要静默跳过校验。
    """
    report = SealedEvaluationReport.model_validate_json(path.read_text(encoding="utf-8"))
    if _content_id(report, "report_id") != report.report_id:
        msg = "sealed 评测报告 report_id 不匹配"
        raise ValueError(msg)
    if verify_artifacts:
        _verify_artifact_hashes(path.parent, report.private_artifact_sha256)
    return report


def _require_step_budget(records: Sequence[FormalTaskRecord]) -> None:
    for index, record in enumerate(records):
        if record.task.max_steps > _MAX_STEPS:
            msg = f"sealed 评测记录 {index} 的 max_steps 超出冻结预算"
            raise ValueError(msg)


def _count_rows(rows: Sequence[dict[str, Any]], field: str) -> dict[str, int]:
    counts = Counter(str(row.get(field) or "none") for row in rows)
    return dict(sorted(counts.items()))


def _count_violations(rows: Sequence[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts.update(str(violation) for violation in row.get("violations", ()))
    return dict(sorted(counts.items()))
