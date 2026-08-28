# 评测脚本 Bug 审查报告

**审查范围**：`src/veritool_rl/retail_ops/evaluate/` 全部模块、`product_cli.py` 评测入口、`configs/retail_ops/evaluate/`、`scripts/run_v3_degradation.py`。

---

### 1. OOD config 的 `dataset_version` Literal 只允许 2 个版本，实际有 5 个

**文件**：`ood_evaluation.py:64-66`

```python
dataset_version: Literal["retail_ops_ood_v1_20260815", "retail_ops_ood_v2_20260817"] = (
    "retail_ops_ood_v1_20260815"
)
```

`ood_manifests.py:69-79` 注册了 5 个合法 `OodDatasetVersion`（v1、v2、v2_2、policy_boundary、v4），但 config 的 Literal 只允许前两个。v2_2、policy_boundary、v4 无法通过配置传入 config。`evaluate_ood` 用的是 `manifest.dataset_version`（正确），但 `config.dataset_version` 参与了 `config_sha256` 计算——**所有 v2_2/policy_boundary/v4 的 OOD 报告的 `config_sha256` 里都嵌入了默认值 `"retail_ops_ood_v1_20260815"`**。

---

### 2. `_run_ood_evaluate` 不从 config 传 `dataset_version`，config 侧值永远是 v1

**文件**：`product_cli.py:752-757`

```python
ood_config = OodEvaluationConfig(
    model=ModelArtifact(**_config_mapping(config, "model")),
    adapter=...,
    generation=GenerationSettings(**_config_mapping(config, "generation")),
    code_commit=...,
)
```

`_OOD_EVAL_BASE_KEYS`（`product_cli.py:628-634`）不包含 `dataset_version`。即使配置文件里有这个 key，它也不会被传入 `OodEvaluationConfig`，因此 config 的 `dataset_version` 永远是 Literal 默认值 `"retail_ops_ood_v1_20260815"`。

**后果**：所有 OOD 评测报告的 `config_sha256` 里嵌入的数据集版本始终是 v1，即使 manifest 实际是 v4。config 声明的数据集版本被静默忽略。

---

### 3. 评测路径没有超时机制

**文件**：`runner.py:76`、`base_evaluation.py:458-473`、`ood_evaluation.py:161-164`

`run_episode` 在 `for index in range(task.max_steps)` 循环里调用 `policy.respond()`，没有超时。`execute_formal_records` 逐条调用 `run_episode`，也没有超时。

`serve` 路径有 `episode_timeout_s`（`product_cli.py:397-401`，`service.py` 用 `asyncio.wait_for` 实现），但评测路径完全没有超时。

**后果**：如果模型在一个步骤上卡住（例如推理链永不停止），整批评测会挂起。GPU 资源被锁死，直到人工干预。没有任何日志或指标能区分「模型在思考」与「后端挂了」。评测可以是 60、120 或 240 条任务，一条卡住就是整批挂住。

---

### 4. `perturb_schema` 的工具描述硬编码了 5 个工具名，v3 的 15 工具子集会 KeyError

**文件**：`environment.py:130-136`

```python
descriptions = {
    "get_order": "读取指定订单的当前详情。",
    "refund_order": "核验后执行符合退款政策的订单退款。",
    "get_store_hours": "读取指定城市的门店营业时间。",
    "get_refund_status": "查询指定订单的退款处理进度。",
    "cancel_order": "核验后取消尚未发货的订单。",
}
```

`perturb_schema`（`environment.py:137-153`）遍历 `self._bundle.tools`（bundle 全量工具），用 `descriptions[schema.name]` 取描述。v3 bundle 有 15 个工具，但 descriptions 只覆盖 5 个。如果 `allowed_tools` 包含未覆盖的工具名，会抛 `KeyError`。

**后果**：v1/v2 不受影响（3 个工具全在 dict 里）。v3 评测如果同时开 `perturb_schema` 和 `allowed_tools`，会在未覆盖的工具上 KeyError。当前 v3 评测配置没开 `perturb_schema`，所以没触发，但这是一个隐藏的硬编码 bug。

