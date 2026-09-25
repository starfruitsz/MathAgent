"""接入"真实口径合并"后重扫架次权重：看能否压到理论下界 24 架次。

前置：`consolidate_real` 以"真实排程 0 违规"为硬前提压缩架次数，
因此本脚本只需关心**起点**（local_search 的输出）是否仍可行：
权重过高会让起点就违规，`consolidate_real` 会直接原样返回。

用法：
    python scripts/diag/q2_consolidate_sweep.py
"""

from __future__ import annotations

import dataclasses
import json
import logging
import sys
import time
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
    print(f"{'viol_pt':>8}{'sortie_w':>9}{'E_w':>6}{'架次':>6}{'能耗':>8}{'完工h':>7}"
          f"{'准时率':>8}{'首批':>5}{'期望':>5}{'秒':>6}")
    print("-" * 76)
    for vp, sw, ew in ((1.0, 0.05, 1.0), (1.0, 0.1, 0.5), (1.0, 0.2, 0.2),
                       (1e3, 0.05, 0.05), (1e3, 0.1, 0.05), (1e3, 0.2, 0.05),
                       (1e3, 0.5, 0.02), (1e3, 1.0, 0.02)):
        w = dataclasses.replace(BASE, violation_point=vp, sortie_per_unit=sw,
                                energy_per_kwh=ew)
        t = time.perf_counter()
        r = solve(boxes, ut, lc, dl, fleet, bi, tf,
                  do_local_search=True, fleet_mode="auto", weights=w)
        el = time.perf_counter() - t
        ok = (r.violations_first_batch + r.violations_expected) == 0
        rows.append({
            "violation_point": vp, "sortie_per_unit": sw, "energy_per_kwh": ew,
            "n_sorties": r.n_sorties,
            "energy_kwh": round(r.total_energy_kwh, 2),
            "makespan_h": round(r.makespan_s / 3600.0, 2),
            "on_time_rate": round(r.on_time_rate, 4),
            "viol_first_batch": r.violations_first_batch,
            "viol_expected": r.violations_expected,
            "feasible": ok, "runtime_s": round(el, 1),
        })
        print(f"{vp:>8.0f}{sw:>9}{ew:>6}{r.n_sorties:>6}{r.total_energy_kwh:>8.2f}"
              f"{r.makespan_s/3600:>7.2f}{r.on_time_rate:>8.1%}"
              f"{r.violations_first_batch:>5}{r.violations_expected:>5}"
              f"{el:>6.0f}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "q2_consolidate_sweep.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    feas = [r for r in rows if r["feasible"]]
    if feas:
        b = min(feas, key=lambda r: (r["n_sorties"], r["energy_kwh"]))
        print(f"\n★ 0 违规中架次最少：{b['n_sorties']} 架次 / {b['energy_kwh']} kWh / "
              f"{b['makespan_h']} h（viol_pt={b['violation_point']:.0f}, "
              f"sortie_w={b['sortie_per_unit']}, E_w={b['energy_per_kwh']}）")
    print(f"已写入 {OUT / 'q2_consolidate_sweep.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
