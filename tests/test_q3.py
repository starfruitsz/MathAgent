"""问题三求解器测试。

重点：
    - **轨迹采样**覆盖爬升/巡航/下降/投送四个阶段
    - **单点覆盖判定**：候选点需同时满足接入段与回传段
    - **中继时间与能耗**口径（准备/建链/悬停服务/返航）
    - **分段覆盖**：单点不够时多架中继接力仍可被判定为已保障
    - **校验器**能识别"中断未被覆盖"
"""

from __future__ import annotations

import math

import pytest

from src.comms.link import DEFAULT_PARAMS
from src.comms.los import has_terrain_obstruction
from src.geo.dem import AnalyticElevationProvider
from src.physics.leg_cache import LegCache
from src.physics.payload import UAVType
from src.q3_comms_relay.coverage import (
    Sample,
    _point_covered,
    covers_all,
    outage_samples,
    sample_trajectory,
)
from src.q3_comms_relay.relay import RelaySpec, evaluate_relay_sortie
from src.verify.feasibility import (
    BoxBatch,
    Leg,
    RelayAssignment,
    Sortie,
    TransportPlan,
    ViolationType,
    verify_transport_plan,
)


# ---------------------------------------------------------------- 夹具

def _lc() -> LegCache:
    import pandas as pd

    geo = {
        ("O01", "S1"): (4000.0, 120.0, 120.0),
        ("S1", "O01"): (4000.0, 120.0, 120.0),
        ("O01", "S2"): (9000.0, 300.0, 300.0),
        ("S2", "O01"): (9000.0, 300.0, 300.0),
        ("S1", "S2"): (5000.0, 150.0, 150.0),
        ("S2", "S1"): (5000.0, 150.0, 150.0),
    }
    rows = [
        {"from_id": a, "to_id": b, "distance_m": d, "climb_m": cu, "descent_m": cd,
         "cruise_alt_m": 400.0, "op_from_m": 150.0, "op_to_m": 150.0,
         "max_ground_elev_m": 350.0}
        for (a, b), (d, cu, cd) in geo.items()
    ]
    return LegCache(pd.DataFrame(rows), "test", 30.0)


@pytest.fixture
def lc() -> LegCache:
    return _lc()


@pytest.fixture
def uav() -> UAVType:
    return UAVType(
        code="B", name="B", empty_mass_kg=65.0, max_payload_kg=30.0, volume_m3=0.073,
        cruise_speed_ms=15.0, range_empty_m=28000.0, range_full_m=16000.0,
        energy_kwh=4.0, reserve_ratio=0.20, prepare_time_s=300.0, box_load_time_s=30.0,
        handover_base_s=150.0, handover_per_box_s=30.0,
        climb_speed_ms=3.0, descent_speed_ms=2.5, climb_efficiency=0.72,
        descent_efficiency=0.0,
    )


NODES = {
    "O01": (109.230852, 23.008509),
    "S1": (109.243232, 23.033593),
    "S2": (109.283136, 23.054464),
}


# ================================================================ 轨迹采样

def test_trajectory_covers_all_four_phases(lc: LegCache, uav: UAVType) -> None:
    """★ 题目要求覆盖爬升/巡航/下降/投送四个阶段。"""
    smp = sample_trajectory(("S1",), {"S1": 3}, uav, lc, NODES, 0.0, dt_s=5.0)
    phases = {s.phase for s in smp}
    assert phases == {"climb", "cruise", "descent", "handover"}


def test_trajectory_starts_with_prepare_and_load(lc: LegCache, uav: UAVType) -> None:
    """首个采样点不早于 准备 + 装载。"""
    smp = sample_trajectory(("S1",), {"S1": 3}, uav, lc, NODES, 0.0, dt_s=5.0)
    earliest = uav.prepare_time_s + uav.box_load_time_s * 3
    assert smp[0].t_s >= earliest - 1e-9


def test_trajectory_is_time_sorted(lc: LegCache, uav: UAVType) -> None:
    smp = sample_trajectory(("S1", "S2"), {"S1": 2, "S2": 2}, uav, lc, NODES, 0.0, dt_s=5.0)
    ts = [s.t_s for s in smp]
    assert ts == sorted(ts)


