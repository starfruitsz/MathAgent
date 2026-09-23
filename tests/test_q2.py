"""问题二求解器测试。

重点：
    - **多点载荷递减**：含爬升时逐段载荷下降使能耗单调下降（与直觉相反但正确）
    - **前缀容量校验**：任一前缀超标即不可行
    - **两阶段充电**：充满时间与 SOC 一致（与 physics 层同源）
    - **资源不重叠**：同机型的无人机与电池占用时段不交叉
    - **时限不可行性下界**：前 60 分钟内可完成的架次数受机队与充电时间限制
"""

from __future__ import annotations

import math

import pytest

from src.physics.battery import charging_time
from src.physics.leg_cache import LegCache
from src.physics.payload import UAVType
from src.q1_payload_grouping.grouping import Box
from src.q2_transport_schedule.models import (
    SortiePlan,
    best_stop_order,
    evaluate_sortie,
    prefix_feasible,
)
from src.q2_transport_schedule.schedule import (
    ResourcePool,
    build_pools,
    schedule_dispatch,
)
from src.q2_transport_schedule.solver import Deadline, clear_caches, construct


# ---------------------------------------------------------------- 夹具

def _leg_cache() -> LegCache:
    """构造 4 个服务区的解析航段缓存（不依赖真实 DEM）。"""
    import pandas as pd

    rows = []
    geo = {
        ("O01", "S1"): (3000.0, 100.0, 100.0),
        ("S1", "O01"): (3000.0, 100.0, 100.0),
        ("O01", "S2"): (3500.0, 150.0, 150.0),
        ("S2", "O01"): (3500.0, 150.0, 150.0),
        ("O01", "S3"): (20000.0, 400.0, 400.0),
        ("S3", "O01"): (20000.0, 400.0, 400.0),
        ("O01", "S4"): (1000.0, 50.0, 50.0),
        ("S4", "O01"): (1000.0, 50.0, 50.0),
        ("S1", "S2"): (2000.0, 80.0, 80.0),
        ("S2", "S1"): (2000.0, 80.0, 80.0),
        ("S1", "S4"): (2500.0, 60.0, 60.0),
        ("S4", "S1"): (2500.0, 60.0, 60.0),
        ("S2", "S4"): (3000.0, 70.0, 70.0),
        ("S4", "S2"): (3000.0, 70.0, 70.0),
        ("S1", "S3"): (18000.0, 300.0, 300.0),
        ("S3", "S1"): (18000.0, 300.0, 300.0),
        ("S2", "S3"): (17500.0, 320.0, 320.0),
        ("S3", "S2"): (17500.0, 320.0, 320.0),
        ("S3", "S4"): (19500.0, 350.0, 350.0),
        ("S4", "S3"): (19500.0, 350.0, 350.0),
    }
    for (a, b), (d, cu, cd) in geo.items():
        rows.append({
            "from_id": a, "to_id": b, "distance_m": d, "climb_m": cu, "descent_m": cd,
            "cruise_alt_m": 300.0, "op_from_m": 150.0, "op_to_m": 180.0,
            "max_ground_elev_m": 250.0,
        })
    return LegCache(pd.DataFrame(rows), "test", 30.0)


@pytest.fixture
def uav_b() -> UAVType:
    return UAVType(
        code="B", name="B", empty_mass_kg=65.0, max_payload_kg=30.0, volume_m3=0.073,
        cruise_speed_ms=15.0, range_empty_m=28000.0, range_full_m=16000.0,
        energy_kwh=4.0, reserve_ratio=0.20, prepare_time_s=300.0, box_load_time_s=30.0,
        handover_base_s=150.0, handover_per_box_s=30.0,
        climb_speed_ms=3.0, descent_speed_ms=2.5, climb_efficiency=0.72,
        descent_efficiency=0.0,
    )


@pytest.fixture
def lc() -> LegCache:
    return _leg_cache()


# ================================================================ 多点载荷递减

