"""Policy 解析与 AgentRunner 闭环测试。"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any


def test_qwen_parser_accepts_one_hermes_tool_call() -> None:
    from veritool_rl.core.agent.parser import parse_qwen_response

    output = parse_qwen_response(
        '<tool_call>\n{"name":"get_order","arguments":{"order_id":"O-1"}}\n</tool_call><|im_end|>'
    )

    assert output.parse_error is None
    assert output.tool_call is not None
    assert output.tool_call.name == "get_order"
    assert output.tool_call.arguments == {"order_id": "O-1"}


def test_qwen_parser_rejects_multiple_or_malformed_tool_calls() -> None:
    from veritool_rl.core.agent.parser import parse_qwen_response

    multiple = parse_qwen_response(
        '<tool_call>{"name":"get_order","arguments":{}}</tool_call>'
        '<tool_call>{"name":"refund_order","arguments":{}}</tool_call>'
    )
    malformed = parse_qwen_response("<tool_call>{not-json}</tool_call>")

    assert multiple.parse_error == "multiple_tool_calls"
    assert malformed.parse_error == "invalid_tool_call_json"


def test_qwen_parser_rejects_text_alongside_a_tool_call() -> None:
    """**文本 + 工具调用同时出现 = 非法调用。**

    这条判定塑造了整个 SFT 数据的形状：`CLAUDE.md`、`docs/AGENT_LOOP.md`、
    teacher 导出代码与多份配置都引用它——「任何『先声明再执行』的数据方案都会把
    `invalid_call` 从 0 打回去」。而在 2026-08-19 之前它**一条测试都没有**：
    外部评审把 `parser.py` 里的 `if outside:` 短路掉，全仓测试全绿。
    一个被六份文档奉为硬约束的不变量，实现可以被静默删除而无人知道。

    三种位置都覆盖：调用之前说话、之后说话、前后都说。
    """
    from veritool_rl.core.agent.parser import parse_qwen_response

    call = '<tool_call>{"name":"get_order","arguments":{"order_id":"O-1"}}</tool_call>'
    for label, raw in (
        ("前置文本", f"我先查一下这个订单。{call}"),
        ("后置文本", f"{call}已经帮你查询了。"),
        ("前后都有", f"稍等。{call}查询完成。"),
        ("后置文本带结束符", f"{call}好的<|im_end|>"),
    ):
        output = parse_qwen_response(raw)
        assert output.parse_error == "mixed_tool_call_content", label
        assert output.tool_call is None, label

    # 反向：纯工具调用（可带结束符与空白）必须仍然被接受，否则这条判定就成了误伤。
    clean = parse_qwen_response(f"  {call}  <|im_end|>")
    assert clean.parse_error is None
    assert clean.tool_call is not None


def test_oracle_runner_completes_all_scenarios() -> None:
    from veritool_rl.core.agent.policy import OraclePolicy
    from veritool_rl.core.agent.runner import run_episode
    from veritool_rl.core.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits
    from veritool_rl.core.trajectory import TaskScenario, TerminationReason

    tasks = build_mvp_task_splits(seed=9)["test"][:4]
    trajectories = [run_episode(task, MiniRetailEnv, OraclePolicy(task), seed=9) for task in tasks]

    assert {trajectory.task.scenario for trajectory in trajectories} == {
        TaskScenario.LOOKUP_STATUS,
        TaskScenario.REFUND_ELIGIBLE,
        TaskScenario.REFUND_DENIED,
        TaskScenario.REFUND_RECOVERY,
    }
    assert all(trajectory.success for trajectory in trajectories)
    assert all(trajectory.termination is TerminationReason.SUCCESS for trajectory in trajectories)
    recovery = next(
        trajectory
        for trajectory in trajectories
        if trajectory.task.scenario is TaskScenario.REFUND_RECOVERY
    )
    assert any(
        step.observation is not None and step.observation.error_code == "transient_error"
        for step in recovery.steps
    )


def test_format_errors_consume_steps_without_crashing_episode() -> None:
    from veritool_rl.core.agent.policy import PolicyOutput
    from veritool_rl.core.agent.runner import run_episode
    from veritool_rl.core.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits
    from veritool_rl.core.trajectory import TerminationReason

    class InvalidPolicy:
        name = "invalid"

        def __init__(self) -> None:
            self._outputs: Iterator[PolicyOutput] = iter(
                PolicyOutput(
                    raw_text="<tool_call>bad</tool_call>",
                    parse_error="invalid_tool_call_json",
                )
                for _ in range(8)
            )

        def respond(self, messages: list[dict[str, Any]], tools: list[Any]) -> PolicyOutput:
            return next(self._outputs)

    task = build_mvp_task_splits(seed=1)["test"][0]
    trajectory = run_episode(task, MiniRetailEnv, InvalidPolicy(), seed=1)

    assert trajectory.success is False
    assert trajectory.termination is TerminationReason.STEP_LIMIT
    assert len(trajectory.steps) == task.max_steps
    assert all(step.observation is not None for step in trajectory.steps)
    assert all(step.reward.invalid_call < 0 for step in trajectory.steps)


def test_policy_violation_terminates_episode() -> None:
    from veritool_rl.core.agent.policy import PolicyOutput
    from veritool_rl.core.agent.runner import run_episode
    from veritool_rl.core.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits
    from veritool_rl.core.trajectory import TaskScenario, TerminationReason, ToolCall

    class RefundFirstPolicy:
        name = "refund-first"

        def respond(self, messages: list[dict[str, Any]], tools: list[Any]) -> PolicyOutput:
            return PolicyOutput(
                raw_text="refund",
                tool_call=ToolCall(
                    name="refund_order",
                    arguments={
                        "order_id": task.metadata["order_id"],
                        "reason": task.metadata["reason"],
                    },
                ),
            )

    task = next(
        task
        for task in build_mvp_task_splits(seed=5)["test"]
        if task.scenario is TaskScenario.REFUND_ELIGIBLE
    )
    trajectory = run_episode(task, MiniRetailEnv, RefundFirstPolicy(), seed=5)

    assert trajectory.termination is TerminationReason.POLICY_VIOLATION
    assert trajectory.violations == ["refund_without_lookup"]
    assert trajectory.steps[0].reward.policy_penalty == -1.0


def test_tool_call_history_is_openai_wire_format_compatible() -> None:
    """assistant tool_calls must carry a string-encoded arguments field and a
    stable id, and the paired tool observation message must reference that id
    via tool_call_id. Local Qwen/Oracle policies never exercise this because
    they never round-trip through a real OpenAI-compatible HTTP API, but a
    real teacher backend (see R2 Task 4 smoke) rejects the raw-dict/missing-id
    form with HTTP 400."""
    import json
    from pathlib import Path

    from veritool_rl.core.agent.policy import PolicyOutput
    from veritool_rl.core.agent.runner import run_episode
    from veritool_rl.core.trajectory import TaskScenario, ToolCall
    from veritool_rl.retail_ops.domain.bundle import load_bundle
    from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
    from veritool_rl.retail_ops.domain.tasks import build_qualification_tasks

    bundle = load_bundle(Path("domains/retail_ops/v1"))
    task = next(
        task
        for task in build_qualification_tasks(seed=0)
        if task.scenario is TaskScenario.LOOKUP_STATUS
    )

    calls_seen: list[list[dict[str, Any]]] = []

    class RecordingPolicy:
        name = "recording"

        def __init__(self) -> None:
            self._responded = False

        def respond(self, messages: list[dict[str, Any]], tools: list[Any]) -> PolicyOutput:
            calls_seen.append(messages)
            if not self._responded:
                self._responded = True
                return PolicyOutput(
                    raw_text="",
                    tool_call=ToolCall(
                        name="get_order",
                        arguments={"order_id": task.metadata["order_id"]},
                    ),
                )
            return PolicyOutput(raw_text="done", final_response="done")

    run_episode(task, lambda current: RetailOpsEnv(current, bundle), RecordingPolicy(), seed=0)

    assert len(calls_seen) >= 2
    second_call_messages = calls_seen[1]
    assistant_message = next(
        message
        for message in second_call_messages
        if message.get("role") == "assistant" and message.get("tool_calls")
    )
    tool_message = next(
        message for message in second_call_messages if message.get("role") == "tool"
    )

    call_entry = assistant_message["tool_calls"][0]
    arguments = call_entry["function"]["arguments"]
    assert isinstance(arguments, str)
    assert json.loads(arguments) == {"order_id": task.metadata["order_id"]}
    call_id = call_entry.get("id")
    assert isinstance(call_id, str) and call_id
    assert tool_message.get("tool_call_id") == call_id


def test_runner_records_terminal_response_before_verification() -> None:
    from pathlib import Path

    from veritool_rl.core.agent.policy import OraclePolicy
    from veritool_rl.core.agent.runner import run_episode
    from veritool_rl.core.trajectory import TaskScenario, TerminationReason
    from veritool_rl.retail_ops.domain.bundle import load_bundle
    from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
    from veritool_rl.retail_ops.domain.tasks import build_qualification_tasks

    bundle = load_bundle(Path("domains/retail_ops/v1"))
    task = next(
        task
        for task in build_qualification_tasks(seed=0)
        if task.scenario is TaskScenario.REFUND_DENIED_WINDOW
    )

    trajectory = run_episode(
        task,
        lambda current: RetailOpsEnv(current, bundle),
        OraclePolicy(task),
        seed=0,
    )

    assert trajectory.success is True
    assert trajectory.termination is TerminationReason.SUCCESS