---

### 5. `OodEvaluationConfig.dataset_version` 与 manifest 的 `dataset_version` 没有做一致性校验

**文件**：`ood_evaluation.py:140-179`

`evaluate_ood` 校验了 `manifest.bundle_sha256 == bundle.bundle_sha256` 和任务数，但没有校验 `config.dataset_version == manifest.dataset_version`。

**后果**：config 里写的是 v1，manifest 实际是 v4，评测会正常运行。`OodRunEvidence.dataset_version` 用 manifest 的值（正确），但 `config_sha256` 里嵌入的是 config 的值（错误）。两份报告的 `config_sha256` 不可比。

---

### 6. formal base/candidate 重放不传 guardrail 和 user_simulator

**文件**：`base_evaluation.py:458-473`

```python
def execute_formal_records(...):
    def env_factory(task): return RetailOpsEnv(task, bundle)
    trajectories = [run_episode(record.task, env_factory, policy, seed) for record in records]
    replayed = sum(
        replay_trajectory(trajectory, env_factory).matched for trajectory in trajectories
    )
```

`replay_trajectory` 只传了 `env_factory`，没有 `guardrail_factory` 和 `user_simulator_factory`。qualification 路径（`evaluation.py:184-192`）正确传了这两个参数。

**后果**：当前 formal 路径不使用 guardrail/user_simulator，所以重放恰好匹配。但如果将来 formal 路径启用 guardrail 或 user_simulator，重放会不匹配且无法发现——`replayable_count` 会假阳性为满分。这是一个违反「重放条件必须与产出条件一致」不变量的脆弱性。

---

### 7. `_MAX_STEPS` 模块常量与 `BaseEvaluationConfig.max_steps` Literal 之间没有代码级绑定

**文件**：`sealed_evaluation.py:74`、`base_evaluation.py:116`

```python
# sealed_evaluation.py
_MAX_STEPS = 5

# base_evaluation.py
max_steps: Literal[5] = 5
```

`_require_step_budget`（`sealed_evaluation.py:692-696`）用 `_MAX_STEPS` 校验，而 `run_episode` 用 `task.max_steps`（来自冻结数据集）。config 的 `max_steps` 也是 `Literal[5]`。三者值恰好相等但互相独立——改一个忘改另一个不会报错。

**后果**：当前无 bug，但将来改步数预算需要同时改三个地方（`_MAX_STEPS`、`BaseEvaluationConfig.max_steps`、冻结数据集），且没有编译期或运行时绑定保证。

---

### 8. `tool_selection_accuracy` 在 `compute_metrics` 里没有分解 distractor/unknown

**文件**：`metrics.py:98-109`

`compute_metrics` 计算 `tool_selection_accuracy` 时，分母是 `max(len(actual_calls), len(expected_calls))`，分子是逐位命中数。它不追踪 distractor calls、unknown tool calls、invalid calls——这些只在 `toolcount_eval.py` 的 `score_tool_selection` 里有。

正式评测报告（`metrics.json`）里的 `tool_selection_accuracy` 是一个粗粒度指标，无法区分「模型调了不存在的工具」与「模型多调了一次正确的工具」。toolcount_eval 有细分指标（`distractor_calls`、`unknown_tool_calls`、`invalid_calls`），但这些不会出现在正式 `metrics.json` 里。

**后果**：正式报告的 `tool_selection_accuracy` 读数比 toolcount_eval 的 `tool_selection_accuracy` 含义不同——前者不分解失败原因。两种路径的数字不能直接比较（`toolcount_eval` 的 `compared = max(len(gold), len(actual))` 与 `compute_metrics` 的公式一致，但 toolcount_eval 的 `matched` 定义与 `compute_metrics` 的 `correct_tools` 定义也一致）。没有数据错误，但正式报告缺少 toolcount_eval 里的关键诊断维度。

---

### 9. 评测配置文件有冗余注释引用已不存在的配置

**文件**：`configs/retail_ops/evaluate/retail_ops_ood_v4_r9_sft003.yaml:3-4`

