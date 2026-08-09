# RetailOps v1 R1 Vertical Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved RetailOps v1 Scheme A as a CPU-only `build -> evaluate -> release -> serve` qualification slice with versioned domain contracts, deterministic policy verification, holdout governance, and auditable GO/NO-GO evidence.

**Architecture:** Add a focused `veritool_rl.retail_ops` package that owns the versioned bundle, qualification task generation, deterministic environment, governance, evidence, release, and service boundaries. Reuse the existing strict trajectory, runner, replay, metrics, and artifact primitives through backward-compatible extensions so MiniRetail and BFCL remain unchanged.

**Tech Stack:** Python 3.11, uv, Pydantic v2, PyYAML, NumPy, FastAPI, Uvicorn, pytest, Ruff, mypy.

## Global Constraints

- Product name remains **RetailAgentOps**; Python package remains `veritool_rl`.
- R1 uses 2 business tools, 6 task categories, and exactly 12 qualification tasks, 2 per category.
- R2 target quotas are train/dev/holdout `240/60/120`; R1 must not create those formal datasets or answers.
- R1 is CPU-only: no GPU, model download, commercial API, training, DPO, GRPO, or online RL.
- The fixed BFCL 200-task manifest, evaluator, failures, and answers remain read-only and must not be referenced by RetailOps configs or data paths.
- Correct denial is distinct from a policy violation; `policy_denied` is not an automatic success signal.
- Formal holdout truth and full release trajectories live under ignored `data/private/retail_ops/v1/`; public evidence must not expose `target_state`, `expected_calls`, prompts, or failure IDs.
- Every behavior change follows red-green TDD and preserves existing MiniRetail/BFCL tests.
- Use `uv`; do not install into system Python. Formal output directories must never be overwritten.
- Documentation, comments, reports, and user-visible errors default to Simplified Chinese.

---

## File Structure

| Path | Responsibility |
|---|---|
| `domains/retail_ops/v1/bundle.yaml` | Bundle identity, component references, category list, evaluator ID |
| `domains/retail_ops/v1/tools.yaml` | Exact JSON schemas for the two business tools and qualification distractor |
| `domains/retail_ops/v1/policies.yaml` | Refund reasons, policy rules, retry limit |
| `domains/retail_ops/v1/release.yaml` | Versioned release thresholds |
| `src/veritool_rl/retail_ops/bundle.py` | Strict bundle models, loading, canonical hashes |
| `src/veritool_rl/retail_ops/tasks.py` | Deterministic 12-task qualification fixture |
| `src/veritool_rl/retail_ops/environment.py` | RetailOps state transitions and policy verification |
| `src/veritool_rl/retail_ops/policies.py` | Qualification baseline and fault-injection policies |
| `src/veritool_rl/retail_ops/manifests.py` | Qualification manifest and non-overwrite build output |
| `src/veritool_rl/retail_ops/governance.py` | Split isolation, holdout receipt, access and tamper gates |
| `src/veritool_rl/retail_ops/evaluation.py` | RetailOps evaluation evidence and redaction |
| `src/veritool_rl/retail_ops/release.py` | Paired release gates and JSON/Markdown/HTML reports |
| `src/veritool_rl/retail_ops/service.py` | FastAPI app and GO/NO-GO deployment selection |
| `src/veritool_rl/product_cli.py` | Stable `build/evaluate/release/serve` command surface |

### Task 1: Versioned RetailOps Bundle

**Files:**
- Create: `domains/retail_ops/v1/bundle.yaml`
- Create: `domains/retail_ops/v1/tools.yaml`
- Create: `domains/retail_ops/v1/policies.yaml`
- Create: `domains/retail_ops/v1/release.yaml`
- Create: `src/veritool_rl/retail_ops/__init__.py`
- Create: `src/veritool_rl/retail_ops/bundle.py`
- Test: `tests/test_retail_ops_bundle.py`

**Interfaces:**
- Consumes: `StrictModel`, `ToolSchema`, `canonical_json`, `sha256_file`.
- Produces: `LoadedRetailOpsBundle`, `RetailOpsPolicies`, `ReleasePolicyConfig`, `load_bundle(bundle_dir: Path) -> LoadedRetailOpsBundle`.

- [ ] **Step 1: Write failing strict-load and tamper tests**

```python
from pathlib import Path

import pytest


def test_load_bundle_pins_versions_tools_and_hashes() -> None:
    from veritool_rl.retail_ops.bundle import load_bundle

    loaded = load_bundle(Path("domains/retail_ops/v1"))

    assert loaded.bundle.bundle_id == "retail_ops"
    assert loaded.bundle.bundle_version == "1.0.0"
    assert [tool.name for tool in loaded.tools] == [
        "get_order",
        "refund_order",
        "get_store_hours",
    ]
    assert loaded.policies.max_transient_retries == 1
    assert len(loaded.bundle_sha256) == 64
    assert set(loaded.component_sha256) == {
        "bundle.yaml",
        "tools.yaml",
        "policies.yaml",
        "release.yaml",
    }


def test_bundle_rejects_unknown_fields(tmp_path: Path) -> None:
    from veritool_rl.retail_ops.bundle import load_bundle

    source = Path("domains/retail_ops/v1")
    target = tmp_path / "v1"
    target.mkdir()
    for name in ("tools.yaml", "policies.yaml", "release.yaml"):
        (target / name).write_bytes((source / name).read_bytes())
    (target / "bundle.yaml").write_text(
        (source / "bundle.yaml").read_text(encoding="utf-8") + "unknown: true\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown"):
        load_bundle(target)
```

- [ ] **Step 2: Run the tests and confirm missing-module failure**

Run: `.venv/bin/pytest tests/test_retail_ops_bundle.py -q`

Expected: FAIL during import with `ModuleNotFoundError: No module named 'veritool_rl.retail_ops'`.

- [ ] **Step 3: Add the exact versioned YAML contract**

`bundle.yaml`:

```yaml
schema_version: "1.0"
bundle_id: retail_ops
bundle_version: "1.0.0"
tools_file: tools.yaml
policies_file: policies.yaml
release_file: release.yaml
evaluator_id: retail_ops_v1
task_categories:
  - lookup_status
  - refund_eligible
  - refund_denied_window
  - refund_denied_ownership
  - refund_denied_duplicate
  - refund_recovery
```

`policies.yaml`:

```yaml
schema_version: "1.0"
policy_version: "1.0.0"
refund_reasons:
  - damaged
  - wrong_item
  - not_as_described
  - changed_mind
max_transient_retries: 1
rules:
  - refund_requires_lookup
  - customer_must_own_order
  - refund_window_must_be_open
  - duplicate_refund_forbidden
  - transient_retry_is_bounded
  - tool_schema_is_strict
```

`tools.yaml`:

```yaml
schema_version: "1.0"
tools:
  - name: get_order
    description: 查询订单详情与当前状态。
    parameters:
      type: object
      properties:
        order_id:
          type: string
          description: 订单号
      required:
        - order_id
      additionalProperties: false
  - name: refund_order
    description: 为符合政策的订单办理退款；调用前必须先查询订单。
    parameters:
      type: object
      properties:
        order_id:
          type: string
          description: 订单号
        reason:
          type: string
          enum:
            - damaged
            - wrong_item
            - not_as_described
            - changed_mind
          description: 退款原因
      required:
        - order_id
        - reason
      additionalProperties: false
  - name: get_store_hours
    description: 查询指定城市门店营业时间，与订单操作无关。
    parameters:
      type: object
      properties:
        city:
          type: string
      required:
        - city
      additionalProperties: false
```

`release.yaml`:

```yaml
schema_version: "1.0"
policy_version: "1.0.0"
success_delta_min: 0.05
critical_policy_violation_delta_max: 0
invalid_call_count_max: 0
p95_latency_ratio_max: 1.25
require_complete_evidence: true
```

The loader must verify that `reason.enum` matches `refund_reasons` exactly.

- [ ] **Step 4: Implement strict models and canonical bundle hashing**

