"""验证求职工程定位和 Agent 接管文档不会静默漂移。"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

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
    design = ROOT / "docs/archive/superpowers/specs/2026-07-20-retailops-v1-contract-design.md"
    implementation = (
        ROOT / "docs/archive/superpowers/plans/2026-07-20-retailops-v1-r1-vertical-slice.md"
    )
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
    handoff = _read("docs/archive/handoffs/2026-07-22-r2-codex-execution-prompt.md")
    design = _read(
        "docs/archive/superpowers/specs/2026-07-22-retailops-v1-r2-formal-data-and-base-design.md"
    )
    implementation = _read(
        "docs/archive/superpowers/plans/2026-07-22-retailops-v1-r2-formal-data-and-base.md"
    )

    # 「当前阶段」必须与阶段状态的唯一事实源一致。
    #
    # 这里此前钉的是 `"当前阶段：`R5` …已完成"` 这一句原话，于是 R6 完成之后
    # 它在强制一个过期的阶段号（LOG-20260817-06 的同一个失败模式，第四次出现）。
    # 现在断言的是**一致性**：AGENTS.md 声明的阶段，在 EXECUTION_PLAN.md 的阶段表里
    # 必须存在且被标为「已完成」。阶段号换了多少次都不需要改这条测试。
    phase = re.search(r"当前阶段：`([^`]+)`", agents)
    assert phase is not None, "AGENTS.md 没有声明当前阶段"
    plan = _read("docs/EXECUTION_PLAN.md")
    phase_rows = [line for line in plan.splitlines() if line.startswith(f"| {phase.group(1)} ")]
    assert phase_rows, f"EXECUTION_PLAN.md 的阶段表里没有 {phase.group(1)}"
    assert all("已完成" in row for row in phase_rows), (
        f"AGENTS.md 声称 {phase.group(1)} 已完成，但阶段状态源里不是：{phase_rows}"
    )

    assert "R2 已完成方案审批" in agents
    assert "正式数据、API、模型下载、SSH 和每条 GPU 命令仍需分别确认" in agents
    # 候选结论必须以 dev / holdout 口径分别陈述，不得被写成 release 判定
    assert "不得把 dev 读数写成 release 判定" in agents
    # 封存 holdout 是不可逆资源，接管文档必须指向台账（次数本身不得复述，
    # 由 test_no_active_doc_restates_the_sealed_holdout_total_count 保证）
    assert "docs/HOLDOUT_LEDGER.md" in agents
    # 观测次数不再是硬约束，但纪律必须同时在场——只写前半句会读成「随便测」。
    assert "观测次数不再是硬约束" in agents
    assert "结果永远不得反馈进开发" in agents
    # R4 的结论已被跨规模检验限缩，接管文档不得留下无条件的一般化表述
    assert "LoRA 容量须与模型规模匹配" in agents
    assert "提示词干预是规模依赖的" in agents

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
    "retail_ops/build/retail_ops_v1_r2_formal_freeze.yaml",
    "retail_ops/build/retail_ops_v1_r2_teacher_smoke.yaml",
    "retail_ops/build/retail_ops_v1_r2_teacher_full.yaml",
    "retail_ops/build/retail_ops_v1_r2_train_export.yaml",
    "retail_ops/evaluate/retail_ops_v1_r2_qwen3_1_7b_dev.yaml",
    "retail_ops/evaluate/retail_ops_v1_r2_qwen3_4b_dev.yaml",
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
    "retail_ops/build/retail_ops_v1_r3_dev_sft_export.yaml",
    "retail_ops/build/retail_ops_v1_r3_sft_smoke.yaml",
    "retail_ops/build/retail_ops_v1_r3_sft_overfit.yaml",
    "retail_ops/build/retail_ops_v1_r3_sft.yaml",
    "retail_ops/evaluate/retail_ops_v1_r3_qwen3_4b_candidate.yaml",
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
    scanned = [ROOT / "src/veritool_rl/retail_ops/build/dev_sft_export.py"]
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


def test_r3_candidate_config_pins_model_and_adapter() -> None:
    """候选 config 必须同时锁定基座模型与 adapter 的逐文件 SHA-256。"""
    import yaml

    parsed = yaml.safe_load(
        _read("configs/retail_ops/evaluate/retail_ops_v1_r3_qwen3_4b_candidate.yaml")
    )
    assert parsed["pipeline"] == "formal_dev_candidate"
    for key in ("model", "adapter"):
        digests = parsed[key]["file_sha256"]
        assert digests, key
        for digest in digests.values():
            assert len(digest) == 64, key
    # 候选必须与 base 跑同一份基座模型，否则 delta 不能归因于 adapter。
    base = yaml.safe_load(_read("configs/retail_ops/evaluate/retail_ops_v1_r2_qwen3_4b_dev.yaml"))[
        "model"
    ]
    assert parsed["model"] == base


def test_r3_candidate_governed_paths_remain_ignored() -> None:
    for ignored_path in (
        "data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722/dev-candidate/cand-001/run.json",
        "reports/retail_ops/v1/r3/candidate-001/candidate-report.json",
    ):
        ignored = subprocess.run(
            ["git", "check-ignore", ignored_path],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert ignored.returncode == 0, ignored_path


def test_source_layers_enforce_one_way_dependency() -> None:
    """`docs/REPO_MAP.md` 主张依赖方向恒为 product_cli → retail_ops.* → core.*，
    且 legacy 不被主线依赖。这条主张是"领域可替换"的结构证据，必须可验证而不是
    仅写在文档里——否则下一次改动就会静默把它破坏掉。"""
    src = ROOT / "src/veritool_rl"
    forbidden = {
        "core": ("veritool_rl.retail_ops", "veritool_rl.legacy", "veritool_rl.training"),
        "retail_ops": ("veritool_rl.legacy",),
        "training": ("veritool_rl.legacy", "veritool_rl.retail_ops"),
    }
    violations: list[str] = []
    for layer, banned in forbidden.items():
        for path in (src / layer).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for name in banned:
                if f"import {name}" in text or f"from {name}" in text:
                    violations.append(f"{path.relative_to(ROOT)} 依赖了 {name}")

    cli_text = (src / "product_cli.py").read_text(encoding="utf-8")
    if "veritool_rl.legacy" in cli_text:
        violations.append("src/veritool_rl/product_cli.py 依赖了 veritool_rl.legacy")

    assert violations == []


def test_four_stable_interfaces_have_config_and_module_homes() -> None:
    """SPEC 第 3 节的四个稳定接口在目录结构上必须各有归属，且每个 configs 子目录
    非空——防止接口名只存在于文档而没有可运行配置。"""
    for interface in ("build", "evaluate", "release", "serve"):
        module_dir = ROOT / "src/veritool_rl/retail_ops" / interface
        config_dir = ROOT / "configs/retail_ops" / interface
        assert module_dir.is_dir(), interface
        assert (module_dir / "__init__.py").is_file(), interface
        assert list(config_dir.glob("*.yaml")), interface


_R4_CONFIG_NAMES = (
    "retail_ops/build/retail_ops_v1_r4_train_export_rebalanced.yaml",
    "retail_ops/build/retail_ops_v1_r4_sft_rebalanced.yaml",
    "retail_ops/evaluate/retail_ops_v1_r4_qwen3_4b_candidate.yaml",
)


def test_r4_configs_hold_the_same_governance_line_as_r2_and_r3() -> None:
    """R4 新增 config 必须落在与 R2/R3 完全相同的治理口径下。

    新阶段最容易发生的退化不是写错哈希，而是"这只是个实验配置"心态下漏掉扫描：
    配置里出现绝对路径、私有根字面量、凭据，或者悄悄引用 BFCL/正式 holdout。
    这条测试把 R4 的新文件明确纳入既有断言，而不是依赖下一个人记得加。
    """
    import yaml

    secret_markers = ("sk-", "Bearer ", "bearer ", "AKIA", "ghp_", "-----BEGIN")
    for name in _R4_CONFIG_NAMES:
        text = _read(f"configs/{name}")
        assert "TEACHER_LLM_" not in text, name
        lowered = text.lower()
        assert "bfcl" not in lowered, name
        assert "holdout" not in lowered, name
        parsed = yaml.safe_load(text)
        assert isinstance(parsed, dict)
        for leaf in _iter_leaf_values(parsed):
            assert not leaf.startswith("/"), f"{name}: 疑似绝对路径 {leaf!r}"
            assert "data/private" not in leaf, f"{name}: 疑似私有根路径 {leaf!r}"
            for marker in secret_markers:
                assert marker not in leaf, f"{name}: 疑似 secret 标记 {marker!r} in {leaf!r}"

        if parsed.get("pipeline") == "sft":
            model = parsed["model"]
            assert len(model["revision"]) >= 7, name
            assert model["file_sha256"], name
            for digest in model["file_sha256"].values():
                assert len(digest) == 64, name


def test_r4_rebalanced_export_output_stays_ignored() -> None:
    """重平衡导出的私有训练数据与公开 quality.json 都必须仍被既有 `.gitignore`
    覆盖，不需要为 R4 新增规则——训练数据永远不进 Git。"""
    for ignored_path in (
        "data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722/train-export/"
        "train-export-002/sft.jsonl",
        "reports/retail_ops/v1/r4/train-export-002/quality.json",
    ):
        ignored = subprocess.run(
            ["git", "check-ignore", ignored_path],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert ignored.returncode == 0, ignored_path


# ---------------------------------------------------------------------------
# R4 第二轮：三候选并列消融的新配置
# ---------------------------------------------------------------------------

_R4_ROUND2_CONFIG_NAMES = (
    "retail_ops/build/retail_ops_v1_r4_round2_a_sft_lora_full.yaml",
    "retail_ops/build/retail_ops_v1_r4_round2_b_train_export.yaml",
    "retail_ops/build/retail_ops_v1_r4_round2_b_sft.yaml",
    "retail_ops/evaluate/retail_ops_v1_r4_round2_a_candidate.yaml",
    "retail_ops/evaluate/retail_ops_v1_r4_round2_b_candidate.yaml",
    "retail_ops/build/retail_ops_v1_r4_round2_c_train_export.yaml",
    "retail_ops/build/retail_ops_v1_r4_round2_c_sft.yaml",
    "retail_ops/evaluate/retail_ops_v1_r4_round2_c_base.yaml",
    "retail_ops/evaluate/retail_ops_v1_r4_round2_c_candidate.yaml",
    "retail_ops/build/retail_ops_v1_r4_round3_capacity_prompt_sft.yaml",
    "retail_ops/evaluate/retail_ops_v1_r4_round3_capacity_prompt_candidate.yaml",
    "retail_ops/build/retail_ops_v1_r4_round3_1p7b_attn_sft.yaml",
    "retail_ops/build/retail_ops_v1_r4_round3_1p7b_full_sft.yaml",
    "retail_ops/evaluate/retail_ops_v1_r4_round3_1p7b_base.yaml",
    "retail_ops/evaluate/retail_ops_v1_r4_round3_1p7b_attn_candidate.yaml",
    "retail_ops/evaluate/retail_ops_v1_r4_round3_1p7b_full_candidate.yaml",
)


#: 封存 holdout 与 release 配置。它们**必然**提到 holdout，因此不能套用
#: `_R4_ROUND2_CONFIG_NAMES` 那组「不得引用 holdout」的断言（R3 的既有做法同样把
#: holdout 配置排除在那组之外）。其余治理口径——secret、绝对路径、私有根字面量、
#: 模型 pin——一条不放宽，见 `test_r4_release_configs_hold_the_governance_line`。
_R4_RELEASE_CONFIG_NAMES = (
    "retail_ops/evaluate/retail_ops_v1_r4_holdout_base.yaml",
    "retail_ops/evaluate/retail_ops_v1_r4_holdout_candidate.yaml",
    "retail_ops/release/retail_ops_v1_r4_formal_release.yaml",
)


def test_r4_release_configs_hold_the_governance_line() -> None:
    """holdout / release 配置的治理口径：除"不得提 holdout"外一条不放宽。

    尤其是**私有根路径字面量**——公开配置只能写 receipt/manifest 路径，
    holdout 的私有数据路径由 `--input_dir` 在运行时提供并经
    `authorize_formal_holdout` 校验，绝不写进版本控制的配置文件。
    """
    import yaml

    secret_markers = ("sk-", "Bearer ", "bearer ", "AKIA", "ghp_", "-----BEGIN")
    for name in _R4_RELEASE_CONFIG_NAMES:
        text = _read(f"configs/{name}")
        assert "TEACHER_LLM_" not in text, name
        assert "bfcl" not in text.lower(), name
        parsed = yaml.safe_load(text)
        assert isinstance(parsed, dict)
        for leaf in _iter_leaf_values(parsed):
            assert not leaf.startswith("/"), f"{name}: 疑似绝对路径 {leaf!r}"
            assert "data/private" not in leaf, f"{name}: 疑似私有根路径 {leaf!r}"
            for marker in secret_markers:
                assert marker not in leaf, f"{name}: 疑似 secret 标记 {marker!r}"

        model = parsed.get("model")
        if model is not None:
            assert len(model["revision"]) >= 7, name
            assert model["file_sha256"], name
            for digest in model["file_sha256"].values():
                assert len(digest) == 64, name


def test_every_r4_config_is_enrolled_in_the_governance_scan() -> None:
    """R4 的每一份 config 都必须出现在扫描列表里。

    `_R4_CONFIG_NAMES` 是手工维护的，而治理断言的全部价值取决于它是否完整——
    漏登记一份配置，那份配置就完全不受 secret / 绝对路径 / 私有根 / BFCL / holdout
    检查约束，且没有任何信号。这条测试把"下一个人记得加"换成"忘了加就红"。
    """
    enrolled = set(_R4_CONFIG_NAMES) | set(_R4_ROUND2_CONFIG_NAMES) | set(_R4_RELEASE_CONFIG_NAMES)
    on_disk = {
        f"retail_ops/{path.relative_to(ROOT / 'configs/retail_ops')}"
        for path in (ROOT / "configs/retail_ops").rglob("*.yaml")
        if "_r4_" in path.name
    }

    assert on_disk - enrolled == set(), "有 R4 config 未纳入治理扫描"
    assert enrolled - on_disk == set(), "扫描列表引用了不存在的 R4 config"


def test_r4_round2_configs_hold_the_same_governance_line() -> None:
    """第二轮三份新 config 落在与 R2/R3/R4 第一轮完全相同的治理口径下。"""
    import yaml

    secret_markers = ("sk-", "Bearer ", "bearer ", "AKIA", "ghp_", "-----BEGIN")
    for name in _R4_ROUND2_CONFIG_NAMES:
        text = _read(f"configs/{name}")
        assert "TEACHER_LLM_" not in text, name
        lowered = text.lower()
        assert "bfcl" not in lowered, name
        assert "holdout" not in lowered, name
        parsed = yaml.safe_load(text)
        assert isinstance(parsed, dict)
        for leaf in _iter_leaf_values(parsed):
            assert not leaf.startswith("/"), f"{name}: 疑似绝对路径 {leaf!r}"
            assert "data/private" not in leaf, f"{name}: 疑似私有根路径 {leaf!r}"
            for marker in secret_markers:
                assert marker not in leaf, f"{name}: 疑似 secret 标记 {marker!r} in {leaf!r}"

        if parsed.get("pipeline") == "sft":
            model = parsed["model"]
            assert len(model["revision"]) >= 7, name
            assert model["file_sha256"], name
            for digest in model["file_sha256"].values():
                assert len(digest) == 64, name


def test_r4_round2_export_outputs_stay_ignored() -> None:
    """第二轮两份新导出与训练产物必须仍被既有 `.gitignore` 覆盖。

    终局回复把工具返回的 order_id 写进了训练文本，system 改写会把 prompt 写进去，
    两者都只属于私有训练数据——训练数据永远不进 Git。
    """
    for ignored_path in (
        "data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722/train-export/"
        "train-export-003/sft.jsonl",
        "data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722/train-export/"
        "train-export-004/sft.jsonl",
        "data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722/train-export/"
        "train-export-003/sft_terminal_template.json",
        "data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722/train-export/"
        "train-export-004/sft_system_prompt.json",
        "reports/retail_ops/v1/r4/train-export-003/quality.json",
        "reports/retail_ops/v1/r4/sft-003/adapter/adapter_model.safetensors",
        "reports/retail_ops/v1/r4/sft-004/adapter/adapter_model.safetensors",
        "reports/retail_ops/v1/r4/sft-005/adapter/adapter_model.safetensors",
    ):
        ignored = subprocess.run(
            ["git", "check-ignore", ignored_path],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert ignored.returncode == 0, ignored_path


def _iter_keys(value: object) -> list[str]:
    if isinstance(value, dict):
        keys: list[str] = []
        for key, item in value.items():
            keys.append(str(key))
            keys.extend(_iter_keys(item))
        return keys
    if isinstance(value, list):
        keys = []
        for item in value:
            keys.extend(_iter_keys(item))
        return keys
    return []


def test_service_credentials_never_live_in_the_repo() -> None:
    """服务 API key 只能来自环境变量，且服务层必须把它当作必填参数。

    这是 P1-7 新增自由请求端点的连带治理：新增一个鉴权面时最常见的失败不是
    比较算法写错，而是把 key 顺手写进配置文件、或者给它一个"没配就放行"的
    默认值。两者都由这条测试变成红灯。
    """
    import inspect

    import yaml

    from veritool_rl.product_cli import SERVICE_API_KEY_ENV
    from veritool_rl.retail_ops.serve.service import create_formal_app

    forbidden = {"api_key", "apikey", "api-key", "token", "secret", "password", "credential"}
    for path in sorted((ROOT / "configs").rglob("*.yaml")):
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
        for key in _iter_keys(parsed):
            assert key.lower() not in forbidden, f"{path}: 配置文件不得声明凭据字段 {key!r}"

    assert SERVICE_API_KEY_ENV == "RETAIL_AGENT_OPS_API_KEY"
    parameter = inspect.signature(create_formal_app).parameters["api_key"]
    assert parameter.default is inspect.Parameter.empty, "api_key 不得有默认值"
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY

    service = _read("src/veritool_rl/retail_ops/serve/service.py")
    assert SERVICE_API_KEY_ENV not in service, "服务模块不读环境变量，key 由调用方注入"


def test_ci_and_container_exist_and_do_not_overclaim() -> None:
    """P2-12：`SPEC.md` §11 的"新环境能按文档完成 CPU smoke"要有自动化背书。

    同时锁住诚实口径：仓库当前无 remote，这份 workflow 从未真正运行过，
    因此它自己必须写明这一点，交付文档里也不得出现"CI 已通过"。
    """
    workflow = _read(".github/workflows/ci.yml")
    for step in ("uv sync", "pytest", "ruff check", "mypy", "verify_qualification_chain.py"):
        assert step in workflow, f"CI 缺少步骤：{step}"
    assert "尚未在" in workflow and "运行过" in workflow, "workflow 必须写明它还没真正运行过"

    dockerfile = _read("Dockerfile")
    assert "torch" in dockerfile, "Dockerfile 必须说明为什么不含 torch"
    assert "RUN pip install torch" not in dockerfile
    assert "USER appuser" in dockerfile, "服务不得以 root 运行"

    for name in ("README.md", "docs/SYSTEM_CARD.md", "docs/MODEL_CARD.md", "docs/DEMO.md"):
        text = _read(name)
        assert "CI 已通过" not in text, f"{name}: 不得声称 CI 已通过"


def test_holdout_ledger_is_the_single_source_of_truth() -> None:
    """P2-11：封存 holdout 的观测次数只有一个事实源。

    同一个数字在五个文件里各写一遍必然漂移——2026-08-15 的评审正是从三处仍写着
    "唯一一次观测"发现这一点的。这条测试把"记得同步五个文件"换成"漏引用就红"。
    """
    ledger = _read("docs/HOLDOUT_LEDGER.md")
    for expected in (
        "唯一事实源",
        "LOG-20260811-03",
        "LOG-20260814-04",
        "success_delta",
        "p95_latency_ratio",
        "1.8774",
        "-0.0333".replace("-", "−"),
    ):
        assert expected in ledger, f"台账缺少 {expected!r}"
    assert ledger.count("NO-GO") >= 2, "两次判定都必须留在台账里"

    for name in (
        "README.md",
        "docs/SYSTEM_CARD.md",
        "docs/MODEL_CARD.md",
        "docs/MODEL_CARD_sft-006.md",
        "docs/RESUME_EVIDENCE.md",
        "docs/REPO_MAP.md",
    ):
        assert "HOLDOUT_LEDGER.md" in _read(name), f"{name} 必须引用封存 holdout 台账"

    # 被评审点名的三处漂移表述不得再出现在任何活动文档里
    # （`docs/PROJECT_LOG.md` 是 append-only 历史档案，记录的是当时的事实，不在此列）。
    for name in ("README.md", "docs/SYSTEM_CARD.md", "docs/MODEL_CARD.md", "docs/DEMO.md"):
        text = _read(name)
        assert "唯一一次观测" not in text, f"{name}: 观测次数表述已过期"
        assert "首次也是" not in text, f"{name}: 观测次数表述已过期"


def test_the_strongest_candidate_has_a_model_card() -> None:
    """在封存 holdout 上做到 120/120 的候选必须有自己的模型卡。

    最强的那个 artifact 没有卡，是交付文档最容易出现的空洞。
    """
    card = _read("docs/MODEL_CARD_sft-006.md")
    for expected in (
        "8a49251fbfc9",  # adapter 指纹
        "ae82917e6ee43d0da8fe8418bba1b6b162a958fe",  # code_commit
        "8ae813c4284246b9",  # system_prompt_sha256
        "120/120",
        "p95_latency_ratio",
        "不是泛化证据",
        "只存在于 gpu-5090",  # 产物可得性风险必须写明
    ):
        assert expected in card, f"sft-006 模型卡缺少 {expected!r}"
    assert "HOLDOUT_LEDGER.md" in card


_R45_CONFIG_NAMES = (
    "retail_ops/evaluate/retail_ops_v1_qualification_schema_clean.yaml",
    "retail_ops/evaluate/retail_ops_v1_qualification_schema_perturbed.yaml",
    "retail_ops/release/retail_ops_v1_r45_formal_release_v11.yaml",
    "retail_ops/evaluate/retail_ops_v1_r45_merged_dev_base.yaml",
    "retail_ops/build/retail_ops_v2_build.yaml",
    "retail_ops/build/retail_ops_v2_build_injected.yaml",
    "retail_ops/evaluate/retail_ops_v2_injection_unguarded.yaml",
    "retail_ops/evaluate/retail_ops_v2_injection_guarded.yaml",
    "retail_ops/build/retail_ops_v2_build_clarify.yaml",
    "retail_ops/evaluate/retail_ops_v2_clarify_singleturn.yaml",
    "retail_ops/evaluate/retail_ops_v2_clarify_multiturn.yaml",
    "retail_ops/evaluate/retail_ops_v1_r45_holdout_base.yaml",
    "retail_ops/evaluate/retail_ops_v1_r45_holdout_candidate.yaml",
    "retail_ops/evaluate/retail_ops_v1_r45_holdout_merged.yaml",
    "retail_ops/evaluate/retail_ops_v1_r45b_holdout_base.yaml",
    "retail_ops/evaluate/retail_ops_v1_r45b_holdout_merged_candidate.yaml",
    "retail_ops/build/retail_ops_ood_v1_build.yaml",
    "retail_ops/evaluate/retail_ops_ood_v1_base.yaml",
    "retail_ops/evaluate/retail_ops_ood_v1_merged_candidate.yaml",
)


def test_r45_configs_hold_the_governance_line() -> None:
    """补强轨道新增的三份 config 落在与既有各轮完全相同的治理口径下。"""
    import yaml

    secret_markers = ("sk-", "Bearer ", "bearer ", "AKIA", "ghp_", "-----BEGIN")
    for name in _R45_CONFIG_NAMES:
        text = _read(f"configs/{name}")
        assert "TEACHER_LLM_" not in text, name
        assert "bfcl" not in text.lower(), name
        parsed = yaml.safe_load(text)
        assert isinstance(parsed, dict)
        for leaf in _iter_leaf_values(parsed):
            assert not leaf.startswith("/"), f"{name}: 疑似绝对路径 {leaf!r}"
            assert "data/private" not in leaf, f"{name}: 疑似私有根路径 {leaf!r}"
            for marker in secret_markers:
                assert marker not in leaf, f"{name}: 疑似 secret 标记 {marker!r}"


def test_schema_perturbation_configs_differ_only_by_the_switch() -> None:
    """对照实验的两侧只能差一个变量，否则测的不是 schema 鲁棒性。"""
    import yaml

    clean = yaml.safe_load(
        _read("configs/retail_ops/evaluate/retail_ops_v1_qualification_schema_clean.yaml")
    )
    perturbed = yaml.safe_load(
        _read("configs/retail_ops/evaluate/retail_ops_v1_qualification_schema_perturbed.yaml")
    )

    assert clean["perturb_schema"] is False
    assert perturbed["perturb_schema"] is True
    assert {key: value for key, value in clean.items() if key != "perturb_schema"} == {
        key: value for key, value in perturbed.items() if key != "perturb_schema"
    }


def test_every_qualification_config_declares_the_perturbation_switch() -> None:
    """`perturb_schema` 没有默认值——漏写一份配置就必须红，而不是静默按旧行为跑。"""
    import yaml

    evaluate_root = ROOT / "configs/retail_ops/evaluate"
    for path in sorted(evaluate_root.glob("retail_ops_v1_qualification_*.yaml")):
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "perturb_schema" in parsed, f"{path.name}: 缺少 perturb_schema"
        assert isinstance(parsed["perturb_schema"], bool), path.name


def test_v1_domain_bundle_is_byte_identical_to_the_frozen_evidence() -> None:
    """v1 的四份文件在 `bundle_sha256` 的分量里，而它同时在 dev 与 sealed 的配对字段内。

    v2 的存在不得以"顺手改一下 v1"为代价——那会让全部已有证据不可配对。
    """
    from veritool_rl.retail_ops.domain.bundle import load_bundle

    assert (
        load_bundle(ROOT / "domains/retail_ops/v1").bundle_sha256
        == "8c158a3068731e7015adfde790f9917ddb924fcd5243195a9640c833cca20eeb"
    )


def test_v2_externalises_the_policy_while_v1_keeps_the_frozen_names() -> None:
    """P0-2 的结构性判据：v2 的 rules 必须是可执行规则，v1 必须仍是六个冻结名字。"""
    import yaml

    v1 = yaml.safe_load(_read("domains/retail_ops/v1/policies.yaml"))
    v2 = yaml.safe_load(_read("domains/retail_ops/v2/policies.yaml"))

    assert all(isinstance(rule, str) for rule in v1["rules"])
    assert all(isinstance(rule, dict) for rule in v2["rules"])
    for rule in v2["rules"]:
        assert set(rule) == {"id", "violation", "error", "when"}, rule["id"]
    v2_tools = yaml.safe_load(_read("domains/retail_ops/v2/tools.yaml"))
    refund = next(tool for tool in v2_tools["tools"] if tool["name"] == "refund_order")
    assert "idempotency_key" in refund["parameters"]["required"]


def test_v2_release_thresholds_equal_v1() -> None:
    """新 bundle 版本不是下调门槛的借口：阈值必须逐值相同。"""
    import yaml

    v1 = yaml.safe_load(_read("domains/retail_ops/v1/release.yaml"))
    v2 = yaml.safe_load(_read("domains/retail_ops/v2/release.yaml"))

    thresholds = (
        "success_delta_min",
        "critical_policy_violation_delta_max",
        "invalid_call_count_max",
        "p95_latency_ratio_max",
        "require_complete_evidence",
    )
    assert {key: v1[key] for key in thresholds} == {key: v2[key] for key in thresholds}


def test_injection_configs_differ_only_by_the_guardrail_switch() -> None:
    import yaml

    unguarded = yaml.safe_load(
        _read("configs/retail_ops/evaluate/retail_ops_v2_injection_unguarded.yaml")
    )
    guarded = yaml.safe_load(
        _read("configs/retail_ops/evaluate/retail_ops_v2_injection_guarded.yaml")
    )

    assert unguarded["guardrail"] is False
    assert guarded["guardrail"] is True
    assert {k: v for k, v in unguarded.items() if k != "guardrail"} == {
        k: v for k, v in guarded.items() if k != "guardrail"
    }


def test_third_observation_uses_fresh_attempt_ids_and_the_same_pins() -> None:
    """第三次观测：不得复用前两次的 attempt_id，且模型/receipt/生成参数逐字段相同。

    唯一允许变的是 attempt_id——其余任何差异都会让"这次与上次的差值来自哪里"变得
    无法归因。
    """
    import yaml

    root = ROOT / "configs/retail_ops/evaluate"
    previous = yaml.safe_load(
        (root / "retail_ops_v1_r4_holdout_base.yaml").read_text(encoding="utf-8")
    )
    current = yaml.safe_load(
        (root / "retail_ops_v1_r45_holdout_base.yaml").read_text(encoding="utf-8")
    )
    cand_prev = yaml.safe_load(
        (root / "retail_ops_v1_r4_holdout_candidate.yaml").read_text(encoding="utf-8")
    )
    cand_now = yaml.safe_load(
        (root / "retail_ops_v1_r45_holdout_candidate.yaml").read_text(encoding="utf-8")
    )

    assert current["attempt_id"] == "qwen3-4b-holdout-base-003"
    assert cand_now["attempt_id"] == "qwen3-4b-holdout-candidate-003"
    assert current["attempt_id"] != previous["attempt_id"]
    assert cand_now["attempt_id"] != cand_prev["attempt_id"]
    for key in ("model", "generation", "dataset_version", "holdout_receipt_path", "bundle_dir"):
        assert current[key] == previous[key], key
        assert cand_now[key] == cand_prev[key], key
    assert cand_now["adapter"] == cand_prev["adapter"], "候选必须仍是同一个 sft-006"
    assert "adapter" not in current


def test_the_merged_candidate_lineage_is_recomputable_from_the_config() -> None:
    """合并候选的血统必须能从配置本身复算——这是它取得配对资格的全部依据。

    `merged_revision` 若只是抄进来的一串字符，"这份权重来自那个基座和那个 adapter"
    就只是一句声明。这条测试重算它，并核对模型 pin 的 revision 就是它。
    """
    import yaml

    from veritool_rl.core.agent.qwen import derive_merged_revision

    parsed = yaml.safe_load(
        _read("configs/retail_ops/evaluate/retail_ops_v1_r45b_holdout_merged_candidate.yaml")
    )
    lineage = parsed["merged_from"]

    recomputed = derive_merged_revision(lineage["base_revision"], lineage["adapter_file_sha256"])

    assert recomputed == lineage["merged_revision"]
    assert parsed["model"]["revision"] == recomputed
    assert parsed["pipeline"] == "formal_holdout_merged_candidate"
    assert "adapter" not in parsed, "合并之后已经没有 adapter"
    # 血统声明的 adapter 必须就是第三次观测里那个候选用的 adapter。
    candidate = yaml.safe_load(
        _read("configs/retail_ops/evaluate/retail_ops_v1_r45_holdout_candidate.yaml")
    )
    assert lineage["adapter_file_sha256"] == candidate["adapter"]["file_sha256"]


def test_the_fourth_observation_base_matches_the_third_field_by_field() -> None:
    """第四次的 base 侧除 attempt_id 外必须与第三次逐字段相同。"""
    import yaml

    root = ROOT / "configs/retail_ops/evaluate"
    third = yaml.safe_load((root / "retail_ops_v1_r45_holdout_base.yaml").read_text("utf-8"))
    fourth = yaml.safe_load((root / "retail_ops_v1_r45b_holdout_base.yaml").read_text("utf-8"))

    assert fourth["attempt_id"] == "qwen3-4b-holdout-base-004"
    assert fourth["attempt_id"] != third["attempt_id"]
    for key in third:
        if key == "attempt_id":
            continue
        assert fourth[key] == third[key], key


def test_the_merged_holdout_probe_is_not_a_paired_candidate() -> None:
    """合并版走 base 通道且不带 adapter——它结构上不能进配对判定，配置必须体现这一点。"""
    import yaml

    merged = yaml.safe_load(
        _read("configs/retail_ops/evaluate/retail_ops_v1_r45_holdout_merged.yaml")
    )

    assert merged["pipeline"] == "formal_holdout_base"
    assert "adapter" not in merged
    assert merged["model"]["repo"].startswith("local/")
    assert merged["attempt_id"] == "qwen3-4b-holdout-merged-003"


def test_clarify_configs_differ_only_by_the_simulator_switch() -> None:
    import yaml

    single = yaml.safe_load(
        _read("configs/retail_ops/evaluate/retail_ops_v2_clarify_singleturn.yaml")
    )
    multi = yaml.safe_load(
        _read("configs/retail_ops/evaluate/retail_ops_v2_clarify_multiturn.yaml")
    )

    assert single["user_simulator"] is False
    assert multi["user_simulator"] is True
    assert {k: v for k, v in single.items() if k != "user_simulator"} == {
        k: v for k, v in multi.items() if k != "user_simulator"
    }


def test_qualification_build_configs_declare_both_variant_switches() -> None:
    """`inject` 与 `clarify` 都没有默认值：漏写一份配置必须红。"""
    import yaml

    build_root = ROOT / "configs/retail_ops/build"
    for path in sorted(build_root.glob("retail_ops_v*_build*.yaml")):
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert set(parsed) == {"bundle_dir", "split", "inject", "clarify"}, path.name
        assert isinstance(parsed["inject"], bool) and isinstance(parsed["clarify"], bool)


def test_merged_model_config_declares_a_derived_revision_not_an_upstream_one() -> None:
    """合并产物不得冒充上游 pin。

    它的 `revision` 是由「基座 revision + adapter 逐文件哈希」派生的内容标识，
    `repo` 用 `local/` 前缀表明它不来自任何 Hub 仓库。把基座的 revision 直接抄过来
    会让"这个权重是官方发布的那一份"变成一句假话。
    """
    import yaml

    parsed = yaml.safe_load(
        _read("configs/retail_ops/evaluate/retail_ops_v1_r45_merged_dev_base.yaml")
    )
    model = parsed["model"]

    assert model["repo"].startswith("local/")
    assert model["revision"] != "8cd0101f70cac4f1efcebc979faf483558e39297"
    assert len(model["revision"]) == 64
    assert parsed["pipeline"] == "formal_dev_base", "合并后已无 adapter，必须走 base 通道"
    assert "adapter" not in parsed


def test_release_configs_declare_their_gate_schema_version() -> None:
    """ "这份判定用的是哪套门禁语义"是证据最重要的元数据之一，不能靠默认值。"""
    import yaml

    for path in sorted((ROOT / "configs/retail_ops/release").glob("*.yaml")):
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
        if parsed.get("pipeline") != "formal_release":
            continue
        assert parsed["gate_schema_version"] in {"1.0", "1.1"}, path.name


#: 不受「不得复述观测总数」约束的文件。
#:
#: - `HOLDOUT_LEDGER.md` 是唯一事实源，次数**只能**写在那里；
#: - `PROJECT_LOG.md`、`docs/archive/`、`docs/handoffs/` 记录的是当时的事实，按协议不得改写；
#: - `progress.md` / `findings.md` 是逐次运行的工作台账，同样只记已发生的事。
_COUNT_EXEMPT_FILES = frozenset(
    {
        "docs/HOLDOUT_LEDGER.md",
        "docs/PROJECT_LOG.md",
        "progress.md",
        "findings.md",
    }
)
_COUNT_EXEMPT_PREFIXES = ("docs/archive/", "docs/handoffs/")

_CJK_NUMERAL = "一二三四五六七八九十两"

#: 英文数词。中英文必须用**同一套**规则——2026-08-17 外部审阅第五轮已经因为
#: 「扫描列表覆盖了文件、词表却没覆盖它的语言」抓到过一次；第六轮又在结构化检查上
#: 抓到同一件事：新规则全是 CJK，英文退回到手写黑名单。
_EN_NUMERAL = "one|two|three|four|five|six|seven|eight|nine|ten"

#: 句子**确实在谈封存 holdout** 才受约束。
#:
#: 这一层是关键：不加限定地禁掉「数量 + 次」会误伤大量合法表述
#: （「只观测一次」说的是 OOD 分片、「两次观测间有 9% 波动」是相对比较）。
#: 限定到封存 holdout 之后，剩下的合法需求几乎为零——**次数只该写在台账里**。
_SEALED_SCOPE = re.compile(
    r"封存\s*holdout|sealed\s+holdout|holdout\s*观测|holdout observation", re.IGNORECASE
)

#: 在数**观测/判定**的数量。数违规、数运行、数场景都不算——
#: 「2 次与 7 次政策违规」「同配置两次运行」是读数，不是观测总数。
#:
#: 每个分支都必须把数词捕获成 `num`，允许判定要看的是**紧挨着数词**的那个字。
_OBSERVATION_QUANTITY = re.compile(
    rf"(?P<num>\d+|[{_CJK_NUMERAL}])\s*次\s*[^。\n]{{0,12}}?(?:观测|(?:发布|release)\s*)?判定"
    rf"|(?P<num2>\d+|[{_CJK_NUMERAL}])\s*次\s*[^。\n]{{0,12}}?观测"
    rf"|(?:观测|判定)\s*了?\s*(?P<num3>\d+|[{_CJK_NUMERAL}])\s*次"
    rf"|观测总数\s*(?:为|是)?\s*(?P<num4>\d+|[{_CJK_NUMERAL}])"
    rf"|(?P<num5>\d+|{_EN_NUMERAL})\s+(?:observations?|decisions?)"
    rf"|observed\s+(?:only\s+|just\s+|a\s+total\s+of\s+)?(?P<num6>\d+|{_EN_NUMERAL})\s+times",
    re.IGNORECASE,
)

#: **相对/序数指代是允许的**——「前三次判定都是 NO-GO」描述历史上的头三次，
#: 永远为真，不会过期；「再消耗一次观测」不含总数。
#:
#: 注意这是一个**白名单**，而且只认**紧挨着数词**的那一个字：
#: 上一版把「上」也算进来，于是「封存 holdout **上**跑通了四次发布判定」
#: 因为句中另有一个方位词「上」而被放行。位置比字符集更重要。
_ADJACENT_MARKERS = frozenset("前头第上历另任何各同每本这那")
_NEARBY_MARKERS = ("再", "另")
_EN_MARKERS = re.compile(r"(?:first|another|the)\s*$", re.IGNORECASE)


def _numeral_start(match: re.Match[str]) -> int:
    for name in ("num", "num2", "num3", "num4", "num5", "num6"):
        if match.group(name) is not None:
            return match.start(name)
    return match.start()


def _total_count_offenders(text: str) -> list[str]:
    """找出「在谈封存 holdout 时复述观测/判定总数」的句子。"""
    offenders: list[str] = []
    for match in _OBSERVATION_QUANTITY.finditer(text):
        window = text[max(0, match.start() - 45) : match.end() + 45]
        if not _SEALED_SCOPE.search(window):
            continue
        cursor = _numeral_start(match)
        before = text[max(0, cursor - 6) : cursor]
        if before[-1:] in _ADJACENT_MARKERS:
            continue
        if any(marker in before for marker in _NEARBY_MARKERS):
            continue
        if _EN_MARKERS.search(before):
            continue
        offenders.append(window.strip())
    return offenders


#: **前瞻式序数**：「下一次会是第 N 次」这一类。它必然会在下一次观测之后过期，
#: 而且过期时没有任何机制会提醒——除非像这样把整个形状禁掉。
#: 英文同形（`will be the fifth`）一并拦，否则又是"规则只覆盖一种语言"。
_FORWARD_ORDINAL_PATTERN = re.compile(
    rf"(?:下一次|下次|会是|将是|都是|等于|等同于)[^。\n]{{0,24}}?第\s*(?:\d+|[{_CJK_NUMERAL}])\s*次"
    rf"|(?:will be|would be|is|becomes)\s+the\s+"
    rf"(?:\d+(?:st|nd|rd|th)|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)"
    rf"\s+observation",
    re.IGNORECASE,
)


def _tracked_markdown_files() -> list[str]:
    """从 `git ls-files` 派生扫描范围。

    **这是本组检查与它的前身最重要的差别之一。** 前身维护一份手写的 `checked` 列表，
    于是新增文档默认不在扫描内——2026-08-16 的 `AGENTS.md`/`CLAUDE.md`、
    2026-08-17 的四份 R6 文档、以及 `docs/ENGINE_SUBSTITUTION.md`，都是这样漏掉的。
    **列表是黑名单，`git ls-files` 是全集。**
    """
    listed = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout.split()
    return [
        name
        for name in listed
        if name not in _COUNT_EXEMPT_FILES and not name.startswith(_COUNT_EXEMPT_PREFIXES)
    ]


def _normalized_text(text: str) -> str:
    """去掉 Markdown 强调标记、压缩空白。

    英文不能把空白删掉（`six times` 会变成 `sixtimes`），因此只压缩不删除。
    """
    text = re.sub(r"[*`]+", "", text)
    return re.sub(r"[ \t]+", " ", text)


def _normalized(name: str) -> str:
    return _normalized_text(_read(name))


#: 这条检查**自己的回归语料**。
#:
#: 一个基于模式的检测器需要它自己的测试，否则"它到底拦得住什么"只是一句声称。
#: 下面每一句都来自 2026-08-17 外部审阅第六轮的探测——**它们当时全部漏检**，
#: 其中最刺眼的是英文侧（结构化规则当时全是 CJK）与动宾倒装（"观测了六次"）。
_MUST_BE_CAUGHT = (
    "封存 holdout 至今观测了六次。",
    "封存 holdout 累计观测 6 次。",
    "封存 holdout 的观测总数为 6。",
    "封存 holdout 已消耗五次观测。",
    "整个开发期封存 holdout 只被观测了四次。",
    "封存 holdout 上跑通了四次发布判定。",
    "The sealed holdout has been observed six times.",
    "We consumed 6 observations on the sealed holdout in total.",
    "Of four observations on the sealed holdout, the first three were NO-GO.",
    "The sealed holdout was observed only four times.",
)

#: 反例：这些**必须放行**，否则检查会逼人删掉正确的相对指代。
_MUST_BE_ALLOWED = (
    "封存 holdout 上前三次观测都是 NO-GO。",
    "第六次封存 holdout 观测拿到 GO。",
    "验证它要再消耗一次封存 holdout 观测。",
    "封存 holdout 上同配置两次运行分别有 2 次与 7 次政策违规。",
    "OOD 封存分片只观测一次。",
    "base 侧 p95 在两次观测间有 9% 的波动。",
    "The first three observations on the sealed holdout were all NO-GO.",
)


def test_the_total_count_detector_catches_what_it_claims_to() -> None:
    """**给检测器本身上测试。**

    第六轮外部审阅的原话是：新规则"本质仍是黑名单，只是带了通配符"，
    并用 14 句自然的同类表述探出 **12 句漏检**。修法不是再补几条正则，
    而是把判别式反过来——**限定到"在谈封存 holdout"，白名单化相对/序数形式，
    其余一律禁**——并且把当时漏掉的每一句钉成回归语料。

    没有这一组，"这次真的结构化了"就仍然只是一句声称。
    """
    for sentence in _MUST_BE_CAUGHT:
        assert _total_count_offenders(_normalized_text(sentence)) != [], f"漏检：{sentence}"
    for sentence in _MUST_BE_ALLOWED:
        assert _total_count_offenders(_normalized_text(sentence)) == [], f"误伤：{sentence}"


def test_no_active_doc_predicts_which_observation_comes_next() -> None:
    """**活动文档不得对"下一次观测是第几次"做序数预言。**

    「下一次会是第五次观测」这类句子在下一次观测发生的**当天**就变成假的，
    而且没有任何机制会提醒——2026-08-17 外部审阅第四轮抓到过一次，
    第五轮又在四份文档里抓到（`ENGINE_SUBSTITUTION` / `EXECUTION_PLAN` /
    `INTERVIEW_PREP` / `MODEL_CARD` / `SERVING_FORM_COMPARISON`）。

    禁掉整个形状比逐条追更可靠：**台账只记已经发生的事，文档只引用台账。**
    要表达"这件事需要再消耗一次观测"，就照这么写，不要写它是第几次。
    """
    offenders: list[str] = []
    for name in _tracked_markdown_files():
        text = _normalized(name)
        for match in _FORWARD_ORDINAL_PATTERN.finditer(text):
            start = max(0, match.start() - 20)
            offenders.append(f"{name}: …{text[start : match.end() + 8]}…")
    assert offenders == [], (
        "活动文档预言了下一次观测是第几次。改成「再消耗一次封存 holdout 观测」这类"
        "不带序数的说法——序数会在下一次观测当天过期：\n  " + "\n  ".join(offenders)
    )


#: §3 的定稿 bullet 里，**这些读数一旦出现就必须带着它的对照**。
#:
#: 左边是"好看的那一半"，右边是"没有它就构成挑数字"的那一半。
#: 2026-08-17 外部审阅第六轮把方案 B 改回「117/120、政策违规仅 2 次」
#: （即两次运行里较好的那一次），**全仓 1089 条测试无一变红**——
#: 因为当时的守卫是**文件级**的：同一文件别处还留着 113/120，被挖空的 bullet 就照样过关。
_PAIRED_READINGS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "117/120",
        ("113/120", "113–117/120"),
        "封存 120 条上是同配置两次运行的两个读数，不能只报较好的那次",
    ),
    ("1.0000", ("0.9833",), "分布外封存分片的满分只在第一份素材上，第二份是 0.9833"),
    ("GO", ("0.5833",), "引用 GO 必须同时给出分布外总分"),
    ("expression_ood", ("n=4", "20 条"), "0.00 → 1.00 的样本量是 20 条 = 五子类 × n=4"),
)


def _resume_bullet_variants() -> dict[str, str]:
    """把 §3 的两版定稿 bullet 各自切出来。

    **按变体切、不按文件切**：一版不能借另一版的免责声明过关。
    """
    text = _read("docs/RESUME_EVIDENCE.md")
    section = text.split("## 3. 简历 bullet")[1].split("\n## ")[0]
    variants: dict[str, str] = {}
    for chunk in re.split(r"^### ", section, flags=re.MULTILINE)[1:]:
        head = chunk.splitlines()[0].strip()
        variants[head] = chunk
    assert variants, "§3 里找不到任何一版定稿 bullet"
    return variants


def test_the_resume_bullets_never_quote_a_reading_without_its_companion() -> None:
    """**全仓风险最高的一段文字，必须有机器约束。**

    §3 是要贴到简历上、要在面试里念出口的那一段。此前它与 §2 的「不可写清单」
    之间**没有任何机械关系**——清单躺在同一个文件里，却只靠人记得去看。

    这条按**变体**检查读数配对：好看的数字出现了，它的对照必须在同一版 bullet 里。
    """
    for name, chunk in _resume_bullet_variants().items():
        for reading, companions, why in _PAIRED_READINGS:
            if reading not in chunk:
                continue
            assert any(companion in chunk for companion in companions), (
                f"{name}: 写了「{reading}」却没有 {list(companions)} 中的任何一个——{why}"
            )


def test_the_resume_bullets_never_use_a_phrasing_the_project_forbids() -> None:
    """§2 的「不可写」清单**直接绑到** §3。

    清单第一列里带引号的那些句子是机器完全可读的字符串表，
    把它绑到 §3 是十几行的事——而 2026-08-17 外部审阅第六轮能把
    「120/120 证明模型泛化」「候选可以上线」原样塞进定稿 bullet 而全仓测试全绿。

    **注意这条能挡的边界**：它挡的是**逐字**复用被禁的说法，挡不住改写。
    改写那一半由上面的读数配对检查与人工审阅负责。两条都不是完备的，
    但"完全没有机械约束"与"挡得住逐字复用"之间的差别是实打实的。
    """
    listed = _read("docs/RESUME_EVIDENCE.md").split("## 2. 明确不可写的表述")[1].split("\n## ")[0]
    forbidden = {
        match.group(1).strip()
        for match in re.finditer(r"^\|\s*[\"“]([^\"”]+)[\"”]", listed, re.MULTILINE)
    }
    assert len(forbidden) >= 15, f"只解析出 {len(forbidden)} 条不可写表述，清单解析大概率坏了"

    for name, chunk in _resume_bullet_variants().items():
        used = sorted(phrase for phrase in forbidden if phrase in chunk)
        assert used == [], f"{name} 用了 §2 明令不可写的表述：{used}"


#: 「候选在封存 120 条上**不是满分**」这个事实的语义匹配。
#:
#: 此前两处直接钉字面量 `"117/120"`——那是 LOG-20260817-06 记的失败模式：
#: 读数一旦改成区间（现在是「113–117/120，同配置两次运行」），
#: 测试就会强制一个已经不完整的旧数字。现在断言的是**语义**：
#: 文中必须给出一个分母 120、分子小于 120 的读数。
_NOT_A_PERFECT_SEALED_SCORE = re.compile(r"(?<!\d)(\d{1,3})(?:–(\d{1,3}))?/120")


def _states_the_sealed_score_is_not_perfect(text: str) -> bool:
    for match in _NOT_A_PERFECT_SEALED_SCORE.finditer(text):
        for group in match.groups():
            if group is not None and int(group) < 120:
                return True
    return False


def test_the_overturned_judgement_count_matches_the_table() -> None:
    """「被自己实验推翻的 N 个判断」这个数必须等于那张表实际有几行。

    2026-08-17 外部审阅第五轮发现这里同时存在**四个**不同的值：标题写"七个"、
    表里 8 行、面试话术写"五次"、定稿简历 bullet 写"五个"。
    一个"我很诚实地记录了自己被推翻多少次"的卖点，自己数不清楚，
    是最容易被面试官一句话戳破的地方。

    **绑到表本身**，因此加一行就必须改标题，改不了就红。
    """
    text = _read("docs/RESUME_EVIDENCE.md")

    heading = re.search(r"### 1\.4 被自己实验推翻的 \*\*(\d+)\*\* 个判断", text)
    assert heading is not None, "§1.4 的标题没有写出可核对的条数"
    declared = int(heading.group(1))

    section = text.split("### 1.4 ")[1].split("\n### ")[0]
    rows = [
        line
        for line in section.splitlines()
        if line.startswith("|") and not line.startswith("|---") and "推翻方式" not in line
    ]
    assert declared == len(rows), f"§1.4 标题写 {declared} 个，表里有 {len(rows)} 行"

    # 文中其它处引用同一个数时也必须一致——散落的复述正是上一轮漂移的来源。
    for pattern in (
        r"被自己的实验推翻 \*\*(\d+)\*\* 个判断",
        r"被自己的实验推翻了 (\d+) 次",
    ):
        for match in re.finditer(pattern, text):
            assert int(match.group(1)) == declared, (
                f"§1.4 声称 {declared} 个，但另一处写 {match.group(1)}：{match.group(0)}"
            )


def test_no_active_doc_restates_a_stale_observation_count() -> None:
    """观测次数只能出现在台账里。

    P2-11 的根因不是"有人忘了改"，而是同一个数字散落在多个文件里。第三次观测之后
    立刻又冒出四处"两次观测"——证明只靠人工同步是不行的。这条测试把次数表述本身
    变成受控字符串：活动文档要么引用台账，要么只说"三次"。

    `docs/PROJECT_LOG.md` 与 `docs/archive/`、`docs/handoffs/` 不在此列——它们记录的是
    当时的事实，按 append-only 协议不得改写。
    """
    # 只拦"把总数说成两次"的表述。"前两次观测"这类**相对**指代是合法的——
    # 它描述的是历史上的某两次，不是当前总数。
    stale = (
        "两次观测均已消耗",
        "已消耗两次观测",
        "已消耗 **2 次**观测",
        "封存 holdout 的两次观测",
        "首次也是",
        "唯一一次观测",
        # 2026-08-16 补：第四次观测把总数推到 4，"三次"同样是过期表述。
        # AGENTS.md 此前不在 checked 里，因此"两次"一路留到了 R5 才被发现。
        "已消耗**三次**观测",
        "已消耗三次观测",
        # 2026-08-17 第五次观测之后，"四次"同样成为过期的总数表述。
        "已消耗四次观测",
        "已消耗**四次**观测",
        "四次观测均已消耗",
        # **前瞻式**表述同样会过期，而旧词表只拦总数（外部审阅第四轮指出：
        # 真正变陈旧的恰恰是"下一次会是第五次"这一类）。
        "会是**第五次**观测",
        "会是第五次观测",
        "都是第五次",
        "需要**第五次**封存 holdout 观测",
        "本轮没有观测",
        "本轮**没有**消耗",
        "两次 release 判定",
        "两次发布判定",
        # 2026-08-17 补：`README.en.md` 一直在 `checked` 里，但整张词表全是中文，
        # 于是英文侧的 "Of four observations" / "observed only four times" 一路没被拦。
        # **扫描列表覆盖了文件，词表却没覆盖它的语言**——这是治理有洞的另一种形状。
        "Of four observations",
        "Of five observations",
        "observed only four times",
        "observed only five times",
        "the last observation of the sealed holdout",
        "no further observations",
        # 注意：不拦"前三次判定都是 NO-GO"——那是**相对**指代（历史上的头三次），
        # 与"两次观测均已消耗"这种**总数**表述不同，且它是正确的。
    )
    checked = [
        "README.md",
        "README.en.md",
        "AGENTS.md",
        "CLAUDE.md",
        # 2026-08-16 补：唯一事实源此前**不在**这个列表里，只有表头那一行被断言，
        # 于是正文里"任何新的发布判定都需要第三次观测"一直没被发现。
        # 唯一事实源恰恰是最该被扫描的文件。
        "docs/HOLDOUT_LEDGER.md",
        # 2026-08-17 补（外部审阅第四轮）：这四份都承载 R6 的结论口径，
        # 却都不在扫描里，于是 GENERALIZATION_FIX 的 §7.5 与 §8 相隔十四行互相矛盾。
        "docs/GENERALIZATION_FIX.md",
        "docs/EXECUTION_PLAN.md",
        "docs/READING_THE_NUMBERS.md",
        "docs/OOD_SEALED_LEDGER.md",
        "SPEC.md",
        "docs/SYSTEM_CARD.md",
        "docs/MODEL_CARD.md",
        "docs/MODEL_CARD_sft-006.md",
        "docs/DEMO.md",
        "docs/RESUME_EVIDENCE.md",
        "docs/REPO_MAP.md",
        "docs/SERVING_FORM_COMPARISON.md",
        "docs/AGENT_LOOP.md",
        "docs/DOMAIN_BUNDLE_V2.md",
        "docs/INTERVIEW_PREP.md",
        "docs/REBUILD_VERIFICATION.md",
        "docs/FAULT_MATRIX.md",
    ]
    for name in checked:
        text = _read(name)
        for phrase in stale:
            assert phrase not in text, f"{name}: 过期的观测次数表述 {phrase!r}"

    ledger = _read("docs/HOLDOUT_LEDGER.md")

    # 台账自洽：表头声称的次数必须等于台账里观测小节的数量。
    #
    # 此前这里写的是 `assert "已消耗观测 | **5 次**" in ledger`——一个会在下一次观测后
    # 过期、并且被测试**焊死**的字面值（LOG-20260817-06 的失败模式）。
    # 现在断言的是「唯一事实源自己说的数」与「它自己记了几条」一致，
    # 这条永远不会过期，而且拦得住真正要防的事：跑了观测但没记账。
    declared = re.search(r"已消耗观测 \| \*\*(\d+) 次\*\*", ledger)
    assert declared is not None, "台账表头没有声明观测次数"
    sections = re.findall(r"^## 观测 (\d+) — ", ledger, re.MULTILINE)
    assert int(declared.group(1)) == len(sections), (
        f"台账声称 {declared.group(1)} 次观测，但只记了 {len(sections)} 条：{sections}"
    )
    assert sections == [str(index + 1) for index in range(len(sections))], (
        f"观测编号不连续：{sections}"
    )

    # 历史条目不得改写：早期观测的 LOG 引用必须原样还在。
    for token in ("LOG-20260815-03", "LOG-20260815-04", "LOG-20260817-04"):
        assert token in ledger, token


def test_the_go_is_never_quoted_without_the_ood_reading() -> None:
    """第四次的 GO 与分布外读数必须成对出现。

    一个通过全部自动门禁的候选，在模板外的表达变化上是 0/20 且比零训练基座还差。
    只讲 GO 不讲这个数就是误导——而"记得一起讲"靠人是靠不住的，所以做成测试。
    """
    for name in (
        "README.md",
        "README.en.md",
        "docs/HOLDOUT_LEDGER.md",
        "docs/MODEL_CARD_sft-006.md",
        "docs/RESUME_EVIDENCE.md",
        "docs/INTERVIEW_PREP.md",
        "docs/REBUILD_VERIFICATION.md",
    ):
        text = _read(name)
        if "GO" not in text:
            continue
        # 2026-08-16 加强：原先「提到 OOD_EVALUATION.md 这个文件名」就算过关，
        # 而文件名可以出现在文末的索引表里、离 GO 十万八千里。外部审阅指出这一点。
        # 现在要求**两个具体读数都在场**——它们没法靠一个链接蒙混。
        assert "0.5833" in text, f"{name}: 提到 GO 就必须给出分布外总分 0.5833"
        assert "0/20" in text or "0.00" in text, (
            f"{name}: 提到 GO 就必须给出表达变化类的读数（0/20 或 0.00）"
        )

        # 2026-08-17 再加强：只要求"同一份文件里都出现过"仍然太松——
        # 那两个数可以躲在文末的索引表里，离 GO 十万八千里。
        # 现在要求**同一个二级/三级小节内**共现：读者顺着读的时候必须看得见。
        # 台账本身就是那个"记着它的地方"，不必自我引用。
        if name == "docs/HOLDOUT_LEDGER.md":
            continue

        # 围栏代码块（mermaid 图、命令示例）里的 GO 是**机制标签**，不是结果声称。
        prose = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
        sections = re.split(r"^#{1,6} ", prose, flags=re.MULTILINE)
        for section in sections:
            # 「GO/NO-GO 门禁」是在讲**机制**，不是在声称一个判定结果。
            # 先把这两种写法连同 NO-GO 一起去掉，剩下的 GO 才是"拿到了 GO"。
            claim = re.sub(r"GO\s*/\s*NO-GO|NO-GO", "", section)
            if "GO" not in claim:
                continue
            # 只是引用别处（"见 …GO…"）或列在目录里的小节不强求
            if "0.5833" in section or "分布外" in section or "out-of-distribution" in section:
                continue
            head = section.splitlines()[0] if section.splitlines() else ""
            assert "HOLDOUT_LEDGER" in section or "OOD" in section or "台账" in section, (
                f"{name} 的小节「{head[:40]}」提到 GO，却既没有给分布外读数、也没有指向记着它的台账"
            )

    ood = _read("docs/OOD_EVALUATION.md")
    for expected in ("0.5833", "0.2167", "expression_ood", "code_switch", "LOG-20260816-01"):
        assert expected in ood, expected
    # 边界必须写在文档里，不能只在提交信息里
    # 两条最容易在引用时被丢掉的边界：模板是作者手写的（不是 LLM 改写），
    # 以及这个集合不封存（用它选候选就等于开始过拟合它）。
    assert "作者手写" in ood
    assert "它不是封存集合" in ood


def test_the_english_readme_agrees_with_the_chinese_one() -> None:
    """双语文档最容易的失效方式是"英文版落后一个版本"。

    不做逐句翻译比对（那不现实），而是断言两边**同一组关键数字**都在。
    任一边更新了结论而另一边没跟上，这条就会红。
    """
    zh = _read("README.md")
    en = _read("README.en.md")

    shared_numbers = (
        "120/120",  # 第二/三/四次观测的候选读数
        "1.8774",  # 被拒的那个 p95 比值
        "1.1265",  # 拿到 GO 的那个 p95 比值
        "0.5833",  # 分布外总分
        "0/20",  # 分布外表达变化类
        "58/60",  # 同 seed 重建
        "54/60",  # 零训练 base
        "99.2%",  # teacher 通过率
        "$0.055",  # teacher 成本
        "163/200",  # BFCL legacy
        "167/200",
    )
    for number in shared_numbers:
        assert number in zh, f"README.md 缺少关键数字 {number}"
        assert number in en, f"README.en.md 缺少关键数字 {number}"

    # 两份都必须互相指向对方，否则读者会停在其中一份
    assert "README.en.md" in zh
    assert "README.md" in en


def test_the_english_readme_keeps_the_same_boundaries() -> None:
    """英文版不得因为"翻译时太长"而丢掉边界。"""
    en = _read("README.en.md")
    for claim in (
        'not "ready to ship."',
        "not generalisation",
        "never actually run",
        "an official BFCL score",
        "not comparable across runs",
    ):
        assert claim in en, f"README.en.md 缺少边界表述：{claim}"


def test_there_is_exactly_one_five_minute_script() -> None:
    """同一份讲稿存在两处就一定会漂。

    `DEMO.md` 原来有一份 R3 时期的五分钟讲稿，结论停在"NO-GO、回滚基座"，
    而此后又发生了三次观测、一个 GO、一次分布外评测和一次重建复验。
    现在讲稿只在 `INTERVIEW_PREP.md`，`DEMO.md` 只保留演示流程。
    """
    demo = _read("docs/DEMO.md")
    prep = _read("docs/INTERVIEW_PREP.md")

    assert "## 1. 五分钟讲解（约 750 字，按段落计时）" in prep
    assert "已迁出本文件" in demo
    assert "INTERVIEW_PREP.md" in demo
    # DEMO 不得再自带时间轴段落（那是讲稿的形状）
    for timeline_marker in ("0:00–0:40", "2:40–4:00", "4:00–5:00"):
        assert timeline_marker not in demo, f"DEMO.md 又长回了一份讲稿：{timeline_marker}"
    # DEMO 保留的是流程
    for kept in ("纯 CPU 全链路演示", "真实模型服务演示", "必须一起讲的失败案例"):
        assert kept in demo, kept


def test_the_documented_test_count_matches_reality() -> None:
    """文档里的测试数是最容易悄悄过期的数字之一。

    这个项目在 R5 之前已经有过 698 / 884 / 885 / 901 / 907 五个版本散落在不同文档里。
    与其每次手改，不如把它绑到 pytest 实际收集到的数量上：改了测试忘了改文档，这条就红。
    """
    # 用**当前解释器**跑，不要往 PATH 前面硬塞 `ROOT/.venv/bin`：
    # 那个目录在一个干净 clone 上并不存在，于是这条测试会以"找不到 python"失败，
    # 而它报出来的却像是"文档数字对不上"（2026-08-17 外部审阅第六轮在 clone 上撞到）。
    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=300,
    )
    match = re.search(r"(\d+) tests collected", collected.stdout)
    assert match is not None, f"无法从 pytest 输出里解析收集数：{collected.stdout[-500:]}"
    actual = int(match.group(1))

    for name in ("README.md", "README.en.md", "CLAUDE.md", "docs/RESUME_EVIDENCE.md"):
        text = _read(name)
        # 三种写法都要覆盖：`**N tests passed**`、`**N** tests passed`、以及
        # **中文的 `**N** 项测试`**——最后这种此前没被覆盖，于是定稿简历 bullet 里的
        # 「936 项测试」一直停在一个旧值上，而那是最会被雇主读到的一句话
        # （2026-08-17 外部审阅指出）。
        documented = re.findall(
            r"\*\*(\d+)\*\*? tests passed|\*\*(\d+) tests passed\*\*|\*\*(\d+)\*\* 项测试",
            text,
        )
        flat = [int(value) for pair in documented for value in pair if value]
        assert flat, f"{name}: 找不到「N tests passed」形式的工程基线数字"
        for value in flat:
            assert value == actual, (
                f"{name}: 文档写 {value} tests，实际收集 {actual}。"
                f"改了测试就要同步这个数字（或者别在文档里写死它）。"
            )


def test_the_author_environment_baseline_never_appears_without_the_clean_clone_one() -> None:
    """写"N tests passed 全绿"的地方，必须同时写干净 clone 上的真实基线。

    2026-08-17 外部审阅第六轮把仓库 clone 到独立目录跑了一遍：**6 failed**，
    而 README 与定稿简历 bullet 写着"全绿"。数字本身没造假（作者环境确实全过），
    但**没有任何一处披露这个差异**——面试官拿到仓库的第一个动作就是 clone + pytest。

    那 6 条已经修掉（缺产物改为 skip 并说明原因、一条硬编码 venv 路径的真 bug 已改），
    现在干净 clone 是 0 failed。**但"两个环境跑出不同数字"这件事本身仍然要说**，
    这条测试就是防止那句披露在下一次改文档时被顺手删掉。
    """
    for name in ("README.md", "README.en.md", "CLAUDE.md", "docs/RESUME_EVIDENCE.md"):
        text = _read(name)
        if not re.search(
            r"\*\*\d+\*\*? tests passed|\*\*\d+ tests passed\*\*|\*\*\d+\*\* 项测试", text
        ):
            continue
        assert "干净 clone" in text or "clean clone" in text, (
            f"{name}: 写了作者环境的测试基线，却没有给出干净 clone 上的基线。"
            f"两者不同是事实，藏起来会在面试官 clone 的三分钟内被撞见"
        )


def test_the_two_teacher_batches_are_never_conflated() -> None:
    """teacher 有两批付费采集，把它们的数字焊在一起是本项目最贵的一类文档缺陷。

    批次 1 `teacher-smoke-001`：519 次请求 / $0.055 / 211-240 = 87.9%（LOG-20260806-06）
    批次 2 `teacher-full-001`： 526 次请求 / $0.0559 / 238/240 = 99.2%（LOG-20260806-12）

    2026-08-16 的外部审阅发现 README 把批次 2 的通过率与批次 1 的请求数和成本写在
    同一格里，而且**没有任何文档给出两批的总计**。修完之后我自己又漏了 5 处——
    所以这条不靠人工检查，靠断言：凡是出现批次 1 成本的地方，必须同时出现批次 2 的
    成本或两批总计，否则就是又焊回去了。
    """
    # `$0.055` 是 `$0.0559` 的子串，直接用 `in` 会让「只写了批次 2」的文件也被判为
    # 「提到了批次 1」。用正则要求 `$0.055` 后面**不是**数字，才是真的批次 1 成本。
    batch1_cost = re.compile(r"\$0\.055(?![0-9])")
    batch2_cost = "$0.0559"
    total_cost = "$0.111"

    for name in (
        "README.md",
        "README.en.md",
        "docs/RESUME_EVIDENCE.md",
        "docs/SYSTEM_CARD.md",
        "docs/INTERVIEW_PREP.md",
        "docs/EXECUTION_PLAN.md",
    ):
        text = _read(name)
        if not batch1_cost.search(text):
            continue
        assert batch2_cost in text or total_cost in text, (
            f"{name}: 出现了批次 1 的成本 $0.055 却没有批次 2 的成本或两批总计——"
            f"这正是把两批数字焊在一起的形态"
        )

    # 唯一取数口径必须把两批和总计都写全
    evidence = _read("docs/RESUME_EVIDENCE.md")
    assert batch1_cost.search(evidence), "docs/RESUME_EVIDENCE.md 缺少批次 1 的成本 $0.055"
    for required in (batch2_cost, total_cost, "519", "526", "1045", "87.9%", "99.2%"):
        assert required in evidence, f"docs/RESUME_EVIDENCE.md 缺少 teacher 采集的 {required}"


def test_the_container_claim_is_specific_and_reproducible() -> None:
    """容器这条声明必须带可复核的细节，而不是"我们有个 Dockerfile"。

    2026-08-16 之前 `Dockerfile` 的注释写着镜像是"几十 MB"——那是个从未构建过的估计，
    实测 1.05 GB，差一个数量级。凡是文档里的数字都得是量出来的，容器不例外。
    """
    dockerfile = _read("Dockerfile")
    assert "1.05 GB" in dockerfile, "Dockerfile 必须记录实测镜像体积"
    assert "--network none" in dockerfile, "必须记录它是在断网下验证的"
    assert "几十 MB" not in dockerfile.split("已更正")[-1], "旧的未验证估计不得留在结论里"

    for name in ("README.md", "README.en.md"):
        text = _read(name)
        assert "--network none" in text, f"{name}: 容器验证必须写明是断网跑的"
        assert "1.05 GB" in text, f"{name}: 容器体积必须是实测值"


def test_the_numbers_guide_covers_every_suspiciously_perfect_number() -> None:
    """用户提的一条真问题：满分太多会让人怀疑。

    对策不是把数字改小，而是**每个满分旁边都摆出它不好看的那一半**。
    这条测试锁住那份指南确实逐个覆盖了它们——漏掉一个，就等于默认它不需要解释。
    """
    guide = _read("docs/READING_THE_NUMBERS.md")

    for number in ("120/120", "1.0000", "99.2%", "87.9%", "0.5833", "0/20", "58/60", "0.00"):
        assert number in guide, f"读数指南没有解释 {number}"

    # 2026-08-17 外部审阅：**被引用最多的那个高分反而漏了**。
    # `expression_ood` 0.00 → 1.00 出现在 README、RESUME_EVIDENCE、CLAUDE、EXECUTION_PLAN
    # 四处，而指南只解释了作为"低得可疑"的 0.00，没解释涨上去的 1.00。
    # 它的样本量（20 条 = 五子类 × n=4）也必须一起写。
    assert "0.00 涨到 1.00" in guide or "`expression_ood` 从 0.00 涨到 1.00" in guide
    assert "n=4" in guide, "expression_ood 的子类样本量必须写明"
    assert _states_the_sealed_score_is_not_perfect(guide), (
        "封存 holdout 上并非满分，这一条必须在场（给出一个分子小于 120 的 N/120 读数）"
    )

    # 每个高分都必须配一个「旁边那个不好看的数」
    for pairing in ("旁边那个不好看的数", "不能支持什么", "哪些数字低得可疑"):
        assert pairing in guide, pairing

    # 不得只解释好消息
    assert "反过来" in guide
    for name in ("README.md", "docs/RESUME_EVIDENCE.md"):
        assert "READING_THE_NUMBERS" in _read(name), f"{name} 未指向读数指南"


def test_the_generalisation_fix_is_never_quoted_without_its_cost() -> None:
    """R6 的收益与代价来自**同一个改动**，只报一半是误导。

    与 `test_the_go_is_never_quoted_without_the_ood_reading` 同一个形状：
    这类「好消息旁边必须有坏消息」的约束靠人记是靠不住的。
    """
    for name in (
        "README.md",
        "README.en.md",
        "docs/GENERALIZATION_FIX.md",
        "docs/RESUME_EVIDENCE.md",
        "docs/READING_THE_NUMBERS.md",
        "docs/EXECUTION_PLAN.md",
        "CLAUDE.md",
    ):
        text = _read(name)
        # **极性必须是「提到收益 -> 断言代价在场」。**
        # 2026-08-17 的外部审阅指出，第一版把两者用 and 连起来当触发条件：
        #   mentions_gain = "1.0000" in text and ("0.8667" in text or "0.00 → 1.00" in text)
        # 于是一份只写 `1.0000` 而删掉代价的文档，`mentions_gain` 为 False、
        # 直接被 continue 跳过——**守卫只在它要防的东西已经不存在时才触发**。
        # 参照同文件里 R4.5 那条（`if "GO" not in text: continue`）的正确形状重写。
        gain_markers = ("1.0000", "0.00 → 1.00", "0.8667")
        if not any(marker in text for marker in gain_markers):
            continue

        # **代价必须是量化的读数，不是"政策违规"这四个字。**
        # 2026-08-17 外部审阅第五轮指出：旧的 `cost_markers` 里有「政策违规」，
        # 而这四个字在这些文档里到处都是，于是断言退化成"文件里出现过这个词"——
        # 它给了作者"有测试兜着"的错觉，而定稿简历 bullet 里恰恰出现了
        # 只报较好那次读数的写法，**这条测试全程是绿的**。
        # 现在要求的是**具体的坏数字**：安全代价的两次读数、或分布外那一类的退化值。
        cost_markers = (
            "7 次",  # 封存 120 条上那次运行的政策违规数（较差的一次）
            "113/120",  # 同上，任务成功率
            "2 与 7",  # 两次运行并列的写法
            "2 and 7",
            "0.75 → 0.60",  # OOD v1 的 scenario_ood 退化
            "0.75 → **0.60**",
            "partial_refund",
        )
        assert any(marker in text for marker in cost_markers), (
            f"{name}: 提到了 R6 的收益（{[m for m in gain_markers if m in text]}）"
            f"却没有给出任何一个**量化**的代价读数。"
            f"「政策违规」这四个字不算——它在这些文档里到处都是。"
        )


def test_the_ledger_discloses_distinct_phrasings_not_just_task_counts() -> None:
    """封存分片的逐风格样本量必须披露**去重后的措辞数**，不能只写任务数。

    2026-08-17 外部审阅第六轮自己按 `phrasing_id` 去重后发现：
    bank-003 的 60 条任务只用到 **35 条不同措辞**，而 `terse` 那一格
    **只有 1 条措辞配了 4 个订单号**。台账当时特意点名表扬「`terse` 4/4 全对」——
    对「没见过的措辞」这个命题，那句话的证据是 n=1，不是 n=4。

    这个项目在披露最小格样本量上是全仓最讲究的地方之一，恰恰在这里少披露了一层。
    这条测试把披露的数字**绑到真实产物上**：改了分片却忘了改表，它会红。
    """
    from veritool_rl.retail_ops.build.phrasing_bank import intent_index, load_phrasing_bank
    from veritool_rl.retail_ops.domain.ood_v2_tasks import build_ood_v2_tasks

    ledger = _read("docs/OOD_SEALED_LEDGER.md")
    assert "不同措辞数" in ledger, "台账只写了任务数，没有披露去重后的措辞数"

    bank_path = (
        ROOT
        / "data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722"
        / "phrasing/phrasing-bank-003/phrasings.jsonl"
    )
    if not bank_path.is_file():
        pytest.skip("措辞池是 ignored 私有产物，未同步到本机时跳过")

    tasks = build_ood_v2_tasks(intent_index(load_phrasing_bank(bank_path), "ood_sealed"))
    distinct = len({task.metadata["phrasing_id"] for task in tasks})
    per_style: dict[str, set[str]] = {}
    for task in tasks:
        per_style.setdefault(str(task.metadata["ood_kind"]), set()).add(
            str(task.metadata["phrasing_id"])
        )
    smallest = min(len(ids) for ids in per_style.values())

    assert f"只用到 {distinct} 条不同措辞" in ledger, (
        f"台账写的去重措辞总数与实际（{distinct}）对不上"
    )
    assert f"真实最小格是 **n={smallest}**" in ledger, f"台账写的最小格与实际（n={smallest}）对不上"


def test_the_sealed_partition_has_a_ledger_not_just_a_sentence() -> None:
    """「只观测一次」不能只是一句写在 Markdown 里的话。

    2026-08-17 的外部审阅指出：120 条 holdout 有 `HOLDOUT_LEDGER.md`，
    而承载头条结果的 OOD 封存分片只有一句 `assert "只观测一次" in fix`——
    「承载结论的证据，其治理级别不能低于它所支撑的结论的分量」。
    现在它有自己的台账，规矩与 holdout 台账同规格。
    """
    ledger = _read("docs/OOD_SEALED_LEDGER.md")

    # 台账必须是唯一事实源，且记着退役分片与变更规则
    assert "唯一事实源" in ledger
    assert "退役记录" in ledger
    assert "历史条目不得改写" in ledger

    # **一份素材只观测一次**——断言的是这条规矩的语义，不是某个次数的字面值。
    # 此前这里写的是 `assert "已消耗观测 | **1 次**" in ledger`：第二个分片被观测后
    # 那句话就过期了，而测试会把它焊死（LOG-20260817-06 的同一个失败模式）。
    sections = re.findall(r"^## 观测 \d+ — .*?（`(phrasing-bank-\d+)`", ledger, re.MULTILINE)
    assert sections, "台账里找不到任何一条观测记录"
    assert len(sections) == len(set(sections)), f"同一份措辞池被观测了多次：{sections}"

    # 每条观测小节都必须带可核对的 run_id 与 code_commit——这条同样是结构性的，
    # 不依赖具体是哪几个哈希。
    bodies = re.split(r"^## ", ledger, flags=re.MULTILINE)[1:]
    for body in bodies:
        if not body.startswith("观测 "):
            continue
        assert "run_id" in body and "code_commit" in body, body.splitlines()[0]
        assert len(re.findall(r"`[0-9a-f]{12,}…?`|`[0-9a-f]{7,}`", body)) >= 3, (
            f"{body.splitlines()[0]}：观测记录里的可核对标识不足三个"
        )

    # 历史条目不得改写：第一条观测的标识必须原样还在。
    for token in ("b4717d43bcb2", "b8b646cb6ba8", "15c8875b1172", "7dfd4ef"):
        assert token in ledger, token

    fix = _read("docs/GENERALIZATION_FIX.md")
    assert "OOD_SEALED_LEDGER.md" in fix, "结论文档必须指向台账"
    assert "只观测一次" in fix
    assert "运行内容在观测前固定" in fix


def test_the_ood_v2_state_space_claim_is_not_overstated() -> None:
    """「唯一自变量是说法」这句话曾经是假的，改正过程必须留在文档里。

    第一版的状态空间比训练/dev 更窄（1 个订单 vs 1–5、1 种余量 vs 7、3 种状态 vs 7），
    而四个文件都写着「业务逻辑完全相同」。这条测试确保那次更正没有被悄悄抹掉——
    项目对「被自己实验推翻的判断」一向留档，被外部审阅推翻的同样要留。
    """
    fix = _read("docs/GENERALIZATION_FIX.md")
    assert "那句话是假的" in fix
    assert "不是我自己发现的" in fix
    ledger = _read("docs/OOD_SEALED_LEDGER.md")
    assert "退役原因（不是因为读数不好看）" in ledger


def test_the_transfer_check_is_labelled_as_never_used_for_selection() -> None:
    """独立迁移检查的价值来自「没被用来选过」，这一点必须显式声明。"""
    for name in ("docs/GENERALIZATION_FIX.md", "docs/OOD_EVALUATION.md"):
        text = _read(name)
        assert "从未用于" in text or "不得用于任何候选选择" in text, name


def test_r6_states_the_current_release_boundary() -> None:
    """R6 候选**已经**通过发布门禁，所以边界从「还没测」变成「测了但不等于可上线」。

    这条测试上一版把一句**已经变假**的话钉住了：它断言
    `"封存 120 条 holdout 本轮**没有观测**" in fix`，而第五次观测在那之前就跑完了。
    结果是 `GENERALIZATION_FIX.md` 的 §7.5（拿到 GO）与 §8（本轮没有观测）
    相隔十四行互相矛盾，**而测试在保护错的那一半**。
    2026-08-17 外部审阅第四轮指出——「比名不副实更糟：它在强制一个谎言」。

    现在断言的是**当前**边界，且刻意不用字符串黑名单：黑名单只会逼出绕过它的措辞
    （审阅指出 §7.5 的「…上拿到 **GO**」正是绕过了旧黑名单）。
    """
    fix = _read("docs/GENERALIZATION_FIX.md")

    # 边界一：通过门禁 ≠ 可以上线，且必须给出「不是满分」这个事实
    assert "通过了发布门禁 ≠ 可以上线" in fix
    assert _states_the_sealed_score_is_not_perfect(fix), (
        "拿到 GO 的候选不是满分，这一条必须在场（给出一个分子小于 120 的 N/120 读数）"
    )

    # 边界二：观测次数不再是硬约束，但纪律不变——两句都必须在场，
    # 只说前半句会读成「随便测」，只说后半句会与台账的当前状态冲突。
    assert "观测次数不再是硬约束" in fix
    assert "永远不得反馈进开发" in fix

    # 反向：那句已经变假的话不得再出现在任何活动文档里
    for name in (
        "README.md",
        "docs/GENERALIZATION_FIX.md",
        "docs/EXECUTION_PLAN.md",
        "docs/RESUME_EVIDENCE.md",
    ):
        text = _read(name)
        assert "封存 120 条 holdout 本轮**没有观测**" not in text, name


def test_the_per_style_sample_sizes_are_disclosed() -> None:
    """「七种风格全部 1.00」的证据强度取决于最小的那一格，n 必须写在旁边。

    2026-08-17 外部审阅第四轮：措辞由哈希分片决定，各风格条数从 2 到 21 不等，
    `terse` 一条都没有——而「八种/七种全部满分」是头条表述。
    """
    ledger = _read("docs/OOD_SEALED_LEDGER.md")
    assert "逐风格样本量" in ledger
    assert "`terse` 一条都没有" in ledger
    assert "n=2 基本没有信息量" in ledger
    assert "逐风格不是" in ledger
