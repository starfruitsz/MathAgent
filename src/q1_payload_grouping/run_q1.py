"""问题一入口：最大安全载荷 + 货箱组批 + 多目标权衡 + ρ_g 敏感性。

用法：
    python -m src.q1_payload_grouping.run_q1
    python -m src.q1_payload_grouping.run_q1 --rho-step 0.05

输出（outputs/q1/）：
    metrics.json / params.json / run_log.json
    tables/*.csv    载荷表、容量表、组批结果、策略对比、Pareto、敏感性
    tables/*.csv   最大安全载荷、组批方案、下界、ρ_g 扫描
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd


from src.common.config import DATA_PROCESSED, DEFAULT_RESERVE_RATIO, outputs_dir
from src.common.io_utils import get_logger, save_json, save_metrics, save_table
from src.physics.leg_cache import load_cached
from src.physics.payload import UAVType
from src.q1_payload_grouping.grouping import (
    Box,
    Solution,
    area_capacities,
    pareto_frontier,
    solve_all_strategies,
    sortie_lower_bound,
)
from src.q1_payload_grouping.sensitivity import (
    critical_reserve_ratios,
    payload_curve,
    sweep_reserve_ratio,
)
from src.q0_data import build_processed as BP



def to_uav_type(r: pd.Series) -> UAVType:
    return UAVType(
        code=str(r["code"]), name=str(r["name"]),
        empty_mass_kg=float(r["empty_mass_kg"]),
        max_payload_kg=float(r["max_payload_kg"]),
        volume_m3=float(r["volume_m3"]),
        cruise_speed_ms=float(r["cruise_speed_ms"]),
        range_empty_m=float(r["range_empty_m"]),
        range_full_m=float(r["range_full_m"]),
        energy_kwh=float(r["energy_kwh"]),
        reserve_ratio=float(r["reserve_ratio"]),
        prepare_time_s=float(r["prepare_time_s"]),
        box_load_time_s=float(r["box_load_time_s"]),
        handover_base_s=float(r["handover_base_s"]),
        handover_per_box_s=float(r["handover_per_box_s"]),
        climb_speed_ms=float(r["climb_speed_ms"]),
        descent_speed_ms=float(r["descent_speed_ms"]),
        climb_efficiency=float(r["climb_efficiency"]),
        descent_efficiency=float(r["descent_efficiency"]),
    )


def load_inputs() -> tuple[
    dict[str, list[Box]], dict[str, UAVType], list[str], pd.DataFrame
]:
    bdf = BP.load_boxes()
    tdf = BP.load_uav_types()
    ndf = BP.load_nodes()

    uav_types = {str(r["code"]): to_uav_type(r) for _, r in tdf.iterrows()}
    boxes_by_area: dict[str, list[Box]] = {}
    for _, r in bdf.iterrows():
        b = Box(
            box_id=str(r["box_id"]),
            service_id=str(r["service_id"]),
            mass_kg=float(r["mass_kg"]),
            volume_m3=float(r["volume_m3"]),
            is_first_batch=bool(r["is_first_batch"]),
            first_batch_deadline_s=(
                float(r["first_batch_deadline_s"])
                if pd.notna(r["first_batch_deadline_s"]) else None
            ),
            expected_time_s=float(r["expected_time_s"]),
            priority=int(r["priority"]),
        )
        boxes_by_area.setdefault(b.service_id, []).append(b)

    service_ids = sorted(ndf.loc[ndf["kind"] == "service", "id"].astype(str))
    return boxes_by_area, uav_types, service_ids, bdf


def solution_records(sol: Solution) -> list[dict]:
    """按 `结果提交模板.xlsx` 的 `Q1_单点组批` sheet 列序输出。"""
    rows = []
    for s in sol.all_sorties:
        rows.append(
            {
                "架次编号": s.sortie_id,
                "服务区编号": s.service_id,
                "机型编号": s.type_code,
                "货箱编号列表": "|".join(s.box_ids),
                "总质量（kg）": round(s.total_mass_kg, 3),
                "总体积（m³）": round(s.total_volume_m3, 5),
                "往返时间（s）": round(s.roundtrip_time_s, 1),
                "架次能耗（kWh）": round(s.energy_kwh, 5),
                "返航SOC（%）": round(s.return_soc * 100, 2),
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="D 题问题一求解器")
    ap.add_argument("--rho-step", type=float, default=0.025, help="ρ_g 扫描步长")
    ap.add_argument("--rho-max", type=float, default=0.50, help="ρ_g 扫描上限")
    args = ap.parse_args(argv)

    log = get_logger("q1")
    out = outputs_dir("q1")
    (out / "tables").mkdir(exist_ok=True)

    t0 = time.perf_counter()
    log.info("载入输入 ...")
    boxes_by_area, uav_types, service_ids, bdf = load_inputs()
    leg_cache = load_cached()
    log.info(
        "服务区 %d 个 / 货箱 %d 个 / 机型 %s / 航段缓存 %d 条",
        len(service_ids), len(bdf), list(uav_types), leg_cache.n_legs,
    )

    # ---------------- (1) 最大安全载荷 ----------------
    caps = area_capacities(service_ids, uav_types, leg_cache)
    payload_rows = []
    for sid in service_ids:
        for code in sorted(uav_types):
            c = caps[(sid, code)]
            payload_rows.append(
                {
                    "服务区编号": sid,
                    "机型编号": code,
                    "单向距离（m）": round(c.distance_m, 1),
                    "最大安全载荷（kg）": round(c.max_payload_kg, 3),
                    "结构上限（kg）": uav_types[code].max_payload_kg,
                    "装载体积上限（m³）": c.volume_m3,
                    "生效约束": {"structure": "结构上限", "energy": "能量",
                                 "infeasible": "不可行"}[c.binding],
                    "空载往返能耗（kWh）": round(c.empty_energy_kwh, 4),
                    "往返时间（s）": round(c.roundtrip_time_s, 1),
                }
            )
    payload_df = pd.DataFrame(payload_rows)
    save_table(payload_df, out / "tables" / "q1_1_max_safe_payload.csv")
    log.info("(1) 最大安全载荷表：%d 行（%d 服务区 × %d 机型）",
             len(payload_df), len(service_ids), len(uav_types))

    # ---------------- (2)(3) 组批与多目标 ----------------
    solutions = solve_all_strategies(boxes_by_area, uav_types, leg_cache)
    if not solutions:
        log.error("没有任何可行策略 —— 请检查机型/货箱参数")
        return 1
    log.info("(2) 可行策略：%s", list(solutions))

    cmp_rows = []
    for name, sol in solutions.items():
        m = sol.metrics()
        cmp_rows.append(
            {
                "策略": name,
                "说明": sol.note,
                "往返架次数": int(m["n_sorties"]),
                "总运输能耗（kWh）": m["total_energy_kwh"],
                "累计作业时间（s）": m["serial_total_time_s"],
                "并行完工时间（s）": m["parallel_makespan_s"],
                "机型使用": "/".join(f"{k}×{v}" for k, v in sorted(sol.type_usage().items())),
            }
        )
    cmp_df = pd.DataFrame(cmp_rows).sort_values("往返架次数").reset_index(drop=True)
    save_table(cmp_df, out / "tables" / "q1_3_strategy_comparison.csv")

    # 架次数下界
    lb_rows = []
    for sid in service_ids:
        lb = sortie_lower_bound(boxes_by_area[sid], uav_types, caps, sid)
        lb_rows.append(
            {
                "服务区编号": sid,
                "箱数": len(boxes_by_area[sid]),
                "总质量（kg）": round(lb["total_mass_kg"], 1),
                "总体积（m³）": round(lb["total_volume_m3"], 4),
                "最好载荷（kg）": round(lb["best_payload_kg"], 1),
                "最好体积（m³）": round(lb["best_volume_m3"], 3),
                "质量下界": lb["lb_mass"],
                "体积下界": lb["lb_volume"],
                "架次数下界": lb["lb"],
            }
        )
    lb_df = pd.DataFrame(lb_rows)
    # 与"架次数最少的策略"逐区对比，暴露启发式与下界的差距
    fewest = min(solutions.values(), key=lambda s: (s.n_sorties, s.total_energy_kwh))
    lb_df["最少架次策略"] = [fewest.areas[sid].n_sorties for sid in lb_df["服务区编号"]]
    lb_df["与下界差距"] = lb_df["最少架次策略"] - lb_df["架次数下界"]
    save_table(lb_df, out / "tables" / "q1_3_sortie_lower_bounds.csv")

    # Pareto
    front = pareto_frontier(solutions.values())
    pf_df = pd.DataFrame(
        [
            {"策略": s.strategy, "往返架次数": s.n_sorties,
             "总运输能耗（kWh）": round(s.total_energy_kwh, 4),
             "累计作业时间（s）": round(s.serial_total_time_s, 1)}
            for s in front
        ]
    )
    save_table(pf_df, out / "tables" / "q1_3_pareto_frontier.csv")
    log.info("(3) Pareto 非支配解 %d 个：%s", len(front), [s.strategy for s in front])

    # 选定方案 = Pareto 中架次数最少者；并输出其明细
    chosen = min(front, key=lambda s: (s.n_sorties, s.total_energy_kwh))
    sortie_df = pd.DataFrame(solution_records(chosen))
    save_table(sortie_df, out / "tables" / "q1_2_groups_by_service.csv")
    log.info("选定方案 %s：%d 架次 / %.3f kWh / %.1f s",
             chosen.strategy, chosen.n_sorties,
             chosen.total_energy_kwh, chosen.serial_total_time_s)

    # ---------------- (4) ρ_g 敏感性 ----------------
    rho_grid = []
    r = 0.0
    while r <= args.rho_max + 1e-9:
        rho_grid.append(round(r, 4))
        r += args.rho_step
    log.info("(4) ρ_g 敏感性扫描：%d 个取值（0 → %.2f）", len(rho_grid), args.rho_max)

    sweep_df = sweep_reserve_ratio(boxes_by_area, uav_types, leg_cache, rho_grid)
    save_table(sweep_df, out / "tables" / "q1_4_rho_sweep.csv")

    curve_df = payload_curve(service_ids, uav_types, leg_cache, rho_grid)
    save_table(curve_df, out / "tables" / "q1_4_payload_vs_rho.csv")

    crit_df = critical_reserve_ratios(service_ids, uav_types, leg_cache, rho_grid)
    save_table(crit_df, out / "tables" / "q1_4_critical_rho.csv")

    # ---------------- 图 ----------------
    log.info("图已改由 src/report/make_figures.py 统一生成（论文图表唯一产出点）；"
             "本模块只产出 outputs/ 下的数据表，不再自绘图片。")
    log.info("完成，用时 %.1f s", time.perf_counter() - t0)
    return 0


if __name__ == "__main__":
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    raise SystemExit(main())
