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
from collections.abc import Sequence
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
    """该中继架次保障的运输架次编号（A 口径下可多于一个）。"""

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


class RelayWindowUnreachable(RuntimeError):
    """★ 中继无法在要求窗口起点前完成建链（严格模式下的显式失败）。

    ADR-031：修复前这里会**静默把服务区间截短**（`svc_end = max(svc_start, window[1])`，
    截到 0 长度也不报错），导致"中继在运输机返航之后才到场"被当成已保障。
    """


@dataclass(frozen=True)
class RelayEvaluation:
    """一次中继架次评估的完整结果（★ 显式暴露"是否真的覆盖了整窗"）。

    字段中的时刻均为绝对时刻（s）。
    """

    link_ready_s: float
    """建链完成时刻。"""
    service_start_s: float
    """实际开始服务的时刻（= max(建链完成, 窗口起点)）。"""
    service_end_s: float
    """实际结束服务的时刻（= max(service_start, 窗口终点)）。"""
    return_s: float
    """返回 O01 的时刻。"""
    energy_kwh: float
    soc_end: float
    flight_time_s: float
    """悬停点往返飞行时间。"""
    window: tuple[float, float]
    """被要求保障的服务窗口（全部区间的包络；单区间时即该区间本身）。"""
    full_coverage: bool
    """★ 中继是否在**每個**区间的起点之前已建链完毕（即整窗被覆盖）。"""
    gap_s: float
    """未获保障的时长合计：Σ max(0, 建链完成 − 各区间起点)。0 表示覆盖完整。"""
    max_service_s: float
    """★ 续航上限（可用能量 ÷ 服务功率，不含往返飞行），用于判定窗口本身是否可行。"""
    n_gaps: int = 0
    """未能按时到站的中断区间个数。"""
    service_windows: tuple[tuple[float, float], ...] = ()
    """实际被保障的区间集合（`strict=False` 时可能少于要求）。"""


def _merge_intervals(windows: Sequence[tuple[float, float]]
                     ) -> tuple[tuple[float, float], ...]:
    """把可能重叠/相接的区间合并成互不相交的升序区间。"""
    out: list[list[float]] = []
    for a, b in sorted(windows):
        if out and a <= out[-1][1] + 1e-9:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return tuple((a, b) for a, b in out)


def evaluate_relay_sortie(
    spec: RelaySpec,
    hover: HoverCandidate,
    provider: ElevationProvider,
    o01: Node,
    leg_cache: LegCache,
    service_window: tuple[float, float]
    | Sequence[tuple[float, float]] | None = None,
    start_s: float = 0.0,
    sample_step_m: float = 30.0,
    strict: bool = False,
    *,
    service_windows: Sequence[tuple[float, float]] | None = None,
) -> RelayEvaluation | None:
    """评估中继架次。

    `service_window` 可以是**单个区间** `(a, b)`，也可以是**区间集合**
    `[(a1,b1), (a2,b2), ...]`。★★ 区间集合是正确口径：一个架次的中断可能分成
    好几段，中间夹着"直连本身可用"的时段 —— 那里**不需要**中继。
    若用包络 `(首段起点, 末段终点)` 当需求，中继会被迫多悬停 39%（实测），
    既浪费续航又压低可保障的架次数。见 `service_windows` 关键字参数（等价写法）。

    返回 `RelayEvaluation`（含 `full_coverage` / `gap_s`）。

    `strict=True` 时，若中继**无法在任一区间起点前完成建链**，返回 `None`
    表示该架次不可行（不再静默截短服务区间）—— 这是排班必须遵守的硬约束。

    时间：
        start → 准备 → 爬升 → 巡航 → 下降 （到达悬停点）
              → 建链(link_setup) → 服务各区间 → 返航
    能耗 = 去程(爬升附加 + 水平巡航) + 悬停服务(各区间时长之和) + 回程(水平巡航 + 爬升附加)
    """
    from src.physics.energy import climb_energy_kwh, segment_energy_kwh

    if service_windows is None:
        if service_window is None:
            raise TypeError("必须给出 service_window 或 service_windows")
        raw = service_window
        # 区分"单区间"与"区间集合"
        if raw and isinstance(raw[0], (int, float)):
            windows = _merge_intervals([(float(raw[0]), float(raw[1]))])  # type: ignore[index]
        else:
            windows = _merge_intervals([(float(a), float(b)) for a, b in raw])  # type: ignore[misc]
    else:
        windows = _merge_intervals([(float(a), float(b)) for a, b in service_windows])
    if not windows:
        raise ValueError("服务窗口集合不能为空")

    out_g, back_g = relay_leg_geometry(provider, o01, hover, sample_step_m)
    seg_out = Segment(out_g.distance_m, out_g.climb_m, out_g.descent_m)
    seg_back = Segment(back_g.distance_m, back_g.climb_m, back_g.descent_m)

    # 时间
    t = start_s + spec.prepare_time_s
    t += segment_time_s(_relay_as_uav(spec), seg_out)
    reach_s = t
    link_ready = reach_s + spec.link_setup_time_s

    # ★★ ADR-031 修复点：每个中断区间都必须被覆盖
    #   建链必须**早于**各区间起点，否则该区间的前段无人保障。
    gaps = [(a, b) for a, b in windows if link_ready > a + 1e-9]
    full_coverage = not gaps
    if strict and not full_coverage:
        # 硬约束：中继来不及到站 ⇒ 该架次不可行（绝不静默截短）
        return None

    # 实际在站服务时长 = 各区间被覆盖部分之和（中继最多在站到最后一个区间终点）
    service_s = sum(max(0.0, b - max(link_ready, a)) for a, b in windows)
    gap_s = sum(max(0.0, link_ready - a) for a, b in windows)
    covered_windows = tuple(
        (max(link_ready, a), b) for a, b in windows if b > max(link_ready, a) + 1e-9
    )
    svc_start = max(link_ready, windows[0][0])
    svc_end = max(windows[-1][1], link_ready)
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
    e_service = spec.service_power_kw * service_s / 3600.0
    e_total = e_out + e_back + e_service
    soc = max(0.0, 1.0 - e_total / spec.energy_kwh)
    flight_time = segment_time_s(_relay_as_uav(spec), seg_out) + segment_time_s(
        _relay_as_uav(spec), seg_back
    )
    return RelayEvaluation(
        link_ready_s=link_ready,
        service_start_s=svc_start,
        service_end_s=svc_end,
        return_s=return_s,
        energy_kwh=e_total,
        soc_end=soc,
        flight_time_s=flight_time,
        window=(windows[0][0], windows[-1][1]),
        full_coverage=full_coverage,
        gap_s=gap_s,
        max_service_s=spec.energy_budget_kwh / spec.service_power_kw * 3600.0,
        n_gaps=len(gaps),
        service_windows=covered_windows,
    )


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


