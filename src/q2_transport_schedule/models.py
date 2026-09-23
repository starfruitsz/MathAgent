"""问题二模型：多点串飞架次的几何、能耗与时间。

与问题一的关键差异
------------------
问题一：`O01 → S_i → O01`，**仅一个服务区**。
问题二：`O01 → S_a → S_b → … → O01`，**可访问多个服务区**，
        且载荷**沿航段递减**（每次投送后卸下该区的箱子）。

载荷递减的直接后果
------------------
1. **逐航段校验容量**：在第 m 段上，机上剩余载荷 = 尚未投送的箱子质量之和。
   它必须同时满足该机型在该段的载荷上限与体积上限。
   → 不是"总质量 ≤ Q_g"这么简单，而是**每个前缀**都要满足（见 `prefix_feasible`）。
2 **逐航段累积能耗**：`E = Σ_m E_g(seg_m, q_m)`，`q_m` 为第 m 段的机上载荷。

时间
----
`架次时间 = 准备 + 装载×箱数 + Σ 航段飞行时间 + Σ 投送交接`
其中交接按**每个服务区**计一次基础交接 + 每箱增加量。
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Sequence

from src.physics.energy import Segment, segment_energy_kwh, segment_time_s
from src.physics.leg_cache import LegCache
from src.physics.payload import UAVType

CENTER_ID = "O01"


@dataclass(frozen=True)
class SortiePlan:
    """一个多点串飞架次的**计划内容**（尚未绑定无人机/电池/时刻）。"""

    type_code: str
    """机型编号。"""
    stops: tuple[str, ...]
    """服务区访问顺序，如 ('S002', 'S003')。"""
    boxes_by_stop: dict[str, tuple[str, ...]]
    """每个服务区投送的货箱编号。"""

    @property
    def all_box_ids(self) -> tuple[str, ...]:
        out: list[str] = []
        for s in self.stops:
            out.extend(self.boxes_by_stop.get(s, ()))
        return tuple(out)

    @property
    def n_boxes(self) -> int:
        return len(self.all_box_ids)


@dataclass
class SortieEval:
    """架次评估结果（几何/能耗/时间/约束）。"""

    energy_kwh: float
    flight_time_s: float
    ground_time_s: float
    total_time_s: float
    return_soc: float
    feasible: bool
    reason: str = ""
    leg_loads: tuple[float, ...] = ()
    leg_energies: tuple[float, ...] = ()


# ---------------------------------------------------------------- 前缀可行性

def prefix_feasible(
    order: Sequence[str],
    mass_by_stop: dict[str, float],
    vol_by_stop: dict[str, float],
    uav: UAVType,
    max_payload_by_stop: dict[str, float] | None = None,
) -> tuple[bool, str]:
    """检查**每个前缀**的机上载荷是否都在容量内。

    第 1 段上机的是全部货物；到第 m 个服务区前，机上还剩第 m..M 站的货。
    因此需要 `∀m: Σ_{k≥m} mass_k ≤ 容量`，最严格的是**第 1 段**（全部货）。
    但体积同样如此；两个维度都要查。

    参数
    ----
    max_payload_by_stop : 各服务区在该机型下的**能量反解**载荷上限；
                          None 时用机型的结构上限 `Q_g`。
    """
    remain_m = 0.0
    remain_v = 0.0
    for s in order:
        remain_m += mass_by_stop.get(s, 0.0)
        remain_v += vol_by_stop.get(s, 0.0)

    for idx, s in enumerate(order):
        cap_m = (
            uav.max_payload_kg
            if max_payload_by_stop is None
            else max_payload_by_stop.get(s, uav.max_payload_kg)
        )
        cap_v = uav.volume_m3
        if remain_m > cap_m + 1e-9:
            return False, (
                f"第 {idx + 1} 段机上载荷 {remain_m:.2f} kg > {s} 的载荷上限 {cap_m:.2f} kg"
            )
        if remain_v > cap_v + 1e-12:
            return False, (
                f"第 {idx + 1} 段机上体积 {remain_v:.4f} m³ > {uav.code} 型体积上限 {cap_v} m³"
            )
        remain_m -= mass_by_stop.get(s, 0.0)
        remain_v -= vol_by_stop.get(s, 0.0)
    return True, ""


# ---------------------------------------------------------------- 架次评估

def evaluate_sortie(
    plan: SortiePlan,
    uav: UAVType,
    leg_cache: LegCache,
    mass_by_stop: dict[str, float],
    vol_by_stop: dict[str, float],
    center_id: str = CENTER_ID,
) -> SortieEval:
    """评估一个多点串飞架次：能耗、时间、返航 SOC、可行性。

    能耗逐段累加，**每段的载荷是机上剩余载荷**（载荷递减）。
    """
    if not plan.stops:
        return SortieEval(0.0, 0.0, 0.0, 0.0, 1.0, True, "空架次")

    ok, reason = prefix_feasible(plan.stops, mass_by_stop, vol_by_stop, uav)
    if not ok:
        return SortieEval(0.0, 0.0, 0.0, 0.0, 1.0, False, reason)

    nodes = [center_id, *plan.stops]
    remain_m = sum(mass_by_stop.get(s, 0.0) for s in plan.stops)

    energy = 0.0
    t_fly = 0.0
    leg_loads: list[float] = []
    leg_energies: list[float] = []

    # 去程各段 + 回程
    # ★ 载荷递减的正确口径：第 m 段携带"尚未投送的货"。
    #   飞到第 k 个服务区的那一段，机上还带着第 k..M 站的货；
    #   在该站投送之后，下一段才减去它的质量。
    n_stops = len(plan.stops)
    for idx, (a, b) in enumerate(zip(nodes, nodes[1:])):
        g = leg_cache.get(a, b)
        seg = Segment(g["distance_m"], g["climb_m"], g["descent_m"])
        e = segment_energy_kwh(uav, seg, remain_m)
        energy += e
        t_fly += segment_time_s(uav, seg)
        leg_loads.append(remain_m)
        leg_energies.append(e)
        # 在第 (idx+1) 个服务区投送 → 开始递减
        if idx < n_stops:
            remain_m -= mass_by_stop.get(plan.stops[idx], 0.0)

    # 回程空载
    g_back = leg_cache.get(plan.stops[-1], center_id)
    seg_back = Segment(g_back["distance_m"], g_back["climb_m"], g_back["descent_m"])
    e_back = segment_energy_kwh(uav, seg_back, 0.0)
    energy += e_back
    t_fly += segment_time_s(uav, seg_back)
    leg_loads.append(0.0)
    leg_energies.append(e_back)

    n = plan.n_boxes
    t_ground = (
        uav.prepare_time_s
        + uav.box_load_time_s * n
        + (uav.handover_base_s + uav.handover_per_box_s * n) * len(plan.stops)
    )
    budget = uav.energy_budget_kwh
    feasible = energy <= budget + 1e-9
    reason = "" if feasible else (
        f"能耗 {energy:.4f} kWh > 预算 {budget:.4f} kWh"
    )
    return SortieEval(
        energy_kwh=energy,
        flight_time_s=t_fly,
        ground_time_s=t_ground,
        total_time_s=t_fly + t_ground,
        return_soc=max(0.0, 1.0 - energy / uav.energy_kwh),
        feasible=feasible,
        reason=reason,
        leg_loads=tuple(leg_loads),
        leg_energies=tuple(leg_energies),
    )


# ---------------------------------------------------------------- 选序

def best_stop_order(
    stops: Sequence[str],
    uav: UAVType,
    leg_cache: LegCache,
    mass_by_stop: dict[str, float],
    vol_by_stop: dict[str, float],
    max_perm: int = 6,
    center_id: str = CENTER_ID,
) -> tuple[tuple[str, ...], SortieEval]:
    """为给定服务区集合选出**能耗最低**的访问顺序。

    - 规模 ≤ `max_perm`：全排列精确求最优（n! 很小，6! = 720）
    - 规模更大：最近邻构造 + 2-opt 改进
    """
    stops = tuple(stops)
    if not stops:
        return (), evaluate_sortie(
            SortiePlan(uav.code, (), {}), uav, leg_cache, mass_by_stop, vol_by_stop, center_id
        )

    if len(stops) <= max_perm:
        best: tuple[tuple[str, ...], SortieEval] | None = None
        for perm in itertools.permutations(stops):
            plan = SortiePlan(uav.code, perm, {s: () for s in perm})
            ev = evaluate_sortie(plan, uav, leg_cache, mass_by_stop, vol_by_stop, center_id)
            if not ev.feasible:
                continue
            if best is None or ev.energy_kwh < best[1].energy_kwh - 1e-12:
                best = (perm, ev)
        if best is not None:
            return best
        # 全部排列都不可行 → 返回第一个顺序的评估（带不可行原因）
        perm = stops
        plan = SortiePlan(uav.code, perm, {s: () for s in perm})
        return perm, evaluate_sortie(
            plan, uav, leg_cache, mass_by_stop, vol_by_stop, center_id
        )

    def total_energy(order: Sequence[str]) -> tuple[float, SortieEval]:
        plan = SortiePlan(uav.code, tuple(order), {s: () for s in order})
        ev = evaluate_sortie(plan, uav, leg_cache, mass_by_stop, vol_by_stop, center_id)
        return ev.energy_kwh, ev

    # 最近邻
    remaining = list(stops)
    order: list[str] = []
    cur = center_id
    while remaining:
        nxt = min(remaining, key=lambda s: leg_cache.distance(cur, s))
        order.append(nxt)
        remaining.remove(nxt)
        cur = nxt
    # 2-opt
    improved = True
    best_order, best_ev = order, total_energy(order)[1]
    while improved:
        improved = False
        for i in range(len(best_order) - 1):
            for j in range(i + 1, len(best_order)):
                cand = best_order[:i] + best_order[i : j + 1][::-1] + best_order[j + 1 :]
                e, ev = total_energy(cand)
                if ev.feasible and e < best_ev.energy_kwh - 1e-12:
                    best_order, best_ev, improved = cand, ev, True
        if not improved:
            break
    return tuple(best_order), best_ev


# ---------------------------------------------------------------- 组合候选

def candidate_groups(
    service_ids: Sequence[str],
    leg_cache: LegCache,
    max_group: int = 3,
    seed_limit: int = 4,
    center_id: str = CENTER_ID,
) -> list[tuple[str, ...]]:
    """生成值得考虑的**服务区组合**（控制规模，避免组合爆炸）。

    策略：对每个服务区，取距其最近的 `seed_limit` 个邻居，
    枚举到 `max_group` 元的所有组合（含单元组）。

    ★ 依据：合并架次的价值来自"省一趟往返"，因此只在**地理邻近**的服务区
      之间才可能划算；远距离组合的段间飞行能耗会吃掉收益。
    """
    svc = list(service_ids)
    groups: set[tuple[str, ...]] = {(s,) for s in svc}
    for s in svc:
        others = sorted(
            (o for o in svc if o != s), key=lambda o: leg_cache.distance(s, o)
        )[:seed_limit]
        for k in range(2, min(max_group, len(others) + 1) + 1):
            for combo in itertools.combinations(others, k - 1):
                groups.add(tuple(sorted((s, *combo))))
    return sorted(groups, key=lambda g: (len(g), g))
