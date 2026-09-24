"""诊断：选型目标（代理调度 vs 真实调度）谁更能降低**真实**违规？

`solve(fleet_mode="auto")` 现在用 `schedule_score`（真实调度）给三个同构机队打分，
但**局部搜索内部**用的是代理调度估计。本脚本对比两种口径在**真实调度**下的表现。

用法：
    python scripts/diag/q2_obj_head2head.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import src.q2_transport_schedule.solver as S  # noqa: E402
from src.physics.leg_cache import load_cached  # noqa: E402
from src.q2_transport_schedule.run_q2 import load_inputs, schedule_score  # noqa: E402
from src.q2_transport_schedule.schedule import build_pools, schedule_dispatch  # noqa: E402
from src.q2_transport_schedule.solver import (  # noqa: E402
    Q2Weights,
    clear_caches,
    construct,
    local_search,
)

W = Q2Weights(late_per_s=1.0 / 1800, first_batch_extra=50.0,
              makespan_per_s=1.0 / 3600, energy_per_kwh=1.0, sortie_per_unit=0.02)


def evaluate(code, uav_types, fleet, bat_inv, t_full, boxes, leg_cache,
             boxes_by_id, deadlines, use_proxy: bool) -> dict:
    only_t = {code: uav_types[code]}
    only_f = {code: fleet[code]}
    only_b = {code: bat_inv.get(code, 0)}
    only_tf = {code: t_full.get(code, 1800.0)}
    res = (len(only_f[code]), only_b[code], only_tf[code]) if use_proxy else None
    clear_caches()
    S.DEFAULT_WEIGHTS = W
    cands = construct(boxes, only_t, leg_cache, deadlines, max_group=3)
    cands = local_search(cands, only_t, leg_cache, boxes_by_id, deadlines,
                         weights=W, resources=res)
    plans = [c.plan for c in cands if c.plan.stops]
    pools = build_pools(only_f, only_b, only_tf)
    sched = schedule_dispatch(plans, only_t, leg_cache, boxes_by_id, pools)
    _, d = schedule_score(sched, boxes_by_id, deadlines, W)
    return d


def main() -> int:
    boxes, uav_types, fleet, bat_inv, t_full, deadlines, bdf = load_inputs()
    leg_cache = load_cached()
    boxes_by_id = {b.box_id: b for b in boxes}

    print(f"{'局部搜索目标':<22}{'机型':>4}{'架次':>5}{'能耗':>9}{'完工h':>8}"
          f"{'准时率':>8}{'首批违规':>9}{'期望违规':>9}")
    print("-" * 84)
    for use_proxy, label in ((False, "假想同时开工"), (True, "代理调度(资源感知)")):
        best = None
        for code in ("C", "B", "A"):
            if code not in uav_types or not fleet.get(code):
                continue
            try:
                d = evaluate(code, uav_types, fleet, bat_inv, t_full, boxes,
                             leg_cache, boxes_by_id, deadlines, use_proxy)
            except Exception as exc:  # noqa: BLE001
                print(f"    {code} 失败: {type(exc).__name__}: {str(exc)[:60]}")
                continue
            key = (d["n_late_first_batch"], d["n_late_boxes"], d["makespan_h"])
            if best is None or key < best[0]:
                best = (key, code, d)
        if best is None:
            continue
        _, code, d = best
        print(f"{label:<22}{code:>4}{d['n_sorties']:>5}{d['energy_kwh']:>9.2f}"
              f"{d['makespan_h']:>8.2f}{d['on_time_rate']:>8.1%}"
              f"{d['n_late_first_batch']:>9}{d['n_late_boxes']:>9}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