def test_trajectory_altitude_profile(lc: LegCache, uav: UAVType) -> None:
    """爬升递增、巡航恒定、下降递减，且三段**首尾相接**（无高度跳变）。

    ★ 这是一个真实修过的 bug：早期实现直接取 `leg_cache` 的 climb/descent，
      与 `cruise_alt_m` 数值上不自洽，导致"爬升末值 ≠ 巡航值"的高度跳变。
      现在剖面按端点作业高度与巡航海拔之差构造，天然连续。
    """
    smp = sample_trajectory(("S1",), {"S1": 1}, uav, lc, NODES, 0.0, dt_s=5.0)
    # 去程与回程各有一段爬升/下降，因此取**第一段连续块**做单调性检查
    climb_all = [s.alt_m for s in smp if s.phase == "climb"]
    climb: list[float] = []
    for x in climb_all:
        if climb and x < climb[-1] - 1e-9:
            break
        climb.append(x)
    descent_all = [s.alt_m for s in smp if s.phase == "descent"]
    descent: list[float] = []
    for x in descent_all:
        if descent and x > descent[-1] + 1e-9:
            break
        descent.append(x)
    cruise = [s.alt_m for s in smp if s.phase == "cruise"]

    assert all(b >= a - 1e-9 for a, b in zip(climb, climb[1:])), "爬升应单调不减"
    assert all(a >= b - 1e-9 for a, b in zip(descent, descent[1:])), "下降应单调不增"
    assert len(set(cruise)) == 1 and cruise[0] == pytest.approx(400.0)

    # ★ 连续性：爬升 → 巡航 → 下降 三段交界处必须无缝（无高度跳变）
    assert climb[-1] == pytest.approx(cruise[0], abs=1e-6)
    assert descent[0] == pytest.approx(cruise[0], abs=1e-6)
    assert climb[0] == pytest.approx(150.0, abs=1e-6)
    assert descent[-1] == pytest.approx(150.0, abs=1e-6)
    # 两段爬升（去程 + 回程）
    assert len(climb_all) == 2 * len(climb)


def test_finer_dt_gives_more_samples(lc: LegCache, uav: UAVType) -> None:
    a = sample_trajectory(("S1",), {"S1": 1}, uav, lc, NODES, 0.0, dt_s=10.0)
    b = sample_trajectory(("S1",), {"S1": 1}, uav, lc, NODES, 0.0, dt_s=2.0)
    assert len(b) > len(a)


# ================================================================ 覆盖判定

FLAT = AnalyticElevationProvider(base=100.0, _bounds=(109.0, 22.85, 109.5, 23.25))


def test_covers_all_true_for_central_relay() -> None:
    """位于中点的中继应能覆盖附近的样本。"""
    targets = [
        Sample(0.0, 109.235, 23.015, 300.0, "cruise"),
        Sample(10.0, 109.238, 23.018, 300.0, "cruise"),
    ]
    gw = (109.230852, 23.008509, 148.0)
    relay = (109.2365, 23.0165, 400.0)
    assert covers_all(targets, DEFAULT_PARAMS, FLAT, gw, relay, los_step_m=50.0)


def test_covers_all_false_when_too_far() -> None:
    """★ 中继离样本太远（超接入段门限）时不可用。"""
    targets = [Sample(0.0, 109.235, 23.015, 300.0, "cruise")]
    gw = (109.230852, 23.008509, 148.0)
    far_relay = (109.40, 23.20, 400.0)  # 约 20 km 之外
    assert not covers_all(targets, DEFAULT_PARAMS, FLAT, gw, far_relay, los_step_m=200.0)


def test_covers_all_false_when_backhaul_blocked() -> None:
    """★ 回传段不可用 → 整体不可用（两段必须同时可用）。

    这是**回归测试**：早期实现在遍历 targets 时可能"侥幸"通过接入段就
    提前返回 True，从而漏掉回传段已失败的事实。
    这里构造一个"接入段完全正常、仅回传段被遮挡"的场景来锁死该行为。
    """

    class BackhaulBlocker:
        """在网关正上方堆起 2000 m 高障碍，只挡回传视线。"""

        _bounds = (109.0, 22.85, 109.5, 23.25)

        def elevation_at(self, lon: float, lat: float) -> float:
            return 2000.0 if abs(lon - 109.2340) < 0.0015 else 100.0

        @property
        def bounds(self):
            return self._bounds

    targets = [Sample(0.0, 109.235, 23.015, 300.0, "cruise")]
    gw = (109.230852, 23.008509, 148.0)
    relay = (109.2365, 23.0165, 400.0)

    # 回传视线确实被遮挡
    assert has_terrain_obstruction(
        BackhaulBlocker(), *relay, *gw, sample_step_m=20.0
    )
    # 接入段本身是可用的（否则测不出"回传被忽略"这个 bug）
    assert _point_covered(
        targets[0], DEFAULT_PARAMS, FLAT, gw, relay, 50.0
    ), "接入段应可用（本测试只针对回传段）"

    # 构造一个回传门限被压低的情形，使遮挡真正导致不可用
    from dataclasses import replace as _replace

    strict = _replace(DEFAULT_PARAMS, obstruction_loss_db=40.0)
    assert not covers_all(
        targets, strict, BackhaulBlocker(), gw, relay, los_step_m=20.0
    ), "回传段被遮挡且遮挡损耗很大时，必须判定为不可用"


