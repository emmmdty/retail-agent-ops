"""FlightOps v1 task manifests — frozen task-set metadata for build/evaluate pairing.

Mirrors retail_ops.build.manifests' role: a manifest binds a task set to its
hashes so build and evaluate can verify they're working on the same data.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import Field

from veritool_rl.core.artifacts import canonical_json
from veritool_rl.core.trajectory.schema import StrictModel
from veritool_rl.flight_ops.domain.tasks import FlightTaskSet


class FlightTaskManifest(StrictModel):
    """Frozen metadata for a FlightOps task set."""

    dataset_version: str = Field(min_length=1)
    seed: int
    generator_id: str = Field(min_length=1)
    train_count: int
    dev_count: int
    task_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_task_set(cls, task_set: FlightTaskSet) -> FlightTaskManifest:
        """Build a manifest from a task set, computing its content hash."""
        payload = {
            "dataset_version": task_set.dataset_version,
            "seed": task_set.seed,
            "generator_id": task_set.generator_id,
            "train": [
                {"task_id": r.task.task_id, "content_sha256": r.content_sha256}
                for r in task_set.train
            ],
            "dev": [
                {"task_id": r.task.task_id, "content_sha256": r.content_sha256}
                for r in task_set.dev
            ],
        }
        content = canonical_json(payload).encode("utf-8")
        return cls(
            dataset_version=task_set.dataset_version,
            seed=task_set.seed,
            generator_id=task_set.generator_id,
            train_count=len(task_set.train),
            dev_count=len(task_set.dev),
            task_set_sha256=hashlib.sha256(content).hexdigest(),
        )


def write_manifest(manifest: FlightTaskManifest, output_dir: Path) -> Path:
    """Write manifest JSON to ``output_dir/manifest.json``."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "manifest.json"
    path.write_text(
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def load_manifest(path: Path) -> FlightTaskManifest:
    """Load and validate a manifest from disk."""
    return FlightTaskManifest.model_validate_json(path.read_text(encoding="utf-8"))
