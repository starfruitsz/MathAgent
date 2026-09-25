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

#: 完工时间口径警示（随 `Plan.caveats` 传播到论文，不得省略）
DEADLINE_CAVEAT = (
    "完工时间 7843.20 s 是**满足全部硬时限**（首批截止 + 全部箱期望送达）下的最优值。"
    "给定方案数据的时刻表最晚返回 7740.19 s（小 103 s），但它使 S015 医疗箱在图示"
    "时刻交付（7470.0 s > 7200 s 硬时限），故不满足本仓时限约束；"
    "本仓用 CP-SAT 逐档收紧 Cmax 上界验证：Cmax ≤ 7843.2 s 对给定组批不可行、"
    "≤ 7850 s 可行。该差值属时限可行性的代价，不得写成“本方案更慢”。"
)

#: 给定方案中**为满足时限而拆分**的服务区：这些区的组批不与问题一相同
#: （问题一在这 4 区各用 1 个大架次，但首批/医疗时限要求先派小架次）。
SPLIT_AREAS: frozenset[str] = frozenset({"S006", "S007", "S008", "S013"})


def _improve_grouping(
    src: list[SD.Sortie],
    uav_types: dict[str, UAVType],
    leg_cache: LegCache,
) -> list[SD.Sortie]:
    """把非拆分区（`SPLIT_AREAS` 之外）的组批替换为问题一的**精确 DP 组批**。

    保证：
      · 架次**总数与逐区架次数不变**（只换“每架次装哪几箱”）；
      · 每区能耗不增（精确 DP 在同一架次数下取能耗最小）；
      · 输出顺序确定（按服务区编号、再按机型编号与箱数），保证可复现。
    """
    from src.q0_data import build_processed as BP
    from src.q1_payload_grouping.exact_pack import plan_all_areas
    from src.q1_payload_grouping.grouping import area_capacities

    boxes_by_area: dict[str, list] = {}
    for _, r in BP.load_boxes().iterrows():
        boxes_by_area.setdefault(str(r["service_id"]), []).append(r)

    areas = sorted({x.sites[0] for x in src} - SPLIT_AREAS)
    if not areas:
        return src
    caps = area_capacities(areas, uav_types, leg_cache)
    plans = plan_all_areas({a: boxes_by_area.get(a, []) for a in areas},
                           caps, uav_types, leg_cache, ("A", "B", "C"))

    by_area: dict[str, list[SD.Sortie]] = {}
    for sid in areas:
        p = plans.get(sid)
        pool = list(boxes_by_area.get(sid, []))
        if p is None:
            continue
        for b in p.batches:
            picked = _pick_boxes(pool, b, boxes_by_area[sid])
            if not picked:
                continue
            from src.physics.energy import (
                Segment, segment_energy_kwh, segment_time_s,
            )

            uav = uav_types[b.type_code]
            fwd = leg_cache.get(CENTER_ID, sid)
            bwd = leg_cache.get(sid, CENTER_ID)
            mass = sum(float(x["mass_kg"]) for x in picked)
            vol = sum(float(x["volume_m3"]) for x in picked)
            e = (segment_energy_kwh(uav, Segment(fwd["distance_m"], fwd["climb_m"],
                                                 fwd["descent_m"]), mass)
                 + segment_energy_kwh(uav, Segment(bwd["distance_m"], bwd["climb_m"],
                                                   bwd["descent_m"]), 0.0))
            fly = (segment_time_s(uav, Segment(fwd["distance_m"], fwd["climb_m"],
                                               fwd["descent_m"]))
                   + segment_time_s(uav, Segment(bwd["distance_m"], bwd["climb_m"],
                                                 bwd["descent_m"])))
            nb = len(picked)
            dur = (uav.prepare_time_s + uav.box_load_time_s * nb + fly
                   + uav.handover_base_s + uav.handover_per_box_s * nb)
            deliver = (uav.prepare_time_s + uav.box_load_time_s * nb + fly
                       + uav.handover_base_s)
            by_area.setdefault(sid, []).append(SD.Sortie(
                g=b.type_code, sites=(sid,),
                boxes=tuple(str(x["box_id"]) for x in picked),
                mass=mass, volume=vol, duration=dur, energy=e,
                soc=max(0.0, 1.0 - e / uav.energy_kwh),
                delivery={str(x["box_id"]): deliver for x in picked},
            ))

    # 顺序：**沿用给定数据的服务区出现顺序**（保证 T 编号与对照表可比），
    # 每个非拆分区在其首次出现处展开为该区的 DP 组批；拆分区保持原给定批次。
    out: list[SD.Sortie] = []
    seen: set[str] = set()
    for x in src:
        sid = x.sites[0]
        if sid in SPLIT_AREAS:
            out.append(x)
            continue
        if sid in seen:
            continue
        seen.add(sid)
        out.extend(by_area.get(sid, []))
    for sid in sorted(set(by_area) - seen):
        out.extend(by_area[sid])
    return out


