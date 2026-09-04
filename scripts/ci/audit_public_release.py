"""公开发布审计：对**被 Git 跟踪的文件**重新验证仓库的对外边界。

`NOTICE.md` 声明了公开这个仓库时不包含什么。声明本身不构成保证——这个脚本
是那个保证。它与 `tests/test_project_governance.py` 的分工是：

* 治理测试逐个配置、逐条契约地检查**已知**的文件；
* 本脚本扫描 `git ls-files` 的**全集**，因此新增一个从未被任何测试覆盖的文件时
  仍然拦得住。

六项审计：

1. `LICENSE` 存在，且与 `pyproject.toml` 声明的 SPDX 标识一致；
2. `NOTICE.md` 存在，且列出了每一个被固定引用的第三方组件；
3. 没有模型权重/checkpoint 类文件被跟踪；
4. 没有凭据类字符串被跟踪；
5. 没有封存 holdout 的任务真值被跟踪；
6. 没有开发机绝对路径被写进代码或配置（文档里引用远端路径是允许的）。

用法（仓库根目录）：

    .venv/bin/python scripts/ci/audit_public_release.py

不接受参数。只读，不修改任何文件。退出码 0 表示可以公开。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 权重与训练 checkpoint 的扩展名。这些文件一律由 `.gitignore` 覆盖；
#: 出现在被跟踪集合里意味着有人 `git add -f` 过。
WEIGHT_SUFFIXES = frozenset(
    {".safetensors", ".bin", ".pt", ".pth", ".ckpt", ".gguf", ".onnx", ".h5", ".msgpack"}
)

#: `.bin` 也被 `training_args.bin` 这类小文件使用，但那同样属于运行产物、
#: 同样不该被跟踪，所以不开例外。唯一的例外是本目录下确实需要跟踪的二进制资源。
WEIGHT_SUFFIX_ALLOWLIST: frozenset[str] = frozenset()

#: 凭据形态。这里刻意只匹配**形态**而不匹配变量名——`TEACHER_LLM_API_KEY` 这个
#: 名字必须能出现在文档和测试里，能出现的是名字，不能出现的是值。
CREDENTIAL_PATTERNS = (
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "OpenAI 形态的 API key"),
    (re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}"), "Anthropic 形态的 API key"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"), "GitHub token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS access key id"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "私钥"),
)

#: 开发机与远端的绝对路径。
#:
#: 扫描的是 YAML/JSON **解析后的取值**，不是文件文本。这个区分是必须的：
#: 配置注释里写"权重复用 /mnt/aidata/… 那一份"是有用的溯源，
#: 测试里用 "/data/TJK/models/…" 当作**应当被拒绝**的输入是正确的负测试，
#: 而把同一个字符串写成 `model.local_dir` 的**值**才会让别人的机器跑不起来。
#: 只有第三种是缺陷，所以只查取值。
ABSOLUTE_PATH_PATTERNS = (
    re.compile(r"/home/tjk\b"),
    re.compile(r"/mnt/aidata\b"),
    re.compile(r"/data/TJK\b"),
    re.compile(r"/home/TJK\b"),
    re.compile(r"/home/tongjiakai\b"),
)

#: 结构化数据文件的后缀。取值扫描只在这些文件上进行。
STRUCTURED_SUFFIXES = frozenset({".yaml", ".yml", ".json", ".jsonl"})

#: `reports/legacy/` 下的 manifest 是**历史运行的溯源记录**：它们如实记下当年那次
#: 运行的模型路径在哪台机器上。改写它们等于伪造运行记录，因此豁免而不是"修好"。
HISTORICAL_ARTIFACT_PREFIXES = ("reports/legacy/",)

#: 封存 holdout 的真值形态。公开的 manifest 只含任务 ID 与哈希；
#: 一旦这些键出现在**结构化数据文件**里，说明答案本身被提交了。
#: 同样只查数据文件——源码里定义或引用同名字段是流水线本来就要做的事。
#: 对抗审查 I-3（2026-09-04）：前四个键名在 TaskSpec schema 里**根本不存在**；
#: 真值的真实字段名是 `initial_state` / `target_state` / `expected_calls`，
#: 缺了它们，`git add -f` 一份 holdout.jsonl 时六项审计全绿。
HOLDOUT_TRUTH_KEYS = (
    "initial_state",
    "target_state",
    "expected_calls",
    "expected_final_state",
    "reference_trajectory",
    "gold_tool_calls",
    "holdout_answer",
)

#: `NOTICE.md` 必须逐个点名的第三方组件。新增一个被固定引用的上游而忘了写进
#: NOTICE 时，这一项会失败。
REQUIRED_NOTICE_MENTIONS = ("Qwen3-4B", "Qwen3-1.7B", "Gorilla", "BFCL", "vLLM", "Apache-2.0")

#: 必须包含凭据形态字面量的两个文件：定义它们的脚本，与验证"种一个进去能被抓到"的
#: 那份测试。**这是唯一的豁免，且被 `test_the_pattern_allowlist_cannot_grow_silently`
#: 钉死为恰好这两项**——豁免清单是审计最容易被悄悄放大的地方。
PATTERN_FIXTURE_ALLOWLIST = (
    "scripts/ci/audit_public_release.py",
    "tests/test_public_release_audit.py",
)


class AuditFailure(Exception):
    """审计不通过。消息里必须包含具体文件与具体原因，不能只说"扫描失败"。"""


def tracked_files() -> list[Path]:
    """被 Git 跟踪的文件全集。审计的是"会被公开的东西"，所以口径是跟踪集而非工作树。"""
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
        timeout=60,
    )
    return [
        REPO_ROOT / name
        for name in completed.stdout.decode("utf-8").split("\0")
        if name and not name.startswith("data/external_repos/")
    ]


def read_text_or_none(path: Path) -> str | None:
    """文本文件返回内容；二进制返回 None（由权重扫描单独负责）。"""
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def audit_license() -> None:
    license_path = REPO_ROOT / "LICENSE"
    if not license_path.is_file():
        raise AuditFailure("缺少 LICENSE：pyproject.toml 声明了许可，但仓库没有许可文件")

    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = pyproject["project"]["license"]
    declared_text = declared["text"] if isinstance(declared, dict) else str(declared)

    body = license_path.read_text(encoding="utf-8")
    if declared_text.upper() not in body.upper():
        raise AuditFailure(
            f"LICENSE 与 pyproject.toml 声明不一致：声明 {declared_text!r}，"
            f"但 LICENSE 正文里找不到这个标识"
        )


def audit_notice() -> None:
    notice_path = REPO_ROOT / "NOTICE.md"
    if not notice_path.is_file():
        raise AuditFailure("缺少 NOTICE.md：无法说明引用了哪些第三方组件、公开时不含什么")

    body = notice_path.read_text(encoding="utf-8")
    missing = [name for name in REQUIRED_NOTICE_MENTIONS if name not in body]
    if missing:
        raise AuditFailure(f"NOTICE.md 未点名以下被固定引用的第三方组件：{missing}")


def audit_no_weights(paths: list[Path]) -> None:
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in paths
        if path.suffix.lower() in WEIGHT_SUFFIXES
        and path.relative_to(REPO_ROOT).as_posix() not in WEIGHT_SUFFIX_ALLOWLIST
    ]
    if offenders:
        raise AuditFailure(f"模型权重/checkpoint 被 Git 跟踪：{offenders}")


def audit_no_credentials(paths: list[Path]) -> None:
    offenders: list[str] = []
    for path in paths:
        relpath = path.relative_to(REPO_ROOT).as_posix()
        if relpath in PATTERN_FIXTURE_ALLOWLIST:
            continue
        text = read_text_or_none(path)
        if text is None:
            continue
        for pattern, label in CREDENTIAL_PATTERNS:
            if pattern.search(text):
                offenders.append(f"{relpath}（{label}）")
    if offenders:
        raise AuditFailure(f"疑似凭据被 Git 跟踪：{offenders}")


def _structured_documents(paths: list[Path]) -> list[tuple[str, object]]:
    """解析全部被跟踪的 YAML/JSON，返回 (相对路径, 已解析对象)。

    解析失败即审计失败——一个进了 Git 却解析不了的配置，本身就是发布前该拦下的问题。
    """
    documents: list[tuple[str, object]] = []
    for path in paths:
        if path.suffix.lower() not in STRUCTURED_SUFFIXES:
            continue
        relpath = path.relative_to(REPO_ROOT).as_posix()
        text = read_text_or_none(path)
        if text is None:
            continue
        try:
            if path.suffix.lower() in {".json", ".jsonl"}:
                documents.append((relpath, _load_json_or_jsonl(text)))
            else:
                documents.append((relpath, yaml.safe_load(text)))
        except (json.JSONDecodeError, yaml.YAMLError) as exc:
            raise AuditFailure(f"{relpath} 被 Git 跟踪但无法解析：{exc}") from None
    return documents


def _load_json_or_jsonl(text: str) -> object:
    """按 JSON 解析；失败则按 JSON Lines 解析。

    上游 BFCL 的 `*_result.json` 实际是 JSON Lines。审计要覆盖它的每一行，
    所以这里不是"解析不了就跳过"，而是换一种正确的解析方式。
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]


