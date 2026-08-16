"""P1-6 方案 A：user simulator + 需澄清的多轮场景。

评审口径：Agent 本体是 3 工具、**单轮用户请求**、最多 5 步的最小 ReAct 循环，
没有 user simulator、没有澄清轮；而 `docs/PRODUCT_BRIEF.md` 自己把 τ²-bench 列为
最接近的参照——"τ² 有 user simulator 和多轮政策冲突，你为什么没有"是必问题。

两条设计约束在这里被锁住：

1. **模拟器是规则式且确定性的。** 评测契约要求可重放：LLM 模拟用户会让每次运行的
   用户侧输入都不同，`replay_trajectory` 直接失效。
2. **默认关闭**，且**只有真正收尾的那一句才算最终答复**——把一次澄清提问记成最终
   答复会让 INFORM/DENY 类任务凭一句反问就判成功。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from veritool_rl.core.agent.user_simulator import (
    ORDER_ID_REPLY,
    ScriptedRetailUserSimulator,
    looks_like_a_question,
)
from veritool_rl.core.trajectory import ExpectedDecision, TaskScenario, TaskSpec
from veritool_rl.retail_ops.build.manifests import build_qualification

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_REL = Path("domains/retail_ops/v2")


def _task(order_id: str = "O-ABC123456789") -> TaskSpec:
    state = {"customer_id": "C-1", "current_day": 20, "orders": {}}
    return TaskSpec(
        task_id="t-1",
        split="qualification",
        scenario=TaskScenario.LOOKUP_STATUS,
        user_request="我想查一下我那笔订单现在到哪了。",
        initial_state=state,
        target_state=state,
        expected_decision=ExpectedDecision.INFORM,
        metadata={"order_id": order_id, "clarification": {"withheld": "order_id"}},
    )


# ---------------------------------------------------------------------------
# 模拟器语义
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "请问您要处理的是哪一个订单？",
        "麻烦提供一下订单号。",
        "请告知订单号",
        "Which order would you like me to refund?",
    ],
)
def test_questions_are_recognised(message: str) -> None:
    assert looks_like_a_question(message) is True


@pytest.mark.parametrize(
    "message",
    ["已为您办理退款。", "订单已于三日前送达。", "该订单已超过退款期限，无法退款。"],
)
def test_terminal_answers_are_not_mistaken_for_questions(message: str) -> None:
    """保守取向：不像提问就当收尾。误判会让 episode 无谓跑到步数上限。"""
    assert looks_like_a_question(message) is False


def test_the_user_answers_only_what_a_user_would_know() -> None:
    simulator = ScriptedRetailUserSimulator()

    reply = simulator.reply("请问是哪一个订单？", _task())

    assert reply == ORDER_ID_REPLY.format(order_id="O-ABC123456789")


def test_a_terminal_answer_ends_the_conversation() -> None:
    simulator = ScriptedRetailUserSimulator()

    assert simulator.reply("已为您办理退款。", _task()) is None


def test_the_number_of_replies_is_capped() -> None:
    """模型可能反复提问，而步数预算是评测契约的一部分——不是无限对话。"""
    simulator = ScriptedRetailUserSimulator(max_replies=1)
    task = _task()

    first = simulator.reply("请问是哪一个订单？", task)
    second = simulator.reply("请问是哪一个订单？", task)

    assert first is not None
    assert second is None
    assert simulator.questions_seen == 2


def test_the_simulator_is_deterministic() -> None:
    """同一句提问必须永远得到同一句回答，否则多轮轨迹无法逐字节重放。"""
    task = _task()

    replies = [ScriptedRetailUserSimulator().reply("请问是哪一个订单？", task) for _ in range(3)]

    assert len(set(replies)) == 1


# ---------------------------------------------------------------------------
# 端到端：多轮通道是否真的接通
# ---------------------------------------------------------------------------


def _run(tmp_path: Path, *, clarify: bool, simulator: bool) -> dict[str, Any]:
    from veritool_rl.retail_ops.evaluate.evaluation import EvaluationMode, evaluate_retail_ops

    root = tmp_path / f"{int(clarify)}{int(simulator)}"
    shutil.copytree(REPO_ROOT / V2_REL, root / V2_REL)
    build_qualification(root / V2_REL, 0, root / "build", clarify=clarify)
    evidence = evaluate_retail_ops(
        bundle_dir=root / V2_REL,
        build_dir=root / "build",
        policy_type="message_grounded",
        config={
            "bundle_dir": str(V2_REL),
            "mode": "qualification",
            "policy_type": "message_grounded",
            "bootstrap_samples": 8,
            "parser_id": "hermes-single-call-v1",
            "budget": {"max_steps": 5},
            "perturb_schema": False,
            "guardrail": False,
            "user_simulator": simulator,
        },
        seed=0,
        output_dir=root / "out",
        mode=EvaluationMode.QUALIFICATION,
    )
    return dict(evidence.metrics)


def test_the_multi_turn_channel_is_what_closes_the_gap(tmp_path: Path) -> None:
    """三组对照缺一不可。

    只跑"开了模拟器之后 12/12"是不够的——那条断言在策略本来就能做对时也会通过。
    必须同时证明：(a) 该策略在不欠指定的任务上本来就能做对；(b) 欠指定 + 无多轮时
    它一条都做不成；(c) 接上多轮之后恢复。三者一起才说明差值来自多轮通道本身。
    """
    control = _run(tmp_path, clarify=False, simulator=False)
    gap = _run(tmp_path, clarify=True, simulator=False)
    closed = _run(tmp_path, clarify=True, simulator=True)

    # (a) 对照组：任务本身是可解的
    assert control["clarification_task_count"] == 0
    assert control["task_success"] == 1.0

    # (b) 缺口是真的：问了，但没人回答
    assert gap["clarification_task_count"] == 12
    assert gap["clarification_asked_count"] == 12
    assert gap["task_success"] == 0.0
    assert gap["average_turns"] == 1.0

    # (c) 接上多轮之后恢复，且轮次真的变多了
    assert closed["task_success"] == 1.0
    assert closed["clarification_rate"] == 1.0
    assert closed["average_turns"] > gap["average_turns"]
    assert closed["user_simulator_enabled"] is True
    # 多轮轨迹必须仍可逐字节重放——重放条件要与运行条件对齐。
    assert closed["replayable_rate"] == 1.0


def test_a_clarifying_question_does_not_count_as_a_terminal_answer(tmp_path: Path) -> None:
    """否则 INFORM/DENY 类任务凭一句反问就判成功。"""
    gap = _run(tmp_path, clarify=True, simulator=False)

    assert gap["task_success"] == 0.0, "反问不得被记成最终答复"


def test_clarification_metrics_are_zero_without_underspecified_tasks(tmp_path: Path) -> None:
    control = _run(tmp_path, clarify=False, simulator=True)

    assert control["clarification_task_count"] == 0
    assert control["clarification_rate"] == 0.0
    assert control["task_success"] == 1.0, "模拟器不得影响不需要澄清的任务"
