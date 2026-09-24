"""诊断：为什么"按服务区合并升级机型"没有生效？

逐环节检查：_repack_area 是否可行 → 目标函数是否改善 → 局部搜索是否采纳。

用法：
    python scripts/diag/q2_consolidate_debug.py
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
    _area_box_lists,
    _Cand,
    _objective,
    _rebuild,
    _remove_boxes,
    _repack_area,
    clear_caches,
    construct,
    local_search,
    objective_breakdown,
)


def main() -> int:
    boxes, uav_types, fleet, bat_inv, t_full, deadlines, bdf = load_inputs()
    leg_cache = load_cached()
    boxes_by_id = {b.box_id: b for b in boxes}

    clear_caches()
    cur = construct(boxes, uav_types, leg_cache, deadlines, max_group=3)
    bd0 = objective_breakdown(cur, uav_types, leg_cache, boxes_by_id, deadlines)
    print(f"初始：{bd0}")

    per_area = _area_box_lists(cur)
    print("\n=== 逐区尝试用 C 型重装 ===")
    for svc in sorted(per_area):
        bids = per_area[svc]
        if len(bids) <= 1:
            continue
        uav = uav_types["C"]
        rebuilt = _repack_area(bids, svc, "C", uav, boxes_by_id, leg_cache)
        if rebuilt is None:
            print(f"  {svc}: {len(bids)} 箱 -> C 型重装 ❌ 不可行")
            continue
        n_new = len(rebuilt)
        n_old = sum(1 for c in cur if svc in c.plan.stops)
        # 构造 trial
        target = set(bids)
        trial: list[_Cand] = []
        for c in cur:
            st = _remove_boxes(c.plan, target)
            if not st.stops:
                continue
            trial.append(c if st is c.plan else _Cand(st, {}, {}, dict(c.boxes), c.ev))
        trial = _rebuild(trial + rebuilt, uav_types, leg_cache, boxes_by_id)
        bd = objective_breakdown(trial, uav_types, leg_cache, boxes_by_id, deadlines)
        flag = "✅ 改善" if bd.score < bd0.score else "—"
        print(f"  {svc}: {len(bids)} 箱 / 原 {n_old} 架次 -> C 型 {n_new} 架次   "
              f"score {bd0.score:.3f} -> {bd.score:.3f}  {flag}")
        print(f"        {bd}")

    print("\n=== 执行 local_search ===")
    after = local_search(cur, uav_types, leg_cache, boxes_by_id, deadlines)
    bd1 = objective_breakdown(after, uav_types, leg_cache, boxes_by_id, deadlines)
    print(f"结果：{len(after)} 架次 | {bd1}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