# ------------------------------------------------- 服务窗口驱动的中继排班（ADR-031）

@dataclass(frozen=True)
class RelayRequest:
    """一个运输架次的**保障需求**：必须在 `windows` 各段内被中继覆盖。

    ★ `windows` 是**真实中断区间集合**（可能多段，中间夹着直连可用的时段）。
    用包络当需求会让中继多悬停约 39%（实测），既浪费续航又压低可保障架次数。

    `candidates` 是能覆盖该架次全部中断样本的悬停点（按能耗升序），
    由选址阶段给出 —— 排班只负责挑点与排时间，不重做几何搜索。
    """

    sortie_id: str
    windows: tuple[tuple[float, float], ...]
    candidates: tuple[HoverCandidate, ...]

    @property
    def window(self) -> tuple[float, float]:
        """全部中断区间的包络（仅用于展示/排序）。"""
        return (self.windows[0][0], self.windows[-1][1])


@dataclass
class PlannedRelaySortie:
    """排班产出的一个中继架次（可同时保障多个运输架次 —— A 口径）。"""

    sortie_id: str
    relay_uav_id: str
    energy_pack_id: str
    hover: HoverCandidate
    start_s: float
    evaluation: RelayEvaluation
    covers: tuple[str, ...]

    @property
    def link_ready_s(self) -> float:
        return self.evaluation.link_ready_s

    @property
    def service_start_s(self) -> float:
        return self.evaluation.service_start_s

    @property
    def service_end_s(self) -> float:
        return self.evaluation.service_end_s

    @property
    def return_s(self) -> float:
        return self.evaluation.return_s