def test_prefix_feasible_rejects_oversize_total(uav_b: UAVType) -> None:
    """总质量超限时不可行。"""
    ok, why = prefix_feasible(
        ("S1", "S2"), {"S1": 20.0, "S2": 20.0}, {"S1": 0.01, "S2": 0.01}, uav_b
    )
    assert not ok and "载荷" in why


def test_prefix_feasible_allows_decreasing_load(uav_b: UAVType) -> None:
    """接近容量但总量不超时可行。"""
    ok, _ = prefix_feasible(
        ("S1", "S2"), {"S1": 15.0, "S2": 14.0}, {"S1": 0.03, "S2": 0.03}, uav_b
    )
    assert ok


def test_prefix_feasible_checks_volume(uav_b: UAVType) -> None:
    ok, why = prefix_feasible(
        ("S1",), {"S1": 1.0}, {"S1": 0.2}, uav_b
    )
    assert not ok and "体积" in why


def test_multi_stop_energy_lower_than_sum_of_singles(uav_b: UAVType, lc: LegCache) -> None:
    """★ 多点在**含爬升**时能耗更低：后续航段载荷递减且无需降回作业高度。

    这是"合并架次省往返"的量化依据。
    """
    m = {"S1": 10.0, "S4": 10.0}
    v = {"S1": 0.02, "S4": 0.02}
    multi = evaluate_sortie(
        SortiePlan("B", ("S4", "S1"), {"S4": ("a",), "S1": ("b",)}),
        uav_b, lc, m, v,
    )
    single_s1 = evaluate_sortie(
        SortiePlan("B", ("S1",), {"S1": ("b",)}), uav_b, lc, {"S1": 10.0}, {"S1": 0.02}
    )
    single_s4 = evaluate_sortie(
        SortiePlan("B", ("S4",), {"S4": ("a",)}), uav_b, lc, {"S4": 10.0}, {"S4": 0.02}
    )
    assert multi.feasible and single_s1.feasible and single_s4.feasible
    assert multi.energy_kwh < single_s1.energy_kwh + single_s4.energy_kwh


def test_best_stop_order_picks_cheaper_sequence(uav_b: UAVType, lc: LegCache) -> None:
    """选序应给出比"先远后近"更省的顺序。"""
    m = {"S1": 5.0, "S4": 5.0}
    v = {"S1": 0.01, "S4": 0.01}
    order, ev = best_stop_order(("S1", "S4"), uav_b, lc, m, v)
    assert ev.feasible
    bad = evaluate_sortie(
        SortiePlan("B", ("S4", "S1"), {"S4": (), "S1": ()}), uav_b, lc, m, v
    )
    assert ev.energy_kwh <= bad.energy_kwh + 1e-9


def test_return_soc_matches_energy(uav_b: UAVType, lc: LegCache) -> None:
    ev = evaluate_sortie(
        SortiePlan("B", ("S1",), {"S1": ()}), uav_b, lc, {"S1": 10.0}, {"S1": 0.02}
    )
    assert ev.return_soc == pytest.approx(1.0 - ev.energy_kwh / uav_b.energy_kwh)


def test_far_area_infeasible_for_small_type(uav_b: UAVType, lc: LegCache) -> None:
    """★ S3 距离 20 km，B 型往返 40 km ≫ 可达距离，必须判为不可行。"""
    ev = evaluate_sortie(
        SortiePlan("B", ("S3",), {"S3": ()}), uav_b, lc, {"S3": 5.0}, {"S3": 0.01}
    )
    assert not ev.feasible


# ================================================================ 资源周转

def test_battery_charge_window_respects_two_phase_model() -> None:
    pool = ResourcePool(["U1"], ["B-B01"], t_full_s=2400.0)
    pool.occupy("U1", "B-B01", 0.0, 1000.0, soc_end=0.5)
    b = pool.batteries["B-B01"]
    expected = 1000.0 + charging_time(0.5, 2400.0)
    assert b.available_at_s == pytest.approx(expected)


