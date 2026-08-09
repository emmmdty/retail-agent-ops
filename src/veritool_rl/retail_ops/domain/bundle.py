"""RetailOps v1 版本化领域 bundle 加载器。"""

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


class RetailOpsBundle(StrictModel):
    """RetailOps v1 bundle 入口文档。"""

    schema_version: Literal["1.0"] = "1.0"
    bundle_id: Literal["retail_ops"] = "retail_ops"
    bundle_version: Literal["1.0.0"] = "1.0.0"
    tools_file: str
    policies_file: str
    release_file: str
    evaluator_id: Literal["retail_ops_v1"] = "retail_ops_v1"
    task_categories: list[str]


class ToolsDocument(StrictModel):
    """RetailOps v1 工具 schema 文档。"""

    schema_version: Literal["1.0"] = "1.0"
    tools: list[ToolSchema]


class RetailOpsPolicies(StrictModel):
    """RetailOps v1 退款政策配置。"""

    schema_version: Literal["1.0"] = "1.0"
    policy_version: Literal["1.0.0"] = "1.0.0"
    refund_reasons: list[str]
    max_transient_retries: Literal[1] = 1
    rules: list[str]


class ReleasePolicyConfig(StrictModel):
    """RetailOps v1 发布门禁阈值。"""

    schema_version: Literal["1.0"] = "1.0"
    policy_version: Literal["1.0.0"] = "1.0.0"
    success_delta_min: float = Field(ge=0.0, le=1.0)
    critical_policy_violation_delta_max: int = Field(ge=0)
    invalid_call_count_max: Literal[0] = 0
    p95_latency_ratio_max: float = Field(ge=1.0)
    require_complete_evidence: Literal[True] = True


@dataclass(frozen=True)
class LoadedRetailOpsBundle:
    """经过严格校验并携带内容哈希的 RetailOps bundle。"""

    bundle: RetailOpsBundle
    tools: tuple[ToolSchema, ...]
    policies: RetailOpsPolicies
    release: ReleasePolicyConfig
    bundle_sha256: str
    component_sha256: dict[str, str]


def _read_yaml(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"YAML 顶层必须是 mapping: {path}")
    return cast(dict[str, Any], loaded)


def load_bundle(bundle_dir: Path) -> LoadedRetailOpsBundle:
    """加载并校验冻结的 RetailOps v1 领域 bundle。"""
    bundle = RetailOpsBundle.model_validate(_read_yaml(bundle_dir / "bundle.yaml"))
    tool_document = ToolsDocument.model_validate(
        _read_yaml(bundle_dir / bundle.tools_file)
    )
    tools = tuple(tool_document.tools)
    policies = RetailOpsPolicies.model_validate(
        _read_yaml(bundle_dir / bundle.policies_file)
    )
    release = ReleasePolicyConfig.model_validate(
        _read_yaml(bundle_dir / bundle.release_file)
    )
    if tuple(bundle.task_categories) != (
        "lookup_status",
        "refund_eligible",
        "refund_denied_window",
        "refund_denied_ownership",
        "refund_denied_duplicate",
        "refund_recovery",
    ) or tuple(tool.name for tool in tools) != (
        "get_order",
        "refund_order",
        "get_store_hours",
    ):
        raise ValueError("RetailOps v1 工具集合或顺序不符合冻结契约")
    reason_schema = tools[1].parameters.get("properties", {}).get("reason", {})
    reason_enum = reason_schema.get("enum") if isinstance(reason_schema, dict) else None
    if reason_enum != policies.refund_reasons:
        raise ValueError("refund_order.reason.enum 必须与 refund_reasons 完全一致")
    component_hashes = {
        name: sha256_file(bundle_dir / name)
        for name in (
            "bundle.yaml",
            bundle.tools_file,
            bundle.policies_file,
            bundle.release_file,
        )
    }
    bundle_hash = hashlib.sha256(
        canonical_json(component_hashes).encode("utf-8")
    ).hexdigest()
    return LoadedRetailOpsBundle(
        bundle=bundle,
        tools=tools,
        policies=policies,
        release=release,
        bundle_sha256=bundle_hash,
        component_sha256=component_hashes,
    )
