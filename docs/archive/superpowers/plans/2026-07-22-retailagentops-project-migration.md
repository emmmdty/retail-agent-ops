# RetailAgentOps Project Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the existing standalone RetailAgentOps repository to its formal project path, rebuild path-sensitive local assets, and deliver a validated Codex R2 execution handoff without starting R2 itself.

**Architecture:** Preserve the single existing Git repository and move it atomically on the same filesystem. Treat the two virtual environments and the benchmark symlink as reconstructible path-sensitive assets, keep a temporary rollback copy until validation passes, then commit the handoff and migration records from the new directory.

**Tech Stack:** Linux/zsh, Git, uv, Python 3.11, pytest, Ruff, mypy, Markdown.

## Global Constraints

- Source path: `/home/tjk/myProjects/internship-projects/.worktrees/retail-agent-ops`.
- Destination path: `/home/tjk/myProjects/internship-projects/retail-agent-ops`.
- Preserve branch `portfolio/retail-agent-ops-init`, all Git history, ignored R1 evidence, and R1 base commit `59cc1b5`.
- Do not create a remote, public repository, second active clone, formal R2 data, model download, API call, or GPU job.
- Do not rename `veritool_rl`.
- Use `UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple` so lock resolution matches the existing lock source.

---

### Task 1: Freeze the migration contract and preflight evidence

**Files:**
- Create: `docs/superpowers/specs/2026-07-22-retailagentops-project-migration-and-r2-handoff-design.md`
- Create: `docs/superpowers/plans/2026-07-22-retailagentops-project-migration.md`
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`

**Interfaces:**
- Consumes: clean R1 repository at `59cc1b5`, approved destination path.
- Produces: committed migration design, rollback strategy, and exact validation contract.

- [x] **Step 1: Verify the destination and Git topology**

Run:

```bash
test ! -e /home/tjk/myProjects/internship-projects/retail-agent-ops
git rev-parse HEAD
git status --short --branch
git diff --check
```

Expected: destination absent; HEAD starts at `59cc1b5`; only the migration planning files are modified before the preparation commit.

- [x] **Step 2: Verify the pre-migration CPU baseline**

Run:

```bash
.venv/bin/pytest -q
```

Expected: `211 passed`.

- [x] **Step 3: Commit migration preparation**

```bash
git add docs/superpowers/specs/2026-07-22-retailagentops-project-migration-and-r2-handoff-design.md docs/superpowers/plans/2026-07-22-retailagentops-project-migration.md task_plan.md findings.md progress.md
git commit -m "docs: plan RetailAgentOps project migration"
```

Expected: clean tracked worktree at the old path.

### Task 2: Move the repository and rebuild path-sensitive assets

**Files:**
- Move directory: `/home/tjk/myProjects/internship-projects/.worktrees/retail-agent-ops` → `/home/tjk/myProjects/internship-projects/retail-agent-ops`
- Recreate ignored directory: `.venv/`
- Recreate ignored directory: `tools/bfcl_eval/.venv/`
- Recreate ignored symlink: `data/external_repos`

**Interfaces:**
- Consumes: clean committed repository and reconstructible uv lockfiles.
- Produces: one working repository at the formal path with path-correct environments and benchmark link.

- [x] **Step 1: Move the repository once**

Run from `/home/tjk/myProjects/internship-projects`:

```bash
mv /home/tjk/myProjects/internship-projects/.worktrees/retail-agent-ops /home/tjk/myProjects/internship-projects/retail-agent-ops
```

Expected: old path absent, new path present, Git HEAD unchanged.

- [x] **Step 2: Create a rollback directory and move path-sensitive assets into it**

Run the following as one shell block and record the printed rollback path:

```bash
MIGRATION_ROLLBACK=$(mktemp -d /tmp/retail-agent-ops-migration.XXXXXX)
printf '%s\n' "$MIGRATION_ROLLBACK"
mv /home/tjk/myProjects/internship-projects/retail-agent-ops/.venv "$MIGRATION_ROLLBACK/main-venv"
mv /home/tjk/myProjects/internship-projects/retail-agent-ops/tools/bfcl_eval/.venv "$MIGRATION_ROLLBACK/bfcl-eval-venv"
mv /home/tjk/myProjects/internship-projects/retail-agent-ops/data/external_repos "$MIGRATION_ROLLBACK/external_repos.link"
```

Expected: Git repository and local evidence remain in place; only reconstructible ignored assets move to rollback storage.

- [x] **Step 3: Recreate the benchmark link for the new path depth**

Run from the new repository:

```bash
ln -s ../../veritool-rl/data/external_repos data/external_repos
readlink -f data/external_repos
```

Expected resolved target: `/home/tjk/myProjects/internship-projects/veritool-rl/data/external_repos`.

- [x] **Step 4: Rebuild both frozen uv environments**

```bash
UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple uv sync --extra dev --frozen
UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple uv sync --project tools/bfcl_eval --frozen
```

Expected: `.venv/` and `tools/bfcl_eval/.venv/` are recreated without changing either lockfile.

- [x] **Step 5: Verify path-sensitive assets before deleting rollback data**

```bash
head -n 1 .venv/bin/pytest
head -n 1 .venv/bin/retail-agent-ops
.venv/bin/python --version
tools/bfcl_eval/.venv/bin/python --version
readlink -f data/external_repos
```

Expected: executable shebangs reference the new absolute directory; both Python commands succeed; link resolves to the original external checkout.

### Task 3: Write the R2 Codex execution handoff

**Files:**
- Create: `docs/handoffs/2026-07-22-r2-codex-execution-prompt.md`
- Modify: `docs/LEGACY_INVENTORY.md`
- Modify: `docs/PROJECT_LOG.md`
- Modify: `task_plan.md`
- Modify: `findings.md`
- Modify: `progress.md`

**Interfaces:**
- Consumes: R1 final contracts, R2 execution-plan requirements, new repository path.
- Produces: copy-paste-ready R2 prompt with decision gates, subagent workflow, exact acceptance gates, and migration provenance.

- [x] **Step 1: Write the prompt with complete startup and stage boundaries**

The prompt must contain the exact new `cwd`, required document read order, R1 base commit, current status checks, R2 quota/category invariants, required decision gates, subagent edit isolation, holdout hard stops, remote GPU approval format, TDD/commit/review loop, final quality commands, and completion-document updates.

- [x] **Step 2: Perform a placeholder and boundary scan**

Run:

```bash
rg -n "TBD|TODO|<[^>]+>|待补|稍后实现" docs/handoffs/2026-07-22-r2-codex-execution-prompt.md
rg -n "240/60/120|40/10/20|data/private/retail_ops/v1|gpu-4090|subagent|211 passed|59cc1b5|git diff --check" docs/handoffs/2026-07-22-r2-codex-execution-prompt.md
```

Expected: first command has no matches; second command matches every required boundary.

- [x] **Step 3: Record migration provenance without rewriting history**

Update the current-path facts in `docs/LEGACY_INVENTORY.md`; append a new `LOG-20260722-*` entry to `docs/PROJECT_LOG.md`; update the three planning files. Do not edit existing log entries.

### Task 4: Validate and commit from the actual new directory

**Files:**
- Verify all Task 3 files.

**Interfaces:**
- Consumes: migrated repository, rebuilt environments, completed handoff.
- Produces: final clean migration commit and reproducible evidence.

- [x] **Step 1: Run the complete CPU quality gate**

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy
git diff --check
UV_DEFAULT_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple uv lock --check
```

