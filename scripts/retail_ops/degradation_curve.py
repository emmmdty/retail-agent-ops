#!/usr/bin/env python3
"""RetailOps v3 tool-count degradation curve.

For each breakpoint N in {6,9,12,15}, runs the full pipeline:
  task_gen → teacher_collect → sft_export → train → eval

The {3} breakpoint reuses sft-008 (already trained on v1's 3 tools).
Results are collected into a JSON summary for plotting.

Usage on gpu-5090:
    cd /mnt/aidata/tongjiakai/retail-agent-ops
    set -a && source .env && set +a
    python scripts/retail_ops/degradation_curve.py --dataset-version retail_ops_v3 --seed 0
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_BREAKPOINTS = [6, 9, 12, 15]


def run_toolcount(n: int, dataset_version: str, seed: int, model_path: str) -> dict:
    """Run full pipeline for one tool-count breakpoint."""
    from veritool_rl.retail_ops.domain.bundle import load_bundle
    from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
    from veritool_rl.retail_ops.domain.v3_tasks import build_toolcount_task_set
    from veritool_rl.core.agent.qwen import QwenPolicy

    bundle = load_bundle(Path("domains/retail_ops/v3"))
    task_set = build_toolcount_task_set(dataset_version, seed, n)

    # 1. Task gen
    out = PROJECT_ROOT / "reports" / "retail_ops" / "v1" / "r9" / f"toolcount-{n}"
    (out / "tasks").mkdir(parents=True, exist_ok=True)
    for split in ("train", "dev"):
        records = task_set.records(split)
        path = out / "tasks" / f"{split}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(r.task.to_jsonl() + "\n")
    print(f"  [{n} tools] tasks: {len(task_set.train)} train, {len(task_set.dev)} dev")

    # 2. Teacher collection
    teacher_dir = out / "teacher"
    teacher_dir.mkdir(parents=True, exist_ok=True)

    from veritool_rl.flight_ops.build.teacher_data import (
        FlightCollectionConfig, FlightCollectionCheckpoint,
        collect_flight_attempt, load_checkpoint,
        load_teacher_route_from_env, write_checkpoint, write_evidence,
    )
    from openai import OpenAI
    from veritool_rl.core.build.teacher_client import OpenAICompatibleTeacherClient

    route, api_key = load_teacher_route_from_env()
    raw_client = OpenAI(api_key=api_key, base_url=route.base_url)
    client = OpenAICompatibleTeacherClient(route=route, client=raw_client)

    config = FlightCollectionConfig(
        dataset_version=dataset_version, seed=seed,
        bundle_sha256=bundle.bundle_sha256,
        manifest_sha256="a" * 64,
        route_sha256=route.route_sha256,
        max_episodes_per_task=2, max_request_attempts=3,
    )

    checkpoint = load_checkpoint(teacher_dir)
    accepted_ids = set(checkpoint.accepted_task_ids) if checkpoint else set()
    already = {p.stem for p in teacher_dir.glob("*.json") if p.name != "checkpoint.json"}

    total, accepted = 0, 0
    t0 = time.monotonic()
    for record in task_set.records("train"):
        safe_id = record.task.task_id.replace("/", "_").replace(":", "_")
        if safe_id in already:
            total += 1
            continue
        evidence = collect_flight_attempt(record.task, record.content_sha256, client, lambda t: RetailOpsEnv(t, bundle), config)
        write_evidence(evidence, teacher_dir)
        total += 1
        if evidence.accepted:
            accepted += 1
            accepted_ids.add(record.task.task_id)
        if total % 20 == 0:
            elapsed = time.monotonic() - t0
            print(f"    [{n} tools] {total}/{len(list(task_set.records('train')))} accepted={accepted} {elapsed:.0f}s")
        if total % 10 == 0:
            write_checkpoint(FlightCollectionCheckpoint(
                dataset_version=config.dataset_version, seed=config.seed,
                bundle_sha256=config.bundle_sha256, manifest_sha256=config.manifest_sha256,
                route_sha256=config.route_sha256, config_sha256=config.config_sha256,
                accepted_task_ids=tuple(sorted(accepted_ids)),
            ), teacher_dir)

    write_checkpoint(FlightCollectionCheckpoint(
        dataset_version=config.dataset_version, seed=config.seed,
        bundle_sha256=config.bundle_sha256, manifest_sha256=config.manifest_sha256,
        route_sha256=config.route_sha256, config_sha256=config.config_sha256,
        accepted_task_ids=tuple(sorted(accepted_ids)),
    ), teacher_dir)
    elapsed = time.monotonic() - t0
    print(f"  [{n} tools] teacher: {accepted}/{total} accepted in {elapsed:.0f}s")

    # 3. SFT export
    from veritool_rl.flight_ops.build.dev_sft_export import export_sft_from_evidences
    sft_dir = out / "sft"
    sft_dir.mkdir(parents=True, exist_ok=True)
    sft_path = sft_dir / "sft.jsonl"
    _, written = export_sft_from_evidences(teacher_dir, sft_path)
    print(f"  [{n} tools] sft: {written} trajectories")

    # 4. Train
    import hashlib
    model_dir = Path(model_path)
    sha256_map = {}
    for f in sorted(model_dir.iterdir()):
        if f.is_file() and not f.name.startswith("."):
            sha256_map[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()
    revision = hashlib.sha256(json.dumps(sha256_map, sort_keys=True).encode()).hexdigest()[:16]

    from veritool_rl.training.sft import run_sft
    rel_sft = str(sft_path.relative_to(PROJECT_ROOT))
    train_config = {
        "model": {"name": model_path, "load_in_4bit": True, "revision": revision, "file_sha256": sha256_map},
        "lora": {"r": 16, "alpha": 32, "dropout": 0.05, "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj"]},
        "data": {"train_path": rel_sft, "eval_path": rel_sft},
        "training": {"epochs": 3, "batch_size": 1, "grad_accum": 1, "lr": 2e-4},
    }
    train_out = out / "train"
    train_out.mkdir(parents=True, exist_ok=True)
    run_sft(train_config, seed=seed, output_dir=train_out)
    adapter_path = str(train_out / "adapter")
    print(f"  [{n} tools] training complete")

    # 5. Eval
    from veritool_rl.flight_ops.evaluate.evaluation import FlightEvalConfig, run_evaluation
    def env_factory(task):
        return RetailOpsEnv(task, bundle)
    def policy_factory(task):
        return QwenPolicy.from_config({"model_name": model_path, "adapter_path": adapter_rel, "max_new_tokens": 256})

    adapter_rel = str(train_out.relative_to(PROJECT_ROOT) / "adapter")
    eval_config = FlightEvalConfig(
        dataset_version=dataset_version, bundle_sha256=bundle.bundle_sha256,
        manifest_sha256="a" * 64, seed=seed, split="dev",
        model_name=model_path.split("/")[-1], adapter_path=adapter_rel,
    )
    eval_out = out / "eval-dev"
    eval_out.mkdir(parents=True, exist_ok=True)
    evidence = run_evaluation(eval_config, task_set, policy_factory, env_factory, output_dir=eval_out)
    print(f"  [{n} tools] eval: task_success={evidence.task_success:.4f} pv={evidence.policy_violation_count} tool_acc={evidence.tool_selection_accuracy:.4f}")

    return {
        "tool_count": n,
        "task_success": evidence.task_success,
        "policy_violation_count": evidence.policy_violation_count,
        "tool_selection_accuracy": evidence.tool_selection_accuracy,
        "report_id": evidence.report_id,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="RetailOps v3 degradation curve")
    parser.add_argument("--dataset-version", default="retail_ops_v3")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--model-path", default="models/Qwen3-4B-pinned")
    args = parser.parse_args()

    results = []
    for n in _BREAKPOINTS:
        print(f"\n=== {n} tools ===")
        t0 = time.monotonic()
        r = run_toolcount(n, args.dataset_version, args.seed, args.model_path)
        r["wall_seconds"] = time.monotonic() - t0
        results.append(r)

    # Write summary
    summary_path = PROJECT_ROOT / "reports" / "retail_ops" / "v1" / "r9" / "degradation_curve.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== DEGRADATION CURVE SUMMARY ===")
    print(f"{'N':>4} {'success':>8} {'pv':>4} {'tool_acc':>9}")
    for r in results:
        print(f"{r['tool_count']:>4} {r['task_success']:>8.4f} {r['policy_violation_count']:>4} {r['tool_selection_accuracy']:>9.4f}")
    print(f"\nResults: {summary_path}")


if __name__ == "__main__":
    main()
