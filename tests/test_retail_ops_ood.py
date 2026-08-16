"""P0-1：分布外任务集与它的评测路径。

评审口径：`domain/formal_tasks.py:_user_request` 只有 6 场景 × 2 变体 = **12 句模板**，
train / dev / holdout 共用它们。五维指纹保证"没有逐字重复"，**不是"没有分布重叠"**。
因此 120/120 只能说明模板内插值成功。这个集合是那句话的对照组。

三条性质在这里被锁住：

1. **它是独立 dataset artifact**——冻结数据集与其配额一个字节不变；
2. **任务本身可解**——否则"模型做不到"与"任务设计错了"分不开；
3. **逐类别指标是核心**——整体成功率会把不同失败原因平均掉。
"""

from __future__ import annotations

import shutil
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from veritool_rl.core.agent.policy import OraclePolicy
from veritool_rl.core.agent.qwen import GeneratedText, GenerationSettings, GpuMeasurement
from veritool_rl.core.agent.runner import run_episode
from veritool_rl.retail_ops.build.ood_manifests import (
    build_ood_task_set,
    load_ood_manifest,
    load_ood_tasks,
)
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
from veritool_rl.retail_ops.domain.ood_tasks import (
    OOD_CATEGORIES,
    OOD_DATASET_VERSION,
    build_ood_tasks,
    ood_category,
)
from veritool_rl.retail_ops.evaluate.base_evaluation import ModelArtifact
from veritool_rl.retail_ops.evaluate.ood_evaluation import OodEvaluationConfig, evaluate_ood

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_REL = Path("domains/retail_ops/v1")


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    shutil.copytree(REPO_ROOT / BUNDLE_REL, tmp_path / BUNDLE_REL)
    build_ood_task_set(tmp_path / BUNDLE_REL, 0, tmp_path / "ood")
    return tmp_path


# ---------------------------------------------------------------------------
# 独立性：冻结数据集不受影响
# ---------------------------------------------------------------------------


def test_the_ood_set_is_a_separate_dataset_artifact(workspace: Path) -> None:
    manifest = load_ood_manifest(workspace / "ood" / "manifest.json")

    assert manifest.dataset_version == OOD_DATASET_VERSION
    assert manifest.dataset_version != "retail_ops_v1_r2_20260722"
    assert manifest.split == "ood"
    assert manifest.task_count == 60
    assert manifest.category_counts == dict.fromkeys(sorted(OOD_CATEGORIES), 20)


def test_the_frozen_dataset_quotas_are_untouched() -> None:
    """`assert_exact_quotas` 的 40/10/20 一个字不动——这是 OOD 走独立路径的全部理由。"""
    from veritool_rl.retail_ops.domain import formal_tasks

    source = Path(formal_tasks.__file__).read_text(encoding="utf-8")

    assert "def assert_exact_quotas" in source
    assert OOD_DATASET_VERSION not in source, "OOD 不得渗进冻结数据集的代码路径"


def test_the_ood_set_is_deterministic(tmp_path: Path) -> None:
    shutil.copytree(REPO_ROOT / BUNDLE_REL, tmp_path / BUNDLE_REL)

    first = build_ood_task_set(tmp_path / BUNDLE_REL, 0, tmp_path / "a")
    second = build_ood_task_set(tmp_path / BUNDLE_REL, 0, tmp_path / "b")

    assert first.tasks_file_sha256 == second.tasks_file_sha256
    assert first.task_ids == second.task_ids


