"""把 LoRA adapter 合并回基座权重，产出一个可独立 pin 的模型目录。

**为什么需要这个**（评审 P0-3）：`core/agent/qwen.py` 的部署形态是 bnb 4-bit 基座 +
`PeftModel` **未 merge** + HF `generate` 逐 episode 串行。未合并的 LoRA 每层多两次
低秩矩阵乘并走一遍 4bit 反量化路径，是**纯实现开销，与模型能力无关**。两次封存
holdout 观测的候选都因此背了 1.96–1.99× 的单次前向代价
（见 `docs/GATE_SCHEMA_V11_RECOMPUTE.md`），其中第二次是唯一挡住 120/120 候选的原因。

**这个脚本不声称合并后数值等价。** 合并在 bf16 下进行，评测时再按同一份
`GenerationSettings` 量化回 NF4；"基座 NF4 + LoRA" 与 "合并后再 NF4" 在数值上不同。
因此合并版的任务指标**必须重测**，不能假设保持不变——脚本只负责产出可 pin 的产物，
判定由评测给出。

用法（在有 GPU 或足够内存的机器上，仓库根目录）：

    python scripts/ops/merge_lora_adapter.py \
        --base_dir models/Qwen3-4B-pinned \
        --adapter_dir reports/retail_ops/v1/r4/sft-006/adapter \
        --output_dir models/Qwen3-4B-sft-006-merged \
        --base_repo Qwen/Qwen3-4B \
        --base_revision 8cd0101f70cac4f1efcebc979faf483558e39297

输出目录不可覆盖已存在目录；来源记录写在同级 sidecar `<output_dir>.provenance.json`
（不放进模型目录，否则 `verify_local_model_files` 的「目录内容 = 锁定清单」会失败）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from veritool_rl.core.agent.qwen import (  # noqa: E402
    derive_merged_revision,
    hash_local_model_files,
    verify_local_model_files,
)
from veritool_rl.core.artifacts import canonical_json  # noqa: E402

PROVENANCE_SUFFIX = ".provenance.json"


def build_provenance(
    *,
    base_repo: str,
    base_revision: str,
    base_dir: Path,
    base_file_sha256: dict[str, str],
    adapter_dir: Path,
    adapter_file_sha256: dict[str, str],
    merged_file_sha256: dict[str, str],
    library_versions: dict[str, str],
) -> dict[str, Any]:
    """合并产物的完整来源记录；没有它，合并版模型就是一个来路不明的权重目录。"""
    return {
        "schema_version": "1.0",
        "merged_revision": derive_merged_revision(base_revision, adapter_file_sha256),
        "base": {
            "repo": base_repo,
            "revision": base_revision,
            "local_dir": base_dir.name,
            "file_sha256": base_file_sha256,
        },
        "adapter": {
            "run_dir": str(adapter_dir.parent.relative_to(REPO_ROOT))
            if adapter_dir.is_absolute() and adapter_dir.is_relative_to(REPO_ROOT)
            else str(adapter_dir.parent),
            "file_sha256": adapter_file_sha256,
        },
        "merged": {"local_dir": None, "file_sha256": merged_file_sha256},
        "library_versions": library_versions,
        "numerical_note": (
            "合并在 bf16 下进行，评测时再量化回 NF4。"
            "「基座 NF4 + LoRA」与「合并后再 NF4」数值不等价，合并版的任务指标必须重测。"
        ),
    }


def _listdir(directory: Path) -> list[str]:
    return sorted(entry.name for entry in directory.iterdir() if not entry.name.startswith("."))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base_dir", type=Path, required=True)
    parser.add_argument("--adapter_dir", type=Path, required=True)
    parser.add_argument("--output_dir", type=Path, required=True)
    parser.add_argument("--base_repo", required=True)
    parser.add_argument("--base_revision", required=True)
    args = parser.parse_args(argv)

    if args.output_dir.exists():
        raise SystemExit(f"输出目录已存在，正式产物不可覆盖: {args.output_dir}")

    base_file_sha256 = hash_local_model_files(args.base_dir, _listdir(args.base_dir))
    adapter_file_sha256 = hash_local_model_files(args.adapter_dir, _listdir(args.adapter_dir))
    # 合并前先按刚算出的清单自校一遍：确认这些文件在读取期间没有被换掉。
    verify_local_model_files(args.base_dir, base_file_sha256)
    verify_local_model_files(args.adapter_dir, adapter_file_sha256)
    print(f"基座 {len(base_file_sha256)} 个文件、adapter {len(adapter_file_sha256)} 个文件已哈希")

    import peft
    import torch
    import transformers
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.base_dir, local_files_only=True)
    # **不量化**地加载：在 4-bit 权重上合并会先反量化再合并，等于把量化误差固化进
    # 合并结果。bf16 合并 + 评测时统一量化，才和基座走同一条量化路径。
    model = AutoModelForCausalLM.from_pretrained(
        args.base_dir,
        dtype=torch.bfloat16,
        device_map="cpu",
        low_cpu_mem_usage=True,
        local_files_only=True,
    )
    merged = PeftModel.from_pretrained(model, str(args.adapter_dir), local_files_only=True)
    merged = merged.merge_and_unload()
    merged.eval()

    staging = args.output_dir.with_name(args.output_dir.name + ".staging")
    if staging.exists():
        raise SystemExit(f"staging 目录残留，先人工确认再重试: {staging}")
    staging.mkdir(parents=True)
    merged.save_pretrained(staging, safe_serialization=True)
    tokenizer.save_pretrained(staging)

    merged_file_sha256 = hash_local_model_files(staging, _listdir(staging))
    provenance = build_provenance(
        base_repo=args.base_repo,
        base_revision=args.base_revision,
        base_dir=args.base_dir,
        base_file_sha256=base_file_sha256,
        adapter_dir=args.adapter_dir,
        adapter_file_sha256=adapter_file_sha256,
        merged_file_sha256=merged_file_sha256,
        library_versions={
            "torch": torch.__version__,
            "transformers": transformers.__version__,
            "peft": peft.__version__,
        },
    )
    provenance["merged"]["local_dir"] = args.output_dir.name
    staging.rename(args.output_dir)
    # provenance 写在**模型目录之外**：`verify_local_model_files` 要求目录内容与
    # 锁定清单精确相等，多一个文件就会失败。放 sidecar 让"模型目录里只有模型文件"
    # 保持为一条可校验的事实，而 provenance 自带全部哈希，能自证与目录一致。
    provenance_path = args.output_dir.with_name(args.output_dir.name + ".provenance.json")
    provenance_path.write_text(canonical_json(provenance) + "\n", encoding="utf-8")

    print(f"合并完成: {args.output_dir}")
    print(f"provenance: {provenance_path}")
    print(f"merged_revision = {provenance['merged_revision']}")
    print("---- 供 evaluate config 直接粘贴的 file_sha256 ----")
    print(json.dumps(merged_file_sha256, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
