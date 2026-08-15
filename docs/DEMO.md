# 演示流程

面向面试与内部复盘。三条路径：**5 分钟口头讲解**（无需终端）、
**纯 CPU 全链路演示**（任何机器可跑）、**真实模型服务演示**（需单卡 GPU）。

数字口径以 [`MODEL_CARD.md`](./MODEL_CARD.md) 与 [`SYSTEM_CARD.md`](./SYSTEM_CARD.md) 为准，
不在演示中临场估算。

---

## 1. 五分钟讲解脚本

### 0:00–0:40　问题

> 企业要在内网或成本敏感场景部署工具 Agent。真正卡住上线的不是"模型能不能调用工具"，
> 而是**凭什么证据允许它上线**：它会不会在没查订单的情况下直接退款？换了一版模型，
> 是真的变好了还是只是格式变整齐了？出问题怎么回滚？
>
> RetailAgentOps 把这条链路做成流水线：领域定义 → 轨迹数据 → 单卡 QLoRA → 执行式评测
> → 发布门禁 → 服务部署，四个稳定接口 `build / evaluate / release / serve`。

### 0:40–1:40　领域与数据

> 场景是中文零售退款闭环：查订单、允许退款、三类拒绝（超窗/非本人/重复）、
> 瞬时故障后恢复。两个业务工具加一个 schema 干扰工具。
>
> 数据 240/60/120 三分，seed 固定，六类均分。训练轨迹来自 DeepSeek teacher，
> 但**不是拿生成文本直接当数据**——每条都要 replay 重放、核对最终状态、过政策 verifier，
> 全量通过率 238/240。train/dev/holdout 之间做五维指纹交叉断言，
> 指纹刻意不含 split 和 task_id，所以"换个标签重新混进来"这种泄漏也挡得住。

### 1:40–2:40　训练与评测

> 单卡 QLoRA，4-bit NF4，r=16，3 epoch，**134 秒，显存峰值 5.16 GiB**，adapter 23.6 MB。
> 训练前走三级阶梯：smoke 验管线、overfit 验 label/mask（loss 从 1.27 降到 0.017，
> 排除系统性缺陷）、然后才全量。
>
> 评测的主判据是**工具执行结果、最终状态和政策 verifier**，不是 loss，也不是奖励值。
> 这一点后面会有个很具体的例子。

### 2:40–4:00　结果与发布判定（核心）

> 候选在封存的 120 条 holdout 上：**政策违规 16→0，非法调用 41→0，schema 有效率
> 0.78→1.00**。格式和安全类问题被彻底清零。
>
> 但**任务成功率从 0.783 降到 0.750**。发布门禁要求 +5pp，实测 −3.3pp，
> 所以判 **NO-GO，回滚基座**。
>
> 为什么降？候选的失败**100% 是"说完就停"**——`refund_eligible` 这一类 20 条全军覆没。
> 逐条看轨迹会发现它并不是不会：它查完订单、正确算出还在退款期、正确说出该退，
> 然后问了一句"请问您需要我为您办理退款吗？"就停了。这是行为倾向，不是能力缺失。
>
> 我当时判断根因是训练数据的动作分布——240 条里 66.7% 只需要一次工具调用。
> 然后我做了实验去验证它，**结果证伪了我自己**：把关键决策点上的比例从 3:1 拉到 1:1
> （多步样本重复三倍），`refund_eligible` 的通过数变化是**精确的零**。
> 现在的嫌疑转向请求措辞——同样的处理下，祈使句那一类涨了 2 条，而措辞里带"核实/检查"
> 的这一类纹丝不动。但这还只是观察，我没有把它当成结论。
>
> 还有一个细节我觉得最能说明问题：候选的 `verifier_reward` 从 0.56 **涨到** 0.75，
> 而任务成功率是**跌的**；改进那一轮 `train_loss` 还从 0.37 降到 0.22，目标行为依然没动。
> **能优化的代理量全都在改善，唯独真实任务没有。** 这就是为什么主判据必须是最终状态
> 而不是奖励值或 loss——这不是教条，是我在这个项目里撞到三次的实证。

### 4:00–5:00　服务与工程立场

