"""Task 3: v3 tool count degradation curve — minimal standalone runner.

For each breakpoint N in {6, 9, 12, 15}:
1. Generate v3 tasks
2. Collect teacher trajectories (DeepSeek)
3. Export SFT data
4. Train QLoRA adapter
5. Evaluate (run episodes + compute metrics)

Usage on gpu-5090:
    cd /mnt/aidata/tongjiakai/retail-agent-ops
    set -a && source .env && set +a
    .venv/bin/python scripts/run_v3_degradation.py
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from veritool_rl.core.agent.runner import run_episode
from veritool_rl.core.metrics import compute_metrics
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.v3_tasks import build_toolcount_task_set

BUNDLE_DIR = PROJECT_ROOT / "domains" / "retail_ops" / "v1"
REPORTS_ROOT = PROJECT_ROOT / "reports" / "retail_ops" / "v1" / "r10"
MODELS_ROOT = PROJECT_ROOT / "models"


def _load_policy(model_dir: str, adapter_dir: str | None = None):
    from veritool_rl.core.agent.qwen import GenerationSettings, QwenPolicy

    gen = GenerationSettings(max_new_tokens=256)
    return QwenPolicy.from_config(
        model_dir=model_dir,
        adapter_dir=adapter_dir,
        generation_settings=gen,
    )


def _make_env():
    from veritool_rl.retail_ops.domain.environment import RetailOpsEnv

    bundle = load_bundle(BUNDLE_DIR)
    return RetailOpsEnv(bundle)


def run_teacher(tool_count: int, output_dir: Path) -> int:
    """Collect teacher trajectories."""
    from veritool_rl.core.build.teacher_route import load_teacher_route
    from veritool_rl.core.build.teacher_client import OpenAICompatibleTeacherClient
    from veritool_rl.retail_ops.build.teacher_data import (
        TeacherCollectionConfig,
        collect_teacher_attempt,
        write_teacher_attempt_evidence,
    )

    version = f"retail_ops_v3_tc{tool_count}_20260824"
    task_set = build_toolcount_task_set(version, seed=0, tool_count=tool_count)
    train_records = task_set.records("train")
    print(f"  {len(train_records)} train tasks")

    route, api_key = load_teacher_route(os.environ)
    from openai import OpenAI

    raw_client = OpenAI(api_key=api_key, base_url=route.base_url)
    client = OpenAICompatibleTeacherClient(route=route, client=raw_client)

    config = TeacherCollectionConfig(
        dataset_version=version,
        seed=0,
        bundle_sha256=hashlib.sha256(f"v3-tc{tool_count}".encode()).hexdigest(),
        manifest_sha256=hashlib.sha256(f"v3-tc{tool_count}-manifest".encode()).hexdigest(),
        route_sha256=route.route_sha256,
        max_episodes_per_task=2,
        max_request_attempts=3,
    )

    evidence_dir = output_dir / "teacher"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    env = _make_env()
    env_factory = lambda: env

    accepted = 0
    for i, record in enumerate(train_records):
        eid = evidence_dir / f"{record.task.task_id}.json"
        if eid.exists():
            ev = json.loads(eid.read_text())
            if ev.get("outcome") == "accepted":
                accepted += 1
            continue
        try:
            evidence = collect_teacher_attempt(record, client, env_factory, config)
            write_teacher_attempt_evidence(evidence, evidence_dir)
            if evidence.outcome.value == "accepted":
                accepted += 1
        except Exception as e:
            print(f"  Error task {i}: {e}")
        if (i + 1) % 40 == 0:
            print(f"  [{i+1}/{len(train_records)}] accepted={accepted}")

    print(f"  Teacher: {accepted}/{len(train_records)} accepted")
    return accepted


def run_export(tool_count: int, output_dir: Path) -> int:
    """Export SFT data from teacher evidence."""
    from veritool_rl.core.generators import trajectory_to_sft_example
    from veritool_rl.core.trajectory.schema import Trajectory

    version = f"retail_ops_v3_tc{tool_count}_20260824"
    task_set = build_toolcount_task_set(version, seed=0, tool_count=tool_count)
    train_records = task_set.records("train")

    evidence_dir = output_dir / "teacher"
    sft_rows = []
    for record in train_records:
        eid = evidence_dir / f"{record.task.task_id}.json"
        if not eid.exists():
            continue
        ev = json.loads(eid.read_text())
        if ev.get("outcome") != "accepted":
            continue
        traj_data = ev.get("trajectory")
        if not traj_data:
            continue
        traj = Trajectory.model_validate(traj_data)
        sft_rows.append(trajectory_to_sft_example(traj))

    sft_dir = output_dir / "sft"
    sft_dir.mkdir(parents=True, exist_ok=True)
    sft_path = sft_dir / "sft.jsonl"
    with sft_path.open("w") as f:
        for row in sft_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"  SFT: {len(sft_rows)} rows")
    return len(sft_rows)


def run_train(tool_count: int, output_dir: Path) -> bool:
    """Train QLoRA adapter."""
    from veritool_rl.training.sft import run_sft

    sft_path = output_dir / "sft" / "sft.jsonl"
    if not sft_path.exists() or sft_path.stat().st_size == 0:
        print("  No SFT data")
        return False

    config = {
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
    run_sft(config, seed=0, output_dir=adapter_dir)
    print(f"  Training done: {adapter_dir}")
    return True


def run_eval(tool_count: int, output_dir: Path, adapter_path: str | None = None) -> dict:
    """Evaluate on dev set by running episodes directly."""
    from veritool_rl.core.agent.qwen import GenerationSettings

    version = f"retail_ops_v3_tc{tool_count}_20260824"
    task_set = build_toolcount_task_set(version, seed=0, tool_count=tool_count)
    dev_records = task_set.records("dev")

    model_dir = str(MODELS_ROOT / "Qwen3-4B-pinned")
    policy = _load_policy(model_dir, adapter_path)
    gen_settings = GenerationSettings(max_new_tokens=256)

    trajectories = []
    successes = []
    policy_violations = 0
    invalid_calls = 0
    tool_selection_correct = 0
    tool_selection_total = 0

    for record in dev_records:
        task = record.task
        env = _make_env()
        try:
            traj = run_episode(task, lambda: env, policy, seed=0)
            trajectories.append(traj)

            # Check success
            success = env.verify_final_state(task, traj)
            successes.append(success)

            # Count policy violations
            for step in traj.steps:
                if step.tool_call:
                    is_valid = env.validate_tool_call(step.tool_call, task)
                    if not is_valid:
                        invalid_calls += 1

            # Tool selection accuracy
            if task.expected_calls and traj.steps:
                expected_names = [c.name for c in task.expected_calls if c.name]
                actual_names = [s.tool_call.name for s in traj.steps if s.tool_call]
                for en in expected_names:
                    if en in actual_names:
                        tool_selection_correct += 1
                    tool_selection_total += 1

        except Exception as e:
            successes.append(False)
            print(f"  Error on {task.task_id}: {e}")

    n = len(dev_records)
    task_success = sum(successes) / n if n > 0 else 0.0
    tool_acc = tool_selection_correct / tool_selection_total if tool_selection_total > 0 else 0.0

    metrics = {
        "task_success": task_success,
        "policy_violation_count": policy_violations,
        "invalid_call_count": invalid_calls,
        "tool_selection_accuracy": tool_acc,
        "task_count": n,
    }

    # Save
    eval_dir = output_dir / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)
    (eval_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))

    label = "candidate" if adapter_path else "base"
    print(f"  {label}: success={task_success:.4f} pv={policy_violations} ta={tool_acc:.4f}")
    return metrics


def main() -> None:
    results = {}

    for tc in [6, 9, 12, 15]:
        print(f"\n{'='*50}")
        print(f"Tool count: {tc}")
        print(f"{'='*50}")

        out = REPORTS_ROOT / f"toolcount-{tc}"
        done = out / "done.json"

        if done.exists():
            print("Already done")
            results[tc] = json.loads(done.read_text())
            continue

        # 1. Teacher
        print("\n[1/4] Teacher...")
        accepted = run_teacher(tc, out)

        # 2. Export
        print("\n[2/4] SFT export...")
        sft_rows = run_export(tc, out)

        # 3. Train
        print("\n[3/4] Train...")
        run_train(tc, out)

        # 4. Eval
        print("\n[4/4] Eval...")
        base_m = run_eval(tc, out, adapter_path=None)
        adapter_dir = out / "adapter"
        cand_m = run_eval(tc, out / "candidate", adapter_path=str(adapter_dir) if adapter_dir.exists() else None)

        r = {"base": base_m, "candidate": cand_m, "accepted": accepted}
        results[tc] = r
        done.write_text(json.dumps(r, indent=2))

    # Summary
    print(f"\n{'='*60}")
    print(f"{'Tools':>6} {'Base':>8} {'Cand':>8} {'Delta':>8} {'PV':>6} {'ToolAcc':>8}")
    print("-" * 60)
    for tc in sorted(results):
        r = results[tc]
        b = r["base"]["task_success"]
        c = r["candidate"]["task_success"]
        pv = r["candidate"]["policy_violation_count"]
        ta = r["candidate"]["tool_selection_accuracy"]
        print(f"{tc:>6} {b:>8.4f} {c:>8.4f} {c-b:>+8.4f} {pv:>6} {ta:>8.4f}")

    (REPORTS_ROOT / "degradation_summary.json").write_text(json.dumps(results, indent=2))
    print(f"\nSaved to {REPORTS_ROOT / 'degradation_summary.json'}")


if __name__ == "__main__":
    main()
