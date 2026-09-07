"""V7 枚举词导出（预注册 `bc1fb01`）的单元测试。

被测干预：`sft_enum_word` 导出键——把 v1 风格枚举词请求（探针同族模板、
reason = 任务 gold 枚举值）显式纳入训练分布（PITFALLS #27 唯一对症干预）。
五条预注册锁定：行数配额精确、allow/deny 平衡、既有行逐字节不变、
请求 reason ∈ gold 工具枚举域、deny 行 gold 仍是不退款终局。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from veritool_rl.core.trajectory import TaskScenario
from veritool_rl.retail_ops.build.phrasing_bank import LEAKAGE_PATTERN
from veritool_rl.retail_ops.build.teacher_data import (
    EnumWordPlan,
    TeacherAttemptEvidence,
    TeacherAttemptOutcome,
    TeacherCollectionConfig,
    TrainExportSelection,
    compute_teacher_quality_report,
    export_formal_train,
    write_formal_train_export,
)
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
from veritool_rl.retail_ops.domain.formal_tasks import FormalTaskRecord, build_v6_task_set
from veritool_rl.retail_ops.domain.policy_boundary_tasks import build_policy_boundary_tasks

_DUMMY_SHA = "0" * 64
_DATASET_VERSION = "test-dataset-v7-enum-word"

_BUNDLE_V4 = load_bundle(Path("domains/retail_ops/v4"))

#: 预注册模板集（task_plan.md A-0 裁定 2，逐字引用）。
_T1 = "请检查订单 {order_id} 是否能因 {reason} 退款。"
_T2 = "我想为 {order_id} 申请 {reason} 的退款，请核实。"
_T3 = "请检查订单 {other_order_id} 是否能因 {reason} 取消。"

#: 预注册场景 → 模板映射（2 模板变体/任务；rtc 只有取消句式）。
_PREREGISTERED_TEMPLATES: dict[str, list[str]] = {
    "refund_eligible": [_T1, _T2],
    "refund_recovery": [_T1, _T2],
    "refund_denied_window": [_T1, _T2],
    "refund_denied_ownership": [_T1, _T2],
    "refund_denied_duplicate": [_T1, _T2],
    "rtc_stepwise": [_T3],
}

_COVERED_SCENARIOS = tuple(TaskScenario(s) for s in _PREREGISTERED_TEMPLATES)

_ALLOW_SCENARIOS = (
    TaskScenario.REFUND_ELIGIBLE,
    TaskScenario.REFUND_RECOVERY,
    TaskScenario.RTC_STEPWISE,
)
_DENY_SCENARIOS = (
    TaskScenario.REFUND_DENIED_WINDOW,
    TaskScenario.REFUND_DENIED_OWNERSHIP,
    TaskScenario.REFUND_DENIED_DUPLICATE,
)


def _v6_train_records(
    scenarios: tuple[TaskScenario, ...] = _COVERED_SCENARIOS, per_scenario: int | None = None
) -> list[FormalTaskRecord]:
    task_set = build_v6_task_set("retail_ops_v6_20260907", seed=0)
    records: list[FormalTaskRecord] = []
    for scenario in scenarios:
        found = [r for r in task_set.train if r.task.scenario is scenario]
        records.extend(found if per_scenario is None else found[:per_scenario])
    return records


def _env_factory(task: Any) -> RetailOpsEnv:
    return RetailOpsEnv(task, _BUNDLE_V4)


def _tool_reason_enums() -> dict[str, set[str]]:
    """与 product_cli 生产路径同一提取规则：枚举从 bundle 工具 schema 读取。"""
    from veritool_rl.product_cli import _tool_reason_enums as extract

    return extract(_BUNDLE_V4)


def _plan(**overrides: Any) -> EnumWordPlan:
    templates: dict[str, list[str]] = {k: list(v) for k, v in _PREREGISTERED_TEMPLATES.items()}
    templates.update(overrides.pop("scenario_templates", {}))
    return EnumWordPlan(scenario_templates=templates, **overrides)


def _config() -> TeacherCollectionConfig:
    return TeacherCollectionConfig(
        dataset_version=_DATASET_VERSION,
        seed=0,
        bundle_sha256=_BUNDLE_V4.bundle_sha256,
        manifest_sha256=_DUMMY_SHA,
        route_sha256=_DUMMY_SHA,
    )


def _accepted_evidence(task_id: str) -> TeacherAttemptEvidence:
    """accepted 但 trajectory=None 的证据桩：导出时回落 Oracle，不触发绑定检查。"""
    return TeacherAttemptEvidence(
        task_id=task_id,
        task_fingerprint=_DUMMY_SHA,
        dataset_version=_DATASET_VERSION,
        seed=0,
        bundle_sha256=_DUMMY_SHA,
        manifest_sha256=_DUMMY_SHA,
        route_sha256=_DUMMY_SHA,
        config_sha256=_DUMMY_SHA,
        outcome=TeacherAttemptOutcome.SUCCESS,
        accepted=True,
        episode_index=0,
        request_attempts=1,
        usage_prompt_tokens=1,
        usage_completion_tokens=1,
        trajectory=None,
    )


def _export_fixture(
    scenarios: tuple[TaskScenario, ...] = (
        TaskScenario.REFUND_ELIGIBLE,
        TaskScenario.REFUND_DENIED_WINDOW,
    ),
    per_scenario: int = 2,
) -> tuple[list[FormalTaskRecord], list[TeacherAttemptEvidence], dict[str, str]]:
    records = _v6_train_records(scenarios, per_scenario=per_scenario)
    evidences = [_accepted_evidence(r.task.task_id) for r in records]
    scenario_map = {r.task.task_id: r.task.scenario.value for r in records}
    return records, evidences, scenario_map


def _run_export(
    records: list[FormalTaskRecord],
    evidences: list[TeacherAttemptEvidence],
    scenario_map: dict[str, str],
    **kwargs: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    _, _, train_rows, sft_rows = export_formal_train(
        records,
        evidences,
        _env_factory,
        _config(),
        scenario_map,
        seed=0,
        tool_reason_enums=kwargs.pop("tool_reason_enums", _tool_reason_enums()),
        **kwargs,
    )
    return train_rows, sft_rows


# ---------------------------------------------------------------------------
# 配额：预注册数字从真实 train split 推导（不跑导出，纯计数）
# ---------------------------------------------------------------------------


def test_v7_preregistered_quota_exact_from_the_train_split() -> None:
    """追加行数 = Σ 每场景任务数 × 模板数；allow 210 / deny 216 / 总 426。"""
    records = _v6_train_records()
    assert {r.task.scenario for r in records} == set(_COVERED_SCENARIOS), (
        "目标六场景必须都出现在 train split"
    )

    per_scenario = {
        scenario: sum(1 for r in records if r.task.scenario is scenario)
        * len(_PREREGISTERED_TEMPLATES[scenario.value])
        for scenario in _COVERED_SCENARIOS
    }
    assert per_scenario == {
        TaskScenario.REFUND_ELIGIBLE: 84,
        TaskScenario.REFUND_RECOVERY: 84,
        TaskScenario.RTC_STEPWISE: 42,
        TaskScenario.REFUND_DENIED_WINDOW: 72,
        TaskScenario.REFUND_DENIED_OWNERSHIP: 72,
        TaskScenario.REFUND_DENIED_DUPLICATE: 72,
    }
    allow = sum(per_scenario[s] for s in _ALLOW_SCENARIOS)
    deny = sum(per_scenario[s] for s in _DENY_SCENARIOS)
    assert (allow, deny, allow + deny) == (210, 216, 426)


def test_gold_reason_tools_agree_with_the_scenario_tool_mapping() -> None:
    """映射的诚实性：allow 侧任务带 reason 的金标工具必须与场景映射一致。"""
    from veritool_rl.retail_ops.build.teacher_data import _ENUM_WORD_SCENARIO_TOOLS

    for record in _v6_train_records():
        task = record.task
        if task.expected_decision.value == "deny":
            # deny 侧金标不执行退款；映射指向「被拒绝的那个工具」。
            assert task.scenario in _DENY_SCENARIOS
            continue
        gold_tools = {call.name for call in task.expected_calls if "reason" in call.arguments}
        mapped = _ENUM_WORD_SCENARIO_TOOLS[task.scenario]
        assert gold_tools == {mapped}, (
            f"{task.scenario.value} 的金标 reason 工具 {gold_tools} 与映射 {mapped} 不一致"
        )


def test_train_instances_are_disjoint_from_the_probe_grid() -> None:
    """练习题污染红线（task_plan 风险 3）：实例只能来自 train split。"""
    records = _v6_train_records()
    train_tids = {r.task.task_id for r in records}
    train_oids = {oid for r in records for oid in r.task.initial_state["orders"]}
    probe = build_policy_boundary_tasks(0)
    probe_tids = {t.task_id for t in probe}
    probe_oids = {oid for t in probe for oid in t.initial_state["orders"]}
    assert train_tids.isdisjoint(probe_tids)
    assert train_oids.isdisjoint(probe_oids)


def test_preregistered_templates_carry_no_state_leakage() -> None:
    """枚举词请求不得泄漏状态（窗口/归属/重复）——泄漏会让「查证后判断」退化成阅读理解。"""
    for template in (_T1, _T2, _T3):
        assert LEAKAGE_PATTERN.search(template) is None, template


# ---------------------------------------------------------------------------
# 行装配：追加、逐字节不变、只动首条 user 消息
# ---------------------------------------------------------------------------


def test_enum_word_rows_are_appended_after_the_base_rows() -> None:
    records, evidences, scenario_map = _export_fixture()
    _, base_sft = _run_export(records, evidences, scenario_map)
    _, with_enum = _run_export(records, evidences, scenario_map, sft_enum_word=_plan())

    assert len(with_enum) == len(base_sft) + 4 * 2  # 4 任务 × 2 模板
    assert with_enum[: len(base_sft)] == base_sft, "既有行必须逐字节不变（追加不改动）"
    assert [row["task_id"] for row in with_enum[len(base_sft) :]] == [
        r.task.task_id for r in records for _ in range(2)
    ]


def test_enum_word_row_only_changes_the_first_user_message() -> None:
    records, evidences, scenario_map = _export_fixture()
    _, base_sft = _run_export(records, evidences, scenario_map)
    _, with_enum = _run_export(records, evidences, scenario_map, sft_enum_word=_plan())

    base_row_by_task_id: dict[str, dict[str, Any]] = {}
    for row in base_sft:
        # 每任务的第一行 = 规范行（同一 task_id 的后续行是 paraphrase 变体）。
        base_row_by_task_id.setdefault(row["task_id"], row)
    for enum_row in with_enum[len(base_sft) :]:
        base_row = base_row_by_task_id[enum_row["task_id"]]
        assert enum_row["tools"] == base_row["tools"]
        base_messages = list(base_row["messages"])
        enum_messages = list(enum_row["messages"])
        assert len(enum_messages) == len(base_messages)
        assert enum_messages[0] == base_messages[0], "system 消息不动"
        assert enum_messages[1]["role"] == "user"
        assert enum_messages[1]["content"] != base_messages[1]["content"]
        assert enum_messages[2:] == base_messages[2:], "assistant/tool 内容逐字节不动"


def test_enum_word_request_text_matches_the_template_with_gold_reason() -> None:
    records, evidences, scenario_map = _export_fixture((TaskScenario.RTC_STEPWISE,), per_scenario=1)
    _, base_sft = _run_export(records, evidences, scenario_map)
    _, with_enum = _run_export(records, evidences, scenario_map, sft_enum_word=_plan())
    assert len(with_enum) == len(base_sft) + 1

    task = records[0].task
    reason = task.metadata["reason"]
    other_order_id = next(
        call.arguments["order_id"] for call in task.expected_calls if call.name == "cancel_order"
    )
    assert with_enum[-1]["messages"][1]["content"] == _T3.format(
        other_order_id=other_order_id, reason=reason
    )
    assert with_enum[-1]["messages"][2:] == base_sft[-1]["messages"][2:]


def test_deny_enum_row_keeps_the_no_refund_terminal_shape() -> None:
    """deny 枚举词行的 gold 仍是不退款终局（Oracle 形状）：无退款执行、终局不变。"""
    records, evidences, scenario_map = _export_fixture(
        (TaskScenario.REFUND_DENIED_WINDOW,), per_scenario=1
    )
    _, base_sft = _run_export(records, evidences, scenario_map)
    _, with_enum = _run_export(records, evidences, scenario_map, sft_enum_word=_plan())
    enum_row = with_enum[-1]
    base_row = base_sft[-1]

    rendered = "".join(
        message["content"] for message in enum_row["messages"] if message["role"] == "assistant"
    )
    assert "refund_order" not in rendered
    assert enum_row["messages"][0] == base_row["messages"][0], "system 消息不动"
    assert enum_row["messages"][2:] == base_row["messages"][2:]


def test_enum_word_rows_are_not_multiplied_by_oversample() -> None:
    """枚举词行是配额固定的附加行，不随 oversample 重复（预注册配额是绝对数）。"""
    records, evidences, scenario_map = _export_fixture(
        (TaskScenario.REFUND_ELIGIBLE,), per_scenario=1
    )
    _, with_enum = _run_export(
        records,
        evidences,
        scenario_map,
        sft_enum_word=_plan(),
        sft_oversample={"refund_eligible": 3},
    )
    # 基础行 1×3（oversample）+ 枚举词 2（不重复）
    assert len(with_enum) == 5


# ---------------------------------------------------------------------------
# 枚举域与结构校验（fail-closed）
# ---------------------------------------------------------------------------


def test_enum_word_plan_requires_the_tool_reason_enums() -> None:
    """启用枚举词但未提供 bundle 枚举 → 拒绝导出（静默跳过会产出虚假的覆盖声明）。"""
    records, evidences, scenario_map = _export_fixture()
    with pytest.raises(ValueError, match="tool_reason_enums"):
        _run_export(
            records,
            evidences,
            scenario_map,
            sft_enum_word=_plan(),
            tool_reason_enums=None,
        )


def test_request_reason_outside_the_tool_enum_fails_loudly() -> None:
    """枚举域检查必须从 bundle 读取并真的拦下缺陷形状（PITFALLS #26 同族）。"""
    records, evidences, scenario_map = _export_fixture()
    with pytest.raises(ValueError, match="枚举域"):
        _run_export(
            records,
            evidences,
            scenario_map,
            sft_enum_word=_plan(),
            tool_reason_enums={},
        )