```yaml
# R9 Phase B sft-003 在 OOD v4（跨工具泛化，12 场景 × 10）上的评测。
# Phase B 核心主张的正面计量：语义重叠工具选择 × 说法泛化。
# R9 Phase B 第二轮候选（sft-002）在 OOD v2 dev 上的评测。
# v1 bundle 任务集（3 工具），检验措辞增强修复后 phrasing 泛化是否恢复。
```

第 3-4 行注释说「sft-002 在 OOD v2 dev 上的评测」「v1 bundle 任务集（3 工具）」，但这个配置实际是 sft-003 在 OOD v4 上的评测，使用 v4 bundle（`bundle_dir: domains/retail_ops/v4`）。注释是从其他配置文件复制过来的，描述的是另一个配置。

**后果**：无功能影响，但注释误导。

---

### 10. OOD 评测路径的 `evaluate_ood` 不做 replay 时的 guardrail 校验

**文件**：`ood_evaluation.py:168-171`

```python
replayed = sum(
    replay_trajectory(trajectory, lambda current: RetailOpsEnv(current, bundle)).matched
    for trajectory in trajectories
)
```

重放不传 guardrail。OOD 路径的 `run_episode`（`ood_evaluation.py:161-164`）也不传 guardrail：

```python
trajectories = [
    run_episode(task, lambda current: RetailOpsEnv(current, bundle), policy, manifest.seed)
    for task in tasks
]
```

所以当前重放条件与产出条件一致（都没有 guardrail）。但如果将来 OOD 路径启用 guardrail，重放会不匹配——与 issue #6 同一类问题。

**后果**：当前无 bug。与 #6 一起，是评测系统缺少「重放条件必须与产出条件一致」的编译期或测试层保障。

---

### 11. `_require_config_keys` 做精确匹配，OOD eval 配置不允许 `dataset_version`

**文件**：`product_cli.py:748`、`product_cli.py:1931-1935`

`_require_config_keys` 用 `set(config) != expected` 做**精确匹配**（不是超集）。`_OOD_EVAL_BASE_KEYS` 不包含 `dataset_version`，因此如果配置文件里写了 `dataset_version`，`_require_config_keys` 会**拒绝**它——但错误信息是「配置字段不符合命令契约」，不会告诉操作者「dataset_version 不在这里用」。

**后果**：操作者如果按直觉在 OOD eval 配置里加了 `dataset_version`，会得到一个不指向真正原因的报错。这与 OOD build 配置（有 `dataset_version` key）形成不对称——build 有，eval 没有。

---

### 12. `OodRunEvidence` 没有 `config_dataset_version` 字段暴露 config 侧值

**文件**：`ood_evaluation.py:79-123`

`OodRunEvidence.dataset_version` 取自 manifest（正确），但没有字段记录 config 里的 `dataset_version`。读者无法从报告追溯 config 声明了什么版本。

**后果**：无法发现 config↔manifest 的 dataset_version 不一致。

---

### 13. `RetLetEnv.perturb_schema` 不校验 bundle 工具是否在 descriptions dict 中

**文件**：`environment.py:137-153`

```python
for schema in self._bundle.tools:
    if schema.name not in self._allowed_tools:
        continue
    alias = f"{schema.name}_{rng.randrange(1000, 10000)}"
    ...
    schemas.append(
        ToolSchema(
            name=alias,
            description=descriptions[schema.name],  # KeyError if not in dict
            ...
        )
    )
```

与 issue #4 相同：`descriptions` dict 只覆盖 5 个工具名，`self._bundle.tools` 可能包含更多。

**后果**：v3 bundle + `perturb_schema` + `allowed_tools` 包含非前 5 工具 → KeyError。

---

### 14. sealed 路径的 `SealedEvaluationReport` 的 `config_sha256` 不包含 `adapter` 字段

**文件**：`sealed_evaluation.py:373-374`

```python
config_sha256=config.config_sha256,
```

