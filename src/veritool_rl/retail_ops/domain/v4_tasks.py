"""RetailOps v4 Phase B 任务生成：12 场景 × 5 口吻 = 60 句模板。

Phase B 的核心假设是数据多样性不足导致 OOD 泛化差。v4_tasks 在 v1 的 6 场景基础上
新增 6 个涉及 get_refund_status / cancel_order 的场景，并为每个场景提供 5 种口吻变体：
  0 = 书面正式
  1 = 口语随意
  2 = 极简指令
  3 = 情绪化
  4 = 中英混合
"""

from __future__ import annotations

from veritool_rl.core.trajectory import TaskScenario

# ---------------------------------------------------------------------------
# 12 场景 × 5 口吻模板
# ---------------------------------------------------------------------------

_V4_REQUESTS: dict[TaskScenario, tuple[str, str, str, str, str]] = {
    # === 原有 6 场景（扩展为 5 口吻） ===
    TaskScenario.LOOKUP_STATUS: (
        "请查询订单 {order_id} 的当前状态。",
        "帮我看看 {order_id} 现在啥情况",
        "查 {order_id} 状态",
        "我特别着急！{order_id} 到底发没发？？",
        "help me check order {order_id} status",
    ),
    TaskScenario.REFUND_ELIGIBLE: (
        "请核实订单 {order_id} 并按 {reason} 办理退款。",
        "这个 {order_id} 想退，原因是 {reason}，帮我处理下",
        "{order_id} 退款 {reason}",
        "求求了！{order_id} 必须退！{reason} 啊！",
        "need refund for {order_id}, reason is {reason}",
    ),
    TaskScenario.REFUND_DENIED_WINDOW: (
        "请检查订单 {order_id} 是否能因 {reason} 退款。",
        "帮我瞅瞅 {order_id} 还能不能退，{reason}",
        "{order_id} 能退不？{reason}",
        "气死了！{order_id} 买了好久了还能退吗？{reason}",
        "can I still refund {order_id}? reason: {reason}",
    ),
    TaskScenario.REFUND_DENIED_OWNERSHIP: (
        "请查询订单 {order_id} 并判断 {reason} 退款是否可办。",
        "帮我查下 {order_id} 能不能退，{reason}",
        "查 {order_id} 退款 {reason}",
        "拜托了！{order_id} 是我的订单！{reason} 退款能办吗？",
        "check {order_id} refund eligibility, reason: {reason}",
    ),
    TaskScenario.REFUND_DENIED_DUPLICATE: (
        "请查看订单 {order_id}，我需要按 {reason} 退款。",
        "{order_id} 要退，{reason}，麻烦看下",
        "{order_id} {reason} 退款",
        "又来了！{order_id} 上次退款失败了，{reason} 再试一次！",
        "refund {order_id} again, reason {reason}",
    ),
    TaskScenario.REFUND_RECOVERY: (
        "请为订单 {order_id} 按 {reason} 办理退款；临时失败时重试一次。",
        "帮我退 {order_id}，{reason}，如果失败了再试一次",
        "{order_id} 退 {reason} 失败重试",
        "求求了退款服务别崩！{order_id} {reason} 退不了就再试！",
        "refund {order_id} ({reason}), retry if fails",
    ),
    # === 新增 6 场景 ===
    TaskScenario.CHECK_REFUND_STATUS: (
        "请查询订单 {order_id} 的退款处理进度。",
        "帮我看看 {order_id} 的退款到哪了",
        "查 {order_id} 退款进度",
        "急死了！{order_id} 的退款什么时候到账啊？！",
        "check refund status for {order_id}",
    ),
    TaskScenario.CANCEL_ELIGIBLE: (
        "请取消订单 {order_id}，原因是 {reason}。",
        "帮我把 {order_id} 取消了吧，{reason}",
        "取消 {order_id} {reason}",
        "求求了！{order_id} 必须取消！{reason} 啊！",
        "cancel order {order_id}, reason: {reason}",
    ),
    TaskScenario.CANCEL_DENIED_RECENT: (
        "请评估订单 {order_id} 是否满足取消条件，告诉我能否取消以及原因。",
        "帮我看看 {order_id} 能不能取消，评估一下",
        "{order_id} 能取消不？评估下",
        "急！{order_id} 到底能不能取消？给个准话！",
        "evaluate if order {order_id} can be cancelled",
    ),
    TaskScenario.CANCEL_DENIED_IN_USE: (
        "请查询订单 {order_id} 并判断 {reason} 取消是否可办。",
        "帮我查下 {order_id} 能不能取消，{reason}",
        "查 {order_id} 取消 {reason}",
        "拜托了！{order_id} 正在用但我想取消！{reason} 可以吗？",
        "check {order_id} cancel eligibility, reason: {reason}",
    ),
    TaskScenario.REFUND_THEN_CANCEL: (
        "请先为订单 {order_id} 办理退款，再取消关联订单 {other_order_id}。",
        "先退 {order_id} 的款，然后把 {other_order_id} 也取消了",
        "退 {order_id} 再取消 {other_order_id}",
        "崩溃了！{order_id} 要退款，{other_order_id} 也要取消！一个一个来！",
        "refund {order_id} first, then cancel {other_order_id}",
    ),
    TaskScenario.CANCEL_RECOVERY: (
        "请取消订单 {order_id}，原因是 {reason}；临时失败时重试一次。",
        "帮我取消 {order_id}，{reason}，如果失败了再试一次",
        "取消 {order_id} {reason} 失败重试",
        "求求了取消服务别崩！{order_id} {reason} 取消不了就再试！",
        "cancel {order_id} ({reason}), retry if fails",
    ),
}


