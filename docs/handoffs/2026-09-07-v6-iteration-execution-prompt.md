# 交接：v6 迭代（空生成诊断 + rtc_stepwise 请求修复 → 冲击 v1.3 GO）——下一窗口执行提示词

**日期**：2026-09-07
**性质**：B-4/v5 收口（LOG-20260907-01）后的下一窗口执行入口。
**决策记录**：观测 8 判定 NO-GO（11/12）后，用户裁定（2026-09-07）如实收官、候选不变
（sft-008）；空生成毛刺与 rtc_stepwise 请求缺陷列为**已诊断迭代入口**，需新预注册 + 全价。
**执行者**：新窗口的 coding agent；允许 subagent（读数与结论须抽查验证）。
**授权状态**：GPU 与 mimo API 沿用既有授权（gpu-5090、mimo-v2.5，费用逐次记账）；
封存观测次数不受限（用户 2026-08-17），但结果永远不得反馈进开发。

---

## 0. 一句话背景

v5 数据重建（难度分层 + margin 0 档 + 口径 A + max_steps 7）把项目拖到**距 v1.3 GO
只差 2 次 format 滑步**的位置：封存观测 8（246 条）candidate 246/246 满分、政策违规
**0**（绝对门 `policy_violation_count_max=0` 历史首过——B-4 立项主张「5.0× 难度偏移
是政策违规根因」被观测证实）、ci_lower +0.3699、OOD 1.0000/+0.3833、探针 15/15；
**唯一失败门 `invalid_call_count=2`**：两条任务第 1 步模型空生成（agent 恢复、任务
仍成功，0.8%）。下一轮的全部价值 = 修掉两个已诊断缺陷后，用同样的门再测一次。

## 1. 先读这些（按顺序）

1. `AGENTS.md`（边界 + 固定流程 + cpolar 运维入口）
2. `docs/HOLDOUT_LEDGER.md` 观测 8（v5 口径首观测；v1 口径终止于观测 7）
3. `docs/PROJECT_LOG.md` LOG-20260907-01
4. `findings.md` 2026-09-07 各节（A-2/A-3 实现、A-4 两连击、观测 8 判定）
5. `docs/PITFALLS.md` §二 #25/#26（空生成毛刺、rtc_stepwise 请求缺陷——本轮新增）
6. `docs/RESUME_EVIDENCE.md` §1.11（对外口径）与 §2 不可写清单新行
7. `task_plan.md` Current Task（v5 预注册原文 + 执行状态终稿——v6 预注册的结构范本）
8. `src/veritool_rl/retail_ops/domain/formal_tasks.py` v5 段（`_V5_*` 常量、
   `_v5_bucket_allocation`、`build_v5_task_set`——v6 的结构起点）

## 2. 已冻结决策（遇到不要再问，也不要重开）

| 决策 | 结论 | 出处 |
|---|---|---|
| v1.3 阈值 | `policy_violation_count_max=0`、`success_delta_ci_lower_min=+0.02` 冻结不变 | LOG-20260904-02 |
| 发布候选 | `sft-008` 保持；`sft-v5-001` NO-GO 不换候选 | 观测 8、用户 2026-09-07 |
| v5 判定处置 | 如实收官；空生成不向封存集重掷骰子 | 用户 2026-09-07 |
| rtc_stepwise（v5 内） | 0.643 分桶门按现状放行；15 条 Oracle 兜底 | 用户 2026-09-07 |
| v1.4 配对 schema | 不启用（沿用 1.3）；v6 判定是否启用**单独问用户** | A-0（2026-09-06） |
| v1 口径 | 终止于观测 7；v5/v6 口径自观测 8/9 起（同台账分节） | HOLDOUT_LEDGER |
| 探针 / OOD 分片 | 逐字节不动（跨候选可比性保留） | 交接 v5 §2 沿袭 |

## 3. 资源与凭据 + 本轮新增 operational 教训（全部真踩过）

### 3.1 远端（gpu-5090）

- 仓库 `/mnt/aidata/tongjiakai/retail-agent-ops`，代码与本地同步（`f6d7cf5` 系）；
  同步走 `git push ssh://gpu-5090/… main:refs/heads/<tmp>` + 远端
  `git merge --ff-only <tmp>`（本轮验证可用，本轮后新增 ssh 会话挂起问题见 §3.3-6）。
- `models/Qwen3-4B-pinned`、`models/Qwen3-4B-sft-v5-001-merged`（+provenance
  sidecar，merged_revision `ff1a88db…`）、v5 私有根（train-export/dev-sft/冻结三件
  +sealed-eval 两份轨迹）均在远端。
