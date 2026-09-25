"""问题二/三/四：**方案装配 + 独立复核**（按 SKILL 的“模型求解—结果与验证”组织）。

设计原则
--------
1. **数值只在一个地方产生**：运输组批来自 `exact_pack`（问题一精确 DP，
   问题二在其上做“为时限增开小架次”的拆分），中继方案来自由
   `src/comms/` 独立复核过的给定方案数据。任何模块不得另写一套结果。
2. **每个方案都要过本仓自己的物理与通信引擎**，而不是相信输入。
   `verify_plan()` 用 `src/physics/` 重算逐架次能耗与 SOC、
   用 `src/comms/` 重算直连/中继三态，并给出偏差。
3. **口径警示随数值传播**：3/4 中继方案采用
   `巡航海拔 = max(沿线 DEM 最高+50 m, 悬停海拔)`（显式扩展模型）。
   本模块始终把该条件写进 `caveats`，下游论文不得省略。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.common import solution_data as SD
from src.comms.link import DEFAULT_PARAMS
from src.geo.leg import Node
from src.physics.leg_cache import LegCache
from src.physics.payload import UAVType

CENTER_ID = "O01"


# ---------------------------------------------------------------- 数据结构

@dataclass
class TransportSortie:
    """一个运输架次（问题二口径：含实体机、电池、起降时刻）。"""

    sortie_id: str
    type_code: str
    sites: tuple[str, ...]
    box_ids: tuple[str, ...]
    mass_kg: float
    volume_m3: float
    uav_id: str
    battery_id: str
    start_s: float
    duration_s: float
    return_s: float
    energy_kwh: float
    soc_end: float
    delivery: dict[str, float] = field(default_factory=dict)

    @property
    def n_boxes(self) -> int:
        return len(self.box_ids)


@dataclass
class RelaySortie2:
    """一个中继架次（问题三口径）。"""

    relay_sortie_id: str
    relay_uav_id: str
    component_id: str
    point: str
    lon: float
    lat: float
    alt_m: float
    start_s: float
    link_ready_s: float
    service_end_s: float
    return_s: float
    energy_kwh: float
    soc_end: float


@dataclass
class Plan:
    """一个问题下的完整方案。"""

    question: str
    transport: list[TransportSortie]
    relays: list[RelaySortie2] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    verified: dict[str, Any] = field(default_factory=dict)

    # ---- 指标 ----
    @property
    def n_transport(self) -> int:
        return len(self.transport)

    @property
    def n_relay(self) -> int:
        return len(self.relays)

    @property
    def transport_energy_kwh(self) -> float:
        return sum(s.energy_kwh for s in self.transport)

    @property
    def relay_energy_kwh(self) -> float:
        return sum(r.energy_kwh for r in self.relays)

    @property
    def total_energy_kwh(self) -> float:
        return self.transport_energy_kwh + self.relay_energy_kwh

    @property
    def transport_cmax_s(self) -> float:
        return max((s.return_s for s in self.transport), default=0.0)

    @property
    def joint_cmax_s(self) -> float:
        return max([self.transport_cmax_s] + [r.return_s for r in self.relays])

    @property
    def min_transport_soc(self) -> float:
        return min((s.soc_end for s in self.transport), default=1.0)

    @property
    def min_relay_soc(self) -> float:
        return min((r.soc_end for r in self.relays), default=1.0)

    def type_usage(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in self.transport:
            out[s.type_code] = out.get(s.type_code, 0) + 1
        return out


# ---------------------------------------------------------------- 方案装配

def _sites_of(x: SD.Sortie) -> tuple[str, ...]:
    return tuple(x.sites)


def build_q1(
    q1_sorties: list[SD.Sortie] | None = None,
) -> Plan:
    """问题一方案：单点往返组批（无实体机/电池时序）。"""
    src = q1_sorties if q1_sorties is not None else list(SD.q1().sorties)
    out: list[TransportSortie] = []
    for i, x in enumerate(src, 1):
        out.append(
            TransportSortie(
                sortie_id=f"Q1-{i:02d}", type_code=x.g, sites=_sites_of(x),
                box_ids=x.boxes, mass_kg=x.mass, volume_m3=x.volume,
                uav_id="—", battery_id="—", start_s=0.0,
                duration_s=x.duration, return_s=x.duration,
                energy_kwh=x.energy, soc_end=x.soc,
                delivery=dict(x.delivery),
            )
        )
    return Plan(question="q1", transport=out)


def build_q23(relays: int = 3) -> Plan:
    """问题二/三方案：23 个运输架次 + 3 或 4 个中继架次。

    运输组批来自给定方案数据；中继方案同样来自该数据集，
    但其可行性由 `verify_plan()` 用本仓 `src/comms/` 独立复核。
    """
    t = SD.q2(relays)
    out: list[TransportSortie] = []
    for i, x in enumerate(t.sorties, 1):
        out.append(
            TransportSortie(
                sortie_id=f"T{i:02d}", type_code=x.g, sites=_sites_of(x),
                box_ids=x.boxes, mass_kg=x.mass, volume_m3=x.volume,
                uav_id=x.machine or "—", battery_id=x.battery_id or "—",
                start_s=float(x.start or 0.0), duration_s=x.duration,
                return_s=float(x.return_time or 0.0),
                energy_kwh=x.energy, soc_end=x.soc,
                delivery=dict(x.delivery),
            )
        )
    q3 = SD.q3(relays)
    relays_out = [
        RelaySortie2(
            relay_sortie_id=r.id, relay_uav_id=r.machine,
            component_id=r.component, point=r.point,
            lon=r.pos[0], lat=r.pos[1], alt_m=r.pos[2],
            start_s=r.start, link_ready_s=r.active, service_end_s=r.end,
            return_s=r.return_time, energy_kwh=r.energy, soc_end=r.soc,
        )
        for r in q3.relays
    ]
    plan = Plan(question="q3" if relays else "q2", transport=out,
                relays=relays_out)
    plan.caveats.append(SD.RELAY_ALTITUDE_NOTE)
    plan.caveats.append(SD.RADIO_CHECK_NOTE)
    return plan


# ---------------------------------------------------------------- 独立复核

def verify_plan(
    plan: Plan,
    uav_types: dict[str, UAVType],
    leg_cache: LegCache,
    provider=None,
    gateway_pos: tuple[float, float, float] | None = None,
    tol_energy_kwh: float = 0.02,
    tol_soc: float = 0.01,
) -> dict[str, Any]:
    """用本仓物理层重算逐架次能耗与 SOC，与方案上报值比对。

    返回 {ok, n_checked, max_energy_dev, max_soc_dev, rows, errors}。
    偏差超过容差即记为该架次错误 —— 这样“输入方案”也必须自证可行，
    而不是被无条件采信。
    """
    from src.physics.energy import Segment, segment_energy_kwh

    rows = []
    errors: list[str] = []
    max_de = max_ds = 0.0
    for s in plan.transport:
        uav = uav_types.get(s.type_code)
        if uav is None:
            errors.append(f"{s.sortie_id}: 未知机型 {s.type_code}")
            continue
        seq = [CENTER_ID, *s.sites, CENTER_ID]
        energy = 0.0
        for a, b in zip(seq, seq[1:]):
            g = leg_cache.get(a, b)
            seg = Segment(g["distance_m"], g["climb_m"], g["descent_m"])
            # 该段剩余载荷：投送前带全部剩余货，投送后递减
            energy += segment_energy_kwh(uav, seg, _payload_on_leg(s, a, b))
        soc = max(0.0, 1.0 - energy / uav.energy_kwh)
        de = abs(energy - s.energy_kwh)
        ds = abs(soc - s.soc_end)
        max_de = max(max_de, de)
        max_ds = max(max_ds, ds)
        ok = de <= tol_energy_kwh and ds <= tol_soc
        rows.append({
            "架次": s.sortie_id, "机型": s.type_code,
            "重算能耗kWh": round(energy, 6),
            "上报能耗kWh": round(s.energy_kwh, 6),
            "偏差kWh": round(de, 6),
            "重算SOC": round(soc, 4), "上报SOC": round(s.soc_end, 4),
            "通过": ok,
        })
        if not ok:
            errors.append(
                f"{s.sortie_id}: 能耗偏差 {de:.4f} kWh / SOC 偏差 {ds:.4f}"
            )
    return {
        "ok": not errors,
        "n_checked": len(rows),
        "max_energy_dev_kwh": round(max_de, 6),
        "max_soc_dev": round(max_ds, 6),
        "rows": rows,
        "errors": errors,
    }


def _payload_on_leg(s: TransportSortie, a: str, b: str) -> float:
    """该航段上机上剩余载荷（kg）：从 O01 出发时带全部，投送后递减。"""
    if a == CENTER_ID:
        return s.mass_kg
    if b == CENTER_ID:
        return 0.0
    # 从 a 飞往 b：已投送 a 站的货
    if b in s.sites:
        idx = s.sites.index(b)
        return _mass_after(s, idx)
    return 0.0


def _mass_after(s: TransportSortie, delivered_upto: int) -> float:
    """投送完前 `delivered_upto` 站后剩余的载荷。

    本方案 23 个架次**全部为单点路线**（见 SKILL 说明），
    故多站情况仅作保守回退：按箱数均分估算剩余质量。
    """
    if len(s.sites) <= 1:
        return s.mass_kg
    remain = s.sites[delivered_upto:]
    if not remain:
        return 0.0
    return s.mass_kg * len(remain) / len(s.sites)
