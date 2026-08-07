"""验证求职工程定位和 Agent 接管文档不会静默漂移。"""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_required_handoff_documents_exist() -> None:
    required = {
        "AGENTS.md",
        "docs/CAREER_CONTEXT.md",
        "docs/PRODUCT_BRIEF.md",
        "docs/EXECUTION_PLAN.md",
        "docs/HANDOFF.md",
        "docs/LEGACY_INVENTORY.md",
        "task_plan.md",
        "findings.md",
        "progress.md",
    }

    missing = sorted(path for path in required if not (ROOT / path).is_file())

    assert missing == []


def test_career_context_records_decision_constraints() -> None:
    context = _read("docs/CAREER_CONTEXT.md")

    for expected in (
        "985",
        "研二",
        "CCKS 2026",
        "中国大陆",
        "2027 届秋招",
        "30+ 小时",
        "4× RTX 4090",
        "不产出论文",
        "Codex",
    ):
        assert expected in context


def test_active_plan_has_goal_execution_and_acceptance_for_every_phase() -> None:
    plan = _read("docs/EXECUTION_PLAN.md")

    assert "RetailAgentOps" in plan
    for phase in ("R0", "R1", "R2", "R3", "R4", "R5"):
        section = plan.split(f"## {phase}", maxsplit=1)[1].split("\n## ", maxsplit=1)[0]
        assert "总体目标" in section
        assert "执行目标" in section
        assert "验收目标" in section


def test_active_docs_reject_research_first_drift() -> None:
    active_docs = "\n".join(
        _read(path)
        for path in (
            "AGENTS.md",
            "CLAUDE.md",
            "SPEC.md",
            "docs/PRODUCT_BRIEF.md",
            "docs/EXECUTION_PLAN.md",
        )
    )

    assert "RetailAgentOps" in active_docs
    assert "单卡" in active_docs
    assert "发布门禁" in active_docs
    assert "至少 3 个预注册 seed" not in active_docs
    assert "研究级 L1/L2" not in active_docs


def test_handoff_defines_read_order_and_stop_rules() -> None:
    handoff = _read("docs/HANDOFF.md")

    for expected in (
        "docs/CAREER_CONTEXT.md",
        "docs/PRODUCT_BRIEF.md",
        "docs/EXECUTION_PLAN.md",
        "task_plan.md",
        "findings.md",
        "progress.md",
        "停止并询问用户",
        "GPU",
    ):
        assert expected in handoff


