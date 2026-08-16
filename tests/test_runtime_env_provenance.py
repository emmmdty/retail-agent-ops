"""P0（本轮自查）：证据必须说得出它到底跑在哪个引擎、哪个环境里。

`uv_lock_sha256` 哈希的是仓库里的 `uv.lock` **文件**（`product_cli.py:1500`），
不是实际装了什么包。2026-08-16 的三次 vLLM 评测就是在一个完全不同的 venv
（Python 3.12 + vLLM）里跑的，而产出的证据逐字段声称用的是冻结依赖——
**没有任何机制发现得了**。

这份测试锁住三条：

1. 新证据必须记录 `inference_engine` 与 `runtime_env_sha256`；
2. **换一个环境必须改变 `runtime_env_sha256`**，否则这个字段没有意义；
3. **已产出的 v1.0 证据 `run_id` 复算逐位不变**——这是这次扩展能做的唯一前提，
   与 sealed v1.1 那次同一个道理。
"""

from __future__ import annotations

import pytest


def test_the_runtime_env_digest_changes_with_the_installed_packages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """不同 venv 必须算出不同摘要；否则它挡不住"换个环境偷偷跑"。"""
    from veritool_rl.core import artifacts

    class _Dist:
        def __init__(self, name: str, version: str) -> None:
            self.metadata = {"Name": name}
            self.version = version

    monkeypatch.setattr(
        artifacts, "_installed_distributions", lambda: [_Dist("torch", "2.13.0")]
    )
    first = artifacts.current_runtime_env_sha256()
    monkeypatch.setattr(
        artifacts,
        "_installed_distributions",
        lambda: [_Dist("torch", "2.13.0"), _Dist("vllm", "0.27.1")],
    )
    second = artifacts.current_runtime_env_sha256()

    assert first != second, "装了 vLLM 的环境必须与冻结环境算出不同的摘要"
    assert len(first) == 64


def test_the_digest_is_order_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    """同一组包无论枚举顺序如何都必须得到同一个摘要，否则它不可复现。"""
    from veritool_rl.core import artifacts

    class _Dist:
        def __init__(self, name: str, version: str) -> None:
            self.metadata = {"Name": name}
            self.version = version

    monkeypatch.setattr(
        artifacts,
        "_installed_distributions",
        lambda: [_Dist("a", "1"), _Dist("b", "2")],
    )
    forward = artifacts.current_runtime_env_sha256()
    monkeypatch.setattr(
        artifacts,
        "_installed_distributions",
        lambda: [_Dist("b", "2"), _Dist("a", "1")],
    )

    assert artifacts.current_runtime_env_sha256() == forward


# ---------------------------------------------------------------------------
# 证据侧：新增字段绝不能作废任何一份已产出的证据
# ---------------------------------------------------------------------------


def test_existing_v1_0_evidence_still_recomputes_bit_identically() -> None:
    """v1.0 证据看不到 v1.1 才有的字段，复算结果必须与它当初落盘时逐位相同。

    这是这次扩展**能做的唯一前提**——与 sealed v1.1 那次同一个道理
    （`SEALED_HASHED_FIELDS`）。做不到就等于把已有全部 dev / OOD 证据作废。
    """
    from tests.helpers_base_evidence import make_base_evidence
    from veritool_rl.retail_ops.evaluate.base_evaluation import (
        RUNTIME_PROVENANCE_FIELDS,
        _content_id,
    )

    assert RUNTIME_PROVENANCE_FIELDS == {"inference_engine", "runtime_env_sha256"}

    # 一份"2026-08-16 之前"的证据：加载后两个新字段都是 None。
    legacy = make_base_evidence()
    before = _content_id(legacy, "run_id")

    # 同一份内容，只是补上了运行时溯源——摘要必须改变，否则这两个字段没有约束力。
    annotated = legacy.model_copy(
        update={"inference_engine": "vllm", "runtime_env_sha256": "c" * 64}
    )

    assert _content_id(annotated, "run_id") != before
    # 而把它们清回 None 必须回到原值：这正是旧证据仍能复算通过的机制。
    assert _content_id(annotated.model_copy(
        update={"inference_engine": None, "runtime_env_sha256": None}
    ), "run_id") == before


def test_new_evidence_records_the_engine_and_the_environment() -> None:
    """新证据必须说得出它跑在哪个引擎、哪个环境；两者缺一都留下静默的空白。"""
    from veritool_rl.retail_ops.evaluate.base_evaluation import BaseRunEvidence

    fields = BaseRunEvidence.model_fields

    assert "inference_engine" in fields
    assert "runtime_env_sha256" in fields

    # 半份记录必须被拒绝：知道引擎却不知道环境（或反之）回答不了"跑在哪里"。
    from tests.helpers_base_evidence import make_base_evidence

    with pytest.raises(ValueError, match="同时记录或同时缺失"):
        make_base_evidence(inference_engine="vllm")
    with pytest.raises(ValueError, match="同时记录或同时缺失"):
        make_base_evidence(runtime_env_sha256="d" * 64)
