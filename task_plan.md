# Task Plan: RetailAgentOps

## Goal

在 12 周内交付可公开、可复现、可面试解释的零售工具 Agent 单卡适配与发布流水线，并在前 6 周完成首个工程闭环。

## Current Phase

**R5 公开交付与求职收口**（`docs/EXECUTION_PLAN.md` 已标为已完成）。R4.5 架构补强 13 条
已全部收口。起始基线 **907 tests passed**，收口基线 **944 passed**。
本阶段不产生新的模型改进方案。

## Current Task：R5 收口封存

### 用户本轮追加的三条硬要求（2026-08-16）

1. **项目必须拿得出 GO**，不能只有 NO-GO；
2. **收尾前必须由一个独立「面试官」角色审核通过**，否则不算完成；
3. **代码整洁性**要做好。

对应到执行上：

- 第 1 条不通过"放宽门禁"实现——阈值一个字不改。项目**已有**一个自动门禁 GO
  （第四次观测，合并部署形态，LOG-20260815-04）。挡在它前面的是 `SPEC.md` §6 第 6 条
  「最终候选独立重建后仍保持正向提升」**未做**。本轮做掉它，把结论从"自动门禁 GO"
  升级为"SPEC §6 六条全部满足"。**若重建复验不通过，如实记录并保留原口径**，
  不修改门禁、不挑选有利 seed。
- 第 2 条在最终质量门之后执行，reviewer 拿不到本会话上下文，只读仓库。
- 第 3 条：全仓 formatter 统一 + lint 集扩展 + 死代码清理 + 把它们写进 CI 门禁。

### 输入

- 基线 `be8f18d`，工作树干净，907 tests passed，Ruff / mypy / uv lock 全绿；
- 已有全部运行产物：四次封存 holdout 观测、dev 2×2 矩阵、跨规模验证、OOD 60 条、
  serving 四档、引擎替换对照；
- 冻结契约：`GATE_IDS` v1.0/v1.1、dev `PAIRING_FIELDS`、`SEALED_PAIRING_FIELDS`、
  `dataset_version` + 40/10/20 配额、`SealedEvaluationReport` v1.0/v1.1 字段集；
- 远端 gpu-5090 `/mnt/aidata/tongjiakai/retail-agent-ops` 已同步到同一 commit，
  模型与私有训练数据齐备。

### 输出

| 编号 | 内容 | 资源 |
|---|---|---|
| T1 | 代码整洁性：全仓 `ruff format`、lint 集扩展到 `SIM/C4/RET/PIE/RUF`、死代码清理、CI 加 format 门 | CPU |
| T2 | **独立重建复验**（SPEC §6 第 6 条）：同 config 换训练 seed 重训 + dev 60 配对评测 | **GPU** |
| T3 | 公开发布审计：`LICENSE`、第三方声明、secret / 权重 / holdout 真值扫描脚本 | CPU |
| T4 | 故障注入矩阵：把 R5 要求的五类故障逐条映射到测试，补缺口 | CPU |
| T5 | 对外文档：README 中文重写（第一屏结论 + 架构图）、`README.en.md` 英文版 | CPU |
| T6 | 求职材料：`RESUME_EVIDENCE.md` 更新与 bullet 定稿、`docs/INTERVIEW_PREP.md` | CPU |
| T7 | 收口：`EXECUTION_PLAN.md` R5 标完成、`PROJECT_LOG.md` 追加、最终质量门、提交 | CPU |
| T8 | **独立面试官审核**（用户第 2 条要求），未通过则回到对应任务修复 | CPU |

### 非目标（硬约束）

- **不下调任何发布门禁阈值**（`test_release_config_does_not_touch_the_gates` 必须通过）；
- **不消耗第五次封存 holdout 观测**——重建复验只在 **dev** 上做；
- 不改 `dataset_version`、40/10/20 配额、任何已冻结字段集合；
- 不重命名 Python 包；
- 不删除或改写四次观测中任何一次的结论，不删除被证伪的假设记录；
- 文档不得出现没有产物支撑的数字；
- 不创建 remote、不推送公开仓库（对外发布是用户的动作，本轮只做到"一条命令即可发布"）。

### 失败模式（实施时主动防御）

1. **为了拿 GO 而挑 seed**：重建的 seed 事先写定（0 与 1）并提交进配置，两次结果无论正负都记录、都进文档，不跑第三个再挑好看的；
2. **formatter 大 diff 掩盖语义改动**：格式化与逻辑修改分成两次提交，中间各跑一次全量测试；
3. **文档漂移**：观测次数、测试数、`report_id` 这类数字只在唯一事实源出现，
   其余文档引用而不复述；新增治理测试锁定；
4. **英文版与中文版结论不一致**：英文版由中文版逐节翻译，并加治理测试断言关键数字一致；
5. **审计脚本给假阳性安全感**：扫描规则必须有对应的负测试（故意放一个假 secret 能被抓到）；
6. **面试官审核走过场**：reviewer 不给本会话上下文，只给仓库和一句岗位设定。

