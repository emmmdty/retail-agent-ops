"""工具数退化曲线 runner：分阶段、可续跑、跑 GPU 之前先自检装置。

    smoke（小样本，先跑这个）  → 证明装置对、流程通
    full （大样本，再跑这个）  → 出真读数

**每个断点的流程**：preflight（CPU） → teacher → export → train → eval(base) →
eval(candidate)。任一阶段失败即停在该阶段，产物留在原地，重跑时自动续。

用法（gpu-5090）见 `docs/handoffs/2026-08-27-r10-degradation-rerun.md`：

    cd /mnt/aidata/tongjiakai/retail-agent-ops
    set -a && source .env && set +a
    .venv/bin/python scripts/run_v3_degradation.py --profile smoke --stage preflight
    .venv/bin/python scripts/run_v3_degradation.py --profile smoke
    .venv/bin/python scripts/run_v3_degradation.py --profile full

设计约束来自 LOG-20260827-01：2026-08-24 那轮曲线的自变量从未生效，而当时
没有任何东西检查这件事。因此 `--stage preflight` 是纯 CPU 的，几秒钟就能跑完，
**它挡不住的东西不该花 GPU 去发现**。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from veritool_rl.core.envs.base import ToolEnv  # noqa: E402
from veritool_rl.core.trajectory import TaskSpec  # noqa: E402
from veritool_rl.retail_ops.domain.bundle import load_bundle  # noqa: E402
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv  # noqa: E402
from veritool_rl.retail_ops.domain.v3_tasks import (  # noqa: E402
    _TOOL_SUBSETS,
    ToolCountTaskRecord,
    build_toolcount_task_set,
    common_scenarios,
    sample_distribution,
    stratified_sample,
)
from veritool_rl.retail_ops.evaluate.toolcount_eval import (  # noqa: E402
    BreakpointMetrics,
    PreflightError,
    evaluate_tasks,
    preflight_breakpoint,
)

BUNDLE_DIR = PROJECT_ROOT / "domains" / "retail_ops" / "v3"
MODELS_ROOT = PROJECT_ROOT / "models"
MODEL_NAME = "Qwen3-4B-pinned"
BREAKPOINTS = (3, 6, 9, 12, 15)
DATASET_VERSION = "retail_ops_v3_tc{tool_count}_20260827"

#: 小样本与大样本**只差每场景条数**，场景集合、难度轴、生成器、seed 全部相同。
PROFILES: dict[str, dict[str, Any]] = {
    "smoke": {"train_per_scenario": 3, "dev_per_scenario": 2, "epochs": 3},
    "full": {"train_per_scenario": 40, "dev_per_scenario": 10, "epochs": 3},
}

#: 冒烟必须满足的装置不变量。**都与模型好坏无关**——它们只回答
#: 「这套装置能不能产出可归因的读数」。任何一条不成立就不要跑大样本。
SMOKE_GATES = {
    "teacher_acceptance_min": 0.80,
    "infrastructure_error_max": 0,
    # 一条 episode 都发不出合法工具调用，通常是 prompt/parser 坏了，不是模型弱
    "episodes_with_a_valid_call_rate_min": 0.80,
}


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def require_repo_cwd() -> None:
    """模型与 adapter 路径都是项目相对的，因此 cwd 必须就是仓库根。

    `QwenPolicy.from_config` 用 `validate_project_relative_path` 拒绝绝对路径，
    而相对路径按 cwd 解析——从别的目录启动会变成"找不到模型"，
    报错信息完全不指向真正原因。
    """
    if Path.cwd().resolve() != PROJECT_ROOT:
        msg = f"必须在仓库根运行：cd {PROJECT_ROOT}（当前 {Path.cwd()}）"
        raise SystemExit(msg)


def reports_root(profile: str) -> Path:
    return PROJECT_ROOT / "reports" / "retail_ops" / "v1" / "r10-rerun" / profile


def env_factory_for(tool_count: int) -> Callable[[TaskSpec], ToolEnv]:
    """按断点构造环境工厂。

    模型看到的工具必须是该断点的子集——直接用整份 v3 bundle 会让 5 个断点
    呈现同样的 15 个工具，自变量根本没变，曲线平坦是恒真而不是读数。
    """
    bundle = load_bundle(BUNDLE_DIR)
    allowed = _TOOL_SUBSETS[tool_count]

    def factory(task: TaskSpec) -> ToolEnv:
        return RetailOpsEnv(task, bundle, allowed_tools=allowed)

    return factory


def sampled_records(
    tool_count: int,
    split: str,
    profile: str,
) -> tuple[ToolCountTaskRecord, ...]:
    task_set = build_toolcount_task_set(
        DATASET_VERSION.format(tool_count=tool_count), seed=0, tool_count=tool_count
    )
    per_scenario = PROFILES[profile][f"{split}_per_scenario"]
    records = task_set.records(split)
    if per_scenario >= len(records) // len(task_set.scenarios):
        return records
    return stratified_sample(records, per_scenario)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# 阶段 1：preflight（纯 CPU，不花任何预算）
# ---------------------------------------------------------------------------


def stage_preflight(tool_count: int, profile: str, out: Path) -> dict[str, Any]:
    train = sampled_records(tool_count, "train", profile)
    dev = sampled_records(tool_count, "dev", profile)
    factory = env_factory_for(tool_count)
    expected_tools = _TOOL_SUBSETS[tool_count]

    preflight_breakpoint([r.task for r in dev], factory, expected_tools)
    preflight_breakpoint([r.task for r in train], factory, expected_tools)

    manifest = {
        "tool_count": tool_count,
        "profile": profile,
        "dataset_version": DATASET_VERSION.format(tool_count=tool_count),
        "tools_presented": list(expected_tools),
        "train_task_count": len(train),
        "dev_task_count": len(dev),
        "train_distribution": sample_distribution(train),
        "dev_distribution": sample_distribution(dev),
        "dev_task_ids": [r.task.task_id for r in dev],
        "train_task_ids": [r.task.task_id for r in train],
        "curve_readable_scenarios": [s.value for s in common_scenarios()],
    }
    write_json(out / "manifest.json", manifest)
    log(
        f"  preflight OK — 呈现 {len(expected_tools)} 工具，"
        f"train {len(train)} / dev {len(dev)}，Oracle 全解且零违规"
    )
    return manifest


# ---------------------------------------------------------------------------
# 阶段 2：teacher 采集
# ---------------------------------------------------------------------------


def stage_teacher(tool_count: int, profile: str, out: Path) -> dict[str, Any]:
    import os

    from openai import OpenAI

    from veritool_rl.core.build.teacher_client import OpenAICompatibleTeacherClient
    from veritool_rl.core.build.teacher_route import load_teacher_route
    from veritool_rl.retail_ops.build.teacher_data import (
        TeacherCollectionConfig,
        collect_teacher_attempt,
        write_teacher_attempt_evidence,
    )

    records = sampled_records(tool_count, "train", profile)
    version = DATASET_VERSION.format(tool_count=tool_count)
    route, api_key = load_teacher_route(os.environ)
    client = OpenAICompatibleTeacherClient(
        route=route, client=OpenAI(api_key=api_key, base_url=route.base_url)
    )
    config = TeacherCollectionConfig(
        dataset_version=version,
        seed=0,
        bundle_sha256=hashlib.sha256(f"v3-tc{tool_count}".encode()).hexdigest(),
        manifest_sha256=hashlib.sha256(f"v3-tc{tool_count}-manifest".encode()).hexdigest(),
        route_sha256=route.route_sha256,
        max_episodes_per_task=2,
        max_request_attempts=3,
    )
    attempt = f"v3-tc{tool_count}"
    evidence_root = out / "teacher-collection"
    (evidence_root / attempt).mkdir(parents=True, exist_ok=True)
    factory = env_factory_for(tool_count)

    accepted = 0
    errors: list[str] = []
    for index, record in enumerate(records):
        path = evidence_root / attempt / f"{record.task.task_id}.json"
        if path.exists():  # 续跑：已尝试过的不重复计费
            if json.loads(path.read_text(encoding="utf-8")).get("accepted"):
                accepted += 1
            continue
        try:
            evidence = collect_teacher_attempt(record, client, factory, config)
            write_teacher_attempt_evidence(evidence, evidence_root, attempt)
            accepted += int(evidence.accepted)
        except Exception as error:  # 单条失败不该炸掉整轮采集
            errors.append(f"{record.task.task_id}: {type(error).__name__}: {error}")
        if (index + 1) % 20 == 0:
            log(f"  teacher [{index + 1}/{len(records)}] accepted={accepted}")

    rate = accepted / len(records) if records else 0.0
    result = {
        "attempted": len(records),
        "accepted": accepted,
        "acceptance_rate": rate,
        "errors": errors[:20],
        "error_count": len(errors),
    }
    write_json(out / "teacher.json", result)
    log(f"  teacher: {accepted}/{len(records)} = {rate:.4f}，异常 {len(errors)} 条")
    return result


# ---------------------------------------------------------------------------
# 阶段 3：SFT 导出
# ---------------------------------------------------------------------------


def stage_export(tool_count: int, profile: str, out: Path) -> dict[str, Any]:
    from veritool_rl.core.generators import trajectory_to_sft_example
    from veritool_rl.core.trajectory.schema import Trajectory

    records = sampled_records(tool_count, "train", profile)
    evidence_dir = out / "teacher-collection" / f"v3-tc{tool_count}"
    rows: list[dict[str, Any]] = []
    accepted_ids: list[str] = []
    for record in records:
        path = evidence_dir / f"{record.task.task_id}.json"
        if not path.exists():
            continue
        evidence = json.loads(path.read_text(encoding="utf-8"))
        if not evidence.get("accepted") or not evidence.get("trajectory"):
            continue
        accepted_ids.append(record.task.task_id)
        rows.append(trajectory_to_sft_example(Trajectory.model_validate(evidence["trajectory"])))

    sft_path = out / "sft" / "sft.jsonl"
    sft_path.parent.mkdir(parents=True, exist_ok=True)
    with sft_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    # 与采集阶段自己记的接受数对账。跟 accepted_ids 比是空壳——它和 rows 在同一个
    # 循环里同步 append，永远相等。真正会漏的是「采集说接受了 N 条，导出只落盘了
    # M 条」，那要拿另一份产物来比。
    teacher_json = out / "teacher.json"
    if teacher_json.exists():
        expected = int(json.loads(teacher_json.read_text(encoding="utf-8"))["accepted"])
        if len(rows) != expected:
            msg = (
                f"导出 {len(rows)} 行，但 teacher.json 记录接受了 {expected} 条——"
                f"有证据文件缺失或 trajectory 字段为空，训练素材会有系统性缺口"
            )
            raise RuntimeError(msg)
    result = {"rows": len(rows), "accepted_task_ids": accepted_ids}
    write_json(out / "export.json", {"rows": len(rows)})
    log(f"  export: {len(rows)} 行")
    return result


# ---------------------------------------------------------------------------
# 阶段 4：训练
# ---------------------------------------------------------------------------


def stage_train(tool_count: int, profile: str, out: Path) -> dict[str, Any]:
    from veritool_rl.training.sft import run_sft

    sft_path = out / "sft" / "sft.jsonl"
    if not sft_path.exists() or sft_path.stat().st_size == 0:
        msg = f"没有 SFT 数据：{sft_path}"
        raise RuntimeError(msg)

    model_dir = MODELS_ROOT / MODEL_NAME
    file_sha256 = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(model_dir.iterdir())
        if path.is_file() and not path.name.startswith(".")
    }
    revision = hashlib.sha256(json.dumps(file_sha256, sort_keys=True).encode()).hexdigest()[:16]
    config = {
        "model": {
            "name": str(model_dir.relative_to(PROJECT_ROOT)),
            "load_in_4bit": True,
            "revision": revision,
            "file_sha256": file_sha256,
        },
        "lora": {
            "r": 16,
            "alpha": 32,
            "dropout": 0.05,
            "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj"],
        },
        "data": {
            "train_path": str(sft_path.relative_to(PROJECT_ROOT)),
            "eval_path": str(sft_path.relative_to(PROJECT_ROOT)),
        },
        "training": {
            "epochs": PROFILES[profile]["epochs"],
            "batch_size": 1,
            "grad_accum": 1,
            "lr": 2e-4,
        },
    }
    adapter_dir = out / "adapter"
    adapter_dir.mkdir(parents=True, exist_ok=True)
    run_sft(config, seed=0, output_dir=adapter_dir)
    write_json(out / "train.json", {"adapter": str(adapter_dir), "model_revision": revision})
    log(f"  train: adapter 落盘 {adapter_dir}")
    return {"adapter": str(adapter_dir)}


# ---------------------------------------------------------------------------
# 阶段 5：评测
# ---------------------------------------------------------------------------


def _policy_factory(adapter_path: Path | None) -> Callable[[TaskSpec], Any]:
    """构造评测用 policy。

    `QwenPolicy.from_config` 对 `model_name` 与 `adapter_path` 都跑
    `validate_project_relative_path`——**绝对路径会被直接拒绝**。因此这里一律传
    相对仓库根的路径，并且要求进程 cwd 就是仓库根（`require_repo_cwd` 已验过）。
    """
    from veritool_rl.core.agent.qwen import QwenPolicy

    config: dict[str, Any] = {
        "model_name": str((MODELS_ROOT / MODEL_NAME).relative_to(PROJECT_ROOT)),
        "max_new_tokens": 256,
    }
    if adapter_path is not None:
        config["adapter_path"] = str(adapter_path.relative_to(PROJECT_ROOT))
    policy = QwenPolicy.from_config(config)
    return lambda _task: policy


def stage_eval(
    tool_count: int,
    profile: str,
    out: Path,
    label: str,
    adapter_path: Path | None,
) -> BreakpointMetrics:
    records = sampled_records(tool_count, "dev", profile)
    metrics, outcomes = evaluate_tasks(
        [record.task for record in records],
        env_factory_for(tool_count),
        _policy_factory(adapter_path),
        _TOOL_SUBSETS[tool_count],
        tool_count=tool_count,
    )
    write_json(out / f"eval-{label}" / "metrics.json", metrics.to_json())
    write_json(
        out / f"eval-{label}" / "episodes.json",
        [
            {
                "task_id": o.task_id,
                "scenario": o.scenario,
                "success": o.success,
                "violations": o.violations,
                "infrastructure_error": o.infrastructure_error,
                "tool_selection_accuracy": o.score.accuracy if o.score else None,
                "distractor_calls": o.score.distractor_calls if o.score else None,
                "unknown_tool_calls": o.score.unknown_tool_calls if o.score else None,
            }
            for o in outcomes
        ],
    )
    log(
        f"  eval[{label}]: success={metrics.task_success:.4f} "
        f"pv={metrics.policy_violation_count} "
        f"tool_acc={metrics.tool_selection_accuracy:.4f} "
        f"distractor={metrics.distractor_call_rate:.4f} "
        f"infra_err={metrics.infrastructure_error_count}"
    )
    return metrics


# ---------------------------------------------------------------------------
# 冒烟门禁
# ---------------------------------------------------------------------------


def check_smoke_gates(result: dict[str, Any]) -> list[str]:
    """返回未通过的门禁描述。空列表 = 装置可信，可以跑大样本。"""
    failures: list[str] = []
    teacher = result.get("teacher", {})
    rate = teacher.get("acceptance_rate", 0.0)
    if rate < SMOKE_GATES["teacher_acceptance_min"]:
        failures.append(
            f"teacher 接受率 {rate:.4f} < {SMOKE_GATES['teacher_acceptance_min']}"
            "（教师采集不稳定，训练素材会有系统性缺口）"
        )
    for label in ("base", "candidate"):
        metrics = result.get(f"eval_{label}")
        if metrics is None:
            failures.append(f"缺 {label} 读数")
            continue
        if metrics["infrastructure_error_count"] > SMOKE_GATES["infrastructure_error_max"]:
            failures.append(
                f"{label} 有 {metrics['infrastructure_error_count']} 条基础设施失败"
                "（后端异常，读数不完整）"
            )
        if metrics["tools_presented"] != list(_TOOL_SUBSETS[metrics["tool_count"]]):
            failures.append(f"{label} 呈现的工具与断点声明不符——自变量没生效")
        count = metrics["task_count"]
        if count == 0:
            failures.append(f"{label} 没有有效 episode")
            continue
        valid_rate = metrics["episodes_with_a_valid_call"] / count
        if valid_rate < SMOKE_GATES["episodes_with_a_valid_call_rate_min"]:
            failures.append(
                f"{label} 只有 {valid_rate:.4f} 的 episode 发出过合法工具调用 "
                f"< {SMOKE_GATES['episodes_with_a_valid_call_rate_min']}"
                "（通常是 prompt/parser 坏了，不是模型弱）"
            )
    return failures


# ---------------------------------------------------------------------------
# 编排
# ---------------------------------------------------------------------------


def run_breakpoint(tool_count: int, profile: str, stage: str) -> dict[str, Any]:
    out = reports_root(profile) / f"toolcount-{tool_count}"
    out.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"tool_count": tool_count, "profile": profile}

    result["manifest"] = stage_preflight(tool_count, profile, out)
    if stage == "preflight":
        return result

    result["teacher"] = stage_teacher(tool_count, profile, out)
    result["export"] = stage_export(tool_count, profile, out)
    if stage == "data":
        return result

    stage_train(tool_count, profile, out)
    result["eval_base"] = stage_eval(tool_count, profile, out, "base", None).to_json()
    adapter = out / "adapter"
    result["eval_candidate"] = stage_eval(tool_count, profile, out, "candidate", adapter).to_json()
    write_json(out / "done.json", result)
    return result


def print_curve(results: dict[int, dict[str, Any]]) -> None:
    print("\n" + "=" * 92)
    print("曲线只能读所有断点共有的场景（见 manifest.curve_readable_scenarios）；")
    print("总体 task_success 跨断点不可比——各断点的场景集合不同。")
    print("=" * 92)
    print(
        f"{'工具数':>6} {'场景':>5} {'base':>8} {'cand':>8} "
        f"{'delta':>8} {'tool_acc':>9} {'干扰调用率':>10} {'pv':>4}"
    )
    print("-" * 92)
    for tool_count in sorted(results):
        row = results[tool_count]
        base = row.get("eval_base")
        cand = row.get("eval_candidate")
        if not base or not cand:
            print(f"{tool_count:>6}  （未完成）")
            continue
        print(
            f"{tool_count:>6} {len(cand['scenarios']):>5} "
            f"{base['task_success']:>8.4f} {cand['task_success']:>8.4f} "
            f"{cand['task_success'] - base['task_success']:>+8.4f} "
            f"{cand['tool_selection_accuracy']:>9.4f} "
            f"{cand['distractor_call_rate']:>10.4f} "
            f"{cand['policy_violation_count']:>4}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=sorted(PROFILES), default="smoke")
    parser.add_argument(
        "--stage",
        choices=("preflight", "data", "all"),
        default="all",
        help="preflight=纯 CPU 自检；data=到 SFT 导出为止（花 API 不花 GPU）；all=全流程",
    )
    parser.add_argument(
        "--breakpoints",
        type=int,
        nargs="+",
        default=list(BREAKPOINTS),
        choices=list(BREAKPOINTS),
    )
    args = parser.parse_args(argv)
    require_repo_cwd()

    root = reports_root(args.profile)
    results: dict[int, dict[str, Any]] = {}
    for tool_count in args.breakpoints:
        log(f"=== tool_count={tool_count} profile={args.profile} stage={args.stage} ===")
        done = root / f"toolcount-{tool_count}" / "done.json"
        if args.stage == "all" and done.exists():
            log("  已完成，跳过（删掉 done.json 可重跑）")
            results[tool_count] = json.loads(done.read_text(encoding="utf-8"))
            continue
        try:
            results[tool_count] = run_breakpoint(tool_count, args.profile, args.stage)
        except PreflightError as error:
            log(f"  ✗ PREFLIGHT 失败，未消耗任何 GPU/API 预算：\n{error}")
            return 2
        except Exception as error:
            log(f"  ✗ {type(error).__name__}: {error}")
            log("  产物留在原地，修好后重跑本断点即可续。")
            return 3

    if args.stage != "all":
        log(f"stage={args.stage} 完成，未进入 GPU 阶段。")
        return 0

    print_curve(results)
    write_json(root / "curve.json", {str(k): v for k, v in results.items()})

    if args.profile == "smoke":
        failures = [f"tc={tc}: {f}" for tc, r in results.items() for f in check_smoke_gates(r)]
        print("\n" + "=" * 92)
        if failures:
            print("冒烟门禁未通过——**不要跑大样本**，先修下面这些：")
            for failure in failures:
                print(f"  ✗ {failure}")
            return 4
        print("冒烟门禁全部通过：装置可信，可以跑 --profile full。")
        print("注意：冒烟的读数本身样本量太小，不作结论，只证明装置能产出可归因的读数。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
