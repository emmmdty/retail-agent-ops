# 演示流程

面向面试与内部复盘。**最快的一条是看视频**：`docs/media/demo.mp4`（70 秒，
终端实录渲染，每一行输出都真跑过；生成方式见 `README.md` 的「演示」一节）。

其余三条路径：**5 分钟口头讲解**（无需终端）、
**纯 CPU 全链路演示**（任何机器可跑）、**真实模型服务演示**（需单卡 GPU）。

数字口径以 [`MODEL_CARD.md`](./MODEL_CARD.md) 与 [`SYSTEM_CARD.md`](./SYSTEM_CARD.md) 为准，
不在演示中临场估算。

---

## 1. 五分钟讲解脚本

**已迁出本文件。** 现行版本是 [`INTERVIEW_PREP.md`](./INTERVIEW_PREP.md) §1。

迁出的理由：这里原本有一份 R3 时期的讲解稿，结论停在"候选 NO-GO、回滚基座"。
此后又发生了三次观测、一个 GO、一次分布外评测和一次独立重建复验。
**同一份讲稿存在两处就一定会漂**，所以本文件只保留演示**流程**，讲稿收敛到一处。

本文件负责的是「怎么跑给人看」：§2 纯 CPU 全链路、§3 真实模型服务、§4 必须一起讲的失败案例。


## 2. 纯 CPU 全链路演示（无需 GPU）

qualification 轨道走**完全相同的代码路径**，只是策略是确定性规则而非真实模型。
用于展示四接口闭环、GO 与 NO-GO 两种结论、以及服务回滚。

```bash
env -u UV_INDEX_URL uv sync --extra dev --frozen
.venv/bin/pytest -q          # 作者环境 1171 passed；干净 clone 1125 passed / 46 skipped

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

**已迁出本文件。** 现行版本是 [`INTERVIEW_PREP.md`](./INTERVIEW_PREP.md) §2（深挖问答，
按系统设计 / 评测方法 / 后训练 / 工程决策 / 失败与边界五类组织）与 §4（常见质疑与回应）。

同 §1 的理由：原先这里的问答里，"holdout 到 2026-08-11 才第一次被观测"
这类表述会随每一次新观测过期，而它无人维护。
