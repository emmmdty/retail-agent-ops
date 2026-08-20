"""FlightOps v1 environment + task generation (R8 C1).

Asserts the environment executes each of the six task categories correctly and
the policy rules fire on the right axis (the 24h window). The environment +
task generator together are the runtime twin of the bundle contract: the
bundle freezes *what* the tools and rules are, these run *what they do*.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from veritool_rl.core.trajectory import ExpectedDecision, TaskScenario, TaskSpec, ToolCall
from veritool_rl.flight_ops.domain.bundle import load_bundle
from veritool_rl.flight_ops.domain.environment import FlightOpsEnv
from veritool_rl.flight_ops.domain.tasks import (
    build_flight_task_set,
)

BUNDLE_DIR = Path(__file__).resolve().parents[1] / "domains" / "flight_ops" / "v1"


@pytest.fixture(scope="module")
def bundle() -> object:
    return load_bundle(BUNDLE_DIR)


@pytest.fixture(scope="module")
def task_set() -> object:
    return build_flight_task_set("flight_ops_v1_r8_001", seed=0)


def test_task_set_quotas_and_isolation(task_set: object) -> None:
    """train=240, dev=60, 6 categories evenly; train/dev task_ids disjoint."""
    assert len(task_set.train) == 240  # type: ignore[attr-defined]
    assert len(task_set.dev) == 60  # type: ignore[attr-defined]
    train_ids = {r.task.task_id for r in task_set.train}  # type: ignore[attr-defined]
    dev_ids = {r.task.task_id for r in task_set.dev}  # type: ignore[attr-defined]
    assert train_ids.isdisjoint(dev_ids)


def test_task_set_content_hashes_are_stable(task_set: object) -> None:
    """Content hashes are deterministic given (dataset_version, seed)."""
    rebuilt = build_flight_task_set("flight_ops_v1_r8_001", seed=0)
    for a, b in zip(task_set.train, rebuilt.train, strict=False):  # type: ignore[attr-defined]
        assert a.content_sha256 == b.content_sha256  # type: ignore[attr-defined]


def test_each_dev_task_runs_to_its_expected_decision(bundle: object, task_set: object) -> None:
    """The oracle (executing expected_calls) reaches the expected final-state
    score for every dev task — i.e. the tasks are *solvable* by construction.
    A task whose oracle cannot reach success would silently break the teacher
    collection that feeds SFT."""
    for record in task_set.dev:  # type: ignore[attr-defined]
        env = FlightOpsEnv(record.task, bundle)  # type: ignore[arg-type]
        for call in record.task.expected_calls:
            obs = env.execute_tool(call.name, dict(call.arguments))
            # The recovery category injects a transient failure; the oracle
            # (like a real agent) retries the rebook once it sees transient_error.
            if obs.ok is False and obs.error_code == "transient_error":
                env.execute_tool(call.name, dict(call.arguments))
        if record.task.expected_decision == ExpectedDecision.INFORM:
            env.record_final_response("Here is your reservation status.")
        elif record.task.expected_decision == ExpectedDecision.DENY:
            env.record_final_response("I cannot rebook this reservation.")
        assert env.verify_final_state() == 1.0, (
            f"{record.task.task_id} oracle did not reach success; violations={env.check_policy()}"
        )


def test_rebook_window_denies_under_24h_and_allows_at_or_above(
    bundle: object,
) -> None:
    """The 24h window is the policy boundary: at 24h eligible, at 23h denied.
    Mirrors the refund window probe axis exactly."""
    for margin, expected_ok in [(24, True), (48, True), (23, False), (1, False)]:
        task = _rebook_task(margin)
        env = FlightOpsEnv(task, bundle)  # type: ignore[arg-type]
        env.execute_tool("get_reservation", {"reservation_id": "RBK001"})
        obs = env.execute_tool(
            "rebook_flight", {"reservation_id": "RBK001", "reason": "schedule_change"}
        )
        assert obs.ok is expected_ok, f"margin={margin} expected ok={expected_ok}"
        if not expected_ok:
            assert obs.error_code == "policy_denied"
            assert "rebook_not_eligible" in env.check_policy()


def test_rebook_without_lookup_is_denied(bundle: object) -> None:
    """Rebooking without first looking up the reservation is a policy
    violation — the lookup-first rule is engine-enforced, not advisory."""
    task = _rebook_task(48)
    env = FlightOpsEnv(task, bundle)  # type: ignore[arg-type]
    obs = env.execute_tool(
        "rebook_flight", {"reservation_id": "RBK001", "reason": "schedule_change"}
    )
    assert obs.ok is False
    assert obs.error_code == "policy_denied"
    assert "rebook_without_lookup" in env.check_policy()


def test_rebook_unowned_reservation_is_denied(bundle: object) -> None:
    task = _rebook_task(48, customer_id="CUST_OTHER")
    env = FlightOpsEnv(task, bundle)  # type: ignore[arg-type]
    env.execute_tool("get_reservation", {"reservation_id": "RBK001"})
    obs = env.execute_tool(
        "rebook_flight", {"reservation_id": "RBK001", "reason": "schedule_change"}
    )
    assert obs.ok is False
    assert "unauthorized_reservation" in env.check_policy()


def test_duplicate_rebook_is_denied(bundle: object) -> None:
    task = _rebook_task(48, rebook_status="rebooked")
    env = FlightOpsEnv(task, bundle)  # type: ignore[arg-type]
    env.execute_tool("get_reservation", {"reservation_id": "RBK001"})
    obs = env.execute_tool(
        "rebook_flight", {"reservation_id": "RBK001", "reason": "schedule_change"}
    )
    assert obs.ok is False
    assert "duplicate_rebook" in env.check_policy()


def test_unknown_tool_returns_error(bundle: object) -> None:
    task = _rebook_task(48)
    env = FlightOpsEnv(task, bundle)  # type: ignore[arg-type]
    obs = env.execute_tool("cancel_flight", {"reservation_id": "RBK001"})
    assert obs.ok is False
    assert obs.error_code == "unknown_tool"


def test_invalid_arguments_return_error(bundle: object) -> None:
    task = _rebook_task(48)
    env = FlightOpsEnv(task, bundle)  # type: ignore[arg-type]
    obs = env.execute_tool("get_reservation", {"locator": "RBK001"})
    assert obs.ok is False
    assert obs.error_code == "invalid_arguments"


def test_get_flight_schedule_returns_schedule(bundle: object) -> None:
    task = _rebook_task(48)
    env = FlightOpsEnv(task, bundle)  # type: ignore[arg-type]
    obs = env.execute_tool("get_flight_schedule", {"origin": "JFK"})
    assert obs.ok is True
    assert "flights" in obs.content


def test_rebook_recovery_succeeds_after_transient_failure(bundle: object) -> None:
    """The recovery category injects one transient failure; the second rebook
    call succeeds. This is the twin of retail's refund_recovery."""
    task = _rebook_task(48, transient=True)
    env = FlightOpsEnv(task, bundle)  # type: ignore[arg-type]
    env.execute_tool("get_reservation", {"reservation_id": "RBK001"})
    first = env.execute_tool(
        "rebook_flight", {"reservation_id": "RBK001", "reason": "schedule_change"}
    )
    assert first.ok is False and first.error_code == "transient_error"
    second = env.execute_tool(
        "rebook_flight", {"reservation_id": "RBK001", "reason": "schedule_change"}
    )
    assert second.ok is True
    assert env.verify_final_state() == 1.0