def test_covers_all_false_when_access_blocked() -> None:
    """★ 接入段被遮挡 → 不可用（隔离"遮挡 + 高损耗"下的接入判定）。"""

    class AccessBlocker:
        _bounds = (109.0, 22.85, 109.5, 23.25)

        def elevation_at(self, lon: float, lat: float) -> float:
            return 2500.0 if abs(lon - 109.2358) < 0.0010 else 100.0

        @property
        def bounds(self):
            return self._bounds

    from dataclasses import replace as _replace

    targets = [Sample(0.0, 109.235, 23.015, 300.0, "cruise")]
    gw = (109.230852, 23.008509, 148.0)
    relay = (109.2400, 23.0180, 300.0)
    strict = _replace(DEFAULT_PARAMS, obstruction_loss_db=40.0)
    assert not covers_all(
        targets, strict, AccessBlocker(), gw, relay, los_step_m=20.0
    )


def test_point_covered_matches_covers_all() -> None:
    sm = Sample(0.0, 109.235, 23.015, 300.0, "cruise")
    gw = (109.230852, 23.008509, 148.0)
    relay = (109.2365, 23.0165, 400.0)
    assert _point_covered(sm, DEFAULT_PARAMS, FLAT, gw, relay, 50.0)
    assert covers_all([sm], DEFAULT_PARAMS, FLAT, gw, relay, los_step_m=50.0)


def test_outage_samples_detects_far_points() -> None:
    """远离网关的样本应被识别为直连中断。"""
    near = Sample(0.0, 109.2315, 23.0085, 300.0, "cruise")
    far = Sample(10.0, 109.42, 23.21, 300.0, "cruise")
    gw = (109.230852, 23.008509, 148.0)
    out = outage_samples([near, far], DEFAULT_PARAMS, FLAT, gw, los_step_m=200.0)
    assert far in out and near not in out


# ================================================================ 中继架次评估

def test_relay_sortie_time_order(lc: LegCache) -> None:
    """时刻必须满足 建链 ≤ 服务结束 ≤ 返回。"""
    from src.geo.leg import Node
    from src.q3_comms_relay.coverage import HoverCandidate

    o01 = Node("O01", 109.230852, 23.008509, "center", ground_elev_m=127.7)
    h = HoverCandidate(109.2365, 23.0165, 100.0, 350.0, 250.0)
    spec = RelaySpec()
    link_ready, svc_end, ret, e, soc, t_fly = evaluate_relay_sortie(
        spec, h, FLAT, o01, lc, (0.0, 1000.0), 0.0, sample_step_m=50.0
    )
    assert link_ready <= svc_end <= ret
    assert e > 0 and 0.0 <= soc <= 1.0
    assert t_fly > 0
    # 建链完成 = 到达 + 建链时间
    assert link_ready == pytest.approx(
        0.0 + spec.prepare_time_s + t_fly / 2 + spec.link_setup_time_s, rel=0.05
    )


def test_relay_energy_includes_hover_service(lc: LegCache) -> None:
    """服务时长越长，能耗越大（悬停 + 通信附加功率）。"""
    from src.geo.leg import Node
    from src.q3_comms_relay.coverage import HoverCandidate

    o01 = Node("O01", 109.230852, 23.008509, "center", ground_elev_m=127.7)
    h = HoverCandidate(109.2365, 23.0165, 100.0, 350.0, 250.0)
    spec = RelaySpec()
    _, _, _, e1, _, _ = evaluate_relay_sortie(spec, h, FLAT, o01, lc, (0.0, 600.0), 0.0)
    _, _, _, e2, _, _ = evaluate_relay_sortie(spec, h, FLAT, o01, lc, (0.0, 3600.0), 0.0)
    assert e2 > e1


def test_relay_spec_matches_attachment() -> None:
    """中继参数应与附件实测值一致。"""
    s = RelaySpec()
    assert s.max_hover_agl_m == 300.0
    assert s.hover_power_kw == 1.05
    assert s.comms_power_kw == 0.05
    assert s.takeoff_mass_kg == 23.5
    assert s.prepare_time_s == 180.0
    assert s.link_setup_time_s == 30.0
    assert s.service_power_kw == pytest.approx(1.10)


