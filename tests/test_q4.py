"""问题四求解器测试。

重点：
    - **原子单元**：同架次的服务区必须并入同一单元（连通分量）
    - **不可行性**：若 15 区被串成 1 个分量，则只存在 K=1 一种合法分区
    - **桥接架次**：移除后分量数增加
    - **资源核算**：并行峰值、电池周转、机型与电池一致性
    - **不均衡度**：均衡方案应接近 0
"""

from __future__ import annotations

import pytest

from src.q4_partitioning.partition import (
    GroupResources,
    PartitionPlan,
    RelayRec,
    SortieRec,
    atomic_units,
    batteries_required,
    bridge_sorties,
    components,
    enumerate_partitions,
    group_resources,
    minimal_edits_for_partition,
    score_plan,
    _parallel_peak,
)


# ---------------------------------------------------------------- 夹具

def _s(sid: str, stops: tuple[str, ...], t0: float, t1: float,
       code: str = "B", energy: float = 1.0) -> SortieRec:
    return SortieRec(
        sortie_id=sid, type_code=code, uav_id=f"U-{sid}", battery_id=f"{code}-B01",
        start_s=t0, return_s=t1, stops=stops, energy_kwh=energy,
    )


ALL = ["S1", "S2", "S3", "S4", "S5"]


# ================================================================ 原子单元

def test_single_stop_sorties_are_separate_units() -> None:
    """全是单点架次 → 每个服务区各成一个原子单元。"""
    sorties = [_s("T1", ("S1",), 0, 100), _s("T2", ("S2",), 0, 100)]
    units = atomic_units(sorties)
    assert len(units) == 2
    assert {frozenset({"S1"}), frozenset({"S2"})} == set(units)


def test_multi_stop_sortie_merges_units() -> None:
    """★ 同架次的服务区必须合并为一个单元。"""
    sorties = [_s("T1", ("S1", "S2"), 0, 100)]
    units = atomic_units(sorties)
    assert units == [frozenset({"S1", "S2"})]


def test_transitive_merging() -> None:
    """S1–S2 同架次、S2–S3 同架次 → S1/S2/S3 必须同单元（传递性）。"""
    sorties = [_s("T1", ("S1", "S2"), 0, 100), _s("T2", ("S2", "S3"), 200, 300)]
    units = atomic_units(sorties)
    assert units == [frozenset({"S1", "S2", "S3"})]


def test_all_services_one_unit_blocks_partition() -> None:
    """★ 若 15 区被串成 1 个分量，则 K=2/3 都不可行。"""
    sorties = [
        _s("T1", ("S1", "S2"), 0, 100),
        _s("T2", ("S2", "S3"), 0, 100),
        _s("T3", ("S3", "S4"), 0, 100),
        _s("T4", ("S4", "S5"), 0, 100),
    ]
    units = atomic_units(sorties)
    assert len(units) == 1
    assert enumerate_partitions(units, 2) == []
    assert enumerate_partitions(units, 3) == []


def test_isolated_service_stays_own_unit() -> None:
    """只在单点架次里出现的服务区自成一单元。"""
    sorties = [_s("T1", ("S1", "S2"), 0, 100), _s("T2", ("S3",), 0, 100)]
    units = atomic_units(sorties)
    assert frozenset({"S3"}) in units
    assert frozenset({"S1", "S2"}) in units
    assert len(units) == 2


# ================================================================ 桥接架次

def test_bridge_sortie_detection() -> None:
    """★ 移除任一"桥"后分量数都会增加。

    注意：本测试的图是一条**链** S1–S2–S3–S4，其中每条边都是桥
    （移除任何一条都会断开）。因此这里断言的是"桥的集合"与
    "移除后分量数均为 2"，而不是唯一性。
    """
    sorties = [
        _s("T1", ("S1", "S2"), 0, 100),
        _s("T2", ("S3", "S4"), 0, 100),
        _s("BRIDGE", ("S2", "S3"), 0, 100),  # 连接左右两半
    ]
    assert len(components(sorties, ALL[:4])) == 1
    br = bridge_sorties(sorties, ALL[:4])
    assert {b.sortie_id for b, _ in br} == {"T1", "T2", "BRIDGE"}
    assert all(n == 2 for _, n in br)

    # 从"整条链"的角度看，只有中间的 BRIDGE 才是**最小改动点**：
    # 去掉它比去掉端点边更划算（去掉 BRIDGE 得到 2 个均衡的分量）
    _, n_after_bridge = next((b, n) for b, n in br if b.sortie_id == "BRIDGE")
    assert n_after_bridge == 2


def test_no_bridge_when_redundant_paths() -> None:
    """存在冗余路径时，单条边不是桥。"""
    sorties = [
        _s("T1", ("S1", "S2"), 0, 100),
        _s("T2", ("S2", "S3"), 0, 100),
        _s("T3", ("S1", "S3"), 0, 100),  # 形成环 → 任一条都不是桥
    ]
    assert bridge_sorties(sorties, ALL[:3]) == []


def test_minimal_edits_reaches_k() -> None:
    """★ 最小改动：去掉最少的桥接架次使分量数 ≥ k。"""
    sorties = [
        _s("T1", ("S1", "S2"), 0, 100),
        _s("T2", ("S2", "S3"), 0, 100),
        _s("T3", ("S3", "S4"), 0, 100),
    ]
    assert len(components(sorties, ALL[:4])) == 1
    removed, n = minimal_edits_for_partition(sorties, ALL[:4], 2)
    assert n >= 2 and len(removed) == 1


# ================================================================ 分区枚举

