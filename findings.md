# Findings: RetailAgentOps

## Stable Facts

- 产品定位已经从研究型 VeriTool-RL 改为工程型 RetailAgentOps。
- 当前 Python 包名仍为 `veritool_rl`；产品改名不等于代码包已改名。
- 现有 MiniRetail 和 BFCL 能支撑流水线起点，但不能证明真实生产价值。
- BFCL Base/SFT 的 +2 个百分点置信区间跨 0，不能写成稳定提升。
- 固定 200 条 holdout 是硬隔离边界，不能用于后续优化。
- 默认单卡 4090、一个开发训练 seed；最终简历数字才做一次独立重建。
- 最值得优先验证的是数据执行质量、parser/模板、政策 verifier 和发布门禁，不是 GRPO。

## Current Initialization Findings

- 隔离 worktree 基线为 107 tests passed，Ruff 与 mypy 通过。
- BFCL evaluator 使用独立 `tools/bfcl_eval/.venv`，避免依赖污染。
- benchmark checkout 通过 ignored 软链接共享，Git 历史和原工作区保持不变。
- 项目治理测试 5 项已通过，活跃文档不再把论文、多 seed 或 GRPO 设为默认交付。
- 本机 uv 还受到 `UV_INDEX_URL` 之外的索引配置影响；冻结环境可直接用 `.venv/bin/*` 验收而不改 lockfile。

## Open Questions

- R1 开始前需要用户确认内部 RetailOps v1 任务契约和冻结 holdout 生成规则。
- Qwen3-4B 下载、单卡 smoke 和 API 教师模型选择均不属于 R0。

## R1 Decision Preparation

- R1 的最小闭环已经固定为 `build -> evaluate -> release -> serve`，且本阶段不进行正式训练。
- RetailOps 内部任务必须以最终状态、政策违规、非法工具调用和参数错误为主判据；语言质量不能替代执行真值。
- 固定 BFCL 200 条及其失败样例只能用于窄口径外部回归，不能作为 RetailOps v1 的开发数据或内部 holdout。
- 用户选择任务契约与冻结规则前，`docs/EXECUTION_PLAN.md` 的 R1 状态必须保持“待执行”。
- 当前分支为 `portfolio/retail-agent-ops-init`，HEAD 为 `5e25bd7`；核对时除本轮治理记录外没有其他未提交改动。
- `SPEC.md` 已冻结稳定入口、主指标和默认发布门槛，但尚未冻结 RetailOps v1 的具体工具 schema、任务规模、政策条款和内部 holdout 生成算法。
- 当前受版本控制资产以 MiniRetail、BFCL 和通用 trajectory/evaluator 为主，尚无正式 domain bundle、release policy 或 serve 模块。
- MiniRetail 当前包含 `get_order`、`refund_order` 两个业务工具，4 类任务和 4 条退款约束；schema 扰动另加一个门店营业时间干扰工具。
- MiniRetail 默认切分为 128/32/32，但按 split/seed 动态生成，当前没有独立 RetailOps holdout manifest、内容哈希或禁止开发读取的加载边界。
- `TaskSpec` 内嵌 `target_state` 与 `expected_calls`，现有 `Evaluator` 还会把完整任务随 trajectory 写入产物；仅做 ID 互斥不足以防止 holdout 答案进入开发分析。
- 当前 `cli.py` 只提供通用参数解析与配置加载，尚未实现产品要求的 `build/evaluate/release/serve` 命令面。
- 现有评测已支持顺序执行、replay、确定性指标和 base/adapter 配对，但缺 run manifest、证据完整率、p95 延迟、版本化门禁和 HTML/Markdown 发布报告。
- `pyproject.toml` 尚无 FastAPI/服务依赖或产品命令 entry point，项目描述仍保留旧研究定位文本。
- 现有 `mvp_eval_*` 配置只声明 `environment: mini_retail` 与 `split: test`，未绑定 task manifest、bundle/policy 版本或哈希。
- `scripts/evaluate.py` 按运行 seed 重新生成评测任务；`scripts/build_trajectories.py` 将 test 的完整 task/trajectory 写入普通输出目录，且 manifest 只哈希 trajectory 文件，不能充当 sealed holdout。
- R1 的 holdout 执行入口应只消费冻结 manifest，开发可见 evidence 不应默认包含 `target_state`、`expected_calls` 或原始失败样例。
- 当前 BFCL 200 条 manifest 的 SHA-256 已复核为 `a74a3748d3af289e8d3f808930b99b6eb5cb9c7d84ba678ff627c762e9448da9`；RetailOps 两案均不修改或复用该集合。
- R1 应只用 qualification fixture 验证契约与门禁；正式 RetailOps train/dev/holdout 数据及 manifest 按批准配额留到 R2 冻结。
- 用户已选择方案 A：RetailOps v1 采用 2 个正式业务工具、6 类任务、R1 qualification 12 条，R2 目标配额 train/dev/holdout 为 `240/60/120`。
- 方案 A 的正确拒绝必须与 policy violation 分开验证；`policy_denied` 不能自动计为成功或失败，取决于任务期望决策与模型是否实际尝试被禁止变更。
- 方案 A 设计规格已写入 `docs/superpowers/specs/2026-07-20-retailops-v1-contract-design.md`；用户复核前不创建实现计划。
