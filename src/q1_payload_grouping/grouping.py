"""问题一核心：最大安全载荷、货箱组批与多目标权衡。

问题结构
--------
每个架次形如 `O01 → S_i → O01`（**仅服务一个服务区**，不得跨服务区组批）；
同一服务区可由多个架次分批服务；货箱**不可拆分**、**每箱只安排一次**。

约束
----
- 载质量：`Σ m_b ≤ q_max^safe(g, i)`
- 装载体积：`Σ v_b ≤ Q_g^vol`
- 返航安全能量余量：已包含在 `q_max^safe` 的反解中

三个目标
--------
1. **往返架次数**（越少越好）
2. **总运输能耗**（kWh）
3. **累计作业时间**（s）—— 定义为全部架次的 `准备 + 装载 + 飞行 + 交接` 之和，
   即所有架次**串行**执行所需的总时间（题目原文"累计作业时间"）。

> ★ 若按"并行执行"理解则应为 makespan，但那需要引入机队规模与调度，
>   属于问题二的范畴。问题一**不考虑实体无人机与共享电池调度**（题目明确），
>   因此这里采用"累计"的字面口径，并在 `metrics.json` 中同时记录
>   `serial_total_time_s` 与 `parallel_makespan_s` 两个值供论文对照。

两类作业时间
------------
- **单点往返**（问题一）：每区独立，时间可直接相加
- **多点串飞**（问题二）：需访问顺序与逐段几何，本模块提供 `multi_stop_time` 备用
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from src.physics.energy import Segment, segment_energy_kwh, segment_time_s
from src.physics.payload import UAVType, max_safe_payload
from src.physics.leg_cache import LegCache


# ---------------------------------------------------------------- 数据结构

@dataclass(frozen=True)
class Box:
    """一个货箱。"""

    box_id: str
    service_id: str
    mass_kg: float
    volume_m3: float
    is_first_batch: bool = False
    first_batch_deadline_s: float | None = None
    expected_time_s: float | None = None
    priority: int = 0

    @property
    def density(self) -> float:
        return self.mass_kg / self.volume_m3 if self.volume_m3 > 0 else math.inf


@dataclass
class Sortie:
    """一个问题一意义上的架次（单点往返）。"""

    sortie_id: str
    service_id: str
    type_code: str
    box_ids: tuple[str, ...]
    total_mass_kg: float
    total_volume_m3: float
    roundtrip_time_s: float
    energy_kwh: float
    return_soc: float
    max_payload_kg: float
    """该 (服务区, 机型) 的最大安全载荷（用于说明载荷余量）。"""

    @property
    def mass_utilisation(self) -> float:
        return self.total_mass_kg / self.max_payload_kg if self.max_payload_kg else 0.0


@dataclass
class AreaSolution:
    """单个服务区的组批结果。"""

    service_id: str
    sorties: list[Sortie]

    @property
    def n_sorties(self) -> int:
        return len(self.sorties)

    @property
    def total_energy_kwh(self) -> float:
        return sum(s.energy_kwh for s in self.sorties)

    @property
    def total_time_s(self) -> float:
        return sum(s.roundtrip_time_s for s in self.sorties)


@dataclass
class Solution:
    """一个完整的组批方案（覆盖全部 15 个服务区）。"""

    strategy: str
    areas: dict[str, AreaSolution]
    uav_types: dict[str, UAVType]
    note: str = ""

    @property
    def n_sorties(self) -> int:
        return sum(a.n_sorties for a in self.areas.values())

    @property
    def total_energy_kwh(self) -> float:
        return sum(a.total_energy_kwh for a in self.areas.values())

    @property
    def serial_total_time_s(self) -> float:
        return sum(a.total_time_s for a in self.areas.values())

    @property
    def all_sorties(self) -> list[Sortie]:
        return [s for a in self.areas.values() for s in a.sorties]

    def type_usage(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in self.all_sorties:
            out[s.type_code] = out.get(s.type_code, 0) + 1
        return out

    def metrics(self) -> dict[str, float]:
        return {
            "n_sorties": float(self.n_sorties),
            "total_energy_kwh": round(self.total_energy_kwh, 6),
            "serial_total_time_s": round(self.serial_total_time_s, 3),
            "parallel_makespan_s": round(max(
                (a.total_time_s for a in self.areas.values()), default=0.0), 3),
        }


# ---------------------------------------------------------------- 载荷能力

@dataclass
class AreaCapacity:
    """某服务区某机型的单架次容量。"""

    service_id: str
    type_code: str
    max_payload_kg: float
    """max(0, 能量反解值, 结构上限) 后的安全载荷。"""
    volume_m3: float
    binding: str
    """起作用的约束：'energy' / 'structure' / 'infeasible'。"""
    feasible: bool
    distance_m: float
    roundtrip_time_s: float
    empty_energy_kwh: float
    """空载往返能耗（用于判断该区该机型是否根本飞不到）。"""


def area_capacities(
    service_ids: Sequence[str],
    uav_types: dict[str, UAVType],
    leg_cache: LegCache,
    center_id: str = "O01",
) -> dict[tuple[str, str], AreaCapacity]:
    """计算全部 (服务区, 机型) 的最大安全载荷与生效约束。"""
    out: dict[tuple[str, str], AreaCapacity] = {}
    for sid in service_ids:
        leg_out = leg_cache.get(center_id, sid)
        leg_back = leg_cache.get(sid, center_id)
        for code, uav in uav_types.items():
            seg_out = Segment(leg_out["distance_m"], leg_out["climb_m"], leg_out["descent_m"])
            seg_back = Segment(leg_back["distance_m"], leg_back["climb_m"], leg_back["descent_m"])
            rt_time = segment_time_s(uav, seg_out) + segment_time_s(uav, seg_back)
            empty_e = (
                segment_energy_kwh(uav, seg_out, 0.0)
                + segment_energy_kwh(uav, seg_back, 0.0)
            )
            try:
                q = max_safe_payload(
                    uav,
                    leg_out["distance_m"],
                    leg_out["climb_m"], leg_out["descent_m"],
                    leg_back["climb_m"], leg_back["descent_m"],
                )
                feasible = True
                binding = "structure" if q >= uav.max_payload_kg - 1e-9 else "energy"
                if q <= 1e-9:
                    feasible = False
                    binding = "infeasible"
            except ValueError:
                q = 0.0
                feasible = False
                binding = "infeasible"
            out[(sid, code)] = AreaCapacity(
                service_id=sid, type_code=code, max_payload_kg=q,
                volume_m3=uav.volume_m3, binding=binding, feasible=feasible,
                distance_m=leg_out["distance_m"], roundtrip_time_s=rt_time,
                empty_energy_kwh=empty_e,
            )
    return out


# ---------------------------------------------------------------- 装箱

def _pack_area(
    boxes: Sequence[Box],
    capacities: dict[str, AreaCapacity],
    uav_types: dict[str, UAVType],
    type_order: Sequence[str],
    use_best_fit: bool = True,
    box_order: str = "volume_desc",
) -> list[tuple[str, list[Box]]]:
    """把一个服务区的货箱装箱，返回 [(机型, 货箱列表), ...]。

    启发式：**首次适应递减（FFD）**
      1. 货箱按指定规则排序（默认体积降序 —— 体积是本题主要瓶颈，见 MODEL_NOTES 1.3b）
      2. 每个货箱尝试放入已有箱，能放则放
      3. 放不下则开新箱，机型由 `use_best_fit` 决定取"最小可容纳"还是"最大"

    参数
    ----
    box_order :
        'volume_desc'  体积降序（FFD，默认，装箱效果最好）
        'mass_desc'    质量降序
        'density_desc' 密度降序
        'as_given'     保持输入顺序（NF，用于对照 FFD 的收益）
    """
    if box_order == "volume_desc":
        order = sorted(boxes, key=lambda b: (-b.volume_m3, -b.mass_kg, b.box_id))
    elif box_order == "mass_desc":
        order = sorted(boxes, key=lambda b: (-b.mass_kg, -b.volume_m3, b.box_id))
    elif box_order == "density_desc":
        order = sorted(boxes, key=lambda b: (-b.density, b.box_id))
    elif box_order == "as_given":
        order = list(boxes)
    else:
        raise ValueError(f"未知的装箱排序规则：{box_order}")

    if not order:
        return []

    bins: list[dict] = []  # {type_code, boxes, mass, volume}

    def fits(type_code: str, mass: float, volume: float) -> bool:
        cap = capacities.get((order[0].service_id, type_code))
        if cap is None or not cap.feasible:
            return False
        return mass <= cap.max_payload_kg + 1e-9 and volume <= cap.volume_m3 + 1e-12

    for b in order:
        placed = False
        for bn in bins:
            if fits(bn["type_code"], bn["mass"] + b.mass_kg, bn["volume"] + b.volume_m3):
                bn["boxes"].append(b)
                bn["mass"] += b.mass_kg
                bn["volume"] += b.volume_m3
                placed = True
                break
        if placed:
            continue
        candidates = [c for c in type_order if fits(c, b.mass_kg, b.volume_m3)]
        if not candidates:
            raise InfeasibleError(
                f"服务区 {b.service_id} 的货箱 {b.box_id}"
                f"（{b.mass_kg} kg / {b.volume_m3} m³）没有任何机型能单箱装载"
            )
        if use_best_fit:
            chosen = min(
                candidates,
                key=lambda c: (capacities[(b.service_id, c)].volume_m3,
                               capacities[(b.service_id, c)].max_payload_kg),
            )
        else:
            chosen = max(
                candidates,
                key=lambda c: (capacities[(b.service_id, c)].volume_m3,
                               capacities[(b.service_id, c)].max_payload_kg),
            )
        bins.append(
            {"type_code": chosen, "boxes": [b], "mass": b.mass_kg, "volume": b.volume_m3}
        )

    return [(bn["type_code"], bn["boxes"]) for bn in bins]


class InfeasibleError(RuntimeError):
    """该服务区在本机型组合下无可行组批。"""


# ---------------------------------------------------------------- 组装方案

def _make_sorties(
    service_id: str,
    packed: list[tuple[str, list[Box]]],
    capacities: dict[str, AreaCapacity],
    uav_types: dict[str, UAVType],
    leg_cache: LegCache,
    center_id: str = "O01",
) -> AreaSolution:
    sorties: list[Sortie] = []
    leg_out = leg_cache.get(center_id, service_id)
    leg_back = leg_cache.get(service_id, center_id)

    for k, (code, bx) in enumerate(packed, start=1):
        uav = uav_types[code]
        cap = capacities[(service_id, code)]
        seg_out = Segment(leg_out["distance_m"], leg_out["climb_m"], leg_out["descent_m"])
        seg_back = Segment(leg_back["distance_m"], leg_back["climb_m"], leg_back["descent_m"])
        mass = sum(b.mass_kg for b in bx)
        vol = sum(b.volume_m3 for b in bx)

        e = (
            segment_energy_kwh(uav, seg_out, mass)
            + segment_energy_kwh(uav, seg_back, 0.0)
        )
        t_fly = segment_time_s(uav, seg_out) + segment_time_s(uav, seg_back)
        t_oper = (
            uav.prepare_time_s
            + uav.box_load_time_s * len(bx)
            + uav.handover_base_s
            + uav.handover_per_box_s * len(bx)
        )
        soc = max(0.0, 1.0 - e / uav.energy_kwh)
        sorties.append(
            Sortie(
                sortie_id=f"S{service_id[1:]}-{k:02d}",
                service_id=service_id,
                type_code=code,
                box_ids=tuple(b.box_id for b in bx),
                total_mass_kg=mass,
                total_volume_m3=vol,
                roundtrip_time_s=t_fly + t_oper,
                energy_kwh=e,
                return_soc=soc,
                max_payload_kg=cap.max_payload_kg,
            )
        )
    return AreaSolution(service_id=service_id, sorties=sorties)


# ---------------------------------------------------------------- 策略

TypeOrderFn = Callable[[str], Sequence[str]]


def _solve_with_order(
    boxes_by_area: dict[str, list[Box]],
    uav_types: dict[str, UAVType],
    capacities: dict[str, AreaCapacity],
    leg_cache: LegCache,
    order_fn: TypeOrderFn,
    use_best_fit: bool,
    strategy: str,
    note: str = "",
) -> Solution:
    areas: dict[str, AreaSolution] = {}
    for sid, bx in boxes_by_area.items():
        order = order_fn(sid)
        packed = _pack_area(bx, capacities, uav_types, order, use_best_fit)
        areas[sid] = _make_sorties(sid, packed, capacities, uav_types, leg_cache)
    return Solution(strategy=strategy, areas=areas, uav_types=uav_types, note=note)


def _order_large_first(codes: Sequence[str], uav_types: dict[str, UAVType]) -> list[str]:
    """大机型优先（体积上限降序）→ 架次数最少。"""
    return sorted(codes, key=lambda c: -uav_types[c].volume_m3)


def _order_small_first(codes: Sequence[str], uav_types: dict[str, UAVType]) -> list[str]:
    """小机型优先（体积上限升序）→ 更省能量。"""
    return sorted(codes, key=lambda c: uav_types[c].volume_m3)


def solve_single_type(
    boxes_by_area: dict[str, list[Box]],
    code: str,
    uav_types: dict[str, UAVType],
    capacities: dict[str, AreaCapacity],
    leg_cache: LegCache,
) -> Solution:
    """只用一种机型（用于对比"专机专用"）。"""
    return _solve_with_order(
        boxes_by_area, uav_types, capacities, leg_cache,
        order_fn=lambda _sid: [code], use_best_fit=True,
        strategy=f"single_{code}", note=f"全程只使用 {code} 型",
    )


def solve_best_fit(
    boxes_by_area: dict[str, list[Box]],
    uav_types: dict[str, UAVType],
    capacities: dict[str, AreaCapacity],
    leg_cache: LegCache,
) -> Solution:
    """混合机型 + 最小可容纳机型（省能量倾向）。"""
    codes = list(uav_types)
    return _solve_with_order(
        boxes_by_area, uav_types, capacities, leg_cache,
        order_fn=lambda _sid: _order_small_first(codes, uav_types),
        use_best_fit=True, strategy="mixed_best_fit",
        note="混合机型，新箱优先选能装下的最小机型",
    )


def solve_largest_first(
    boxes_by_area: dict[str, list[Box]],
    uav_types: dict[str, UAVType],
    capacities: dict[str, AreaCapacity],
    leg_cache: LegCache,
) -> Solution:
    """混合机型 + 最大机型优先（架次数倾向）。"""
    codes = list(uav_types)
    return _solve_with_order(
        boxes_by_area, uav_types, capacities, leg_cache,
        order_fn=lambda _sid: _order_large_first(codes, uav_types),
        use_best_fit=False, strategy="mixed_largest_first",
        note="混合机型，新箱优先选最大机型",
    )


def solve_ffd_volume_desc(
    boxes_by_area: dict[str, list[Box]],
    uav_types: dict[str, UAVType],
    capacities: dict[str, AreaCapacity],
    leg_cache: LegCache,
) -> Solution:
    """默认策略：FFD（体积降序）+ 最大机型优先。"""
    codes = list(uav_types)
    return _solve_with_order(
        boxes_by_area, uav_types, capacities, leg_cache,
        order_fn=lambda _sid: _order_large_first(codes, uav_types),
        use_best_fit=False, strategy="ffd_volume",
        note="FFD 体积降序 + 最大机型优先",
    )


def solve_ffd_mass_desc(
    boxes_by_area: dict[str, list[Box]],
    uav_types: dict[str, UAVType],
    capacities: dict[str, AreaCapacity],
    leg_cache: LegCache,
) -> Solution:
    """对照策略：按质量降序（检验"体积才是主瓶颈"这一判断）。"""
    codes = list(uav_types)
    return _solve_with_order(
        boxes_by_area, uav_types, capacities, leg_cache,
        order_fn=lambda _sid: _order_large_first(codes, uav_types),
        use_best_fit=False, strategy="ffd_mass",
        note="FFD 质量降序 + 最大机型优先",
    )


def solve_next_fit_as_given(
    boxes_by_area: dict[str, list[Box]],
    uav_types: dict[str, UAVType],
    capacities: dict[str, AreaCapacity],
    leg_cache: LegCache,
) -> Solution:
    """对照策略：保持附件顺序（NF），用于量化"排序带来的收益"。"""
    codes = list(uav_types)
    areas: dict[str, AreaSolution] = {}
    for sid, bx in boxes_by_area.items():
        packed = _pack_area(
            bx, capacities, uav_types, _order_large_first(codes, uav_types),
            use_best_fit=False, box_order="as_given",
        )
        areas[sid] = _make_sorties(sid, packed, capacities, uav_types, leg_cache)
    return Solution(strategy="nf_as_given", areas=areas, uav_types=uav_types,
                    note="不排序（按附件顺序）+ 最大机型优先")


def solve_all_strategies(
    boxes_by_area: dict[str, list[Box]],
    uav_types: dict[str, UAVType],
    leg_cache: LegCache,
) -> dict[str, Solution]:
    """跑完全部策略，返回 {策略名: 方案}（不可行的策略会被跳过）。"""
    sids = sorted(boxes_by_area)
    caps = area_capacities(sids, uav_types, leg_cache)
    out: dict[str, Solution] = {}
    for code in sorted(uav_types):
        try:
            s = solve_single_type(boxes_by_area, code, uav_types, caps, leg_cache)
            out[s.strategy] = s
        except InfeasibleError:
            continue
    for fn in (
        solve_ffd_volume_desc,
        solve_ffd_mass_desc,
        solve_next_fit_as_given,
        solve_best_fit,
        solve_largest_first,
    ):
        try:
            s = fn(boxes_by_area, uav_types, caps, leg_cache)
            out[s.strategy] = s
        except InfeasibleError:
            continue
    return out


# ---------------------------------------------------------------- 下界

def sortie_lower_bound(boxes: Sequence[Box], uav_types: dict[str, UAVType],
                       cap: dict[str, AreaCapacity], service_id: str) -> dict[str, int]:
    """该服务区架次数的**下界**：按质量与体积分别算，取较大者。

    质量下界 = ceil(Σm / max_g q_max)  （用最好的机型）
    体积下界 = ceil(Σv / max_g V_g)
    """
    total_m = sum(b.mass_kg for b in boxes)
    total_v = sum(b.volume_m3 for b in boxes)
    best_q = max(
        (cap[(service_id, c)].max_payload_kg for c in uav_types
         if cap[(service_id, c)].feasible),
        default=0.0,
    )
    best_v = max(
        (cap[(service_id, c)].volume_m3 for c in uav_types
         if cap[(service_id, c)].feasible),
        default=0.0,
    )
    lb_m = math.ceil(total_m / best_q - 1e-9) if best_q > 0 else 10**9
    lb_v = math.ceil(total_v / best_v - 1e-12) if best_v > 0 else 10**9
    return {
        "lb_mass": lb_m,
        "lb_volume": lb_v,
        "lb": max(lb_m, lb_v),
        "total_mass_kg": total_m,
        "total_volume_m3": total_v,
        "best_payload_kg": best_q,
        "best_volume_m3": best_v,
    }


def bin_count_fixed_capacity(
    boxes: Sequence[Box],
    cap_volume_m3: float,
    cap_mass_kg: float,
) -> int:
    """**固定容量**箱装问题的 FFD 箱数。

    用于证明最优性：把问题退化为"所有机型容量都等于最大机型"，
    若 FFD 的箱数等于该退化问题的下界，则原多容量问题也是最优的
    （因为容量只增不减，退化问题的下界即原问题的下界）。
    """
    if not boxes:
        return 0
    order = sorted(boxes, key=lambda b: (-b.volume_m3, -b.mass_kg, b.box_id))
    bins: list[dict] = []
    for b in order:
        placed = False
        for bn in bins:
            if (
                bn["volume"] + b.volume_m3 <= cap_volume_m3 + 1e-12
                and bn["mass"] + b.mass_kg <= cap_mass_kg + 1e-9
            ):
                bn["volume"] += b.volume_m3
                bn["mass"] += b.mass_kg
                placed = True
                break
        if not placed:
            bins.append({"volume": b.volume_m3, "mass": b.mass_kg})
    return len(bins)


def single_capacity_lower_bound(
    boxes: Sequence[Box],
    cap_volume_m3: float,
    cap_mass_kg: float,
) -> int:
    """单一容量装箱的 **Martello–Toth L2 型下界**。

    设容量 V（体积）与 M（质量），
        L1 = ceil(Σv / V)
        L2 = |大箱（v > V/2）| + ceil(剩余体积 / V)
    取 max(L1, L2)。质量维度同理再取一次 max。

    ★ 用途：若 FFD 结果 == 该下界，则**该服务区的架次数是最优的**，
      可用于在论文中声明"达到最优"而非仅仅"启发式可行"。
    """
    if not boxes:
        return 0

    def lb_for(cap: float, values: Sequence[float]) -> int:
        if cap <= 0:
            return 10**9
        total = sum(values)
        l1 = math.ceil(total / cap - 1e-9)
        big = sum(1 for v in values if v > cap / 2 + 1e-12)
        small = sum(v for v in values if v <= cap / 2 + 1e-12)
        l2 = big + math.ceil(small / cap - 1e-9)
        return max(l1, l2)

    lb_v = lb_for(cap_volume_m3, [b.volume_m3 for b in boxes])
    lb_m = lb_for(cap_mass_kg, [b.mass_kg for b in boxes])
    return max(lb_v, lb_m)


def pareto_frontier(solutions: Iterable[Solution]) -> list[Solution]:
    """在 (架次数, 总能耗, 累计作业时间) 上求 Pareto 非支配解。

    ★ 三个目标均**越小越好**。同一目标向量上只保留第一个。
    """
    cands = list(solutions)
    keep: list[Solution] = []
    for s in cands:
        v = (s.n_sorties, round(s.total_energy_kwh, 6), round(s.serial_total_time_s, 3))
        dominated = False
        for t in cands:
            if t is s:
                continue
            w = (t.n_sorties, round(t.total_energy_kwh, 6), round(t.serial_total_time_s, 3))
            if all(a <= b for a, b in zip(w, v)) and any(a < b for a, b in zip(w, v)):
                dominated = True
                break
        if not dominated:
            keep.append(s)
    # 去重（同一目标向量）
    seen: set[tuple] = set()
    uniq: list[Solution] = []
    for s in keep:
        key = (s.n_sorties, round(s.total_energy_kwh, 6), round(s.serial_total_time_s, 3))
        if key not in seen:
            seen.add(key)
            uniq.append(s)
    return sorted(uniq, key=lambda s: (s.n_sorties, s.total_energy_kwh, s.serial_total_time_s))


# ---------------------------------------------------------------- 多点（备用，Q2 用）

def multi_stop_time(
    uav: UAVType,
    sequence: Sequence[str],
    leg_cache: LegCache,
    center_id: str = "O01",
    n_boxes: int = 0,
) -> float:
    """多点串飞的架次作业时间（Q2 备用）。

    去程：O01 → S_a → S_b → …；回程：最后一个服务区 → O01。
    每次投送后**从 30 m 作业高度重新爬升**（已在 leg_cache 的爬升高度中体现）。
    """
    t = uav.prepare_time_s + uav.box_load_time_s * n_boxes
    nodes = [center_id, *sequence]
    for a, b in zip(nodes, nodes[1:]):
        g = leg_cache.get(a, b)
        t += segment_time_s(uav, Segment(g["distance_m"], g["climb_m"], g["descent_m"]))
    g_back = leg_cache.get(sequence[-1], center_id)
    t += segment_time_s(
        uav, Segment(g_back["distance_m"], g_back["climb_m"], g_back["descent_m"])
    )
    t += (uav.handover_base_s + uav.handover_per_box_s * n_boxes) * max(1, len(sequence))
    return t
