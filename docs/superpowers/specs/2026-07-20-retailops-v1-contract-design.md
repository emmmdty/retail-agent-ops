# RetailOps v1 契约与冻结规则设计

- 日期：2026-07-20
- 状态：方案 A 已获用户选择，等待规格书面复核
- 关联阶段：R1 产品契约与 v0.1
- 关联产品：RetailAgentOps

## 1. 目标与边界

本设计为 RetailAgentOps 固化一个窄而完整的零售退款工具 Agent 契约，支撑
`build -> evaluate -> release -> serve` 的 CPU qualification vertical slice。
R1 只实现契约、执行真值、发布门禁和本地演示；正式 train/dev/holdout 数据在
R2 按本设计冻结。R1 不训练模型、不下载模型、不调用商业 API、不运行 GPU。

本设计不重命名 Python 包 `veritool_rl`，不修改 BFCL 固定 200 条 manifest 或其
evaluator，不把 BFCL 结果当作 RetailOps 内部效果，不引入 DPO、GRPO、在线 RL 或
新的业务领域。

## 2. RetailOps v1 领域契约

### 2.1 工具集合

正式业务工具只有：

| 工具 | 参数 | 副作用 | 约束 |
|---|---|---|---|
| `get_order` | `order_id: string` | 无 | 只能查询当前会话客户可见订单 |
| `refund_order` | `order_id: string`, `reason: enum` | 将符合条件订单置为 `refunded` | 必须先查询，参数无额外字段 |

`get_store_hours(city)` 只作为 schema 扰动和无关工具选择的 qualification distractor，
不属于业务成功路径。所有工具均使用 `additionalProperties: false`；未知工具、缺失
参数、额外参数和错误参数类型都算非法工具调用。

### 2.2 任务类别

R1 qualification fixture 使用 12 条任务，每类 2 条。R2 正式任务池目标为
train/dev/holdout `240/60/120`，六类均衡；这些数字是配额，不代表 R1 已生成正式数据。

| 类别 | 初始状态与期望 | 必须覆盖的行为 |
|---|---|---|
| `lookup_status` | 查询订单，状态不变 | 正确查询并结束，不得退款 |
| `refund_eligible` | 订单在期限内且理由合法，最终退款 | 查询后执行一次退款 |
| `refund_denied_window` | 订单超过期限，状态不变 | 查询后拒绝，不得调用退款 |
| `refund_denied_ownership` | 订单属于其他客户，状态不变 | 不得泄漏或修改他人订单 |
| `refund_denied_duplicate` | 订单已退款，状态不变 | 不得重复退款 |
| `refund_recovery` | 首次退款返回 transient error，随后可成功 | 最多一次重试，最终只产生一次状态变更 |

任务真值由 `initial_state`、`expected_state`、允许的读取行为、政策决策和故障注入
组成。评测不要求所有成功轨迹都匹配一条唯一的 `expected_calls` 序列，但必须满足
必要查询、政策不变量、状态结果和重试上限。

### 2.3 政策约束

1. 退款前必须查询订单。
2. 只能操作当前认证客户拥有的订单。
3. 订单必须在退款期限内，且 `reason` 属于版本化 allowlist。
4. 已退款订单不得再次退款，拒绝路径不得改变状态。
5. transient error 最多允许一次重试，重试不得产生重复状态变更。
6. 工具调用必须通过版本化 schema 和 allowlist；禁止通过自然语言替代工具执行真值。

“正确拒绝”和“违规调用”必须分开：拒绝类任务在模型不调用被禁止的变更工具、完成
必要读取并给出终止响应时可以成功；如果模型实际调用被禁止的退款工具，则记录
policy violation，即使环境最终没有改变状态。`policy_denied` 不是自动成功信号。

## 3. R1 组件与数据流

```text
RetailOps bundle
  -> qualification task loader
  -> policy-aware ToolEnv
  -> Policy/AgentRunner
  -> replay + state/policy verifier
  -> redacted metrics/evidence
  -> release policy
  -> GO candidate or base fallback service
```

### 3.1 Bundle

`domains/retail_ops/v1/` 保存 `bundle.yaml`、`tools.yaml`、`policies.yaml` 和
`release.yaml`。bundle 必须包含 schema version、bundle version、工具 schema 哈希、
政策版本、任务类别和 evaluator 标识。任何评测运行清单都记录 bundle 内容哈希。

### 3.2 任务与环境

新增 RetailOps 专用任务/环境适配层，复用现有严格 trajectory、AgentRunner、replay
和指标接口，不把 `MiniRetailEnv` 的动态 `test` split 直接当作正式 holdout。环境必须
暴露最终状态、政策检查、工具观测和资源字段；正确拒绝由任务决策真值验证，非法调用
与政策违规分别分类。

### 3.3 命令面

- `build`：读取 bundle 和 qualification/train/dev 来源，执行 schema、重放、去重和
  覆盖检查；明确拒绝 holdout 输入。
- `evaluate`：在 qualification 或已批准 dev manifest 上运行 base/oracle/fake
  candidate；固定任务 manifest、policy、parser、预算和 seed。
