"""DPO 训练管线（r11 主线 A-4）配置与机器守卫测试，不在本地加载模型。

预注册契约（task_plan `eeec309`，用户 2026-09-06 逐项确认）：
- 起始权重 = `models/Qwen3-4B-sft-008-merged`（合并部署形态 = 初始策略）；
- ref model = 初始策略冻结副本，由 TRL peft 模式自动处理（不显式传 ref_model）；
- beta 0.1、lr 5e-7、epochs 1、per_device_batch 2 + grad_accum 4、max_length 2048；
- 训练前按实际渲染长度实测留余量（LOG-20260905-02）；
- 训练后自动断言 loss 曲线非零、末端下降（同一教训的机器守卫）。
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _model_pin() -> dict[str, Any]:
    return {
        "name": "models/Qwen3-4B-sft-008-merged",
        "revision": "a" * 64,
        "file_sha256": {"model.safetensors": "b" * 64},
    }


def _config(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    train_relpath = Path("pairs.jsonl")
    if not train_relpath.exists():
        train_relpath.write_text("{}\n", encoding="utf-8")
    config: dict[str, Any] = {
        "model": _model_pin(),
        "lora": {
            "r": 16,
            "alpha": 32,
            "dropout": 0.05,
            "target_modules": [
                "q_proj",
                "k_proj",
                "v_proj",
                "o_proj",
                "gate_proj",
                "up_proj",
                "down_proj",
            ],
        },
        "data": {"train_path": str(train_relpath)},
        "training": {},
    }
    for key, value in overrides.items():
        if key == "train_path":
            config["data"]["train_path"] = str(value)
        else:
            config["training"][key] = value
    return config


def test_resolve_dpo_config_locks_the_preregistered_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from veritool_rl.training.dpo import resolve_dpo_config

    monkeypatch.chdir(tmp_path)
    resolved = resolve_dpo_config(_config(tmp_path), seed=0, output_dir=tmp_path / "run")

    assert resolved.model.name == "models/Qwen3-4B-sft-008-merged"
    assert resolved.model.load_in_4bit is True
    assert resolved.training.beta == 0.1
    assert resolved.training.lr == 5e-7
    assert resolved.training.epochs == 1
    assert resolved.training.batch_size == 2
    assert resolved.training.grad_accum == 4
    assert resolved.training.max_length == 2048
    assert resolved.seed == 0
    assert resolved.adapter_dir == tmp_path / "run/adapter"


def test_resolve_dpo_config_rejects_missing_pairs_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from veritool_rl.training.dpo import resolve_dpo_config

    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError, match="missing-pairs"):
        resolve_dpo_config(
            _config(tmp_path, train_path="missing-pairs.jsonl"),
            seed=0,
            output_dir=tmp_path / "run",
        )


def test_resolve_dpo_config_rejects_bf16_base_and_non_project_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic import ValidationError

    from veritool_rl.training.dpo import resolve_dpo_config

    monkeypatch.chdir(tmp_path)
    config = _config(tmp_path)
    config["model"]["load_in_4bit"] = False
    with pytest.raises(ValueError, match="NF4"):
        resolve_dpo_config(config, seed=0, output_dir=tmp_path / "run")

    config = _config(tmp_path)
    config["model"]["name"] = "/data/TJK/models/Qwen3-4B-sft-008-merged"
    with pytest.raises(ValidationError, match="项目相对路径"):
        resolve_dpo_config(config, seed=0, output_dir=tmp_path / "run")


def test_validate_dpo_pairs_requires_unique_and_contrastive_rows() -> None:
    from veritool_rl.training.dpo import validate_dpo_pairs

    base_row: dict[str, Any] = {
        "pair_id": "a" * 64,
        "task_id": "task-1",
        "sample_index": 0,
        "source": "policy_boundary_probe",
        "prompt": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        "chosen": [{"role": "assistant", "content": "", "tool_calls": []}],
        "rejected": [{"role": "assistant", "content": "执行了退款"}],
        "tools": [{"type": "function", "function": {"name": "get_order"}}],
    }
    validate_dpo_pairs([dict(base_row)])

    duplicate = dict(base_row, pair_id="a" * 64)
    second = dict(base_row, task_id="task-2")
    with pytest.raises(ValueError, match="pair_id"):
        validate_dpo_pairs([duplicate, second])

    same = dict(base_row, pair_id="c" * 64, rejected=base_row["chosen"])
    with pytest.raises(ValueError, match="相同"):
        validate_dpo_pairs([same])

    empty_prompt = dict(base_row, pair_id="d" * 64, prompt=[{"role": "user", "content": "u"}])
    with pytest.raises(ValueError, match="system"):
        validate_dpo_pairs([empty_prompt])


def test_render_dpo_pairs_strips_the_prompt_prefix_and_enforces_max_length() -> None:
    from veritool_rl.training.dpo import render_dpo_pairs

    class StubTokenizer:
        """模板渲染 = 前缀拼接 + assistant 头；长度 = 字符数（stub 只服务结构测试）。

        真实 Qwen 模板里 `add_generation_prompt` 追加的 assistant 头与完整渲染里
        assistant 消息自身的头逐字节相同——stub 用 `A(` 头复刻这一结构，这正是
        前缀剥离得以成立的前提。
        """

        def apply_chat_template(
            self, messages: list[dict[str, Any]], tools: Any = None, **kwargs: Any
        ) -> str:
            del tools
            parts = []
            for message in messages:
                if message.get("role") == "assistant":
                    calls = message.get("tool_calls") or []
                    body = "|".join(f"[call:{call['function']['name']}]" for call in calls) or str(
                        message.get("content", "")
                    )
                    parts.append(f"A({body})")
                else:
                    parts.append(str(message.get("content", "")))
            text = "|".join(parts)
            if kwargs.get("add_generation_prompt"):
                text += "|A("
            return text

        def __call__(self, text: str, **kwargs: Any) -> dict[str, Any]:
            del kwargs
            return {"input_ids": list(range(len(text)))}

    row: dict[str, Any] = {
        "pair_id": "a" * 64,
        "task_id": "task-1",
        "sample_index": 0,
        "prompt": [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "USER"},
        ],
        "chosen": [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": "get_order"}}],
            }
        ],
        "rejected": [{"role": "assistant", "content": "BAD"}],
        "tools": [],
    }

    rendered = render_dpo_pairs([dict(row)], StubTokenizer(), max_length=10_000)

    assert rendered[0]["prompt"].startswith("SYS|USER|A(")
    assert rendered[0]["prompt"] + rendered[0]["chosen"] == StubTokenizer().apply_chat_template(
        row["prompt"] + row["chosen"]
    )
    assert rendered[0]["rejected"] == "BAD)"
    assert "token_lengths" in rendered[0]

    with pytest.raises(ValueError, match="max_length"):
        render_dpo_pairs([dict(row)], StubTokenizer(), max_length=4)


def test_render_dpo_pairs_fails_loudly_on_template_prefix_mismatch() -> None:
    from veritool_rl.training.dpo import render_dpo_pairs

    class LyingTokenizer:
        """渲染出的完整序列不带 prompt 前缀——必须显式失败而不是错位截断。"""

        def apply_chat_template(
            self, messages: list[dict[str, Any]], tools: Any = None, **kwargs: Any
        ) -> str:
            del tools, kwargs
            return "MISMATCH" if len(messages) > 2 else "P"

        def __call__(self, text: str, **kwargs: Any) -> dict[str, Any]:
            del kwargs
            return {"input_ids": list(range(len(text)))}

    row: dict[str, Any] = {
        "pair_id": "a" * 64,
        "task_id": "task-1",
        "sample_index": 0,
        "prompt": [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
        ],
        "chosen": [{"role": "assistant", "content": "c"}],
        "rejected": [{"role": "assistant", "content": "r"}],
        "tools": [],
    }

    with pytest.raises(ValueError, match="前缀"):
        render_dpo_pairs([row], LyingTokenizer(), max_length=10_000)


def test_loss_guard_requires_nonzero_and_declining_curve() -> None:
    from veritool_rl.training.dpo import require_nonzero_declining_losses

    require_nonzero_declining_losses([0.6931, 0.5, 0.4, 0.35])

    with pytest.raises(RuntimeError, match="全零"):
        require_nonzero_declining_losses([0.0, 0.0, 0.0])
    with pytest.raises(RuntimeError, match="有限"):
        require_nonzero_declining_losses([float("nan"), 0.5])
    with pytest.raises(RuntimeError, match="下降"):
        require_nonzero_declining_losses([0.3, 0.5, 0.7])
    with pytest.raises(RuntimeError, match="正数"):
        require_nonzero_declining_losses([0.7, 0.5, 0.0])

    # smoke（≤4 对自检）没有趋势可言：只要求有限非零，不要求下降
    require_nonzero_declining_losses([0.7, 0.69], smoke=True)
    with pytest.raises(RuntimeError, match="全零"):
        require_nonzero_declining_losses([0.0, 0.0], smoke=True)


def test_run_dpo_source_locks_the_ref_model_and_determinism_contract() -> None:
    """ref model 不得显式传入（TRL peft 模式自动处理 = 禁用 adapter 的基座 =
    初始策略冻结副本）；确定性配置与 max_length 必须在场。"""
    from veritool_rl.training import dpo

    source = inspect.getsource(dpo.run_dpo)
    assert "peft_config=lora_config" in source
    assert "ref_model" not in source
    assert "configure_training_determinism" in source
    assert "max_length" in source
    assert "require_nonzero_declining_losses" in source


# ---------------------------------------------------------------------------
# CLI 接线（_run_dpo）
# ---------------------------------------------------------------------------


def _dpo_cli_config() -> dict[str, Any]:
    return {
        "pipeline": "dpo",
        "model": _model_pin(),
        "lora": {
            "r": 16,
            "alpha": 32,
            "dropout": 0.05,
            "target_modules": ["q_proj", "k_proj", "v_proj", "o_proj"],
        },
        "data": {"train_relpath": "reports/retail_ops/v1/r11-dpo/sampling-001/pairs.jsonl"},
        "training": {"beta": 0.1, "lr": 5e-7, "max_length": 2048},
    }


def _cli_args(seed: int = 0) -> Any:
    from argparse import Namespace

    return Namespace(seed=seed, output_dir=Path("out"), input_dir=None, config=None)


def test_cli_dpo_passes_project_relative_pairs_path_to_trainer(tmp_path: Path) -> None:
    from veritool_rl.product_cli import _run_dpo

    calls: list[tuple[dict[str, Any], int, Path]] = []

    def trainer(config: dict[str, Any], seed: int, output_dir: Path) -> dict[str, Any]:
        calls.append((config, seed, output_dir))
        return {}

    _run_dpo(_cli_args(seed=3), _dpo_cli_config(), trainer_factory=trainer)

    config, seed, output_dir = calls[0]
    assert seed == 3
    assert output_dir == Path("out")
    assert "pipeline" not in config
    assert config["data"]["train_path"] == (
        "reports/retail_ops/v1/r11-dpo/sampling-001/pairs.jsonl"
    )
    assert config["model"]["name"] == "models/Qwen3-4B-sft-008-merged"


def test_cli_dpo_rejects_absolute_and_escaping_train_paths() -> None:
    from veritool_rl.product_cli import _run_dpo

    config = _dpo_cli_config()
    config["data"]["train_relpath"] = "/data/TJK/pairs.jsonl"
    with pytest.raises(ValueError, match="路径分量"):
        _run_dpo(_cli_args(), config, trainer_factory=lambda *a: {})

    config = _dpo_cli_config()
    config["data"]["train_relpath"] = "../escape/pairs.jsonl"
    with pytest.raises(ValueError, match="路径分量"):
        _run_dpo(_cli_args(), config, trainer_factory=lambda *a: {})


def test_cli_dpo_config_is_accepted_by_the_real_resolver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI 组装出的 config 必须能被真实 `resolve_dpo_config` 接受，形状不能漂移。"""
    from veritool_rl.product_cli import _run_dpo
    from veritool_rl.training.dpo import resolve_dpo_config

    monkeypatch.chdir(tmp_path)
    pairs_path = tmp_path / "reports/retail_ops/v1/r11-dpo/sampling-001/pairs.jsonl"
    pairs_path.parent.mkdir(parents=True)
    pairs_path.write_text("{}\n", encoding="utf-8")

    calls: list[tuple[dict[str, Any], int, Path]] = []

    def trainer(config: dict[str, Any], seed: int, output_dir: Path) -> dict[str, Any]:
        calls.append((config, seed, output_dir))
        return {}

    _run_dpo(_cli_args(), _dpo_cli_config(), trainer_factory=trainer)
    config, seed, output_dir = calls[0]

    resolved = resolve_dpo_config(config, seed, output_dir)

    assert resolved.model.name == "models/Qwen3-4B-sft-008-merged"
    assert resolved.adapter_dir == output_dir / "adapter"
    assert resolved.training.max_length == 2048


def test_the_committed_dpo_config_matches_the_preregistration() -> None:
    """已提交的 dpo 训练配置与预注册超参逐字段一致。"""
    import yaml

    raw = yaml.safe_load(
        (REPO_ROOT / "configs/retail_ops/build/retail_ops_dpo.yaml").read_text(encoding="utf-8")
    )

    assert raw["pipeline"] == "dpo"
    assert raw["model"]["name"] == "models/Qwen3-4B-sft-008-merged"
    assert raw["model"]["file_sha256"]["model.safetensors"].startswith("70981220")
    assert raw["data"]["train_relpath"] == (
        "reports/retail_ops/v1/r11-dpo/sampling-001/pairs.jsonl"
    )
    training = raw["training"]
    assert training["beta"] == 0.1
    assert training["lr"] == 5e-7
    assert training["epochs"] == 1
    assert training["batch_size"] == 2
    assert training["grad_accum"] == 4
    assert training["max_length"] == 2048
