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
