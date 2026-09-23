"""问题二求解器：异构无人机多点多架次运输调度。

决策变量（题目要求联合确定）
----------------------------
货箱组批 / 服务区访问顺序 / 运输机型 / 具体执行无人机 / 共享电池 / 各架次开始时刻

约束
----
货箱不可拆分 · 载质量与装载体积 · 返航安全余量 · 无人机与共享电池数量 ·
充电周转 · 物资时限（首批截止时间 / 期望送达时间）

目标（多目标）
--------------
配送及时性 + 全部任务完成时间 + 运输能耗 + 架次数

求解思路
--------
1. **装箱 + 邻近合并**：按时限紧急性排序货箱，优先并入已有架次（同机型、
   容量允许、合并后仍可行、能耗增量最小）；否则新开架次。
2. **选序**：每个架次的服务区顺序用全排列（≤6 站）或最近邻+2-opt 求能耗最小。
3. **局部搜索**：反复尝试「把某箱搬到另一个架次」与「两架次合并」，
   直到无改进 —— 目标为 (及时性惩罚, 架次数, 能耗) 的字典序。
4. **迭代调度**：调度改变时刻 → 重新计算交付时刻 → 重排架次顺序，迭代至收敛。
   资源周转（电池充电）会推迟后续架次，而推迟又影响时限，
   因此必须迭代而不能单次贪心。
"""

from __future__ import annotations

import copy
import math
import time
from dataclasses import dataclass, field, replace

import pandas as pd

from src.physics.leg_cache import LegCache
from src.physics.payload import UAVType
from src.q1_payload_grouping.grouping import Box, area_capacities, AreaCapacity
from src.q2_transport_schedule.models import (
    CENTER_ID,
    SortieEval,
    SortiePlan,
    best_stop_order,
    candidate_groups,
    evaluate_sortie,
    prefix_feasible,
)
from src.q2_transport_schedule.schedule import (
    ResourcePool,
    ScheduledSortie,
    build_pools,
)


# ---------------------------------------------------------------- 数据

@dataclass(frozen=True)
class Deadline:
    """一个货箱的时限要求。"""

    expected_s: float
    first_batch_s: float | None = None
    is_first_batch: bool = False


@dataclass
class Q2Result:
    """求解结果。"""

    sorties: list[ScheduledSortie]
    makespan_s: float
    total_energy_kwh: float
    n_sorties: int
    n_boxes: int
    violations_first_batch: int
    violations_expected: int
    mean_lateness_s: float
    max_lateness_s: float
    on_time_rate: float
    objective: float
    runtime_s: float
    iterations: int
    note: str = ""


# ---------------------------------------------------------------- 及时性

def lateness_of(
    sortie: ScheduledSortie,
    boxes_by_id: dict[str, Box],
    deadlines: dict[str, Deadline],
    first_batch_weight: float = 10.0,
) -> tuple[float, int, int, float, float]:
    """计算一个架次的时限违规情况。

    返回 (加权惩罚, 首批违规数, 期望违规数, 平均迟到, 最大迟到)。
    """
    penalty = 0.0
    n_fb = 0
    n_exp = 0
    latenesses: list[float] = []
    for svc, t in sortie.delivery_times.items():
        for bid in sortie.boxes_by_stop.get(svc, ()):
            dl = deadlines.get(bid)
            if dl is None:
                continue
            if dl.is_first_batch and dl.first_batch_s is not None:
                late = t - dl.first_batch_s
                if late > 1e-6:
                    n_fb += 1
                    penalty += first_batch_weight * late
                    latenesses.append(late)
            late_e = t - dl.expected_s
            if late_e > 1e-6:
                n_exp += 1
                penalty += late_e
                latenesses.append(late_e)
    mean_late = sum(latenesses) / len(latenesses) if latenesses else 0.0
    max_late = max(latenesses) if latenesses else 0.0
    return penalty, n_fb, n_exp, mean_late, max_late


