"""R2 Task 4: teacher 采集、质量门与 train 导出测试。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from veritool_rl.core.trajectory import TaskScenario, ToolCall
from veritool_rl.retail_ops.build.teacher_client import (
    TeacherClientError,
    TeacherResponse,
    TeacherUsage,
)
from veritool_rl.retail_ops.build.teacher_data import (
    TeacherAttemptEvidence,
    TeacherAttemptOutcome,
    TeacherCollectionCheckpoint,
    TeacherCollectionConfig,
    TeacherQualityGateError,
    TrainExportSelection,
    collect_teacher_attempt,
    compute_teacher_quality_report,
    export_formal_train,
    load_teacher_checkpoint,
    validate_teacher_trajectory,
    write_formal_train_export,
    write_teacher_attempt_evidence,
    write_teacher_checkpoint,
)
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
from veritool_rl.retail_ops.domain.formal_tasks import FormalTaskRecord, build_formal_task_set

_DUMMY_SHA = "0" * 64
_DATASET_VERSION = "test-dataset-r2-task4"

_BUNDLE = load_bundle(Path("domains/retail_ops/v1"))


def _env_factory(task: Any) -> RetailOpsEnv:
    return RetailOpsEnv(task, _BUNDLE)


def _train_record(scenario: TaskScenario) -> FormalTaskRecord:
    task_set = build_formal_task_set(_DATASET_VERSION, seed=0)
    return next(record for record in task_set.records("train") if record.task.scenario is scenario)


def _config(**overrides: Any) -> TeacherCollectionConfig:
    values = {
        "dataset_version": _DATASET_VERSION,
        "seed": 0,
        "bundle_sha256": _BUNDLE.bundle_sha256,
        "manifest_sha256": _DUMMY_SHA,
        "route_sha256": _DUMMY_SHA,
    }
    values.update(overrides)
    return TeacherCollectionConfig(**values)


def _response(
    *, tool_calls: tuple[ToolCall, ...] = (), content: str | None = None
) -> TeacherResponse:
    return TeacherResponse(
        model="teacher-model",
        content=content,
        tool_calls=tool_calls,
        usage=TeacherUsage(prompt_tokens=100, completion_tokens=10, total_tokens=110),
    )


class _ScriptedTeacherClient:
    """按脚本循环返回响应（跨 episode 从头重放同一模式）。异常会被原样抛出。"""

    def __init__(self, script: list[TeacherResponse | Exception]) -> None:
        self._script = script
        self.calls = 0

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        temperature: float = 0.0,
    ) -> TeacherResponse:
        item = self._script[self.calls % len(self._script)]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return item


def _get_order_call(record: FormalTaskRecord) -> ToolCall:
    order_id = record.task.metadata["order_id"]
    return ToolCall(name="get_order", arguments={"order_id": order_id})


def _refund_call(record: FormalTaskRecord) -> ToolCall:
    order_id = record.task.metadata["order_id"]
    reason = record.task.metadata["reason"]
    return ToolCall(name="refund_order", arguments={"order_id": order_id, "reason": reason})


# ---------------------------------------------------------------------------
# collect_teacher_attempt: 分类与治理边界
# ---------------------------------------------------------------------------


def test_dev_and_holdout_records_are_rejected_before_any_client_call() -> None:
    task_set = build_formal_task_set(_DATASET_VERSION, seed=0)
    for split in ("dev", "holdout"):
        record = task_set.records(split)[0]
        client = _ScriptedTeacherClient([_response(content="不该被调用")])
        with pytest.raises(ValueError, match="train"):
            collect_teacher_attempt(record, client, _env_factory, _config())
        assert client.calls == 0


def test_valid_multi_step_trajectory_is_accepted_with_bound_hashes() -> None:
    record = _train_record(TaskScenario.LOOKUP_STATUS)
    client = _ScriptedTeacherClient(
        [_response(tool_calls=(_get_order_call(record),)), _response(content="已查到状态")]
    )
    config = _config()

    evidence = collect_teacher_attempt(record, client, _env_factory, config)

    assert evidence.outcome is TeacherAttemptOutcome.SUCCESS
    assert evidence.accepted is True
    assert evidence.trajectory is not None
    assert evidence.trajectory.success is True
    assert evidence.task_id == record.task.task_id
    assert evidence.task_fingerprint == record.task_fingerprint
    assert evidence.dataset_version == config.dataset_version
    assert evidence.bundle_sha256 == config.bundle_sha256
    assert evidence.manifest_sha256 == config.manifest_sha256
    assert evidence.route_sha256 == config.route_sha256
    assert evidence.config_sha256 == config.config_sha256
    assert evidence.usage_prompt_tokens == 200
    assert evidence.usage_completion_tokens == 20
    assert evidence.request_attempts == 2


def test_schema_invalid_arguments_are_classified_and_not_accepted() -> None:
    record = _train_record(TaskScenario.LOOKUP_STATUS)
    bad_call = ToolCall(name="get_order", arguments={})  # missing required order_id
    client = _ScriptedTeacherClient([_response(tool_calls=(bad_call,))] * 8)

    evidence = collect_teacher_attempt(record, client, _env_factory, _config())

    assert evidence.outcome is TeacherAttemptOutcome.SCHEMA_INVALID
    assert evidence.accepted is False


def test_illegal_tool_call_is_classified() -> None:
    record = _train_record(TaskScenario.LOOKUP_STATUS)
    bad_call = ToolCall(name="delete_order", arguments={"order_id": "O-anything"})
    client = _ScriptedTeacherClient([_response(tool_calls=(bad_call,))] * 8)

    evidence = collect_teacher_attempt(record, client, _env_factory, _config())

    assert evidence.outcome is TeacherAttemptOutcome.ILLEGAL_TOOL
    assert evidence.accepted is False


def test_policy_violation_is_classified() -> None:
    record = _train_record(TaskScenario.REFUND_ELIGIBLE)
    client = _ScriptedTeacherClient([_response(tool_calls=(_refund_call(record),))] * 4)

    evidence = collect_teacher_attempt(record, client, _env_factory, _config())

    assert evidence.outcome is TeacherAttemptOutcome.POLICY_VIOLATION
    assert evidence.accepted is False


def test_generic_step_limit_without_specific_error_is_classified() -> None:
    record = _train_record(TaskScenario.LOOKUP_STATUS)
    client = _ScriptedTeacherClient([_response(tool_calls=(_get_order_call(record),))] * 8)

    evidence = collect_teacher_attempt(record, client, _env_factory, _config())

    assert evidence.outcome is TeacherAttemptOutcome.STEP_LIMIT
    assert evidence.accepted is False


def test_wrong_final_state_is_classified() -> None:
    record = _train_record(TaskScenario.REFUND_ELIGIBLE)
    client = _ScriptedTeacherClient(
        [_response(tool_calls=(_get_order_call(record),)), _response(content="已处理")]
    )

    evidence = collect_teacher_attempt(record, client, _env_factory, _config())

    assert evidence.outcome is TeacherAttemptOutcome.WRONG_FINAL_STATE
    assert evidence.accepted is False


def test_transient_recovery_within_a_single_episode_succeeds() -> None:
    record = _train_record(TaskScenario.REFUND_RECOVERY)
    client = _ScriptedTeacherClient(
        [
            _response(tool_calls=(_get_order_call(record),)),
            _response(tool_calls=(_refund_call(record),)),  # first attempt hits transient_error
            _response(tool_calls=(_refund_call(record),)),  # retry succeeds
            _response(content="已完成退款"),
        ]
    )

    evidence = collect_teacher_attempt(record, client, _env_factory, _config())

    assert evidence.outcome is TeacherAttemptOutcome.SUCCESS
    assert evidence.accepted is True


def test_replay_mismatch_is_rejected_even_though_trajectory_succeeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import veritool_rl.retail_ops.build.teacher_data as teacher_data_module
    from veritool_rl.core.trajectory.replay import ReplayMismatch

    def _always_mismatch(trajectory: Any, env_factory: Any) -> None:
        raise ReplayMismatch("forced mismatch for test")

    monkeypatch.setattr(teacher_data_module, "replay_trajectory", _always_mismatch)

    record = _train_record(TaskScenario.LOOKUP_STATUS)
    client = _ScriptedTeacherClient(
        [_response(tool_calls=(_get_order_call(record),)), _response(content="已查到状态")]
    )

    evidence = collect_teacher_attempt(record, client, _env_factory, _config())

    assert evidence.outcome is TeacherAttemptOutcome.REPLAY_MISMATCH
    assert evidence.accepted is False


def test_transport_errors_retry_then_succeed_within_budget() -> None:
    record = _train_record(TaskScenario.LOOKUP_STATUS)
    transient = TeacherClientError("timeout", retryable=True)
    client = _ScriptedTeacherClient(
        [
            transient,
            _response(tool_calls=(_get_order_call(record),)),
            _response(content="已查到状态"),
        ]
    )

    evidence = collect_teacher_attempt(record, client, _env_factory, _config())

    assert evidence.outcome is TeacherAttemptOutcome.SUCCESS
    assert evidence.request_attempts == 3


def test_transport_errors_exhaust_retry_budget_across_all_episodes() -> None:
    record = _train_record(TaskScenario.LOOKUP_STATUS)
    transient = TeacherClientError("timeout", retryable=True)
    client = _ScriptedTeacherClient([transient])

    evidence = collect_teacher_attempt(record, client, _env_factory, _config())

    assert evidence.outcome is TeacherAttemptOutcome.TRANSPORT_EXHAUSTED
    assert evidence.accepted is False
    assert evidence.trajectory is None
    # 2 episodes * 3 attempts each
    assert evidence.request_attempts == 6


def test_non_retryable_client_error_does_not_retry_and_is_schema_invalid() -> None:
    record = _train_record(TaskScenario.LOOKUP_STATUS)
    fatal = TeacherClientError("bad request", retryable=False)
    client = _ScriptedTeacherClient([fatal])

    evidence = collect_teacher_attempt(record, client, _env_factory, _config())

    assert evidence.outcome is TeacherAttemptOutcome.SCHEMA_INVALID
    # 1 attempt per step (no retry), 4 steps per episode * 2 episodes
    assert evidence.request_attempts == record.task.max_steps * 2


def test_validate_teacher_trajectory_rejects_unsuccessful_trajectory() -> None:
    record = _train_record(TaskScenario.LOOKUP_STATUS)
    client = _ScriptedTeacherClient([_response(tool_calls=(_get_order_call(record),))] * 8)
    evidence = collect_teacher_attempt(record, client, _env_factory, _config())
    assert evidence.trajectory is not None

    assert validate_teacher_trajectory(evidence.trajectory, _env_factory) is False


# ---------------------------------------------------------------------------
# 私有产物写入：不可覆盖 + 只允许 ignored private root
# ---------------------------------------------------------------------------


_ATTEMPT_ID = "attempt-1"


def _private_root(tmp_path: Path) -> Path:
    return tmp_path / "data" / "private" / "retail_ops" / _DATASET_VERSION


def test_write_evidence_rejects_traversal_via_attempt_id(tmp_path: Path) -> None:
    record = _train_record(TaskScenario.LOOKUP_STATUS)
    client = _ScriptedTeacherClient(
        [_response(tool_calls=(_get_order_call(record),)), _response(content="ok")]
    )
    evidence = collect_teacher_attempt(record, client, _env_factory, _config())

    with pytest.raises(ValueError):
        write_teacher_attempt_evidence(evidence, _private_root(tmp_path), "../../../../../escaped")


def test_write_evidence_rejects_intermediate_symlink_escape(tmp_path: Path) -> None:
    record = _train_record(TaskScenario.LOOKUP_STATUS)
    client = _ScriptedTeacherClient(
        [_response(tool_calls=(_get_order_call(record),)), _response(content="ok")]
    )
    evidence = collect_teacher_attempt(record, client, _env_factory, _config())

    private_root = _private_root(tmp_path)
    private_root.mkdir(parents=True)
    outside = tmp_path / "outside-repo-root"
    outside.mkdir()
    (private_root / "teacher-collection").symlink_to(outside)

    with pytest.raises(ValueError):
        write_teacher_attempt_evidence(evidence, private_root, _ATTEMPT_ID)
    assert not any(outside.iterdir())


def test_write_evidence_is_non_overwrite(tmp_path: Path) -> None:
    record = _train_record(TaskScenario.LOOKUP_STATUS)
    client = _ScriptedTeacherClient(
        [_response(tool_calls=(_get_order_call(record),)), _response(content="ok")]
    )
    evidence = collect_teacher_attempt(record, client, _env_factory, _config())

    written = write_teacher_attempt_evidence(evidence, _private_root(tmp_path), _ATTEMPT_ID)
    assert written.exists()

    with pytest.raises(FileExistsError):
        write_teacher_attempt_evidence(evidence, _private_root(tmp_path), _ATTEMPT_ID)


# ---------------------------------------------------------------------------
# Checkpoint resume：精确哈希匹配，损坏即失败
# ---------------------------------------------------------------------------


def test_resume_returns_none_when_no_checkpoint_exists(tmp_path: Path) -> None:
    assert load_teacher_checkpoint(_private_root(tmp_path), _ATTEMPT_ID, _config()) is None


def test_resume_loads_matching_checkpoint(tmp_path: Path) -> None:
    record = _train_record(TaskScenario.LOOKUP_STATUS)
    client = _ScriptedTeacherClient(
        [_response(tool_calls=(_get_order_call(record),)), _response(content="ok")]
    )
    config = _config()
    evidence = collect_teacher_attempt(record, client, _env_factory, config)
    private_root = _private_root(tmp_path)
    write_teacher_attempt_evidence(evidence, private_root, _ATTEMPT_ID)
    checkpoint = TeacherCollectionCheckpoint(
        dataset_version=config.dataset_version,
        seed=config.seed,
        bundle_sha256=config.bundle_sha256,
        manifest_sha256=config.manifest_sha256,
        route_sha256=config.route_sha256,
        config_sha256=config.config_sha256,
        accepted_task_ids=(record.task.task_id,),
    )
    write_teacher_checkpoint(checkpoint, private_root, _ATTEMPT_ID)

    loaded = load_teacher_checkpoint(private_root, _ATTEMPT_ID, config)
    assert loaded is not None
    assert loaded.accepted_task_ids == (record.task.task_id,)


def test_resume_rejects_mismatched_governance_hashes(tmp_path: Path) -> None:
    config = _config()
    private_root = _private_root(tmp_path)
    checkpoint = TeacherCollectionCheckpoint(
        dataset_version=config.dataset_version,
        seed=config.seed,
        bundle_sha256=config.bundle_sha256,
        manifest_sha256=config.manifest_sha256,
        route_sha256=config.route_sha256,
        config_sha256=config.config_sha256,
        accepted_task_ids=(),
    )
    write_teacher_checkpoint(checkpoint, private_root, _ATTEMPT_ID)

    different_config = _config(seed=1)
    with pytest.raises(ValueError, match="哈希不匹配"):
        load_teacher_checkpoint(private_root, _ATTEMPT_ID, different_config)


def test_resume_rejects_checkpoint_with_missing_evidence_file(tmp_path: Path) -> None:
    config = _config()
    private_root = _private_root(tmp_path)
    checkpoint = TeacherCollectionCheckpoint(
        dataset_version=config.dataset_version,
        seed=config.seed,
        bundle_sha256=config.bundle_sha256,
        manifest_sha256=config.manifest_sha256,
        route_sha256=config.route_sha256,
        config_sha256=config.config_sha256,
        accepted_task_ids=("0" * 64,),
    )
    write_teacher_checkpoint(checkpoint, private_root, _ATTEMPT_ID)

    with pytest.raises(ValueError, match="缺失"):
        load_teacher_checkpoint(private_root, _ATTEMPT_ID, config)


def test_resume_rejects_checkpoint_when_evidence_content_does_not_match(tmp_path: Path) -> None:
    """独立审查发现的真实漏洞回归：证据文件被替换成内容不一致的版本时必须拒绝，
    而不是只做"文件存在且能解析"这种表面检查。"""
    record = _train_record(TaskScenario.LOOKUP_STATUS)
    client = _ScriptedTeacherClient(
        [_response(tool_calls=(_get_order_call(record),)), _response(content="ok")]
    )
    config = _config()
    accepted_evidence = collect_teacher_attempt(record, client, _env_factory, config)
    private_root = _private_root(tmp_path)
    checkpoint = TeacherCollectionCheckpoint(
        dataset_version=config.dataset_version,
        seed=config.seed,
        bundle_sha256=config.bundle_sha256,
        manifest_sha256=config.manifest_sha256,
        route_sha256=config.route_sha256,
        config_sha256=config.config_sha256,
        accepted_task_ids=(record.task.task_id,),
    )
    write_teacher_checkpoint(checkpoint, private_root, _ATTEMPT_ID)

    # 写入一份 task_id 文件名相同、但内容（哈希/接受状态）与 checkpoint 不一致的证据
    tampered = accepted_evidence.model_copy(update={"accepted": False, "bundle_sha256": "1" * 64})
    attempt_dir = private_root / "teacher-collection" / _ATTEMPT_ID
    (attempt_dir / f"{record.task.task_id}.json").write_text(
        tampered.model_dump_json(), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="不一致"):
        load_teacher_checkpoint(private_root, _ATTEMPT_ID, config)


def test_resume_rejects_corrupted_checkpoint_file(tmp_path: Path) -> None:
    private_root = _private_root(tmp_path)
    attempt_dir = private_root / "teacher-collection" / _ATTEMPT_ID
    attempt_dir.mkdir(parents=True)
    (attempt_dir / "checkpoint.json").write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ValueError, match="损坏"):
        load_teacher_checkpoint(private_root, _ATTEMPT_ID, _config())


# ---------------------------------------------------------------------------
# 质量报告与门槛
# ---------------------------------------------------------------------------


def _evidence(task_id: str, accepted: bool) -> TeacherAttemptEvidence:
    return TeacherAttemptEvidence(
        task_id=task_id,
        task_fingerprint=_DUMMY_SHA,
        dataset_version=_DATASET_VERSION,
        seed=0,
        bundle_sha256=_DUMMY_SHA,
        manifest_sha256=_DUMMY_SHA,
        route_sha256=_DUMMY_SHA,
        config_sha256=_DUMMY_SHA,
        outcome=TeacherAttemptOutcome.SUCCESS if accepted else TeacherAttemptOutcome.STEP_LIMIT,
        accepted=accepted,
        episode_index=0,
        request_attempts=1,
        usage_prompt_tokens=1,
        usage_completion_tokens=1,
        trajectory=None,
    )


def test_quality_report_exactly_at_threshold_passes() -> None:
    evidences = [_evidence(f"t{i}", accepted=i < 7) for i in range(10)]
    scenarios = {f"t{i}": "lookup_status" for i in range(10)}

    report = compute_teacher_quality_report(evidences, scenarios)

    assert report.overall_pass_rate == pytest.approx(0.70)
    assert report.passes_gate is True


def test_quality_report_just_below_overall_threshold_fails() -> None:
    evidences = [_evidence(f"t{i}", accepted=i < 6) for i in range(10)]
    scenarios = {f"t{i}": "lookup_status" for i in range(10)}

    report = compute_teacher_quality_report(evidences, scenarios)

    assert report.overall_pass_rate == pytest.approx(0.60)
    assert report.passes_gate is False


def test_quality_report_one_category_failure_despite_overall_success() -> None:
    evidences = [_evidence(f"a{i}", accepted=True) for i in range(10)] + [
        _evidence(f"b{i}", accepted=i < 4) for i in range(10)
    ]
    scenarios = {f"a{i}": "lookup_status" for i in range(10)}
    scenarios.update({f"b{i}": "refund_eligible" for i in range(10)})

    report = compute_teacher_quality_report(evidences, scenarios)

    assert report.overall_pass_rate == pytest.approx(0.70)
    assert report.failing_categories == ("refund_eligible",)
    assert report.passes_gate is False


# ---------------------------------------------------------------------------
# export_formal_train：质量门、来源选择、去重、独立 replay
# ---------------------------------------------------------------------------


def _real_train_records(scenarios: list[TaskScenario]) -> list[FormalTaskRecord]:
    task_set = build_formal_task_set(_DATASET_VERSION, seed=0)
    records = []
    for scenario in scenarios:
        records.extend(r for r in task_set.records("train") if r.task.scenario is scenario)
    return records


def test_export_blocks_before_any_write_when_quality_gate_fails() -> None:
    records = _real_train_records([TaskScenario.LOOKUP_STATUS])[:2]
    evidences = [_evidence(record.task.task_id, accepted=False) for record in records]
    scenarios = {record.task.task_id: record.task.scenario.value for record in records}

    with pytest.raises(TeacherQualityGateError):
        export_formal_train(records, evidences, _env_factory, _config(), scenarios, seed=0)


def test_export_rejects_duplicate_task_ids() -> None:
    record = _train_record(TaskScenario.LOOKUP_STATUS)
    evidences = [_evidence(record.task.task_id, accepted=True)]
    scenarios = {record.task.task_id: record.task.scenario.value}

    with pytest.raises(ValueError, match="重复"):
        export_formal_train([record, record], evidences, _env_factory, _config(), scenarios, seed=0)


def _accepted_evidence(record: FormalTaskRecord, config: TeacherCollectionConfig) -> Any:
    """真正跑一次成功采集，得到与 record/config 完全绑定的合法证据。"""
    client = _ScriptedTeacherClient(
        [_response(tool_calls=(_get_order_call(record),)), _response(content="已查到状态")]
    )
    evidence = collect_teacher_attempt(record, client, _env_factory, config)
    assert evidence.accepted is True
    return evidence


def _gate_filler(count: int) -> tuple[list[FormalTaskRecord], list[TeacherAttemptEvidence]]:
    """补齐若干"已接受但无轨迹"的任务，只为让 70% 质量门通过。

    这些证据走 internal_reference 分支，不参与 teacher 轨迹绑定校验。
    """
    records = _real_train_records([TaskScenario.LOOKUP_STATUS])[2 : 2 + count]
    return records, [_evidence(record.task.task_id, accepted=True) for record in records]


def test_export_rejects_teacher_evidence_whose_trajectory_belongs_to_another_task() -> None:
    """按 task_id 取到的证据必须自证属于这条记录，否则拒绝导出。

    `validate_teacher_trajectory` 用 `trajectory.task` 自建环境重放，所以两条被
    互换过 trajectory 的证据各自都能重放成功——只有把证据内嵌的
    `task_fingerprint`/`trajectory.task` 与当前记录对照才能发现调包。
    """
    config = _config()
    first_record, second_record = _real_train_records([TaskScenario.LOOKUP_STATUS])[:2]
    first_evidence = _accepted_evidence(first_record, config)
    second_evidence = _accepted_evidence(second_record, config)

    swapped_first = first_evidence.model_copy(
        update={
            "trajectory": second_evidence.trajectory,
            "task_fingerprint": second_record.task_fingerprint,
        }
    )
    swapped_second = second_evidence.model_copy(
        update={
            "trajectory": first_evidence.trajectory,
            "task_fingerprint": first_record.task_fingerprint,
        }
    )
    filler_records, filler_evidences = _gate_filler(8)

    all_records = [first_record, second_record, *filler_records]
    all_evidences = [swapped_first, swapped_second, *filler_evidences]
    scenarios = {record.task.task_id: record.task.scenario.value for record in all_records}

    with pytest.raises(ValueError, match="证据"):
        export_formal_train(
            all_records, all_evidences, _env_factory, config, scenarios, seed=0
        )


def test_export_rejects_teacher_evidence_from_another_governance_context() -> None:
    """证据内嵌的 dataset_version/bundle/manifest 哈希必须与本次导出上下文一致。"""
    config = _config()
    record = _real_train_records([TaskScenario.LOOKUP_STATUS])[0]
    evidence = _accepted_evidence(record, config)
    stale = evidence.model_copy(update={"manifest_sha256": "f" * 64})
    filler_records, filler_evidences = _gate_filler(9)

    all_records = [record, *filler_records]
    all_evidences = [stale, *filler_evidences]
    scenarios = {r.task.task_id: r.task.scenario.value for r in all_records}

    with pytest.raises(ValueError, match="证据"):
        export_formal_train(all_records, all_evidences, _env_factory, config, scenarios, seed=0)


def test_export_accepts_teacher_evidence_when_config_budget_fields_differ() -> None:
    """`config_sha256`/`seed` 不参与绑定校验：导出侧会用默认预算重建 config。"""
    collect_config = _config(max_episodes_per_task=1, max_request_attempts=1)
    record = _real_train_records([TaskScenario.LOOKUP_STATUS])[0]
    evidence = _accepted_evidence(record, collect_config)
    export_config = _config()  # 默认预算字段 -> 不同的 config_sha256
    assert evidence.config_sha256 != export_config.config_sha256
    filler_records, filler_evidences = _gate_filler(9)

    all_records = [record, *filler_records]
    all_evidences = [evidence, *filler_evidences]
    scenarios = {r.task.task_id: r.task.scenario.value for r in all_records}

    _, selections, _, _ = export_formal_train(
        all_records, all_evidences, _env_factory, export_config, scenarios, seed=1
    )

    selection_by_task = {selection.task_id: selection.source for selection in selections}
    assert selection_by_task[record.task.task_id] == "teacher"


def test_export_prefers_teacher_trajectory_and_falls_back_to_reference() -> None:
    lookup_records = _real_train_records([TaskScenario.LOOKUP_STATUS])[:2]
    accepted_record, fallback_record = lookup_records

    client = _ScriptedTeacherClient(
        [
            _response(tool_calls=(_get_order_call(accepted_record),)),
            _response(content="已查到状态"),
        ]
    )
    accepted_evidence = collect_teacher_attempt(accepted_record, client, _env_factory, _config())
    assert accepted_evidence.accepted is True
    fallback_evidence = _evidence(fallback_record.task.task_id, accepted=False)

    # 拉齐质量门：凑够总数以让 70% 门槛通过（2 条中 1 条接受不够，补 8 条全接受）
    filler_records = _real_train_records([TaskScenario.LOOKUP_STATUS])[2:10]
    filler_evidences = [_evidence(record.task.task_id, accepted=True) for record in filler_records]

    all_records = lookup_records + filler_records
    all_evidences = [accepted_evidence, fallback_evidence, *filler_evidences]
    scenarios = {record.task.task_id: record.task.scenario.value for record in all_records}

    report, selections, train_rows, sft_rows = export_formal_train(
        all_records, all_evidences, _env_factory, _config(), scenarios, seed=0
    )

    assert report.passes_gate is True
    selection_by_task = {selection.task_id: selection.source for selection in selections}
    assert selection_by_task[accepted_record.task.task_id] == "teacher"
    assert selection_by_task[fallback_record.task.task_id] == "internal_reference"
    assert len(train_rows) == len(all_records)
    assert len(sft_rows) == len(all_records)
    assert len({row["task_id"] for row in train_rows}) == len(all_records)


# ---------------------------------------------------------------------------
# 公开产物：只出聚合 quality.json，不含任务级真值
# ---------------------------------------------------------------------------


def _train_export_roots(tmp_path: Path) -> tuple[Path, Path]:
    private_root = tmp_path / "data" / "private" / "retail_ops" / _DATASET_VERSION
    public_root = tmp_path / "manifests" / "retail_ops" / _DATASET_VERSION
    return private_root, public_root


def test_write_formal_train_export_public_output_has_no_task_level_data(
    tmp_path: Path,
) -> None:
    private_root, public_root = _train_export_roots(tmp_path)

    record = _train_record(TaskScenario.LOOKUP_STATUS)
    report = compute_teacher_quality_report(
        [_evidence(record.task.task_id, accepted=True)],
        {record.task.task_id: record.task.scenario.value},
    )

    selections = [TrainExportSelection(task_id=record.task.task_id, source="teacher")]
    train_rows = [{"task_id": record.task.task_id, "trajectory": {"secret": "should-stay-private"}}]
    sft_rows = [{"task_id": record.task.task_id}]

    write_formal_train_export(
        private_root=private_root,
        public_root=public_root,
        attempt_id=_ATTEMPT_ID,
        dataset_version=_DATASET_VERSION,
        report=report,
        selections=selections,
        train_rows=train_rows,
        sft_rows=sft_rows,
    )

    export_dir = private_root / "train-export" / _ATTEMPT_ID
    public_content = (public_root / "quality.json").read_text("utf-8")
    assert "should-stay-private" not in public_content
    assert record.task.task_id not in public_content
    assert (export_dir / "train.jsonl").exists()
    assert (export_dir / "sft.jsonl").exists()


def test_write_formal_train_export_is_non_overwrite(tmp_path: Path) -> None:
    private_root, public_root = _train_export_roots(tmp_path)

    report = compute_teacher_quality_report([], {})
    kwargs: dict[str, Any] = dict(
        private_root=private_root,
        public_root=public_root,
        attempt_id=_ATTEMPT_ID,
        dataset_version=_DATASET_VERSION,
        report=report,
        selections=[],
        train_rows=[],
        sft_rows=[],
    )
    write_formal_train_export(**kwargs)

    with pytest.raises(FileExistsError):
        write_formal_train_export(**kwargs)


def test_write_formal_train_export_rejects_traversal_via_attempt_id(tmp_path: Path) -> None:
    private_root, public_root = _train_export_roots(tmp_path)
    report = compute_teacher_quality_report([], {})

    with pytest.raises(ValueError):
        write_formal_train_export(
            private_root=private_root,
            public_root=public_root,
            attempt_id="../../../escaped",
            dataset_version=_DATASET_VERSION,
            report=report,
            selections=[],
            train_rows=[],
            sft_rows=[],
        )


def test_write_formal_train_export_rolls_back_private_dir_on_public_conflict(
    tmp_path: Path,
) -> None:
    """独立审查发现的真实漏洞回归：private 三文件已经原子发布后，如果公开
    quality.json 写入失败（比如已存在），private 导出目录必须整体回滚，
    不能残留半成品——不是"private 已发布但公开缺失"的中间态。"""
    private_root, public_root = _train_export_roots(tmp_path)
    public_root.mkdir(parents=True)
    (public_root / "quality.json").write_text("{}", encoding="utf-8")

    report = compute_teacher_quality_report([], {})
    with pytest.raises(FileExistsError):
        write_formal_train_export(
            private_root=private_root,
            public_root=public_root,
            attempt_id=_ATTEMPT_ID,
            dataset_version=_DATASET_VERSION,
            report=report,
            selections=[],
            train_rows=[],
            sft_rows=[],
        )

    assert not (private_root / "train-export" / _ATTEMPT_ID).exists()


# ---------------------------------------------------------------------------
# R4 Task 1：多步家族重复采样（只重复 sft 行，provenance 保持 1:1）
# ---------------------------------------------------------------------------


def _oversample_fixture() -> tuple[
    list[FormalTaskRecord], list[TeacherAttemptEvidence], dict[str, str]
]:
    """10 条 lookup_status 全部接受，用于观察重复采样对三份产物的不同影响。"""
    records = _real_train_records([TaskScenario.LOOKUP_STATUS])[:10]
    evidences = [_evidence(record.task.task_id, accepted=True) for record in records]
    scenarios = {record.task.task_id: record.task.scenario.value for record in records}
    return records, evidences, scenarios


def test_export_oversample_repeats_only_sft_rows() -> None:
    """重复采样必须只作用于 sft.jsonl。

    `train.jsonl` 与 `selection.json` 是 provenance：它们声称"这次导出覆盖了哪些冻结
    任务"。让重复采样漏进去会使产物声称 30 条任务，而冻结契约只有 10 条。
    """
    records, evidences, scenarios = _oversample_fixture()

    _, selections, train_rows, sft_rows = export_formal_train(
        records,
        evidences,
        _env_factory,
        _config(),
        scenarios,
        seed=0,
        sft_oversample={"lookup_status": 3},
    )

    assert len(train_rows) == 10
    assert len(selections) == 10
    assert len(sft_rows) == 30
    assert [row["task_id"] for row in sft_rows] == [
        record.task.task_id for record in records for _ in range(3)
    ]


def test_export_oversample_default_is_identity() -> None:
    """不传 `sft_oversample` 与传空 mapping 都必须等价于原样导出。"""
    records, evidences, scenarios = _oversample_fixture()

    _, _, _, without = export_formal_train(
        records, evidences, _env_factory, _config(), scenarios, seed=0
    )
    _, _, _, empty = export_formal_train(
        records, evidences, _env_factory, _config(), scenarios, seed=0, sft_oversample={}
    )

    assert without == empty
    assert len(without) == 10


def test_export_oversample_rejects_unknown_scenario() -> None:
    """写错场景名必须硬失败，而不是静默无效——静默无效会产出一份和
    未重采样逐字节相同的产物，却让人以为实验已经生效。"""
    records, evidences, scenarios = _oversample_fixture()

    with pytest.raises(ValueError, match="未知场景"):
        export_formal_train(
            records,
            evidences,
            _env_factory,
            _config(),
            scenarios,
            seed=0,
            sft_oversample={"refund_eligible_typo": 3},
        )


def test_export_oversample_rejects_non_positive_factor() -> None:
    """因子 0 会静默丢掉整个类别，负数无意义；两者都必须拒绝。"""
    records, evidences, scenarios = _oversample_fixture()

    for factor in (0, -1):
        with pytest.raises(ValueError, match="重复因子"):
            export_formal_train(
                records,
                evidences,
                _env_factory,
                _config(),
                scenarios,
                seed=0,
                sft_oversample={"lookup_status": factor},
            )


def test_write_formal_train_export_records_oversample_manifest(tmp_path: Path) -> None:
    """重采样因子必须随产物落盘并纳入哈希，否则 sft.jsonl 的行数无法自证来源。"""
    private_root, public_root = _train_export_roots(tmp_path)
    record = _train_record(TaskScenario.LOOKUP_STATUS)
    report = compute_teacher_quality_report(
        [_evidence(record.task.task_id, accepted=True)],
        {record.task.task_id: record.task.scenario.value},
    )

    hashes = write_formal_train_export(
        private_root=private_root,
        public_root=public_root,
        attempt_id=_ATTEMPT_ID,
        dataset_version=_DATASET_VERSION,
        report=report,
        selections=[TrainExportSelection(task_id=record.task.task_id, source="teacher")],
        train_rows=[{"task_id": record.task.task_id}],
        sft_rows=[{"task_id": record.task.task_id}, {"task_id": record.task.task_id}],
        sft_oversample={"lookup_status": 2},
    )

    assert "sft_oversample.json" in hashes
    manifest = json.loads(
        (private_root / "train-export" / _ATTEMPT_ID / "sft_oversample.json").read_text("utf-8")
    )
    assert manifest["factors"] == {"lookup_status": 2}
    assert manifest["train_row_count"] == 1
    assert manifest["sft_row_count"] == 2
