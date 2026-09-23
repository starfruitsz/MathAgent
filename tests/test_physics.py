"""物理层单元测试（★ 规范第 7.3 节：物理公式必须逐条锁死）。

本文件刻意**不依赖任何附件数据与 DEM**（见 docs/IMPLEMENTATION_PLAN.md 的分层解耦），
全部用构造的机型参数做解析验证。

覆盖：
    - 载荷-航程关系 L_g(q) 的端点、单调性、凸性
    - 最大安全载荷 q_max 的边界情形与能量约束紧性
    - 航段时间的三段分解与退化情形
    - 航段能耗：下降不单独计、爬升高度为 0 时无爬升能耗
    - 两阶段充电模型：端点、分段连续性、单调性
    - 电池周转可行性
"""

from __future__ import annotations

import math

import pytest

from src.physics.battery import (
    SocTimeline,
    charging_time,
    soc_after_energy,
    turnaround_feasible,
)
from src.physics.energy import (
    Segment,
    climb_energy_kwh,
    horizontal_energy_kwh,
    sortie_energy_kwh,
    segment_energy_kwh,
    segment_time_s,
)
from src.physics.payload import (
    UAVType,
    equivalent_range_m,
    max_safe_payload,
    payload_fraction,
)


# ---------------------------------------------------------------- 测试用机型

@pytest.fixture
def uav_a() -> UAVType:
    """接近附件 A 型（中轻载），但用整数便于手算。"""
    return UAVType(
        code="A",
        name="测试A",
        empty_mass_kg=70.0,
        max_payload_kg=25.0,
        volume_m3=0.06,
        cruise_speed_ms=12.0,
        range_empty_m=25000.0,
        range_full_m=20000.0,
        energy_kwh=4.5,
        reserve_ratio=0.20,
        climb_speed_ms=3.0,
        descent_speed_ms=2.5,
        climb_efficiency=0.72,
        descent_efficiency=0.0,
    )


# ================================================================ 载荷-航程

def test_equivalent_range_endpoints(uav_a: UAVType) -> None:
    """L_g(0) = L_g0（空载）；L_g(Q_g) = L_gF（满载）。"""
    assert equivalent_range_m(uav_a, 0.0) == pytest.approx(uav_a.range_empty_m)
    assert equivalent_range_m(uav_a, uav_a.max_payload_kg) == pytest.approx(
        uav_a.range_full_m
    )


def test_equivalent_range_monotone_decreasing(uav_a: UAVType) -> None:
    """载荷越大，等效航程越小（单调不增）。"""
    qs = [i * uav_a.max_payload_kg / 20 for i in range(21)]
    rs = [equivalent_range_m(uav_a, q) for q in qs]
    assert all(b <= a + 1e-9 for a, b in zip(rs, rs[1:]))


def test_equivalent_range_is_convex(uav_a: UAVType) -> None:
    """指数 3/2 > 1 → L_g(q) 是凸函数：中点值 ≥ 两端点均值。

    因为 L_g 是 -q^{3/2} 的仿射变换，凸性来自 q^{3/2} 的凸性。
    """
    q_lo, q_hi = 0.0, uav_a.max_payload_kg
    q_mid = (q_lo + q_hi) / 2
    l_lo = equivalent_range_m(uav_a, q_lo)
    l_hi = equivalent_range_m(uav_a, q_hi)
    l_mid = equivalent_range_m(uav_a, q_mid)
    assert l_mid >= (l_lo + l_hi) / 2 - 1e-9


def test_equivalent_range_exponent_is_three_halves(uav_a: UAVType) -> None:
    """显式验证指数确实是 3/2，而不是 2 或 1。"""
    q = uav_a.max_payload_kg / 4  # q/Q = 1/4
    expected = uav_a.range_empty_m - (uav_a.range_empty_m - uav_a.range_full_m) * (
        0.25 ** 1.5
    )
    assert equivalent_range_m(uav_a, q) == pytest.approx(expected)
    # 1/4^{3/2} = 1/8 = 0.125
    assert 0.25**1.5 == pytest.approx(0.125)


def test_equivalent_range_rejects_out_of_domain(uav_a: UAVType) -> None:
    with pytest.raises(ValueError):
        equivalent_range_m(uav_a, -1.0)
    with pytest.raises(ValueError):
        equivalent_range_m(uav_a, uav_a.max_payload_kg + 1e-6)


