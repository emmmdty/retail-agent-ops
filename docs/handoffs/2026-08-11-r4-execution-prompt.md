# RetailAgentOps R4 执行提示词（失败驱动优化）

## 使用方式

在项目目录启动新会话（Claude Code 或 Codex 均可）：

```bash
cd /home/tjk/myProjects/internship-projects/retail-agent-ops
```

然后把下面「可直接复制的提示词」整段发送给 agent。

**本提示词不预先批准任何 GPU 运行、API 调用或第二次 holdout 观测。** 它的作用是让新窗口
在不重新发现既有事实的前提下开始工作，并把已知的决策点摆在明处等用户裁决。第三节列出的
候选方案是主 agent 的工程判断，不是已批准设计——用户可以否决其中任何一条。

---

## 可直接复制的提示词

```text
你现在负责 RetailAgentOps 的 R4「失败驱动优化」阶段。工作目录必须是：

/home/tjk/myProjects/internship-projects/retail-agent-ops

一、不可违反的边界

1. 先读根目录 CLAUDE.md / AGENTS.md 并遵守；与本提示词冲突时以它们和用户最新指令为准。
2. 产品名是 RetailAgentOps，Python 包名仍是 `veritool_rl`，不做全仓改名。
3. **封存 holdout 已于 2026-08-11 被观测过一次**（120 条，LOG-20260811-03）。其结果
   ——包括聚合数字与任何逐任务信息——**不得**进入本阶段的开发、调参、prompt/parser 修改、
   数据构造或 checkpoint 选择。R4 的一切分析只能用 train(240) 与 dev(60)。
   是否为改进后的候选消耗**第二次** holdout 观测，是必须单独请示的用户决策，不得自行安排。
4. `SealedEvaluationReport` 与 `BaseRunEvidence` 的字段集合已冻结。两份 sealed 证据已产出，
   `report_id` 是全字段自哈希——**改字段等于作废已有证据**。需要新字段时用子类扩展
   （`CandidateRunEvidence` 是既有先例），不要改基类。
5. 发布门禁阈值不得修改。不因负结果降低门槛。
6. 不进入 GRPO / 在线 RL。偏好优化（DPO）只有在同时满足「失败类别稳定」「SFT 路线明确停滞」
   「能构造足量执行有效偏好对」三条时才可**提出方案等待批准**，不得自行启动。
7. 每一条 SSH、远端 GPU、商业 API 命令都必须单独展示精确命令、工作目录、物理 GPU、
   预计时长与产物，等待用户明确批准；不得把本提示词当作已批准清单顺序执行。
8. 远端 gpu-5090 的数据一律落 `/mnt/aidata`，**不得写系统盘**；远端 `/tmp` 会被重启清空，
   不可承载跨故障的运行日志。
9. 本地 WSL 只跑 CPU。正式运行目录不可覆盖，每次新目录。
10. 不自动 push、不创建外部仓库。

二、必读上下文（按序，不要跳）

1. `docs/CAREER_CONTEXT.md`、`docs/PRODUCT_BRIEF.md`、`SPEC.md`
2. `docs/EXECUTION_PLAN.md` 的 R4 执行目标与验收目标（这是本阶段的合同）
3. `docs/MODEL_CARD.md` §5「失败模式」与 §8「后续方向」——R4 的直接输入
4. `docs/SYSTEM_CARD.md` §7「已知限度」
5. `task_plan.md`、`findings.md`、`progress.md`
6. `docs/PROJECT_LOG.md` 的 LOG-20260807-09 与 LOG-20260811-01 ~ -04
7. 相关代码：`src/veritool_rl/retail_ops/build/teacher_data.py`、
   `retail_ops/domain/formal_tasks.py`、`retail_ops/evaluate/candidate_evaluation.py`、
   `training/sft.py`、`core/agent/runner.py`

三、已确定的事实（不要重新发现，也不要推翻）

R3 的唯一候选 `qwen3-4b-retailops-sft-001` 被判 NO-GO，服务已回滚基座。关键事实：

- 候选把**格式与安全类失败彻底清零**：holdout 上非法调用 41→0、政策违规 16→0、
  schema 有效率 0.7819→1.0000。dev 上同向（21→0、8→0、0.781→1.000）。
- 代价集中在**多步执行**：holdout task_success 0.7833(94/120) → 0.7500(90/120)；
  候选失败 **100% 是 `premature_final_response`**，政策违规与非法调用各 0。
  `refund_eligible` **20/20 全数失败**，`refund_recovery` 失败 9/20，
  单次调用即可完成的四类全对。dev 上机制完全一致（`refund_eligible` 5/10→0/10）。
- **根因已定位**：240 条训练数据中 160 条（66.7%）只含 1 次工具调用，模型把
  「调一次 → 写总结」过度泛化。旁证：`average_tool_calls` 1.25→1.18、
  `average_turns` 2.25→2.09、`average_output_tokens` 109→147。
- **`verifier_reward` 与主判据反向**（0.5646→0.7500 上升而成功率下降），
  在 dev 与 holdout 上各发生一次。**不得用奖励值作为改进的判据。**
- 训练成本极低：单卡 3 epoch / 45 steps / 134 秒 / 峰值 5.16 GiB。
  这意味着**多做几轮训练实验是廉价的，昂贵的是评测与 holdout 观测**。

四、R4 的目标与非目标

目标：只针对上述**已定位、可复现、数量足够**的失败类别做**一到两项**高收益改进，
在 dev(60) 上用配对比较验证，形成可解释的正结果或负结果。

非目标：扩大领域；新增工具；更换基座模型；修改发布门禁；引入 RL；
为保留算法叙事而堆方法；在 holdout 上做任何探索。

五、建议的第一轮方向（需用户确认后才动手）

按 `docs/EXECUTION_PLAN.md` 的 R4 执行目标，改进前必须先按顺序排查
「数据覆盖 → 模板/parser → 工具 schema → verifier」，确认问题确实在数据侧再动训练。
基于已知事实，主 agent 的判断是问题在数据分布，给出两个候选方案供用户选择：

**方案一：重平衡训练数据的动作长度分布**（改数据，不改算法）
  - 做法：提高需 ≥2 次工具调用样本的比例（当前 33.3%），可通过对
    `refund_eligible`/`refund_recovery` 家族增采或对单步样本降采实现。
  - 优点：直接对准根因；训练成本 134 秒/轮，可快速迭代；变量单一，易归因。
  - 风险：增采需要新的 teacher 采集（有 API 成本，需批准）；降采会缩小训练集；
    改变类别比例可能损害已经清零的格式/安全类收益——**必须在 dev 上同时监控这两侧**。

**方案二：在不改数据规模的前提下改训练目标**（如对最终回复段的 loss 加权、
  或显式惩罚"未执行状态变更即终止"）
  - 优点：无 API 成本；训练集不变，与 R3 候选严格可比。
  - 风险：偏离标准 SFT，需要额外实现与测试；容易引入难以解释的耦合变量。

主 agent 倾向**方案一**：它对准已定位的根因，变量单一，且符合"先查数据覆盖"的既定顺序。
但两者都需要用户拍板，且无论选哪个，**每轮只改一个主要变量**。

六、纪律要求

1. 每轮改进必须在 `task_plan.md` 写明：针对的失败类别、影响文件、预计成本、
   **预设收益门槛**与**停止条件**。达不到预设收益就停止，不得转而扩展算法。
2. 配对比较必须使用相同任务集、预算、seed 与 evaluator；沿用既有
   `compare_dev_runs` / `require_comparable_sealed_runs` 机制，不新造一套。
3. 主判据是 dev 的 task_success 与失败 taxonomy，**不是** `verifier_reward`、
   不是 loss、不是 token accuracy。同时必须报告格式/安全类是否退化。
4. 最多两轮主要改进。负结果、回归和被放弃的方案要与正结果同样完整地记录。
5. 行为变化先写失败测试并确认失败原因，再实现最小闭环。
6. 每两次重要检索更新 `findings.md`，阶段进度更新 `progress.md`，
   重大决定/失败/阻塞/GPU 运行/go-no-go 追加 `docs/PROJECT_LOG.md` 并在答复中报告 LOG ID。
   **例行执行步骤不要写 LOG。**
7. 每次收口跑：`.venv/bin/pytest -q`（当前基线 624 passed）、`.venv/bin/ruff check .`、
   `.venv/bin/mypy`、`env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check`、
   `git diff --check`。

七、本阶段的用户决策门（先问，不要替用户决定）

1. 第一轮改进选方案一还是方案二（或用户自己的方案）。
2. 若选方案一：是否批准新的 teacher API 采集，以及预算上限。
3. 预设收益门槛定多少（例如 dev task_success 需回到多少才算成功）。
4. 改进后的候选是否消耗**第二次 holdout 观测**——这是不可逆的，且会削弱该集合的独立性。
5. 若最终要在简历写「提升」，需要做一次独立重建复验（`docs/CAREER_CONTEXT.md` 与
   R4 验收目标均有此要求），是否安排。

八、先做什么

不要直接开始改数据。第一步是**只读核查**：确认三、节所述事实在当前代码与产物中仍然成立
（特别是 66.7% 这个比例，用 train 导出文件重新统计一遍而不是引用本提示词），
按「数据覆盖 → 模板/parser → 工具 schema → verifier」的顺序做一轮排查并汇报，
然后带着第七节的决策门等用户回答。
```

---

## 附：本提示词未覆盖的事项

- **R5 的公开交付**（跨模型对比、故障测试、双语文档、演示视频、公开仓库）不在 R4 范围。
- **R3 的剩余收口**已完成：模型卡、系统卡、演示流程与第一版简历证据分别位于
  `docs/MODEL_CARD.md`、`docs/SYSTEM_CARD.md`、`docs/DEMO.md`、`docs/RESUME_EVIDENCE.md`。
- 简历 bullet 的**方案 A / 方案 B 尚未选定**（见 `docs/RESUME_EVIDENCE.md` §3），
  该选择取决于主投岗位方向，不属于 R4 的技术工作。
