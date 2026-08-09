# RetailOps v1 R2 Formal Data and Base Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the audited RetailOps v1 formal 240/60/120 dataset pipeline, provider-agnostic teacher collection, sealed holdout contract, and reproducible Qwen3-1.7B/4B development baselines without training an adapter or opening the formal holdout.

**Architecture:** Keep R1 qualification contracts unchanged and add focused R2 modules for formal task generation, manifests/governance, teacher data, sealed evaluation, and base-run evidence. All external resources remain behind explicit approval gates; CPU tests use real deterministic environments and injected fake model clients/backends.

**Tech Stack:** Python 3.11, Pydantic v2, canonical JSON/SHA-256, pytest, uv, OpenAI-compatible Chat Completions, Transformers/bitsandbytes on the approved remote GPU only.

## Global Constraints

- Work only on branch `feature/r2-formal-data-and-base-eval` starting from `a3c748bdad1ce6fb7ec8a838d2f1f36da0bbae60`; do not push or merge automatically.
- Dataset version is `retail_ops_v1_r2_20260722`, generator ID is `family_sha256_v1`, and seed is `0`.
- Exact task quotas are train/dev/holdout=`240/60/120`; each of six categories contributes `40/10/20` tasks from `20/5/10` semantic families with two variants per family.
- Split families before materializing tasks; assert isolation across task, family, answer-free content, source, and derivation fingerprints.
- Teacher sees train only. Dev uses internal reference. Formal holdout is never sent to an API and never evaluated by a real model in R2.
- Teacher export requires overall pass rate at least 70% and every category at least 50%; do not automatically alter provider, model, prompt, or policy when the gate fails.
- Initial route is DeepSeek `deepseek-v4-pro` non-thinking, but code must dynamically resolve any OpenAI-compatible provider profile selected by `TEACHER_LLM_PROVIDER`.
- Qwen model revisions are exactly `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e` and `1cfa9a7208912126459214e8b04321603b3df60c`.
- No local GPU, adapter training, SFT, DPO, GRPO, formal holdout model run, BFCL change, package rename, remote creation, public release, or secret logging.
- Before formal data generation, API, SSH, remote mutation, model download, or each GPU command, present the exact command, actual working directory, physical GPU where applicable, duration, outputs, and wait for user approval.
- Use `apply_patch` for repository edits, preserve unrelated changes, write a failing test before every behavior change, and commit only after focused and regression checks pass.

---

### Task 1: Formal family-first task generation

**Files:**
- Create: `src/veritool_rl/retail_ops/formal_tasks.py`
- Create: `tests/test_retail_ops_formal_tasks.py`
- Modify: `src/veritool_rl/retail_ops/__init__.py`

**Interfaces:**
- Produces: `FormalSplit`, `FormalTaskRecord`, `FormalTaskSet`, `build_formal_task_set(dataset_version: str, seed: int) -> FormalTaskSet`.
- `FormalTaskRecord` fields: `task`, `task_fingerprint`, `family_fingerprint`, `content_fingerprint`, `source_fingerprint`, `derivation_fingerprint`, `variant_index`.
- `FormalTaskSet.records(split)` returns an ordered tuple; `FormalTaskSet.assert_exact_quotas()` verifies all category and total quotas.

- [ ] **Step 1: Write failing quota and determinism tests**