def test_unknown_scenario_in_spec_is_rejected() -> None:
    with pytest.raises(ValueError, match="未知场景"):
        _plan(scenario_templates={"refund_eligible_typo": [_T1]})


def test_template_must_carry_reason_and_one_order_placeholder() -> None:
    for bad in (
        "请检查订单 {order_id} 是否能退款。",  # 缺 {reason}
        "请因 {reason} 退款。",  # 缺订单占位符
        "请检查订单 {order_id} 与 {other_order_id} 是否能因 {reason} 退款。",  # 双订单占位符
        "请检查订单 {oid} 是否能因 {reason} 退款。",  # 未知占位符
    ):
        with pytest.raises(ValueError, match="占位符"):
            _plan(scenario_templates={"refund_eligible": [bad]})


def test_rtc_template_requires_the_other_order_placeholder() -> None:
    cancel_flavored = _T1.replace("退款", "取消")
    with pytest.raises(ValueError, match="占位符"):
        _plan(scenario_templates={"rtc_stepwise": [cancel_flavored]})
    with pytest.raises(ValueError, match="占位符"):
        _plan(scenario_templates={"refund_eligible": [_T3]})


def test_empty_template_list_is_rejected() -> None:
    with pytest.raises(ValueError, match="至少一个模板"):
        _plan(scenario_templates={"refund_eligible": []})


