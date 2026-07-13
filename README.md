# VeriTool-RL

**Verifier-Guided Curriculum Post-Training for Small Tool-Using Agents**
面向小型工具智能体的可验证课程式后训练方法

面向 1.5B–4B 级开源模型, 用「成功轨迹 SFT + 失败轨迹偏好优化 + 校准的可验证奖励 + schema 扰动」研究**课程顺序、奖励设计与工具鲁棒性**对多轮工具任务成功率与稳定性的影响。在 BFCL / ToolSandbox / 单个 tau2 领域上做因果消融。

> **状态**: 🚧 已初始化 (标准骨架, 接口签名就绪, 核心逻辑待按 `SPEC.md` 分步实现)。研究级 L1/L2, 不宣称生产上线。

## 文档

- **[`SPEC.md`](./SPEC.md)** — 项目规格 (single source of truth): 问题、假设 H1–H4、数据、基线、评测、消融、里程碑。
- **[`CLAUDE.md`](./CLAUDE.md)** — coding agent 协作协议、命令、必须人工手写的核心模块。

## 快速开始

```bash
uv sync --extra dev          # 创建环境 (提交生成的 uv.lock)
uv run pytest                # 结构 smoke 测试
```

训练重依赖 (torch/trl/peft) 请在 **gpu-4090** 服务器上 `uv sync --extra train`; 本地只做开发与轻量评测。

## 环境

- Python 3.11 · uv · 训练机 4× RTX 4090 (24GB)
- 遵循工作区 [`../AGENTS.md`](../AGENTS.md) 统一开发规则。