`SealedEvaluationConfig` 继承自 `BaseEvaluationConfig`（`max_steps: Literal[5]`），外加 `adapter` 和 `merged_from`。`config_sha256` 是 `_content_sha256(self.model_dump(mode="json"))`（`base_evaluation.py:124-125`），包含全部字段（包括 adapter）。

**后果**：无 bug，config_sha256 正确包含了 adapter 信息。

---

### 15. `toolcount_eval.preflight_breakpoint` 用 `OraclePolicy` 但不传 seed

**文件**：`toolcount_eval.py:253`

```python
trajectory = run_episode(task, env_factory, OraclePolicy(task), seed=0)
```

Oracle 是确定性的（按 gold 序列执行），seed 不影响其行为。`run_episode` 把 seed 存入 metadata，不用于 Oracle。

**后果**：无 bug，seed 对 Oracle 无意义。

---

### 总结

| # | 严重程度 | 类型 | 文件 |
|---|---|---|---|
| 1 | 中 | Literal 不完整 | `ood_evaluation.py:64` |
| 2 | 中 | config 传参遗漏 | `product_cli.py:752` |
| 3 | 高 | 缺失超时 | `runner.py:76` |
| 4 | 中 | 硬编码 bug | `environment.py:130` |
| 5 | 中 | 缺失校验 | `ood_evaluation.py:140` |
| 6 | 低 | 脆弱性 | `base_evaluation.py:458` |
| 7 | 低 | 冗余常量 | `sealed_evaluation.py:74` |
| 8 | 低 | 指标粒度 | `metrics.py:98` |
| 9 | 低 | 注释错误 | `retail_ops_ood_v4_r9_sft003.yaml:3` |
| 10 | 低 | 脆弱性 | `ood_evaluation.py:168` |
| 11 | 低 | 配置校验 | `product_cli.py:748` |
| 12 | 低 | 可追溯性 | `ood_evaluation.py:79` |
| 13 | 中 | 硬编码 bug | `environment.py:137` |

---

# 7.2 测试覆盖盲区审查

**审查日期**：2026-08-28
**审查范围**：`tests/` 全部 90 个文件（1352 条测试）、`src/veritool_rl/` 全部源模块

---

## 1. 核心路径的测试覆盖

### 1.1 Agent 执行循环 (`core/agent/runner.py`)

`test_agent_runner.py` 有 8 条测试覆盖了 oracle 完成、格式错误消耗步数、政策违规终止、工具调用历史格式、终端响应记录。以下分支无测试：

- **user_simulator 分支 (runner.py:139-143)**：`test_retail_ops_user_simulator.py` 通过端到端测试间接覆盖了 `clarify=True, simulator=True` 的组合，但没有单元测试验证 `user_reply` 追加到 messages 后下一步 policy 收到的是带澄清内容的 messages。端到端测试只看到最终 `success=1.0`，看不到中间 messages 的形状。
- **非成功最终答复终止 (runner.py:171-173)**：`test_runner_records_terminal_response_before_verification` 覆盖了 `success` 路径，但没有测试 `final_response is not None and user_reply is None` 且 `reward.final_state != 1.0` 的路径（agent 说了结束语但任务没做完）。
- **system_prompt 参数 (runner.py:48, 68)**：没有单元测试验证传入自定义 `system_prompt` 后 messages 的 system 段确实被替换。`test_v2_prompt_carries_the_policy` 只验证了 prompt 文本生成，没有验证 `run_episode` 里它被放进了 messages。
- **guardrail 在 parse_error 路径的行为**：`test_retail_ops_guardrail.py` 测试了 guardrail 拦截 tool_call 的路径，但没有测试当 `parse_error is not None` 时 guardrail 是否仍参与（代码里 parse_error 路径跳过了 guardrail 检查——这是正确的，但没有测试确认这个隐含契约）。

### 1.2 Tool Parser (`core/agent/parser.py`)

5 条测试覆盖了主要路径。遗漏：