Add tests that call `build_formal_task_set("retail_ops_v1_r2_20260722", 0)` twice and assert byte-identical model dumps, exact totals 240/60/120, exact per-category 40/10/20, exactly two records per family, and task splits matching their container.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/pytest tests/test_retail_ops_formal_tasks.py -q`

Expected: collection fails because `veritool_rl.retail_ops.formal_tasks` does not exist.

- [ ] **Step 3: Implement the minimum family catalog and materializer**

Use the six existing `TaskScenario` values. Build 35 canonical families per scenario from `state_variant=0..6` crossed with `context_variant=0..4`. For lookup, the seven state variants are `pending/processing/shipped/delivered/cancelled/returned/refunded`; for allow, recovery, and deny scenarios, use window margins `1/2/3/5/7/10/14` on the scenario-appropriate side of the policy boundary. Context variant `n` adds exactly `n` unrelated distractor orders. Select the refund reason with `(scenario_index + state_variant * 5 + context_variant) % 4` over the four bundle-approved reasons; never synthesize a fifth reason or require `get_store_hours`. Compute the family order from canonical SHA-256, assign the first 20/next 5/final 10 families to train/dev/holdout, then materialize variants 0 and 1 with opaque entity IDs derived from dataset/seed/family/variant.

Keep all policy facts compatible with `RetailOpsEnv`: lookup tasks inform after `get_order`; eligible tasks lookup then refund; the three deny classes lookup and do not mutate; recovery tasks lookup, encounter one transient refund failure, then retry once. Do not change R1 qualification generation.

- [ ] **Step 4: Add fingerprint and isolation tests**

Assert the two variants of a family share family/source/derivation fingerprints but have distinct task/content fingerprints. Assert every fingerprint is lowercase 64-character hex and all five fingerprint sets are disjoint across splits. Mutate a policy-relevant field in a copied private task and assert task/derivation fingerprints change; mutate only the surface request and assert family/derivation remain stable while content changes. Also change only `task_id` or `split` and assert the answer-free content fingerprint remains unchanged.

- [ ] **Step 5: Run GREEN and regressions**

Run: `.venv/bin/pytest tests/test_retail_ops_formal_tasks.py tests/test_retail_ops_environment.py tests/test_retail_ops_manifest.py -q`

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

Commit message: `feat: add formal RetailOps task generation`

### Task 2: Formal manifests, five-dimensional isolation, and sealed holdout loading

**Files:**
- Create: `src/veritool_rl/retail_ops/formal_manifests.py`
- Create: `src/veritool_rl/retail_ops/formal_governance.py`
- Create: `tests/test_retail_ops_formal_manifest.py`
- Create: `tests/test_retail_ops_formal_holdout.py`
- Modify: `src/veritool_rl/retail_ops/governance.py`

**Interfaces:**
- Produces: `FormalTaskManifest`, `FormalHoldoutReceipt`, `FormalDatasetReceipt`, `write_formal_task_set(...)`, `load_formal_split(...)`, `assert_formal_split_isolation(...)`, `authorize_formal_holdout(...)`, and `load_authorized_formal_holdout(...)`.
- Public manifests contain ordered opaque fingerprints and file hashes only; private task JSONL retains `TaskSpec` truth.
- Existing R1 `TaskManifest`, `HoldoutReceipt`, `assert_split_isolation`, and `authorize_holdout` stay backward compatible.

- [ ] **Step 1: Write failing public/private artifact tests**

Build into temporary private and public directories. Assert private files contain complete tasks; serialize all public JSON and assert it does not contain any task ID, family ID, user request, order/customer ID, `initial_state`, `target_state`, `expected_calls`, `expected_decision`, or private path.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/pytest tests/test_retail_ops_formal_manifest.py tests/test_retail_ops_formal_holdout.py -q`

Expected: imports fail for the new formal manifest/governance modules.

- [ ] **Step 3: Implement canonical non-overwriting writers and loaders**

Write private `train.jsonl`, `dev.jsonl`, and `holdout.jsonl`; public `train.json`, `dev.json`, `holdout-receipt.json`, and `dataset.json`. Bind schema version `2.0`, dataset/generator/bundle IDs, seed, quotas, ordered five-dimensional fingerprints, and SHA-256. Refuse existing output directories and validate exact key sets on load.

- [ ] **Step 4: Implement two-stage holdout authorization**

`authorize_formal_holdout` must reject non-release purpose, absolute/out-of-root logical paths, missing/non-file artifacts, and file hash mismatch without opening/parsing task content. `load_authorized_formal_holdout` runs only after authorization and verifies every row's split, scenario order, five fingerprints, count, quotas, dataset version, bundle hash, and receipt order.

- [ ] **Step 5: Add tamper and isolation tests**

Cover reordered rows, removed/extra rows, altered scenario/truth/fingerprint, duplicate within-manifest fingerprints, overlap in each of five dimensions, wrong receipt hash, development-purpose access, and a spy path/file proving non-release access fails before `read_text`/`open`.

- [ ] **Step 6: Run GREEN and R1 regressions**

Run: `.venv/bin/pytest tests/test_retail_ops_formal_manifest.py tests/test_retail_ops_formal_holdout.py tests/test_retail_ops_holdout.py tests/test_retail_ops_manifest.py -q`

