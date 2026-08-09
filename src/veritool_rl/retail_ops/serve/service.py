"""由 release report 选择 candidate 或 base 的 qualification FastAPI 服务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException

from veritool_rl.core.agent.runner import run_episode
from veritool_rl.core.artifacts import sha256_file
from veritool_rl.core.trajectory import Trajectory
from veritool_rl.core.trajectory.schema import StrictModel
from veritool_rl.retail_ops.build.manifests import load_built_tasks, load_task_manifest
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
from veritool_rl.retail_ops.domain.policies import build_qualification_policy
from veritool_rl.retail_ops.release.release import (
    ReleaseDecision,
    load_release_report,
)


class HealthResponse(StrictModel):
    """服务当前发布选择的最小健康信息。"""

    status: Literal["ok"] = "ok"
    bundle_version: str
    release_decision: ReleaseDecision
    deployment: Literal["candidate", "baseline"]


def create_app(release_dir: Path, bundle_dir: Path, build_dir: Path) -> FastAPI:
    """从已验证 release、bundle 与 build 产物创建只读 qualification 服务。"""
    release = load_release_report(release_dir / "release.json")
    bundle = load_bundle(bundle_dir)
    manifest_path = build_dir / "manifest.json"
    manifest = load_task_manifest(manifest_path)
    if release.bundle_sha256 != bundle.bundle_sha256:
        raise ValueError("release report 与 bundle SHA-256 不匹配")
    if release.task_manifest_sha256 != sha256_file(manifest_path):
        raise ValueError("release report 与 task manifest SHA-256 不匹配")
    if manifest.bundle_sha256 != bundle.bundle_sha256:
        raise ValueError("task manifest 与 bundle SHA-256 不匹配")
    if manifest.split != "qualification":
        raise ValueError("R1 service 只接受 qualification manifest")

    tasks = load_built_tasks(build_dir)
    selected = release.deployment
    policy_type = release.candidate_policy if selected == "candidate" else release.baseline_policy
    for task in tasks.values():
        build_qualification_policy(policy_type, task)

    app = FastAPI(title="RetailAgentOps", version=bundle.bundle.bundle_version)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            bundle_version=bundle.bundle.bundle_version,
            release_decision=release.decision,
            deployment=selected,
        )

    @app.post("/v1/tasks/{task_id}/run")
    def run_task(task_id: str) -> dict[str, Any]:
        task = tasks.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="未知 qualification task")
        trajectory = run_episode(
            task,
            lambda current: RetailOpsEnv(current, bundle),
            build_qualification_policy(policy_type, task),
            seed=manifest.seed,
        )
        return _public_trajectory_response(trajectory)

    return app


def _public_trajectory_response(trajectory: Trajectory) -> dict[str, Any]:
    return {
        "task_id": trajectory.task.task_id,
        "category": trajectory.task.scenario.value,
        "success": trajectory.success,
        "termination": trajectory.termination.value,
        "violations": trajectory.violations,
        "steps": [
            {
                "index": step.index,
                "tool_call": (
                    step.tool_call.model_dump(mode="json") if step.tool_call is not None else None
                ),
                "observation": (
                    step.observation.model_dump(mode="json")
                    if step.observation is not None
                    else None
                ),
            }
            for step in trajectory.steps
        ],
    }
