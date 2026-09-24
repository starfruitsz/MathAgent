"""问题二四目标的权衡关系扫描：架次数 ↔ 及时性 ↔ 完工时间 ↔ 能耗。

题目要求"综合考虑配送及时性、全部任务完成时间、运输能耗和架次数等指标进行
优化，并说明各指标之间的权衡关系"。本脚本扫 `sortie_per_unit`（每个架次的
惩罚）与 `load_balance`（机队摊平力度），给出各指标随权重的变化以及
**帕累托前沿**，用于论文的"权衡关系"一节与推荐方案的选取依据。

用法：
    python scripts/diag/q2_tradeoff_sweep.py
"""

from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path

from src.physics.leg_cache import load_cached
from src.q2_transport_schedule.run_q2 import load_inputs, solve
from src.q2_transport_schedule.solver import DEFAULT_WEIGHTS

OUT = Path("outputs/diag")
OUT.mkdir(parents=True, exist_ok=True)
logging.disable(logging.INFO)


def main() -> int:
    boxes, uav_types, fleet, bat_inv, t_full, deadlines, _ = load_inputs()
    lc = load_cached()

    rows = []
    # ① 只改"架次惩罚"（题目要求"综合考虑四个指标"，这里给出各指标随权重的变化）
    for w in (0.05, 0.5, 2.0, 8.0, 32.0, 128.0):
        wt = dataclasses.replace(DEFAULT_WEIGHTS, sortie_per_unit=w)
        r = solve(boxes, uav_types, lc, deadlines, fleet, bat_inv, t_full,
                  do_local_search=True, fleet_mode="auto", weights=wt)
        rows.append({
            "sweep": "sortie_w", "value": w,
            "chosen": r.note.split("；")[0].split("=")[0] if r.note else "",
            "n_sorties": r.n_sorties, "energy_kwh": round(r.total_energy_kwh, 3),
            "makespan_h": round(r.makespan_s / 3600.0, 3),
            "on_time": round(r.on_time_rate, 4),
            "viol_fb": r.violations_first_batch, "viol_exp": r.violations_expected,
            "score": round(r.objective, 2),
        })
        print(f"sortie_w={w:<6} → {r.n_sorties:3d} 架次 / {r.total_energy_kwh:6.2f} kWh / "
              f"{r.makespan_s/3600:5.2f} h / 准时 {r.on_time_rate:5.1%} / "
              f"违规 {r.violations_first_batch}+{r.violations_expected} / 分 {r.objective:8.1f}")

    # ② 只改"能耗惩罚"：能耗与架次数/及时性的对冲
    for we in (0.25, 1.0, 4.0, 16.0):
        wt = dataclasses.replace(DEFAULT_WEIGHTS, energy_per_kwh=we)
        r = solve(boxes, uav_types, lc, deadlines, fleet, bat_inv, t_full,
                  do_local_search=True, fleet_mode="auto", weights=wt)
        rows.append({
            "sweep": "energy_w", "value": we,
            "chosen": r.note.split("；")[0].split("=")[0] if r.note else "",
            "n_sorties": r.n_sorties, "energy_kwh": round(r.total_energy_kwh, 3),
            "makespan_h": round(r.makespan_s / 3600.0, 3),
            "on_time": round(r.on_time_rate, 4),
            "viol_fb": r.violations_first_batch, "viol_exp": r.violations_expected,
            "score": round(r.objective, 2),
        })
        print(f"energy_w={we:<6} → {r.n_sorties:3d} 架次 / {r.total_energy_kwh:6.2f} kWh / "
              f"{r.makespan_s/3600:5.2f} h / 准时 {r.on_time_rate:5.1%} / "
              f"违规 {r.violations_first_batch}+{r.violations_expected} / 分 {r.objective:8.1f}")

    # ③ 只改"完工时间惩罚"
    for wm in (0.0, 0.25, 1.0, 4.0):
        wt = dataclasses.replace(DEFAULT_WEIGHTS, makespan_per_s=wm / 3600.0)
        r = solve(boxes, uav_types, lc, deadlines, fleet, bat_inv, t_full,
                  do_local_search=True, fleet_mode="auto", weights=wt)
        rows.append({
            "sweep": "makespan_w", "value": wm,
            "chosen": r.note.split("；")[0].split("=")[0] if r.note else "",
            "n_sorties": r.n_sorties, "energy_kwh": round(r.total_energy_kwh, 3),
            "makespan_h": round(r.makespan_s / 3600.0, 3),
            "on_time": round(r.on_time_rate, 4),
            "viol_fb": r.violations_first_batch, "viol_exp": r.violations_expected,
            "score": round(r.objective, 2),
        })
        print(f"makespan_w={wm:<5} → {r.n_sorties:3d} 架次 / {r.total_energy_kwh:6.2f} kWh / "
              f"{r.makespan_s/3600:5.2f} h / 准时 {r.on_time_rate:5.1%} / "
              f"违规 {r.violations_first_batch}+{r.violations_expected} / 分 {r.objective:8.1f}")

    # ④ 四种代表方案的正面对比（论文"权衡关系"一节的表）
    for label, mode, ps in (("同构A", "A", False), ("同构B", "B", False),
                            ("同构C", "C", False),
                            ("混合-大机型", "mixed", False),
                            ("混合-小机型", "mixed", True)):
        r = solve(boxes, uav_types, lc, deadlines, fleet, bat_inv, t_full,
                  do_local_search=True, fleet_mode=mode, prefer_small=ps)
        rows.append({
            "sweep": "strategy", "value": label, "chosen": label,
            "n_sorties": r.n_sorties, "energy_kwh": round(r.total_energy_kwh, 3),
            "makespan_h": round(r.makespan_s / 3600.0, 3),
            "on_time": round(r.on_time_rate, 4),
            "viol_fb": r.violations_first_batch, "viol_exp": r.violations_expected,
            "score": round(r.objective, 2),
        })
        print(f"{label:<10} → {r.n_sorties:3d} 架次 / {r.total_energy_kwh:6.2f} kWh / "
              f"{r.makespan_s/3600:5.2f} h / 准时 {r.on_time_rate:5.1%} / "
              f"违规 {r.violations_first_batch}+{r.violations_expected} / 分 {r.objective:8.1f}")

    (OUT / "q2_tradeoff_sweep.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {OUT / 'q2_tradeoff_sweep.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
