"""评测路径超时守卫（findings #3 / P1-7 修复的测试补齐）。

纪律（先于测试写定，测试岗位主管四类用例）：

1. **正例**：慢策略必须在 `episode_timeout` 内被终止，产出
   `TerminationReason.INTERNAL_ERROR` 轨迹，metadata 记录
   `infrastructure_error="episode_timeout"`——一条卡住的策略不得锁死整批评测。
2. **反例（负例模式）**：`execute_formal_records` 批里混入一条慢记录时，
   整批必须**照常返回**（不崩溃、不锁死、逐条有轨迹）；被僵尸污染的余下
   读数如实记为 `INTERNAL_ERROR` 并通过 evidence 不完整 fail-closed，
   不得带着无标记的污染读数继续。
3. **边界**：快策略在充足超时下的行为与不带包装的 `run_episode` 逐字节一致
   ——包装对正常路径零干扰，否则历史证据的可比性被破坏。
4. **突变**：慢策略的睡眠时长有限（不是无限挂起），测试同时断言耗时上界与
   终止原因。删掉超时包装（突变）时测试**变红而不是挂死**——红色来自
   「终止原因不符」与「耗时超界」两个断言。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from veritool_rl.core.agent.policy import PolicyOutput
from veritool_rl.core.agent.qwen import GeneratedText
from veritool_rl.core.agent.runner import run_episode
from veritool_rl.core.envs.base import ToolSchema
from veritool_rl.core.trajectory import TaskScenario
from veritool_rl.core.trajectory.schema import TaskSpec, TerminationReason
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
from veritool_rl.retail_ops.evaluate.base_evaluation import (
    _run_episode_with_timeout as _base_run_episode_with_timeout,
)
from veritool_rl.retail_ops.evaluate.base_evaluation import (
    execute_formal_records,
)

BUNDLE_DIR = "domains/retail_ops/v1"

#: 慢策略的睡眠时长。必须**远大于**超时值（保证被终止）且**有限**（保证突变时
#: 测试变红而不是挂死）、**远小于** pytest 默认无超时的可容忍等待（保证红色快速）。
SLOW_POLICY_SLEEP_SECONDS = 6.0
EPISODE_TIMEOUT_SECONDS = 0.2
#: 超时包装自身的开销上界。真实实现是 daemon 线程 + `worker.join(timeout)`，
#: 终止应在超时值附近完成；给到 5 秒是给 CI 抖动留余量，同时远小于睡眠时长。
ELAPSED_UPPER_BOUND_SECONDS = 5.0


class SlowPolicy:
    """第一次 respond 时长时间阻塞的策略——模拟推理后端卡死。"""

    name = "slow-policy"

    def __init__(self, sleep_seconds: float = SLOW_POLICY_SLEEP_SECONDS) -> None:
        self._sleep_seconds = sleep_seconds
        self._first_call_seen = False

    def respond(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema],
    ) -> PolicyOutput:
        del messages, tools
        if not self._first_call_seen:
            self._first_call_seen = True
            time.sleep(self._sleep_seconds)
        return PolicyOutput(raw_text="已完成。", final_response="已完成。")


class FastPolicy:
    """立即收尾的策略——正常路径的代表。"""

    name = "fast-policy"

    def respond(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSchema],
    ) -> PolicyOutput:
        del messages, tools
        return PolicyOutput(
            raw_text="已为您查询完毕。",
            final_response="已为您查询完毕。",
            input_tokens=32,
            output_tokens=6,
            latency_ms=2.0,
        )


class SlowFirstCallPolicy(SlowPolicy):
    """只阻塞第一次 respond 的慢策略：批内单条被终止、其余照常的负例用。"""

    name = "slow-first-call-policy"


def _task(task_id: str) -> TaskSpec:
    state = {"customer_id": "C-1", "current_day": 20, "orders": {}}
    return TaskSpec(
        task_id=task_id,
        split="qualification",
        scenario=TaskScenario.LOOKUP_STATUS,
        user_request="我想查一下我那笔订单现在到哪了。",
        initial_state=state,
        target_state=state,
        metadata={"order_id": "O-ABC123456789"},
    )


def _env_factory() -> Any:
    bundle = load_bundle(Path(BUNDLE_DIR))
    return lambda task: RetailOpsEnv(task, bundle)


# ---------------------------------------------------------------------------
# 正例：慢策略被超时终止
# ---------------------------------------------------------------------------


def test_slow_policy_is_terminated_by_the_base_evaluation_timeout() -> None:
    started = time.perf_counter()
    trajectory = _base_run_episode_with_timeout(
        _task("t-slow"),
        _env_factory(),
        SlowPolicy(),
        seed=0,
        timeout=EPISODE_TIMEOUT_SECONDS,
    )
    elapsed = time.perf_counter() - started

    assert trajectory.termination is TerminationReason.INTERNAL_ERROR
    assert trajectory.success is False
    assert trajectory.steps == []
    assert trajectory.metadata["infrastructure_error"] == "episode_timeout"
    assert trajectory.metadata["timeout_s"] == EPISODE_TIMEOUT_SECONDS
    assert elapsed < ELAPSED_UPPER_BOUND_SECONDS, (
        f"慢策略耗时 {elapsed:.2f}s 未被超时终止——整批评测会被锁死"
    )


def test_slow_policy_is_terminated_by_the_ood_evaluation_timeout() -> None:
    from veritool_rl.retail_ops.evaluate.ood_evaluation import (
        _run_episode_with_timeout as _ood_run_episode_with_timeout,
    )

    started = time.perf_counter()
    trajectory = _ood_run_episode_with_timeout(
        _task("t-slow-ood"),
        _env_factory(),
        SlowPolicy(),
        seed=0,
        timeout=EPISODE_TIMEOUT_SECONDS,
    )
    elapsed = time.perf_counter() - started

    assert trajectory.termination is TerminationReason.INTERNAL_ERROR
    assert trajectory.success is False
    assert trajectory.metadata["infrastructure_error"] == "episode_timeout"
    assert elapsed < ELAPSED_UPPER_BOUND_SECONDS


# ---------------------------------------------------------------------------
# 反例（负例模式）：批内一条慢记录被终止，其余照常——整批不得被锁死
# ---------------------------------------------------------------------------


def test_a_slow_record_is_terminated_without_crashing_the_batch() -> None:
    """批内一条慢记录被终止，**整批照常返回**而不崩溃、不锁死。

    后端串行化语义（对齐 serve 的信号量纪律）：被超时放弃的僵尸线程持有批内
    后端锁直到自然结束；后续 episode 的等待计入它们自己的超时窗口，等待耗尽的
    也如实记为 `INTERNAL_ERROR`。因此一个真实挂起会**毒化余下批次**——所有
    受污染读数都被丢弃（replayed=0、evidence 不完整、发布门禁 fail-closed），
    但绝不会带着被并发污染却毫无标记的读数继续。
    """
    from dataclasses import dataclass
    from typing import cast

    from veritool_rl.retail_ops.domain.formal_tasks import FormalTaskRecord

    @dataclass(frozen=True)
    class _Record:
        """`execute_formal_records` 只访问 `record.task`，用轻量替身即可。"""

        task: TaskSpec

    bundle = load_bundle(Path(BUNDLE_DIR))
    records = cast(
        "list[FormalTaskRecord]",
        [_Record(_task(f"t-batch-{index}")) for index in range(3)],
    )
    policy = SlowFirstCallPolicy()

    started = time.perf_counter()
    trajectories, replayed = execute_formal_records(
        records,
        bundle,
        policy,  # type: ignore[arg-type]
        seed=0,
        episode_timeout=EPISODE_TIMEOUT_SECONDS,
    )
    elapsed = time.perf_counter() - started

    assert len(trajectories) == 3
    for trajectory in trajectories:
        assert trajectory.termination is TerminationReason.INTERNAL_ERROR
        assert trajectory.metadata["infrastructure_error"] == "episode_timeout"
    assert replayed == 0
    assert elapsed < ELAPSED_UPPER_BOUND_SECONDS, (
        f"批处理耗时 {elapsed:.2f}s——一条慢记录锁死了整批评测"
    )


def test_backend_lock_serializes_episodes_and_recovers_after_release() -> None:
    """后端锁被占用时 episode 如实超时；锁释放后恢复正常——确定性、无睡眠。"""
    import threading

    lock = threading.Lock()
    task = _task("t-serialized")
    with lock:  # 模拟僵尸线程持有后端
        blocked = _base_run_episode_with_timeout(
            task,
            _env_factory(),
            FastPolicy(),
            seed=0,
            timeout=EPISODE_TIMEOUT_SECONDS,
            backend_lock=lock,
        )
        assert blocked.termination is TerminationReason.INTERNAL_ERROR
        assert blocked.metadata["infrastructure_error"] == "episode_timeout"

    recovered = _base_run_episode_with_timeout(
        task,
        _env_factory(),
        FastPolicy(),
        seed=0,
        timeout=30.0,
        backend_lock=lock,
    )
    assert recovered.termination is TerminationReason.FINAL_RESPONSE
    assert recovered.success is False  # 查询类任务未调工具，verifier 不给满分


# ---------------------------------------------------------------------------
# 边界：快策略不受包装干扰（正常路径零回归）
# ---------------------------------------------------------------------------


def test_fast_policy_output_is_identical_with_and_without_the_timeout_wrapper() -> None:
    task = _task("t-fast")
    direct = run_episode(task, _env_factory(), FastPolicy(), seed=0)
    wrapped = _base_run_episode_with_timeout(
        task,
        _env_factory(),
        FastPolicy(),
        seed=0,
        timeout=30.0,
    )

    assert wrapped.model_dump(mode="json") == direct.model_dump(mode="json")
    assert wrapped.termination is TerminationReason.FINAL_RESPONSE


def test_timeout_wrapper_propagates_the_seed_into_trajectory_metadata() -> None:
    trajectory = _base_run_episode_with_timeout(
        _task("t-seed"),
        _env_factory(),
        FastPolicy(),
        seed=7,
        timeout=30.0,
    )

    assert trajectory.metadata["seed"] == 7


# ---------------------------------------------------------------------------
# 突变验证的契约说明（本文件自身的守卫）
# ---------------------------------------------------------------------------


def test_slow_policy_sleep_exceeds_the_timeout_window() -> None:
    """守卫本文件自己的常量：睡眠不足或超时过大都会让上面的突变失去意义。

    突变（删掉超时包装）发生时，慢策略会**正常完成**并返回
    FINAL_RESPONSE/SUCCESS 轨迹——上面的终止原因断言与耗时断言都会红。
    这条测试保证慢策略真的跨过了超时窗口，红色只能来自突变本身。
    """
    assert SLOW_POLICY_SLEEP_SECONDS > 10 * EPISODE_TIMEOUT_SECONDS
    assert SLOW_POLICY_SLEEP_SECONDS < 60.0
    assert EPISODE_TIMEOUT_SECONDS < ELAPSED_UPPER_BOUND_SECONDS


def test_generated_text_contract_is_untouched_by_this_module() -> None:
    """`GeneratedText` 只是导入契约占位：确认导入面没有随测试漂移。"""
    payload = GeneratedText(text="ok", input_tokens=1, output_tokens=1, latency_ms=1.0)
    assert payload.text == "ok"
