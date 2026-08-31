# 项目审查与修复派遣指令

你是 RetailAgentOps 项目的质量协调者。你的任务是**审查 → 修复 → 验证 → 交叉检验 → 收尾**，最终让项目达到"面试无硬伤"的状态。

## 背景

这是一个面向 AI Agent 岗位的简历工程项目，已历 10 个阶段（R0-R10）。项目包含大量实验、结论作废、归因修正、NO-GO 判定。现在需要**一次性找出并修复所有内部问题**，确保对外数字可追溯、文档自洽、代码无 bug、CI 全绿。

## 硬约束（不可违反）

- 本地 WSL 只运行 CPU 开发、测试、lint 和类型检查；**不得在本地运行 GPU 推理或训练**
- 未经用户确认，不得新增产品方向、业务领域、训练算法、模型家族
- 不覆盖、不清理其他工作区的未提交内容；不自动 push、不创建外部仓库
- Python 统一使用 `uv`
- 最终必须通过：`.venv/bin/pytest -q`、`.venv/bin/ruff check .`、`.venv/bin/ruff format --check`、`.venv/bin/mypy`、`uv lock --check`、`git diff --check`

---

## 阶段一：问题审查（15 个 subagent 并行）

从 `reviews/` 目录读取提示词文件，每个文件派遣一个 `general` subagent。每个 subagent 的任务是**只找问题，不评分，不给建议**。

**必须派遣的 15 个审查任务：**

| 提示词文件 | 审查视角 |
|---|---|
| `reviews/1.1_doc_number_conflicts.md` | 文档间数字与结论矛盾 |
| `reviews/1.2_doc_code_mismatch.md` | 文档声明与代码实现不符 |
| `reviews/1.3_plan_loose_ends.md` | 执行计划未闭环项 |
| `reviews/2.1_agent_edge_cases.md` | Agent 执行循环边界 bug |
| `reviews/2.2_tool_parser_bugs.md` | Tool parser 与工具执行 bug |
| `reviews/3.1_data_isolation_bugs.md` | 数据隔离实际漏洞 |
| `reviews/3.2_training_data_issues.md` | 训练数据质量问题 |
| `reviews/3.3_eval_set_consistency.md` | 评测集自洽性问题 |
| `reviews/4.1_eval_script_bugs.md` | 评测脚本 bug |
| `reviews/5.1_training_config_issues.md` | 训练配置与流程问题 |
| `reviews/6.1_number_trace_problems.md` | 数字追溯中的问题 |
| `reviews/6.2_obsolete_remnants.md` | 废弃数字与归因残留 |
| `reviews/7.1_code_bugs.md` | 代码中的 TODO/潜在 bug |
| `reviews/7.2_test_coverage_gaps.md` | 测试覆盖盲区 |
| `reviews/7.3_config_dependency_risks.md` | 配置管理与依赖风险 |

**派遣方式：** 使用 `task` 工具，`subagent_type` 为 `general`，prompt 为提示词文件全文。最多同时 5 个，分三批：
- 批次1：1.1, 1.2, 1.3, 2.1, 2.2
- 批次2：3.1, 3.2, 3.3, 4.1, 5.1
- 批次3：6.1, 6.2, 7.1, 7.2, 7.3

---

## 阶段二：问题汇总与分级

所有审查 subagent 返回后，汇总去重，按严重程度分三级：

**P0（必须修复）：**
- 文档间数字矛盾（不同文件同一指标写的不同数字）
- 文档声明与代码不符（声称的功能代码里没有）
- 评测集自洽性问题（Oracle 回放不过、版本间 ID 重叠）
- 废弃数字仍在对外材料中引用
- 代码中实际的 bug（会运行时报错或产出错误结果）

**P1（应该修复）：**
- 执行计划未闭环项（标注已完成但有子项未做）
- Agent 边界问题（极端输入处理不当但不影响核心流程）
- 训练数据分布问题（已知限制但未在文档中标注）
- 测试覆盖盲区（核心逻辑无测试）

**P2（记录即可）：**
- TODO/FIXME 注释（不影响功能）
- 配置管理的理论风险（当前未触发）
- 文档措辞的微小不精确

---

## 阶段三：交叉验证

在修复前，对所有 **P0 问题**派遣独立 subagent 验证——用另一个 subagent 重新读取问题指向的文件和代码，确认问题真实存在，排除误判。

验证 subagent 的 prompt 格式：
```
请阅读以下文件：[文件列表]
确认以下问题是否存在：[问题描述]
如果存在，给出具体证据（文件行号、代码片段、数字差异）。
如果不存在，说明为什么该问题不成立。
```

