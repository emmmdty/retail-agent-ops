# 交接：GPU 执行阶段——C2 方差验证 → D1 rtc 第四轮 → E2 退化曲线续跑 → D4 一次性 v1.3 判定

**日期**：2026-09-04
**性质**：质量收口第二轮的 **GPU/API 执行阶段**。纯 CPU 部分已在同日完成并提交
（9 个 commit，`3121e7d` 止，见 `docs/EXECUTION_PLAN.md`「质量收口第二轮」与
`findings.md` 2026-09-04 各节）；本轮把剩余四项 GPU 任务按序执行并收口。
**执行者**：新窗口的 coding agent；**允许使用 subagent**（探索、审查、可并行的独立
工作），subagent 的读数与结论必须抽查验证后再采信。
**授权状态**：用户已批准 gpu-5090 使用与本阶段任务方向（2026-09-04）；本文件 §4 的
命令清单即逐条确认的执行依据，**偏离清单（新命令/更长时长/更高费用）必须先停下确认**。

---

## 0. 一句话背景

评测基建的缺口已全部修完（5C+7I，含 FormalReleaseReport 自哈希、OOD 门禁 fail-closed、
评测超时真生效），v1.3 门禁已上线且**阈值（0 / +0.02）已冻结**；剩下的工作是：在 GPU 上
验证训练方差治理（C2）、跑完两个在途实验（D1 rtc、E2 退化曲线）、然后按预注册纪律做
一次性 v1.3 发布判定（D4）。

## 1. 先读这些（按顺序）

1. `AGENTS.md`（不可违反边界 + 固定流程）
2. `docs/EXECUTION_PLAN.md`「质量收口第二轮」节 + `findings.md` 2026-09-04 各节
   （**不要重新审计**：A1 三 persona 审查的 5C+7I 已修复并 scoped re-review 通过）
3. `docs/PROJECT_LOG.md` 最后两条（LOG-20260904-01 门禁上线、LOG-20260904-02 阈值冻结）
4. `docs/PITFALLS.md`（四层根因 + 24 踩坑 + 8 已证伪方向——**第三节不得重试**）
5. 两份在途交接（本轮要执行/续接的）：
   - `docs/handoffs/2026-08-23-r9-phase-b-round4-execution-prompt.md`（D1，判读规则已预注册）
   - `docs/handoffs/2026-08-27-r10-degradation-rerun.md`（E2，**§5 故障手册必读**）
6. `docs/OOD_SEALED_LEDGER.md`（D4 的规则 4：新测量 = 新池）与
   `configs/retail_ops/build/retail_ops_ood_v2_2_sealed_build.yaml`（sealed 构建先例）

## 2. 已冻结的决策（遇到不要再问，也不要重开）

| 决策门 | 结论 | 出处 |
|---|---|---|
| #1 v1.3 阈值 | **冻结 `policy_violation_count_max = 0`、`success_delta_ci_lower_min = +0.02`**（用户 2026-09-04 确认） | LOG-20260904-02 |
| #3 max_steps 4→6 / reason 语义化 | **缓议维持**（提案文档的建议未被推翻） | `docs/PROPOSAL_EVAL_SEMANTICS_C4.md` |
| #4 DPO | **D4 之后再说**（用户 2026-09-04 裁定；D4 判定完成前不启动采样器/训练） | `docs/DPO_ENTRY_EVIDENCE_D2.md` |
| #6 宽工具面迁移 | **不迁移**（用户 2026-09-04 裁定；发布口径维持 v1/v2，v3/v4 结论保持探索性） | `docs/TOOLFACE_MIGRATION_ANALYSIS_E1.md` |
| 发布候选 | **仍是 `sft-008`（合并部署形态）**，D1/E2 结论仅探索性，不改变候选 | 既有台账 |

## 3. 资源与凭据

### 3.1 gpu-5090（2026-09-04 只读实测）

- 远端仓库：`/mnt/aidata/tongjiakai/retail-agent-ops`，HEAD 在 `f192b6f4`——**落后本地
  15+ 个提交，执行前必须同步**（见 §4 第 0 步）。
