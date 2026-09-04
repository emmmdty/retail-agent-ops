"""episode 级超时执行：慢/卡死的策略不得锁死整批评测。

R4.5 审查（findings #3，高严重度）定性的后果是「模型一步卡住，整批 GPU 评测
挂死直到人工干预」。第一版修复用 `with ThreadPoolExecutor(...)` 包
`future.result(timeout)`——但 `Executor.__exit__` 会 `shutdown(wait=True)` 等
正在运行的线程返回，调用方在超时**之后**仍被阻塞整个卡死时长。测试
（`tests/test_evaluation_timeout.py`）用带耗时上界断言的慢策略抓到了这一点：
轨迹字段是对的，调用方却仍被锁满全程。

因此本实现改用**每条 episode 一个 daemon 线程**：

- 超时后调用方立即拿到 `INTERNAL_ERROR` 轨迹继续下一条，批次不再被锁死；
- daemon 线程不阻塞解释器退出——真正的挂死场景里进程可以正常被收尾；
- 工作线程里的异常在调用方原样重抛（与 `future.result()` 的语义一致），
  后端崩溃不能被静默降级成超时。

**后端串行化（`backend_lock`）**：被超时放弃的线程无法被杀死，它会继续持有
policy/backend。同一个模型对象上的并发生成不是受支持模式，还会让后续 episode
的 `latency_ms`（发布门禁项）与显存峰值读数被僵尸污染且**无任何标记**——
这与 `serve/service.py` 用信号量把超时后的工作压到串行的既有纪律是同一个
 hazard。批处理调用方因此必须传入一把**批内共享**的锁：僵尸线程持锁到自然
结束，后续 episode 的等待时间计入它们自己的超时窗口；等待耗尽的也如实记为
`INTERNAL_ERROR`（证据随后 fail-closed），而不是带着被污染的读数继续。
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from veritool_rl.core.agent.policy import Policy
from veritool_rl.core.agent.runner import run_episode
from veritool_rl.core.envs.base import ToolEnv
from veritool_rl.core.trajectory import Trajectory
from veritool_rl.core.trajectory.schema import TaskSpec, TerminationReason


def run_episode_with_timeout(
    task: TaskSpec,
    env_factory: Callable[[TaskSpec], ToolEnv],
    policy: Policy,
    seed: int,
    timeout: float,
    *,
    backend_lock: threading.Lock | None = None,
) -> Trajectory:
    """在时限内运行单个 episode；超时返回 `INTERNAL_ERROR` 轨迹。

    超时是**评测基础设施的保险丝**，不是模型指标：被终止的轨迹带
    `infrastructure_error="episode_timeout"` 元数据，让基础设施失败在
    失败 taxonomy 里与模型失败分开。
    """
    result: list[Trajectory] = []
    error: list[BaseException] = []

    def _target() -> None:
        try:
            if backend_lock is not None:
                with backend_lock:
                    result.append(run_episode(task, env_factory, policy, seed))
            else:
                result.append(run_episode(task, env_factory, policy, seed))
        except BaseException as exc:
            error.append(exc)

    worker = threading.Thread(target=_target, daemon=True, name=f"episode-{task.task_id}")
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        return _timeout_trajectory(task, timeout)
    if error:
        raise error[0]
    return result[0]


def _timeout_trajectory(task: TaskSpec, timeout: float) -> Trajectory:
    return Trajectory(
        task=task,
        steps=[],
        final_state={},
        violations=[],
        termination=TerminationReason.INTERNAL_ERROR,
        success=False,
        metadata={"infrastructure_error": "episode_timeout", "timeout_s": timeout},
    )