验证后，**确认存在的问题进入修复阶段，误判的问题标记为"误报"并归档**。

---

## 阶段四：问题修复

对每个确认的 P0 和 P1 问题，派遣一个 `general` subagent 执行修复。

**修复 subagent 的 prompt 模板：**
```
请修复以下项目问题：

问题：[问题描述]
位置：[文件:行号]
证据：[具体证据]

修复要求：
1. 最小化改动，只修这个问题，不重构不扩展
2. 修复后运行相关测试确认不引入新问题
3. 如果是文档修改，确保修改后的数字/结论与其他文档一致
4. 如果是代码修改，确保相关测试通过
5. 给出修复前后的 diff 摘要

注意：
- 不得修改 docs/PROJECT_LOG.md（历史记录不可改写）
- 不得修改测试的预期值来让测试通过（如果测试暴露了真 bug，修代码）
- 不得删除或降低任何发布门禁阈值
```

**修复顺序：**
1. 先修代码 bug（可能影响测试结果）
2. 再修数据/评测一致性问题
3. 最后修文档矛盾和废弃数字

每修完一批，运行 `.venv/bin/ruff check .` 和 `.venv/bin/ruff format --check` 确保代码整洁。

---

## 阶段五：修复验收

每个 P0 问题修复后，派遣**独立验收 subagent**（不是修复者自己验收）：

验收 subagent 的任务：
1. 读取修复前的问题描述
2. 读取修复后的文件内容
3. 确认问题是否真正被修复
4. 确认修复没有引入新问题（检查相关文件的一致性）
5. 如果修复不完整或引入新问题，标记为"需返工"

对所有 P0 修复执行验收。P1 修复可以通过运行测试批量验收。

---

## 阶段六：多轮交叉检验

验收通过后，执行两轮交叉检验：

**第一轮交叉检验（文档一致性）：**
派遣一个 subagent 扫描所有对外文档（README.md、README.en.md、docs/RESUME_EVIDENCE.md、docs/INTERVIEW_PREP.md），确认：
- 所有数字与 HOLDOUT_LEDGER.md 的原始记录一致
- 所有阶段描述与 EXECUTION_PLAN.md 一致
- 没有引用已作废的结论或数字

**第二轮交叉检验（代码-文档对齐）：**
派遣一个 subagent 对照 PRODUCT_BRIEF.md 的声明与实际代码，确认：
- 声称的 4 个 CLI 接口都存在且可用
- 声称的输出格式与实际输出一致
- 没有功能声明但无代码实现的情况

如果交叉检验发现问题，返回阶段四修复。

---

## 阶段七：Git 和 CI 收尾

所有修复和验证完成后：

1. **运行完整质量门**（按顺序）：
   ```bash
   .venv/bin/pytest -q
   .venv/bin/ruff check .
   .venv/bin/ruff format --check
   .venv/bin/mypy
   uv lock --check
   git diff --check
   .venv/bin/python scripts/ci/audit_public_release.py
   ```

2. **处理 git**：
   - `git status` 查看所有变更
   - 只暂存修复相关的文件（不包括 reviews/ 目录下的审查提示词）
   - 写一个清晰的 commit message，格式：`fix: [修复内容摘要]`
   - **不要自动 push**，只本地 commit

3. **如果 CI 有配置**：检查 CI 配置是否存在，确认修复后的代码能通过 CI。

4. **最终状态报告**：
   ```markdown
   ## 修复完成报告

   ### 修复统计
   - P0 问题：X 个修复 / Y 个确认
   - P1 问题：X 个修复 / Y 个确认
   - 误报：X 个

   ### 质量门结果
   - pytest: PASS/FAIL
   - ruff check: PASS/FAIL
   - ruff format: PASS/FAIL
   - mypy: PASS/FAIL
   - uv lock: PASS/FAIL
   - git diff --check: PASS/FAIL
   - audit: PASS/FAIL

   ### 未修复的问题（如有）
   - [问题]：未修复原因

   ### 建议的后续行动
   - [如有]
   ```

---

## 约束

- 每个 subagent 的输出原样保留，不美化不删减
- 发现的问题必须有**具体文件位置和证据**
- 修复必须最小化，不重构不扩展
- 不修改历史记录文件（PROJECT_LOG.md）
- 不降低任何门禁阈值
- 不自动 push、不创建外部仓库
- 所有修改必须通过质量门
