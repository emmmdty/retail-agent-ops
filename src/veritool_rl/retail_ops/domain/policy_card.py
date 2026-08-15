"""把 bundle 里的业务政策渲染成模型可读的政策卡。

评审 P0-2 的第二层：**政策合规被烧进了模型权重，而运行时环境已在强制同样的规则**
——冗余的那一份恰恰是最难更新、最难审计的。v1 的 `SYSTEM_PROMPT` 只说了"退款前必须
查询订单"和"可以重试"，时间窗 / 归属 / 重复三条规则模型全靠猜；`SYSTEM_CARD.md` §7
记录的"`current_day` 未暴露导致该类不可解"就是同一问题的早期表现。

**渲染必须是确定性的**：同一个 bundle 必须渲染出**逐字节相同**的 prompt。
`system_prompt_sha256` 在 dev 的 `PAIRING_FIELDS` 与 `SEALED_PAIRING_FIELDS` 内，
一个不稳定的渲染会让配对契约变成不可复现的——那比不渲染更糟。因此这里只做
纯函数式的字符串拼接，不读时间、不读环境变量、不遍历无序容器。
"""

from __future__ import annotations

from veritool_rl.core.agent.runner import SYSTEM_PROMPT
from veritool_rl.retail_ops.domain.bundle import LoadedRetailOpsBundle

#: 规则 ID → 面向模型的自然语言表述。渲染的是**政策的含义**而不是谓词语法：
#: 模型要读的是"超过退款期限的订单不能退"，不是 `days_past_deadline > 0`。
#: 未登记的规则 ID 会退化为通用表述并显式标注，不会静默漏掉一条政策。
_RULE_PHRASING = {
    "refund_requires_lookup": "退款前必须先用 get_order 查询该订单。",
    "customer_must_own_order": "只能为当前客户本人的订单退款。",
    "refund_window_must_be_open": (
        "订单超过退款期限后不得退款；get_order 会同时返回 current_day 与 refund_deadline。"
    ),
    "duplicate_refund_forbidden": "已经退过款的订单不得再次退款。",
}


def render_policy_card(bundle: LoadedRetailOpsBundle) -> str:
    """从 bundle 渲染政策卡。纯函数：同一个 bundle 永远得到同一串字节。"""
    lines = [
        f"业务政策（{bundle.bundle.bundle_id} v{bundle.policies.policy_version}）：",
    ]
    for index, rule in enumerate(bundle.policy_rules, start=1):
        phrasing = _RULE_PHRASING.get(rule.rule_id)
        if phrasing is None:
            phrasing = f"（{rule.rule_id}）违反时按 {rule.violation} 拒绝：{rule.error}"
        lines.append(f"{index}. {phrasing}")
    lines.append(
        f"{len(bundle.policy_rules) + 1}. 允许的退款原因只有："
        + "、".join(bundle.policies.refund_reasons)
        + "。"
    )
    lines.append(
        f"{len(bundle.policy_rules) + 2}. 遇到 transient_error 最多重试 "
        f"{bundle.policies.max_transient_retries} 次；重试必须复用同一个 idempotency_key。"
        if _has_idempotency_key(bundle)
        else f"{len(bundle.policy_rules) + 2}. 遇到 transient_error 最多重试 "
        f"{bundle.policies.max_transient_retries} 次。"
    )
    return "\n".join(lines)


def build_system_prompt(bundle: LoadedRetailOpsBundle) -> str:
    """组装该 bundle 对应的 system prompt。

    **v1 逐字节返回冻结常量**，不追加任何内容：`system_prompt_sha256` 是 v1 全部
    已有评测证据的配对字段之一，给它加一个字都会让那些证据不再可配对。政策卡是
    v2 起的能力。
    """
    if bundle.bundle.bundle_version == "1.0.0":
        return SYSTEM_PROMPT
    return f"{SYSTEM_PROMPT}\n\n{render_policy_card(bundle)}"


def _has_idempotency_key(bundle: LoadedRetailOpsBundle) -> bool:
    for tool in bundle.tools:
        if tool.name == "refund_order":
            return "idempotency_key" in tool.parameters.get("properties", {})
    return False
