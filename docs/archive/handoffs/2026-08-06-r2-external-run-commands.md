# RetailOps v1 R2 外部执行命令清单

## 状态

- 日期：2026-08-06
- 分支：`feature/r2-formal-data-and-base-eval`，HEAD 待本文档提交后确定（见文末最终验收）
- CPU 实现范围（Task 1-7）：已完成，独立审查通过（含整分支审查一次修复轮）
- 本文档状态：**清单本身未执行任何命令**。以下每一节列出的命令均为"待批准"，必须逐条获得用户对精确命令的确认后才能执行，不得批量批准或跳过任何一节。
- 关联：`docs/superpowers/plans/2026-07-22-retailops-v1-r2-formal-data-and-base.md`（Task 8）、
  `docs/handoffs/2026-08-05-r2-task5-7-execution-prompt.md`、`docs/PROJECT_LOG.md`
  LOG-20260805-10 至 LOG-20260806-02。

## 0. 在执行本清单任何一节之前：必须满足的前置条件

整分支最终审查（re-review 后确认无残留 Critical/Important）明确指出：`_run_formal_dev_base`
现在会在工作树不干净时直接拒绝运行（`git status --porcelain` 非空即报错，含未跟踪文件）。
这意味着实际执行顺序比原计划想象的更严格，必须按以下顺序处理提交，而不是"跑完所有步骤最后
一次性提交"：

1. **`manifests/retail_ops/v1/<dataset_version>/` 不在 `.gitignore` 覆盖范围内**（`data/`、
   `models/`、`reports/retail_ops/` 都被忽略，这个目录没有）。第 1 节 `formal_freeze`
   产出的 4 个公开文件（`train.json`/`dev.json`/`holdout-receipt.json`/`dataset.json`）
   必须在进入第 3 节（`formal_dev_base`）之前提交到 Git，否则会被判定为"未跟踪 = 脏"。
2. 两份 `configs/retail_ops_v1_r2_qwen3_{1_7b,4b}_dev.yaml` 的 `model.revision`/
   `model.file_sha256` 占位值必须替换成真实值**并提交**，不能只在远端临时编辑
   （见第 6 节）。
3. 每次 `evaluate --config configs/retail_ops_v1_r2_qwen3_*_dev.yaml` 之前，确认
   `git status --porcelain` 为空（包括本会话自己写的 `docs/PROJECT_LOG.md` 追加记录）。
4. 所有 `--output_dir` 必须指向已被忽略的路径（`reports/retail_ops/...`），不要指向
   `manifests/` 或仓库其他未忽略目录，否则下一次评测又会因为新的未跟踪文件而被拒绝。

这四点是本会话整分支修复轮引入的真实行为变化（`commit c4d7fdc`），不是原计划文本就有的
要求；命令清单据此调整执行顺序。

## 1. formal freeze（本地 CPU，产出正式 240/60/120 数据集）

**未执行。** 精确命令：

```bash
cd /home/tjk/myProjects/internship-projects/retail-agent-ops
.venv/bin/retail-agent-ops build \
  --config configs/retail_ops_v1_r2_formal_freeze.yaml \
  --output_dir manifests/retail_ops/v1/retail_ops_v1_r2_20260722
```

- 工作目录：本地 WSL 仓库根目录（无需远端/GPU）。
- 预计耗时：数秒（纯 CPU 生成 240+60+120=420 条任务并写文件）。
- 产物：
  - 私有（ignored，CLI 内部推导，不是 config 字段）：
    `data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722/{train,dev,holdout}.jsonl`
  - 公开（本命令的 `--output_dir`）：
    `manifests/retail_ops/v1/retail_ops_v1_r2_20260722/{train.json,dev.json,holdout-receipt.json,dataset.json}`
- 批准后建议：按计划验收，独立重跑一次到临时目录做逐字节比较（CPU 测试已覆盖同一断言，
  这里只是对正式产物做一次人工复核，非强制）。