Expected: all tests pass, Ruff/mypy pass, no diff errors, lock unchanged.

- [x] **Step 2: Verify path, history, remote, ignored evidence, and benchmark link**

```bash
test ! -e /home/tjk/myProjects/internship-projects/.worktrees/retail-agent-ops
test "$(git rev-parse --show-toplevel)" = "/home/tjk/myProjects/internship-projects/retail-agent-ops"
test "$(cd "$(git rev-parse --git-dir)" && pwd -P)" = "$(cd "$(git rev-parse --git-common-dir)" && pwd -P)"
git merge-base --is-ancestor 59cc1b5 HEAD
test -z "$(git remote)"
git check-ignore -q reports/retail_ops/v1/qualification-r1-final/release-go/release.json
readlink -f data/external_repos
```

Expected: every command succeeds and the link resolves to the original external checkout.

- [x] **Step 3: Commit the handoff and migration record**

```bash
git add docs/handoffs/2026-07-22-r2-codex-execution-prompt.md docs/LEGACY_INVENTORY.md docs/PROJECT_LOG.md task_plan.md findings.md progress.md
git commit -m "docs: hand off RetailAgentOps R2 execution"
```

- [x] **Step 4: Re-run the final verification on actual HEAD**

Repeat the complete CPU gate and `git status --short --branch`.

Expected: clean branch at the final migration/handoff commit. Only after this succeeds may the exact `/tmp/retail-agent-ops-migration.*` rollback directory be removed.
