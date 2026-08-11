"""由 release report 选择 candidate 或 base 的 FastAPI 服务。

两条并行通道：
- `create_app`：R1 qualification 服务，跑规则策略，契约已冻结，不改。
- `create_formal_app`：按封存 holdout 的 `FormalReleaseReport` 加载真实模型。
  后端经工厂注入，因此本地 CPU 用 fake backend 就能启动并验证服务契约与回滚
  路径，GPU 主机上换成真实的 base+adapter 后端即可，无需改服务代码。
"""

from __future__ import annotations

import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from veritool_rl.core.agent.qwen import GenerationBackend, QwenPolicy
from veritool_rl.core.agent.runner import run_episode
from veritool_rl.core.artifacts import sha256_file
from veritool_rl.core.trajectory import Trajectory
from veritool_rl.core.trajectory.schema import StrictModel
from veritool_rl.retail_ops.build.manifests import load_built_tasks, load_task_manifest
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
from veritool_rl.retail_ops.domain.policies import build_qualification_policy
from veritool_rl.retail_ops.evaluate.base_evaluation import ModelArtifact
from veritool_rl.retail_ops.evaluate.candidate_evaluation import AdapterArtifact
from veritool_rl.retail_ops.release.formal_release import (
    FormalReleaseReport,
    load_formal_release_report,
)
from veritool_rl.retail_ops.release.release import (
    ReleaseDecision,
    load_release_report,
)

#: 单卡服务同时只跑一条 episode：并发解码会让显存峰值不可预测，也会破坏
#: 逐 episode 的延迟测量。SPEC §9 要求限制并发，这里用最保守的串行化实现。
_MAX_CONCURRENT_EPISODES = 1

#: SPEC §9 的请求大小上限。当前端点不接受请求体，这个上限因此是**前瞻性**的：
#: 它保证后续新增带 body 的端点时，超限请求在触达模型之前就被拒绝。
MAX_REQUEST_BYTES = 64 * 1024

BackendFactory = Callable[[ModelArtifact, AdapterArtifact | None], GenerationBackend]


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


class FormalHealthResponse(StrictModel):
    """服务当前发布选择、失败门禁与回滚路径。"""

    status: Literal["ok"] = "ok"
    bundle_version: str
    dataset_version: str
    release_decision: ReleaseDecision
    deployment: Literal["candidate", "baseline"]
    failed_gate_ids: list[str]
    adapter_loaded: bool
    policy_id: str
    rollback: str


def create_formal_app(
    release_dir: Path,
    bundle_dir: Path,
    build_dir: Path,
    *,
    backend_factory: BackendFactory,
) -> FastAPI:
    """按封存 holdout 的发布决策加载真实模型并暴露受控工具 Agent 服务。

    SPEC §4 的"没有通过发布门禁的模型不得被服务入口加载"在这里是**双重**执行的：
    NO-GO 时 adapter 根本不会传给工厂，且随后还会核对工厂真正返回的后端没有挂
    adapter。只做前者不够——工厂是注入缝，实现可能来自别处。
    """
    release = load_formal_release_report(release_dir / "release.json")
    bundle = load_bundle(bundle_dir)
    if release.bundle_sha256 != bundle.bundle_sha256:
        raise ValueError("release report 与 bundle SHA-256 不匹配")

    manifest_path = build_dir / "manifest.json"
    manifest = load_task_manifest(manifest_path)
    if manifest.bundle_sha256 != bundle.bundle_sha256:
        raise ValueError("task manifest 与 bundle SHA-256 不匹配")
    if manifest.split != "qualification":
        raise ValueError("formal service 只接受 qualification 演示任务集")

    deploy_candidate = release.deployment == "candidate"
    adapter = release.adapter if deploy_candidate else None
    backend = backend_factory(release.model, adapter)
    _require_backend_matches_deployment(backend, adapter)

    policy_id = release.candidate_policy_id if deploy_candidate else release.base_policy_id
    policy = QwenPolicy(backend, policy_id, release.generation.max_new_tokens)
    tasks = load_built_tasks(build_dir)
    allowed_tools = tuple(sorted(tool.name for tool in bundle.tools))
    episode_lock = threading.BoundedSemaphore(_MAX_CONCURRENT_EPISODES)

    app = FastAPI(title="RetailAgentOps", version=bundle.bundle.bundle_version)

    @app.middleware("http")
    async def limit_request_size(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        declared = request.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > MAX_REQUEST_BYTES:
            return JSONResponse(
                status_code=413,
                content={"detail": f"请求体超过 {MAX_REQUEST_BYTES} 字节上限"},
            )
        return await call_next(request)

    @app.get("/health", response_model=FormalHealthResponse)
    def health() -> FormalHealthResponse:
        return FormalHealthResponse(
            bundle_version=bundle.bundle.bundle_version,
            dataset_version=release.dataset_version,
            release_decision=release.decision,
            deployment=release.deployment,
            failed_gate_ids=list(release.failed_gate_ids),
            adapter_loaded=adapter is not None,
            policy_id=policy_id,
            rollback=_rollback_instruction(release),
        )

    @app.get("/v1/tasks")
    def list_tasks() -> dict[str, Any]:
        return {"task_ids": sorted(tasks), "allowed_tools": list(allowed_tools)}

    @app.post("/v1/tasks/{task_id}/run")
    def run_task(task_id: str) -> dict[str, Any]:
        task = tasks.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="未知演示 task")
        if not episode_lock.acquire(blocking=False):
            raise HTTPException(status_code=503, detail="服务已达并发上限，请稍后重试")
        try:
            trajectory = run_episode(
                task,
                lambda current: RetailOpsEnv(current, bundle),
                policy,
                seed=manifest.seed,
            )
        finally:
            episode_lock.release()
        response = _public_trajectory_response(trajectory)
        response["deployment"] = release.deployment
        response["policy_id"] = policy_id
        return response

    return app


def _require_backend_matches_deployment(
    backend: GenerationBackend,
    expected_adapter: AdapterArtifact | None,
) -> None:
    """核对工厂返回的后端与发布决策一致；这条检查是回滚承诺的执行者。"""
    declared = getattr(backend, "adapter_path", None)
    if expected_adapter is None:
        if declared is not None:
            msg = f"发布结论要求回滚到冻结 base，但后端挂载了 adapter {declared!r}"
            raise ValueError(msg)
        return
    if declared is None:
        msg = "发布结论要求部署候选，但后端未声明任何 adapter"
        raise ValueError(msg)
    if Path(declared).resolve() != expected_adapter.adapter_dir.resolve():
        msg = "后端加载的 adapter 目录与发布报告锁定的 adapter 不一致"
        raise ValueError(msg)


def _rollback_instruction(release: FormalReleaseReport) -> str:
    if release.deployment == "candidate":
        return "候选已通过全部发布门禁；回滚路径是重新部署冻结 base（不加载 adapter）。"
    return (
        "候选未通过发布门禁，服务已回滚到冻结 base，不加载 adapter；"
        f"失败门禁：{', '.join(release.failed_gate_ids)}。"
    )


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