- GPU 0：RTX 5090，12.2 / 32.6 GB 已用（他人占用），0% util → **约 20 GB 空闲**；
  QLoRA 训练峰值 5.65 GB、NF4 评测同量级，够用。多人共用卡，跑之前重看一眼
  `nvidia-smi`，跑长任务用 `nohup`。
- 远端有一个未跟踪的 `archive/` 目录；同步后先确认 `git status --short` 里没有
  **已跟踪文件**的改动（rtc 交接的坑 1：工作树不干净会拒盖 code_commit）。
- 驱动故障处理照 E2 交接 §5.5：`nvidia-smi` D 状态 = 停手抓 dmesg、报用户重启，
  **不要**尝试 `--gpu-reset` 或杀别人的进程。

### 3.2 LLM API（teacher / 措辞池生成）

- 用户指定的模型与端点：**`mimo-v2.5` @ `https://opencode.ai/zen/go/v1`**（OpenAI 兼容）。
  API key 由用户在会话内提供，**绝不写入仓库任何文件**（治理测试会抓；`.env` 已被
  gitignore，密钥只进远端/本地 `.env`）。
- provider 接入方式（`.env` 追加，本地与远端各一份）：

  ```bash
  TEACHER_LLM_PROVIDER=mimo
  TEACHER_LLM_MIMO_BASE_URL=https://opencode.ai/zen/go/v1
  TEACHER_LLM_MIMO_API_KEY=<会话内提供的 key>
  TEACHER_LLM_MIMO_MODEL=mimo-v2.5
  ```

  `teacher_client.py` 按 `TEACHER_LLM_PROVIDER` 大写后拼 `TEACHER_LLM_{PROVIDER}_*`，
  `EXTRA_BODY_JSON` 可不设。**使用 mimo 以外的任何模型必须先获得用户允许。**
- **费用纪律**：每次 API 调用前先 `--dry_run` 估量，跑完把 token 用量与金额记进
  `progress.md` 的命令表（teacher_client 的响应里有 usage 字段）。
- **teacher 混用纪律（重要）**：E2 的 smoke 采集证据（5 断点，2026-08-27）是
  **DeepSeek 产的且已落盘**，续跑会按任务跳过、不再计费——这是设计行为。
  若续跑时出现**新增** teacher 采集需求（说明证据文件缺损），**先停下**向用户确认
  是否接受同一实验内混用两个 teacher（混杂变量），不要静默混采。
- 换 teacher 的行为差异要有预期（PITFALLS #4/#5）：不同模型对 DENY 类措辞的服从率
  不同，教师给的轨迹必须过执行式 verifier 才能进训练——这两条装置里已有，不要绕过。

## 4. 执行顺序与命令清单

> 每条命令的属性：**工作目录 / 物理 GPU / 预计时长 / 产物**。按序执行；前一步的
> 通过条件不满足就停在原地定位，不要靠加长运行时间硬闯（E2 交接 §0 的教训）。

### 第 0 步：环境准备（~10 分钟，零 GPU）

1. 本地：确认全绿 + 推送到 origin（远端靠 origin 同步，此为既定流程；本次 push 已在
   用户批准的执行范围内）：

   ```bash
   # 工作目录：本地仓库根
   .venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy
   git push origin main
   ```

2. 远端：同步 + 自检：

   ```bash
   # 工作目录：gpu-5090:/mnt/aidata/tongjiakai/retail-agent-ops（物理 GPU：无，纯 git/fs）
   git pull --ff-only origin main && git log --oneline -1   # 应等于本地 HEAD
   git status --short                                        # 已跟踪文件不得有改动
   timeout 20 nvidia-smi -L                                  # 能返回 = 驱动正常（§5.5 判据）
   python3 - <<'PY'                                          # 远端 venv 依赖与本地 HEAD 一致性
   import subprocess, sys
   print(sys.executable)
   PY
   uv sync --frozen 2>/dev/null || .venv/bin/pip check       # 视远端环境取其一
   ```

   追加 §3.2 的 mimo provider 块到远端 `.env`（本地 `.env` 同样加，供 bank-004 生成）。

