"""R3 Task 3 C：按发布结论加载真实模型的 serve 通道。

serve 消费的是 `FormalReleaseReport` 而不是 sealed 报告，因此这里直接构造发布
报告，把服务层与评测层隔开测试。后端经工厂注入，全程用 fake backend，不加载
真实模型、不访问 CUDA——这正是"默认本地 CPU 可启动"的含义。
"""

from __future__ import annotations

import shutil
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
ADAPTER_RUN_DIR = "reports/retail_ops/v1/r3/sft-001"
REVISION = "8cd0101f70cac4f1efcebc979faf483558e39297"
ORDER_PATTERN = "O-"
API_KEY = "test-formal-service-key"
AUTH = {"Authorization": f"Bearer {API_KEY}"}


class _RecordingBackend:
    """记录自身 pin 的 fake 后端；只回一句最终答复。"""

    def __init__(self, *, model_dir: str, adapter_path: str | None) -> None:
        self.model_dir = model_dir
        self.adapter_path = adapter_path
        self.revision = REVISION
        self.calls = 0

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_new_tokens: int,
    ) -> GeneratedText:
        del messages, tools, max_new_tokens
        self.calls += 1
        return GeneratedText(text="已为您核实完毕。", input_tokens=8, output_tokens=6)


@pytest.fixture(scope="module")
def _source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("r3-serve-source")
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


def _adapter() -> AdapterArtifact:
    return AdapterArtifact(
        run_dir=ADAPTER_RUN_DIR,
        file_sha256={"adapter_model.safetensors": "1" * 64},
    )


def _gates(*, success_passed: bool) -> list[GateResult]:
    passed = {
        "success_delta": success_passed,
        "policy_violation_delta": True,
        "invalid_call_count": True,
        "p95_latency_ratio": True,
        "evidence_complete": True,
    }
    return [
        GateResult(
            gate_id=gate_id,
            passed=value,
            observed=0,
            threshold=0,
            reason="测试用门禁结果。",
        )
        for gate_id, value in passed.items()
    ]


def _release_report(workspace: Path, *, go: bool) -> FormalReleaseReport:
    gates = _gates(success_passed=go)
    failed = [gate.gate_id for gate in gates if not gate.passed]
    return FormalReleaseReport(
        decision=ReleaseDecision.GO if go else ReleaseDecision.NO_GO,
        deployment="candidate" if go else "baseline",
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
        adapter=_adapter(),
        generation=GenerationSettings(max_new_tokens=256),
        base_policy_id="qwen:base",
        candidate_policy_id="qwen:base+adapter",
        gates=gates,
        failed_gate_ids=failed,
        base_metrics={"task_success": 0.8},
        candidate_metrics={"task_success": 0.72},
    )


def _write_release(workspace: Path, *, go: bool) -> Path:
    release_dir = workspace / ("release-go" if go else "release-no-go")
    write_formal_release_report(_release_report(workspace, go=go), release_dir)
    return release_dir


def _factory_recording(seen: list[tuple[ModelArtifact, AdapterArtifact | None]]) -> Any:
    def factory(model: ModelArtifact, adapter: AdapterArtifact | None) -> _RecordingBackend:
        seen.append((model, adapter))
        return _RecordingBackend(
            model_dir=f"models/{model.local_dir}",
            adapter_path=None if adapter is None else str(adapter.adapter_dir),
        )

    return factory


def test_no_go_release_must_not_load_the_adapter(workspace: Path) -> None:
    """SPEC §4：没有通过发布门禁的模型不得被服务入口加载。

    NO-GO 时服务必须只拿到基座 pin，adapter 连传都不能传给后端工厂——否则
    "回滚到冻结 base" 只是文档承诺，而不是代码事实。
    """
    from veritool_rl.retail_ops.serve.service import create_formal_app

    seen: list[tuple[ModelArtifact, AdapterArtifact | None]] = []
    release_dir = _write_release(workspace, go=False)

    create_formal_app(
        release_dir,
        workspace / BUNDLE_REL,
        workspace / "build",
        backend_factory=_factory_recording(seen),
        api_key=API_KEY,
    )

    assert len(seen) == 1
    assert seen[0][1] is None


def test_go_release_loads_the_pinned_adapter(workspace: Path) -> None:
    """正对照：GO 时必须把发布报告锁定的那个 adapter 交给后端。"""
    from veritool_rl.retail_ops.serve.service import create_formal_app

    seen: list[tuple[ModelArtifact, AdapterArtifact | None]] = []
    release_dir = _write_release(workspace, go=True)

    create_formal_app(
        release_dir,
        workspace / BUNDLE_REL,
        workspace / "build",
        backend_factory=_factory_recording(seen),
        api_key=API_KEY,
    )

    assert len(seen) == 1
    assert seen[0][1] == _adapter()


