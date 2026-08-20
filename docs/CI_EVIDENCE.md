# CI 真跑证据（R8 / Task B2）

本文件是 GitHub Actions CI **首次真跑**的证据落地。此前 workflow 自 2026-08-16 起已提交，
但仓库无 remote，从未在任何一次 push 上真正运行过（见 `.github/workflows/ci.yml` 头部
注释的历史表述）。2026-08-20 用户授权公开发布门（remote
`https://github.com/emmmdty/retail-agent-ops.git`），CI 首次真跑。

## 首次运行（也是本仓库的第一次 CI 运行）

| 字段 | 值 |
|---|---|
| run URL | https://github.com/emmmdty/retail-agent-ops/actions/runs/32326919228 |
| job URL | https://github.com/emmmdty/retail-agent-ops/actions/runs/32326919228/job/96299938287 |
| commit SHA | `596eee81f4365e15108bde8ddfa3496b67ecf428`（`596eee8`，`feat(r8): D1 第三个 seed 方差刻画`） |
| 分支 | `main` |
| 触发事件 | push |
| 起止 | 2026-08-20T03:04:29Z → 2026-08-20T03:06:45Z |
| 总时长 | 2m16s（job 自身 2m12s） |
| conclusion | **success** |
| runner | `ubuntu-latest`（GitHub 托管） |

## 逐步结果（全部 success）

| # | 步骤 | 起止（UTC） | 时长 |
|---|---|---|---|
| 1 | Set up job | 03:04:33 → 03:04:35 | 2s |
| 2 | Run actions/checkout@v4 | 03:04:35 → 03:04:36 | 1s |
| 3 | 安装 uv | 03:04:36 → 03:04:38 | 2s |
| 4 | 同步冻结依赖（`uv sync --extra dev --frozen`） | 03:04:38 → 03:05:04 | 26s |
| 5 | pytest（`uv run --frozen pytest -q`） | 03:05:04 → 03:06:32 | 88s |
| 6 | ruff lint | 03:06:32 → 03:06:32 | <1s |
| 7 | ruff format --check | 03:06:32 → 03:06:32 | <1s |
| 8 | mypy | 03:06:32 → 03:06:38 | 6s |
| 9 | uv.lock 未漂移 | 03:06:38 → 03:06:38 | <1s |
| 10 | 公开发布审计 | 03:06:38 → 03:06:38 | <1s |
| 11 | CPU qualification 全链路复现 | 03:06:38 → 03:06:41 | 3s |
| 12 | 工作树保持干净 | 03:06:41 → 03:06:42 | 1s |

## 本地等价命令

CI 跑的就是本地全门禁，逐条对应 `.github/workflows/ci.yml` 每一步注释里的本地等价命令：

```bash
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy
env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check
.venv/bin/python scripts/ci/audit_public_release.py
.venv/bin/python scripts/ci/verify_qualification_chain.py
git diff --check
```

本地在 commit `596eee8` 上实测全绿（1171 passed / 67.6s），与 CI 的 88s 一致
（GitHub 2 核 runner 慢约 1.3×，主要差在 pytest 那一步）。

## 已知非阻塞警告

- **Node.js 20 deprecation**：`actions/checkout@v4` 与 `astral-sh/setup-uv@v5`
  仍 target Node.js 20，被 runner 强制升到 Node.js 24。这是 annotation 不是
  failure，不影响 conclusion=success。后续可单独把这两个 action 升到 target
  Node.js 24 的版本，属独立维护项，不阻塞 B2 验收。

## 边界（这条证据不证明什么）

- CI 跑的是 **CPU 全链路与发布审计**，**不包含** GPU 训练、GPU 评测、商业 API
  采集——这些仍在本地/远程 GPU 上由用户逐条授权后运行（见 `task_plan.md`
  授权状态与 R8 D2 运行清单）。
- CI 通过只说明「在 commit `596eee8` 的代码与冻结依赖下，CPU 质量门与
  qualification 全链路在 GitHub 托管 runner 上可复现」，**不**说明模型可上线、
  不说明候选泛化、不说明发布门禁阈值合理——那些是 `RESUME_EVIDENCE.md` 的口径。
- 后续若 CI 出现失败，本文件追加新行；**不删改首次运行这一行**（历史不得改写）。