> 服务按 NO-GO 回滚，只加载冻结基座。回滚是**双重执行**的：不给工厂传 adapter，
> 并且还要核对工厂真正返回的后端声明的 adapter 路径——因为工厂是注入缝，
> 实现可能来自别处。`/health` 和每条响应都能看到 `adapter_loaded=false`。
> 并发上限 1，超限返回 503 而不是排队，因为排队会让延迟测量失真，而延迟是门禁项。
>
> 这个项目最终交付的是一个 **NO-GO**。我认为这恰恰是它的价值：
> 能拒绝不合格候选、并且拒绝得有证据、拒绝之后能自动回滚，这才是发布系统。

---

## 2. 纯 CPU 全链路演示（无需 GPU）

qualification 轨道走**完全相同的代码路径**，只是策略是确定性规则而非真实模型。
用于展示四接口闭环、GO 与 NO-GO 两种结论、以及服务回滚。

```bash
env -u UV_INDEX_URL uv sync --extra dev --frozen
.venv/bin/pytest -q          # 期望 698 passed

R=reports/retail_ops/v1/demo
.venv/bin/retail-agent-ops build    --config configs/retail_ops/build/retail_ops_v1_build.yaml \
    --seed 0 --output_dir $R/build
.venv/bin/retail-agent-ops evaluate --config configs/retail_ops/evaluate/retail_ops_v1_qualification_base.yaml \
    --seed 0 --input_dir $R/build --output_dir $R/base
.venv/bin/retail-agent-ops evaluate --config configs/retail_ops/evaluate/retail_ops_v1_qualification_oracle.yaml \
    --seed 0 --input_dir $R/build --output_dir $R/oracle
.venv/bin/retail-agent-ops evaluate --config configs/retail_ops/evaluate/retail_ops_v1_qualification_fault.yaml \
    --seed 0 --input_dir $R/build --output_dir $R/fault
.venv/bin/retail-agent-ops release  --config configs/retail_ops/release/retail_ops_v1_release.yaml \
    --seed 0 --baseline_dir $R/base --candidate_dir $R/oracle   --output_dir $R/release-go
.venv/bin/retail-agent-ops release  --config configs/retail_ops/release/retail_ops_v1_release.yaml \
    --seed 0 --baseline_dir $R/base --candidate_dir $R/fault    --output_dir $R/release-no-go
```

**演示要点**：baseline 8/12、oracle 12/12、fault 0/12；oracle 走 **GO/candidate**、
fault 走 **NO-GO/baseline**。同一份策略文件、同一套门禁算术产出两种相反结论。
重复运行整棵证据树逐文件一致（确定性），HTML 报告可直接在浏览器打开。

启动 qualification 服务（GO 分支，加载 candidate 规则策略）：

```bash
.venv/bin/retail-agent-ops serve --config configs/retail_ops/serve/retail_ops_v1_serve.yaml \
    --release_dir $R/release-go --input_dir $R/build --output_dir $R/service
```

---

## 3. 真实模型服务演示（需单卡 GPU）

前置：已锁定哈希的 Qwen3-4B 权重、私有数据集、两份 sealed 报告与发布报告。
以 2026-08-11 的实跑为例（gpu-5090，物理 GPU 0）。

```bash
# 1) 演示任务集（纯 CPU，12 条确定性 fixture；serve 的 --input_dir 需要它）
.venv/bin/retail-agent-ops build --config configs/retail_ops/build/retail_ops_v1_build.yaml \
    --seed 0 --output_dir reports/retail_ops/v1/r3/serve-demo-build

# 2) 按发布决策启动服务（NO-GO → 只加载冻结基座）
#    API key 只从环境变量读，绝不进配置文件或 Git；缺失时**启动即失败**，
#    不会退化成"没配就放行"。
export RETAIL_AGENT_OPS_API_KEY="$(openssl rand -hex 16)"
TORCH_DISABLE_NATIVE_JIT=1 CUDA_VISIBLE_DEVICES=0 \
.venv/bin/retail-agent-ops serve \
    --config configs/retail_ops/serve/retail_ops_v1_r3_formal_serve.yaml \
    --release_dir reports/retail_ops/v1/r3/formal-release-001 \
    --input_dir  reports/retail_ops/v1/r3/serve-demo-build \
    --output_dir reports/retail_ops/v1/r3/serve-demo-001
```

