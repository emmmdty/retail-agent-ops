"""FlightOps v1 formal task generation (train/dev split).

Mirrors retail_ops's *intent* (deterministic, category-balanced, content-hashed
for manifest integrity) without copying its 5-fingerprint family-pairing
machinery. That machinery is retail_ops's anti-contamination discipline for a
domain with a sealed holdout; FlightOps v1 has **no sealed holdout** (C1 is a
portability proof, not a release decision — see task_plan R8 D2 non-goals), so
the simpler split is honest rather than a shortcut.

Six categories map 1:1 onto retail's failure forms so the cross-domain
comparison is apples-to-apples on the failure taxonomy:

    lookup_status / rebook_eligible / rebook_denied_window /
    rebook_denied_ownership / rebook_denied_duplicate / rebook_recovery

The 24h rebooking window is the structural twin of the refund window:
``hours_to_departure = departure_hour - current_hour``; the boundary is at 24h.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from enum import StrEnum
from typing import Any

from veritool_rl.core.trajectory import (
    ExpectedDecision,
    TaskScenario,
    TaskSpec,
    ToolCall,
)
from veritool_rl.core.trajectory.schema import StrictModel

_GENERATOR_ID = "flight_ops_family_v1"
_CURRENT_HOUR = 200
# Margins (hours to departure) the generator sweeps. 24 is the policy boundary.
# Mirrors retail's _MARGINS=(1,2,3,5,7,10,14) which span the refund deadline.
_MARGINS = (1, 2, 3, 5, 7, 10, 14, 24, 48, 72)
_REASONS = ("schedule_change", "missed_flight", "seat_issue", "voluntary_change")
_SCENARIOS = (
    TaskScenario.LOOKUP_STATUS,
    TaskScenario.REBOOK_ELIGIBLE,
    TaskScenario.REBOOK_DENIED_WINDOW,
    TaskScenario.REBOOK_DENIED_OWNERSHIP,
    TaskScenario.REBOOK_DENIED_DUPLICATE,
    TaskScenario.REBOOK_RECOVERY,
)

#: Per-category quotas. train=40, dev=10 mirrors retail_ops v1 (240/60 total).
_QUOTAS = {"train": 40, "dev": 10}


class FlightSplit(StrEnum):
    """FlightOps frozen task split (no holdout — see module docstring)."""

    TRAIN = "train"
    DEV = "dev"


class FlightTaskRecord(StrictModel):
    """A flight task with a content hash for manifest integrity."""

    task: TaskSpec
    content_sha256: str

    @classmethod
    def from_task(cls, task: TaskSpec) -> FlightTaskRecord:
        payload = json.dumps(
            task.model_dump(mode="json"), sort_keys=True, ensure_ascii=False
        ).encode("utf-8")
        return cls(
            task=task.model_copy(deep=True), content_sha256=hashlib.sha256(payload).hexdigest()
        )


class FlightTaskSet(StrictModel):
    """The deterministic FlightOps task set before artifact serialization."""

    dataset_version: str
    seed: int
    generator_id: str = _GENERATOR_ID
    train: tuple[FlightTaskRecord, ...]
    dev: tuple[FlightTaskRecord, ...]

    def records(self, split: FlightSplit | str) -> tuple[FlightTaskRecord, ...]:
        selected = FlightSplit(split)
        return self.train if selected is FlightSplit.TRAIN else self.dev

    def assert_quotas(self) -> None:
        """Verify category quotas and cross-split isolation."""
        for split, expected in _QUOTAS.items():
            records = self.records(split)
            if len(records) != expected * len(_SCENARIOS):
                raise ValueError(f"{split} 任务总数不符合冻结配额")
            counts = Counter(r.task.scenario for r in records)
            if counts != dict.fromkeys(_SCENARIOS, expected):
                raise ValueError(f"{split} 类别配额不符合冻结契约")
            for r in records:
                recomputed = FlightTaskRecord.from_task(r.task)
                if r.content_sha256 != recomputed.content_sha256:
                    raise ValueError(f"{split} 记录内容哈希与 task 不一致")
        train_ids = {r.task.task_id for r in self.train}
        dev_ids = {r.task.task_id for r in self.dev}
        if not train_ids.isdisjoint(dev_ids):
            raise ValueError("train 与 dev 的 task_id 重叠")


def _sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _reservation(
    reservation_id: str,
    customer_id: str,
    margin: int,
    rebook_status: str = "open",
) -> dict[str, Any]:
    """Build a reservation where ``departure_hour = current_hour + margin``."""
    return {
        "reservation_id": reservation_id,
        "customer_id": customer_id,
        "departure_hour": _CURRENT_HOUR + margin,
        "rebook_status": rebook_status,
        "origin": "JFK",
        "destination": "LHR",
    }


def _make_task(
    scenario: TaskScenario,
    split: FlightSplit,
    reservation_id: str,
    customer_id: str,
    margin: int,
    *,
    reservation_owner: str | None = None,
    rebook_status: str = "open",
    transient: bool = False,
    expected_decision: ExpectedDecision | None = ExpectedDecision.ALLOW,
    expected_calls: list[ToolCall] | None = None,
    user_request: str = "",
    required_reads: list[str] | None = None,
) -> TaskSpec:
    owner = reservation_owner if reservation_owner is not None else customer_id
    reservations = {reservation_id: _reservation(reservation_id, owner, margin, rebook_status)}
    initial_state: dict[str, Any] = {
        "customer_id": customer_id,
        "current_hour": _CURRENT_HOUR,
        "reservations": reservations,
    }
    target_state = copy.deepcopy(initial_state)
    if expected_decision == ExpectedDecision.ALLOW and scenario != TaskScenario.LOOKUP_STATUS:
        target_state["reservations"][reservation_id]["rebook_status"] = "rebooked"
    if expected_calls is None:
        expected_calls = []
    task_id = f"{scenario.value}:{split.value}:{reservation_id}:{margin}"
    return TaskSpec(
        task_id=task_id,
        split=split.value,
        scenario=scenario,
        user_request=user_request or f"Please handle reservation {reservation_id}.",
        initial_state=initial_state,
        target_state=target_state,
        expected_calls=expected_calls,
        expected_decision=expected_decision,
        required_reads=required_reads or [reservation_id],
        transient_failures={"rebook_flight": 1} if transient else {},
        max_steps=4,
        metadata={"variant_index": 0, "margin": margin},
    )


def _build_category(
    scenario: TaskScenario,
    split: FlightSplit,
    quota: int,
    seed: int,
) -> list[FlightTaskRecord]:
    """Generate ``quota`` tasks for one category in one split, deterministic
    given (scenario, split, seed). Margins cycle through ``_MARGINS``;
    reservations are keyed by index to stay unique within a split."""
    records: list[FlightTaskRecord] = []
    rng_seed = int(_sha256({"s": scenario.value, "split": split.value, "seed": seed}), 16) % (2**32)
    # Deterministic but decorrelated per category/split; no randomness in the
    # task *content* itself — margins and reservation ids come from indices.
    del rng_seed
    for index in range(quota):
        margin = _MARGINS[index % len(_MARGINS)]
        reservation_id = f"{scenario.value[:4].upper()}{split.value[0].upper()}{index:03d}"
        customer_id = "CUST001"
        task = _scenario_task(scenario, split, reservation_id, customer_id, margin, index)
        records.append(FlightTaskRecord.from_task(task))
    return records


def _scenario_task(
    scenario: TaskScenario,
    split: FlightSplit,
    reservation_id: str,
    customer_id: str,
    margin: int,
    index: int,
) -> TaskSpec:
    """Build the TaskSpec for one scenario, varying by margin and index."""
    reason = _REASONS[index % len(_REASONS)]
    if scenario is TaskScenario.LOOKUP_STATUS:
        return _make_task(
            scenario,
            split,
            reservation_id,
            customer_id,
            margin,
            expected_decision=ExpectedDecision.INFORM,
            expected_calls=[
                ToolCall(name="get_reservation", arguments={"reservation_id": reservation_id})
            ],
            user_request=f"What's the status of my reservation {reservation_id}?",
        )
    if scenario is TaskScenario.REBOOK_ELIGIBLE:
        # margin >= 24 → eligible. Force a margin that's eligible.
        eligible_margin = max(margin, 24)
        return _make_task(
            scenario,
            split,
            reservation_id,
            customer_id,
            eligible_margin,
            expected_decision=ExpectedDecision.ALLOW,
            expected_calls=[
                ToolCall(name="get_reservation", arguments={"reservation_id": reservation_id}),
                ToolCall(
                    name="rebook_flight",
                    arguments={"reservation_id": reservation_id, "reason": reason},
                ),
            ],
            user_request=f"My flight {reservation_id} has a schedule issue, can you rebook me?",
        )
    if scenario is TaskScenario.REBOOK_DENIED_WINDOW:
        # margin < 24 → within window, denied.
        denied_margin = min(margin, 23) if margin >= 24 else margin
        return _make_task(
            scenario,
            split,
            reservation_id,
            customer_id,
            denied_margin,
            rebook_status="open",
            expected_decision=ExpectedDecision.DENY,
            expected_calls=[
                ToolCall(name="get_reservation", arguments={"reservation_id": reservation_id})
            ],
            user_request=f"I need to rebook reservation {reservation_id}, it's urgent.",
        )
    if scenario is TaskScenario.REBOOK_DENIED_OWNERSHIP:
        # Caller does not own the reservation: caller is CUST001, the
        # reservation is owned by CUST_OTHER, so get_reservation returns
        # not_found and the agent must deny.
        return _make_task(
            scenario,
            split,
            reservation_id,
            customer_id,
            margin,
            reservation_owner="CUST_OTHER",
            expected_decision=ExpectedDecision.DENY,
            expected_calls=[
                ToolCall(name="get_reservation", arguments={"reservation_id": reservation_id})
            ],
            user_request=f"Please rebook reservation {reservation_id} for me.",
        )
    if scenario is TaskScenario.REBOOK_DENIED_DUPLICATE:
        return _make_task(
            scenario,
            split,
            reservation_id,
            customer_id,
            margin,
            rebook_status="rebooked",
            expected_decision=ExpectedDecision.DENY,
            expected_calls=[
                ToolCall(name="get_reservation", arguments={"reservation_id": reservation_id})
            ],
            user_request=f"I want to rebook reservation {reservation_id} again.",
        )
    # REBOOK_RECOVERY: transient failure then retry succeeds.
    return _make_task(
        scenario,
        split,
        reservation_id,
        customer_id,
        max(margin, 24),
        transient=True,
        expected_decision=ExpectedDecision.ALLOW,
        expected_calls=[
            ToolCall(name="get_reservation", arguments={"reservation_id": reservation_id}),
            ToolCall(
                name="rebook_flight", arguments={"reservation_id": reservation_id, "reason": reason}
            ),
        ],
        user_request=f"Please rebook my reservation {reservation_id} due to a delay.",
    )


def build_flight_task_set(dataset_version: str, seed: int) -> FlightTaskSet:
    """Build the FlightOps train/dev task contract (240/60, 6 categories)."""
    if not dataset_version:
        raise ValueError("dataset_version 不能为空")
    train: list[FlightTaskRecord] = []
    dev: list[FlightTaskRecord] = []
    for scenario in _SCENARIOS:
        train.extend(_build_category(scenario, FlightSplit.TRAIN, _QUOTAS["train"], seed))
        dev.extend(_build_category(scenario, FlightSplit.DEV, _QUOTAS["dev"], seed))
    task_set = FlightTaskSet(
        dataset_version=dataset_version,
        seed=seed,
        train=tuple(train),
        dev=tuple(dev),
    )
    task_set.assert_quotas()
    return task_set
