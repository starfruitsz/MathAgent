"""问题一（4）：返航安全余量 ρ_g 的敏感性分析。

题目要求：**讨论返航安全余量变化对不同机型最大安全载荷和货箱组批结果的影响**。

做法：把 ρ_g 从 0 扫到 0.5（步长 0.025），对每个取值：
    1. 重算 3 机型 × 15 服务区的最大安全载荷
    2. 重跑组批策略，记录架次数 / 总能耗 / 累计作业时间 / 可行与否
    3. 标出**临界点**：某机型在某服务区由"可行"变为"不可行"的 ρ_g

物理含义
--------
ρ_g 越大 → 可用能量 `(1−ρ_g)·E_g^use` 越小 → 最大安全载荷越小
        → 架次数越多 → 总能耗与作业时间上升
因此 ρ_g 是"安全裕度"与"运输效率"之间的直接权衡旋钮。
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import pandas as pd

from src.physics.leg_cache import LegCache
from src.physics.payload import UAVType, max_safe_payload
from src.q1_payload_grouping.grouping import (
    AreaCapacity,
    Box,
    InfeasibleError,
    Solution,
    _pack_area,
    _make_sorties,
    area_capacities,
)


@dataclass
class SensitivityRow:
    """一个 ρ_g 取值的汇总结果。"""

    rho: float
    n_sorties: int
    total_energy_kwh: float
    serial_total_time_s: float
    feasible: bool
    n_infeasible_areas: int
    type_usage: dict[str, int]
    max_payload_table: dict[tuple[str, str], float]
    """(服务区, 机型) → 最大安全载荷（kg）。"""


def capacities_with_reserve(
    service_ids: list[str],
    uav_types: dict[str, UAVType],
    leg_cache: LegCache,
    rho: float,
    center_id: str = "O01",
) -> dict[tuple[str, str], AreaCapacity]:
    """指定 ρ_g 下的容量表（其余逻辑复用 `area_capacities`）。"""
    adjusted = {c: replace(u, reserve_ratio=rho) for c, u in uav_types.items()}
    return area_capacities(service_ids, adjusted, leg_cache, center_id)


def sweep_reserve_ratio(
    boxes_by_area: dict[str, list[Box]],
    uav_types: dict[str, UAVType],
    leg_cache: LegCache,
    rhos: list[float],
    center_id: str = "O01",
) -> pd.DataFrame:
    """扫描 ρ_g，返回逐 ρ_g 的汇总表。

    对每个 ρ_g，**先在全部策略上求 Pareto 前沿**，再从中挑
    「架次数最少、同架次数取能耗最低」的那个方案作为该裕度下的结果。
    因此表中的数值是"该裕度下能达到的最好结果"，
    反映的是**安全裕度本身的代价**，而不是某个启发式的偶然表现。

    ★ `feasible=False` 表示该 ρ_g 下**存在无可行组批的服务区**
      （能量预算太小，连单箱都飞不到）—— 此时架次数/能耗已无实际意义。
    """
    from src.q1_payload_grouping.grouping import (
        _order_large_first,
        _order_small_first,
        pareto_frontier,
        solve_all_strategies,
    )

    service_ids = sorted(boxes_by_area)
    rows: list[dict] = []

    for rho in rhos:
        adjusted = {c: replace(u, reserve_ratio=rho) for c, u in uav_types.items()}
        caps = area_capacities(service_ids, adjusted, leg_cache, center_id)

        # 该 ρ_g 下"无可行组批"的服务区数（与策略无关，由容量决定）
        n_bad = 0
        for sid, bx in boxes_by_area.items():
            n_bad += int(
                not _area_has_any_fit(bx, caps, adjusted, sid)
            )

        solutions = solve_all_strategies(boxes_by_area, adjusted, leg_cache)
        if not solutions:
            rows.append(
                {
                    "rho": round(rho, 4),
                    "n_sorties": 0,
                    "total_energy_kwh": 0.0,
                    "serial_total_time_s": 0.0,
                    "feasible": False,
                    "n_infeasible_areas": n_bad,
                    "strategy": "—",
                    "types": "—",
                }
            )
            continue

        front = pareto_frontier(solutions.values())
        best = min(front, key=lambda s: (s.n_sorties, s.total_energy_kwh))
        usage = best.type_usage()
        rows.append(
            {
                "rho": round(rho, 4),
                "n_sorties": best.n_sorties,
                "total_energy_kwh": round(best.total_energy_kwh, 6),
                "serial_total_time_s": round(best.serial_total_time_s, 3),
                "feasible": n_bad == 0,
                "n_infeasible_areas": n_bad,
                "strategy": best.strategy,
                "types": "/".join(f"{k}:{v}" for k, v in sorted(usage.items())),
            }
        )
    return pd.DataFrame(rows)


def _area_has_any_fit(
    boxes: Sequence[Box],
    caps: dict[tuple[str, str], AreaCapacity],
    uav_types: dict[str, UAVType],
    service_id: str,
) -> bool:
    """该服务区是否存在"每个箱子都能被某机型单独装载"的机型组合。

    注意：这只是必要条件（装箱是否可行还要看组合），
    用于给出 ρ_g 过大的**指示性**临界点。
    """
    for b in boxes:
        ok = any(
            cap.feasible
            and b.mass_kg <= cap.max_payload_kg + 1e-9
            and b.volume_m3 <= cap.volume_m3 + 1e-12
            for (sid, _c), cap in caps.items()
            if sid == service_id
        )
        if not ok:
            return False
    return True


def critical_reserve_ratios(
    service_ids: list[str],
    uav_types: dict[str, UAVType],
    leg_cache: LegCache,
    rho_grid: list[float],
    center_id: str = "O01",
) -> pd.DataFrame:
    """找出 (服务区, 机型) 由可行变为不可行的**临界 ρ_g**。

    判据：最大安全载荷降到 0 以下（即该区该机型根本飞不到）。
    返回每个 (服务区, 机型) 的"最后可行 ρ_g"。
    """
    rows: list[dict] = []
    for code, uav in uav_types.items():
        for sid in service_ids:
            leg_out = leg_cache.get(center_id, sid)
            leg_back = leg_cache.get(sid, center_id)
            last_ok: float | None = None
            q_at_last = 0.0
            for rho in rho_grid:
                u = replace(uav, reserve_ratio=rho)
                try:
                    q = max_safe_payload(
                        u,
                        leg_out["distance_m"],
                        leg_out["climb_m"], leg_out["descent_m"],
                        leg_back["climb_m"], leg_back["descent_m"],
                    )
                    ok = q > 1e-9
                except ValueError:
                    q, ok = 0.0, False
                if ok:
                    last_ok = rho
                    q_at_last = q
                else:
                    break
            rows.append(
                {
                    "service_id": sid,
                    "type_code": code,
                    "last_feasible_rho": last_ok,
                    "payload_at_last_rho_kg": round(q_at_last, 3),
                    "distance_m": round(leg_out["distance_m"], 1),
                }
            )
    return pd.DataFrame(rows)


def payload_curve(
    service_ids: list[str],
    uav_types: dict[str, UAVType],
    leg_cache: LegCache,
    rhos: list[float],
    center_id: str = "O01",
) -> pd.DataFrame:
    """给出 (服务区, 机型, ρ_g) → 最大安全载荷的长表，用于画曲线。"""
    rows: list[dict] = []
    for code, uav in uav_types.items():
        for sid in service_ids:
            leg_out = leg_cache.get(center_id, sid)
            leg_back = leg_cache.get(sid, center_id)
            for rho in rhos:
                u = replace(uav, reserve_ratio=rho)
                try:
                    q = max_safe_payload(
                        u,
                        leg_out["distance_m"],
                        leg_out["climb_m"], leg_out["descent_m"],
                        leg_back["climb_m"], leg_back["descent_m"],
                    )
                except ValueError:
                    q = 0.0
                rows.append(
                    {"service_id": sid, "type_code": code, "rho": round(rho, 4),
                     "max_payload_kg": round(q, 4)}
                )
    return pd.DataFrame(rows)
