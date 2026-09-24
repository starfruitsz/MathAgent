"""定位 Q2 求解器中"架次超载"的引入阶段。

思路：在 `construct` 与 `local_search` 之后分别检查每个候选架次是否满足
容量/体积/能量硬约束，找出第一个违规架次与它出现的阶段。

用法：
    python scripts/diag/q2_overload_trace.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.physics.leg_cache import load_cached  # noqa: E402
from src.q2_transport_schedule.run_q2 import load_inputs  # noqa: E402
from src.q2_transport_schedule.solver import (  # noqa: E402
    _EVAL_CACHE,
    _ORDER_CACHE,
    construct,
    local_search,
)


def audit(cands, uav_types, boxes_by_id, tag: str) -> list[str]:
    bad = []
    for c in cands:
        uav = uav_types[c.plan.type_code]
        m = sum(boxes_by_id[b].mass_kg for s in c.plan.stops
                for b in c.plan.boxes_by_stop.get(s, ()))
        v = sum(boxes_by_id[b].volume_m3 for s in c.plan.stops
                for b in c.plan.boxes_by_stop.get(s, ()))
        n = sum(len(c.plan.boxes_by_stop.get(s, ())) for s in c.plan.stops)
        prob = []
        if m > uav.max_payload_kg + 1e-9:
            prob.append(f"质量 {m:.1f}>{uav.max_payload_kg}")
        if v > uav.volume_m3 + 1e-12:
            prob.append(f"体积 {v:.4f}>{uav.volume_m3}")
        if c.ev.energy_kwh > uav.energy_budget_kwh + 1e-9:
            prob.append(f"能耗 {c.ev.energy_kwh:.3f}>{uav.energy_budget_kwh:.3f}")
        if prob:
            bad.append(f"  [{tag}] {c.plan.type_code} 型 {c.plan.stops} "
                       f"{n}箱 ev.feasible={c.ev.feasible} :: " + "; ".join(prob))
    print(f"{tag}: {len(cands)} 个架次，违规 {len(bad)} 个")
    return bad


def main() -> int:
    boxes, uav_types, fleet, bat_inv, t_full, deadlines, bdf = load_inputs()
    leg_cache = load_cached()
    boxes_by_id = {b.box_id: b for b in boxes}

    _EVAL_CACHE.clear(); _ORDER_CACHE.clear()
    c1 = construct(boxes, uav_types, leg_cache, deadlines, max_group=3)
    bad1 = audit(c1, uav_types, boxes_by_id, "construct 之后")

    c2 = local_search(c1, uav_types, leg_cache, boxes_by_id, deadlines)
    bad2 = audit(c2, uav_types, boxes_by_id, "local_search 之后")

    print()
    for line in (bad1 + bad2)[:14]:
        print(line)

    if bad2:
        print(f"\n最早出现阶段：{'construct' if bad1 else 'local_search'}")
    else:
        print("\n★ 两个阶段都没有违规 —— 说明违规发生在更靠后的调度/输出环节")
        # 检查调度之后
        from src.q2_transport_schedule.schedule import build_pools, schedule_dispatch
        plans = [c.plan for c in c2 if c.plan.stops]
        pools = build_pools(fleet, bat_inv, t_full)
        sched = schedule_dispatch(plans, uav_types, leg_cache, boxes_by_id, pools)
        nb = 0
        for s in sched:
            uav = uav_types[s.type_code]
            m = sum(boxes_by_id[b].mass_kg for st in s.stops
                    for b in s.boxes_by_stop.get(st, ()))
            if m > uav.max_payload_kg + 1e-9:
                nb += 1
                if nb <= 6:
                    print(f"  [sched] {s.sortie_id} {s.type_code} {s.stops} "
                          f"质量 {m:.1f} > {uav.max_payload_kg}")
        print(f"sched 之后违规 {nb} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