def test_payload_fraction(uav_a: UAVType) -> None:
    assert payload_fraction(uav_a, 0.0) == pytest.approx(0.0)
    assert payload_fraction(uav_a, uav_a.max_payload_kg) == pytest.approx(1.0)
    assert payload_fraction(uav_a, uav_a.max_payload_kg / 2) == pytest.approx(0.5)


# ================================================================ 最大安全载荷

def test_max_safe_payload_zero_distance(uav_a: UAVType) -> None:
    """水平距离为 0（纯垂直起降）时，结构上限 Q_g 起作用。"""
    q = max_safe_payload(uav_a, horizontal_distance_m=0.0)
    assert q == pytest.approx(uav_a.max_payload_kg, abs=1e-6)


def test_max_safe_payload_is_monotone_in_distance(uav_a: UAVType) -> None:
    """距离越远，能带的货越少。"""
    ds = [0.0, 2000.0, 5000.0, 8000.0]
    qs = [max_safe_payload(uav_a, d) for d in ds]
    assert all(b <= a + 1e-6 for a, b in zip(qs, qs[1:])), qs


def test_max_safe_payload_capped_by_structure_when_close(uav_a: UAVType) -> None:
    """近距离时**结构上限 Q_g** 起作用，而不是能量。"""
    q = max_safe_payload(uav_a, horizontal_distance_m=6000.0)
    assert q == pytest.approx(uav_a.max_payload_kg)


def test_max_safe_payload_energy_constraint_is_tight(uav_a: UAVType) -> None:
    """★ 核心不变量：反解出的 q_max 必须让能量约束取等号（除非被 Q_g 截断）。

    对测试机型 A：d ≤ 8500 m 时受结构上限约束，d ≥ 9000 m 时转为能量约束。
    这里取 9000 m 以确保能量约束**确实**是紧的。

    注意：验证时必须**传入与求解时完全相同的航段几何**，
    否则对比的是两个不同的任务（这正是本测试最初写错的地方）。
    """
    d, up, down = 9000.0, 50.0, 50.0
    q = max_safe_payload(
        uav_a,
        horizontal_distance_m=d,
        climb_out_m=up,
        descent_out_m=down,
        climb_back_m=up,
        descent_back_m=down,
    )
    assert q < uav_a.max_payload_kg, "该距离下应受能量约束而非结构上限"

    seg = Segment(distance_m=d, climb_m=up, descent_m=down)
    used = sortie_energy_kwh(uav_a, outbound=(seg, q), inbound=(seg, 0.0))
    budget = (1 - uav_a.reserve_ratio) * uav_a.energy_kwh
    assert used == pytest.approx(budget, rel=1e-9)


def test_max_safe_payload_invariant_holds_with_climb(uav_a: UAVType) -> None:
    """带爬升时，能量约束同样必须取等号（回归测试：曾因几何不一致而失效）。"""
    d, up, down = 9000.0, 120.0, 60.0
    q = max_safe_payload(
        uav_a,
        horizontal_distance_m=d,
        climb_out_m=up,
        descent_out_m=down,
        climb_back_m=up,
        descent_back_m=down,
    )
    assert 0.0 < q < uav_a.max_payload_kg
    seg = Segment(distance_m=d, climb_m=up, descent_m=down)
    used = sortie_energy_kwh(uav_a, outbound=(seg, q), inbound=(seg, 0.0))
    assert used == pytest.approx(uav_a.energy_budget_kwh, rel=1e-9)


def test_max_safe_payload_zero_at_max_round_trip_distance(uav_a: UAVType) -> None:
    """★ 往返能量记账的正确性检查。

    单点往返要飞**两个**航段（去 + 回），所以空载往返的极限单向距离是

        d_max = (1 − ρ_g) · L_g0 / 2

    而不是 L_g0。在 d_max 处 q_max 恰好为 0；再远则无可行载荷。
    """
    d_max = (1 - uav_a.reserve_ratio) * uav_a.range_empty_m / 2.0
    assert d_max == pytest.approx(10000.0)
    assert max_safe_payload(uav_a, d_max) == pytest.approx(0.0, abs=1e-6)
    # 略小于 d_max → 还能带一点点
    assert max_safe_payload(uav_a, d_max - 1.0) > 0.0


def test_max_safe_payload_exceeds_range_raises(uav_a: UAVType) -> None:
    """距离超过空载往返可达距离 → 无可行载荷，必须显式报错而不是返回负值。"""
    d_max = (1 - uav_a.reserve_ratio) * uav_a.range_empty_m / 2.0
    with pytest.raises(ValueError):
        max_safe_payload(uav_a, horizontal_distance_m=d_max * 1.5)


# ================================================================ 航段时间

