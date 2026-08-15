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
from veritool_rl.retail_ops.domain.policy_rules import PolicyRule, resolve_rules

#: 每个 bundle 版本的冻结形状。就地放宽任何一项都会让"领域输入是版本化的"这句话
#: 失去意义——新语义必须作为**新版本**存在，旧版本逐字节不动。
#:
#: v2 与 v1 的工具名与类别完全相同：变的是 `refund_order` 的参数（新增必填
#: `idempotency_key`）与政策规则的表达形式，不是领域本身。
_FROZEN_TOOL_NAMES = ("get_order", "refund_order", "get_store_hours")
_FROZEN_CATEGORIES = (
    "lookup_status",
    "refund_eligible",
    "refund_denied_window",
    "refund_denied_ownership",
    "refund_denied_duplicate",
    "refund_recovery",
)
_SUPPORTED_BUNDLE_VERSIONS = ("1.0.0", "2.0.0")


class RetailOpsBundle(StrictModel):
    """RetailOps bundle 入口文档。"""

    schema_version: Literal["1.0", "2.0"] = "1.0"
    bundle_id: Literal["retail_ops"] = "retail_ops"
    bundle_version: Literal["1.0.0", "2.0.0"] = "1.0.0"
    tools_file: str
    policies_file: str
    release_file: str
    evaluator_id: Literal["retail_ops_v1"] = "retail_ops_v1"
    task_categories: list[str]


class ToolsDocument(StrictModel):
    """RetailOps 工具 schema 文档。"""

    schema_version: Literal["1.0", "2.0"] = "1.0"
    tools: list[ToolSchema]


class RetailOpsPolicies(StrictModel):
    """RetailOps 退款政策配置。

    `rules` 有两种合法形态，由 `policy_rules.resolve_rules` 分派：v1 是六个名字
    （解析到内置冻结规则集，YAML 不必改），v2 起是内联的声明式规则。
    `max_transient_retries` 从 v2 起真正驱动环境的瞬时故障上限，不再只是被解析。
    """

    schema_version: Literal["1.0", "2.0"] = "1.0"
    #: 保留 v1 的默认值，使既有构造点（含测试）不受放宽影响；v1 的取值由
    #: `_require_version_consistency` 显式冻结，v2 的 YAML 必须自己声明。
    policy_version: str = Field(default="1.0.0", min_length=1)
    refund_reasons: list[str]
    max_transient_retries: int = Field(default=1, ge=0)
    rules: list[Any]


class ReleasePolicyConfig(StrictModel):
    """RetailOps 发布门禁阈值。"""

    schema_version: Literal["1.0", "2.0"] = "1.0"
    policy_version: str = Field(default="1.0.0", min_length=1)
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
    policy_rules: tuple[PolicyRule, ...]
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
    if bundle.bundle_version not in _SUPPORTED_BUNDLE_VERSIONS:
        raise ValueError(f"未知 bundle 版本: {bundle.bundle_version}")
    if (
        tuple(bundle.task_categories) != _FROZEN_CATEGORIES
        or tuple(tool.name for tool in tools) != _FROZEN_TOOL_NAMES
    ):
        raise ValueError("RetailOps 工具集合或顺序不符合冻结契约")
    reason_schema = tools[1].parameters.get("properties", {}).get("reason", {})
    reason_enum = reason_schema.get("enum") if isinstance(reason_schema, dict) else None
    if reason_enum != policies.refund_reasons:
        raise ValueError("refund_order.reason.enum 必须与 refund_reasons 完全一致")
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
    bundle_hash = hashlib.sha256(
        canonical_json(component_hashes).encode("utf-8")
    ).hexdigest()
    return LoadedRetailOpsBundle(
        bundle=bundle,
        tools=tools,
        policies=policies,
        policy_rules=policy_rules,
        release=release,
        bundle_sha256=bundle_hash,
        component_sha256=component_hashes,
    )


def _require_version_consistency(
    bundle: RetailOpsBundle,
    tool_document: ToolsDocument,
    policies: RetailOpsPolicies,
    release: ReleasePolicyConfig,
) -> None:
    """四份文档必须同属一个版本，且 v1 的形状逐字段冻结。

    `RetailOpsPolicies` 的字段类型为了容纳 v2 而放宽了（`policy_version` 从
    `Literal["1.0.0"]` 变成任意非空串、`max_transient_retries` 从 `Literal[1]`
    变成整数）。放宽会让 v1 失去类型层的保护，因此在这里把 v1 的约束**显式**加回来：
    v1 的每一份已产出证据都依赖这些值，它们不能因为 v2 的存在而变得可改。
    """
    expected_schema = "1.0" if bundle.bundle_version == "1.0.0" else "2.0"
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