Expected: all selected tests pass and R1 schemas remain unchanged.

- [ ] **Step 7: Commit**

Commit message: `feat: add formal manifest and holdout governance`

### Task 3: Dynamic teacher route and OpenAI-compatible client boundary

**Files:**
- Create: `src/veritool_rl/retail_ops/teacher_route.py`
- Create: `src/veritool_rl/retail_ops/teacher_client.py`
- Create: `tests/test_teacher_route.py`
- Create: `tests/test_teacher_client.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Produces: `TeacherRouteSnapshot`, `load_teacher_route(environ: Mapping[str, str]) -> tuple[TeacherRouteSnapshot, str]`, `TeacherClient` protocol, `OpenAICompatibleTeacherClient`, `TeacherResponse`, and `TeacherUsage`.
- The returned string is the selected API key in memory only; snapshots and exceptions never contain it.
- Add optional dependency group `teacher` containing the OpenAI Python SDK; imports remain lazy so core CPU tests work without the extra.

- [ ] **Step 1: Write failing selector and validation tests**

Use fake environments containing `deepseek` and `other` profiles. Change only `TEACHER_LLM_PROVIDER` and assert the selected base/model/extras and route hash change. Cover invalid provider names, missing selected fields, ignored unselected secrets, HTTP/userinfo/query/fragment URLs, invalid/oversized JSON, nested secret-like keys, and deterministic canonical snapshots.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/pytest tests/test_teacher_route.py -q`

Expected: missing module failure.

- [ ] **Step 3: Implement route resolution and redaction**

Dynamically construct `TEACHER_LLM_<NORMALIZED>_*` keys after validating the selector. Store provider/base/model/extras/protocol ID in a strict Pydantic snapshot and compute canonical SHA-256. Never enumerate or log environment values beyond selected non-secret fields.

- [ ] **Step 4: Write failing client translation tests**

Inject a fake OpenAI-style client and assert messages/tools/model/temperature/extra body are translated exactly, tool calls and usage are normalized, actual response model/system fingerprint are retained, and errors redact API keys and authorization headers.

- [ ] **Step 5: Implement the lazy client adapter**

Use `OpenAI(base_url=route.base_url, api_key=api_key)` only inside the production factory. Keep all collection logic dependent on the `TeacherClient` protocol. Reject responses without choices or with malformed tool-call arguments; preserve absent usage as `None` rather than inventing counts.

- [ ] **Step 6: Resolve and verify dependencies**

Add the optional group with uv, preserve the existing Tsinghua lock source, and add `[tool.uv] default-index = "https://pypi.tuna.tsinghua.edu.cn/simple"` so plain `uv lock --check` is independent of user-level mirror aliases. Verify the lock diff contains the teacher SDK and its real transitive dependencies plus the small project config change, not a mirror-only rewrite.

- [ ] **Step 7: Run GREEN**

Run: `.venv/bin/pytest tests/test_teacher_route.py tests/test_teacher_client.py -q && .venv/bin/ruff check src/veritool_rl/retail_ops/teacher_route.py src/veritool_rl/retail_ops/teacher_client.py tests/test_teacher_route.py tests/test_teacher_client.py && .venv/bin/mypy && uv lock --check`

Expected: all commands pass without an API call.

- [ ] **Step 8: Commit**

Commit message: `feat: add dynamic teacher routing`

### Task 4: Teacher collection, checkpoint resume, quality gate, and train export

**Files:**
- Create: `src/veritool_rl/retail_ops/teacher_data.py`
- Create: `tests/test_teacher_data.py`
- Modify: `src/veritool_rl/data/generators.py`

**Interfaces:**
- Produces: `TeacherCollectionConfig`, `TeacherAttemptEvidence`, `TeacherQualityReport`, `collect_teacher_attempt(...)`, `validate_teacher_trajectory(...)`, and `export_formal_train(...)`.
- Consumes Task 1 records, Task 2 manifests, Task 3 `TeacherClient`, existing `RetailOpsEnv`, runner/replay, `build_success_trajectories`, and `trajectory_to_sft_example`.

- [ ] **Step 1: Write failing fake-teacher collection tests**

