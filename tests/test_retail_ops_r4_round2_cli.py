"""R4 第二轮：三候选并列消融的配置契约与单变量纪律。

本轮的产品行为变化是导出侧的两项**纯局部变换**——按场景追加终局回复、把 system
消息改写为当前 `runner.SYSTEM_PROMPT`。这里守的是配置层的两件事：配置必须显式声明
每一项变换的意图（不能靠省略键表达"不启用"），以及随仓库提交的候选配置确实只改了
它该改的那一个变量。

「每轮只改一个变量」如果只写在文档里，一次顺手的超参调整就能让整轮 dev delta 失去
归因能力，而产物看起来完全正常。所以每个候选都有一条逐字段比对的断言。
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest
import yaml

from veritool_rl.product_cli import _run_train_export

ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = ROOT / "configs"

_R2_EXPORT_CONFIG = CONFIG_ROOT / "retail_ops/build/retail_ops_v1_r2_train_export.yaml"
_R4_EXPORT_CONFIG = CONFIG_ROOT / "retail_ops/build/retail_ops_v1_r4_train_export_rebalanced.yaml"

# 三候选的共同参照点：R4 第一轮的训练配置（sft-002 / candidate-002，45/60）。
_BASELINE_SFT_CONFIG = CONFIG_ROOT / "retail_ops/build/retail_ops_v1_r4_sft_rebalanced.yaml"

_A_SFT_CONFIG = CONFIG_ROOT / "retail_ops/build/retail_ops_v1_r4_round2_a_sft_lora_full.yaml"
_B_EXPORT_CONFIG = CONFIG_ROOT / "retail_ops/build/retail_ops_v1_r4_round2_b_train_export.yaml"
_B_SFT_CONFIG = CONFIG_ROOT / "retail_ops/build/retail_ops_v1_r4_round2_b_sft.yaml"


def _load(path: Path) -> dict[str, Any]:
    return dict(yaml.safe_load(path.read_text(encoding="utf-8")))


def _args() -> argparse.Namespace:
    return argparse.Namespace(seed=0, input_dir=Path("unused"), output_dir=Path("unused"))


# ---------------------------------------------------------------------------
# 配置契约：两个新键都必填
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["sft_terminal_response", "sft_system_prompt_sha256"])
def test_train_export_config_must_declare_every_transform(key: str) -> None:
    """省略任一变换键必须报契约错误，而不是被当成"不启用"。

    默认值会让"忘了写"和"故意不启用"产出同一份产物，事后无法从配置分辨这轮实验
    是否按预期设置过——这正是第一轮给 `sft_oversample` 定必填的同一条理由。
    """
    config = _load(_R2_EXPORT_CONFIG)
    config.pop(key)

    with pytest.raises(ValueError, match="配置字段不符合命令契约"):
        _run_train_export(_args(), config)


def test_shipped_export_configs_before_round2_declare_both_transforms_off() -> None:
    """R2 与 R4 第一轮的导出是两项变换之前的基线，必须显式声明未启用。"""
    for path in (_R2_EXPORT_CONFIG, _R4_EXPORT_CONFIG):
        config = _load(path)
        assert config["sft_terminal_response"] == [], path.name
        assert config["sft_system_prompt_sha256"] is None, path.name


# ---------------------------------------------------------------------------
# 候选 A：唯一变量是 lora.target_modules
# ---------------------------------------------------------------------------


def test_round2_a_changes_exactly_one_variable() -> None:
    """A 的唯一变量是 LoRA 覆盖的投影层，其余必须与参照点逐字段相同。

    数据不动（复用 train-export-002）、超参不动，dev 上的 delta 才能归因到容量。
    """
    baseline = _load(_BASELINE_SFT_CONFIG)
    candidate = _load(_A_SFT_CONFIG)

    assert set(baseline) == set(candidate)
    for section in ("model", "data", "training"):
        assert candidate[section] == baseline[section], section
    changed = {key for key in baseline["lora"] if baseline["lora"][key] != candidate["lora"][key]}
    assert changed == {"target_modules"}


def test_round2_a_adds_the_mlp_projections() -> None:
    """r/alpha/dropout 不变，只把 LoRA 从 attention 扩到全部 linear layer。

    现行共识是「rank 翻倍但只挂 attention，不如保持 r=16 并加上 MLP 投影」；
    改 r 会同时改变两个量，本轮拿不到干净读数。
    """
    lora = _load(_A_SFT_CONFIG)["lora"]

    assert lora["r"] == 16
    assert lora["alpha"] == 32
    assert lora["target_modules"] == [
        "q_proj",
        "k_proj",
        "v_proj",
        "o_proj",
        "gate_proj",
        "up_proj",
        "down_proj",
    ]


def test_round2_a_reuses_the_round1_export() -> None:
    """A 不产生新数据：读回 train-export-002，与参照点用同一份训练集。"""
    assert (
        _load(_A_SFT_CONFIG)["data"]["train_relpath"]
        == "train-export/train-export-002/sft.jsonl"
    )


# ---------------------------------------------------------------------------
# 候选 B：唯一变量是训练数据（新导出带终局回复）
# ---------------------------------------------------------------------------


def test_round2_b_export_declares_the_terminal_response_scenarios() -> None:
    """B 的导出必须只对两个多步家族启用终局回复，其余设置与第一轮相同。

    重采样因子必须与第一轮一致：B 的变量是"多步路径有没有闭环"，不是样本数。
    """
    config = _load(_B_EXPORT_CONFIG)
    baseline = _load(_R4_EXPORT_CONFIG)

    assert config["pipeline"] == "train_export"
    assert config["sft_terminal_response"] == ["refund_eligible", "refund_recovery"]
    assert config["sft_system_prompt_sha256"] is None
    assert config["sft_oversample"] == baseline["sft_oversample"]
    assert config["dataset_version"] == baseline["dataset_version"]
    assert config["teacher_attempt_id"] == baseline["teacher_attempt_id"]
    # 新导出目录，不覆盖 001（R3 输入）与 002（R4 第一轮输入）。
    assert config["attempt_id"] == "train-export-003"


def test_round2_b_changes_exactly_one_variable() -> None:
    """B 的唯一变量是训练数据：lora 与 training 段必须与参照点逐字段相同。"""
    baseline = _load(_BASELINE_SFT_CONFIG)
    candidate = _load(_B_SFT_CONFIG)

    assert set(baseline) == set(candidate)
    for section in ("model", "lora", "training"):
        assert candidate[section] == baseline[section], section
    changed = {key for key in baseline["data"] if baseline["data"][key] != candidate["data"][key]}
    assert changed == {"train_relpath"}
    assert candidate["data"]["train_relpath"] == "train-export/train-export-003/sft.jsonl"


# ---------------------------------------------------------------------------
# 跨候选：三者必须写到互不覆盖的新输出目录
# ---------------------------------------------------------------------------


def test_round2_candidates_use_distinct_fresh_output_dirs() -> None:
    """每个正式运行用新输出目录，不覆盖 r3/ 与 r4/ 已有产物。

    训练目录由 `_ensure_new_training_output` 在运行时拒绝覆盖，但那是最后一道；
    配置层先把它写清楚，避免两个候选写进同一个目录后才发现。
    """
    train_relpaths = {
        _load(path)["data"]["train_relpath"] for path in (_A_SFT_CONFIG, _B_SFT_CONFIG)
    }
    assert len(train_relpaths) == 2


# ---------------------------------------------------------------------------
# 候选 dev 评测配置：训练之后才写（adapter.file_sha256 是运行产物）
# ---------------------------------------------------------------------------

_ROUND1_CANDIDATE_CONFIG = (
    CONFIG_ROOT / "retail_ops/evaluate/retail_ops_v1_r4_qwen3_4b_candidate.yaml"
)
_EVALUATE_DIR = CONFIG_ROOT / "retail_ops/evaluate"

#: 候选字母 -> (attempt_id, 训练产物目录)。配置本身按训练顺序逐个产出，
#: 因此断言只作用于**已存在**的那些；未登记的候选由下面一条测试抓出来。
_ROUND2_CANDIDATE_SPECS = {
    "a": ("qwen3-4b-dev-candidate-003", "reports/retail_ops/v1/r4/sft-003"),
    "b": ("qwen3-4b-dev-candidate-004", "reports/retail_ops/v1/r4/sft-004"),
    "c": ("qwen3-4b-dev-candidate-005", "reports/retail_ops/v1/r4/sft-005"),
}


def _existing_round2_candidates() -> list[tuple[str, Path]]:
    found = []
    for letter in _ROUND2_CANDIDATE_SPECS:
        path = _EVALUATE_DIR / f"retail_ops_v1_r4_round2_{letter}_candidate.yaml"
        if path.exists():
            found.append((letter, path))
    return found


def test_every_round2_candidate_config_on_disk_is_registered() -> None:
    """磁盘上的每份第二轮候选评测配置都必须在 `_ROUND2_CANDIDATE_SPECS` 里。

    下面的断言只作用于已登记且已存在的配置。没有这一条，新增一份未登记的配置
    就会完全逃过 adapter pin 与单变量检查，且没有任何信号——与治理扫描同一个理由。
    """
    on_disk = {
        path.name.removeprefix("retail_ops_v1_r4_round2_").removesuffix("_candidate.yaml")
        for path in _EVALUATE_DIR.glob("retail_ops_v1_r4_round2_*_candidate.yaml")
    }
    assert on_disk - set(_ROUND2_CANDIDATE_SPECS) == set(), "有未登记的第二轮候选评测配置"


@pytest.mark.parametrize(("letter", "path"), _existing_round2_candidates())
def test_round2_candidate_config_differs_from_round1_only_by_adapter(
    letter: str, path: Path
) -> None:
    """候选评测两侧只能差 adapter，否则 dev delta 会混入与消融无关的变量。

    model / generation / dataset_version / dev_manifest_path 任一不同，delta 就不再
    归因于这一轮改的那个变量；A/B 的 base 侧沿用既有 qwen3-4b-dev-base-001，不重跑。
    """
    attempt_id, run_dir = _ROUND2_CANDIDATE_SPECS[letter]
    round1 = _load(_ROUND1_CANDIDATE_CONFIG)
    candidate = _load(path)

    assert set(round1) == set(candidate)
    assert {key for key in round1 if round1[key] != candidate[key]} == {"attempt_id", "adapter"}
    assert candidate["attempt_id"] == attempt_id
    assert candidate["adapter"]["run_dir"] == run_dir


@pytest.mark.parametrize(("letter", "path"), _existing_round2_candidates())
def test_round2_candidate_config_pins_every_adapter_file(letter: str, path: Path) -> None:
    """adapter 的每个文件都要有 64 位 SHA-256：评测在产物落盘前逐文件核对，
    少 pin 一个文件就等于允许那一个文件被替换。"""
    round1_files = _load(_ROUND1_CANDIDATE_CONFIG)["adapter"]["file_sha256"]
    adapter = _load(path)["adapter"]["file_sha256"]

    assert set(adapter) == set(round1_files)
    for name, digest in adapter.items():
        assert len(digest) == 64, name
        assert all(char in "0123456789abcdef" for char in digest), name


def test_round2_candidate_adapters_are_all_distinct() -> None:
    """已产出的 adapter 权重必须互不相同，也不得指回第一轮。

    指回同一份权重会让两个候选产出完全相同的读数，而配置看起来完全正常——
    这种错误在报告里表现为"两个候选表现一致"，极易被误读成有意义的结论。
    """
    paths = [_ROUND1_CANDIDATE_CONFIG, *(path for _, path in _existing_round2_candidates())]
    weights = {
        path.name: _load(path)["adapter"]["file_sha256"]["adapter_model.safetensors"]
        for path in paths
    }
    assert len(set(weights.values())) == len(weights), weights