- **空响应 (parser.py:29-30)**：`parse_error="empty_response"` 分支无测试。当输入是空字符串时的行为未验证。
- **Pydantic ValidationError 路径 (parser.py:39)**：`json.loads` 成功但 `ToolCall.model_validate` 失败时（例如 arguments 里有非法类型），当前只测了 JSON 解析失败，没测 Pydantic 验证失败。

### 1.3 Metrics (`core/metrics.py`)

`test_metrics.py` 有 4 条测试。遗漏：

- **`split_headline_and_diagnostic` 函数 (metrics.py:32-36)**：完全没有测试。这个函数把 `verifier_reward` 分离出来，但没有任何测试验证分离逻辑。
- **`paired_bootstrap_delta_ci95` 的边界情况**：没有测试全 True、全 False、一半一半的配对结果。当前只在 `test_release_gate_schema_v11.py` 中间接覆盖了均匀改善和噪声带内的场景。
- **`compute_metrics` 中 `recovery_success` 和 `tool_selection_accuracy` 在零步轨迹上的行为**：`test_empty_metrics_have_defined_zero_denominators` 测试了空列表，但没有测试有轨迹但所有轨迹都是零步（`steps=[]`）的情况。

### 1.4 Verifier Rewards (`core/rewards/verifier.py`)

`compute_reward_breakdown` 在 `test_agent_runner.py` 和 `test_metrics.py` 中被间接覆盖。但：

- **`final_state_reward`、`policy_reward`、`milestone_reward` 三个独立函数 (verifier.py:32-47)**：完全没有独立测试。它们只是 `compute_reward_breakdown` 的分量包装，但没有任何测试验证它们与 `compute_reward_breakdown` 的一致性。

### 1.5 Trajectory Schema (`core/trajectory/schema.py`)

- **`validate_json_value` 函数 (schema.py:19-40)**：完全没有测试。这个递归验证器拒绝非 JSON 类型、非字符串 object key 和非有限浮点数，但没有任何测试覆盖。`test_trajectory_schema.py` 只测了 schema 零字段校验，没测这个验证器。
- **`StrictModel` 基类的 `extra="forbid"` 和 `allow_inf_nan=False`**：没有专门测试传入未知字段或 NaN/Inf 时是否被拒绝。

### 1.6 Replay (`core/trajectory/replay.py`)

`test_replay.py` 有 6 条测试。覆盖良好。遗漏：

- **`replay_trajectory` 对 `user_simulator` 产生的多轮轨迹的重放**：当前只测了单轮 oracle 轨迹和 retail_ops denial 轨迹的重放，没有测多轮（带 user simulator）轨迹的重放。

### 1.7 User Simulator (`core/agent/user_simulator.py`)

`test_retail_ops_user_simulator.py` 覆盖良好（提问识别、终端答复、回复上限、确定性、端到端三组对照）。遗漏：

- **`_known_order_id` 函数 (user_simulator.py:84-91)**：当 `task.metadata["order_id"]` 不是字符串或为空时返回 None，但没有直接测试。
- **`clarification_metadata` 函数 (user_simulator.py:94-97)**：完全没有测试。这个函数解析任务的 clarification 元数据，但没有任何测试覆盖。

### 1.8 RetailOps Environment (`retail_ops/domain/environment.py`)

`test_retail_ops_environment.py` 有 7 条测试，覆盖了主要场景。遗漏：

- **v3 任务（CANCEL/REFUND_THEN_CANCEL）在环境中的执行**：环境代码里有 `CANCEL_ELIGIBLE`、`REFUND_THEN_CANCEL` 等场景的处理逻辑，但环境层面的测试只覆盖了 v1 的 7 个场景。v4 新增场景（v3_tasks.py/v4_tasks.py）的行为没有在环境层面被测试。
- **`execute_tool` 传入不存在的 tool name 时的行为**：没有测试环境对未知工具名的拒绝。

### 1.9 Flight Ops

`test_flight_ops_eval.py` 有 4 条测试，覆盖了 oracle 评测、report ID 确定性、篡改检测、paired comparison。但：

