"""Task 3: v3 tool count degradation curve — standalone runner.

For each breakpoint N in {6, 9, 12, 15}, runs:
1. Teacher collection (DeepSeek via OpenAI-compatible API)
2. SFT data export
3. QLoRA training
4. Dev evaluation (base + candidate)

{3} breakpoint reuses sft-008 from retail_ops v1.

Usage on gpu-5090:
    cd /mnt/aidata/tongjiakai/retail-agent-ops
    set -a && source .env && set +a
    .venv/bin/python scripts/run_v3_degradation.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from veritool_rl.core.agent.qwen import GenerationSettings, QwenPolicy
from veritool_rl.core.generators import trajectory_to_sft_example
from veritool_rl.retail_ops.build.teacher_data import (
    TeacherCollectionConfig,
    collect_teacher_attempt,
    write_teacher_attempt_evidence,
    write_teacher_checkpoint,
    load_teacher_checkpoint,
    load_teacher_route,
)
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
from veritool_rl.retail_ops.domain.v3_tasks import (
    ToolCountTaskRecord,
    build_toolcount_task_set,
)
from veritool_rl.retail_ops.evaluate.evaluation import run_evaluation

BUNDLE_DIR = PROJECT_ROOT / "domains/retail_ops/v1"
REPORTS_ROOT = PROJECT_ROOT / "reports" / "retail_ops" / "v1" / "r10"


def _env_factory():
    bundle = load_bundle(BUNDLE_DIR)
    return lambda: RetailOpsEnv(bundle)


def run_teacher_collection(tool_count: int, output_dir: Path) -> int:
    """Collect teacher trajectories for v3 tool count breakpoint."""
    tag = f"toolcount-{tool_count}"
    version = f"retail_ops_v3_tc{tool_count}_20260824"

    task_set = build_toolcount_task_set(version, seed=0, tool_count=tool_count)
    train_records = task_set.records("train")
    print(f"  Tasks: {len(train_records)} train")

    route, api_key = load_teacher_route(os.environ)
    from openai import OpenAI

    raw_client = OpenAI(api_key=api_key, base_url=route.base_url)
    client = route.client_factory(raw_client, api_key)

    config = TeacherCollectionConfig(
        dataset_version=version,
        attempt_id=f"v3-{tag}",
        seed=0,
        max_episodes_per_task=2,
        max_request_attempts=3,
        bundle_sha256="v3-toolcount",
        tool_schema_sha256="v3-toolcount",
        system_prompt_sha256="v3-toolcount",
        config_sha256="v3-toolcount",
    )

    evidence_dir = output_dir / "teacher"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    checkpoint = load_teacher_checkpoint(evidence_dir, f"v3-{tag}", config)
    attempted_ids = {r.task.task_id for r in checkpoint.attempts} if checkpoint else set()

    accepted = 0
    rejected = 0
    skipped = 0
    env_factory = _env_factory()

    for i, record in enumerate(train_records):
        if record.task.task_id in attempted_ids:
            skipped += 1
            continue

        try:
            evidence = collect_teacher_attempt(record, client, env_factory, config)
            write_teacher_attempt_evidence(evidence, evidence_dir)
            if evidence.outcome.value == "accepted":
                accepted += 1
            else:
                rejected += 1
        except Exception as e:
            rejected += 1
            print(f"  Error on task {i}: {e}")

        if (i + 1) % 40 == 0:
            print(f"  [{i+1}/{len(train_records)}] accepted={accepted} rejected={rejected}")

    print(f"  Teacher: {accepted}/{len(train_records)} accepted, {rejected} rejected")
    return accepted


def run_sft_export(tool_count: int, output_dir: Path) -> int:
    """Export SFT data from teacher evidence."""
    evidence_dir = output_dir / "teacher"
    version = f"retail_ops_v3_tc{tool_count}_20260824"
    task_set = build_toolcount_task_set(version, seed=0, tool_count=tool_count)
    train_records = task_set.records("train")

    evidence_files = sorted(evidence_dir.glob("*.json"))
    evidence_files = [f for f in evidence_files if f.name != "checkpoint.json"]

    sft_rows = []
    accepted = 0
    for record in train_records:
        evidence_path = evidence_dir / f"{record.task.task_id}.json"
        if not evidence_path.exists():
            continue
        evidence = json.loads(evidence_path.read_text())
        if evidence.get("outcome") != "accepted":
            continue
        trajectory = evidence.get("trajectory")
        if not trajectory:
            continue
        from veritool_rl.core.trajectory.schema import Trajectory

        traj = Trajectory.model_validate(trajectory)
        sft_example = trajectory_to_sft_example(traj)
        sft_rows.append(sft_example)
        accepted += 1

    sft_dir = output_dir / "sft"
    sft_dir.mkdir(parents=True, exist_ok=True)
    sft_path = sft_dir / "sft.jsonl"
    with sft_path.open("w") as f:
        for row in sft_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"  SFT export: {accepted} rows -> {sft_path}")
    return accepted


def run_training(tool_count: int, output_dir: Path) -> bool:
    """Train QLoRA adapter."""
    from veritool_rl.training.sft import run_sft

    sft_path = output_dir / "sft" / "sft.jsonl"
    if not sft_path.exists():
        print(f"  SFT file not found: {sft_path}")
        return False

    train_config = {
        "model": {
            "repo": "Qwen/Qwen3-4B",
            "revision": "8cd0101f70cac4f1efcebc979faf483558e39297",
            "local_dir": "Qwen3-4B-pinned",
        },
        "lora": {"r": 16, "alpha": 32, "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj"]},
        "data": {"train_relpath": str(sft_path.relative_to(PROJECT_ROOT))},
        "training": {
            "num_train_epochs": 3,
            "per_device_train_batch_size": 4,
            "learning_rate": 2e-4,
            "max_seq_length": 2048,
        },
    }

    adapter_dir = output_dir / "adapter"
    adapter_dir.mkdir(parents=True, exist_ok=True)
    run_sft(train_config, seed=0, output_dir=adapter_dir)
    print(f"  Training complete: {adapter_dir}")
    return True


def run_evaluation(tool_count: int, output_dir: Path, adapter_path: str | None = None) -> dict:
    """Evaluate on dev set."""
    version = f"retail_ops_v3_tc{tool_count}_20260824"
    task_set = build_toolcount_task_set(version, seed=0, tool_count=tool_count)
    dev_records = task_set.records("dev")

    bundle = load_bundle(BUNDLE_DIR)
    gen_settings = GenerationSettings(max_new_tokens=256)
    policy = QwenPolicy.from_config(
        model_dir=str(PROJECT_ROOT / "models" / "Qwen3-4B-pinned"),
        adapter_dir=adapter_path,
        generation_settings=gen_settings,
    )

    env_factory = _env_factory()
    evidence = run_evaluation(
        dev_records,
        policy,
        env_factory,
        bundle,
        gen_settings,
    )

    report_dir = output_dir / "eval"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "report.json").write_text(
        json.dumps(evidence.model_dump(mode="json"), indent=2)
    )

    metrics = evidence.metrics
    print(f"  Eval: task_success={metrics.get('task_success', 0):.4f}, "
          f"pv={metrics.get('policy_violation_count', 0)}, "
          f"tool_acc={metrics.get('tool_selection_accuracy', 0):.4f}")
    return metrics


def main() -> None:
    results = {}

    for tool_count in [6, 9, 12, 15]:
        print(f"\n{'='*50}")
        print(f"Tool count: {tool_count}")
        print(f"{'='*50}")

        output_dir = REPORTS_ROOT / f"toolcount-{tool_count}"
        done_marker = output_dir / "done"

        if done_marker.exists():
            print("Already done, loading results")
            report_path = output_dir / "eval" / "report.json"
            if report_path.exists():
                report = json.loads(report_path.read_text())
                results[tool_count] = report.get("metrics", {})
            continue

        # 1. Teacher collection
        print("\n[1/4] Teacher collection...")
        accepted = run_teacher_collection(tool_count, output_dir)

        # 2. SFT export
        print("\n[2/4] SFT export...")
        sft_rows = run_sft_export(tool_count, output_dir)

        # 3. Training
        print("\n[3/4] Training...")
        success = run_training(tool_count, output_dir)

        # 4. Base eval
        print("\n[4a/4] Base eval...")
        base_metrics = run_evaluation(tool_count, output_dir, adapter_path=None)

        # 4b. Candidate eval
        print("\n[4b/4] Candidate eval...")
        adapter_dir = output_dir / "adapter"
        cand_metrics = run_evaluation(
            tool_count,
            output_dir / "candidate",
            adapter_path=str(adapter_dir) if adapter_dir.exists() else None,
        )

        results[tool_count] = {
            "base": base_metrics,
            "candidate": cand_metrics,
            "accepted": accepted,
        }

        done_marker.write_text(json.dumps(results[tool_count], indent=2))
        print(f"Completed {tool_count} tools")

    # Summary
    print(f"\n{'='*50}")
    print("Degradation Curve Summary")
    print(f"{'='*50}")
    print(f"{'Tools':>6} {'Base':>8} {'Cand':>8} {'Delta':>8} {'PV':>6} {'ToolAcc':>8}")
    for tc in sorted(results.keys()):
        r = results[tc]
        base = r.get("base", r)
        cand = r.get("candidate", r)
        bs = base.get("task_success", 0) if isinstance(base, dict) else 0
        cs = cand.get("task_success", 0) if isinstance(cand, dict) else 0
        pv = cand.get("policy_violation_count", 0) if isinstance(cand, dict) else 0
        ta = cand.get("tool_selection_accuracy", 0) if isinstance(cand, dict) else 0
        print(f"{tc:>6} {bs:>8.4f} {cs:>8.4f} {cs-bs:>+8.4f} {pv:>6} {ta:>8.4f}")

    # Save summary
    summary_path = REPORTS_ROOT / "degradation_summary.json"
    summary_path.write_text(json.dumps(results, indent=2))
    print(f"\nSummary saved to {summary_path}")


if __name__ == "__main__":
    main()