def test_missing_other_order_for_rtc_fails_at_render() -> None:
    plan = _plan()
    (record,) = _v6_train_records((TaskScenario.RTC_STEPWISE,), per_scenario=1)
    broken = record.task.model_copy(deep=True)
    broken.expected_calls = [call for call in broken.expected_calls if call.name != "cancel_order"]
    with pytest.raises(ValueError, match="第二订单"):
        plan.render(broken, _tool_reason_enums())


# ---------------------------------------------------------------------------
# sidecar 与产物哈希
# ---------------------------------------------------------------------------


def test_write_formal_train_export_records_enum_word_manifest(tmp_path: Path) -> None:
    """sidecar 记录模板集与逐场景行数；stats 与 sft.jsonl 实际追加行数一致。"""
    records, evidences, scenario_map = _export_fixture()
    plan = _plan()
    _, _, train_rows, sft_rows = export_formal_train(
        records,
        evidences,
        _env_factory,
        _config(),
        scenario_map,
        seed=0,
        sft_enum_word=plan,
        tool_reason_enums=_tool_reason_enums(),
    )
    private_root = tmp_path / "private"
    public_root = tmp_path / "public"
    hashes = write_formal_train_export(
        private_root=private_root,
        public_root=public_root,
        attempt_id="attempt-1",
        dataset_version=_DATASET_VERSION,
        report=compute_teacher_quality_report(evidences, scenario_map),
        selections=[],
        train_rows=train_rows,
        sft_rows=sft_rows,
        sft_enum_word=plan,
    )
    target = private_root / "train-export" / "attempt-1"
    manifest = json.loads((target / "sft_enum_word.json").read_text(encoding="utf-8"))
    assert manifest["enabled"] is True
    assert manifest["scenario_templates"] == {
        k: list(v) for k, v in sorted(_PREREGISTERED_TEMPLATES.items())
    }
    assert manifest["appended_rows"] == 8
    assert sum(manifest["rows_by_scenario"].values()) == 8
    assert set(hashes) == {
        "train.jsonl",
        "sft.jsonl",
        "selection.json",
        "sft_oversample.json",
        "sft_terminal_template.json",
        "sft_system_prompt.json",
        "sft_paraphrase.json",
        "sft_enum_word.json",
    }


