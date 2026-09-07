# 交接：v7 迭代（枚举词域覆盖 → 冲击 v1.3 GO）——下一窗口执行提示词

**日期**：2026-09-08
**性质**：V6 收口（LOG-20260908-01，NO-GO 10/12）后的下一窗口执行入口。
**唯一候选方向**：词域覆盖——把 v1 风格枚举词请求显式纳入训练分布 + 双词域判读。
这是当前已诊断失败类（PITFALLS #27）的唯一对症干预；其它方向（换算法/扩场景/调门禁）
均不在本轮范围。
**执行者**：新窗口的 coding agent；允许 subagent（读数与结论须抽查验证）。
**授权状态**：GPU 沿用既有授权（gpu-5090，费用逐次记账）；**本轮无 teacher/API 成本**
（v7 导出复用 teacher-v6-001 既有证据 + 确定性模板行，无需新采集）。封存观测次数
不受限（用户 2026-08-17），但结果永远不得反馈进开发。

---

## 0. 一句话背景

v6 把两个已诊断工程缺陷修干净了（解析器容忍 → 封存 `invalid_call_count=0`；
rtc 修复 → teacher 分桶 1.000），却暴露了一个更深的失败类：**模型「该拒绝」的判定
是措辞域锁定的**——同源词域近乎满分（封存 0.9959/pv1、dev 0.9949/pv1），v1 风格
枚举词域塌方（探针 DENY 侧 7 点 0.00–0.107、OOD v2 candidate 0.6833<0.70 绝对门
FAIL）。根因（数据 diff 逐项排除后收敛，findings 2026-09-08）：口径 A 把枚举词从
训练请求中移除后，**枚举词 deny 请求在 v5/v6 训练分布中都不存在**，对该词域的拒绝
泛化是训练运行的 basin 性质——v5 的探针 15/15 是 basin 运气，不是被训练出的能力。
v7 = 把这个词域显式放进训练分布，让拒绝行为不再依赖 basin 运气。

## 1. 先读这些（按顺序）

1. `AGENTS.md`（边界 + 固定流程 + cpolar 运维入口）
2. `docs/HOLDOUT_LEDGER.md` 观测 9（v6 口径首观测；10/12 双门 FAIL 的逐门事实）
3. `docs/PROJECT_LOG.md` LOG-20260908-01（三个方法论事件）
4. `findings.md` 2026-09-08 各节（塌方读数、根因链、检测器补强）
5. `docs/PITFALLS.md` §二 #27（措辞域锁定）+ #26（采集前断言已上线）
6. `docs/RESUME_EVIDENCE.md` §1.12 + §2 不可写新两行（对外口径边界）
7. `task_plan.md` Current Task（v6 收口 + 预注册原文存档——**v7 预注册的结构范本**；
   运行清单是声明守卫绑定对象，r13-v6 目录不得从声明中删除）
8. `src/veritool_rl/retail_ops/build/teacher_data.py` `write_formal_train_export`（:905）
   与 `product_cli._run_train_export`（:1235）——v7 追加行的落点

## 2. 已冻结决策（遇到不要再问，也不要重开）

| 决策 | 结论 | 出处 |
|---|---|---|
| v1.3 阈值 | `policy_violation_count_max=0`、`success_delta_ci_lower_min=+0.02`、`ood_task_success_min=0.70` 冻结不变 | LOG-20260904-02；release.yaml 三层锁 |
| 探针条件 | 15 偏移每点 ≥ 0.875（GO 的必要条件，与十二门并列） | v6 预注册 A-0.3 |
| 发布候选 | `sft-008` 保持，直到 v7 判定出结果 | 观测 9 |
| v1.4 配对 schema | 不启用（观测 10 沿用 `--gate_schema_version 1.3`）；如要启用**单独问用户** | v6 A-0.3 沿袭 |
| v6 冻结数据集 | `retail_ops_v6_20260907` 逐字节不动；探针网格 / OOD v2/v4 分片逐字节不动 | 观测 9 配对前提 |
| phrasing bank | bank-v4 pin（`aa6ccee…`）不动；bank-005 永不进入评测面 | v5/v6 沿袭 |
| 判读分支形状 | 三分支完整划分（GO / NO-GO 如实收官 / 边界组合升级），不写「任一门 FAIL → 路径穷尽」类机械解读 | v5 教训（观测 8 形状缺口） |
| teacher 证据 | `teacher-v6-001`（579 接受）原样复用，**不重采**（同任务集，证据仍有效） | v6 A-4 |