def delivery_times_for(
    plan: SortiePlan,
    uav: UAVType,
    leg_cache: LegCache,
    start_s: float,
    boxes_by_id: dict[str, Box],
) -> dict[str, float]:
    """按顺序精确计算各服务区的**交付完成时刻**。

    时刻推进：准备 → 装载 → (飞到 S_a) → 在 S_a 交接 → (飞到 S_b) → 交接 → …
    交付完成时刻取该站交接**结束**的时刻。
    """
    from src.physics.energy import Segment, segment_time_s

    n = plan.n_boxes
    t = start_s + uav.prepare_time_s + uav.box_load_time_s * n
    out: dict[str, float] = {}
    prev = CENTER_ID
    for svc in plan.stops:
        g = leg_cache.get(prev, svc)
        t += segment_time_s(uav, Segment(g["distance_m"], g["climb_m"], g["descent_m"]))
        k = len(plan.boxes_by_stop.get(svc, ()))
        t += uav.handover_base_s + uav.handover_per_box_s * k
        out[svc] = t
        prev = svc
    return out


# ---------------------------------------------------------------- 构造

@dataclass
class _Cand:
    """候选架次（未调度）。"""

    plan: SortiePlan
    mass_by_stop: dict[str, float]
    vol_by_stop: dict[str, float]
    boxes: dict[str, Box]
    ev: SortieEval


def _make_plan(
    type_code: str,
    stops: tuple[str, ...],
    boxes_by_stop: dict[str, tuple[str, ...]],
) -> SortiePlan:
    return SortiePlan(type_code=type_code, stops=stops, boxes_by_stop=boxes_by_stop)


def _plan_signature(plan: SortiePlan) -> tuple:
    """架次的唯一签名（机型 + 顺序 + 各站箱集合，箱集合与顺序无关）。

    用于记忆化：同一内容无论顺序如何，`_eval_plan` 的结果只取决于**给定顺序**，
    但"选序"过程会对同一集合反复尝试不同顺序，因此签名按 (机型, 顺序, 箱集合) 构造。
    """
    return (
        plan.type_code,
        plan.stops,
        tuple((s, tuple(sorted(plan.boxes_by_stop.get(s, ())))) for s in plan.stops),
    )


_EVAL_CACHE: dict[tuple, SortieEval] = {}
_ORDER_CACHE: dict[tuple, tuple[tuple[str, ...], SortieEval]] = {}


def clear_caches() -> None:
    """清空记忆化缓存（在不同问题实例之间复用进程时调用）。"""
    _EVAL_CACHE.clear()
    _ORDER_CACHE.clear()


def _eval_plan(
    plan: SortiePlan,
    uav: UAVType,
    leg_cache: LegCache,
    boxes_by_id: dict[str, Box],
) -> SortieEval:
    """评估架次（带记忆化 + 必要条件剪枝）。

    ★ 性能：`evaluate_sortie` 在选序与局部搜索中被反复调用，
      记忆化把重复评估降到 O(1)。
    """
    sig = _plan_signature(plan)
    hit = _EVAL_CACHE.get(sig)
    if hit is not None:
        return hit

    total_m = 0.0
    total_v = 0.0
    for s in plan.stops:
        for b in plan.boxes_by_stop.get(s, ()):
            bx = boxes_by_id[b]
            total_m += bx.mass_kg
            total_v += bx.volume_m3
    if total_m > uav.max_payload_kg + 1e-9:
        ev = SortieEval(0, 0, 0, 0, 1.0, False,
                        f"总质量 {total_m:.2f} kg > {uav.code} 型上限 {uav.max_payload_kg} kg")
        _EVAL_CACHE[sig] = ev
        return ev
    if total_v > uav.volume_m3 + 1e-12:
        ev = SortieEval(0, 0, 0, 0, 1.0, False,
                        f"总体积 {total_v:.4f} m³ > {uav.code} 型上限 {uav.volume_m3} m³")
        _EVAL_CACHE[sig] = ev
        return ev

    mass = {s: sum(boxes_by_id[b].mass_kg for b in plan.boxes_by_stop.get(s, ()))
            for s in plan.stops}
    vol = {s: sum(boxes_by_id[b].volume_m3 for b in plan.boxes_by_stop.get(s, ()))
           for s in plan.stops}
    ev = evaluate_sortie(plan, uav, leg_cache, mass, vol)
    _EVAL_CACHE[sig] = ev
    return ev