def plan_relay_sorties(
    spec: RelaySpec,
    requests: Sequence[RelayRequest],
    provider: ElevationProvider,
    o01: Node,
    leg_cache: LegCache,
    relay_uav_ids: Sequence[str],
    n_energy_packs: int,
    turnaround_s: float | None = None,
    pack_t_full_s: float = 1800.0,
    sample_step_m: float = 30.0,
    share: bool = True,
) -> tuple[list[PlannedRelaySortie], list[dict]]:
    """★ 把保障需求排成中继架次，**把服务窗口当作硬约束**（ADR-031 修复）。

    规则
    ----
    1. 每个需求都必须在**其每个中断区间的起点之前**完成建链（`strict=True`）。
       资源来不及 ⇒ 记为不可行，**绝不放宽窗口**（旧实现会静默截短）。
    2. `share=True` 时（A 口径）：**同一悬停点可被多架运输机共享** ——
       若已有中继架次的悬停点也能覆盖本需求，则复用同一架次
       （题目只限制"每架运输机任一时刻只能由 G01 或一架中继保障"，
       未限制一架中继的服务对象数量）。
    3. 同一中继无人机的相邻架次之间须留出**架次周转时间**；
       能源组件还需**充电完成**后才能再次投入。

    ★ 共享时按**区间并集**评估（不取包络）：若两架次的中断区间接得上，
    并集几乎不增加在站时长；取包络则会凭空多出中间那段"其实直连可用"的时间。

    返回 `(中继架次列表, 逐需求判定记录)`。
    """
    turn = spec.turnaround_time_s if turnaround_s is None else turnaround_s
    uav_avail = {u: 0.0 for u in relay_uav_ids}
    pack_avail = {f"R-P{i:02d}": 0.0 for i in range(1, n_energy_packs + 1)}
    planned: list[PlannedRelaySortie] = []
    records: list[dict] = []

    for req in sorted(requests, key=lambda r: (r.window[0], r.sortie_id)):
        need_a = req.window[0]

        # ---- 1. A 口径：能否并入已有中继架次（同一悬停点共享）----
        if share:
            shared = False
            for ps in planned:
                if ps.hover not in req.candidates:
                    continue
                merged = _merge_intervals(
                    [*ps.evaluation.service_windows, *req.windows]
                    if ps.evaluation.service_windows else req.windows
                )
                ev = evaluate_relay_sortie(
                    spec, ps.hover, provider, o01, leg_cache, merged,
                    ps.start_s, sample_step_m=sample_step_m, strict=True,
                )
                if ev is None or ev.soc_end < spec.reserve_ratio:
                    continue
                ps.evaluation = ev
                ps.covers = (*ps.covers, req.sortie_id)
                records.append({"sortie_id": req.sortie_id, "feasible": True,
                                "shared_with": ps.sortie_id,
                                "link_ready_s": ev.link_ready_s,
                                "window_start_s": need_a, "gap_s": 0.0})
                shared = True
                break
            if shared:
                continue

        # ---- 2. 新开一个中继架次 ----
        best = None
        for hover in req.candidates:
            t_fly = _flight_time(spec, hover, provider, o01, sample_step_m)
            lead = spec.prepare_time_s + t_fly + spec.link_setup_time_s
            for ru, ru_ready in uav_avail.items():
                for pk, pk_ready in pack_avail.items():
                    start = max(ru_ready, pk_ready)
                    if start + lead > need_a + 1e-6:
                        # 该组合来不及在首个区间起点前建链
                        continue
                    ev = evaluate_relay_sortie(
                        spec, hover, provider, o01, leg_cache, req.windows,
                        start, sample_step_m=sample_step_m, strict=True,
                    )
                    if ev is None or ev.soc_end < spec.reserve_ratio:
                        continue
                    score = (ev.energy_kwh, start)
                    if best is None or score < best[0]:
                        best = (score, hover, ru, pk, start, ev)
        if best is None:
            records.append({"sortie_id": req.sortie_id, "feasible": False,
                            "reason": "无可用中继资源或窗口内续航不足",
                            "window_start_s": need_a,
                            "window_end_s": req.window[1],
                            "window_duration_s": sum(b - a for a, b in req.windows)})
            continue

        _, hover, ru, pk, start, ev = best
        ps = PlannedRelaySortie(
            sortie_id=f"RT{len(planned) + 1:02d}", relay_uav_id=ru,
            energy_pack_id=pk, hover=hover, start_s=start,
            evaluation=ev, covers=(req.sortie_id,),
        )
        planned.append(ps)
        uav_avail[ru] = ps.return_s + turn
        pack_avail[pk] = ps.return_s + charging_time(ev.soc_end, pack_t_full_s)
        records.append({"sortie_id": req.sortie_id, "feasible": True,
                        "relay_sortie": ps.sortie_id,
                        "link_ready_s": ev.link_ready_s,
                        "window_start_s": need_a, "gap_s": ev.gap_s})

    return planned, records


def _flight_time(
    spec: RelaySpec,
    hover: HoverCandidate,
    provider: ElevationProvider,
    o01: Node,
    sample_step_m: float,
) -> float:
    """悬停点往返飞行时间（供排班估算"最晚必须几点起飞"）。"""
    out_g, back_g = relay_leg_geometry(provider, o01, hover, sample_step_m)
    return (
        segment_time_s(_relay_as_uav(spec),
                       Segment(out_g.distance_m, out_g.climb_m, out_g.descent_m))
        + segment_time_s(_relay_as_uav(spec),
                         Segment(back_g.distance_m, back_g.climb_m, back_g.descent_m))
    )
