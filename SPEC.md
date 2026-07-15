# VeriTool-RL — 项目规格 (SPEC)

> **Verifier-Guided Curriculum Post-Training for Small Tool-Using Agents**
> 面向小型工具智能体的可验证课程式后训练方法
>
> 本文件是本项目的**单一事实来源 (single source of truth)**。coding agent 与开发者的所有实现、评测与叙事都以本文件为准。协作方式见 `CLAUDE.md`。

---

## 1. 一句话定位

面向 1.5B–4B 级开源模型, 构建「单轮函数调用 → 多步状态操作 → 多轮用户—工具交互」的统一训练流水线; 采用成功轨迹 SFT、失败轨迹偏好优化与可验证奖励, 研究**课程顺序、奖励设计与工具模式扰动**对 Agent 成功率与稳定性的影响。

**成熟度定位**: 研究级 L1/L2 —— 形成可复现算法原型与可信实验, **不**宣称单独达到企业生产系统。

## 2. 正式研究问题

> 在 1.5B–4B 级开源模型和 1–2 张 RTX 4090 的约束下, 课程式交互难度、失败轨迹偏好学习、可验证奖励校准与工具 schema 扰动, 能否在**不显著增加推理成本**的前提下, 提高多轮工具任务的**最终成功率、政策遵循与错误恢复能力**?

这是一个序列决策问题: 给定用户目标、当前环境状态、可用工具及政策约束, 模型要在多轮中选择动作、读取反馈、必要时补充询问, 最终把系统推进到正确的**最终状态**。可迁移真实场景: 客服工单、订单退款、航旅改签、CRM/ERP 操作、IT 运维、数据库工作流。

## 3. 当前痛点 (为什么单轮 Function Calling 不够)

1. 长程搜索空间膨胀, 错误逐步累积;
2. 奖励稀疏 + 信用分配困难 (朴素 per-turn 奖励可能被钻空子);
3. 环境 rollout 昂贵且有噪声, 在线 RL 稳定性/可复现性弱;
4. 只模仿成功轨迹, 学不到「何时不调用 / 失败后如何恢复 / 何时先询问」;
5. schema 脆弱: 改名、改描述、换参数顺序、加无关工具都可能显著退化;
6. 安全 ≠ 成功: 某轨迹可能完成目标却违反授权/隐私/政策;
7. 平均分掩盖不稳定: 生产关心一致性、尾部失败、调用成本与违规概率。

## 4. 相关工作与研究空位

- **BFCL V4** 已从单纯函数调用扩展到 multi-turn / agentic / memory / hallucination / format sensitivity, 提供固定代码版本与可复现评测。
- **ToolSandbox** 引入有状态、对话式工具环境与 milestone/minefield; **tau2-bench** 把用户、工具、政策与最终数据库状态纳入同一任务。
- **AgentGym-RL** (ICLR 2026 Oral) 指出多轮 RL 面临搜索空间/方差/探索-利用不稳定, 用逐步增加交互轮数的 ScalingInter-RL 改善训练。
- **Agent-R1** 把多轮 rollout 建模为 step-level MDP。
- **Iterative Reward Calibration** 表明朴素 dense per-turn reward 可能比稀疏奖励更差 (部分设置最多下降 14 个百分点), 奖励区分度必须与优势估计对齐。
- **CacheRL (2026)** 强调高质量轨迹与奖励设计有时比复杂 RL 算法更重要。

**研究空位 (本项目的定位)**: 在消费级双卡以内, 建立一条从单轮工具格式、到有状态多步、再到多轮用户交互的**可复现小模型训练路线**, 并把课程、失败偏好、奖励校准与 schema 鲁棒性分别做**因果消融**。不重复造通用 RL 框架, 交付一套资源受限、问题清晰、招聘者可复跑的研究闭环。

## 5. 方法: 四个相互独立、可被证伪的假设

