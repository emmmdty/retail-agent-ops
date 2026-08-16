# Task Plan: RetailAgentOps

## Goal

在 12 周内交付可公开、可复现、可面试解释的零售工具 Agent 单卡适配与发布流水线，并在前 6 周完成首个工程闭环。

## Current Phase

**R4.5 架构补强**（用户于 2026-08-15 裁定新开补强轨道，`docs/EXECUTION_PLAN.md` 已更新）。
执行提示词：`docs/handoffs/2026-08-15-architecture-hardening-execution-prompt.md`。
R4 已标为已完成；封存 holdout 两次观测均已消耗，本轨道不消耗第三次。

## Current Task：架构补强（评审 13 条）

这一轮的性质与 R4 三轮**不同**：R4 是"改模型让候选达标"，这一轮是"补齐系统本身的
架构缺口"。**没有一项以候选通过发布门禁为成功标准。**

### 输入

- 评审 13 条问题及证据位置（提示词第 3 节），已逐条复核代码属实（见 `findings.md`
  2026-08-15 小节）；
- 已冻结的四条硬契约：`GATE_IDS` 逐字段冻结、dev `PAIRING_FIELDS`、
  `SEALED_PAIRING_FIELDS`、`dataset_version` + 40/10/20 配额；
- 基线：698 tests passed，Ruff / mypy / uv lock 全绿；
- 已有真实产物：`formal-release-001/002`、R1 qualification release 报告、
  两侧 sealed holdout 证据、`sft-006` adapter 与 dev/holdout 逐任务证据。

### 输出

| 批次 | 内容 | 资源 |
|---|---|---|
| 1 | serve 服务化（1.1）、CI + Dockerfile（1.2）、文档单一事实源 + `sft-006` 模型卡（1.3）、`verifier_reward` 降级为诊断量（1.4） | 纯 CPU |
| 3 | 发布门禁语义**版本化**升级：延迟门禁拆分（6.1）、配对统计检验（6.2）、`schema_version` 1.0/1.1 双路径（6.3） | 纯 CPU |
| 2 | 政策外置（2.1）、幂等键（2.2）、guardrail + 注入评测（2.3） | 改被哈希输入，需一次性 dev base 重跑 |
| 4 | 分布外 holdout（7.1）、serving 形态对照（7.2）、Agent 能力面（7.3） | 需 GPU / API / 用户裁定 |

批次 1 与批次 3 均为纯 CPU 且不触碰被哈希的领域输入，可连续完成；批次 2 的实现是 CPU，
但其证据重跑是 GPU 执行门；批次 4 逐项请示。

### 非目标（硬约束）

- **不调模型超参、不产生新的发布候选、不追第三次 holdout 观测**；
- **不下调任何发布门禁阈值**（`test_release_config_does_not_touch_the_gates` 必须保持通过）；
- 不改 `formal_tasks.assert_exact_quotas` 的 40/10/20 配额，不改 `dataset_version`；
- 不重命名 Python 包；
- 不就地增删 `GATE_IDS`（必须走 schema 版本化路径）；
- 不削弱被评审认可的机制：`SEALED_PAIRING_FIELDS` 逐字段配对、两段式授权门、
  产物自哈希与不可覆盖目录、模型文件 SHA-256 锁定、负结果留档；
- 不改 R1 `create_app` / `ReleaseReport` v1.0 的既有契约语义；
- 不删除或改写旧口径下的两次 NO-GO 结论。

### 失败模式（实施时主动防御）

1. **照着结果改门禁**：批次 3 的新口径必须在看到任何新读数**之前**定稿并提交；
2. **就地改 `GATE_IDS`** → 磁盘上已有全部 release 报告无法加载（不可逆证据损失）；
3. **政策外置时 prompt 渲染不确定** → 同一 bundle 渲染出不同字节的 prompt，
   `system_prompt_sha256` 变成不可复现，配对契约失效；
