"""FlightOps v1 versioned domain bundle loader.

Mirrors ``retail_ops.domain.bundle`` so a second domain reuses the exact same
bundle-contract shape: versioned schema, frozen tool names and categories per
version, component SHA-256, and a single ``bundle_sha256`` over the canonical
JSON of component hashes. The one-way dependency test asserts this module
imports only from ``core`` (and from this domain's own ``policy_rules``), never
from ``retail_ops`` — which is the structural proof that the bundle contract is
portable to a second domain.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import yaml
from pydantic import Field

from veritool_rl.core.artifacts import canonical_json, sha256_file
from veritool_rl.core.envs.base import ToolSchema
from veritool_rl.core.trajectory.schema import StrictModel
from veritool_rl.flight_ops.domain.policy_rules import PolicyRule, resolve_rules

#: The frozen shape of each bundle version. Relaxing any one of these makes
#: "domain input is versioned" lose its meaning — new semantics must exist as
#: a **new version**, old versions stay byte-identical.
_FROZEN_TOOL_NAMES = ("get_reservation", "rebook_flight", "get_flight_schedule")
_FROZEN_CATEGORIES = (
    "lookup_status",
    "rebook_eligible",
    "rebook_denied_window",
    "rebook_denied_ownership",
    "rebook_denied_duplicate",
    "rebook_recovery",
)
_SUPPORTED_BUNDLE_VERSIONS = ("1.0.0",)


class FlightOpsBundle(StrictModel):
    """FlightOps bundle entry document."""

    schema_version: Literal["1.0"] = "1.0"
    bundle_id: Literal["flight_ops"] = "flight_ops"
    bundle_version: Literal["1.0.0"] = "1.0.0"
    tools_file: str
    policies_file: str
    release_file: str
    evaluator_id: Literal["flight_ops_v1"] = "flight_ops_v1"
    task_categories: list[str]


class ToolsDocument(StrictModel):
    """FlightOps tool schema document."""

    schema_version: Literal["1.0"] = "1.0"
    tools: list[ToolSchema]


class FlightOpsPolicies(StrictModel):
    """FlightOps rebooking policy configuration.

    ``rules`` has the same two legal forms as RetailOps: v1 is six names
    (resolved to the built-in frozen rule set, the YAML need not change), and
    v2+ is inlined declarative rules. ``max_transient_retries`` drives the
    environment's transient-failure cap.
    """

    schema_version: Literal["1.0"] = "1.0"
    policy_version: str = Field(default="1.0.0", min_length=1)
    rebook_reasons: list[str]
    max_transient_retries: int = Field(default=1, ge=0)
    rules: list[Any]


class ReleasePolicyConfig(StrictModel):
    """FlightOps release gate thresholds (same shape as RetailOps)."""

    schema_version: Literal["1.0"] = "1.0"
    policy_version: str = Field(default="1.0.0", min_length=1)
    success_delta_min: float = Field(ge=0.0, le=1.0)
    critical_policy_violation_delta_max: int = Field(ge=0)
    invalid_call_count_max: Literal[0] = 0
    p95_latency_ratio_max: float = Field(ge=1.0)
    require_complete_evidence: Literal[True] = True


@dataclass(frozen=True)
class LoadedFlightOpsBundle:
    """A strictly validated FlightOps bundle carrying its content hashes."""

    bundle: FlightOpsBundle
    tools: tuple[ToolSchema, ...]
    policies: FlightOpsPolicies
    policy_rules: tuple[PolicyRule, ...]
    release: ReleasePolicyConfig
    bundle_sha256: str
    component_sha256: dict[str, str]


def _read_yaml(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"YAML 顶层必须是 mapping: {path}")
    return cast(dict[str, Any], loaded)


def load_bundle(bundle_dir: Path) -> LoadedFlightOpsBundle:
    """Load and validate the frozen FlightOps v1 domain bundle."""
    bundle = FlightOpsBundle.model_validate(_read_yaml(bundle_dir / "bundle.yaml"))
    tool_document = ToolsDocument.model_validate(_read_yaml(bundle_dir / bundle.tools_file))
    tools = tuple(tool_document.tools)
    policies = FlightOpsPolicies.model_validate(_read_yaml(bundle_dir / bundle.policies_file))
    release = ReleasePolicyConfig.model_validate(_read_yaml(bundle_dir / bundle.release_file))
    if bundle.bundle_version not in _SUPPORTED_BUNDLE_VERSIONS:
        raise ValueError(f"未知 bundle 版本: {bundle.bundle_version}")
    if (
        tuple(bundle.task_categories) != _FROZEN_CATEGORIES
        or tuple(tool.name for tool in tools) != _FROZEN_TOOL_NAMES
    ):
        raise ValueError("FlightOps 工具集合或顺序不符合冻结契约")
    reason_schema = tools[1].parameters.get("properties", {}).get("reason", {})
    reason_enum = reason_schema.get("enum") if isinstance(reason_schema, dict) else None
    if reason_enum != policies.rebook_reasons:
        raise ValueError("rebook_flight.reason.enum 必须与 rebook_reasons 完全一致")
    _require_version_consistency(bundle, tool_document, policies, release)
    policy_rules = resolve_rules(policies.rules)
    component_hashes = {
        name: sha256_file(bundle_dir / name)
        for name in (
            "bundle.yaml",
            bundle.tools_file,
            bundle.policies_file,
            bundle.release_file,
        )
    }
    bundle_hash = hashlib.sha256(canonical_json(component_hashes).encode("utf-8")).hexdigest()
    return LoadedFlightOpsBundle(
        bundle=bundle,
        tools=tools,
        policies=policies,
        policy_rules=policy_rules,
        release=release,
        bundle_sha256=bundle_hash,
        component_sha256=component_hashes,
    )


def _require_version_consistency(
    bundle: FlightOpsBundle,
    tool_document: ToolsDocument,
    policies: FlightOpsPolicies,
    release: ReleasePolicyConfig,
) -> None:
    """All four documents must belong to the same version, and v1's shape is
    frozen field-by-field."""
    expected_schema = "1.0"
    versions = {
        "tools": tool_document.schema_version,
        "policies": policies.schema_version,
        "release": release.schema_version,
        "bundle": bundle.schema_version,
    }
    drifted = {name: value for name, value in versions.items() if value != expected_schema}
    if drifted:
        raise ValueError(f"bundle 内文档 schema 版本不一致: {drifted}")
    if bundle.bundle_version == "1.0.0":
        if policies.policy_version != "1.0.0" or release.policy_version != "1.0.0":
            raise ValueError("v1 的 policy_version 已冻结为 1.0.0")
        if policies.max_transient_retries != 1:
            raise ValueError("v1 的 max_transient_retries 已冻结为 1")
