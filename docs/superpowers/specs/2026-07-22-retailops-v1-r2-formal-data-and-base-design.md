# RetailOps v1 R2 正式数据与双模型 Base 设计

## 状态

- 日期：2026-07-22
- 状态：用户已批准，允许进入 CPU 实现
- 分支：`feature/r2-formal-data-and-base-eval`
- 起点：`a3c748bdad1ce6fb7ec8a838d2f1f36da0bbae60`
- 数据版本：`retail_ops_v1_r2_20260722`
- 生成器：`family_sha256_v1`
- seed：`0`

## 目标与边界

R2 交付 RetailOps v1 的正式 train/dev/holdout 数据合同、可审计的混合 teacher
数据生成、密封 holdout evaluator 合同，以及 Qwen3-1.7B/4B 两份真实 dev base。
R2 不训练 adapter，不执行 SFT、DPO、GRPO，不在正式 holdout 上运行模型，不修改或
读取 BFCL 固定 200 条及其失败样例用于开发、调参或 prompt 修改。

本地 WSL 只运行 CPU 测试、lint、类型检查、假后端和轻量数据构建。正式数据生成、API、
模型下载、SSH、远端环境修改和每条 GPU 命令均保留独立用户批准门。不得自动 push、merge、
发布、创建 remote 或更改 Python 包名 `veritool_rl`。

## 正式任务合同

沿用 R1 冻结的两个业务工具和六类任务：

1. `lookup_status`
2. `refund_eligible`
3. `refund_denied_window`
4. `refund_denied_ownership`
5. `refund_denied_duplicate`
6. `refund_recovery`

每类由 35 个 semantic family 构成，每个 family 生成两个固定表述变体。35 个 family
精确来自 `state_variant=0..6` 与 `context_variant=0..4` 的笛卡尔积。`state_variant` 对 lookup
依次绑定 `pending/processing/shipped/delivered/cancelled/returned/refunded` 七个订单状态，对允许、
恢复和所有拒绝场景依次绑定 `1/2/3/5/7/10/14` 七个确定性的窗口 margin，并由场景决定 margin
位于允许侧或拒绝侧；
`context_variant` 绑定 0..4 个不相关 distractor order。退款原因按
`(scenario_index + state_variant * 5 + context_variant) % 4` 映射到 bundle 已批准的四个原因，
每类覆盖数为 8 或 9；`get_store_hours` 只保留在冻结 tool schema 中，不进入 expected calls。
family canonical payload 是 `dataset_version/scenario/state_variant/context_variant/primary_policy_state/
reason/distractor_count/expected_decision/required_reads/call_sequence/transient_failure_rule`。表述变体
只改变用户表面表达和 opaque 实体值，不能改变正确答案。

生成顺序固定为：构造 family canonical payload → 计算 family fingerprint → 按 fingerprint
排序 → 每类分配 train/dev/holdout=`20/5/10` families → 再物化两个任务变体。最终每类任务
为 `40/10/20`，总计 `240/60/120`。任一类别或总量不精确时构建失败，不允许补抽、截断或
跨类别挪用。

每条任务同时具有：

- opaque task fingerprint：绑定完整任务身份，但不公开原始 ID；
- family fingerprint：绑定规范化语义，不受表述变体影响；
- answer-free content fingerprint：绑定精确 canonical projection
  `scenario/user_request/initial_state/transient_failures/max_steps`；明确排除 `task_id`、`split`、
  `target_state`、`expected_calls`、`expected_decision`、`required_reads` 和全部 `metadata`；
- source fingerprint：绑定生成来源 family；
- derivation fingerprint：绑定可导致答案等价的语义派生关系。

train/dev/holdout 必须在 task、family、answer-free content、source 和 derivation 五个维度
两两不相交。分割后才允许写任务；不得先生成任务再按 task ID 分割。

## Manifest 与私有边界

新增 R2 专用 `FormalTaskManifest` 和 `FormalHoldoutReceipt`，不改变 R1 `TaskManifest`、
`HoldoutReceipt` 与 qualification 证据语义。正式私有根为：

`data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722/`

其中保存完整 task truth、reference/teacher 原始响应、轨迹、holdout 和不可覆盖 attempt。
公开 answer-free 元数据根为：

`manifests/retail_ops/v1/retail_ops_v1_r2_20260722/`

