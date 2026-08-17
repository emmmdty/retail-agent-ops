"""OOD v2 任务集的契约测试。

最要紧的一条是 **oracle 可解性**：把 `expected_calls` 在环境里执行一遍，
最终状态必须等于 `target_state`。这一条不过，整份评测测的就不是模型而是我的真值写错了——
而且会在花掉 GPU 之后才发现。
"""

from __future__ import annotations

import copy
import json
import re
import tempfile
from pathlib import Path

import pytest

from veritool_rl.core.trajectory import ExpectedDecision, TaskScenario, TaskSpec
from veritool_rl.retail_ops.build.phrasing_bank import (
    LEAKAGE_PATTERN,
    intent_index,
    load_phrasing_bank,
)
from veritool_rl.retail_ops.domain.bundle import load_bundle
from veritool_rl.retail_ops.domain.environment import RetailOpsEnv
from veritool_rl.retail_ops.domain.formal_tasks import build_formal_task_set
from veritool_rl.retail_ops.domain.ood_v2_tasks import (
    OOD_V2_DATASET_VERSION,
    OOD_V2_SCENARIOS,
    OOD_V2_TASKS_PER_SCENARIO,
    build_ood_v2_tasks,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLE_DIR = REPO_ROOT / "domains" / "retail_ops" / "v1"
_FROZEN_DATASET = "retail_ops_v1_r2_20260722"
_PRIVATE_ROOT = REPO_ROOT / "data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722"

#: 两份措辞池。bank-003 是 R7 为「换一份素材还成不成」新生成的一批，
#: 与 bank-002 零重叠。**它必须受与 bank-002 完全相同的一套契约约束**——
#: 新素材如果适用一套更松的检查，"同一个评测集换素材"这句话就是假的。
BANKS = {
    "bank-002": _PRIVATE_ROOT / "phrasing/phrasing-bank-002/phrasings.jsonl",
    "bank-003": _PRIVATE_ROOT / "phrasing/phrasing-bank-003/phrasings.jsonl",
}

#: 全部**评测**分片。bank-003 只用它的 `ood_sealed`——另外两个分片存在但不参与任何用途。
SHARDS = (("bank-002", "ood_dev"), ("bank-002", "ood_sealed"), ("bank-003", "ood_sealed"))


def _index(bank: str, partition: str):  # type: ignore[no-untyped-def]
    path = BANKS[bank]
    if not path.is_file():
        pytest.skip("措辞池是 ignored 私有产物，未同步到本机时跳过")
    return intent_index(load_phrasing_bank(path), partition)  # type: ignore[arg-type]


@pytest.mark.parametrize(("bank", "partition"), SHARDS)
def test_oracle_reaches_the_target_state(bank: str, partition: str) -> None:
    """按 gold 调用序列执行，最终状态必须等于 `target_state`。

    `refund_recovery` 的第一次 refund 会被注入的瞬时故障挡掉，第二次才成功——
    这正是 `expected_calls` 里有两次 refund 的原因。
    """
    bundle = load_bundle(BUNDLE_DIR)
    tasks = build_ood_v2_tasks(_index(bank, partition))
    for task in tasks:
        env = RetailOpsEnv(task, bundle)
        for call in task.expected_calls:
            env.execute_tool(call.name, call.arguments)
        # INFORM / DENY 两类的成功条件包含「给出最终答复」——查完不说话不算完成。
        env.record_final_response("已按订单实际状态给出结论。")
        assert env.verify_final_state() == 1.0, (
            f"{task.metadata['ood_category']} 任务 {task.task_id[:8]} 的 gold 序列没有到达目标状态"
        )
        assert env.check_policy() == [], (
            f"{task.metadata['ood_category']} 任务 {task.task_id[:8]} 的 gold 序列触发了政策违规"
        )


@pytest.mark.parametrize(("bank", "partition"), SHARDS)
def test_deny_scenarios_must_not_change_state(bank: str, partition: str) -> None:
    """拒绝类的 `target_state` 必须与 `initial_state` 相同——正确行为是不动状态。"""
    tasks = build_ood_v2_tasks(_index(bank, partition))
    for task in tasks:
        if task.expected_decision in (ExpectedDecision.DENY, ExpectedDecision.INFORM):
            assert task.target_state == task.initial_state, task.metadata["ood_category"]


@pytest.mark.parametrize(("bank", "partition"), SHARDS)
def test_six_scenarios_ten_each(bank: str, partition: str) -> None:
    """六个场景同时在场，是为了让「见谁都退款」这条捷径当场暴露。"""
    tasks = build_ood_v2_tasks(_index(bank, partition))
    counts: dict[str, int] = {}
    for task in tasks:
        counts[str(task.metadata["ood_category"])] = (
            counts.get(str(task.metadata["ood_category"]), 0) + 1
        )
    assert counts == {scenario.value: OOD_V2_TASKS_PER_SCENARIO for scenario in OOD_V2_SCENARIOS}


@pytest.mark.parametrize(("bank", "partition"), SHARDS)
def test_no_user_request_leaks_the_order_state(bank: str, partition: str) -> None:
    """顾客说破订单状态 = 不查订单也能猜对。整份评测会因此变成读理解。"""
    for task in build_ood_v2_tasks(_index(bank, partition)):
        assert LEAKAGE_PATTERN.search(task.user_request) is None, task.user_request


@pytest.mark.parametrize(("bank", "partition"), SHARDS)
def test_generation_is_deterministic(bank: str, partition: str) -> None:
    first = build_ood_v2_tasks(_index(bank, partition))
    second = build_ood_v2_tasks(_index(bank, partition))
    assert [task.model_dump(mode="json") for task in first] == [
        task.model_dump(mode="json") for task in second
    ]


def test_dev_and_sealed_share_no_phrasing() -> None:
    """两个评测分片逐条互斥——否则「只观测一次」的那一份早就被看过了。"""
    dev = {
        task.metadata["phrasing_id"] for task in build_ood_v2_tasks(_index("bank-002", "ood_dev"))
    }
    sealed = {
        task.metadata["phrasing_id"]
        for task in build_ood_v2_tasks(_index("bank-002", "ood_sealed"))
    }
    assert dev & sealed == set()


def test_evaluation_sets_never_use_the_training_partition() -> None:
    """拿训练增强用过的措辞当评测集，测的是有没有背下训练数据。

    取 `train_aug` 的**全部意图**——早期版本只取了 `refund_request` 一个，
    那样 `status_inquiry` 与 `refund_request_retry` 的重叠会漏检。
    """
    for bank in BANKS:
        train_index = _index(bank, "train_aug")
        train = {record.phrasing_id for bucket in train_index.values() for record in bucket}
        assert len(train) > 100, f"{bank} 的 train_aug 分片过小，这条断言会变得没有意义"
        for shard_bank, partition in SHARDS:
            if shard_bank != bank:
                continue
            used = {
                task.metadata["phrasing_id"] for task in build_ood_v2_tasks(_index(bank, partition))
            }
            assert used, (bank, partition)
            assert used & train == set(), (bank, partition)


def test_no_evaluation_phrasing_appears_in_the_actual_training_file() -> None:
    """最强的一条：直接比对**真实训练文件**，而不是比对分片。

    分片互斥是「构造上应该互斥」，这条是「实际写进 sft.jsonl 的那些句子里，
    确实没有一句是评测集用的」。两者的区别在于：前者信任导出流水线没写错，
    后者不信任任何东西，直接读产物。
    """
    sft_path = (
        REPO_ROOT
        / "data/private/retail_ops/v1/r2/retail_ops_v1_r2_20260722"
        / "train-export/train-export-007/sft.jsonl"
    )
    if not sft_path.is_file():
        pytest.skip("训练集是 ignored 私有产物，未同步到本机时跳过")

    trained_requests: set[str] = set()
    for line in sft_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        user = next(m for m in row["messages"] if m["role"] == "user")
        # 去掉订单号，只留说法本身——订单号本来就每条不同
        trained_requests.add(re.sub(r"O-[A-Z0-9]+", "<OID>", user["content"]))

    assert len(trained_requests) > 100, "训练集里的说法太少，这条断言会变得没有意义"

    for bank, partition in SHARDS:
        for task in build_ood_v2_tasks(_index(bank, partition)):
            normalized = re.sub(r"O-[A-Z0-9]+", "<OID>", task.user_request)
            assert normalized not in trained_requests, (
                f"{bank}/{partition} 的这句话在真实训练文件里出现过：{normalized}"
            )


@pytest.mark.parametrize(("bank", "partition"), SHARDS)
def test_only_real_tools_appear_in_gold_calls(bank: str, partition: str) -> None:
    bundle = load_bundle(BUNDLE_DIR)
    allowed = {tool.name for tool in bundle.tools}
    for task in build_ood_v2_tasks(_index(bank, partition)):
        assert {call.name for call in task.expected_calls} <= allowed


@pytest.mark.parametrize(("bank", "partition"), SHARDS)
def test_the_state_space_matches_the_frozen_contract(bank: str, partition: str) -> None:
    """状态空间必须与冻结契约同宽——否则「唯一自变量是说法」这句话是假的。

    2026-08-17 的外部审阅发现第一版在三个维度上都更窄：每条状态只有 1 个订单
    （冻结集合 1–5）、期限余量只有 ±6（冻结集合 7 种）、订单状态只有 3 种
    （冻结集合 7 种）。也就是说那个评测集**更容易**，而四个文件都写着
    「业务逻辑完全相同，唯一自变量是顾客怎么说」。

    这条测试**直接构造冻结任务集来比对**，不比对写死的清单——
    被它替换掉的旧测试叫 `test_the_business_contract_matches_the_frozen_one`，
    名字承诺了这件事，实现却只是抽一条样本看几个符号，正是它漏掉了这个缺陷。
    """
    # 下限取 **train ∪ dev ∪ holdout** 的全集，不是 dev 一份。
    # 外部审阅第四轮指出：只拿 dev 当下限，一个退回到「只覆盖 dev 那 4 种状态」的
    # 回归会通过一个名字写着「冻结契约」的测试。契约是全集，下限就该是全集。
    task_set = build_formal_task_set(_FROZEN_DATASET, 0)
    frozen = [
        record.task
        for split in (task_set.train, task_set.dev, task_set.holdout)
        for record in split
    ]
    ood = build_ood_v2_tasks(_index(bank, partition))

    def order_counts(tasks: list[TaskSpec]) -> set[int]:
        return {len(task.initial_state["orders"]) for task in tasks}

    def margins(tasks: list[TaskSpec]) -> set[int]:
        return {
            order["refund_deadline"] - task.initial_state["current_day"]
            for task in tasks
            for order in task.initial_state["orders"].values()
        }

    def statuses(tasks: list[TaskSpec]) -> set[str]:
        return {
            str(order.get("status"))
            for task in tasks
            for order in task.initial_state["orders"].values()
        }

    # 干扰订单：冻结集合里 1–5 都出现，OOD 必须同样覆盖，
    # 否则「退错订单」这一整类失败模式在结构上测不出来。
    assert order_counts(ood) >= order_counts(frozen), (
        f"{partition} 的订单数覆盖窄于冻结集合：{order_counts(ood)} vs {order_counts(frozen)}"
    )
    assert margins(ood) >= margins(frozen), (
        f"{partition} 的期限余量覆盖窄于冻结集合：{sorted(margins(ood))}"
    )
    assert statuses(ood) >= statuses(frozen), (
        f"{partition} 的订单状态覆盖窄于冻结集合：{sorted(statuses(ood))}"
    )


@pytest.mark.parametrize(("bank", "partition"), SHARDS)
def test_the_per_scenario_semantics_match_the_frozen_contract(bank: str, partition: str) -> None:
    """逐场景核对语义形状，确认 v2 改的是说法而不是任务。"""
    tasks: dict[str, list[TaskSpec]] = {}
    for task in build_ood_v2_tasks(_index(bank, partition)):
        tasks.setdefault(str(task.metadata["ood_category"]), []).append(task)

    def primary(task: TaskSpec) -> dict:
        return task.initial_state["orders"][task.metadata["order_id"]]

    for task in tasks[TaskScenario.REFUND_ELIGIBLE.value]:
        assert primary(task)["refund_status"] == "none"
        assert primary(task)["customer_id"] == task.initial_state["customer_id"]
    for task in tasks[TaskScenario.REFUND_DENIED_DUPLICATE.value]:
        assert primary(task)["refund_status"] == "refunded"
    for task in tasks[TaskScenario.REFUND_DENIED_WINDOW.value]:
        assert primary(task)["refund_deadline"] < task.initial_state["current_day"]
    for task in tasks[TaskScenario.REFUND_DENIED_OWNERSHIP.value]:
        assert primary(task)["customer_id"] != task.initial_state["customer_id"]
    for task in tasks[TaskScenario.REFUND_RECOVERY.value]:
        assert task.transient_failures == {"refund_order": 1}


@pytest.mark.parametrize(("bank", "partition"), SHARDS)
def test_user_requests_are_distinct_within_a_set(bank: str, partition: str) -> None:
    tasks = build_ood_v2_tasks(_index(bank, partition))
    requests = {task.user_request for task in tasks}
    assert len(requests) == len(tasks)


def test_the_built_artifacts_match_the_generator() -> None:
    """已落盘的任务集必须与当前代码重算的结果**逐字节**一致。

    早期版本只比 `manifest.task_ids`——而 `task_id` 是
    `sha256(f"oodv2:{seed}:{scenario}:{index}")`，**只依赖位置**，
    不依赖措辞池、不依赖请求文本、不依赖状态。证据：退役的窄状态空间版本与
    现在的宽版本 `task_ids` **完全相同**。那条断言什么都没验证，
    而且它还指向已退役的 `ood-v2/` 目录，加载一份陈旧 manifest 然后通过。
    （2026-08-17 外部审阅第四轮抓到，与它上一轮抓到的是同一个失败模式。）

    现在比的是 `tasks_file_sha256`——那个哈希覆盖每一条任务的全部内容。
    """
    import hashlib

    from veritool_rl.core.artifacts import write_jsonl
    from veritool_rl.retail_ops.build.ood_manifests import load_ood_manifest

    for partition, name in (("ood_dev", "dev"), ("ood_sealed", "sealed")):
        manifest_path = REPO_ROOT / f"reports/retail_ops/v1/ood-v2.1/{name}/tasks/manifest.json"
        if not manifest_path.is_file():
            pytest.skip("OOD v2.1 产物是 ignored 运行产物，未生成时跳过")
        manifest = load_ood_manifest(manifest_path)
        rebuilt = build_ood_v2_tasks(_index("bank-002", partition))

        assert manifest.task_ids == [task.task_id for task in rebuilt]
        assert manifest.dataset_version == OOD_V2_DATASET_VERSION

        # 逐条内容哈希：把重算结果按同一套写入器落到临时文件再比
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.jsonl"
            write_jsonl(path, (task.model_dump(mode="json") for task in rebuilt))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == manifest.tasks_file_sha256, (
            f"{name} 的落盘任务集与当前代码重算结果不一致——"
            f"manifest 声称 {manifest.tasks_file_sha256[:16]}…，重算得到 {digest[:16]}…"
        )


def test_recovery_target_state_is_refunded() -> None:
    """`refund_recovery` 的正确终局是退款成功，不是「试过了就算」。"""
    tasks = build_ood_v2_tasks(_index("bank-002", "ood_dev"))
    recovery = next(
        task
        for task in tasks
        if task.metadata["ood_category"] == TaskScenario.REFUND_RECOVERY.value
    )
    target_order = next(iter(recovery.target_state["orders"].values()))
    assert target_order["refund_status"] == "refunded"
    assert copy.deepcopy(recovery.initial_state) != recovery.target_state


def test_the_dataset_version_distinguishes_v1_from_v2() -> None:
    """两个数据集必须有不同的版本号，否则它们的读数在同一张表里不可区分。

    此前 `dataset_version` 被写死成 v1 的字面量，于是 OOD v2 的报告也声称属于
    `retail_ops_ood_v1_20260815`——v1 的 0.8667 与 v2 的 1.0000 挂着同一个版本号，
    恰好违反项目自己的配对前提。2026-08-17 外部审阅指出后修正。
    """
    from veritool_rl.retail_ops.build.ood_manifests import OodTaskManifest, load_ood_manifest
    from veritool_rl.retail_ops.domain.ood_tasks import OOD_DATASET_VERSION
    from veritool_rl.retail_ops.domain.ood_v2_tasks import OOD_V2_DATASET_VERSION

    assert OOD_DATASET_VERSION != OOD_V2_DATASET_VERSION
    allowed = OodTaskManifest.model_fields["dataset_version"].annotation
    assert OOD_DATASET_VERSION in str(allowed)
    assert OOD_V2_DATASET_VERSION in str(allowed)

    manifest_path = REPO_ROOT / "reports/retail_ops/v1/ood-v2.1/sealed/tasks/manifest.json"
    if not manifest_path.is_file():
        pytest.skip("OOD v2.1 产物是 ignored 运行产物，未生成时跳过")
    assert load_ood_manifest(manifest_path).dataset_version == OOD_V2_DATASET_VERSION