### 影响文件（预计）

- T1：全仓 `.py`、`pyproject.toml`、`.github/workflows/ci.yml`；
- T2：新增 `configs/retail_ops/evaluate/retail_ops_v1_r5_rebuild_seed{0,1}_candidate.yaml`、
  `docs/REBUILD_VERIFICATION.md`、`tests/test_retail_ops_r5_cli.py`；
- T3：新增 `LICENSE`、`NOTICE.md`、`scripts/ci/audit_public_release.py`、对应测试；
- T4：新增 `docs/FAULT_MATRIX.md`、`tests/` 补缺口；
- T5：`README.md`、新增 `README.en.md`、`tests/test_project_governance.py`；
- T6：`docs/RESUME_EVIDENCE.md`、新增 `docs/INTERVIEW_PREP.md`；
- T7：`docs/EXECUTION_PLAN.md`、`docs/PROJECT_LOG.md`、`progress.md`、`findings.md`。

### 验收命令与预期产物

```bash
.venv/bin/pytest -q                    # 起始 907 passed，只增不减
.venv/bin/ruff check .
.venv/bin/ruff format --check .        # 本轮新增为硬门禁
.venv/bin/mypy
env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check
git diff --check
.venv/bin/python scripts/ci/verify_qualification_chain.py
.venv/bin/python scripts/ci/audit_public_release.py   # 本轮新增
```

另需证明：`formal-release-001/002`、R1 qualification 的 `release.json` 仍能加载；
48 份已有运行证据的哈希复算不变。

### 授权状态

GPU **是**（用户 2026-08-16 授权，仅 dev 轨道，不碰封存 holdout）、
商业 API **否**（两台机器均无 `TEACHER_LLM_*` 凭据）、模型下载 **否**、
封存 holdout 执行 **否**、公开发布推送 **否**（留给用户）、新运行时依赖 **否**。

### 进度

- [x] 0. 上下文读取、基线确认（907 passed）、后台 shell 核查（属另一项目，与本仓库无关）
- [x] 1. `task_plan.md` 重写为 R5
- [x] 2. **T2 GPU 独立重建复验**：seed 0 与 seed 1 各重训 + dev 配对评测；
      58/60 与 60/60（base 54/60）→ SPEC §6 第 6 条满足；
      **同时发现同 seed 不可逐位复现**（LOG-20260816-05）
- [x] 3. T1 代码整洁性：全仓 format（58 文件）+ lint 集扩展（45 处）+ format 进 CI
- [x] 4. T3 公开发布审计：`LICENSE` / `NOTICE.md` / `audit_public_release.py` / 19 项测试
- [x] 5. T4 故障注入矩阵：`FAULT_MATRIX.md` + 文档-测试绑定（已突变验证）；
      修掉 teacher client 无超时的真缺陷（LOG-20260816-06）
- [x] 6. T5 对外文档：README 重写 + `README.en.md`，关键数字由治理测试断言一致
- [x] 7. T6 求职材料：`INTERVIEW_PREP.md` + `RESUME_EVIDENCE.md` bullet 定稿
- [x] 8. T7 收口：`EXECUTION_PLAN` R5 标完成、`PROJECT_LOG` 两条、接管文档漂移收口、
      最终门禁 **944 passed** 全绿、三次提交
- [x] 9. **T8 独立面试官审核已通过**（LOG-20260816-07）。两轮，reviewer 不带本会话上下文、
      自跑全部门禁、自查数字。第一轮 **PASS 8/10** + 4 条阻塞项（**四条全部属实，
      且全部落在本项目自己的卖点「数字纪律」上**）；逐条收口后第二轮
      **PASS，4/4 解除，8 → 8.5/10**。
      收口过程中我自己又漏了 5 处残留 → 据此把「文档数字绑到可执行校验」变成常设做法。
- [x] 10. 收尾封存：PROJECT_LOG 三条（-05/-06/-07）、progress 台账、最终门禁、
      远端同步、`v1.0-r5` 标签

## Task Rules

- 本文件只跟踪当前任务；长期阶段状态以 `docs/EXECUTION_PLAN.md` 为准。
- 新任务开始时重写 Current Task，保留已完成任务的摘要到 `progress.md`。
- 输入、输出、非目标、失败模式和验收命令不完整时不得开始实现。
- GPU、API、数据下载和公开发布必须显式标注授权状态。

## Errors

| Date | Error | Resolution |
|---|---|---|
| 2026-08-16 | R5 重建复验首次起跑漏了 `--input_dir`，CLI 硬失败退出（未产生任何输出目录） | 私有训练数据根是 `data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722`；补参数后重跑，两次失败均未污染产物树 |

（R0–R4.5 的历史错误台账已归档到 `progress.md`，本表只保留当前阶段。）
