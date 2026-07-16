# reports/ 实验记录

分层结构 (见工作区 `AGENTS.md`「实验记录要求」): 每次实验产出可复现记录, 至少包含配置、日志、指标、图表。

约定布局:

```
reports/<experiment>/<run_id>/
├── config.yaml     # 本次运行冻结配置
├── metrics.json    # 关键指标 (含均值/方差或置信区间)
├── log.txt         # 运行日志
├── trajectories.jsonl # 逐任务可重放证据 (评测运行)
├── failures.jsonl  # 失败任务摘要 (评测运行)
├── comparison.jsonl # 训练前后逐任务配对 (汇总运行)
└── figures/        # 图表 (消融对照、鲁棒性曲线、成本-质量 Pareto)
```

结果优先写入此处, 便于回传、聚合与复核。权重 / checkpoint / 大文件不进 git (见 `.gitignore`)。

BFCL 运行额外保留 `manifest.json`、`raw_generations.jsonl`、官方 result/score、
`metrics.json`、`failures.jsonl`、`run.log` 和 `report.md`。其中官方 score 与
`failures.jsonl` 含原始 prompt、function schema 和 possible answer，只在本地及
远程审计目录保留并由 `.gitignore` 排除；模型权重和独立 evaluator `.venv` 同样
不进入 git。

BFCL SFT 运行还保留 `data_audit.json`、训练 `metrics.json`、
`trainer_log_history.json` 和 Base/SFT `comparison.jsonl`。split manifest 只含
task_id、类别、commit、源文件哈希和选择算法；派生 train/dev JSONL、adapter、
checkpoint、官方逐题 score、完整失败分析与 smoke 目录不进入 git。