## 3. 资源与凭据 + 上一窗口 operational 教训（全部真踩过）

### 3.1 远端（gpu-5090）

- 仓库 `/mnt/aidata/tongjiakai/retail-agent-ops`，与 origin main 同步（`7321958`）；
  同步走 `git push ssh://gpu-5090/… main:refs/heads/v6-sync` + 远端
  `git merge --ff-only v6-sync`（本轮验证可用）。
- `models/Qwen3-4B-pinned`、`models/Qwen3-4B-sft-v6-001-merged`（`8f2c0591…`）、
  v6 私有根（train-export/dev-sft/冻结三件 + sealed-eval 两份轨迹）均在远端。
- GPU 常驻他人 ~17GB（32GB 卡）：QLoRA 训练 ~7GB、NF4 评测 ~7GB 可并存（v5/v6 两轮验证）；
  发射前 `nvidia-smi` 确认，发射后用**独立短 ssh** 验证进程与日志（见 3.3-9）。

### 3.2 mimo API

- **本轮预计零 API 成本**：v7 导出复用 `teacher-v6-001` 证据。若方案点裁定需要新采集
  （不应需要），先直连试探（~250 tok）+ 会话头必设（`x-opencode-session`，每周限
  ~07:50 重置；429 = 停下等重置，不要改路由）。

### 3.3 上一窗口 operational 教训（全部真踩过，逐条生效）

1. **ssh + heredoc 会炸**：嵌套引号经本地 zsh/远端 bash 双层解析必出错——诊断与执行
   脚本一律**写本地文件 → scp → 远端执行**，不写内联 heredoc。
2. **rsync 整目录会卡在 checkpoints**（训练产物大目录）——同步训练产物用 **scp 精确
   文件清单**：`adapter/` 7 文件 + `config.yaml/log.txt/metrics.json/trainer_log_history.json`。
3. **干净 clone 实跑**：`uv sync --frozen --python 3.11 --extra dev`（裸 sync 落
   Python 3.10 缺 tomllib；不带 `--extra dev` 没有 pytest；偶发半装加 `--reinstall`）。
4. **评测产物双层结构**：完整指标在**私有 attempt 目录**
   （`data/private/.../dev-candidate/v6-dev-candidate-001/metrics.json`），
   `--output_dir` 公开报告只有聚合；OOD/探针面**无逐任务轨迹**（公开可迭代面设计如此），
   需要看步骤要跑 live 诊断（可迭代面允许）。
5. **配置治理三坑**：(a) `TEACHER_LLM_` 变量名不得出现在提交的 config 里（含注释）；
   (b) 新 release 配置要么 `1.4` 要么判定完成后进 `test_gate_schema_v14` historical
   白名单（附 LOG 号）；(c) 磁盘上新增 `formal-release-*/release.json` 必须同步进
   `test_release_gate_v13::test_every_release_report_on_disk_still_loads` 的自哈希豁免清单。
6. **观测计数检测器**：形状网已补强（2026-09-08），但写文档仍避免复述观测总数——
   用「见台账」句式；新总数语气句式会触发语料缺口，补形状要连误伤一起验。
7. **smoke 与全量必须不同 attempt_id**（smoke 的 already_attempted 会挡同 attempt 续采）。
8. **发射后台任务**：`setsid nohup … < /dev/null &` 后**不依赖发射命令回显**，
   用独立短 ssh `pgrep` + 日志 tail 验证；`pkill -f` 模式会命中自身，先 `pgrep -fa` 看清。
9. **远端长任务日志**：`tr "\r" "\n"` 再 tail（tqdm 进度条是 \r 分隔）。

## 4. v6 收口事实（v7 的起点）

- 候选：`sft-008` 保持；`sft-v6-001` NO-GO 不换；合并形态 `Qwen3-4B-sft-v6-001-merged`
  （merged_revision `8f2c0591…`）。
- 观测 9（封存 246，v6 口径首观测）：base 0.5691/pv85/inv2 → candidate（合并）
  **0.9959/pv1/inv0**、p95 3290ms；**10/12**：FAIL `policy_violation_count_max`（1>0，
  唯一违规 = window 场景 variant-1 措辞、deadline 过期 7 天、查状态后仍退）与
  `ood_task_success_min`（0.6833<0.70）；delta +0.4268、ci_lower +0.3618、三延迟比全 PASS。