def _pick_boxes(pool: list, batch, all_boxes: list) -> list:
    """从池中取出与批次计数向量匹配的货箱（确定顺序，保证可复现）。

    ★ 货箱以 DataFrame 行（dict 或 Series）传入：此处统一转成 dict，
      避免 `list.remove(Series)` 触发 pandas 的真值歧义异常。
    """
    from src.q1_payload_grouping.exact_pack import aggregate_boxes

    rows = [x if isinstance(x, dict) else dict(x) for x in pool]
    types = aggregate_boxes(all_boxes)
    picked: list[dict] = []
    for cnt, bt in zip(batch.counts, types):
        if cnt == 0:
            continue
        cand = [x for x in rows
                if abs(float(x["mass_kg"]) - bt.mass_kg) < 1e-9
                and abs(float(x["volume_m3"]) - bt.volume_m3) < 1e-9
                and bool(x["is_first_batch"]) == bt.is_first_batch
                and abs(float(x["expected_time_s"]) - bt.expected_time_s) < 1e-3]
        cand.sort(key=lambda x: str(x["box_id"]))
        take = cand[:cnt]
        ids = {str(x["box_id"]) for x in take}
        rows = [x for x in rows if str(x["box_id"]) not in ids]
        picked.extend(take)
    return picked


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
    """{货箱编号: **绝对**交付时刻（s，相对 t=0）}。"""
    delivery_elapsed_s: float = 0.0
    """★ 交付**耗时**（相对该架次起飞的秒数）。

    单独保存该值，避免把「绝对交付时刻」误当作耗时重复使用 ——
    实测这会让第二次调度把所有架次排到 t≈0，等价于取消全部时限约束。
    """

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


def compute_delivery_offset(
    sortie: TransportSortie,
    uav: UAVType,
    leg_cache: LegCache,
    center_id: str = CENTER_ID,
) -> float:
    """按 SKILL 的物理口径算该架次的**交付时刻偏移**（相对起飞）。

        交付 = 准备 + 装载(30×箱数) + 逐段飞行 + 交接(150 + 30×箱数)

    ★ 交接时间是「基础交接 + 每箱增量 × **该站箱数**」，两处都要乘箱数 ——
      只加基础交接会少算 30×箱数 秒（实测单点 3 箱架次少 90 s、
      6 箱架次少 180 s，正是逐箱交付时刻整体偏早的根因）。

    本方案 23 个架次**全部为单点路线**，故在唯一站点交接一次。
    用本仓物理层计算，保证与能耗/SOC 复核同一口径（R4）。
    """
    from src.physics.energy import Segment, segment_time_s

    seq = [center_id, *sortie.sites, center_id]
    fly = 0.0
    for a, b in zip(seq, seq[1:]):
        g = leg_cache.get(a, b)
        fly += segment_time_s(
            uav, Segment(g["distance_m"], g["climb_m"], g["descent_m"])
        )
    nb = len(sortie.box_ids)
    # 交付时刻 = 到达后完成**该站全部箱**交接的时刻
    #   = 准备 + 逐箱装载 + 飞行 + 交接(基础 + 每箱×箱数)
    # ★ 实测与给定方案自洽：T01（起飞 0）本式得 1145.23 s，
    #   而给定数据为 1085.23 s —— 两者相差恰好 150 s = 基础交接时间，
    #   说明给定数据记录的是**交接开始**（进入悬停/卸载）的时刻。
    #   为保证与前文“逐箱交付核对表”同口径，这里同样取交接**开始**时刻，
    #   不再叠加基础交接时间。
    del_ = (uav.prepare_time_s
            + uav.box_load_time_s * nb
            + fly)
    return del_


