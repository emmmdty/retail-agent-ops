"""RetailAgentOps 稳定 build/evaluate/release/serve 产品命令面。

R1 的四个命令行为完全保留：config 没有 `pipeline` 字段时，`build`/`evaluate`
逐字节走原有的精确 key 集合路径。R2 在 `build`/`evaluate` 之上新增按
`pipeline` 分发的四条流水线（`formal_freeze`/`teacher_collect`/`train_export`/
`formal_dev_base`），`release`/`serve` 不新增任何 R2 路径。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import uvicorn

from veritool_rl.agent.qwen import (
    CudaHardwareProvider,
    GenerationBackend,
    GenerationSettings,
    HardwareProvider,
    TransformersBackend,
)
from veritool_rl.artifacts import canonical_json, create_output_dir, sha256_file, write_json
from veritool_rl.cli import load_config
from veritool_rl.paths import validate_project_relative_path
from veritool_rl.retail_ops.base_evaluation import (
    BaseEvaluationConfig,
    ModelArtifact,
    evaluate_formal_dev_base,
    load_verified_formal_dev,
)
from veritool_rl.retail_ops.bundle import load_bundle
from veritool_rl.retail_ops.candidate_evaluation import (
    AdapterArtifact,
    CandidateEvaluationConfig,
    evaluate_formal_dev_candidate,
)
from veritool_rl.retail_ops.dev_sft_export import build_dev_sft_rows, write_dev_sft_export
from veritool_rl.retail_ops.environment import RetailOpsEnv
from veritool_rl.retail_ops.evaluation import (
    EvaluationMode,
    evaluate_retail_ops,
    load_run_evidence,
)
from veritool_rl.retail_ops.formal_manifests import (
    FormalTaskManifest,
    load_formal_split,
    load_formal_task_manifest,
    load_verified_formal_dataset,
    write_formal_task_set,
)
from veritool_rl.retail_ops.formal_tasks import build_formal_task_set
from veritool_rl.retail_ops.manifests import build_qualification
from veritool_rl.retail_ops.release import decide_release, load_release_report, write_release_report
from veritool_rl.retail_ops.service import create_app
from veritool_rl.retail_ops.teacher_client import OpenAICompatibleTeacherClient, TeacherClient
from veritool_rl.retail_ops.teacher_data import (
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
from veritool_rl.retail_ops.teacher_route import TeacherRouteSnapshot, load_teacher_route
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
        _require_config_keys(config, {"bundle_dir", "split"})
        if args.input_dir is not None:
            raise ValueError("R1 build（无 pipeline 字段）不接受 --input_dir")
        if config["split"] != "qualification":
            raise ValueError("R1 build 只允许 qualification split")
        bundle_dir = _bundle_dir(config)
        build_qualification(bundle_dir, args.seed, args.output_dir)
        return
    if pipeline == "formal_freeze":
        _run_formal_freeze(args, config)
    elif pipeline == "teacher_collect":
        _run_teacher_collect(args, config)
    elif pipeline == "train_export":
        _run_train_export(args, config)
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
    raise ValueError(f"未知 evaluate pipeline: {pipeline!r}")


def _run_release(args: argparse.Namespace) -> None:
    config = load_config(args.config)
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


def _run_serve(args: argparse.Namespace) -> None:
    config = load_config(args.config)
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
# R2 pipeline: formal_freeze (build)
# ---------------------------------------------------------------------------

_FORMAL_FREEZE_KEYS = {"pipeline", "bundle_dir", "dataset_version"}


def _run_formal_freeze(args: argparse.Namespace, config: dict[str, Any]) -> None:
    """从冻结 bundle 生成正式 240/60/120 任务集，写私有真值与公开 answer-free manifest。

    绝不读取 `os.environ`：这条流水线只依赖 bundle 文件和 config 里的
    `dataset_version`，与 teacher provider 无关。
    """
    _require_config_keys(config, _FORMAL_FREEZE_KEYS)
    if args.input_dir is not None:
        raise ValueError("formal_freeze 产出私有根目录，不接受 --input_dir")
    bundle_dir = _bundle_dir(config)
    dataset_version = _dataset_version(config)
    bundle = load_bundle(bundle_dir)
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
# R2 pipeline: train_export (build)
# ---------------------------------------------------------------------------

_TRAIN_EXPORT_KEYS = {
    "pipeline",
    "bundle_dir",
    "public_dir",
    "dataset_version",
    "teacher_attempt_id",
    "attempt_id",
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
    model_dir = models_root / config.model.local_dir
    return TransformersBackend.from_pretrained(
        str(model_dir),
        None,
        revision=config.model.revision,
        expected_file_sha256=config.model.file_sha256,
        settings=config.generation,
    )


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

    backend = (backend_factory or _default_generation_backend)(base_config, models_root)
    hardware_provider = (hardware_provider_factory or _default_hardware_provider)()

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