公开文件只允许数据版本、bundle/generator/parser/evaluator ID、seed、配额、顺序化 opaque
fingerprint、route snapshot、文件 SHA-256 和聚合质量指标。不得包含 user request、初始或
目标状态、期望调用、预期决策、原始 task/family ID、失败样例 ID、完整轨迹或密钥。

holdout 授权采用两段式：先在不读取内容的前提下验证 `release` purpose、私有路径和整文件
SHA-256；授权后才解析 JSONL，并逐行验证 receipt 中的版本、类别、顺序、计数和五类指纹。
开发用途必须在打开私有文件前失败。密封 evaluator 的完整输出保存在 private root，对外
只写固定 allowlist 的聚合指标、运行 provenance 和失败 taxonomy 计数。

R2 只用临时 fake holdout 验证 evaluator 合同，不在正式 holdout 上运行 base。正式 holdout
冻结、授权与未来 R3 配对评测只能由主 agent 串行执行；子 agent 不得读取私有路径。

正式 dev loader 允许 `develop` purpose，但只解析 receipt 明确标为 `dev` 的 private artifact；
它先验证 private artifact SHA-256 与公开 dev manifest，再逐行验证 dataset/split/计数/类别/顺序
和五类 fingerprint。`evaluate_formal_dev_base` 只接受该 loader 返回的已验证 records 与对应公开
manifest。CLI 的 `--input_dir` 指向数据版本 private root，并固定解析 `dev.jsonl`；传入 holdout
receipt、`holdout.jsonl` 或 release purpose 均失败。因此 dev base 经 private artifact SHA-256 和公开 dev manifest 双重校验，同时没有通往正式 holdout 的开发入口。

## Provider-Agnostic Teacher

teacher 采用 OpenAI-compatible Chat Completions 与 tool calls 协议，代码不硬编码 provider、
base URL、API key、model 或 provider 专用 request body。`.env` 使用 selector 与动态命名空间：

```dotenv
TEACHER_LLM_PROVIDER=deepseek
TEACHER_LLM_DEEPSEEK_BASE_URL=https://api.deepseek.com
TEACHER_LLM_DEEPSEEK_API_KEY=...
TEACHER_LLM_DEEPSEEK_MODEL=deepseek-v4-pro
TEACHER_LLM_DEEPSEEK_EXTRA_BODY_JSON={"thinking":{"type":"disabled"}}
```

provider 名仅允许 `[a-z][a-z0-9_]*`，规范化为大写环境变量前缀。`BASE_URL` 必须是 HTTPS，
禁止 userinfo、query、fragment；`EXTRA_BODY_JSON` 必须是有限大小的 JSON object，并递归拒绝
键名包含 `key`、`token`、`authorization`、`secret`。不得记录 API key 或 key 哈希。

每次运行先生成 `TeacherRouteSnapshot`，记录 provider、规范化 base URL、model、extra body、
协议 ID 与 canonical SHA-256。smoke/full/resume 都必须绑定同一 route fingerprint；route 变化
必须新建 attempt 并重新 smoke，不得回退到未选择 provider。

初始 profile 为 DeepSeek `deepseek-v4-pro` 非思考模式，但正式数据只绑定用户在 API 门前
确认的 route snapshot。生成参数固定 temperature 0、每个 task 最多两个 episode、每个 episode
最多五步。网络层只重试 timeout、429 和 5xx，最多三次总请求尝试；401/403/4xx schema 错误
立即停止。没有金额预算上限，但必须记录请求数和服务端 usage；缺 usage 记为 provenance 缺失，
不得伪造 token 数。

## Teacher 数据与质量门

teacher 只接收 240 条 train task；dev 使用 internal reference；holdout 不发送给任何 API。
先运行每类一条、共六条 smoke，报告 route、结构化调用成功率、环境成功率、请求数、token 和
错误分类。用户单独批准后才运行 240 条全量。

每次 smoke 或全量采集的原始响应、normalized step、完整轨迹、usage、错误分类、checkpoint
和逐文件哈希只能写入 private ignored root 的 `teacher-collection/<attempt>/`；目录不可覆盖，
恢复时必须先验证 route/config/task/bundle/manifest 与 artifact 哈希。公开路径不得保存这些逐任务
采集内容。

teacher 轨迹只有同时满足以下条件才合格：