Cover a valid multi-step tool trajectory, schema-invalid arguments, policy denial, illegal tool, step limit, wrong final state, transient recovery, and replay mismatch. Assert no dev/holdout record can enter collection and every accepted record binds task/route/config/bundle/manifest hashes.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/pytest tests/test_teacher_data.py -q`

Expected: missing `teacher_data` module.

- [ ] **Step 3: Implement bounded collection**

For each train task run at most two episodes of at most five environment steps. Retry only timeout/429/5xx transport failures with at most three total request attempts; never retry auth or schema 4xx. Write raw response, normalized step, trajectory, usage, error taxonomy, checkpoint, and per-file hashes only under a new private ignored `teacher-collection/<attempt>/` directory without overwriting prior evidence. Add tests that reject collection output outside the dataset version's ignored private root and assert no task-level collection artifact appears under the public manifest root.

- [ ] **Step 4: Implement exact resume semantics**

Resume only a checkpoint whose dataset/task/route/config/bundle/manifest hashes match and whose artifact hashes reload cleanly. Reuse only accepted task results; corrupt or mismatched checkpoints fail rather than silently rerun into the same directory.

- [ ] **Step 5: Implement quality report and export**

Compute overall and six per-category teacher pass rates. Below 70% overall or 50% in any category raises a quality-gate error before export. Above the gate, choose one accepted teacher trajectory per task, otherwise the deterministic internal reference for that same task; independently replay all 240. Write canonical `train.jsonl`, `sft.jsonl`, task-level selection evidence, and hashes only beneath the private ignored `train-export/<attempt>/` directory. The public manifest root may receive only an allowlisted aggregate `quality.json` plus private-artifact hashes and must contain no task row, request, trajectory, or truth.

- [ ] **Step 6: Add boundary tests**

Test exactly-at-threshold success, just-below failures, one-category failure despite overall success, exactly 240 unique exports, teacher preference, reference fallback, usage missing/reporting, non-overwrite, resume corruption, and no secret/private task data in public quality output.

- [ ] **Step 7: Run GREEN and regressions**

Run: `.venv/bin/pytest tests/test_teacher_data.py tests/test_replay.py tests/test_trajectory_schema.py -q`

Expected: all selected tests pass.

- [ ] **Step 8: Commit**

Commit message: `feat: add audited teacher data pipeline`

### Task 5: Sealed evaluator contract and real-model dev base evidence

**Files:**
- Create: `src/veritool_rl/retail_ops/sealed_evaluation.py`
- Create: `src/veritool_rl/retail_ops/base_evaluation.py`
- Create: `tests/test_sealed_evaluation.py`
- Create: `tests/test_base_evaluation.py`
- Modify: `src/veritool_rl/agent/qwen.py`

**Interfaces:**
- Produces: `SealedEvaluationReport`, `evaluate_authorized_holdout(...)`, `ModelArtifact`, `HardwareProvenance`, `BaseEvaluationConfig`, `BaseRunEvidence`, `load_verified_formal_dev(...)`, `evaluate_formal_dev_base(...)`, and `load_base_run_evidence(...)`.
- `load_verified_formal_dev(private_root, public_manifest, purpose="develop")` opens only `dev.jsonl`, checks the validated private dev artifact SHA-256 against the public manifest, then validates all rows, counts, categories, order, split, and five fingerprints.
- `evaluate_formal_dev_base` accepts only records returned by that loader, their corresponding public dev manifest, and a `GenerationBackend`; adapter paths are forbidden.
- `evaluate_authorized_holdout` accepts only an already authorized formal holdout and writes full private evidence plus an allowlisted aggregate public report.

- [ ] **Step 1: Write failing sealed evaluator tests**

Use temporary fake holdout tasks and a fake backend. Assert development/unapproved input is rejected, full trajectories stay in private output, public output contains only aggregate metric/provenance/taxonomy fields, and no task/family ID or truth appears.

- [ ] **Step 2: Run sealed RED and implement**

Run: `.venv/bin/pytest tests/test_sealed_evaluation.py -q`

Expected: missing module. Implement the minimum evaluator around existing runner, replay, metrics, and redaction without adding any CLI that can open formal holdout in development mode.

- [ ] **Step 3: Write failing base evidence tests**

Use a fake generation backend and fake hardware provider. Assert exact model repo/revision/file hashes, commit/lock/bundle/manifest/parser/prompt/config hashes, generation settings, physical GPU index/UUID/name, CUDA mapping, peak memory, duration, throughput, token/latency, and artifact hashes are required and tamper-checked.

- [ ] **Step 4: Implement deterministic dev evaluation**

Accept exactly the 60 dev records returned by `load_verified_formal_dev`; require `develop` purpose and `split=dev`, and validate both the private artifact SHA-256 and the public manifest before evaluation. Reject holdout paths, holdout receipts, release purpose, or raw unverified records. Enforce seed 0, no adapter, non-thinking, no sampling, 4-bit NF4, and max five steps. Reuse the same policy/parser/tool schema for both models. Full task trajectories remain private; public report contains aggregate metrics and model/hardware provenance but no task IDs.

- [ ] **Step 5: Harden Qwen backend provenance**

Extend existing Qwen loading compatibly so formal base runs can supply a pinned local model path/revision, deterministic generation settings, and injectable hardware measurements. Keep R1 and BFCL call sites working and never load CUDA in CPU tests.

- [ ] **Step 6: Run GREEN and regressions**

Run: `.venv/bin/pytest tests/test_sealed_evaluation.py tests/test_base_evaluation.py tests/test_qwen_policy.py tests/test_retail_ops_evaluation.py -q`

Expected: all selected tests pass.

- [ ] **Step 7: Commit**

Commit message: `feat: add sealed and dev base evaluation evidence`

### Task 6: Strict R2 CLI/config dispatch and CPU end-to-end acceptance

**Files:**
- Modify: `src/veritool_rl/product_cli.py`
- Create: `configs/retail_ops_v1_r2_formal_freeze.yaml`
- Create: `configs/retail_ops_v1_r2_teacher_smoke.yaml`
- Create: `configs/retail_ops_v1_r2_teacher_full.yaml`
- Create: `configs/retail_ops_v1_r2_train_export.yaml`
- Create: `configs/retail_ops_v1_r2_qwen3_1_7b_dev.yaml`
- Create: `configs/retail_ops_v1_r2_qwen3_4b_dev.yaml`
- Create: `tests/test_retail_ops_r2_cli.py`
- Create: `tests/test_retail_ops_r2_e2e.py`
- Modify: `tests/test_project_governance.py`

**Interfaces:**
- Preserve all R1 command invocations exactly.
- `build` gains optional `--input_dir`; R2 build configs dispatch by `pipeline` to `formal_freeze`, `teacher_collect`, or `train_export`.
- `evaluate` dispatches `pipeline=formal_dev_base`; no R2 release or serve path is added.

- [ ] **Step 1: Write failing parser/dispatch tests**

Assert old R1 configs still parse and run. Assert each R2 pipeline accepts only its exact key set, requires/forbids `--input_dir` as appropriate, rejects absolute committed paths, unknown pipelines, missing/extra keys, holdout evaluation, adapter config, wrong dataset version/seed/model revision, and output overwrite.

- [ ] **Step 2: Run RED**

Run: `.venv/bin/pytest tests/test_retail_ops_r2_cli.py -q`

Expected: R2 dispatch/config failures while R1 tests remain green.

- [ ] **Step 3: Implement strict backward-compatible dispatch**

If config has no `pipeline`, execute the current R1 exact-key path. For each R2 pipeline validate the exact schema and call the corresponding Task 1–5 interface. Never read `.env` during formal freeze, train export, fake base, R1, release, or serve.

- [ ] **Step 4: Add CPU end-to-end fake flow**

In temporary roots run formal freeze twice and compare all files byte-for-byte; run a fake teacher attempt with a controlled pass/fallback mix; export 240 trajectories; run both model configs through fake backends; validate all evidence loaders and public leak allowlists. Do not generate the repository's formal dataset in this test.

- [ ] **Step 5: Add governance scans**

Assert `.env`, `/data/`, `/models/`, `/reports/retail_ops/` remain ignored; committed R2 configs contain no secret or private path; no source/config references BFCL holdout task/failure IDs; plain `uv lock --check` succeeds through project-level index pinning.

- [ ] **Step 6: Run GREEN and full CPU gate**

Run: `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/mypy && uv lock --check && git diff --check`

Expected: all commands pass at the current HEAD.

- [ ] **Step 7: Commit**

Commit message: `feat: expose audited R2 product pipelines`

### Task 7: Review CPU implementation and prepare external approval commands

**Files:**
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`
- Modify: `docs/EXECUTION_PLAN.md`
- Modify: `docs/PROJECT_LOG.md`
- Create: `docs/handoffs/2026-07-22-r2-external-run-commands.md`

