#!/usr/bin/env python3
"""将 oversampled train.jsonl 转换为 SFT 格式的 sft.jsonl。"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from veritool_rl.core.generators import trajectory_to_sft_example
from veritool_rl.core.trajectory.schema import (
    ExpectedDecision,
    TaskScenario,
    TerminationReason,
    Trajectory,
)


def convert_enums(sample: dict) -> dict:
    """将字符串枚举值转换为实际的枚举类型。"""
    traj = sample["trajectory"]

    # 转换 task.scenario
    if "task" in traj and "scenario" in traj["task"]:
        scenario_str = traj["task"]["scenario"]
        try:
            traj["task"]["scenario"] = TaskScenario(scenario_str)
        except ValueError:
            # 尝试匹配
            for s in TaskScenario:
                if s.value == scenario_str:
                    traj["task"]["scenario"] = s
                    break

    # 转换 task.expected_decision
    if "task" in traj and "expected_decision" in traj["task"]:
        decision_str = traj["task"]["expected_decision"]
        try:
            traj["task"]["expected_decision"] = ExpectedDecision(decision_str)
        except ValueError:
            for d in ExpectedDecision:
                if d.value == decision_str:
                    traj["task"]["expected_decision"] = d
                    break

    # 转换 termination
    if "termination" in traj:
        term_str = traj["termination"]
        try:
            traj["termination"] = TerminationReason(term_str)
        except ValueError:
            for t in TerminationReason:
                if t.value == term_str:
                    traj["termination"] = t
                    break

    return sample


def main():
    input_path = Path("data/private/retail_ops/v1/r9/phase-a/sft.jsonl")
    output_path = Path("data/private/retail_ops/v1/r9/phase-a/sft_sftformat.jsonl")

    count = 0
    errors = 0
    with open(input_path) as fin, open(output_path, "w") as fout:
        for line in fin:
            sample = json.loads(line)
            try:
                sample = convert_enums(sample)
                traj = Trajectory.model_validate(sample["trajectory"])
                sft_example = trajectory_to_sft_example(traj)
                fout.write(json.dumps(sft_example, ensure_ascii=False) + "\n")
                count += 1
            except Exception as e:
                errors += 1
                if errors <= 3:
                    print(f"Error: {sample.get('task_id', '?')}: {e}", file=sys.stderr)

    print(f"Converted: {count}, Errors: {errors}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
