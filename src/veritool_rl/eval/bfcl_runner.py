"""BFCL 固定单轮子集的生成编排。"""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import Field

from veritool_rl.agent.qwen import GeneratedText, GenerationBackend
from veritool_rl.artifacts import sha256_file, write_json, write_jsonl
from veritool_rl.data.bfcl import (
    BfclGroundTruth,
    BfclManifest,
    BfclTask,
    load_bfcl_category,
)
from veritool_rl.eval.bfcl import (
    BfclDiagnostic,
    build_official_result_row,
    compute_bfcl_metrics,
    diagnose_bfcl_generation,
    load_official_scores,
    write_official_result_files,
)
from veritool_rl.trajectory.schema import StrictModel


class BfclGenerationRecord(StrictModel):
    """逐任务原始生成、用量与补充诊断。"""

    task_id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    raw_output: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: float = Field(ge=0.0)
    diagnostic: BfclDiagnostic

    def as_generated_text(self) -> GeneratedText:
        """恢复官方 result 行需要的未修改生成记录。"""
        return GeneratedText(
            text=self.raw_output,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            latency_ms=self.latency_ms,
        )


def build_official_evaluator_command(
    *,
    python: Path,
    model_name: str,
    categories: tuple[str, ...],
    result_dir: Path,
    score_dir: Path,
) -> list[str]:
    """构造固定 BFCL 官方 AST evaluator 的独立进程命令。"""
    return [
        str(python),
        "-m",
        "bfcl_eval.eval_checker.eval_runner",
        "--model",
        model_name,
        "--test-category",
        *categories,
        "--result-dir",
        str(result_dir),
        "--score-dir",
        str(score_dir),
        "--partial-eval",
    ]


def verify_bfcl_checkout(repo: Path, expected_commit: str) -> dict[str, Any]:
    """验证固定 BFCL checkout 的 commit 与干净工作树。"""
    if not repo.is_dir():
        raise FileNotFoundError(repo)
    actual_commit = _run_git(repo, "rev-parse", "HEAD").strip()
    if actual_commit != expected_commit:
        msg = f"BFCL commit 不一致: {actual_commit} != {expected_commit}"
        raise ValueError(msg)
    status = _run_git(repo, "status", "--porcelain")
    if status.strip():
        msg = f"BFCL checkout 存在修改:\n{status}"
        raise ValueError(msg)
    return {"commit": actual_commit, "worktree_clean": True}


def resolve_manifest_task_answers(
    manifest: BfclManifest,
    data_root: Path,
    requested_ids: list[str] | None = None,
) -> list[tuple[BfclTask, BfclGroundTruth]]:
    """按 manifest 顺序解析正式集合或其显式 smoke 子集。"""
    manifest_ids = [item.task_id for item in manifest.tasks]
    if requested_ids is None:
        selected_ids = set(manifest_ids)
    else:
        if len(requested_ids) != len(set(requested_ids)):
            msg = "task_ids 包含重复 ID"
            raise ValueError(msg)
        extra = sorted(set(requested_ids) - set(manifest_ids))
        if extra:
            msg = f"task_ids 包含 manifest 外 ID: {extra}"
            raise ValueError(msg)
        selected_ids = set(requested_ids)

    task_lookup: dict[str, BfclTask] = {}
    answer_lookup: dict[str, BfclGroundTruth] = {}
    for category in manifest.quotas:
        tasks, answers = load_bfcl_category(data_root, category)
        task_lookup.update((task.id, task) for task in tasks)
        answer_lookup.update((answer.id, answer) for answer in answers)
    pairs = [
        (task_lookup[task_id], answer_lookup[task_id])
        for task_id in manifest_ids
        if task_id in selected_ids
    ]
    if len(pairs) != len(selected_ids):
        msg = "manifest task_id 无法在固定 BFCL 数据中完整解析"
        raise ValueError(msg)
    return pairs