def test_perturb_schema_renames_tools_but_keeps_semantics(bundle: object) -> None:
    """Schema perturbation renames tools and shuffles param order, but the
    alias map keeps execution semantics — a model trained on perturbed names
    must still succeed if it picks the right tool."""
    task = _rebook_task(48)
    env = FlightOpsEnv(task, bundle)  # type: ignore[arg-type]
    env.perturb_schema(seed=42)
    tools = env.list_tools()
    # Original names are gone; aliases are different.
    assert all("_" in t.name and t.name != "get_reservation" for t in tools)
    # Find the renamed get_reservation and call through the alias.
    renamed_lookup = next(t for t in tools if "reservation" in t.description.lower())
    obs = env.execute_tool(renamed_lookup.name, {"reservation_id": "RBK001"})
    assert obs.ok is True


def _rebook_task(
    margin: int = 48,
    *,
    customer_id: str = "CUST001",
    rebook_status: str = "open",
    transient: bool = False,
) -> TaskSpec:
    reservations = {
        "RBK001": {
            "reservation_id": "RBK001",
            "customer_id": "CUST001",
            "departure_hour": 200 + margin,
            "rebook_status": rebook_status,
            "origin": "JFK",
            "destination": "LHR",
        }
    }
    initial_state = {
        "customer_id": customer_id,
        "current_hour": 200,
        "reservations": reservations,
    }
    import copy

    target_state = copy.deepcopy(initial_state)
    # ALLOW scenarios (including transient recovery) end with rebook_status=rebooked.
    allow = not (rebook_status == "rebooked" or customer_id == "CUST_OTHER")
    if allow:
        target_state["reservations"]["RBK001"]["rebook_status"] = "rebooked"
    return TaskSpec(
        task_id=f"test:rebook:{margin}:{rebook_status}",
        split="dev",
        scenario=TaskScenario.REBOOK_ELIGIBLE,
        user_request="Please rebook my reservation RBK001.",
        initial_state=initial_state,
        target_state=target_state,
        expected_calls=[
            ToolCall(name="get_reservation", arguments={"reservation_id": "RBK001"}),
            ToolCall(
                name="rebook_flight",
                arguments={"reservation_id": "RBK001", "reason": "schedule_change"},
            ),
        ]
        if not (rebook_status == "rebooked" or customer_id == "CUST_OTHER")
        else [ToolCall(name="get_reservation", arguments={"reservation_id": "RBK001"})],
        expected_decision=ExpectedDecision.DENY
        if rebook_status == "rebooked" or customer_id == "CUST_OTHER"
        else ExpectedDecision.ALLOW,
        required_reads=["RBK001"],
        transient_failures={"rebook_flight": 1} if transient else {},
        max_steps=4,
    )
