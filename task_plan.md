# Task Plan: RetailAgentOps

## Goal

在 12 周内交付可公开、可复现、可面试解释的零售工具 Agent 单卡适配与发布流水线，并在前 6 周完成首个工程闭环。

## Current Phase

R3「单卡适配与服务 v1」。Task 1（SFT 训练接入与首次真实 QLoRA-SFT）已完成（`e9cb95b`），
产出候选 adapter `reports/retail_ops/v1/r3/sft-001/adapter/`。当前任务是 R3 Task 2：
**对 60 条 dev 任务做候选评测，与已有 Qwen3-4B base 配对比较**。正式 120 条 holdout、
release GO/NO-GO 与 serve 仍不在范围内。

## Current Task

- 输入：候选 adapter（7 文件，`adapter_model.safetensors` =
  `34544fac3ec9afae10f9212f730aaf275bc86b536ffaeecfb4fe0eeb745e8748`）；已有 Qwen3-4B base
  证据（`qwen3-4b-dev-base-001`，task_success=0.80、policy_violation_rate=0.133、
  schema_valid_rate=0.781、invalid_call_rate=0.219、recovery_success=0.5）；同一份已哈希
  校验的模型（revision `8cd0101f...`）；冻结的 60 条 dev 与公开 dev manifest。
- 输出：`formal_dev_candidate` 流水线与候选证据契约（含 adapter provenance 锁定）、配对
  比较函数与报告、真实 GPU 候选评测结果，以及与 base 的逐指标对照。
- 非目标：**不打开或评测正式 120 条 holdout**、不调用 `evaluate_authorized_holdout`/
  `sealed_evaluation.py`、不做 release GO/NO-GO 决策、不部署 serve、不触碰 BFCL 200 条；
  不重训、不调超参、不改 240/60 配额；不自动 push/merge。
- 关键约束（已核实的代码事实）：`BaseRunEvidence`/`BaseEvaluationConfig` **一个字段都不能加**
  ——`_content_id` 把除 `run_id`/`schema_version` 外的全部字段算进自哈希，加字段会让已有两份
  R2 base 证据（`qwen3-1.7b`/`qwen3-4b-dev-base-001`）的 `run_id` 复算失败。因此候选契约必须
  用子类扩展，且 base 路径行为逐字节不变。
- 失败模式：候选跑在未哈希校验的 adapter 上；base/candidate 用了不同 bundle/manifest/parser/
  seed/预算/生成参数导致比较无效；候选证据能被当作 base 证据加载（或反之）；base 路径因重构
  发生行为漂移；把 n=60 的小幅差异说成稳定提升。
- [x] A：`AdapterArtifact` + `CandidateEvaluationConfig`/`CandidateRunEvidence` 子类契约；
      `_require_backend_matches_pin` 改为**双向**绑定（base 拒绝任何 adapter；candidate
      拒绝缺失或不符的 adapter）。
- [x] B：抽出 `require_dev_evaluation_preconditions` 与 `measure_dev_run` 两个共用核心；
      两份真实 R2 base 证据仍能加载且 `run_id` 复算一致（已固化为测试）。
- [x] C：`evaluate_formal_dev_candidate` + `load_candidate_run_evidence`；候选证据与 base
      证据互不可加载（严格模型 + 必填 adapter）。
- [x] D：`compare_dev_runs` 校验 15 项配对字段 + model + generation + task_count，任一不符
      即抛 `ComparisonError`，不给出带警告的无效 delta。
- [x] E：CLI `pipeline: formal_dev_candidate` 分派（默认后端工厂真实挂载 adapter）+
      `configs/retail_ops_v1_r3_qwen3_4b_candidate.yaml`（model 段与 base config 逐字段相同）。
- [x] F：治理测试补充 2 项（候选 config 同时锁定 model+adapter 逐文件哈希且 model 段必须
      与 base config 相同；候选私有/公开产物路径仍被 ignore）。
