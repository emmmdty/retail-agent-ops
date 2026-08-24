"""Task 3: Run degradation curve for tool counts {6, 9, 12, 15} on flight_ops."""

import subprocess
import sys
from pathlib import Path

ROOT = Path("/mnt/aidata/tongjiakai/retail-agent-ops")
PYTHON = str(ROOT / ".venv/bin/python")
RUNNER = str(ROOT / "scripts/flight_ops/run.py")

for tool_count in [6, 9, 12, 15]:
    print(f"\n===== Tool count: {tool_count} =====", flush=True)
    tag = f"toolcount-{tool_count}"
    version = f"flight_ops_v1_r10_tc{tool_count}"

    done_marker = ROOT / f"reports/flight_ops/v1/r10/{tag}/done"
    if done_marker.exists():
        print("Already done, skipping", flush=True)
        continue

    # Teacher collection
    print(f"Teacher collection for {tool_count} tools...", flush=True)
    r = subprocess.run(
        [PYTHON, RUNNER, "--mode", "teacher_collect", "--dataset-version", version, "--seed", "0"],
        cwd=ROOT, capture_output=True, text=True, timeout=3600,
    )
    if r.returncode != 0:
        print(f"Teacher failed: {r.stderr[-300:]}", flush=True)
        continue
    print(r.stdout[-200:] if r.stdout else "no stdout", flush=True)

    # SFT export
    print("SFT export...", flush=True)
    r = subprocess.run(
        [PYTHON, RUNNER, "--mode", "sft_export", "--dataset-version", version],
        cwd=ROOT, capture_output=True, text=True, timeout=300,
    )
    print(r.stdout[-100:] if r.stdout else "no stdout", flush=True)

    # Train
    print("Training...", flush=True)
    r = subprocess.run(
        [PYTHON, RUNNER, "--mode", "train", "--dataset-version", version, "--seed", "0"],
        cwd=ROOT, capture_output=True, text=True, timeout=600,
    )
    if r.returncode != 0:
        print(f"Train failed: {r.stderr[-300:]}", flush=True)
        continue
    print(r.stdout[-200:] if r.stdout else "no stdout", flush=True)

    # Base eval
    print("Base eval...", flush=True)
    r = subprocess.run(
        [PYTHON, RUNNER, "--mode", "eval", "--dataset-version", version,
         "--split", "dev", "--model-path", "models/Qwen3-4B-pinned"],
        cwd=ROOT, capture_output=True, text=True, timeout=600,
    )
    print(r.stdout[-200:] if r.stdout else "no stdout", flush=True)

    # Candidate eval
    print("Candidate eval...", flush=True)
    r = subprocess.run(
        [PYTHON, RUNNER, "--mode", "eval", "--dataset-version", version,
         "--split", "dev", "--model-path", "models/Qwen3-4B-pinned",
         "--adapter-path", f"reports/flight_ops/v1/r10/{tag}/train/adapter"],
        cwd=ROOT, capture_output=True, text=True, timeout=600,
    )
    print(r.stdout[-200:] if r.stdout else "no stdout", flush=True)

    done_marker.parent.mkdir(parents=True, exist_ok=True)
    done_marker.write_text("done")
    print(f"Completed {tool_count} tools", flush=True)

print("\n===== All breakpoints complete =====", flush=True)
