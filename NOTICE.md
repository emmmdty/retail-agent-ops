# NOTICE — 第三方组件与分发边界

本仓库自身以 MIT 许可（见 [`LICENSE`](./LICENSE)）。本文件声明它**引用但不分发**的
第三方组件，以及公开这个仓库时明确**不包含**的东西。

`scripts/ci/audit_public_release.py` 会对被 Git 跟踪的文件重新验证下面的每一条边界；
它是 CI 的一个步骤，不是一份只写在文档里的承诺。

## 1. 引用但不分发的第三方组件

| 组件 | 许可 | 在本项目中的角色 | 是否进入本仓库 |
|---|---|---|---|
| [Qwen3-4B](https://huggingface.co/Qwen/Qwen3-4B) / [Qwen3-1.7B](https://huggingface.co/Qwen/Qwen3-1.7B)（阿里巴巴） | Apache-2.0 | 被适配的基座模型 | **否**。配置里只固定 `revision` 与逐文件 SHA-256，权重由使用者自行获取 |
| [Gorilla / BFCL](https://github.com/ShishirPatil/gorilla)（UC Berkeley） | Apache-2.0 | legacy 轨道的外部单轮 AST 回归 | **否**。固定 commit `6ea5797…`，按 `data/external_repos/BFCL_PIN.txt` 自行 checkout |
| PyTorch / Transformers / TRL / PEFT / bitsandbytes / FastAPI / pydantic 等 | 各自开源许可 | 运行时依赖 | **否**。由 `uv.lock` 逐版本固定，按需安装 |
| vLLM | Apache-2.0 | 引擎替换对照的**旁证**环境 | **否**。装在独立 venv，项目 `uv.lock` 一个字节未动（见 `docs/ENGINE_SUBSTITUTION.md`） |

`domains/retail_ops/v1` 与 `domains/retail_ops/v2` 的工具 schema、业务政策与任务模板
是本项目自己写的合成零售场景，不来自任何客户或真实业务系统。

## 2. 公开这个仓库时明确不包含的东西

| 不包含 | 原因 | 强制方式 |
|---|---|---|
| 模型权重、adapter、合并权重 | 体积与许可；本项目只固定它们的哈希 | `.gitignore` 覆盖 `models/`；审计脚本扫描被跟踪文件里的权重扩展名 |
| 训练/dev/holdout 的**任务真值与轨迹** | 封存 holdout 的答案一旦公开，此后任何评测都不再有意义 | `.gitignore` 覆盖 `data/private/`；两段式授权门 + 审计脚本扫描 |
| API key、`.env`、任何凭据 | 安全 | 审计脚本扫描 + `test_service_credentials_never_live_in_the_repo` |
| 正式运行产物（`reports/retail_ops/`） | 体积；公开的是 manifest 与哈希，不是原始轨迹 | `.gitignore` + CI 的「工作树保持干净」步骤 |

**公开的是什么**：代码、配置、领域 bundle、公开 manifest（含哈希）、文档与全部结论，
包括负结果。任何人可以用自己的模型与数据重跑同一条链路；无法做的是"重放我这一次的
具体轨迹"——那需要私有产物，而那些产物本来就不该公开。

## 3. Benchmark 声明边界

- 本项目的主结论**全部**来自内部冻结的 RetailOps 任务集，那不是任何公开榜单。
- BFCL 相关读数（Qwen3-1.7B 固定 200 条单轮 AST 子集，Base/SFT 163/200 与 167/200）
  是**项目自己划的固定子集**，不是官方 BFCL 全量成绩，也不是排行榜名次；
  差值置信区间跨 0，不得声称稳定提升。
- τ²-bench / ToolSandbox / AppWorld 当前**零引用**，未做，不得暗示做过。
