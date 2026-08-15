"""P1-7：把 formal serve 从演示夹具补成一个真正的服务。

评审口径：R3 的 `create_formal_app` 只有 `/v1/tasks/{id}/run`，只能跑预置任务、
不接受自由请求、无鉴权、无结构化日志、无 trace_id、无 `/metrics`、超时会挂死。
"单卡部署"这个卖点当时只兑现了"能把权重加载起来"。

这里全程用 fake backend，不加载真实模型、不访问 CUDA。并发上限保持 1 且保留
503 语义——排队会让延迟测量失真，而延迟是发布门禁项（`docs/SYSTEM_CARD.md` §4.2）。
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from veritool_rl.core.agent.qwen import GeneratedText, GenerationSettings
from veritool_rl.retail_ops.build.manifests import build_qualification
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.evaluate.base_evaluation import ModelArtifact
from veritool_rl.retail_ops.evaluate.candidate_evaluation import AdapterArtifact
from veritool_rl.retail_ops.release.formal_release import (
    FormalReleaseReport,
    write_formal_release_report,
)
from veritool_rl.retail_ops.release.release import GateResult, ReleaseDecision

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_REL = Path("domains/retail_ops/v1")
DATASET_VERSION = "retail_ops_v1_r2_20260722"
REVISION = "8cd0101f70cac4f1efcebc979faf483558e39297"
API_KEY = "test-service-key"
AUTH = {"Authorization": f"Bearer {API_KEY}"}


class _StubBackend:
    """按脚本回放生成结果的 fake 后端。"""

    def __init__(self, *, replies: list[str] | None = None, delay_s: float = 0.0) -> None:
        self.adapter_path: str | None = None
        self.replies = replies or ["已为您核实完毕。"]
        self.delay_s = delay_s
        self.calls = 0
        self.seen_messages: list[list[dict[str, Any]]] = []

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_new_tokens: int,
    ) -> GeneratedText:
        del tools, max_new_tokens
        self.seen_messages.append(messages)
        if self.delay_s:
            time.sleep(self.delay_s)
        text = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return GeneratedText(text=text, input_tokens=8, output_tokens=6)


@pytest.fixture(scope="module")
def _source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("service-layer-source")
    shutil.copytree(REPO_ROOT / BUNDLE_REL, root / BUNDLE_REL)
    build_qualification(root / BUNDLE_REL, 0, root / "build")
    return root


@pytest.fixture
def workspace(_source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shutil.copytree(_source, tmp_path, dirs_exist_ok=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _model() -> ModelArtifact:
    return ModelArtifact(
        repo="Qwen/Qwen3-4B",
        revision=REVISION,
        local_dir="Qwen3-4B-pinned",
        file_sha256={"config.json": "0" * 64},
    )


def _release_report(workspace: Path) -> FormalReleaseReport:
    gates = [
        GateResult(
            gate_id=gate_id,
            passed=gate_id != "success_delta",
            observed=0,
            threshold=0,
            reason="测试用门禁结果。",
        )
        for gate_id in (
            "success_delta",
            "policy_violation_delta",
            "invalid_call_count",
            "p95_latency_ratio",
            "evidence_complete",
        )
    ]
    return FormalReleaseReport(
        decision=ReleaseDecision.NO_GO,
        deployment="baseline",
        policy_version="1.0.0",
        dataset_version=DATASET_VERSION,
        task_count=120,
        base_report_id="a" * 64,
        candidate_report_id="b" * 64,
        bundle_sha256=load_bundle(workspace / BUNDLE_REL).bundle_sha256,
        holdout_artifact_sha256="c" * 64,
        holdout_receipt_sha256="d" * 64,
        parser_id="hermes-single-call-v1",
        evaluator_id="retail_ops_v1",
        code_commit="1" * 40,
        uv_lock_sha256="0" * 64,
        model=_model(),
        adapter=AdapterArtifact(
            run_dir="reports/retail_ops/v1/r3/sft-001",
            file_sha256={"adapter_model.safetensors": "1" * 64},
        ),
        generation=GenerationSettings(max_new_tokens=256),
        base_policy_id="qwen:base",
        candidate_policy_id="qwen:base+adapter",
        gates=gates,
        failed_gate_ids=["success_delta"],
        base_metrics={"task_success": 0.8},
        candidate_metrics={"task_success": 0.72},
    )


def _app(
    workspace: Path,
    backend: _StubBackend | None = None,
    **kwargs: Any,
) -> Any:
    from veritool_rl.retail_ops.serve.service import create_formal_app

    release_dir = workspace / "release"
    write_formal_release_report(_release_report(workspace), release_dir)
    chosen = backend or _StubBackend()
    return create_formal_app(
        release_dir,
        workspace / BUNDLE_REL,
        workspace / "build",
        backend_factory=lambda model, adapter: chosen,
        **{"api_key": API_KEY, **kwargs},
    )


# ---------------------------------------------------------------------------
# 鉴权：新的自由请求面必须默认关闭
# ---------------------------------------------------------------------------


def test_service_refuses_to_start_without_an_api_key(workspace: Path) -> None:
    """fail-closed：没有 API key 就不能装配出一个会接受请求的服务。

    比"key 缺失时放行"更重要的是让缺失变成启动期错误——运行期放行是最容易
    在部署脚本里被忽略的失败形态。
    """
    with pytest.raises(ValueError, match="API key"):
        _app(workspace, api_key="")


def test_free_request_endpoint_rejects_a_missing_key(workspace: Path) -> None:
    client = TestClient(_app(workspace))

    response = client.post("/v1/chat", json={"user_request": "查一下订单"})

    assert response.status_code == 401


def test_free_request_endpoint_rejects_a_wrong_key(workspace: Path) -> None:
    client = TestClient(_app(workspace))

    response = client.post(
        "/v1/chat",
        json={"user_request": "查一下订单"},
        headers={"Authorization": "Bearer wrong-key"},
    )

    assert response.status_code == 401


def test_preset_task_endpoints_also_require_the_key(workspace: Path) -> None:
    """鉴权覆盖整个 `/v1` 面，不只是新端点。"""
    client = TestClient(_app(workspace))

    assert client.get("/v1/tasks").status_code == 401
    assert client.post("/v1/tasks/anything/run").status_code == 401


def test_health_and_metrics_stay_open(workspace: Path) -> None:
    """/health 与 /metrics 不带 key 也可读：两者都不暴露任务内容或凭据。"""
    client = TestClient(_app(workspace))

    assert client.get("/health").status_code == 200
    assert client.get("/metrics").status_code == 200


# ---------------------------------------------------------------------------
# 自由请求端点
# ---------------------------------------------------------------------------


def test_free_request_runs_an_episode_and_returns_the_tool_trace(workspace: Path) -> None:
    """`POST /v1/chat` 接受任意 user_request，落到同一条 run_episode。"""
    backend = _StubBackend(
        replies=[
            '<tool_call>{"name": "get_order", "arguments": {"order_id": "%s"}}</tool_call>',
            "您的订单已核实完毕。",
        ]
    )
    app = _app(workspace, backend)
    client = TestClient(app)
    context_task_id = client.get("/v1/tasks", headers=AUTH).json()["task_ids"][0]

    response = client.post(
        "/v1/chat",
        json={"user_request": "帮我看看我那笔订单到哪了", "context_task_id": context_task_id},
        headers=AUTH,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["deployment"] == "baseline"
    assert body["policy_id"] == "qwen:base"
    assert isinstance(body["steps"], list) and body["steps"]
    assert body["termination"] in {"final_response", "step_limit", "policy_violation"}
    assert len(body["trace_id"]) == 32


def test_free_request_does_not_report_success(workspace: Path) -> None:
    """自由请求没有真值，服务不得报告 success——那会把演示包装成能力证明。"""
    app = _app(workspace)
    client = TestClient(app)

    body = client.post("/v1/chat", json={"user_request": "你好"}, headers=AUTH).json()

    assert "success" not in body
    assert body["ground_truth"] is False


def test_free_request_reaches_the_model_with_the_users_own_text(workspace: Path) -> None:
    """借用的上下文只提供订单数据，用户请求必须是调用方自己的那一句。"""
    backend = _StubBackend()
    client = TestClient(_app(workspace, backend))

    client.post("/v1/chat", json={"user_request": "唯一标识句 ABC123"}, headers=AUTH)

    first_turn = backend.seen_messages[0]
    assert first_turn[-1]["role"] == "user"
    assert first_turn[-1]["content"] == "唯一标识句 ABC123"


def test_free_request_rejects_an_unknown_context_task(workspace: Path) -> None:
    client = TestClient(_app(workspace))

    response = client.post(
        "/v1/chat",
        json={"user_request": "查订单", "context_task_id": "no-such-task"},
        headers=AUTH,
    )

    assert response.status_code == 404


def test_free_request_rejects_an_empty_user_request(workspace: Path) -> None:
    client = TestClient(_app(workspace))

    assert client.post("/v1/chat", json={"user_request": "  "}, headers=AUTH).status_code == 422


def test_free_request_body_over_the_limit_is_rejected_before_the_model(
    workspace: Path,
) -> None:
    """`MAX_REQUEST_BYTES` 终于不再是"前瞻性"的：这是第一个带 body 的端点。"""
    from veritool_rl.retail_ops.serve.service import MAX_REQUEST_BYTES

    backend = _StubBackend()
    client = TestClient(_app(workspace, backend))

    response = client.post(
        "/v1/chat",
        content=b"x" * (MAX_REQUEST_BYTES + 1),
        headers={**AUTH, "content-type": "application/json"},
    )

    assert response.status_code == 413
    assert backend.calls == 0


# ---------------------------------------------------------------------------
# 超时与优雅降级
# ---------------------------------------------------------------------------


def test_generation_timeout_returns_a_structured_error(workspace: Path) -> None:
    """超时必须返回结构化错误而不是挂死，并带上可关联日志的 trace_id。"""
    backend = _StubBackend(delay_s=2.0)
    client = TestClient(_app(workspace, backend, episode_timeout_s=0.05))

    response = client.post("/v1/chat", json={"user_request": "查订单"}, headers=AUTH)

    assert response.status_code == 504
    body = response.json()
    assert body["detail"]["error"] == "episode_timeout"
    assert len(body["detail"]["trace_id"]) == 32


# ---------------------------------------------------------------------------
# 结构化日志
# ---------------------------------------------------------------------------


def test_every_request_emits_one_structured_log_line_with_a_trace_id(
    workspace: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = TestClient(_app(workspace))

    with caplog.at_level(logging.INFO, logger="retail_agent_ops.serve"):
        response = client.post("/v1/chat", json={"user_request": "查订单"}, headers=AUTH)

    records = [json.loads(record.message) for record in caplog.records]
    assert len(records) == 1
    entry = records[0]
    assert entry["trace_id"] == response.json()["trace_id"]
    assert entry["endpoint"] == "/v1/chat"
    assert entry["status"] == 200
    assert entry["deployment"] == "baseline"
    assert entry["termination"] in {"final_response", "step_limit", "policy_violation"}
    assert isinstance(entry["tool_calls"], list)
    assert isinstance(entry["duration_ms"], float)
    assert isinstance(entry["violations"], list)


def test_logs_record_a_request_digest_never_the_raw_text(
    workspace: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """日志不得含请求原文：既避免把用户数据落盘，也避免任何任务答案进日志。"""
    secret_text = "订单 O-000123 的敏感描述 ZZTOP"
    client = TestClient(_app(workspace))

    with caplog.at_level(logging.INFO, logger="retail_agent_ops.serve"):
        client.post("/v1/chat", json={"user_request": secret_text}, headers=AUTH)

    blob = "\n".join(record.message for record in caplog.records)
    assert secret_text not in blob
    assert "ZZTOP" not in blob
    entry = json.loads(caplog.records[0].message)
    assert len(entry["request_sha256"]) == 64
    assert entry["request_chars"] == len(secret_text)


def test_logs_never_contain_the_api_key(workspace: Path, caplog: pytest.LogCaptureFixture) -> None:
    client = TestClient(_app(workspace))

    with caplog.at_level(logging.INFO, logger="retail_agent_ops.serve"):
        client.post("/v1/chat", json={"user_request": "查订单"}, headers=AUTH)
        client.post("/v1/chat", json={"user_request": "查订单"})

    blob = "\n".join(record.message for record in caplog.records)
    assert API_KEY not in blob


# ---------------------------------------------------------------------------
# /metrics
# ---------------------------------------------------------------------------


def _metric(text: str, name: str) -> float:
    for line in text.splitlines():
        if line.startswith(f"{name} "):
            return float(line.split(" ", 1)[1])
    raise AssertionError(f"metrics 缺少 {name}\n{text}")


def test_metrics_exposes_prometheus_text(workspace: Path) -> None:
    client = TestClient(_app(workspace))
    client.post("/v1/chat", json={"user_request": "查订单"}, headers=AUTH)

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    text = response.text
    for name in (
        "retail_agent_ops_requests_total",
        "retail_agent_ops_episodes_total",
        "retail_agent_ops_episode_latency_ms",
        "retail_agent_ops_tool_calls_total",
        "retail_agent_ops_policy_violations_total",
        "retail_agent_ops_rejected_total",
        "retail_agent_ops_timeouts_total",
    ):
        assert f"# HELP {name}" in text, f"缺少 {name} 的 HELP"
    assert _metric(text, 'retail_agent_ops_episode_latency_ms{quantile="0.5"}') >= 0.0
    assert _metric(text, 'retail_agent_ops_episode_latency_ms{quantile="0.95"}') >= 0.0
    assert _metric(text, "retail_agent_ops_episodes_total") == 1.0


def test_metrics_counts_the_concurrency_rejection(workspace: Path) -> None:
    """503 必须计数：并发上限是产品承诺，不可观测的承诺等于没有。"""
    entered = threading.Event()
    hold = threading.Event()

    class _Blocking(_StubBackend):
        def generate(
            self,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
            max_new_tokens: int,
        ) -> GeneratedText:
            entered.set()
            hold.wait(timeout=5)
            return super().generate(messages, tools, max_new_tokens)

    client = TestClient(_app(workspace, _Blocking()))
    statuses: list[int] = []

    def first() -> None:
        statuses.append(
            client.post("/v1/chat", json={"user_request": "查订单"}, headers=AUTH).status_code
        )

    worker = threading.Thread(target=first)
    worker.start()
    try:
        assert entered.wait(timeout=5)
        second = client.post("/v1/chat", json={"user_request": "查订单"}, headers=AUTH)
    finally:
        hold.set()
        worker.join(timeout=10)

    assert second.status_code == 503
    assert statuses == [200]
    text = client.get("/metrics").text
    assert _metric(text, 'retail_agent_ops_rejected_total{reason="concurrency_limit"}') == 1.0


def test_metrics_counts_timeouts(workspace: Path) -> None:
    client = TestClient(_app(workspace, _StubBackend(delay_s=2.0), episode_timeout_s=0.05))

    client.post("/v1/chat", json={"user_request": "查订单"}, headers=AUTH)

    text = client.get("/metrics").text
    assert _metric(text, "retail_agent_ops_timeouts_total") == 1.0


def test_metrics_counts_unauthorized_requests(workspace: Path) -> None:
    client = TestClient(_app(workspace))

    client.post("/v1/chat", json={"user_request": "查订单"})

    text = client.get("/metrics").text
    assert _metric(text, 'retail_agent_ops_rejected_total{reason="unauthorized"}') == 1.0
