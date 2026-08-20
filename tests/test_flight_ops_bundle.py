"""FlightOps v1 domain bundle + policy rules (R8 C1 cross-domain portability).

These tests assert the second domain's bundle contract is isomorphic to the
retail domain's: same versioned schema, same frozen tool/category shape, same
component + bundle SHA-256, and the same policy-rule engine shape. The
structural proof that this is a real second domain (not an alias of retail_ops)
lives in ``test_source_layers_enforce_one_way_dependency`` — flight_ops imports
only from core.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from veritool_rl.flight_ops.domain.bundle import load_bundle
from veritool_rl.flight_ops.domain.policy_rules import (
    V1_BUILTIN_RULES,
    RebookFacts,
    evaluate_rebook_rules,
)

BUNDLE_DIR = Path(__file__).resolve().parents[1] / "domains" / "flight_ops" / "v1"


@pytest.fixture(scope="module")
def bundle() -> object:
    return load_bundle(BUNDLE_DIR)


def test_bundle_loads_with_all_component_hashes(bundle: object) -> None:
    """The bundle carries a SHA-256 for each of its four component files plus a
    single ``bundle_sha256`` over their canonical-JSON aggregate."""
    assert set(bundle.component_sha256) == {  # type: ignore[attr-defined]
        "bundle.yaml",
        "tools.yaml",
        "policies.yaml",
        "release.yaml",
    }
    assert len(bundle.bundle_sha256) == 64  # type: ignore[attr-defined]


def test_frozen_tool_names_and_order(bundle: object) -> None:
    """Tool names and order are frozen per version — a reordered or renamed tool
    would silently change which tool a trained model is calling."""
    assert [t.name for t in bundle.tools] == [  # type: ignore[attr-defined]
        "get_reservation",
        "rebook_flight",
        "get_flight_schedule",
    ]


def test_frozen_categories_match_retail_failure_shape(bundle: object) -> None:
    """The six task categories mirror retail's failure forms (lookup / eligible /
    denied-window / denied-ownership / denied-duplicate / recovery) so the
    cross-domain comparison is apples-to-apples on the failure taxonomy."""
    assert tuple(bundle.bundle.task_categories) == (  # type: ignore[attr-defined]
        "lookup_status",
        "rebook_eligible",
        "rebook_denied_window",
        "rebook_denied_ownership",
        "rebook_denied_duplicate",
        "rebook_recovery",
    )


def test_rebook_reason_enum_matches_policy_list(bundle: object) -> None:
    """``rebook_flight.reason.enum`` must equal ``policies.rebook_reasons``
    verbatim — a divergence means the schema and the policy disagree on which
    reasons exist."""
    reason_schema = bundle.tools[1].parameters["properties"]["reason"]  # type: ignore[attr-defined]
    assert reason_schema["enum"] == list(bundle.policies.rebook_reasons)  # type: ignore[attr-defined]


def test_v1_rules_resolve_to_four_denial_rules(bundle: object) -> None:
    """v1's six rule names resolve to four engine-enforceable denial rules; the
    last two (retry bound, schema strictness) are structural and enforced
    elsewhere — folding them in would muddy "rule = denial condition"."""
    assert [r.rule_id for r in bundle.policy_rules] == [  # type: ignore[attr-defined]
        "rebook_requires_lookup",
        "caller_must_own_reservation",
        "rebook_window_must_be_open",
        "duplicate_rebook_forbidden",
    ]


def test_rebook_window_rule_denies_under_24h() -> None:
    """The 24h rebooking window is the structural twin of the refund window:
    deny when ``hours_to_departure < 24``. This is the axis the policy-boundary
    probe scans, and it must behave identically to the refund rule."""
    rule = next(r for r in V1_BUILTIN_RULES if r.rule_id == "rebook_window_must_be_open")
    # Eligible: 24h exactly → the rule uses `lt 24`, so 24 does not fire.
    assert rule.when.holds(RebookFacts(True, True, 24, False, True)) is False
    # Denied: 23h → fires.
    decided = evaluate_rebook_rules(V1_BUILTIN_RULES, RebookFacts(True, True, 23, False, True))
    assert decided is not None and decided.violation == "rebook_not_eligible"


def test_duplicate_rebook_rule_fires_when_already_rebooked() -> None:
    decided = evaluate_rebook_rules(V1_BUILTIN_RULES, RebookFacts(True, True, 72, True, True))
    assert decided is not None and decided.violation == "duplicate_rebook"


def test_rules_evaluate_in_declaration_order() -> None:
    """A reservation that is both under 24h AND already rebooked reports the
    window violation first — order is contract, changing it changes the failure
    taxonomy for the same candidate."""
    decided = evaluate_rebook_rules(V1_BUILTIN_RULES, RebookFacts(True, True, 2, True, True))
    assert decided is not None and decided.rule_id == "rebook_window_must_be_open"


def test_rebook_requires_lookup_fires_first() -> None:
    decided = evaluate_rebook_rules(V1_BUILTIN_RULES, RebookFacts(False, False, 2, True, True))
    assert decided is not None and decided.rule_id == "rebook_requires_lookup"


def test_no_rule_fires_for_a_clean_eligible_rebook() -> None:
    decided = evaluate_rebook_rules(V1_BUILTIN_RULES, RebookFacts(True, True, 48, False, True))
    assert decided is None


def test_predicate_rejects_unknown_fact() -> None:
    from veritool_rl.flight_ops.domain.policy_rules import parse_predicate

    with pytest.raises(ValueError, match="未知事实"):
        parse_predicate({"fact": "weather_is_bad", "is": True})


def test_predicate_rejects_multiple_operators() -> None:
    from veritool_rl.flight_ops.domain.policy_rules import parse_predicate

    with pytest.raises(ValueError, match="只能声明一个算子"):
        parse_predicate({"fact": "hours_to_departure", "lt": 24, "gte": 0})


def test_bundle_version_consistency_rejects_drift(tmp_path: Path) -> None:
    """A bundle whose four documents disagree on schema_version must fail to
    load — at the Literal type layer or the explicit consistency check,
    whichever catches it first. Both are valid; the contract is "drift is
    rejected at load time, not at evaluation time"."""
    drift_dir = tmp_path / "drift"
    shutil.copytree(BUNDLE_DIR, drift_dir)
    tools_path = drift_dir / "tools.yaml"
    tools_path.write_text(
        tools_path.read_text(encoding="utf-8").replace(
            'schema_version: "1.0"', 'schema_version: "2.0"', 1
        ),
        encoding="utf-8",
    )
    with pytest.raises((ValueError, ValidationError)):
        load_bundle(drift_dir)


def test_bundle_rejects_renamed_tool(tmp_path: Path) -> None:
    """Renaming a tool must break the frozen contract — otherwise a trained
    model's tool names could silently drift."""
    drift_dir = tmp_path / "rename"
    shutil.copytree(BUNDLE_DIR, drift_dir)
    tools_path = drift_dir / "tools.yaml"
    tools_path.write_text(
        tools_path.read_text(encoding="utf-8").replace(
            "name: get_reservation", "name: fetch_reservation", 1
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="工具集合或顺序不符合冻结契约"):
        load_bundle(drift_dir)


def test_bundle_rejects_reason_enum_drift(tmp_path: Path) -> None:
    """If the tool's reason enum and the policy's reason list diverge, the
    schema and the policy disagree on which reasons exist — load must fail."""
    drift_dir = tmp_path / "reasons"
    shutil.copytree(BUNDLE_DIR, drift_dir)
    policies_path = drift_dir / "policies.yaml"
    policies_path.write_text(
        policies_path.read_text(encoding="utf-8").replace("- voluntary_change", "- voluntary", 1),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"rebook_flight\.reason\.enum"):
        load_bundle(drift_dir)
