"""V6-2b：解析器协议容忍（eos 前未闭合 tool_call）——预注册 A-0 裁定 4（2026-09-07）。

诊断依据（findings 2026-09-07「V6-1 空生成诊断」节）：观测 8 两次
`invalid_tool_call_json` 的实录是「有效 JSON 缺 `\\n</tool_call>` 闭合标签」
（tokenizer 边界退化，非空生成；`"}}\\n` 合并 token 与裸 `"​}}` 的近僵持 + NF4 噪声）。

本文件锁定四件事：
1. **v1 解析器（`hermes-single-call-v1`）行为逐字节不变**——含「未闭合 → 拒绝」锚点；
   它是 v1–v5 冻结评测契约的一部分。
2. **v2 解析器（`hermes-single-call-v2-unterminated`）只在最窄条件下容忍**：存在
   `<tool_call>` 开标签、无闭标签、开标签前无散文、剥离 eos 标记后剩余部分**恰好是
   合法 JSON**。尾部另有内容 / JSON 非法 / 多重开标签 / 前置散文 / 已闭合但 JSON
   非法，一律维持 v1 的拒绝判定。
3. `QwenPolicy` 按 `parser_id` 选择解析器；未知 id fail-closed；默认 v1（不传即
   旧行为，全部既有构造点零扰动）。
4. metrics 的 `unterminated_call_count` 是**诊断计数不是门禁**——由
   `assistant_raw` 派生，不触碰 Trajectory schema，老证据加载零影响。
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# 1. v1 锚点：老解析器逐字节不变
# ---------------------------------------------------------------------------


def test_v1_parser_still_rejects_unterminated_tool_call() -> None:
    """观测 8 的实录形状在 v1 下必须仍是 invalid_tool_call_json（历史口径锚点）。"""
    from veritool_rl.core.agent.parser import parse_qwen_response

    raw = (
        '<tool_call>\n{"name": "get_refund_status",'
        ' "arguments": {"order_id": "O-18B3A1260B91"}}<|im_end|>'
    )
    output = parse_qwen_response(raw)
    assert output.parse_error == "invalid_tool_call_json"
    assert output.tool_call is None


def test_v1_parser_normal_paths_unchanged() -> None:
    from veritool_rl.core.agent.parser import parse_qwen_response

    closed = (
        '<tool_call>\n{"name": "get_order", "arguments": {"order_id": "O-1"}}'
        "\n</tool_call><|im_end|>"
    )
    assert parse_qwen_response(closed).tool_call is not None
    assert parse_qwen_response("好的，已处理。").final_response == "好的，已处理。"
    assert parse_qwen_response("").parse_error == "empty_response"
    assert parse_qwen_response("<tool_call>bad</tool_call>").parse_error == (
        "invalid_tool_call_json"
    )


# ---------------------------------------------------------------------------
# 2. v2 容忍语义：最窄条件
# ---------------------------------------------------------------------------


def test_v2_accepts_unterminated_valid_json_with_eos() -> None:
    """观测 8 的实录形状在 v2 下恢复为有效调用（含 milestone 一致的内容）。"""
    from veritool_rl.core.agent.parser import parse_qwen_response_v2

    raw = (
        '<tool_call>\n{"name": "get_refund_status",'
        ' "arguments": {"order_id": "O-18B3A1260B91"}}<|im_end|>'
    )
    output = parse_qwen_response_v2(raw)
    assert output.parse_error is None
    assert output.tool_call is not None
    assert output.tool_call.name == "get_refund_status"
    assert output.tool_call.arguments == {"order_id": "O-18B3A1260B91"}


def test_v2_accepts_unterminated_valid_json_without_eos() -> None:
    from veritool_rl.core.agent.parser import parse_qwen_response_v2

    raw = '{"name": "get_order", "arguments": {"order_id": "O-1"}}'
    output = parse_qwen_response_v2(f"<tool_call>\n{raw}")
    assert output.parse_error is None
    assert output.tool_call is not None
    assert output.tool_call.name == "get_order"


def test_v2_rejects_unterminated_with_trailing_prose() -> None:
    from veritool_rl.core.agent.parser import parse_qwen_response_v2

    raw = '<tool_call>\n{"name": "get_order", "arguments": {"order_id": "O-1"}} 然后帮我退款'
    output = parse_qwen_response_v2(raw)
    assert output.parse_error == "invalid_tool_call_json"
    assert output.tool_call is None


def test_v2_rejects_unterminated_invalid_json() -> None:
    from veritool_rl.core.agent.parser import parse_qwen_response_v2

    output = parse_qwen_response_v2('<tool_call>\n{"name": "get_order"<|im_end|>')
    assert output.parse_error == "invalid_tool_call_json"


def test_v2_rejects_multiple_open_tags() -> None:
    from veritool_rl.core.agent.parser import parse_qwen_response_v2

    raw = (
        "<tool_call>\n"
        '{"name": "get_order", "arguments": {"order_id": "O-1"}}\n'
        "<tool_call>\n"
        '{"name": "get_refund_status", "arguments": {"order_id": "O-1"}}<|im_end|>'
    )
    output = parse_qwen_response_v2(raw)
    assert output.parse_error == "invalid_tool_call_json"


def test_v2_rejects_prose_before_the_open_tag() -> None:
    from veritool_rl.core.agent.parser import parse_qwen_response_v2

    raw = '我先查一下。<tool_call>\n{"name": "get_order", "arguments": {"order_id": "O-1"}}'
    output = parse_qwen_response_v2(raw)
    assert output.parse_error == "invalid_tool_call_json"


def test_v2_keeps_closed_but_invalid_json_rejected() -> None:
    """闭合标签存在时容忍路径永不生效——JSON 质量守卫不放松。"""
    from veritool_rl.core.agent.parser import parse_qwen_response_v2

    output = parse_qwen_response_v2("<tool_call>bad</tool_call>")
    assert output.parse_error == "invalid_tool_call_json"


def test_v2_matches_v1_on_all_normal_outputs() -> None:
    from veritool_rl.core.agent.parser import parse_qwen_response, parse_qwen_response_v2

    closed = (
        '<tool_call>\n{"name": "get_order", "arguments": {"order_id": "O-1"}}'
        "\n</tool_call><|im_end|>"
    )
    for raw in (closed, "好的，已处理。", "", "<tool_call>bad</tool_call>"):
        first = parse_qwen_response(raw)
        second = parse_qwen_response_v2(raw)
        assert first == second


# ---------------------------------------------------------------------------
# 3. QwenPolicy 按 parser_id 选择
# ---------------------------------------------------------------------------


class _UnterminatedBackend:
    """回放观测 8 实录形状的后端。"""

    def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_new_tokens: int,
    ) -> Any:
        del messages, tools, max_new_tokens
        from veritool_rl.core.agent.qwen import GeneratedText

        return GeneratedText(
            text=(
                '<tool_call>\n{"name": "get_refund_status",'
                ' "arguments": {"order_id": "O-18B3A1260B91"}}<|im_end|>'
            ),
            input_tokens=836,
            output_tokens=35,
            latency_ms=730.0,
        )


def test_qwen_policy_default_parser_is_v1_strict() -> None:
    from veritool_rl.core.agent.qwen import QwenPolicy

    output = QwenPolicy(_UnterminatedBackend(), "models/Qwen3-1.7B").respond([], [])
    assert output.parse_error == "invalid_tool_call_json"


def test_qwen_policy_v2_parser_recovers_unterminated_call() -> None:
    from veritool_rl.core.agent.qwen import QwenPolicy

    policy = QwenPolicy(
        _UnterminatedBackend(),
        "models/Qwen3-1.7B",
        parser_id="hermes-single-call-v2-unterminated",
    )
    output = policy.respond([], [])
    assert output.parse_error is None
    assert output.tool_call is not None
    assert output.tool_call.name == "get_refund_status"


def test_qwen_policy_unknown_parser_id_fails_closed() -> None:
    import pytest

    from veritool_rl.core.agent.qwen import QwenPolicy

    with pytest.raises(ValueError, match="parser_id"):
        QwenPolicy(_UnterminatedBackend(), "models/Qwen3-1.7B", parser_id="hermes-v99")


# ---------------------------------------------------------------------------
# 4. metrics：诊断计数（不进门禁）
# ---------------------------------------------------------------------------


def test_metrics_count_unterminated_calls_as_diagnostic() -> None:

    from veritool_rl.core.agent.policy import PolicyOutput
    from veritool_rl.core.agent.runner import run_episode
    from veritool_rl.core.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits
    from veritool_rl.core.metrics import compute_metrics
    from veritool_rl.core.trajectory import ToolCall

    class UnterminatedCallPolicy:
        name = "unterminated-call"

        def respond(self, messages: list[dict[str, Any]], tools: list[Any]) -> PolicyOutput:
            del messages, tools
            # v2 解析器恢复后的形态：tool_call 有效、raw_text 缺闭合标签。
            return PolicyOutput(
                raw_text=(
                    '<tool_call>\n{"name": "get_order", "arguments": {"order_id": "O-1"}}<|im_end|>'
                ),
                tool_call=ToolCall(name="get_order", arguments={"order_id": "O-1"}),
            )

    task = build_mvp_task_splits(seed=0)["test"][0]
    trajectory = run_episode(task, MiniRetailEnv, UnterminatedCallPolicy(), seed=0)
    metrics = compute_metrics([trajectory], bootstrap_samples=10, seed=0)
    expected = sum(
        1
        for step in trajectory.steps
        if step.tool_call is not None
        and "<tool_call>" in step.assistant_raw
        and "</tool_call>" not in step.assistant_raw
    )
    assert expected >= 1
    assert metrics["unterminated_call_count"] == expected
    # 诊断计数不影响任何门禁语义：invalid_call_count 仍由 parse_error / 观察错误码决定。
    assert metrics["invalid_call_count"] == 0


def test_metrics_unterminated_count_is_zero_for_closed_calls() -> None:
    from veritool_rl.core.agent.policy import OraclePolicy
    from veritool_rl.core.agent.runner import run_episode
    from veritool_rl.core.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits
    from veritool_rl.core.metrics import compute_metrics

    tasks = build_mvp_task_splits(seed=10)["test"][:4]
    trajectories = [run_episode(task, MiniRetailEnv, OraclePolicy(task), seed=10) for task in tasks]
    metrics = compute_metrics(trajectories, bootstrap_samples=100, seed=3)
    assert metrics["unterminated_call_count"] == 0