def get_v4_user_request(
    scenario: TaskScenario,
    order_id: str,
    reason: str,
    variant_index: int,
    other_order_id: str = "",
) -> str:
    """返回指定场景、口吻的用户请求模板。"""
    template = _V4_REQUESTS[scenario][variant_index]
    return template.format(
        order_id=order_id,
        reason=reason,
        other_order_id=other_order_id,
    )


# ---------------------------------------------------------------------------
# 12 场景的辅助元数据
# ---------------------------------------------------------------------------

#: 每个场景需要哪个工具来完成（正确的工具选择）。
V4_SCENARIO_PRIMARY_TOOL: dict[TaskScenario, str] = {
    TaskScenario.LOOKUP_STATUS: "get_order",
    TaskScenario.REFUND_ELIGIBLE: "refund_order",
    TaskScenario.REFUND_DENIED_WINDOW: "refund_order",
    TaskScenario.REFUND_DENIED_OWNERSHIP: "refund_order",
    TaskScenario.REFUND_DENIED_DUPLICATE: "refund_order",
    TaskScenario.REFUND_RECOVERY: "refund_order",
    TaskScenario.CHECK_REFUND_STATUS: "get_refund_status",
    TaskScenario.CANCEL_ELIGIBLE: "cancel_order",
    TaskScenario.CANCEL_DENIED_RECENT: "cancel_order",
    TaskScenario.CANCEL_DENIED_IN_USE: "cancel_order",
    TaskScenario.REFUND_THEN_CANCEL: "refund_order",
    TaskScenario.CANCEL_RECOVERY: "cancel_order",
}

#: 每个场景的 expected_decision。
V4_SCENARIO_DECISION: dict[TaskScenario, str] = {
    TaskScenario.LOOKUP_STATUS: "inform",
    TaskScenario.REFUND_ELIGIBLE: "allow",
    TaskScenario.REFUND_DENIED_WINDOW: "deny",
    TaskScenario.REFUND_DENIED_OWNERSHIP: "deny",
    TaskScenario.REFUND_DENIED_DUPLICATE: "deny",
    TaskScenario.REFUND_RECOVERY: "allow",
    TaskScenario.CHECK_REFUND_STATUS: "inform",
    TaskScenario.CANCEL_ELIGIBLE: "allow",
    TaskScenario.CANCEL_DENIED_RECENT: "deny",
    TaskScenario.CANCEL_DENIED_IN_USE: "deny",
    TaskScenario.REFUND_THEN_CANCEL: "allow",
    TaskScenario.CANCEL_RECOVERY: "allow",
}

#: 5 种口吻的名称。
V4_VARIANT_NAMES = (
    "书面正式",
    "口语随意",
    "极简指令",
    "情绪化",
    "中英混合",
)
