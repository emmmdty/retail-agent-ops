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

    assert "当前阶段：`R4` 失败驱动优化" in agents
    assert "R2 已完成方案审批" in agents
    assert "正式数据、API、模型下载、SSH 和每条 GPU 命令仍需分别确认" in agents
    # 候选结论必须以 dev / holdout 口径分别陈述，不得被写成 release 判定
    assert "不得把 dev 读数写成 release 判定" in agents
    # 封存 holdout 的消耗状态是不可逆资源，必须在接管文档里显式可见
    assert "封存 holdout 的两次观测均已消耗" in agents
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
    )
    checked = [
        "README.md",
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
    ]
    for name in checked:
        text = _read(name)
        for phrase in stale:
            assert phrase not in text, f"{name}: 过期的观测次数表述 {phrase!r}"

    ledger = _read("docs/HOLDOUT_LEDGER.md")
    assert "已消耗观测 | **4 次**" in ledger
    assert "LOG-20260815-03" in ledger
    assert "LOG-20260815-04" in ledger


def test_the_go_is_never_quoted_without_the_ood_reading() -> None:
    """第四次的 GO 与分布外读数必须成对出现。

    一个通过全部自动门禁的候选，在模板外的表达变化上是 0/20 且比零训练基座还差。
    只讲 GO 不讲这个数就是误导——而"记得一起讲"靠人是靠不住的，所以做成测试。
    """
    for name in (
        "README.md",
        "docs/HOLDOUT_LEDGER.md",
        "docs/MODEL_CARD_sft-006.md",
        "docs/RESUME_EVIDENCE.md",
    ):
        text = _read(name)
        if "GO" not in text:
            continue
        assert "OOD_EVALUATION.md" in text or "0.5833" in text, (
            f"{name}: 提到 GO 就必须同时给出分布外读数"
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
