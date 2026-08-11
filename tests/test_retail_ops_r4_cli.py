"""R4 Task 1: train_export 的重复采样配置契约与随仓库提交的 R4 配置。

本轮唯一的产品行为变化是"按场景重复 sft 行"。这里守的是**配置层**的两件事：
配置必须显式声明重采样意图（不能靠省略键来表达"不重采样"），以及随仓库提交的
R4 配置确实声明了实验预期的因子——否则一次 GPU 训练会跑在一份没生效的数据上，
而产物看起来完全正常。
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
_R3_SFT_CONFIG = CONFIG_ROOT / "retail_ops/build/retail_ops_v1_r3_sft.yaml"
_R4_EXPORT_CONFIG = CONFIG_ROOT / "retail_ops/build/retail_ops_v1_r4_train_export_rebalanced.yaml"
_R4_SFT_CONFIG = CONFIG_ROOT / "retail_ops/build/retail_ops_v1_r4_sft_rebalanced.yaml"
_R3_CANDIDATE_CONFIG = CONFIG_ROOT / "retail_ops/evaluate/retail_ops_v1_r3_qwen3_4b_candidate.yaml"
_R4_CANDIDATE_CONFIG = CONFIG_ROOT / "retail_ops/evaluate/retail_ops_v1_r4_qwen3_4b_candidate.yaml"


def _load(path: Path) -> dict[str, Any]:
    return dict(yaml.safe_load(path.read_text(encoding="utf-8")))


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        seed=0,
        input_dir=Path("unused"),
        output_dir=Path("unused"),
    )


def test_train_export_config_must_declare_sft_oversample() -> None:
    """省略 `sft_oversample` 必须报契约错误，而不是被当成"不重采样"。

    默认值会让"忘了写"和"故意不重采样"产生同一份产物，事后无法从配置分辨
    实验是否按预期设置过。
    """
    config = _load(_R2_EXPORT_CONFIG)
    config.pop("sft_oversample")

    with pytest.raises(ValueError, match="配置字段不符合命令契约"):
        _run_train_export(_args(), config)


def test_shipped_r2_export_config_declares_no_oversample() -> None:
    """R2 的既有导出是重采样前的基线，必须显式声明空 mapping。"""
    assert _load(_R2_EXPORT_CONFIG)["sft_oversample"] == {}


def test_shipped_r4_export_config_declares_intended_factors() -> None:
    """R4 第一轮的实验设置：两个多步家族各 ×3，其余不动。"""
    config = _load(_R4_EXPORT_CONFIG)

    assert config["pipeline"] == "train_export"
    assert config["sft_oversample"] == {"refund_eligible": 3, "refund_recovery": 3}
    # 冻结数据集与 teacher 采集完全复用 R2，本轮不新增任务、不新采 teacher。
    assert config["dataset_version"] == "retail_ops_v1_r2_20260722"
    assert config["teacher_attempt_id"] == "teacher-full-001"
    # 新导出目录，不覆盖 R3 训练用的 train-export-001。
    assert config["attempt_id"] == "train-export-002"


def test_r4_sft_config_reads_the_rebalanced_export() -> None:
    """训练必须读新导出；读回 001 会让整轮实验静默退化成 R3 的重跑。"""
    config = _load(_R4_SFT_CONFIG)

    assert config["pipeline"] == "sft"
    assert config["data"]["train_relpath"] == "train-export/train-export-002/sft.jsonl"
    # eval 数据不变：它不参与梯度，换掉只会让本轮与 R3 的 loss 曲线不可比。
    assert config["data"]["eval_relpath"] == _load(_R3_SFT_CONFIG)["data"]["eval_relpath"]


def test_r4_sft_config_changes_exactly_one_variable() -> None:
    """R4 第一轮的纪律是"每轮只改一个主要变量"。

    这条测试把那句话变成可执行断言：R4 训练配置除 `data.train_relpath` 外，
    model / lora / training 三段必须与 R3 逐字段相同。否则 dev 上的 delta 就无法
    归因到数据重平衡——它可能来自任何一个顺手调了的超参。
    """
    r3 = _load(_R3_SFT_CONFIG)
    r4 = _load(_R4_SFT_CONFIG)

    assert set(r3) == set(r4)
    for section in ("model", "lora", "training"):
        assert r4[section] == r3[section], section
    changed = {key for key in r3["data"] if r3["data"][key] != r4["data"][key]}
    assert changed == {"train_relpath"}


def test_r4_candidate_config_differs_from_r3_only_by_adapter() -> None:
    """dev 配对要能把 delta 归因到"训练数据换了"，候选评测两侧就必须只差 adapter。

    model / generation / dataset_version / dev_manifest_path 任一不同，delta 都会混入
    与本轮实验无关的变量；而 base 侧沿用既有 qwen3-4b-dev-base-001，不重跑。
    """
    r3 = _load(_R3_CANDIDATE_CONFIG)
    r4 = _load(_R4_CANDIDATE_CONFIG)

    assert set(r3) == set(r4)
    assert {key for key in r3 if r3[key] != r4[key]} == {"attempt_id", "adapter"}
    assert r4["attempt_id"] == "qwen3-4b-dev-candidate-002"
    assert r4["adapter"]["run_dir"] == "reports/retail_ops/v1/r4/sft-002"


def test_r4_candidate_config_pins_every_adapter_file() -> None:
    """adapter 的每个文件都必须有 64 位 SHA-256：评测在产物落盘前逐文件核对，
    少 pin 一个文件就等于允许那一个文件被替换。"""
    adapter = _load(_R4_CANDIDATE_CONFIG)["adapter"]["file_sha256"]

    assert set(adapter) == set(_load(_R3_CANDIDATE_CONFIG)["adapter"]["file_sha256"])
    for name, digest in adapter.items():
        assert len(digest) == 64, name
        assert all(char in "0123456789abcdef" for char in digest), name
    # 权重必须确实是新的一份，不能指回 R3 的 adapter。
    r3_weights = _load(_R3_CANDIDATE_CONFIG)["adapter"]["file_sha256"]["adapter_model.safetensors"]
    assert adapter["adapter_model.safetensors"] != r3_weights
