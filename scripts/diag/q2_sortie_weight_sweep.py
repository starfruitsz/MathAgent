"""扫描"架次惩罚"权重：看架次数能被压到多少，同时时限是否仍全部满足。

动机：题目要求"综合考虑配送及时性、全部任务完成时间、运输能耗和架次数"，
但不指定优先级。本脚本给出架次数 ↔ 及时性 ↔ 完工时间 ↔ 能耗 的权衡曲线，
并回答"能否在不牺牲时限的前提下把架次数压到理论下界 24"。

理论下界推导：总需求 758 kg / 2.011 m³；机队（A×4+B×2+C×2）单轮容量
320 kg / 0.886 m³ ⇒ ⌈758/320⌉ = 3 轮 × 8 架 = 24 架次。

用法：
    python scripts/diag/q2_sortie_weight_sweep.py
"""

from __future__ import annotations

import dataclasses
import json
import logging
import sys
from pathlib import Path

from src.physics.leg_cache import load_cached
from src.q2_transport_schedule.run_q2 import load_inputs, solve
from src.q2_transport_schedule.solver import DEFAULT_WEIGHTS

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
logging.disable(logging.INFO)

OUT = Path("outputs/diag")


def main() -> int:
    boxes, ut, fleet, bi, tf, dl, _ = load_inputs()
    lc = load_cached()
    rows = []
    print(f"{'sortie_w':>9} {'架次数':>7} {'能耗kWh':>9} {'完工h':>7} "
          f"{'准时率':>8} {'首批违规':>9} {'期望违规':>9}")
    print("-" * 70)
    for w in (0.05, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0):
        wt = dataclasses.replace(DEFAULT_WEIGHTS, sortie_per_unit=w)
        r = solve(boxes, ut, lc, dl, fleet, bi, tf,
                  do_local_search=True, fleet_mode="auto", weights=wt)
        rows.append({
            "sortie_per_unit": w, "n_sorties": r.n_sorties,
            "energy_kwh": round(r.total_energy_kwh, 3),
            "makespan_h": round(r.makespan_s / 3600.0, 3),
            "on_time_rate": round(r.on_time_rate, 4),
            "viol_first_batch": r.violations_first_batch,
            "viol_expected": r.violations_expected,
            "score": round(r.objective, 2),
        })
        print(f"{w:>9} {r.n_sorties:>7} {r.total_energy_kwh:>9.2f} "
              f"{r.makespan_s/3600:>7.2f} {r.on_time_rate:>8.1%} "
              f"{r.violations_first_batch:>9} {r.violations_expected:>9}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "q2_sortie_weight_sweep.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {OUT / 'q2_sortie_weight_sweep.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