- **批准后必须紧接着执行**：
  ```bash
  git add manifests/retail_ops/v1/retail_ops_v1_r2_20260722/
  git commit -m "data: freeze RetailOps v1 R2 formal answer-free manifests"
  ```
  （见第 0 节第 1 点——不提交这一步，后续 `formal_dev_base` 会因为未跟踪文件判定工作树
  不干净而拒绝运行。）

## 2. `.env` preflight（本地，只读检查，不打印密钥值）

**未执行。** 精确命令（均不输出密钥内容，只输出文件权限与变量名）：

```bash
cd /home/tjk/myProjects/internship-projects/retail-agent-ops
stat -c "%a %n" .env
grep -o '^[A-Z_]*=' .env
```

- 预期结果（已在本会话核对过一次，供比对）：权限 `600`；变量名精确为
  `TEACHER_LLM_PROVIDER`、`TEACHER_LLM_DEEPSEEK_BASE_URL`、`TEACHER_LLM_DEEPSEEK_API_KEY`、
  `TEACHER_LLM_DEEPSEEK_MODEL`、`TEACHER_LLM_DEEPSEEK_EXTRA_BODY_JSON`。
- 若权限或变量名不符，停止并让用户先修正 `.env`，不得由 agent 编辑或打印其内容。
- 确认后运行：
  ```bash
  set -a; source .env; set +a
  .venv/bin/python -c "
  from veritool_rl.retail_ops.teacher_route import load_teacher_route
  import os
  snapshot, _ = load_teacher_route(os.environ)
  print(snapshot.model_dump(mode='json'))
  "
  ```
  只打印不含凭据的 route snapshot（provider/base_url/model/extra_body/route_sha256），验证
  `.env` 能被正确解析、且 `extra_body` 确实含 `{"thinking":{"type":"disabled"}}`。

## 3. teacher smoke（本地，真实网络调用，产生真实费用）

**已于 2026-08-06 执行一次（`teacher-smoke-001`，见 `docs/PROJECT_LOG.md`
LOG-20260806-05/06），本节描述已按实际行为更正。** 精确命令：

```bash
cd /home/tjk/myProjects/internship-projects/retail-agent-ops
set -a; source .env; set +a
.venv/bin/retail-agent-ops build \
  --config configs/retail_ops_v1_r2_teacher_smoke.yaml \
  --input_dir data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722 \
  --output_dir reports/retail_ops/v1/r2/retail_ops_v1_r2_20260722/teacher-smoke-001
```

- 工作目录：本地 WSL（这是纯 API 调用，不需要 GPU）。
- **更正**：`configs/retail_ops_v1_r2_teacher_smoke.yaml`（`pipeline: teacher_collect`）
  没有任何任务数量限制字段，会处理 `--input_dir` 私有根目录下 `train.jsonl` 的**全部
  240 条**任务，只是把 `max_episodes_per_task`/`max_request_attempts` 降到 `1`/`1`
  （相对 teacher_full 的 `2`/`3`）。"每类别 1 条、共 6 条"是本文档原稿的错误设想，
  从未与 `teacher_collect` 实现核对过；`teacher_collect` 当前不支持按数量抽样，"更便宜
  的 smoke"和"全量采集"唯一的区别只是重试预算，不是任务数量。这条命令的真实费用/耗时量级
  与第 4 节相近（首次真实执行：519 次请求、约 $0.055、耗时约 12 分钟，而非本节曾经承诺的
  "<$0.01、数秒到约 1 分钟"），不是可忽略的探测性调用。
- 预计耗时：数秒到约 1 分钟（参照 2026-08-05 20 条真实 smoke 实测单次调用约 1 秒）。
- 预计费用：按 2026-08-05 实测单价推算 < $0.01（6 次调用，远小于 20 条 smoke 的
  $0.003996）。
- 产物：`data/private/retail_ops/v1/r2/.../teacher-collection/teacher-smoke-001/`
  （逐任务证据 + checkpoint，ignored）；`--output_dir` 下的公开聚合 `summary.json`
  （不含任务级内容）。