- **塌方解剖（v7 的靶面）**：
  - 探针（120 条，v1 风格）：ALLOW 侧 8 点全 1.00，DENY 侧 −14/−10/−7/−5/−3/−2 全
    **0.00**、−1 点 0.75；pv50 全部 `refund_denied_window`；invalid/unterminated 全 0。
  - OOD v2 candidate（60 条，v1 风格）：**window 0.10、duplicate 0.00**（塌方），
    **ownership 1.00**（幸存），其余四类 1.00；base 0.6167。
  - dev（198 条，v6 词域）：candidate 0.9949/pv1——同源词域几乎不见此病。
  - ⇒ 塌方 = **window + duplicate 两条状态比较规则的枚举词域泛化失败**；
    ownership 规则已泛化。覆盖设计必须含 deny 全部三场景（不止 window）。
- teacher-v6-001：588/588 处理、579 接受（98.5%）、rtc 42/42、分桶全 ≥0.80；
  9 条拒绝 = window 6 + rtc 2 + duplicate 1（已回退 Oracle 兜底行）。
- 产物：`reports/retail_ops/v1/r13-v6/`（本地全套）+ 远端
  `data/private/.../sealed-eval/` 两份轨迹；训练 sft-v6-001（441 步，loss 1.2525→0.0464）。
- 测试基线：**1544**（作者环境）/ 干净 clone **1495/49/0**；origin main = `7321958`。

## 5. v7 迭代执行计划

### V7-0 与用户确认的方案点（正式稿确认后才能动）

1. **干预面（核心方案点）**：**只动 train_export，不动任务集**——v7 在
   `write_formal_train_export` 增加确定性的「v1 风格枚举词请求」附加行（模板族同探针
   措辞、实例来自 train split 任务），dataset_version 沿用 `retail_ops_v6_20260907`，
   观测 10 与观测 9 **同一封存集**（可比性最强、零重冻结、零 teacher 成本）。
   备选「新 dataset_version 重冻结算子集」被否理由：改任务集 = 全价（重冻结 + base
   重跑 + 丢观测 9 可比性），而干预不需要改任务——只改训练行。
   ——建议：采纳只动导出。若用户选重冻结，预算与计划重写。
2. **覆盖范围与平衡**：枚举词行覆盖 **deny 三场景（window/ownership/duplicate）+
   allow 三场景（eligible/recovery/rtc）**——allow 侧必须同步覆盖，否则「枚举词 ↔
   拒绝」成为新的伪相关（口径 A 反关联要求的域内版本；探针 ALLOW 侧 1.00 不能因此退化）。
   每任务行数（1 行 vs 2 模板变体）与模板集（2–3 个 v1 风格句式，reason 用 gold 枚举值）
   在预注册写死。
3. **判读规则**：沿用 v1.3 十二门 + 探针每点 ≥0.875，阈值一个字不改；三分支完整
   划分（GO / NO-GO 如实收官 / 边界组合升级），预注册先于观测 10 提交。
4. **观测 10 的 base 侧**：导出代码变更 → code_commit 变 → **base 必须重跑**
   （配对字段含 code_commit；base/candidate 同 commit 同 parser）。

### V7-1 实现前静态核查（本地 CPU，不占观测）

- 复核 v6 OOD v2 / 探针失败的规则分布（本文件 §4 已给：window+duplicate 塌方、
  ownership 幸存）——确认枚举词行覆盖清单与之对齐；
- 确认 `write_formal_train_export` 的行装配点与「追加行」的注入缝（TDD 设计）；
- 模板集草案写入预注册（探针任务文本家族：如「请检查订单 {oid} 是否能因 {reason}
  退款。」——**模板族相同、实例不同**：只用 train split 任务，绝不触碰探针/OOD 任务
  实例，防诊断仪器被练习题污染）。

### V7-2 枚举词导出实现（TDD，本地 CPU）

- `sft_enum_word` 导出键（config 显式声明模板集 + 目标场景 + 每任务行数；键白名单走
  `_require_config_keys` optional 参数——v5 max_steps 先例）；
- 行内容 = 该任务既有轨迹（teacher 接受行优先，拒绝任务用 Oracle 兜底行）+ 枚举词
  请求文本重渲染；assistant/tool 内容逐字节不动；
- 测试锁定：(a) 行数与配额精确；(b) allow/deny 场景枚举词行数平衡（断言写死比例）；
  (c) 既有 2352 行逐字节不变（追加不改动）；(d) 枚举词行的请求 reason ∈ gold 工具
  枚举域（复用 `_assert_request_reasons_within_tool_enums` 同族检查）；
  (e) deny 行的 gold 仍是不退款终局（Oracle 形状）。

