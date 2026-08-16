# 故障注入矩阵

`SPEC.md` §9 与 `docs/EXECUTION_PLAN.md` R5 要求覆盖五类故障：**外部 API 超时、
幂等、策略冲突、资源限制、回滚故障**。这份文件把每一类映射到具体的自动化测试。

**这张表由测试锁定**：`tests/test_fault_matrix.py::test_every_fault_class_names_a_real_test`
会解析本文件，逐个断言被引用的测试真实存在且会被收集。文档写了一个不存在的测试名，
测试会红——这是为了防止"矩阵越写越漂亮、实际覆盖不动"。

口径说明：本表列的是**自动化测试**。真实故障演练（拔网线、打满显存、杀进程）没有做，
不得表述为"经过混沌工程验证"。

---

## 1. 外部 API 超时与重试

Teacher 采集是本项目唯一的外部 API 依赖（DeepSeek，OpenAI 兼容）。

| 故障 | 期望行为 | 测试 |
|---|---|---|
| 请求挂起 | SDK client 显式设置 60 s 超时与 2 次 SDK 重试上限；不得沿用 SDK 默认的 600 s | `tests/test_teacher_client.py::test_production_factory_bounds_the_request_timeout_and_retries` |
| 超时/连接失败/429/5xx | 归类为 `retryable=True`，由采集层决定是否重试 | `tests/test_teacher_client.py::test_transport_errors_are_marked_retryable` |
| 认证失败与其他 4xx | 归类为 `retryable=False`，**立即停止**而不是反复撞墙 | `tests/test_teacher_client.py::test_non_transport_errors_are_not_retryable` |
| 错误信息里带着 API key | 日志与异常里的 key / Authorization / Bearer 全部脱敏 | `tests/test_teacher_client.py::test_sdk_errors_redact_key_authorization_and_bearer_values` |
| 响应结构非法 | 硬失败而不是产出半截轨迹 | `tests/test_teacher_client.py::test_malformed_tool_arguments_are_rejected` |

**2026-08-16 修掉的真缺陷**：`_classify_retryable` 一直把超时当作可重试，
但 `from_route` 构造 SDK client 时**从未设置超时**。240 条轨迹是 519 次请求，
一次挂起就是 10 分钟静默停摆，而采集脚本看起来像在正常工作。
两层重试的乘积必须可预测，所以 SDK 层上限（`TEACHER_MAX_RETRIES`）与采集层上限
（`TeacherCollectionConfig`）是两个分开的旋钮。

## 2. 幂等

自 bundle **v2** 起，`refund_order` 有必填 `idempotency_key`，环境按 key 去重
（v1 逐字节冻结不动，见 `docs/DOMAIN_BUNDLE_V2.md`）。

| 故障 | 期望行为 | 测试 |
|---|---|---|
| 同一个 key 重试 | 返回同一个结果，**只退款一次** | `tests/test_retail_ops_v2_bundle.py::test_same_key_retry_returns_the_same_result_and_refunds_once` |
| 瞬时失败后用同一个 key 重试 | 仍然只退款一次 | `tests/test_retail_ops_v2_bundle.py::test_same_key_retry_after_a_transient_failure_still_refunds_once` |
| 换一个新 key 打同一个订单 | 判为 `duplicate_refund` 违规，不是"再退一次" | `tests/test_retail_ops_v2_bundle.py::test_a_new_key_on_an_already_refunded_order_is_a_duplicate_refund` |
| 缺 `idempotency_key` | schema 层拒绝调用 | `tests/test_retail_ops_v2_bundle.py::test_v2_refund_requires_an_idempotency_key` |

## 3. 策略冲突

| 故障 | 期望行为 | 测试 |
|---|---|---|
| 多条规则同时成立 | 判定取**声明顺序**里的第一条；顺序本身是契约 | `tests/test_retail_ops_policy_rules.py::test_rule_order_is_the_contract_not_an_accident` |
| 规则引用不存在的事实 | **加载期**失败，不是运行期静默放行 | `tests/test_retail_ops_v2_bundle.py::test_a_rule_referencing_an_unknown_fact_fails_at_load_time` |
| 未知操作符 | 解析期拒绝 | `tests/test_retail_ops_policy_rules.py::test_unknown_operator_is_rejected_at_parse_time` |
| 只改 YAML 阈值 | 全链路判定改变，**零 Python 改动** | `tests/test_retail_ops_v2_bundle.py::test_changing_only_the_yaml_threshold_changes_the_verdict` |
| v2 规则与 v1 硬编码判定不一致 | v2 必须逐条复现 v1 的判定 | `tests/test_retail_ops_v2_bundle.py::test_v2_reproduces_v1_policy_decisions` |