def test_segment_time_pure_cruise(uav_a: UAVType) -> None:
    """爬升=下降=0 时，时间退化为纯巡航 d/v_c。"""
    d = 1200.0
    t = segment_time_s(uav_a, Segment(distance_m=d, climb_m=0.0, descent_m=0.0))
    assert t == pytest.approx(d / uav_a.cruise_speed_ms)


def test_segment_time_three_phases(uav_a: UAVType) -> None:
    """时间为爬升/巡航/下降三段之和。"""
    seg = Segment(distance_m=1000.0, climb_m=150.0, descent_m=90.0)
    expected = (
        150.0 / uav_a.climb_speed_ms
        + 1000.0 / uav_a.cruise_speed_ms
        + 90.0 / uav_a.descent_speed_ms
    )
    assert segment_time_s(uav_a, seg) == pytest.approx(expected)


def test_segment_time_zero_for_degenerate_segment(uav_a: UAVType) -> None:
    assert segment_time_s(uav_a, Segment(0.0, 0.0, 0.0)) == pytest.approx(0.0)


# ================================================================ 航段能耗

def test_climb_energy_zero_at_zero_height(uav_a: UAVType) -> None:
    """爬升高度为 0 → 爬升附加能耗为 0。"""
    assert climb_energy_kwh(uav_a, mass_kg=95.0, climb_m=0.0) == pytest.approx(0.0)


def test_climb_energy_matches_physics(uav_a: UAVType) -> None:
    """爬升能耗 = m·g·h / η（ADR-020）。

    m = 空载 70 + 载荷 25 = 95 kg，h = 100 m，η = 0.72
    E = 95 * 9.80665 * 100 / 0.72 J → kWh
    """
    e = climb_energy_kwh(uav_a, mass_kg=95.0, climb_m=100.0)
    expected = 95.0 * 9.80665 * 100.0 / 0.72 / 3.6e6
    assert e == pytest.approx(expected)
    assert e == pytest.approx(0.03594, rel=1e-3)


def test_climb_energy_scales_with_mass_and_height(uav_a: UAVType) -> None:
    e1 = climb_energy_kwh(uav_a, mass_kg=80.0, climb_m=100.0)
    assert climb_energy_kwh(uav_a, mass_kg=160.0, climb_m=100.0) == pytest.approx(2 * e1)
    assert climb_energy_kwh(uav_a, mass_kg=80.0, climb_m=200.0) == pytest.approx(2 * e1)


def test_horizontal_energy_uses_range_model(uav_a: UAVType) -> None:
    """★ ADR-021：水平能耗 = (d / L_g(q)) · E_g^use。"""
    d, q = 5000.0, 10.0
    e = horizontal_energy_kwh(uav_a, distance_m=d, payload_kg=q)
    expected = d / equivalent_range_m(uav_a, q) * uav_a.energy_kwh
    assert e == pytest.approx(expected)


def test_horizontal_energy_zero_distance(uav_a: UAVType) -> None:
    assert horizontal_energy_kwh(uav_a, distance_m=0.0, payload_kg=10.0) == pytest.approx(0.0)


def test_descent_does_not_add_energy(uav_a: UAVType) -> None:
    """★ 下降能耗效率取 0 → 下降高度不影响总能耗（题目明确）。"""
    d = 4000.0
    e_no_desc = segment_energy_kwh(
        uav_a, Segment(distance_m=d, climb_m=100.0, descent_m=0.0), payload_kg=5.0
    )
    e_with_desc = segment_energy_kwh(
        uav_a, Segment(distance_m=d, climb_m=100.0, descent_m=800.0), payload_kg=5.0
    )
    assert e_no_desc == pytest.approx(e_with_desc)


def test_segment_energy_equals_sum_of_parts(uav_a: UAVType) -> None:
    seg = Segment(distance_m=3000.0, climb_m=120.0, descent_m=60.0)
    q = 8.0
    total = segment_energy_kwh(uav_a, seg, payload_kg=q)
    parts = horizontal_energy_kwh(uav_a, seg.distance_m, q) + climb_energy_kwh(
        uav_a, uav_a.empty_mass_kg + q, seg.climb_m
    )
    assert total == pytest.approx(parts)