def _improve_order(
    plan: SortiePlan,
    uav: UAVType,
    leg_cache: LegCache,
    boxes_by_id: dict[str, Box],
) -> SortiePlan:
    """在给定"哪些区送哪些箱"的前提下，优化访问顺序（带记忆化）。

    ★ 记忆化键与顺序无关（用排序后的 stops 与箱集合），
      因此对同一集合的不同顺序尝试只会真正计算一次。
    """
    sig = (
        plan.type_code,
        tuple(sorted(plan.stops)),
        tuple(
            (s, tuple(sorted(plan.boxes_by_stop.get(s, ()))))
            for s in sorted(plan.stops)
        ),
    )
    hit = _ORDER_CACHE.get(sig)
    if hit is not None:
        order, ev = hit
        return replace(plan, stops=order) if ev.feasible else plan

    mass = {s: sum(boxes_by_id[b].mass_kg for b in plan.boxes_by_stop.get(s, ()))
            for s in plan.stops}
    vol = {s: sum(boxes_by_id[b].volume_m3 for b in plan.boxes_by_stop.get(s, ()))
           for s in plan.stops}
    order, ev = best_stop_order(plan.stops, uav, leg_cache, mass, vol)
    _ORDER_CACHE[sig] = (order, ev)
    return replace(plan, stops=order) if ev.feasible else plan


def _try_add_box(
    cand: _Cand,
    bid: str,
    svc: str,
    uav: UAVType,
    leg_cache: LegCache,
    boxes_by_id: dict[str, Box],
) -> tuple[SortiePlan, SortieEval] | None:
    """尝试把箱子 bid 加入候选架次，返回 (新计划, 新评估)；不可行返回 None。

    ★ 性能：先用「总质量/总体积」快速剪枝，再做（昂贵的）选序与评估。
      绝大多数候选都会在剪枝阶段被挡掉，否则全排列搜索会把构造过程拖死。
    """
    b = boxes_by_id[bid]
    total_m = b.mass_kg
    total_v = b.volume_m3
    for s in cand.plan.stops:
        for x in cand.plan.boxes_by_stop.get(s, ()):
            bx = boxes_by_id[x]
            total_m += bx.mass_kg
            total_v += bx.volume_m3
    if total_m > uav.max_payload_kg + 1e-9 or total_v > uav.volume_m3 + 1e-12:
        return None

    new_boxes = dict(cand.plan.boxes_by_stop)
    new_boxes[svc] = tuple(new_boxes.get(svc, ())) + (bid,)
    new_stops = cand.plan.stops if svc in cand.plan.stops else tuple(sorted((*cand.plan.stops, svc)))
    plan = SortiePlan(cand.plan.type_code, new_stops, new_boxes)
    plan = _improve_order(plan, uav, leg_cache, boxes_by_id)
    ev = _eval_plan(plan, uav, leg_cache, boxes_by_id)
    return (plan, ev) if ev.feasible else None