3. 预检（本地 CPU，零成本）：

   ```bash
   # 工作目录：本地仓库根
   .venv/bin/pytest tests/test_retail_ops_toolcount_eval.py tests/test_retail_ops_v3_tasks.py -q
   .venv/bin/python scripts/run_v3_degradation.py --profile smoke --stage preflight
   .venv/bin/python scripts/run_v3_degradation.py --profile full  --stage preflight
   ```

   任一不过 → 按 E2 交接 §5.1/§5.2 定位，**一分钱 GPU/API 都不该花**。

### 第 1 步：C2 方差治理 GPU 验证（物理 GPU 0；2 × ~10 min；零 API 费用）

同配置同 seed（0）训练两次，对比 adapter SHA-256 与 `metrics.json` 的 `determinism`
provenance，把「同 seed 逐位不同」的无边界表述替换成实测结论。

```bash
# 工作目录：gpu-5090:/mnt/aidata/tongjiakai/retail-agent-ops；GPU 0；每次 ~10 min（960 行 / 180 步）
set -a && source .env && set +a
env TORCH_DISABLE_NATIVE_JIT=1 .venv/bin/retail-agent-ops build \
  --config configs/retail_ops/build/retail_ops_v1_r6b_no_oversample_sft.yaml \
  --input_dir data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722 \
  --seed 0 \
  --output_dir reports/retail_ops/v1/r6/sft-008-determinism-a
# 第二次：同一命令，--output_dir 换成 ...-determinism-b（输出目录不可覆盖）
```

- 配置就是 **sft-008 的训练配置**（`retail_ops_v1_r6b_no_oversample_sft.yaml`，
  960 行 / 180 步），因此结论直接治理「sft-008 不可复现」的表述；前提是远端私有根里
  `train-export/train-export-007/sft.jsonl` 在（R6 跑过，应在；缺失即停，报告用户）。
- 产物：两个 run 目录（`adapter/`、`metrics.json`、`config.yaml`）。
- **判读**（跑之前写定）：`sha256sum adapter/adapter_model.safetensors` 两次逐位相同
  → 「同 seed 逐位复现（在本配置 + 本驱动 + 本卡上）」；不同 → 用两个
  `metrics.json` 的 loss 曲线量化方差（「方差收窄到 X」），并把差异归因到
  `determinism.provenance` 里声明为不可消的 bitsandbytes 原子操作——**两种结果都是
  有效结论，如实记录**。
- 收口：结论写进 `findings.md` 与 `docs/REBUILD_VERIFICATION.md`（追加，不改写），
  并替换 `AGENTS.md`/`RESUME_EVIDENCE.md` 里「同 seed 逐位不同」的无边界表述。
  若逐位复现成立，追加 PROJECT_LOG（方法论级：训练可复现性结论变更）。

### 第 2 步：D1 rtc 第四轮（物理 GPU 0；teacher ~¥? 记账 + 训练 ~25 min + 三面评测 ~40 min）

照 `docs/handoffs/2026-08-23-r9-phase-b-round4-execution-prompt.md` **原样执行**，要点：

- **方案甲单变量**：`_v4_family_spec` 的 CANCEL_* 每场景 train family 20 → 30–35，
  其余与 sft-003 完全一致；attempt_id `train-export-v4-004`，候选 `sft-004`。
- **判读规则已预注册**（rtc dev ≥ 8/10 且 OOD v4 rtc ≥ 5/10 且 pv 不升 → 修好），
  一个字不改地用；**方案乙必须先停下获得用户确认**（round4 交接第四步原文）。
- **teacher 换 mimo**：新增 cancel family 的采集走 mimo；DENY 类措辞先按 R9 经验
  写「评估/判断」式（PITFALLS #5），采集后核对接受率 ≥0.80 门禁。