> 下面 `/v1/*` 的每条请求都要带 `-H "Authorization: Bearer $RETAIL_AGENT_OPS_API_KEY"`。
> `/health` 与 `/metrics` 不需要——两者都不暴露任务内容或凭据。
> 2026-08-11 的实跑记录早于服务层补强（该轮只有预置任务端点、无鉴权），
> 下面的输出摘自那次运行，端点语义已按当前代码更新。

### 3.1 先看部署身份

```bash
curl -s http://127.0.0.1:8000/health
```

```json
{"release_decision":"NO-GO","deployment":"baseline","adapter_loaded":false,
 "failed_gate_ids":["success_delta"],
 "policy_id":"qwen:Qwen/Qwen3-4B@8cd0101f70cac4f1efcebc979faf483558e39297",
 "rollback":"候选未通过发布门禁，服务已回滚到冻结 base，不加载 adapter；失败门禁：success_delta。"}
```

**讲解点**：`policy_id` 没有 adapter 后缀。候选证据里的是
`…+adapter:reports/retail_ops/v1/r3/sft-001#34544fac3ec9`。回滚不是配置声明，是可核对的事实。

`GET /v1/tasks` 返回 12 个任务 ID 与工具 allowlist，**不暴露任务类别**——
类别属于评测真值，不进服务响应。

### 3.2 三条业务流程

```bash
curl -s -X POST http://127.0.0.1:8000/v1/tasks/<task_id>/run
```

| 流程 | 类别 | 实跑轨迹 |
|---|---|---|
| **允许** | `refund_eligible` | `get_order`（`refund_status=none`、`current_day=20`、`refund_deadline=30`）→ `refund_order(reason=wrong_item)` → `refunded` |
| **拒绝** | `refund_denied_ownership` | `get_order` → `error_code=not_found` → **停止，未尝试退款**，`violations=[]` |
| **异常恢复** | `refund_recovery` | `get_order` → `refund_order` 遇 `transient_error` → **重试** → `refunded` |

三条均 `success=true`、`violations=[]`、`deployment=baseline`，响应内含完整工具轨迹。

**讲解点**：拒绝那条要强调——`success=true` 且 `violations=[]`。
**正确拒绝**与**政策违规**是分离语义：模型该拒绝时拒绝了就是成功，
只有真的尝试了被禁止的状态变更才算违规。这个区分是 R1 设计时刻意做的。

### 3.3 自由请求（`POST /v1/chat`）

预置任务端点只能跑 12 条固定 fixture，回答不了"随便说一句话它怎么办"。
`/v1/chat` 接受任意 `user_request`，复用同一 `RetailOpsEnv`、同一 tool allowlist、
同一条 `run_episode`：

```bash
curl -s -X POST http://127.0.0.1:8000/v1/chat \
  -H "Authorization: Bearer $RETAIL_AGENT_OPS_API_KEY" \
  -H 'content-type: application/json' \
  -d '{"user_request":"帮我看看我那笔订单到哪了","context_task_id":"<task_id>"}'
```

`context_task_id` 只提供**订单数据上下文**（可见订单、customer_id、current_day），
不提供任务真值。因此响应里**没有 `success` 字段**，而是 `ground_truth: false`——
自由请求没有真值，报告一个成功率就是把演示包装成能力证明。

### 3.4 并发保护、超时与可观测性

```bash
curl -X POST .../run & sleep 0.3; curl -X POST .../run & wait
```

先到者 200，后到者 **503「服务已达并发上限，请稍后重试」**。并发上限保持 1 而不是排队：
排队会让延迟测量失真，而延迟是发布门禁项。

- 每条请求分配 `trace_id`（也回在 `X-Trace-Id` 头），并输出**一行** JSON 日志：
  trace_id、端点、状态码、部署、工具调用序列、终止原因、耗时、violations。
  日志记的是请求的 **SHA-256 摘要与字符数，不是原文**——足以事后对上一条 trace，
  又不会把用户数据或任务答案写进日志文件。
- 单次 episode 超时返回 **504** 结构化错误（带 trace_id）而不是挂死。生成是同步阻塞
  调用无法中断，因此那次生成会跑到自然结束，**信号量直到那时才释放**：后续请求得到
  503，而不是把第二份工作压到同一张卡上。