- v5 评测脚本先例：`/mnt/aidata/tongjiakai/v5-eval-fix.sh`（`--input_dir` 不可漏——
  formal 管线全部要求私有根/任务目录入参）。

### 3.2 mimo API（**必读：会话头已是硬要求**）

- **2026-09-07 起 opencode zen 强制 `x-opencode-session` 头**（400 MissingSessionID）。
  客户端已支持：设 env `TEACHER_LLM_EXTRA_HEADERS_JSON='{"x-opencode-session": "<uuid>"}'`
  （每次采集用新 uuid）；**漏设 = 26 条 transport_exhausted 那种静默全灭**。
- 周用量限制存在（GoUsageLimitError，7 天窗）：大规模采集前先做 1 次直连试探
  （~250 tok）；429 = 停下等重置，**不要**改路由或换素材。
- `.env` 本地有 mimo/DeepSeek 凭据；`--dry_run`/小样本先行（PITFALLS #5）。

### 3.3 本窗口 operational 教训（全部真踩过，逐条生效）

1. **管道吞退出码**（本窗口犯过两次）：`cmd | tail` 后 `$?` 是 tail 的；用
   `set -o pipefail` 或显式逐命令检查。
2. **CLI 的 summary.json 落 `--output_dir`**（reports/），不在私有根——链式脚本
   第一次就查错了位置。
3. **config 键白名单是精确匹配**：新配置键要走 `_require_config_keys` 的
   `optional=` 参数（`max_steps` 已加）；pipeline 构造代码必须把键**传入**冻结配置
   模型（本轮 max_steps 被构造层丢过，validator 以「got 5」当场报错——fail-closed）。
4. **teacher 失败重试**：删除失败 evidence 文件 + 同 attempt_id 续跑即可（checkpoint
   只记 accepted）；summary 会在收尾重写。
5. **zen 代理瞬断**呈 5 分钟窗爆发（26 条/5 min），之后自愈——遇到成串
   transport_exhausted 先测端点再归因，别急着改代码。
6. **ssh 远端 nohup 挂起**：`setsid nohup … < /dev/null` 仍可能吃满本地 ssh 超时——
   发射后用独立短 ssh 验证进程与日志，不要依赖该命令的回显。

## 4. v5 收口事实（v6 的起点）

- 冻结数据：`retail_ops_v5_20260906`（588/198/246；覆盖表
  `reports/retail_ops/v1/r12-v5/coverage-v5-001/coverage.json`：5.0×→0.926）。
- 候选：`sft-v5-001`（NO-GO，不换候选）；adapter 7 文件哈希与 merged 模型
  （`ff1a88db…`）见 `configs/retail_ops/evaluate/retail_ops_v5_holdout_merged_candidate.yaml`。
- 观测 8 全套产物：`reports/retail_ops/v1/r12-v5/`（本地）+
  远端 `data/private/.../sealed-eval/`（两份完整轨迹）。
- 测试基线：**1515**（作者环境）/ 干净 clone **1466/49/0**；新增测试必须同步四文档
  （README/README.en/CLAUDE/RESUME_EVIDENCE——算术守卫会算总账）。

## 5. 下一迭代（v6）执行计划

### V6-0 与用户确认的方案点（正式稿确认后才能动）

1. **范围**：单变量修 rtc_stepwise 请求缺陷（`_v4_user_request_fallback` 的
   RTC_STEPWISE 分支改用 cancel 枚举 reason），还是**同时**纳入空生成的诊断产出？
   ——建议：先诊断（V6-1，不占观测），诊断若指向数据侧可修项则一并入 v6；若指向
   引擎栈则单独评估（不与数据修复捆绑）。
2. **dataset_version**：`retail_ops_v6_<日期>`（版本↔内容双射；v5 冻结集逐字节不动）。
3. **判读规则**：沿用 v1.3 十二门 + 探针条件（每点 ≥0.875），阈值一个字不改；
   分支表在预注册时冻结（注意 v5 的教训：**分支形状要覆盖「11/12 但非绝对门」的
   组合**，别再写「任一门 FAIL → 修坏」的单句）。

### V6-1 空生成根因诊断（不占观测，本地 CPU/GPU 可做）

- 已知事实：2 条同为 `refund_denied_duplicate`、同在第 1 步、raw_text 空、
  贪心解码（temperature 0）。候选根因：(a) NF4 非确定性下的退化前向；(b) 渲染栈
  在特定上下文上的边界 bug；(c) 模型本身的低频行为。
