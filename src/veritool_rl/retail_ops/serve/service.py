"""由 release report 选择 candidate 或 base 的 FastAPI 服务。

两条并行通道：
- `create_app`：R1 qualification 服务，跑规则策略，契约已冻结，不改。
- `create_formal_app`：按封存 holdout 的 `FormalReleaseReport` 加载真实模型。
  后端经工厂注入，因此本地 CPU 用 fake backend 就能启动并验证服务契约与回滚
  路径，GPU 主机上换成真实的 base+adapter 后端即可，无需改服务代码。
"""

from __future__ import annotations

import hmac
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import Field, field_validator

from veritool_rl.core.agent.qwen import GenerationBackend, QwenPolicy
from veritool_rl.core.agent.runner import run_episode
from veritool_rl.core.artifacts import sha256_file
from veritool_rl.core.trajectory import TaskSpec, Trajectory
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
from veritool_rl.retail_ops.serve.observability import (
    REQUEST_RECORD,
    ServiceMetrics,
    digest_text,
    emit,
    new_record,
)

#: 单卡服务同时只跑一条 episode：并发解码会让显存峰值不可预测，也会破坏
#: 逐 episode 的延迟测量。SPEC §9 要求限制并发，这里用最保守的串行化实现。
#: 保留 503 而不是排队：排队会让延迟测量失真，而延迟是发布门禁项。
_MAX_CONCURRENT_EPISODES = 1

#: SPEC §9 的请求大小上限。`POST /v1/chat` 是第一个带 body 的端点，这个上限
#: 因此不再是"前瞻性"的——超限请求在触达模型之前就被拒绝。
MAX_REQUEST_BYTES = 64 * 1024

#: 自由请求的步数上限。与正式评测的 4–5 步同量级，避免一条请求无限占用单卡。
CHAT_MAX_STEPS = 5

#: 单次 episode 的默认时限（秒）。超时返回结构化错误而不是挂死。
DEFAULT_EPISODE_TIMEOUT_S = 120.0

#: 自由请求没有任务真值。给 env 一个**永远不可能达成**的 target_state，
#: 使 `verify_final_state` 恒为 0，episode 只能由最终答复、步数上限或政策违规
#: 终止。服务因此不会报告 `success`——那会把一次演示包装成能力证明。
_NO_GROUND_TRUTH_STATE: dict[str, Any] = {"__no_ground_truth__": True}

#: 不需要鉴权的端点：两者都不暴露任务内容、请求原文或凭据。
_OPEN_PATHS = frozenset({"/health", "/metrics"})

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


class ChatRequest(StrictModel):
    """自由工具 Agent 请求。

    `context_task_id` 只提供**订单数据上下文**（可见订单、customer_id、current_day），
    不提供任务真值：`user_request` 完全由调用方决定。省略时使用演示任务集里第一条
    任务的上下文，保证本地演示无需先查 task id。
    """

    user_request: str = Field(min_length=1, max_length=4096)
    context_task_id: str | None = None

    @field_validator("user_request")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            msg = "user_request 不得为空白"
            raise ValueError(msg)
        return value


