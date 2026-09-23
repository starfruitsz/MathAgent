"""问题一入口：最大安全载荷 + 货箱组批 + 多目标权衡 + ρ_g 敏感性。

用法：
    python -m src.q1_payload_grouping.run_q1
    python -m src.q1_payload_grouping.run_q1 --rho-step 0.05

输出（outputs/q1/）：
    metrics.json / params.json / run_log.json
    tables/*.csv    载荷表、容量表、组批结果、策略对比、Pareto、敏感性
    figures/*.png   策略对比、载荷曲线、ρ_g 敏感性
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

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

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 130
plt.rcParams["savefig.bbox"] = "tight"


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
    (out / "figures").mkdir(exist_ok=True)

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
    fig, ax = plt.subplots(1, 2, figsize=(12, 4.4))
    ax[0].bar(cmp_df["策略"], cmp_df["往返架次数"], color="#3b7dd8")
    ax[0].set_title("各策略往返架次数")
    ax[0].set_ylabel("架次数")
    ax[0].tick_params(axis="x", rotation=20)
    ax[1].scatter(cmp_df["总运输能耗（kWh）"], cmp_df["累计作业时间（s）"],
                  s=70, c="#d85a3b")
    for _, rr in cmp_df.iterrows():
        ax[1].annotate(rr["策略"], (rr["总运输能耗（kWh）"], rr["累计作业时间（s）"]),
                       fontsize=7, xytext=(4, 3), textcoords="offset points")
    ax[1].set_xlabel("总运输能耗 (kWh)")
    ax[1].set_ylabel("累计作业时间 (s)")
    ax[1].set_title("能耗—时间权衡")
    fig.savefig(out / "figures" / "q1_strategy_comparison.png")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 4.6))
    for code in sorted(uav_types):
        sub = curve_df[curve_df["type_code"] == code]
        med = sub.groupby("rho")["max_payload_kg"].median()
        ax.plot(med.index, med.values, marker="o", ms=3, label=f"{code} 型（中位数）")
    ax.axvline(DEFAULT_RESERVE_RATIO, color="k", ls="--", lw=1,
               label=f"附件取值 ρ={DEFAULT_RESERVE_RATIO:.2f}")
    ax.set_xlabel(r"返航安全余量 $\rho_g$")
    ax.set_ylabel("最大安全载荷 (kg)")
    ax.set_title(r"最大安全载荷随 $\rho_g$ 的变化（15 个服务区中位数）")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.savefig(out / "figures" / "q1_payload_vs_rho.png")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 4.8))
    feas = sweep_df[sweep_df["feasible"]]
    infeas = sweep_df[~sweep_df["feasible"]]
    ax.plot(feas["rho"], feas["n_sorties"], marker="o", ms=4, color="#3b7dd8",
            label="可行（架次数最少方案）")
    if len(infeas):
        ax.axvspan(infeas["rho"].min(), sweep_df["rho"].max(),
                   color="#d85a3b", alpha=0.12, label="不可行（存在无解服务区）")
    ax.axvline(DEFAULT_RESERVE_RATIO, color="k", ls="--", lw=1,
               label=f"附件取值 ρ={DEFAULT_RESERVE_RATIO:.2f}")
    ax.set_xlabel(r"返航安全余量 $\rho_g$")
    ax.set_ylabel("总架次数")
    ax.set_title(r"组批结果随 $\rho_g$ 的变化（每点取 Pareto 最优策略）")
    ax.grid(alpha=0.3)
    ax2 = ax.twinx()
    ax2.plot(feas["rho"], feas["total_energy_kwh"], marker="s", ms=4,
             color="#2e8b57", ls="--", label="总运输能耗")
    ax2.set_ylabel("总运输能耗 (kWh)", color="#2e8b57")
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=8, loc="upper left")
    fig.savefig(out / "figures" / "q1_rho_sensitivity.png")
    plt.close(fig)

    # ---------------- 落盘 ----------------
    runtime = time.perf_counter() - t0
    metrics = {
        "n_service_areas": len(service_ids),
        "n_boxes": int(len(bdf)),
        "n_uav_types": len(uav_types),
        "chosen_strategy": chosen.strategy,
        "chosen_n_sorties": chosen.n_sorties,
        "chosen_total_energy_kwh": round(chosen.total_energy_kwh, 6),
        "chosen_serial_total_time_s": round(chosen.serial_total_time_s, 3),
        "lower_bound_total_sorties": int(lb_df["架次数下界"].sum()),
        "n_pareto": len(front),
        "n_strategies": len(solutions),
        "rho_sweep_points": len(rho_grid),
        "runtime_sec": round(runtime, 2),
    }
    save_metrics("q1", metrics, params={"chosen": chosen.metrics()},
                 extra={"data_sources": ["调度中心与服务区.xlsx", "物资需求与配送时限.xlsx",
                                         "运输无人机数据.xlsx", "30米DEM.tif"]})
    save_json(
        {
            "strategies": {n: s.metrics() for n, s in solutions.items()},
            "chosen_sorties": solution_records(chosen),
            "lower_bounds_total": int(lb_df["架次数下界"].sum()),
        },
        out / "run_log.json",
    )

    log.info("完成，用时 %.1f s；输出目录 %s", runtime, out)
    print()
    print("=" * 78)
    print("问题一求解结果")
    print("=" * 78)
    print(cmp_df.to_string(index=False))
    print()
    print(f"架次数下界合计 = {int(lb_df['架次数下界'].sum())}，"
          f"选定方案 {chosen.n_sorties} 架次（策略 {chosen.strategy}）")
    print()
    print("ρ_g 敏感性（部分）：")
    print(sweep_df.iloc[:: max(1, len(sweep_df) // 8)].to_string(index=False))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    raise SystemExit(main())
