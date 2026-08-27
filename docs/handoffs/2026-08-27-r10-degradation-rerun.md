# 交接：R10 工具数退化曲线重跑（小样本先行）

**日期**：2026-08-27　**前置 commit**：见本文件所在提交　**授权**：用户已批准重跑（GPU + teacher API）

---

## 0. 一句话背景

2026-08-24 那轮退化曲线**测的不是工具数**：`tool_count` 是空转参数，五个断点产出的任务
逐条哈希相同，评测又每次加载整份 15 工具 bundle。五个读数完全一样不是"曲线平坦"，
是自变量从未变化。同期还发现 v3 评测集自身不自洽（Oracle 回放 110/120，随后被两次提交
改成 90/120，其中一次让任务数据能关掉政策守卫）。

**这些都已修好**（LOG-20260827-01）。本轮任务是在修好的装置上重新取得读数。

> **为什么必须先小样本**：上一轮的教训不是"跑得不够久"，是"跑了很久但测的东西是空的"。
> 因此本轮的顺序是：CPU 自检 → 小样本冒烟（证明装置对） → 大样本（出读数）。
> 每一步都有明确的通过条件，不通过就停下修，**不要靠加长运行时间来解决问题**。

---

## 1. 先读这些（按顺序，10 分钟）

| 文件 | 看什么 |
|---|---|
| `docs/PROJECT_LOG.md` 的 `LOG-20260827-01` | 上一轮为什么失效、修了什么、代价是什么 |
| `src/veritool_rl/retail_ops/evaluate/toolcount_eval.py` | 自检门与指标的定义（**先读 docstring**） |
| `src/veritool_rl/retail_ops/domain/v3_tasks.py` 模块 docstring | 断点语义、场景为什么随断点变化 |
| `scripts/run_v3_degradation.py` 模块 docstring | 阶段划分与续跑语义 |
| 本文件 §5 | 出问题时怎么定位 |

---

## 2. 实验设计（照抄进报告，不要改）

**自变量**：呈现给模型的工具数 N ∈ {3, 6, 9, 12, 15}（v3 bundle 的前 N 个）。
环境按 `RetailOpsEnv(task, bundle, allowed_tools=...)` 构造；未呈现的工具被调用时按
`unknown_tool` 拒绝。

**任务集随断点变化**：所需工具没被呈现的场景在该断点上无解，因此被排除。

| N | 场景数 | full: train / dev | smoke: train / dev |
|---|---|---|---|
| 3 | 6 | 240 / 60 | 18 / 12 |
| 6 | 11 | 440 / 110 | 33 / 22 |
| 9 | 12 | 480 / 120 | 36 / 24 |
| 12 | 12 | 480 / 120 | 36 / 24 |
| 15 | 12 | 480 / 120 | 36 / 24 |

**因此总体 `task_success` 跨断点不可比**。曲线只能读所有断点共有的 6 类
（`common_scenarios()`，恰好是 v1 的 6 类，所以 {3} 端点仍可复用 `sft-008` 的口径）。
每次运行的 `manifest.json` 里有 `curve_readable_scenarios` 字段，照它读。

**小样本与大样本的分布关系**（由 `tests/test_retail_ops_toolcount_eval.py` 强制）：

- **类型分布严格一致**：每个场景抽同样条数，而全量本身每场景等量 → 场景占比逐字相等；
- **难度轴两端必到**：按 `metadata["margin"]` 的不同取值等距抽样，`per_scenario ≥ 2`
  时最易与最难两档一定在样本里；
- **小样本是大样本的真子集**；抽满时逐条等于全量；
- **不保证难度直方图成比例**——做不到（`refund_denied_window` 全量是 1×2/2×4/3×2/5×1/7×1，
  抽 2 条时任何方案都无法成比例）。每次运行把实际直方图写进 `manifest.json` 的
  `dev_distribution` / `train_distribution`，读报告时自己核对，**不要假装它等于全量**。

**主指标**（`toolcount_eval.py`）：

