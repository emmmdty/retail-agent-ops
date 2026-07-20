"""验证求职工程定位和 Agent 接管文档不会静默漂移。"""

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
