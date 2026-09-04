"""`scripts/ci/audit_public_release.py` 的行为测试。

这份测试的重点是**负例**。一个只在"仓库本来就干净"时通过的审计脚本给的是
虚假的安全感——它必须能在真的有东西泄漏时失败。因此每一项审计都配一个
"种进去一个违规，断言被抓到"的用例，外加一个"合法用法不被误报"的用例，
后者防止审计粗到只能靠豁免清单活着。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "ci" / "audit_public_release.py"


def _load_audit_module() -> ModuleType:
    """按文件路径加载脚本。它刻意不是包的一部分，所以不能直接 import。"""
    spec = importlib.util.spec_from_file_location("audit_public_release", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


audit = _load_audit_module()


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把审计的仓库根指向一个临时目录，用来种违规样本。"""
    monkeypatch.setattr(audit, "REPO_ROOT", tmp_path)
    return tmp_path


def _write(root: Path, relpath: str, content: str) -> Path:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# --- 真实仓库的当前状态 -------------------------------------------------------


def test_the_real_repository_passes_every_audit() -> None:
    assert audit.run_audits() == []


def test_the_audit_actually_scans_a_non_trivial_number_of_files() -> None:
    """防止 `git ls-files` 静默返回空集时审计"通过"。"""
    assert len(audit.tracked_files()) > 100


# --- 负例：种一个违规，必须被抓到 ---------------------------------------------


def test_a_planted_openai_key_is_detected(fake_repo: Path) -> None:
    planted = _write(
        fake_repo,
        "configs/leaky.yaml",
        'api_key: "sk-' + "A" * 32 + '"\n',
    )
    with pytest.raises(audit.AuditFailure, match="疑似凭据"):
        audit.audit_no_credentials([planted])


def test_a_planted_private_key_is_detected(fake_repo: Path) -> None:
    planted = _write(
        fake_repo,
        "deploy/id_rsa",
        "-----BEGIN OPENSSH PRIVATE KEY-----\nbase64\n",
    )
    with pytest.raises(audit.AuditFailure, match="疑似凭据"):
        audit.audit_no_credentials([planted])


def test_a_planted_adapter_weight_is_detected(fake_repo: Path) -> None:
    planted = _write(fake_repo, "models/adapter_model.safetensors", "not really weights")
    with pytest.raises(audit.AuditFailure, match="模型权重"):
        audit.audit_no_weights([planted])


def test_planted_holdout_truth_in_a_data_file_is_detected(fake_repo: Path) -> None:
    planted = _write(
        fake_repo,
        "manifests/holdout.json",
        json.dumps({"tasks": [{"task_id": "t-1", "expected_final_state": {"refunded": True}}]}),
    )
    with pytest.raises(audit.AuditFailure, match="封存 holdout 真值"):
        audit.audit_no_holdout_truth([planted])


def test_planted_real_schema_truth_keys_are_detected(fake_repo: Path) -> None:
    """对抗审查 I-3：真值的**真实字段名**是 TaskSpec 的三个冻结字段。

    修复前审计只认 `expected_final_state` 等四个在 schema 里根本不存在的键名
    ——`git add -f` 一份 holdout.jsonl（行结构是 `task.initial_state` /
    `task.expected_calls`）时六项审计全绿。
    """
    planted = _write(
        fake_repo,
        "manifests/holdout.jsonl",
        json.dumps(
            {
                "task": {
                    "task_id": "t-1",
                    "initial_state": {"orders": {}},
                    "target_state": {"orders": {}},
                    "expected_calls": [{"name": "refund_order", "arguments": {}}],
                }
            }
        )
        + "\n",
    )
    with pytest.raises(audit.AuditFailure, match="封存 holdout 真值"):
        audit.audit_no_holdout_truth([planted])


def test_legacy_trajectories_are_exempt_from_the_truth_scan(fake_repo: Path) -> None:
    """reports/legacy/ 是已公开的 MVP 产物，豁免口径与绝对路径审计一致。"""
    planted = _write(
        fake_repo,
        "reports/legacy/mvp/oracle/trajectories.jsonl",
        json.dumps({"task": {"initial_state": {}, "expected_calls": []}}) + "\n",
    )
    audit.audit_no_holdout_truth([planted])


def test_a_planted_absolute_dev_path_value_is_detected(fake_repo: Path) -> None:
    planted = _write(
        fake_repo,
        "configs/broken.yaml",
        "model:\n  local_dir: /mnt/aidata/tongjiakai/models/Qwen3-4B-pinned\n",
    )
    with pytest.raises(audit.AuditFailure, match="开发机绝对路径"):
        audit.audit_no_absolute_dev_paths([planted])


def test_an_unparseable_tracked_config_is_detected(fake_repo: Path) -> None:
    planted = _write(fake_repo, "configs/broken.yaml", "key: [unclosed\n")
    with pytest.raises(audit.AuditFailure, match="无法解析"):
        audit.audit_no_absolute_dev_paths([planted])


