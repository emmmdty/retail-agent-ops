# RetailAgentOps CPU 镜像。
#
# **刻意不含 torch / transformers / peft / bitsandbytes**：那套重依赖只在 GPU
# 主机上安装（`pyproject.toml` 的 `train` extra）。这个镜像覆盖的是本项目在
# CPU 上真正能跑完的那一半——R1 qualification 全链路（build → evaluate → release）
# 与 formal serve 的装配路径。把 GPU 依赖塞进来只会让镜像从几十 MB 涨到几 GB，
# 却不会多跑通任何一条命令。
#
# **2026-08-16 首次实际构建并验证**：镜像 **1.05 GB**，在 `--network none`（完全离线）
# 下跑通 `verify_qualification_chain.py`，输出"决策与内容哈希均与冻结期望一致"。
# 此前本注释写的是"几十 MB"——那是个从未验证过的估计，与实测差一个数量级，已更正。
# 1.05 GB 里绝大部分是 `--extra dev`（pytest/ruff/mypy）与 numpy/pydantic 的 wheel；
# 装上 `train` extra（torch + CUDA runtime）会再涨到 ~7 GB 量级，那才是不装它的理由。
#
# 构建：
#   docker build -t retail-agent-ops:cpu .
# 跑一次全链路复现校验（与 CI 同一条命令；加 --network none 证明它不需要网络）：
#   docker run --rm --network none retail-agent-ops:cpu
# 看命令面：
#   docker run --rm retail-agent-ops:cpu retail-agent-ops --help
#
# serve 需要 API key，且它只能来自环境变量、绝不进镜像层：
#   docker run --rm -e RETAIL_AGENT_OPS_API_KEY=... -p 8000:8000 retail-agent-ops:cpu ...

FROM python:3.11-slim-bookworm

# uv 由官方镜像提供二进制，避免在容器里再解析一次自身依赖。
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 先只拷依赖声明，让依赖层在源码变化时仍能命中缓存。
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --extra dev

COPY src ./src
COPY configs ./configs
COPY domains ./domains
COPY scripts ./scripts
COPY tests ./tests
RUN uv sync --frozen --extra dev

# 不以 root 运行：服务会执行模型输出驱动的工具调用，最小权限是基本要求。
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app /opt/venv
USER appuser

# 无网络、无凭据即可完成的自检；镜像坏了会在这里暴露而不是在运行时。
HEALTHCHECK --interval=60s --timeout=30s --start-period=5s --retries=2 \
    CMD python -c "import veritool_rl.product_cli" || exit 1

CMD ["python", "scripts/ci/verify_qualification_chain.py"]