def test_loading_detects_a_tampered_task_file(workspace: Path) -> None:
    tasks_path = workspace / "ood" / "tasks.jsonl"
    tasks_path.write_text(tasks_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256"):
        load_ood_tasks(workspace / "ood")


# ---------------------------------------------------------------------------
# 任务本身必须可解
# ---------------------------------------------------------------------------


def test_every_ood_task_is_solvable_by_the_oracle() -> None:
    """否则"模型做不到"与"任务设计错了"分不开——那会让整份读数失去意义。"""
    bundle = load_bundle(REPO_ROOT / BUNDLE_REL)
    tasks = build_ood_tasks(0)

    failures = [
        task.metadata["ood_kind"]
        for task in tasks
        if not run_episode(
            task, lambda current: RetailOpsEnv(current, bundle), OraclePolicy(task), 0
        ).success
    ]

    assert failures == [], f"这些类别的 gold 序列解不出来：{Counter(failures)}"


def test_the_gold_sequences_only_use_tools_that_exist() -> None:
    """`tool_bait` 一类在**用户请求文本**里提到不存在的工具，但 gold 序列不得用它。"""
    bundle = load_bundle(REPO_ROOT / BUNDLE_REL)
    allowed = {tool.name for tool in bundle.tools}
    tasks = build_ood_tasks(0)

    baits = [task for task in tasks if task.metadata["ood_kind"] == "tool_bait"]

    assert baits, "对抗类必须包含诱导使用不存在工具的一支"
    assert any("cancel_order" in task.user_request for task in baits)
    for task in tasks:
        assert {call.name for call in task.expected_calls} <= allowed


def test_unsupported_requests_expect_no_state_change() -> None:
    """部分退款 / 换货 / 通融：正确行为是查证后拒绝，任何状态变更都算失败。"""
    tasks = [
        task
        for task in build_ood_tasks(0)
        if task.metadata["ood_kind"] in {"partial_refund", "exchange", "policy_grace"}
    ]

    assert len(tasks) == 15
    for task in tasks:
        assert task.target_state == task.initial_state
        assert [call.name for call in task.expected_calls] == ["get_order"]


def test_expression_variants_keep_the_business_semantics() -> None:
    """表达类只改表面形式：目标状态与 gold 调用序列与原场景相同。"""
    tasks = [task for task in build_ood_tasks(0) if ood_category(task) == "expression_ood"]

    kinds = {task.metadata["ood_kind"] for task in tasks}
    assert kinds == {"colloquial", "greeting_noise", "typo", "code_switch", "terse"}
    for task in tasks:
        assert [call.name for call in task.expected_calls] == ["get_order", "refund_order"]


# ---------------------------------------------------------------------------
# 评测路径
# ---------------------------------------------------------------------------


class _OracleBackend:
    """按每条任务的 gold 序列作答的 fake 后端；用来验证评测管线本身。"""

    def __init__(self) -> None:
        self.model_dir: str | None = None
        self.adapter_path: str | None = None
        self._scripts: dict[str, list[str]] = {}

    def generate(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], max_new_tokens: int
    ) -> GeneratedText:
        del tools, max_new_tokens
        request = next(m["content"] for m in messages if m["role"] == "user")
        script = self._scripts[request]
        step = min(len([m for m in messages if m["role"] == "assistant"]), len(script) - 1)
        return GeneratedText(text=script[step], input_tokens=1, output_tokens=1)

    def load(self, tasks: list[Any]) -> None:
        import json as _json

        for task in tasks:
            calls = [
                "<tool_call>"
                + _json.dumps({"name": c.name, "arguments": c.arguments}, ensure_ascii=False)
                + "</tool_call>"
                for c in task.expected_calls
            ]
            self._scripts[task.user_request] = [*calls, "已处理完毕。"]


class _FakeHardware:
    def reset_peak_memory(self) -> None:
        return None

    def measure(self) -> GpuMeasurement:
        return GpuMeasurement(
            gpu_index=0,
            gpu_uuid="GPU-00000000-0000-0000-0000-000000000000",
            gpu_name="fake",
            cuda_visible_devices="0",
            cuda_device="cuda:0",
            peak_memory_bytes=1,
        )


def test_the_ood_evaluation_reports_per_category_and_per_kind_success(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """逐类别与逐 kind 指标是这份证据的核心：整体成功率会把不同失败原因平均掉。"""
    import veritool_rl.retail_ops.evaluate.ood_evaluation as module

    monkeypatch.setattr(module, "verify_local_model_files", lambda *a, **k: None)
    bundle = load_bundle(workspace / BUNDLE_REL)
    manifest = load_ood_manifest(workspace / "ood" / "manifest.json")
    tasks = load_ood_tasks(workspace / "ood")
    backend = _OracleBackend()
    backend.load(tasks)

    evidence = evaluate_ood(
        config=OodEvaluationConfig(
            model=ModelArtifact(
                repo="Qwen/Qwen3-4B",
                revision="8cd0101f",
                local_dir="Qwen3-4B-pinned",
                file_sha256={"config.json": "0" * 64},
            ),
            generation=GenerationSettings(max_new_tokens=256),
            code_commit="a" * 40,
        ),
        bundle=bundle,
        manifest=manifest,
        build_dir=workspace / "ood",
        models_root=workspace / "models",
        output_dir=workspace / "out",
        backend_factory=lambda config, root: backend,
        hardware_provider=_FakeHardware(),
    )

    assert evidence.task_count == 60
    assert set(evidence.category_success) == set(OOD_CATEGORIES)
    assert evidence.metrics["task_success"] == 1.0, "gold 序列必须能被评测管线跑通"
    assert evidence.category_success == dict.fromkeys(OOD_CATEGORIES, 1.0)
    assert evidence.evidence_complete is True
    assert evidence.replayable_count == 60
    assert (workspace / "out" / "ood-report.json").is_file()


def test_the_ood_evaluation_rejects_a_mismatched_bundle(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import veritool_rl.retail_ops.evaluate.ood_evaluation as module

    monkeypatch.setattr(module, "verify_local_model_files", lambda *a, **k: None)
    other = workspace / "other-bundle"
    shutil.copytree(workspace / BUNDLE_REL, other)
    policies = other / "policies.yaml"
    policies.write_text(policies.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256"):
        evaluate_ood(
            config=OodEvaluationConfig(
                model=ModelArtifact(
                    repo="Qwen/Qwen3-4B",
                    revision="8cd0101f",
                    local_dir="Qwen3-4B-pinned",
                    file_sha256={"config.json": "0" * 64},
                ),
                generation=GenerationSettings(max_new_tokens=256),
                code_commit="a" * 40,
            ),
            bundle=load_bundle(other),
            manifest=load_ood_manifest(workspace / "ood" / "manifest.json"),
            build_dir=workspace / "ood",
            models_root=workspace / "models",
            output_dir=workspace / "out2",
            backend_factory=lambda config, root: _OracleBackend(),
            hardware_provider=_FakeHardware(),
        )
