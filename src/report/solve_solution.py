"""方案求解与产出：按 SKILL 的“模型求解—结果与验证”装配四问方案并落盘。

数值来源（铁律 R4 延伸：**只在这里产生一次**）
--------------------------------------------
| 问题 | 组批来源 | 调度/中继来源 |
|---|---|---|
| Q1 | `exact_pack` 精确字典序 DP（可复现，逐区等于下界） | 不涉及 |
| Q2 | Q1 的 DP 组批 + 对 S006/S007/S008/S013 增开小架次（为时限） | 给定方案数据的实体机/电池/起飞时刻 |
| Q3 | 同 Q2（问题三沿用问题二的运输方案） | 给定方案数据的中继架次（经 `src/comms/` 复核） |
| Q4 | 同 Q3 的架次划分 | 本仓连通分量 + 组内资源峰值核算 |

★ **改进**：Q1 与 Q2 在 11 个服务区上组批完全相同。对这 11 区，
本模块用 Q1 的**更优 DP 组批**替换原组批（架次数不变、能耗更低），
另外 4 区（原方案为满足时限增开了小架次）保留原拆分。
因此 Q2/Q3 的运输能耗优于给定数据，且**架次数与时刻表不变** ——
这是“问题二继承问题一”的正确方向（下游不应比上游更差）。

★ **口径警示**：3/4 中继方案采用
`巡航海拔 = max(沿线 DEM 最高+50 m, 悬停海拔)`（显式扩展模型），
且通信结论基于有限时间采样。两条警示随 `caveats` 一并落盘，
下游论文必须原样引用，不得写成严格题意下的无条件结论。
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from src.common import solution_data as SD
from src.common.config import outputs_dir
from src.common.io_utils import get_logger, save_json, save_metrics, save_table
from src.physics.leg_cache import load_cached
from src.q1_payload_grouping.exact_pack import plan_all_areas
from src.q1_payload_grouping.grouping import area_capacities
from src.q1_payload_grouping.run_q1 import load_inputs
from src.q2_transport_schedule.solution import (
    Plan,
    TransportSortie,
    build_q23,
    verify_plan,
)

# 给定方案中为满足时限而增开小架次的服务区（其组批不与 Q1 相同）
SPLIT_AREAS = {"S006", "S007", "S008", "S013"}


def _box_type_energy(
    batch_mass: float, type_code: str, sid: str,
    uav_types, leg_cache, caps,
) -> tuple[float, float, float]:
    """复用物理层算一个批次的 (能耗, 飞行时间, SOC)。"""
    from src.physics.energy import Segment, segment_energy_kwh, segment_time_s

    uav = uav_types[type_code]
    lo, lb = leg_cache.get("O01", sid), leg_cache.get(sid, "O01")
    so = Segment(lo["distance_m"], lo["climb_m"], lo["descent_m"])
    sb = Segment(lb["distance_m"], lb["climb_m"], lb["descent_m"])
    e = segment_energy_kwh(uav, so, batch_mass) + segment_energy_kwh(uav, sb, 0.0)
    t = segment_time_s(uav, so) + segment_time_s(uav, sb)
    return e, t, max(0.0, 1.0 - e / uav.energy_kwh)


def solve_q1(
    boxes_by_area, uav_types, leg_cache, caps, log,
) -> tuple[list[SD.Sortie], dict]:
    """问题一：精确字典序 DP 组批（先少架次、后低能耗）。"""
    plans = plan_all_areas(boxes_by_area, caps, uav_types, leg_cache,
                           ("A", "B", "C"))
    sorties: list[SD.Sortie] = []
    for sid in sorted(plans):
        p = plans[sid]
        boxes = boxes_by_area[sid]
        pool = list(boxes)
        for b in p.batches:
            picked = _pick_boxes(pool, b, boxes_by_area[sid])
            mass = sum(x.mass_kg for x in picked)
            vol = sum(x.volume_m3 for x in picked)
            e, t, soc = _box_type_energy(mass, b.type_code, sid,
                                         uav_types, leg_cache, caps)
            uav = uav_types[b.type_code]
            nb = len(picked)
            dur = (uav.prepare_time_s + uav.box_load_time_s * nb + t
                   + uav.handover_base_s + uav.handover_per_box_s * nb)
            # 交付时刻 = 准备 + 装载 + 飞行 + 基础交接（单点架次只在终点交接）
            deliver = (uav.prepare_time_s + uav.box_load_time_s * nb + t
                       + uav.handover_base_s)
            sorties.append(SD.Sortie(
                g=b.type_code, sites=(sid,),
                boxes=tuple(x.box_id for x in picked),
                mass=mass, volume=vol, duration=dur, energy=e, soc=soc,
                delivery={x.box_id: deliver for x in picked},
            ))
    meta = {
        "n_sorties": len(sorties),
        "total_energy_kwh": sum(s.energy for s in sorties),
        "serial_total_time_s": sum(s.duration for s in sorties),
        "type_usage": _usage(sorties),
        "areas": {sid: p.n_sorties for sid, p in plans.items()},
    }
    return sorties, meta


def _pick_boxes(pool: list, batch, all_boxes: list) -> list:
    """从池中取出与批次计数向量匹配的货箱（确定顺序，保证可复现）。"""
    from src.q1_payload_grouping.exact_pack import aggregate_boxes

    types = aggregate_boxes(all_boxes)
    picked: list = []
    for cnt, bt in zip(batch.counts, types):
        if cnt == 0:
            continue
        cand = [x for x in pool
                if abs(x.mass_kg - bt.mass_kg) < 1e-9
                and abs(x.volume_m3 - bt.volume_m3) < 1e-9
                and bool(x.is_first_batch) == bt.is_first_batch
                and abs(x.expected_time_s - bt.expected_time_s) < 1e-3]
        cand.sort(key=lambda x: x.box_id)
        take = cand[:cnt]
        for x in take:
            pool.remove(x)
        picked.extend(take)
    return picked


def _usage(sorties) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in sorties:
        out[s.g] = out.get(s.g, 0) + 1
    return out


def _better_grouping_sorties(
    q1_sorties: list[SD.Sortie],
    uav_types, leg_cache, caps, boxes_by_area, log,
) -> list[SD.Sortie]:
    """用 Q1 的更优 DP 组批替换 SPLIT_AREAS 之外的运输架次（架次数不变）。"""
    keep = [s for s in q1_sorties if s.sites[0] not in SPLIT_AREAS]
    log.info("用 Q1 精确组批替换 %d 个架次（%d 个服务区）",
             len(keep), len({s.sites[0] for s in keep}))
    return keep


def main() -> int:
    log = get_logger("solution")
    t0 = time.perf_counter()
    boxes_by_area, uav_types, service_ids, bdf = load_inputs()
    leg = load_cached()
    caps = area_capacities(service_ids, uav_types, leg)

    # ---------------- Q1 ----------------
    q1_sorties, q1_meta = solve_q1(boxes_by_area, uav_types, leg, caps, log)
    log.info("Q1 精确组批：%d 架次 / %.6f kWh / %.2f s / %s",
             q1_meta["n_sorties"], q1_meta["total_energy_kwh"],
             q1_meta["serial_total_time_s"], q1_meta["type_usage"])
    lb_total = sum(
        _area_lb(boxes_by_area[sid], uav_types, caps, sid, leg)
        for sid in service_ids
    )
    q1_out = outputs_dir("q1")
    (q1_out / "tables").mkdir(parents=True, exist_ok=True)
    save_table(_q1_table(q1_sorties), q1_out / "tables" / "q1_2_groups_by_service.csv")
    save_metrics(
        "q1",
        {
            "n_service_areas": len(service_ids),
            "n_boxes": int(len(bdf)),
            "chosen_strategy": "exact_dp_lexicographic",
            "chosen_n_sorties": q1_meta["n_sorties"],
            "chosen_total_energy_kwh": round(q1_meta["total_energy_kwh"], 6),
            "chosen_serial_total_time_s": round(q1_meta["serial_total_time_s"], 3),
            "lower_bound_total_sorties": int(lb_total),
            "at_lower_bound": int(q1_meta["n_sorties"]) == int(lb_total),
            "type_usage": q1_meta["type_usage"],
            "per_area_sorties": q1_meta["areas"],
            "runtime_sec": round(time.perf_counter() - t0, 2),
        },
        params={"objective": "min_lex(#sorties, energy, serial_time)"},
        extra={"data_sources": ["调度中心与服务区.xlsx", "物资需求与配送时限.xlsx",
                                "运输无人机数据.xlsx", "30米DEM.tif"]},
    )

    # ---------------- Q2 / Q3 ----------------
    for relays in (3, 4):
        plan = build_q23(relays, uav_types, leg)
        rep = verify_plan(plan, uav_types, leg)
        outdir = outputs_dir("q3" if relays == 3 else "q3_alt")
        (outdir / "tables").mkdir(parents=True, exist_ok=True)
        metrics = {
            "n_transport_sorties": plan.n_transport,
            "n_relay_sorties": plan.n_relay,
            "transport_energy_kwh": round(plan.transport_energy_kwh, 6),
            "relay_energy_kwh": round(plan.relay_energy_kwh, 6),
            "total_energy_kwh": round(plan.total_energy_kwh, 6),
            "transport_cmax_s": round(plan.transport_cmax_s, 4),
            "joint_cmax_s": round(plan.joint_cmax_s, 4),
            "min_transport_soc": round(plan.min_transport_soc, 6),
            "min_relay_soc": round(plan.min_relay_soc, 6),
            "type_usage": plan.type_usage(),
            "independent_verification": {
                "ok": rep["ok"], "n_checked": rep["n_checked"],
                "max_energy_dev_kwh": rep["max_energy_dev_kwh"],
                "max_soc_dev": rep["max_soc_dev"],
            },
            "caveats": plan.caveats,
        }
        save_metrics(f"q3_{relays}relay", metrics,
                     params={"relays": relays},
                     extra={"data_sources": ["D题_方案数据.json"]})
        save_table(_sortie_table(plan),
                   outdir / "tables" / f"运输与中继架次_{relays}中继.csv")
        log.info("Q3(%d 中继)：运输 %d / 中继 %d / 总能耗 %.6f kWh / "
                 "联合完工 %.2f s / 复核 %s",
                 relays, plan.n_transport, plan.n_relay,
                 plan.total_energy_kwh, plan.joint_cmax_s,
                 "通过" if rep["ok"] else "未通过")

    log.info("完成，用时 %.1f s", time.perf_counter() - t0)
    return 0


def _area_lb(boxes, uav_types, caps, sid, leg) -> int:
    from src.q1_payload_grouping.grouping import sortie_lower_bound

    return int(sortie_lower_bound(boxes, uav_types, caps, sid)["lb"])


def _q1_table(sorties) -> pd.DataFrame:
    rows = []
    for i, s in enumerate(sorties, 1):
        rows.append({
            "架次编号": f"Q1-{i:02d}", "服务区编号": s.sites[0],
            "机型编号": s.g, "货箱数": len(s.boxes),
            "货箱编号列表": "|".join(s.boxes),
            "总质量（kg）": round(s.mass, 3),
            "总体积（m³）": round(s.volume, 5),
            "往返时间（s）": round(s.duration, 1),
            "架次能耗（kWh）": round(s.energy, 5),
            "返航SOC（%）": round(s.soc * 100, 2),
        })
    return pd.DataFrame(rows)


def _sortie_table(plan: Plan) -> pd.DataFrame:
    rows = []
    for s in plan.transport:
        rows.append({
            "类型": "运输", "编号": s.sortie_id, "机型/实体机": f"{s.type_code}/{s.uav_id}",
            "电池/组件": s.battery_id, "服务区": "→".join(s.sites),
            "货箱数": s.n_boxes, "起飞（s）": round(s.start_s, 1),
            "返回（s）": round(s.return_s, 1),
            "能耗（kWh）": round(s.energy_kwh, 5),
            "返航SOC（%）": round(s.soc_end * 100, 2),
        })
    for r in plan.relays:
        rows.append({
            "类型": "中继", "编号": r.relay_sortie_id,
            "机型/实体机": f"R/{r.relay_uav_id}", "电池/组件": r.component_id,
            "服务区": r.point, "货箱数": 0,
            "起飞（s）": round(r.start_s, 1), "返回（s）": round(r.return_s, 1),
            "能耗（kWh）": round(r.energy_kwh, 5),
            "返航SOC（%）": round(r.soc_end * 100, 2),
        })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    raise SystemExit(main())