def test_write_formal_train_export_without_enum_word_writes_no_sidecar(tmp_path: Path) -> None:
    """禁用时：无 sidecar 文件、无哈希键——老配置重建逐字节不变。"""
    records, evidences, scenario_map = _export_fixture()
    _, _, train_rows, sft_rows = export_formal_train(
        records, evidences, _env_factory, _config(), scenario_map, seed=0
    )
    private_root = tmp_path / "private"
    public_root = tmp_path / "public"
    hashes = write_formal_train_export(
        private_root=private_root,
        public_root=public_root,
        attempt_id="attempt-1",
        dataset_version=_DATASET_VERSION,
        report=compute_teacher_quality_report(evidences, scenario_map),
        selections=[],
        train_rows=train_rows,
        sft_rows=sft_rows,
    )
    target = private_root / "train-export" / "attempt-1"
    assert not (target / "sft_enum_word.json").exists()
    assert "sft_enum_word.json" not in hashes


def test_write_formal_train_export_requires_export_stats(tmp_path: Path) -> None:
    """启用枚举词但未经过 export_formal_train（无 stats）→ 拒绝写盘。"""
    plan = _plan()
    private_root = tmp_path / "private"
    public_root = tmp_path / "public"
    with pytest.raises(ValueError, match="统计"):
        write_formal_train_export(
            private_root=private_root,
            public_root=public_root,
            attempt_id="attempt-1",
            dataset_version=_DATASET_VERSION,
            report=compute_teacher_quality_report([], {}),
            selections=[TrainExportSelection(task_id="t", source="internal_reference")],
            train_rows=[],
            sft_rows=[],
            sft_enum_word=plan,
        )