**Interfaces:**
- Produces a reviewed CPU implementation and copy-paste-safe command sheet; does not execute external operations.

- [ ] **Step 1: Run per-task and whole-branch review**

Generate review packages from each task base and from `a3c748b..HEAD`. Resolve every Critical/Important finding with focused tests and re-review; record Minor findings for final triage.

- [ ] **Step 2: Run the full CPU gate from scratch**

Run: `.venv/bin/pytest -q`, `.venv/bin/ruff check .`, `.venv/bin/mypy`, `uv lock --check`, `git diff --check`, formal repeat-build comparison in temporary directories, and repository secret/BFCL/holdout leak scans.

- [ ] **Step 3: Write exact approval command sheet**

Include separate, non-executed sections for formal freeze, `.env` preflight, six-task API smoke, 240-task API full run, read-only SSH inventory, remote source snapshot setup, each pinned model download, each single-task GPU smoke, and each 60-task GPU dev run. The inventory section states that no GPU command exists until its output identifies an idle physical index and UUID; after approval and inventory, write each concrete GPU command with that physical identity, remote cwd, duration, outputs, and hashes before requesting its own approval.

- [ ] **Step 4: Update stage records without claiming R2 complete**

Mark CPU implementation complete and external evidence pending. Append the branch, tests, route contract, data/model revisions, failures, and pending approval gates to the project log. Commit message: `docs: prepare R2 external execution gates`.

