"""Q2 目标权重方案对比：在"时限为硬要求"前提下压架次数。

动机
----
题目要求同时优化 配送及时性 / 完工时间 / 能耗 / 架次数，但不给优先级；
而原文对时限用的是"**应满足**…要求"，即时限是**约束**。
旧权重 `sortie_per_unit=0.05` 使架次数几乎免费 ⇒ 求解器用"多开小架次"
换及时性，得到 28 架次、装载率仅 71%（理论下界 24 架次）。

本脚本对比若干权重方案，回答：能否在 **0 违规**的前提下把架次数压到 20~25。

用法：
    python scripts/diag/q2_weight_regimes.py
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
REGIMES: dict[str, Q2Weights] = {
    # 旧口径：违规权重 1、架次几乎免费
    "legacy(viol=1, sortie=.05, E=1)": BASE,
    # 违规压倒 + 架次成为一等目标
    "A(viol=1e3, sortie=1, E=.05)": dataclasses.replace(
        BASE, violation_point=1e3, sortie_per_unit=1.0, energy_per_kwh=0.05),
    "B(viol=1e3, sortie=2, E=.02)": dataclasses.replace(
        BASE, violation_point=1e3, sortie_per_unit=2.0, energy_per_kwh=0.02),
    "C(viol=1e4, sortie=1, E=.02)": dataclasses.replace(
        BASE, violation_point=1e4, sortie_per_unit=1.0, energy_per_kwh=0.02),
    # 完工时间也压低，避免"为省架次把尾部拖长"
    "D(viol=1e3, sortie=1, E=.05, span=1/h)": dataclasses.replace(
        BASE, violation_point=1e3, sortie_per_unit=1.0, energy_per_kwh=0.05,
        makespan_per_s=1.0 / 3600.0),
}


def main() -> int:
    boxes, ut, fleet, bi, tf, dl, _ = load_inputs()
    lc = load_cached()
    rows = []
    print(f"{'权重方案':<36}{'架次':>5}{'能耗':>8}{'完工h':>7}{'准时率':>8}"
          f"{'首批':>5}{'期望':>5}")
    print("-" * 78)
    for name, w in REGIMES.items():
        r = solve(boxes, ut, lc, dl, fleet, bi, tf,
                  do_local_search=True, fleet_mode="auto", weights=w)
        rows.append({
            "regime": name, "n_sorties": r.n_sorties,
            "energy_kwh": round(r.total_energy_kwh, 2),
            "makespan_h": round(r.makespan_s / 3600.0, 2),
            "on_time_rate": round(r.on_time_rate, 4),
            "viol_first_batch": r.violations_first_batch,
            "viol_expected": r.violations_expected,
            "type_usage": r.fleet_trials.get("混合-机队摊平", {}).get("n_sorties"),
        })
        print(f"{name:<36}{r.n_sorties:>5}{r.total_energy_kwh:>8.2f}"
              f"{r.makespan_s/3600:>7.2f}{r.on_time_rate:>8.1%}"
              f"{r.violations_first_batch:>5}{r.violations_expected:>5}")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "q2_weight_regimes.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {OUT / 'q2_weight_regimes.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