- **FlightOps Environment 的政策拒绝路径**：`test_flight_ops_env.py` 的覆盖范围没有检查。FlightOps 有独立的 `policy_rules.py`，但没有测试验证其规则引擎与 RetailOps 的同构性。
- **FlightOps 的 guardrail 层**：完全没有 flight_ops 版本的 guardrail 测试。

### 1.10 Service Layer (`retail_ops/serve/service.py`)

`test_formal_service.py` 有 10 条测试，覆盖了 GO/NO-GO 回滚、health 端点、episode 运行、并发限制、请求大小限制。遗漏：

- **`/v1/tasks` 端点的分页或空任务列表行为**：没有测试当 build 目录为空时的行为。
- **鉴权失败路径**：没有测试 `api_key` 缺失或错误时返回 401 的行为。`test_project_governance.py` 只验证了参数签名，没有测试实际的 HTTP 401 响应。
- **`episode_timeout_s` 超时行为**：配置里有 `episode_timeout_s` 参数，但没有测试验证超时后 episode 被终止。

### 1.11 Product CLI (`product_cli.py`)

`test_product_cli_entrypoint.py` 和 `test_retail_ops_cli.py` 覆盖了主要 CLI 命令。遗漏：

- **`serve` 命令在无 API key 环境变量时的行为**：`test_formal_service.py` 里 `monkeypatch.setenv` 设了 key，但没有测试缺少 key 时报错的行为。
- **`build` / `evaluate` / `release` 命令传入不存在的 config 文件时的行为**：没有测试 config 文件缺失时的错误消息。

---

## 2. 边界条件测试

### 2.1 有测试的边界条件

- 最大步数（`test_format_errors_consume_steps_without_crashing_episode`）
- 空输入/空轨迹（`test_empty_metrics_have_defined_zero_denominators`）
- 格式错误输入（`test_qwen_parser_rejects_malformed_tool_call`）
- 不安全路径名（`test_sealed_evaluator_rejects_unsafe_attempt_identifiers`）
- 并发限制（`test_concurrent_episodes_are_capped_instead_of_queueing`）
- 请求大小上限（`test_oversized_request_body_is_rejected`）
- 配对证据缺失（`test_paired_ci_gate_fails_when_there_is_no_paired_evidence`）
- 分母为零（`test_undefined_ratios_fail_closed`）

### 2.2 缺失的边界条件

- **`max_steps=0` 或 `max_steps=1` 的 TaskSpec**：没有测试零步或一步的 episode 行为。runner.py 的 `for index in range(task.max_steps)` 在 `max_steps=0` 时直接返回空 steps 列表，但没有测试确认。
- **所有工具调用都失败时的轨迹**：没有测试连续 N 次 `unknown_tool` 后轨迹的 termination 和 metrics。
- **`bootstrap_samples` 大于轨迹数时的行为**：`compute_metrics` 里 bootstrap 采样在样本数大于轨迹数时的行为没有测试。
- **tool_call 的 `arguments` 包含嵌套对象、数组、null 值**：parser 测了 JSON 解析失败，但没测合法但深层嵌套的 arguments。
- **`idempotency_key` 重复时的环境行为**：`test_retail_ops_environment.py` 测了 `duplicate_refund`，但没有专门测 idempotency_key 相同的两次 refund_order 调用。

---

## 3. 测试本身的 Bug

### 3.1 `test_project_governance.py` 中 `_collected_test_count` 的脆弱性

`test_documented_test_count_matches_reality` (line 1463) 和 `test_the_author_environment_baseline_never_appears_without_the_clean_clone_one` (line 1493) 都调用 `_collected_test_count()`，该函数跑 `pytest --collect-only` 来获取当前测试数。这意味着 **测试在运行自身时会递归收集自己**，如果收集过程出错（比如 import 失败），报错信息会像是"文档数字对不上"而不是"import 失败"。docstring 里已经提到了这个风险（clone 上的 python 找不到），但没有 try/except 保护。

### 3.2 `test_the_total_count_detector_catches_what_it_claims_to` 的断言方向