```python
class RetailOpsBundle(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    bundle_id: Literal["retail_ops"] = "retail_ops"
    bundle_version: Literal["1.0.0"] = "1.0.0"
    tools_file: str
    policies_file: str
    release_file: str
    evaluator_id: Literal["retail_ops_v1"] = "retail_ops_v1"
    task_categories: list[str]


class ToolsDocument(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    tools: list[ToolSchema]


class RetailOpsPolicies(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    policy_version: Literal["1.0.0"] = "1.0.0"
    refund_reasons: list[str]
    max_transient_retries: Literal[1] = 1
    rules: list[str]


class ReleasePolicyConfig(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    policy_version: Literal["1.0.0"] = "1.0.0"
    success_delta_min: float = Field(ge=0.0, le=1.0)
    critical_policy_violation_delta_max: int = Field(ge=0)
    invalid_call_count_max: Literal[0] = 0
    p95_latency_ratio_max: float = Field(ge=1.0)
    require_complete_evidence: Literal[True] = True


@dataclass(frozen=True)
class LoadedRetailOpsBundle:
    bundle: RetailOpsBundle
    tools: tuple[ToolSchema, ...]
    policies: RetailOpsPolicies
    release: ReleasePolicyConfig
    bundle_sha256: str
    component_sha256: dict[str, str]


def _read_yaml(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"YAML 顶层必须是 mapping: {path}")
    return cast(dict[str, Any], loaded)


def load_bundle(bundle_dir: Path) -> LoadedRetailOpsBundle:
    bundle = RetailOpsBundle.model_validate(_read_yaml(bundle_dir / "bundle.yaml"))
    tool_document = ToolsDocument.model_validate(
        _read_yaml(bundle_dir / bundle.tools_file)
    )
    tools = tuple(tool_document.tools)
    policies = RetailOpsPolicies.model_validate(
        _read_yaml(bundle_dir / bundle.policies_file)
    )
    release = ReleasePolicyConfig.model_validate(
        _read_yaml(bundle_dir / bundle.release_file)
    )
    if tuple(bundle.task_categories) != (
        "lookup_status",
        "refund_eligible",
        "refund_denied_window",
        "refund_denied_ownership",
        "refund_denied_duplicate",
        "refund_recovery",
    ) or tuple(tool.name for tool in tools) != (
        "get_order",
        "refund_order",
        "get_store_hours",
    ):
        raise ValueError("RetailOps v1 工具集合或顺序不符合冻结契约")
    component_hashes = {
        name: sha256_file(bundle_dir / name)
        for name in (
            "bundle.yaml",
            bundle.tools_file,
            bundle.policies_file,
            bundle.release_file,
        )
    }
    bundle_hash = hashlib.sha256(
        canonical_json(component_hashes).encode("utf-8")
    ).hexdigest()
    return LoadedRetailOpsBundle(
        bundle=bundle,
        tools=tools,
        policies=policies,
        release=release,
        bundle_sha256=bundle_hash,
        component_sha256=component_hashes,
    )
```

- [ ] **Step 5: Run focused and regression tests**

Run: `.venv/bin/pytest tests/test_retail_ops_bundle.py tests/test_mini_retail_env.py -q`

Expected: all selected tests PASS.

- [ ] **Step 6: Commit the bundle unit**

```bash
git add domains/retail_ops/v1 src/veritool_rl/retail_ops tests/test_retail_ops_bundle.py
git commit -m "feat: add versioned RetailOps v1 bundle"
```

### Task 2: Task Schema and Policy-Aware Environment

**Files:**
- Modify: `src/veritool_rl/trajectory/schema.py:43-119`
- Modify: `src/veritool_rl/envs/base.py:39-76`
- Modify: `src/veritool_rl/agent/runner.py:29-111`
- Create: `src/veritool_rl/retail_ops/tasks.py`
- Create: `src/veritool_rl/retail_ops/environment.py`
- Test: `tests/test_retail_ops_environment.py`
- Test: `tests/test_trajectory_schema.py`

**Interfaces:**
- Consumes: `LoadedRetailOpsBundle`, `TaskSpec`, `ToolEnv`, `Observation`, `ToolCall`.
- Produces: `ExpectedDecision`, three new denial `TaskScenario` values plus the frozen six-category qualification set, `build_qualification_tasks(seed: int) -> list[TaskSpec]`, `RetailOpsEnv(task: TaskSpec, bundle: LoadedRetailOpsBundle)`.

- [ ] **Step 1: Write failing schema, balance, denial, and retry tests**

```python
from pathlib import Path


def test_qualification_tasks_are_deterministic_balanced_and_disjoint() -> None:
    from collections import Counter

    from veritool_rl.retail_ops.tasks import build_qualification_tasks

    first = build_qualification_tasks(seed=0)
    second = build_qualification_tasks(seed=0)

    assert first == second
    assert len(first) == 12
    assert set(Counter(task.scenario for task in first).values()) == {2}
    assert len({task.task_id for task in first}) == 12
    assert len({task.metadata["family_id"] for task in first}) == 12


def test_correct_window_denial_requires_read_and_final_response() -> None:
    from veritool_rl.retail_ops.bundle import load_bundle
    from veritool_rl.retail_ops.environment import RetailOpsEnv
    from veritool_rl.retail_ops.tasks import build_qualification_tasks
    from veritool_rl.trajectory import TaskScenario

    bundle = load_bundle(Path("domains/retail_ops/v1"))
    task = next(
        task
        for task in build_qualification_tasks(seed=0)
        if task.scenario is TaskScenario.REFUND_DENIED_WINDOW
    )
    env = RetailOpsEnv(task, bundle)

    env.execute_tool("get_order", {"order_id": task.metadata["order_id"]})
    assert env.verify_final_state() == 0.0
    env.record_final_response("该订单已超过退款期限，无法退款。")

    assert env.verify_final_state() == 1.0
    assert env.check_policy() == []


def test_attempted_forbidden_refund_is_policy_violation() -> None:
    from veritool_rl.retail_ops.bundle import load_bundle
    from veritool_rl.retail_ops.environment import RetailOpsEnv
    from veritool_rl.retail_ops.tasks import build_qualification_tasks
    from veritool_rl.trajectory import TaskScenario

    bundle = load_bundle(Path("domains/retail_ops/v1"))
    task = next(
        task
        for task in build_qualification_tasks(seed=0)
        if task.scenario is TaskScenario.REFUND_DENIED_WINDOW
    )
    env = RetailOpsEnv(task, bundle)
    env.execute_tool("get_order", {"order_id": task.metadata["order_id"]})
    result = env.execute_tool(
        "refund_order",
        {"order_id": task.metadata["order_id"], "reason": task.metadata["reason"]},
    )

    assert result.error_code == "policy_denied"
    assert env.verify_final_state() == 0.0
    assert env.check_policy() == ["refund_not_eligible"]


def test_recovery_allows_exactly_one_transient_retry() -> None:
    from veritool_rl.retail_ops.bundle import load_bundle
    from veritool_rl.retail_ops.environment import RetailOpsEnv
    from veritool_rl.retail_ops.tasks import build_qualification_tasks
    from veritool_rl.trajectory import TaskScenario

    bundle = load_bundle(Path("domains/retail_ops/v1"))
    task = next(
        task
        for task in build_qualification_tasks(seed=0)
        if task.scenario is TaskScenario.REFUND_RECOVERY
    )
    env = RetailOpsEnv(task, bundle)
    arguments = {
        "order_id": task.metadata["order_id"],
        "reason": task.metadata["reason"],
    }
    env.execute_tool("get_order", {"order_id": task.metadata["order_id"]})
    first = env.execute_tool("refund_order", arguments)
    second = env.execute_tool("refund_order", arguments)

    assert first.error_code == "transient_error"
    assert second.ok is True
    assert env.verify_final_state() == 1.0
    assert env.check_policy() == []
```

- [ ] **Step 2: Run focused tests and confirm missing types/modules**

Run: `.venv/bin/pytest tests/test_retail_ops_environment.py tests/test_trajectory_schema.py -q`

Expected: FAIL because the new scenarios, fields, task builder, and environment do not exist.

- [ ] **Step 3: Extend `TaskSpec` without breaking old trajectories**

```python
class ExpectedDecision(StrEnum):
    INFORM = "inform"
    ALLOW = "allow"
    DENY = "deny"


class TaskSpec(StrictModel):
    task_id: str = Field(min_length=1)
    split: Literal["train", "dev", "test", "qualification", "holdout"]
    scenario: TaskScenario
    user_request: str = Field(min_length=1)
    initial_state: dict[str, Any]
    target_state: dict[str, Any]
    expected_calls: list[ToolCall] = Field(default_factory=list)
    expected_decision: ExpectedDecision | None = None
    required_reads: list[str] = Field(default_factory=list)
    transient_failures: dict[str, int] = Field(default_factory=dict)
    max_steps: int = Field(default=4, ge=1, le=32)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

Add `REFUND_DENIED_WINDOW`, `REFUND_DENIED_OWNERSHIP`, and
`REFUND_DENIED_DUPLICATE` without removing legacy `REFUND_DENIED`. Export
`ExpectedDecision` from `src/veritool_rl/trajectory/__init__.py`.

- [ ] **Step 4: Add terminal-response notification as a backward-compatible hook**

```python
class ToolEnv(ABC):
    def record_final_response(self, response: str) -> None:
        del response
