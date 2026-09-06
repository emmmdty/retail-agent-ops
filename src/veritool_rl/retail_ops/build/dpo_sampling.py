"""DPO 偏好对采样器（r11 主线，A-2/A-3）。

## 它在修什么

D4 判定（LOG-20260905-03）：发布候选 `sft-008` 在「封存集零政策违规」绝对门下
NO-GO，违规集中在 `refund_denied_window` 的「该拒绝却执行」。SFT 补数据修不掉
（R7 判负：补覆盖是平移不是校准）。DPO 是当前唯一未被证伪的根治路径：
同状态下「拒绝（chosen）」与「执行（rejected）」构成偏好对，直接校准决策边界。

## 设计约束（全部有测试锁定）

- **rejected 必须是模型自己的失败采样**（`DPO_ENTRY_EVIDENCE_D2.md` §二.2）：
  本模块只做配对，轨迹由 GPU 采样脚本经真实 `run_episode` + `RetailOpsEnv` 产生；
  测试夹具同样走真实链路，不手工构造失败轨迹。
- **chosen = Oracle 轨迹**：模型无关、逐位确定，与 SFT 数据同一条消息格式链路
  （`core.generators.trajectory_messages`）。
- **门禁守卫方案**（用户 2026-09-06 裁定）：偏好对只来自 DENY 任务单一方向；
  防平移由预注册的「放行侧不塌」门禁承担，本模块负责前提检查——
  放行侧采样出现执行类错误时 `premise_ok=False`，调用方必须停下回用户决策。
- **溯源**：每对携带 `task_id` + `sample_index` + 两个任务面的 dataset_version。
  采样逐样本确定性播种（`sample_seed`），同一份权重重跑可复现。

判读规则与运行清单见 `task_plan.md` 的 DPO 预注册（先于一切运行提交）。
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal

from pydantic import ConfigDict, Field, field_validator

from veritool_rl.core.agent.policy import OraclePolicy
from veritool_rl.core.agent.runner import run_episode
from veritool_rl.core.artifacts import canonical_json
from veritool_rl.core.envs.base import ToolEnv
from veritool_rl.core.generators import trajectory_messages
from veritool_rl.core.trajectory import (
    ExpectedDecision,
    TaskSpec,
    Trajectory,
)
from veritool_rl.core.trajectory.schema import StrictModel, validate_json_value
from veritool_rl.retail_ops.build.phrasing_bank import PhrasingRecord
from veritool_rl.retail_ops.domain.policy_boundary_phrasing_tasks import (
    POLICY_BOUNDARY_PHRASING_DATASET_VERSION,
    build_policy_boundary_phrasing_tasks,
)
from veritool_rl.retail_ops.domain.policy_boundary_tasks import (
    POLICY_BOUNDARY_DATASET_VERSION,
    build_policy_boundary_tasks,
)

DPO_SAMPLING_GENERATOR_ID = "dpo_preference_sampling_v1"

#: 预注册的采样协议：每任务 N=8 条轨迹，temperature 0.8。
SAMPLES_PER_TASK = 8

#: 「该拒绝却执行」的违规签名（`domains/retail_ops/v2/policies.yaml` 的
#: `refund_window_must_be_open` 规则）。偏好对只收这一种失败。
REFUND_NOT_ELIGIBLE = "refund_not_eligible"

PHRASING_SOURCE = "policy_boundary_phrasing"

_SOURCE_BY_FACE_DATASET_VERSION: Mapping[str, str] = {
    POLICY_BOUNDARY_DATASET_VERSION: "policy_boundary_probe",
    POLICY_BOUNDARY_PHRASING_DATASET_VERSION: PHRASING_SOURCE,
}

EnvFactory = Callable[[TaskSpec], ToolEnv]


class SamplingSettings(StrictModel):
    """采样专用的生成契约。

    与正式评测的 `GenerationSettings`（do_sample 恒 False）**刻意不共用**：
    那是全部已有评测证据的确定性契约，一个字段都不能动。DPO 采样需要
    temperature 0.8 的随机采样，因此另立一个冻结类，把预注册的采样协议
    变成机器守卫——温度写错配置根本构造不出来。
    """

    model_config = ConfigDict(frozen=True)

    max_new_tokens: int = Field(default=256, ge=1, le=4096)
    do_sample: Literal[True] = True
    #: 预注册采样协议（task_plan `eeec309`）：temperature 0.8、top_p 1.0、top_k 0。
    #: float 不是合法的 Literal 参数（PEP 586），契约由下方校验器机器锁定。
    temperature: float = 0.8
    top_p: float = 1.0
    top_k: int = 0
    enable_thinking: Literal[False] = False
    quantization: Literal["nf4"] = "nf4"

    @field_validator("temperature")
    @classmethod
    def _lock_temperature(cls, value: float) -> float:
        if value != 0.8:
            msg = f"采样温度已预注册冻结为 0.8，收到 {value!r}"
            raise ValueError(msg)
        return value

    @field_validator("top_p")
    @classmethod
    def _lock_top_p(cls, value: float) -> float:
        if value != 1.0:
            msg = f"top_p 已预注册冻结为 1.0（纯温度采样），收到 {value!r}"
            raise ValueError(msg)
        return value

    @field_validator("top_k")
    @classmethod
    def _lock_top_k(cls, value: int) -> int:
        if value != 0:
            msg = f"top_k 已预注册冻结为 0（关闭 top-k 过滤），收到 {value!r}"
            raise ValueError(msg)
        return value

    def generate_kwargs(self) -> dict[str, Any]:
        """传给 `TransformersBackend(generate_kwargs=...)` 的采样开关。

        do_sample 覆盖评测后端默认的 `settings.do_sample=False`——采样后端与
        评测后端是同一条加载链路，差别只有这一组显式 kwargs（含 temperature/
        top_p/top_k，不留给模型 generation_config 的默认值）。
        """
        return {
            "do_sample": self.do_sample,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
        }


def sample_seed(task_id: str, sample_index: int) -> int:
    """逐样本确定性播种：同一权重重跑得到同一批采样轨迹。"""
    digest = hashlib.sha256(f"dpo-sample:{task_id}:{sample_index}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


def _pair_source_for(task: TaskSpec) -> str:
    """由任务面的 dataset_version 严格映射来源标签；未知版本一律拒绝。"""
    source = _SOURCE_BY_FACE_DATASET_VERSION.get(str(task.metadata["dataset_version"]))
    if source is None:
        version = str(task.metadata["dataset_version"])
        msg = (
            f"任务面的 dataset_version {version!r} 不在已登记的采样面清单里——"
            f"采样面只允许探针与 C3 交叉面两个来源"
        )
        raise ValueError(msg)
    return source


def build_sampling_face(
    *,
    seed: int,
    phrasing_index: Mapping[str, Sequence[PhrasingRecord]] | None = None,
    phrasing_partition: str = "ood_dev",
) -> list[TaskSpec]:
    """组装采样任务面：政策边界探针（120）+ C3 交叉面（120）。

    交叉面的措辞取措辞池的**评测分片**（装置强制）：bank-004 的 `ood_dev`
    分片未用于任何训练与评测，措辞分布外——R7 的教训是不在同源措辞上修边界。
    """
    tasks = list(build_policy_boundary_tasks(seed))
    if phrasing_index is not None:
        tasks.extend(
            build_policy_boundary_phrasing_tasks(seed, phrasing_index, partition=phrasing_partition)
        )
    return tasks


def oracle_reference(task: TaskSpec, env_factory: EnvFactory, seed: int = 0) -> Trajectory:
    """DENY 任务的 chosen 侧：Oracle 轨迹（查订单 → 结束），逐位确定。

    探针的 DENY 任务 gold 序列只有 `get_order`：状态本就等于目标状态，
    「拒绝」由**不执行退款**表达——与冻结训练数据里拒绝类样本的形状一致。
    """
    trajectory = run_episode(task, env_factory, OraclePolicy(task), seed=seed)
    if not trajectory.success:
        msg = f"Oracle 未能解出 DENY 任务，装置自洽被破坏: {task.task_id}"
        raise RuntimeError(msg)
    if trajectory.violations:
        msg = f"Oracle 轨迹带政策违规，装置自洽被破坏: {task.task_id}"
        raise RuntimeError(msg)
    return trajectory


def split_prompt_completion(
    trajectory: Trajectory,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """把轨迹切成 prompt（system+user）与 completion（其余消息）。"""
    messages = trajectory_messages(trajectory)
    if len(messages) < 3:
        msg = f"轨迹没有任何 completion 消息: {trajectory.task.task_id}"
        raise ValueError(msg)
    prompt = messages[:2]
    if prompt[0]["role"] != "system" or prompt[1]["role"] != "user":
        msg = f"轨迹消息序列必须以 system+user 开头: {trajectory.task.task_id}"
        raise ValueError(msg)
    return prompt, messages[2:]


class DpoPairRecord(StrictModel):
    """一条偏好对及其完整溯源。"""

    pair_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_id: str = Field(min_length=1)
    sample_index: int = Field(ge=0)
    source: str = Field(min_length=1)
    face_dataset_version: str = Field(min_length=1)
    face_generator_id: str = Field(min_length=1)
    deadline_offset_days: int
    phrasing_id: str | None = None
    probe_task_id: str | None = None
    prompt: list[dict[str, Any]]
    chosen: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    rejected_violations: list[str]

    _validate_prompt = field_validator("prompt")(validate_json_value)
    _validate_chosen = field_validator("chosen")(validate_json_value)
    _validate_rejected = field_validator("rejected")(validate_json_value)
    _validate_tools = field_validator("tools")(validate_json_value)


class DpoSamplingReport(StrictModel):
    """采样报告：实际配对数与方向分布（预注册要求写进产物）。

    `premise_ok=False` 表示门禁守卫方案的前提（放行侧零执行类错误）不成立，
    调用方必须停止并回用户决策——不得悄悄构造对冲对。
    """

    generator_id: str = DPO_SAMPLING_GENERATOR_ID
    face_task_counts: dict[str, int]
    sampled_tasks: int
    sample_count: int
    deny_tasks: int
    deny_tasks_with_pairs: int
    pairs_total: int
    pairs_per_offset: dict[str, int]
    allow_side_violation_samples: int
    allow_side_failed_samples: int
    premise_ok: bool
    pairs: list[DpoPairRecord]


def build_preference_pairs(
    *,
    tasks: Sequence[TaskSpec],
    samples: Mapping[str, Sequence[Trajectory]],
    oracle: Mapping[str, Trajectory],
) -> DpoSamplingReport:
    """按预注册配对规则把采样轨迹变成偏好对。

    - DENY 任务（offset < 0）：chosen = Oracle 轨迹；rejected = 该任务采样中
      真实发生 `refund_not_eligible` 的轨迹（violation 与 refund_order 调用
      必须同时在场，二者缺一说明装置有问题，直接失败）；
    - ALLOW 任务：不产对，只统计「放行侧不塌」前提检查所需计数；
    - 同任务内按 rejected 内容去重，保留首个 sample_index。
    """
    face_task_counts: dict[str, int] = {}
    for task in tasks:
        source = _pair_source_for(task)
        face_task_counts[source] = face_task_counts.get(source, 0) + 1

    pairs: list[DpoPairRecord] = []
    pairs_per_offset: dict[str, int] = {}
    deny_tasks = 0
    deny_tasks_with_pairs = 0
    allow_side_violation_samples = 0
    allow_side_failed_samples = 0

    for task in tasks:
        task_samples = _require_samples(task, samples)
        if task.expected_decision is ExpectedDecision.ALLOW:
            for trajectory in task_samples:
                allow_side_failed_samples += int(trajectory.termination.value != "success")
                allow_side_violation_samples += int(bool(trajectory.violations))
            continue

        deny_tasks += 1
        chosen_oracle = oracle.get(task.task_id)
        if chosen_oracle is None:
            msg = f"任务缺少 Oracle 参照轨迹: {task.task_id}"
            raise ValueError(msg)
        _, chosen = split_prompt_completion(chosen_oracle)
        seen_rejected: set[str] = set()
        task_pair_count = 0
        for sample_index, trajectory in enumerate(task_samples):
            if REFUND_NOT_ELIGIBLE not in trajectory.violations:
                continue
            _require_refund_attempt(trajectory)
            prompt, rejected = split_prompt_completion(trajectory)
            content_key = hashlib.sha256(canonical_json(rejected).encode("utf-8")).hexdigest()
            if content_key in seen_rejected:
                continue
            seen_rejected.add(content_key)
            pairs.append(
                _build_pair(
                    task=task,
                    sample_index=sample_index,
                    prompt=prompt,
                    chosen=chosen,
                    rejected=rejected,
                    chosen_oracle=chosen_oracle,
                    rejected_trajectory=trajectory,
                )
            )
            task_pair_count += 1
        if task_pair_count:
            deny_tasks_with_pairs += 1
            kind = str(task.metadata["ood_kind"])
            pairs_per_offset[kind] = pairs_per_offset.get(kind, 0) + task_pair_count

    return DpoSamplingReport(
        face_task_counts=face_task_counts,
        sampled_tasks=len(tasks),
        sample_count=sum(len(_require_samples(task, samples)) for task in tasks),
        deny_tasks=deny_tasks,
        deny_tasks_with_pairs=deny_tasks_with_pairs,
        pairs_total=len(pairs),
        pairs_per_offset=dict(sorted(pairs_per_offset.items())),
        allow_side_violation_samples=allow_side_violation_samples,
        allow_side_failed_samples=allow_side_failed_samples,
        premise_ok=allow_side_violation_samples == 0,
        pairs=pairs,
    )


def _require_samples(
    task: TaskSpec, samples: Mapping[str, Sequence[Trajectory]]
) -> Sequence[Trajectory]:
    task_samples = samples.get(task.task_id)
    if task_samples is None:
        msg = f"任务没有任何采样轨迹（采样不完整时报告会说谎）: {task.task_id}"
        raise ValueError(msg)
    for trajectory in task_samples:
        if trajectory.task.task_id != task.task_id:
            msg = f"采样轨迹与任务不匹配: {trajectory.task.task_id} != {task.task_id}"
            raise ValueError(msg)
    return task_samples


def _require_refund_attempt(trajectory: Trajectory) -> None:
    """`refund_not_eligible` 必须真的来自一次 refund_order 执行。

    违规签名与调用记录缺一时，说明环境或配对逻辑有问题——这种对不能进训练。
    """
    if any(
        step.tool_call is not None and step.tool_call.name == "refund_order"
        for step in trajectory.steps
    ):
        return
    msg = (
        f"轨迹带 {REFUND_NOT_ELIGIBLE} 违规却没有任何 refund_order 调用，"
        f"装置自洽被破坏: {trajectory.task.task_id}"
    )
    raise ValueError(msg)


def _build_pair(
    *,
    task: TaskSpec,
    sample_index: int,
    prompt: list[dict[str, Any]],
    chosen: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    chosen_oracle: Trajectory,
    rejected_trajectory: Trajectory,
) -> DpoPairRecord:
    tools = chosen_oracle.metadata.get("tools")
    if not isinstance(tools, list):
        msg = f"Oracle 轨迹缺少训练所需的 tools: {task.task_id}"
        raise ValueError(msg)
    source = _pair_source_for(task)
    face_dataset_version = str(task.metadata["dataset_version"])
    phrasing_id = task.metadata.get("phrasing_id")
    probe_task_id = task.metadata.get("probe_task_id")
    identity = {
        "generator_id": DPO_SAMPLING_GENERATOR_ID,
        "task_id": task.task_id,
        "sample_index": sample_index,
        "source": source,
        "face_dataset_version": face_dataset_version,
        "chosen": chosen,
        "rejected": rejected,
    }
    return DpoPairRecord(
        pair_id=hashlib.sha256(canonical_json(identity).encode("utf-8")).hexdigest(),
        task_id=task.task_id,
        sample_index=sample_index,
        source=source,
        face_dataset_version=face_dataset_version,
        face_generator_id=str(task.metadata["generator_id"]),
        deadline_offset_days=int(task.metadata["deadline_offset_days"]),
        phrasing_id=str(phrasing_id) if phrasing_id is not None else None,
        probe_task_id=str(probe_task_id) if probe_task_id is not None else None,
        prompt=prompt,
        chosen=chosen,
        rejected=rejected,
        tools=tools,
        rejected_violations=list(rejected_trajectory.violations),
    )
