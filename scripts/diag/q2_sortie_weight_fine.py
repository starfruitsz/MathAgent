"""细扫 Q2 架次权重：找出"0 违规前提下架次数最少"的取值。

背景（proxy/real 口径差异）
--------------------------
`local_search` 用 `objective_breakdown` 的**代理派发**（乐观下界）估及时性，
而最终判违规用的是真实 `schedule_dispatch`。代理偏乐观 ⇒ 局部搜索以为
"0 违规"、真实排程却出现若干超时。因此**不能**只看目标函数值挑权重，
必须按**真实排程**的违规数与架次数来选。

用法：
    python scripts/diag/q2_sortie_weight_fine.py
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
    print(f"{'sortie_w':>9}{'viol_pt':>9}{'架次':>6}{'能耗':>8}{'完工h':>7}"
          f"{'准时率':>8}{'首批':>5}{'期望':>5}{'可行':>6}")
    print("-" * 72)
    for vp in (1.0, 1e3):
        for sw in (0.0, 0.02, 0.05, 0.1, 0.2, 0.35, 0.5, 0.75, 1.0):
            w = dataclasses.replace(BASE, violation_point=vp,
                                    sortie_per_unit=sw, energy_per_kwh=0.05)
            r = solve(boxes, ut, lc, dl, fleet, bi, tf,
                      do_local_search=True, fleet_mode="auto", weights=w)
            ok = (r.violations_first_batch + r.violations_expected) == 0
            rows.append({
                "violation_point": vp, "sortie_per_unit": sw,
                "n_sorties": r.n_sorties,
                "energy_kwh": round(r.total_energy_kwh, 2),
                "makespan_h": round(r.makespan_s / 3600.0, 2),
                "on_time_rate": round(r.on_time_rate, 4),
                "viol_first_batch": r.violations_first_batch,
                "viol_expected": r.violations_expected,
                "feasible": ok,
            })
            print(f"{sw:>9}{vp:>9.0f}{r.n_sorties:>6}{r.total_energy_kwh:>8.2f}"
                  f"{r.makespan_s/3600:>7.2f}{r.on_time_rate:>8.1%}"
                  f"{r.violations_first_batch:>5}{r.violations_expected:>5}"
                  f"{'✅' if ok else '❌':>6}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "q2_sortie_weight_fine.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    feas = [r for r in rows if r["feasible"]]
    if feas:
        best = min(feas, key=lambda r: (r["n_sorties"], r["energy_kwh"]))
        print(f"\n★ 0 违规中架次最少：{best['n_sorties']} 架次 / "
              f"{best['energy_kwh']} kWh / {best['makespan_h']} h "
              f"（viol_pt={best['violation_point']:.0f}, "
              f"sortie_w={best['sortie_per_unit']}）")
    else:
        print("\n⚠️ 没有任何配置达到 0 违规")
    print(f"已写入 {OUT / 'q2_sortie_weight_fine.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