- `GET /metrics`（Prometheus 文本，无新依赖）：请求数、episode 数、p50/p95 端到端延迟、
  工具调用与违规累计、按原因分的拒绝数（`unauthorized` / `request_too_large` /
  `concurrency_limit` / `episode_timeout`）、超时数。

```bash
curl -s http://127.0.0.1:8000/metrics | head
```

---

## 4. 必须一起讲的失败案例

演示只挑成功案例是不诚实的，下面三条建议主动讲。

**① 同批次的另一条 `refund_eligible` 失败了。** 并发测试里那条陪衬请求返回
`success=false`、`termination=final_response`。基座也会"说完就停"，只是频率低于候选。
三条成功轨迹不代表能力，holdout 上基座是 94/120。

**② `refund_denied_window` 曾经无解，是真实 API 采集暴露的。** 环境早期只返回
`refund_deadline=19` 这样的裸整数，判定用的 `current_day` 从不暴露给模型——
任何推理式 Agent 都无法判断订单是否超窗，只能试探性调用退款，而试探本身就被记为违规。
506 个 CPU 测试和多轮审查都没发现，因为测试路径全走 Oracle（直接读真值）。
真实 teacher 采集时该类通过率只有 30%，修复后 95%。
**教训**：Oracle 驱动的测试永远发现不了"信息是否足够让模型解出来"这类缺陷。

**③ 我曾经把一个推测当结论，后来被数据推翻。** 基座那一步耗时是候选的两倍，
我推测是共享 GPU 被他人抢占；但 provenance 里的 `wall_time_seconds` 是 287 s vs 544 s
——候选确实更慢，基座那 20 分钟里约 15 分钟是冷启动读 7.6 GB 权重加 13 个文件哈希校验。
**步骤 wall time 不是评测延迟。**

---

## 5. 深挖问答准备

**Q：为什么不直接用商业 API？**
成本与数据边界。这条流水线的目标场景是内网/成本敏感部署，单卡 4-bit 推理峰值显存 2.95 GB。
商业 API 在本项目里的定位是 teacher（240 条采集约 $0.055），不是运行时依赖。

**Q：为什么不上 GRPO / RL？**
因为失败类别还没到需要 RL 的阶段。当前主要失败是"多步执行不完成"，而且它有一个
非常具体的形态：模型正确判定该退款，然后向用户请求确认后停止。数据、模板/parser、
工具 schema、verifier 四层我已排查完，后三层无缺陷。数据侧的第一个假设（动作分布失衡）
已经被我自己的实验证伪——把比例从 3:1 拉到 1:1，该类通过数变化为零。
所以现在是"SFT 路线的第一个假设被推翻"，不是"SFT 已经停滞"，这两者不一样。
只有在 SFT 明确停滞、且能构造出足量执行有效的偏好对时，才考虑偏好优化。
为保留算法叙事而上 RL 是本项目的明确非目标。

**Q：120 条能说明什么？**
CI 宽度约 ±7.5pp，分辨不了小幅差异。所以我不会说"候选显著更差"——
两侧 CI95 大幅重叠。但门禁要的是实测 +5pp，没做到就是 NO-GO，
这是**产品决策阈值**，跟统计显著性是两回事。反过来，`refund_eligible` 20/20 全灭
是结构性的，不能当噪声。

**Q：怎么保证 holdout 没被污染？**
两段式授权（purpose 必须 RELEASE、逻辑路径必须精确匹配）、五维指纹交叉断言、
公开报告是 allowlist 字段集且有子串扫描测试。holdout 到 2026-08-11 才第一次被观测，
此前一次运行被机器重启中断但**零产出**——判据是有没有数字落盘并被读取，不是跑了多久。

**Q：如果候选 GO 了会怎样？**
服务加载 base+adapter，`policy_id` 带 adapter 指纹后缀，`adapter_loaded=true`。
这条路径在 qualification 轨道上有真实演示（oracle → GO/candidate），
formal 轨道上则由测试覆盖。

**Q：这个项目最难的部分？**
不是训练，是**让证据不可伪造**。`report_id` 是全字段自哈希，改任何字段都加载失败；
私有产物逐一 SHA-256；配对比较前逐字段校验同条件。做这些的动机很实际——
如果证据可以手改，那 GO/NO-GO 就只是一句话而不是结论。