def _walk(node: object) -> Iterator[tuple[str | None, object]]:
    """深度遍历解析后的结构，产出 (键名, 取值)。顶层与列表元素的键名为 None。"""
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key), value
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def audit_no_holdout_truth(paths: list[Path]) -> None:
    offenders: list[str] = []
    for relpath, document in _structured_documents(paths):
        if relpath in PATTERN_FIXTURE_ALLOWLIST:
            continue
        if relpath.startswith(HISTORICAL_ARTIFACT_PREFIXES):
            # reports/legacy/ 是已公开的 MVP 产物（含任务真值），
            # 豁免口径与 audit_no_absolute_dev_paths 一致。
            continue
        hits = sorted({key for key, _ in _walk(document) if key in HOLDOUT_TRUTH_KEYS})
        if hits:
            offenders.append(f"{relpath}（{hits}）")
    if offenders:
        raise AuditFailure(f"封存 holdout 真值字段出现在被跟踪的数据文件里：{offenders}")


def audit_no_absolute_dev_paths(paths: list[Path]) -> None:
    offenders: list[str] = []
    for relpath, document in _structured_documents(paths):
        if relpath.startswith(HISTORICAL_ARTIFACT_PREFIXES):
            continue
        for _, value in _walk(document):
            if not isinstance(value, str):
                continue
            for pattern in ABSOLUTE_PATH_PATTERNS:
                match = pattern.search(value)
                if match:
                    offenders.append(f"{relpath}（取值含 {match.group(0)}）")
                    break
            else:
                continue
            break
    if offenders:
        raise AuditFailure(
            f"开发机绝对路径出现在配置取值里，会让仓库在别人的机器上跑不起来：{offenders}"
        )


AUDITS = (
    ("LICENSE 与 pyproject 声明一致", lambda paths: audit_license()),
    ("NOTICE.md 点名全部第三方组件", lambda paths: audit_notice()),
    ("无模型权重被跟踪", audit_no_weights),
    ("无凭据被跟踪", audit_no_credentials),
    ("无封存 holdout 真值被跟踪", audit_no_holdout_truth),
    ("无开发机绝对路径进代码/配置", audit_no_absolute_dev_paths),
)


def run_audits() -> list[str]:
    """跑完全部审计，返回失败原因列表（空列表表示通过）。

    刻意**不**在第一项失败时短路：公开前想知道的是全部问题，不是第一个。
    """
    paths = tracked_files()
    failures: list[str] = []
    for label, audit in AUDITS:
        try:
            audit(paths)
        except AuditFailure as exc:
            failures.append(f"{label}: {exc}")
    return failures


def main() -> int:
    failures = run_audits()
    if failures:
        print("公开发布审计不通过：", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print(f"公开发布审计通过（{len(AUDITS)} 项，扫描 {len(tracked_files())} 个被跟踪文件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