def test_retail_ops_v1_contract_and_holdout_boundary_are_governed() -> None:
    design = ROOT / "docs/superpowers/specs/2026-07-20-retailops-v1-contract-design.md"
    implementation = ROOT / "docs/superpowers/plans/2026-07-20-retailops-v1-r1-vertical-slice.md"
    assert design.is_file()
    assert implementation.is_file()
    assert "RetailOps v1" in design.read_text(encoding="utf-8")
    assert "RetailOps v1" in implementation.read_text(encoding="utf-8")

    for path in (ROOT / "domains/retail_ops/v1").rglob("*"):
        if path.is_file():
            assert "bfcl" not in path.read_text(encoding="utf-8").lower()

    for ignored_path in (
        "data/private/retail_ops/v1/holdout/tasks.jsonl",
        "reports/retail_ops/v1/qualification-example/run.json",
    ):
        ignored = subprocess.run(
            ["git", "check-ignore", ignored_path],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert ignored.returncode == 0, ignored_path


def test_r1_closeout_and_r2_authorization_keep_formal_holdout_sealed() -> None:
    readme = _read("README.md")
    execution_plan = _read("docs/EXECUTION_PLAN.md")
    project_log = _read("docs/PROJECT_LOG.md")

    for expected in ("合成 qualification", "未生成正式 holdout", "不是 RetailOps 内部指标"):
        assert expected in readme
    assert "| R1 产品契约与 v0.1 | 第 1–2 周 | 已完成 |" in execution_plan
    assert "| R2 数据与评测流水线 | 第 3–4 周 | 已完成 |" in execution_plan
    assert "R1 qualification 纵向切片完成" in project_log
    assert "批准并启动 R2 正式数据与双模型 Base" in project_log
    assert "正式 holdout 在\nR2 不运行真实模型" in project_log
    assert "正式外部动作尚未授权" in project_log


def test_r2_active_instructions_reference_approved_contract_and_external_gates() -> None:
    agents = _read("AGENTS.md")
    handoff = _read("docs/handoffs/2026-07-22-r2-codex-execution-prompt.md")
    design = _read(
        "docs/superpowers/specs/2026-07-22-retailops-v1-r2-formal-data-and-base-design.md"
    )
    implementation = _read(
        "docs/superpowers/plans/2026-07-22-retailops-v1-r2-formal-data-and-base.md"
    )

    assert "当前阶段：`R2` CPU 实现" in agents
    assert "R2 已完成方案审批" in agents
    assert "正式数据、API、模型下载、SSH 和每条 GPU 命令仍需分别确认" in agents

    for expected in (
        "R2 设计选择和 CPU 实施计划已经用户批准",
        "2026-07-22-retailops-v1-r2-formal-data-and-base-design.md",
        "2026-07-22-retailops-v1-r2-formal-data-and-base.md",
        "不得重复创建平行规格或重新打开已裁决方案",
    ):
        assert expected in handoff

    for excluded_field in (
        "`task_id`",
        "`split`",
        "`target_state`",
        "`expected_calls`",
        "`expected_decision`",
    ):
        assert excluded_field in design
    assert "经 private artifact SHA-256 和公开 dev manifest 双重校验" in design
    assert "`train.jsonl` 与 `sft.jsonl` 只能写入 private ignored root" in design
    assert "private ignored root 的 `teacher-collection/<attempt>/`" in design
    assert "change only `task_id` or `split`" in implementation
    assert "validated private dev artifact" in implementation
    assert "private ignored `teacher-collection/<attempt>/`" in implementation


_R2_CONFIG_NAMES = (
    "retail_ops_v1_r2_formal_freeze.yaml",
    "retail_ops_v1_r2_teacher_smoke.yaml",
    "retail_ops_v1_r2_teacher_full.yaml",
    "retail_ops_v1_r2_train_export.yaml",
    "retail_ops_v1_r2_qwen3_1_7b_dev.yaml",
    "retail_ops_v1_r2_qwen3_4b_dev.yaml",
)


def test_r2_governed_paths_remain_ignored() -> None:
    """R2 CLI 新增的私有/模型/产物路径必须仍被 `.env`/`/data/`/`/models/`/
    `/reports/retail_ops/` 这几条既有 `.gitignore` 规则覆盖，不需要新增规则；
    这里用具体 R2 示例路径核实规则确实生效，而不是假设它们生效。"""
    for ignored_path in (
        ".env",
        "data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722/train.jsonl",
        "data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722/teacher-collection/"
        "attempt-1/checkpoint.json",
        "data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722/train-export/"
        "attempt-1/train.jsonl",
        "data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722/dev-base/base-001/run.json",
        "models/Qwen3-1.7B-pinned/model.safetensors",
        "reports/retail_ops/v1/r2-example/run.json",
    ):
        ignored = subprocess.run(
            ["git", "check-ignore", ignored_path],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert ignored.returncode == 0, ignored_path

    # 公开正式 manifest 根目录相反：不应被忽略（它是 answer-free、计划提交的产物）。
    not_ignored = subprocess.run(
        [
            "git",
            "check-ignore",
            "manifests/retail_ops/v1/retail_ops_v1_r2_20260722/dataset.json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert not_ignored.returncode == 1


def _iter_leaf_values(value: object) -> list[str]:
    if isinstance(value, dict):
        leaves: list[str] = []
        for item in value.values():
            leaves.extend(_iter_leaf_values(item))
        return leaves
    if isinstance(value, list):
        leaves = []
        for item in value:
            leaves.extend(_iter_leaf_values(item))
        return leaves
    return [str(value)]


def test_r2_configs_contain_no_secrets_or_private_paths() -> None:
    """已提交的 6 份 R2 config 的实际取值（不含说明性注释）不得包含真实凭据、
    绝对路径或私有根路径字面量——只扫描解析后的 YAML value，注释里出现
    `data/private/...` 是在解释 CLI 内部推导的约定，不是配置数据本身。"""
    import yaml

    secret_markers = ("sk-", "Bearer ", "bearer ", "AKIA", "ghp_", "-----BEGIN")
    for name in _R2_CONFIG_NAMES:
        text = _read(f"configs/{name}")
        assert "TEACHER_LLM_" not in text, name
        parsed = yaml.safe_load(text)
        assert isinstance(parsed, dict)
        for leaf in _iter_leaf_values(parsed):
            assert not leaf.startswith("/"), f"{name}: 疑似绝对路径 {leaf!r}"
            assert "data/private" not in leaf, f"{name}: 疑似私有根路径 {leaf!r}"
            for marker in secret_markers:
                assert marker not in leaf, f"{name}: 疑似 secret 标记 {marker!r} in {leaf!r}"


def test_product_cli_and_r2_configs_never_reference_bfcl() -> None:
    """R2 CLI 分发代码和新增 config 不得引用 BFCL 固定 200 条 holdout 或其失败样例。"""
    scanned = [ROOT / "src/veritool_rl/product_cli.py"]
    scanned.extend((ROOT / "src/veritool_rl/retail_ops").rglob("*.py"))
    scanned.extend(ROOT / "configs" / name for name in _R2_CONFIG_NAMES)
    for path in scanned:
        assert "bfcl" not in path.read_text(encoding="utf-8").lower(), path


def test_uv_lock_check_succeeds_through_project_level_index_pinning() -> None:
    """`uv.lock` 必须与 `pyproject.toml`（含项目级 `[[tool.uv.index]] default = true`
    锁定）保持一致，且这个一致性不依赖进程环境里可能存在的镜像 index 覆盖
    （`UV_INDEX_URL`，见 `task_plan.md` 里几条相关 Errors 记录）——清掉它之后
    `uv lock --check` 必须干净通过，不需要任何重写。"""
    env = dict(os.environ)
    env.pop("UV_INDEX_URL", None)
    result = subprocess.run(
        ["uv", "lock", "--check"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"


_R3_CONFIG_NAMES = (
    "retail_ops_v1_r3_dev_sft_export.yaml",
    "retail_ops_v1_r3_sft_smoke.yaml",
    "retail_ops_v1_r3_sft_overfit.yaml",
    "retail_ops_v1_r3_sft.yaml",
)


def test_r3_configs_contain_no_secrets_or_private_paths() -> None:
    """R3 新增 config 与 R2 同一口径：解析后的取值不得含真实凭据、绝对路径或
    私有根路径字面量。训练数据路径只写私有根内的相对片段，前缀由 `--input_dir`
    在运行时提供，因此这条断言对 SFT config 同样成立。"""
    import yaml

    secret_markers = ("sk-", "Bearer ", "bearer ", "AKIA", "ghp_", "-----BEGIN")
    for name in _R3_CONFIG_NAMES:
        text = _read(f"configs/{name}")
        assert "TEACHER_LLM_" not in text, name
        parsed = yaml.safe_load(text)
        assert isinstance(parsed, dict)
        for leaf in _iter_leaf_values(parsed):
            assert not leaf.startswith("/"), f"{name}: 疑似绝对路径 {leaf!r}"
            assert "data/private" not in leaf, f"{name}: 疑似私有根路径 {leaf!r}"
            for marker in secret_markers:
                assert marker not in leaf, f"{name}: 疑似 secret 标记 {marker!r} in {leaf!r}"


def test_r3_configs_never_reference_bfcl_or_holdout() -> None:
    """R3 config 与训练侧代码不得引用 BFCL 固定 200 条或正式 holdout。"""
    scanned = [ROOT / "src/veritool_rl/retail_ops/dev_sft_export.py"]
    scanned.extend(ROOT / "configs" / name for name in _R3_CONFIG_NAMES)
    for path in scanned:
        text = path.read_text(encoding="utf-8").lower()
        assert "bfcl" not in text, path
        assert "holdout" not in text, path


def test_r3_sft_configs_pin_model_provenance() -> None:
    """每份正式 SFT config 都必须带 revision + 逐文件 SHA-256，不允许无 pin 训练。"""
    import yaml

    for name in _R3_CONFIG_NAMES:
        parsed = yaml.safe_load(_read(f"configs/{name}"))
        if parsed.get("pipeline") != "sft":
            continue
        model = parsed["model"]
        assert len(model["revision"]) >= 7, name
        assert model["file_sha256"], name
        for digest in model["file_sha256"].values():
            assert len(digest) == 64, name


def test_r3_governed_paths_remain_ignored() -> None:
    """R3 新增的 dev-sft 私有产物与训练输出（adapter/checkpoints）必须仍被既有
    `.gitignore` 规则覆盖，不需要新增规则。"""
    for ignored_path in (
        "data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722/dev-sft/dev-sft-001/sft.jsonl",
        "models/Qwen3-4B-pinned/model-00001-of-00003.safetensors",
        "reports/retail_ops/v1/r3-sft-001/metrics.json",
        "reports/retail_ops/v1/r3-sft-001/adapter/adapter_model.safetensors",
        "reports/retail_ops/v1/r3-sft-001/checkpoints/trainer_state.json",
    ):
        ignored = subprocess.run(
            ["git", "check-ignore", ignored_path],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert ignored.returncode == 0, ignored_path