| 假设 | 方法 | 对照实验 | 预期现象 | 假设失败时怎么办 |
|---|---|---|---|---|
| **H1** 渐进难度比混合喂数据更稳定 | single-call → stateful multi-step → multi-turn curriculum | 相同数据量的 shuffled mixed SFT | final-state success 提升, 长轨迹失败方差下降 | 保留统一流水线, 结论改为「课程无显著收益」并分析任务分布 |
| **H2** 失败偏好能补足纯模仿学习 | 构造错误工具/参数/违规/循环/恢复失败的 rejected trajectory, 做 DPO/SimPO | success-only SFT | invalid call、policy violation、重复循环下降 | 检查偏好对难度/长度偏差; 若仍无效则停止偏好优化 |
| **H3** 校准 verifier reward 优于朴素 dense reward | final-state + policy + milestone, 按区分度/优势信号校准 | sparse only / naïve dense / calibrated | 成功率提高且 reward hacking 不增加 | 在线 RL 不过 go/no-go 时转为 rejection sampling + 离线偏好 |
| **H4** schema 扰动提升工具泛化 | 训练中随机改名/改写描述/打乱参数/插入 distractor | 无扰动训练 | 未见 schema 上性能跌幅更小 | 若干扰正常任务, 降低扰动强度并报告鲁棒-精度权衡 |

**统一数据单位**: `Trajectory = task + initial_state + messages + actions + observations + rewards + final_state + violations` (见 `src/veritool_rl/trajectory/schema.py`)。每条轨迹必须可重放; 每个奖励分量必须可追溯到环境状态或政策规则。论文叙事是**逐一验证四个因果假设**, 而非把 SFT/DPO/GRPO 堆在一起。

## 6. 数据设计 (从易到难三层任务)

1. **BFCL V4 子集**: 单轮、并行、多函数、格式鲁棒性 → tool-call syntax 与参数精度;
2. **ToolSandbox**: 可变状态、隐式依赖、milestone/minefield → 多步状态操作与错误恢复;
3. **tau2/tau3-bench 的一个领域** (retail / airline / telecom 选一): 多轮用户交互、政策遵循与最终数据库状态。

只选**一个**主多轮领域, 避免同时维护多个昂贵 user simulator。公开测试集只用于最终评测; 训练轨迹来自公开训练任务、规则驱动合成与本地模型 rollout。

## 7. 必须实现的工具/接口

见 `src/veritool_rl/envs/base.py::ToolEnv`:

- `list_tools()` — 获取工具及 JSON schema;
- `execute_tool(name, arguments)` — 执行并返回结构化 observation;
- `get_state()` — 当前环境可见状态;
- `verify_milestone()` — 中间里程碑;
- `verify_final_state()` — 确定性成功奖励;
- `check_policy()` — 越权/顺序错误/minefield;
- `perturb_schema()` — 名称/描述/参数顺序/无关工具扰动。

## 8. 基线 (至少 5 个)

1. Base/Instruct 模型零样本 function calling;
2. 仅格式/单轮工具调用的 SFT;
3. 单轮 + 多步成功轨迹的 curriculum SFT;
4. SFT + trajectory DPO/SimPO;
5. SFT + rejection sampling / self-training;
6. SFT + verifier-guided GRPO (过 go/no-go 后);
7. 有无 per-turn reward calibration;
8. 有无 schema perturbation augmentation。

**当前已验证基线（2026-07-15）**：Qwen3-1.7B 在 BFCL V4 固定 200 条单轮
AST 子集上的 seed-0 零样本官方 AST accuracy 为 0.815（163/200）。四类各
50 条，`simple_python` / `multiple` / `parallel` / `parallel_multiple` 分别为
0.82 / 0.90 / 0.76 / 0.78。这不是 BFCL 官方全量成绩或排行榜成绩，不能替代
后续 BFCL 后训练对照或多轮基准。

## 9. 训练数据