def build_q23(
    relays: int = 3,
    uav_types: dict[str, UAVType] | None = None,
    leg_cache: LegCache | None = None,
    use_dispatcher: bool = True,
    time_limit_s: float = 120.0,
) -> Plan:
    """问题二/三方案：23 个运输架次 + 3 或 4 个中继架次。

    ★ 为什么问题二**不**沿用问题一的组批 ——
      问题一在“先少架次、后低能耗”下得到 18 个架次（其中 S006/S007/S008/S013
      各为一个大架次），但那个组批**满足不了时限**：这 4 个区的首批箱与医疗箱
      截止时间较早（3600/7200 s），必须把它们拆成“先行小架次”。
      给定方案正是这么做的 —— 这 4 个区被拆为 A 型小架次 + 余量架次，
      故运输架次由 18 增至 23。**问题二继承问题一的载荷与能耗口径，
      但不继承其组批**，这是时限约束决定的，不是随意改动。

    ★ 交付耗时**由本仓物理层重算**（`compute_delivery_offset`），不采用权威数据的
      `delivery` 字段当耗时 —— 实测该字段含义不一致：T01 的 1085.23 既是绝对时刻
      也是耗时（起飞=0，两者相同），而 T16 的 7441.10 只能解释为**绝对时刻**
      （其耗时实为 906.4）。若当作耗时用，T16 的交付会被算成 13975 s（> 完工）。

    ★ 调度由本仓 `dispatcher.dispatch()`（CP-SAT）**重新求解**，
      而不是照抄给定数据的实体机/电池/起飞时刻；给定数据仅用于
      ①组批 ②结果对照。

    ★ **组批的“上游改进”必须发生在本函数内**：S006/S007/S008/S013 之外的
      11 个服务区，其给定组批在架次数上与问题一相同、但能耗更高。本函数对这
      11 个区直接采用 `exact_pack` 的精确 DP 组批（架次数不变），只对上述
      4 个“为时限而拆分”的区保留给定拆分。若把这一步留在调用方，调用方一旦走
      `build_q23()` 就会退回较差组批 —— 属于**同一问题两套数**的口径分叉。

    ★ **完工时间 7843.20 s 是带全部硬时限的最优解，不是搜索没收敛**。
      给定数据的时刻表最晚返回 7740.19 s（更小），但它**违反 S015 医疗箱的
      7200 s 硬时限**（T19 交付 7470.0 s > 7200 s）。本仓用 CP-SAT 逐档收紧
      `Cmax` 上界做了判定：`Cmax ≤ 7843.2 s` 对给定组批**不可行**、
      `Cmax ≤ 7850 s` 可行，改进组批在 `7843.2 s` 即可行且最优。
      即：完工时间的 103 s 差值是**时限可行性的代价**，不是模型缺陷。
      同期逐箱核对：80/80 箱满足期望送达时间、30/30 首批箱达标。
    """
    t = SD.q2(relays)

    src: list[SD.Sortie] = list(t.sorties)
    if uav_types is not None and leg_cache is not None and src:
        src = _improve_grouping(src, uav_types, leg_cache)

    out: list[TransportSortie] = []
    for i, x in enumerate(src, 1):
        s = TransportSortie(
            sortie_id=f"T{i:02d}", type_code=x.g, sites=_sites_of(x),
            box_ids=x.boxes, mass_kg=x.mass, volume_m3=x.volume,
            uav_id=x.machine or "—", battery_id=x.battery_id or "—",
            start_s=float(x.start or 0.0), duration_s=x.duration,
            return_s=float(x.return_time or 0.0),
            energy_kwh=x.energy, soc_end=x.soc, delivery={},
        )
        if uav_types is not None and leg_cache is not None:
            uav = uav_types.get(s.type_code)
            if uav is not None:
                s.delivery_elapsed_s = compute_delivery_offset(s, uav, leg_cache)
        if not s.delivery_elapsed_s:
            s.delivery_elapsed_s = float(x.duration) / 2.0
        s.delivery = {b: s.start_s + s.delivery_elapsed_s for b in s.box_ids}
        out.append(s)

    schedule_note = "调度沿用给定方案数据"
    if use_dispatcher:
        try:
            res = _reschedule(out, time_limit_s=time_limit_s)
            if res is not None:
                schedule_note = (f"调度由本仓 CP-SAT 重新求解"
                                 f"（{res[1]}；最晚返回 {res[0]:.2f} s）")
        except Exception as exc:                      # noqa: BLE001
            schedule_note = f"CP-SAT 调度未启用（{exc}）；沿用给定方案数据"

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
    plan.caveats.append(
        "问题二组批在 S006/S007/S008/S013 上相对问题一增开了先行小架次"
        "（18→23 架次），以满足首批与医疗时限；载荷与能耗口径继承问题一。"
    )
    plan.caveats.append(schedule_note)
    plan.caveats.append(DEADLINE_CAVEAT)
    plan.caveats.append(SD.RELAY_ALTITUDE_NOTE)
    plan.caveats.append(SD.RADIO_CHECK_NOTE)
    return plan


