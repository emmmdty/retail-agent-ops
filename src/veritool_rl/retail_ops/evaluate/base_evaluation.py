"""RetailOps R2 formal dev split loading and Qwen dev-base run evidence.

本模块只服务 `develop` 目的：它固定解析数据版本私有根下的 `dev.jsonl`，
并在公开 dev manifest 的哈希、计数、顺序和五类指纹全部核对通过后才允许评测。
正式 holdout 没有任何经由此处的开发入口——holdout 只能走
`sealed_evaluation.evaluate_authorized_holdout` 的 release 授权路径。
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar

from pydantic import ConfigDict, Field, field_validator, model_validator

from veritool_rl.core.agent.policy import Policy
from veritool_rl.core.agent.qwen import (
    GenerationBackend,
    GenerationSettings,
    GpuMeasurement,
    HardwareProvider,
    QwenPolicy,
    verify_local_model_files,
)
from veritool_rl.core.agent.runner import SYSTEM_PROMPT, run_episode
from veritool_rl.core.artifacts import canonical_json, sha256_file, write_json, write_jsonl
from veritool_rl.core.metrics import compute_metrics
from veritool_rl.core.trajectory import Trajectory
from veritool_rl.core.trajectory.replay import replay_trajectory
from veritool_rl.core.trajectory.schema import StrictModel, validate_json_value
from veritool_rl.retail_ops.build.formal_manifests import (
    _FINGERPRINT_FIELDS,
    _ROW_FINGERPRINT_FIELDS,
    FormalHoldoutReceipt,
    FormalTaskManifest,
    _parse_and_validate_private_rows,
)
from veritool_rl.retail_ops.domain.bundle import LoadedRetailOpsBundle
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
from veritool_rl.retail_ops.domain.formal_tasks import FormalTaskRecord
from veritool_rl.retail_ops.evaluate.evaluation import redact_failure_rows
from veritool_rl.retail_ops.release.governance import EvidencePurpose

BASE_ARTIFACT_NAMES = ("config.json", "trajectories.jsonl", "metrics.json", "failures.jsonl")

_SAFE_COMPONENT_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_DEV_ARTIFACT_NAME = "dev.jsonl"

EvidenceT = TypeVar("EvidenceT", bound=StrictModel)


class ModelArtifact(StrictModel):
    """锁定的本地模型身份；逐文件 SHA-256 才是真正的防篡改依据。

    `repo`/`revision` 只做形状校验，由调用方以配置数据提供——模型 pin 会随
    上游仓库变化，因此不在代码里硬编码任何具体 revision。
    """

    model_config = ConfigDict(frozen=True)

    repo: str = Field(pattern=r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")
    revision: str = Field(pattern=r"^[0-9a-f]{7,64}$")
    local_dir: str = Field(min_length=1)
    file_sha256: dict[str, str]

    @field_validator("local_dir")
    @classmethod
    def validate_local_dir(cls, value: str) -> str:
        """模型目录名必须是受信 models_root 下的单一安全片段。"""
        return _validate_path_component(value, label="model.local_dir")

    @field_validator("file_sha256")
    @classmethod
    def validate_file_sha256(cls, value: dict[str, str]) -> dict[str, str]:
        """文件名不得注入路径分隔符，摘要必须是 SHA-256。"""
        if not value:
            raise ValueError("model.file_sha256 不得为空")
        for name, digest in value.items():
            _validate_path_component(name, label="model.file_sha256 文件名")
            if _SHA256_PATTERN.fullmatch(digest) is None:
                raise ValueError(f"model.file_sha256 摘要必须是 SHA-256: {name}")
        return value


class HardwareProvenance(StrictModel):
    """一次 base 运行的物理 GPU 身份、显存峰值、耗时与吞吐。"""

    model_config = ConfigDict(frozen=True)

    gpu: GpuMeasurement
    wall_time_seconds: float = Field(ge=0.0)
    tasks_per_second: float = Field(ge=0.0)
    output_tokens_per_second: float = Field(ge=0.0)


class BaseEvaluationConfig(StrictModel):
    """dev base 运行的冻结契约：seed 0、五步预算、无采样、非思考、4-bit NF4。

    这里没有 adapter 字段：R2 不存在任何合法的 adapter 调用路径。
    """

    model_config = ConfigDict(frozen=True)

    dataset_version: str = Field(min_length=1)
    seed: Literal[0] = 0
    max_steps: Literal[5] = 5
    model: ModelArtifact
    generation: GenerationSettings
    code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    uv_lock_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bootstrap_samples: Literal[1000] = 1000

    @property
    def config_sha256(self) -> str:
        return _content_sha256(self.model_dump(mode="json"))


class BaseRunEvidence(StrictModel):
    """dev base 运行的完整治理绑定；不含任何 task/family 标识。

    **新增 `inference_engine` / `runtime_env_sha256`。** 二者都可选且默认 `None`，
    并且在**取值为 None 时被排除出内容哈希**（见 `RUNTIME_PROVENANCE_FIELDS` 与
    `_content_id`），因此加上它们不会作废任何一份已产出的证据——这是这次扩展能做的
    唯一前提。

    **刻意不用 `schema_version` 做这件事**：`CandidateRunEvidence` 早已把它当作
    类型判别符（固定 `"1.1"` 以便 base 的严格模型无法加载候选证据，反之亦然），
    再往上叠演进语义会让同一个 `"1.1"` 同时表示两件事，且会改变磁盘上已有候选证据的
    哈希投影。按"值为 None 即视为未记录"来投影没有这个歧义。

    加它们的理由：`uv_lock_sha256` 哈希的是仓库里的 `uv.lock` **文件**而不是实际装了
    什么包，换一个 venv 跑评测它纹丝不动。2026-08-16 的三次 vLLM 评测正是跑在另一个
    环境里的，而证据逐字段声称用的是冻结依赖，**没有任何机制发现得了**。
    """

    schema_version: Literal["1.0"] = "1.0"
    run_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    purpose: Literal["develop"] = "develop"
    split: Literal["dev"] = "dev"
    dataset_version: str = Field(min_length=1)
    generator_id: str = Field(min_length=1)
    bundle_id: str = Field(min_length=1)
    bundle_version: str = Field(min_length=1)
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_id: str = Field(min_length=1)
    evaluator_id: str = Field(min_length=1)
    seed: Literal[0] = 0
    max_steps: Literal[5] = 5
    dev_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dev_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    system_prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tool_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    uv_lock_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_id: str = Field(min_length=1)
    model: ModelArtifact
    generation: GenerationSettings
    hardware: HardwareProvenance
    task_count: int = Field(ge=1)
    category_counts: dict[str, int]
    metrics: dict[str, Any]
    replayable_count: int = Field(ge=0)
    evidence_complete: bool
    artifact_sha256: dict[str, str]
    #: 真正跑这次评测的推理引擎。缺失读作**"未记录"而不是 "transformers"**——
    #: 2026-08-16 之前的证据都没有这个字段，把缺失当成某个具体值就是编造。
    inference_engine: Literal["transformers", "vllm"] | None = None
    #: 实际安装包集合的摘要，见 `current_runtime_env_sha256`。
    runtime_env_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _runtime_provenance_is_all_or_nothing(self) -> BaseRunEvidence:
        """要么两个都记，要么都不记。

        只记一个会产生一份"说了一半"的证据：知道引擎却不知道环境（或反之），
        而这两条恰恰要合起来才能回答"这次到底跑在哪里"。
        """
        recorded = [self.inference_engine is not None, self.runtime_env_sha256 is not None]
        if any(recorded) and not all(recorded):
            msg = "inference_engine 与 runtime_env_sha256 必须同时记录或同时缺失"
            raise ValueError(msg)
        return self

    _validate_json_fields = field_validator("metrics")(validate_json_value)

    @field_validator("artifact_sha256")
    @classmethod
    def validate_artifact_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        """产物集合固定，路径不可注入，摘要必须是 SHA-256。"""
        return _validate_artifact_hashes(value, BASE_ARTIFACT_NAMES)


def load_verified_formal_dev(
    private_root: Path,
    public_manifest: FormalTaskManifest,
    purpose: EvidencePurpose = EvidencePurpose.DEVELOP,
) -> tuple[FormalTaskRecord, ...]:
    """只打开 `<private_root>/dev.jsonl` 并逐行校验后返回全部 dev 记录。

    目的和 manifest split 都在触碰文件系统之前判定；artifact 文件名固定，
    调用方无法传入其他文件名，因此不存在指向 holdout 的开发入口。
    """
    if purpose is not EvidencePurpose.DEVELOP:
        msg = "formal dev split 只允许 develop 目的访问"
        raise PermissionError(msg)
    _require_dev_manifest(public_manifest)

    artifact = _resolve_within(private_root, _DEV_ARTIFACT_NAME)
    if artifact.is_symlink():
        msg = "formal dev artifact 不得是符号链接"
        raise ValueError(msg)
    if not artifact.is_file():
        msg = "formal dev artifact 必须是普通文件"
        raise ValueError(msg)
    try:
        content = artifact.read_bytes()
    except OSError:
        msg = "formal dev artifact 无法读取"
        raise ValueError(msg) from None
    if hashlib.sha256(content).hexdigest() != public_manifest.artifact_sha256:
        msg = "formal dev artifact SHA-256 不匹配"
        raise ValueError(msg)
    return _parse_and_validate_private_rows(public_manifest, content)


def evaluate_formal_dev_base(
    records: Sequence[FormalTaskRecord],
    public_manifest: FormalTaskManifest,
    backend: GenerationBackend,
    config: BaseEvaluationConfig,
    *,
    bundle: LoadedRetailOpsBundle,
    models_root: Path,
    private_root: Path,
    attempt_id: str,
    public_report_path: Path,
    hardware_provider: HardwareProvider,
    inference_engine: Literal["transformers", "vllm"] | None = None,
    runtime_env_sha256: str | None = None,
) -> BaseRunEvidence:
    """在 60 条已验证 dev 记录上跑一次确定性 base 评测并写出全部证据。

    `records` 必须来自 `load_verified_formal_dev`：这里先按公开 manifest 复核
    数量、split、五步预算和五类指纹顺序，再独立重新加载并哈希校验私有
    `dev.jsonl`，逐条比对内容。因此调用方无法用未经验证、被重排或与磁盘真值
    不一致的记录绕过治理。完整轨迹只写入私有 attempt 目录，公开报告只包含
    聚合指标与模型/硬件 provenance。

    调用方必须用同一 `config.model` 构造 `backend`；`TransformersBackend` 会声明
    自身的 `model_dir`/`revision`/`adapter_path`/`settings`，此处据此拒绝任何带
    adapter、指向其他模型或使用非冻结生成参数的后端。
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
        private_subdir="dev-base",
    )
    _require_backend_matches_pin(backend, model_dir, config, expected_adapter=None)

    run = measure_dev_run(
        records,
        public_manifest,
        backend,
        config,
        bundle=bundle,
        hardware_provider=hardware_provider,
        policy_id=f"{config.model.repo}@{config.model.revision}",
    )

    def build(staging: Path) -> BaseRunEvidence:
        artifact_sha256 = write_run_artifacts(
            staging, run.run_config, run.trajectories, run.metrics
        )
        evidence = _finalize_evidence(
            BaseRunEvidence(
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


def require_dev_evaluation_preconditions(
    records: Sequence[FormalTaskRecord],
    public_manifest: FormalTaskManifest,
    config: BaseEvaluationConfig,
    *,
    bundle: LoadedRetailOpsBundle,
    models_root: Path,
    private_root: Path,
    attempt_id: str,
    public_report_path: Path,
    private_subdir: str,
) -> tuple[Path, Path]:
    """base 与 candidate 共用的全部前置守卫，返回 (私有输出目录, 模型目录)。

    这些守卫必须对两条通道**逐条相同**，否则 base/candidate 的比较就建立在
    不同的验证强度上。唯一允许不同的是 backend↔pin 的 adapter 绑定，由调用方
    各自传入期望值。
    """
    _require_dev_manifest(public_manifest)
    _require_matching_bundle(bundle, public_manifest)
    if config.dataset_version != public_manifest.dataset_version:
        msg = "dev 评测 config 与公开 dev manifest 的 dataset_version 不一致"
        raise ValueError(msg)
    _require_verified_dev_records(records, public_manifest, config.max_steps)
    _require_records_match_private_artifact(records, private_root, public_manifest)

    _validate_path_component(attempt_id, label="attempt_id")
    private_target = _resolve_within(private_root, private_subdir, attempt_id)
    _validate_output_pair(private_root, public_report_path)

    model_dir = _resolve_within(models_root, config.model.local_dir)
    verify_local_model_files(model_dir, config.model.file_sha256)
    return private_target, model_dir


@dataclass(frozen=True)
class DevRunMeasurement:
    """一次 dev 评测的执行结果与全部 provenance 摘要。"""

    trajectories: list[Trajectory]
    replayed: int
    metrics: dict[str, Any]
    category_counts: dict[str, int]
    hardware: HardwareProvenance
    manifest_sha256: str
    prompt_sha256: str
    tools_sha256: str
    policy_id: str
    run_config: dict[str, Any]


def measure_dev_run(
    records: Sequence[FormalTaskRecord],
    public_manifest: FormalTaskManifest,
    backend: GenerationBackend,
    config: BaseEvaluationConfig,
    *,
    bundle: LoadedRetailOpsBundle,
    hardware_provider: HardwareProvider,
    policy_id: str,
) -> DevRunMeasurement:
    """base 与 candidate 共用的执行、计时、指标与 provenance 摘要计算。

    配对比较只有在两次运行经过**同一套**执行与指标机器时才成立，因此这段代码
    刻意只有一份；两条通道的差别仅在于 `policy_id`（候选侧带 adapter 身份）。
    """
    policy = QwenPolicy(backend, policy_id, config.generation.max_new_tokens)
    hardware_provider.reset_peak_memory()
    started = time.perf_counter()
    trajectories, replayed = execute_formal_records(records, bundle, policy, config.seed)
    wall_time_seconds = time.perf_counter() - started
    measurement = hardware_provider.measure()

    metrics = compute_metrics(trajectories, config.bootstrap_samples, config.seed)
    category_counts = _category_counts(trajectories, public_manifest)
    hardware = HardwareProvenance(
        gpu=measurement,
        wall_time_seconds=wall_time_seconds,
        tasks_per_second=_rate(len(trajectories), wall_time_seconds),
        output_tokens_per_second=_rate(
            sum(step.output_tokens for trajectory in trajectories for step in trajectory.steps),
            wall_time_seconds,
        ),
    )
    manifest_sha256 = _content_sha256(public_manifest.model_dump(mode="json"))
    prompt_sha256 = _text_sha256(SYSTEM_PROMPT)
    tools_sha256 = _tool_schema_sha256(bundle)
    return DevRunMeasurement(
        trajectories=trajectories,
        replayed=replayed,
        metrics=metrics,
        category_counts=category_counts,
        hardware=hardware,
        manifest_sha256=manifest_sha256,
        prompt_sha256=prompt_sha256,
        tools_sha256=tools_sha256,
        policy_id=policy.name,
        run_config={
            "config": config.model_dump(mode="json"),
            "bundle_sha256": bundle.bundle_sha256,
            "dev_manifest_sha256": manifest_sha256,
            "dev_artifact_sha256": public_manifest.artifact_sha256,
            "parser_id": public_manifest.parser_id,
            "policy_id": policy.name,
            "system_prompt_sha256": prompt_sha256,
            "tool_schema_sha256": tools_sha256,
        },
    )


def load_base_run_evidence(path: Path, *, verify_artifacts: bool = True) -> BaseRunEvidence:
    """读取 base 运行证据并重算 run_id；默认同时校验同目录全部产物哈希。

    公开报告是同一份 JSON 的拷贝，其旁边没有私有产物，加载时应显式传入
    `verify_artifacts=False`，不要静默跳过校验。
    """
    evidence = BaseRunEvidence.model_validate_json(path.read_text(encoding="utf-8"))
    if _content_id(evidence, "run_id") != evidence.run_id:
        msg = "base 评测证据 run_id 不匹配"
        raise ValueError(msg)
    if verify_artifacts:
        _verify_artifact_hashes(path.parent, evidence.artifact_sha256)
    return evidence


def execute_formal_records(
    records: Sequence[FormalTaskRecord],
    bundle: LoadedRetailOpsBundle,
    policy: Policy,
    seed: int,
) -> tuple[list[Trajectory], int]:
    """在真实 RetailOpsEnv 上逐条运行并独立重放，返回轨迹与重放通过数。"""

    def env_factory(task: Any) -> RetailOpsEnv:
        return RetailOpsEnv(task, bundle)

    trajectories = [run_episode(record.task, env_factory, policy, seed) for record in records]
    replayed = sum(
        replay_trajectory(trajectory, env_factory).matched for trajectory in trajectories
    )
    return trajectories, replayed


def publish_run_evidence(
    *,
    private_target: Path,
    public_report_path: Path,
    build: Callable[[Path], EvidenceT],
    serialize: Callable[[EvidenceT], dict[str, Any]] | None = None,
) -> EvidenceT:
    """先在 staging 目录写全部私有产物，原子发布后再写公开报告。

    公开报告写入失败时会整体回滚已发布的私有目录，不留半成品；发布之前的
    任何异常只会删除 staging 目录，真正的目标路径始终未被创建。

    `serialize` 默认是 `evidence.model_dump(mode="json")`；sealed 路径传
    `_serialize_sealed_report` 以按 schema 版本投影 allowlist 字段，避免
    v1.0 报告的公开 payload 出现 v1.1/v1.2 才有的字段（即使值是 None）。
    """
    staging = _make_staging_dir(private_target)
    private_published = False
    try:
        evidence = build(staging)
        _publish_staging_dir(staging, private_target)
        private_published = True
        payload = serialize(evidence) if serialize is not None else evidence.model_dump(mode="json")
        _write_public_report(public_report_path, payload)
        return evidence
    except BaseException:
        if private_published:
            _remove_owned_dir(private_target)
        else:
            _remove_owned_dir(staging)
        raise


def write_run_artifacts(
    staging: Path,
    run_config: dict[str, Any],
    trajectories: Sequence[Trajectory],
    metrics: dict[str, Any],
) -> dict[str, str]:
    """写入四份固定私有产物并返回逐文件 SHA-256。"""
    write_json(staging / "config.json", run_config)
    write_jsonl(
        staging / "trajectories.jsonl",
        (trajectory.model_dump(mode="json") for trajectory in trajectories),
    )
    write_json(staging / "metrics.json", metrics)
    write_jsonl(staging / "failures.jsonl", redact_failure_rows(trajectories))
    return {name: sha256_file(staging / name) for name in BASE_ARTIFACT_NAMES}


_ID_PLACEHOLDER = "0" * 64


#: 2026-08-16 新增的运行时溯源字段。**取值为 None 时不参与内容哈希**，
#: 因此此前产出的每一份证据复算结果逐位不变。未来若再加字段，登记到这里即可，
#: 忘了登记就会让旧证据复算不出原值——那正是要防的事。
RUNTIME_PROVENANCE_FIELDS = frozenset({"inference_engine", "runtime_env_sha256"})


def _finalize_evidence(evidence: EvidenceT, id_field: str) -> EvidenceT:
    """用内容摘要回填自哈希字段。"""
    return evidence.model_copy(update={id_field: _content_id(evidence, id_field)})


def _content_id(evidence: StrictModel, id_field: str) -> str:
    """内容摘要；未记录（None）的运行时溯源字段不参与。

    这样一份 2026-08-16 之前的证据——它根本没有这两个字段，加载后取值为 None——
    复算出的 `run_id` 与它当初落盘时**逐位相同**。这是新增字段的唯一前提。
    """
    payload = evidence.model_dump(mode="json", exclude={id_field, "schema_version"})
    payload = {
        key: value
        for key, value in payload.items()
        if key not in RUNTIME_PROVENANCE_FIELDS or value is not None
    }
    return _content_sha256(payload)


def _content_sha256(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _tool_schema_sha256(bundle: LoadedRetailOpsBundle) -> str:
    return _content_sha256([tool.to_transformers() for tool in bundle.tools])


def _rate(amount: int, seconds: float) -> float:
    return amount / seconds if seconds > 0.0 else 0.0


def _evidence_complete(trajectories: Sequence[Trajectory], replayed: int) -> bool:
    return len(trajectories) == replayed and all(trajectory.steps for trajectory in trajectories)


def _category_counts(
    trajectories: Sequence[Trajectory],
    evidence: FormalTaskManifest | FormalHoldoutReceipt,
) -> dict[str, int]:
    counts = Counter(trajectory.task.scenario.value for trajectory in trajectories)
    ordered = {scenario: counts[scenario] for scenario in evidence.category_counts}
    if ordered != evidence.category_counts:
        msg = "评测轨迹类别分布与公开证据不一致"
        raise ValueError(msg)
    return ordered


def _validate_artifact_hashes(
    value: dict[str, str],
    expected_names: Sequence[str],
) -> dict[str, str]:
    if set(value) != set(expected_names):
        raise ValueError("评测证据产物集合不符合冻结契约")
    if any(_SHA256_PATTERN.fullmatch(digest) is None for digest in value.values()):
        raise ValueError("评测证据产物摘要必须是 SHA-256")
    return value


def _verify_artifact_hashes(directory: Path, artifact_sha256: dict[str, str]) -> None:
    for name, expected in artifact_sha256.items():
        artifact = _resolve_within(directory, name)
        try:
            actual = sha256_file(artifact)
        except OSError as error:
            msg = f"无法读取评测证据产物: {name}"
            raise ValueError(msg) from error
        if actual != expected:
            msg = f"评测证据产物 SHA-256 不匹配: {name}"
            raise ValueError(msg)


def _require_dev_manifest(public_manifest: FormalTaskManifest) -> None:
    if not isinstance(public_manifest, FormalTaskManifest) or public_manifest.split != "dev":
        msg = "formal dev 流程只接受 split=dev 的公开 manifest"
        raise ValueError(msg)


def _require_matching_bundle(
    bundle: LoadedRetailOpsBundle,
    evidence: FormalTaskManifest | FormalHoldoutReceipt,
) -> None:
    if (
        bundle.bundle_sha256 != evidence.bundle_sha256
        or bundle.bundle.bundle_id != evidence.bundle_id
        or bundle.bundle.bundle_version != evidence.bundle_version
        or bundle.bundle.evaluator_id != evidence.evaluator_id
    ):
        msg = "评测 bundle 与公开正式证据不一致"
        raise ValueError(msg)


def _require_verified_dev_records(
    records: Sequence[FormalTaskRecord],
    public_manifest: FormalTaskManifest,
    max_steps: int,
) -> None:
    if len(records) != public_manifest.task_count:
        msg = "base 评测记录数量与公开 dev manifest 不一致"
        raise ValueError(msg)
    for index, record in enumerate(records):
        if not isinstance(record, FormalTaskRecord):
            msg = f"base 评测记录 {index} 不是已验证的 FormalTaskRecord"
            raise ValueError(msg)
        if record.task.split != "dev":
            msg = f"base 评测记录 {index} 的 split 必须是 dev"
            raise ValueError(msg)
        if record.task.max_steps > max_steps:
            msg = f"base 评测记录 {index} 的 max_steps 超出冻结预算"
            raise ValueError(msg)
    for public_field, row_field in zip(_FINGERPRINT_FIELDS, _ROW_FINGERPRINT_FIELDS, strict=True):
        if [getattr(record, row_field) for record in records] != getattr(
            public_manifest, public_field
        ):
            msg = f"base 评测记录指纹顺序与公开 dev manifest 不一致: {row_field}"
            raise ValueError(msg)


def _require_records_match_private_artifact(
    records: Sequence[FormalTaskRecord],
    private_root: Path,
    public_manifest: FormalTaskManifest,
) -> None:
    """独立重新加载并哈希校验 `dev.jsonl`，逐条比对调用方传入的记录。

    这样 `dev_artifact_sha256` 不是调用方的一面之词：证据里记录的私有 artifact
    摘要和真正被评测的任务内容在同一次调用里被重新核对过。
    """
    verified = load_verified_formal_dev(private_root, public_manifest)
    if [record.model_dump(mode="json") for record in records] != [
        record.model_dump(mode="json") for record in verified
    ]:
        msg = "base 评测记录与私有 dev artifact 内容不一致"
        raise ValueError(msg)


class PinnedRunConfig(Protocol):
    """`_require_backend_matches_pin` 真正需要的那两个字段。

    抽成 Protocol 而不是绑定 `BaseEvaluationConfig`：分布外评测有自己的配置类型
    （它的步数预算不是 5，继承会让那个 Literal 变成一句假话），但**必须走同一条
    后端绑定校验**——那条校验是"证据里写的模型就是真正跑的模型"的唯一执行者。
    """

    @property
    def model(self) -> ModelArtifact: ...

    @property
    def generation(self) -> GenerationSettings: ...


def _require_backend_matches_pin(
    backend: GenerationBackend,
    model_dir: Path,
    config: PinnedRunConfig,
    *,
    expected_adapter: Path | None,
) -> None:
    """后端若声明了自身来源，必须与锁定的模型目录、revision 和生成参数完全一致。

    最关键的一条是 adapter，而且是**双向**的：dev base 证据没有 adapter 字段，
    所以一个被 PEFT 包装过的后端若通过检查，产出的证据会与真正的 base 运行逐字节
    难以区分（`expected_adapter=None` 时任何非 None 声明都拒绝）；反过来，候选运行
    若拿到一个没挂 adapter 的后端，证据会谎称评测了候选而实际跑的是 base
    （`expected_adapter` 非 None 时缺失或不符也拒绝）。`config` 侧把 seed/步数/采样/
    思考/量化冻结为 Literal，这里则校验真正跑评测的那个后端。
    """
    declared_adapter = getattr(backend, "adapter_path", None)
    if expected_adapter is None:
        if declared_adapter is not None:
            msg = f"dev base 评测禁止 adapter：生成后端声明了 adapter 路径 {declared_adapter!r}"
            raise ValueError(msg)
    elif declared_adapter is None:
        msg = "dev candidate 评测要求 adapter：生成后端未声明任何 adapter 路径"
        raise ValueError(msg)
    elif Path(declared_adapter).resolve() != expected_adapter.resolve():
        msg = "生成后端加载的 adapter 目录与锁定 adapter 不一致"
        raise ValueError(msg)
    declared_dir = getattr(backend, "model_dir", None)
    if declared_dir is not None and Path(declared_dir).resolve() != model_dir.resolve():
        msg = "生成后端加载的模型目录与锁定 local_dir 不一致"
        raise ValueError(msg)
    declared_revision = getattr(backend, "revision", None)
    if declared_revision is not None and declared_revision != config.model.revision:
        msg = "生成后端声明的模型 revision 与锁定 revision 不一致"
        raise ValueError(msg)
    declared_settings = getattr(backend, "settings", None)
    if declared_settings is not None and declared_settings != config.generation:
        msg = "生成后端声明的生成参数与冻结契约不一致"
        raise ValueError(msg)


def _validate_path_component(value: str, *, label: str) -> str:
    """拒绝空值、`.`/`..` 和任何非白名单字符——杜绝路径穿越和分隔符注入。"""
    if not value or value in {".", ".."} or _SAFE_COMPONENT_PATTERN.fullmatch(value) is None:
        msg = f"{label} 必须是安全的单一路径片段: {value!r}"
        raise ValueError(msg)
    return value


def _resolve_within(root: Path, *parts: str) -> Path:
    """在已建立的受信根目录下逐段拼接，并核对结果确实落在该根之内。

    对最终结果做 `resolve()`（同时解析符号链接与 `..`）后与根目录的
    resolve() 结果比较，可同时挡住路径穿越、绝对路径注入和把中间某段
    做成指向仓库外目录的符号链接这三类绕过手法。
    """
    root_resolved = root.resolve()
    target = root
    for part in parts:
        target = target / part
    target_resolved = target.resolve()
    if target_resolved != root_resolved and root_resolved not in target_resolved.parents:
        msg = f"目标路径逃逸出受信根目录: {target}"
        raise ValueError(msg)
    return target


def _validate_output_pair(private_root: Path, public_report_path: Path) -> None:
    """公开报告不得落在私有根之内，私有根也不得落在公开报告路径之下。"""
    private_resolved = private_root.resolve()
    public_resolved = public_report_path.resolve()
    if (
        private_resolved == public_resolved
        or private_resolved in public_resolved.parents
        or public_resolved in private_resolved.parents
    ):
        msg = "private/public 输出必须分离且不能互相嵌套"
        raise ValueError(msg)


def _make_staging_dir(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent))


def _publish_staging_dir(staging: Path, target: Path) -> None:
    if target.exists() or target.is_symlink():
        msg = f"输出目录已存在，拒绝覆盖: {target}"
        raise FileExistsError(msg)
    staging.rename(target)


def _remove_owned_dir(path: Path | None) -> None:
    if path is None:
        return
    try:
        if path.is_symlink():
            path.unlink()
        elif path.exists():
            shutil.rmtree(path)
    except FileNotFoundError:
        return


def _write_public_report(path: Path, payload: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        msg = f"拒绝覆盖已有公开报告: {path}"
        raise FileExistsError(msg)
    _atomic_write_json(path, payload)


def _atomic_write_json(path: Path, value: Any) -> None:
    """写临时文件后原子 rename，避免崩溃留下半写的 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(canonical_json(value) + "\n")
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
