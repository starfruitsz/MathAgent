"""D 题**方案数据的唯一权威来源**（single source of truth）。

背景
----
本仓的方案数值来自外部给定并经独立复核的方案数据集
`data/reference/D题_方案数据.json`。它的核对结果记录在
`verification` 字段中（逐问 errors 为空、抽检中断 0），
叙述性说明见 `docs/reference/D题_前三问模型与求解结果.md`、
逐箱明细见 `docs/reference/D题_逐箱交付核对表.md`。

★ 铁律 R4 的延伸：**方案数值只在这里读一次**，问题层与论文层
一律通过本模块取数，禁止在别处硬编码架次/能耗/时刻等结果数字，
否则各处口径必然分叉。

★ 口径警示（必须随数值一起传播）
--------------------------------
`relay_flight_altitude_note` 记录了一个**显式建模扩展**：
3/4 中继方案的三个悬停点海拔（DEM+300 m）**高于**该航段按附录 2
“沿线 DEM 最高 + 50 m”算出的巡航海拔。因此这些方案采用的是

    巡航海拔 = max(沿线 DEM 最高 + 50 m, 悬停海拔)

若附录 2 被要求**严格取等号、不得抬升**，则这两套中继方案只能作为
**扩展模型下的条件方案**，不能写成严格题意下的可行解。
本模块把该警示作为数据的一部分一并暴露（`RELAY_ALTITUDE_NOTE`），
供论文与校验器引用，避免下游写成无条件结论。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.common.config import REPO_ROOT

DATA_PATH = REPO_ROOT / "data" / "reference" / "D题_方案数据.json"

# 巡航海拔口径（论文与校验器都要引用）
CRUISE_ALT_STRICT = "strict"      # 附录 2 严格口径：沿线 DEM 最高 + 50 m
CRUISE_ALT_RAISED = "raised"      # 扩展口径：max(沿线 DEM 最高 + 50 m, 悬停海拔)


@dataclass(frozen=True)
class Sortie:
    """一个运输架次（问题一/二/三共用）。"""

    g: str
    """机型代码（A/B/C）。"""
    sites: tuple[str, ...]
    """访问的服务区序列。"""
    boxes: tuple[str, ...]
    """装载的货箱编号。"""
    mass: float
    volume: float
    duration: float
    """架次历时（s），含准备/装载/飞行/交接。"""
    energy: float
    """架次能耗（kWh）。"""
    soc: float
    """返航剩余 SOC（0–1）。"""
    delivery: dict[str, float]
    """{货箱编号: 该箱完成交接的时刻（s，相对 t=0）}。"""
    machine: str | None = None
    """实体无人机编号（问题一起无实体机分配，为 None）。"""
    battery_id: str | None = None
    start: float | None = None
    """起飞时刻（s）。"""
    return_time: float | None = None
    """返回 O01 时刻（s）。"""

    @property
    def n_boxes(self) -> int:
        return len(self.boxes)


@dataclass(frozen=True)
class RelaySortie:
    """一个中继架次。"""

    id: str
    machine: str
    """中继实体机编号（R01/R02）。"""
    component: str
    """能源组件编号（ER01…）。"""
    point: str
    """悬停点标识（如 G2-3、S010、G4-4）。"""
    pos: tuple[float, float, float]
    """悬停位置（经度, 纬度, 海拔 m）。"""
    start: float
    active: float
    """建链完成（开始服务）时刻（s）。"""
    end: float
    """服务结束时刻（s）。"""
    return_time: float
    energy: float
    soc: float

    @property
    def service_window(self) -> tuple[float, float]:
        return (self.active, self.end)


@dataclass(frozen=True)
class CaseResult:
    """一个问题下的某套方案结果（含运输与中继）。"""

    trips: int
    cmax: float
    energy: float
    sorties: tuple[Sortie, ...]
    relays: tuple[RelaySortie, ...] = ()
    joint_cmax: float | None = None
    total_energy: float | None = None
    radio_samples: int | None = None
    radio_failures: int | None = None
    direct_samples: int | None = None
    relayed_samples: int | None = None
    n_late: int | None = None
    hard_violations: tuple[str, ...] = ()

    @property
    def relay_energy(self) -> float | None:
        if self.total_energy is None:
            return None
        return self.total_energy - self.energy


@lru_cache(maxsize=1)
def raw() -> dict[str, Any]:
    """整份方案数据（只读）。"""
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def _to_sorties(items: list[dict[str, Any]]) -> tuple[Sortie, ...]:
    return tuple(
        Sortie(
            g=x["g"], sites=tuple(x["sites"]), boxes=tuple(x["boxes"]),
            mass=float(x["mass"]), volume=float(x["volume"]),
            duration=float(x["duration"]), energy=float(x["energy"]),
            soc=float(x["soc"]), delivery=dict(x.get("delivery", {})),
            machine=x.get("machine"), battery_id=x.get("battery_id"),
            start=x.get("start"), return_time=x.get("return"),
        )
        for x in items
    )


def _to_relays(items: list[dict[str, Any]]) -> tuple[RelaySortie, ...]:
    return tuple(
        RelaySortie(
            id=x["id"], machine=x["machine"], component=x["component"],
            point=x["point"], pos=tuple(x["pos"]), start=float(x["start"]),
            active=float(x["active"]), end=float(x["end"]),
            return_time=float(x["return_time"]), energy=float(x["energy"]),
            soc=float(x["soc"]),
        )
        for x in items
    )


# ---------------------------------------------------------------- 逐问方案

def q1() -> CaseResult:
    """问题一：B+C 单点往返组批（18 架次）。"""
    s = _to_sorties(raw()["q1_BC"])
    return CaseResult(
        trips=len(s),
        cmax=max(x.duration for x in s),
        energy=sum(x.energy for x in s),
        sorties=s,
    )


def q1_serial_time_s() -> float:
    """问题一的**累计作业时间**（所有架次历时之和，不是并行完工时刻）。"""
    return sum(x.duration for x in q1().sorties)


def q2(relays: int = 3) -> CaseResult:
    """问题二：多架次异构调度。

    `relays` 取 3 或 4 —— 两套问题三方案复用同一组批与运输能耗，
    仅起飞时刻不同；问题二以 **3 架次配套**为主方案。
    """
    key = "q2_for_three_relays" if relays == 3 else "q2_for_four_relays"
    s = _to_sorties(raw()[key])
    return CaseResult(
        trips=len(s),
        cmax=max(x.return_time or 0.0 for x in s),
        energy=sum(x.energy for x in s),
        sorties=s,
    )


def q3(relays: int = 3) -> CaseResult:
    """问题三：通信约束下的运输与中继联合调度。"""
    key = "q3_three_relays" if relays == 3 else "q3_four_relays"
    q = raw()[key]
    t = q["transport"]
    s = _to_sorties(raw()["q2_for_three_relays" if relays == 3
                         else "q2_for_four_relays"])
    return CaseResult(
        trips=int(t["trips"]),
        cmax=float(t["cmax"]),
        energy=float(t["energy"]),
        sorties=s,
        relays=_to_relays(q["relays"]),
        joint_cmax=float(q["joint_cmax"]),
        total_energy=float(q["total_energy"]),
        radio_samples=int(q["count"]),
        radio_failures=int(q["failure_count"]),
        direct_samples=int(q["direct"]),
        relayed_samples=int(q["relayed"]),
        n_late=int(t.get("late", 0)),
        hard_violations=tuple(t.get("hard", ())),
    )


def verification() -> dict[str, Any]:
    """外部数据集自带的核对结果（逐问 errors 为空、抽检中断 0）。"""
    return raw()["verification"]


def relay_altitude_note() -> str:
    """巡航海拔抬升口径的警示原文（必须随中继方案一起引用）。"""
    return str(raw().get("relay_flight_altitude_note", ""))


def radio_check_note() -> str:
    """通信抽检口径说明（有限采样 ≠ 严格连续证明）。"""
    return str(raw().get("radio_check_note", ""))


RELAY_ALTITUDE_NOTE = relay_altitude_note()
RADIO_CHECK_NOTE = radio_check_note()


# ---------------------------------------------------------------- 派生汇总

def box_deliveries(relays: int = 3) -> dict[str, dict[str, Any]]:
    """逐箱交付明细：{箱号: {架次, 交付时刻, 服务区, 机型}}。

    供“逐箱交付核对表”与论文的交付时刻表使用。
    """
    out: dict[str, dict[str, Any]] = {}
    for i, s in enumerate(q2(relays).sorties, 1):
        sid = f"T{i:02d}"
        for b in s.boxes:
            out[b] = {
                "sortie": sid, "g": s.g,
                "site": s.sites[0] if s.sites else "",
                "delivery_s": s.delivery.get(b),
                "start": s.start, "machine": s.machine,
            }
    return out


def summary() -> dict[str, Any]:
    """四问关键指标汇总（供 metrics.json 与论文表使用）。"""
    a, b3, b4 = q1(), q2(3), q2(4)
    c3, c4 = q3(3), q3(4)
    return {
        "q1": {
            "n_sorties": a.trips,
            "total_energy_kwh": round(a.energy, 6),
            "serial_total_time_s": round(q1_serial_time_s(), 2),
            "type_usage": _type_usage(a.sorties),
        },
        "q2": {
            "n_sorties": b3.trips,
            "cmax_s": round(b3.cmax, 4),
            "total_energy_kwh": round(b3.energy, 6),
            "type_usage": _type_usage(b3.sorties),
            "min_return_soc": round(min(x.soc for x in b3.sorties), 6),
        },
        "q3_three_relays": {
            "n_transport_sorties": c3.trips,
            "n_relay_sorties": len(c3.relays),
            "joint_cmax_s": round(c3.joint_cmax or 0.0, 4),
            "total_energy_kwh": round(c3.total_energy or 0.0, 6),
            "relay_energy_kwh": round(c3.relay_energy or 0.0, 6),
            "radio_samples": c3.radio_samples,
            "radio_failures": c3.radio_failures,
            "direct_samples": c3.direct_samples,
            "relayed_samples": c3.relayed_samples,
            "min_relay_soc": round(min(x.soc for x in c3.relays), 6),
        },
        "q3_four_relays": {
            "n_transport_sorties": c4.trips,
            "n_relay_sorties": len(c4.relays),
            "joint_cmax_s": round(c4.joint_cmax or 0.0, 4),
            "total_energy_kwh": round(c4.total_energy or 0.0, 6),
            "relay_energy_kwh": round(c4.relay_energy or 0.0, 6),
            "radio_samples": c4.radio_samples,
            "radio_failures": c4.radio_failures,
            "min_relay_soc": round(min(x.soc for x in c4.relays), 6),
        },
        "cruise_altitude_convention": CRUISE_ALT_RAISED,
        "relay_altitude_caveat": bool(RELAY_ALTITUDE_NOTE),
    }


def _type_usage(sorties: tuple[Sortie, ...]) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in sorties:
        out[s.g] = out.get(s.g, 0) + 1
    return out
