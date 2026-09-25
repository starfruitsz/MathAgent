"""Q2 `max_group`（单架次最多访问几个服务区）× 架次权重 的网格扫描。

动机：题目只说"每个运输架次可访问一个或多个服务区"，**没有限制站数**；
而求解器把 `max_group` 默认设成 3——这是**自加的人为约束**。
站数上限越小，架次越难装满（实测装载率仅 71%、理论下界 24 架次却排出 28 架次）。
本脚本检验放宽站数能否在 **0 违规**前提下把架次数压进 20~25。

用法：
    python scripts/diag/q2_maxgroup_grid.py
"""

from __future__ import annotations

import dataclasses
import json
import logging
import sys
from pathlib import Path

from src.physics.leg_cache import load_cached
from src.q2_transport_schedule.run_q2 import load_inputs, solve
from src.q2_transport_schedule.solver import Q2Weights

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
logging.disable(logging.INFO)
OUT = Path("outputs/diag")

BASE = Q2Weights()


def main() -> int:
    boxes, ut, fleet, bi, tf, dl, _ = load_inputs()
    lc = load_cached()
    rows = []
    print(f"{'max_group':>10}{'sortie_w':>10}{'架次':>6}{'能耗':>8}{'完工h':>7}"
          f"{'准时率':>8}{'首批':>5}{'期望':>5}{'可行':>6}")
    print("-" * 74)
    for mg in (3, 4, 5, 6):
        for sw in (0.1, 0.2, 0.5):
            w = dataclasses.replace(BASE, violation_point=1e3, sortie_per_unit=sw,
                                    energy_per_kwh=0.05)
            r = solve(boxes, ut, lc, dl, fleet, bi, tf, do_local_search=True,
                      fleet_mode="auto", max_group=mg, weights=w)
            ok = (r.violations_first_batch + r.violations_expected) == 0
            rows.append({
                "max_group": mg, "sortie_per_unit": sw, "n_sorties": r.n_sorties,
                "energy_kwh": round(r.total_energy_kwh, 2),
                "makespan_h": round(r.makespan_s / 3600.0, 2),
                "on_time_rate": round(r.on_time_rate, 4),
                "viol_first_batch": r.violations_first_batch,
                "viol_expected": r.violations_expected, "feasible": ok,
            })
            print(f"{mg:>10}{sw:>10}{r.n_sorties:>6}{r.total_energy_kwh:>8.2f}"
                  f"{r.makespan_s/3600:>7.2f}{r.on_time_rate:>8.1%}"
                  f"{r.violations_first_batch:>5}{r.violations_expected:>5}"
                  f"{'✅' if ok else '❌':>6}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "q2_maxgroup_grid.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    feas = [r for r in rows if r["feasible"]]
    if feas:
        b = min(feas, key=lambda r: (r["n_sorties"], r["energy_kwh"]))
        print(f"\n★ 0 违规中架次最少：{b['n_sorties']} 架次 / {b['energy_kwh']} kWh / "
              f"{b['makespan_h']} h（max_group={b['max_group']}, "
              f"sortie_w={b['sortie_per_unit']}）")
    print(f"已写入 {OUT / 'q2_maxgroup_grid.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
