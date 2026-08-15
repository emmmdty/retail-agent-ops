"""确定性 user simulator：让 episode 从单轮变成可澄清的多轮。

评审 P1-6：Agent 本体是 3 工具、**单轮用户请求**、最多 5 步的最小 ReAct 循环，
没有 user simulator、没有澄清轮。而 `docs/PRODUCT_BRIEF.md` 自己把 τ²-bench 列为
最接近的参照——"τ² 有 user simulator 和多轮政策冲突，你为什么没有"因此是必问题。

**为什么是规则式而不是 LLM 模拟用户**：本项目的评测契约要求确定性
（固定 seed、固定预算、可重放轨迹、逐字节可复现的证据）。一个 LLM 模拟用户会让
每次运行的用户侧输入都不同，`replay_trajectory` 直接失效，配对比较也不再成立。
规则式模拟器牺牲了自然度，换来的是"这条多轮轨迹可以被逐字节重放"——对一个以
证据链为核心主张的项目，这个取舍没有第二个答案。用 LLM 做模拟用户是可以的，
但那要作为**独立的、不进发布判定**的探索轨道，且必须记录 provider 与采样参数。

模拟器只回答**它作为用户本来就知道的事**（任务 metadata 里声明的订单号等），
不透露任何真值（期望调用、目标状态、判定结果）。否则多轮就变成了泄题。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from veritool_rl.core.trajectory import TaskSpec

#: 判定"这是一个提问"而不是"这是最终答复"的模式。
#: 保守取向：不像提问就当作最终答复，episode 照常结束——把一次正常收尾误判成提问
#: 会让 episode 无谓地跑到步数上限，比漏判一次提问更糟。
_QUESTION_PATTERNS = (
    re.compile(r"[?？]\s*$"),
    re.compile(r"(请问|请提供|请告知|麻烦提供|能否提供|方便提供)"),
    re.compile(r"(哪一?个订单|订单号是多少|需要.*订单号)"),
    re.compile(r"(?i)\b(which order|what is the order|could you provide)\b"),
)

#: 用户被问到订单号时的应答模板。固定文案使多轮轨迹逐字节可复现。
ORDER_ID_REPLY = "订单号是 {order_id}。"
UNKNOWN_REPLY = "抱歉，这个我不清楚，请你自己判断。"


class UserSimulator(Protocol):
    """episode 循环所需的最小模拟用户协议。"""

    name: str

    def reply(self, assistant_message: str, task: TaskSpec) -> str | None:
        """返回用户的下一句话；返回 None 表示对话到此结束。"""
        ...


def looks_like_a_question(message: str) -> bool:
    """助手这句话是在提问，还是在收尾。"""
    text = message.strip()
    return any(pattern.search(text) for pattern in _QUESTION_PATTERNS)


@dataclass
class ScriptedRetailUserSimulator:
    """只回答用户本来就知道的事的确定性模拟用户。

    `max_replies` 是硬上限：模型可能反复提问，而 episode 的步数预算是评测契约的一
    部分。上限用尽后模拟器一律返回 None，让 episode 按最终答复收尾——不是无限对话。
    """

    max_replies: int = 2
    name: str = "scripted_retail_user_v1"

    replies_given: int = field(default=0, init=False)
    questions_seen: int = field(default=0, init=False)

    def reply(self, assistant_message: str, task: TaskSpec) -> str | None:
        if not looks_like_a_question(assistant_message):
            return None
        self.questions_seen += 1
        if self.replies_given >= self.max_replies:
            return None
        self.replies_given += 1
        order_id = _known_order_id(task)
        if order_id is None:
            return UNKNOWN_REPLY
        return ORDER_ID_REPLY.format(order_id=order_id)


def _known_order_id(task: TaskSpec) -> str | None:
    """用户知道自己的订单号——这是任务 metadata 里的公开事实，不是评测真值。

    刻意**不**从 `expected_calls` 或 `target_state` 里取：那些是判定依据，
    从它们取值会让多轮变成泄题。
    """
    order_id = task.metadata.get("order_id")
    return order_id if isinstance(order_id, str) and order_id else None


def clarification_metadata(task: TaskSpec) -> dict[str, Any] | None:
    """任务是否声明了"必须先澄清"。"""
    value = task.metadata.get("clarification")
    return value if isinstance(value, dict) else None