def inspect_local_model(model_dir: Path) -> dict[str, Any]:
    """验证 Qwen 本地配置、tokenizer、index 与全部权重分片。"""
    required = [
        model_dir / "config.json",
        model_dir / "tokenizer.json",
        model_dir / "tokenizer_config.json",
        model_dir / "model.safetensors.index.json",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        msg = f"模型文件缺失: {missing}"
        raise ValueError(msg)
    try:
        index = json.loads(required[-1].read_text(encoding="utf-8"))
        weight_map = index["weight_map"]
        shards = sorted(set(weight_map.values()))
    except (json.JSONDecodeError, KeyError, AttributeError) as error:
        msg = f"模型 safetensors index 无效: {required[-1]}"
        raise ValueError(msg) from error
    if not shards or not all(isinstance(name, str) for name in shards):
        msg = f"模型 safetensors index 未引用有效分片: {required[-1]}"
        raise ValueError(msg)
    shard_paths = [model_dir / name for name in shards]
    missing_shards = [str(path) for path in shard_paths if not path.is_file()]
    if missing_shards:
        msg = f"模型权重分片缺失: {missing_shards}"
        raise ValueError(msg)
    files = required + shard_paths
    return {
        "configured_path": str(model_dir),
        "resolved_path": str(model_dir.resolve()),
        "is_symlink": model_dir.is_symlink(),
        "files": {
            path.name: {"size_bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in files
        },
        "weight_shards": shards,
    }


def validate_offline_single_gpu_environment() -> str:
    """拒绝联网模型加载与多卡/隐式 GPU 选择。"""
    for name in ("TRANSFORMERS_OFFLINE", "HF_HUB_OFFLINE"):
        if os.environ.get(name) != "1":
            msg = f"{name} 必须显式设置为 1"
            raise ValueError(msg)
    visible = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    if not visible.isdigit():
        msg = "CUDA_VISIBLE_DEVICES 必须是单个物理 GPU 编号"
        raise ValueError(msg)
    return visible


def run_official_evaluator(
    *,
    python: Path,
    project_root: Path,
    model_name: str,
    categories: tuple[str, ...],
    result_dir: Path,
    score_dir: Path,
) -> tuple[list[str], str, float]:
    """在隔离 Python 进程中运行固定源码的 BFCL 官方 AST evaluator。"""
    if not python.is_file():
        raise FileNotFoundError(python)
    python = python.resolve()
    project_root.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    score_dir.mkdir(parents=True, exist_ok=True)
    command = build_official_evaluator_command(
        python=python,
        model_name=model_name,
        categories=categories,
        result_dir=result_dir.resolve(),
        score_dir=score_dir.resolve(),
    )
    env = os.environ.copy()
    env["BFCL_PROJECT_ROOT"] = str(project_root.resolve())
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=project_root,
        env=env,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    elapsed = time.perf_counter() - started
    if completed.returncode != 0:
        msg = f"BFCL 官方 evaluator 失败 ({completed.returncode}):\n{completed.stdout}"
        raise RuntimeError(msg)
    return command, completed.stdout, elapsed


def build_bfcl_failure_rows(
    *,
    score_root: Path,
    model_name: str,
    records: list[BfclGenerationRecord],
    task_answers: list[tuple[BfclTask, BfclGroundTruth]],
) -> list[dict[str, Any]]:
    """结合官方失败行和原始生成构造可审计的真实失败分析。"""
    record_by_id = {record.task_id: record for record in records}
    task_by_id = {task.id: task for task, _ in task_answers}
    answer_by_id = {answer.id: answer for _, answer in task_answers}
    rows: list[dict[str, Any]] = []
    score_dir = score_root / model_name.replace("/", "_") / "non_live"
    for path in sorted(score_dir.glob("BFCL_v4_*_score.json")):
        score_rows = _read_dict_jsonl(path)
        for official in score_rows[1:]:
            task_id = official.get("id")
            if not isinstance(task_id, str) or task_id not in record_by_id:
                msg = f"官方失败 ID 无法对齐原始生成: {task_id}"
                raise ValueError(msg)
            record = record_by_id[task_id]
            task = task_by_id[task_id]
            answer = answer_by_id[task_id]
            rows.append(
                {
                    "task_id": task_id,
                    "category": record.category,
                    "user_question": [
                        message.model_dump(mode="json") for message in task.question[0]
                    ],
                    "function_schema": [
                        function.model_dump(mode="json") for function in task.function
                    ],
                    "raw_model_output": record.raw_output,
                    "expected_calls": answer.ground_truth,
                    "official_error_type": official.get("error_type", "unknown"),
                    "official_error": official.get("error"),
                    "diagnostic": record.diagnostic.model_dump(mode="json"),
                    "root_cause": _root_cause(record.diagnostic, official),
                }
            )
    return sorted(rows, key=lambda row: str(row["task_id"]))


def finalize_bfcl_artifacts(
    *,
    output_dir: Path,
    model_name: str,
    records: list[BfclGenerationRecord],
    task_answers: list[tuple[BfclTask, BfclGroundTruth]],
    wall_time_seconds: float,
    cuda_peak_allocated_bytes: int,
    cuda_peak_reserved_bytes: int,
) -> dict[str, Any]:
    """严格对齐官方 score 后写入指标、失败分析与范围限定报告。"""
    ids_by_category: dict[str, list[str]] = defaultdict(list)
    for record in records:
        ids_by_category[record.category].append(record.task_id)
    scores = load_official_scores(
        output_dir / "official_scores",
        model_name,
        dict(ids_by_category),
    )
    metrics = compute_bfcl_metrics(
        scores=scores,
        diagnostics=[record.diagnostic for record in records],
        generation_latency_ms=[record.latency_ms for record in records],
        wall_time_seconds=wall_time_seconds,
        cuda_peak_allocated_bytes=cuda_peak_allocated_bytes,
        cuda_peak_reserved_bytes=cuda_peak_reserved_bytes,
    )
    failures = build_bfcl_failure_rows(
        score_root=output_dir / "official_scores",
        model_name=model_name,
        records=records,
        task_answers=task_answers,
    )
    if len(failures) != metrics["official_error_count"]:
        msg = "真实失败分析数量与官方错误数不一致"
        raise ValueError(msg)
    metrics["failure_analysis_count"] = len(failures)
    write_json(output_dir / "metrics.json", metrics)
    write_jsonl(output_dir / "failures.jsonl", failures)
    (output_dir / "report.md").write_text(
        _render_bfcl_report(metrics, failures),
        encoding="utf-8",
    )
    return metrics


def _run_git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _read_dict_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            msg = f"无效 JSONL: {path}:{line_number}"
            raise ValueError(msg) from error
        if not isinstance(row, dict):
            msg = f"JSONL 行必须是对象: {path}:{line_number}"
            raise ValueError(msg)
        rows.append(row)
    return rows


def _root_cause(diagnostic: BfclDiagnostic, official: dict[str, Any]) -> str:
    if diagnostic.parse_error is not None:
        return f"模型输出不可解析: {diagnostic.parse_error}"
    if diagnostic.wrong_function_name_count:
        return "模型选择了错误的函数名"
    if diagnostic.call_count_error:
        return "模型输出的函数调用数量与期望不一致"
    if diagnostic.missing_parameter_count:
        return "模型函数调用缺少必需参数"
    if diagnostic.extra_parameter_count:
        return "模型函数调用包含 schema 外参数"
    if diagnostic.type_error_parameter_count:
        return "模型函数调用参数类型不符合 schema"
    error_type = official.get("error_type", "unknown")
    return f"官方 AST evaluator 判定调用语义或参数值错误: {error_type}"


def _render_bfcl_report(
    metrics: dict[str, Any],
    failures: list[dict[str, Any]],
) -> str:
    task_count = metrics["task_count"]
    accuracy = metrics["official_ast_accuracy"]
    lines = [
        f"# Qwen3-1.7B 在 BFCL V4 固定 {task_count} 条单轮 AST 子集上的零样本结果",
        "",
        "## 结论",
        "",
        f"官方 BFCL AST accuracy 为 {accuracy:.6f} "
        f"({metrics['official_correct_count']}/{task_count})。",
        "这是固定子集实验，不是 BFCL 官方全量成绩或排行榜成绩。",
        "",
        "## 分类别结果",
        "",
        "| 类别 | 任务数 | 正确 | 错误 | AST accuracy |",
        "|---|---:|---:|---:|---:|",
    ]
    for category, count in metrics["category_counts"].items():
        lines.append(
            f"| {category} | {count} | "
            f"{metrics['official_correct_count_by_category'][category]} | "
            f"{metrics['official_error_count_by_category'][category]} | "
            f"{metrics['official_ast_accuracy_by_category'][category]:.6f} |"
        )
    lines.extend(
        [
            "",
            "## 补充诊断",
            "",
            f"- 输出可解析率：{metrics['parseable_rate']:.6f}",
            f"- function-call schema-valid rate：{metrics['schema_valid_rate']:.6f}",
            f"- 错误函数名：{metrics['wrong_function_name_count']}",
            f"- 缺失参数：{metrics['missing_parameter_count']}",
            f"- 额外参数：{metrics['extra_parameter_count']}",
            f"- 参数类型错误：{metrics['type_error_parameter_count']}",
            f"- 调用数量错误：{metrics['call_count_error_count']}",
            f"- parallel/multiple 结构错误：{metrics['structure_error_count']}",
            "",
            "这些诊断不替代官方 AST evaluator 指标。",
            "",
            "## 失败分析",
            "",
        ]
    )
    if failures:
        analyzed = failures[: max(20, len(failures))]
        lines.append(
            f"`failures.jsonl` 包含全部 {len(failures)} 条真实官方失败及逐条根因。"
        )
        lines.append("")
        for failure in analyzed[:20]:
            lines.append(
                f"- `{failure['task_id']}`：{failure['official_error_type']}；"
                f"{failure['root_cause']}。"
            )
        if len(failures) < 20:
            lines.append("")
            lines.append(f"总失败不足 20 条，因此已分析全部 {len(failures)} 条。")
    else:
        lines.append("本次没有官方失败，因此没有失败样例可分析。")
    lines.extend(
        [
            "",
            "## 适用范围",
            "",
            "结果仅适用于提交 manifest 冻结的 BFCL V4 单轮 AST 子集、seed 0、"
            "Qwen3-1.7B 4-bit NF4 零样本设置；不能外推到 BFCL 全量、官方排行榜、"
            "多轮任务、ToolSandbox、tau2、SFT、偏好优化或 GRPO。",
            "",
        ]
    )
    return "\n".join(lines)


def generate_bfcl_records(
    task_answers: list[tuple[BfclTask, BfclGroundTruth]],
    backend: GenerationBackend,
    max_new_tokens: int,
) -> list[BfclGenerationRecord]:
    """按给定顺序生成 BFCL 响应，并保留原始输出。"""
    records: list[BfclGenerationRecord] = []
    for task, answer in task_answers:
        if task.id != answer.id:
            msg = f"任务与 ground truth ID 不一致: {task.id} != {answer.id}"
            raise ValueError(msg)
        generated = backend.generate(
            [message.model_dump(mode="json") for message in task.question[0]],
            [function.model_dump(mode="json") for function in task.function],
            max_new_tokens,
        )
        records.append(
            BfclGenerationRecord(
                task_id=task.id,
                category=task.id.rsplit("_", 1)[0],
                raw_output=generated.text,
                input_tokens=generated.input_tokens,
                output_tokens=generated.output_tokens,
                latency_ms=generated.latency_ms,
                diagnostic=diagnose_bfcl_generation(task, answer, generated.text),
            )
        )
    return records


def write_bfcl_generation_artifacts(
    output_dir: Path,
    model_name: str,
    records: list[BfclGenerationRecord],
) -> list[Path]:
    """写入原始生成与 BFCL 官方 result 文件。"""
    write_jsonl(
        output_dir / "raw_generations.jsonl",
        (record.model_dump(mode="json") for record in records),
    )
    ids_by_category: dict[str, list[str]] = defaultdict(list)
    rows: list[dict[str, object]] = []
    for record in records:
        ids_by_category[record.category].append(record.task_id)
        rows.append(build_official_result_row(record.task_id, record.as_generated_text()))
    return write_official_result_files(
        output_dir / "official_results",
        model_name,
        dict(ids_by_category),
        rows,
    )