# ================================================================ 校验器：通信覆盖

def test_verifier_flags_uncovered_outage() -> None:
    """★ 负样本：存在中断时段且无中继 → 必须报违规。"""
    uav = UAVType(
        code="B", name="B", empty_mass_kg=65.0, max_payload_kg=30.0, volume_m3=0.073,
        cruise_speed_ms=15.0, range_empty_m=28000.0, range_full_m=16000.0,
        energy_kwh=4.0, reserve_ratio=0.20,
        climb_speed_ms=3.0, descent_speed_ms=2.5, climb_efficiency=0.72,
        descent_efficiency=0.0,
    )
    boxes = {"b1": BoxBatch("b1", "S1", 5.0, 0.01)}
    s = Sortie(
        sortie_id="T01", uav_id="U01", type_code="B", battery_id="B-B01",
        start_s=0.0, service_sequence=("S1",), box_ids=("b1",),
        legs=(Leg(4000.0, 120.0, 120.0), Leg(4000.0, 120.0, 120.0)),
        boxes_per_stop={"S1": 1},
        outage_windows=((100.0, 200.0),),
    )
    rep = verify_transport_plan(TransportPlan(sorties=(s,)), {"B": uav}, boxes)
    assert rep.has(ViolationType.COMMS_UNSUPPORTED)


def test_verifier_accepts_relay_handover() -> None:
    """★ 正样本：中断时段被**两架中继接力**覆盖也算已保障。"""
    uav = UAVType(
        code="B", name="B", empty_mass_kg=65.0, max_payload_kg=30.0, volume_m3=0.073,
        cruise_speed_ms=15.0, range_empty_m=28000.0, range_full_m=16000.0,
        energy_kwh=4.0, reserve_ratio=0.20,
        climb_speed_ms=3.0, descent_speed_ms=2.5, climb_efficiency=0.72,
        descent_efficiency=0.0,
    )
    boxes = {"b1": BoxBatch("b1", "S1", 5.0, 0.01)}
    s = Sortie(
        sortie_id="T01", uav_id="U01", type_code="B", battery_id="B-B01",
        start_s=0.0, service_sequence=("S1",), box_ids=("b1",),
        legs=(Leg(4000.0, 120.0, 120.0), Leg(4000.0, 120.0, 120.0)),
        boxes_per_stop={"S1": 1},
        outage_windows=((1000.0, 3000.0),),
    )
    relays = (
        RelayAssignment("R01", 900.0, 2000.0, ("T01",)),
        RelayAssignment("R02", 2000.0, 3100.0, ("T01",)),
    )
    rep = verify_transport_plan(
        TransportPlan(sorties=(s,), relays=relays), {"B": uav}, boxes
    )
    assert not rep.has(ViolationType.COMMS_UNSUPPORTED), rep.summary()


def test_verifier_flags_gap_in_relay_handover() -> None:
    """★ 负样本：两架中继之间存在**空档** → 必须报违规。"""
    uav = UAVType(
        code="B", name="B", empty_mass_kg=65.0, max_payload_kg=30.0, volume_m3=0.073,
        cruise_speed_ms=15.0, range_empty_m=28000.0, range_full_m=16000.0,
        energy_kwh=4.0, reserve_ratio=0.20,
        climb_speed_ms=3.0, descent_speed_ms=2.5, climb_efficiency=0.72,
        descent_efficiency=0.0,
    )
    boxes = {"b1": BoxBatch("b1", "S1", 5.0, 0.01)}
    s = Sortie(
        sortie_id="T01", uav_id="U01", type_code="B", battery_id="B-B01",
        start_s=0.0, service_sequence=("S1",), box_ids=("b1",),
        legs=(Leg(4000.0, 120.0, 120.0), Leg(4000.0, 120.0, 120.0)),
        boxes_per_stop={"S1": 1},
        outage_windows=((1000.0, 3000.0),),
    )
    relays = (
        RelayAssignment("R01", 900.0, 1800.0, ("T01",)),
        RelayAssignment("R02", 2200.0, 3100.0, ("T01",)),  # 1800~2200 空档
    )
    rep = verify_transport_plan(
        TransportPlan(sorties=(s,), relays=relays), {"B": uav}, boxes
    )
    assert rep.has(ViolationType.COMMS_UNSUPPORTED)