def test_enumerate_partitions_counts() -> None:
    """3 个单元分成 2 组 → S(3,2)=3 种。"""
    units = [frozenset({"S1"}), frozenset({"S2"}), frozenset({"S3"})]
    parts = enumerate_partitions(units, 2)
    assert len(parts) == 3
    for p in parts:
        assert len(p) == 2
        assert all(len(g) > 0 for g in p)
        assert set().union(*p) == {"S1", "S2", "S3"}


def test_enumerate_partitions_covers_all_and_disjoint() -> None:
    """★ 每个服务区必须且只能属于一组（并集完整、两两互斥）。"""
    units = [frozenset({"S1", "S2"}), frozenset({"S3"}), frozenset({"S4", "S5"})]
    for p in enumerate_partitions(units, 2) + enumerate_partitions(units, 3):
        flat: list[str] = []
        for g in p:
            flat.extend(sorted(g))
        assert sorted(flat) == ALL
        assert len(flat) == len(set(flat)), "不得有服务区重复出现"


def test_enumerate_rejects_k_too_large() -> None:
    units = [frozenset({"S1"})]
    assert enumerate_partitions(units, 3) == []


# ================================================================ 资源核算

def test_parallel_peak_basic() -> None:
    assert _parallel_peak([]) == 0
    assert _parallel_peak([(0, 100)]) == 1
    assert _parallel_peak([(0, 100), (0, 100)]) == 2
    assert _parallel_peak([(0, 100), (100, 200)]) == 1, "首尾相接不算重叠"
    assert _parallel_peak([(0, 100), (50, 200)]) == 2


def test_batteries_required_sequential_reuse() -> None:
    """★ 首尾相隔足够久时，同一组电池可复用 → 只需 1 组。"""
    spans = [(0.0, 1000.0), (100000.0, 101000.0)]
    socs = [0.0, 0.0]
    assert batteries_required(spans, socs, t_full_s=1800.0) == 1


def test_batteries_required_overlapping_needs_two() -> None:
    spans = [(0.0, 1000.0), (0.0, 1000.0)]
    assert batteries_required(spans, [1.0, 1.0], 1800.0) == 2


def test_batteries_required_accounts_for_charging() -> None:
    """★ 紧接使用但充电未完成 → 需要额外一组。"""
    spans = [(0.0, 1000.0), (1100.0, 2000.0)]
    # SOC=0 → 充满需 1800s，第二段在 1100s 开工时第一组还没充满 → 需 2 组
    assert batteries_required(spans, [0.0, 0.0], 1800.0) == 2
    # 若任务结束时 SOC=1（无需充电）→ 第二段可复用同一组
    assert batteries_required(spans, [1.0, 1.0], 1800.0) == 1


def test_group_resources_excludes_other_groups() -> None:
    """★ 只统计属于本组的架次。"""
    sorties = [
        _s("T1", ("S1",), 0, 100, code="A"),
        _s("T2", ("S2",), 0, 100, code="A"),
    ]
    r = group_resources("G1", ("S1",), sorties, [],
                        {"A": 4.5, "B": 4.0}, {"A": 1800.0, "B": 2400.0})
    assert r.n_sorties == 1
    assert r.uav_by_type == {"A": 1}


def test_group_resources_peak_across_time() -> None:
    """本组内的并行峰值应正确统计。"""
    sorties = [
        _s("T1", ("S1",), 0, 100, code="A"),
        _s("T2", ("S1",), 0, 100, code="A"),
        _s("T3", ("S1",), 500, 600, code="A"),
    ]
    r = group_resources("G1", ("S1",), sorties, [],
                        {"A": 4.5}, {"A": 1800.0})
    assert r.uav_by_type["A"] == 2


def test_group_resources_relay_counts_by_window() -> None:
    """中继按服务窗口统计并行峰值。"""
    sorties = [_s("T1", ("S1",), 0, 100)]
    relays = [
        RelayRec("RT1", "R01", "P01", 0, 10, 50, 60, 0.5, ("T1",)),
        RelayRec("RT2", "R02", "P02", 0, 10, 50, 60, 0.5, ("T1",)),
    ]
    r = group_resources("G1", ("S1",), sorties, relays, {"B": 4.0}, {"B": 2400.0})
    assert r.n_relay_sorties == 2
    assert r.relay_uavs == 2


# ================================================================ 方案评价

def test_imbalance_zero_for_equal_groups() -> None:
    g1 = GroupResources("G1", ("S1",), 1, 0, workload_s=1000.0)
    g2 = GroupResources("G2", ("S2",), 1, 0, workload_s=1000.0)
    p = PartitionPlan(k=2, groups=[g1, g2])
    assert p.workload_imbalance == pytest.approx(0.0)


def test_imbalance_positive_for_unequal_groups() -> None:
    g1 = GroupResources("G1", ("S1",), 1, 0, workload_s=1000.0)
    g2 = GroupResources("G2", ("S2",), 1, 0, workload_s=500.0)
    p = PartitionPlan(k=2, groups=[g1, g2])
    assert p.workload_imbalance > 0


def test_score_prefers_smaller_gap() -> None:
    """有缺口的方案应当被排在无缺口方案之后。"""
    ok = PartitionPlan(k=1, groups=[
        GroupResources("G1", ("S1",), 1, 0, uav_by_type={"A": 1},
                       battery_by_type={"A": 1}, relay_uavs=1, relay_packs=1)
    ])
    bad = PartitionPlan(k=1, groups=[
        GroupResources("G1", ("S1",), 1, 0, uav_by_type={"A": 99},
                       battery_by_type={"A": 99}, relay_uavs=99, relay_packs=99)
    ])
    inv = {"A": 4}
    bat = {"A": 6}
    rel = {"relay_uavs": 2, "relay_packs": 6}
    assert score_plan(ok, inv, bat, rel) < score_plan(bad, inv, bat, rel)
