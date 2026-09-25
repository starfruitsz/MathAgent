"""问题三：**联合时间线诊断** —— 在最终方案（本仓重排的运输时刻 + 中继架次）上
沿完整轨迹逐时刻判定「直连 / 中继 / 中断」三态，并给出**两条链路的最小裕量**。

为什么需要这一层（与 `coverage.py` 的分工）
-------------------------------------------
`coverage.py` 解决的是**选址**问题：给定一个悬停点，判断它能否覆盖某架次的全部
中断样本（用于候选点扫描，要求快）。它不回答“最终方案在时间轴上到底有没有断”。

本模块回答的是**最终方案的连续通信结论**，因此必须：

1. 用 `Plan` 里**本仓 CP-SAT 重排后的**起飞/返回时刻（而不是给定数据的时刻）；
2. 每个采样时刻只在“当时**确实在站**”的中继里挑一个可用的（在中继起飞前 /
   返航后，该中继不能算作保障来源）；
3. 同时记录**最小链路裕量** `裕量 = 双向门限 − 实际路损`（越小越危险，
   裕量 < 0 即不可用），这是 SKILL 要求的“逐时刻直连/中继状态及最小链路裕量图”
   的数据来源；
4. 采样步长按 `sample_dt_s`（默认 0.25 s）显式给出，并在结论里如实声明
   “有限采样，不构成连续时间的数学证明”。

口径警示（随数值一起传播）
--------------------------
最终方案的**巡航海拔**取 `max(沿线 DEM 最高 + 50 m, 悬停海拔)`，
其中第二项是**显式扩展模型**（见 `solution_data.RELAY_ALTITUDE_NOTE`）。
本模块沿用该口径，故结论只在同一口径下成立。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from src.comms.link import (
    CommsParams,
    DEFAULT_PARAMS,
    EndpointKind,
    bidirectional_max_loss_db,
    distance_3d_m,
    path_loss_db,
)
from src.comms.los import has_terrain_obstruction
from src.geo.dem import ElevationProvider
from src.q3_comms_relay.coverage import Sample, sample_trajectory

# ---------------------------------------------------------------- 数据结构


@dataclass(frozen=True)
class SortieTimeline:
    """一个运输架次在最终方案下的连续通信诊断结果。"""

    sortie_id: str
    type_code: str
    sites: tuple[str, ...]
    n_samples: int
    n_direct: int
    n_relay: int
    n_outage: int
    outage_fraction: float
    min_margin_direct_db: float | None
    """直连链路最小裕量（门限 − 路损，dB）；全程未采样到则为 None。"""
    min_margin_relay_db: float | None
    """中继接入链路最小裕量（仅统计需要中继的中断样本）。"""
    n_relay_source_change: bool
    """该架次是否出现过“保障来源切换”（中继架次换班）。"""
    first_outage_s: float | None
    last_outage_s: float | None
    time_lo_s: float
    time_hi_s: float


@dataclass
class TimelineDiagnosis:
    """全部架次的诊断汇总。"""

    sorties: list[SortieTimeline]
    sample_dt_s: float
    los_step_m: float

    @property
    def total_samples(self) -> int:
        return sum(s.n_samples for s in self.sorties)

    @property
    def total_outage(self) -> int:
        return sum(s.n_outage for s in self.sorties)

    @property
    def n_need_relay(self) -> int:
        return sum(1 for s in self.sorties if s.n_outage > 0 or s.n_relay > 0)

    @property
    def n_fully_covered(self) -> int:
        return sum(1 for s in self.sorties if s.n_outage == 0)

    @property
    def mean_outage_fraction(self) -> float:
        if not self.sorties:
            return 0.0
        return sum(s.outage_fraction for s in self.sorties) / len(self.sorties)

    @property
    def min_margin_direct_db(self) -> float | None:
        vals = [s.min_margin_direct_db for s in self.sorties
                if s.min_margin_direct_db is not None]
        return min(vals) if vals else None

    @property
    def min_margin_relay_db(self) -> float | None:
        vals = [s.min_margin_relay_db for s in self.sorties
                if s.min_margin_relay_db is not None]
        return min(vals) if vals else None


# ---------------------------------------------------------------- 单点判定


def _margin_db(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    kind_a: EndpointKind,
    kind_b: EndpointKind,
    params: CommsParams,
    provider: ElevationProvider,
    los_step_m: float,
) -> float:
    """返回该链路在此时的**裕量**（dB）= 双向门限 − 实际路损。

    裕量 ≥ 0 ⇔ 链路可用。遮挡按地形视线判定附加固定衰减（`params` 内部口径）。
    """
    d = distance_3d_m(a[0], a[1], a[2], b[0], b[1], b[2])
    blocked = has_terrain_obstruction(
        provider, a[0], a[1], a[2], b[0], b[1], b[2], sample_step_m=los_step_m
    )
    loss = path_loss_db(params, d, obstructed=blocked)
    return bidirectional_max_loss_db(params, kind_a, kind_b) - loss


# ---------------------------------------------------------------- 主流程


def diagnose(
    plan,
    uav_types: dict,
    leg_cache,
    nodes_xy: dict[str, tuple[float, float]],
    provider: ElevationProvider,
    gateway_pos: tuple[float, float, float],
    *,
    sample_dt_s: float = 0.25,
    los_step_m: float = 60.0,
    center_id: str = "O01",
    params: CommsParams | None = None,
) -> TimelineDiagnosis:
    """对最终方案做逐时刻连续通信诊断。

    参数
    ----
    plan : `src.q2_transport_schedule.solution.Plan`
        本仓装配的最终方案（运输架次**已重排**，中继架次带在站窗口）。
    sample_dt_s : float
        时间采样步长（s）。最终方案取 0.25 s。
    """
    p = params or DEFAULT_PARAMS
    out: list[SortieTimeline] = []

    for s in plan.transport:
        uav = uav_types[s.type_code]
        per_stop = _boxes_per_stop(s)
        samples: list[Sample] = sample_trajectory(
            tuple(s.sites), per_stop, uav, leg_cache, nodes_xy,
            s.start_s, center_id=center_id, dt_s=sample_dt_s,
        )
        if not samples:
            continue
        t0, t1 = samples[0].t_s, samples[-1].t_s

        n_d = n_r = n_o = 0
        m_dir: float | None = None
        m_rel: float | None = None
        first_o: float | None = None
        last_o: float | None = None
        used_sources: set[str] = set()

        for sm in samples:
            pos = (sm.lon, sm.lat, sm.alt_m)
            m = _margin_db(pos, gateway_pos, EndpointKind.TRANSPORT,
                           EndpointKind.GATEWAY, p, provider, los_step_m)
            m_dir = m if m_dir is None else min(m_dir, m)
            if m >= 0.0:
                n_d += 1
                continue
            # 直连不可用 → 在**当时在站**的中继中找一个接入段可用的
            best: tuple[float, str] | None = None
            for r in plan.relays:
                if not (r.link_ready_s <= sm.t_s <= r.service_end_s):
                    continue
                rpos = (r.lon, r.lat, r.alt_m)
                mr = _margin_db(pos, rpos, EndpointKind.TRANSPORT,
                                EndpointKind.RELAY_ACCESS, p, provider, los_step_m)
                if mr < 0.0:
                    continue
                # 回传段与运输机位置无关，对每个中继只算一次
                mb = _backhaul_margin_cached(r, gateway_pos, p, provider,
                                             los_step_m, cache=_BACKHAUL_CACHE)
                if mb < 0.0:
                    continue
                if best is None or mr > best[0]:
                    best = (mr, r.relay_sortie_id)
            if best is not None:
                n_r += 1
                m_rel = best[0] if m_rel is None else min(m_rel, best[0])
                used_sources.add(best[1])
                continue
            n_o += 1
            if first_o is None:
                first_o = sm.t_s
            last_o = sm.t_s

        nt = len(samples)
        out.append(SortieTimeline(
            sortie_id=s.sortie_id, type_code=s.type_code, sites=tuple(s.sites),
            n_samples=nt, n_direct=n_d, n_relay=n_r, n_outage=n_o,
            outage_fraction=(n_o / nt) if nt else 0.0,
            min_margin_direct_db=m_dir, min_margin_relay_db=m_rel,
            n_relay_source_change=len(used_sources) > 1,
            first_outage_s=first_o, last_outage_s=last_o,
            time_lo_s=t0, time_hi_s=t1,
        ))
    return TimelineDiagnosis(sorties=out, sample_dt_s=sample_dt_s, los_step_m=los_step_m)


_BACKHAUL_CACHE: dict[tuple, float] = {}


def _backhaul_margin_cached(relay, gateway_pos, params, provider, los_step_m,
                            cache: dict) -> float:
    """中继↔G01 回传裕量（同一中继的几何固定，缓存避免重复 LOS 扫描）。"""
    key = (relay.relay_sortie_id, relay.lon, relay.lat, relay.alt_m,
           gateway_pos, los_step_m)
    if key not in cache:
        cache[key] = _margin_db(
            (relay.lon, relay.lat, relay.alt_m), gateway_pos,
            EndpointKind.RELAY_BACKHAUL, EndpointKind.GATEWAY,
            params, provider, los_step_m,
        )
    return cache[key]


def to_state_series(plan, uav_types, leg_cache, nodes_xy, provider,
                    gateway_pos, *, sample_dt_s: float = 0.25,
                    los_step_m: float = 60.0, center_id: str = "O01",
                    params: CommsParams | None = None) -> list[dict]:
    """逐时刻**通信状态**序列（直连 / 中继 / 中断），供重采样敏感性分析。

    与 `diagnose()` 同一物理口径；`diagnose()` 只给逐架次汇总，
    本函数把每个采样时刻的状态留下，因此可以对它做"按更粗步长重采样"
    的对照实验 —— 这是回答"结论对采样步长是否稳健"的唯一正确做法。

    ★ 必须用**与最终诊断相同的步长**（默认 0.25 s）：若用更粗的基准序列
      去做重采样对照，重采样本身就退化成同一份粗数据，曲线会是一条平线
      （踩过的坑：用 1 s 基准序列时 0.25~30 s 的中断率全为 0，因为那 203 个
      中断样本在 1 s 网格上被判成了中继/直连）。
    """
    p = params or DEFAULT_PARAMS
    rows: list[dict] = []
    for s in plan.transport:
        uav = uav_types[s.type_code]
        samples = sample_trajectory(
            tuple(s.sites), _boxes_per_stop(s), uav, leg_cache, nodes_xy,
            s.start_s, center_id=center_id, dt_s=sample_dt_s,
        )
        for sm in samples:
            pos = (sm.lon, sm.lat, sm.alt_m)
            md = _margin_db(pos, gateway_pos, EndpointKind.TRANSPORT,
                            EndpointKind.GATEWAY, p, provider, los_step_m)
            state = "直连"
            if md < 0.0:
                state = "中断"
                for r in plan.relays:
                    if not (r.link_ready_s <= sm.t_s <= r.service_end_s):
                        continue
                    mb = _backhaul_margin_cached(r, gateway_pos, p, provider,
                                                 los_step_m, cache=_BACKHAUL_CACHE)
                    if mb < 0.0:
                        continue
                    ma = _margin_db(pos, (r.lon, r.lat, r.alt_m),
                                    EndpointKind.TRANSPORT,
                                    EndpointKind.RELAY_ACCESS, p, provider,
                                    los_step_m)
                    if ma >= 0.0:
                        state = "中继"
                        break
            rows.append({"架次编号": s.sortie_id, "时刻（s）": round(sm.t_s, 3),
                         "阶段": sm.phase, "状态": state})
    return rows


def _boxes_per_stop(s) -> dict[str, int]:
    """该架次每个停靠点交付的箱数（本方案均为单点，故等于全部箱数）。"""
    return {site: len(s.box_ids) for site in s.sites}


# ---------------------------------------------------------------- 落盘

def to_rows(d: TimelineDiagnosis) -> list[dict]:
    """转成表格行（列名与论文表一致）。"""
    return [{
        "架次编号": s.sortie_id, "机型": s.type_code,
        "服务区": "->".join(s.sites),
        "采样点数": s.n_samples, "直连点数": s.n_direct,
        "中继点数": s.n_relay, "中断点数": s.n_outage,
        "直连可达比例": round(s.n_direct / s.n_samples, 4) if s.n_samples else 0.0,
        "中断占比": round(s.outage_fraction, 6),
        "直连最小裕量（dB）": (round(s.min_margin_direct_db, 2)
                              if s.min_margin_direct_db is not None else None),
        "中继最小裕量（dB）": (round(s.min_margin_relay_db, 2)
                              if s.min_margin_relay_db is not None else None),
        "保障来源切换": "是" if s.n_relay_source_change else "否",
        "首个中断时刻（s）": (round(s.first_outage_s, 2)
                              if s.first_outage_s is not None else None),
        "末个中断时刻（s）": (round(s.last_outage_s, 2)
                              if s.last_outage_s is not None else None),
        "需中继": "是" if (s.n_outage or s.n_relay) else "否",
    } for s in d.sorties]


def to_min_margin_series(plan, uav_types, leg_cache, nodes_xy, provider,
                         gateway_pos, *, sample_dt_s: float = 1.0,
                         los_step_m: float = 60.0, center_id: str = "O01",
                         params: CommsParams | None = None) -> list[dict]:
    """逐时刻**最小链路裕量**序列（供“最小链路裕量图”直接绘制）。

    与 `diagnose()` 同一物理口径，只是把每个采样时刻的裕量都留下：
        直连可用            → 记录直连裕量
        直连不可用但中继可用 → 记录中继链路裕量（接入段与回传段取小）
        其余                → 记录直连裕量（负值）并标为中断
    """
    p = params or DEFAULT_PARAMS
    rows: list[dict] = []
    for s in plan.transport:
        uav = uav_types[s.type_code]
        samples = sample_trajectory(
            tuple(s.sites), _boxes_per_stop(s), uav, leg_cache, nodes_xy,
            s.start_s, center_id=center_id, dt_s=sample_dt_s,
        )
        for sm in samples:
            pos = (sm.lon, sm.lat, sm.alt_m)
            md = _margin_db(pos, gateway_pos, EndpointKind.TRANSPORT,
                            EndpointKind.GATEWAY, p, provider, los_step_m)
            if md >= 0.0:
                rows.append({"架次编号": s.sortie_id, "时刻（s）": round(sm.t_s, 3),
                             "阶段": sm.phase, "状态": "直连",
                             "链路裕量（dB）": round(md, 3)})
                continue
            best = None
            for r in plan.relays:
                if not (r.link_ready_s <= sm.t_s <= r.service_end_s):
                    continue
                rpos = (r.lon, r.lat, r.alt_m)
                ma = _margin_db(pos, rpos, EndpointKind.TRANSPORT,
                                EndpointKind.RELAY_ACCESS, p, provider, los_step_m)
                mb = _backhaul_margin_cached(r, gateway_pos, p, provider,
                                             los_step_m, cache=_BACKHAUL_CACHE)
                mm = min(ma, mb)
                if best is None or mm > best:
                    best = mm
            if best is not None and best >= 0.0:
                rows.append({"架次编号": s.sortie_id, "时刻（s）": round(sm.t_s, 3),
                             "阶段": sm.phase, "状态": "中继",
                             "链路裕量（dB）": round(best, 3)})
            else:
                rows.append({"架次编号": s.sortie_id, "时刻（s）": round(sm.t_s, 3),
                             "阶段": sm.phase, "状态": "中断",
                             "链路裕量（dB）": round(md, 3)})
    return rows
