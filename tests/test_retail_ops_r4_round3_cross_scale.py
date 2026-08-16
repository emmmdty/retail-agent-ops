"""R4 第三轮跨规模验证：Qwen3-1.7B 上复现"容量决定训练效果的符号"。

4B 上的结论是：LoRA 只挂 attention 投影时 SFT 对目标类别是净负作用，加上 MLP 三投影后
同一份数据从负作用变正作用。要把它从**单模型观察**升级为**跨规模规律**，1.7B 侧的两次
训练必须与 4B 侧的对应候选严格对齐——否则拿到的差异可能来自数据、超参或 prompt，
而不是模型规模。

这些断言的存在意义就是让"严格对齐"成为机器可检查的事实：四个读数必须构成一个
2（模型规模）× 2（LoRA 覆盖）的对照，任何第三处差异都会让它退化成四个互不可比的点。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = ROOT / "configs"
BUILD = CONFIG_ROOT / "retail_ops/build"
EVAL = CONFIG_ROOT / "retail_ops/evaluate"

#: 4B 侧的两个对应候选（第二轮 C = attention-only、第三轮叠加 = 全 linear）。
_4B_ATTN = BUILD / "retail_ops_v1_r4_round2_c_sft.yaml"
_4B_FULL = BUILD / "retail_ops_v1_r4_round3_capacity_prompt_sft.yaml"
_17B_ATTN = BUILD / "retail_ops_v1_r4_round3_1p7b_attn_sft.yaml"
_17B_FULL = BUILD / "retail_ops_v1_r4_round3_1p7b_full_sft.yaml"

_ATTENTION_ONLY = ["q_proj", "k_proj", "v_proj", "o_proj"]
_ALL_LINEAR = [*_ATTENTION_ONLY, "gate_proj", "up_proj", "down_proj"]


def _load(path: Path) -> dict[str, Any]:
    return dict(yaml.safe_load(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize(("small", "large"), [(_17B_ATTN, _4B_ATTN), (_17B_FULL, _4B_FULL)])
def test_cross_scale_pairs_differ_only_by_model(small: Path, large: Path) -> None:
    """1.7B 与 4B 的对应候选**只能差 model 段**。

    数据、LoRA、超参任一不同，"1.7B 与 4B 表现不同"就无法归因到模型规模——
    那是这次实验唯一想测的东西。
    """
    small_cfg, large_cfg = _load(small), _load(large)

    assert set(small_cfg) == set(large_cfg)
    assert {k for k in large_cfg if large_cfg[k] != small_cfg[k]} == {"model"}
    for section in ("lora", "data", "training"):
        assert small_cfg[section] == large_cfg[section], section


def test_the_only_variable_within_each_scale_is_lora_coverage() -> None:
    """同一模型规模内，两个候选只能差 `lora.target_modules`。"""
    for attn, full in ((_17B_ATTN, _17B_FULL), (_4B_ATTN, _4B_FULL)):
        a, f = _load(attn), _load(full)
        assert {key for key in a if a[key] != f[key]} == {"lora"}
        changed = {k for k in a["lora"] if a["lora"][k] != f["lora"][k]}
        assert changed == {"target_modules"}, (attn.name, full.name)


def test_lora_coverage_values_are_the_intended_two_arms() -> None:
    """两臂的取值必须精确是 attention-only 与全 linear，r/alpha 不变。"""
    for path in (_17B_ATTN, _4B_ATTN):
        lora = _load(path)["lora"]
        assert lora["target_modules"] == _ATTENTION_ONLY, path.name
    for path in (_17B_FULL, _4B_FULL):
        lora = _load(path)["lora"]
        assert lora["target_modules"] == _ALL_LINEAR, path.name
    for path in (_17B_ATTN, _17B_FULL, _4B_ATTN, _4B_FULL):
        lora = _load(path)["lora"]
        assert lora["r"] == 16, path.name
        assert lora["alpha"] == 32, path.name


def test_all_four_arms_train_on_the_same_new_prompt_export() -> None:
    """四臂必须用同一份训练数据（新 prompt 的 train-export-004）。

    混用新旧 prompt 的导出会让跨规模比较同时含 prompt 变量——4B 侧第二轮就是因为
    对照了旧 prompt 的 base 才需要补第三轮实验，这里不重犯。
    """
    for path in (_17B_ATTN, _17B_FULL, _4B_ATTN, _4B_FULL):
        assert _load(path)["data"]["train_relpath"] == "train-export/train-export-004/sft.jsonl", (
            path.name
        )


def test_1p7b_base_rerun_differs_from_the_original_only_by_attempt_id() -> None:
    """1.7B 的配对 base 必须与既有 base 评测除 attempt_id 外逐字段相同。

    重跑的唯一理由是 system prompt 变了；顺手改动模型 pin 或生成参数会让
    "零训练读数"混入别的变量。
    """
    original = _load(EVAL / "retail_ops_v1_r2_qwen3_1_7b_dev.yaml")
    rerun = _load(EVAL / "retail_ops_v1_r4_round3_1p7b_base.yaml")

    assert set(original) == set(rerun)
    assert {key for key in original if original[key] != rerun[key]} == {"attempt_id"}
    assert rerun["attempt_id"] == "qwen3-1.7b-dev-base-002"
    assert "adapter" not in rerun


def test_1p7b_training_configs_pin_the_1p7b_model_not_the_4b() -> None:
    """1.7B 的训练配置必须 pin 1.7B 的权重。

    指错模型是这类批量生成配置最容易犯且最难看出的错误：文件名写着 1p7b，
    model 段却还是 4B 的哈希，训练会照跑，产出一个名字骗人的 adapter。
    """
    expected = _load(EVAL / "retail_ops_v1_r2_qwen3_1_7b_dev.yaml")["model"]
    four_b = _load(_4B_FULL)["model"]

    for path in (_17B_ATTN, _17B_FULL):
        model = _load(path)["model"]
        assert model["name"] == f"models/{expected['local_dir']}", path.name
        assert model["revision"] == expected["revision"], path.name
        assert model["file_sha256"] == expected["file_sha256"], path.name
        assert model["revision"] != four_b["revision"], path.name
        assert model["file_sha256"] != four_b["file_sha256"], path.name
        assert model["load_in_4bit"] is True, path.name


_17B_BASE_EVAL = EVAL / "retail_ops_v1_r4_round3_1p7b_base.yaml"
_17B_ATTN_EVAL = EVAL / "retail_ops_v1_r4_round3_1p7b_attn_candidate.yaml"
_17B_FULL_EVAL = EVAL / "retail_ops_v1_r4_round3_1p7b_full_candidate.yaml"


@pytest.mark.parametrize(
    ("path", "attempt_id", "run_dir"),
    [
        (
            _17B_ATTN_EVAL,
            "qwen3-1.7b-dev-candidate-attn-001",
            "reports/retail_ops/v1/r4/sft-1p7b-attn",
        ),
        (
            _17B_FULL_EVAL,
            "qwen3-1.7b-dev-candidate-full-001",
            "reports/retail_ops/v1/r4/sft-1p7b-full",
        ),
    ],
)
def test_1p7b_candidate_differs_from_its_base_only_by_adapter(
    path: Path, attempt_id: str, run_dir: str
) -> None:
    """1.7B 候选与其配对 base 只能差 pipeline / attempt_id / adapter。

    模型 pin 或生成参数任一不同，"训练相对零训练的符号"就不再可归因——
    而那个符号是这次跨规模验证唯一要读的量。
    """
    base = _load(_17B_BASE_EVAL)
    cand = _load(path)

    assert set(cand) - set(base) == {"adapter"}
    assert cand["pipeline"] == "formal_dev_candidate"
    assert cand["attempt_id"] == attempt_id
    assert cand["adapter"]["run_dir"] == run_dir
    for key in base:
        if key in ("pipeline", "attempt_id"):
            continue
        assert base[key] == cand[key], key


def test_1p7b_candidates_pin_distinct_adapters() -> None:
    """两臂的 adapter 权重必须不同，否则两个读数是同一次训练的复读。"""
    attn = _load(_17B_ATTN_EVAL)["adapter"]["file_sha256"]
    full = _load(_17B_FULL_EVAL)["adapter"]["file_sha256"]

    assert attn["adapter_model.safetensors"] != full["adapter_model.safetensors"]
    for name, digest in {**attn, **full}.items():
        assert len(digest) == 64, name
