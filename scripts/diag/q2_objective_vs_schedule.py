"""诊断：确认两件事
① 目标函数用"假想同时开工"估计及时性 → 永远得出"0 违规"（与真实调度严重不符）；
② 调度器 `build_pools` 按机型分池 → 混合机型方案不可调度
   —— 这解释了为什么"默认（三型可选）"的结果与"仅 B 型"逐位相同。

用法：
    python scripts/diag/q2_objective_vs_schedule.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.physics.leg_cache import load_cached  # noqa: E402
from src.q2_transport_schedule.run_q2 import load_inputs  # noqa: E402
from src.q2_transport_schedule.schedule import build_pools, schedule_dispatch  # noqa: E402
from src.q2_transport_schedule.solver import (  # noqa: E402
    clear_caches,
    construct,
    local_search,
    objective_breakdown,
)


def main() -> int:
    boxes, uav_types, fleet, bat_inv, t_full, deadlines, bdf = load_inputs()
    leg_cache = load_cached()
    boxes_by_id = {b.box_id: b for b in boxes}

    print("=== ① 假想目标 vs 真实调度 ===")
    for code in ("A", "B", "C"):
        only = {code: uav_types[code]}
        clear_caches()
        cands = construct(boxes, only, leg_cache, deadlines, max_group=3)
        cands = local_search(cands, only, leg_cache, boxes_by_id, deadlines)
        bd = objective_breakdown(cands, only, leg_cache, boxes_by_id, deadlines)

        plans = [c.plan for c in cands if c.plan.stops]
        pools = build_pools({code: fleet[code]}, {code: bat_inv[code]}, {code: t_full[code]})
        try:
            sched = schedule_dispatch(plans, only, leg_cache, boxes_by_id, pools)
        except Exception as exc:  # noqa: BLE001
            print(f"  {code}: 调度失败 {type(exc).__name__}: {str(exc)[:70]}")
            continue
        mk = max((s.return_s for s in sched), default=0.0)
        n_fb = n_exp = n_tot = n_on = 0
        for s in sched:
            for svc, t in s.delivery_times.items():
                for bid in s.boxes_by_stop.get(svc, ()):
                    dl = deadlines[bid]
                    n_tot += 1
                    if t <= dl.expected_s + 1e-6:
                        n_on += 1
                    else:
                        n_exp += 1
                    if dl.is_first_batch and dl.first_batch_s is not None and t > dl.first_batch_s:
                        n_fb += 1
        print(f"  {code}: 假想目标 违规={bd.n_late_boxes} 完工={bd.makespan_s/3600:.2f}h "
              f"能耗={bd.energy_kwh:.2f} | 真实调度 架次={len(sched)} "
              f"完工={mk/3600:.2f}h 准时={n_on/n_tot:.1%} 首批违规={n_fb} 期望违规={n_exp}")

    print("\n=== ② 混合机型能否调度 ===")
    clear_caches()
    cands = construct(boxes, uav_types, leg_cache, deadlines, max_group=3)
    from collections import Counter
    cnt = Counter(c.plan.type_code for c in cands if c.plan.stops)
    print(f"  默认构造得到的机型分布：{dict(cnt)}")
    print(f"  机队：{fleet}；电池：{bat_inv}")
    print("  → 调度器 build_pools 按机型分池，A/B/C 各自独立；")
    print("    因此'混合机型'方案实际只在**某一个池**里调度，与单机型等价。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
