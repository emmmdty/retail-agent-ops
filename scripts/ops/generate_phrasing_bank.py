"""用 teacher API 生成用户措辞池，双向校验后按哈希确定性三分。

配套模块：`veritool_rl.retail_ops.build.phrasing_bank`（那里有为什么需要这个池子、
以及为什么分片必须由哈希决定的完整理由）。

## 两道校验，缺一不可

1. **结构校验**（本地，`validate_phrasing`）：必须恰好一个 `{order_id}` 占位符、
   长度在区间内、不得出现工具名。
2. **语义回环校验**（再调一次 API）：把生成出来的措辞**反过来**让模型分类回
   三个**意图**之一（查询进度 / 要求退款 / 要求退款并交代重试）。
   分类结果与生成时的意图不一致就丢弃。

**注意它能挡住什么、挡不住什么。** 它挡的是「要求退款」被写成了「查询进度」
这类意图漂移。它**挡不住**场景级泄漏——因为四个退款场景的请求在语义上本来就
无法区分（区别全在订单状态里），这正是本模块按意图而不是按场景组织的原因。
场景级的正确性由 `validate_phrasing` 的 `LEAKAGE_PATTERN` 负责：
顾客不得说出「已经过期了」「不是我的单」这类状态，说了就丢弃。

## 用法

    set -a; . ./.env; set +a
    .venv/bin/python scripts/ops/generate_phrasing_bank.py \\
        --output_dir data/private/retail_ops/v1/phrasing/phrasing-bank-001 \\
        --per_intent 90

`--dry_run` 只跑每个意图 3 条用于看质量与估算成本，不写文件。
输出目录不可覆盖。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from veritool_rl.retail_ops.build.phrasing_bank import (  # noqa: E402
    INTENT_BRIEFS,
    ORDER_ID_PLACEHOLDER,
    PHRASING_BANK_VERSION,
    PHRASING_STYLES,
    PhrasingRecord,
    assert_intent_coverage,
    assert_partitions_are_disjoint,
    build_records,
    normalize_phrasing,
    partition_records,
    validate_phrasing,
    write_phrasing_bank,
)
from veritool_rl.retail_ops.build.teacher_client import (  # noqa: E402
    TEACHER_MAX_RETRIES,
    TEACHER_REQUEST_TIMEOUT_SECONDS,
)

#: 一次请求生成多少条。太大模型会开始重复自己，太小则请求数上去、成本反而高。
_BATCH = 12

#: 回环分类一次判多少条。
_CLASSIFY_BATCH = 20

_GENERATE_SYSTEM = (
    "你在为一个中文电商客服系统构造测试语料。"
    "你的任务是写出**顾客真实会说的话**，不是写规范的工单描述。"
    "只输出 JSON，不要任何解释。"
)

_CLASSIFY_SYSTEM = (
    "你在给中文电商客服语料做分类。只输出 JSON，不要任何解释。"
    "如果一句话同时符合多个类别或都不符合，选 unclear。"
)


def _generate_prompt(intent: str, styles: Sequence[str], count: int) -> str:
    brief = INTENT_BRIEFS[intent]
    style_list = "、".join(styles)
    return (
        f"情境：{brief}\n\n"
        f"请写出 {count} 句**不同的**顾客原话，覆盖这些风格：{style_list}。\n\n"
        "硬性要求：\n"
        f"1. 每句必须恰好包含一次 `{ORDER_ID_PLACEHOLDER}` 占位符（订单号会在之后填入），"
        "不要自己编订单号；\n"
        "2. 只写顾客说的话，**不要**写客服的回复，不要写系统提示；\n"
        "3. 不要出现任何英文函数名或字段名；\n"
        "4. **绝对不要让顾客说出这单的状态**——不要写「已经过期了」「不是我下的单」"
        "「之前已经退过」这类话。顾客只知道自己想做什么，不知道系统里这单能不能退；"
        "他一旦说破，客服不查订单也能猜到答案，这条语料就废了；\n"
        "5. 长度从几个字到一两句话都要有，不要每句都一样长；\n"
        "6. 允许口语、语气词、错别字、中英夹杂、寒暄和无关闲聊，"
        "这正是我们要的多样性。\n\n"
        '输出格式：{"phrasings": [{"style": "...", "text": "..."}, ...]}'
    )


def _classify_prompt(texts: Sequence[str]) -> str:
    options = "\n".join(f"- {intent}：{brief}" for intent, brief in INTENT_BRIEFS.items())
    numbered = "\n".join(f"{index}. {text}" for index, text in enumerate(texts))
    return (
        "下面每一句都是顾客说的话。请判断每一句属于哪个情境。\n\n"
        f"可选意图：\n{options}\n- unclear：同时符合多个或都不符合\n\n"
        f"待分类：\n{numbered}\n\n"
        '输出格式：{"labels": [{"index": 0, "intent": "..."}, ...]}，'
        "每一句都要有一条，index 与上面一致。"
    )


class _Teacher:
    """薄封装：只做 JSON 模式的文本补全，沿用 teacher client 的超时与重试上限。"""

    def __init__(self) -> None:
        from openai import OpenAI

        provider = os.environ["TEACHER_LLM_PROVIDER"].upper()
        self.model = os.environ[f"TEACHER_LLM_{provider}_MODEL"]
        self.extra: dict[str, Any] = json.loads(
            os.environ.get(f"TEACHER_LLM_{provider}_EXTRA_BODY_JSON", "{}")
        )
        self.client = OpenAI(
            base_url=os.environ[f"TEACHER_LLM_{provider}_BASE_URL"],
            api_key=os.environ[f"TEACHER_LLM_{provider}_API_KEY"],
            timeout=TEACHER_REQUEST_TIMEOUT_SECONDS,
            max_retries=TEACHER_MAX_RETRIES,
        )
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.requests = 0

    def json_call(self, system: str, user: str, *, temperature: float) -> dict[str, Any]:
        self.requests += 1
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            response_format={"type": "json_object"},
            extra_body=self.extra,
        )
        usage = response.usage
        if usage is not None:
            self.prompt_tokens += usage.prompt_tokens or 0
            self.completion_tokens += usage.completion_tokens or 0
        content = response.choices[0].message.content or "{}"
        parsed: dict[str, Any] = json.loads(content)
        return parsed


def _generate_for_intent(teacher: _Teacher, intent: str, wanted: int) -> list[tuple[str, str]]:
    """返回 (style, text)。结构校验不通过的当场丢弃并计数。"""
    produced: list[tuple[str, str]] = []
    seen: set[str] = set()
    rejected = 0
    round_index = 0
    while len(produced) < wanted and round_index < 12:
        styles = [
            PHRASING_STYLES[(round_index * 3 + offset) % len(PHRASING_STYLES)]
            for offset in range(4)
        ]
        payload = teacher.json_call(
            _GENERATE_SYSTEM,
            _generate_prompt(intent, styles, _BATCH),
            # 生成要多样性，所以不是贪心；回环分类那一步才用 0.0。
            temperature=1.0,
        )
        for item in payload.get("phrasings", []):
            if not isinstance(item, dict):
                continue
            text = normalize_phrasing(str(item.get("text", "")))
            style = str(item.get("style", "")) or "unspecified"
            reason = validate_phrasing(text)
            if reason is not None or text in seen:
                rejected += 1
                continue
            seen.add(text)
            produced.append((style, text))
        round_index += 1
        time.sleep(0.2)
    print(
        f"  {intent}: 生成 {len(produced)} 条（结构校验拒绝 {rejected} 条，{round_index} 轮）",
        flush=True,
    )
    return produced[:wanted]


def _roundtrip_filter(
    teacher: _Teacher, intent: str, candidates: Sequence[tuple[str, str]]
) -> list[tuple[str, str]]:
    """让模型把措辞反分类回意图，只留分类一致的。"""
    kept: list[tuple[str, str]] = []
    dropped = 0
    for start in range(0, len(candidates), _CLASSIFY_BATCH):
        chunk = candidates[start : start + _CLASSIFY_BATCH]
        payload = teacher.json_call(
            _CLASSIFY_SYSTEM,
            _classify_prompt([text for _, text in chunk]),
            temperature=0.0,
        )
        labels: dict[int, str] = {}
        for item in payload.get("labels", []):
            if isinstance(item, dict) and isinstance(item.get("index"), int):
                labels[item["index"]] = str(item.get("intent", ""))
        for offset, (style, text) in enumerate(chunk):
            if labels.get(offset) == intent:
                kept.append((style, text))
            else:
                dropped += 1
        time.sleep(0.2)
    print(f"  {intent}: 回环校验保留 {len(kept)} / 丢弃 {dropped}", flush=True)
    return kept


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output_dir", type=Path, required=False)
    parser.add_argument("--per_intent", type=int, default=90)
    parser.add_argument("--min_per_partition_intent", type=int, default=12)
    parser.add_argument("--dry_run", action="store_true")
    args = parser.parse_args()

    if not args.dry_run and args.output_dir is None:
        parser.error("非 --dry_run 必须给 --output_dir")

    teacher = _Teacher()
    wanted = 3 if args.dry_run else args.per_intent

    accepted: list[tuple[str, str, str]] = []
    for intent in INTENT_BRIEFS:
        raw = _generate_for_intent(teacher, intent, wanted)
        kept = raw if args.dry_run else _roundtrip_filter(teacher, intent, raw)
        accepted.extend((intent, style, text) for style, text in kept)

    cost = teacher.prompt_tokens / 1e6 * 0.14 + teacher.completion_tokens / 1e6 * 0.28
    print(
        f"\n请求 {teacher.requests} 次 | prompt {teacher.prompt_tokens} tok | "
        f"completion {teacher.completion_tokens} tok | 折算约 ${cost:.4f}",
        flush=True,
    )

    if args.dry_run:
        print(f"dry-run：接受 {len(accepted)} 条，未写文件。")
        for intent, style, text in accepted:
            print(f"  [{intent}/{style}] {text}")
        return 0

    records: list[PhrasingRecord] = build_records(accepted)
    assert_partitions_are_disjoint(records)
    assert_intent_coverage(records, minimum=args.min_per_partition_intent)

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=False)
    digest = write_phrasing_bank(output_dir / "phrasings.jsonl", records)

    summary = {
        "phrasing_bank_version": PHRASING_BANK_VERSION,
        "bank_sha256": digest,
        "total": len(records),
        "by_partition": {
            partition: len(partition_records(records, partition))
            for partition in ("train_aug", "ood_dev", "ood_sealed")
        },
        "by_intent": {
            intent: sum(1 for record in records if record.intent == intent)
            for intent in INTENT_BRIEFS
        },
        "teacher": {
            "model": teacher.model,
            "requests": teacher.requests,
            "prompt_tokens": teacher.prompt_tokens,
            "completion_tokens": teacher.completion_tokens,
            "estimated_usd": round(cost, 6),
        },
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