### Task 8: Approval-gated formal runs and final closeout

**Files:**
- Generate ignored private data under `data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722/`
- Generate tracked public metadata under `manifests/retail_ops/v1/retail_ops_v1_r2_20260722/`
- Generate ignored reports under `reports/retail_ops/v1/r2/retail_ops_v1_r2_20260722/`
- Modify: `task_plan.md`, `findings.md`, `progress.md`, `docs/EXECUTION_PLAN.md`, `docs/PROJECT_LOG.md`

**Interfaces:**
- Consumes only commands explicitly approved at each gate.
- Produces the formal dataset receipt, approved teacher route/quality evidence, Qwen3-1.7B/4B dev evidence, synchronized hashes, and final R2 completion record.

- [ ] **Step 1: Stop and request formal freeze approval**

Show the exact local CPU command, paths, estimated duration, and output. Run only after approval; repeat in an independent attempt and compare hashes before promoting public metadata.

- [ ] **Step 2: Stop and request API smoke approval**

Ask the user to place the selected profile key in `.env`; verify names/permissions without printing values. Show the resolved non-secret route snapshot and six-task command. Run only after approval and report success, usage, errors, hashes, and no dev/holdout access.

- [ ] **Step 3: Stop and request API full approval**

Require the exact same route fingerprint as smoke. Show the 240-task command, 20–60 minute estimate, checkpoint/output paths, and hard task/episode/step limits. Run only after approval; enforce quality gates and export/replay all 240.

- [ ] **Step 4: Stop at every remote gate**

Obtain approval for read-only inventory first. Then separately approve source snapshot setup, each model download to `/data/TJK/models`, each one-task smoke, and each full 60-task run. Never describe logical CUDA device 0 as the physical GPU; record `nvidia-smi` physical index and UUID.

- [ ] **Step 5: Synchronize and verify evidence**

Copy only approved public-safe reports plus private artifacts intended for local ignored storage. Compare SHA-256 across remote/local, reload evidence, verify exact final commit/config/model/data hashes, and reject stale runs after any relevant commit.

- [ ] **Step 6: Final verification and closeout**

Run the full CPU gate on the actual final HEAD, perform whole-branch review, update all planning/log documents, and mark R2 complete only if formal data, teacher quality, both true dev bases, leak scans, hashes, and clean worktree evidence are all present. Use the finishing-development-branch workflow and present branch handling options without merging automatically.
