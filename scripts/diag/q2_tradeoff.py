"""诊断：架次数 ↔ 及时性 的权衡（Q2）。

现象：16 架次（全 C 型）虽然架次少、能耗低，但**首批达标只有 17/30**，
S002/S006/S010/S012/S013 等 3600 s 硬期限的区被排到 4 h 之后。
参考稿给出的是 **17 架次 / 首批零违反**，说明"压架次数"与"保及时性"需要平衡。

本脚本按"架次上限"扫描多目标权重（把架次数权重逐步加大 = 允许更多架次），
报告每种权重下的真实调度结果。

用法：
    python scripts/diag/q2_tradeoff.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import src.q2_transport_schedule.solver as S  # noqa: E402
from src.physics.leg_cache import load_cached  # noqa: E402
from src.q2_transport_schedule.run_q2 import (  # noqa: E402
    load_inputs,
    schedule_score,
)
from src.q2_transport_schedule.schedule import build_pools, schedule_dispatch  # noqa: E402
from src.q2_transport_schedule.solver import (  # noqa: E402
    Q2Weights,
    clear_caches,
    construct,
    local_search,
)


def evaluate(only_t, only_f, only_b, only_tf, boxes, leg_cache, boxes_by_id,
             deadlines, w):
    clear_caches()
    S.DEFAULT_WEIGHTS = w
    cands = construct(boxes, only_t, leg_cache, deadlines, max_group=3)
    cands = local_search(cands, only_t, leg_cache, boxes_by_id, deadlines, weights=w)
    plans = [c.plan for c in cands if c.plan.stops]
    pools = build_pools(only_f, only_b, only_tf)
    sched = schedule_dispatch(plans, only_t, leg_cache, boxes_by_id, pools)
    return sched, schedule_score(sched, boxes_by_id, deadlines, w)[1]


def main() -> int:
    boxes, uav_types, fleet, bat_inv, t_full, deadlines, bdf = load_inputs()
    leg_cache = load_cached()
    boxes_by_id = {b.box_id: b for b in boxes}

    # 架次数权重从 0（完全不在意架次数）到 1.0（很在意）
    grid = [("少架次权重 0.00", 0.0), ("0.02", 0.02), ("0.05", 0.05),
            ("0.10", 0.10), ("0.30", 0.30), ("1.00", 1.00)]
    print(f"{'架次数权重':<16}{'机型':>4}{'架次':>5}{'能耗':>9}{'完工h':>8}"
          f"{'准时率':>8}{'首批违规':>9}{'期望违规':>9}")
    print("-" * 78)
    for label, sw in grid:
        w = Q2Weights(late_per_s=1.0 / 1800, first_batch_extra=50.0,
                      makespan_per_s=1.0 / 3600, energy_per_kwh=1.0,
                      sortie_per_unit=sw)
        best = None
        for code in ("C", "B", "A"):
            if code not in uav_types or not fleet.get(code):
                continue
            try:
                _, d = evaluate({code: uav_types[code]}, {code: fleet[code]},
                                {code: bat_inv.get(code, 0)},
                                {code: t_full.get(code, 1800.0)},
                                boxes, leg_cache, boxes_by_id, deadlines, w)
            except Exception:  # noqa: BLE001
                continue
            key = (d["n_late_first_batch"], d["n_late_boxes"], d["makespan_h"])
            if best is None or key < best[0]:
                best = (key, code, d)
        if best is None:
            print(f"{label:<16}  ❌ 无可行机型")
            continue
        _, code, d = best
        print(f"{label:<16}{code:>4}{d['n_sorties']:>5}{d['energy_kwh']:>9.2f}"
              f"{d['makespan_h']:>8.2f}{d['on_time_rate']:>8.1%}"
              f"{d['n_late_first_batch']:>9}{d['n_late_boxes']:>9}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