`test_project_governance.py:1074-1089` 里 `_MUST_BE_CAUGHT` 语料库用的是当前观测次数的值（从 ledger 现算）。但 `_MUST_BE_ALLOWED` 里的句子如"封存 holdout 上前三次观测都是 NO-GO"——如果将来观测次数变成 3，`_count_offenders` 会因为它包含了数字 "3" 且在封存 holdout 作用域内而误判。当前 ledger 有 5+ 次观测所以 "3" 不是当前值，但这依赖于 ledger 的当前状态。**测试通过不是因为逻辑正确，而是因为当前那个数字恰好不是 3。**

### 3.3 `test_fault_matrix.py` 的最低引用数断言

`test_every_fault_class_names_a_real_test` (line 52) 断言 `len(references) >= 20`。如果故障矩阵被缩减到 19 个引用但仍然覆盖了所有五类故障，测试会失败——而 19 个引用可能比 20 个更精炼。这个阈值是任意的，没有绑定到任何设计约束。

### 3.4 `test_retail_ops_e2e.py` 的硬编码期望值

`test_retail_ops_v1_cpu_vertical_slice` (line 76-80) 硬编码了 `task_success == 8/12`（base）和 `task_success == 0.0`（fault）。如果环境行为变化（例如修复了一个 bug 让 base 从 8/12 变成 9/12），这条测试会失败——但它不是因为回归，而是因为进步。这些值没有绑定到任何规格文档。

---

## 4. 测试的确定性

### 4.1 确定性良好的部分

- `test_retail_ops_evaluation.py` 的 `test_identical_qualification_runs_write_identical_evidence` 直接验证了两次运行产生逐字节相同的结果。
- `test_metrics.py` 的 `test_oracle_metrics_match_hand_computed_values` 验证了同一份输入两次计算结果相同。
- `test_release_gate_schema_v11.py` 的 `test_paired_bootstrap_is_deterministic` 验证了 bootstrap 的可复现性。
- 所有使用 `seed` 参数的地方都使用了固定 seed。

### 4.2 潜在不确定性的来源

- **`_collected_test_count()` 依赖 pytest 收集顺序**：如果测试文件被重命名或新增，收集数变化会导致 `test_documented_test_count_matches_reality` 失败。这不是 flaky test，但是高维护成本的测试。
- **`test_gitignore_covers_every_class_of_artefact_that_must_not_ship` 依赖 `git ls-files` 和 `git check-ignore`**：如果开发者有未提交的 `.gitignore` 变更，这条测试的结果会不同。但因为用的是 `git ls-files`（只看已提交的），这个风险较低。
- **`test_the_documented_test_count_matches_reality` 在不同环境下可能给出不同数字**：`pytest --collect-only` 的结果取决于当前 Python 环境安装的依赖（某些测试可能被 skip 或 conditional skip）。

---

## 5. 治理测试的有效性

### 5.1 有效且深入的部分

- **`test_gitignore_covers_every_class_of_artefact_that_must_not_ship`**：双向验证——既验"该忽略的被忽略了"，也验"该进 Git 的没被忽略"。这是防止 `.gitignore` 规则过宽的唯一机制。有效。
- **`test_source_layers_enforce_one_way_dependency`**：通过 grep import 语句验证层间依赖方向。虽然不覆盖动态 import 和 `__import__`，但对当前代码库足够。
- **`test_service_credentials_never_live_in_the_repo`**：验证配置文件里没有凭据字段、`create_formal_app` 的 `api_key` 参数没有默认值。有效。
- **`test_the_config_governance_scan_catches_a_planted_violation`**：反向验证——种一个违规必须被抓到。这证明治理扫描不是空操作。

### 5.2 有效性不足或表面化的部分