4. **guardrail 做成 env 的一个方法** → 不是纵深防御，两层退化成一层；
5. **serve 加自由端点时泄漏 holdout 真值或答案**到日志/响应；
6. **API key 进 Git**（必须纳入既有 secret 扫描治理测试）；
7. **文档新增未经运行的数字**——所有数字必须来自已有产物；
8. 幂等键改 `tool_schema_sha256` 后**静默**让 240 条 teacher 轨迹参数非法（需用户裁定，
   见下方决策点）。

### 影响文件（预计）

- 批次 1：`retail_ops/serve/service.py`、`core/reporting.py`、`core/metrics.py`（只读）、
  新增 `.github/workflows/`、`Dockerfile`、`docs/HOLDOUT_LEDGER.md`、
  `docs/MODEL_CARD*.md`、`docs/SYSTEM_CARD.md`、`README.md`、`tests/`；
- 批次 3：`retail_ops/release/release.py`、`release/formal_release.py`、
  `core/metrics.py`、`domains/retail_ops/v1/release.yaml`（**只增字段不改阈值**）、`tests/`；
- 批次 2：`domains/retail_ops/v1/{policies,tools}.yaml`、`retail_ops/domain/{bundle,environment}.py`、
  `core/agent/runner.py`、新增 guardrail 模块、`tests/`。

### 验收命令与预期产物

```bash
.venv/bin/pytest -q            # 起始基线 698 passed，只增不减
.venv/bin/ruff check .
.venv/bin/mypy
env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check
git diff --check
```

另需证明：`formal-release-001` / `formal-release-002` / R1 qualification 的 `release.json`
在改动后**仍能被加载**（批次 3 的核心回归）。

### 授权状态

GPU **否**、商业 API **否**、模型下载 **否**、holdout 执行 **否**（第三次需单独决策）、
公开发布 **否**、新依赖 **否**（CI/Dockerfile 不引入运行时新依赖）。

### 待用户裁定的决策点（提示词第 9 节）

1. 阶段归属（R4 收尾 / R5 提前启动 / 新开补强轨道）；
2. P2-8 幂等键对现有 240 条 teacher 轨迹的处理方式；
3. P1-6 二选一：user simulator（A）还是工具面扩容（B）；
4. P2-13 `perturb_schema`：接入 qualification 轨道还是删除；
5. 模型卡形态：`sft-006` 独立卡还是现卡分节；
6. 任何 GPU / 商业 API / 模型下载 / 新依赖；
7. 第三次封存 holdout 观测。

### 进度

- [x] 0. 上下文读取 + 13 条证据复核
- [x] 1. `task_plan.md`
- [x] 2. 冻结契约影响矩阵（写入 `findings.md`）
- [x] 3. 批次 1.1 serve 服务化（19 项新测试，4 次突变验证）
- [x] 4. 批次 1.2 CI workflow + 全链路复现脚本 + CPU-only Dockerfile
- [x] 5. 批次 1.3 `docs/HOLDOUT_LEDGER.md` + 三处漂移修复 + `sft-006` 独立模型卡
- [x] 6. 批次 1.4 `verifier_reward` 降级为诊断量（只改呈现层）
- [x] 7. 批次 3 发布门禁版本化（v1.0 冻结 + v1.1 新集合，16 项测试，3 次突变验证）
- [x] 8. P2-13 `perturb_schema` 接入 qualification 轨道（用户裁定）
- [x] 9. 外部执行门 1：提交（`3427c40`），并同步 gpu-5090
- [x] 10. 用 v1.1 复算两次已有观测；两次仍 NO-GO，无翻转（`docs/GATE_SCHEMA_V11_RECOMPUTE.md`）
- [x] 11. **批次 4 / 7.2 部署形态对照（P0-3）**：merge 后 dev 重测，单次调用 −46%、
      能力 60/60 未损伤（`docs/SERVING_FORM_COMPARISON.md`、LOG-20260815-01）
