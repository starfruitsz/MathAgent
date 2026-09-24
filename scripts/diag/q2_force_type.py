"""诊断：强制单一机型跑完整 Q2 求解，对比 及时性 / 完工时间 / 能耗 / 架次数。

目的：回答"35 架次是否合理"。Q1 用 C 型 18 架次；Q2 若也能用 C 型，
      架次数应显著低于 35。

用法：
    python scripts/diag/q2_force_type.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.q2_transport_schedule.run_q2 import load_inputs, solve  # noqa: E402
from src.q2_transport_schedule.solver import clear_caches  # noqa: E402
from src.physics.leg_cache import load_cached  # noqa: E402


def main() -> int:
    boxes, uav_types, fleet, bat_inv, t_full, deadlines, bdf = load_inputs()
    leg_cache = load_cached()

    cases = [
        ("全部机型（默认）", uav_types, fleet),
        ("仅 A 型", {"A": uav_types["A"]}, {"A": fleet["A"]}),
        ("仅 B 型", {"B": uav_types["B"]}, {"B": fleet["B"]}),
        ("仅 C 型", {"C": uav_types["C"]}, {"C": fleet["C"]}),
    ]
    print(f"{'方案':<18}{'架次':>5}{'能耗kWh':>10}{'完工h':>8}{'准时率':>9}{'首批违规':>9}{'期望违规':>9}")
    print("-" * 70)
    for name, types, fl in cases:
        clear_caches()
        bi = {c: bat_inv[c] for c in types}
        tf = {c: t_full[c] for c in types}
        try:
            res = solve(boxes, types, leg_cache, deadlines, fl, bi, tf,
                        do_local_search=True, max_group=3)
            print(f"{name:<18}{res.n_sorties:>5}{res.total_energy_kwh:>10.2f}"
                  f"{res.makespan_s/3600:>8.2f}{res.on_time_rate:>9.1%}"
                  f"{res.violations_first_batch:>9}{res.violations_expected:>9}")
        except Exception as exc:  # noqa: BLE001
            print(f"{name:<18}  ❌ {type(exc).__name__}: {str(exc)[:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
