"""serve 的请求级可观测性：trace_id、结构化 JSON 日志与 Prometheus 文本指标。

刻意不引入 `prometheus_client`：本项目的依赖锁是配对契约的一部分
（`uv_lock_sha256` 在 `SEALED_PAIRING_FIELDS` 内），为一个几十行的文本渲染
新增运行时依赖会让每次发布判定多背一个可比性风险。

日志口径的硬约束：**不落请求原文**。落的是 SHA-256 摘要与字符数——足以在事后
把一条投诉对上一条 trace，又不会把用户数据或任务答案写进日志文件。
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import threading
from collections import Counter
from typing import Any

LOGGER_NAME = "retail_agent_ops.serve"
_logger = logging.getLogger(LOGGER_NAME)

#: 当前请求的可变记录。由最外层中间件写入，端点在其中补充 episode 细节，
#: 中间件在响应返回后一次性输出——保证"一次请求恰好一行日志"。
REQUEST_RECORD: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "retail_agent_ops_request_record"
)


def new_record(trace_id: str, endpoint: str) -> dict[str, Any]:
    """构造一条请求记录的默认字段集合。"""
    return {
        "trace_id": trace_id,
        "endpoint": endpoint,
        "status": 0,
        "duration_ms": 0.0,
        "deployment": None,
        "policy_id": None,
        "termination": None,
        "tool_calls": [],
        "violations": [],
        "request_sha256": digest_text(""),
        "request_chars": 0,
        "reject_reason": None,
    }


def digest_text(text: str) -> str:
    """请求文本的稳定摘要；日志与响应都只引用它，不引用原文。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def emit(record: dict[str, Any]) -> None:
    """输出一行 JSON 日志。字段顺序稳定，便于 diff 与离线聚合。"""
    _logger.info(json.dumps(record, ensure_ascii=False, sort_keys=True))


def configure_service_logging() -> None:
    """给服务进程装一个只输出原始 JSON 行的 stdout handler。

    库代码本身不装 handler（那会污染宿主应用的日志配置），只有真正启动服务的
    CLI 才调用这里。重复调用是幂等的。
    """
    if any(getattr(handler, "_retail_agent_ops", False) for handler in _logger.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler._retail_agent_ops = True  # type: ignore[attr-defined]
    _logger.addHandler(handler)
    _logger.setLevel(logging.INFO)


class ServiceMetrics:
    """进程内计数器与延迟样本；渲染为 Prometheus 文本格式。

    分位数用全量样本精确计算而不是滑窗近似：单卡服务的 QPS 上界是个位数，
    样本量小到可以直接排序，没有必要引入近似带来的解释负担。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: Counter[tuple[str, int]] = Counter()
        self._rejected: Counter[str] = Counter()
        self._episodes = 0
        self._timeouts = 0
        self._tool_calls = 0
        self._violations = 0
        self._latencies: list[float] = []

    def record_request(self, endpoint: str, status: int) -> None:
        with self._lock:
            self._requests[(endpoint, status)] += 1

    def record_rejection(self, reason: str) -> None:
        with self._lock:
            self._rejected[reason] += 1

    def record_timeout(self) -> None:
        with self._lock:
            self._timeouts += 1

    def record_episode(self, *, latency_ms: float, tool_calls: int, violations: int) -> None:
        with self._lock:
            self._episodes += 1
            self._tool_calls += tool_calls
            self._violations += violations
            self._latencies.append(latency_ms)

    def render(self) -> str:
        with self._lock:
            requests = dict(self._requests)
            rejected = dict(self._rejected)
            episodes = self._episodes
            timeouts = self._timeouts
            tool_calls = self._tool_calls
            violations = self._violations
            latencies = sorted(self._latencies)

        lines: list[str] = []
        lines += _block(
            "retail_agent_ops_requests_total",
            "counter",
            "按端点与 HTTP 状态码统计的请求数。",
            [
                (f'{{endpoint="{endpoint}",status="{status}"}}', float(count))
                for (endpoint, status), count in sorted(requests.items())
            ],
        )
        lines += _block(
            "retail_agent_ops_rejected_total",
            "counter",
            "在触达模型之前被拒绝的请求数，按原因分。",
            [
                (f'{{reason="{reason}"}}', float(count))
                for reason, count in sorted(rejected.items())
            ],
        )
        lines += _block(
            "retail_agent_ops_episodes_total",
            "counter",
            "完整跑完的 agent episode 数。",
            [("", float(episodes))],
        )
        lines += _block(
            "retail_agent_ops_timeouts_total",
            "counter",
            "超过单次 episode 时限而被结构化降级的请求数。",
            [("", float(timeouts))],
        )
        lines += _block(
            "retail_agent_ops_tool_calls_total",
            "counter",
            "全部 episode 累计的工具调用次数。",
            [("", float(tool_calls))],
        )
        lines += _block(
            "retail_agent_ops_policy_violations_total",
            "counter",
            "全部 episode 累计的政策违规次数。",
            [("", float(violations))],
        )
        lines += _block(
            "retail_agent_ops_episode_latency_ms",
            "summary",
            "端到端 episode 耗时（毫秒）的分位数。",
            [
                ('{quantile="0.5"}', _quantile(latencies, 0.5)),
                ('{quantile="0.95"}', _quantile(latencies, 0.95)),
            ],
        )
        lines += _block(
            "retail_agent_ops_episode_tool_calls_avg",
            "gauge",
            "每个 episode 的平均工具调用次数。",
            [("", tool_calls / episodes if episodes else 0.0)],
        )
        return "\n".join(lines) + "\n"


def _block(
    name: str,
    metric_type: str,
    help_text: str,
    samples: list[tuple[str, float]],
) -> list[str]:
    lines = [f"# HELP {name} {help_text}", f"# TYPE {name} {metric_type}"]
    lines += [f"{name}{labels} {_number(value)}" for labels, value in samples]
    return lines


def _number(value: float) -> str:
    return repr(float(value))


def _quantile(sorted_samples: list[float], quantile: float) -> float:
    """最近秩分位数；空样本回 0.0 而不是 NaN，Prometheus 文本不接受 NaN 语义歧义。"""
    if not sorted_samples:
        return 0.0
    index = max(0, min(len(sorted_samples) - 1, round(quantile * len(sorted_samples) + 0.5) - 1))
    return sorted_samples[index]
