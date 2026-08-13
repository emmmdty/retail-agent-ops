"""R2 CPU 端到端 fake 验收：formal_freeze 确定性、teacher_collect 混合结果、
train_export 240 条导出，以及两个 Qwen dev base 配置在 fake backend 下的完整
运行。全程只用 tmp_path 隔离根 + fake client/backend/hardware，绝不生成仓库
真正的正式数据集输出位置，也绝不加载真实模型或触碰 CUDA。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from veritool_rl.core.agent.qwen import GeneratedText, GpuMeasurement, hash_local_model_files
from veritool_rl.core.trajectory import ToolCall
from veritool_rl.retail_ops.build.formal_manifests import (
    load_formal_task_manifest,
    load_verified_formal_dataset,
)
from veritool_rl.retail_ops.build.teacher_client import TeacherResponse
from veritool_rl.retail_ops.build.teacher_data import TeacherAttemptEvidence
from veritool_rl.retail_ops.build.teacher_route import TeacherRouteSnapshot
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.formal_tasks import FormalTaskRecord, build_formal_task_set
from veritool_rl.retail_ops.evaluate.base_evaluation import (
    load_base_run_evidence,
    load_verified_formal_dev,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_VERSION = "retail_ops_v1_r2_20260722"
BUNDLE_REL = Path("domains/retail_ops/v1")
PUBLIC_REL = Path("manifests/retail_ops/v1") / DATASET_VERSION
PRIVATE_REL = Path("data/private/retail_ops/v1/r2") / DATASET_VERSION
MODEL_FILES = ("config.json", "model.safetensors", "tokenizer.json")

_VALID_ENVIRON = {
    "TEACHER_LLM_PROVIDER": "acme",
    "TEACHER_LLM_ACME_BASE_URL": "https://teacher.example.com/v1",
    "TEACHER_LLM_ACME_API_KEY": "sk-test-not-a-real-key",
    "TEACHER_LLM_ACME_MODEL": "acme-teacher-1",
}


def _fresh_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> Path:
    root = tmp_path / name
    shutil.copytree(REPO_ROOT / BUNDLE_REL, root / BUNDLE_REL)
    monkeypatch.chdir(root)
    return root


# ---------------------------------------------------------------------------
# formal_freeze determinism across two isolated roots
# ---------------------------------------------------------------------------


def test_formal_freeze_is_byte_identical_across_two_isolated_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from veritool_rl.product_cli import main

    config_path = REPO_ROOT / "configs" / "retail_ops/build/retail_ops_v1_r2_formal_freeze.yaml"
    roots: list[Path] = []
    for name in ("run-a", "run-b"):
        root = _fresh_workspace(tmp_path, monkeypatch, name)
        exit_code = main(
            [
                "build",
                "--config",
                str(config_path),
                "--output_dir",
                str(root / PUBLIC_REL),
            ]
        )
        assert exit_code == 0
        roots.append(root)

    monkeypatch.undo()  # stop chdir from leaking into later assertions/tests

    public_names = ("dataset.json", "train.json", "dev.json", "holdout-receipt.json")
    private_names = ("train.jsonl", "dev.jsonl", "holdout.jsonl")
    for name in public_names:
        left = (roots[0] / PUBLIC_REL / name).read_bytes()
        right = (roots[1] / PUBLIC_REL / name).read_bytes()
        assert left == right, f"public {name} 在两个独立根之间不是逐字节一致"
    for name in private_names:
        left = (roots[0] / PRIVATE_REL / name).read_bytes()
        right = (roots[1] / PRIVATE_REL / name).read_bytes()
        assert left == right, f"private {name} 在两个独立根之间不是逐字节一致"


# ---------------------------------------------------------------------------
# shared: a pre-built formal dataset + bundle, reused by teacher/export/dev-base
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _formal_source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from veritool_rl.retail_ops.build.formal_manifests import write_formal_task_set

    root = tmp_path_factory.mktemp("r2-e2e-source")
    bundle_dst = root / BUNDLE_REL
    shutil.copytree(REPO_ROOT / BUNDLE_REL, bundle_dst)
    bundle = load_bundle(bundle_dst)
    task_set = build_formal_task_set(DATASET_VERSION, seed=0)
    write_formal_task_set(task_set, bundle, root / PRIVATE_REL, root / PUBLIC_REL)
    return root


@pytest.fixture
def workspace(_formal_source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shutil.copytree(_formal_source, tmp_path, dirs_exist_ok=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# teacher_collect controlled pass/fallback mix -> train_export 240 rows
# ---------------------------------------------------------------------------


class _MixedOracleTeacherClient:
    """按 record 的 gold 调用序列回放；被标记为"应失败"的任务永远给非法工具调用。

    这样可以对全部 6 个场景通用地构造一份"部分接受、部分回退"的证据集合，
    不需要为每个场景单独手写脚本。失败任务用统一的 illegal-tool 分类
    （`ILLEGAL_TOOL`，不被接受），成功任务精确回放 `task.expected_calls`。
    """

    def __init__(self, records: list[FormalTaskRecord], fail_task_ids: set[str]) -> None:
        self._record_by_request = {record.task.user_request: record for record in records}
        self._fail_task_ids = fail_task_ids

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        temperature: float = 0.0,
    ) -> TeacherResponse:
        del tools, temperature
        user_request = messages[1]["content"]
        record = self._record_by_request[user_request]
        if record.task.task_id in self._fail_task_ids:
            return TeacherResponse(
                model="fake-teacher",
                tool_calls=(ToolCall(name="not_a_real_tool", arguments={}),),
            )
        completed = sum(
            1
            for message in messages
            if message.get("role") == "assistant" and message.get("tool_calls")
        )
        expected = record.task.expected_calls
        if completed < len(expected):
            call = expected[completed]
            return TeacherResponse(model="fake-teacher", tool_calls=(call.model_copy(deep=True),))
        return TeacherResponse(model="fake-teacher", content="已完成核实。")


def _client_factory(records: list[FormalTaskRecord], fail_task_ids: set[str]):
    def factory(route: TeacherRouteSnapshot, api_key: str) -> _MixedOracleTeacherClient:
        del route, api_key
        return _MixedOracleTeacherClient(records, fail_task_ids)

    return factory


def test_teacher_collect_mixed_results_then_export_240_trajectories(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from veritool_rl.product_cli import (
        _run_teacher_collect,
        _run_train_export,
        build_product_parser,
    )
    from veritool_rl.retail_ops.build.formal_manifests import load_formal_split

    dataset = load_verified_formal_dataset(PUBLIC_REL)
    train_records = list(load_formal_split(dataset, "train", PRIVATE_REL / "train.jsonl"))
    assert len(train_records) == 240

    # 每 40 条一个类别 block，各 block 前 8 条标记失败 -> 每类别 80% 接受，
    # 整体 80% 接受，同时越过 70% 整体门槛与 50% 逐类别门槛，且确实产生了
    # teacher 接受 + internal_reference 回退的混合。
    fail_task_ids = {
        record.task.task_id for index, record in enumerate(train_records) if (index % 40) < 8
    }
    assert len(fail_task_ids) == 48

    parser = build_product_parser()
    teacher_config = {
        "pipeline": "teacher_collect",
        "bundle_dir": str(BUNDLE_REL),
        "public_dir": str(PUBLIC_REL),
        "dataset_version": DATASET_VERSION,
        "attempt_id": "e2e-teacher-001",
        "max_episodes_per_task": 2,
        "max_request_attempts": 3,
    }
    teacher_args = parser.parse_args(
        [
            "build",
            "--config",
            "unused.yaml",
            "--input_dir",
            str(PRIVATE_REL),
            "--output_dir",
            str(workspace / "teacher-summary"),
        ]
    )

    _run_teacher_collect(
        teacher_args,
        teacher_config,
        environ=_VALID_ENVIRON,
        client_factory=_client_factory(train_records, fail_task_ids),
    )

    attempt_dir = PRIVATE_REL / "teacher-collection" / "e2e-teacher-001"
    evidence_paths = sorted(p for p in attempt_dir.glob("*.json") if p.name != "checkpoint.json")
    assert len(evidence_paths) == 240
    evidences = [
        TeacherAttemptEvidence.model_validate_json(p.read_text("utf-8")) for p in evidence_paths
    ]
    accepted_ids = {evidence.task_id for evidence in evidences if evidence.accepted}
    assert len(accepted_ids) == 240 - 48
    assert accepted_ids.isdisjoint(fail_task_ids)

    summary = json.loads((workspace / "teacher-summary" / "summary.json").read_text("utf-8"))
    assert summary["total_accepted"] == 192
    assert summary["train_task_count"] == 240
    # 公开侧摘要不含任何 task_id
    summary_text = json.dumps(summary)
    assert not any(task_id in summary_text for task_id in fail_task_ids)

    export_config = {
        "pipeline": "train_export",
        "bundle_dir": str(BUNDLE_REL),
        "public_dir": str(PUBLIC_REL),
        "dataset_version": DATASET_VERSION,
        "teacher_attempt_id": "e2e-teacher-001",
        "attempt_id": "e2e-export-001",
        "sft_oversample": {},
        "sft_terminal_response": [],
        "sft_system_prompt_sha256": None,
    }
    export_args = parser.parse_args(
        [
            "build",
            "--config",
            "unused.yaml",
            "--input_dir",
            str(PRIVATE_REL),
            "--output_dir",
            str(workspace / "export-quality"),
        ]
    )

    _run_train_export(export_args, export_config)

    export_dir = PRIVATE_REL / "train-export" / "e2e-export-001"
    train_rows = (export_dir / "train.jsonl").read_text("utf-8").splitlines()
    sft_rows = (export_dir / "sft.jsonl").read_text("utf-8").splitlines()
    selection = json.loads((export_dir / "selection.json").read_text("utf-8"))
    assert len(train_rows) == 240
    assert len(sft_rows) == 240
    assert len(selection) == 240

    sources = {item["task_id"]: item["source"] for item in selection}
    teacher_sourced = {task_id for task_id, source in sources.items() if source == "teacher"}
    fallback_sourced = {
        task_id for task_id, source in sources.items() if source == "internal_reference"
    }
    assert teacher_sourced == accepted_ids
    assert fallback_sourced == fail_task_ids

    quality = json.loads((workspace / "export-quality" / "quality.json").read_text("utf-8"))
    assert quality["passes_gate"] is True
    assert quality["total_accepted"] == 192
    assert quality["total_tasks"] == 240
    quality_text = json.dumps(quality)
    for record in train_records:
        assert record.task.task_id not in quality_text
        assert record.task.user_request not in quality_text

    # R4：同一批任务与证据再导出一次，只加重复采样。走完整 CLI 路径，证明
    # 因子确实从 YAML 穿到产物，而不是只有 export_formal_train 的单测覆盖。
    rebalanced_config = {
        **export_config,
        "attempt_id": "e2e-export-002",
        "sft_oversample": {"refund_eligible": 3, "refund_recovery": 3},
        "sft_terminal_response": [],
        "sft_system_prompt_sha256": None,
    }
    rebalanced_args = parser.parse_args(
        [
            "build",
            "--config",
            "unused.yaml",
            "--input_dir",
            str(PRIVATE_REL),
            "--output_dir",
            str(workspace / "export-quality-rebalanced"),
        ]
    )
    _run_train_export(rebalanced_args, rebalanced_config)

    rebalanced_dir = PRIVATE_REL / "train-export" / "e2e-export-002"
    # provenance 两份文件必须与未重采样的那次逐字节相同：重采样只动训练输入。
    for name in ("train.jsonl", "selection.json"):
        assert (rebalanced_dir / name).read_bytes() == (export_dir / name).read_bytes()
    rebalanced_sft = (rebalanced_dir / "sft.jsonl").read_text("utf-8").splitlines()
    assert len(rebalanced_sft) == 240 + 80 * 2  # 两个多步家族各 40 条，×3 即各多出 80 条

    scenario_by_task = {record.task.task_id: record.task.scenario.value for record in train_records}
    counts: dict[str, int] = {}
    for line in rebalanced_sft:
        scenario = scenario_by_task[json.loads(line)["task_id"]]
        counts[scenario] = counts.get(scenario, 0) + 1
    assert counts["refund_eligible"] == 120
    assert counts["refund_recovery"] == 120
    assert counts["lookup_status"] == 40

    manifest = json.loads((rebalanced_dir / "sft_oversample.json").read_text("utf-8"))
    assert manifest == {
        "factors": {"refund_eligible": 3, "refund_recovery": 3},
        "train_row_count": 240,
        "sft_row_count": 400,
    }


# ---------------------------------------------------------------------------
# both Qwen dev-base configs through fake backends
# ---------------------------------------------------------------------------


class _ScriptedDevBackend:
    """确定性 fake 生成后端：先查订单，再给最终确认文本。"""

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_new_tokens: int,
    ) -> GeneratedText:
        del max_new_tokens
        assert tools and tools[0]["type"] == "function"
        if any(message["role"] == "assistant" for message in messages):
            return GeneratedText(text="已完成核实。", input_tokens=48, output_tokens=6)
        import re

        match = re.search(r"O-[A-Z0-9]{12}", str(messages[-1]["content"]))
        assert match is not None
        import json as _json

        payload = _json.dumps({"name": "get_order", "arguments": {"order_id": match.group(0)}})
        return GeneratedText(
            text=f"<tool_call>{payload}</tool_call>", input_tokens=32, output_tokens=17
        )


def _fake_backend_factory(config: Any, models_root: Path) -> _ScriptedDevBackend:
    del config, models_root
    return _ScriptedDevBackend()


class _FakeHardwareProvider:
    def reset_peak_memory(self) -> None:
        return None

    def measure(self) -> GpuMeasurement:
        return GpuMeasurement(
            gpu_index=0,
            gpu_uuid="GPU-8f6d3c21-4b5a-4c7d-9e10-2f3a4b5c6d7e",
            gpu_name="fake-gpu",
            cuda_visible_devices="0",
            cuda_device="cuda:0",
            peak_memory_bytes=1024,
        )


def _fake_hardware_factory() -> _FakeHardwareProvider:
    return _FakeHardwareProvider()


def _fake_code_commit_factory() -> str:
    """CPU 测试注入缝：默认路径会拒绝脏工作树，这里与仓库 git 状态解耦。"""
    return "1" * 40


@pytest.mark.parametrize(
    "config_name",
    [
        "retail_ops/evaluate/retail_ops_v1_r2_qwen3_1_7b_dev.yaml",
        "retail_ops/evaluate/retail_ops_v1_r2_qwen3_4b_dev.yaml",
    ],
)
def test_both_qwen_dev_base_configs_run_through_fake_backends(
    workspace: Path, tmp_path: Path, config_name: str
) -> None:
    from veritool_rl.cli import load_config
    from veritool_rl.product_cli import _run_formal_dev_base, build_product_parser

    config = load_config(REPO_ROOT / "configs" / config_name)
    models_root_name = config["models_root"]
    local_dir = config["model"]["local_dir"]
    model_dir = workspace / models_root_name / local_dir
    model_dir.mkdir(parents=True)
    (model_dir / "config.json").write_text('{"model_type":"qwen3"}', encoding="utf-8")
    (model_dir / "model.safetensors").write_bytes(b"fake-weights-for-cpu-test")
    (model_dir / "tokenizer.json").write_text('{"version":"1.0"}', encoding="utf-8")
    # 提交的 config 里 model.revision/file_sha256 只是占位值（真实权重尚未下载/
    # 审批）；这里用测试自建的 fake 本地文件重新计算真实哈希再覆盖，其余字段
    # （dataset_version/bundle_dir/generation/models_root/attempt_id/pipeline）
    # 保持和仓库里已提交的 config 完全一致。
    config["model"]["file_sha256"] = hash_local_model_files(model_dir, MODEL_FILES)

    output_dir = tmp_path / f"out-{config_name}"
    parser = build_product_parser()
    args = parser.parse_args(
        [
            "evaluate",
            "--config",
            "unused.yaml",
            "--input_dir",
            str(PRIVATE_REL),
            "--output_dir",
            str(output_dir),
        ]
    )

    _run_formal_dev_base(
        args,
        config,
        backend_factory=_fake_backend_factory,
        hardware_provider_factory=_fake_hardware_factory,
        code_commit_factory=_fake_code_commit_factory,
    )

    report_path = output_dir / "base-report.json"
    evidence = load_base_run_evidence(report_path, verify_artifacts=False)
    assert evidence.task_count == 60
    assert evidence.dataset_version == DATASET_VERSION
    assert evidence.seed == 0
    assert evidence.max_steps == 5
    assert evidence.model.repo == config["model"]["repo"]
    assert evidence.model.local_dir == local_dir

    private_attempt_dir = PRIVATE_REL / "dev-base" / config["attempt_id"]
    reloaded = load_base_run_evidence(private_attempt_dir / "run.json")
    assert reloaded.task_count == 60

    dev_manifest = load_formal_task_manifest(PUBLIC_REL / "dev.json")
    dev_records = load_verified_formal_dev(PRIVATE_REL, dev_manifest)

    report_text = report_path.read_text(encoding="utf-8")
    for record in dev_records:
        assert record.task.task_id not in report_text
        assert record.task.user_request not in report_text
        assert record.task_fingerprint not in report_text
