# R6 收口执行提示词（新会话直接粘贴）

复制下面 `---` 之间的全部内容作为新会话的第一条消息。

---

继续 RetailAgentOps 的 R6 收口。项目在
`/home/tjk/myProjects/internship-projects/retail-agent-ops`，本地 HEAD `e4495eb`，
工作树干净，**1048 tests passed**，全部质量门通过。
远端 gpu-5090 停在 `a8f054d`，**比本地少一个提交，先同步**。

先按 `CLAUDE.md` 第 1 节读取上下文。**授权状态**：GPU 是、商业 API 是（`.env` 里有
可用的 DeepSeek 凭据）、**封存 holdout 观测不限次数**（用户 2026-08-17 明确）、
新依赖可自行下载（从中国镜像）、公开仓库推送仍是用户的动作。
不用停下来问，自行决策，除非需要我没有的凭据。

## 背景：已经过四轮独立审阅

一个不带上下文的外部 reviewer 审了四轮，分数 8/10 → 8.5 → 8.5 → **8.75**。
第四轮首次判定「**剩下的差距是文书性的，不是科学性的**」，它认定的实质门槛
（「有一个扛得住分布漂移的结果」）已经达到。**目标是拿到 ≥9 并由它签字。**

前四轮抓到过的失败模式，做事时请一直防着：

1. **名字承诺了但实现没做的测试**——抓到过两条
   （`test_the_business_contract_matches_the_frozen_one` 只抽一条样本看符号；
   `test_the_built_artifacts_match_the_generator` 只比与内容无关的 `task_ids`）。
2. **守卫极性反了**——`test_the_generalisation_fix_is_never_quoted_without_its_cost`
   的触发条件曾要求代价已经在场，等于什么都不拦。
3. **治理测试钉住一句已经变假的话**（审阅原话：「比名不副实更糟：它在强制一个谎言」）。
4. **前瞻式表述会过期**——「下一次会是第五次观测」这类，旧词表只拦总数表述。
5. **文档数字靠人工同步必然漏**——已把测试数、teacher 两批成本等绑到可执行校验。

## 任务（按优先级）

### T1（最高价值，GPU ~1 小时）：`sft-008` 的独立重建复验

**为什么**：`SPEC.md` §6 第 6 条的独立重建复验当初只在 `sft-006` 上做、且只在 dev 上做
（`docs/REBUILD_VERIFICATION.md`）。而 **`sft-008` 才是最终候选**——它修好了分布外
鲁棒性、拿到了第五次封存 holdout 观测的 GO，却**从未被独立重建过**。
「你的最终候选没被独立重建过」是一个比任何文书问题都更值得被问的缺口。

**做法**（每一步的输出目录都必须是新目录，不可覆盖）：

1. 换训练 seed 重训 `sft-008`：配置
   `configs/retail_ops/build/retail_ops_v1_r6b_no_oversample_sft.yaml`（**一个字不改**），
   `--seed 1`，`--input_dir data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722`，
   输出 `reports/retail_ops/v1/r6/sft-008-rebuild-seed1`。约 10 分钟。
2. dev 60 条配对评测（回归）：仿照
   `configs/retail_ops/evaluate/retail_ops_v1_r6b_candidate.yaml`，只改 `attempt_id`
   与 `adapter` 段。配对对照仍是 `qwen3-4b-dev-base-002`。
3. **OOD v2.1 的 `ood_sealed` 分片**：仿照
   `configs/retail_ops/evaluate/retail_ops_ood_r6b_candidate.yaml`，
   `--input_dir reports/retail_ops/v1/ood-v2.1/sealed/tasks`。
   **这是那个分片的第二次观测**——按 `docs/OOD_SEALED_LEDGER.md` 的变更规则，
   要么生成一份新措辞池（`scripts/ops/generate_phrasing_bank.py`，约 $0.006、3 分钟，
   这是台账规则 4 推荐的做法），要么如实记为第二次观测并说明理由。**自己判断，但要写清楚。**
4. 合并权重 + 封存 holdout（第六次观测，**现已不限次数**）：
   `scripts/ops/merge_lora_adapter.py` → base + merged candidate → `release` 两套口径。
   **`release` 命令必须带 `--baseline_trajectories` / `--candidate_trajectories`**，
   否则 v1.1 会产出一份看起来像模型失败的 NO-GO（LOG-20260817-03 就是这个坑）。

**纪律（违反即结论作废）**：

- **运行内容与判读规则必须在跑之前写进 `task_plan.md` 并提交**，三种结果都要预先写明
  （复现 / 不复现 / 部分复现），且**不得在规则里塞入对结果的预期**——
  上一轮我在规则第 3 条的括号里写了预期，结果预期落空导致规则自相矛盾。