def test_pool_rejects_overlap() -> None:
    """★ 同一资源的任务占用不得重叠。"""
    pool = ResourcePool(["U1"], ["B-B01"], t_full_s=2400.0)
    pool.occupy("U1", "B-B01", 0.0, 1000.0, 0.5)
    with pytest.raises(ValueError):
        pool.occupy("U1", "B-B01", 500.0, 1500.0, 0.5)


def test_build_pools_naming() -> None:
    pools = build_pools({"A": ["U01", "U02"]}, {"A": 3}, {"A": 1800.0})
    assert set(pools["A"].batteries) == {"A-B01", "A-B02", "A-B03"}


# ================================================================ 调度

def test_dispatch_no_resource_overlap(uav_b: UAVType, lc: LegCache) -> None:
    """★ 调度结果中同一无人机/电池的占用时段不得重叠。"""
    boxes = {f"b{i}": Box(f"b{i}", "S1", 5.0, 0.01) for i in range(6)}
    deadlines = {f"b{i}": Deadline(expected_s=1e9) for i in range(6)}
    clear_caches()
    cands = construct(list(boxes.values()), {"B": uav_b}, lc, deadlines, max_group=1)
    plans = [c.plan for c in cands if c.plan.stops]
    pools = build_pools({"B": ["U1", "U2"]}, {"B": 2}, {"B": 2400.0})
    sched = schedule_dispatch(plans, {"B": uav_b}, lc, boxes, pools)
    for attr in ("uav_id", "battery_id"):
        seen: dict[str, list[tuple[float, float]]] = {}
        for s in sched:
            seen.setdefault(getattr(s, attr), []).append((s.start_s, s.return_s))
        for rid, spans in seen.items():
            spans.sort()
            for a, b in zip(spans, spans[1:]):
                assert b[0] >= a[1] - 1e-9, f"{rid} 占用重叠：{spans}"


def test_dispatch_uses_all_boxes_once(uav_b: UAVType, lc: LegCache) -> None:
    boxes = [Box(f"b{i}", "S4", 5.0, 0.01) for i in range(5)]
    deadlines = {b.box_id: Deadline(expected_s=1e9) for b in boxes}
    clear_caches()
    cands = construct(boxes, {"B": uav_b}, lc, deadlines, max_group=1)
    plans = [c.plan for c in cands if c.plan.stops]
    pools = build_pools({"B": ["U1"]}, {"B": 3}, {"B": 2400.0})
    sched = schedule_dispatch(plans, {"B": uav_b}, lc,
                              {b.box_id: b for b in boxes}, pools)
    delivered = [x for s in sched for st in s.stops for x in s.boxes_by_stop.get(st, ())]
    assert sorted(delivered) == sorted(b.box_id for b in boxes)
    assert len(delivered) == len(set(delivered))


# ================================================================ 时限下界

def test_first_hour_sortie_capacity_bound(uav_b: UAVType) -> None:
    """★ 资源是首批时限的硬瓶颈（本测试固化这一结论）。

    单架次典型时长 ≈ 准备 + 装载 + 往返 + 交接。
    若往返 6 km、3 箱，则时长约 20 min；电池充满需 40 min。
    因此"第一小时"内可完成的架次数由 **无人机数** 与 **电池数** 共同限制。

    这里验证算术本身：同一组电池在前 1 小时内最多支撑
    `1 + floor(3600 / t_full_effective)` 次使用（首次无需充电）。
    """
    t_full = 2400.0
    duration = 1200.0  # 20 min
    # 一次任务 + 充满，才算"能再用一次"
    cycle = duration + t_full
    uses = 1 + math.floor((3600.0 - duration) / cycle) if 3600.0 >= duration else 0
    assert uses == 1, "前 1 小时同一组电池只能支撑 1 次任务"

    # 4 组电池 + 2 架无人机 → 前 1 小时最多 4 架次（电池比无人机更紧 → 取 min）
    n_uav, n_bat = 2, 4
    max_sorties_first_hour = min(n_uav, n_bat) * uses
    assert max_sorties_first_hour == 2
