# VeriTool-RL 可执行阶段计划

本文件是项目阶段、依赖、并行边界和验收状态的唯一事实来源。`SPEC.md` 说明研究
目标与最终验收，本文件说明执行顺序。每次阶段状态变化必须同步本文件，并在
`docs/PROJECT_LOG.md` 追加记录；不得静默改写已完成阶段的历史结论。

## 状态约定

- `已完成`：验收证据存在，后续只能通过新记录补充或纠正。
- `当前`：允许执行的主阶段；同一时间原则上只有一个当前阶段。
- `待执行`：依赖尚未满足，不得提前启动正式实验。
- `条件执行`：仅在明确 go/no-go 通过并获得所需 GPU 授权后执行。
- `已阻塞`：停止继续消耗资源，记录证据并等待依赖或用户决策。

每个阶段内部先完成“共享前置”，再启动并行轨道。并行轨道不得同时修改同一核心
接口；共享接口变化必须先回到阶段评审点。所有 benchmark holdout、源码 commit、
manifest、evaluator 和模型生成配置在阶段入口冻结。

## 总览

| 阶段 | 状态 | 目标 | 主要产物 |
|---|---|---|---|
| P0 基础设施与 MiniRetail | 已完成 | 打通可审计的工具轨迹闭环 | 环境、轨迹、重放、verifier、QLoRA MVP |
| P1 BFCL 单轮 Base/SFT | 已完成 | 在固定非重叠公开数据划分上完成一次对照 | Base/SFT 报告、provenance、失败分析 |
| P2 执行治理 | 已完成 | 建立持久阶段计划和自动记录协议 | 本文件、项目日志、Agent 配置、ADR 0003 |
| P3 Benchmark 扩展 | 待执行（下一阶段） | 建立静态、多轮和有状态基线 | BFCL 扩展、ToolSandbox、tau2 基线报告 |
| P4 课程式 SFT（H1） | 待执行 | 检验课程顺序是否优于等数据混合 | 冻结数据、配对配置、多 seed 结果 |
| P5 独立离线实验 | 待执行 | 并行检验 H2、H4 与离线 H3 | 偏好、schema、奖励校准报告 |
| P6 在线 RL 决策（H3） | 条件执行 | 小规模验证在线优化是否值得继续 | go/no-go 证据或降级方案 |
| P7 汇总与交付 | 待执行 | 形成可复现、边界清晰的研究交付 | 消融、报告、系统卡、演示材料 |

## P0 基础设施与 MiniRetail

**状态**：已完成。

**已验收**：本地/远程 `uv` 环境、固定 Qwen3-1.7B 模型路径、确定性
MiniRetail、trajectory/replay/verifier/metrics、Base 与 QLoRA-SFT 最小闭环及基础
质量门。MiniRetail 只验证基础设施，不作为外部 benchmark 成绩。

**证据**：`reports/mvp/`、`docs/adr/0002-mini-retail-mvp.md`。

## P1 BFCL 单轮 Base/SFT

**状态**：已完成并冻结。

**已验收**：固定 BFCL commit 和 200 条 holdout；720/80/200 ID 互斥；800/800
训练目标通过官方 AST checker；一次 QLoRA-SFT 和一次固定 holdout 评测。Base 为
163/200，SFT 为 167/200，配对 delta 为 +0.020，seed 0 bootstrap 95% CI 为
[-0.040, 0.080]，不能声称稳定改善。

**硬边界**：固定 holdout 及其失败不得进入训练、开发、调参、checkpoint 选择或
目标修改。不得把结果称为官方 BFCL 训练、全量成绩、排行榜成绩或独立分布泛化。

**证据**：`reports/bfcl/qwen3-1.7b-base-vs-sft-seed0/report.md`、
`manifests/bfcl_v4_single_turn_seed0.json`、
`manifests/bfcl_v4_sft_split_seed0.json`。

## P2 执行治理

**状态**：已完成（2026-07-17）。

**共享前置**：冻结 P0/P1 事实；区分阶段计划、项目日志、ADR 和实验报告的职责。

**任务**：

1. 建立本阶段计划和 append-only 项目日志。
2. 让 Codex 在根目录无 `AGENTS.md` 时自动加载 `CLAUDE.md`。
3. 为 Claude 配置 Stop 日志遗漏检查，并排除只读和琐碎任务。
4. 更新 `CLAUDE.md`、`SPEC.md`、`README.md` 的入口和触发协议。
5. 验证 JSON/TOML、测试、Ruff、mypy 和 `git diff --check`。

**退出门**：配置解析和完整质量门通过；日志至少包含本次记录系统决策；文档之间
没有第二套冲突状态；根目录仍无 `AGENTS.md`，`.serena/` 未修改。