```

In `run_episode`, call `env.record_final_response(output.final_response)` before computing
the reward whenever `final_response` is not `None`. Existing environments inherit the no-op
implementation.

- [ ] **Step 5: Implement the exact 12 tasks and environment transitions**

Use two tasks per category, opaque IDs derived from
`sha256(f"retail_ops_v1:{seed}:{index}")`, and a unique `family_id` per qualification task.
The environment must implement these transitions:

```python
def verify_final_state(self) -> float:
    reads_complete = set(self._task.required_reads) <= self._reads
    state_matches = self._state == self._task.target_state
    clean = not self._violations
    if self._task.expected_decision in {
        ExpectedDecision.INFORM,
        ExpectedDecision.DENY,
    }:
        return float(reads_complete and self._terminal_response and state_matches and clean)
    return float(reads_complete and state_matches and clean and self._refund_applied)
```

`get_order` marks the read before returning; a cross-customer order returns a generic
`not_found` observation without customer data. `refund_order` validates exact arguments,
lookup, ownership, deadline, duplicate state, reason allowlist, and one transient failure in
that order. A prohibited refund appends one stable violation code and never changes state.

- [ ] **Step 6: Run environment and all legacy trajectory tests**

Run: `.venv/bin/pytest tests/test_retail_ops_environment.py tests/test_trajectory_schema.py tests/test_agent_runner.py tests/test_mini_retail_env.py tests/test_replay.py -q`

Expected: all selected tests PASS; legacy 128/32/32 MiniRetail behavior remains unchanged.

- [ ] **Step 7: Commit the environment unit**

```bash
git add src/veritool_rl/trajectory src/veritool_rl/envs/base.py src/veritool_rl/agent/runner.py src/veritool_rl/retail_ops/tasks.py src/veritool_rl/retail_ops/environment.py tests/test_retail_ops_environment.py tests/test_trajectory_schema.py
git commit -m "feat: add RetailOps policy-aware environment"
```

### Task 3: Qualification Policies and Oracle Regression

**Files:**
- Modify: `src/veritool_rl/agent/policy.py:39-68`
- Create: `src/veritool_rl/retail_ops/policies.py`
- Test: `tests/test_retail_ops_policies.py`
- Test: `tests/test_agent_runner.py`

**Interfaces:**
- Consumes: `TaskSpec`, `PolicyOutput`, `ToolSchema`, `ToolCall`.
- Produces: `QualificationBaselinePolicy(task)`, `UnknownToolPolicy`, `build_qualification_policy(policy_type: str, task: TaskSpec) -> Policy`.

- [ ] **Step 1: Write failing 12-task policy outcome tests**

```python
from veritool_rl.trajectory import Trajectory


def _run_policy(policy_type: str) -> list[Trajectory]:
    from pathlib import Path

    from veritool_rl.agent.runner import run_episode
    from veritool_rl.retail_ops.bundle import load_bundle
    from veritool_rl.retail_ops.environment import RetailOpsEnv
    from veritool_rl.retail_ops.policies import build_qualification_policy
    from veritool_rl.retail_ops.tasks import build_qualification_tasks

    bundle = load_bundle(Path("domains/retail_ops/v1"))
    tasks = build_qualification_tasks(seed=0)
    return [
        run_episode(
            task,
            lambda current: RetailOpsEnv(current, bundle),
            build_qualification_policy(policy_type, task),
            seed=0,
        )
        for task in tasks
    ]


def test_qualification_oracle_completes_all_twelve_tasks() -> None:
    trajectories = _run_policy("oracle")
    assert len(trajectories) == 12
    assert all(trajectory.success for trajectory in trajectories)


def test_baseline_only_completes_read_or_deny_tasks() -> None:
    trajectories = _run_policy("baseline")
    assert sum(trajectory.success for trajectory in trajectories) == 8
    assert all(not trajectory.violations for trajectory in trajectories)


def test_fault_policy_produces_invalid_calls_without_batch_crash() -> None:
    trajectories = _run_policy("unknown_tool")
    assert not any(trajectory.success for trajectory in trajectories)
    assert all(
        any(
            step.observation is not None
            and step.observation.error_code == "unknown_tool"
            for step in trajectory.steps
        )
        for trajectory in trajectories
    )
```

- [ ] **Step 2: Run tests and confirm missing-policy failure**

Run: `.venv/bin/pytest tests/test_retail_ops_policies.py tests/test_agent_runner.py -q`

Expected: FAIL importing `veritool_rl.retail_ops.policies`.

- [ ] **Step 3: Implement deterministic qualification policies**

`QualificationBaselinePolicy` executes only the task's first `get_order` call and then returns
a final response; therefore it succeeds on lookup and the three safe-denial categories but not
on eligible/recovery refunds. `UnknownToolPolicy` always emits:

```python
PolicyOutput(
    raw_text='<tool_call>{"name":"delete_order","arguments":{}}</tool_call>',
    tool_call=ToolCall(name="delete_order", arguments={}),
)
```

`build_qualification_policy` accepts exactly `oracle`, `baseline`, and `unknown_tool`; any
other value raises `ValueError(f"未知 qualification policy: {policy_type}")`.

- [ ] **Step 4: Preserve `OraclePolicy`'s legacy expected-call behavior**

Do not make `OraclePolicy` inspect target state or hidden holdout truth. RetailOps denial tasks
encode only the required `get_order` call in `expected_calls`; after it is exhausted, the
existing final-response behavior completes the denial through `record_final_response`.

- [ ] **Step 5: Run policy, runner, and data-pipeline regressions**

Run: `.venv/bin/pytest tests/test_retail_ops_policies.py tests/test_agent_runner.py tests/test_data_pipeline.py -q`

Expected: all selected tests PASS.

- [ ] **Step 6: Commit the policy unit**

```bash
git add src/veritool_rl/agent/policy.py src/veritool_rl/retail_ops/policies.py tests/test_retail_ops_policies.py tests/test_agent_runner.py
git commit -m "feat: add RetailOps qualification policies"
```

### Task 4: Qualification Build and Immutable Manifest

**Files:**
- Modify: `src/veritool_rl/artifacts.py:14-50`
- Modify: `src/veritool_rl/trajectory/schema.py:93-119`
- Create: `src/veritool_rl/retail_ops/manifests.py`
- Test: `tests/test_retail_ops_manifest.py`
- Test: `tests/test_trajectory_schema.py`

**Interfaces:**
- Consumes: `LoadedRetailOpsBundle`, `build_qualification_tasks`, canonical JSON writers.
- Produces: `TaskManifest`, `build_qualification(bundle_dir: Path, seed: int, output_dir: Path) -> TaskManifest`, `load_task_manifest(path: Path) -> TaskManifest`, `load_built_tasks(build_dir: Path) -> dict[str, TaskSpec]`.

- [ ] **Step 1: Write failing determinism and non-overwrite tests**

```python
def test_build_writes_stable_qualification_manifest(tmp_path: Path) -> None:
    from veritool_rl.retail_ops.manifests import build_qualification

    manifest = build_qualification(
        Path("domains/retail_ops/v1"), seed=0, output_dir=tmp_path / "run"
    )

    assert manifest.split == "qualification"
    assert manifest.task_count == 12
    assert set(manifest.category_counts.values()) == {2}
    assert len(manifest.task_sha256) == 12
    assert (tmp_path / "run/tasks.jsonl").is_file()
    assert (tmp_path / "run/manifest.json").is_file()


def test_build_rejects_existing_output_directory(tmp_path: Path) -> None:
    from veritool_rl.retail_ops.manifests import build_qualification

    output = tmp_path / "run"
    output.mkdir()
    with pytest.raises(FileExistsError, match="输出目录已存在"):
        build_qualification(Path("domains/retail_ops/v1"), 0, output)


def test_task_spec_jsonl_round_trip() -> None:
    from veritool_rl.retail_ops.tasks import build_qualification_tasks
    from veritool_rl.trajectory import TaskSpec

    task = build_qualification_tasks(seed=0)[0]
    assert TaskSpec.from_jsonl(task.to_jsonl()) == task