def test_backend_that_ignores_the_rollback_is_rejected(workspace: Path) -> None:
    """工厂即使无视回滚指令挂上 adapter，服务也必须在启动时拒绝。

    只把 adapter 传或不传给工厂是不够的——工厂是注入缝，可能来自别处。
    """
    from veritool_rl.retail_ops.serve.service import create_formal_app

    release_dir = _write_release(workspace, go=False)

    def rogue(model: ModelArtifact, adapter: AdapterArtifact | None) -> _RecordingBackend:
        del adapter
        return _RecordingBackend(
            model_dir=f"models/{model.local_dir}",
            adapter_path=f"{ADAPTER_RUN_DIR}/adapter",
        )

    with pytest.raises(ValueError, match="adapter"):
        create_formal_app(
            release_dir,
            workspace / BUNDLE_REL,
            workspace / "build",
            backend_factory=rogue,
            api_key=API_KEY,
        )


def test_health_exposes_the_decision_and_rollback_path(workspace: Path) -> None:
    """/health 必须能直接回答"现在跑的是哪个、为什么、怎么回滚"。"""
    from veritool_rl.retail_ops.serve.service import create_formal_app

    app = create_formal_app(
        _write_release(workspace, go=False),
        workspace / BUNDLE_REL,
        workspace / "build",
        backend_factory=_factory_recording([]),
        api_key=API_KEY,
    )

    payload = TestClient(app).get("/health").json()

    assert payload["status"] == "ok"
    assert payload["release_decision"] == "NO-GO"
    assert payload["deployment"] == "baseline"
    assert payload["failed_gate_ids"] == ["success_delta"]
    assert payload["adapter_loaded"] is False
    assert "回滚" in payload["rollback"]


