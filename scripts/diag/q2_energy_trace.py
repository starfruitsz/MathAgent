"""诊断：逐段复现 T001，对比求解器与校验器的能耗口径。

用法：
    python scripts/diag/q2_energy_trace.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from src.physics.energy import Segment, segment_energy_kwh, segment_time_s  # noqa: E402
from src.physics.leg_cache import load_cached  # noqa: E402
from src.q2_transport_schedule.run_q2 import load_inputs  # noqa: E402


def main() -> int:
    boxes, uav_types, fleet, bat_inv, t_full, deadlines, bdf = load_inputs()
    leg_cache = load_cached()
    print("机型:", {c: f"Q={u.max_payload_kg}kg V={u.volume_m3}m3 "
                      f"E={u.energy_kwh}kWh budget={u.energy_budget_kwh:.4f} "
                      f"rho={u.reserve_ratio}"
                   for c, u in uav_types.items()})

    # T001: B 型，S001→S002
    uav = uav_types["B"]
    stops = ("S001", "S002")
    boxes_by_stop = {
        st: tuple(b.box_id for b in boxes if b.service_id == st) for st in stops
    }
    mass = {st: sum(b.mass_kg for b in boxes if b.service_id == st) for st in stops}
    vol = {st: sum(b.volume_m3 for b in boxes if b.service_id == st) for st in stops}
    print(f"\nT001: B 型 {stops}")
    print(f"  逐站质量 { {k: round(v,2) for k, v in mass.items()} }")
    print(f"  逐站体积 { {k: round(v,4) for k, v in vol.items()} }  B 舱容 {uav.volume_m3}")
    print(f"  逐站箱数 { {k: len(v) for k, v in boxes_by_stop.items()} }")

    nodes = ["O01", *stops, "O01"]
    legs = []
    for a, b in zip(nodes, nodes[1:]):
        g = leg_cache.get(a, b)
        legs.append((a, b, g))
        print(f"  航段 {a}->{b}: d={g['distance_m']:.1f}m "
              f"climb={g['climb_m']:.1f} descent={g['descent_m']:.1f}")

    print("\n--- 求解器口径（models.evaluate_sortie）---")
    remain = sum(mass.values())
    total = 0.0
    for idx, (a, b) in enumerate(zip(nodes, nodes[1:])):
        g = leg_cache.get(a, b)
        seg = Segment(g["distance_m"], g["climb_m"], g["descent_m"])
        e = segment_energy_kwh(uav, seg, remain)
        print(f"  {a}->{b}  payload={remain:.2f}kg  E={e:.5f} kWh  t={segment_time_s(uav, seg):.1f}s")
        total += e
        if idx < len(stops):
            remain -= mass.get(stops[idx], 0.0)
    g = leg_cache.get(stops[-1], "O01")
    seg = Segment(g["distance_m"], g["climb_m"], g["descent_m"])
    e = segment_energy_kwh(uav, seg, 0.0)
    print(f"  {stops[-1]}->O01  payload=0.00kg  E={e:.5f} kWh  t={segment_time_s(uav, seg):.1f}s")
    total += e
    print(f"  合计 = {total:.5f} kWh  (预算 {uav.energy_budget_kwh:.4f})")

    print("\n--- 校验器口径（feasibility._sortie_energy）---")
    total2 = 0.0
    remain2 = sum(mass.values())
    n_legs = len(legs)
    n_out = max(1, n_legs - 1)
    for i, (a, b, g) in enumerate(legs):
        seg = Segment(g["distance_m"], g["climb_m"], g["descent_m"])
        is_return = i >= n_out and n_legs > 1
        payload = 0.0 if is_return else min(remain2, uav.max_payload_kg)
        e = segment_energy_kwh(uav, seg, payload)
        print(f"  [{i}] {a}->{b}  return={is_return} payload={payload:.2f}kg  E={e:.5f}")
        total2 += e
        if not is_return and i < len(stops):
            remain2 = max(0.0, remain2 - mass.get(stops[i], 0.0))
    print(f"  合计 = {total2:.5f} kWh  (预算 {uav.energy_budget_kwh:.4f})")
    print(f"\n差异 = {total2 - total:.5f} kWh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
