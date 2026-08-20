# 业界工具对照矩阵

本文件回答 R8 第一轮独立审查 A2 的硬扣分项：「这套自建证据链相比 MLflow Tracking +
W&B Artifacts + DVC pipeline + Evidently drift 检测，新增了什么、牺牲了什么」。
面试官第一反应是"为什么不用业界已有"——这里逐条给坐标。

## 一句话坐标

**本项目不是 MLflow / W&B / DVC / Evidently 的替代品，是它们都不做的"发布判定"层**：
上面四家都能记、能跟踪、能版本化、能检测 drift，但**没有一个把"该不该上线"做成
配对证据 + 版本化门禁 + 封存 holdout 台账的可审计决策**。本项目补的就是这一层。

## 功能对照（5 工具 × 8 维度）

| 维度 | MLflow Tracking | W&B Artifacts | DVC | Evidently | **本项目** |
|---|---|---|---|---|---|
| **跑记什么** | 参数 / 指标 / artifact | 同 MLflow + 可视化 | 数据/模型版本 + pipeline | 数据 drift + 数据质量 | 逐任务轨迹 + 最终状态 + 政策 verifier |
| **run_id 怎么来** | 自增整数或 UUID | 同 MLflow | commit hash | 自增 | **全字段自哈希（SHA-256）** |
| **配对可比性** | 无（两次 run 各自记） | 无 | 无 | 无 | **逐字段同条件校验，任一不符拒绝给 delta** |
| **运行环境绑定** | 无（只记 Python 包版本可选） | 同 MLflow | 无 | 无 | `runtime_env_sha256`（实际装的包摘要，非 lock 文件） |
| **数据版本化** | 无（artifact 级） | 同 MLflow | **是（核心能力）** | 无 | manifest + 五维指纹 + 内容哈希 |
| **发布判定** | 无（只记指标） | 无 | 无 | 无 | **GO/NO-GO + 失败门禁 + 阈值版本化** |
| **封存 holdout** | 无 | 无 | 无 | 无 | **两段式授权 + 台账 + 不反馈开发** |
| **证据不可伪造** | 弱（可改 run_id） | 弱 | 中（commit hash） | 弱 | **强（自哈希 + 逐字段配对 + 阈值入 bundle_sha256）** |

## 各家"能做什么、不能做什么、本项目补在哪"

### MLflow Tracking
- **能做**：记参数 / 指标 / artifact，autolog 接 HuggingFace / PyTorch；`mlflow.models` 推理部署。
- **不能做**：配对可比性（两次 run 各自记，没有"同条件才能比"）；运行环境指纹（`uv_lock_sha256` 哈希的是文件不是实际装的包）；发布判定（只记指标，不出 GO/NO-GO）。
- **本项目补在哪**：`run_id = sha256(全字段)` 让"改一个字节就对不上"成为结构事实；`runtime_env_sha256` 哈希实际装的包；`build_release_gates` 把指标变成版本化门禁决策。

### W&B Artifacts
- **能做**：artifact 版本化 + lineage + 可视化 dashboard；团队协作。
- **不能做**：配对可比性（同 MLflow）；封存 holdout（artifact 是可反复读的，没有"两段式授权 + 不反馈开发"的语义）；证据不可伪造（artifact 版本可被覆盖）。
- **本项目补在哪**：封存 holdout 两段式授权 + 台账；输出目录不可覆盖（`exist_ok=False`）；`report_id` 自哈希让覆盖即作废。

### DVC
- **能做**：数据/模型版本化（核心能力）；pipeline 重现（`dvc.yaml` + `dvc.lock`）。
- **不能做**：发布判定（只版本化，不出 GO/NO-GO）；配对可比性（两次 run 用同一份 `dvc.lock` 不等于"同条件"，因为 `dvc.lock` 哈希的是文件不是实际装的包——和本项目 `uv_lock_sha256` 同一个洞）；运行环境指纹。
- **本项目补在哪**：`runtime_env_sha256` 补 DVC 没补的"实际装的包"；`build_release_gates` 把"数据版本相同"升级为"发布判定可审计"。

### Evidently
- **能做**：数据 drift 检测 + 数据质量报告 + 模型质量监控。
- **不能做**：发布判定（只检测 drift，不出 GO/NO-GO）；任务级真值（drift 是分布层面，不是"这条任务对没对"）；政策 verifier（业务规则可执行）。
- **本项目补在哪**：`verifier` 是业务政策可执行规则（退款到底有没有发生、有没有违反业务规则），不是分布 drift；最终状态校验是任务级真值，不是文本相似度。

### Great Expectations（同类参照，未单列）
- **能做**：数据质量断言 + 数据 contract。
- **不能做**：发布判定；模型行为校验（GE 校验数据，不校验模型输出）。
- **本项目补在哪**：`policy_verifier` 校验模型行为是否违反业务政策，GE 校验数据是否符合 schema——两者正交。

## 本项目"牺牲了什么"

诚实交代自建证据链的代价：

1. **不可移植到任意仓库**：证据系统依赖本仓库的目录结构、`bundle_sha256`、私有产物路径。换到面试官公司，这套不能直接用——它不是 library，是一个紧贴单一领域的工程。R8 Task A2 用第二个 toy 域实证了 `core → devops_ops` 分层成立，但仍然需要该域实现自己的 domain/build/evaluate/release。
2. **没有协作能力**：MLflow / W&B 有团队 dashboard、权限、协作流。本项目是单仓库、单人、append-only 台账，没有多用户概念。封存 holdout 两段式授权是单机进程内机制，不防多人共谋。
3. **没有可视化**：MLflow / W&B 有 UI。本项目只有 HTML 报告 + Markdown 台账，没有交互式 dashboard。
4. **数据版本化弱于 DVC**：本项目用 manifest + 内容哈希，但不像 DVC 那样有 pipeline 重现（`dvc repro`）。本项目的 pipeline 重现靠 `verify_qualification_chain.py` 一条命令，不是声明式 DAG。
5. **drift 检测弱于 Evidently**：本项目只校验"这次运行 vs 上次运行"的配对可比性，不做分布 drift 检测。
6. **生态接不上**：MLflow 有 `mlflow.evaluate`、`mlflow.models.serve`；本项目没有等价物，serve 是独立的 FastAPI。

## MLflow 导出器（桥接，不替代）

`scripts/export_mlflow.py` 把本项目的 `candidate-report.json` 导成 MLflow 可消费格式：
- `mlflow.log_metrics` 记录 `task_success` / `policy_violation_count` / `p95_latency_ms` 等核心指标
- `mlflow.log_artifact` 记录完整 `candidate-report.json` 作为不可篡改 artifact
- `mlflow.log_param` 记录 `model_revision` / `code_commit` / `inference_engine` 等运行条件

**这桥接不替代**：导出去的 MLflow run 仍然只有"记指标"的能力，没有"配对可比性 +
发布判定"的能力。面试官用 MLflow UI 看指标，用本项目看判定。

## 一句话口径（面试用）

> 我没有重造 MLflow / W&B / DVC。它们都解决"记什么、跟踪什么、版本化什么"；
> 我解决的是"该不该上线"——配对证据 + 版本化门禁 + 封存 holdout 台账。
> MLflow / W&B 记完指标后，GO/NO-GO 仍然是人看曲线决定的；我把它做成
> `改一个阈值会让磁盘上每一份已有证据配对失败`的结构事实。
> 业界工具桥接在 `scripts/export_mlflow.py`——指标可以导出去用 MLflow UI 看，
> 但判定回到本项目的 `release` 命令。