| 指标 | 定义 | 为什么这么定义 |
|---|---|---|
| `tool_selection_accuracy` | 逐位置命中数 / max(len(gold), len(actual)) | 旧实现是"gold 工具名出现在轨迹任意位置就算对"，把 15 个工具全调一遍能拿满分 |
| `distractor_call_rate` | 调用了"呈现了但这条任务用不到"的工具的占比 | **这才是本实验真正想量的东西**：工具变多时模型是否更容易伸错手 |
| `unknown_tool_call_count` | 调用了没呈现的工具 | 断点约束是否被模型突破 |
| `infrastructure_error_count` | 后端异常的 episode 数 | 旧实现把 CUDA OOM 记成 `success=False`，环境故障看起来像模型退化 |

---

## 3. 执行步骤

### 3.0 环境（gpu-5090）

```bash
ssh gpu-5090
cd /mnt/aidata/tongjiakai/retail-agent-ops
git log --oneline -1                     # 应等于本交接所在 commit
nvidia-smi                                # 确认目标卡空闲显存 ≥ 8GB（多人共用）
df -h /mnt/aidata                         # 确认余量
set -a && source .env && set +a           # teacher API 凭据
```

数据一律落 `/mnt/aidata`；远端 `/tmp` 会被重启清空。产物目录：
`reports/retail_ops/v1/r10-rerun/{smoke,full}/toolcount-N/`（被 `.gitignore` 覆盖，不进 Git）。

### 3.1 CPU 自检（0 成本，**先做**）

```bash
.venv/bin/pytest tests/test_retail_ops_toolcount_eval.py tests/test_retail_ops_v3_tasks.py -q
.venv/bin/python scripts/run_v3_degradation.py --profile smoke --stage preflight
.venv/bin/python scripts/run_v3_degradation.py --profile full  --stage preflight
```

**通过条件**：测试全绿；两条 preflight 都对 5 个断点打印
`preflight OK — 呈现 N 工具，…，Oracle 全解且零违规`。

任一条不过 → **停**，去 §5 定位。这一步失败时**一分钱 GPU/API 都不该花**。

### 3.2 小样本冒烟（约 30–45 分钟，teacher API 约 ¥0.5）

```bash
.venv/bin/python scripts/run_v3_degradation.py --profile smoke 2>&1 | tee smoke.log
```

分阶段跑（想把 API 花费和 GPU 分开时）：

```bash
.venv/bin/python scripts/run_v3_degradation.py --profile smoke --stage data   # 只到 SFT 导出
.venv/bin/python scripts/run_v3_degradation.py --profile smoke                # 续跑到评测
```

**冒烟门禁**（脚本自动判定，退出码 4 表示未通过）。这些**全部是装置不变量，与模型好坏无关**：

| 门 | 阈值 | 不过意味着什么 |
|---|---|---|
| teacher 接受率 | ≥ 0.80 | 教师采集不稳定，训练素材会有系统性缺口 |
| `infrastructure_error_count` | = 0 | 后端异常，读数不完整 |
| `tools_presented` == 断点声明 | 逐字相等 | **自变量没生效**——上一轮就死在这 |
| 发出过合法工具调用的 episode 占比 | ≥ 0.80 | 通常是 prompt/parser 坏了，不是模型弱 |

**故意不设的门**：`task_success`、`tool_selection_accuracy`、`distractor_call_rate`
不设阈值。冒烟样本量太小（每场景 2 条），给它们设阈值等于用噪声做判定。
冒烟只回答"装置能不能产出可归因的读数"，不回答"模型好不好"。

看到 `冒烟门禁全部通过：装置可信，可以跑 --profile full。` 才进下一步。

### 3.3 大样本（约 4–6 小时）

```bash
nohup .venv/bin/python scripts/run_v3_degradation.py --profile full > full.log 2>&1 &
tail -f full.log
```

断点级续跑：某个断点跑完会写 `done.json`，重跑时自动跳过；要重做某断点就删掉它的
`done.json`。teacher 采集按任务续跑（已有证据文件的任务不会重复计费）。

### 3.4 收口

