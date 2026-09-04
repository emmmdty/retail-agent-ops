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
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import ConfigDict, Field, field_validator, model_validator

from veritool_rl.core.agent.qwen import (
    GenerationBackend,
    GenerationSettings,
    HardwareProvider,
    QwenPolicy,
    derive_merged_revision,
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
    _content_sha256,
    _evidence_complete,
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

#: findings #7：与 `BaseEvaluationConfig.max_steps` 单源绑定，改步数预算只需改
#: config 的 Literal 一处；冻结数据集那一路由 `_require_step_budget` 运行时校验。
_MAX_STEPS = BaseEvaluationConfig.model_fields["max_steps"].default
_SEALED_EVIDENCE_DIR = "sealed-eval"


class DeploymentForm(StrEnum):
    """候选**以什么形态被评测**——这是 v1.1 才有的概念。

    v1.0 只能表达两种情形，且靠 `adapter` 是否为 None 隐式区分。第三次观测
    （LOG-20260815-03）证明这个假设不够用：把 adapter 合并回基座之后，模型既没有
    adapter、又不是原来的那份权重，于是一个 120/120、门禁算术全过的部署形态**结构上
    拿不到判定**。形态因此升为显式字段。
    """

    BASE = "base"
    BASE_PLUS_ADAPTER = "base_plus_adapter"
    MERGED = "merged"


class MergedProvenance(StrictModel):
    """合并权重的血统：它由哪个基座和哪个 adapter 合成。

    `merged_revision` **必须可复算**——`derive_merged_revision` 用「基座 revision +
    adapter 逐文件哈希」确定性导出它。自己声明一个标识等于没有证明；可复算才让
    "这份权重来自那对输入"成为可验证的事实，也才让合并候选能靠**血统**而不是
    **同一性**与 base 配对。
    """

    model_config = ConfigDict(frozen=True)

    base_repo: str = Field(pattern=r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
    base_revision: str = Field(pattern=r"^[0-9a-f]{7,64}$")
    adapter_file_sha256: dict[str, str]
    merged_revision: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_derived_identity(self) -> Self:
        expected = derive_merged_revision(self.base_revision, self.adapter_file_sha256)
        if self.merged_revision != expected:
            msg = (
                "merged_revision 必须等于由基座 revision 与 adapter 哈希导出的派生标识："
                f"声明 {self.merged_revision}，复算 {expected}"
            )
            raise ValueError(msg)
        return self


class SealedEvaluationConfig(BaseEvaluationConfig):
    """sealed holdout 运行的冻结契约：与 dev base 完全相同，外加一个可选 adapter。

    与 dev 侧刻意不同的一点：这里的 `adapter` 是**可选**的。同一条 sealed 通道要
    同时承载 base（`adapter=None`）与 candidate（`adapter` 必填）两次运行，两次
    必须经过逐条相同的守卫，否则 release 门禁的 delta 就建立在不同的验证强度上。
    base/candidate 的区分由 `require_comparable_sealed_runs` 显式断言，而不是靠
    两个类型——sealed 报告是对外的单一 allowlist schema，不宜分裂成两个版本。

    **R8 起加 `inference_engine` / `runtime_env_sha256`**（与 `BaseRunEvidence`
    同构）：封存 holdout 路径是唯一产生 GO/NO-GO 判定的路径，此前只哈希
    `uv.lock` 文件、不哈希实际装的包——"换个 venv 跑评测，证据仍逐字段声称用的
    是冻结依赖"这个洞在发布判定那条路径上开着（R8 第一轮独立审查 A4）。给出它
    即进入 v1.2 语义：报告会带上这两个字段并参与自哈希。
    """

    adapter: AdapterArtifact | None = None
    #: 声明本次运行的模型是"某个基座 + 某个 adapter"合并而来。给出它即进入 v1.1
    #: 语义：报告会带上 `deployment_form=merged` 与可复算的血统。
    merged_from: MergedProvenance | None = None
    #: 真正跑这次评测的推理引擎。给出它即进入 v1.2 语义（见 _schema_version）。
    inference_engine: Literal["transformers", "vllm"] | None = None
    #: 实际安装包集合的摘要，见 `current_runtime_env_sha256`。
    runtime_env_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _runtime_provenance_is_all_or_nothing(self) -> SealedEvaluationConfig:
        """要么两个都记，要么都不记——与 `BaseRunEvidence` 同构。"""
        recorded = [self.inference_engine is not None, self.runtime_env_sha256 is not None]
        if any(recorded) and not all(recorded):
            msg = "inference_engine 与 runtime_env_sha256 必须同时记录或同时缺失"
            raise ValueError(msg)
        return self


class SealedEvaluationReport(StrictModel):
    """sealed holdout 运行的公开 allowlist 报告。

    字段集合是固定白名单：只有聚合指标、运行 provenance 和失败 taxonomy 计数。
    这里不存在 task/family 标识、任何 opaque 指纹、prompt、真值或逐任务失败样例。

    `model`/`adapter`/`generation`/`hardware`/`config_sha256`/`code_commit`/
    `uv_lock_sha256` 是**配对可比性**所必需的：没有它们，两份只在基座模型或生成
    参数上不同的报告在字段级完全一致，release 门禁会把环境差异当成 adapter 效果。
    这些字段只描述模型与运行环境，不含任何任务侧信息，因此不破坏 allowlist 语义。
    """

    schema_version: Literal["1.0", "1.1", "1.2"] = "1.0"
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

    #: 以下两个字段自 v1.1 起存在。**它们不进 v1.0 报告的自哈希**（见
    #: `SEALED_V1_0_FIELDS` 与 `_sealed_content_id`），因此加上它们不会作废任何一份
    #: 已产出的证据——这正是这次扩展能做的唯一前提。
    deployment_form: DeploymentForm | None = None
    merged_from: MergedProvenance | None = None

    #: 以下两个字段自 v1.2 起存在（R8 第一轮独立审查 A4）。**它们不进 v1.0 / v1.1
    #: 报告的自哈希**——这是这次扩展能做的唯一前提，与 v1.1 那次同构。封存路径
    #: 此前只哈希 `uv.lock` 文件、不哈希实际装的包，"换个 venv 跑评测"这个洞
    #: 在发布判定那条路径上开着；这两个字段把它补上。
    inference_engine: Literal["transformers", "vllm"] | None = None
    runtime_env_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    _validate_json_fields = field_validator("metrics")(validate_json_value)

    @model_validator(mode="after")
    def validate_form_matches_version_and_artifacts(self) -> Self:
        """形态、版本与产物三者必须自洽，否则报告在描述一个不存在的东西。"""
        # 先做 all-or-nothing 检查（与 BaseRunEvidence 同构）——这必须在版本检查之前，
        # 否则 v1.2 + 半份记录会被"v1.2 必须显式声明"抓住，掩盖了更基础的"半份记录"问题
        recorded = [self.inference_engine is not None, self.runtime_env_sha256 is not None]
        if any(recorded) and not all(recorded):
            msg = "inference_engine 与 runtime_env_sha256 必须同时记录或同时缺失"
            raise ValueError(msg)
        if self.schema_version == "1.0":
            if self.deployment_form is not None or self.merged_from is not None:
                raise ValueError("v1.0 sealed 报告不得声明 deployment_form / merged_from")
            if self.inference_engine is not None or self.runtime_env_sha256 is not None:
                raise ValueError("v1.0 sealed 报告不得声明 inference_engine / runtime_env_sha256")
            return self
        if self.schema_version == "1.1" and (
            self.inference_engine is not None or self.runtime_env_sha256 is not None
        ):
            # v1.1 不含运行时溯源语义；声明它是自相矛盾
            raise ValueError("v1.1 sealed 报告不得声明 inference_engine / runtime_env_sha256")
        if self.schema_version == "1.2":
            # v1.2 必须显式声明运行时溯源——这是它升版本的全部理由
            if self.inference_engine is None or self.runtime_env_sha256 is None:
                raise ValueError(
                    "v1.2 sealed 报告必须显式声明 inference_engine 与 runtime_env_sha256"
                )
            # v1.2 同时也必须声明 deployment_form（继承自 v1.1 的语义）
            if self.deployment_form is None:
                raise ValueError("v1.2 sealed 报告必须显式声明 deployment_form")
        if self.deployment_form is None:
            raise ValueError("v1.1 起 sealed 报告必须显式声明 deployment_form")
        if self.deployment_form is DeploymentForm.MERGED:
            if self.merged_from is None:
                raise ValueError("merged 形态必须携带 merged_from 血统")
            if self.adapter is not None:
                raise ValueError("merged 形态不得同时声明 adapter——合并后已经没有 adapter")
        elif self.merged_from is not None:
            raise ValueError("只有 merged 形态才能携带 merged_from")
        if self.deployment_form is DeploymentForm.BASE_PLUS_ADAPTER and self.adapter is None:
            raise ValueError("base_plus_adapter 形态必须声明 adapter")
        if self.deployment_form is DeploymentForm.BASE and self.adapter is not None:
            raise ValueError("base 形态不得声明 adapter")
        return self

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
    trajectories, replayed = execute_formal_records(
        records, bundle, policy, receipt.seed, episode_timeout=config.episode_timeout
    )
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
        report = _finalize_sealed(
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
                deployment_form=_deployment_form(config),
                merged_from=config.merged_from,
                inference_engine=config.inference_engine,
                runtime_env_sha256=config.runtime_env_sha256,
                schema_version=_schema_version(config),
            ),
        )
        write_json(staging / "report.json", _serialize_sealed_report(report))
        return report

    return publish_run_evidence(
        private_target=private_target,
        public_report_path=public_report_path,
        build=build,
        serialize=_serialize_sealed_report,
    )


def _policy_id(config: SealedEvaluationConfig) -> str:
    """与 dev 侧同口径的策略标识：基座身份，候选另附 adapter 身份。"""
    base = f"{config.model.repo}@{config.model.revision}"
    if config.adapter is None:
        return base
    return f"{base}+adapter:{config.adapter.identity}"


#: v1.0 报告的字段集合。**这是那七份已产出证据的哈希输入，逐字冻结。**
#:
#: `report_id` 是全字段自哈希，因此任何新字段都会改变旧报告的复算结果、使它们永久
#: 加载失败——LOG-20260810-02 说的"再改即作废"指的就是这件事。版本感知的内容哈希
#: 把"新增字段"与"作废旧证据"解耦：v1.0 报告只按这份集合复算。
SEALED_V1_0_FIELDS = frozenset(
    {
        "schema_version",
        "report_id",
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
        "policy_id",
        "max_steps",
        "task_count",
        "category_counts",
        "holdout_artifact_sha256",
        "holdout_receipt_sha256",
        "system_prompt_sha256",
        "tool_schema_sha256",
        "config_sha256",
        "code_commit",
        "uv_lock_sha256",
        "model",
        "adapter",
        "generation",
        "hardware",
        "metrics",
        "failure_type_counts",
        "failure_category_counts",
        "failure_last_error_counts",
        "failure_violation_counts",
        "replayable_count",
        "evidence_complete",
        "private_artifact_sha256",
    }
)

#: 各 schema 版本参与自哈希的字段集合。新增版本时只能**追加**条目，
#: 已有版本的集合一个字都不能改——改了就等于宣布那一版的全部证据无效。
SEALED_HASHED_FIELDS: dict[str, frozenset[str]] = {
    "1.0": SEALED_V1_0_FIELDS,
    "1.1": SEALED_V1_0_FIELDS | {"deployment_form", "merged_from"},
    # R8：v1.2 起把运行时溯源计入自哈希。封存路径此前只哈希 `uv.lock` 文件、
    # 不哈希实际装的包——"换个 venv 跑评测，证据仍逐字段声称用的是冻结依赖"
    # 这个洞在发布判定那条路径上开着（第一轮独立审查 A4）。v1.2 把它补上。
    "1.2": SEALED_V1_0_FIELDS
    | {"deployment_form", "merged_from", "inference_engine", "runtime_env_sha256"},
}


def _finalize_sealed(report: SealedEvaluationReport) -> SealedEvaluationReport:
    """用版本感知的内容哈希回填 `report_id`。"""
    return report.model_copy(update={"report_id": sealed_content_id(report)})


def _schema_version(config: SealedEvaluationConfig) -> Literal["1.0", "1.1", "1.2"]:
    """只有需要新版本才有的语义时才升版本。

    默认停在 v1.0：升版本会改变 `report_id` 的计算口径，而 base 与 candidate 两侧
    必须用同一口径才能配对。让"合并候选"和"运行时溯源"这两个真实需求驱动版本，
    而不是让版本号随代码演进自动漂移。

    R8 新增 v1.2 触发条件：`config.inference_engine` 不为 None。这强制新报告
    主动声明它跑在哪个引擎、哪个环境，否则升不上 v1.2——而停留在 v1.0/v1.1
    的报告看不到这两个字段，旧证据复算逐位不变。
    """
    if config.merged_from is not None:
        # 合并候选 + 运行时溯源：v1.2（v1.1 的所有语义 + 运行时溯源）
        if config.inference_engine is not None:
            return "1.2"
        return "1.1"
    if config.inference_engine is not None:
        return "1.2"
    return "1.0"


def _deployment_form(config: SealedEvaluationConfig) -> DeploymentForm | None:
    if config.merged_from is None:
        return None
    return DeploymentForm.MERGED


def sealed_content_id(report: SealedEvaluationReport) -> str:
    """按报告**自身声明的 schema 版本**复算 report_id。

    与通用的 `_content_id` 的差别只有一处：它先把 payload 投影到该版本的字段集合上。
    v1.0 报告因此看不到 v1.1 才有的字段，复算结果与它当初落盘时逐位相同。
    """
    allowed = SEALED_HASHED_FIELDS[report.schema_version]
    payload = report.model_dump(mode="json")
    projected = {
        key: value
        for key, value in payload.items()
        if key in allowed and key not in {"report_id", "schema_version"}
    }
    return _content_sha256(projected)


def _serialize_sealed_report(report: SealedEvaluationReport) -> dict[str, Any]:
    """序列化时只暴露**该 schema 版本该有**的字段。

    与 `sealed_content_id` 同一个 allowlist 投影，但保留 `schema_version` 和
    `report_id`。这是 allowlist 的真正语义：v1.0 报告的公开 payload 不该
    出现 v1.1/v1.2 才有的字段（即使值是 None），否则下游消费者会看到一个
    "声称是 v1.0 却带新字段"的自相矛盾的报告。

    历史上（v1.0 报告磁盘产物）这一点靠"字段还没加进 model"自然成立；自 v1.1
    起字段加进 model 但默认 None，必须靠主动投影才能保住 allowlist 语义。
    """
    allowed = SEALED_HASHED_FIELDS[report.schema_version] | {"schema_version", "report_id"}
    payload = report.model_dump(mode="json")
    return {key: value for key, value in payload.items() if key in allowed}


#: 两份 sealed 报告必须逐字段相同才允许配对——任何一项不同，delta 都不再归因于候选。
#:
#: **`schema_version` 刻意不在其中。** 它描述的是**报告格式**，不是实验条件：两次运行
#: 只要 `code_commit`、`uv_lock_sha256`、模型、生成参数、数据集、receipt、prompt、
#: 工具 schema 全部相同，就是在同一条件下跑的，序列化成哪一版报告不改变这一点。
#:
#: 把它当作配对字段会产生一个更糟的性质：**每次 schema 升级都要重跑 base 侧**——
#: 为一次序列化格式变更烧掉一次封存 holdout 观测。这是 2026-08-15 让合并候选
#: （v1.1）与基座（v1.0）配对时暴露出来的。
#:
#: 跨版本配对的健全性由另一条更强的约束保证：`SEALED_HASHED_FIELDS` 只能**追加**，
#: 旧版本的字段集合必须是新版本的子集——由 `_require_compatible_schema_versions`
#: 逐对校验，并由测试对整张表做一次结构性断言。
SEALED_PAIRING_FIELDS = (
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


def _candidate_form(report: SealedEvaluationReport) -> DeploymentForm:
    """报告没有显式声明形态时（v1.0），从 `adapter` 推断——那正是 v1.0 的原语义。"""
    if report.deployment_form is not None:
        return report.deployment_form
    return DeploymentForm.BASE_PLUS_ADAPTER if report.adapter is not None else DeploymentForm.BASE


def _require_compatible_schema_versions(
    base: SealedEvaluationReport,
    candidate: SealedEvaluationReport,
) -> None:
    """两侧的报告格式必须是**可嵌套**的——较旧那一版的字段集合是较新那一版的子集。

    这是允许跨 schema 版本配对的全部依据。如果将来某一版**改变**了某个字段的含义
    而不是追加新字段，这条断言会立刻失败，跨版本配对随之被禁止——正是应有的行为。
    """
    for report, label in ((base, "base"), (candidate, "candidate")):
        if report.schema_version not in SEALED_HASHED_FIELDS:
            msg = f"{label} 报告的 schema_version 未知：{report.schema_version}"
            raise ComparisonError(msg)
    older, newer = sorted((base.schema_version, candidate.schema_version))
    if not SEALED_HASHED_FIELDS[older] <= SEALED_HASHED_FIELDS[newer]:
        msg = (
            f"sealed 报告 schema {older} 与 {newer} 不可嵌套，"
            "跨版本配对会把字段含义的变化当成模型效果"
        )
        raise ComparisonError(msg)


def _require_valid_forms(
    base: SealedEvaluationReport,
    candidate: SealedEvaluationReport,
) -> None:
    if _candidate_form(base) is not DeploymentForm.BASE:
        msg = "base 位置必须是未挂 adapter、未合并的基座 sealed 报告"
        raise ComparisonError(msg)
    if _candidate_form(candidate) is DeploymentForm.BASE:
        msg = "candidate 位置必须是候选形态（base_plus_adapter 或 merged）的 sealed 报告"
        raise ComparisonError(msg)


def _require_merged_lineage(
    base: SealedEvaluationReport,
    candidate: SealedEvaluationReport,
) -> None:
    """合并候选靠**血统**而不是同一性与 base 配对。

    它的 `model` 与 base **必然不同**——合并产物就是另一份权重。可比性因此建立在
    两条可验证的事实上：(1) 它声明的基座就是 base 那一侧实际跑的那个模型；
    (2) 它的 `model.revision` 等于由「基座 revision + adapter 哈希」复算出的派生标识。
    第二条让"这份权重确实由那对输入合成"无法被一句声明蒙混过去。
    """
    lineage = candidate.merged_from
    if lineage is None:
        msg = "merged 候选缺少 merged_from 血统"
        raise ComparisonError(msg)
    if lineage.base_repo != base.model.repo or lineage.base_revision != base.model.revision:
        msg = (
            "merged 候选的血统与 base 不符："
            f"声明基座 {lineage.base_repo}@{lineage.base_revision}，"
            f"base 侧实际是 {base.model.repo}@{base.model.revision}"
        )
        raise ComparisonError(msg)
    if candidate.model.revision != lineage.merged_revision:
        msg = (
            "merged 候选的 model.revision 必须等于其派生标识："
            f"model {candidate.model.revision}，血统 {lineage.merged_revision}"
        )
        raise ComparisonError(msg)


def require_comparable_sealed_runs(
    base: SealedEvaluationReport,
    candidate: SealedEvaluationReport,
) -> None:
    """证明两份 sealed 报告确实跑在同一条件下，否则拒绝把它们放进发布门禁。

    契约不一致时直接抛错而不是给出带警告的 delta：一个"看起来能用"的无效比较
    比没有比较更危险，它会被直接抄进发布报告。这里只校验可比性，不做 GO/NO-GO
    判定——发布判定属于 release 门禁。
    """
    _require_compatible_schema_versions(base, candidate)
    _require_valid_forms(base, candidate)

    for field in SEALED_PAIRING_FIELDS:
        base_value = getattr(base, field)
        candidate_value = getattr(candidate, field)
        if base_value != candidate_value:
            msg = f"配对字段 {field} 不一致：base={base_value!r} candidate={candidate_value!r}"
            raise ComparisonError(msg)
    if _candidate_form(candidate) is DeploymentForm.MERGED:
        _require_merged_lineage(base, candidate)
    elif base.model != candidate.model:
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
    if sealed_content_id(report) != report.report_id:
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