- 观测发生在代码冻结提交**之后**。
- **结果无论正负都写**。如果重建不复现，那是比复现更重要的发现，
  它会把「58–60/60，三次同配置运行」那条结论扩展到最终候选上。
- 证据跑完**同步回本地并逐项哈希核对**，且用
  `load_candidate_run_evidence(path, verify_artifacts=True)` 完整行使逐产物校验
  （私有产物在 `data/private/.../dev-candidate/<attempt>/`）。

### T2：`docs/PROJECT_LOG.md` 追加

只写够门槛的（改变做法的）。至少一条：**治理测试钉住一句已经变假的话**这个失败模式——
它比「文档写错了」严重一级，因为测试本该是防线却成了帮凶。
一般化的教训是：**断言「某句话必须在场」的测试，会在那句话过期时把它焊死；
边界类断言应该断言当前边界的语义，而不是某句特定措辞。**

### T3：README 观测表补第五次（以及 T1 之后的第六次）

`README.md` 的封存 holdout 表格停在 4 行而正文说五次。有「本节是摘录 + 台账指针」
缓解，但审阅点过。补齐后确认
`tests/test_project_governance.py::test_no_active_doc_restates_a_stale_observation_count` 仍绿。

### T4：送第五轮独立审核（**必做，且必须由它签字才算完成**）

用 `Agent` 工具起一个 `general-purpose` subagent，**不给它本会话的任何上下文**，
只给仓库路径、岗位设定（「资深技术面试官，评估这个个人项目是否值得进下一轮」）
与门槛（**9 分以上、没有薄弱点、没有靠投机取巧过关的东西**）。
要求它自己跑门禁、自己抽查数字、**主动往低了判**，并给出：
判定与分数、是否达到 9、仍存在的阻塞项（逐条给文件与位置）、以及差在哪。

**上一轮它给的验收清单（本轮已全部动手，请让它逐条确认解除）**：
①`GENERALIZATION_FIX.md` §8 与 §7.5 的矛盾；②钉住假话的
`test_r6_never_claims_a_release_decision`；③空的 `test_the_built_artifacts_match_the_generator`；
④陈旧表述扫描漏掉四份文档且不拦前瞻式表述；⑤状态空间测试下限只到 dev；⑥逐风格 n 未披露。

**如果它仍判不到 9，把它列的阻塞项做完再送一轮，直到签字。**

## 每步收尾必须跑的门禁

```bash
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy
env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check
git diff --check
.venv/bin/python scripts/ci/verify_qualification_chain.py
.venv/bin/python scripts/ci/audit_public_release.py
```

**文档里的测试数由 `test_the_documented_test_count_matches_reality` 绑定**，
加了测试就要同步 `README.md` / `README.en.md` / `CLAUDE.md` / `docs/RESUME_EVIDENCE.md`
四处（含中文的「N 项测试」形式）。

## 硬约束（一条都不能破）

- **不下调任何发布门禁阈值**；不改 `dataset_version` / 40/10/20 配额 / 已冻结字段集合。
- **封存集的结果永远不得反馈进开发、调参、候选选择或 prompt/parser 修改**——
  观测次数放开了，这条没有放开。
- 训练增强只能取措辞池的 `train_aug` 分片；评测只能取 `ood_dev` / `ood_sealed`。
- 文档不得出现没有产物支撑的数字；每个高分都要按 `docs/READING_THE_NUMBERS.md`
  的规矩配上「为什么可能」「旁边那个不好看的数」「不能支持什么」。
- 不创建 remote、不推送公开仓库。

## 当前关键读数（引用时必须带条件，别记错）

- **封存 holdout 五次观测**：前三次 NO-GO，第四次 GO（`sft-006` 合并形态），
  第五次 GO（`sft-008` 合并形态，117/120、政策违规 11→2、`p95_latency_ratio` 1.0203、
  CI 下界 +0.0583，两套口径都是）。**候选不是满分**，且 base 侧 p95 比第四次慢 6%
  ——门禁是比值，更慢的 base 等于放宽了门禁。
- **OOD v2.1 封存分片**（状态空间与冻结契约同宽，只观测一次）：
  基座 0.7667 / `sft-006` **0.7167（低于基座）** / `sft-008` **1.0000**。
  逐风格 n 从 2 到 21，`terse` 一条都没有——「七种风格全部 1.00」的强度取决于最小那格。
- **独立迁移检查**（OOD v1，作者手写，从未用于选择）：
  `expression_ood` 0.00 → 1.00（20 条 = 五子类 × n=4），总分 0.5833 → 0.8667。
- **代价**：dev 与封存 holdout 上各有 2 次 `refund_denied_window` 政策违规，
  OOD v1 的 `scenario_ood` 0.75 → 0.60（`partial_refund` 1.00 → 0.00）。
  收益与代价来自同一个改动。

---