- 批准后请报告：route snapshot、6/6 结构成功率、环境成功率、总请求数、token 用量、
  任何错误分类。

## 4. 240 任务 API 全量采集 + train 导出（本地，真实网络调用，产生真实费用）

**未执行，且必须在第 3 节 smoke 结果被用户单独确认"结构与环境成功率符合预期"之后才请求
批准。** 精确命令（采集 + 导出两步）：

```bash
cd /home/tjk/myProjects/internship-projects/retail-agent-ops
set -a; source .env; set +a
.venv/bin/retail-agent-ops build \
  --config configs/retail_ops_v1_r2_teacher_full.yaml \
  --input_dir data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722 \
  --output_dir reports/retail_ops/v1/r2/retail_ops_v1_r2_20260722/teacher-full-001

.venv/bin/retail-agent-ops build \
  --config configs/retail_ops_v1_r2_train_export.yaml \
  --input_dir data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722 \
  --output_dir reports/retail_ops/v1/r2/retail_ops_v1_r2_20260722/train-export-001
```

- 240 条 train 任务，`max_episodes_per_task=2`、`max_request_attempts=3`（理论上限 1440 次
  调用）。
- 预计耗时：按 2026-08-05 实测（20 条同类别串行 42.5 秒）线性外推且不跨类别外推，
  乐观估计 **8-15 分钟**；因 6 类任务步数可能高于已测的 `lookup_status`，保守估计到
  **30-40 分钟**。首次全量运行前应观察实际速率并可随时中断（`teacher_collect` 支持按
  `attempt_id` 安全续跑，已采集任务不会重复计费——本会话已用回归测试验证这一点）。
- 预计费用：按 2026-08-05 实测单价（$0.14/M 输入、$0.28/M 输出，未计 cache-hit 折扣）
  线性外推约 **$0.05-0.10**；不设金额硬上限，但必须记录真实请求数与 usage。
- 质量门：整体 ≥70%、每类别 ≥50%；不达标时命令会以 `TeacherQualityGateError` 停止，
  **不得**自动改 prompt/模型/provider——回来找用户决定。
- 产物：私有完整 `train-export/train-export-001/{train.jsonl,sft.jsonl,selection.json}`
  （ignored）；公开 `train-export-001/quality.json`（仅聚合指标，不含任务/prompt）。
- 批准后请报告：teacher 总通过率、逐类别通过率、teacher/internal_reference 各自条数、
  总请求数、总费用、总耗时。

## 5. 只读 SSH 盘点（远端环境，无副作用）

**在盘点命令给出实际空闲物理 index/UUID 之前，不存在任何 GPU 命令。**

两个远程环境均可选，CLAUDE.md §4 要求同一任务只用其中一个，需用户明确选择：

- **`gpu-5090`**（推荐，理由见第 6 节：Qwen3-1.7B/4B 已下载并逐文件 SHA256 校验通过）：
  `ssh gpu-5090`，仓库路径固定 `/mnt/aidata/tongjiakai/retail-agent-ops`，模型根
  `/mnt/aidata/tongjiakai/models`，`uv` 为 `~/.local/bin/uv`。
- **`gpu-4090`**（备选，需要重新下载模型）：`ssh gpu-4090`，仓库路径固定
  `/data/TJK/internship-projects/retail-agent-ops`，`uv` 为 `/home/TJK/.local/bin/uv`，
  `UV_CACHE_DIR=/data/TJK/uv-cache`。

盘点命令（两个环境相同结构，路径按选定环境替换）：

```bash
ssh <gpu-4090|gpu-5090> 'nvidia-smi --query-gpu=index,uuid,name,memory.used,memory.total,utilization.gpu --format=csv'
ssh <gpu-4090|gpu-5090> 'nvidia-smi --query-compute-apps=pid,used_memory,process_name --format=csv'
ssh <gpu-4090|gpu-5090> 'nproc && free -h'
ssh gpu-5090 'df -h /mnt/aidata'          # 或
ssh gpu-4090 'df -h /data/TJK /home/TJK'
ssh <gpu-4090|gpu-5090> 'whoami && pwd'
```