def create_formal_app(
    release_dir: Path,
    bundle_dir: Path,
    build_dir: Path,
    *,
    backend_factory: BackendFactory,
    api_key: str,
    episode_timeout_s: float = DEFAULT_EPISODE_TIMEOUT_S,
) -> FastAPI:
    """按封存 holdout 的发布决策加载真实模型并暴露受控工具 Agent 服务。

    SPEC §4 的"没有通过发布门禁的模型不得被服务入口加载"在这里是**双重**执行的：
    NO-GO 时 adapter 根本不会传给工厂，且随后还会核对工厂真正返回的后端没有挂
    adapter。只做前者不够——工厂是注入缝，实现可能来自别处。

    `api_key` 是必填的：缺失时在**装配期**就失败，而不是在运行期放行。运行期放行
    是部署脚本里最容易被忽略的失败形态。key 由调用方提供（CLI 从环境变量读），
    因此永远不会出现在仓库里。
    """
    if not api_key or not api_key.strip():
        msg = "formal service 必须配置非空 API key"
        raise ValueError(msg)
    if episode_timeout_s <= 0:
        msg = "episode_timeout_s 必须为正数"
        raise ValueError(msg)

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
    # 合并形态的候选是**另一份权重**而不是"基座 + 旁路"：GO 时加载它，
    # NO-GO 时必须回到基座——后者恰恰是被拒绝的那个东西。
    model = release.model
    if deploy_candidate and release.candidate_model is not None:
        model = release.candidate_model
    backend = backend_factory(model, adapter)
    _require_backend_matches_deployment(backend, model, adapter)

    policy_id = release.candidate_policy_id if deploy_candidate else release.base_policy_id
    policy = QwenPolicy(backend, policy_id, release.generation.max_new_tokens)
    tasks = load_built_tasks(build_dir)
    allowed_tools = tuple(sorted(tool.name for tool in bundle.tools))
    episode_lock = threading.BoundedSemaphore(_MAX_CONCURRENT_EPISODES)
    # 生成是同步阻塞调用，无法从外部中断。放进单 worker 线程池后，超时的请求
    # 可以立刻返回结构化错误，而占着单卡的那次生成继续跑到自然结束；信号量直到
    # 那时才释放，于是后续请求得到 503 而不是把第二份工作压到同一张卡上。
    executor = ThreadPoolExecutor(max_workers=_MAX_CONCURRENT_EPISODES)
    metrics = ServiceMetrics()

    app = FastAPI(title="RetailAgentOps", version=bundle.bundle.bundle_version)
    app.state.metrics = metrics

    @app.middleware("http")
    async def authenticate(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path in _OPEN_PATHS:
            return await call_next(request)
        if not _authorized(request, api_key):
            _mark_rejected("unauthorized")
            return JSONResponse(status_code=401, content={"detail": "缺少或无效的 API key"})
        return await call_next(request)

    @app.middleware("http")
    async def limit_request_size(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        verdict = _request_body_verdict(request)
        if verdict is not None:
            reason = "request_length_required" if verdict == 411 else "request_too_large"
            _mark_rejected(reason)
            detail = (
                "带请求体的请求必须声明 content-length"
                if verdict == 411
                else f"请求体超过 {MAX_REQUEST_BYTES} 字节上限"
            )
            return JSONResponse(status_code=verdict, content={"detail": detail})
        return await call_next(request)

    @app.middleware("http")
    async def observe(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        record = new_record(uuid.uuid4().hex, request.url.path)
        REQUEST_RECORD.set(record)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # SRE 审查 I-4：未处理异常此前完全绕过指标与结构化日志——
            # "一次请求恰好一行日志"的承诺必须在异常路径同样成立。
            record["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
            record["status"] = 500
            if request.url.path not in _OPEN_PATHS:
                metrics.record_request(request.url.path, 500)
                emit(record)
            raise
        finally:
            record["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
        record["status"] = response.status_code
        response.headers["X-Trace-Id"] = record["trace_id"]
        if request.url.path not in _OPEN_PATHS:
            metrics.record_request(request.url.path, response.status_code)
            if record["reject_reason"] is not None:
                metrics.record_rejection(str(record["reject_reason"]))
            emit(record)
        return response

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

    @app.get("/metrics")
    def prometheus_metrics() -> PlainTextResponse:
        return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")

    @app.get("/v1/tasks")
    def list_tasks() -> dict[str, Any]:
        return {"task_ids": sorted(tasks), "allowed_tools": list(allowed_tools)}

    def _run_guarded(task: TaskSpec) -> Trajectory:
        """在并发上限与时限内跑一条 episode；两种降级都是结构化错误。"""
        if not episode_lock.acquire(blocking=False):
            _mark_rejected("concurrency_limit")
            raise HTTPException(status_code=503, detail="服务已达并发上限，请稍后重试")
        # SRE 审查 I-3：episode 延迟必须在这里计时。`duration_ms` 由 observe
        # 中间件在 call_next **返回之后**才写入，路由体内读到的永远是初始 0.0，
        # /metrics 的延迟分位数因此从上线起就恒为 0。
        episode_started = time.perf_counter()
        future = executor.submit(
            run_episode,
            task,
            lambda current: RetailOpsEnv(current, bundle),
            policy,
            manifest.seed,
        )
        future.add_done_callback(lambda _: episode_lock.release())
        try:
            trajectory = future.result(timeout=episode_timeout_s)
        except FutureTimeoutError:
            metrics.record_timeout()
            _mark_rejected("episode_timeout")
            raise HTTPException(
                status_code=504,
                detail={
                    "error": "episode_timeout",
                    "trace_id": _trace_id(),
                    "timeout_s": episode_timeout_s,
                },
            ) from None
        record = REQUEST_RECORD.get(None)
        if record is not None:
            record["episode_ms"] = round((time.perf_counter() - episode_started) * 1000, 3)
        return trajectory

    def _finish(trajectory: Trajectory) -> None:
        record = REQUEST_RECORD.get(None) or {}
        tool_calls = [
            step.tool_call.name for step in trajectory.steps if step.tool_call is not None
        ]
        record["termination"] = trajectory.termination.value
        record["tool_calls"] = tool_calls
        record["violations"] = list(trajectory.violations)
        record["deployment"] = release.deployment
        record["policy_id"] = policy_id
        episode_ms = record.get("episode_ms")
        if episode_ms is None:
            # 无 episode 计时的请求不该发生（_run_guarded 总会写）；给 0.0 并
            # 依赖 episodes 计数兜底，不伪造一个看似合法的延迟数。
            episode_ms = 0.0
        metrics.record_episode(
            latency_ms=float(episode_ms),
            tool_calls=len(tool_calls),
            violations=len(trajectory.violations),
        )

    @app.post("/v1/tasks/{task_id}/run")
    def run_task(task_id: str) -> dict[str, Any]:
        task = tasks.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="未知演示 task")
        trajectory = _run_guarded(task)
        _finish(trajectory)
        response = _public_trajectory_response(trajectory)
        response["deployment"] = release.deployment
        response["policy_id"] = policy_id
        response["trace_id"] = _trace_id()
        return response

    @app.post("/v1/chat")
    def chat(payload: ChatRequest) -> dict[str, Any]:
        context = _chat_context(tasks, payload.context_task_id)
        record = REQUEST_RECORD.get(None) or {}
        record["request_sha256"] = digest_text(payload.user_request)
        record["request_chars"] = len(payload.user_request)
        trajectory = _run_guarded(_chat_task(context, payload.user_request, _trace_id()))
        _finish(trajectory)
        response = _public_trajectory_response(trajectory)
        # 自由请求没有真值：删掉 success 而不是填一个恒假的值，避免任何
        # 下游把它读成"这次请求失败了"。
        response.pop("success", None)
        response["ground_truth"] = False
        response["final_response"] = _last_final_response(trajectory)
        response["deployment"] = release.deployment
        response["policy_id"] = policy_id
        response["trace_id"] = _trace_id()
        response["context_task_id"] = context.task_id
        return response

    return app


def _request_body_verdict(request: Request) -> int | None:
    """请求体检查：411（无 content-length 的带体方法）/ 413（超限）/ None（放行）。

    SRE 审查 I-7：chunked 传输没有 content-length，会绕过大小检查——FastAPI
    随后把整个 body 读进内存才由 Pydantic 拒绝。带请求体的方法必须声明长度。
    """
    declared = request.headers.get("content-length")
    # scoped re-review Minor-2：isdigit 对 "¹²" 等上标数字也返回 True，int() 会抛
    # ValueError 变 500——长度必须全 ASCII 数字才算数，否则视同未声明（411）。
    declared_valid = declared is not None and declared.isascii() and declared.isdigit()
    if request.method in {"POST", "PUT", "PATCH"} and not declared_valid:
        return 411
    if declared_valid and int(declared or "0") > MAX_REQUEST_BYTES:
        return 413
    return None


def _authorized(request: Request, api_key: str) -> bool:
    """常量时间比较，避免按前缀逐字符试探。

    `hmac.compare_digest` 对含非 ASCII 字符的 str 抛 TypeError（SRE 审查 I-4），
    会在鉴权中间件里变成一个不进任何指标日志的 500——两侧先编码成 bytes。
    """
    header = request.headers.get("authorization", "")
    scheme, _, presented = header.partition(" ")
    if scheme.lower() != "bearer" or not presented:
        presented = request.headers.get("x-api-key", "")
    if not presented:
        return False
    return hmac.compare_digest(
        presented.encode("utf-8", errors="replace"),
        api_key.encode("utf-8", errors="replace"),
    )


def _mark_rejected(reason: str) -> None:
    record = REQUEST_RECORD.get(None)
    if record is not None:
        record["reject_reason"] = reason


def _trace_id() -> str:
    record = REQUEST_RECORD.get(None) or {}
    return str(record.get("trace_id", ""))


def _chat_context(tasks: dict[str, TaskSpec], task_id: str | None) -> TaskSpec:
    if task_id is None:
        return tasks[sorted(tasks)[0]]
    context = tasks.get(task_id)
    if context is None:
        raise HTTPException(status_code=404, detail="未知上下文 task")
    return context


def _chat_task(context: TaskSpec, user_request: str, trace_id: str) -> TaskSpec:
    """借用演示任务的订单数据，但**不借用**它的真值。"""
    return TaskSpec(
        task_id=f"chat-{trace_id}",
        split="qualification",
        scenario=context.scenario,
        user_request=user_request,
        initial_state=context.initial_state,
        target_state=dict(_NO_GROUND_TRUTH_STATE),
        expected_calls=[],
        expected_decision=None,
        required_reads=[],
        transient_failures={},
        max_steps=CHAT_MAX_STEPS,
        metadata={"context_task_id": context.task_id, "ground_truth": False},
    )


def _last_final_response(trajectory: Trajectory) -> str | None:
    for step in reversed(trajectory.steps):
        if step.final_response is not None:
            return step.final_response
    return None


def _require_backend_matches_deployment(
    backend: GenerationBackend,
    expected_model: ModelArtifact,
    expected_adapter: AdapterArtifact | None,
) -> None:
    """核对工厂返回的后端与发布决策一致；这条检查是回滚承诺的执行者。

    **模型与 adapter 都要核。** 只核 adapter 在合并形态下是空的保证：那时候选与基座
    两侧都没有 adapter，真正的区别在**加载了哪份权重**——工厂是注入缝，返回错的那份
    权重会让"回滚"变成一句空话。
    """
    declared_model = getattr(backend, "model_dir", None)
    if declared_model is None:
        # SRE 审查 I-5：不声明 pin 的后端会让全部核对 vacuous pass——工厂是
        # 注入缝，"没说加载了什么"必须与"加载错了"同样被拒绝。
        msg = "后端未声明 model_dir，无法核对它与发布决策加载了同一份权重"
        raise ValueError(msg)
    if Path(declared_model).name != expected_model.local_dir:
        msg = (
            f"后端加载的模型与发布决策不一致：期望 {expected_model.local_dir}，"
            f"实际 {declared_model}"
        )
        raise ValueError(msg)
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
