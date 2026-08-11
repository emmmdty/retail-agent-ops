# 系统卡：RetailAgentOps v1

本卡描述系统**做什么、靠什么保证、在哪里会失败**。产品边界见 [`SPEC.md`](../SPEC.md)，
候选模型见 [`MODEL_CARD.md`](./MODEL_CARD.md)，目录职责见 [`REPO_MAP.md`](./REPO_MAP.md)。

## 1. 系统定位

RetailAgentOps 把零售工具 Agent 的**领域定义 → 轨迹数据 → 单卡后训练 → 执行式评测 →
发布门禁 → 服务部署**串成一条可复现流水线。它解决的问题不是"把模型调得更强"，而是
**在什么证据下才允许把一个模型放上线，以及不允许时如何回滚**。

系统的核心产出之一是**拒绝**：R3 的唯一候选被判 NO-GO，服务据此回滚到冻结基座。
这条路径被完整执行并留下证据，是系统价值的正面证明而非失败。

## 2. 四个稳定接口

| 接口 | 职责 | 真实模型轨道产物 |
|---|---|---|
| `build` | 生成/导入轨迹，执行校验、去重、覆盖与划分审计 | 240/60/120 冻结数据集 + teacher 采集 + SFT 导出 + QLoRA 训练 |
| `evaluate` | 在冻结任务上跑 base/candidate，输出可比证据 | dev 报告（1.7B/4B base、候选）、封存 holdout sealed 报告 ×2 |
| `release` | 按版本化策略产出 GO/NO-GO | `formal-release-001/`（JSON/MD/HTML），NO-GO / baseline |
| `serve` | 加载通过门禁的模型，暴露受控服务 | 按 NO-GO 回滚加载纯基座，三条演示流程 + 并发保护 |

两条平行轨道共用同一实现：**qualification 轨道**（12 条确定性 fixture、规则策略、纯 CPU）
用于契约回归与无 GPU 演示；**formal 轨道**（真实 Qwen3-4B）用于正式判定。
发布门禁的阈值与算术是**同一份 `build_release_gates`**，两条轨道不可能对同一策略文件
得出互相矛盾的结论。

## 3. 数据治理

| 机制 | 实现 |
|---|---|
| 三分隔离 | train/dev/holdout 的 ID 与派生内容五维指纹交叉断言，`content_fingerprint`/`derivation_fingerprint` 刻意不含 split 与 task_id，防止"重新贴标签"式泄漏 |
| 封存 holdout | 两段式授权：purpose 必须为 `RELEASE`，逻辑路径必须精确等于 `data/private/…/<version>/holdout.jsonl`；非 release 目的在任何 `open`/`read` 之前失败 |
| 公开/私有边界 | 完整轨迹、逐任务证据只写私有 ignored 目录；公开报告是**固定 allowlist 字段集**，测试用真实 task_id/user_request/family_id/五类指纹做子串扫描，确认公开 JSON 一个都不出现 |
| 产物完整性 | 每份证据的 `run_id`/`report_id` 是全字段自哈希，逐产物 SHA-256 内嵌；手改任一字段都会导致加载失败 |
| 路径安全 | 私有根用受信根 + `resolve()` 逃逸检测，拒绝 `..` 穿越、绝对路径与中间 symlink（曾用攻击脚本实证三种绕过并修复） |
| 原子发布 | 多文件产物走 staging + rename，任何后续步骤失败整体回滚，不留半成品 |
| 不可覆盖 | 每次正式运行必须新输出目录，`create_output_dir` 对已存在目录直接失败 |

**holdout 使用状态**：2026-08-11 首次也是迄今唯一一次观测（LOG-20260811-03）。
此前的一次运行被机器重启中断，**零产出**，未消耗盲性（判据是"有没有数字落盘并被读取"，
不是跑了多久）。

## 4. 发布门禁与服务约束

### 4.1 五项门禁（`domains/retail_ops/v1/release.yaml`）

`success_delta ≥ +0.05`、`policy_violation_delta ≤ 0`、`invalid_call_count ≤ 0`、
`p95_latency_ratio ≤ 1.25`、`evidence_complete = true`。
五项全过才 GO；任一失败即 NO-GO 且 `deployment=baseline`。门禁集合与顺序由
`validate_decision_consistency` 断言，残缺的报告无法被加载。

配对公平性在门禁计算**之前**校验：基座模型、生成参数、holdout artifact、代码 commit、
依赖锁等逐字段相同才允许比较；base 必须无 adapter、candidate 必须有。任一不符直接失败，
不产出"带警告"的结论。

### 4.2 服务约束（SPEC §9）