- 目的：确认物理 GPU index/UUID、当前空闲显存、是否有其他用户进程占用（两台均为多人
  共用环境）、磁盘余量。
- 只读，无任何写入或长任务。
- 拿到结果后，第 7/8 节的具体命令才能补上真实的物理 GPU index/UUID，每条单独等待批准。

## 6. 远端代码同步

**未执行。** 以 `gpu-5090` 为例（已验证过一次可行的同步方式，见
`docs/PROJECT_LOG.md` LOG-20260805-01/02）：

```bash
# 本地：只打包已提交的历史（不含任何未提交改动）
git bundle create /tmp/retail-agent-ops-r2.bundle feature/r2-formal-data-and-base-eval

# 传输
scp /tmp/retail-agent-ops-r2.bundle gpu-5090:/tmp/

# 远端：首次 clone 或已存在仓库时 fetch + merge/rebase 到 bundle 里的最新 commit
ssh gpu-5090 'cd /mnt/aidata/tongjiakai/retail-agent-ops && git fetch /tmp/retail-agent-ops-r2.bundle feature/r2-formal-data-and-base-eval:incoming && git status'
# 核对 incoming 与本地 HEAD 一致后再决定 merge/reset 到该 commit——由用户确认，不自动执行
```

- 远端环境同步后需要执行（gpu-5090 之前只 sync 过 `--extra dev --extra train`，
  `teacher` extra 尚未同步过）：
  ```bash
  ssh gpu-5090 'cd /mnt/aidata/tongjiakai/retail-agent-ops && ~/.local/bin/uv sync --extra dev --extra train --extra teacher --frozen'
  ```
- 预计耗时：`git bundle`/`scp` 数秒到数十秒（仅历史，不含模型）；`uv sync` 视网络和缓存
  情况数十秒到几分钟。
- 产物：远端仓库 HEAD 与本地一致；远端 `.venv` 含 teacher extra。
- **同步后必须确认远端工作树干净**（`ssh gpu-5090 'cd .../retail-agent-ops && git status --porcelain'`
  应为空），否则第 8 节的 `formal_dev_base` 会被拒绝——这是本会话整分支修复引入的新
  前置条件，同步流程必须显式包含这一步核对。

## 7. 每个锁定模型下载

**Qwen3-1.7B、Qwen3-4B 在 `gpu-5090` 上已经下载完成并逐文件 SHA256 校验通过**
（`docs/PROJECT_LOG.md` LOG-20260805-01/02/03；`findings.md` "gpu-5090 环境扩展与
ModelScope 重新锁定"小节）：

- `Qwen/Qwen3-1.7B`：ModelScope commit `980712f58bdf09497308d37d0e30b535064cde04`，
  磁盘占用 3.8G，路径 `/mnt/aidata/tongjiakai/models/Qwen3-1.7B/`。
- `Qwen/Qwen3-4B`：ModelScope commit `8cd0101f70cac4f1efcebc979faf483558e39297`，
  磁盘占用 7.6G，路径 `/mnt/aidata/tongjiakai/models/Qwen3-4B/`。

**请用户先决定：是否复用 gpu-5090 已有的这两份模型文件，而不是默认重新下载。** 若选择
复用，跳过下面的下载命令，直接执行"复用现有下载"小节；若选择 `gpu-4090` 或要求重新下载，
执行"全新下载"小节。

### 复用现有下载（gpu-5090，推荐）

```bash
ssh gpu-5090 'ls -la /mnt/aidata/tongjiakai/models/Qwen3-1.7B/ /mnt/aidata/tongjiakai/models/Qwen3-4B/'
ssh gpu-5090 'cd /mnt/aidata/tongjiakai/retail-agent-ops && mkdir -p models && ln -sfn /mnt/aidata/tongjiakai/models/Qwen3-1.7B models/Qwen3-1.7B-pinned && ln -sfn /mnt/aidata/tongjiakai/models/Qwen3-4B models/Qwen3-4B-pinned'
```

