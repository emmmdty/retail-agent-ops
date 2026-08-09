"""Provider-agnostic teacher 路由解析与公开快照。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any, Literal, Self
from urllib.parse import urlsplit, urlunsplit

from pydantic import ConfigDict, Field, field_validator, model_validator

from veritool_rl.core.artifacts import canonical_json
from veritool_rl.core.trajectory.schema import StrictModel, validate_json_value

TEACHER_PROTOCOL_ID: Literal["openai-chat-completions-tools-v1"] = (
    "openai-chat-completions-tools-v1"
)
_PROVIDER_PATTERN = re.compile(r"[a-z][a-z0-9_]*\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_SECRET_KEY_PARTS = ("key", "token", "authorization", "secret")
_MAX_EXTRA_BODY_BYTES = 16 * 1024


class TeacherRouteSnapshot(StrictModel):
    """不含凭据、可稳定哈希的 teacher 路由快照。"""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        frozen=True,
    )

    provider: str
    base_url: str
    model: str = Field(min_length=1)
    extra_body: dict[str, Any] = Field(default_factory=dict)
    protocol_id: Literal["openai-chat-completions-tools-v1"] = TEACHER_PROTOCOL_ID
    route_sha256: str

    _validate_extra_body = field_validator("extra_body")(validate_json_value)

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        if _PROVIDER_PATTERN.fullmatch(value) is None:
            msg = "provider 名称不合法"
            raise ValueError(msg)
        return value

    @field_validator("route_sha256")
    @classmethod
    def validate_route_sha256(cls, value: str) -> str:
        if _SHA256_PATTERN.fullmatch(value) is None:
            msg = "route_sha256 必须是小写 SHA-256"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def validate_route_hash(self) -> Self:
        expected = _route_sha256(
            provider=self.provider,
            base_url=self.base_url,
            model=self.model,
            extra_body=self.extra_body,
            protocol_id=self.protocol_id,
        )
        if self.route_sha256 != expected:
            msg = "teacher route 快照哈希不匹配"
            raise ValueError(msg)
        return self


def load_teacher_route(
    environ: Mapping[str, str],
) -> tuple[TeacherRouteSnapshot, str]:
    """只解析所选 provider namespace，并单独返回内存中的 API key。"""
    provider = environ.get("TEACHER_LLM_PROVIDER", "")
    if _PROVIDER_PATTERN.fullmatch(provider) is None:
        msg = "TEACHER_LLM_PROVIDER 必须匹配 [a-z][a-z0-9_]*"
        raise ValueError(msg)

    prefix = f"TEACHER_LLM_{provider.upper()}_"
    base_url = _required_value(environ, prefix, "BASE_URL")
    api_key = _required_value(environ, prefix, "API_KEY")
    model = _required_value(environ, prefix, "MODEL")
    extra_body = _parse_extra_body(environ.get(f"{prefix}EXTRA_BODY_JSON", ""))
    normalized_base_url = _normalize_base_url(base_url)
    route_sha256 = _route_sha256(
        provider=provider,
        base_url=normalized_base_url,
        model=model,
        extra_body=extra_body,
        protocol_id=TEACHER_PROTOCOL_ID,
    )
    snapshot = TeacherRouteSnapshot(
        provider=provider,
        base_url=normalized_base_url,
        model=model,
        extra_body=extra_body,
        protocol_id=TEACHER_PROTOCOL_ID,
        route_sha256=route_sha256,
    )
    return snapshot, api_key


def _required_value(
    environ: Mapping[str, str],
    prefix: str,
    suffix: str,
) -> str:
    value = environ.get(f"{prefix}{suffix}")
    if value is None or not value.strip():
        msg = f"选中的 teacher profile 缺少 {suffix}"
        raise ValueError(msg)
    return value.strip()


def _normalize_base_url(value: str) -> str:
    if any(character.isspace() for character in value):
        msg = "选中的 BASE_URL 必须是无凭据、query 或 fragment 的 HTTPS URL"
        raise ValueError(msg)
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        msg = "选中的 BASE_URL 必须是无凭据、query 或 fragment 的 HTTPS URL"
        raise ValueError(msg) from None
    if (
        parsed.scheme.casefold() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or "@" in parsed.netloc
        or parsed.query
        or parsed.fragment
    ):
        msg = "选中的 BASE_URL 必须是无凭据、query 或 fragment 的 HTTPS URL"
        raise ValueError(msg)

    hostname = parsed.hostname.casefold()
    if ":" in hostname:
        hostname = f"[{hostname}]"
    netloc = hostname if port is None else f"{hostname}:{port}"
    path = parsed.path.rstrip("/")
    return urlunsplit(("https", netloc, path, "", ""))


def _parse_extra_body(raw_value: str) -> dict[str, Any]:
    if not raw_value.strip():
        return {}
    if len(raw_value.encode("utf-8")) > _MAX_EXTRA_BODY_BYTES:
        msg = "选中的 EXTRA_BODY_JSON 超过大小限制"
        raise ValueError(msg)
    try:
        value = json.loads(
            raw_value,
            parse_constant=lambda _: _reject_json_constant(),
        )
    except (json.JSONDecodeError, ValueError, TypeError, RecursionError):
        msg = "选中的 EXTRA_BODY_JSON 必须是有限 JSON object"
        raise ValueError(msg) from None
    if not isinstance(value, dict):
        msg = "选中的 EXTRA_BODY_JSON 必须是有限 JSON object"
        raise ValueError(msg)
    try:
        validate_json_value(value)
        _reject_secret_keys(value)
    except (TypeError, ValueError):
        msg = "选中的 EXTRA_BODY_JSON 包含不允许的字段或值"
        raise ValueError(msg) from None
    return value


def _reject_json_constant() -> None:
    msg = "JSON constant 不允许"
    raise ValueError(msg)


def _reject_secret_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = key.casefold()
            if any(part in normalized for part in _SECRET_KEY_PARTS):
                msg = "extra body 不允许 secret-like key"
                raise ValueError(msg)
            _reject_secret_keys(item)
    elif isinstance(value, list):
        for item in value:
            _reject_secret_keys(item)


def _route_sha256(
    *,
    provider: str,
    base_url: str,
    model: str,
    extra_body: dict[str, Any],
    protocol_id: str,
) -> str:
    payload = {
        "base_url": base_url,
        "extra_body": extra_body,
        "model": model,
        "protocol_id": protocol_id,
        "provider": provider,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
