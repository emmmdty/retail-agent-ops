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


def test_qwen_parser_uses_first_tool_call_when_multiple_returned() -> None:
    """Multiple tool calls should pick the FIRST one, not error.

    This fixes the refund_then_cancel scenario where the teacher returns
    get_order for both the primary AND other order in a single response.
    """
    from veritool_rl.core.agent.parser import parse_qwen_response

    multiple = parse_qwen_response(
        '<tool_call>{"name":"get_order","arguments":{"order_id":"O-1"}}</tool_call>'
        '<tool_call>{"name":"refund_order","arguments":{}}</tool_call>'
    )

    assert multiple.parse_error is None
    assert multiple.tool_call is not None
    assert multiple.tool_call.name == "get_order"
    assert multiple.tool_call.arguments == {"order_id": "O-1"}


def test_qwen_parser_rejects_malformed_tool_call() -> None:
    from veritool_rl.core.agent.parser import parse_qwen_response

    malformed = parse_qwen_response("<tool_call>{not-json}</tool_call>")

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


# ---------------------------------------------------------------------------
# F1 测试补齐（7.2 清单 §1.1 / §1.2 / §2.2）
# ---------------------------------------------------------------------------


def test_premature_final_response_terminates_with_final_response_reason() -> None:
    """runner 非成功终止分支：说了结束语但任务没做完 → FINAL_RESPONSE，不算成功。

    `test_runner_records_terminal_response_before_verification` 只覆盖了
    success 路径；这条锁定它的反面——「提前收尾」不得伪装成成功。
    """

    from pathlib import Path

    from veritool_rl.core.agent.parser import parse_qwen_response
    from veritool_rl.core.agent.runner import run_episode
    from veritool_rl.core.trajectory import TaskScenario
    from veritool_rl.core.trajectory.schema import TerminationReason
    from veritool_rl.retail_ops.domain.bundle import load_bundle
    from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
    from veritool_rl.retail_ops.domain.tasks import build_qualification_tasks

    bundle = load_bundle(Path("domains/retail_ops/v1"))
    task = next(
        t for t in build_qualification_tasks(seed=0) if t.scenario is TaskScenario.REFUND_ELIGIBLE
    )

    class _PrematurePolicy:
        name = "premature"

        def respond(self, messages, tools):
            del messages, tools
            return parse_qwen_response("我已经处理完您的请求了。")

    trajectory = run_episode(
        task, lambda current: RetailOpsEnv(current, bundle), _PrematurePolicy(), 0
    )

    assert trajectory.termination is TerminationReason.FINAL_RESPONSE
    assert trajectory.success is False


def test_custom_system_prompt_reaches_the_model_messages() -> None:
    """system_prompt 参数必须真的进 messages 的 system 段。"""
    from pathlib import Path

    from veritool_rl.core.agent.policy import OraclePolicy
    from veritool_rl.core.agent.runner import run_episode
    from veritool_rl.retail_ops.domain.bundle import load_bundle
    from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
    from veritool_rl.retail_ops.domain.tasks import build_qualification_tasks

    bundle = load_bundle(Path("domains/retail_ops/v1"))
    task = build_qualification_tasks(seed=0)[0]

    class _CapturePolicy(OraclePolicy):
        def __init__(self, task):
            super().__init__(task)
            self.seen_system: list[str] = []

        def respond(self, messages, tools):
            self.seen_system.append(messages[0]["content"])
            return super().respond(messages, tools)

    policy = _CapturePolicy(task)
    marker = "自定义系统提示词-探针"
    run_episode(
        task,
        lambda current: RetailOpsEnv(current, bundle),
        policy,
        0,
        system_prompt=marker,
    )

    assert policy.seen_system, "policy 没有被调用"
    assert all(content == marker for content in policy.seen_system)


def test_parse_error_path_skips_the_guardrail_but_records_format_error() -> None:
    """隐含契约：parse_error 路径不触达 guardrail（没有调用可查），但要记 format_error。

    guardrail 是对**工具调用**的第二道防线；没有合法调用时它无从参与。
    这条测试把这个隐含契约写下来，防止未来有人把 guardrail 挪到 parse 之前
    而不改变语义声明。
    """
    from pathlib import Path

    from veritool_rl.core.agent.guardrail import Guardrail
    from veritool_rl.core.agent.parser import parse_qwen_response
    from veritool_rl.core.agent.runner import run_episode
    from veritool_rl.core.trajectory import TaskScenario
    from veritool_rl.retail_ops.domain.bundle import load_bundle
    from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
    from veritool_rl.retail_ops.domain.tasks import build_qualification_tasks

    bundle = load_bundle(Path("domains/retail_ops/v1"))
    task = next(
        t for t in build_qualification_tasks(seed=0) if t.scenario is TaskScenario.REFUND_ELIGIBLE
    )

    class _BrokenPolicy:
        name = "broken"

        def respond(self, messages, tools):
            del messages, tools
            return parse_qwen_response("<tool_call>{bad json}</tool_call>")

    consulted: list[object] = []

    class _SpyGuardrail(Guardrail):
        def check_call(self, call, tools):
            consulted.append(call)
            return super().check_call(call, tools)

    trajectory = run_episode(
        task,
        lambda current: RetailOpsEnv(current, bundle),
        _BrokenPolicy(),
        0,
        guardrail=_SpyGuardrail(),
    )

    assert consulted == [], "parse_error 路径不得触达 guardrail"
    assert trajectory.steps
    assert all(step.parse_error is not None for step in trajectory.steps)


