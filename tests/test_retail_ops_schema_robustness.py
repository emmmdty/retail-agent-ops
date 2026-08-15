"""P2-13：`perturb_schema` 从"写好了但从没用过"接入 qualification 轨道。

`domain/environment.py` 早就实现了工具别名 + 参数顺序扰动，但全部 config 与正式
评测**零调用**，只在环境单测里被碰过。删掉是信息丢失——它恰好能回答本项目
"领域可替换"这条主张最尖锐的追问：**换一份客户的工具 schema，这套东西还能用吗？**

接入 qualification 轨道（规则策略、纯 CPU、不触碰任何被哈希的 formal 输入），
用一组对照把答案变成数字：
- 硬编码工具名的 oracle 在扰动下**全灭**；
- 从当前工具清单按参数形状解析的 adaptive oracle **不受影响**。

两者跑的是同一批任务、同一个环境、同一条 `run_episode`，差别只有"名字从哪来"。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from veritool_rl.core.agent.runner import run_episode
from veritool_rl.core.trajectory import TerminationReason
from veritool_rl.retail_ops.build.manifests import build_qualification, load_built_tasks
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
from veritool_rl.retail_ops.domain.policies import build_qualification_policy

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_REL = Path("domains/retail_ops/v1")
PERTURB_SEED = 7


@pytest.fixture(scope="module")
def _built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("schema-robustness")
    shutil.copytree(REPO_ROOT / BUNDLE_REL, root / BUNDLE_REL)
    build_qualification(root / BUNDLE_REL, 0, root / "build")
    return root


def _run(root: Path, policy_type: str, *, perturb: bool) -> list[bool]:
    bundle = load_bundle(root / BUNDLE_REL)
    tasks = list(load_built_tasks(root / "build").values())

    def make_env(current: object) -> RetailOpsEnv:
        env = RetailOpsEnv(current, bundle)  # type: ignore[arg-type]
        if perturb:
            env.perturb_schema(PERTURB_SEED)
        return env

    return [
        run_episode(task, make_env, build_qualification_policy(policy_type, task), 0).success
        for task in tasks
    ]


def test_perturbation_renames_tools_and_shuffles_parameters(_built: Path) -> None:
    """先证明扰动确实生效——否则下面的对照只是在测同一件事两遍。"""
    bundle = load_bundle(_built / BUNDLE_REL)
    task = next(iter(load_built_tasks(_built / "build").values()))
    env = RetailOpsEnv(task, bundle)

    canonical = [tool.name for tool in env.list_tools()]
    env.perturb_schema(PERTURB_SEED)
    perturbed = env.list_tools()

    assert canonical == ["get_order", "refund_order", "get_store_hours"]
    assert [tool.name for tool in perturbed] != canonical
    assert all(tool.name not in canonical for tool in perturbed)
    # 参数**键集合**不变，只是顺序与工具名变了：这正是"同一份能力换了个 schema"。
    assert [sorted(tool.parameters["properties"]) for tool in perturbed] == [
        ["order_id"],
        ["order_id", "reason"],
        ["city"],
    ]


def test_perturbation_is_deterministic_for_a_given_seed(_built: Path) -> None:
    """扰动必须可复现，否则它产生的读数无法配对比较。"""
    bundle = load_bundle(_built / BUNDLE_REL)
    task = next(iter(load_built_tasks(_built / "build").values()))

    names = []
    for _ in range(2):
        env = RetailOpsEnv(task, bundle)
        env.perturb_schema(PERTURB_SEED)
        names.append([tool.name for tool in env.list_tools()])

    assert names[0] == names[1]


def test_hardcoded_oracle_collapses_under_schema_perturbation(_built: Path) -> None:
    """硬编码工具名的策略在 schema 扰动下必须全灭——这是对照组的意义。"""
    clean = _run(_built, "oracle", perturb=False)
    perturbed = _run(_built, "oracle", perturb=True)

    assert all(clean), "未扰动时 oracle 必须全通过"
    assert not any(perturbed), "扰动后硬编码策略不应有任何成功"


def test_schema_adaptive_policy_survives_the_perturbation(_built: Path) -> None:
    """从当前工具清单解析名字的策略不受重命名影响。"""
    clean = _run(_built, "schema_adaptive", perturb=False)
    perturbed = _run(_built, "schema_adaptive", perturb=True)

    assert all(clean)
    assert all(perturbed), "adaptive 策略必须在扰动后保持全通过"


def test_adaptive_policy_fails_visibly_when_no_tool_matches(_built: Path) -> None:
    """解析不到时必须发出可见的非法调用，而不是静默换一个工具。

    静默回退是最坏的失败形态：读报告的人会以为 schema 兼容，其实是被兜住了。
    """
    from veritool_rl.core.envs.base import ToolSchema
    from veritool_rl.retail_ops.domain.policies import SchemaAdaptiveOraclePolicy

    task = next(iter(load_built_tasks(_built / "build").values()))
    policy = SchemaAdaptiveOraclePolicy(task)

    output = policy.respond(
        [],
        [
            ToolSchema(
                name="unrelated_tool",
                description="与订单无关。",
                parameters={"type": "object", "properties": {"foo": {"type": "string"}}},
            )
        ],
    )

    assert output.tool_call is not None
    assert output.tool_call.name == task.expected_calls[0].name


def test_evaluation_records_whether_the_schema_was_perturbed(tmp_path: Path) -> None:
    """扰动是评测条件的一部分，必须落进证据里，否则两次运行不可区分。"""
    from veritool_rl.retail_ops.evaluate.evaluation import EvaluationMode, evaluate_retail_ops

    shutil.copytree(REPO_ROOT / BUNDLE_REL, tmp_path / BUNDLE_REL)
    build_qualification(tmp_path / BUNDLE_REL, 0, tmp_path / "build")
    config = {
        "bundle_dir": str(BUNDLE_REL),
        "mode": "qualification",
        "policy_type": "schema_adaptive",
        "bootstrap_samples": 8,
        "parser_id": "hermes-single-call-v1",
        "budget": {"max_steps": 5},
        "perturb_schema": True,
        "guardrail": False,
            "user_simulator": False,
    }

    evidence = evaluate_retail_ops(
        bundle_dir=tmp_path / BUNDLE_REL,
        build_dir=tmp_path / "build",
        policy_type="schema_adaptive",
        config=config,
        seed=0,
        output_dir=tmp_path / "out",
        mode=EvaluationMode.QUALIFICATION,
    )

    assert evidence.metrics["schema_perturbed"] is True
    assert evidence.metrics["task_success"] == 1.0
    # 扰动后仍必须可重放：重放环境要用与运行时**相同**的扰动，否则证据自相矛盾。
    assert evidence.evidence_complete is True
    assert evidence.metrics["replayable_rate"] == 1.0


def test_perturb_schema_is_a_required_config_key(tmp_path: Path) -> None:
    """没有默认值：让"忘了写"与"故意不启用"在配置层可分辨。"""
    from veritool_rl.retail_ops.evaluate.evaluation import EvaluationMode, evaluate_retail_ops

    shutil.copytree(REPO_ROOT / BUNDLE_REL, tmp_path / BUNDLE_REL)
    build_qualification(tmp_path / BUNDLE_REL, 0, tmp_path / "build")

    with pytest.raises(ValueError, match="perturb_schema"):
        evaluate_retail_ops(
            bundle_dir=tmp_path / BUNDLE_REL,
            build_dir=tmp_path / "build",
            policy_type="oracle",
            config={
                "bundle_dir": str(BUNDLE_REL),
                "mode": "qualification",
                "policy_type": "oracle",
                "bootstrap_samples": 8,
                "parser_id": "hermes-single-call-v1",
                "budget": {"max_steps": 5},
            },
            seed=0,
            output_dir=tmp_path / "out",
            mode=EvaluationMode.QUALIFICATION,
        )


def test_unknown_tool_under_perturbation_is_still_an_invalid_call(_built: Path) -> None:
    """扰动不得把"未知工具"变成别的失败类别——taxonomy 必须保持稳定。"""
    bundle = load_bundle(_built / BUNDLE_REL)
    task = next(iter(load_built_tasks(_built / "build").values()))

    def make_env(current: object) -> RetailOpsEnv:
        env = RetailOpsEnv(current, bundle)  # type: ignore[arg-type]
        env.perturb_schema(PERTURB_SEED)
        return env

    trajectory = run_episode(task, make_env, build_qualification_policy("unknown_tool", task), 0)

    assert not trajectory.success
    assert trajectory.termination is not TerminationReason.SUCCESS
    assert any(
        step.observation is not None and step.observation.error_code == "unknown_tool"
        for step in trajectory.steps
    )