def construct(
    boxes: list[Box],
    uav_types: dict[str, UAVType],
    leg_cache: LegCache,
    deadlines: dict[str, Deadline],
    max_group: int = 3,
    first_batch_weight: float = 10.0,
    seed_limit: int = 4,
    prefer_larger: bool = True,
    area_coherent: bool = True,
) -> list[_Cand]:
    """构造初始架次集合（装箱 + 邻近合并）。

    货箱排序：**首批箱优先** → 期望送达时间升序 → 应急优先系数降序 → 体积降序。
    （先把最急的箱安排掉，避免后期无处可放。）

    参数
    ----
    prefer_larger :
        True  —— 新开架次时优先用**能装下更多**的机型（减少架次数）
        False —— 优先用最小可容纳机型（减少能耗）
    area_coherent :
        True  —— 尽量把**同一服务区**的货放进同一个架次（填满再换新架次），
                 避免同一区的货被拆到很多架次而延误。
                 这批箱装满后，下一个箱优先开"本区新架次"或并入别的架次。
    """
    def key(b: Box):
        dl = deadlines.get(b.box_id)
        fb = 0 if (dl and dl.is_first_batch) else 1
        exp = dl.expected_s if dl else 1e18
        return (fb, exp, -b.priority, -b.volume_m3, b.box_id)

    ordered = sorted(boxes, key=key)
    boxes_by_id = {b.box_id: b for b in boxes}

    service_ids = sorted({b.service_id for b in boxes})
    groups = candidate_groups(
        service_ids, leg_cache, max_group=max_group, seed_limit=seed_limit
    )
    group_of: dict[str, list[tuple[str, ...]]] = {}
    for g in groups:
        if len(g) == 1:
            group_of.setdefault(g[0], []).append(g)
    for g in sorted(groups, key=lambda g: -len(g)):
        if len(g) > 1:
            for s in g:
                group_of.setdefault(s, []).append(g)

    # 机型排序：prefer_larger → 体积降序；否则升序
    type_order = sorted(
        uav_types,
        key=(lambda c: -uav_types[c].volume_m3) if prefer_larger
        else (lambda c: uav_types[c].volume_m3),
    )

    cands: list[_Cand] = []
    last_area_cand: dict[str, _Cand] = {}  # 该区最近一次开的架次（area_coherent 用）

    def _try_all_existing(b: Box):
        """在已有架次中找能耗增量最小的并入方案。"""
        best = None
        for cand in cands:
            uav = uav_types[cand.plan.type_code]
            r = _try_add_box(cand, b.box_id, b.service_id, uav, leg_cache, boxes_by_id)
            if r is None:
                continue
            plan, ev = r
            delta = ev.energy_kwh - cand.ev.energy_kwh
            # 合并到别的服务区会绕路，略加惩罚以偏好"同区"
            if b.service_id not in cand.plan.stops:
                delta += 0.05 * leg_cache.distance(cand.plan.stops[0], b.service_id) / 1000.0
            if best is None or delta < best[0] - 1e-12:
                best = (delta, cand, plan, ev)
        return best

    def _open_new(b: Box) -> _Cand:
        """新开一个架次（按 prefer_larger 试机型与邻近组合）。"""
        created: tuple[float, _Cand] | None = None
        for g in group_of.get(b.service_id, [(b.service_id,)]):
            for code in type_order:
                uav = uav_types[code]
                if (b.mass_kg > uav.max_payload_kg + 1e-9
                        or b.volume_m3 > uav.volume_m3 + 1e-12):
                    continue
                stops = tuple(sorted(g))
                boxes_by_stop: dict[str, tuple[str, ...]] = {s: () for s in stops}
                boxes_by_stop[b.service_id] = (b.box_id,)
                plan = SortiePlan(code, stops, boxes_by_stop)
                plan = _improve_order(plan, uav, leg_cache, boxes_by_id)
                ev = _eval_plan(plan, uav, leg_cache, boxes_by_id)
                if not ev.feasible:
                    continue
                cost = ev.energy_kwh + 0.02 * len(stops)
                cost += 0.5 * sum(1 for s in stops if s != b.service_id)
                if created is None or cost < created[0]:
                    created = (
                        cost,
                        _Cand(plan=plan, mass_by_stop={}, vol_by_stop={},
                              boxes={b.box_id: b}, ev=ev),
                    )
        if created is None:
            raise RuntimeError(
                f"货箱 {b.box_id}（{b.mass_kg} kg / {b.volume_m3} m³）无任何可行架次"
            )
        return created[1]

    for b in ordered:
        # (a) area_coherent：先试"本区上一个架次"
        if area_coherent:
            prev = last_area_cand.get(b.service_id)
            if prev is not None and prev in cands:
                uav = uav_types[prev.plan.type_code]
                r = _try_add_box(prev, b.box_id, b.service_id, uav, leg_cache, boxes_by_id)
                if r is not None:
                    prev.plan, prev.ev = r
                    prev.boxes[b.box_id] = b
                    continue

        # (b) 并入任意已有架次（能耗增量最小）
        best = _try_all_existing(b)
        if best is not None:
            _, cand, plan, ev = best
            cand.plan, cand.ev = plan, ev
            cand.boxes[b.box_id] = b
            last_area_cand[b.service_id] = cand
            continue

        # (c) 新开架次
        newc = _open_new(b)
        cands.append(newc)
        last_area_cand[b.service_id] = newc

    # (d) ★ 跨区合并：初版装箱是"逐区独立"的，一个区装完就换下一个，
    #     因此同一架次里很少出现多个服务区 —— 那样架次数会偏多。
    #     这里做一轮**合并不增耗**的跨区合并：
    #     若两个架次的目标区互为最近邻，且合并后仍满足能耗与容量，则合并。
    cands = _merge_across_areas(cands, uav_types, leg_cache, boxes_by_id)
    return cands


