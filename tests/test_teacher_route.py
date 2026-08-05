"""动态 teacher provider 路由与 secret 边界测试。"""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest

from veritool_rl.retail_ops.teacher_route import load_teacher_route

DEEPSEEK_KEY = "deepseek-key-material"
OTHER_KEY = "other-key-material"


def _environment(provider: str = "deepseek") -> dict[str, str]:
    return {
        "TEACHER_LLM_PROVIDER": provider,
        "TEACHER_LLM_DEEPSEEK_BASE_URL": "https://API.DeepSeek.com/",
        "TEACHER_LLM_DEEPSEEK_API_KEY": DEEPSEEK_KEY,
        "TEACHER_LLM_DEEPSEEK_MODEL": "deepseek-v4-pro",
        "TEACHER_LLM_DEEPSEEK_EXTRA_BODY_JSON": (
            '{"thinking":{"type":"disabled"},"metadata":{"team":"retail"}}'
        ),
        "TEACHER_LLM_OTHER_BASE_URL": "https://teacher.example.test/v1/",
        "TEACHER_LLM_OTHER_API_KEY": OTHER_KEY,
        "TEACHER_LLM_OTHER_MODEL": "other-model",
        "TEACHER_LLM_OTHER_EXTRA_BODY_JSON": '{"response_format":{"type":"json_object"}}',
    }


def test_selector_changes_only_the_selected_dynamic_namespace() -> None:
    deepseek_env = _environment("deepseek")
    other_env = {**deepseek_env, "TEACHER_LLM_PROVIDER": "other"}

    deepseek, deepseek_key = load_teacher_route(deepseek_env)
    other, other_key = load_teacher_route(other_env)

    assert deepseek.provider == "deepseek"
    assert deepseek.base_url == "https://api.deepseek.com"
    assert deepseek.model == "deepseek-v4-pro"
    assert deepseek.extra_body == {
        "metadata": {"team": "retail"},
        "thinking": {"type": "disabled"},
    }
    assert deepseek_key == DEEPSEEK_KEY
    assert other.provider == "other"
    assert other.base_url == "https://teacher.example.test/v1"
    assert other.model == "other-model"
    assert other.extra_body == {"response_format": {"type": "json_object"}}
    assert other_key == OTHER_KEY
    assert deepseek.route_sha256 != other.route_sha256


def test_route_snapshot_and_hash_are_canonical_and_secret_free() -> None:
    first, key = load_teacher_route(_environment())
    reordered = dict(reversed(list(_environment().items())))
    second, _ = load_teacher_route(reordered)

    assert first == second
    assert len(first.route_sha256) == 64
    assert set(first.route_sha256) <= set("0123456789abcdef")
    public_forms = "\n".join(
        [
            repr(first),
            first.model_dump_json(),
            json.dumps(first.model_dump(mode="json"), sort_keys=True),
        ]
    )
    assert key == DEEPSEEK_KEY
    assert DEEPSEEK_KEY not in public_forms
    assert OTHER_KEY not in public_forms


@pytest.mark.parametrize(
    "provider",
    ["", "DeepSeek", "1provider", "provider-name", "provider.name", "provider name"],
)
def test_provider_selector_rejects_invalid_names(provider: str) -> None:
    with pytest.raises(ValueError, match="TEACHER_LLM_PROVIDER"):
        load_teacher_route(_environment(provider))


@pytest.mark.parametrize("suffix", ["BASE_URL", "API_KEY", "MODEL"])
def test_selected_profile_requires_all_core_fields_without_echoing_values(
    suffix: str,
) -> None:
    environ = _environment()
    del environ[f"TEACHER_LLM_DEEPSEEK_{suffix}"]

    with pytest.raises(ValueError) as error:
        load_teacher_route(environ)

    message = str(error.value)
    assert suffix in message
    assert DEEPSEEK_KEY not in message
    assert OTHER_KEY not in message


class _SelectedOnlyMapping(Mapping[str, str]):
    """只允许精确键读取，枚举 environment 即失败。"""

    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def __getitem__(self, key: str) -> str:
        return self._values[key]

    def __iter__(self):  # type: ignore[no-untyped-def]
        raise AssertionError("不得枚举 environment")

    def __len__(self) -> int:
        raise AssertionError("不得统计 environment")


def test_loader_reads_only_selected_keys_and_ignores_unselected_secrets() -> None:
    snapshot, key = load_teacher_route(_SelectedOnlyMapping(_environment()))

    assert snapshot.provider == "deepseek"
    assert key == DEEPSEEK_KEY


@pytest.mark.parametrize(
    "base_url",
    [
        "http://teacher.example.test/v1",
        "https://user@teacher.example.test/v1",
        "https://user:password@teacher.example.test/v1",
        "https://teacher.example.test/v1?mode=unsafe",
        "https://teacher.example.test/v1#fragment",
        "https:///missing-host",
    ],
)
def test_base_url_rejects_non_https_credentials_query_and_fragment(
    base_url: str,
) -> None:
    environ = _environment()
    environ["TEACHER_LLM_DEEPSEEK_BASE_URL"] = base_url

    with pytest.raises(ValueError, match="BASE_URL") as error:
        load_teacher_route(environ)

    assert DEEPSEEK_KEY not in str(error.value)


@pytest.mark.parametrize(
    "extra_body",
    [
        "not-json",
        "[]",
        "null",
        '{"nested":{"api_key":"forbidden"}}',
        '{"nested":{"accessToken":"forbidden"}}',
        '{"nested":{"Authorization":"forbidden"}}',
        '{"nested":{"client_secret":"forbidden"}}',
        '{"value":NaN}',
        "[" * 4000 + "]" * 4000,
    ],
)
def test_extra_body_requires_finite_secret_free_json_object(extra_body: str) -> None:
    environ = _environment()
    environ["TEACHER_LLM_DEEPSEEK_EXTRA_BODY_JSON"] = extra_body

    with pytest.raises(ValueError, match="EXTRA_BODY_JSON") as error:
        load_teacher_route(environ)

    message = str(error.value)
    assert DEEPSEEK_KEY not in message
    assert "forbidden" not in message


def test_extra_body_rejects_oversized_json_without_echoing_it() -> None:
    environ = _environment()
    oversized_marker = "oversized-sensitive-value"
    environ["TEACHER_LLM_DEEPSEEK_EXTRA_BODY_JSON"] = json.dumps(
        {"payload": oversized_marker * 2000}
    )

    with pytest.raises(ValueError, match="EXTRA_BODY_JSON") as error:
        load_teacher_route(environ)

    assert oversized_marker not in str(error.value)