# ---------------------------------------------------------------------------
# CLI 配置解析
# ---------------------------------------------------------------------------


def test_cli_enum_word_plan_absent_or_null_is_disabled() -> None:
    from veritool_rl.product_cli import _sft_enum_word_plan

    assert _sft_enum_word_plan({}) is None
    assert _sft_enum_word_plan({"sft_enum_word": None}) is None


def test_cli_enum_word_plan_rejects_non_mapping() -> None:
    from veritool_rl.product_cli import _sft_enum_word_plan

    with pytest.raises(ValueError, match="mapping"):
        _sft_enum_word_plan({"sft_enum_word": "yes"})


def test_cli_enum_word_plan_parses_the_preregistered_shape() -> None:
    from veritool_rl.product_cli import _sft_enum_word_plan

    plan = _sft_enum_word_plan({"sft_enum_word": {"scenario_templates": _PREREGISTERED_TEMPLATES}})
    assert plan is not None
    assert set(plan.scenario_templates) == set(_COVERED_SCENARIOS)
    assert plan.scenario_templates[TaskScenario.RTC_STEPWISE] == (_T3,)


# ---------------------------------------------------------------------------
# 已提交的 v7 导出配置 = 预注册声明的逐字落实
# ---------------------------------------------------------------------------


def test_v7_committed_config_declares_the_preregistered_spec() -> None:
    import yaml

    config = yaml.safe_load(
        Path("configs/retail_ops/build/retail_ops_v7_train_export.yaml").read_text(encoding="utf-8")
    )
    assert config["pipeline"] == "train_export"
    assert config["dataset_version"] == "retail_ops_v6_20260907", "A-0 裁定 1：沿用 v6 数据集"
    assert config["teacher_attempt_id"] == "teacher-v6-001", "teacher 证据复用，不重采"
    assert config["attempt_id"] == "train-export-v7-001"
    assert config["sft_oversample"] == {}
    assert config["sft_paraphrase"]["bank_sha256"].startswith("aa6ccee"), "bank-v4 pin 不动"
    assert config["sft_paraphrase"]["per_task"] == 3
    assert config["sft_enum_word"]["scenario_templates"] == _PREREGISTERED_TEMPLATES