def _merge_across_areas(
    cands: list[_Cand],
    uav_types: dict[str, UAVType],
    leg_cache: LegCache,
    boxes_by_id: dict[str, Box],
    max_neighbour_km: float = 4.0,
) -> list[_Cand]:
    """把**地理位置邻近**的两个架次合并为一个多点串飞架次（贪心，无退化则停）。

    判据：合并后能耗 < 两者之和（省下一趟往返），且容量与能量均可行。
    只考虑最近邻在 `max_neighbour_km` 以内的组合，避免远距离硬凑。
    """
    cur = [c for c in cands if c.plan.stops]
    improved = True
    while improved:
        improved = False
        best = None
        for i in range(len(cur)):
            for j in range(i + 1, len(cur)):
                a, b = cur[i], cur[j]
                if not a.plan.stops or not b.plan.stops:
                    continue
                # 只合并邻近区（取两两最近距离；跳过同一服务区）
                dmin = min(
                    (leg_cache.distance(sa, sb)
                     for sa in a.plan.stops for sb in b.plan.stops if sa != sb),
                    default=float("inf"),
                )
                if dmin > max_neighbour_km * 1000.0:
                    continue
                code = a.plan.type_code
                merged = _merge_plans(a.plan, b.plan)
                if merged is None:
                    continue
                # 试原机型，再试更大的机型
                trial_codes = [code] + [
                    c for c in sorted(uav_types, key=lambda c: uav_types[c].volume_m3)
                    if uav_types[c].volume_m3 > uav_types[code].volume_m3
                ]
                for c2 in trial_codes:
                    m2 = replace(merged, type_code=c2)
                    m2 = _improve_order(m2, uav_types[c2], leg_cache, boxes_by_id)
                    ev2 = _eval_plan(m2, uav_types[c2], leg_cache, boxes_by_id)
                    if not ev2.feasible:
                        continue
                    saving = (a.ev.energy_kwh + b.ev.energy_kwh) - ev2.energy_kwh
                    if saving > 1e-9 and (best is None or saving > best[0]):
                        best = (saving, i, j, _Cand(
                            m2, {}, {}, {**a.boxes, **b.boxes}, ev2))
                    break
        if best is not None:
            _, i, j, newc = best
            cur = [c for k, c in enumerate(cur) if k not in (i, j)]
            cur.append(newc)
            improved = True
    return cur


# ---------------------------------------------------------------- 局部搜索

def _objective(
    cands: list[_Cand],
    uav_types: dict[str, UAVType],
    leg_cache: LegCache,
    boxes_by_id: dict[str, Box],
    deadlines: dict[str, Deadline],
) -> tuple[float, int, float]:
    """目标（字典序）：(及时性惩罚, 架次数, 能耗)。

    及时性用**静态估计**（从 0 时刻开工），仅用于局部搜索的相对比较；
    最终报告的及时性由迭代调度给出精确值。
    """
    penalty = 0.0
    energy = 0.0
    for c in cands:
        if not c.plan.stops:
            continue
        uav = uav_types[c.plan.type_code]
        dt = delivery_times_for(c.plan, uav, leg_cache, 0.0, boxes_by_id)
        fake = ScheduledSortie(
            sortie_id="x", plan_index=0, uav_id="", type_code=c.plan.type_code,
            battery_id="", stops=c.plan.stops, boxes_by_stop=c.plan.boxes_by_stop,
            start_s=0.0, return_s=c.ev.total_time_s, energy_kwh=c.ev.energy_kwh,
            soc_end=c.ev.return_soc, delivery_times=dt, n_boxes=c.plan.n_boxes,
        )
        p, _, _, _, _ = lateness_of(fake, boxes_by_id, deadlines)
        penalty += p
        energy += c.ev.energy_kwh
    return (round(penalty, 3), len([c for c in cands if c.plan.stops]), round(energy, 6))