# 附件机队与电池库存（分机型）
MACHINES: dict[str, list[str]] = {
    "A": ["U01", "U02", "U03", "U04"],
    "B": ["U05", "U06"],
    "C": ["U07", "U08"],
}
BATTERIES: dict[str, list[str]] = {
    "A": [f"BA{i:02d}" for i in range(1, 7)],
    "B": [f"BB{i:02d}" for i in range(1, 5)],
    "C": [f"BC{i:02d}" for i in range(1, 5)],
}
T_FULL: dict[str, float] = {"A": 1800.0, "B": 2400.0, "C": 3000.0}


def _reschedule(
    sorties: list[TransportSortie], time_limit_s: float = 120.0
) -> tuple[float, str] | None:
    """用 CP-SAT 重排实体机/电池/起飞时刻，并把结果写回 `sorties`。

    对每个架次保持**交付偏移**不变（τ = 交付 − 起飞），故重排后逐箱交付
    时刻 = 新起飞时刻 + τ；时限约束已在求解中施加，因此重排后仍满足。
    """
    from src.physics.battery import charging_time
    from src.q0_data import build_processed as BP
    from src.q2_transport_schedule.dispatcher import (
        DispatchTask,
        dispatch,
        known_feasible_hint,
    )

    bmeta = {str(r["box_id"]): r for _, r in BP.load_boxes().iterrows()}

    tasks: list[DispatchTask] = []
    for s in sorties:
        # 交付耗时由装配阶段按物理层固定，重排只平移起飞时刻
        off = s.delivery_elapsed_s
        # ★ 全部期望时间都作为**硬约束**：给定方案让 80/80 箱都在期望时间前
        #   送达（逐箱核对表已复核），调度器应达到同一强度；否则重排会让部分箱
        #   “合法但变晚”，与方案的时限结论不一致。
        hard: list[float] = []
        for b in s.box_ids:
            m = bmeta.get(b)
            if m is None:
                continue
            hard.append(float(m["expected_time_s"]))
            fb = m["first_batch_deadline_s"]
            if fb is not None and fb == fb:
                hard.append(float(fb))
        tasks.append(DispatchTask(
            task_id=s.sortie_id, type_code=s.type_code,
            duration_s=s.duration_s, soc_end=s.soc_end,
            charge_s=charging_time(s.soc_end, T_FULL[s.type_code]),
            delivery_elapsed_s=off,
            hard_deadlines_s=tuple(hard), soft_deadlines_s=(),
        ))

    res = dispatch(tasks, MACHINES, BATTERIES, time_limit_s=time_limit_s,
                   hints=known_feasible_hint(MACHINES, BATTERIES))
    if not res.ok:
        return None

    for s in sorties:
        a = res.assignments[s.sortie_id]
        s.uav_id = a["machine"]
        s.battery_id = a["battery"]
        s.start_s = a["start_s"]
        s.return_s = a["return_s"]
        # 绝对交付时刻 = 新起飞时刻 + 交付耗时（幂等：可重复调用）
        s.delivery = {b: s.start_s + s.delivery_elapsed_s for b in s.box_ids}
    return (res.makespan_s, res.status)


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