- **成功轨迹**: 基准参考轨迹 + 规则规划器 + 验证通过的本地模型 rollout;
- **失败轨迹**: 错误工具、错误参数、遗漏信息、policy violation、冗余循环、错误恢复;
- SFT 先学格式与局部动作, 再学多步完整轨迹;
- DPO/SimPO 用「最终状态正确、无违规、调用更短」排序构造偏好对;
- 在线 RL 只用确定性 final-state/policy reward, 不把通用 LLM judge 当核心奖励;
- 首选 Qwen3 1.7B/4B + LoRA/QLoRA。**先用 1.7B 打通闭环, 再决定是否升到 4B**。

## 10. 算力与降级线 (硬约束)

- **1 张 RTX 4090**: 完成 1.7B/4B QLoRA-SFT、偏好优化、离线 rollout 评测;
- **2 张 RTX 4090**: 一张 policy 训练, 一张 rollout/user simulator, 先在 1.7B + 小任务子集验证在线 GRPO;
- **在线 RL go/no-go**: 48 小时内完成可重复 smoke run, reward 非退化、无持续 OOM/NaN, 且在小验证集上优于 SFT;
- **未通过则停止在线 RL**, 主方法收敛为 curriculum SFT + verifier-guided rejection sampling + trajectory DPO/SimPO + reward calibration analysis;
- 不依赖闭源 API 生成核心训练数据或核心成绩, 闭源模型只作参考上限。

> gpu-4090 实测: 4× RTX 4090 (24GB), `/data` 约 35T 可用。训练/批量评测在服务器执行; 本地 (WSL) 只做开发、调试、轻量评测。

## 11. 评测指标

- BFCL AST / executable call accuracy;
- Final-state task success / resolution rate;
- Policy compliance / minefield violation rate;
- Tool selection 与 argument accuracy;
- Trajectory exact match / normalized edit distance;
- Invalid tool-call rate;
- Recovery success after tool error;
- 平均轮数、工具调用次数、token、延迟、显存/训练成本;
- 工具名称/描述/参数顺序/无关工具干扰下的鲁棒性曲线。

**主结论必须由执行结果、数据库状态与 policy verifier 支撑; LLM-as-a-judge 只作补充。**

## 12. 必做消融

- w/o curriculum;
- w/o failure trajectories;
- w/o preference optimization;
- w/o verifier reward;
- sparse outcome reward vs naïve dense reward vs calibrated reward;
- w/o schema perturbation;
- 不同模型尺寸 (1.7B vs 4B);
- 质量—成本 Pareto 对比。

## 13. 预期效果、解决程度与停止条件

> 以下全部是**立项验收目标, 不是已完成结果**。简历只能填写实际测得数据。

| 维度 | 相对完整 SFT 基线的目标 | 最低可接受结果 |
|---|---|---|
| 单领域多轮 final-state success | 绝对提升 5–10 个百分点 | 95% CI 显示非退化, 且至少一个核心假设有显著收益 |
| Invalid tool call / policy violation | 相对下降 ≥20% | 至少一项相对下降 ≥10% 且成功率不退化 |
| 错误恢复成功率 | 绝对提升 ≥5 个百分点 | 给出按错误类型分组的可信分析 |
| 平均工具调用 / token | 成功率不降下下降 ≥10% | 报告 Pareto 曲线, 不隐去成本上升 |
| 未见 schema 鲁棒性 | 相对减少 ≥25% 的性能跌幅 | 明确哪些扰动可迁移、哪些不可 |

**三个月合理成熟度**: 证明一组小模型后训练方法在公开、可重放、有确定性成功条件的状态任务上是否有效, 并给出算力—质量—稳定性边界。**不**保证企业生产上线 (真实系统还需工具 ACL、用户身份、业务审批、隐私治理、在线监控与人工接管)。

## 14. 非目标与边界

- 不造通用 RL 框架;
- 不训练超出双 4090 承受范围的大模型;
- 不用 LLM-as-a-judge 取代确定性 gold 指标;
- 不用闭源 API 生成核心训练数据/核心成绩;
- 生产落地形态是「模型输出候选动作 → 工具权限 / policy verifier / 审批 / canary / 审计日志约束」, **而非模型直接改业务状态**。

## 15. 非-Toy 验收门 (与 PatchPilot 共用的 10 条)