```

- [ ] **Step 2: Run tests and confirm missing-manifest failure**

Run: `.venv/bin/pytest tests/test_retail_ops_manifest.py -q`

Expected: FAIL importing `veritool_rl.retail_ops.manifests`.

- [ ] **Step 3: Add a reusable non-overwrite artifact guard**

```python
def create_output_dir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        msg = f"输出目录已存在，拒绝覆盖: {path}"
        raise FileExistsError(msg) from None
```

- [ ] **Step 4: Implement the manifest schema and build output**

```python
class TaskManifest(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    bundle_id: Literal["retail_ops"] = "retail_ops"
    bundle_version: Literal["1.0.0"] = "1.0.0"
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    split: Literal["train", "dev", "qualification", "holdout"]
    seed: int
    task_count: int = Field(ge=1)
    category_counts: dict[str, int]
    task_ids: list[str]
    family_ids: list[str]
    task_sha256: dict[str, str]
    tasks_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
```

`build_qualification` loads the approved bundle, creates the 12 tasks, writes canonical
`tasks.jsonl`, computes per-task and file hashes, validates counts/order/uniqueness, then writes
`manifest.json`. It must not write SFT data, formal train/dev data, or a holdout receipt.

```python
def load_built_tasks(build_dir: Path) -> dict[str, TaskSpec]:
    manifest = load_task_manifest(build_dir / "manifest.json")
    tasks_path = build_dir / "tasks.jsonl"
    if sha256_file(tasks_path) != manifest.tasks_file_sha256:
        raise ValueError("tasks.jsonl 与 manifest SHA-256 不匹配")
    tasks = [
        TaskSpec.from_jsonl(line)
        for line in tasks_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    indexed = {task.task_id: task for task in tasks}
    if list(indexed) != manifest.task_ids or len(indexed) != manifest.task_count:
        raise ValueError("tasks.jsonl 的任务集合或顺序与 manifest 不一致")
    for task_id, task in indexed.items():
        digest = hashlib.sha256(
            canonical_json(task.model_dump(mode="json")).encode("utf-8")
        ).hexdigest()
        if digest != manifest.task_sha256[task_id]:
            raise ValueError(f"任务内容 SHA-256 不匹配: {task_id}")
    return indexed
```

Because `TaskSpec` currently exposes `from_jsonl` only through `Trajectory`, add
`TaskSpec.to_jsonl()` and `TaskSpec.from_jsonl()` using the same canonical JSON rules as
`Trajectory`; cover their strict round trip in `tests/test_trajectory_schema.py`.

- [ ] **Step 5: Run focused and artifact tests**

Run: `.venv/bin/pytest tests/test_retail_ops_manifest.py tests/test_trajectory_schema.py tests/test_data_pipeline.py -q`

Expected: all selected tests PASS.

- [ ] **Step 6: Commit the manifest unit**

```bash
git add src/veritool_rl/artifacts.py src/veritool_rl/trajectory/schema.py src/veritool_rl/retail_ops/manifests.py tests/test_retail_ops_manifest.py tests/test_trajectory_schema.py
git commit -m "feat: add immutable RetailOps qualification manifest"
```

### Task 5: Holdout Governance and Sealed Access Gates

**Files:**
- Create: `src/veritool_rl/retail_ops/governance.py`
- Modify: `tests/test_config_paths.py:42-113`
- Test: `tests/test_retail_ops_holdout.py`

**Interfaces:**
- Consumes: `TaskManifest`, `sha256_file`, `validate_project_relative_path`.
- Produces: `HoldoutReceipt`, `EvidencePurpose`, `assert_split_isolation(manifests: Sequence[TaskManifest]) -> None`, `authorize_holdout(receipt: HoldoutReceipt, artifact_path: Path, logical_path: Path, purpose: EvidencePurpose) -> None`.

- [ ] **Step 1: Write failing leakage, tamper, and ignore tests**

```python
import subprocess
from pathlib import Path
from typing import Literal

import pytest

from veritool_rl.artifacts import sha256_file
from veritool_rl.retail_ops.governance import (
    EvidencePurpose,
    HoldoutReceipt,
    assert_split_isolation,
    authorize_holdout,
)
from veritool_rl.retail_ops.manifests import TaskManifest

ROOT = Path(__file__).parents[1]


def _manifest(
    split: Literal["train", "dev", "qualification", "holdout"],
    task_id: str,
    family_id: str,
    content_hash: str,
) -> TaskManifest:
    return TaskManifest(
        bundle_sha256="c" * 64,
        split=split,
        seed=0,
        task_count=1,
        category_counts={"lookup_status": 1},
        task_ids=[task_id],
        family_ids=[family_id],
        task_sha256={task_id: content_hash},
        tasks_file_sha256="d" * 64,
    )


def test_split_isolation_rejects_shared_family() -> None:
    train = _manifest("train", task_id="T1", family_id="F1", content_hash="a" * 64)
    holdout = _manifest("holdout", task_id="H1", family_id="F1", content_hash="b" * 64)

    with pytest.raises(ValueError, match="family_id 交叉"):
        assert_split_isolation([train, holdout])


@pytest.mark.parametrize("purpose", [EvidencePurpose.BUILD, EvidencePurpose.DEVELOP])
def test_non_release_purpose_cannot_open_holdout(
    tmp_path: Path,
    purpose: EvidencePurpose,
) -> None:
    artifact = tmp_path / "tasks.jsonl"
    artifact.write_text("{}\n", encoding="utf-8")
    receipt = HoldoutReceipt(
        bundle_sha256="c" * 64,
        task_count=1,
        category_counts={"lookup_status": 1},
        task_ids=["H1"],
        family_ids=["HF1"],
        task_sha256={"H1": "d" * 64},
        artifact_sha256=sha256_file(artifact),
    )
    with pytest.raises(PermissionError, match="只允许 release"):
        authorize_holdout(
            receipt,
            artifact,
            Path("data/private/retail_ops/v1/holdout/tasks.jsonl"),
            purpose,
        )


def test_release_rejects_tampered_holdout(tmp_path: Path) -> None:
    artifact = tmp_path / "tasks.jsonl"
    artifact.write_text("tampered\n", encoding="utf-8")
    receipt = HoldoutReceipt(
        bundle_sha256="c" * 64,
        task_count=1,
        category_counts={"lookup_status": 1},
        task_ids=["H1"],
        family_ids=["HF1"],
        task_sha256={"H1": "d" * 64},
        artifact_sha256="0" * 64,
    )
    with pytest.raises(ValueError, match="artifact SHA-256 不匹配"):
        authorize_holdout(
            receipt,
            artifact,
            Path("data/private/retail_ops/v1/holdout/tasks.jsonl"),
            EvidencePurpose.RELEASE,
        )


def test_git_ignores_retail_ops_private_holdout() -> None:
    result = subprocess.run(
        ["git", "check-ignore", "-q", "data/private/retail_ops/v1/holdout/tasks.jsonl"],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0
```

- [ ] **Step 2: Run tests and confirm missing-governance failure**

Run: `.venv/bin/pytest tests/test_retail_ops_holdout.py tests/test_config_paths.py -q`

Expected: FAIL importing `veritool_rl.retail_ops.governance`.

- [ ] **Step 3: Implement strict public receipt and isolation checks**

```python
class HoldoutReceipt(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluator_id: Literal["retail_ops_v1"] = "retail_ops_v1"
    split: Literal["holdout"] = "holdout"
    task_count: int = Field(ge=1)
    category_counts: dict[str, int]
    task_ids: list[str]
    family_ids: list[str]
    task_sha256: dict[str, str]
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvidencePurpose(StrEnum):
    BUILD = "build"
    DEVELOP = "develop"
    RELEASE = "release"
```

`assert_split_isolation` rejects duplicate `task_id`, `family_id`, or content hash across any
pair of manifests. `authorize_holdout` requires `purpose is RELEASE`, a project-relative
`logical_path` under `data/private/retail_ops/v1/`, and exact physical artifact SHA-256 equality
with the receipt.

- [ ] **Step 4: Add synthetic tamper fixtures without creating formal holdout data**

Tests may create temporary `HoldoutReceipt` and artifact files under `tmp_path`; no file under
`data/private/retail_ops/v1/` is created or committed in R1. The path-prefix check receives a
project-relative logical path separately from the temporary physical fixture.

- [ ] **Step 5: Run governance and BFCL provenance regressions**

Run: `.venv/bin/pytest tests/test_retail_ops_holdout.py tests/test_config_paths.py tests/test_bfcl_compare.py -q`

Expected: all selected tests PASS.

- [ ] **Step 6: Commit the governance unit**

```bash
git add src/veritool_rl/retail_ops/governance.py tests/test_retail_ops_holdout.py tests/test_config_paths.py
git commit -m "feat: enforce RetailOps holdout isolation"
```

### Task 6: Evaluation Evidence, Metrics, and Redaction

**Files:**
- Modify: `src/veritool_rl/eval/metrics.py:16-192`
- Create: `src/veritool_rl/retail_ops/evaluation.py`
- Test: `tests/test_retail_ops_evaluation.py`
- Test: `tests/test_metrics.py`

**Interfaces:**
- Consumes: `TaskManifest`, `LoadedRetailOpsBundle`, `PolicyFactory`, `run_episode`, `replay_trajectory`, `compute_metrics`.
- Produces: `EvaluationMode`, `RunEvidence`, `evaluate_retail_ops(bundle_dir: Path, build_dir: Path, policy_type: str, config: dict[str, Any], seed: int, output_dir: Path, mode: EvaluationMode) -> RunEvidence`, `load_run_evidence(path: Path) -> RunEvidence`, `redact_failure_rows(trajectories: Sequence[Trajectory]) -> list[dict[str, Any]]`.

- [ ] **Step 1: Write failing evidence, percentile, and redaction tests**

```python
from pathlib import Path

import pytest

from veritool_rl.eval.metrics import compute_metrics
from veritool_rl.retail_ops.evaluation import RunEvidence
from veritool_rl.trajectory import Trajectory


def _latency_trajectories(values: list[float]) -> list[Trajectory]:
    from typing import Any

    from veritool_rl.agent.policy import PolicyOutput
    from veritool_rl.agent.runner import run_episode
    from veritool_rl.envs.mini_retail import MiniRetailEnv, build_mvp_task_splits

    class TimedFinalPolicy:
        name = "timed-final"

        def __init__(self, latency_ms: float) -> None:
            self._latency_ms = latency_ms

        def respond(self, messages: list[dict[str, Any]], tools: list[Any]) -> PolicyOutput:
            del messages, tools
            return PolicyOutput(
                raw_text="无法处理",
                final_response="无法处理",
                latency_ms=self._latency_ms,
            )

    tasks = build_mvp_task_splits(seed=0)["test"][: len(values)]
    return [
        run_episode(task, MiniRetailEnv, TimedFinalPolicy(value), seed=0)
        for task, value in zip(tasks, values, strict=True)
    ]


def _evaluate(tmp_path: Path, policy_type: str) -> RunEvidence:
    from veritool_rl.retail_ops.evaluation import EvaluationMode, evaluate_retail_ops
    from veritool_rl.retail_ops.manifests import build_qualification

    build_dir = tmp_path / "build"
    build_qualification(Path("domains/retail_ops/v1"), 0, build_dir)
    return evaluate_retail_ops(
        bundle_dir=Path("domains/retail_ops/v1"),
        build_dir=build_dir,
        policy_type=policy_type,
        config={
            "bootstrap_samples": 1000,
            "parser_id": "hermes-single-call-v1",
            "budget": {"max_steps": 5},
        },
        seed=0,
        output_dir=tmp_path / policy_type,
        mode=EvaluationMode.QUALIFICATION,
    )


def test_metrics_report_episode_latency_percentiles() -> None:
    metrics = compute_metrics(_latency_trajectories([10.0, 20.0, 40.0]), 20, 0)
    assert metrics["p50_latency_ms"] == 20.0
    assert metrics["p95_latency_ms"] == pytest.approx(38.0)


def test_qualification_evidence_is_complete_and_replayable(tmp_path: Path) -> None:
    evidence = _evaluate(tmp_path, policy_type="oracle")
    assert evidence.task_count == 12
    assert evidence.evidence_complete is True
    assert evidence.metrics["task_success"] == 1.0
    assert (tmp_path / "oracle/trajectories.jsonl").is_file()


def test_redacted_failures_exclude_truth_fields() -> None:
    from veritool_rl.agent.runner import run_episode
    from veritool_rl.artifacts import canonical_json
    from veritool_rl.retail_ops.bundle import load_bundle
    from veritool_rl.retail_ops.environment import RetailOpsEnv
    from veritool_rl.retail_ops.evaluation import redact_failure_rows
    from veritool_rl.retail_ops.policies import UnknownToolPolicy
    from veritool_rl.retail_ops.tasks import build_qualification_tasks

    bundle = load_bundle(Path("domains/retail_ops/v1"))
    task = build_qualification_tasks(seed=0)[0]
    trajectory = run_episode(
        task,
        lambda current: RetailOpsEnv(current, bundle),
        UnknownToolPolicy(),
        seed=0,
    )
    public_text = canonical_json(redact_failure_rows([trajectory]))
    for forbidden in ("target_state", "expected_calls", "user_request", "task_id"):
        assert forbidden not in public_text
```

- [ ] **Step 2: Run tests and confirm missing evidence/metric keys**

Run: `.venv/bin/pytest tests/test_retail_ops_evaluation.py tests/test_metrics.py -q`

Expected: FAIL because `evaluation.py`, `p50_latency_ms`, and `p95_latency_ms` do not exist.

- [ ] **Step 3: Add deterministic episode latency percentiles**

```python
episode_latency = np.asarray(
    [sum(step.latency_ms for step in trajectory.steps) for trajectory in trajectories],
    dtype=np.float64,
)
metrics["p50_latency_ms"] = float(np.quantile(episode_latency, 0.50))
metrics["p95_latency_ms"] = float(np.quantile(episode_latency, 0.95))
```

The empty metric values are both `0.0`; retain `average_latency_ms` for backward compatibility.

- [ ] **Step 4: Implement run evidence and mode-aware outputs**

```python
class EvaluationMode(StrEnum):
    QUALIFICATION = "qualification"
    DEVELOPMENT = "development"


class RunEvidence(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    mode: EvaluationMode
    policy_type: str
    bundle_sha256: str
    task_manifest_sha256: str
    evaluator_id: Literal["retail_ops_v1"] = "retail_ops_v1"
    seed: int
    parser_id: str
    budget: dict[str, Any]
    task_count: int
    metrics: dict[str, Any]
    evidence_complete: bool
    artifact_sha256: dict[str, str]
```

`evaluate_retail_ops` validates the manifest and bundle hashes, rejects holdout manifests,
runs/replays every task, writes canonical config, metrics, failures, `run.json`, and log, then
hashes required files. Qualification/development evidence may contain full trajectories.
`redact_failure_rows` is the tested R1 boundary that R2 must use when wiring the authorized
sealed holdout evaluator; R1 does not open or generate a formal holdout artifact.

- [ ] **Step 5: Run evaluation, metrics, replay, and reporting regressions**

Run: `.venv/bin/pytest tests/test_retail_ops_evaluation.py tests/test_metrics.py tests/test_replay.py tests/test_aggregate_report.py -q`

Expected: all selected tests PASS.

- [ ] **Step 6: Commit the evaluation unit**

```bash
git add src/veritool_rl/eval/metrics.py src/veritool_rl/retail_ops/evaluation.py tests/test_retail_ops_evaluation.py tests/test_metrics.py
git commit -m "feat: add redacted RetailOps evaluation evidence"
```

### Task 7: Release Gates and Deterministic Reports

**Files:**
- Create: `src/veritool_rl/retail_ops/release.py`
- Test: `tests/test_release_policy.py`

**Interfaces:**
- Consumes: two `RunEvidence` files and `ReleasePolicyConfig`.
- Produces: `ReleaseDecision`, `GateResult`, `ReleaseReport`, `decide_release(baseline: RunEvidence, candidate: RunEvidence, policy: ReleasePolicyConfig) -> ReleaseReport`, `write_release_report(report: ReleaseReport, output_dir: Path) -> None`, `load_release_report(path: Path) -> ReleaseReport`.

- [ ] **Step 1: Write failing GO, NO-GO, and fairness tests**

```python
import pytest

from veritool_rl.retail_ops.bundle import ReleasePolicyConfig
from veritool_rl.retail_ops.evaluation import EvaluationMode, RunEvidence
from veritool_rl.retail_ops.release import ReleaseDecision, decide_release


def _evidence(
    run_id: str,
    policy_type: str,
    task_success: float,
    invalid_calls: int,
    manifest_hash: str = "a" * 64,
) -> RunEvidence:
    return RunEvidence(
        run_id=run_id,
        mode=EvaluationMode.QUALIFICATION,
        policy_type=policy_type,
        bundle_sha256="b" * 64,
        task_manifest_sha256=manifest_hash,
        seed=0,
        parser_id="hermes-single-call-v1",
        budget={"max_steps": 5},
        task_count=12,
        metrics={
            "task_success": task_success,
            "policy_violation_count": 0,
            "invalid_call_count": invalid_calls,
            "p95_latency_ms": 10.0,
        },
        evidence_complete=True,
        artifact_sha256={"metrics.json": "c" * 64},
    )


def _release_policy() -> ReleasePolicyConfig:
    return ReleasePolicyConfig(
        success_delta_min=0.05,
        critical_policy_violation_delta_max=0,
        invalid_call_count_max=0,
        p95_latency_ratio_max=1.25,
        require_complete_evidence=True,
    )


def _baseline() -> RunEvidence:
    return _evidence("baseline", "baseline", 8 / 12, 0)


def _oracle() -> RunEvidence:
    return _evidence("oracle", "oracle", 1.0, 0)


def _unknown_tool() -> RunEvidence:
    return _evidence("unknown", "unknown_tool", 0.0, 12)


def test_oracle_candidate_passes_all_release_gates() -> None:
    report = decide_release(_baseline(), _oracle(), _release_policy())
    assert report.decision == ReleaseDecision.GO
    assert all(gate.passed for gate in report.gates)


def test_unknown_tool_candidate_is_no_go() -> None:
    report = decide_release(_baseline(), _unknown_tool(), _release_policy())
    assert report.decision == ReleaseDecision.NO_GO
    assert "invalid_call_count" in report.failed_gate_ids


def test_release_rejects_mismatched_task_manifest() -> None:
    candidate = _oracle().model_copy(update={"task_manifest_sha256": "f" * 64})
    with pytest.raises(ValueError, match="任务 manifest 不一致"):
        decide_release(_baseline(), candidate, _release_policy())
```

- [ ] **Step 2: Run tests and confirm missing-release failure**

Run: `.venv/bin/pytest tests/test_release_policy.py -q`

Expected: FAIL importing `veritool_rl.retail_ops.release`.

- [ ] **Step 3: Implement explicit gate results and paired validation**

```python
class ReleaseDecision(StrEnum):
    GO = "GO"
    NO_GO = "NO-GO"


class GateResult(StrictModel):
    gate_id: str
    passed: bool
    observed: float | int | bool | str
    threshold: float | int | bool
    reason: str


class ReleaseReport(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    decision: ReleaseDecision
    baseline_run_id: str
    candidate_run_id: str
    baseline_policy: str
    candidate_policy: str
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    deployment: Literal["candidate", "baseline"]
    gates: list[GateResult]
    failed_gate_ids: list[str]
    baseline_metrics: dict[str, Any]
    candidate_metrics: dict[str, Any]
```

Validate equal bundle hash, task manifest hash, evaluator ID, task count, seed, parser ID, and
budget before computing gates. Compute success delta, policy-violation delta, invalid-call
count, p95 latency ratio, and evidence completeness separately; never short-circuit after the
first failure. If base and candidate p95 are both `0.0`, record a ratio of `1.0`; if base is
`0.0` but candidate is positive, fail the latency gate with observed value
`"undefined_base_zero"` rather than serializing infinity.

- [ ] **Step 4: Write canonical JSON, Markdown, and HTML reports**

`write_release_report` creates a new output directory and writes `release.json`, `report.md`,
and `report.html`. Use `html.escape` and a fixed template; do not add Jinja. Reports contain
bundle/manifest hashes, paired metrics, every gate result, selected deployment (`candidate` on
GO, `baseline` on NO-GO), and no wall-clock timestamp so identical inputs produce identical
content.

- [ ] **Step 5: Run release and aggregate-report tests**

Run: `.venv/bin/pytest tests/test_release_policy.py tests/test_aggregate_report.py -q`

Expected: all selected tests PASS.

- [ ] **Step 6: Commit the release unit**

```bash
git add src/veritool_rl/retail_ops/release.py tests/test_release_policy.py
git commit -m "feat: add RetailOps release gates and reports"
```

### Task 8: Stable Build, Evaluate, and Release CLI

**Files:**
- Create: `src/veritool_rl/product_cli.py`
- Modify: `pyproject.toml:1-40`
- Create: `configs/retail_ops_v1_build.yaml`
- Create: `configs/retail_ops_v1_qualification_base.yaml`
- Create: `configs/retail_ops_v1_qualification_oracle.yaml`
- Create: `configs/retail_ops_v1_qualification_fault.yaml`
- Create: `configs/retail_ops_v1_release.yaml`
- Test: `tests/test_retail_ops_cli.py`

**Interfaces:**
- Consumes: Tasks 1-7 public functions.
- Produces: `main(argv: Sequence[str] | None = None) -> int` and console script `retail-agent-ops` with `build`, `evaluate`, and `release` subcommands.

- [ ] **Step 1: Write failing parser and one-command CLI tests**

```python
def test_product_cli_exposes_three_nonblocking_commands() -> None:
    parser = build_product_parser()
    build = parser.parse_args(
        ["build", "--config", "x", "--output_dir", "y"]
    )
    evaluate = parser.parse_args(
        [
            "evaluate",
            "--config",
            "x",
            "--input_dir",
            "build",
            "--output_dir",
            "y",
        ]
    )
    release = parser.parse_args(
        [
            "release",
            "--config",
            "x",
            "--baseline_dir",
            "base",
            "--candidate_dir",
            "candidate",
            "--output_dir",
            "y",
        ]
    )
    assert (build.command, evaluate.command, release.command) == (
        "build",
        "evaluate",
        "release",
    )


def test_build_cli_writes_manifest(tmp_path: Path) -> None:
    exit_code = main(
        [
            "build",
            "--config",
            "configs/retail_ops_v1_build.yaml",
            "--seed",
            "0",
            "--output_dir",
            str(tmp_path / "build"),
        ]
    )
    assert exit_code == 0
    assert (tmp_path / "build/manifest.json").is_file()
```

- [ ] **Step 2: Run tests and confirm missing-CLI failure**

Run: `.venv/bin/pytest tests/test_retail_ops_cli.py -q`

Expected: FAIL importing `veritool_rl.product_cli`.

- [ ] **Step 3: Implement argparse subcommands and typed config dispatch**

Each subcommand requires `--config`, accepts `--seed` with default `0`, and requires
`--output_dir`. `evaluate` additionally requires `--input_dir` for a built task directory;
`release` additionally requires `--baseline_dir` and `--candidate_dir`. Config files declare
only stable bundle/policy/evaluator settings, while run directories remain explicit CLI inputs.
Validate path values stored inside committed configs with `validate_project_relative_path`;
runtime input/output directories may be absolute pytest temporary paths.

```python
def _run_build(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    bundle_dir = Path(str(config["bundle_dir"]))
    validate_project_relative_path(bundle_dir, "bundle_dir")
    build_qualification(bundle_dir, args.seed, args.output_dir)


def _run_evaluate(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    bundle_dir = Path(str(config["bundle_dir"]))
    validate_project_relative_path(bundle_dir, "bundle_dir")
    evaluate_retail_ops(
        bundle_dir=bundle_dir,
        build_dir=args.input_dir,
        policy_type=str(config["policy_type"]),
        config=config,
        seed=args.seed,
        output_dir=args.output_dir,
        mode=EvaluationMode.QUALIFICATION,
    )


def _run_release(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    bundle_dir = Path(str(config["bundle_dir"]))
    validate_project_relative_path(bundle_dir, "bundle_dir")
    bundle = load_bundle(bundle_dir)
    baseline = load_run_evidence(args.baseline_dir / "run.json")
    candidate = load_run_evidence(args.candidate_dir / "run.json")
    report = decide_release(baseline, candidate, bundle.release)
    write_release_report(report, args.output_dir)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_product_parser()
    args = parser.parse_args(argv)
    handlers = {
        "build": _run_build,
        "evaluate": _run_evaluate,
        "release": _run_release,
    }
    handlers[args.command](args)
    return 0
```

Use these exact stable config payloads:

```yaml
# configs/retail_ops_v1_build.yaml
bundle_dir: domains/retail_ops/v1
split: qualification
```

```yaml
# configs/retail_ops_v1_qualification_oracle.yaml
bundle_dir: domains/retail_ops/v1
mode: qualification
policy_type: oracle
bootstrap_samples: 1000
parser_id: hermes-single-call-v1
budget:
  max_steps: 5
```

```yaml
# configs/retail_ops_v1_qualification_base.yaml
bundle_dir: domains/retail_ops/v1
mode: qualification
policy_type: baseline
bootstrap_samples: 1000
parser_id: hermes-single-call-v1
budget:
  max_steps: 5
```

```yaml
# configs/retail_ops_v1_qualification_fault.yaml
bundle_dir: domains/retail_ops/v1
mode: qualification
policy_type: unknown_tool
bootstrap_samples: 1000
parser_id: hermes-single-call-v1
budget:
  max_steps: 5
```

The release config is:

```yaml
# configs/retail_ops_v1_release.yaml
bundle_dir: domains/retail_ops/v1
```

- [ ] **Step 4: Register the product command without renaming the package**

```toml
[project.scripts]
retail-agent-ops = "veritool_rl.product_cli:main"
```

Do not change `[project].name`, imports, or historical script entry points.

- [ ] **Step 5: Run CLI and config-path regressions**

Run: `.venv/bin/pytest tests/test_retail_ops_cli.py tests/test_config_paths.py -q`

Expected: all selected tests PASS.

- [ ] **Step 6: Commit the CLI unit**

```bash
git add src/veritool_rl/product_cli.py pyproject.toml configs/retail_ops_v1_*.yaml tests/test_retail_ops_cli.py
git commit -m "feat: add RetailAgentOps product CLI"
```

### Task 9: FastAPI Service and Base Fallback

**Files:**
- Create: `src/veritool_rl/retail_ops/service.py`
- Modify: `src/veritool_rl/product_cli.py`
- Modify: `pyproject.toml:11-40`
- Modify: `uv.lock`
- Create: `configs/retail_ops_v1_serve.yaml`
- Test: `tests/test_service.py`

**Interfaces:**
- Consumes: `ReleaseReport`, approved bundle, qualification task manifest, qualification policies.
- Produces: `create_app(release_dir: Path, bundle_dir: Path, build_dir: Path) -> FastAPI` and `serve` CLI dispatch.

- [ ] **Step 1: Add FastAPI/Uvicorn through uv and update the lock**

Run: `env -u UV_INDEX_URL uv add "fastapi>=0.115" "uvicorn>=0.30"`

Run: `env -u UV_INDEX_URL uv add --dev "httpx>=0.27"`

Expected: `pyproject.toml` and `uv.lock` change; no system Python packages are modified.

- [ ] **Step 2: Write failing health, GO selection, and NO-GO fallback tests**

```python
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from veritool_rl.artifacts import sha256_file
from veritool_rl.retail_ops.bundle import ReleasePolicyConfig, load_bundle
from veritool_rl.retail_ops.evaluation import EvaluationMode, RunEvidence


def _service_evidence(
    run_id: str,
    policy_type: str,
    task_success: float,
    invalid_calls: int,
    bundle_hash: str,
    manifest_hash: str,
) -> RunEvidence:
    return RunEvidence(
        run_id=run_id,
        mode=EvaluationMode.QUALIFICATION,
        policy_type=policy_type,
        bundle_sha256=bundle_hash,
        task_manifest_sha256=manifest_hash,
        seed=0,
        parser_id="hermes-single-call-v1",
        budget={"max_steps": 5},
        task_count=12,
        metrics={
            "task_success": task_success,
            "policy_violation_count": 0,
            "invalid_call_count": invalid_calls,
            "p95_latency_ms": 10.0,
        },
        evidence_complete=True,
        artifact_sha256={"metrics.json": "c" * 64},
    )


def _app(tmp_path: Path, policy_type: str, success: float, invalid: int) -> FastAPI:
    from veritool_rl.retail_ops.manifests import build_qualification
    from veritool_rl.retail_ops.release import decide_release, write_release_report
    from veritool_rl.retail_ops.service import create_app

    build_dir = tmp_path / f"build-{policy_type}"
    release_dir = tmp_path / f"release-{policy_type}"
    build_qualification(Path("domains/retail_ops/v1"), 0, build_dir)
    bundle_hash = load_bundle(Path("domains/retail_ops/v1")).bundle_sha256
    manifest_hash = sha256_file(build_dir / "manifest.json")
    report = decide_release(
        _service_evidence(
            "baseline", "baseline", 8 / 12, 0, bundle_hash, manifest_hash
        ),
        _service_evidence(
            policy_type, policy_type, success, invalid, bundle_hash, manifest_hash
        ),
        ReleasePolicyConfig(
            success_delta_min=0.05,
            critical_policy_violation_delta_max=0,
            invalid_call_count_max=0,
            p95_latency_ratio_max=1.25,
            require_complete_evidence=True,
        ),
    )
    write_release_report(report, release_dir)
    return create_app(release_dir, Path("domains/retail_ops/v1"), build_dir)


def test_serve_parser_requires_release_and_built_input_dirs() -> None:
    from veritool_rl.product_cli import build_product_parser

    parsed = build_product_parser().parse_args(
        [
            "serve",
            "--config",
            "configs/retail_ops_v1_serve.yaml",
            "--release_dir",
            "reports/retail_ops/v1/release",
            "--input_dir",
            "reports/retail_ops/v1/build",
            "--output_dir",
            "reports/retail_ops/v1/service",
        ]
    )
    assert parsed.command == "serve"


def test_health_reports_candidate_for_go_release(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path, "oracle", 1.0, 0))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["deployment"] == "candidate"


def test_no_go_release_falls_back_to_baseline(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path, "unknown_tool", 0.0, 12))
    response = client.get("/health")
    assert response.json()["deployment"] == "baseline"


def test_service_runs_allowed_denied_and_recovery_tasks(tmp_path: Path) -> None:
    from veritool_rl.retail_ops.tasks import build_qualification_tasks

    client = TestClient(_app(tmp_path, "oracle", 1.0, 0))
    tasks = build_qualification_tasks(seed=0)
    for category in ("refund_eligible", "refund_denied_window", "refund_recovery"):
        task_id = next(
            task.task_id for task in tasks if task.scenario.value == category
        )
        payload = client.post(f"/v1/tasks/{task_id}/run").json()
        assert payload["success"] is True
        assert payload["category"] == category
        assert "steps" in payload
```

- [ ] **Step 3: Run service tests and confirm missing-app failure**

Run: `.venv/bin/pytest tests/test_service.py -q`

Expected: FAIL importing `veritool_rl.retail_ops.service`.

- [ ] **Step 4: Implement bounded FastAPI app and deployment selection**

```python
class HealthResponse(StrictModel):
    status: Literal["ok"] = "ok"
    bundle_version: str
    release_decision: ReleaseDecision
    deployment: Literal["candidate", "baseline"]


def _public_trajectory_response(trajectory: Trajectory) -> dict[str, Any]:
    return {
        "task_id": trajectory.task.task_id,
        "category": trajectory.task.scenario.value,
        "success": trajectory.success,
        "termination": trajectory.termination.value,
        "violations": trajectory.violations,
        "steps": [
            {
                "index": step.index,
                "tool_call": (
                    step.tool_call.model_dump(mode="json")
                    if step.tool_call is not None
                    else None
                ),
                "observation": (
                    step.observation.model_dump(mode="json")
                    if step.observation is not None
                    else None
                ),
            }
            for step in trajectory.steps
        ],
    }


def create_app(release_dir: Path, bundle_dir: Path, build_dir: Path) -> FastAPI:
    release = load_release_report(release_dir / "release.json")
    bundle = load_bundle(bundle_dir)
    tasks = load_built_tasks(build_dir)
    if release.bundle_sha256 != bundle.bundle_sha256:
        raise ValueError("release report 与 bundle SHA-256 不匹配")
    if release.task_manifest_sha256 != sha256_file(build_dir / "manifest.json"):
        raise ValueError("release report 与 task manifest SHA-256 不匹配")
    selected = "candidate" if release.decision is ReleaseDecision.GO else "baseline"
    app = FastAPI(title="RetailAgentOps", version=bundle.bundle.bundle_version)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            bundle_version=bundle.bundle.bundle_version,
            release_decision=release.decision,
            deployment=selected,
        )

    @app.post("/v1/tasks/{task_id}/run")
    def run_task(task_id: str) -> dict[str, Any]:
        task = tasks.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="未知 qualification task")
        policy_type = release.candidate_policy if selected == "candidate" else release.baseline_policy
        trajectory = run_episode(
            task,
            lambda current: RetailOpsEnv(current, bundle),
            build_qualification_policy(policy_type, task),
            seed=0,
        )
        return _public_trajectory_response(trajectory)

    return app
```

The public trajectory response may include qualification task ID, category, calls,
observations, success, and violations. It must not accept arbitrary tool names, filesystem
paths, model paths, or raw holdout payloads. Request size is bounded by having no request body.

- [ ] **Step 5: Add blocking `serve` dispatch only at the command boundary**

The CLI loads stable `host`, `port`, and `bundle_dir` from config, requires explicit
`--release_dir` and `--input_dir` run paths, creates the app, and calls
`uvicorn.run(app, host=host, port=port)`. Tests call `create_app` directly and must never start a
real server. Before blocking, create the non-overwritable `--output_dir` and write a canonical
`service.json` containing release report SHA-256, bundle SHA-256, selected deployment, host, and
port. Add `"serve": _run_serve` to the existing handler map.

```python
def _run_serve(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    bundle_dir = Path(str(config["bundle_dir"]))
    validate_project_relative_path(bundle_dir, "bundle_dir")
    app = create_app(args.release_dir, bundle_dir, args.input_dir)
    release = load_release_report(args.release_dir / "release.json")
    create_output_dir(args.output_dir)
    write_json(
        args.output_dir / "service.json",
        {
            "release_sha256": sha256_file(args.release_dir / "release.json"),
            "bundle_sha256": load_bundle(bundle_dir).bundle_sha256,
            "deployment": release.deployment,
            "host": str(config["host"]),
            "port": int(config["port"]),
        },
    )
    uvicorn.run(app, host=str(config["host"]), port=int(config["port"]))
```

```yaml
# configs/retail_ops_v1_serve.yaml
bundle_dir: domains/retail_ops/v1
host: 127.0.0.1
port: 8000
```

- [ ] **Step 6: Run service, CLI, and dependency-lock checks**

Run: `.venv/bin/pytest tests/test_service.py tests/test_retail_ops_cli.py -q`

Run: `env -u UV_INDEX_URL uv lock --check`

Expected: tests PASS and the lock is current.

- [ ] **Step 7: Commit the service unit**

```bash
git add src/veritool_rl/retail_ops/service.py src/veritool_rl/product_cli.py pyproject.toml uv.lock configs/retail_ops_v1_serve.yaml tests/test_service.py
git commit -m "feat: add RetailAgentOps qualification service"
```

### Task 10: End-to-End Acceptance, Governance, and R1 Closeout

**Files:**
- Create: `tests/test_retail_ops_e2e.py`
- Modify: `tests/test_project_governance.py:8-86`
- Modify: `README.md`
- Modify: `docs/EXECUTION_PLAN.md`
- Modify: `docs/PROJECT_LOG.md`
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`

**Interfaces:**
- Consumes: complete R1 command surface and evidence.
- Produces: one CPU-only acceptance flow, documented artifact layout, and evidence-backed R1 completion record.

- [ ] **Step 1: Write the failing full-flow acceptance test**

```python
from pathlib import Path


def _run_cli(arguments: list[str]) -> None:
    from veritool_rl.product_cli import main

    assert main(arguments) == 0


def test_retail_ops_v1_cpu_vertical_slice(tmp_path: Path) -> None:
    import json

    build_dir = tmp_path / "build"
    base_dir = tmp_path / "base"
    oracle_dir = tmp_path / "oracle"
    fault_dir = tmp_path / "fault"
    go_dir = tmp_path / "release-go"
    no_go_dir = tmp_path / "release-no-go"

    _run_cli(
        [
            "build",
            "--config",
            "configs/retail_ops_v1_build.yaml",
            "--seed",
            "0",
            "--output_dir",
            str(build_dir),
        ]
    )
    for config, output in (
        ("configs/retail_ops_v1_qualification_base.yaml", base_dir),
        ("configs/retail_ops_v1_qualification_oracle.yaml", oracle_dir),
        ("configs/retail_ops_v1_qualification_fault.yaml", fault_dir),
    ):
        _run_cli(
            [
                "evaluate",
                "--config",
                config,
                "--seed",
                "0",
                "--input_dir",
                str(build_dir),
                "--output_dir",
                str(output),
            ]
        )
    for config, candidate, output in (
        ("configs/retail_ops_v1_release.yaml", oracle_dir, go_dir),
        ("configs/retail_ops_v1_release.yaml", fault_dir, no_go_dir),
    ):
        _run_cli(
            [
                "release",
                "--config",
                config,
                "--seed",
                "0",
                "--baseline_dir",
                str(base_dir),
                "--candidate_dir",
                str(candidate),
                "--output_dir",
                str(output),
            ]
        )

    go = json.loads((go_dir / "release.json").read_text(encoding="utf-8"))
    no_go = json.loads((no_go_dir / "release.json").read_text(encoding="utf-8"))
    oracle_metrics = json.loads(
        (oracle_dir / "metrics.json").read_text(encoding="utf-8")
    )
    assert go["decision"] == "GO"
    assert no_go["decision"] == "NO-GO"
    assert oracle_metrics["task_success"] == 1.0
    for release_dir in (go_dir, no_go_dir):
        public_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(release_dir.iterdir())
            if path.suffix in {".json", ".md", ".html"}
        )
        for forbidden in ("target_state", "expected_calls", "user_request"):
            assert forbidden not in public_text
```

- [ ] **Step 2: Add governance assertions before making them pass**

`test_project_governance.py` must assert that the approved design and implementation plan exist,
R1 active docs contain `RetailOps v1`, no file under `domains/retail_ops/v1/` references `bfcl`,
and `git check-ignore data/private/retail_ops/v1/holdout/tasks.jsonl` succeeds.

- [ ] **Step 3: Run end-to-end and governance tests**

Run: `.venv/bin/pytest tests/test_retail_ops_e2e.py tests/test_project_governance.py -q`

Expected before final documentation: the vertical-slice test PASSes; governance fails only on
the still-unwritten closeout statements.

- [ ] **Step 4: Document exact CPU commands and artifact layout**

Update `README.md` with the six qualification commands, expected directories, GO/NO-GO report
paths, service command, and explicit statements that qualification is synthetic, no formal
holdout was generated, and BFCL is not an internal RetailOps metric.

- [ ] **Step 5: Run the mandatory full quality gate**

Run: `.venv/bin/pytest -q`

Expected: all tests PASS with zero failures.

Run: `.venv/bin/ruff check .`

Expected: `All checks passed!`

Run: `.venv/bin/mypy`

Expected: `Success: no issues found` for all configured source files.

Run: `git diff --check`

Expected: no output and exit code 0.

Run: `env -u UV_INDEX_URL uv lock --check`

Expected: exit code 0 with no lock changes.

- [ ] **Step 6: Inspect final artifacts and public-data boundary**

Run the CPU flow into a new `reports/retail_ops/v1/qualification-*` tree. Verify Oracle 12/12,
expected baseline/fault outcomes, stable hashes, both release decisions, HTML readability, and
absence of `target_state`, `expected_calls`, raw holdout data, BFCL prompts, model files, or
secrets from public reports. Do not start a persistent server; use FastAPI TestClient evidence.

- [ ] **Step 7: Update phase facts only from the fresh evidence**

If every R1 acceptance target is satisfied, mark R1 `已完成` and R2 `待执行` in
`docs/EXECUTION_PLAN.md`; append commands/results/artifacts to `progress.md`, stable facts to
`findings.md`, and an append-only R1 completion entry to `docs/PROJECT_LOG.md`. If any required
gate fails, keep R1 `当前` or mark it `已阻塞` with the exact evidence; never lower thresholds.

- [ ] **Step 8: Commit the acceptance and closeout unit**

```bash
git add README.md tests/test_retail_ops_e2e.py tests/test_project_governance.py docs/EXECUTION_PLAN.md docs/PROJECT_LOG.md task_plan.md findings.md progress.md
git commit -m "feat: complete RetailOps v1 R1 vertical slice"
```

- [ ] **Step 9: Re-run final verification on the actual final HEAD**

Run: `.venv/bin/pytest -q`

Run: `.venv/bin/ruff check .`

Run: `.venv/bin/mypy`

Run: `git diff --check`

Run: `git status --short --branch`

Expected: all gates PASS and the worktree is clean on the R1 final commit.