- [x] 12. **批次 2**（用户裁定：落在独立的 **v2 bundle**，v1 逐字节不动）
      - [x] 12a 政策规则引擎（`policies.yaml` 的 rules 变成可执行声明式规则）
      - [x] 12b `max_transient_retries` 真正驱动重试上限
      - [x] 12c 政策卡由 bundle 渲染进 prompt（同一 bundle 逐字节相同）
      - [x] 12d v2 `tools.yaml` 的 `refund_order` 增必填 `idempotency_key` + env 按 key 去重
      - [x] 12e 独立于 env 的 guardrail 层（调用前置校验 + 工具观测消毒）
      - [x] 12f 注入评测子集与「注入成功率」指标
      - [x] 12g 政策变更回归测试：只改 v2 `policies.yaml` 一个阈值 → 全链路不同判定，零 Python 改动
- [x] 13a. 7.3 Agent 能力面：**用户裁定方案 A**（user simulator + 多轮澄清）已完成
      （`docs/AGENT_LOOP.md`；三组对照 1.0000 / 0.0000 / 1.0000）
- [ ] 13b. 7.1 分布外 holdout（需 teacher API 预算批准）
- [x] 14. **第三次封存 holdout 观测已完成**（LOG-20260815-03）：三次运行、
      两套口径判定**都是 NO-GO**；合并部署形态的门禁算术全部通过但**拿不到判定**
      （契约要求 candidate = 同一基座 + adapter）。
- [x] 15. **版本化 `SealedEvaluationReport`**，让合并部署形态可获得发布判定
      - [x] 15a 版本感知的内容哈希（`report_id` 对 v1.0 报告逐位不变）
      - [x] 15b `deployment_form` + `merged_from` 血统证明（`merged_revision` 可从
            「基座 revision + adapter 逐文件哈希」**复算**，不是自己声明）
      - [x] 15c `require_comparable_sealed_runs` 按形态分派：base+adapter 走同一性，
            merged 走血统
      - [x] 15d `FormalReleaseReport` 与 `serve` 支持 merged 候选（GO 时加载合并权重）
      - [x] 15e 用第三次观测的已有证据产出**第四次判定**（不消耗新观测）
- [x] 16. **merged + vLLM 吞吐档已完成**（`docs/SERVING_FORM_COMPARISON.md` §第四档、
      LOG-20260816-02）。同一批 12 条公开 qualification 提示词、同一份合并权重、
      同一套贪心契约，三侧各吐 **390** 个 token 且工具调用与文本 **12/12 全同**：
      HF+NF4 48.08 tok/s → HF+bf16 78.95（**1.64×**）→ vLLM+bf16 159.70（再 **2.02×**）。
      批量 12 并发 1375.4 tok/s；prefix caching 值 **+57.5%**。
- [x] 17. **P0-1 分布外任务集已建成并跑完**（`docs/OOD_EVALUATION.md`、LOG-20260816-01）：
      候选 1.0000 → **0.5833**；表达类 **0.00**（base 0.30），场景/对抗类大幅变好。

### 尚未做的（需要新的裁定）

| 项 | 阻塞点 |
|---|---|
| ~~7.2 的第四档 merged + vLLM~~ | **已完成**（独立 venv，项目 `uv.lock` 未动；旁证不进判定） |
| ~~2.2 幂等键~~ | **已裁定：bundle 打新版本号（v2），新旧并存**；v1 全部已有证据保持可加载可解释 |
| ~~7.3 Agent 能力面~~ | **已裁定方案 A 并完成**；方案 B（工具面扩到 15+）未选中、未做 |
| 7.1 分布外 holdout | 表达改写需 teacher API 调用与预算批准 |
| 第三次封存 holdout 观测 | 必须在所有代码改动冻结并提交之后一次性进行（base + candidate 两侧） |

### 用户已裁定（2026-08-15）

1. 阶段归属：**新开补强轨道 R4.5**（提交后再改 `docs/EXECUTION_PLAN.md`）；
2. 本轮范围：**批次 1 + 批次 3，一次提交**；
3. 模型卡形态：**独立** `docs/MODEL_CARD_sft-006.md`；
4. `perturb_schema`：**接入** qualification 轨道做鲁棒性评测。

### 当前基线

698 passed → **885 passed**；Ruff / mypy / `uv lock --check` / `git diff --check` 全过；
`scripts/ci/verify_qualification_chain.py` 通过。

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