## 4. 资源限制

| 故障 | 期望行为 | 测试 |
|---|---|---|
| 并发超过上限 | 返回 503 并计数，**不排队** | `tests/test_formal_service.py::test_concurrent_episodes_are_capped_instead_of_queueing` |
| 请求体超限 | 在**到达模型之前**被拒 | `tests/test_formal_service.py::test_oversized_request_body_is_rejected` |
| 生成超时 | 结构化错误而不是挂死 | `tests/test_retail_ops_service_layer.py::test_generation_timeout_returns_a_structured_error` |
| 步数预算耗尽 | 终止原因为 `STEP_LIMIT`，逐步都有观测，不抛异常 | `tests/test_agent_runner.py::test_format_errors_consume_steps_without_crashing_episode` |
| 瞬时故障注入次数超过重试上限 | 由 `policies.yaml` 的 `max_transient_retries` 截断 | `tests/test_retail_ops_v2_bundle.py::test_max_transient_retries_actually_caps_the_injected_failures` |
| 并发拒绝 / 超时 / 未授权 | 各自有独立计数器，可在 `/metrics` 观测 | `tests/test_retail_ops_service_layer.py::test_metrics_counts_the_concurrency_rejection` |

## 5. 回滚故障

发布判定为 `NO-GO` 时，服务必须加载**纯基座**。这一类的失败是"回滚没生效却报告成功"。

| 故障 | 期望行为 | 测试 |
|---|---|---|
| NO-GO 判定 | 绝不加载 adapter | `tests/test_formal_service.py::test_no_go_release_must_not_load_the_adapter` |
| 后端**声称**回滚但实际加载了 adapter | 服务**拒绝启动**，不是打个日志继续 | `tests/test_formal_service.py::test_backend_that_ignores_the_rollback_is_rejected` |
| GO 判定 | 加载被 release 报告固定的那一个 adapter | `tests/test_formal_service.py::test_go_release_loads_the_pinned_adapter` |
| 运维想核对当前到底加载了什么 | `/health` 暴露判定与回滚路径 | `tests/test_formal_service.py::test_health_exposes_the_decision_and_rollback_path` |
| bundle 与 release 报告不一致 | 启动期拒绝 | `tests/test_formal_service.py::test_formal_service_rejects_a_bundle_that_differs_from_the_release` |

## 6. 额外覆盖：注入与工具滥用

不在 R5 的五类清单里，但属于同一类"外部输入不可信"的防御，一并列出。

| 故障 | 期望行为 | 测试 |
|---|---|---|
| 工具返回的内容里藏指令 | guardrail 消毒后才进模型上下文 | `tests/test_retail_ops_guardrail.py::test_with_the_guardrail_injected_content_never_reaches_the_model` |
| 调用 allowlist 之外的工具 | 调用前置校验拦截，产生结构化观测 | `tests/test_retail_ops_guardrail.py::test_tool_outside_the_allowlist_is_blocked` |
| 未查证就退款 | 会话作用域校验拦截，**不触碰环境** | `tests/test_retail_ops_guardrail.py::test_refund_on_an_unconfirmed_order_is_blocked_without_touching_the_env` |
| guardrail 误伤正常流程 | 干净 episode 逐字节不变 | `tests/test_retail_ops_guardrail.py::test_the_guardrail_does_not_change_a_clean_episode` |

## 7. 明确没有做的

| 项 | 原因 |
|---|---|
| 真实混沌演练（断网、OOM、杀进程） | 未做。上表全部是进程内故障注入，不得表述为"混沌工程验证" |
| 长稳与压测 | 未做。服务只做过单次演示与并发上限验证，没有持续负载数据 |
| 多租户隔离 | 不在产品边界内（`SPEC.md` §10） |
| GPU 显存耗尽的恢复 | 未做。单卡单进程，OOM 当前是硬失败 |