def local_search(
    cands: list[_Cand],
    uav_types: dict[str, UAVType],
    leg_cache: LegCache,
    boxes_by_id: dict[str, Box],
    deadlines: dict[str, Deadline],
    max_rounds: int = 30,
) -> list[_Cand]:
    """局部搜索：搬箱（relocate）与合并（merge），目标为字典序 `_objective`。"""
    cur = _rebuild(cands, uav_types, leg_cache, boxes_by_id)
    cur_obj = _objective(cur, uav_types, leg_cache, boxes_by_id, deadlines)

    for _ in range(max_rounds):
        improved = False

        # --- move 1: relocate 一个箱子到另一个架次 ---
        for i, ci in enumerate(cur):
            for bid in list(ci.plan.all_box_ids):
                b = boxes_by_id[bid]
                src_plan = _remove_box(ci.plan, bid)
                src_ev = (
                    _eval_plan(src_plan, uav_types[src_plan.type_code], leg_cache, boxes_by_id)
                    if src_plan.stops else SortieEval(0, 0, 0, 0, 1.0, True)
                )
                if src_plan.stops and not src_ev.feasible:
                    continue
                for j, cj in enumerate(cur):
                    if i == j or not cj.plan.stops:
                        continue
                    r = _try_add_box(cj, bid, b.service_id,
                                     uav_types[cj.plan.type_code], leg_cache, boxes_by_id)
                    if r is None:
                        continue
                    new_plan_j, new_ev_j = r
                    trial = list(cur)
                    trial[i] = _Cand(src_plan, {}, {}, dict(ci.boxes), src_ev)
                    trial[j] = _Cand(new_plan_j, {}, {}, dict(cj.boxes), new_ev_j)
                    trial = _rebuild(trial, uav_types, leg_cache, boxes_by_id)
                    obj = _objective(trial, uav_types, leg_cache, boxes_by_id, deadlines)
                    if obj < cur_obj:
                        cur, cur_obj, improved = trial, obj, True
                        break
                if improved:
                    break
            if improved:
                break
        if improved:
            continue

        # --- move 2: merge 两个架次 ---
        for i in range(len(cur)):
            for j in range(i + 1, len(cur)):
                if not cur[i].plan.stops or not cur[j].plan.stops:
                    continue
                merged = _merge_plans(cur[i].plan, cur[j].plan)
                if merged is None:
                    continue
                code = merged.type_code
                ev = _eval_plan(merged, uav_types[code], leg_cache, boxes_by_id)
                if not ev.feasible:
                    # 试更大型机
                    bigger = sorted(
                        (c for c in uav_types if uav_types[c].volume_m3 >= uav_types[code].volume_m3),
                        key=lambda c: uav_types[c].volume_m3,
                    )
                    for c2 in bigger:
                        m2 = replace(merged, type_code=c2)
                        m2 = _improve_order(m2, uav_types[c2], leg_cache, boxes_by_id)
                        ev2 = _eval_plan(m2, uav_types[c2], leg_cache, boxes_by_id)
                        if ev2.feasible:
                            merged, ev, code = m2, ev2, c2
                            break
                    else:
                        continue
                trial = [c for k, c in enumerate(cur) if k not in (i, j)]
                trial.append(_Cand(merged, {}, {}, {**cur[i].boxes, **cur[j].boxes}, ev))
                trial = _rebuild(trial, uav_types, leg_cache, boxes_by_id)
                obj = _objective(trial, uav_types, leg_cache, boxes_by_id, deadlines)
                if obj < cur_obj:
                    cur, cur_obj, improved = trial, obj, True
                    break
            if improved:
                break
        if not improved:
            break

    return cur


def _remove_box(plan: SortiePlan, bid: str) -> SortiePlan:
    new_boxes = {s: tuple(x for x in v if x != bid) for s, v in plan.boxes_by_stop.items()}
    new_stops = tuple(s for s in plan.stops if new_boxes.get(s))
    return SortiePlan(plan.type_code, new_stops, {s: new_boxes.get(s, ()) for s in new_stops})


def _merge_plans(a: SortiePlan, b: SortiePlan) -> SortiePlan | None:
    """合并两个架次（同机型或取更大机型）。"""
    code = a.type_code if a.type_code == b.type_code else max(
        (a.type_code, b.type_code), key=lambda c: c
    )
    boxes: dict[str, tuple[str, ...]] = {}
    for s in set(a.stops) | set(b.stops):
        boxes[s] = tuple(a.boxes_by_stop.get(s, ())) + tuple(b.boxes_by_stop.get(s, ()))
    stops = tuple(s for s in (*a.stops, *(x for x in b.stops if x not in a.stops)))
    return SortiePlan(code, stops, boxes)


def _rebuild(
    cands: list[_Cand],
    uav_types: dict[str, UAVType],
    leg_cache: LegCache,
    boxes_by_id: dict[str, Box],
) -> list[_Cand]:
    """重算每个候选架次的顺序与评估，丢弃空架次。"""
    out: list[_Cand] = []
    for c in cands:
        if not c.plan.stops:
            continue
        uav = uav_types[c.plan.type_code]
        plan = _improve_order(c.plan, uav, leg_cache, boxes_by_id)
        ev = _eval_plan(plan, uav, leg_cache, boxes_by_id)
        if not ev.feasible:
            continue
        out.append(_Cand(plan, {}, {}, dict(c.boxes), ev))
    return out
