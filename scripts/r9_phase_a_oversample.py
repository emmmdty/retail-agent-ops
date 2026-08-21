#!/usr/bin/env python3
"""R9 Phase A: Oversample 240→2000 条训练数据。

对每条原始样本生成 7-8 个变体：
- 替换 order_id（随机生成新的 16 位 hex）
- 替换 reason（从 damaged/wrong_item/not_as_described/changed_mind 中轮换）
- 替换 margin（从 _MARGINS=(1,2,3,5,7,10,14) 中轮换）
- 替换 customer_id（从 CUST001-CUST010 中轮换）
- 保持 user_request 模板不变（仍是那 12 句），只替换其中的实体
- 去重：同一模板+同一实体组合只保留一条
- 目标 2,000 条，实际可能 1,800-2,200 条（去重后）
- 按 sha256 切分 train/dev/holdout = 80/10/10
"""

import hashlib
import json
import random
import re
from pathlib import Path
from typing import Any

# 常量
_MARGINS = (1, 2, 3, 5, 7, 10, 14)
_REASONS = ("damaged", "wrong_item", "not_as_described", "changed_mind")
_CUSTOMER_IDS = [f"CUST{i:03d}" for i in range(1, 11)]
_TARGET_TOTAL = 2000
_SEED = 42


def generate_order_id() -> str:
    """生成随机 16 位 hex 订单号。"""
    return "O-" + "".join(random.choices("0123456789ABCDEF", k=16))


def get_user_request_template(user_request: str) -> str:
    """从 user_request 中提取模板（替换 order_id 和 reason 为占位符）。"""
    template = re.sub(r"O-[A-F0-9]+", "O-PLACEHOLDER", user_request)
    for reason in _REASONS:
        template = template.replace(reason, "REASON_PLACEHOLDER")
    return template


def apply_variant(
    task: dict[str, Any],
    order_id: str,
    reason: str,
    margin: int,
    customer_id: str,
    template: str,
) -> dict[str, Any]:
    """应用变体到任务上。"""
    # 深拷贝任务
    import copy

    new_task = copy.deepcopy(task)

    # 替换 user_request 中的实体
    new_ur = template.replace("O-PLACEHOLDER", order_id)
    new_ur = new_ur.replace("REASON_PLACEHOLDER", reason)
    new_task["user_request"] = new_ur

    # 替换 order_id
    new_task["task_id"] = hashlib.sha256(
        f"{order_id}:{reason}:{margin}:{customer_id}:{template}".encode()
    ).hexdigest()

    # 替换 initial_state 中的订单
    if "initial_state" in new_task:
        new_state = copy.deepcopy(new_task["initial_state"])
        if "orders" in new_state:
            new_orders = {}
            for old_oid, order_data in new_state["orders"].items():
                expected_oid = (
                    task.get("expected_calls", [{}])[0].get("args", {}).get("order_id", old_oid)
                )
                new_oid = order_id if old_oid == expected_oid else old_oid
                new_order = copy.deepcopy(order_data)
                new_order["customer_id"] = customer_id
                # 调整 refund_deadline 以匹配 margin
                new_order["refund_deadline"] = 20 + margin  # current_day=20
                new_orders[new_oid] = new_order
            new_state["orders"] = new_orders
        new_task["initial_state"] = new_state

    # 替换 target_state 中的订单
    if "target_state" in new_task:
        new_target = copy.deepcopy(new_task["target_state"])
        if "orders" in new_target:
            new_orders = {}
            for old_oid, order_data in new_target["orders"].items():
                expected_oid = (
                    task.get("expected_calls", [{}])[0].get("args", {}).get("order_id", old_oid)
                )
                new_oid = order_id if old_oid == expected_oid else old_oid
                new_order = copy.deepcopy(order_data)
                new_order["customer_id"] = customer_id
                new_orders[new_oid] = new_order
            new_target["orders"] = new_orders
        new_task["target_state"] = new_target

    # 替换 expected_calls 中的 order_id
    if "expected_calls" in new_task:
        new_calls = []
        for call in new_task["expected_calls"]:
            new_call = copy.deepcopy(call)
            # expected_calls 中的键可能是 'args' 或 'arguments'
            call_args = new_call.get("args") or new_call.get("arguments", {})
            if "order_id" in call_args:
                call_args["order_id"] = order_id
            new_calls.append(new_call)
        new_task["expected_calls"] = new_calls

    return new_task


def apply_variant_to_trajectory(
    trajectory: dict[str, Any],
    old_order_id: str,
    new_order_id: str,
    new_reason: str,
) -> dict[str, Any]:
    """更新 trajectory steps 中的 tool_call arguments。"""
    import copy
    new_traj = copy.deepcopy(trajectory)

    if "steps" not in new_traj:
        return new_traj

    for step in new_traj["steps"]:
        if "tool_call" in step and step["tool_call"] is not None:
            tc = step["tool_call"]
            if "arguments" in tc:
                # 更新 order_id
                if "order_id" in tc["arguments"] and tc["arguments"]["order_id"] == old_order_id:
                    tc["arguments"]["order_id"] = new_order_id
                # 更新 reason（如果存在）
                if "reason" in tc["arguments"] and tc["arguments"]["reason"] in _REASONS:
                    tc["arguments"]["reason"] = new_reason

    return new_traj