- tool call schema 可解析且参数合法；
- 在真实 `RetailOpsEnv` 中执行完成；
- 最终状态、预期决策、政策违规和非法调用判据正确；
- 用独立 replay 从初始状态重放得到相同结果；
- 轨迹与 task/route/config/hash 一致。

全量结束后，teacher 总通过率必须至少 70%，每类至少 50%。未达到即停止并记录失败，不自动
改 prompt、模型或 provider。达到门槛后，每个 train task 导出恰一条轨迹：合格 teacher
优先，否则使用同一正式 task 的 deterministic internal reference。最终正好 240 条，全部
schema-valid、environment-valid、policy-valid、replayable，并报告 teacher yield 与 fallback。

`train.jsonl` 与 `sft.jsonl` 只能写入 private ignored root 的不可覆盖
`train-export/<attempt>/`；同目录保存完整 `evidence.json` 和逐文件哈希。公开 manifest 根只允许
写 answer-free `quality.json`，字段固定为 dataset/route/config/bundle/manifest hash、总量、六类
聚合 teacher yield/fallback、schema/environment/policy/replay 计数和 private artifact SHA-256；
不得复制 prompt、messages、tools、task/family ID、失败 ID 或逐任务映射。

## 双模型 Dev Base

固定模型：

- `Qwen/Qwen3-1.7B@70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`
- `Qwen/Qwen3-4B@1cfa9a7208912126459214e8b04321603b3df60c`

两者消费同一 60 条 dev、相同 bundle、manifest、system prompt、tool schema、parser、seed 0、
`do_sample=false`、`enable_thinking=false`、4-bit NF4、最多五步，且 adapter path 必须为空。
只输出 dev 聚合指标，不打开正式 holdout，不产生 R2 GO/NO-GO。

`BaseRunEvidence` 必须绑定模型 repo/revision、本地模型文件逐项哈希、代码 commit、`uv.lock`
哈希、bundle/manifest/parser/system prompt/config 哈希、生成参数、GPU physical index/UUID/name、
CUDA 映射、峰值显存、wall time、吞吐、token/延迟、完整 private artifact 哈希与公开报告哈希。

远端项目根固定 `/data/TJK/internship-projects/retail-agent-ops`；每个 commit 使用不可覆盖的
`source/<commit>` 快照。模型根固定 `/data/TJK/models`，目标目录分别为
`Qwen3-1.7B-70d244cc86cc` 与 `Qwen3-4B-1cfa9a720891`。真实命令必须在执行前根据只读盘点
结果写出完整命令、实际 cwd、物理 GPU、预计时长和产物，并逐条等待用户批准。

## CLI 与运行产物

不新增顶层产品命令。`retail-agent-ops build/evaluate/release/serve` 保持稳定，R1 无
`pipeline` 配置继续按原路径执行。R2 使用严格 pipeline：

- `build` + `formal_freeze`
- `build` + `teacher_collect`
- `build` + `train_export`
- `evaluate` + `formal_dev_base`

每个 pipeline 使用精确配置键集合；未知、多余或缺失字段失败。R2 build 可使用可选
`--input_dir` 指向同数据版本的私有根；输出目录始终不可覆盖。resume 只复用 task、route、
config、bundle、manifest 哈希完全相同且已经验证的 checkpoint，否则新建 attempt。

## 验收与停止规则

CPU 阶段必须覆盖精确配额、重复构建字节一致、answer-free public artifacts、五维隔离、
receipt/逐行篡改、purpose-before-read、selector 切换、secret redaction、API fake retry/resume、
teacher 阈值/fallback、真实环境 replay、fake hardware provenance、adapter/holdout 拒绝和全部 R1
回归。

任何正式数据生成、API、模型下载、SSH 或 GPU 前必须暂停并等待用户明确批准。外部调用失败、
数据质量未达门、route 改变、模型 revision/hash 不符、磁盘或 GPU 条件不满足时记录失败并停止，
不得扩大范围或绕过门禁。

最终必须在实际最终 HEAD 运行 `.venv/bin/pytest -q`、`.venv/bin/ruff check .`、
`.venv/bin/mypy`、`uv lock --check` 与 `git diff --check`。只有正式数据、teacher 全量、两份
真实 dev base、文档和哈希证据全部完成后才把 R2 标为完成。