- 说明：`configs/retail_ops_v1_r2_qwen3_*_dev.yaml` 的 `models_root: models` +
  `local_dir: Qwen3-{1.7B,4B}-pinned` 要求模型文件出现在仓库相对路径
  `models/Qwen3-*-pinned/` 下；`/models/` 已被 `.gitignore` 忽略，用符号链接指回真实存储
  路径（同 `data/external_repos` 的既有模式），不复制 11.4G 数据。
- 之后必须重新计算逐文件 SHA-256 并回填两份 dev config（而不是信任 2026-08-05 记录的
  ModelScope commit级哈希——那是整仓库/提交级别的校验，`ModelArtifact.file_sha256` 需要
  的是 `hash_local_model_files` 逐文件哈希，且必须覆盖目录下**全部**非点号前缀文件，
  否则 `verify_local_model_files` 会因文件集合不匹配而拒绝）：
  ```bash
  ssh gpu-5090 'cd /mnt/aidata/tongjiakai/retail-agent-ops && .venv/bin/python -c "
  from pathlib import Path
  from veritool_rl.agent.qwen import hash_local_model_files
  for name in (\"Qwen3-1.7B-pinned\", \"Qwen3-4B-pinned\"):
      d = Path(\"models\") / name
      files = sorted(p.name for p in d.iterdir() if p.is_file() and not p.name.startswith(\".\"))
      print(name, files)
      print(hash_local_model_files(d, files))
  "'
  ```
  把输出的文件名列表和哈希填入对应 config 的 `model.file_sha256`（替换示例里的 3 个
  占位 key 为真实的完整文件列表），`model.revision` 填 ModelScope commit
  （`980712f5...`/`8cd0101f...`），**改完后必须提交** `configs/retail_ops_v1_r2_qwen3_*_dev.yaml`
  （见第 0 节第 2 点）。

### 全新下载（仅当用户明确要求，例如改用 gpu-4090）

```bash
ssh <目标> 'nvidia-smi --query-gpu=memory.free --format=csv'   # 下载前再核对一次空闲显存/磁盘
ssh <目标> 'cd <repo> && .venv/bin/python -c "
from modelscope import snapshot_download
snapshot_download(\"Qwen/Qwen3-1.7B\", revision=\"master\", local_dir=\"<模型根>/Qwen3-1.7B\")
snapshot_download(\"Qwen/Qwen3-4B\", revision=\"master\", local_dir=\"<模型根>/Qwen3-4B\")
"'
```

- 预计耗时：11.4G 总量，视网络约 5-20 分钟。
- 下载后必须逐文件重算 SHA256 并与 ModelScope 侧 REST API 报告的逐文件哈希比对，
  ALL_FILES_VERIFIED_OK 才算通过，任何文件缺失/大小不符/哈希不符都判定整体失败——按
  2026-08-05 gpu-5090 下载时使用的同一验证方法。

## 8. 每次单任务 GPU smoke

**未执行，等待第 5 节盘点结果确认实际空闲物理 GPU index/UUID 后补上精确命令。** 命令骨架
（`<GPU_INDEX>`/`<GPU_UUID>` 待盘点后填入；工作目录为选定远端仓库根；先跑 1.7B 再跑 4B）：

```bash
ssh <目标> 'cd <repo> && CUDA_VISIBLE_DEVICES=<GPU_INDEX> git status --porcelain'   # 必须为空，见第0节
ssh <目标> 'cd <repo> && CUDA_VISIBLE_DEVICES=<GPU_INDEX> .venv/bin/retail-agent-ops evaluate \
  --config configs/retail_ops_v1_r2_qwen3_1_7b_dev.yaml \
  --input_dir data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722 \
  --output_dir reports/retail_ops/v1/r2/retail_ops_v1_r2_20260722/qwen3-1.7b-dev-base-smoke \
  --seed 0'
```

