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
    ev = evaluate_relay_sortie(
        spec, h, FLAT, o01, lc, (3600.0, 5000.0), 0.0,
        sample_step_m=50.0, strict=True,
    )
    assert ev is not None
    assert ev.link_ready_s <= ev.service_end_s <= ev.return_s
    assert ev.energy_kwh > 0 and 0.0 <= ev.soc_end <= 1.0
    assert ev.flight_time_s > 0
    # 建链完成 = 到达 + 建链时间
    assert ev.link_ready_s == pytest.approx(
        0.0 + spec.prepare_time_s + ev.flight_time_s / 2 + spec.link_setup_time_s,
        rel=0.05,
    )


def test_relay_energy_includes_hover_service(lc: LegCache) -> None:
    """服务时长越长，能耗越大（悬停 + 通信附加功率）。"""
    from src.geo.leg import Node
    from src.q3_comms_relay.coverage import HoverCandidate

    o01 = Node("O01", 109.230852, 23.008509, "center", ground_elev_m=127.7)
    h = HoverCandidate(109.2365, 23.0165, 100.0, 350.0, 250.0)
    spec = RelaySpec()
    e1 = evaluate_relay_sortie(spec, h, FLAT, o01, lc, (3600.0, 4200.0), 0.0,
                               strict=True)
    e2 = evaluate_relay_sortie(spec, h, FLAT, o01, lc, (3600.0, 7200.0), 0.0,
                               strict=True)
    assert e1 is not None and e2 is not None
    assert e1.full_coverage and e2.full_coverage
    assert e2.energy_kwh > e1.energy_kwh


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


# ================================================================ 中继服务窗口（ADR-031）

def test_relay_sortie_full_coverage_when_ready_in_time(lc: LegCache) -> None:
    """★ 建链早于窗口起点 → 完整覆盖，`full_coverage=True` 且无缺口。"""
    from src.geo.leg import Node
    from src.q3_comms_relay.coverage import HoverCandidate

    o01 = Node("O01", 109.230852, 23.008509, "center", ground_elev_m=127.7)
    h = HoverCandidate(109.2365, 23.0165, 100.0, 350.0, 250.0)
    spec = RelaySpec()
    ev = evaluate_relay_sortie(spec, h, FLAT, o01, lc, (3600.0, 5000.0), 0.0,
                               sample_step_m=50.0, strict=True)
    assert ev is not None
    assert ev.full_coverage
    assert ev.gap_s == pytest.approx(0.0)
    assert ev.link_ready_s <= 3600.0
    assert ev.service_start_s == pytest.approx(3600.0)
    assert ev.service_end_s == pytest.approx(5000.0)
    # 服务时长 = 窗口长度（没有截短）
    assert ev.service_end_s - ev.service_start_s == pytest.approx(1400.0)


def test_relay_sortie_strict_fails_when_arriving_late(lc: LegCache) -> None:
    """★★ ADR-031 核心负样本：中继无法在窗口起点前建链 → **必须显式失败**。

    修复前：`svc_end = max(svc_start, window[1])` 会把服务区间**截短到零长**
    （`svc_end == svc_start`）且不报错，于是"中继在运输机返航之后才到场"
    被静默当成已保障。
    """
    from src.geo.leg import Node
    from src.q3_comms_relay.coverage import HoverCandidate

    o01 = Node("O01", 109.230852, 23.008509, "center", ground_elev_m=127.7)
    h = HoverCandidate(109.2365, 23.0165, 100.0, 350.0, 250.0)
    spec = RelaySpec()
    # 窗口从 0 开始，而中继至少需要 准备(180) + 飞行 + 建链(30) 才能到站
    assert evaluate_relay_sortie(spec, h, FLAT, o01, lc, (0.0, 1000.0), 0.0,
                                 sample_step_m=50.0, strict=True) is None


def test_relay_sortie_nonstrict_reports_truncation_explicitly(lc: LegCache) -> None:
    """★ 非严格模式：允许截短，但必须**如实报告**覆盖不完整与缺口时长。"""
    from src.geo.leg import Node
    from src.q3_comms_relay.coverage import HoverCandidate

    o01 = Node("O01", 109.230852, 23.008509, "center", ground_elev_m=127.7)
    h = HoverCandidate(109.2365, 23.0165, 100.0, 350.0, 250.0)
    spec = RelaySpec()
    ev = evaluate_relay_sortie(spec, h, FLAT, o01, lc, (0.0, 1000.0), 0.0,
                               sample_step_m=50.0, strict=False)
    assert ev is not None
    assert not ev.full_coverage
    assert ev.gap_s > 0.0
    assert ev.service_start_s > 0.0          # 晚到 ⇒ 服务从建链后开始
    assert ev.service_start_s == pytest.approx(ev.link_ready_s)
    # 缺口 = 窗口起点到建链完成之间未获保障的时长
    assert ev.gap_s == pytest.approx(ev.service_start_s - 0.0)