- 已证伪方向（调 rtc oversample 权重、统一调用顺序）不得复活。
- 已知坑四条（远端工作树、SFT/TaskSpec 数据互斥换入换出、adapter 哈希现算、
  输出目录不可覆盖）照 round4 交接第五步执行。
- 产物：`train-export-004` 导出证据、`sft-004` adapter、三面评测报告
  （v4 dev / OOD v2 / OOD v4）。
- 收口：`docs/R9_PHASE_B_RESULTS.md` 追加第四轮小节 + findings/progress/LOG。

### 第 3 步：E2 退化曲线续跑（物理 GPU 0；smoke 续跑 ~1–1.5 h；full ~4–6 h nohup）

**远端现状（2026-09-04 实测）**：`reports/retail_ops/v1/r10-rerun/smoke/` 下 5 个断点
目录齐全；`toolcount-3/` 有 teacher + sft + `eval-base`，**缺 `eval-candidate`**——
正是 2026-08-27 驱动卡死的中断点。smoke 数据阶段 5 断点全部过门禁且已落盘（续跑不再
计费）。

```bash
# 工作目录：gpu-5090:/mnt/aidata/tongjiakai/retail-agent-ops；GPU 0；smoke 续跑 ~1–1.5 h
nohup .venv/bin/python scripts/run_v3_degradation.py --profile smoke > smoke-resume.log 2>&1 &
tail -f smoke-resume.log
```

- 冒烟门禁（脚本自动判，退出码 4 = 未过）四条：teacher 接受率 ≥0.80（应直接由既有
  证据通过）、`infrastructure_error_count = 0`、`tools_presented` 逐字等于断点声明、
  发出过合法工具调用的 episode ≥80%。**全过才进 full**；不过按 E2 交接 §5 定位。
- full 阶段含新 teacher 采集（大样本，mimo 计费）：

  ```bash
  # GPU 0；~4–6 h；nohup 长跑
  nohup .venv/bin/python scripts/run_v3_degradation.py --profile full > full.log 2>&1 &
  ```

  断点级续跑（`done.json`）自动跳过已完成断点。
- 若出现**新增** teacher 采集需求（smoke 证据缺损）→ 停，向用户确认混 teacher 事项
  （§3.2）。
- 收口照 E2 交接 §3.4：curve.json 回本地核对哈希、读数只按
  `curve_readable_scenarios` 口径陈述、LOG 追加（不改写 LOG-20260827-01）、
  `RESUME_EVIDENCE.md` / `INTERVIEW_PREP.md` 的「读数作废」段落到此更新为真读数。

### 第 4 步：D4 一次性 v1.3 发布判定（顺序严格，最后执行）

**这是本阶段的收口动作，前置条件：C2/D1/E2 已收口且其代码改动全部提交（「代码冻结」）。**

1. **生成 `phrasing-bank-004`**（mimo 计费；v2.2 先例 268 条 / $0.0061 量级）：

   ```bash
   # 工作目录：本地仓库根（或远端，二选一，产物进私有根）；零 GPU
   .venv/bin/python scripts/ops/generate_phrasing_bank.py --dry_run \
     --output_dir data/private/retail_ops/v1/phrasing/phrasing-bank-004 --per_intent 90
   # dry_run 看质量与估成本 → 去掉 --dry_run 正式跑；输出目录不可覆盖
   ```

   记录：token 用量与金额、生成模型（mimo-v2.5——**与 bank-002/003 的 DeepSeek 不同，
   这是素材层面的真实差异，写进台账**）。
2. **互斥性实测**（v2.2 先例的同款检查）：bank-004 的 `ood_sealed` 分片与 bank-002/003
   全部分片、与真实训练文件 `train-export-*/sft.jsonl` 的说法交集必须为 0。
3. **登记新 dataset_version + sealed 构建配置**（TDD，照 v2.2 先例逐字段照抄）：
   `OodDatasetVersion` Literal 加新版本号、新 sealed build config（只差 `phrasing` 段）、
   复刻 `test_retail_ops_r7_rebuild.py` 的「两配置只差 bank」断言。
