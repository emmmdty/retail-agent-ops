# 审查修复交接文档（第二轮）

**生成时间**: 2026-08-28
**当前 commit**: `829bf95` (fix: P1-14 perturb_schema fallback/P1-7 评测超时/P1-9 SFT task_id 重叠检查)
**工作区状态**: 5 个文件未提交（含 1 个代码 bug + 4 个文档变更 + 2 个工作文档）

---

## 一、本窗口已完成的工作

### 已完成且正确的文档修复（4 个文件）

| 编号 | 问题 | 文件 | 修复内容 |
|---|---|---|---|
| P1-1 | README.en.md 目录树缺 v3/v4/flight_ops | README.en.md | 补充 `flight_ops/`、`domains/retail_ops/{v1,v2,v3,v4}/`、`domains/flight_ops/v1/` |
| P1-2 | CLI release/serve 参数未在 PRODUCT_BRIEF 说明 | docs/PRODUCT_BRIEF.md | 新增「CLI 关键参数」表 + release/serve 行为说明 |
| P1-3 | v1 政策规则 Python 硬编码 | docs/PRODUCT_BRIEF.md | 新增「已知限制」节，标注 v1 规则硬编码在 `V1_BUILTIN_RULES` |
| P1-4 | 幂等键只在 v2+ 下生效 | docs/PRODUCT_BRIEF.md | 同上节，标注 v1 无 `idempotency_key`、去重依赖 `refund_status` |
| P1-8 | Guardrail 默认 None | docs/PRODUCT_BRIEF.md | 同上节，标注 `guardrail` 参数默认 `None`、正式评测不传入 |
| P1-11 | 哈希切分不分难度 | docs/PRODUCT_BRIEF.md | 同上节，标注 train/dev/holdout 按 sha256 切分、不按 margin 分层 |

### 未完成：P1-6 Parser 修复（引入回归）

**状态**: 代码已写入但**有 3 条测试失败**，不可提交。

**实现的策略**: 方案 C — 非 greedy 首选 + greedy fallback。
- 新增 `_extract_payload()` 辅助函数（支持 greedy/non-greedy 两种模式）
- 新增 `_parse_json_payload()` 辅助函数（JSON + Pydantic 校验）
- `parse_qwen_response` 主函数：先非 greedy → 失败后 greedy fallback

**回归根因**：

Qwen 模型的 ChatML 模板会在工具调用后追加 `</im_end>` 作为结束标记。
这是**正常的模型输出格式**，不是"混合内容"。

旧代码的 `outside` 检查先用 `_TOOL_CALL_PATTERN.sub("", raw_text)` 删除所有
`<tool_call>...</tool_call>` 块，再删除所有 `</im_end>`，然后检查剩余内容。如果只有 `</im_end>`
残留，`outside` 为空 → 通过。

新代码第 52 行也做了 `.replace("</tool_call>", "")` 但**没有删除 `</im_end>`**，
导致 `</im_end>` 被视为 outside 内容 → `mixed_tool_call_content`。

**修复方向**：第 52 行的 `.replace("</tool_call>", "")` 需要同时删除 `</im_end>` 和
`<im_start>` 等 ChatML 模板 token。或者直接恢复旧代码的删除顺序：
先 `.sub("", raw_text)` 删所有 `<tool_call>...</tool_call>`，再 `.replace("</im_end>", "")`
删所有结束标记。

**3 条失败测试**：
- `test_agent_runner.py::test_qwen_parser_accepts_one_hermes_tool_call`
  - 输入：`<tool_call>\n{...}\n</tool_call></im_end>`
  - 期望：`tool_call` 非 None
  - 实际：`parse_error="mixed_tool_call_content"`
- `test_agent_runner.py::test_qwen_parser_rejects_text_alongside_a_tool_call`
  - 「后置文本带结束符」用例：`<tool_call>...</tool_call>好的</im_end>`
  - 期望：`parse_error="mixed_tool_call_content"`（正确，有真实文本"好的"）
  - **此条实际也通过**——因为它确实有非模板内容
- `test_qwen_policy.py::test_qwen_policy_passes_tools_and_records_usage`
  - FakeBackend 返回 `<tool_call>...</tool_call></im_end>`
  - 期望：`tool_call` 非 None
  - 实际：`parse_error="mixed_tool_call_content"`

**修复后的验证命令**：
```bash
.venv/bin/pytest tests/test_agent_runner.py::test_qwen_parser_accepts_one_hermes_tool_call tests/test_agent_runner.py::test_qwen_parser_rejects_text_alongside_a_tool_call tests/test_qwen_policy.py::test_qwen_policy_passes_tools_and_records_usage -v
```

---

## 二、工作区未提交的文件

```
 M README.en.md                         |    4 +-  (P1-1: 目录树)
 M docs/PRODUCT_BRIEF.md                |   21 +   (P1-2/P1-3/P1-4/P1-8/P1-11)
 M src/veritool_rl/core/agent/parser.py |   69 +-  (P1-6: 有回归，需修复)
 M findings.md                          | 2199 +-  (工作文档)
 M task_plan.md                         |   10 +   (工作文档)
```

**不能提交**直到 P1-6 的 3 条测试全部通过。

---

## 三、尚未修复的 P1 问题

| 编号 | 问题 | 修复方式 | 是否需要用户决策 |
|---|---|---|---|
| P1-5 | R5 跨模型参考未做 | 已在 EXECUTION_PLAN 记录 | 否 |
| P1-10 | 分布偏移无自动检测 | 需新增工具 | 否 |
| P1-12 | v1/v2 无 Oracle 回放回归测试 | 需新增测试 | 否 |
| P1-15 | flight_ops 候选是 SFT 还是 teacher 未写明 | 文档标注 | **是** |
| P1-16 | flight_ops OOD 0.9833 来源不明 | 需确认数据 | **是** |

---

## 四、下一步操作清单

### 必须先做（阻塞提交）

1. **修复 P1-6 parser 回归**：在 `parser.py:52` 的 `outside` 计算中，
   `.replace("</tool_call>", "")` 之后追加 `.replace("</im_end>", "")`
   （或等价地删除所有 ChatML 模板 token）。然后重跑 3 条失败测试。

2. **运行完整质量门**：
```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy
env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check
git diff --check
.venv/bin/python scripts/ci/audit_public_release.py
```

3. **Commit 所有变更**（P1-1/P1-2/P1-3/P1-4/P1-6/P1-8/P1-11）。

### 之后可做

4. 多轮独立验收（步骤 5）。
5. P1-15/P1-16 需用户确认后再修复。

---

## 五、关键文件路径

| 文件 | 用途 |
|---|---|
| `src/veritool_rl/core/agent/parser.py` | P1-6 修复目标（有回归） |
| `tests/test_agent_runner.py:9-19` | 失败测试 1（accepts one hermes tool call） |
| `tests/test_agent_runner.py:49-70` | 失败测试 2（rejects text alongside tool call） |
| `tests/test_qwen_policy.py:14-53` | 失败测试 3（policy passes tools） |
| `docs/PRODUCT_BRIEF.md` | P1-2/P1-3/P1-4/P1-8/P1-11 已修改 |
| `README.en.md` | P1-1 已修改 |
| `reviews/HANDOFF.md` | 本文档 |

---

## 六、注意事项

1. **不要修改 `docs/PROJECT_LOG.md`**（历史记录不可改写）
2. **不要降低任何发布门禁阈值**
3. **不要自动 push**，只本地 commit
4. **P1-15/P1-16 需要用户确认**后再修复
5. Python 使用 `uv`，不用 pip
6. 本地 WSL 只跑 CPU，不跑 GPU
