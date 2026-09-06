"""DPO 偏好对采样器（r11 主线 A-2）。

设计约束全部来自 `docs/DPO_ENTRY_EVIDENCE_D2.md` 与 task_plan 预注册（`eeec309`）：

1. rejected 必须是模型在真实链路上采样得到的失败轨迹——本文件的全部夹具都走
   `run_episode` + 真实 `RetailOpsEnv`，不手工捏 Trajectory（手工构造的 rejected
   会让 DPO 学到「不要执行退款」而不是「过期的才不能执行」）；
2. chosen = Oracle 轨迹，模型无关、逐位确定；
3. 门禁守卫方案：偏好对只来自 DENY 任务（offset < 0）单一方向，ALLOW 任务不产对，
   只进「放行侧不塌」前提检查；放行侧出现执行类错误 → `premise_ok=False`，
   调用方必须停下回用户决策（用户已否掉高温诱导对冲对）；
4. 配对携带 `task_id` + `sample_index` 溯源；同任务内按 rejected 内容去重。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from veritool_rl.core.agent.policy import PolicyOutput
from veritool_rl.core.agent.runner import run_episode
from veritool_rl.core.trajectory import ExpectedDecision, TaskSpec, ToolCall, Trajectory
from veritool_rl.retail_ops.build.phrasing_bank import INTENT_REFUND, build_records
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
from veritool_rl.retail_ops.domain.policy_boundary_phrasing_tasks import (
    POLICY_BOUNDARY_PHRASING_DATASET_VERSION,
    build_policy_boundary_phrasing_tasks,
)
from veritool_rl.retail_ops.domain.policy_boundary_tasks import (
    POLICY_BOUNDARY_DATASET_VERSION,
    build_policy_boundary_tasks,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = REPO_ROOT / "domains/retail_ops/v1"


# ---------------------------------------------------------------------------
# 夹具：真实链路的轨迹（不手工捏）
# ---------------------------------------------------------------------------


class _ScriptedPolicy:
    """按脚本重放动作的策略替身：动作真的过环境执行、真的产生观测与违规。"""

    name = "scripted"

    def __init__(self, script: list[ToolCall | str]) -> None:
        self._script = script
        self._index = 0

    def respond(self, messages: list[dict[str, Any]], tools: list[Any]) -> PolicyOutput:
        del messages, tools
        if self._index >= len(self._script):
            return PolicyOutput(raw_text="任务已完成。", final_response="任务已完成。")
        item = self._script[self._index]
        self._index += 1
        if isinstance(item, ToolCall):
            payload = {"name": item.name, "arguments": item.arguments}
            raw = f"<tool_call>\n{json.dumps(payload, ensure_ascii=False)}\n</tool_call>"
            return PolicyOutput(raw_text=raw, tool_call=item)
        return PolicyOutput(raw_text=item, final_response=item)


def _env_factory(task: TaskSpec) -> RetailOpsEnv:
    from veritool_rl.retail_ops.domain.bundle import load_bundle

    return RetailOpsEnv(task, load_bundle(BUNDLE_DIR))


def _probe_task(offset: int) -> TaskSpec:
    matches = [
        task
        for task in build_policy_boundary_tasks(0)
        if task.metadata["deadline_offset_days"] == offset
    ]
    assert matches, f"探针没有 offset {offset} 的任务"
    return matches[0]


def _violation_trajectory(task: TaskSpec) -> Trajectory:
    """真实链路：查订单 → 对过期订单执行退款 → 环境拒绝（refund_not_eligible）。"""
    order_id = str(task.metadata["order_id"])
    trajectory = run_episode(
        task,
        _env_factory,
        _ScriptedPolicy(
            [
                ToolCall(name="get_order", arguments={"order_id": order_id}),
                ToolCall(
                    name="refund_order",
                    arguments={"order_id": order_id, "reason": "damaged"},
                ),
            ]
        ),
        seed=0,
    )
    assert trajectory.termination.value == "policy_violation"
    assert "refund_not_eligible" in trajectory.violations
    return trajectory


def _oracle(task: TaskSpec) -> Trajectory:
    from veritool_rl.retail_ops.build.dpo_sampling import oracle_reference

    return oracle_reference(task, _env_factory)


def _phrasing_face() -> list[TaskSpec]:
    accepted = [
        (INTENT_REFUND, "test-style", f"麻烦帮我处理第 {index} 号形态的退款请求 {{order_id}}。")
        for index in range(2000)
    ]
    records = [r for r in build_records(accepted) if r.partition == "ood_dev"]
    return build_policy_boundary_phrasing_tasks(0, {INTENT_REFUND: records}, partition="ood_dev")


# ---------------------------------------------------------------------------
# 正例：配对长什么样
# ---------------------------------------------------------------------------


def test_a_real_violation_sample_becomes_the_rejected_side() -> None:
    from veritool_rl.retail_ops.build.dpo_sampling import build_preference_pairs

    task = _probe_task(-14)
    report = build_preference_pairs(
        tasks=[task],
        samples={task.task_id: [_violation_trajectory(task)]},
        oracle={task.task_id: _oracle(task)},
    )

    assert report.pairs_total == 1
    pair = report.pairs[0]
    assert pair.task_id == task.task_id
    assert pair.sample_index == 0
    rejected_calls = [
        message.get("tool_calls", [{}])[0].get("function", {}).get("name")
        for message in pair.rejected
        if message.get("tool_calls")
    ]
    assert rejected_calls == ["get_order", "refund_order"]
    chosen_calls = [
        message.get("tool_calls", [{}])[0].get("function", {}).get("name")
        for message in pair.chosen
        if message.get("tool_calls")
    ]
    assert chosen_calls == ["get_order"]


def test_chosen_is_the_bitwise_deterministic_oracle() -> None:
    from veritool_rl.core.generators import trajectory_messages
    from veritool_rl.retail_ops.build.dpo_sampling import build_preference_pairs

    task = _probe_task(-14)
    oracle = _oracle(task)
    first = build_preference_pairs(
        tasks=[task],
        samples={task.task_id: [_violation_trajectory(task)]},
        oracle={task.task_id: oracle},
    )
    second = build_preference_pairs(
        tasks=[task],
        samples={task.task_id: [_violation_trajectory(task)]},
        oracle={task.task_id: _oracle(task)},
    )

    assert first.pairs[0].chosen == second.pairs[0].chosen
    assert first.pairs[0].pair_id == second.pairs[0].pair_id
    assert first.pairs[0].chosen == trajectory_messages(oracle)[2:]
    assert oracle.success and not oracle.violations


def test_allow_tasks_never_produce_pairs_even_with_successful_refunds() -> None:
    from veritool_rl.retail_ops.build.dpo_sampling import build_preference_pairs

    task = _probe_task(1)
    order_id = str(task.metadata["order_id"])
    executed = run_episode(
        task,
        _env_factory,
        _ScriptedPolicy(
            [
                ToolCall(name="get_order", arguments={"order_id": order_id}),
                ToolCall(
                    name="refund_order",
                    arguments={"order_id": order_id, "reason": "damaged"},
                ),
                "已为订单办理退款。",
            ]
        ),
        seed=0,
    )
    assert executed.success

    report = build_preference_pairs(
        tasks=[task],
        samples={task.task_id: [executed]},
        oracle={task.task_id: _oracle(task)},
    )

    assert report.pairs_total == 0
    assert report.allow_side_violation_samples == 0
    assert report.premise_ok is True


def test_deny_tasks_without_violation_samples_are_skipped() -> None:
    from veritool_rl.retail_ops.build.dpo_sampling import build_preference_pairs

    task = _probe_task(-14)
    report = build_preference_pairs(
        tasks=[task],
        samples={task.task_id: [_oracle(task)]},
        oracle={task.task_id: _oracle(task)},
    )

    assert report.pairs_total == 0
    assert report.deny_tasks == 1
    assert report.deny_tasks_with_pairs == 0


def test_duplicates_within_a_task_are_deduplicated_to_the_first_sample() -> None:
    from veritool_rl.retail_ops.build.dpo_sampling import build_preference_pairs

    task = _probe_task(-14)
    first = _violation_trajectory(task)
    second = _violation_trajectory(task)
    report = build_preference_pairs(
        tasks=[task],
        samples={task.task_id: [first, second]},
        oracle={task.task_id: _oracle(task)},
    )

    assert report.pairs_total == 1
    assert report.pairs[0].sample_index == 0


def test_identical_rejections_on_different_tasks_are_both_kept() -> None:
    """去重是「同任务内」语义：不同任务的同形失败各自成对。"""
    from veritool_rl.retail_ops.build.dpo_sampling import build_preference_pairs

    first_task = _probe_task(-14)
    second_task = _probe_task(-10)
    report = build_preference_pairs(
        tasks=[first_task, second_task],
        samples={
            first_task.task_id: [_violation_trajectory(first_task)],
            second_task.task_id: [_violation_trajectory(second_task)],
        },
        oracle={
            first_task.task_id: _oracle(first_task),
            second_task.task_id: _oracle(second_task),
        },
    )

    assert report.pairs_total == 2


def test_pairs_carry_task_and_sample_provenance() -> None:
    from veritool_rl.retail_ops.build.dpo_sampling import build_preference_pairs

    task = _probe_task(-14)
    report = build_preference_pairs(
        tasks=[task],
        samples={task.task_id: [_violation_trajectory(task)]},
        oracle={task.task_id: _oracle(task)},
    )
    pair = report.pairs[0]

    assert pair.source == "policy_boundary_probe"
    assert pair.face_dataset_version == POLICY_BOUNDARY_DATASET_VERSION
    assert pair.face_generator_id == "policy_boundary_sweep_v1"
    assert pair.deadline_offset_days == -14
    assert pair.phrasing_id is None
    assert pair.probe_task_id is None
    assert pair.rejected_violations == ["refund_not_eligible"]
    assert [message["role"] for message in pair.prompt] == ["system", "user"]
    assert pair.tools and all(tool["function"]["name"] for tool in pair.tools)
    assert len(pair.pair_id) == 64


def test_phrasing_face_pairs_are_attributed_to_the_phrasing_source() -> None:
    from veritool_rl.retail_ops.build.dpo_sampling import build_preference_pairs

    tasks = _phrasing_face()
    deny = [task for task in tasks if task.expected_decision is ExpectedDecision.DENY]
    task = next(t for t in deny if t.metadata["deadline_offset_days"] == -14)
    report = build_preference_pairs(
        tasks=[task],
        samples={task.task_id: [_violation_trajectory(task)]},
        oracle={task.task_id: _oracle(task)},
    )
    pair = report.pairs[0]

    assert pair.source == "policy_boundary_phrasing"
    assert pair.face_dataset_version == POLICY_BOUNDARY_PHRASING_DATASET_VERSION
    assert len(pair.phrasing_id) == 64
    assert pair.probe_task_id is not None


def test_per_offset_counts_land_in_the_report() -> None:
    from veritool_rl.retail_ops.build.dpo_sampling import build_preference_pairs

    first = _probe_task(-14)
    second = _probe_task(-10)
    report = build_preference_pairs(
        tasks=[first, second],
        samples={
            first.task_id: [_violation_trajectory(first)],
            second.task_id: [_violation_trajectory(second)],
        },
        oracle={
            first.task_id: _oracle(first),
            second.task_id: _oracle(second),
        },
    )

    assert report.pairs_per_offset == {"offset_-14": 1, "offset_-10": 1}
    assert report.deny_tasks == 2
    assert report.deny_tasks_with_pairs == 2


# ---------------------------------------------------------------------------
# 前提检查与输入校验
# ---------------------------------------------------------------------------


def test_allow_side_execution_errors_trip_the_premise_flag() -> None:
    """门禁守卫方案的前提：放行侧出现执行类错误时调用方必须停下回用户决策。"""
    from veritool_rl.retail_ops.build.dpo_sampling import build_preference_pairs

    task = _probe_task(1)
    order_id = str(task.metadata["order_id"])
    premature_refund = run_episode(
        task,
        _env_factory,
        _ScriptedPolicy(
            [ToolCall(name="refund_order", arguments={"order_id": order_id, "reason": "damaged"})]
        ),
        seed=0,
    )
    assert premature_refund.violations

    report = build_preference_pairs(
        tasks=[task],
        samples={task.task_id: [premature_refund]},
        oracle={task.task_id: _oracle(task)},
    )

    assert report.allow_side_violation_samples == 1
    assert report.premise_ok is False


def test_every_task_must_have_samples_and_an_oracle() -> None:
    from veritool_rl.retail_ops.build.dpo_sampling import build_preference_pairs

    task = _probe_task(-14)
    with pytest.raises(ValueError, match="采样"):
        build_preference_pairs(tasks=[task], samples={}, oracle={task.task_id: _oracle(task)})
    with pytest.raises(ValueError, match="Oracle"):
        build_preference_pairs(
            tasks=[task], samples={task.task_id: [_violation_trajectory(task)]}, oracle={}
        )


def test_unknown_face_dataset_version_is_rejected() -> None:
    from veritool_rl.retail_ops.build.dpo_sampling import build_preference_pairs

    task = _probe_task(-14).model_copy(
        update={
            "metadata": {**_probe_task(-14).metadata, "dataset_version": "not_a_registered_face"}
        }
    )
    with pytest.raises(ValueError, match="dataset_version"):
        build_preference_pairs(
            tasks=[task],
            samples={task.task_id: [_violation_trajectory(task)]},
            oracle={task.task_id: _oracle(task)},
        )


def test_sample_seed_is_deterministic_and_index_sensitive() -> None:
    from veritool_rl.retail_ops.build.dpo_sampling import sample_seed

    assert sample_seed("task-a", 0) == sample_seed("task-a", 0)
    assert sample_seed("task-a", 0) != sample_seed("task-a", 1)
    assert sample_seed("task-a", 0) != sample_seed("task-b", 0)


def test_sampling_settings_lock_the_preregistered_contract() -> None:
    from pydantic import ValidationError

    from veritool_rl.retail_ops.build.dpo_sampling import SamplingSettings

    settings = SamplingSettings()
    assert settings.do_sample is True
    assert settings.temperature == 0.8
    assert settings.top_p == 1.0
    assert settings.top_k == 0
    assert settings.enable_thinking is False
    assert settings.quantization == "nf4"
    assert settings.generate_kwargs() == {
        "do_sample": True,
        "temperature": 0.8,
        "top_p": 1.0,
        "top_k": 0,
    }

    with pytest.raises(ValidationError):
        SamplingSettings(temperature=0.7)  # type: ignore[arg-type]


def test_both_faces_are_combined_into_one_sampling_face() -> None:
    from veritool_rl.retail_ops.build.dpo_sampling import build_sampling_face

    tasks = build_sampling_face(seed=0, phrasing_index=_phrasing_index())

    assert len(tasks) == 240
    versions = {task.metadata["dataset_version"] for task in tasks}
    assert versions == {POLICY_BOUNDARY_DATASET_VERSION, POLICY_BOUNDARY_PHRASING_DATASET_VERSION}


def _phrasing_index() -> dict[str, Any]:
    accepted = [
        (INTENT_REFUND, "test-style", f"麻烦帮我处理第 {index} 号形态的退款请求 {{order_id}}。")
        for index in range(2000)
    ]
    records = [r for r in build_records(accepted) if r.partition == "ood_dev"]
    return {INTENT_REFUND: records}


# ---------------------------------------------------------------------------
# prompt/completion 切分
# ---------------------------------------------------------------------------


def test_prompt_completion_split_keeps_system_and_user_in_the_prompt() -> None:
    from veritool_rl.retail_ops.build.dpo_sampling import split_prompt_completion

    task = _probe_task(-14)
    prompt, completion = split_prompt_completion(_violation_trajectory(task))

    assert [message["role"] for message in prompt] == ["system", "user"]
    assert prompt[1]["content"] == task.user_request
    assert completion
    assert all(message["role"] in {"assistant", "tool"} for message in completion)


# ---------------------------------------------------------------------------
# 断点续跑与运行配置
# ---------------------------------------------------------------------------


def test_sample_files_round_trip_through_json() -> None:
    """断点续跑依赖轨迹 JSON 往返保真——失真会让 rejected 不再是真实采样。"""
    task = _probe_task(-14)
    trajectory = _violation_trajectory(task)

    restored = Trajectory.model_validate_json(trajectory.model_dump_json())

    assert restored == trajectory


def _sampling_script_module() -> Any:
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "run_dpo_sampling", REPO_ROOT / "scripts/retail_ops/run_dpo_sampling.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_dpo_sampling"] = module
    spec.loader.exec_module(module)
    return module


def test_the_committed_sampling_config_matches_the_preregistration() -> None:
    """运行配置在观测之前与预注册逐字段对齐（温度/条数/分片/候选 pin）。"""
    import yaml

    module = _sampling_script_module()
    raw = yaml.safe_load(
        (REPO_ROOT / "configs/retail_ops/build/retail_ops_dpo_sampling.yaml").read_text(
            encoding="utf-8"
        )
    )
    config = module.DpoSamplingConfig.model_validate(raw)

    assert config.pipeline == "dpo_sampling"
    assert config.seed == 0
    assert config.sampling.samples_per_task == 8
    assert config.sampling.max_new_tokens == 256
    assert config.phrasing.partition == "ood_dev"
    assert config.phrasing.bank_relpath == "phrasing/phrasing-bank-004/phrasings.jsonl"
    assert config.phrasing.bank_sha256.startswith("f4b14e8d")
    assert config.adapter.run_dir == "reports/retail_ops/v1/r6/sft-008"
    assert config.model.local_dir == "Qwen3-4B-pinned"


def test_bank_hash_verification_uses_the_content_hash_not_file_bytes(
    tmp_path: Path,
) -> None:
    """声明哈希 = `bank_sha256(records)` 内容哈希（与 _run_ood_build 同一语义）。

    突变验证：若改回文件字节哈希，本测试的「非文件哈希声明值」分支会红——
    R11-1 首次远端启动正是被这个语义差拦下（文件 sha ≠ 内容哈希）。
    """
    import pytest as _pytest

    from veritool_rl.retail_ops.build.phrasing_bank import (
        bank_sha256,
        build_records,
        write_phrasing_bank,
    )

    module = _sampling_script_module()
    records = build_records(
        [(INTENT_REFUND, "test-style", f"第 {i} 号退款说法 {{order_id}}。") for i in range(30)]
    )
    bank_path = tmp_path / "phrasings.jsonl"
    write_phrasing_bank(bank_path, records)

    returned, actual = module._verify_bank_sha256(bank_path, bank_sha256(records))

    assert [r.phrasing_id for r in returned] == [r.phrasing_id for r in records]
    assert actual == bank_sha256(records)
    assert actual != "0" * 64

    import hashlib

    file_bytes_sha = hashlib.sha256(bank_path.read_bytes()).hexdigest()
    assert file_bytes_sha != bank_sha256(records)
    with _pytest.raises(ValueError, match="内容哈希"):
        module._verify_bank_sha256(bank_path, file_bytes_sha)
