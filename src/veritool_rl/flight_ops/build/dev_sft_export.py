"""FlightOps v1 SFT data export — convert accepted teacher trajectories to JSONL.

Uses core.generators.trajectory_to_sft_example (generic) and reads teacher
evidence files written by flight_ops.build.teacher_data.
"""

from __future__ import annotations

import json
from pathlib import Path

from veritool_rl.core.generators import trajectory_to_sft_example
from veritool_rl.flight_ops.build.teacher_data import FlightTaskEvidence


def export_sft_from_evidences(
    evidence_dir: Path,
    output_path: Path,
) -> tuple[int, int]:
    """Read all evidence JSON files in ``evidence_dir``, convert accepted
    trajectories to SFT JSONL, write to ``output_path``.

    Returns ``(total_read, accepted_written)``.
    """
    total = 0
    written = 0
    lines: list[str] = []
    for path in sorted(evidence_dir.glob("*.json")):
        if path.name == "checkpoint.json":
            continue
        ev = FlightTaskEvidence.model_validate_json(path.read_text(encoding="utf-8"))
        total += 1
        if not ev.accepted or ev.trajectory is None:
            continue
        example = trajectory_to_sft_example(ev.trajectory)
        lines.append(json.dumps(example, ensure_ascii=False))
        written += 1
    if lines:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return total, written