1. 把 `reports/retail_ops/v1/r10-rerun/full/curve.json` 同步回本地并核对哈希；
2. 读数写进 `findings.md` / `progress.md`；
3. 结论按「只在该工具面规模、该 teacher、该基座上成立」陈述；
4. 追加 `docs/PROJECT_LOG.md` 条目，并更新 `docs/EXECUTION_PLAN.md` R10 节的更正记录
   （**不要改写 LOG-20260827-01**，它是 append-only 档案）；
5. 同步 `docs/RESUME_EVIDENCE.md` / `docs/INTERVIEW_PREP.md` 里目前写着"读数作废"的段落。

---

## 4. 边界（不要越过）

- **不消耗封存 holdout 观测**。本轮不是发布判定。
- **发布候选仍是 `sft-008`**，它的读数全部来自 v1/v2 口径，与 v3 无关。
- **不改 v1/v2 冻结契约**：`GATE_IDS` v1.0、`SealedEvaluationReport` 字段集、
  `PAIRING_FIELDS`、`formal_tasks.assert_exact_quotas` 的 40/10/20。
- **不改 `runner.SYSTEM_PROMPT` / parser / prompt 模板**——改了会让已有证据不可比。
- **不为了让数字好看而改任务或关守卫**。上一轮就是这么坏掉的：
  `skip_reads_gate` 关掉政策门、`refund_then_cancel` 被改成一次 cancel。
  如果读数不好看，那就是读数不好看。

---

## 5. 出问题时怎么定位

**总原则：先问"装置对不对"，再问"模型行不行"。** 下面每一条都能在 CPU 上几秒内验证。

### 5.1 preflight 报「自变量没有生效」

```
环境呈现的工具与断点声明不符：期望 [...] 实际 [...]
```

环境工厂没传 `allowed_tools`。检查 `scripts/run_v3_degradation.py::env_factory_for`——
它必须是 `RetailOpsEnv(task, bundle, allowed_tools=allowed)`。这是上一轮的原始缺陷。

### 5.2 preflight 报「gold 调用序列在环境里走不通」

评测集不自洽，此时任何模型读数都无法归因。逐条定位：

```bash
.venv/bin/python - <<'PY'
import sys; sys.path.insert(0, "src")
from pathlib import Path
from veritool_rl.core.agent.policy import OraclePolicy
from veritool_rl.core.agent.runner import run_episode
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
from veritool_rl.retail_ops.domain.v3_tasks import _TOOL_SUBSETS, build_toolcount_task_set

N = 15
bundle = load_bundle(Path("domains/retail_ops/v3"))
factory = lambda t: RetailOpsEnv(t, bundle, allowed_tools=_TOOL_SUBSETS[N])
for rec in build_toolcount_task_set("dbg", seed=0, tool_count=N).dev:
    tr = run_episode(rec.task, factory, OraclePolicy(rec.task), seed=0)
    if not tr.success or tr.violations:
        print(rec.task.scenario.value, rec.task.task_id, tr.termination.value, tr.violations)
        for s in tr.steps:
            print("   ", s.tool_call, "->", s.observation)
        break
PY
```

常见三种成因，各自的判别与修法：

| 症状 | 成因 | 修哪里 |
|---|---|---|
| `termination=policy_violation`，违规码 `*_requires_lookup` | gold 序列里少了先 `get_order` 的一步 | `v3_tasks.py::_scenario_task` 的该场景 `expected_calls` |
| `termination=final_response`，无违规 | `required_reads` 里的订单没被读到，或 `target_state` 要求的状态没被任何 gold 调用改到 | `_make_task` 的 `target_state` 分支与 `required_reads` |
| `termination=step_limit` | gold 调用数 ≥ `max_steps`，没给收尾答复留位置 | `_make_task` 的 `multi_call_scenarios` |

**不要**通过删掉这个场景、简化任务或加 metadata 开关来"修复"——上一轮三种都试过，
结果是把一个坏场景变成三个。

### 5.3 teacher 接受率低

先看 `teacher.json` 的 `errors`（前 20 条原样保留）：