- [ ] G：远端同步 + 真实 GPU 候选评测（60 条 dev，与 base 同预算）。
- [ ] H：产物同步回本地、哈希核对、配对比较报告与记录。
- 验收命令：`.venv/bin/pytest -q`、`.venv/bin/ruff check .`、`.venv/bin/mypy`、
  `env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check`、`git diff --check`；
  另需证明两份既有 R2 base 证据加载不受影响，且候选运行的 bundle/manifest/parser/seed/
  预算/生成参数与 base 逐字段一致。

## Task Rules

- 本文件只跟踪当前任务；长期阶段状态以 `docs/EXECUTION_PLAN.md` 为准。
- 新任务开始时重写 Current Task，保留已完成任务的摘要到 `progress.md`。
- 输入、输出、非目标、失败模式和验收命令不完整时不得开始实现。
- GPU、API、数据下载和公开发布必须显式标注授权状态。

## Errors

| Date | Error | Resolution |
|---|---|---|
| 2026-07-20 | 新 worktree 缺 BFCL evaluator 环境和 ignored benchmark checkout | 建立独立 evaluator venv，并通过相对软链接共享固定 checkout |
| 2026-07-20 | 本机镜像变量机械改写 `uv.lock` | 反向应用仅 lock diff，后续命令显式清除 `UV_INDEX_URL` |
| 2026-07-20 | 清除 `UV_INDEX_URL` 后 `uv run` 仍按全局索引改写 `uv.lock` | 最终验收直接调用已冻结 `.venv/bin/*`，提交前精确回退 lock diff |
| 2026-07-20 | 新治理测试被 Ruff I001 拒绝双空行 | 按 import sorter 的最小 diff 删除一行空白后重跑 |
| 2026-07-21 | Task 6 规格检索误写为不存在的 `docs/SPEC.md` | 确认产品契约实际位于根目录 `SPEC.md`，后续使用正确路径 |
| 2026-07-21 | Task 6 首次 GREEN 加载 `run.json` 时错误要求 artifact map 保留插入顺序 | canonical JSON 会排序 object key；改为验证精确 key 集合，确定性由写入器保证 |
| 2026-07-21 | Task 6 `ruff format --check` 报告 4 个变更文件需格式化 | 使用仓库 `.venv/bin/ruff format` 仅格式化本任务 Python 文件后重跑验证 |
| 2026-07-21 | Task 7 `ruff format --check` 报告 `release.py` 需格式化 | 使用仓库 formatter 处理该文件并重跑 focused/Ruff/diff |
| 2026-07-21 | Task 8 初查误探测不存在的 `src/veritool_rl/config.py` 与 `tests/test_cli.py` | 确认配置加载在 `veritool_rl.cli`，产品 CLI 测试按计划新建 `test_retail_ops_cli.py` |
| 2026-07-21 | Task 8 `uv lock --check` 报告锁文件过期，`UV_INDEX_URL` 仍被全局默认索引覆盖 | 清除 3506 行镜像 URL 机械 diff，改用 `UV_DEFAULT_INDEX` 对齐现有 lock 索引；离线解析后 `uv.lock` 字节不变 |
| 2026-07-21 | Task 8 planning 记录补丁因表格行顺序假设错误未应用 | 用 `rg` 定位实际行后按精确上下文重新应用，未影响产品文件 |
| 2026-07-21 | Task 8 `ruff format --check` 报告 CLI 测试需格式化 | 仅格式化本任务测试文件并重跑 focused/Ruff/diff |
| 2026-07-21 | Task 9 首次全门禁发现 `product_cli.py` import 未排序且 service/test 需格式化 | 对本任务文件执行 Ruff import fix/format 后重跑 selected/full 相关门禁 |
| 2026-07-21 | Task 9 误将全仓 `ruff format --check .` 当作验收项，发现 35 个既有文件未采用当前 formatter | 不扩大本阶段 diff；仅检查本任务 Python 文件，继续执行项目规定的 `.venv/bin/ruff check .` |
| 2026-07-21 | Task 10 新鲜 qualification 证据树在最终状态审计中显示为未跟踪文件 | 新增失败治理断言并将 `/reports/retail_ops/` 纳入产品运行产物 ignore 边界，保留本地证据但不提交 |
| 2026-07-21 | Task 10 完成前 targeted format check 报告两个新增测试需格式化 | 仅格式化 `test_retail_ops_e2e.py` 与 `test_project_governance.py`，随后从头重跑完整质量门 |
| 2026-07-22 | `using-superpowers` 的 Codex reference 首次按错误的技能根路径读取失败 | 按 SKILL.md 相对路径改读 `skills/using-superpowers/references/codex-tools.md`，已恢复完整指令 |
| 2026-07-22 | 迁移准备提交前 `git diff --cached --check` 报告设计文件 EOF 多一个空行，但 shell 未启用 fail-fast 仍完成提交 | 在最终文档提交中删除多余空行；后续提交命令使用 `set -e` 或显式检查退出码后再 commit |
| 2026-07-22 | 执行环境拒绝用 `rm -rf` 清理迁移回滚目录 | 未删除任何内容；改用 `gio trash` 将精确目录移入系统回收站，并验证原 `/tmp` 路径不存在 |
| 2026-07-22 | R2 分支基线 `uv lock --check` 因用户级清华镜像 URL 从旧别名规范化为新域名而要求 4336 行纯 URL 重写 | 临时目录差异确认版本/哈希不变；`--default-index https://pypi.tuna.tsinghua.edu.cn/simple` 立即通过，R2 将用项目级索引固定现有 lock，避免机械重写 |
| 2026-07-22 | R2 family 轴核对首次探测了不存在的 `domains/retail_ops/v1/policies/refund.yaml`，随后 zsh 未匹配 glob 中止批量查看 | 改读实际扁平文件 `domains/retail_ops/v1/policies.yaml`、`tools.yaml`、`bundle.yaml`；确认仅使用四个批准退款原因且未改文件 |
| 2026-07-22 | 两次跨文件文档补丁因 `task_plan.md` 既有错误行与预期上下文不一致而整体拒绝 | 先读取精确表格，再按目标文件拆分应用；补丁原子失败，未产生半写入或产品内容损坏 |
| 2026-07-22 | 新增治理测试仍因目标短语跨 Markdown 换行失败 | 保留语义不变并合并为单行可机器检查契约，再重跑 focused test |
| 2026-07-22 | 一次双引号 `rg` 模式中的反引号被 zsh 当作命令替换，并且一次 reviewer wait 使用了低于工具下限的 1 秒 timeout | 检索模式改用安全单引号/无反引号形式；等待调用改为工具允许的至少 10 秒，均未修改产品状态 |
| 2026-07-22 | 计划审阅收口记录的跨文件补丁因 `progress.md` 目标句与实际表述不同而整体拒绝 | 读取文件尾部后按文件拆分应用，未产生半写入 |
| 2026-07-22 | R2 Task 1 实现代理完成 RED 和初版实现后因所选模型容量不足退出 | 保留全部未提交改动，换用新 worker 接手 focused GREEN、修复、全门禁和提交；判定为代理基础设施故障而非仓库回归 |
| 2026-07-22 | Task 1 独立审查发现 derivation 未绑定实际政策状态、quota 接受重复变体，且 catalog/420 条环境验证未固化为测试 | 判定 NOT PASS；派回实现代理先补 deadline/owner/status/duplicate/tamper/catalog/environment RED，再强化真值投影和 integrity 校验，复审通过前不进入 Task 2 |
| 2026-07-22 | Task 2 独立审查用攻击脚本复现 public value 泄漏、provenance 断链、重复 variant、非原子双根、symlink 越界和可伪造授权 token 六项 Important | 判定 NOT PASS；统一补固定 Literal、verified dataset、private provenance/variant 重建、failure-atomic staging、trusted-root no-follow 读取和注册 capability 的 RED/GREEN，复审通过前不进入 Task 3 |
| 2026-07-22 | Task 2 修复复审代理的最终输出被平台 cybersecurity 风险过滤器误拦截 | 保留已完成的代码与 284 个测试证据，把复审改写为不描述利用步骤的“数据治理契约回归审查”并复用同一只读 reviewer |
| 2026-07-22 | Task 3 只读接口检索误读不存在的 `src/veritool_rl/agent/base.py`，导致同一 `&&` 链后的 Qwen 查看未执行 | 改读实际 `agent/qwen.py`、`agent/policy.py`、`agent/runner.py`；未修改代码或环境 |
| 2026-08-05 | 20 条真实 DeepSeek smoke（会话临时脚本）发现 `run_episode`（`agent/runner.py`）组装的多轮消息历史不是合法 OpenAI wire format：`tool_calls[].function.arguments` 是原始 dict 而非 JSON 字符串，且 assistant `tool_calls[]`/`tool` 消息缺 `id`/`tool_call_id`；本地 Qwen backend 从未触发过 | 判定为 Task 4 前置阻塞：先在 `agent/runner.py` 用 TDD 修复两处 wire format bug 并补回归测试，再开始 `teacher_data.py` 实现；smoke 脚本本身未提交，详见 `docs/PROJECT_LOG.md` LOG-20260805-07 |
| 2026-08-05 | Task 6 env 边界测试最初用 `monkeypatch.setattr("os.environ", HostileMapping())` 整体替换 `os.environ`，导致 pytest 自身内部读取 `COLUMNS`/`PY_COLORS` 时炸穿并使整个 session 内部报错，而非产品代码问题 | 改用 `monkeypatch.setenv("TEACHER_LLM_PROVIDER", "not a provider name!!")` 只毒化 `load_teacher_route` 真正会读的具体 key，不整体替换 `os.environ`；同时确认没有任何产品代码本身依赖 `COLUMNS`/`PY_COLORS` |
| 2026-08-05 | Task 6 首个 `--input_dir` 覆盖测试误传相对路径 `"configs/retail_ops_v1_build.yaml"`，但该测试用的 `workspace` fixture 已 `monkeypatch.chdir` 到隔离 tmp 根，仓库真实 `configs/` 在那里不存在 | 改用 `Path(__file__).resolve().parents[1]`（`REPO_ROOT`）拼出绝对路径引用仓库里真正提交的 config 文件，不依赖当前 CWD |
| 2026-08-05 | Task 6 修复轮首次派发因触发本会话 API 用量限制中断，未产生任何改动（工作树、报告文件均未受影响） | 原样重新恢复同一 implementer agent（未改变任务或方案），重试后成功完成 |
| 2026-08-06 | Task 7 整分支审查发现 `formal_dev_base` 独立加载 `dev.json` 未走 `load_verified_formal_dataset`，跳过五维隔离交叉断言；`export_formal_train` 接收 `TeacherCollectionConfig` 却从未读取，teacher 证据仅凭 `task_id` 匹配记录；`code_commit` 可能来自脏工作树且 git 子进程无超时 | 三项均用 TDD 修复：`_run_formal_dev_base` 改为先 `load_verified_formal_dataset` 再取其 `dev_manifest`；新增 `_require_evidence_binds_record` 在 export 循环内核对 `task_fingerprint`/`trajectory.task`/`dataset_version`/`bundle_sha256`/`manifest_sha256`，不匹配即硬失败（非静默回退）；`_current_code_commit` 先查 `git status --porcelain` 非空即拒绝，git 调用统一加 30s 超时；复审确认 3 项均已解决、3 个关键判断均合理（`c4d7fdc`） |
| 2026-08-06 | Task 7 复审发现 `manifests/retail_ops/v1/` 未被 `.gitignore` 覆盖（不同于 `data/`/`models/`/`reports/retail_ops/`），导致 `formal_freeze` 产出的公开 manifest 若不提交，会被新的脏树检查判定为"未跟踪=脏"从而阻塞 `formal_dev_base` | 非代码缺陷，是正式执行顺序的前置条件；已写入 `docs/handoffs/2026-08-06-r2-external-run-commands.md` 第 0 节，要求 `formal_freeze` 产出必须先提交再进入 `formal_dev_base` |

## Maintenance: Codex 启动简化

- [x] 确认 `AGENTS.md` 已覆盖 Codex 接管和记录协议
- [x] 移除冗余 `.codex/config.toml` 与对应 fallback 测试
- [x] 将 linked worktree 原地转为独立 Git checkout
- [x] 验证环境、ignored benchmark 链接、质量门和 Codex 启动
- [x] 提交结果，保持 R1 规格复核门不变