只有同时满足才允许在简历中写「研究型项目」, 否则统一降级为 prototype:

1. 真实任务 (公开基准 + 冻结私有 holdout);
2. 可执行真值 (AST / 数据库最终状态 / 隐藏测试 / 静态检查);
3. 公平对照 (固定 backbone、prompt 预算、采样参数、硬件、超时、任务集合);
4. 至少三类基线 (原始模型 / 强基线 / 完整方法);
5. 因果消融 (逐个移除课程、失败轨迹、verifier 等);
6. 重复实验 (≥3 seed 或报告方差; 评测多次运行 + bootstrap CI);
7. 负面证据 (未解决任务、典型失败、退化实验、方法边界);
8. 资源证据 (成功率 + token + 延迟 + 显存/成本);
9. 可复现交付 (固定 commit、容器、配置、数据版本、一键最小复现);
10. 安全边界 (权限、隔离、审批、审计、回滚; 模型输出永不作为自动执行高风险动作的充分条件)。

## 16. 最终交付物

- 可复现 GitHub 仓库;
- 轨迹数据生成器、验证器与 dataset card;
- SFT、偏好学习与可选 GRPO 训练脚本;
- BFCL / ToolSandbox / 单领域多轮任务评测;
- 至少 5 个基线、完整消融与奖励分析;
- 轨迹回放与错误分类报告;
- 5 分钟演示视频;
- 8–12 页技术报告;
- 一页模型/系统卡 (数据、限制、风险、复现方式)。

## 17. 里程碑 (映射到 12 周执行计划)

| 周 (日) | VeriTool-RL 目标 | 产出 |
|---|---|---|
| W1 (D1–D7) | 问题—方法—边界一页纸; RFC; 相关工作矩阵; 非-Toy 门清单 | Problem Brief、RFC、related-work matrix |
| W3 (D20–D21) | 下载并审计 BFCL/ToolSandbox; 定义 trajectory JSON schema; 20 条失败轨迹分析 | dataset card、数据检查报告、tool-use baseline report V0 |
| W4 (D26) | BFCL 单轮 + ToolSandbox 多步零样本基线 | 100–300 条样本基线结果 |
| W5 (D29–D35) | trajectory→SFT 转换器; LoRA 过拟合实验; SFT V0; 数据质量报告 | 可复现实验配置与结果、实验报告 V1 |
| W6 (D36–D38) | 偏好数据规则; DPO/SimPO 小规模可行性; 在线 GRPO go/no-go 结论 | reward 设计文档、go/no-go 结论 |
| W8 (D50) | 全量基线 (固定模型/数据/种子/环境) | baseline table V1 |
| W9 (D57–D63) | 课程/失败/偏好消融; 后训练收益表; schema 鲁棒性曲线; 成本-质量 Pareto; 100 例误差分析; 复现报告 | VeriTool-RL 报告 V1 |
| W12 (D79/D81) | 技术报告与图表; 5 分钟演示视频 | 算法报告 RC1、演示链接 |

**阶段验收线**: D28 可投递 · D49 主投递 · D70 竞争力 · D84 交付 (详见根计划文档 §12)。

## 18. 参考链接

- BFCL V4 — https://gorilla.cs.berkeley.edu/leaderboard.html
- ToolSandbox — https://github.com/apple/ToolSandbox
- tau2-bench — https://github.com/sierra-research/tau2-bench
- AgentGym-RL (ICLR 2026 Oral) — https://github.com/woooodyy/AgentGym-RL
- Agent-R1 — https://github.com/AgentR1/Agent-R1
- Agent Reinforcement Trainer (ART) — https://github.com/openpipe/art
- Iterative Reward Calibration — https://arxiv.org/abs/2604.02869
- CacheRL — https://arxiv.org/abs/2606.14179
- Self-Evolving Synthetic Data to Verifiable-Reward RL — https://arxiv.org/abs/2601.22607
- Hugging Face TRL — https://huggingface.co/docs/trl/en/index
- TRL PEFT/LoRA — https://huggingface.co/docs/trl/en/peft_integration
