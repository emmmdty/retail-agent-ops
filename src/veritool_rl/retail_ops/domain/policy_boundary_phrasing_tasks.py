"""政策边界探针 × 措辞池的二维迭代面（Phase C3，生成器部分）。

## 它解决什么

R7 判负的机制（`POLICY_BOUNDARY.md` §6）：探针措辞与训练同源，
「同源评测面高估修复收益」——数据侧修复在探针与 dev 上改善、在措辞分布外退化，
而探针**看不见**措辞型退化。本模块把探针任务的用户话术改用措辞池分片，
让同一次迭代同时看见边界型（`offset` 轴）与措辞型（`phrasing_id` 维度）退化。

## 复用而不新造

- 任务**就是** `build_policy_boundary_tasks` 的产物：状态、gold 序列、
  `ood_kind`（偏移量）、类别、`max_steps` 逐字节相同——只有 `user_request`
  与 `task_id` 换掉。决策曲线的横轴不变；`metadata["probe_task_id"]`
  反向指回同格探针任务，支持成对比较；
- 措辞经 `phrasing_bank.paraphrases_for_task` 的确定性选取（起点 = 任务哈希）
  与 `{order_id}` 占位符填充——与 OOD v2/v4 同一条措辞链路。

分片必须传评测分片（`ood_dev` / `ood_sealed`）：用 `train_aug` 当评测面
测的是「背没背下训练数据」，不是边界校准。
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from veritool_rl.core.trajectory import TaskSpec
from veritool_rl.retail_ops.build.phrasing_bank import (
    INTENT_REFUND,
    Partition,
    PhrasingRecord,
    paraphrases_for_task,
)
from veritool_rl.retail_ops.domain.policy_boundary_tasks import (
    INSTANCES_PER_OFFSET,
    build_policy_boundary_tasks,
    expected_category_counts,
)

POLICY_BOUNDARY_PHRASING_DATASET_VERSION = "retail_ops_policy_boundary_phrasing_v1_20260904"
POLICY_BOUNDARY_PHRASING_GENERATOR_ID = "policy_boundary_phrasing_sweep_v1"

_EVALUATION_PARTITIONS: tuple[Partition, ...] = ("ood_dev", "ood_sealed")


def expected_phrasing_category_counts() -> dict[str, int]:
    """与探针同形：放行侧 8 格 × n + 拒绝侧 7 格 × n。"""
    return expected_category_counts()


def build_policy_boundary_phrasing_tasks(
    seed: int,
    index: Mapping[str, Sequence[PhrasingRecord]],
    *,
    partition: str,
    instances_per_offset: int = INSTANCES_PER_OFFSET,
) -> list[TaskSpec]:
    """沿探针网格生成交叉任务集；措辞全部来自指定分片的措辞池。"""
    if partition not in _EVALUATION_PARTITIONS:
        raise ValueError(
            f"交叉面只能用评测分片 ood_dev/ood_sealed，收到 {partition!r}——"
            f"用 train_aug 当评测面测的是有没有背下训练数据"
        )
    pool = list(index.get(INTENT_REFUND, ()))
    if len(pool) < instances_per_offset:
        raise ValueError(
            f"分片 {partition} 的 {INTENT_REFUND} 意图只有 {len(pool)} 条措辞，"
            f"少于每偏移量 {instances_per_offset} 个实例——措辞轴的覆盖不足，"
            f"交叉面会退化成措辞复读（调用方应传按分片过滤后的索引）"
        )
    probes = build_policy_boundary_tasks(seed)
    tasks: list[TaskSpec] = []
    for position, probe in enumerate(probes):
        offset = int(probe.metadata["deadline_offset_days"])
        instance = position % INSTANCES_PER_OFFSET

        (user_request,) = paraphrases_for_task(
            index,
            intent=INTENT_REFUND,
            task_key=f"boundary-phrasing:{seed}:{offset}:{instance}",
            count=1,
            order_id=str(probe.metadata["order_id"]),
        )
        metadata: dict[str, Any] = {
            **probe.metadata,
            "dataset_version": POLICY_BOUNDARY_PHRASING_DATASET_VERSION,
            "generator_id": POLICY_BOUNDARY_PHRASING_GENERATOR_ID,
            "probe_task_id": probe.task_id,
            "phrasing_id": hashlib.sha256(user_request.encode("utf-8")).hexdigest(),
            "phrasing_partition": partition,
        }
        tasks.append(
            probe.model_copy(
                update={
                    "task_id": hashlib.sha256(
                        f"boundary-phrasing-task:{seed}:{offset}:{instance}".encode()
                    ).hexdigest(),
                    "user_request": user_request,
                    "metadata": metadata,
                }
            )
        )
    return tasks