### V7-3 导出 + 训练（本地 CPU 导出 + GPU 训练，命令逐条给出后执行）

- `train_export-v7-001`（复用 teacher-v6-001；输出 sft.jsonl = 2352 + 追加行）→
  dev_sft 沿用 v6（dev 任务集未变，`dev-sft-v6-001` 仍有效——若导出校验要求重跑则重跑，
  本地 CPU 分钟级）；
- 训练 `sft-v7-001`（gpu-5090 GPU 0，~35 min；步数随行数线性增加，loss 曲线守卫沿用）；
- merge → `Qwen3-4B-sft-v7-001-merged`（provenance sidecar，merged_revision 可复算）。

### V7-4 评测级联 + 观测 10 + v1.3 判定（GPU ~2h，命令逐条给出后执行）

与 v6 级联同构（产物前缀 `reports/retail_ops/v1/r14-v7/`，运行清单逐字声明进
task_plan 预注册）：dev 配对（base 重跑 + candidate）→ 探针 → OOD v2（base 重跑 +
candidate）→ OOD v4 → 封存观测 10（base + candidate 合并形态，同一 v6 封存集）→
release v1.3。OOD v2 平铺导出注入 evidence 级 parser_id（v6 先例）。

### 判读（预注册正式稿确认后冻结，一个字不改）

v1.3 十二门全 PASS 且探针 15 点每点 ≥0.875 → **换候选 `sft-v7-001`**（项目首个
v1.3 GO）；任一门 FAIL 或探针任一点 <0.875 → 如实收官（分支细则覆盖 v5/v6 两次
形状教训：不写机械解读）；边界组合 → 升级用户。无论哪种结果：不重跑、不换素材、
台账同日收口。

### 风险（预注册预期段必须如实写入）

1. **封存单点翻转的不可消除方差**：绝对门要 pv=0，而 obs 9 pv=1（0.4%）；重训一次
   的封存 pv 期望 0–2——这一门存在抽签成分，判 NO-GO 不代表干预失败，如实记录。
2. **过校正（平移）风险**：枚举词 deny 行可能把拒绝泛化到 allow 侧（R7/DPO 机制）
   ——探针 ALLOW 侧 8 点与 allow 场景枚举词行的平衡配额是门内防线。
3. **练习题污染红线**：枚举词行实例只能来自 train split；任何与探针/OOD 任务实例
   重合的行都是评测污染，测试必须断言实例不相交（task_id 级）。

## 6. 硬边界（全部沿用）

- 封存结果永远不反馈进开发；已证伪方向（PITFALLS §三）不得原样重试；
  v1–v6 冻结契约与既有数据集逐字节不动；探针网格 / OOD 分片逐字节不动；
  判读规则与运行清单先于观测 10 提交；不为数字好看改任务/关守卫/挑读数；
  每条远程 GPU 命令给出工作目录 / 物理 GPU / 预计时长 / 产物并记录（本轮已获用户
  连续执行授权，仍须逐条留痕）；Python 统一 uv；文档默认简体中文。

## 7. 验收（收口全绿）

```bash
.venv/bin/pytest -q                    # 先于 push
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy
env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check
git diff --check
.venv/bin/python scripts/ci/verify_qualification_chain.py
.venv/bin/python scripts/ci/audit_public_release.py
# 干净 clone 实跑（--python 3.11 --extra dev）+ 文档基线同步（测试数变了必须四文档同步）
```

## 8. 故障手册指针

- zen 会话头/周限/瞬断：v6 交接 §3.2（沿用）；本轮无采集，预计不触发
- max_steps 键契约/构造转发：`_require_config_keys` optional 参数 + validator
- 干净 clone：本文件 §3.3-3；训练产物同步：§3.3-2
- 观测计数检测器语料缺口：findings 2026-09-08「检测器补强」节——新句式先跑
  `test_the_total_count_detector_catches_what_it_claims_to` 再写文档
- teacher/bank 采集失败（如触发）：LOG-20260905-03 与 teacher-v6-001 先例
- release 配置/报告磁盘守卫：`test_gate_schema_v14` historical 白名单 +
  `test_release_gate_v13` 自哈希豁免清单（新 `formal-release-010` 记得加）

## 9. 低优先级搁置项（有记录的决策，非欠账）

去掉 NF4 的延迟验证（需再耗观测）、跨 benchmark（τ²-bench/ToolSandbox）、
压测/长稳/混沌、多 seed 方差区间、真实分布采样评测集（泛化根治项，最大最贵）、
v1.4 配对 schema 首用时机。
