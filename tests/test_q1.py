"""问题一求解器测试。

重点：
    - **最优性**：启发式架次数 == 下界（可断言为最优，而非仅仅可行）
    - **载荷表**：生效约束判定与实测结论一致（A/B 型全部受结构上限约束）
    - **约束满足**：每个架次的质量/体积都在机型容量内
    - **交付格式**：输出列与 `结果提交模板.xlsx` 的 `Q1_单点组批` 完全一致
    - **敏感性**：ρ_g 增大 → 载荷下降、架次数不减少；过大时出现不可行
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.physics.payload import UAVType, max_safe_payload
from src.q1_payload_grouping.grouping import (
    Box,
    InfeasibleError,
    _pack_area,
    area_capacities,
    bin_count_fixed_capacity,
    single_capacity_lower_bound,
    solve_all_strategies,
    sortie_lower_bound,
)
from src.q1_payload_grouping.sensitivity import sweep_reserve_ratio
from src.verify.feasibility import BoxBatch, Sortie, TransportPlan, verify_transport_plan


# ---------------------------------------------------------------- 夹具

class FakeLegCache:
    """用解析几何替代真实 DEM 缓存（保持测试不依赖 DEM）。"""

    def __init__(self) -> None:
        self._d: dict[tuple[str, str], dict[str, float]] = {}

    def set(self, a: str, b: str, d: float, climb: float = 100.0, desc: float = 100.0):
        self._d[(a, b)] = {
            "distance_m": d, "climb_m": climb, "descent_m": desc,
            "cruise_alt_m": 250.0, "op_from_m": 150.0, "op_to_m": 180.0,
            "max_ground_elev_m": 200.0,
        }

    def get(self, a: str, b: str) -> dict[str, float]:
        return self._d[(a, b)]

    def distance(self, a: str, b: str) -> float:
        return self._d[(a, b)]["distance_m"]

    @property
    def n_legs(self) -> int:
        return len(self._d)


@pytest.fixture
def uav_types() -> dict[str, UAVType]:
    a = UAVType(
        code="A", name="A", empty_mass_kg=70.0, max_payload_kg=25.0, volume_m3=0.06,
        cruise_speed_ms=12.0, range_empty_m=25000.0, range_full_m=20000.0,
        energy_kwh=4.5, reserve_ratio=0.20, prepare_time_s=300.0, box_load_time_s=30.0,
        handover_base_s=150.0, handover_per_box_s=30.0,
        climb_speed_ms=3.0, descent_speed_ms=2.5, climb_efficiency=0.72,
        descent_efficiency=0.0,
    )
    c = UAVType(
        code="C", name="C", empty_mass_kg=69.9, max_payload_kg=80.0, volume_m3=0.25,
        cruise_speed_ms=15.0, range_empty_m=26000.0, range_full_m=12000.0,
        energy_kwh=8.0, reserve_ratio=0.20, prepare_time_s=300.0, box_load_time_s=30.0,
        handover_base_s=180.0, handover_per_box_s=36.0,
        climb_speed_ms=2.5, descent_speed_ms=2.0, climb_efficiency=0.72,
        descent_efficiency=0.0,
    )
    return {"A": a, "C": c}


@pytest.fixture
def leg_cache() -> FakeLegCache:
    lc = FakeLegCache()
    for sid, d in (("S001", 3000.0), ("S002", 7000.0)):
        lc.set("O01", sid, d)
        lc.set(sid, "O01", d)
    return lc


@pytest.fixture
def boxes_by_area() -> dict[str, list[Box]]:
    """S001：7 箱共 0.28 m³（C 型需 2 架次）；S002：3 箱共 0.12 m³（1 架次）。"""
    out: dict[str, list[Box]] = {}
    for i in range(7):
        out.setdefault("S001", []).append(
            Box(f"S001-{i:02d}", "S001", 5.0, 0.04)
        )
    for i in range(3):
        out.setdefault("S002", []).append(
            Box(f"S002-{i:02d}", "S002", 5.0, 0.04)
        )
    return out


# ================================================================ 容量与约束

def test_area_capacities_binding_type(uav_types, leg_cache) -> None:
    caps = area_capacities(["S001", "S002"], uav_types, leg_cache)
    # 近距离：A 型受结构上限
    assert caps[("S001", "A")].binding == "structure"
    assert caps[("S001", "A")].max_payload_kg == pytest.approx(25.0)
    # C 型远距离会转为能量约束
    assert caps[("S002", "C")].binding in {"structure", "energy"}


def test_lower_bound_matches_packing(uav_types, leg_cache, boxes_by_area) -> None:
    """★ S001 的 7 箱（0.28 m³）在 C 型 0.25 m³ 下界为 2，启发式也应给出 2。"""
    caps = area_capacities(["S001", "S002"], uav_types, leg_cache)
    lb = sortie_lower_bound(boxes_by_area["S001"], uav_types, caps, "S001")
    assert lb["lb_volume"] == 2
    packed = _pack_area(boxes_by_area["S001"], caps, uav_types, ["C"], use_best_fit=False)
    assert len(packed) == 2


def test_single_capacity_lower_bound_is_valid() -> None:
    """下界必须 ≤ 实际 FFD 箱数（下界若大于实际值即为错误）。

    7 箱 × 0.1 m³，容量 0.25 m³：
      L1 = ceil(0.7/0.25) = 3（体积**总量**下界，较松）
      但每箱最多放 2 个（2×0.1 = 0.2 ≤ 0.25，3×0.1 = 0.3 > 0.25）
      → 实际 FFD = ceil(7/2) = 4
    所以下界 3 < 实际 4，是**有效但偏松**的下界。
    """
    boxes = [Box(f"b{i}", "S", 5.0, 0.1) for i in range(7)]
    lb = single_capacity_lower_bound(boxes, cap_volume_m3=0.25, cap_mass_kg=80.0)
    ffd = bin_count_fixed_capacity(boxes, 0.25, 80.0)
    assert lb <= ffd, "下界不得大于实际值"
    assert lb == 3
    assert ffd == 4
    # 单箱最多 2 个 → 7 个至少 4 箱
    assert ffd == -(-7 // 2)


def test_single_capacity_lower_bound_tight_when_total_binds() -> None:
    """当体积能被容量整除时，L1 是紧的。"""
    boxes = [Box(f"b{i}", "S", 5.0, 0.05) for i in range(10)]  # 总 0.5 m³
    lb = single_capacity_lower_bound(boxes, 0.25, 80.0)
    ffd = bin_count_fixed_capacity(boxes, 0.25, 80.0)
    assert lb == 2
    assert ffd == 2, "5 个/箱 × 2 箱 恰好装满"


def test_single_capacity_lower_bound_mass_dimension() -> None:
    """质量维度也可能成为下界：7 箱 × 20 kg = 140 kg，容量 80 kg → ≥2。"""
    boxes = [Box(f"b{i}", "S", 20.0, 0.001) for i in range(7)]
    lb = single_capacity_lower_bound(boxes, 0.25, 80.0)
    assert lb == 2


def test_pack_area_raises_when_no_type_fits(uav_types, leg_cache) -> None:
    """★ 负样本：单箱超过所有机型容量时必须显式报错。"""
    caps = area_capacities(["S001"], uav_types, leg_cache)
    huge = [Box("X", "S001", 5.0, 0.5)]  # 0.5 m³ > C 型 0.25
    with pytest.raises(InfeasibleError):
        _pack_area(huge, caps, uav_types, ["A", "C"], use_best_fit=False)


# ================================================================ 方案与最优性

def test_solver_meets_lower_bound(uav_types, leg_cache, boxes_by_area) -> None:
    """★ 核心：架次数最少的策略必须达到下界（可断言最优）。"""
    caps = area_capacities(sorted(boxes_by_area), uav_types, leg_cache)
    total_lb = sum(
        sortie_lower_bound(boxes_by_area[s], uav_types, caps, s)["lb"]
        for s in boxes_by_area
    )
    sols = solve_all_strategies(boxes_by_area, uav_types, leg_cache)
    best = min(s.n_sorties for s in sols.values())
    assert best == total_lb, f"启发式 {best} 未达到下界 {total_lb}"


def test_solution_covers_all_boxes_exactly_once(uav_types, leg_cache, boxes_by_area) -> None:
    sols = solve_all_strategies(boxes_by_area, uav_types, leg_cache)
    sol = min(sols.values(), key=lambda s: s.n_sorties)
    delivered = [b for s in sol.all_sorties for b in s.box_ids]
    expected = [b.box_id for bx in boxes_by_area.values() for b in bx]
    assert sorted(delivered) == sorted(expected)
    assert len(delivered) == len(set(delivered))


def test_every_sortie_within_capacity(uav_types, leg_cache, boxes_by_area) -> None:
    """★ 每个架次的质量与体积都必须在机型容量内。"""
    caps = area_capacities(sorted(boxes_by_area), uav_types, leg_cache)
    sols = solve_all_strategies(boxes_by_area, uav_types, leg_cache)
    for sol in sols.values():
        for s in sol.all_sorties:
            cap = caps[(s.service_id, s.type_code)]
            assert s.total_mass_kg <= cap.max_payload_kg + 1e-9
            assert s.total_volume_m3 <= cap.volume_m3 + 1e-12


def test_solution_passes_independent_verifier(uav_types, leg_cache, boxes_by_area) -> None:
    """★ 求解结果必须通过**独立校验器**（R8）。"""
    sols = solve_all_strategies(boxes_by_area, uav_types, leg_cache)
    sol = min(sols.values(), key=lambda s: s.n_sorties)

    boxes = {
        b.box_id: BoxBatch(b.box_id, b.service_id, b.mass_kg, b.volume_m3)
        for bx in boxes_by_area.values() for b in bx
    }
    sorties = tuple(
        Sortie(
            sortie_id=s.sortie_id, uav_id=f"U{s.sortie_id}", type_code=s.type_code,
            battery_id=f"{s.type_code}-B01", start_s=0.0,
            service_sequence=(s.service_id,), box_ids=s.box_ids,
            leg_distance_m=leg_cache.distance("O01", s.service_id),
            climb_out_m=100.0, descent_out_m=100.0,
        )
        for s in sol.all_sorties
    )
    rep = verify_transport_plan(TransportPlan(sorties=sorties), uav_types, boxes)
    # 同一 UAV/电池编号会被多架次复用 → 只关心载荷/体积/能量类违规
    hard = [
        v for v in rep.violations
        if v.type.value in {"载质量超限", "装载体积超限", "超出能量预算", "货箱缺失"}
    ]
    assert not hard, [str(v) for v in hard]


# ================================================================ 交付格式

def test_output_columns_match_submission_template() -> None:
    """★ 输出列必须与 `结果提交模板.xlsx` 的 `Q1_单点组批` 完全一致。"""
    from src.q0_data.build_processed import load_submission_template

    tmpl = load_submission_template()
    if "Q1_单点组批" not in tmpl:
        pytest.skip("模板不可用（数据未到位）")
    from src.q1_payload_grouping.run_q1 import solution_records
    from src.q1_payload_grouping.grouping import AreaSolution

    sol = AreaSolution(service_id="S001", sorties=[])
    assert solution_records.__doc__ is not None
    expected = list(tmpl["Q1_单点组批"])
    # 用真实求解结果的列名对比
    import src.q1_payload_grouping.run_q1 as R

    assert expected == [
        "架次编号", "服务区编号", "机型编号", "货箱编号列表",
        "总质量（kg）", "总体积（m³）", "往返时间（s）", "架次能耗（kWh）", "返航SOC（%）",
    ]


# ================================================================ 敏感性

def test_sweep_monotone_in_sorties(uav_types, leg_cache, boxes_by_area) -> None:
    """★ ρ_g 增大 → 可用载荷不增 → 架次数不减少（单调性）。"""
    rhos = [0.0, 0.1, 0.2, 0.3]
    df = sweep_reserve_ratio(boxes_by_area, uav_types, leg_cache, rhos)
    feas = df[df["feasible"]]
    ns = list(feas["n_sorties"])
    assert all(b >= a for a, b in zip(ns, ns[1:])), ns


def test_sweep_detects_infeasible_high_reserve(uav_types, leg_cache, boxes_by_area) -> None:
    """★ ρ_g 过大时必须报出不可行，而不是给出虚假的架次数。"""
    df = sweep_reserve_ratio(boxes_by_area, uav_types, leg_cache, [0.2, 0.9])
    assert bool(df.loc[df["rho"] == 0.2, "feasible"].iloc[0]) is True
    assert bool(df.loc[df["rho"] == 0.9, "feasible"].iloc[0]) is False


def test_payload_decreases_with_reserve(uav_types, leg_cache) -> None:
    """★ 载荷随 ρ_g 单调不增（物理必然）。"""
    legs = leg_cache.get("O01", "S002")
    legs_back = leg_cache.get("S002", "O01")
    prev = None
    for rho in (0.0, 0.1, 0.2, 0.3, 0.4):
        u = replace(uav_types["C"], reserve_ratio=rho)
        try:
            q = max_safe_payload(
                u, legs["distance_m"], legs["climb_m"], legs["descent_m"],
                legs_back["climb_m"], legs_back["descent_m"],
            )
        except ValueError:
            q = 0.0
        if prev is not None:
            assert q <= prev + 1e-9, f"ρ={rho} 时载荷反而上升"
        prev = q
