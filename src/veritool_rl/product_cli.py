"""RetailAgentOps 稳定 build/evaluate/release/serve 产品命令面。

R1 的四个命令行为完全保留：config 没有 `pipeline` 字段时，`build`/`evaluate`
逐字节走原有的精确 key 集合路径。R2 在 `build`/`evaluate` 之上新增按
`pipeline` 分发的四条流水线（`formal_freeze`/`teacher_collect`/`train_export`/
`formal_dev_base`），`release`/`serve` 不新增任何 R2 路径。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, cast

import uvicorn
from fastapi import FastAPI

from veritool_rl.cli import load_config
from veritool_rl.core.agent.qwen import (
    CudaHardwareProvider,
    GenerationBackend,
    GenerationSettings,
    HardwareProvider,
    TransformersBackend,
    verify_local_model_files,
)
from veritool_rl.core.artifacts import (
    canonical_json,
    create_output_dir,
    current_runtime_env_sha256,
    sha256_file,
    write_json,
)
from veritool_rl.core.paths import validate_project_relative_path
from veritool_rl.retail_ops.build.dev_sft_export import build_dev_sft_rows, write_dev_sft_export
from veritool_rl.retail_ops.build.formal_manifests import (
    FormalTaskManifest,
    load_formal_holdout_receipt,
    load_formal_split,
    load_formal_task_manifest,
    load_verified_formal_dataset,
    write_formal_task_set,
)
from veritool_rl.retail_ops.build.manifests import build_qualification
from veritool_rl.retail_ops.build.ood_manifests import (
    OodPhrasingSpec,
    build_ood_task_set,
    load_ood_manifest,
)
from veritool_rl.retail_ops.build.phrasing_bank import (
    ParaphrasePlan,
    assert_partitions_are_disjoint,
    bank_sha256,
    intent_index,
    load_paraphrase_plan,
    load_phrasing_bank,
)
from veritool_rl.retail_ops.build.teacher_client import OpenAICompatibleTeacherClient, TeacherClient
from veritool_rl.retail_ops.build.teacher_data import (
    TeacherAttemptEvidence,
    TeacherCollectionCheckpoint,
    TeacherCollectionConfig,
    collect_teacher_attempt,
    export_formal_train,
    load_teacher_checkpoint,
    write_formal_train_export,
    write_teacher_attempt_evidence,
    write_teacher_checkpoint,
)
from veritool_rl.retail_ops.build.teacher_route import TeacherRouteSnapshot, load_teacher_route
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
from veritool_rl.retail_ops.domain.formal_tasks import build_formal_task_set
from veritool_rl.retail_ops.evaluate.base_evaluation import (
    BaseEvaluationConfig,
    ModelArtifact,
    evaluate_formal_dev_base,
    load_verified_formal_dev,
)
from veritool_rl.retail_ops.evaluate.candidate_evaluation import (
    AdapterArtifact,
    CandidateEvaluationConfig,
    evaluate_formal_dev_candidate,
)
from veritool_rl.retail_ops.evaluate.evaluation import (
    EvaluationMode,
    evaluate_retail_ops,
    load_run_evidence,
)
from veritool_rl.retail_ops.evaluate.ood_evaluation import OodEvaluationConfig, evaluate_ood
from veritool_rl.retail_ops.evaluate.sealed_evaluation import (
    MergedProvenance,
    SealedEvaluationConfig,
    evaluate_authorized_holdout,
    load_sealed_evaluation_report,
)
from veritool_rl.retail_ops.release.formal_governance import authorize_formal_holdout
from veritool_rl.retail_ops.release.formal_release import (
    decide_formal_release,
    load_formal_release_report,
    write_formal_release_report,
)
from veritool_rl.retail_ops.release.governance import EvidencePurpose
from veritool_rl.retail_ops.release.release import (
    GATE_IDS_BY_SCHEMA,
    GateSchemaVersion,
    decide_release,
    load_release_report,
    write_release_report,
)
from veritool_rl.retail_ops.serve.observability import configure_service_logging
from veritool_rl.retail_ops.serve.service import BackendFactory, create_app, create_formal_app
from veritool_rl.training.sft import run_sft

_R2_PRIVATE_ROOT = Path("data/private/retail_ops/v1/r2")
_SAFE_COMPONENT_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
_GIT_TIMEOUT_SECONDS = 30.0


def build_product_parser() -> argparse.ArgumentParser:
    """构造稳定的 RetailAgentOps 产品 CLI parser。"""
    parser = argparse.ArgumentParser(description="RetailAgentOps 产品流水线")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser(
        "build", help="构建 qualification 任务与 manifest，或 R2 数据/采集流水线"
    )
    _add_common_arguments(build)
    build.add_argument(
        "--input_dir",
        type=Path,
        default=None,
        help="R2 流水线读取的已产出私有根目录（R1 build 与 formal_freeze 不使用）",
    )

    evaluate = subparsers.add_parser(
        "evaluate", help="运行固定任务评测，或 R2 formal dev base 评测"
    )
    _add_common_arguments(evaluate)
    evaluate.add_argument("--input_dir", type=Path, required=True, help="build 产物目录")
    evaluate.add_argument(
        "--engine",
        choices=["transformers", "vllm"],
        default="transformers",
        help=(
            "推理引擎。transformers = 全部已有证据的路径。vllm 需要一个另装了 vLLM 的 "
            "venv（项目 uv.lock 不变），且只支持已合并的模型；两者都跑 NF4，"
            "因此引擎是唯一变量"
        ),
    )

    release = subparsers.add_parser("release", help="执行配对发布门禁")
    _add_common_arguments(release)
    release.add_argument(
        "--baseline_dir",
        type=Path,
        required=True,
        help="基座 run evidence 目录",
    )
    release.add_argument(
        "--candidate_dir",
        type=Path,
        required=True,
        help="候选 run evidence 目录",
    )
    release.add_argument(
        "--baseline_trajectories",
        type=Path,
        default=None,
        help=(
            "可选：基座逐任务 trajectories.jsonl（私有产物）。"
            "只有 gate schema v1.1 的配对统计检验需要它；不给则该门禁判 FAIL"
        ),
    )
    release.add_argument(
        "--candidate_trajectories",
        type=Path,
        default=None,
        help="可选：候选逐任务 trajectories.jsonl（私有产物），与上一项必须成对提供",
    )

    serve = subparsers.add_parser("serve", help="按发布结论启动 qualification 服务")
    _add_common_arguments(serve)
    serve.add_argument(
        "--release_dir",
        type=Path,
        required=True,
        help="release report 目录",
    )
    serve.add_argument("--input_dir", type=Path, required=True, help="build 产物目录")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """解析命令并同步执行一个不可覆盖的产品流水线步骤。"""
    parser = build_product_parser()
    args = parser.parse_args(argv)
    handlers: dict[str, Callable[[argparse.Namespace], None]] = {
        "build": _run_build,
        "evaluate": _run_evaluate,
        "release": _run_release,
        "serve": _run_serve,
    }
    handlers[args.command](args)
    return 0


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, required=True, help="已提交的 YAML 配置")
    parser.add_argument("--seed", type=int, default=0, help="运行随机种子")
    parser.add_argument("--output_dir", type=Path, required=True, help="新产物目录")


def _run_build(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    pipeline = config.get("pipeline")
    if pipeline is None:
        _require_config_keys(config, {"bundle_dir", "split", "inject", "clarify"})
        if args.input_dir is not None:
            raise ValueError("R1 build（无 pipeline 字段）不接受 --input_dir")
        if config["split"] != "qualification":
            raise ValueError("R1 build 只允许 qualification split")
        inject = config["inject"]
        clarify = config["clarify"]
        if not isinstance(inject, bool) or not isinstance(clarify, bool):
            raise ValueError("inject 与 clarify 必须是 bool")
        bundle_dir = _bundle_dir(config)
        build_qualification(bundle_dir, args.seed, args.output_dir, inject=inject, clarify=clarify)
        return
    if pipeline == "ood_build":
        _run_ood_build(args, config)
    elif pipeline == "formal_freeze":
        _run_formal_freeze(args, config)
    elif pipeline == "teacher_collect":
        _run_teacher_collect(args, config)
    elif pipeline == "train_export":
        _run_train_export(args, config)
    elif pipeline == "state_aug_export":
        _run_state_aug_export(args, config)
    elif pipeline == "dev_sft_export":
        _run_dev_sft_export(args, config)
    elif pipeline == "sft":
        _run_sft(args, config)
    else:
        raise ValueError(f"未知 build pipeline: {pipeline!r}")


def _run_evaluate(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    pipeline = config.get("pipeline")
    if pipeline is None:
        _require_config_keys(
            config,
            {
                "bundle_dir",
                "mode",
                "policy_type",
                "bootstrap_samples",
                "parser_id",
                "budget",
                "perturb_schema",
                "guardrail",
                "user_simulator",
            },
        )
        bundle_dir = _bundle_dir(config)
        try:
            mode = EvaluationMode(str(config["mode"]))
        except ValueError as error:
            raise ValueError(f"未知 RetailOps evaluation mode: {config['mode']}") from error
        policy_type = config["policy_type"]
        if not isinstance(policy_type, str) or not policy_type:
            raise ValueError("policy_type 必须是非空字符串")
        evaluate_retail_ops(
            bundle_dir=bundle_dir,
            build_dir=args.input_dir,
            policy_type=policy_type,
            config=config,
            seed=args.seed,
            output_dir=args.output_dir,
            mode=mode,
        )
        return
    if pipeline == "formal_dev_base":
        _run_formal_dev_base(args, config)
        return
    if pipeline == "formal_dev_candidate":
        _run_formal_dev_candidate(args, config)
        return
    if pipeline in _FORMAL_HOLDOUT_PIPELINES:
        _run_formal_holdout(args, config)
        return
    if pipeline in _OOD_EVAL_PIPELINES:
        _run_ood_evaluate(args, config)
        return
    raise ValueError(f"未知 evaluate pipeline: {pipeline!r}")


def _run_release(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    pipeline = config.get("pipeline")
    if pipeline == "formal_release":
        _run_formal_release(args, config)
        return
    if pipeline is not None:
        raise ValueError(f"未知 release pipeline: {pipeline!r}")
    _require_config_keys(config, {"bundle_dir"})
    bundle = load_bundle(_bundle_dir(config))
    baseline = load_run_evidence(args.baseline_dir / "run.json")
    candidate = load_run_evidence(args.candidate_dir / "run.json")
    if (
        baseline.bundle_sha256 != bundle.bundle_sha256
        or candidate.bundle_sha256 != bundle.bundle_sha256
    ):
        raise ValueError("run evidence 与 release bundle SHA-256 不匹配")
    report = decide_release(baseline, candidate, bundle.release)
    write_release_report(report, args.output_dir)


def _run_serve(
    args: argparse.Namespace,
    *,
    backend_factory: BackendFactory | None = None,
    app_runner: Callable[[FastAPI, str, int], None] | None = None,
) -> None:
    """启动 R1 qualification 服务，或按封存 holdout 发布决策启动真实模型服务。

    `backend_factory`/`app_runner` 是注入缝：CPU 测试可以用 fake 后端装配服务并
    断言 provenance，而不真的加载模型或监听端口。`main()` 走默认的真实实现。
    """
    config = load_config(args.config)
    if config.get("pipeline") == "formal_serve":
        _run_formal_serve(args, config, backend_factory=backend_factory, app_runner=app_runner)
        return
    if config.get("pipeline") is not None:
        raise ValueError(f"未知 serve pipeline: {config['pipeline']!r}")
    _require_config_keys(config, {"bundle_dir", "host", "port"})
    bundle_dir = _bundle_dir(config)
    host = config["host"]
    port = config["port"]
    if not isinstance(host, str) or not host:
        raise ValueError("host 必须是非空字符串")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port 必须是 1 到 65535 的整数")

    app = create_app(args.release_dir, bundle_dir, args.input_dir)
    release = load_release_report(args.release_dir / "release.json")
    create_output_dir(args.output_dir)
    write_json(
        args.output_dir / "service.json",
        {
            "release_sha256": sha256_file(args.release_dir / "release.json"),
            "bundle_sha256": load_bundle(bundle_dir).bundle_sha256,
            "deployment": release.deployment,
            "host": host,
            "port": port,
        },
    )
    uvicorn.run(app, host=host, port=port)


# ---------------------------------------------------------------------------
# R3 pipeline: formal_serve (serve)
# ---------------------------------------------------------------------------

_FORMAL_SERVE_KEYS = {
    "pipeline",
    "bundle_dir",
    "models_root",
    "host",
    "port",
    "episode_timeout_s",
}

#: 服务 API key 只从环境变量读，绝不进配置文件或 Git。缺失时启动即失败。
SERVICE_API_KEY_ENV = "RETAIL_AGENT_OPS_API_KEY"


def _service_api_key() -> str:
    """从环境变量取服务 API key；缺失时给出可操作的错误而不是静默放行。"""
    key = os.environ.get(SERVICE_API_KEY_ENV, "")
    if not key.strip():
        msg = (
            f"必须通过环境变量 {SERVICE_API_KEY_ENV} 提供服务 API key；"
            "该值不得写入配置文件或提交进 Git"
        )
        raise ValueError(msg)
    return key


def _episode_timeout(config: dict[str, Any]) -> float:
    value = config["episode_timeout_s"]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ValueError("episode_timeout_s 必须是正数（秒）")
    return float(value)


def _default_formal_backend(
    model: ModelArtifact,
    adapter: AdapterArtifact | None,
    models_root: Path,
) -> GenerationBackend:
    """生产默认工厂：加载锁定基座，只有发布决策为 candidate 时才挂 adapter。"""
    return TransformersBackend.from_pretrained(
        str(models_root / model.local_dir),
        None if adapter is None else str(adapter.adapter_dir),
        revision=model.revision,
        expected_file_sha256=model.file_sha256,
        settings=GenerationSettings(),
    )


def _run_formal_serve(
    args: argparse.Namespace,
    config: dict[str, Any],
    *,
    backend_factory: BackendFactory | None = None,
    app_runner: Callable[[FastAPI, str, int], None] | None = None,
) -> None:
    """按 `FormalReleaseReport` 装配服务；未过门禁时只加载冻结 base。"""
    _require_config_keys(config, _FORMAL_SERVE_KEYS)
    bundle_dir = _bundle_dir(config)
    models_root = _project_relative_path(config, "models_root")
    host = _config_str(config, "host")
    port = config["port"]
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("port 必须是 1 到 65535 的整数")

    factory = backend_factory or (
        lambda model, adapter: _default_formal_backend(model, adapter, models_root)
    )
    configure_service_logging()
    app = create_formal_app(
        args.release_dir,
        bundle_dir,
        args.input_dir,
        backend_factory=factory,
        api_key=_service_api_key(),
        episode_timeout_s=_episode_timeout(config),
    )
    release = load_formal_release_report(args.release_dir / "release.json")

    create_output_dir(args.output_dir)
    write_json(
        args.output_dir / "service.json",
        {
            "release_sha256": sha256_file(args.release_dir / "release.json"),
            "bundle_sha256": load_bundle(bundle_dir).bundle_sha256,
            "dataset_version": release.dataset_version,
            "release_decision": release.decision.value,
            "deployment": release.deployment,
            "failed_gate_ids": list(release.failed_gate_ids),
            "adapter_loaded": release.deployment == "candidate",
            "host": host,
            "port": port,
        },
    )
    (app_runner or _default_app_runner)(app, host, port)


def _default_app_runner(app: FastAPI, host: str, port: int) -> None:
    uvicorn.run(app, host=host, port=port)


# ---------------------------------------------------------------------------
# R3 pipeline: formal_release (release)
# ---------------------------------------------------------------------------

_FORMAL_RELEASE_KEYS = {"pipeline", "bundle_dir", "gate_schema_version"}
_FORMAL_RELEASE_OPTIONAL_KEYS = {"ood_evidence"}


def _run_formal_release(args: argparse.Namespace, config: dict[str, Any]) -> None:
    """用两份 sealed holdout 报告执行 SPEC §6 的发布门禁并写出证据包。

    公开 sealed 报告是单文件副本，同目录没有私有产物，因此这里显式传
    `verify_artifacts=False`——`load_sealed_evaluation_report` 的默认值是校验，
    不显式关掉会退化成"文件缺失即失败"。report_id 自哈希仍然逐字校验。

    `gate_schema_version` 没有默认值，必须在配置里写出来：判定用的是哪一套门禁
    语义，是这份证据最重要的元数据之一，不能靠"没写就是旧的"。

    v1.2 新增可选 `ood_evidence` 配置项：包含 `base_metrics_path` 和
    `candidate_metrics_path`，指向两份 OOD 评测指标 JSON 文件。传入时
    OOD 门禁参与判定；不传时 OOD 门禁判 FAIL（缺证据不是通过的理由）。
    """
    actual_keys = set(config)
    unknown = actual_keys - _FORMAL_RELEASE_KEYS - _FORMAL_RELEASE_OPTIONAL_KEYS
    if unknown:
        raise ValueError(
            f"配置字段不符合命令契约: 未知键 {sorted(unknown)}，"
            f"允许 {sorted(_FORMAL_RELEASE_KEYS | _FORMAL_RELEASE_OPTIONAL_KEYS)}"
        )
    missing = _FORMAL_RELEASE_KEYS - actual_keys
    if missing:
        raise ValueError(
            f"配置字段不符合命令契约: 缺少 {sorted(missing)}，必须 {sorted(_FORMAL_RELEASE_KEYS)}"
        )
    gate_schema_version = _gate_schema_version(config)
    bundle = load_bundle(_bundle_dir(config))
    base = load_sealed_evaluation_report(
        args.baseline_dir / "sealed-report.json", verify_artifacts=False
    )
    candidate = load_sealed_evaluation_report(
        args.candidate_dir / "sealed-report.json", verify_artifacts=False
    )
    for label, report in (("基座", base), ("候选", candidate)):
        if report.bundle_sha256 != bundle.bundle_sha256:
            raise ValueError(f"{label} sealed 证据与 release bundle SHA-256 不匹配")

    ood_evidence = _load_ood_evidence(config, gate_schema_version)

    write_formal_release_report(
        decide_formal_release(
            base,
            candidate,
            bundle.release,
            gate_schema_version=gate_schema_version,
            paired_outcomes=_paired_outcomes(args, gate_schema_version),
            ood_evidence=ood_evidence,
        ),
        args.output_dir,
    )


def _gate_schema_version(config: dict[str, Any]) -> GateSchemaVersion:
    value = config["gate_schema_version"]
    if value not in GATE_IDS_BY_SCHEMA:
        raise ValueError(f"未知 gate_schema_version: {value!r}，可选 {sorted(GATE_IDS_BY_SCHEMA)}")
    return cast(GateSchemaVersion, value)


def _paired_outcomes(
    args: argparse.Namespace, gate_schema_version: GateSchemaVersion = "1.0"
) -> list[tuple[bool, bool]] | None:
    """从两份私有 `trajectories.jsonl` 读逐任务配对结局。

    两个路径必须成对提供：只给一侧是配置错误，不是"降级到无配对证据"——后者会把
    一次误用悄悄变成一个 FAIL 的门禁，看起来像模型问题。

    **两侧都不给 + v1.1 同样是配置错误**，理由完全相同。库层的
    `_paired_ci_gate` 保持 fail-closed（缺证据不是通过的理由），
    但那是给"拿一份只有聚合量的公开报告复算门禁"用的；这里是命令行，
    操作者明确配了 v1.1，就必须给出它需要的证据。
    2026-08-17 的第五次封存 holdout 观测正是漏了这两个参数，产出了一份
    `NO-GO / success_delta_ci_lower` 的报告——读起来像模型没通过统计检验，
    实际是命令少了两个参数（LOG-20260817-03）。
    """
    baseline_path = getattr(args, "baseline_trajectories", None)
    candidate_path = getattr(args, "candidate_trajectories", None)
    if baseline_path is None and candidate_path is None:
        if gate_schema_version == "1.1":
            raise ValueError(
                "gate_schema_version 1.1 需要逐任务配对证据来计算 success_delta_ci_lower，"
                "请补上 --baseline_trajectories 与 --candidate_trajectories。"
                "缺证据是配置问题，不能产出一份看起来像模型失败的 NO-GO。"
            )
        return None
    if baseline_path is None or candidate_path is None:
        raise ValueError("--baseline_trajectories 与 --candidate_trajectories 必须成对提供")
    baseline = _success_by_task(baseline_path)
    candidate = _success_by_task(candidate_path)
    if set(baseline) != set(candidate):
        raise ValueError("两侧逐任务证据的 task_id 集合不一致，无法配对")
    return [(baseline[task_id], candidate[task_id]) for task_id in sorted(baseline)]


def _load_ood_evidence(
    config: dict[str, Any], gate_schema_version: GateSchemaVersion
) -> tuple[dict[str, Any] | None, dict[str, Any] | None] | None:
    """从配置加载 OOD 评测指标，仅 v1.2 支持。

    v1.2 配置中可选 `ood_evidence` 字段，包含 `base_metrics_path` 和
    `candidate_metrics_path`（JSON 文件路径）。两者必须成对提供。

    非 v1.2 版本传入 ood_evidence 配置是配置错误——该字段只在 v1.2 下有意义。
    """
    ood_config = config.get("ood_evidence")
    if ood_config is None:
        return None
    if gate_schema_version != "1.2":
        raise ValueError(
            f"ood_evidence 配置仅在 gate_schema_version=1.2 下有效，收到 {gate_schema_version!r}"
        )
    if not isinstance(ood_config, dict):
        raise ValueError("ood_evidence 必须是 mapping")
    missing = {"base_metrics_path", "candidate_metrics_path"} - set(ood_config)
    if missing:
        raise ValueError(f"ood_evidence 缺少必填键: {sorted(missing)}")
    base_path = Path(ood_config["base_metrics_path"])
    cand_path = Path(ood_config["candidate_metrics_path"])
    base_ood = json.loads(base_path.read_text(encoding="utf-8"))
    cand_ood = json.loads(cand_path.read_text(encoding="utf-8"))
    if not isinstance(base_ood, dict):
        raise ValueError(f"基座 OOD 指标必须是 JSON object: {base_path}")
    if not isinstance(cand_ood, dict):
        raise ValueError(f"候选 OOD 指标必须是 JSON object: {cand_path}")
    return base_ood, cand_ood


def _success_by_task(path: Path) -> dict[str, bool]:
    outcomes: dict[str, bool] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        task_id = record["task"]["task_id"]
        if task_id in outcomes:
            raise ValueError(f"逐任务证据中存在重复 task_id: {task_id}")
        outcomes[task_id] = bool(record["success"])
    if not outcomes:
        raise ValueError(f"逐任务证据为空: {path}")
    return outcomes


# ---------------------------------------------------------------------------
# R4.5 pipeline: 分布外任务集（build + evaluate）
# ---------------------------------------------------------------------------

_OOD_BUILD_KEYS = {"pipeline", "bundle_dir", "phrasing", "boundary"}
_OOD_EVAL_PIPELINES = ("ood_base", "ood_candidate", "ood_merged_candidate")
_OOD_EVAL_BASE_KEYS = {
    "pipeline",
    "bundle_dir",
    "models_root",
    "model",
    "generation",
}
_OOD_EVAL_CANDIDATE_KEYS = _OOD_EVAL_BASE_KEYS | {"adapter"}


def _run_ood_build(args: argparse.Namespace, config: dict[str, Any]) -> None:
    """生成任务集。它是**独立 dataset artifact**，不碰冻结数据集的一个字节。

    `boundary` 与 `phrasing` 都必须显式写出来（可以是 `false` / `null`）。
    不给默认值的理由与 `partition` 那条相同：一个漏写的开关会让产物静默变成另一份
    数据集，而目录名、manifest 结构、报告字段全都看起来正常。
    """
    _require_config_keys(config, _OOD_BUILD_KEYS)
    boundary = config["boundary"]
    if not isinstance(boundary, bool):
        raise ValueError("boundary 必须是 bool（探针集写 true，其余写 false）")
    phrasing = _ood_phrasing_spec(config, args.input_dir)
    if boundary:
        if phrasing is not None:
            raise ValueError("boundary 与 phrasing 互斥：一次只能构建一种任务集")
        if args.input_dir is not None:
            raise ValueError("政策边界探针不读任何私有素材，因此不接受 --input_dir")
    elif phrasing is None and args.input_dir is not None:
        raise ValueError("ood_build（v1，phrasing 为 null）不接受 --input_dir")
    build_ood_task_set(
        _bundle_dir(config),
        args.seed,
        args.output_dir,
        phrasing=phrasing,
        boundary=boundary,
    )


def _default_ood_backend(config: OodEvaluationConfig, models_root: Path) -> GenerationBackend:
    return _ood_backend_for_engine("transformers")(config, models_root)


def _engine_from(args: argparse.Namespace) -> Literal["transformers", "vllm"]:
    """读出 `--engine` 并收窄类型。

    argparse 的 `choices` 只管命令行那一路；库内调用与旧 Namespace 走的是 `getattr`
    默认值那一路，不在这里挡一次就会把任意字符串带进证据的 `inference_engine`。
    """
    value = getattr(args, "engine", "transformers")
    if value == "vllm":
        return "vllm"
    if value == "transformers":
        return "transformers"
    msg = f"未知的推理引擎: {value!r}"
    raise ValueError(msg)


def _hardware_provider_for_engine(engine: str) -> HardwareProvider:
    """vLLM 把模型跑在子进程里，父进程的 torch CUDA 统计要么报错要么恒为 0。

    见 `NvmlHardwareProvider` 的文档：那个 0 会被写进证据的 `peak_memory_bytes`，
    比直接报错更糟——它是一个看起来合法的假数。
    """
    if engine == "vllm":
        from veritool_rl.core.agent.vllm_backend import NvmlHardwareProvider

        return NvmlHardwareProvider()
    return CudaHardwareProvider()


def _ood_backend_for_engine(
    engine: str,
) -> Callable[[OodEvaluationConfig, Path], GenerationBackend]:
    """按引擎选后端。两者都跑 NF4，因此换的只有引擎这一个变量。

    vLLM 分支**不做**模型文件哈希校验：`verify_local_model_files` 是
    `TransformersBackend.from_pretrained` 的一部分，这里显式先调它，
    否则 vLLM 路径会绕过"证据里写的模型就是磁盘上那份"的校验。
    """

    def build(config: OodEvaluationConfig, models_root: Path) -> GenerationBackend:
        model_dir = models_root / config.model.local_dir
        adapter_dir = None if config.adapter is None else str(config.adapter.adapter_dir)
        if engine == "vllm":
            from veritool_rl.core.agent.vllm_backend import VllmBackend

            verify_local_model_files(model_dir, config.model.file_sha256)
            return VllmBackend.from_pretrained(
                str(model_dir),
                adapter_dir,
                revision=config.model.revision,
                settings=config.generation,
            )
        return TransformersBackend.from_pretrained(
            str(model_dir),
            adapter_dir,
            revision=config.model.revision,
            expected_file_sha256=config.model.file_sha256,
            settings=config.generation,
        )

    return build


def _run_ood_evaluate(
    args: argparse.Namespace,
    config: dict[str, Any],
    *,
    backend_factory: Callable[[OodEvaluationConfig, Path], GenerationBackend] | None = None,
    hardware_provider: HardwareProvider | None = None,
    code_commit_factory: Callable[[], str] | None = None,
) -> None:
    """在分布外集合上评测一个模型形态（基座 / base+adapter / 合并版）。

    这条路径**不是**封存 holdout：分布外集合公开、可反复读、可逐类别拆解。
    两者的治理级别不同，因此代码路径也不同——共用的只有环境、verifier 与模型 pin 校验。
    """
    engine = _engine_from(args)
    pipeline = config.get("pipeline")
    is_candidate = pipeline == "ood_candidate"
    _require_config_keys(config, _OOD_EVAL_CANDIDATE_KEYS if is_candidate else _OOD_EVAL_BASE_KEYS)
    bundle = load_bundle(_bundle_dir(config))
    models_root = _project_relative_path(config, "models_root")
    manifest = load_ood_manifest(args.input_dir / "manifest.json")
    ood_config = OodEvaluationConfig(
        model=ModelArtifact(**_config_mapping(config, "model")),
        adapter=AdapterArtifact(**_config_mapping(config, "adapter")) if is_candidate else None,
        generation=GenerationSettings(**_config_mapping(config, "generation")),
        code_commit=(code_commit_factory or _current_code_commit)(),
        dataset_version=manifest.dataset_version,
    )
    evaluate_ood(
        config=ood_config,
        bundle=bundle,
        manifest=manifest,
        build_dir=args.input_dir,
        models_root=models_root,
        output_dir=args.output_dir,
        backend_factory=backend_factory or _ood_backend_for_engine(engine),
        hardware_provider=hardware_provider or _hardware_provider_for_engine(engine),
        inference_engine=engine,
        runtime_env_sha256=current_runtime_env_sha256(),
    )


# ---------------------------------------------------------------------------
# R2 pipeline: formal_freeze (build)
# ---------------------------------------------------------------------------

_FORMAL_FREEZE_KEYS = {"pipeline", "bundle_dir", "dataset_version"}


def _run_formal_freeze(args: argparse.Namespace, config: dict[str, Any]) -> None:
    """从冻结 bundle 生成正式任务集，写私有真值与公开 answer-free manifest。

    绝不读取 `os.environ`：这条流水线只依赖 bundle 文件和 config 里的
    `dataset_version`，与 teacher provider 无关。
    """
    _require_config_keys(config, _FORMAL_FREEZE_KEYS)
    if args.input_dir is not None:
        raise ValueError("formal_freeze 产出私有根目录，不接受 --input_dir")
    bundle_dir = _bundle_dir(config)
    dataset_version = _dataset_version(config)
    bundle = load_bundle(bundle_dir)
    if bundle.bundle.bundle_version == "4.0.0":
        from veritool_rl.retail_ops.domain.formal_tasks import build_v4_task_set

        task_set = build_v4_task_set(dataset_version, args.seed)
    else:
        task_set = build_formal_task_set(dataset_version, args.seed)
    private_root = _r2_private_root(dataset_version)
    write_formal_task_set(task_set, bundle, private_root, args.output_dir)


# ---------------------------------------------------------------------------
# R2 pipeline: teacher_collect (build)
# ---------------------------------------------------------------------------

_TEACHER_COLLECT_KEYS = {
    "pipeline",
    "bundle_dir",
    "public_dir",
    "dataset_version",
    "attempt_id",
    "max_episodes_per_task",
    "max_request_attempts",
}


def _default_teacher_client_factory(route: TeacherRouteSnapshot, api_key: str) -> TeacherClient:
    """生产环境默认工厂：延迟导入 openai SDK，不在导入期发起任何请求。"""
    return OpenAICompatibleTeacherClient.from_route(route, api_key)


def _run_teacher_collect(
    args: argparse.Namespace,
    config: dict[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
    client_factory: Callable[[TeacherRouteSnapshot, str], TeacherClient] | None = None,
) -> None:
    """对已冻结的 train split 逐任务采集 teacher 轨迹，可续采集，写私有证据。

    只有这一条流水线会读取 `TEACHER_LLM_*` 环境变量，且只在全部配置/治理
    校验通过之后才读取一次（通过 `environ` 注入缝，生产默认值是真实
    `os.environ`；`client_factory` 注入缝的生产默认值是 `_default_teacher_client_factory`，
    两者都可以在调用处或本函数单一定义点被测试替换，不需要额外的"测试模式"开关）。
    """
    _require_config_keys(config, _TEACHER_COLLECT_KEYS)
    if args.input_dir is None:
        raise ValueError("teacher_collect 需要 --input_dir 指向 formal_freeze 的私有根目录")

    bundle_dir = _bundle_dir(config)
    public_dir = _project_relative_path(config, "public_dir")
    dataset_version = _dataset_version(config)
    attempt_id = _attempt_id(config)
    max_episodes_per_task = _positive_int(config, "max_episodes_per_task")
    max_request_attempts = _positive_int(config, "max_request_attempts")

    bundle = load_bundle(bundle_dir)
    dataset = load_verified_formal_dataset(public_dir)
    if dataset.receipt.dataset_version != dataset_version:
        raise ValueError(
            "teacher_collect 配置的 dataset_version 与 public_dir 下已发布的正式数据不一致"
        )

    private_root = args.input_dir
    train_records = load_formal_split(dataset, "train", private_root / "train.jsonl")
    manifest_sha256 = _manifest_content_sha256(dataset.train_manifest)

    # 到这里为止全部校验都不依赖环境变量；只有真正要构造 client 时才读取。
    env = environ if environ is not None else os.environ
    route, api_key = load_teacher_route(env)
    factory = client_factory or _default_teacher_client_factory
    client = factory(route, api_key)

    teacher_config = TeacherCollectionConfig(
        dataset_version=dataset_version,
        seed=args.seed,
        bundle_sha256=bundle.bundle_sha256,
        manifest_sha256=manifest_sha256,
        route_sha256=route.route_sha256,
        max_episodes_per_task=max_episodes_per_task,
        max_request_attempts=max_request_attempts,
    )

    def env_factory(task: Any) -> RetailOpsEnv:
        return RetailOpsEnv(task, bundle)

    checkpoint = load_teacher_checkpoint(private_root, attempt_id, teacher_config)
    accepted_ids = set(checkpoint.accepted_task_ids) if checkpoint is not None else set()

    _validate_path_component(attempt_id, label="attempt_id")
    attempt_dir = _resolve_within(private_root, "teacher-collection", attempt_id)
    already_attempted = (
        {path.stem for path in attempt_dir.glob("*.json") if path.name != "checkpoint.json"}
        if attempt_dir.is_dir()
        else set()
    )

    processed = 0
    for record in train_records:
        task_id = record.task.task_id
        if task_id in already_attempted:
            continue
        evidence = collect_teacher_attempt(record, client, env_factory, teacher_config)
        write_teacher_attempt_evidence(evidence, private_root, attempt_id)
        processed += 1
        if evidence.accepted:
            accepted_ids.add(task_id)
        write_teacher_checkpoint(
            TeacherCollectionCheckpoint(
                dataset_version=teacher_config.dataset_version,
                seed=teacher_config.seed,
                bundle_sha256=teacher_config.bundle_sha256,
                manifest_sha256=teacher_config.manifest_sha256,
                route_sha256=teacher_config.route_sha256,
                config_sha256=teacher_config.config_sha256,
                accepted_task_ids=tuple(sorted(accepted_ids)),
            ),
            private_root,
            attempt_id,
        )

    create_output_dir(args.output_dir)
    write_json(
        args.output_dir / "summary.json",
        {
            "dataset_version": dataset_version,
            "attempt_id": attempt_id,
            "train_task_count": len(train_records),
            "processed_this_run": processed,
            "already_attempted_before_this_run": len(already_attempted),
            "total_accepted": len(accepted_ids),
        },
    )


# ---------------------------------------------------------------------------
# R8 pipeline: state_aug_export (build)
# ---------------------------------------------------------------------------

_STATE_AUG_EXPORT_KEYS = {
    "pipeline",
    "bundle_dir",
    "base_attempt_id",
    "attempt_id",
    "max_episodes_per_task",
    "max_request_attempts",
    "sft_paraphrase",
}


def _run_state_aug_export(
    args: argparse.Namespace,
    config: dict[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
    client_factory: Callable[[TeacherRouteSnapshot, str], TeacherClient] | None = None,
) -> None:
    """在**冻结网格之外**的 margin 上补训练素材，与既有导出合并成新的训练集。

    与 `train_export` 分开是刻意的：那一条的产物同时是 provenance，声称"本次导出
    覆盖了哪些冻结任务"，把网格外的新任务塞进去会让那份声称超出冻结契约。
    这里的形状是「读一份已导出的 sft.jsonl 作基底 + 追加增强行 + 写成新导出」，
    两部分的哈希都进公开报告。

    动机与判读见 `docs/POLICY_BOUNDARY.md`。
    """
    from veritool_rl.retail_ops.build.state_augmentation import (
        AugmentationRecord,
        build_augmentation_rows,
        load_persisted_evidence,
        persist_evidence,
        write_state_augmented_export,
    )
    from veritool_rl.retail_ops.domain.state_augmentation_tasks import (
        STATE_AUG_DATASET_VERSION,
        build_state_augmentation_tasks,
    )

    _require_config_keys(config, _STATE_AUG_EXPORT_KEYS)
    if args.input_dir is None:
        raise ValueError("state_aug_export 需要 --input_dir 指向私有根目录")

    bundle = load_bundle(_bundle_dir(config))
    base_attempt_id = _validate_path_component(
        _config_str(config, "base_attempt_id"), label="base_attempt_id"
    )
    attempt_id = _validate_path_component(_attempt_id(config), label="attempt_id")
    max_episodes_per_task = _positive_int(config, "max_episodes_per_task")
    max_request_attempts = _positive_int(config, "max_request_attempts")
    paraphrase = _sft_paraphrase_plan(config, args.input_dir)
    if paraphrase is None:
        raise ValueError(
            "state_aug_export 必须启用 sft_paraphrase：增强行若不走与既有 960 行同一条"
            "措辞路径，表面形式就成了第二个变量"
        )

    tasks = build_state_augmentation_tasks(args.seed)

    def env_factory(task: Any) -> RetailOpsEnv:
        return RetailOpsEnv(task, bundle)

    env = environ if environ is not None else os.environ
    route, api_key = load_teacher_route(env)
    client = (client_factory or _default_teacher_client_factory)(route, api_key)

    teacher_config = TeacherCollectionConfig(
        dataset_version=STATE_AUG_DATASET_VERSION,
        seed=args.seed,
        bundle_sha256=bundle.bundle_sha256,
        manifest_sha256=hashlib.sha256(STATE_AUG_DATASET_VERSION.encode()).hexdigest(),
        route_sha256=route.route_sha256,
        max_episodes_per_task=max_episodes_per_task,
        max_request_attempts=max_request_attempts,
    )

    # 断点续采：teacher 采集是付费动作，已落盘的证据不重采。
    persisted = {
        evidence.task_id: evidence
        for evidence in load_persisted_evidence(args.input_dir, attempt_id)
    }
    evidences: list[TeacherAttemptEvidence] = []
    for task in tasks:
        existing = persisted.get(task.task_id)
        if existing is not None and existing.accepted:
            evidences.append(existing)
            continue
        evidence = collect_teacher_attempt(
            AugmentationRecord.from_task(task), client, env_factory, teacher_config
        )
        persist_evidence(evidence, args.input_dir, attempt_id)
        evidences.append(evidence)

    accepted = sum(1 for evidence in evidences if evidence.accepted)
    print(f"state_aug_export: teacher 接受 {accepted}/{len(tasks)} 条增强任务")

    rows = build_augmentation_rows(tasks, evidences, env_factory, paraphrase)
    report = write_state_augmented_export(
        private_root=args.input_dir,
        public_root=args.output_dir,
        base_attempt_id=base_attempt_id,
        attempt_id=attempt_id,
        tasks=tasks,
        evidences=evidences,
        augmentation_rows=rows,
        paraphrase=paraphrase,
    )
    print(
        f"state_aug_export: 基底 {report.base_row_count} 行 + 增强 "
        f"{report.augmentation_row_count} 行 = {report.total_row_count} 行"
    )


# ---------------------------------------------------------------------------
# R2 pipeline: train_export (build)
# ---------------------------------------------------------------------------

_TRAIN_EXPORT_KEYS = {
    "pipeline",
    "bundle_dir",
    "public_dir",
    "dataset_version",
    "teacher_attempt_id",
    "attempt_id",
    "sft_oversample",
    "sft_terminal_response",
    "sft_system_prompt_sha256",
    "sft_paraphrase",
}


def _run_train_export(args: argparse.Namespace, config: dict[str, Any]) -> None:
    """质量门通过后为全部 240 条 train 任务选定轨迹并导出，绝不读取环境变量。"""
    _require_config_keys(config, _TRAIN_EXPORT_KEYS)
    if args.input_dir is None:
        raise ValueError("train_export 需要 --input_dir 指向 formal_freeze 的私有根目录")

    bundle_dir = _bundle_dir(config)
    public_dir = _project_relative_path(config, "public_dir")
    dataset_version = _dataset_version(config)
    teacher_attempt_id = _config_str(config, "teacher_attempt_id")
    attempt_id = _attempt_id(config)
    sft_oversample = _sft_oversample(config)
    sft_terminal_response = _sft_terminal_response(config)
    sft_system_prompt_sha256 = _sft_system_prompt_sha256(config)
    sft_paraphrase = _sft_paraphrase_plan(config, args.input_dir)

    bundle = load_bundle(bundle_dir)
    dataset = load_verified_formal_dataset(public_dir)
    if dataset.receipt.dataset_version != dataset_version:
        raise ValueError(
            "train_export 配置的 dataset_version 与 public_dir 下已发布的正式数据不一致"
        )

    private_root = args.input_dir
    train_records = load_formal_split(dataset, "train", private_root / "train.jsonl")
    evidences = _load_teacher_attempt_evidences(private_root, teacher_attempt_id)
    scenario_by_task_id = {
        record.task.task_id: record.task.scenario.value for record in train_records
    }

    def env_factory(task: Any) -> RetailOpsEnv:
        return RetailOpsEnv(task, bundle)

    manifest_sha256 = _manifest_content_sha256(dataset.train_manifest)
    teacher_config = TeacherCollectionConfig(
        dataset_version=dataset_version,
        seed=args.seed,
        bundle_sha256=bundle.bundle_sha256,
        manifest_sha256=manifest_sha256,
        route_sha256=_teacher_evidence_route_sha256(evidences),
    )

    report, selections, train_rows, sft_rows = export_formal_train(
        train_records,
        evidences,
        env_factory,
        teacher_config,
        scenario_by_task_id,
        args.seed,
        sft_oversample=sft_oversample,
        sft_terminal_response=sft_terminal_response,
        sft_system_prompt_sha256=sft_system_prompt_sha256,
        sft_paraphrase=sft_paraphrase,
    )

    create_output_dir(args.output_dir)
    write_formal_train_export(
        private_root=private_root,
        public_root=args.output_dir,
        attempt_id=attempt_id,
        dataset_version=dataset_version,
        report=report,
        selections=selections,
        train_rows=train_rows,
        sft_rows=sft_rows,
        sft_oversample=sft_oversample,
        sft_terminal_response=sft_terminal_response,
        sft_system_prompt_sha256=sft_system_prompt_sha256,
        sft_paraphrase=sft_paraphrase,
    )


def _load_teacher_attempt_evidences(
    private_root: Path, attempt_id: str
) -> list[TeacherAttemptEvidence]:
    _validate_path_component(attempt_id, label="teacher_attempt_id")
    attempt_dir = _resolve_within(private_root, "teacher-collection", attempt_id)
    if not attempt_dir.is_dir():
        return []
    evidences: list[TeacherAttemptEvidence] = []
    for path in sorted(attempt_dir.glob("*.json")):
        if path.name == "checkpoint.json":
            continue
        evidences.append(
            TeacherAttemptEvidence.model_validate_json(path.read_text(encoding="utf-8"))
        )
    return evidences


def _teacher_evidence_route_sha256(evidences: Sequence[TeacherAttemptEvidence]) -> str:
    """从已采集证据推导 route_sha256，不读取环境变量。

    `export_formal_train` 会核对证据的 dataset_version/bundle/manifest 绑定，但
    不核对 `route_sha256`——那在这里是同义反复，因为本函数正是从证据自身推导
    出该值的。真正的保护在这一步：同一次导出引用的证据不允许混用不同 route。
    """
    distinct = sorted({evidence.route_sha256 for evidence in evidences})
    if not distinct:
        return hashlib.sha256(b"no-teacher-evidence").hexdigest()
    if len(distinct) > 1:
        raise ValueError("teacher 证据混合了多个 route_sha256，拒绝导出")
    return distinct[0]


# ---------------------------------------------------------------------------
# R2 pipeline: formal_dev_base (evaluate)
# ---------------------------------------------------------------------------

_FORMAL_DEV_BASE_KEYS = {
    "pipeline",
    "bundle_dir",
    "dataset_version",
    "dev_manifest_path",
    "models_root",
    "model",
    "generation",
    "attempt_id",
}


def _default_generation_backend(
    config: BaseEvaluationConfig, models_root: Path
) -> GenerationBackend:
    """生产环境默认工厂：真实单卡 4-bit NF4 Transformers 后端，torch 只在方法内部导入。"""
    return _generation_backend_for_engine("transformers")(config, models_root)


def _generation_backend_for_engine(
    engine: str,
) -> Callable[[BaseEvaluationConfig, Path], GenerationBackend]:
    """dev base 通道的引擎选路；与 `_ood_backend_for_engine` 同一套规则。

    **两条通道必须都接上**：只接一条的话，另一条会**静默忽略** `--engine` 并回落到
    transformers，产出的证据看起来完全正常却根本不是那个引擎跑的。
    """

    def build(config: BaseEvaluationConfig, models_root: Path) -> GenerationBackend:
        model_dir = models_root / config.model.local_dir
        if engine == "vllm":
            from veritool_rl.core.agent.vllm_backend import VllmBackend

            # vLLM 不走 TransformersBackend.from_pretrained，模型文件校验要显式补。
            verify_local_model_files(model_dir, config.model.file_sha256)
            return VllmBackend.from_pretrained(
                str(model_dir), None, revision=config.model.revision, settings=config.generation
            )
        return TransformersBackend.from_pretrained(
            str(model_dir),
            None,
            revision=config.model.revision,
            expected_file_sha256=config.model.file_sha256,
            settings=config.generation,
        )

    return build


def _default_hardware_provider() -> HardwareProvider:
    """生产环境默认工厂：真实单卡 CUDA 测量，torch 只在方法内部导入。"""
    return CudaHardwareProvider()


def _run_formal_dev_base(
    args: argparse.Namespace,
    config: dict[str, Any],
    *,
    backend_factory: Callable[[BaseEvaluationConfig, Path], GenerationBackend] | None = None,
    hardware_provider_factory: Callable[[], HardwareProvider] | None = None,
    code_commit_factory: Callable[[], str] | None = None,
) -> None:
    """在 60 条已验证 formal dev 任务上跑一次冻结 base 评测，绝不读取环境变量。

    `backend_factory`/`hardware_provider_factory`/`code_commit_factory` 是 CPU
    测试的注入缝：直接调用本函数并传入 fake 实现即可绕开真实模型/CUDA/仓库
    git 状态；`main()` 走的默认路径使用模块级 `_default_generation_backend`/
    `_default_hardware_provider`/`_current_code_commit`（后者会拒绝脏工作树）。
    """
    _require_config_keys(config, _FORMAL_DEV_BASE_KEYS)
    if args.seed != 0:
        raise ValueError("formal_dev_base 冻结 seed=0，收到 --seed 与之不一致")

    bundle_dir = _bundle_dir(config)
    dataset_version = _dataset_version(config)
    dev_manifest_path = _project_relative_path(config, "dev_manifest_path")
    models_root = _project_relative_path(config, "models_root")
    attempt_id = _attempt_id(config)
    model_value = _config_mapping(config, "model")
    generation_value = _config_mapping(config, "generation")

    bundle = load_bundle(bundle_dir)
    # 和 teacher_collect/train_export 一样走统一的公开数据集校验：只有跨 manifest
    # 的 `assert_formal_split_isolation` 能发现一份"单文件自洽、内容却与封存
    # holdout 重叠"的 dev manifest（content/derivation 指纹刻意不含 split/task_id）。
    dataset = load_verified_formal_dataset(dev_manifest_path.parent)
    declared_manifest = load_formal_task_manifest(dev_manifest_path)
    if declared_manifest != dataset.dev_manifest:
        raise ValueError("formal_dev_base 的 dev manifest 不是 dataset.json 绑定的那一份")
    public_manifest = dataset.dev_manifest
    if public_manifest.dataset_version != dataset_version:
        raise ValueError("formal_dev_base 配置的 dataset_version 与公开 dev manifest 不一致")

    private_root = args.input_dir
    records = load_verified_formal_dev(private_root, public_manifest)

    model_artifact = ModelArtifact(**model_value)
    generation_settings = GenerationSettings(**generation_value)
    base_config = BaseEvaluationConfig(
        dataset_version=dataset_version,
        model=model_artifact,
        generation=generation_settings,
        code_commit=(code_commit_factory or _current_code_commit)(),
        uv_lock_sha256=_current_uv_lock_sha256(),
    )

    engine = _engine_from(args)
    backend = (backend_factory or _generation_backend_for_engine(engine))(base_config, models_root)
    hardware_provider = (
        hardware_provider_factory or (lambda: _hardware_provider_for_engine(engine))
    )()

    create_output_dir(args.output_dir)
    public_report_path = args.output_dir / "base-report.json"

    evaluate_formal_dev_base(
        records,
        public_manifest,
        backend,
        base_config,
        bundle=bundle,
        models_root=models_root,
        private_root=private_root,
        attempt_id=attempt_id,
        public_report_path=public_report_path,
        hardware_provider=hardware_provider,
        # 证据必须说得出它跑在哪个引擎、哪个环境：`uv_lock_sha256` 只哈希仓库里的
        # `uv.lock` 文件，换一个 venv 跑它发现不了。
        inference_engine=engine,
        runtime_env_sha256=current_runtime_env_sha256(),
    )


# ---------------------------------------------------------------------------
# R3 pipeline: formal_dev_candidate (evaluate)
# ---------------------------------------------------------------------------

_FORMAL_DEV_CANDIDATE_KEYS = {
    "pipeline",
    "bundle_dir",
    "dataset_version",
    "dev_manifest_path",
    "models_root",
    "model",
    "adapter",
    "generation",
    "attempt_id",
}


def _default_candidate_backend(
    config: CandidateEvaluationConfig, models_root: Path
) -> GenerationBackend:
    """生产环境默认工厂：真实 4-bit NF4 后端并挂载锁定的 adapter 目录。"""
    model_dir = models_root / config.model.local_dir
    return TransformersBackend.from_pretrained(
        str(model_dir),
        str(config.adapter.adapter_dir),
        revision=config.model.revision,
        expected_file_sha256=config.model.file_sha256,
        settings=config.generation,
    )


def _run_formal_dev_candidate(
    args: argparse.Namespace,
    config: dict[str, Any],
    *,
    backend_factory: Callable[[CandidateEvaluationConfig, Path], GenerationBackend] | None = None,
    hardware_provider_factory: Callable[[], HardwareProvider] | None = None,
    code_commit_factory: Callable[[], str] | None = None,
) -> None:
    """在同一 60 条 dev 上跑候选（base+adapter），与 base 逐字段同契约，绝不读环境变量。

    这条流水线刻意与 `_run_formal_dev_base` 保持同样的 dataset/manifest 校验顺序：
    只有两次运行经过同一套守卫，`compare_dev_runs` 的 delta 才能归因于 adapter。
    """
    _require_config_keys(config, _FORMAL_DEV_CANDIDATE_KEYS)
    if args.seed != 0:
        raise ValueError("formal_dev_candidate 冻结 seed=0，收到 --seed 与之不一致")

    bundle_dir = _bundle_dir(config)
    dataset_version = _dataset_version(config)
    dev_manifest_path = _project_relative_path(config, "dev_manifest_path")
    models_root = _project_relative_path(config, "models_root")
    attempt_id = _attempt_id(config)
    model_value = _config_mapping(config, "model")
    adapter_value = _config_mapping(config, "adapter")
    generation_value = _config_mapping(config, "generation")

    bundle = load_bundle(bundle_dir)
    dataset = load_verified_formal_dataset(dev_manifest_path.parent)
    declared_manifest = load_formal_task_manifest(dev_manifest_path)
    if declared_manifest != dataset.dev_manifest:
        raise ValueError("formal_dev_candidate 的 dev manifest 不是 dataset.json 绑定的那一份")
    public_manifest = dataset.dev_manifest
    if public_manifest.dataset_version != dataset_version:
        raise ValueError("formal_dev_candidate 配置的 dataset_version 与公开 dev manifest 不一致")

    private_root = args.input_dir
    records = load_verified_formal_dev(private_root, public_manifest)

    candidate_config = CandidateEvaluationConfig(
        dataset_version=dataset_version,
        model=ModelArtifact(**model_value),
        adapter=AdapterArtifact(**adapter_value),
        generation=GenerationSettings(**generation_value),
        code_commit=(code_commit_factory or _current_code_commit)(),
        uv_lock_sha256=_current_uv_lock_sha256(),
    )

    backend = (backend_factory or _default_candidate_backend)(candidate_config, models_root)
    hardware_provider = (hardware_provider_factory or _default_hardware_provider)()
    engine = _engine_from(args)

    create_output_dir(args.output_dir)
    evaluate_formal_dev_candidate(
        records,
        public_manifest,
        backend,
        candidate_config,
        bundle=bundle,
        models_root=models_root,
        private_root=private_root,
        attempt_id=attempt_id,
        public_report_path=args.output_dir / "candidate-report.json",
        hardware_provider=hardware_provider,
        # R8 第二轮审查 A-3：dev 候选路径与 base 同构——证据必须说得出它跑在
        # 哪个引擎、哪个环境，否则 dev base 在 venv-A 跑、dev candidate 在 venv-B
        # 跑，证据链发现不了。
        inference_engine=engine,
        runtime_env_sha256=current_runtime_env_sha256(),
    )


# ---------------------------------------------------------------------------
# R3 pipeline: formal_holdout_base / formal_holdout_candidate (evaluate)
# ---------------------------------------------------------------------------

#: 两条 holdout 流水线刻意分开命名：base/candidate 的区分是安全关键的，让配置
#: 文件本身声明意图，比"有没有写 adapter 这个 key"更难被误配置。
_FORMAL_HOLDOUT_PIPELINES = (
    "formal_holdout_base",
    "formal_holdout_candidate",
    "formal_holdout_merged_candidate",
)

_FORMAL_HOLDOUT_BASE_KEYS = {
    "pipeline",
    "bundle_dir",
    "dataset_version",
    "holdout_receipt_path",
    "models_root",
    "model",
    "generation",
    "attempt_id",
}
_FORMAL_HOLDOUT_CANDIDATE_KEYS = _FORMAL_HOLDOUT_BASE_KEYS | {"adapter"}
#: 合并形态的候选没有 adapter，取而代之的是**可复算的血统**。
#: `merged_from` 里的 `merged_revision` 必须等于由「基座 revision + adapter 逐文件
#: 哈希」导出的派生标识，配对校验据此认证它确实来自那对输入。
_FORMAL_HOLDOUT_MERGED_KEYS = _FORMAL_HOLDOUT_BASE_KEYS | {"merged_from"}

#: `authorize_formal_holdout` 要求逻辑路径精确等于这个前缀下的冻结文件。
_PRIVATE_R2_LOGICAL_ROOT = Path("data/private/retail_ops/v1/r2")
_HOLDOUT_ARTIFACT_NAME = "holdout.jsonl"


def _default_sealed_backend(config: SealedEvaluationConfig, models_root: Path) -> GenerationBackend:
    """生产环境默认工厂：真实 4-bit NF4 后端，候选侧另挂锁定的 adapter 目录。"""
    model_dir = models_root / config.model.local_dir
    adapter_dir = None if config.adapter is None else str(config.adapter.adapter_dir)
    return TransformersBackend.from_pretrained(
        str(model_dir),
        adapter_dir,
        revision=config.model.revision,
        expected_file_sha256=config.model.file_sha256,
        settings=config.generation,
    )


def _run_formal_holdout(
    args: argparse.Namespace,
    config: dict[str, Any],
    *,
    backend_factory: Callable[[SealedEvaluationConfig, Path], GenerationBackend] | None = None,
    hardware_provider_factory: Callable[[], HardwareProvider] | None = None,
    code_commit_factory: Callable[[], str] | None = None,
) -> None:
    """在封存的正式 120 条 holdout 上跑一次 release 目的的评测。

    这条流水线是 SPEC §6 发布门禁**唯一**的证据来源。它绝不接受开发用途：
    `authorize_formal_holdout` 只签发 `EvidencePurpose.RELEASE` 的能力对象，
    逻辑路径必须精确等于冻结数据版本的 `holdout.jsonl`，两项都不在这里放宽。
    完整轨迹只写私有 attempt 目录，公开侧只有 allowlist 聚合报告。
    """
    pipeline = config.get("pipeline")
    is_candidate = pipeline == "formal_holdout_candidate"
    is_merged = pipeline == "formal_holdout_merged_candidate"
    if is_candidate:
        expected_keys = _FORMAL_HOLDOUT_CANDIDATE_KEYS
    elif is_merged:
        expected_keys = _FORMAL_HOLDOUT_MERGED_KEYS
    else:
        expected_keys = _FORMAL_HOLDOUT_BASE_KEYS
    _require_config_keys(config, expected_keys)
    if args.seed != 0:
        raise ValueError(f"{pipeline} 冻结 seed=0，收到 --seed 与之不一致")

    bundle_dir = _bundle_dir(config)
    dataset_version = _dataset_version(config)
    receipt_path = _project_relative_path(config, "holdout_receipt_path")
    models_root = _project_relative_path(config, "models_root")
    attempt_id = _attempt_id(config)
    model_value = _config_mapping(config, "model")
    generation_value = _config_mapping(config, "generation")

    bundle = load_bundle(bundle_dir)
    dataset = load_verified_formal_dataset(receipt_path.parent)
    if dataset.receipt.dataset_version != dataset_version:
        raise ValueError(f"{pipeline} 配置的 dataset_version 与公开 dataset receipt 不一致")
    declared_receipt = load_formal_holdout_receipt(receipt_path)
    if declared_receipt != dataset.holdout_receipt:
        raise ValueError(f"{pipeline} 的 holdout receipt 不是 dataset.json 绑定的那一份")

    sealed_config = SealedEvaluationConfig(
        dataset_version=dataset_version,
        model=ModelArtifact(**model_value),
        adapter=AdapterArtifact(**_config_mapping(config, "adapter")) if is_candidate else None,
        merged_from=(
            MergedProvenance(**_config_mapping(config, "merged_from")) if is_merged else None
        ),
        generation=GenerationSettings(**generation_value),
        code_commit=(code_commit_factory or _current_code_commit)(),
        uv_lock_sha256=_current_uv_lock_sha256(),
    )

    private_root = args.input_dir
    authorization = authorize_formal_holdout(
        dataset,
        private_root / _HOLDOUT_ARTIFACT_NAME,
        _PRIVATE_R2_LOGICAL_ROOT / dataset_version / _HOLDOUT_ARTIFACT_NAME,
        EvidencePurpose.RELEASE,
        trusted_private_root=private_root,
    )

    backend = (backend_factory or _default_sealed_backend)(sealed_config, models_root)
    hardware_provider = (hardware_provider_factory or _default_hardware_provider)()

    create_output_dir(args.output_dir)
    evaluate_authorized_holdout(
        authorization,
        bundle,
        backend,
        sealed_config,
        models_root=models_root,
        attempt_id=attempt_id,
        public_report_path=args.output_dir / "sealed-report.json",
        hardware_provider=hardware_provider,
    )


# ---------------------------------------------------------------------------
# R3 pipeline: dev_sft_export (build)
# ---------------------------------------------------------------------------

_DEV_SFT_EXPORT_KEYS = {
    "pipeline",
    "bundle_dir",
    "dataset_version",
    "dev_manifest_path",
    "attempt_id",
}


def _run_dev_sft_export(args: argparse.Namespace, config: dict[str, Any]) -> None:
    """用 internal reference（Oracle）为全部 60 条 dev 任务导出训练侧 eval 数据。

    绝不读取环境变量、绝不构造 teacher client：`build_dev_sft_rows` 的签名里
    根本没有 client 参数。dev 记录经 `load_verified_formal_dev`（purpose 与
    split 在触碰文件系统之前判定）加载，因此这条通道无法被指向 holdout。
    """
    _require_config_keys(config, _DEV_SFT_EXPORT_KEYS)
    if args.input_dir is None:
        raise ValueError("dev_sft_export 需要 --input_dir 指向 formal_freeze 的私有根目录")

    bundle_dir = _bundle_dir(config)
    dataset_version = _dataset_version(config)
    dev_manifest_path = _project_relative_path(config, "dev_manifest_path")
    attempt_id = _attempt_id(config)

    bundle = load_bundle(bundle_dir)
    # 与 formal_dev_base 同一套统一校验：只有跨 manifest 的五维隔离断言能发现
    # 一份"单文件自洽、内容却与封存 holdout 重叠"的 dev manifest。
    dataset = load_verified_formal_dataset(dev_manifest_path.parent)
    declared_manifest = load_formal_task_manifest(dev_manifest_path)
    if declared_manifest != dataset.dev_manifest:
        raise ValueError("dev_sft_export 的 dev manifest 不是 dataset.json 绑定的那一份")
    public_manifest = dataset.dev_manifest
    if public_manifest.dataset_version != dataset_version:
        raise ValueError("dev_sft_export 配置的 dataset_version 与公开 dev manifest 不一致")

    private_root = args.input_dir
    records = load_verified_formal_dev(private_root, public_manifest)

    def env_factory(task: Any) -> RetailOpsEnv:
        return RetailOpsEnv(task, bundle)

    rows = build_dev_sft_rows(records, env_factory, args.seed)

    create_output_dir(args.output_dir)
    write_dev_sft_export(
        private_root=private_root,
        public_root=args.output_dir,
        attempt_id=attempt_id,
        dataset_version=dataset_version,
        rows=rows,
    )


# ---------------------------------------------------------------------------
# R3 pipeline: sft (build)
# ---------------------------------------------------------------------------

_SFT_KEYS = {"pipeline", "model", "lora", "data", "training"}
_SFT_DATA_REQUIRED_KEYS = {"train_relpath", "eval_relpath"}
_SFT_DATA_OPTIONAL_KEYS = {"train_limit", "eval_limit"}

_default_sft_trainer = run_sft


def _run_sft(
    args: argparse.Namespace,
    config: dict[str, Any],
    *,
    trainer_factory: Callable[[dict[str, Any], int, Path], dict[str, Any]] | None = None,
) -> None:
    """执行一次单卡 QLoRA-SFT；训练数据路径由 `--input_dir` 在运行时提供。

    已提交的 config 只写私有根内的相对路径（`train_relpath`/`eval_relpath`），
    与 R2 的 teacher/export 流水线保持同一约定：私有根前缀绝不进入版本控制的
    配置文件，运行时才由 `--input_dir` 拼接并做逃逸校验。

    `trainer_factory` 是 CPU 测试的注入缝（同 `backend_factory` 那一套）；
    `main()` 走的默认路径是模块级 `_default_sft_trainer`，它就是真实的
    `training.sft.run_sft`——模型逐文件哈希校验、不可覆盖输出目录和有限 loss
    检查都在那里，本函数不复制也不放宽任何一条。
    """
    _require_config_keys(config, _SFT_KEYS)
    if args.input_dir is None:
        raise ValueError("sft 需要 --input_dir 指向已导出训练数据的私有根目录")

    model_value = _config_mapping(config, "model")
    lora_value = _config_mapping(config, "lora")
    data_value = _config_mapping(config, "data")
    training_value = _config_mapping(config, "training")

    missing = _SFT_DATA_REQUIRED_KEYS - set(data_value)
    unknown = set(data_value) - _SFT_DATA_REQUIRED_KEYS - _SFT_DATA_OPTIONAL_KEYS
    if missing or unknown:
        raise ValueError(
            f"data 字段不符合 sft 契约: missing={sorted(missing)}, unknown={sorted(unknown)}"
        )

    private_root = args.input_dir
    resolved_data: dict[str, Any] = {
        "train_path": str(_private_data_path(data_value, "train_relpath", private_root)),
        "eval_path": str(_private_data_path(data_value, "eval_relpath", private_root)),
    }
    for key in sorted(_SFT_DATA_OPTIONAL_KEYS):
        if key in data_value:
            resolved_data[key] = data_value[key]

    sft_config = {
        "model": model_value,
        "lora": lora_value,
        "data": resolved_data,
        "training": training_value,
    }
    (trainer_factory or _default_sft_trainer)(sft_config, args.seed, args.output_dir)


def _private_data_path(data: dict[str, Any], key: str, private_root: Path) -> Path:
    """把私有根内的相对路径逐段校验后拼接，拒绝穿越、绝对路径与符号链接逃逸。"""
    value = _config_str(data, key)
    parts = value.split("/")
    for part in parts:
        _validate_path_component(part, label=f"data.{key} 路径分量")
    return _resolve_within(private_root, *parts)


# ---------------------------------------------------------------------------
# 共享辅助函数
# ---------------------------------------------------------------------------


def _bundle_dir(config: dict[str, Any]) -> Path:
    return _project_relative_path(config, "bundle_dir")


def _project_relative_path(config: dict[str, Any], key: str) -> Path:
    value = config.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} 必须是字符串")
    path = Path(value)
    validate_project_relative_path(path, key)
    return path


def _dataset_version(config: dict[str, Any]) -> str:
    return _config_str(config, "dataset_version")


def _config_str(config: dict[str, Any], key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} 必须是非空字符串")
    return value


def _config_mapping(config: dict[str, Any], key: str) -> dict[str, Any]:
    value = config.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{key} 必须是 mapping")
    return value


def _sft_oversample(config: dict[str, Any]) -> dict[str, int]:
    """读取按场景的 sft 重复采样因子；键必须存在，空 mapping 表示不重采样。

    该键是**必填**的：给它一个默认值会让"忘了写"和"故意不重采样"产出同一份数据，
    事后无法从配置文件本身分辨这一轮实验是否按预期设置过。取值的语义校验
    （未知场景名、非正因子）由 `export_formal_train` 统一负责，这里只做形状检查，
    避免同一条规则出现两份实现。
    """
    value = _config_mapping(config, "sft_oversample")
    factors: dict[str, int] = {}
    for scenario, factor in value.items():
        if not isinstance(scenario, str):
            raise ValueError("sft_oversample 的键必须是场景名字符串")
        if isinstance(factor, bool) or not isinstance(factor, int):
            raise ValueError(f"sft_oversample 的重复因子必须是整数: {scenario}={factor!r}")
        factors[scenario] = factor
    return factors


def _sft_terminal_response(config: dict[str, Any]) -> list[str]:
    """读取要追加终局回复的场景名列表；键必须存在，空列表表示不追加。

    与 `sft_oversample` 同一条理由：有默认值时"忘了写"和"故意不启用"产出同一份
    数据。场景名是否有效由 `export_formal_train` 统一校验，这里只做形状检查。
    """
    value = config.get("sft_terminal_response")
    if not isinstance(value, list):
        raise ValueError("sft_terminal_response 必须是场景名列表（不启用时写空列表）")
    scenarios: list[str] = []
    for scenario in value:
        if not isinstance(scenario, str):
            raise ValueError(f"sft_terminal_response 的元素必须是场景名字符串: {scenario!r}")
        scenarios.append(scenario)
    return scenarios


def _sft_system_prompt_sha256(config: dict[str, Any]) -> str | None:
    """读取 system 改写声明：64 位 hex 表示改写，`null` 表示沿用轨迹里的 prompt。

    这个键刻意不是布尔值。teacher 证据的 `trajectory.metadata["system_prompt"]` 是
    采集当时持久化的，改 `runner.SYSTEM_PROMPT` 不会追溯改写它。布尔值下
    "配置写了 true 但常量忘了改" 会产出一份与未改写逐字节相同的训练集且不报错——
    实验变量没生效而产物看起来完全正常。声明期望哈希，让这种静默失效变成硬错误
    （实际比对在 `export_formal_train` 里做，那里能读到当前常量）。
    """
    value = config.get("sft_system_prompt_sha256")
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("sft_system_prompt_sha256 必须是 64 位 SHA-256 十六进制串或 null")
    if any(char not in "0123456789abcdef" for char in value):
        raise ValueError("sft_system_prompt_sha256 必须是小写十六进制")
    return value


def _ood_phrasing_spec(config: dict[str, Any], private_root: Path | None) -> OodPhrasingSpec | None:
    """读取 OOD v2 的措辞来源。`null` 表示走 v1（作者手写模板库）。

    `partition` 必须显式写出来，且只能是两个**评测**分片之一：
    拿 `train_aug` 当评测集，就是在测模型有没有背下训练数据。

    `dataset_version` 同样必填、同样不给默认值。给默认值的话，第二份措辞池会静默挂上
    第一份的版本号，而产物看起来完全正常——两批内容不同的评测集因此在同一张表里
    被当成同一个数据集，配对前提当场失效。这与外部审阅在 v1/v2 上抓到的是同一类错误。
    """
    value = config.get("phrasing")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("phrasing 必须是 mapping 或 null")
    missing = {"bank_relpath", "bank_sha256", "partition", "dataset_version"} - set(value)
    if missing:
        raise ValueError(f"phrasing 缺少必填键: {sorted(missing)}")
    partition = value["partition"]
    if partition not in ("ood_dev", "ood_sealed"):
        raise ValueError(
            f"OOD 评测集只能用 ood_dev / ood_sealed 分片，收到 {partition!r}——"
            f"用 train_aug 当评测集测的是有没有背下训练数据"
        )
    if private_root is None:
        raise ValueError("phrasing 非 null 时必须给 --input_dir 指向私有根目录")
    bank_relpath = value["bank_relpath"]
    declared = value["bank_sha256"]
    if not isinstance(bank_relpath, str) or not bank_relpath:
        raise ValueError("phrasing.bank_relpath 必须是非空字符串")
    if not isinstance(declared, str) or len(declared) != 64:
        raise ValueError("phrasing.bank_sha256 必须是 64 位 SHA-256 十六进制串")
    validate_project_relative_path(bank_relpath, "phrasing.bank_relpath")
    records = load_phrasing_bank(private_root / bank_relpath)
    assert_partitions_are_disjoint(records)
    actual = bank_sha256(records)
    if actual != declared:
        raise ValueError(f"措辞池哈希与配置声明不一致: declared={declared}, actual={actual}")
    dataset_version = value["dataset_version"]
    if not isinstance(dataset_version, str) or not dataset_version:
        raise ValueError("phrasing.dataset_version 必须是非空字符串")
    return OodPhrasingSpec(
        index=intent_index(records, partition),
        partition=partition,
        bank_sha256=actual,
        dataset_version=dataset_version,
    )


def _sft_paraphrase_plan(config: dict[str, Any], private_root: Path) -> ParaphrasePlan | None:
    """读取 R6 的措辞增强声明。`null` 表示不做增强。

    三个键都必填而不是给默认值：`bank_relpath` 指哪份池子、`bank_sha256` 声明期望内容、
    `per_task` 每条任务改写几次。哈希是**声明**而不是读出来的实测值——
    与 `sft_system_prompt_sha256` 同一个理由：换了池子却忘了改配置，
    会静默产出另一份训练集，而产物看起来完全正常。
    """
    value = config.get("sft_paraphrase")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("sft_paraphrase 必须是 mapping 或 null")
    missing = {"bank_relpath", "bank_sha256", "per_task"} - set(value)
    if missing:
        raise ValueError(f"sft_paraphrase 缺少必填键: {sorted(missing)}")
    bank_relpath = value["bank_relpath"]
    if not isinstance(bank_relpath, str) or not bank_relpath:
        raise ValueError("sft_paraphrase.bank_relpath 必须是非空字符串")
    declared = value["bank_sha256"]
    if not isinstance(declared, str) or len(declared) != 64:
        raise ValueError("sft_paraphrase.bank_sha256 必须是 64 位 SHA-256 十六进制串")
    per_task = value["per_task"]
    if not isinstance(per_task, int) or isinstance(per_task, bool) or per_task < 1:
        raise ValueError("sft_paraphrase.per_task 必须是 >= 1 的整数")
    validate_project_relative_path(bank_relpath, "sft_paraphrase.bank_relpath")
    return load_paraphrase_plan(
        private_root / bank_relpath, declared_sha256=declared, per_task=per_task
    )


def _positive_int(config: dict[str, Any], key: str) -> int:
    value = config.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{key} 必须是正整数")
    return value


def _attempt_id(config: dict[str, Any]) -> str:
    return _config_str(config, "attempt_id")


def _r2_private_root(dataset_version: str) -> Path:
    """在受信的 R2 私有根目录下按 `dataset_version` 拼接子目录，拒绝路径穿越。

    `dataset_version` 来自已提交的 config 文件，不是硬编码常量；下游
    `write_formal_task_set` 恰好也会拒绝非冻结 `dataset_version`，但这条 CLI
    路径本身不能依赖调用顺序里另一个函数的校验时机——必须自己先做路径安全
    校验，再拼接受信根目录下的路径。
    """
    _validate_path_component(dataset_version, label="dataset_version")
    return _resolve_within(_R2_PRIVATE_ROOT, dataset_version)


def _manifest_content_sha256(manifest: FormalTaskManifest) -> str:
    return hashlib.sha256(
        canonical_json(manifest.model_dump(mode="json")).encode("utf-8")
    ).hexdigest()


def _repo_root() -> Path:
    """定位本包安装所在的仓库根目录，与调用方 CWD 无关。"""
    return Path(__file__).resolve().parents[2]


def _current_code_commit() -> str:
    """返回 HEAD commit，并且只在工作树完全干净时才允许盖这个章。

    脏工作树上盖出的 `code_commit` 会让证据声称跑了并没有真的跑过的代码，
    下游"任何相关提交之后的运行一律作废"的判定也就失去依据。这里按项目
    一贯的 fail-closed 约定直接报错并列出脏路径，不做静默降级（例如附加
    `-dirty` 后缀），因为 `BaseEvaluationConfig.code_commit` 是严格 40 位
    十六进制，任何降级表示都只会在更远的地方以更难解释的形式失败。

    未跟踪文件同样算脏：包内新增一个未提交的 .py 就足以改变实际运行行为。
    每个 git 调用都带 timeout，卡死的 git 进程不能无限期挂住 CLI。
    """
    root = _repo_root()
    dirty = _run_readonly_git(root, "status", "--porcelain").strip()
    if dirty:
        raise ValueError(f"工作树不干净，拒绝为本次运行盖 code_commit：\n{dirty}")
    return _run_readonly_git(root, "rev-parse", "HEAD").strip()


def _run_readonly_git(root: Path, *args: str) -> str:
    """在仓库根跑一条只读 git 命令，必有超时上界，失败一律转成可读错误。

    `subprocess.CalledProcessError` 的字符串形式不含 stderr，而这条路径最常见的
    失败（不是 git 仓库、dubious ownership、HEAD 不存在）全部只在 stderr 里说得
    清楚；直接抛裸异常会让远程运行的排障成本高得没有必要。
    """
    command = ["git", "-C", str(root), *args]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        msg = f"git {' '.join(args)} 超过 {_GIT_TIMEOUT_SECONDS} 秒未返回: {root}"
        raise ValueError(msg) from error
    except subprocess.CalledProcessError as error:
        msg = f"git {' '.join(args)} 失败（{root}）: {(error.stderr or '').strip()}"
        raise ValueError(msg) from error
    return result.stdout


def _current_uv_lock_sha256() -> str:
    return sha256_file(_repo_root() / "uv.lock")


def _validate_path_component(value: str, *, label: str) -> str:
    """拒绝空值、`.`/`..` 和任何非白名单字符——杜绝路径穿越和分隔符注入。"""
    if not value or value in {".", ".."} or _SAFE_COMPONENT_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} 必须是安全的单一路径片段: {value!r}")
    return value


def _resolve_within(root: Path, *parts: str) -> Path:
    """在已建立的受信根目录下逐段拼接，并核对结果确实落在该根之内。"""
    root_resolved = root.resolve()
    target = root
    for part in parts:
        target = target / part
    target_resolved = target.resolve()
    if target_resolved != root_resolved and root_resolved not in target_resolved.parents:
        raise ValueError(f"目标路径逃逸出受信根目录: {target}")
    return target


def _require_config_keys(config: dict[str, Any], expected: set[str]) -> None:
    if set(config) != expected:
        raise ValueError(
            f"配置字段不符合命令契约: expected={sorted(expected)}, actual={sorted(config)}"
        )


if (
    __name__ == "__main__"
):  # pragma: no cover - 由 tests/test_product_cli_entrypoint.py 以子进程覆盖
    # 没有这个守卫时，`python -m veritool_rl.product_cli` 会**静默退出 0**：
    # 模块被导入、parser 被定义、然后什么也不发生。文档里的调用方式一直是
    # console script `.venv/bin/retail-agent-ops`，所以这不是回归；但一个能跑、
    # 不报错、什么都不做的入口，对任何按直觉试它的人都是陷阱。
    raise SystemExit(main())