- **`test_holdout_ledger_is_the_single_source_of_truth`**：断言了台账里有特定字符串（`"唯一事实源"`, `"LOG-20260811-03"` 等），但这只是在检查**措辞在场**，不是在检查**机制有效**。台账的"唯一事实源"地位实际上由 `test_no_active_doc_restates_the_sealed_holdout_observation_count` 扫描全部 Markdown 来保障——但那条测试的检测器自己有明确记录的漏检（docstring 里写了四种挡不住的写法）。
- **`test_v1_domain_bundle_is_byte_identical_to_the_frozen_evidence`**：断言了一个特定的 SHA-256 哈希值。这是有效的冻结检查，但哈希值本身是硬编码的——如果 bundle 内容被合法修改（比如修复一个拼写错误），测试会失败，而失败的原因是"旧哈希不对"而不是"你改了不该改的东西"。测试没有区分"合法修改"和"非法篡改"。
- **`test_the_r3_candidate_shares_the_base_model_with_its_control`**：只验证了 `retail_ops_v1_r3_qwen3_4b_candidate.yaml` 与 `retail_ops_v1_r2_qwen3_4b_dev.yaml` 的 model 段相同。但如果有人新增了一个候选配置而没有配对 base 配置，这条测试不会捕捉到——它只检查已列出的两份配置。
- **`test_release_configs_declare_their_gate_schema_version`**：只验证 `gate_schema_version in {"1.0", "1.1"}`，不验证这个版本号是否与实际使用的门禁集合匹配。一份声明了 `"1.1"` 但实际用 v1.0 门禁的配置不会被这条测试抓到。

### 5.3 治理测试的结构性盲区

- **配置的 `file_sha256` 内容是否真实**：`test_every_committed_config_holds_the_governance_line` 验证了 `file_sha256` 是 64 位十六进制，但不验证它是否与实际模型文件匹配。一个写了正确长度但错误值的哈希会通过。
- **`model.revision` 是否可解析**：测试验证了 `revision` 长度 >= 7，但不验证这个 revision 在模型仓库中是否存在。
- **configs 和 domains 的一致性**：没有测试验证配置文件引用的 `bundle_dir` 是否存在且包含有效 bundle。配置引用了一个不存在的路径不会被测试抓到。

---

## 6. 测试的维护成本

### 6.1 测试数量

1352 条测试，90 个测试文件。

### 6.2 高维护成本的测试

- **`test_project_governance.py` (1823 行)**：这是全仓最大的测试文件，包含 ~30 条测试。它承担了文档一致性、数字配对、双语同步、观测次数单一来源、简历 bullet 审计等多个不相关的职责。每次修改 README、RESUME_EVIDENCE、MODEL_CARD、GENERALIZATION_FIX 等文档都可能触发多条测试失败。这些测试的失败消息通常很长且难以快速定位根因。
- **`test_fault_matrix.py`**：虽然只有 79 行，但它解析故障矩阵的 AST 来验证引用存在性。这种"测试文档里的测试引用"的元测试维护成本高——改一个测试名就要同步更新文档。
- **`test_sealed_evaluation.py` (491 行)**：使用了 `module` 级 fixture (`formal_source`)，这意味着如果 fixture 构建失败，整个模块的所有测试都会失败，而不是单条失败。`formal_source` 调用了 `write_formal_task_set` 和 `load_bundle`，这些操作在测试环境不存在私有数据时会跳过。

### 6.3 测试运行时间

大部分测试是纯 CPU 逻辑测试，应该很快。但以下测试可能较慢：

- `test_retail_ops_e2e.py`：跑完整的 build → evaluate → release 全链路。
- `test_sealed_evaluation.py`：构建 120 条形式化任务并重放。
- `test_retail_ops_guardrail.py` 的端到端注入评测：构建 12 条注入任务并跑两轮。
- `test_retail_ops_user_simulator.py` 的端到端三组对照：构建 36 条任务。
- `_collected_test_count()` 在每条调用时都会跑一次 `pytest --collect-only`。

### 6.4 测试与文档的耦合

`test_project_governance.py` 里大量测试直接读取并断言特定文档的内容（README、RESUME_EVIDENCE、MODEL_CARD 等）。这意味着**文档修改和代码修改会互相触发测试失败**。AGENTS.md 里的规则（如"候选结论一律以 dev 或 holdout 口径分别陈述"）由这些测试执行，但测试的失败消息通常引用的是文档字符串而不是规则本身。
