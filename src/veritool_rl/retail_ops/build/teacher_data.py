"""R2 Task 4: bounded teacher collection, checkpoint resume, quality gate, and train export."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from pydantic import ConfigDict, Field

from veritool_rl.core.agent.policy import OraclePolicy, PolicyOutput
from veritool_rl.core.agent.runner import SYSTEM_PROMPT, run_episode
from veritool_rl.core.artifacts import canonical_json, sha256_file, write_json, write_jsonl
from veritool_rl.core.envs.base import ToolEnv, ToolSchema
from veritool_rl.core.generators import trajectory_to_sft_example
from veritool_rl.core.trajectory import TaskScenario, TaskSpec, TerminationReason, Trajectory
from veritool_rl.core.trajectory.replay import ReplayMismatch, replay_trajectory
from veritool_rl.core.trajectory.schema import StrictModel
from veritool_rl.retail_ops.build.phrasing_bank import (
    PHRASING_BANK_VERSION,
    SCENARIO_INTENTS,
    ParaphrasePlan,
    paraphrases_for_task,
)
from veritool_rl.retail_ops.build.teacher_client import (
    TeacherClient,
    TeacherClientError,
    TeacherResponse,
)
from veritool_rl.retail_ops.domain.formal_tasks import FormalTaskRecord

EnvFactory = Callable[[TaskSpec], ToolEnv]

_QUALITY_GATE_OVERALL = 0.70
_QUALITY_GATE_PER_CATEGORY = 0.50
_SAFE_COMPONENT_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


class TeacherAttemptOutcome(StrEnum):
    """六类失败分类之一，加上成功。"""

    SUCCESS = "success"
    SCHEMA_INVALID = "schema_invalid"
    ILLEGAL_TOOL = "illegal_tool"
    POLICY_VIOLATION = "policy_violation"
    STEP_LIMIT = "step_limit"
    WRONG_FINAL_STATE = "wrong_final_state"
    TRANSPORT_EXHAUSTED = "transport_exhausted"
    REPLAY_MISMATCH = "replay_mismatch"


class TeacherTransportExhausted(RuntimeError):
    """在耗尽 max_request_attempts 次可重试传输错误后抛出。"""


class TeacherCollectionConfig(StrictModel):
    """一次采集运行绑定的全部治理哈希与预算参数。"""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, frozen=True)

    dataset_version: str = Field(min_length=1)
    seed: int = Field(ge=0)
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    route_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    max_episodes_per_task: int = Field(default=2, ge=1, le=2)
    max_request_attempts: int = Field(default=3, ge=1, le=3)

    @property
    def config_sha256(self) -> str:
        payload = {
            "dataset_version": self.dataset_version,
            "seed": self.seed,
            "bundle_sha256": self.bundle_sha256,
            "manifest_sha256": self.manifest_sha256,
            "route_sha256": self.route_sha256,
            "max_episodes_per_task": self.max_episodes_per_task,
            "max_request_attempts": self.max_request_attempts,
        }
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class TeacherAttemptEvidence(StrictModel):
    """一次任务采集尝试的完整私有证据；绑定五项治理哈希。"""

    task_id: str = Field(min_length=1)
    task_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_version: str = Field(min_length=1)
    seed: int = Field(ge=0)
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    route_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: TeacherAttemptOutcome
    accepted: bool
    episode_index: int = Field(ge=0)
    request_attempts: int = Field(ge=0)
    usage_prompt_tokens: int = Field(ge=0)
    usage_completion_tokens: int = Field(ge=0)
    trajectory: Trajectory | None = None


def _to_policy_output(response: TeacherResponse) -> PolicyOutput:
    if len(response.tool_calls) == 1:
        call = response.tool_calls[0]
        raw = json.dumps({"name": call.name, "arguments": call.arguments}, ensure_ascii=False)
        return PolicyOutput(raw_text=raw, tool_call=call)
    if len(response.tool_calls) > 1:
        call = response.tool_calls[0]
        raw = json.dumps({"name": call.name, "arguments": call.arguments}, ensure_ascii=False)
        return PolicyOutput(raw_text=raw, tool_call=call)
    if response.content:
        return PolicyOutput(raw_text=response.content, final_response=response.content)
    return PolicyOutput(raw_text="", parse_error="empty_response")


class _RetryingTeacherPolicy:
    """把 TeacherClient 适配为 Policy，仅对可重试传输错误做有限重试。"""

    name = "teacher"

    def __init__(self, client: TeacherClient, *, max_attempts: int) -> None:
        self._client = client
        self._max_attempts = max_attempts
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.request_attempts = 0

    def respond(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema],
    ) -> PolicyOutput:
        tool_dicts = [tool.to_transformers() for tool in tools]
        last_error: TeacherClientError | None = None
        for _ in range(self._max_attempts):
            self.request_attempts += 1
            try:
                response = self._client.complete(messages, tool_dicts, temperature=0.0)
            except TeacherClientError as error:
                last_error = error
                if not error.retryable:
                    return PolicyOutput(raw_text="", parse_error=str(error))
                continue
            if response.usage is not None:
                self.total_prompt_tokens += response.usage.prompt_tokens or 0
                self.total_completion_tokens += response.usage.completion_tokens or 0
            return _to_policy_output(response)
        message = str(last_error) if last_error is not None else "teacher transport 重试耗尽"
        raise TeacherTransportExhausted(message)


def _classify_outcome(trajectory: Trajectory) -> TeacherAttemptOutcome:
    if trajectory.termination is TerminationReason.SUCCESS:
        return TeacherAttemptOutcome.SUCCESS
    if trajectory.termination is TerminationReason.POLICY_VIOLATION:
        return TeacherAttemptOutcome.POLICY_VIOLATION
    if trajectory.termination is TerminationReason.FINAL_RESPONSE:
        return TeacherAttemptOutcome.WRONG_FINAL_STATE

    error_codes = {
        step.observation.error_code
        for step in trajectory.steps
        if step.observation is not None and step.observation.error_code is not None
    }
    has_parse_error = any(step.parse_error is not None for step in trajectory.steps)
    if "unknown_tool" in error_codes:
        return TeacherAttemptOutcome.ILLEGAL_TOOL
    if "invalid_arguments" in error_codes or has_parse_error:
        return TeacherAttemptOutcome.SCHEMA_INVALID
    return TeacherAttemptOutcome.STEP_LIMIT


class TeacherCollectable(Protocol):
    """采集一条轨迹**实际**需要的东西：一个任务和它的指纹。

    此前这里的类型是 `FormalTaskRecord`，而那个类型的构造要求任务带
    `metadata["formal_family"]`——冻结数据集的 family canonical payload。
    R8 的状态增强任务落在冻结网格**之外**，按定义没有 family payload，
    于是这条采集路径对它们不可用，尽管函数体从未用到那四个额外指纹。

    放宽成 Protocol 是把函数的真实契约写出来，不是绕过检查：
    `FormalTaskRecord` 仍然满足它，既有调用点一个字不改。
    """

    @property
    def task(self) -> TaskSpec: ...

    @property
    def task_fingerprint(self) -> str: ...


def collect_teacher_attempt(
    record: TeacherCollectable,
    client: TeacherClient,
    env_factory: EnvFactory,
    config: TeacherCollectionConfig,
) -> TeacherAttemptEvidence:
    """对一条 train 任务最多尝试 config.max_episodes_per_task 个 episode。

    只有真正的成功轨迹会再经过独立 replay 校验；replay 不一致的成功轨迹按
    REPLAY_MISMATCH 处理，不被接受。dev/holdout 任务直接拒绝进入采集。
    """
    if record.task.split != "train":
        msg = f"teacher 采集只能处理 train split 任务，收到 {record.task.split!r}"
        raise ValueError(msg)

    last_outcome = TeacherAttemptOutcome.STEP_LIMIT
    last_trajectory: Trajectory | None = None
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_attempts = 0
    last_episode_index = 0

    for episode_index in range(config.max_episodes_per_task):
        last_episode_index = episode_index
        policy = _RetryingTeacherPolicy(client, max_attempts=config.max_request_attempts)
        try:
            trajectory = run_episode(record.task, env_factory, policy, seed=config.seed)
        except TeacherTransportExhausted:
            total_prompt_tokens += policy.total_prompt_tokens
            total_completion_tokens += policy.total_completion_tokens
            total_attempts += policy.request_attempts
            last_outcome = TeacherAttemptOutcome.TRANSPORT_EXHAUSTED
            last_trajectory = None
            continue

        total_prompt_tokens += policy.total_prompt_tokens
        total_completion_tokens += policy.total_completion_tokens
        total_attempts += policy.request_attempts
        outcome = _classify_outcome(trajectory)

        if outcome is TeacherAttemptOutcome.SUCCESS:
            try:
                replay_trajectory(trajectory, env_factory)
            except ReplayMismatch:
                last_outcome = TeacherAttemptOutcome.REPLAY_MISMATCH
                last_trajectory = trajectory
                continue
            return TeacherAttemptEvidence(
                task_id=record.task.task_id,
                task_fingerprint=record.task_fingerprint,
                dataset_version=config.dataset_version,
                seed=config.seed,
                bundle_sha256=config.bundle_sha256,
                manifest_sha256=config.manifest_sha256,
                route_sha256=config.route_sha256,
                config_sha256=config.config_sha256,
                outcome=TeacherAttemptOutcome.SUCCESS,
                accepted=True,
                episode_index=episode_index,
                request_attempts=total_attempts,
                usage_prompt_tokens=total_prompt_tokens,
                usage_completion_tokens=total_completion_tokens,
                trajectory=trajectory,
            )

        last_outcome = outcome
        last_trajectory = trajectory

    return TeacherAttemptEvidence(
        task_id=record.task.task_id,
        task_fingerprint=record.task_fingerprint,
        dataset_version=config.dataset_version,
        seed=config.seed,
        bundle_sha256=config.bundle_sha256,
        manifest_sha256=config.manifest_sha256,
        route_sha256=config.route_sha256,
        config_sha256=config.config_sha256,
        outcome=last_outcome,
        accepted=False,
        episode_index=last_episode_index,
        request_attempts=total_attempts,
        usage_prompt_tokens=total_prompt_tokens,
        usage_completion_tokens=total_completion_tokens,
        trajectory=last_trajectory,
    )


def validate_teacher_trajectory(trajectory: Trajectory, env_factory: EnvFactory) -> bool:
    """独立复核一条轨迹：必须成功且 replay 完全一致才算有效。"""
    if not trajectory.success:
        return False
    try:
        replay_trajectory(trajectory, env_factory)
    except ReplayMismatch:
        return False
    return True


def _validate_path_component(value: str, *, label: str) -> str:
    """拒绝空值、`.`/`..` 和任何非白名单字符——杜绝路径穿越和分隔符注入。"""
    if not value or value in {".", ".."} or not _SAFE_COMPONENT_PATTERN.fullmatch(value):
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
        msg = f"目标路径逃逸出受信私有根目录: {target}"
        raise ValueError(msg)
    return target


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


def write_teacher_attempt_evidence(
    evidence: TeacherAttemptEvidence,
    private_root: Path,
    attempt_id: str,
) -> Path:
    """写入一条任务的采集证据；同一 attempt 目录内逐任务不可覆盖。

    `private_root` 必须是调用方已经建立的、指向该 dataset_version 私有
    ignored 根（例如 ``data/private/retail_ops/<version>``）的受信目录；
    本函数只在其内部按校验过的简单分量拼接路径，不接受调用方传入任意
    完整路径，也不信任路径字符串里恰好出现的目录名片段。
    """
    _validate_path_component(attempt_id, label="attempt_id")
    _validate_path_component(evidence.task_id, label="evidence.task_id")
    attempt_dir = _resolve_within(private_root, "teacher-collection", attempt_id)
    attempt_dir.mkdir(parents=True, exist_ok=True)
    target = attempt_dir / f"{evidence.task_id}.json"
    if target.exists() or target.is_symlink():
        msg = f"拒绝覆盖已有采集证据: {target}"
        raise FileExistsError(msg)
    _atomic_write_json(target, evidence.model_dump(mode="json"))
    return target


class TeacherCollectionCheckpoint(StrictModel):
    """记录已接受任务，用于精确匹配治理哈希后的续采集。"""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, frozen=True)

    dataset_version: str = Field(min_length=1)
    seed: int = Field(ge=0)
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    route_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted_task_ids: tuple[str, ...]


def write_teacher_checkpoint(
    checkpoint: TeacherCollectionCheckpoint,
    private_root: Path,
    attempt_id: str,
) -> Path:
    _validate_path_component(attempt_id, label="attempt_id")
    attempt_dir = _resolve_within(private_root, "teacher-collection", attempt_id)
    target = attempt_dir / "checkpoint.json"
    _atomic_write_json(target, checkpoint.model_dump(mode="json"))
    return target


def load_teacher_checkpoint(
    private_root: Path,
    attempt_id: str,
    config: TeacherCollectionConfig,
) -> TeacherCollectionCheckpoint | None:
    """只在治理哈希完全匹配、每条引用证据的内容也逐字段核对一致时才续采集。

    checkpoint 缺失返回 None（全新采集）；哈希不匹配、证据文件缺失/损坏，
    或证据文件内容（task_id、accepted、五项治理哈希）与 checkpoint 自身
    记录不一致，一律报错，绝不静默接受被替换过的证据文件。
    """
    _validate_path_component(attempt_id, label="attempt_id")
    attempt_dir = _resolve_within(private_root, "teacher-collection", attempt_id)
    target = attempt_dir / "checkpoint.json"
    if not target.exists():
        return None
    try:
        checkpoint = TeacherCollectionCheckpoint.model_validate_json(target.read_text("utf-8"))
    except ValueError as error:
        msg = f"teacher checkpoint 损坏，拒绝续采集: {target}"
        raise ValueError(msg) from error
    if (
        checkpoint.dataset_version != config.dataset_version
        or checkpoint.seed != config.seed
        or checkpoint.bundle_sha256 != config.bundle_sha256
        or checkpoint.manifest_sha256 != config.manifest_sha256
        or checkpoint.route_sha256 != config.route_sha256
        or checkpoint.config_sha256 != config.config_sha256
    ):
        msg = f"teacher checkpoint 治理哈希不匹配，拒绝续采集: {target}"
        raise ValueError(msg)
    for task_id in checkpoint.accepted_task_ids:
        _validate_path_component(task_id, label="accepted_task_ids 中的 task_id")
        evidence_path = attempt_dir / f"{task_id}.json"
        if not evidence_path.exists():
            msg = f"teacher checkpoint 引用的证据文件缺失: {evidence_path}"
            raise ValueError(msg)
        try:
            evidence = TeacherAttemptEvidence.model_validate_json(evidence_path.read_text("utf-8"))
        except ValueError as error:
            msg = f"teacher checkpoint 引用的证据文件无法解析: {evidence_path}"
            raise ValueError(msg) from error
        if (
            evidence.task_id != task_id
            or not evidence.accepted
            or evidence.dataset_version != checkpoint.dataset_version
            or evidence.seed != checkpoint.seed
            or evidence.bundle_sha256 != checkpoint.bundle_sha256
            or evidence.manifest_sha256 != checkpoint.manifest_sha256
            or evidence.route_sha256 != checkpoint.route_sha256
            or evidence.config_sha256 != checkpoint.config_sha256
        ):
            msg = f"teacher checkpoint 引用的证据文件内容与治理哈希不一致: {evidence_path}"
            raise ValueError(msg)
    return checkpoint


class TeacherQualityReport(StrictModel):
    """整体与逐类别 teacher 通过率；低于门槛即阻断导出。"""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, frozen=True)

    total_tasks: int = Field(ge=0)
    total_accepted: int = Field(ge=0)
    overall_pass_rate: float = Field(ge=0.0, le=1.0)
    category_pass_rates: dict[str, float]
    category_counts: dict[str, int]
    passes_gate: bool
    failing_categories: tuple[str, ...]


class TeacherQualityGateError(RuntimeError):
    """整体或某一类别 teacher 通过率低于冻结门槛。"""


def compute_teacher_quality_report(
    evidences: Sequence[TeacherAttemptEvidence],
    scenario_by_task_id: dict[str, str],
) -> TeacherQualityReport:
    total = len(evidences)
    accepted = sum(1 for evidence in evidences if evidence.accepted)
    overall_rate = accepted / total if total else 0.0

    category_total: dict[str, int] = {}
    category_accepted: dict[str, int] = {}
    for evidence in evidences:
        scenario = scenario_by_task_id[evidence.task_id]
        category_total[scenario] = category_total.get(scenario, 0) + 1
        if evidence.accepted:
            category_accepted[scenario] = category_accepted.get(scenario, 0) + 1

    category_rates = {
        scenario: category_accepted.get(scenario, 0) / count
        for scenario, count in category_total.items()
    }
    failing = tuple(
        sorted(
            scenario
            for scenario, rate in category_rates.items()
            if rate < _QUALITY_GATE_PER_CATEGORY
        )
    )
    passes_gate = overall_rate >= _QUALITY_GATE_OVERALL and not failing

    return TeacherQualityReport(
        total_tasks=total,
        total_accepted=accepted,
        overall_pass_rate=overall_rate,
        category_pass_rates=category_rates,
        category_counts=category_total,
        passes_gate=passes_gate,
        failing_categories=failing,
    )


class TrainExportSelection(StrictModel):
    """单条任务的 train 导出来源与最终校验结果。"""

    task_id: str = Field(min_length=1)
    source: str = Field(pattern=r"^(teacher|internal_reference)$")


ExportResult = tuple[
    TeacherQualityReport, list[TrainExportSelection], list[dict[str, Any]], list[dict[str, Any]]
]


def _resolve_sft_oversample(
    sft_oversample: Mapping[str, int] | None,
    scenario_by_task_id: Mapping[str, str],
) -> dict[str, int]:
    """校验重复采样因子，未知场景名与非正因子一律硬失败。

    静默忽略写错的场景名是这里最危险的行为：产出会与未重采样的导出逐字节相同，
    而实验记录却声称重平衡已经生效，整轮结论都会挂在一个没发生的改动上。
    因子必须 ≥1——0 会把整个类别从训练集里悄悄删掉，那是另一种实验，不是重采样。
    """
    if not sft_oversample:
        return {}
    known = {scenario.value for scenario in TaskScenario}
    resolved: dict[str, int] = {}
    for scenario, factor in sft_oversample.items():
        if scenario not in known:
            msg = f"sft_oversample 指定了未知场景: {scenario}"
            raise ValueError(msg)
        if not isinstance(factor, int) or isinstance(factor, bool) or factor < 1:
            msg = f"sft_oversample 的重复因子必须是 ≥1 的整数: {scenario}={factor!r}"
            raise ValueError(msg)
        resolved[scenario] = factor
    present = set(scenario_by_task_id.values())
    missing = sorted(set(resolved) - present)
    if missing:
        msg = f"sft_oversample 指定的场景未出现在本次导出的任务里: {missing}"
        raise ValueError(msg)
    return resolved


SFT_TERMINAL_RESPONSE_TEMPLATE = (
    "已为订单 {order_id} 按 {reason} 办理退款，当前退款状态为 {refund_status}。"
)


def _resolve_terminal_response(
    sft_terminal_response: Sequence[str] | None,
) -> tuple[str, ...]:
    """校验要追加终局回复的场景名，未知场景名一律硬失败。

    与 `_resolve_sft_oversample` 同一个理由：静默忽略写错的场景名会产出与未启用
    逐字节相同的产物，而实验记录声称数据闭环已经生效。这里刻意**不**检查场景是否
    出现在本次导出里——终局回复的可行性取决于该样本有没有成功的 refund_order，
    那个更强的检查在 `_append_terminal_response` 里逐样本执行。
    """
    if not sft_terminal_response:
        return ()
    known = {scenario.value for scenario in TaskScenario}
    resolved: list[str] = []
    for scenario in sft_terminal_response:
        if scenario not in known:
            msg = f"sft_terminal_response 指定了未知场景: {scenario}"
            raise ValueError(msg)
        if scenario in resolved:
            msg = f"sft_terminal_response 重复指定了同一场景: {scenario}"
            raise ValueError(msg)
        resolved.append(scenario)
    return tuple(resolved)


def _last_successful_refund(messages: Sequence[Mapping[str, Any]]) -> tuple[str, str, str]:
    """从消息序列里取最后一次**成功**的 refund_order 的三个字段。

    `refund_recovery` 有两次 refund_order（首次 transient_error），用首次失败的返回值
    会产出"已办理退款，当前退款状态为 None"这种自相矛盾的监督信号。三个字段全部来自
    样本自身，不读任务记录，因此这个变换不引入任何外部信息，也不产生新的 provenance 问题。
    """
    for index in range(len(messages) - 1, 0, -1):
        message = messages[index]
        if message.get("role") != "tool":
            continue
        previous = messages[index - 1]
        calls = previous.get("tool_calls") or []
        if not calls or calls[0].get("function", {}).get("name") != "refund_order":
            continue
        observation = json.loads(str(message.get("content")))
        if not observation.get("ok"):
            continue
        content = observation.get("content") or {}
        arguments = json.loads(calls[0]["function"]["arguments"])
        order_id = content.get("order_id")
        refund_status = content.get("refund_status")
        reason = arguments.get("reason")
        if order_id is None or refund_status is None or reason is None:
            break
        return str(order_id), str(reason), str(refund_status)
    msg = (
        "sft_terminal_response 启用的场景里没有成功的 refund_order 返回值，"
        "无法在不编造字段的前提下生成终局回复"
    )
    raise ValueError(msg)


def _append_terminal_response(sft_example: dict[str, Any]) -> dict[str, Any]:
    """在样本末尾追加一条**独立的** assistant 终局回复。

    独立消息是硬要求：`core/agent/parser.py` 把「文本 + 工具调用同时出现」判为
    `mixed_tool_call_content` 即非法调用，把文本拼进工具调用消息会把已取得的
    invalid_call = 0 打回去。终局回复加在 refund_order **之后**，而决策点是
    get_order 返回**之后**，两个位置不同，因此决策点的形状分布不受影响。
    """
    messages = list(sft_example["messages"])
    order_id, reason, refund_status = _last_successful_refund(messages)
    messages.append(
        {
            "role": "assistant",
            "content": SFT_TERMINAL_RESPONSE_TEMPLATE.format(
                order_id=order_id, reason=reason, refund_status=refund_status
            ),
        }
    )
    return {**sft_example, "messages": messages}


def _resolve_system_prompt_rewrite(sft_system_prompt_sha256: str | None) -> str | None:
    """确认声明的哈希与当前 `runner.SYSTEM_PROMPT` 一致，返回要写入的 prompt。

    这个键刻意不是布尔值。teacher 证据的 `trajectory.metadata["system_prompt"]` 是
    采集当时持久化的，改 `runner.SYSTEM_PROMPT` 不会追溯改写它；而
    `_require_evidence_binds_record` 不比较 system_prompt。因此布尔值下
    "配置写了 true 但常量忘了改" 会产出一份与未改写逐字节相同的训练集且不报错——
    实验变量没生效而产物看起来完全正常。让配置声明期望哈希，把这种静默失效变成硬错误。
    """
    if sft_system_prompt_sha256 is None:
        return None
    actual = hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()
    if sft_system_prompt_sha256 != actual:
        msg = (
            "sft_system_prompt_sha256 与当前 runner.SYSTEM_PROMPT 的哈希不一致: "
            f"declared={sft_system_prompt_sha256}, actual={actual}"
        )
        raise ValueError(msg)
    return SYSTEM_PROMPT


def _rewrite_system_prompt(sft_example: dict[str, Any], prompt: str) -> dict[str, Any]:
    """只替换首条 system 消息的 content，其余消息与字段一律不动。"""
    messages = list(sft_example["messages"])
    if not messages or messages[0].get("role") != "system":
        msg = f"sft 样本首条消息不是 system，无法改写: {sft_example.get('task_id')}"
        raise ValueError(msg)
    messages[0] = {**messages[0], "content": prompt}
    return {**sft_example, "messages": messages}


def _task_order_id(task: TaskSpec) -> str:
    """取任务的主订单号。措辞池里的 `{order_id}` 要填的就是它。"""
    order_id = task.metadata.get("order_id")
    if not isinstance(order_id, str) or not order_id:
        msg = f"任务缺少 order_id，无法填充改写模板: {task.task_id}"
        raise ValueError(msg)
    return order_id


def _task_other_order_id(task: TaskSpec) -> str:
    """取双订单场景（refund_then_cancel）的第二订单号。

    判定依据是 `expected_calls` 里 cancel_order 的目标订单号——它与主订单号不同，
    且正是改写模板 `{other_order_id}` 要填的那个值。单订单任务返回空串。
    """
    for call in task.expected_calls:
        if call.name != "cancel_order":
            continue
        target = call.arguments.get("order_id")
        if isinstance(target, str) and target and target != _task_order_id(task):
            return target
    return ""


def _rewrite_user_request(sft_example: dict[str, Any], text: str) -> dict[str, Any]:
    """只替换首条 user 消息的 content。

    **assistant 的工具调用、tool 观测与最终状态一个字不动**——这是 paraphrase 增强
    与「换个任务」之间的全部区别。改写只作用于「顾客怎么说」，
    不作用于「Agent 该做什么」，因此 `target_state` / `expected_calls` 仍然成立。
    """
    messages = list(sft_example["messages"])
    user_positions = [i for i, message in enumerate(messages) if message.get("role") == "user"]
    if not user_positions:
        msg = f"sft 样本没有 user 消息，无法改写: {sft_example.get('task_id')}"
        raise ValueError(msg)
    first = user_positions[0]
    messages[first] = {**messages[first], "content": text}
    return {**sft_example, "messages": messages}


def export_formal_train(
    records: Sequence[FormalTaskRecord],
    evidences: Sequence[TeacherAttemptEvidence],
    env_factory: EnvFactory,
    config: TeacherCollectionConfig,
    scenario_by_task_id: dict[str, str],
    seed: int,
    sft_oversample: Mapping[str, int] | None = None,
    sft_terminal_response: Sequence[str] | None = None,
    sft_system_prompt_sha256: str | None = None,
    sft_paraphrase: ParaphrasePlan | None = None,
) -> ExportResult:
    """质量门通过后，为每条任务选一条轨迹并独立 replay 全部导出集合。

    优先使用已接受且 replay 通过的 teacher 轨迹；否则退回该任务的确定性
    internal reference（Oracle）。质量门不通过时抛 TeacherQualityGateError，
    不产出任何导出文件。

    `config` 是本次导出的治理上下文：每条被选中的 teacher 证据都要先通过
    `_require_evidence_binds_record`，证明它确实属于当前记录（而不只是 task_id
    对得上），否则整次导出失败。

    `sft_oversample` 按场景重复 **sft 行**，用于重平衡训练集的动作分布。它刻意
    不影响 `train_rows`/`selections`：那两份是 provenance，声称"本次导出覆盖了哪些
    冻结任务"，让重复采样漏进去会使产物声称的任务数超过冻结契约。重复而不是
    加权，是为了让改动完全落在数据产物里、训练代码一行不改，变量单一且可哈希追溯。

    `sft_terminal_response` 与 `sft_system_prompt_sha256` 是 R4 第二轮的两个消融变量，
    同样只作用于 `sft.jsonl`，且都是**纯局部变换**——只读样本自身的消息序列与当前
    `runner.SYSTEM_PROMPT`，不读任务记录、不碰 `target_state`/`expected_calls`。
    三者互相独立，可单独启用；本轮的纪律是每个候选只启用一个。

    `sft_paraphrase`（R6）是第四个、也是唯一改变**输入分布**的变量：为每条任务额外
    产出 `per_task` 条只改写了 user 第一句话的样本。它存在的理由是 LOG-20260816-01
    的子类拆分——冻结集合的 12 句模板全是「请核实…」的书面祈使句，模型据此学到
    「表面形式 → 动作」的触发器，换个说法就退回「说完就停」。
    改写文本只取自措辞池的 **`train_aug`** 分片，与两个评测分片逐条互斥。
    """
    resolved_oversample = _resolve_sft_oversample(sft_oversample, scenario_by_task_id)
    resolved_terminal = _resolve_terminal_response(sft_terminal_response)
    rewrite_prompt = _resolve_system_prompt_rewrite(sft_system_prompt_sha256)
    report = compute_teacher_quality_report(evidences, scenario_by_task_id)
    if not report.passes_gate:
        raise TeacherQualityGateError(
            f"teacher 质量门未通过：整体 {report.overall_pass_rate:.2%}，"
            f"未达标类别 {report.failing_categories}"
        )

    evidence_by_task_id = {evidence.task_id: evidence for evidence in evidences}
    selections: list[TrainExportSelection] = []
    train_rows: list[dict[str, Any]] = []
    sft_rows: list[dict[str, Any]] = []
    seen_task_ids: set[str] = set()

    for record in records:
        task_id = record.task.task_id
        if task_id in seen_task_ids:
            msg = f"formal train 导出发现重复 task_id: {task_id}"
            raise ValueError(msg)
        seen_task_ids.add(task_id)

        evidence = evidence_by_task_id.get(task_id)
        trajectory: Trajectory
        source: str
        if evidence is not None and evidence.accepted and evidence.trajectory is not None:
            _require_evidence_binds_record(evidence, record, config)
            trajectory = evidence.trajectory
            source = "teacher"
        else:
            (trajectory,) = _build_reference_trajectory(record.task, env_factory, seed)
            source = "internal_reference"

        if not validate_teacher_trajectory(trajectory, env_factory):
            msg = f"导出前独立 replay 校验失败: {task_id}"
            raise ReplayMismatch(msg)

        selections.append(TrainExportSelection(task_id=task_id, source=source))
        train_rows.append(
            {
                "task_id": task_id,
                "task_fingerprint": record.task_fingerprint,
                "source": source,
                "trajectory": trajectory.model_dump(mode="json"),
            }
        )
        scenario = scenario_by_task_id[task_id]
        repeat = resolved_oversample.get(scenario, 1)
        sft_example = trajectory_to_sft_example(trajectory)
        if scenario in resolved_terminal:
            sft_example = _append_terminal_response(sft_example)
        if rewrite_prompt is not None:
            sft_example = _rewrite_system_prompt(sft_example, rewrite_prompt)
        sft_rows.extend(sft_example for _ in range(repeat))
        if sft_paraphrase is not None:
            for text in paraphrases_for_task(
                sft_paraphrase.index,
                intent=SCENARIO_INTENTS[record.task.scenario],
                task_key=task_id,
                count=sft_paraphrase.per_task,
                order_id=_task_order_id(record.task),
                other_order_id=_task_other_order_id(record.task),
            ):
                sft_rows.extend(_rewrite_user_request(sft_example, text) for _ in range(repeat))

    if len(train_rows) != len(records):
        msg = "formal train 导出数量与输入任务数不一致"
        raise ValueError(msg)

    return report, selections, train_rows, sft_rows


def _require_evidence_binds_record(
    evidence: TeacherAttemptEvidence,
    record: FormalTaskRecord,
    config: TeacherCollectionConfig,
) -> None:
    """按 task_id 取到的 teacher 证据必须自证属于这条记录和本次导出上下文。

    `validate_teacher_trajectory` 通过 `replay_trajectory(trajectory, env_factory)`
    重放，而环境是用 `trajectory.task`（轨迹自带的任务，不是记录里的任务）建的，
    所以两份被互换过 `trajectory` 的证据各自都能自洽地重放成功，最终会导出一条
    prompt 与其声称的 manifest 行对不上的 `sft.jsonl`。只有把证据内嵌的绑定字段
    与当前记录/配置对照才能发现这种"文件名对得上、内容对不上"的调包。

    不一致时直接抛错而不是退回 internal_reference：证据目录被替换/混用是完整性
    事件，不是"这条任务恰好没有 teacher 数据"。静默降级会产出一份和正常导出
    逐字节难以区分的产物，只在 `selection.json` 里留下一个来源标签。抛错发生在
    任何写盘之前（`write_formal_train_export` 尚未调用），因此不违反本流程
    "绝不半途导出"的契约。

    刻意不比较 `config_sha256` 和 `seed`：`_run_train_export` 用默认预算字段
    （`max_episodes_per_task`/`max_request_attempts`）和导出侧 seed 重建
    `TeacherCollectionConfig`，采集时用的是 YAML 里的实际预算与采集 seed，两者
    本就允许不同——把它们纳入比较会变成永远失败的断言。
    """
    task_id = record.task.task_id
    if evidence.task_fingerprint != record.task_fingerprint:
        msg = f"teacher 证据 task_fingerprint 与导出记录不一致: {task_id}"
        raise ValueError(msg)
    if evidence.trajectory is None or evidence.trajectory.task != record.task:
        msg = f"teacher 证据 trajectory.task 与导出记录不一致: {task_id}"
        raise ValueError(msg)
    if evidence.dataset_version != config.dataset_version:
        msg = f"teacher 证据 dataset_version 与本次导出上下文不一致: {task_id}"
        raise ValueError(msg)
    if evidence.bundle_sha256 != config.bundle_sha256:
        msg = f"teacher 证据 bundle_sha256 与本次导出上下文不一致: {task_id}"
        raise ValueError(msg)
    if evidence.manifest_sha256 != config.manifest_sha256:
        msg = f"teacher 证据 manifest_sha256 与本次导出上下文不一致: {task_id}"
        raise ValueError(msg)


def _build_reference_trajectory(
    task: TaskSpec,
    env_factory: EnvFactory,
    seed: int,
) -> tuple[Trajectory]:
    trajectory = run_episode(task, env_factory, OraclePolicy(task), seed=seed)
    if not trajectory.success:
        msg = f"internal reference（Oracle）未能完成任务: {task.task_id}"
        raise RuntimeError(msg)
    return (trajectory,)


def _validate_export_output_pair(private_target: Path, public_root: Path) -> None:
    private_resolved = private_target.resolve()
    public_resolved = public_root.resolve()
    if (
        private_resolved == public_resolved
        or private_resolved in public_resolved.parents
        or public_resolved in private_resolved.parents
    ):
        msg = "private/public 导出目录必须分离且不能互相嵌套"
        raise ValueError(msg)
    if private_target.exists() or private_target.is_symlink():
        msg = f"输出目录已存在，拒绝覆盖: {private_target}"
        raise FileExistsError(msg)


def write_formal_train_export(
    *,
    private_root: Path,
    public_root: Path,
    attempt_id: str,
    dataset_version: str,
    report: TeacherQualityReport,
    selections: Sequence[TrainExportSelection],
    train_rows: Sequence[dict[str, Any]],
    sft_rows: Sequence[dict[str, Any]],
    sft_oversample: Mapping[str, int] | None = None,
    sft_terminal_response: Sequence[str] | None = None,
    sft_system_prompt_sha256: str | None = None,
    sft_paraphrase: ParaphrasePlan | None = None,
) -> dict[str, str]:
    """把完整训练数据写到 private ignored root，公开 root 只留聚合质量报告。

    private 四个文件通过 staging 目录一次性原子发布（rename）；只要公开
    quality.json 写入失败或此前任一步骤失败，已发布的 private 目录会被
    整体回滚删除，不留半成品——不会出现 private 已发布但公开缺失、或
    private 只写了部分文件的中间状态。

    `sft_oversample.json` 让产物自证行数来源：只看 `sft.jsonl` 无法区分
    "400 条任务" 与 "240 条任务、其中 80 条重复三次"，而这两者对结论的含义完全不同。
    它同样纳入 `private_artifact_sha256`，手改即被发现。
    """
    _validate_path_component(attempt_id, label="attempt_id")
    private_target = _resolve_within(private_root, "train-export", attempt_id)
    _validate_export_output_pair(private_target, public_root)

    staging = _make_staging_dir(private_target)
    private_published = False
    try:
        write_jsonl(staging / "train.jsonl", train_rows)
        write_jsonl(staging / "sft.jsonl", sft_rows)
        write_json(
            staging / "selection.json",
            [selection.model_dump(mode="json") for selection in selections],
        )
        write_json(
            staging / "sft_oversample.json",
            {
                "factors": dict(sorted((sft_oversample or {}).items())),
                "train_row_count": len(train_rows),
                "sft_row_count": len(sft_rows),
            },
        )
        terminal_scenarios = sorted(sft_terminal_response or ())
        write_json(
            staging / "sft_terminal_template.json",
            {
                "template": SFT_TERMINAL_RESPONSE_TEMPLATE,
                "scenarios": terminal_scenarios,
                "affected_sft_rows": sum(
                    1 for row in sft_rows if row.get("scenario") in terminal_scenarios
                ),
            },
        )
        write_json(
            staging / "sft_system_prompt.json",
            {
                "rewritten": sft_system_prompt_sha256 is not None,
                "sha256": sft_system_prompt_sha256,
                "prompt": SYSTEM_PROMPT if sft_system_prompt_sha256 is not None else None,
                "affected_sft_rows": len(sft_rows) if sft_system_prompt_sha256 is not None else 0,
            },
        )
        write_json(
            staging / "sft_paraphrase.json",
            {
                "enabled": sft_paraphrase is not None,
                "bank_sha256": sft_paraphrase.bank_sha256 if sft_paraphrase else None,
                "partition": sft_paraphrase.partition if sft_paraphrase else None,
                "per_task": sft_paraphrase.per_task if sft_paraphrase else 0,
                "phrasing_bank_version": PHRASING_BANK_VERSION if sft_paraphrase else None,
            },
        )
        artifact_hashes = {
            "train.jsonl": sha256_file(staging / "train.jsonl"),
            "sft_paraphrase.json": sha256_file(staging / "sft_paraphrase.json"),
            "sft.jsonl": sha256_file(staging / "sft.jsonl"),
            "selection.json": sha256_file(staging / "selection.json"),
            "sft_oversample.json": sha256_file(staging / "sft_oversample.json"),
            "sft_terminal_template.json": sha256_file(staging / "sft_terminal_template.json"),
            "sft_system_prompt.json": sha256_file(staging / "sft_system_prompt.json"),
        }
        _publish_staging_dir(staging, private_target)
        private_published = True

        public_quality_path = public_root / "quality.json"
        if public_quality_path.exists() or public_quality_path.is_symlink():
            msg = f"拒绝覆盖已有公开 quality.json: {public_quality_path}"
            raise FileExistsError(msg)
        _atomic_write_json(
            public_quality_path,
            {
                "dataset_version": dataset_version,
                "overall_pass_rate": report.overall_pass_rate,
                "category_pass_rates": report.category_pass_rates,
                "category_counts": report.category_counts,
                "total_tasks": report.total_tasks,
                "total_accepted": report.total_accepted,
                "passes_gate": report.passes_gate,
                "private_artifact_sha256": artifact_hashes,
            },
        )
        return artifact_hashes
    except BaseException:
        if private_published:
            _remove_owned_dir(private_target)
        else:
            _remove_owned_dir(staging)
        raise