- `TeacherClientError` + 401/403 → 凭据没 source，重跑 `set -a && source .env && set +a`；
- 大量 `ReplayMismatch` → 教师给的轨迹重放不出来，通常是环境或 gold 契约刚被改过，
  回 §5.2 先跑 Oracle 自检；
- 某一类场景集中失败 → 看该场景的 `user_request` 措辞。**已知经验**（R9）：
  DENY 类必须写「评估/判断」而不是「检查/执行」，否则教师会直接去执行
  （`cancel_denied_recent` 曾因此从 8% 升到 100%）。

采集会按任务续跑，改完措辞只需删掉对应场景的证据文件再跑。

### 5.4 评测出现 `infrastructure_error_count > 0`

看 `eval-*/episodes.json` 的 `infrastructure_error` 字段（记了异常类型和消息）：

- `CUDA out of memory` → 换空闲卡或降 `max_new_tokens`；**不要**把它当模型失败读；
- `triton` 相关 → 本机没有 C 编译器；确认 `TORCH_DISABLE_NATIVE_JIT=1`，
  且若引入了第二个 Python 深度学习环境，必须先隔离其 `TRITON_CACHE_DIR`
  （否则会覆盖项目自己的 triton 缓存，报错信息完全不指向真正原因，LOG-20260816-02）。

### 5.5 报「必须在仓库根运行」或「policy.model_name 必须是项目相对路径」

`QwenPolicy.from_config` 对 `model_name` 与 `adapter_path` 都跑
`validate_project_relative_path`，**绝对路径会被直接拒绝**；而相对路径按进程 cwd 解析。
因此 runner 在起步时就断言 `cwd == 仓库根`（`require_repo_cwd`）。
`cd /mnt/aidata/tongjiakai/retail-agent-ops` 之后再跑即可。

这一条是 2026-08-27 从 gpu-5090 上一次手工运行残留的未提交改动里捞回来的——
远端把 `str(MODELS_ROOT / ...)` 改成了 `"models/Qwen3-4B-pinned"`，正是撞了这道校验。
新 runner 已经统一用相对路径，不需要再手工改。

### 5.6 读数看起来"太平坦"

**这正是上一轮的形态，务必按下面顺序排除装置问题再下结论**：

1. 打开各断点的 `eval-candidate/metrics.json`，比对 `tools_presented` ——
   五个断点必须**不同**，长度分别是 3/6/9/12/15；
2. 比对各断点 `manifest.json` 的 `dev_task_ids` —— 断点之间**必须不同**
   （场景集合不同，任务数也不同）；
3. 如果 `distractor_call_rate` 在所有断点上都是 0，说明模型从不碰多余工具，
   那"平坦"是真读数——但要同时报告 `tool_selection_accuracy` 与逐场景成功率，
   不要只报一个总分；
4. 只有 1、2 都确认过之后，"平坦"才可以写进结论。

### 5.7 想确认小样本没抽偏

```bash
.venv/bin/python -c "
import json
s=json.load(open('reports/retail_ops/v1/r10-rerun/smoke/toolcount-15/manifest.json'))
f=json.load(open('reports/retail_ops/v1/r10-rerun/full/toolcount-15/manifest.json'))
for k in s['dev_distribution']:
    print(f'{k:26s} smoke={s[\"dev_distribution\"][k]}  full={f[\"dev_distribution\"][k]}')
"
```

每个场景的 smoke 条数应相等（=2），且 margin 的最小/最大值与 full 一致。

---

## 6. 本轮之前已经做完的事（不用重做）

- `tool_count` 现在真的限制 `env.list_tools()`；`RetailOpsEnv` 的 `allowed_tools`
  默认 `None`，v1/v2 已产出证据逐字节不变；
- `skip_reads_gate` 已撤除，并有回归测试断言任务 metadata 关不掉政策门；
- `refund_then_cancel` 按 v4 已验证的双订单形态重建；
- Oracle 在 5 个断点的 smoke 与 full 任务集上均全解、零违规；
- 分层抽样、指标、自检门都在 `src/` 里，受 mypy 与 41 条测试覆盖；
- 全量门禁基线：作者环境 1352 passed，干净 clone 1306 passed / 46 skipped / 0 failed。