def test_max_steps_one_executes_exactly_one_step() -> None:
    """max_steps=1 边界：一步预算下只跑一次 respond，终止原因是步数上限或提前收尾。"""
    from pathlib import Path

    from veritool_rl.core.agent.parser import parse_qwen_response
    from veritool_rl.core.agent.runner import run_episode
    from veritool_rl.core.trajectory import TaskScenario
    from veritool_rl.retail_ops.domain.bundle import load_bundle
    from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
    from veritool_rl.retail_ops.domain.tasks import build_qualification_tasks

    bundle = load_bundle(Path("domains/retail_ops/v1"))
    task = next(
        t for t in build_qualification_tasks(seed=0) if t.scenario is TaskScenario.LOOKUP_STATUS
    ).model_copy(update={"max_steps": 1})

    calls: list[int] = []

    class _CountingPolicy:
        name = "counting"

        def respond(self, messages, tools):
            calls.append(len(messages))
            return parse_qwen_response('<tool_call>{"name":"get_order","arguments":{}}</tool_call>')

    trajectory = run_episode(
        task, lambda current: RetailOpsEnv(current, bundle), _CountingPolicy(), 0
    )

    assert len(calls) == 1
    assert trajectory.termination.value in {"step_limit", "final_response", "success"}


def test_task_spec_rejects_zero_max_steps() -> None:
    """max_steps=0 被 schema 拒绝（ge=1）：零步 episode 是配置错误不是合法边界。"""
    import pytest as _pytest
    from pydantic import ValidationError as _ValidationError

    from veritool_rl.core.trajectory import TaskScenario
    from veritool_rl.core.trajectory.schema import TaskSpec

    with _pytest.raises(_ValidationError):
        TaskSpec(
            task_id="t",
            split="dev",
            scenario=TaskScenario.LOOKUP_STATUS,
            user_request="查询",
            initial_state={},
            target_state={},
            max_steps=0,
        )


def test_consecutive_unknown_tool_calls_do_not_crash_the_episode() -> None:
    """连续 unknown_tool：轨迹继续、步数耗尽、终止原因 step_limit、无违规。"""
    from pathlib import Path

    from veritool_rl.core.agent.parser import parse_qwen_response
    from veritool_rl.core.agent.runner import run_episode
    from veritool_rl.retail_ops.domain.bundle import load_bundle
    from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
    from veritool_rl.retail_ops.domain.tasks import build_qualification_tasks

    bundle = load_bundle(Path("domains/retail_ops/v1"))
    task = build_qualification_tasks(seed=0)[0].model_copy(update={"max_steps": 3})

    class _UnknownToolPolicy:
        name = "unknown-tool"

        def respond(self, messages, tools):
            del messages, tools
            return parse_qwen_response(
                '<tool_call>{"name":"delete_everything","arguments":{}}</tool_call>'
            )

    trajectory = run_episode(
        task, lambda current: RetailOpsEnv(current, bundle), _UnknownToolPolicy(), 0
    )

    assert len(trajectory.steps) == 3
    assert all(
        step.observation is not None and step.observation.error_code == "unknown_tool"
        for step in trajectory.steps
    )
    assert trajectory.termination.value == "step_limit"
    assert trajectory.violations == []


def test_nested_arguments_survive_parsing_and_execution() -> None:
    """深层嵌套但合法的 arguments 结构：解析器与 wire format 不失真。"""
    import json as _json

    from veritool_rl.core.agent.parser import parse_qwen_response

    nested = {"order_id": "O-1", "extra": {"a": [1, 2, {"b": None}]}}
    output = parse_qwen_response(
        f'<tool_call>{{"name":"get_order","arguments":{_json.dumps(nested)}}}</tool_call>'
    )
    assert output.parse_error is None
    assert output.tool_call is not None
    assert output.tool_call.arguments == nested


def test_parser_empty_response_and_pydantic_validation_failure() -> None:
    """7.2 §1.2：空响应与「JSON 合法但 Pydantic 校验失败」两条 parser 分支。"""
    from veritool_rl.core.agent.parser import parse_qwen_response

    empty = parse_qwen_response("")
    assert empty.parse_error == "empty_response"
    assert empty.tool_call is None
    assert empty.final_response is None

    whitespace = parse_qwen_response("   \n  ")
    assert whitespace.parse_error == "empty_response"

    # JSON 解析成功、ToolCall.model_validate 失败：arguments 类型非法
    bad_types = parse_qwen_response(
        '<tool_call>{"name":"get_order","arguments":"not-a-dict"}</tool_call>'
    )
    assert bad_types.parse_error == "invalid_tool_call_json"
    assert bad_types.tool_call is None

    # 缺 arguments 不是 Pydantic 失败——ToolCall.arguments 有默认 {}（既有契约，
    # 显式记录在这里）；缺 name 才是校验失败
    default_args = parse_qwen_response('<tool_call>{"name":"get_order"}</tool_call>')
    assert default_args.parse_error is None
    assert default_args.tool_call is not None
    assert default_args.tool_call.arguments == {}

    missing_name = parse_qwen_response('<tool_call>{"arguments":{}}</tool_call>')
    assert missing_name.parse_error == "invalid_tool_call_json"