def main():
    random.seed(_SEED)

    # 读取原始训练数据
    input_path = Path(
        "data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722"
        "/train-export/train-export-004/train.jsonl"
    )
    output_dir = Path("data/private/retail_ops/v1/r9/phase-a")
    output_dir.mkdir(parents=True, exist_ok=True)

    original_samples = []
    with open(input_path) as f:
        for line in f:
            original_samples.append(json.loads(line))

    print(f"Original samples: {len(original_samples)}")

    # 计算每个样本需要生成的变体数
    variants_per_sample = _TARGET_TOTAL // len(original_samples)
    remainder = _TARGET_TOTAL % len(original_samples)
    print(f"Variants per sample: {variants_per_sample} (+ {remainder} extra)")

    # 生成变体
    all_samples = []
    seen_combinations = set()

    for i, sample in enumerate(original_samples):
        task = sample["trajectory"]["task"]
        template = get_user_request_template(task["user_request"])

        # 获取原始 order_id（用于更新 trajectory steps）
        old_order_id = None
        if "expected_calls" in task and task["expected_calls"]:
            first_call = task["expected_calls"][0]
            # expected_calls 中的键可能是 'args' 或 'arguments'
            call_args = first_call.get("args") or first_call.get("arguments", {})
            if "order_id" in call_args:
                old_order_id = call_args["order_id"]
        if old_order_id is None and "initial_state" in task and "orders" in task["initial_state"]:
            old_order_id = next(iter(task["initial_state"]["orders"]), None)

        # 确定这个样本需要生成多少变体
        n_variants = variants_per_sample + (1 if i < remainder else 0)

        for _v in range(n_variants):
            # 选择变体参数
            order_id = generate_order_id()
            reason = random.choice(_REASONS)
            margin = random.choice(_MARGINS)
            customer_id = random.choice(_CUSTOMER_IDS)

            # 检查是否重复
            combo_key = (template, order_id, reason, margin, customer_id)
            if combo_key in seen_combinations:
                # 如果重复，重新生成 order_id
                for _ in range(10):
                    order_id = generate_order_id()
                    combo_key = (template, order_id, reason, margin, customer_id)
                    if combo_key not in seen_combinations:
                        break
            seen_combinations.add(combo_key)

            # 应用变体到 task
            new_task = apply_variant(task, order_id, reason, margin, customer_id, template)

            # 应用变体到 trajectory（更新 steps 中的 tool_call arguments）
            new_trajectory = apply_variant_to_trajectory(
                sample["trajectory"], old_order_id, order_id, reason
            )
            new_trajectory["task"] = new_task

            # 构造新的样本
            new_sample = {
                "source": "oversampled",
                "task_fingerprint": hashlib.sha256(
                    json.dumps(new_task, sort_keys=True).encode()
                ).hexdigest(),
                "task_id": new_task["task_id"],
                "trajectory": new_trajectory,
            }
            all_samples.append(new_sample)

    print(f"Generated samples: {len(all_samples)}")

    # 按 sha256 切分 train/dev/holdout = 80/10/10
    random.shuffle(all_samples)
    n = len(all_samples)
    train_end = int(n * 0.8)
    dev_end = int(n * 0.9)

    train_samples = all_samples[:train_end]
    dev_samples = all_samples[train_end:dev_end]
    holdout_samples = all_samples[dev_end:]

    print(f"Train: {len(train_samples)}, Dev: {len(dev_samples)}, Holdout: {len(holdout_samples)}")

    # 写入文件
    for split_name, split_samples in [
        ("sft", train_samples),
        ("dev", dev_samples),
        ("holdout", holdout_samples),
    ]:
        output_path = output_dir / f"{split_name}.jsonl"
        with open(output_path, "w") as f:
            for sample in split_samples:
                f.write(json.dumps(sample, ensure_ascii=False) + "\n")
        print(f"Wrote {output_path}: {len(split_samples)} samples")

    # 写入 metadata
    metadata = {
        "source": "r9_phase_a_oversample",
        "original_count": len(original_samples),
        "generated_count": len(all_samples),
        "train_count": len(train_samples),
        "dev_count": len(dev_samples),
        "holdout_count": len(holdout_samples),
        "split_ratio": "80/10/10",
        "seed": _SEED,
        "margins": list(_MARGINS),
        "reasons": list(_REASONS),
        "customer_ids": _CUSTOMER_IDS,
    }
    with open(output_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)
    print("Wrote metadata.json")


if __name__ == "__main__":
    main()
