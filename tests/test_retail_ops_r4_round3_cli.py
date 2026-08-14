"""R4 第三轮实验 1：容量 × 指令框定的叠加。

第二轮把三个变量分别测了一遍，但**没有测过任何叠加**。本实验只叠加其中两个，
且必须能精确说清"相对谁改了哪一个字段"——否则一个四读数的实验矩阵里，
第四个点会变成无法归因的杂交体。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = ROOT / "configs"

_A_SFT = CONFIG_ROOT / "retail_ops/build/retail_ops_v1_r4_round2_a_sft_lora_full.yaml"
_C_SFT = CONFIG_ROOT / "retail_ops/build/retail_ops_v1_r4_round2_c_sft.yaml"
_AC_SFT = CONFIG_ROOT / "retail_ops/build/retail_ops_v1_r4_round3_capacity_prompt_sft.yaml"


def _load(path: Path) -> dict[str, Any]:
    return dict(yaml.safe_load(path.read_text(encoding="utf-8")))


def test_round3_is_exactly_a_plus_c_and_nothing_else() -> None:
    """叠加候选必须相对 A 只差数据、相对 C 只差 LoRA 容量。

    这一条把"这是 A 和 C 的叠加"从一句描述变成可执行断言。任何第三处差异都会让
    四个读数（A / C / base-002 / 本候选）不再构成一个可解释的 2×2，
    而本实验的全部价值就在于那个 2×2 能被解释。
    """
    a, c, ac = _load(_A_SFT), _load(_C_SFT), _load(_AC_SFT)

    assert {key for key in a if a[key] != ac[key]} == {"data"}
    assert {k for k in a["data"] if a["data"][k] != ac["data"][k]} == {"train_relpath"}

    assert {key for key in c if c[key] != ac[key]} == {"lora"}
    assert {k for k in c["lora"] if c["lora"][k] != ac["lora"][k]} == {"target_modules"}


def test_round3_uses_the_new_prompt_export_and_full_linear_lora() -> None:
    """取值本身也要锁死：新 prompt 的导出 + 全 linear LoRA。"""
    config = _load(_AC_SFT)

    assert config["data"]["train_relpath"] == "train-export/train-export-004/sft.jsonl"
    assert config["lora"]["target_modules"] == [
        "q_proj",
        "k_proj",
        "v_proj",
        "o_proj",
        "gate_proj",
        "up_proj",
        "down_proj",
    ]
    # r/alpha/dropout 与前两轮全部候选相同，容量的唯一自由度仍是覆盖范围。
    assert config["lora"]["r"] == 16
    assert config["lora"]["alpha"] == 32


_ROUND1_CANDIDATE = CONFIG_ROOT / "retail_ops/evaluate/retail_ops_v1_r4_qwen3_4b_candidate.yaml"
_AC_CANDIDATE = (
    CONFIG_ROOT / "retail_ops/evaluate/retail_ops_v1_r4_round3_capacity_prompt_candidate.yaml"
)


def test_round3_candidate_differs_from_round1_only_by_adapter() -> None:
    """候选评测两侧只能差 adapter，delta 才能归因到这次的叠加。"""
    round1 = _load(_ROUND1_CANDIDATE)
    candidate = _load(_AC_CANDIDATE)

    assert set(round1) == set(candidate)
    assert {key for key in round1 if round1[key] != candidate[key]} == {"attempt_id", "adapter"}
    assert candidate["attempt_id"] == "qwen3-4b-dev-candidate-006"
    assert candidate["adapter"]["run_dir"] == "reports/retail_ops/v1/r4/sft-006"


def test_round3_candidate_adapter_is_a_fresh_set_of_weights() -> None:
    """权重必须是新的一份：指回 A 或 C 的 adapter 会让叠加读数变成复读。"""
    weights = _load(_AC_CANDIDATE)["adapter"]["file_sha256"]["adapter_model.safetensors"]
    others = {
        _load(path)["adapter"]["file_sha256"]["adapter_model.safetensors"]
        for path in CONFIG_ROOT.glob("retail_ops/evaluate/retail_ops_v1_r4_round2_*_candidate.yaml")
    }
    others.add(_load(_ROUND1_CANDIDATE)["adapter"]["file_sha256"]["adapter_model.safetensors"])

    assert len(weights) == 64
    assert weights not in others
