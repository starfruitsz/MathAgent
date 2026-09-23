"""问题三求解器：通信约束下的运输与中继联合调度。

求解思路
--------
1. **复用 Q2 的运输方案**作为起点（题目要求"保持运输方案"的一致性，
   且 Q4 明确"以问题三得到的联合调度方案为基础"）。
2. **诊断**：对每个运输架次的完整轨迹逐时刻采样，标出直连中断时段。
3. **中继选址**：对每个需要保障的架次，在候选悬停点中选一个
   使该架次**全程**（或尽可能长的时间）被覆盖的点；优先选能耗最低的。
4. **中继架次生成与调度**：把覆盖任务变成中继架次（含起飞、建链、服务、返航），
   再按中继资源（2 架 + 6 组能源组件）与充电周转排程。
5. **独立校验**：交给 `verify.feasibility`（含通信中断覆盖检查）。

中继时间口径（题目附录 2）
--------------------------
    架次时间 = 工位固定准备(180s) + 飞往悬停点 + 建链(30s)
             + 通信服务时长 + 返航
    能耗 = 爬升附加 + 水平巡航(巡航功率×时间) + 悬停与通信服务能耗
    悬停服务能耗 = (悬停功率 + 通信附加功率) × 服务时长
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from src.comms.link import DEFAULT_PARAMS
from src.comms.service import CommState, ServiceContext, comm_status
from src.common.config import M_TO_KM
from src.geo.dem import ElevationProvider
from src.physics.battery import charging_time
from src.physics.energy import Segment, segment_time_s
from src.physics.leg_cache import LegCache
from src.physics.payload import UAVType
from src.q3_comms_relay.coverage import (
    CENTER_ID,
    HoverCandidate,
    coverage_of_samples,
    sample_trajectory,
)

JOULE_PER_KWH = 3.6e6


# ---------------------------------------------------------------- 中继参数

@dataclass(frozen=True)
class RelaySpec:
    """中继无人机参数（附件实测，见 docs/DATA_NOTES.md 第 4 节）。"""

    code: str = "R"
    name: str = "中继标准测试多旋翼"
    empty_mass_kg: float = 21.0
    comms_module_mass_kg: float = 2.5
    takeoff_mass_kg: float = 23.5
    cruise_speed_ms: float = 15.0
    cruise_power_kw: float = 1.15
    energy_kwh: float = 3.2
    reserve_ratio: float = 0.20
    prepare_time_s: float = 180.0
    link_setup_time_s: float = 30.0
    turnaround_time_s: float = 300.0
    climb_speed_ms: float = 4.0
    descent_speed_ms: float = 3.0
    climb_efficiency: float = 0.72
    descent_efficiency: float = 0.0
    hover_power_kw: float = 1.05
    comms_power_kw: float = 0.05
    max_hover_agl_m: float = 300.0

    @property
    def energy_budget_kwh(self) -> float:
        return (1.0 - self.reserve_ratio) * self.energy_kwh

    @property
    def service_power_kw(self) -> float:
        """悬停 + 通信附加功率（kW）。"""
        return self.hover_power_kw + self.comms_power_kw


# ---------------------------------------------------------------- 中继架次

@dataclass
class RelaySortie:
    """一个中继架次。"""

    sortie_id: str
    relay_uav_id: str
    energy_pack_id: str
    hover: HoverCandidate
    start_s: float
    link_ready_s: float
    """建链完成时刻。"""
    service_end_s: float
    return_s: float
    energy_kwh: float
    soc_end: float
    covers: tuple[str, ...]
    """该中继架次保障的运输架次编号。"""

    @property
    def service_start_s(self) -> float:
        return self.link_ready_s


def relay_leg_geometry(
    provider: ElevationProvider,
    o01: Node,
    hover: HoverCandidate,
    sample_step_m: float = 30.0,
):
    """中继从 O01 往返悬停点的航段几何（按附录 2 的净空规则）。

    ★ 悬停点的"作业高度"就是它的**飞行海拔**，因此把该节点建成
      `kind="center"`（作业高度 = 地面海拔）并令其地面海拔 = `hover.alt_m`，
      这样 `leg_geometry` 给出的爬升/下降高度恰好是"从 O01 作业高度到悬停海拔"。
    """
    from src.geo.leg import Node, leg_geometry

    hover_node = Node(
        "RELAY_HOVER", hover.lon, hover.lat, "center", ground_elev_m=hover.alt_m
    )
    out = leg_geometry(provider, o01, hover_node, sample_step_m=sample_step_m)
    back = leg_geometry(provider, hover_node, o01, sample_step_m=sample_step_m)
    return out, back


def evaluate_relay_sortie(
    spec: RelaySpec,
    hover: HoverCandidate,
    provider: ElevationProvider,
    o01: Node,
    leg_cache: LegCache,
    service_window: tuple[float, float],
    start_s: float,
    sample_step_m: float = 30.0,
) -> tuple[float, float, float, float, float, float]:
    """评估中继架次。

    返回 `(建链完成, 服务结束, 返回, 能耗kWh, 返航SOC, 悬停往返飞行时间)`。

    时间：
        start → 准备 → 爬升 → 巡航 → 下降 （到达悬停点）
              → 建链(link_setup) → 服务 window → 返航（下降 → 巡航 → 爬升？）
    能耗 = 去程(爬升附加 + 水平巡航) + 悬停服务 + 回程(水平巡航 + 爬升附加)
    """
    from src.physics.energy import climb_energy_kwh, segment_energy_kwh

    out_g, back_g = relay_leg_geometry(provider, o01, hover, sample_step_m)
    seg_out = Segment(out_g.distance_m, out_g.climb_m, out_g.descent_m)
    seg_back = Segment(back_g.distance_m, back_g.climb_m, back_g.descent_m)

    # 时间
    t = start_s + spec.prepare_time_s
    t += segment_time_s(_relay_as_uav(spec), seg_out)
    reach_s = t
    link_ready = reach_s + spec.link_setup_time_s
    svc_start = max(link_ready, service_window[0])
    svc_end = max(svc_start, service_window[1])
    t = svc_end + segment_time_s(_relay_as_uav(spec), seg_back)
    return_s = t

    # 能耗：起飞总质量（附录 2 规定"质量取计划起飞总质量"）
    m = spec.takeoff_mass_kg
    e_out = (
        m * 9.80665 * seg_out.climb_m / spec.climb_efficiency / JOULE_PER_KWH
        + seg_out.distance_m / spec.cruise_speed_ms * spec.cruise_power_kw / 3600.0
    )
    e_back = (
        m * 9.80665 * seg_back.climb_m / spec.climb_efficiency / JOULE_PER_KWH
        + seg_back.distance_m / spec.cruise_speed_ms * spec.cruise_power_kw / 3600.0
    )
    e_service = spec.service_power_kw * (svc_end - svc_start) / 3600.0
    e_total = e_out + e_back + e_service
    soc = max(0.0, 1.0 - e_total / spec.energy_kwh)
    flight_time = segment_time_s(_relay_as_uav(spec), seg_out) + segment_time_s(
        _relay_as_uav(spec), seg_back
    )
    return link_ready, svc_end, return_s, e_total, soc, flight_time


def _relay_as_uav(spec: RelaySpec) -> UAVType:
    """把中继参数映射成 `UAVType` 以复用 `segment_time_s`（口径统一，R4）。"""
    return UAVType(
        code=spec.code, name=spec.name,
        empty_mass_kg=spec.empty_mass_kg, max_payload_kg=spec.comms_module_mass_kg,
        volume_m3=1.0, cruise_speed_ms=spec.cruise_speed_ms,
        range_empty_m=1.0, range_full_m=1.0, energy_kwh=spec.energy_kwh,
        reserve_ratio=spec.reserve_ratio,
        climb_speed_ms=spec.climb_speed_ms, descent_speed_ms=spec.descent_speed_ms,
        climb_efficiency=spec.climb_efficiency,
        descent_efficiency=spec.descent_efficiency,
    )