4. **判读规则与运行内容先写定并提交**（写进 `task_plan.md` 后 commit，再动任何 GPU）：
   - 运行内容（建议，照 v2.2 先例）：新封存分片上跑 零训练基座 + `sft-008`（合并形态）
     两个 OOD 评测；封存 holdout 观测 7 = base + 合并候选两份 sealed 评测；
     然后 `release --gate_schema_version 1.3`（带 `--*_trajectories` 与 OOD 证据）。
   - 判读：v1.3 十二门逐门读。**预期结果（基于既有读数的诚实预判）：NO-GO——
     `policy_violation_count_max` 必然拦下违规 2/7 > 0**。这不是流程失败：D4 的目的是
     把 v1.2 OOD 门与 v1.3 绝对门的**首次真实发布判定**写入台账，宣告当前候选在绝对
     安全门下不合格；违规根治的路径是 DPO（用户已裁定 D4 后启动）。
   - **无论结果如何不重跑、不换素材再试；结果不得反馈进任何后续开发。**
5. **一次性执行**（GPU 0；OOD 2× ~20 min + holdout 2× ~40 min + release 秒级）。
6. 判定后收口：`HOLDOUT_LEDGER.md` 追加观测 7、`OOD_SEALED_LEDGER.md` 追加新分片观测、
   `EXECUTION_PLAN.md` 追加记录、`findings.md` 记读数、`PITFALLS.md` 追加本轮新踩坑
   （若有）；对外材料若引用 GO/NO-GO 必须按新口径成对陈述。

## 5. subagent 使用规范（本窗口已获用户批准沿用）

- 适用于：探索、code review、可并行的独立小任务；**读数与结论必须抽查**——要么自己
  复算，要么用测试验证，不得直接采信。
- 沿用三 persona 规程（评测基建 / SRE / 对抗）做阶段性复审：D4 判定落盘后建议做一次
  scoped re-review（范围：新 dataset_version 登记、sealed 配置、判读规则执行与台账
  追加是否逐字符合预注册）。

## 6. 硬边界（全部沿用，逐条仍在生效）

- 封存 holdout 与 OOD 封存分片的结果**永远不得反馈进开发**；D4 之后才启动 DPO。
- 已证伪方向 8 条（`PITFALLS.md` §三）不得重试；D1 不得调 rtc oversample 权重。
- 不改 v1/v2 冻结契约：`GATE_IDS` v1.0–v1.2、`SealedEvaluationReport` 字段集、
  `PAIRING_FIELDS`、`assert_exact_quotas` 的 40/10/20、`runner.SYSTEM_PROMPT`、parser。
- 不为了让数字好看改任务、关守卫或挑读数；历史文档 append-only。
- v1.3 判读规则与运行内容**必须在观测之前写定并提交**；观测必须在代码冻结提交之后。
- 每条远程 GPU 命令按 §4 清单执行；偏离清单先停下确认。API 费用逐次记账。
- Python 统一 `uv`；文档默认简体中文；不自动 push 之外的远端操作（origin push 是
  本阶段已批准的同步手段）。

## 7. 验收（每轮收口全绿）

```bash
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy
env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check
git diff --check
.venv/bin/python scripts/ci/verify_qualification_chain.py
.venv/bin/python scripts/ci/audit_public_release.py
```

## 8. 故障手册指针

- gpu-5090 驱动卡死（D 状态判据、Xid 抓取、只能重启整机）：E2 交接 §5.5；
- preflight 自检门（自变量生效性、gold 可解性）：E2 交接 §5.1–5.2；
- teacher 接受率低与 DENY 措辞先验：E2 交接 §5.3、PITFALLS #4/#5；
- Triton JIT 缺系统编译器：`TORCH_DISABLE_NATIVE_JIT=1`（E2 交接 §5.4）；
- 读数「太平坦」的自检顺序：E2 交接 §5.7；
- cpolar 隧道 host key 变更：`task_plan.md` Errors 表（核对指纹后 `ssh-keyscan -H` 追加，
  **不关** `StrictHostKeyChecking`）。