def test_a_missing_license_is_detected(fake_repo: Path) -> None:
    _write(fake_repo, "pyproject.toml", '[project]\nlicense = { text = "MIT" }\n')
    with pytest.raises(audit.AuditFailure, match="缺少 LICENSE"):
        audit.audit_license()


def test_a_license_that_contradicts_pyproject_is_detected(fake_repo: Path) -> None:
    _write(fake_repo, "pyproject.toml", '[project]\nlicense = { text = "Apache-2.0" }\n')
    _write(fake_repo, "LICENSE", "MIT License\n\nCopyright (c) 2026 someone\n")
    with pytest.raises(audit.AuditFailure, match=r"与 pyproject\.toml 声明不一致"):
        audit.audit_license()


def test_a_notice_that_forgets_a_pinned_upstream_is_detected(fake_repo: Path) -> None:
    _write(fake_repo, "NOTICE.md", "# NOTICE\n\n只提到 Qwen3-4B 和 Qwen3-1.7B。\n")
    with pytest.raises(audit.AuditFailure, match="未点名"):
        audit.audit_notice()


# --- 正例：合法用法不得被误报 -------------------------------------------------


def test_a_credential_variable_name_without_a_value_is_not_flagged(fake_repo: Path) -> None:
    """`TEACHER_LLM_API_KEY` 这个**名字**必须能出现在文档和代码里。"""
    clean = _write(
        fake_repo,
        "docs/setup.md",
        "把 `TEACHER_LLM_API_KEY` 导出到环境变量，不要写进仓库。\n",
    )
    audit.audit_no_credentials([clean])


def test_an_absolute_path_in_a_yaml_comment_is_not_flagged(fake_repo: Path) -> None:
    """注释里指出"这份权重复用了哪台机器上的哪个目录"是有用的溯源，不是缺陷。"""
    clean = _write(
        fake_repo,
        "configs/fine.yaml",
        "# 权重复用 /mnt/aidata/tongjiakai/models/Qwen3-4B/ 那一份（已逐文件校验）\n"
        "model:\n  local_dir: Qwen3-4B-pinned\n",
    )
    audit.audit_no_absolute_dev_paths([clean])


def test_source_code_naming_a_truth_field_is_not_flagged(fake_repo: Path) -> None:
    """导出流水线本来就要读写 `reference_trajectory` 字段，源码提到它不是泄漏。"""
    clean = _write(
        fake_repo,
        "src/pipeline.py",
        'REFERENCE_KEY = "reference_trajectory"\n',
    )
    audit.audit_no_holdout_truth([clean])


def test_a_historical_legacy_manifest_keeps_its_provenance_path(fake_repo: Path) -> None:
    """改写历史运行记录里的机器路径等于伪造溯源，所以这一类是豁免而不是"修好"。"""
    clean = _write(
        fake_repo,
        "reports/legacy/bfcl/run-1/manifest.json",
        json.dumps({"model_path": "/data/TJK/models/Qwen3-1.7B"}),
    )
    audit.audit_no_absolute_dev_paths([clean])


# --- 聚合行为 -----------------------------------------------------------------


def test_run_audits_reports_every_failure_not_just_the_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """公开前想知道的是全部问题，不是第一个。"""

    def always_fail(_: object) -> None:
        raise audit.AuditFailure("planted")

    monkeypatch.setattr(
        audit,
        "AUDITS",
        (("一", always_fail), ("二", always_fail), ("三", always_fail)),
    )
    assert len(audit.run_audits()) == 3


def test_the_ci_workflow_runs_the_audit() -> None:
    """审计脚本不进 CI 就只是一份文档。"""
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "scripts/ci/audit_public_release.py" in workflow


def test_the_pattern_allowlist_cannot_grow_silently() -> None:
    """豁免清单是审计最容易被悄悄放大的地方，所以把它钉死。

    只有两个文件**必须**包含凭据形态字面量：定义模式的脚本，和验证"种一个进去
    能被抓到"的这份测试。任何第三个条目都意味着有人在用豁免绕过审计。
    """
    assert audit.PATTERN_FIXTURE_ALLOWLIST == (
        "scripts/ci/audit_public_release.py",
        "tests/test_public_release_audit.py",
    )


def test_the_allowlist_does_not_disable_the_scan_for_those_files(fake_repo: Path) -> None:
    """豁免只针对**凭据形态**与**真值键名**两项，不是让这两个文件免于全部审计。"""
    planted = fake_repo / "scripts" / "ci" / "audit_public_release.py"
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text("model:\n  local_dir: /mnt/aidata/whatever\n", encoding="utf-8")

    # 后缀不是 yaml/json，绝对路径扫描本来就不看它；换一个 yaml 名字验证豁免没有外溢
    other = _write(fake_repo, "scripts/ci/config.yaml", "local_dir: /mnt/aidata/whatever\n")
    with pytest.raises(audit.AuditFailure, match="开发机绝对路径"):
        audit.audit_no_absolute_dev_paths([other])
