# flight_ops 跨域发布判定报告

> 生成时间：2026-08-24  
> 报告阶段：R10  
> 数据集：flight_ops_v1_r10（60 条 dev 任务）  
> 基座模型：Qwen3-4B-pinned（无 adapter）  
> 候选 adapter：reports/flight_ops/v1/r9/train/adapter

---

## 发布判定：GO

flight_ops 跨域候选在全部 60 条 dev 任务上达到 100% 成功，零策略违规，且 4/4 门禁全部通过。

---

## 指标对比

| 指标 | Base | Candidate | 变化 |
|---|---|---|---|
| task_success | 0.4833 (29/60) | 1.0000 (60/60) | +0.5167 |
| task_success_ci95 | [0.35, 0.62] | [1.00, 1.00] | — |
| policy_violation_count | 30 | 0 | −30 |
| policy_violation_rate | 0.5000 | 0.0000 | −0.5000 |
| tool_selection_accuracy | 0.5900 | 1.0000 | +0.4100 |
| argument_accuracy | 0.5000 | 0.7667 | +0.2667 |
| invalid_call_count | 0 | 0 | — |
| invalid_call_rate | 0.0000 | 0.0000 | — |
| schema_valid_rate | 1.0000 | 1.0000 | — |
| executable_rate | 1.0000 | 1.0000 | — |
| average_turns | 1.82 | 2.17 | +0.35 |
| average_tool_calls | 1.48 | 1.50 | +0.02 |
| average_input_tokens | 884.72 | 1077.17 | +192.45 |
| average_output_tokens | 60.23 | 94.67 | +34.44 |
| average_latency_ms | 1292.05 | 2766.89 | +1474.84 |
| p50_latency_ms | 1172.65 | 2417.02 | +1244.37 |
| p95_latency_ms | 2037.73 | 4344.68 | +2306.95 |
| verifier_reward | −0.0167 | 1.0000 | +1.0167 |
| recovery_success | 0.0000 | 0.0000 | — |

---

## 门禁结果

| 门禁 ID | 阈值 | 实际值 | 判定 |
|---|---|---|---|
| success_delta | ≥ 0.05 | +0.5167 | PASS |
| policy_violation_delta | ≤ 0 | −30 | PASS |
| invalid_call_count | = 0 | 0 | PASS |
| evidence_complete | = true | true | PASS |

**4/4 门禁通过。**

---

## 证据链

### report_id 自哈希

| 角色 | report_id |
|---|---|
| base | `4a9fe7ff8477941cbc3a4bb6947fb1c0f9deb2a3279b436f2a9358daf51a6cba` |
| candidate | `743dda363f0b35594effe742c55a3a0fb8e59cd50c2011f3e91f8b219396e939` |

### 数据完整性

- base bundle_sha256：`7405582765270cb6decb94cccb3e209ab6f290b237707e98782ae3f9307fe524`
- candidate bundle_sha256：`7405582765270cb6decb94cccb3e209ab6f290b237707e98782ae3f9307fe524`
- manifest_sha256（共用）：`1b0211d1edf89fd96533c1fea224fb05de0128a889ae1daa556efa1423d52de4`

### 失败类型分布

| 失败类型 | Base | Candidate |
|---|---|---|
| policy_violation | 30 | 0 |
| premature_final_response | 1 | 0 |

---

## 局限性

1. **单领域**：本次评估仅覆盖 flight_ops 领域，未验证跨领域泛化。
2. **60 条 dev 任务**：样本量有限，置信区间较宽（base CI95: [0.35, 0.62]）。
3. **无 holdout**：未设置独立 holdout 集，存在选择偏差风险。
4. **延迟上升**：候选 p95 延迟 4344.68ms，较 base 上升约 2.13×，生产部署需关注。
5. **argument_accuracy 未达满分**：候选 argument_accuracy 为 0.7667，虽不影响最终成功但存在参数精度空间。