- 目的：在跑满 60 条之前，先验证单卡 CUDA 加载、4-bit NF4 量化、tool parser 与固定
  60 条 dev manifest 加载链路都能跑通（可考虑临时把 dev manifest 截成 1 条做纯粹的
  管线 smoke，或直接接受第一条任务的结果作为 smoke 证据——由用户在批准时选择）。
- 预计耗时：数十秒到几分钟（模型加载占大头）。
- 产物：`reports/retail_ops/v1/r2/.../qwen3-1.7b-dev-base-smoke/`（ignored）。
- 4B 模型同构命令，`--config configs/retail_ops_v1_r2_qwen3_4b_dev.yaml`、
  `--output_dir .../qwen3-4b-dev-base-smoke`。
- 记录物理 GPU index/UUID/名称（来自 `nvidia-smi`，不得只报告逻辑 `cuda:0`）、峰值显存、
  实际耗时。

## 9. 每次 60 任务 GPU dev run

**未执行，同样等待第 5 节盘点结果与第 8 节 smoke 通过后才请求批准。** 命令与第 8 节相同，
仅 `--output_dir` 换成正式产物目录（避免覆盖 smoke 证据）：

```bash
ssh <目标> 'cd <repo> && git status --porcelain'   # 必须为空
ssh <目标> 'cd <repo> && CUDA_VISIBLE_DEVICES=<GPU_INDEX> .venv/bin/retail-agent-ops evaluate \
  --config configs/retail_ops_v1_r2_qwen3_1_7b_dev.yaml \
  --input_dir data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722 \
  --output_dir reports/retail_ops/v1/r2/retail_ops_v1_r2_20260722/qwen3-1.7b-dev-base-001 \
  --seed 0'
# 4B 同构，--config configs/retail_ops_v1_r2_qwen3_4b_dev.yaml，
# --output_dir .../qwen3-4b-dev-base-001
```

- 预计耗时：未实测；60 条任务、最多 5 步/条、4-bit NF4 单卡推理，数量级参考 BFCL 200 条
  单轮评测的历史耗时按比例缩放估计，实际以真实运行为准，不得预先声称具体数字。
- 产物：私有 `run.json`/`trajectories.jsonl`/`metrics.json`（含逐任务结果，ignored）；
  公开 `base-report.json`（聚合指标 + 完整 provenance，无任务 ID）。
- 两个模型必须使用完全相同的 bundle/manifest/parser/seed/预算，只有 `model`/`attempt_id`
  不同，以保证可配对比较（R3 会用到，R2 本身不产出 GO/NO-GO）。
- 运行后需要：把 `code_commit`/`uv_lock_sha256`（CLI 自动计算，会因为工作树干净才能算出）
  与本地/远端锁文件核对一致；把两份 `base-report.json` 同步回本地供后续分析。

## 10. 证据同步与最终验收（无 GPU/API，本地）

以上任一节实际执行后，只把批准的公开安全产物（`base-report.json`、`quality.json`、
`summary.json` 等）与私有产物摘要同步回本地；私有完整证据保留在原产出环境的 ignored
路径，不因为"同步"而进入 Git。同步后需要：

```bash
# 逐份产物核对 SHA-256（示例，按实际同步的文件列表逐条执行）
sha256sum reports/retail_ops/v1/r2/retail_ops_v1_r2_20260722/qwen3-1.7b-dev-base-001/base-report.json
ssh <目标> 'sha256sum <远端同路径文件>'
# 两者必须一致

# 最终在实际最终 HEAD 上重跑完整门禁
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy
env -u UV_INDEX_URL -u UV_DEFAULT_INDEX uv lock --check
git diff --check
git status --short --branch
```

只有正式数据（第 1 节）、teacher 全量（第 4 节）、两份真实 dev base（第 9 节）、上述哈希
核对与完整门禁全部通过后，才能把 R2 标记为已完成——由用户最终确认，agent 不得自行下此
结论。
