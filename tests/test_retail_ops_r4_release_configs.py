"""R4 第二次封存 holdout 观测的三份配置。

封存 holdout 的第二次观测是**不可逆**的一次性资源。这些断言存在的唯一目的是：
在消耗它之前，把"两侧只差 adapter""阈值一个字没改""不复用第一次观测的 attempt_id"
这三件事变成机器可检查的事实，而不是执行者的记忆。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = ROOT / "configs"

_R3_BASE = CONFIG_ROOT / "retail_ops/evaluate/retail_ops_v1_r3_qwen3_4b_holdout_base.yaml"
_R3_CAND = CONFIG_ROOT / "retail_ops/evaluate/retail_ops_v1_r3_qwen3_4b_holdout_candidate.yaml"
_R4_BASE = CONFIG_ROOT / "retail_ops/evaluate/retail_ops_v1_r4_holdout_base.yaml"
_R4_CAND = CONFIG_ROOT / "retail_ops/evaluate/retail_ops_v1_r4_holdout_candidate.yaml"
_R3_RELEASE = CONFIG_ROOT / "retail_ops/release/retail_ops_v1_r3_formal_release.yaml"
_R4_RELEASE = CONFIG_ROOT / "retail_ops/release/retail_ops_v1_r4_formal_release.yaml"


def _load(path: Path) -> dict[str, Any]:
    return dict(yaml.safe_load(path.read_text(encoding="utf-8")))


def test_second_observation_uses_fresh_attempt_ids() -> None:
    """不得复用第一次观测的 attempt_id——那会试图覆盖已封存的证据。"""
    assert _load(_R4_BASE)["attempt_id"] == "qwen3-4b-holdout-base-002"
    assert _load(_R4_CAND)["attempt_id"] == "qwen3-4b-holdout-candidate-002"
    assert _load(_R4_BASE)["attempt_id"] != _load(_R3_BASE)["attempt_id"]
    assert _load(_R4_CAND)["attempt_id"] != _load(_R3_CAND)["attempt_id"]


def test_holdout_base_and_candidate_differ_only_by_adapter() -> None:
    """两侧只能差 adapter，delta 才能归因到 adapter 本身。

    base 必须**没有** adapter 字段：`formal_holdout_base` 与
    `formal_holdout_candidate` 是两条独立流水线，让配置文件本身声明意图，
    比"有没有写 adapter 这个 key"更难误配置（沿用 R3 Task 3 A3 的裁定）。
    """
    base, cand = _load(_R4_BASE), _load(_R4_CAND)

    assert "adapter" not in base
    assert cand["adapter"]["run_dir"] == "reports/retail_ops/v1/r4/sft-006"
    assert set(cand) - set(base) == {"adapter"}
    # pipeline 与 attempt_id 必然不同（两条独立流水线、两个新目录）；其余必须逐字段相同。
    for key in base:
        if key in ("pipeline", "attempt_id"):
            continue
        assert base[key] == cand[key], key


def test_holdout_configs_keep_the_frozen_model_pin_and_receipt() -> None:
    """第二次观测必须跑在与第一次**同一份**已哈希校验的基座与同一份冻结 receipt 上，
    否则两次观测之间的任何差异都无法归因。"""
    for r3, r4 in ((_R3_BASE, _R4_BASE), (_R3_CAND, _R4_CAND)):
        old, new = _load(r3), _load(r4)
        assert new["model"] == old["model"]
        assert new["generation"] == old["generation"]
        assert new["dataset_version"] == old["dataset_version"]
        assert new["holdout_receipt_path"] == old["holdout_receipt_path"]


def test_release_config_does_not_touch_the_gates() -> None:
    """发布门禁阈值一个字不改——不因负结果降低门槛。

    R4 的 release 配置必须与 R3 逐字段相同：阈值来自
    domains/retail_ops/v1/release.yaml，两条通道共用同一份 build_release_gates。
    """
    assert _load(_R4_RELEASE) == _load(_R3_RELEASE)


def test_candidate_adapter_is_the_stacked_round3_run() -> None:
    """候选必须是 sft-006（第三轮叠加），不是任何一个第二轮候选。

    选它的依据是 dev 上同 prompt 配对的 +0.100；若指向别的 adapter，
    holdout 结果就与我们记录的选择依据脱钩。
    """
    cand = _load(_R4_CAND)
    round3_dev = _load(
        CONFIG_ROOT / "retail_ops/evaluate/retail_ops_v1_r4_round3_capacity_prompt_candidate.yaml"
    )

    # run_dir 与 file_sha256 **两者都**要和 dev 侧一致。只比哈希会漏掉"声明一个目录、
    # 却 pin 另一个目录的哈希"这种配置——运行时 verify_local_model_files 会拦下它，
    # 但那已经是消耗掉一次 holdout 观测之后的事了。
    assert cand["adapter"]["run_dir"] == round3_dev["adapter"]["run_dir"]
    assert cand["adapter"]["file_sha256"] == round3_dev["adapter"]["file_sha256"]
    for name, digest in cand["adapter"]["file_sha256"].items():
        assert len(digest) == 64, name