## P3 Benchmark 扩展

**状态**：待执行（下一阶段，尚未启动），依赖 P2。

**共享前置（串行）**：先冻结统一 `ToolEnv`/trajectory/evaluator 接口、各 benchmark
源码 commit、任务 manifest、holdout 边界、指标口径和失败 taxonomy。模型加载继续
离线；benchmark 自身需要的联网能力另行做 provenance 与授权评审。

**并行轨道**：

- A：BFCL robustness/multi-turn 数据审计、固定子集、Base 基线与错误分析。
- B：在独立 `uv` 环境/进程边界完成 ToolSandbox adapter、replay 和零样本基线，
  不把其 `transformers==4.41.2` 安装进主训练环境。
- C：从 retail/airline/telecom 中只选一个 tau2 领域，完成政策、user simulator、
  状态验证的可行性审计和零样本基线。
- D：共享报告与配对汇总工具；只能在 A-C 的任务 ID 和评分口径冻结后推进。

**退出门**：每条轨道都有固定 manifest、可重放样例、官方或项目固定 evaluator、
100-300 条或预先声明规模的基线、资源记录和至少 20 条真实失败分析。若 evaluator
无法固定、出现数据泄漏或依赖无法隔离，立即停止对应轨道。

## P4 课程式 SFT（H1）

**状态**：待执行，依赖 P3。

**共享前置（串行）**：统一各 benchmark 的轨迹映射；冻结 train/dev/test、token
审计、模型、训练预算和 checkpoint 选择规则；先做小样本 target/verifier 审计。

**并行轨道**：数据转换与泄漏测试、课程/混合对照配置、评测与统计脚本可并行；
正式 GPU 作业在上述三项验收后串行执行，先 smoke，再固定配置正式运行。不得用
holdout 选择课程顺序或超参数。

**退出门**：课程式 SFT 与等数据量/等 token 的 shuffled-mixed SFT 可配对比较；
至少 3 个预注册 seed，报告均值、方差、配对区间、分类指标和资源成本。单 seed
只能作为开发证据，不作为 H1 结论。

## P5 独立离线实验

**状态**：待执行，依赖 P4 的冻结 SFT checkpoint。

以下轨道可并行，数据、配置和输出目录相互独立：

- H2：按错误工具、参数、政策违规、循环和恢复失败构造 rejected trajectory，比较
  DPO/SimPO 与 success-only SFT；检查长度和难度偏差。
- H4：生成可验证的 rename/reorder/optional/nested/distractor schema 扰动，绘制原始
  与扰动性能曲线，禁止改变任务语义。
- H3-offline：测量 reward 分量的区分度、优势方差、与最终成功/违规的一致性，比较
  sparse、naive dense 和 calibrated reward。

**退出门**：每个轨道都有独立的预注册比较、至少 3 seed 或明确的可行性结论、失败
分析与停止理由。任一轨道失败不阻塞其他轨道。

## P6 在线 RL 决策（H3）

**状态**：条件执行，依赖 P5 的 reward calibration 通过。

**入口门**：固定小任务子集；reward 非退化且能区分正负轨迹；rollout 可重放；无
holdout 泄漏；已获得单独 GPU 授权和完整远程命令确认。

**顺序**：单卡/小 batch smoke → 48 小时内 go/no-go → 仅通过后扩大。出现 OOM、
NaN、reward hacking、持续零优势、依赖后端重大变更或不优于 SFT 时立即停止。

**降级**：不过门时主方法固定为 curriculum SFT + verifier-guided rejection
sampling + 离线偏好 + reward calibration analysis，不为保留 GRPO 叙事而重写门槛。

## P7 汇总与交付

**状态**：待执行，依赖 P4-P6 的实际结论。

**可并行轨道**：最终多 seed 表格和统计复核、100 例真实错误分析、成本-质量
Pareto、复现包与 dataset/model/system card、8-12 页技术报告和 5 分钟演示材料。

**退出门**：`SPEC.md` 非-Toy 验收门逐项有证据；所有数字可追溯到固定 config、
manifest、commit 和原始产物；负结果和不可外推限制完整保留；最终 HEAD 在本地和
远程重新通过质量门。

## 阶段更新规则

1. 开始阶段前检查入口门，记录阶段开始；未满足依赖时不得把状态改为“当前”。
2. 并行轨道先声明文件/数据/输出所有权，避免共享状态冲突。
3. 每次正式训练、批量评测、阶段阻塞、go/no-go 或结论变化均追加项目日志。
4. 阶段完成时先核对退出门和证据，再更新本文件；不得只凭“命令运行过”完成。
5. 计划变更影响研究假设或长期架构时，另建 ADR；日常执行取舍只写项目日志。
