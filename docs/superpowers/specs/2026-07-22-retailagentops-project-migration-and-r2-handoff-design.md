# RetailAgentOps 正式目录迁移与 R2 Codex 交接设计

## 批准背景

用户已在 2026-07-22 明确要求完成项目迁移，并在新目录写入一份可供 Codex 完整执行、验证 R2 的交接提示词；用户允许 R2 执行时使用 subagent。上一轮已确认推荐目标为：

`/home/tjk/myProjects/internship-projects/retail-agent-ops`

本设计只把现有独立 Git 仓库迁入正式目录并准备 R2 交接，不在本轮执行 R2 产品工作。

## 目标

- 保留当前完整 Git 历史、分支 `portfolio/retail-agent-ops-init`、R1 本地证据和 ignored 资产；
- 把仓库从容易被误解为临时 worktree 的 `.worktrees/retail-agent-ops` 迁到正式项目路径；
- 重建包含旧绝对 shebang 的主 uv 环境和 BFCL evaluator uv 环境；
- 修复 `data/external_repos` 在新目录层级下的相对软链接；
- 写入一份可直接复制给新 Codex 会话的 R2 执行提示词，覆盖决策门、subagent 协作、TDD、holdout 隔离、远程 GPU 审批、验收和停止规则；
- 在新目录验证 Git、环境、测试、静态检查、软链接、固定 benchmark commit 与提示词完整性。

## 非目标

- 不重新 `git init`，不复制出第二份活动仓库，不创建 remote 或公开仓库；
- 不重命名 Python 包 `veritool_rl`，不清理旧 MiniRetail/BFCL/训练代码；
- 不生成正式 R2 train/dev/holdout，不访问 holdout 真值；
- 不调用商业 API，不下载模型，不运行本地或远程 GPU；
- 不在交接提示词中把 QLoRA-SFT、DPO、GRPO 或在线 RL 提前纳入 R2。

## 方案比较

### 方案 A：原子移动现有独立仓库（采用）

把当前 201M 目录在同一文件系统内移动到正式路径，保留 `.git`、ignored 证据和全部历史；随后重建路径敏感环境与链接。

优点：只有一个事实源；不产生双仓库漂移；Git 对象和 ignored R1 证据完整；目标路径清晰。

风险：旧 `.venv/bin/*` 绝对 shebang 和旧层级相对软链接会失效，必须在验证前重建。

### 方案 B：复制或本地 clone 到新路径（不采用）

优点：旧目录可作为长期副本。

缺点：ignored 数据、环境和软链接不能由普通 clone 完整迁移；复制会同时留下两份活动仓库，后续极易在错误目录继续提交。

### 方案 C：继续保留 `.worktrees/` 路径（不采用）

技术上可以工作，但目录语义仍像临时 worktree，容易在后续维护、脚本或人工清理中被误判，且不适合作为正式求职项目入口。

## 迁移架构与回滚

1. 在旧目录记录 HEAD、状态、目标不存在、磁盘空间、软链接真实目标和 211-test CPU 基线。
2. 提交本设计、迁移计划和 planning 状态，使移动前 Git 工作树干净。
3. 同文件系统移动整个仓库到正式路径；不删除 `.git`，不改写历史。
4. 在 `/tmp` 创建唯一迁移备份目录，把旧主 `.venv`、BFCL evaluator `.venv` 和旧软链接移入备份。
5. 在新目录以冻结 lock 重建两个 uv 环境，创建指向 `../../veritool-rl/data/external_repos` 的新相对链接。
6. 若环境/链接重建失败，停止继续写文档；保留 `/tmp` 备份，可把仓库移回旧路径并原样恢复三项路径敏感资产。
7. 只有新目录完整质量门和路径验收通过后，才删除临时备份。

旧路径移动后应不存在；原 `/home/tjk/myProjects/internship-projects/veritool-rl` 仓库不修改。

## R2 交接提示词契约

提示词保存到 `docs/handoffs/2026-07-22-r2-codex-execution-prompt.md`，必须让新 Codex：

1. 从新绝对目录启动，按 `AGENTS.md` 固定顺序恢复上下文；
2. 先执行 read-only preflight，确认当前 HEAD 是 `59cc1b5` 的后代、工作树和 CPU 基线可解释；
3. 把 R2 拆成正式数据/manifest、轨迹质检、sealed holdout evaluator、base 评测和阶段收口等独立 TDD 单元；
4. 在数据来源、teacher/provider/model、计划主模型和任何外部资源运行前给出至少两个方案并等待用户确认；
5. 允许 subagent-driven 实施，但一个任务只允许一个 implementer 写入，独立 reviewer 只读审查，主 agent 负责最终集成验证；
6. 固定目标配额 train/dev/holdout `240/60/120`，六类均衡为每类 `40/10/20`，并按 family、task ID 和内容/派生指纹自动验证无交叉；
7. 把 holdout 原始任务、真值、完整轨迹和逐任务失败保留在 ignored sealed 路径，公共 receipt/report 不包含 prompt、答案、failure ID 或任务真值；
8. 把 QLoRA-SFT 留到 R3；R2 只允许 base evaluation，不得根据 holdout 结果改 parser/prompt/数据或降低门槛；
9. 在任何远程 GPU 命令前报告完整命令、远程工作目录、物理 GPU、预计时长和产物，等待用户确认；
10. 只有新鲜证据满足 R2 的数据、评测、泄漏、质量和完整质量门后才把 R2 标为完成。

## 验收

- 新目录存在、旧目录不存在，`git-dir == git-common-dir`，分支和历史不变，无 remote；
- `.venv/bin/pytest` 和 `.venv/bin/retail-agent-ops` 的 shebang 指向新目录；
- `tools/bfcl_eval/.venv` 可用，`data/external_repos` 解析到原仓库固定 external checkout；
- Gorilla/BFCL checkout 保持既有固定 commit，不下载或更新；
- `.venv/bin/pytest -q`、`.venv/bin/ruff check .`、`.venv/bin/mypy`、`git diff --check`、`uv lock --check` 全部通过；
- 提示词无 `TBD`/`TODO`/占位符，包含新目录、配额、审批门、holdout 硬停机条件、subagent 规则、最终命令和阶段状态更新规则；
- `docs/LEGACY_INVENTORY.md`、planning 文件和 append-only `docs/PROJECT_LOG.md` 记录迁移事实。