def test_relay_sortie_max_service_duration_reflects_energy(lc: LegCache) -> None:
    """★ 续航上限：可用能量 ÷ 服务功率 —— 用于判定"窗口是否本就不可行"。"""
    from src.geo.leg import Node
    from src.q3_comms_relay.coverage import HoverCandidate

    o01 = Node("O01", 109.230852, 23.008509, "center", ground_elev_m=127.7)
    h = HoverCandidate(109.2365, 23.0165, 100.0, 350.0, 250.0)
    spec = RelaySpec()
    ev = evaluate_relay_sortie(spec, h, FLAT, o01, lc, (3600.0, 5000.0), 0.0,
                               sample_step_m=50.0, strict=True)
    assert ev is not None
    assert ev.max_service_s == pytest.approx(
        spec.energy_budget_kwh / spec.service_power_kw * 3600.0
    )
    # 2.56 kWh / 1.10 kW ≈ 8381 s ≈ 140 min
    assert ev.max_service_s == pytest.approx(8381.0, rel=0.01)


def test_relay_sortie_interval_set_avoids_envelope_padding(lc: LegCache) -> None:
    """★★ 中断区间集合 ≠ 包络：中间"直连可用"的时段不该要求中继驻留。

    同一架次断两次（1000~1100 与 2000~2100），中间 1100~2000 直连可用。
    - 区间集合口径：服务时长 = 200 s
    - 包络口径 [1000, 2100]：服务时长 = 1100 s（虚高 5.5 倍）
    实测全题 20 个架次的包络比真实中断虚高 **39%** 的站岗时长（277 vs 168 min），
    用包络会显著浪费续航并压低可保障的架次数。
    """
    from src.geo.leg import Node
    from src.q3_comms_relay.coverage import HoverCandidate

    o01 = Node("O01", 109.230852, 23.008509, "center", ground_elev_m=127.7)
    h = HoverCandidate(109.2365, 23.0165, 100.0, 350.0, 250.0)
    spec = RelaySpec()

    ivs = ((1000.0, 1100.0), (2000.0, 2100.0))
    ev = evaluate_relay_sortie(spec, h, FLAT, o01, lc, ivs, 0.0,
                               sample_step_m=50.0, strict=True)
    assert ev is not None and ev.full_coverage
    assert ev.service_windows == ivs
    assert ev.service_end_s == pytest.approx(2100.0)
    assert ev.gap_s == pytest.approx(0.0)
    # 服务能耗只按两段真实中断计（各 100 s）
    e_ivs = ev.energy_kwh

    env = evaluate_relay_sortie(spec, h, FLAT, o01, lc, (1000.0, 2100.0), 0.0,
                                sample_step_m=50.0, strict=True)
    assert env is not None
    assert env.service_end_s == pytest.approx(2100.0)
    # 包络口径把中间 900 s 也算成服务，能耗必然明显更大
    assert env.energy_kwh > e_ivs
    expected_pad = spec.service_power_kw * 900.0 / 3600.0
    assert env.energy_kwh - e_ivs == pytest.approx(expected_pad, rel=1e-6)


def test_relay_sortie_strict_fails_when_any_interval_is_late(lc: LegCache) -> None:
    """★ 多区间时，**任一段**来不及建链即判不可行（连续通信不能有缺口）。"""
    from src.geo.leg import Node
    from src.q3_comms_relay.coverage import HoverCandidate

    o01 = Node("O01", 109.230852, 23.008509, "center", ground_elev_m=127.7)
    h = HoverCandidate(109.2365, 23.0165, 100.0, 350.0, 250.0)
    spec = RelaySpec()
    # 第二段从 100 s 开始，而中继至少需要 准备+飞行+建链 才到站
    assert evaluate_relay_sortie(spec, h, FLAT, o01, lc,
                                 ((3600.0, 3700.0), (100.0, 200.0)), 0.0,
                                 sample_step_m=50.0, strict=True) is None
    # 非严格模式：如实报告有几段没赶上
    ev = evaluate_relay_sortie(spec, h, FLAT, o01, lc,
                               ((3600.0, 3700.0), (100.0, 200.0)), 0.0,
                               sample_step_m=50.0, strict=False)
    assert ev is not None
    assert not ev.full_coverage
    assert ev.n_gaps == 1
    assert ev.gap_s > 0.0


# ================================================================ 校验器：通信覆盖

def test_verifier_flags_outage_before_relay_arrives() -> None:
    """★★ ADR-031 负样本：中断发生在中继建链**之前** → 必须报违规。

    这条用例锁死"中继晚到"必须被校验器抓到（修复前该情形会被静默放过）。
    """
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
        outage_windows=((100.0, 200.0),),          # 100~200 s 就断了
    )
    relays = (RelayAssignment("R01", 900.0, 2000.0, ("T01",)),)  # 900 s 才建链
    rep = verify_transport_plan(
        TransportPlan(sorties=(s,), relays=relays), {"B": uav}, boxes
    )
    assert rep.has(ViolationType.COMMS_UNSUPPORTED), rep.summary()


