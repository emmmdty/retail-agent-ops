"""构造一份字段齐全的 `BaseRunEvidence`，只用于哈希口径测试。

内容全是占位值——这些测试关心的是**哪些字段进入自哈希**，不是字段的语义。
"""

from __future__ import annotations

from typing import Any

from veritool_rl.core.agent.qwen import GenerationSettings, GpuMeasurement
from veritool_rl.retail_ops.evaluate.base_evaluation import (
    BaseRunEvidence,
    HardwareProvenance,
    ModelArtifact,
)


def make_base_evidence(**overrides: Any) -> BaseRunEvidence:
    payload: dict[str, Any] = {
        "run_id": "0" * 64,
        "dataset_version": "retail_ops_v1_r2_20260722",
        "generator_id": "g",
        "bundle_id": "retail_ops",
        "bundle_version": "v1",
        "bundle_sha256": "1" * 64,
        "parser_id": "p",
        "evaluator_id": "e",
        "dev_manifest_sha256": "2" * 64,
        "dev_artifact_sha256": "3" * 64,
        "system_prompt_sha256": "4" * 64,
        "tool_schema_sha256": "5" * 64,
        "config_sha256": "6" * 64,
        "code_commit": "a" * 40,
        "uv_lock_sha256": "7" * 64,
        "policy_id": "Qwen/Qwen3-4B@8cd0101f",
        "model": ModelArtifact(
            repo="Qwen/Qwen3-4B",
            revision="8cd0101f",
            local_dir="Qwen3-4B-pinned",
            file_sha256={"config.json": "8" * 64},
        ),
        "generation": GenerationSettings(max_new_tokens=256),
        "hardware": HardwareProvenance(
            gpu=GpuMeasurement(
                gpu_index=0,
                gpu_uuid="GPU-00000000-0000-0000-0000-000000000000",
                gpu_name="fake",
                cuda_visible_devices="0",
                cuda_device="cuda:0",
                peak_memory_bytes=1,
            ),
            wall_time_seconds=1.0,
            tasks_per_second=1.0,
            output_tokens_per_second=1.0,
        ),
        "task_count": 60,
        "category_counts": {"refund_eligible": 10},
        "metrics": {"task_success": 1.0},
        "replayable_count": 60,
        "evidence_complete": True,
        "artifact_sha256": {
            "config.json": "9" * 64,
            "trajectories.jsonl": "a" * 64,
            "metrics.json": "b" * 64,
            "failures.jsonl": "c" * 64,
        },
    }
    payload.update(overrides)
    return BaseRunEvidence(**payload)