def test_sortie_energy_sums_both_legs(uav_a: UAVType) -> None:
    """架次能耗 = 去程（载货）+ 回程（空载）。"""
    d = 5000.0
    seg_out = Segment(distance_m=d, climb_m=100.0, descent_m=100.0)
    seg_in = Segment(distance_m=d, climb_m=100.0, descent_m=100.0)
    total = sortie_energy_kwh(uav_a, outbound=(seg_out, 10.0), inbound=(seg_in, 0.0))
    e_out = segment_energy_kwh(uav_a, seg_out, 10.0)
    e_in = segment_energy_kwh(uav_a, seg_in, 0.0)
    assert total == pytest.approx(e_out + e_in)
    # 回程空载更省
    assert e_in < e_out


def test_return_leg_must_be_empty(uav_a: UAVType) -> None:
    """回程应空载；若传入非零载荷必须报错（防止把去程载荷误用到回程）。"""
    with pytest.raises(ValueError):
        sortie_energy_kwh(
            uav_a,
            outbound=(Segment(1000.0, 50.0, 50.0), 5.0),
            inbound=(Segment(1000.0, 50.0, 50.0), 5.0),
        )


# ================================================================ 两阶段充电

def test_charging_time_endpoints() -> None:
    """s=0 → T_full；s=1 → 0。"""
    assert charging_time(soc=0.0, t_full_s=1800.0) == pytest.approx(1800.0)
    assert charging_time(soc=1.0, t_full_s=1800.0) == pytest.approx(0.0)


def test_charging_time_continuous_at_boundary() -> None:
    """★ 核心不变量：分段函数在 s = 0.90 处必须连续。"""
    t_full = 1800.0
    left = charging_time(soc=0.90 - 1e-12, t_full_s=t_full)
    right = charging_time(soc=0.90, t_full_s=t_full)
    assert left == pytest.approx(right, rel=1e-9)
    # 该点值应为 T_full * 0.35
    assert right == pytest.approx(t_full * 0.35)


def test_charging_time_phases() -> None:
    """快慢两阶段的占比：0→0.9 占 65%，0.9→1 占 35%。"""
    t_full = 1000.0
    assert charging_time(0.0, t_full) == pytest.approx(t_full)
    assert charging_time(0.9, t_full) == pytest.approx(t_full * 0.35)
    # 0 → 0.9 的耗时 = T_full - T_full*0.35 = T_full*0.65
    assert charging_time(0.0, t_full) - charging_time(0.9, t_full) == pytest.approx(
        t_full * 0.65
    )


def test_charging_time_monotone_decreasing() -> None:
    """SOC 越高，剩余充电时间越短。"""
    ts = [charging_time(s / 100, 1800.0) for s in range(101)]
    assert all(b <= a + 1e-9 for a, b in zip(ts, ts[1:]))


def test_charging_time_rejects_bad_soc() -> None:
    with pytest.raises(ValueError):
        charging_time(soc=-0.01, t_full_s=1800.0)
    with pytest.raises(ValueError):
        charging_time(soc=1.01, t_full_s=1800.0)


# ================================================================ SOC

def test_soc_after_energy() -> None:
    assert soc_after_energy(energy_used_kwh=0.0, energy_total_kwh=4.5) == pytest.approx(1.0)
    assert soc_after_energy(energy_used_kwh=4.5, energy_total_kwh=4.5) == pytest.approx(0.0)
    assert soc_after_energy(energy_used_kwh=2.25, energy_total_kwh=4.5) == pytest.approx(0.5)


def test_reserve_ratio_is_twenty_percent() -> None:
    """附件实测：返航电量下限 20%（ADR-017）。"""
    from src.common.config import DEFAULT_RESERVE_RATIO

    assert DEFAULT_RESERVE_RATIO == pytest.approx(0.20)


# ================================================================ 周转可行性

def test_turnaround_feasible_basic() -> None:
    """任务 0–600 s，回 SOC=0.5；充电至 100% 需 t_chg(0.5)。

    若下一任务在 600 + t_chg(0.5) 之后开始，则可行。
    """
    t_full = 1800.0
    tl = SocTimeline(t_full_s=t_full)
    tl.add_task(start_s=0.0, end_s=600.0, soc_end=0.5)
    t_chg = charging_time(0.5, t_full)
    assert turnaround_feasible(tl, next_start_s=600.0 + t_chg + 1.0)
    assert not turnaround_feasible(tl, next_start_s=600.0 + t_chg - 1.0)


def test_turnaround_detects_overlapping_occupancy() -> None:
    """★ 同一资源的任务占用时段不得重叠。"""
    tl = SocTimeline(t_full_s=1800.0)
    tl.add_task(start_s=0.0, end_s=600.0, soc_end=0.5)
    with pytest.raises(ValueError, match="重叠"):
        tl.add_task(start_s=300.0, end_s=900.0, soc_end=0.3)