def test_verifier_flags_outage_after_relay_leaves() -> None:
    """★ 中继提前离站（服务结束早于中断结束）→ 必须报违规。"""
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
    relays = (RelayAssignment("R01", 900.0, 2000.0, ("T01",)),)  # 2000 s 就走
    rep = verify_transport_plan(
        TransportPlan(sorties=(s,), relays=relays), {"B": uav}, boxes
    )
    assert rep.has(ViolationType.COMMS_UNSUPPORTED), rep.summary()


def test_verifier_flags_relay_deficit_as_soft_violation() -> None:
    """★★ 负样本：中断**完全没有**中继任务 → 记为资源缺口（软违规）。

    区分两种"没覆盖"：
      - 没有任何中继任务 ⇒ `COMMS_RELAY_INSUFFICIENT`（软，如实报告资源缺口）
      - 有中继但窗口没盖住 ⇒ `COMMS_UNSUPPORTED`（硬，排班缺陷）

    若把前者也当硬违规，求解器会直接中止、什么都不产出 ——
    等于"因为资源不够就干脆不报告"，反而违反 ADR-031 的红线。
    """
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
        outage_windows=((1000.0, 2000.0),),
    )
    rep = verify_transport_plan(TransportPlan(sorties=(s,)), {"B": uav}, boxes)
    assert rep.has(ViolationType.COMMS_RELAY_INSUFFICIENT), rep.summary()
    assert not rep.has(ViolationType.COMMS_UNSUPPORTED), rep.summary()
    # 软违规不阻断产出
    rep.assert_deliverable()


def test_verifier_rejects_zero_length_relay_window() -> None:
    """★ 零长度的中继窗口（未建链即返回）不算提供保障 → 仍应报缺口。"""
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
        outage_windows=((1000.0, 2000.0),),
    )
    # 中继建链于 3409.8、服务结束也是 3409.8 —— 正是修复前那类"静默截短"
    relays = (RelayAssignment("R01", 3409.8, 3409.8, ("T01",)),)
    rep = verify_transport_plan(
        TransportPlan(sorties=(s,), relays=relays), {"B": uav}, boxes
    )
    assert rep.has(ViolationType.COMMS_RELAY_INSUFFICIENT), rep.summary()


def test_verifier_accepts_one_relay_serving_two_sorties() -> None:
    """★★ A 口径正样本：**一架中继同时保障两架运输机**（悬停点可共享）。

    题目附录 3 只限制"每架运输无人机在任一时刻只能由 G01 或**一架**中继保障"，
    未限制一架中继的服务对象数量，故同一中继窗口可写入多个架次。
    """
    uav = UAVType(
        code="B", name="B", empty_mass_kg=65.0, max_payload_kg=30.0, volume_m3=0.073,
        cruise_speed_ms=15.0, range_empty_m=28000.0, range_full_m=16000.0,
        energy_kwh=4.0, reserve_ratio=0.20,
        climb_speed_ms=3.0, descent_speed_ms=2.5, climb_efficiency=0.72,
        descent_efficiency=0.0,
    )
    boxes = {"b1": BoxBatch("b1", "S1", 5.0, 0.01), "b2": BoxBatch("b2", "S1", 5.0, 0.01)}
    def _sortie(sid: str, box: str, win: tuple[float, float]) -> Sortie:
        return Sortie(
            sortie_id=sid, uav_id=f"U{sid[-1]}", type_code="B",
            battery_id="B-B01", start_s=0.0, service_sequence=("S1",),
            box_ids=(box,),
            legs=(Leg(4000.0, 120.0, 120.0), Leg(4000.0, 120.0, 120.0)),
            boxes_per_stop={"S1": 1}, outage_windows=(win,),
        )
    s1 = _sortie("T01", "b1", (1000.0, 2000.0))
    s2 = _sortie("T02", "b2", (1500.0, 2500.0))
    relays = (RelayAssignment("R01", 900.0, 2600.0, ("T01", "T02")),)
    rep = verify_transport_plan(
        TransportPlan(sorties=(s1, s2), relays=relays), {"B": uav}, boxes
    )
    assert not rep.has(ViolationType.COMMS_UNSUPPORTED), rep.summary()


def test_verifier_flags_uncovered_outage() -> None:
    """★ 负样本：存在中断时段且**完全没有中继** → 记为资源缺口（软违规）。

    ADR-031：无中继可用 ⇒ `COMMS_RELAY_INSUFFICIENT`；
    有正长度中继窗口但未盖住 ⇒ `COMMS_UNSUPPORTED`（见下一条用例）。
    """
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
    assert rep.has(ViolationType.COMMS_RELAY_INSUFFICIENT)


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