def test_episode_runs_the_model_policy_and_returns_the_tool_trace(workspace: Path) -> None:
    """服务必须能跑通一条 episode 并展示工具轨迹，而不只是返回一个分数。"""
    from veritool_rl.retail_ops.serve.service import create_formal_app

    app = create_formal_app(
        _write_release(workspace, go=False),
        workspace / BUNDLE_REL,
        workspace / "build",
        backend_factory=_factory_recording([]),
        api_key=API_KEY,
    )
    client = TestClient(app)
    task_id = client.get("/v1/tasks", headers=AUTH).json()["task_ids"][0]

    response = client.post(f"/v1/tasks/{task_id}/run", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["task_id"] == task_id
    assert body["deployment"] == "baseline"
    assert "steps" in body
    assert "termination" in body


def test_unknown_task_is_rejected(workspace: Path) -> None:
    from veritool_rl.retail_ops.serve.service import create_formal_app

    app = create_formal_app(
        _write_release(workspace, go=False),
        workspace / BUNDLE_REL,
        workspace / "build",
        backend_factory=_factory_recording([]),
        api_key=API_KEY,
    )

    assert TestClient(app).post("/v1/tasks/../escape/run", headers=AUTH).status_code == 404


def test_formal_service_rejects_a_bundle_that_differs_from_the_release(
    workspace: Path,
) -> None:
    """服务加载的 bundle 必须与发布决策所依据的那一份一致。"""
    from veritool_rl.retail_ops.serve.service import create_formal_app

    release_dir = _write_release(workspace, go=False)
    other_bundle = workspace / "other-bundle"
    shutil.copytree(workspace / BUNDLE_REL, other_bundle)
    policies = other_bundle / "policies.yaml"
    policies.write_text(policies.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")

    with pytest.raises(ValueError, match="SHA-256 不匹配"):
        create_formal_app(
            release_dir,
            other_bundle,
            workspace / "build",
            backend_factory=_factory_recording([]),
            api_key=API_KEY,
        )


def test_oversized_request_body_is_rejected(workspace: Path) -> None:
    """SPEC §9 的请求大小上限：超限必须在进入模型之前以 413 拒绝。"""
    from veritool_rl.retail_ops.serve.service import MAX_REQUEST_BYTES, create_formal_app

    app = create_formal_app(
        _write_release(workspace, go=False),
        workspace / BUNDLE_REL,
        workspace / "build",
        backend_factory=_factory_recording([]),
        api_key=API_KEY,
    )
    client = TestClient(app)
    task_id = client.get("/v1/tasks", headers=AUTH).json()["task_ids"][0]

    response = client.post(
        f"/v1/tasks/{task_id}/run",
        content=b"x" * (MAX_REQUEST_BYTES + 1),
        headers={**AUTH, "content-type": "application/octet-stream"},
    )

    assert response.status_code == 413


def test_concurrent_episodes_are_capped_instead_of_queueing(workspace: Path) -> None:
    """单卡服务串行跑 episode：第二个并发请求必须立刻 503，而不是排队占显存。

    排队会让延迟测量失真，也会在真实 GPU 上把显存峰值推到不可预测的位置。
    """
    import threading

    from veritool_rl.retail_ops.serve.service import create_formal_app

    entered = threading.Event()
    release_hold = threading.Event()

    class _BlockingBackend(_RecordingBackend):
        def generate(
            self,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
            max_new_tokens: int,
        ) -> GeneratedText:
            entered.set()
            release_hold.wait(timeout=5)
            return super().generate(messages, tools, max_new_tokens)

    def factory(model: ModelArtifact, adapter: AdapterArtifact | None) -> _BlockingBackend:
        del adapter
        return _BlockingBackend(model_dir=f"models/{model.local_dir}", adapter_path=None)

    app = create_formal_app(
        _write_release(workspace, go=False),
        workspace / BUNDLE_REL,
        workspace / "build",
        backend_factory=factory,
        api_key=API_KEY,
    )
    client = TestClient(app)
    task_ids = client.get("/v1/tasks", headers=AUTH).json()["task_ids"]

    first_status: list[int] = []

    def run_first() -> None:
        first_status.append(client.post(f"/v1/tasks/{task_ids[0]}/run", headers=AUTH).status_code)

    worker = threading.Thread(target=run_first)
    worker.start()
    try:
        assert entered.wait(timeout=5)
        second = client.post(f"/v1/tasks/{task_ids[1]}/run", headers=AUTH)
    finally:
        release_hold.set()
        worker.join(timeout=10)

    assert second.status_code == 503
    assert first_status == [200]


def test_serve_cli_dispatches_the_formal_path_and_records_provenance(
    workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`serve` 必须有一条按封存 holdout 发布决策启动真实模型服务的通道。

    `uvicorn.run` 会阻塞，因此 runner 是注入缝；本测试只验证服务被正确装配、
    provenance 落盘，不真的监听端口。
    """
    import argparse

    import yaml
    from fastapi import FastAPI

    from veritool_rl.product_cli import SERVICE_API_KEY_ENV, _run_serve

    monkeypatch.setenv(SERVICE_API_KEY_ENV, API_KEY)

    release_dir = _write_release(workspace, go=False)
    config_path = workspace / "formal-serve.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "pipeline": "formal_serve",
                "bundle_dir": str(BUNDLE_REL),
                "models_root": "models",
                "host": "127.0.0.1",
                "port": 8000,
                "episode_timeout_s": 30.0,
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    started: list[tuple[FastAPI, str, int]] = []

    _run_serve(
        argparse.Namespace(
            command="serve",
            config=config_path,
            seed=0,
            output_dir=workspace / "serve-out",
            release_dir=release_dir,
            input_dir=workspace / "build",
        ),
        backend_factory=_factory_recording([]),
        app_runner=lambda app, host, port: started.append((app, host, port)),
    )

    assert len(started) == 1
    assert started[0][1:] == ("127.0.0.1", 8000)

    import json

    service = json.loads((workspace / "serve-out" / "service.json").read_text(encoding="utf-8"))
    assert service["deployment"] == "baseline"
    assert service["release_decision"] == "NO-GO"
    assert service["adapter_loaded"] is False
    assert service["failed_gate_ids"] == ["success_delta"]


def test_default_formal_backend_factory_honours_the_rollback(workspace: Path) -> None:
    """默认工厂在 adapter 为 None 时不得给 TransformersBackend 传任何 adapter 路径。"""
    import veritool_rl.product_cli as product_cli

    calls: list[tuple[str, str | None]] = []

    def fake_from_pretrained(model_name: str, adapter_name: str | None, **kwargs: Any) -> object:
        calls.append((model_name, adapter_name))
        return object()

    original = product_cli.TransformersBackend.from_pretrained
    product_cli.TransformersBackend.from_pretrained = staticmethod(  # type: ignore[method-assign]
        fake_from_pretrained
    )
    try:
        product_cli._default_formal_backend(_model(), None, Path("models"))
        product_cli._default_formal_backend(_model(), _adapter(), Path("models"))
    finally:
        product_cli.TransformersBackend.from_pretrained = original  # type: ignore[method-assign]

    del workspace
    assert calls[0][1] is None
    assert calls[1][1] == str(_adapter().adapter_dir)