- `release`：读取 base/candidate evidence，产生版本化 `GO/NO-GO` 和原因；只有
  证据完整且门禁全部满足才允许 GO。
- `serve`：只加载 GO evidence 指向的候选；NO-GO 自动回退冻结 base，并能演示
  允许、拒绝和恢复三条流程。

R1 qualification 允许完整逐任务轨迹用于测试；正式 holdout 的完整轨迹只进入 sealed
 evidence，开发可见报告只保留聚合指标、失败类别计数、资源摘要、manifest/hash 和
 release 决策。

## 4. Holdout 冻结规则

正式 holdout 在 R2 冻结，R1 只实现和测试规则，不创建正式答案集。

1. 先生成不带 split 的任务池，再以 `family_id` 为最小分组单位划分，禁止同一任务族
   的改写、参数变体或派生轨迹跨 train/dev/holdout。
2. 每条任务在划分前获得不含答案的 opaque `task_id` 和 canonical content hash；
   选择算法、配额、bundle/policy/evaluator 版本写入冻结 receipt。
3. 公共 receipt 只含版本、数量、类别配额、任务/族指纹和文件哈希；holdout 原始
   请求、初始状态、期望状态、答案和失败样例存放于 Git 外的 sealed artifact。
4. `build`、训练数据导出、dev 分析和 prompt/parser/checkpoint 选择路径不得读取
   sealed holdout。release evaluator 必须显式提供匹配 receipt/hash，篡改即失败。
5. 每个 holdout 版本只做一次锁定的 base/candidate 配对发布门禁。若基于任何
   holdout 信号修改候选，必须新建版本化 bundle 和全新 holdout；不得把旧失败样例
   回灌任何训练、开发或调参输入。
6. BFCL 固定 200 条及其失败样例保持独立只读，仅能作为窄口径外部回归；RetailOps
   manifest、任务生成器和 release policy 不得引用其任务或答案。

## 5. 评测指标与发布门禁

### 5.1 必报指标

主指标为最终状态任务成功率、最终状态正确率、关键政策违规数、非法工具调用率和
参数错误率。工程指标为 p50/p95 延迟、平均工具调用次数、执行通过率、轨迹可重放率、
证据完整率以及可用时的 token/cost 字段。失败类别至少包含 parser/格式、工具选择、
参数 schema、政策违规、恢复失败、步数上限和环境错误。

### 5.2 默认 release policy

候选相对同一 base 必须同时满足：

1. 正式冻结 holdout 最终状态成功率绝对提升至少 5 个百分点；
2. 关键政策违规不增加；
3. 非法工具调用为零；
4. p95 延迟不超过 base 的 1.25 倍；
5. manifest、逐任务 sealed evidence、运行环境和资源字段完整；
6. R3 若要把提升写入简历，必须完成一次独立重建且保持正向结果。

任何条件失败均为 `NO-GO`，服务回退到冻结 base；不得根据 holdout 结果临时降低门槛。
R1 用 qualification fixture 验证 Oracle 能 GO、故障注入 candidate 能 NO-GO，正式
holdout 数字留到 R2/R3。

## 6. 影响文件与非目标

批准规格后，R1 实现预计触及：

- `domains/retail_ops/v1/` bundle 配置；
- `src/veritool_rl` 的 domain/env、trajectory verifier、evaluator、release、service
  和 CLI 适配；
- `configs/retail_ops_v1_*.yaml`、`pyproject.toml`、`.gitignore`；
- `tests/test_retail_ops_contract.py`、`test_retail_ops_holdout.py`、
  `test_release_policy.py`、`test_service.py` 及现有相关回归测试；
- R1 设计 ADR、阶段日志和 progress 记录。

不在本设计内修改 BFCL evaluator/manifest、启动远程 GPU、下载 Qwen3-4B、接入商业
API、生成正式 R2 数据或重命名 `veritool_rl`。

## 7. 验收标准

- bundle、工具、政策和 qualification manifest 能通过严格 schema 校验并产生稳定哈希。
- Oracle 在 12 条 qualification 任务上 100% 成功；六类任务的允许、正确拒绝、越权、
  重复和恢复路径均有正反测试。
- 同一输入重复运行的任务集合、门禁和脱敏报告一致；运行目录不可覆盖既有正式产物。
- holdout 输入误用、任务族交叉、manifest 篡改、答案字段进入公开报告和 BFCL 引用均有
  失败测试。
- base、oracle、fake candidate 走同一 evaluate/release 流程，分别产生可解释的
  结果；NO-GO 服务回退 base。
- 质量门保持通过：`.venv/bin/pytest -q`、`.venv/bin/ruff check .`、`.venv/bin/mypy`
  和 `git diff --check`。

## 8. 决策后果与停止条件

方案 A 优先保证 R1 在 1–2 周内形成可演示闭环，代价是工具面和任务分布较窄。若 R1
qualification 显示政策 verifier 无法稳定区分正确拒绝与违规调用、sealed evidence
边界无法自动验证，或 6 类任务无法在 CPU 上重放，则停止进入 R2，记录为阻塞并重新
评估是否需要新 ADR；不得通过放宽 holdout 或 release 门禁继续推进。
