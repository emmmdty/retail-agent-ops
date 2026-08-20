#!/usr/bin/env python3
"""FlightOps v1 end-to-end runner for remote GPU execution.

Usage on gpu-5090:
    cd /mnt/aidata/tongjiakai/retail-agent-ops
    python scripts/flight_ops/run.py --mode task_gen --dataset-version flight_ops_v1_r8 --seed 0
    python scripts/flight_ops/run.py --mode teacher_collect \
        --dataset-version flight_ops_v1_r8 --seed 0
    python scripts/flight_ops/run.py --mode sft_export --dataset-version flight_ops_v1_r8
    python scripts/flight_ops/run.py --mode train --dataset-version flight_ops_v1_r8 --seed 0
    python scripts/flight_ops/run.py --mode eval --dataset-version flight_ops_v1_r8 --split dev

Each mode produces artifacts under reports/flight_ops/v1/r9/<mode>-<hash>/.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Ensure the project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def mode_task_gen(args: argparse.Namespace) -> None:
    """Generate flight_ops task set + manifest."""
    from veritool_rl.flight_ops.build.manifests import FlightTaskManifest, write_manifest
    from veritool_rl.flight_ops.domain.tasks import build_flight_task_set

    output_dir = _output_dir(args, "tasks")
    task_set = build_flight_task_set(args.dataset_version, args.seed)
    task_set.assert_quotas()

    manifest = FlightTaskManifest.from_task_set(task_set)
    write_manifest(manifest, output_dir)

    # Write task set as JSONL for downstream consumption
    for split in ("train", "dev"):
        records = task_set.records(split)
        path = output_dir / f"{split}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(r.task.to_jsonl() + "\n")

    print(f"Task set: {len(task_set.train)} train, {len(task_set.dev)} dev")
    print(f"Manifest: {manifest.task_set_sha256[:16]}...")
    print(f"Output: {output_dir}")


def mode_teacher_collect(args: argparse.Namespace) -> None:
    """Collect teacher trajectories for train split."""
    from veritool_rl.flight_ops.build.manifests import load_manifest
    from veritool_rl.flight_ops.build.teacher_data import (
        FlightCollectionCheckpoint,
        FlightCollectionConfig,
        collect_flight_attempt,
        load_checkpoint,
        load_teacher_route_from_env,
        write_checkpoint,
        write_evidence,
    )
    from veritool_rl.flight_ops.domain.bundle import load_bundle
    from veritool_rl.flight_ops.domain.environment import FlightOpsEnv
    from veritool_rl.flight_ops.domain.tasks import FlightSplit, build_flight_task_set

    bundle = load_bundle(_bundle_dir())
    task_set = build_flight_task_set(args.dataset_version, args.seed)
    train_records = task_set.records(FlightSplit.TRAIN)

    # Load manifest for hashes
    manifest_dir = _output_dir(args, "tasks")
    manifest = load_manifest(manifest_dir / "manifest.json")

    # Load teacher route
    route, api_key = load_teacher_route_from_env()
    from veritool_rl.core.build.teacher_client import OpenAICompatibleTeacherClient
    from openai import OpenAI

    raw_client = OpenAI(api_key=api_key, base_url=route.base_url)
    client = OpenAICompatibleTeacherClient(route=route, client=raw_client)

    config = FlightCollectionConfig(
        dataset_version=args.dataset_version,
        seed=args.seed,
        bundle_sha256=bundle.bundle_sha256,
        manifest_sha256=manifest.task_set_sha256,
        route_sha256=route.route_sha256,
        max_episodes_per_task=args.max_episodes,
        max_request_attempts=args.max_attempts,
    )

    def env_factory(task):
        return FlightOpsEnv(task, bundle)

    output_dir = _output_dir(args, "teacher")
    checkpoint = load_checkpoint(output_dir)
    accepted_ids = set(checkpoint.accepted_task_ids) if checkpoint else set()
    already = (
        {p.stem for p in output_dir.glob("*.json") if p.name != "checkpoint.json"}
        if output_dir.exists()
        else set()
    )

    total = 0
    accepted = 0
    t0 = time.monotonic()
    for record in train_records:
        task_id = record.task.task_id
        safe_id = task_id.replace("/", "_").replace(":", "_")
        if safe_id in already:
            accepted += task_id in accepted_ids
            total += 1
            continue

        evidence = collect_flight_attempt(
            record.task, record.content_sha256, client, env_factory, config
        )
        write_evidence(evidence, output_dir)
        total += 1
        if evidence.accepted:
            accepted += 1
            accepted_ids.add(task_id)

        # Checkpoint every 10 tasks
        if total % 10 == 0:
            write_checkpoint(
                FlightCollectionCheckpoint(
                    dataset_version=config.dataset_version,
                    seed=config.seed,
                    bundle_sha256=config.bundle_sha256,
                    manifest_sha256=config.manifest_sha256,
                    route_sha256=config.route_sha256,
                    config_sha256=config.config_sha256,
                    accepted_task_ids=tuple(sorted(accepted_ids)),
                ),
                output_dir,
            )

        if total % 20 == 0:
            elapsed = time.monotonic() - t0
            print(f"  [{total}/{len(train_records)}] accepted={accepted} elapsed={elapsed:.0f}s")

    # Final checkpoint
    write_checkpoint(
        FlightCollectionCheckpoint(
            dataset_version=config.dataset_version,
            seed=config.seed,
            bundle_sha256=config.bundle_sha256,
            manifest_sha256=config.manifest_sha256,
            route_sha256=config.route_sha256,
            config_sha256=config.config_sha256,
            accepted_task_ids=tuple(sorted(accepted_ids)),
        ),
        output_dir,
    )

    elapsed = time.monotonic() - t0
    print(f"Teacher collection: {accepted}/{total} accepted in {elapsed:.0f}s")
    print(f"Output: {output_dir}")


def mode_sft_export(args: argparse.Namespace) -> None:
    """Export accepted teacher trajectories to SFT JSONL."""
    from veritool_rl.flight_ops.build.dev_sft_export import export_sft_from_evidences

    teacher_dir = _output_dir(args, "teacher")
    output_dir = _output_dir(args, "sft")
    output_dir.mkdir(parents=True, exist_ok=True)
    sft_path = output_dir / "sft.jsonl"

    total, written = export_sft_from_evidences(teacher_dir, sft_path)
    print(f"SFT export: {written}/{total} accepted trajectories → {sft_path}")


def mode_train(args: argparse.Namespace) -> None:
    """Train QLoRA-SFT candidate."""
    import hashlib
    import json as _json
    from veritool_rl.training.sft import run_sft

    sft_dir = _output_dir(args, "sft")
    sft_path = sft_dir / "sft.jsonl"
    if not sft_path.exists():
        print(f"ERROR: SFT data not found at {sft_path}")
        sys.exit(1)

    # Compute model revision and file_sha256
    model_dir = Path(args.model_path)
    sha256_map = {}
    for f in sorted(model_dir.rglob("*.json")):
        if f.is_file():
            sha256_map[str(f.relative_to(model_dir))] = hashlib.sha256(f.read_bytes()).hexdigest()
    for f in sorted(model_dir.rglob("*.safetensors")):
        if f.is_file():
            sha256_map[str(f.relative_to(model_dir))] = hashlib.sha256(f.read_bytes()).hexdigest()
    revision = hashlib.sha256(_json.dumps(sha256_map, sort_keys=True).encode()).hexdigest()[:16]

    # Project-relative paths
    rel_sft = str(sft_path.relative_to(PROJECT_ROOT))
    output_dir = _output_dir(args, "train")
    config = {
        "model": {
            "name": args.model_path,
            "load_in_4bit": True,
            "revision": revision,
            "file_sha256": sha256_map,
        },
        "lora": {
            "r": 16,
            "alpha": 32,
            "dropout": 0.05,
            "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj"],
        },
        "data": {
            "train_path": rel_sft,
            "eval_path": rel_sft,
        },
        "training": {
            "epochs": 3,
            "batch_size": 1,
            "grad_accum": 1,
            "lr": 2e-4,
        },
    }

    result = run_sft(config, seed=args.seed, output_dir=output_dir)
    print(f"Training complete: {output_dir}")
    print(f"Adapter: {result.get('adapter_dir', 'unknown')}")


def mode_eval(args: argparse.Namespace) -> None:
    """Evaluate model on dev tasks."""
    from veritool_rl.core.agent.qwen import load_model_and_tokenizer
    from veritool_rl.flight_ops.build.manifests import load_manifest
    from veritool_rl.flight_ops.domain.bundle import load_bundle
    from veritool_rl.flight_ops.domain.environment import FlightOpsEnv
    from veritool_rl.flight_ops.domain.tasks import build_flight_task_set
    from veritool_rl.flight_ops.evaluate.evaluation import FlightEvalConfig, run_evaluation

    bundle = load_bundle(_bundle_dir())
    task_set = build_flight_task_set(args.dataset_version, args.seed)
    manifest = load_manifest(_output_dir(args, "tasks") / "manifest.json")

    # Load model
    model, tokenizer = load_model_and_tokenizer(args.model_path)

    # Apply adapter if provided
    if args.adapter_path:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, args.adapter_path)

    def env_factory(task):
        return FlightOpsEnv(task, bundle)

    def policy_factory(task):
        from veritool_rl.core.agent.qwen import QwenPolicy

        return QwenPolicy(model, tokenizer, task)

    config = FlightEvalConfig(
        dataset_version=args.dataset_version,
        bundle_sha256=bundle.bundle_sha256,
        manifest_sha256=manifest.task_set_sha256,
        seed=args.seed,
        split=args.split,
        model_name=args.model_path.split("/")[-1],
        adapter_path=args.adapter_path,
    )

    output_dir = _output_dir(args, f"eval-{args.split}")
    evidence = run_evaluation(
        config,
        task_set,
        policy_factory,
        env_factory,
        output_dir=output_dir,
    )

    print(f"Evaluation: task_success={evidence.task_success:.4f}")
    print(f"  policy_violations={evidence.policy_violation_count}")
    print(f"  invalid_calls={evidence.invalid_call_count}")
    print(f"  tool_selection_accuracy={evidence.tool_selection_accuracy:.4f}")
    print(f"  report_id={evidence.report_id[:16]}...")
    print(f"  Output: {output_dir}")


def _output_dir(args: argparse.Namespace, label: str) -> Path:
    """Standard output directory: reports/flight_ops/v1/r9/<label>/"""
    base = PROJECT_ROOT / "reports" / "flight_ops" / "v1" / "r9" / label
    base.mkdir(parents=True, exist_ok=True)
    return base


def _bundle_dir() -> Path:
    return PROJECT_ROOT / "domains" / "flight_ops" / "v1"


def main() -> None:
    parser = argparse.ArgumentParser(description="FlightOps v1 runner")
    parser.add_argument(
        "--mode",
        required=True,
        choices=["task_gen", "teacher_collect", "sft_export", "train", "eval"],
    )
    parser.add_argument("--dataset-version", default="flight_ops_v1_r8")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--model-path", default="models/Qwen3-4B-pinned")
    parser.add_argument("--adapter-path", default=None)
    parser.add_argument("--split", default="dev")
    parser.add_argument("--max-episodes", type=int, default=2)
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args()

    modes = {
        "task_gen": mode_task_gen,
        "teacher_collect": mode_teacher_collect,
        "sft_export": mode_sft_export,
        "train": mode_train,
        "eval": mode_eval,
    }
    modes[args.mode](args)


if __name__ == "__main__":
    main()