| 约束 | 实现 | 真实验证 |
|---|---|---|
| 回滚 | `deployment=baseline` 时 adapter 根本不传给后端工厂，**并且**核对工厂真正返回的后端声明的 `adapter_path` —— 工厂是注入缝，实现可能来自别处 | `/health` 与每条响应均为 `adapter_loaded=false`、`policy_id` 无 adapter 后缀 |
| 工具 allowlist | `/v1/tasks` 暴露 `get_order`/`refund_order`/`get_store_hours` | 已验证 |
| 并发上限 | 串行 episode（上限 1），超限返回 **503** 而不排队——排队会让延迟测量失真，而延迟是门禁项 | 并发两请求：200 + 503 |
| 请求体上限 | `MAX_REQUEST_BYTES = 64 KB`，超限 413 | 前瞻性：现有端点不接受请求体 |
| 输出边界 | 响应为固定字段集，不含任务真值 | 已验证 |

## 5. 资源画像（实测）

| 阶段 | 硬件 | 时间 | 显存峰值 |
|---|---|---|---|
| QLoRA-SFT（240+60，3 epoch） | RTX 5090 单卡 | 134.3 s | 5.16 GiB |
| dev 评测（60 条） | 同上 | 154 s（基座）/ 251 s（候选） | 2.94 / 2.95 GB |
| holdout 评测（120 条） | 同上 | 287 s（基座）/ 544 s（候选） | 2.95 / 2.95 GB |
| 服务冷启动 | 同上 | 权重加载约 1–2 s（页缓存热）；冷启动含 13 文件 SHA-256 校验约 15 min | 同评测量级 |
| teacher 采集（240 条全量） | DeepSeek `deepseek-v4-flash` API | — | 约 $0.055（519 次请求的 smoke 批次实测） |

延迟：基座 p50/p95 = 2035/5255 ms，候选 4700/5712 ms（holdout 120 条，逐 episode）。

**步骤 wall time ≠ 评测延迟**：基座那一步整体耗时 20 分钟，其中约 15 分钟是冷启动读
7.6 GB 权重并逐一校验 13 个文件哈希。可用于比较的量是 provenance 里的
`wall_time_seconds`（287 s vs 544 s）。

## 6. 失败模式与恢复

| 层 | 失败 | 系统行为 |
|---|---|---|
| 模型 | 输出不合 schema、调用未知工具、参数错误 | 计入 `invalid_call`，episode 继续或终止，进入失败 taxonomy |
| 政策 | 未查询即退款、超窗/非本人/重复退款 | verifier 判 `policy_violation`；**正确拒绝**与**政策违规**是分离语义，拒绝不计为失败 |
| 工具 | `transient_error` 瞬时故障 | 环境返回可重试错误，Agent 重试成功即 `refund_recovery` 通过 |
| 数据 | 哈希不符、指纹不一致、证据与记录不绑定 | **硬失败**，不静默回退 |
| 训练 | 模型文件被篡改 | `verify_local_model_files` 在任何产物落盘与 `import torch` 之前拒绝 |
| 发布 | 候选未过门禁 | NO-GO + `deployment=baseline` |
| 服务 | 部署与决策不符 | 启动时拒绝；并发超限 503；请求体超限 413 |
| 基础设施 | 机器重启杀死运行 | 产物不可覆盖 + 自哈希，中断只留空目录，不产生半截证据 |

## 7. 已知限度（必须与结果一同陈述）

1. **共享 GPU 的延迟精度**：gpu-5090 多人共用，评测期间他人占用与利用率显著波动。
   p95 比值距阈值有余量，但延迟数不得表述为精确测量。
2. **统计功效**：holdout n=120，CI 宽度约 ±7.5pp；dev n=60 更宽。系统无法分辨小幅差异。
3. **单 seed**：训练与评测各一个 seed，未做重复性验证。
4. **领域窄**：2 个业务工具、6 类任务、单一中文零售退款场景，无跨领域证据。
5. **teacher 依赖**：训练数据来自单一商业 API teacher，其偏好（如详尽风格）会被继承。
6. **holdout 已消耗一次观测**，多次判定会侵蚀其独立性。
7. **`refund_denied_window` 曾不可解**：环境早期未向模型暴露 `current_day`，任何推理式
   Agent 都无法判断订单是否超窗。该缺陷由真实 teacher 采集暴露（该类通过率 30%），
   修复后升至 95%。**Oracle 驱动的测试永远发现不了这类问题**——这是本项目最有价值的
   工程教训之一。
8. **qualification 演示成功不等于能力证明**：同批次另一条 `refund_eligible` 仍会失败。

## 8. 复现路径

无 GPU（纯 CPU，qualification 轨道全链路）：

```bash
env -u UV_INDEX_URL uv sync --extra dev --frozen
.venv/bin/pytest -q          # 624 passed
# build → evaluate(base/oracle/fault) → release(GO/NO-GO) → serve
# 六条命令见 README「本地 CPU 演示」
```

真实模型轨道需要单卡 GPU、已锁定哈希的 Qwen3-4B 权重与私有数据集，命令见
[`DEMO.md`](./DEMO.md) §3。所有正式运行的命令、物理 GPU、耗时与产物均记录在
`docs/PROJECT_LOG.md`。