- 手段：在 **dev 面 / v5 训练面**（非封存）上复现——重放同 family 渲染提示词 N 次
  （NF4 多 seed），统计空生成频率；检查 trainer/eval 的 max_seq_len 与停止符处理。
  **禁止**用封存集提示词做诊断输入。
- 产出：根因结论 + 是否可修的判定；不可修则如实记录（毛刺 0.8% 的残差风险进
  预注册的预期段落）。

### V6-2 rtc_stepwise 请求修复（一行生成器改动 + TDD）

- `_v4_user_request_fallback` 的 RTC_STEPWISE 分支：reason 从 `_REASONS` 轮转改为
  gold 同源的 `_V4_CANCEL_REASONS[0]`（与 `cancel_other` 的 gold 一致）；同步检查
  v4 老版本**不受影响**（版本键控，v6 才生效）。
- 测试：请求 reason ∈ cancel 枚举、与 gold cancel reason 一致；v4 版本重建逐位不变。

### V6-3 冻结与采集（本地 CPU + mimo）

`formal_freeze` v6 → 覆盖表断言（沿用 `assert_exact_quotas_v5` 全部断言）→
teacher 全量（~588 任务，**必设会话头**；0.80 分桶门 + **新增自查：请求陈述的
reason/fact 必须落在该工具枚举域内**——PITFALLS #26 的教训前移成采集前断言）→
train_export（措辞 ×3 沿用 bank-v4）→ dev_sft_export。

### V6-4 训练 + 全套评测 + 观测 9 + v1.3 判定（GPU，命令逐条确认）

与 v5 同构（运行清单逐字声明进 task_plan；产物前缀建议 `reports/retail_ops/v1/r13-v6/`）：
训练（~35 min）→ dev 配对 → 探针 → OOD v2/v4（base 若 commit 未变可沿用
`ood-v2-base-001`/`ood-v4-base-001`——**commit 变了就必须重跑 base**，配对字段含
code_commit）→ merge → 封存观测 9（base/candidate 两侧）→ v1.3 release。
成本预估：GPU ~2h + teacher ~$0.05 + 观测 9 消耗。

### 判读（预注册正式稿确认后冻结，一个字不改）

v1.3 十二门全 PASS 且探针每点 ≥0.875 → **换候选 `sft-v6-001`**（项目首个 v1.3 GO）；
任一门 FAIL → 如实收官（分支细则注意覆盖 v5 的形状缺口）；边界组合 → 升级用户确认。
无论哪种结果：不重跑、不换素材、台账同日收口。

## 6. 硬边界（全部沿用）

- 封存结果永远不反馈进开发；已证伪方向（PITFALLS §三 9 条）不得原样重试；
  v1–v5 冻结契约与既有数据集逐字节不动；v6 一切新契约走新 dataset_version；
- 判读规则与运行清单先于观测提交；不为数字好看改任务/关守卫/挑读数；
- 每条远程 GPU 命令给出工作目录 / 物理 GPU / 预计时长 / 产物；API 费用逐次记账；
  Python 统一 uv；文档默认简体中文；origin push 已批准（CI 全绿后推）。

## 7. 验收（每轮收口全绿）

```bash
.venv/bin/pytest -q                    # 先于 push
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy
env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check
git diff --check
.venv/bin/python scripts/ci/verify_qualification_chain.py
.venv/bin/python scripts/ci/audit_public_release.py
# 干净 clone 实跑 + 文档基线同步（测试数变了必须四文档同步）
```

## 8. 故障手册指针

- zen 会话头/周限/瞬断：本文件 §3.2 + findings 2026-09-07
- max_steps 键契约/构造转发：`_require_config_keys` optional 参数 +
  `_declared_max_steps`（漏传会以「got 5」fail-closed）
- cpolar 拒连：`cpolar-ssh-update`；驱动卡死：E2 交接 §5.5
- teacher/bank 采集失败：LOG-20260905-03 与 bank-004/005 先例
- 干净 clone 基线：四文档同步 + 算术守卫（passed+skipped==collected）

## 9. 低优先级搁置项（有记录的决策，非欠账）

去掉 NF4 的延迟验证（需再耗观测）、跨 benchmark（τ²-bench/ToolSandbox）、
压测/长稳/混沌、多 seed 方差区间、真实分布采样评测集（泛化根治项，最大最贵）。
