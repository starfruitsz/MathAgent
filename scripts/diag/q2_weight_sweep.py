"""诊断：Q2 目标权重对结果的影响 —— 回答"架次数应当是多少"。

背景
----
参考稿（`docs/reference/参考文稿2.pdf`）的推荐方案是 **17 架次 / 63.16 kWh /
完工 9799 s / 首批硬期限零违反**，其 Pareto 前沿横跨 15~28 架次。
而本仓库曾出现 35 架次（偏差大）与 16 架次（过分压架次数、13 箱首批超时）两端。

本脚本扫描目标权重，回答：
  1. 把"首批硬期限违反"提到最高优先级后，需要多少架次才能做到零违反？
  2. 架次数落在哪个区间时，完工时间 / 能耗 / 准时率综合最好？

用法：
    python scripts/diag/q2_weight_sweep.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.physics.leg_cache import load_cached  # noqa: E402
from src.q2_transport_schedule.run_q2 import load_inputs, schedule_score  # noqa: E402
from src.q2_transport_schedule.schedule import build_pools, schedule_dispatch  # noqa: E402
from src.q2_transport_schedule.solver import (  # noqa: E402
    Q2Weights,
    clear_caches,
    construct,
    local_search,
)

# 权重方案：(名称, Q2Weights)
CASES = {
    "① 主压架次（现行）": Q2Weights(sortie_per_unit=0.05, makespan_per_s=0.25 / 3600,
                                late_per_s=1.0 / 3600, first_batch_extra=9.0),
    "② 首批零违反优先": Q2Weights(sortie_per_unit=0.02, makespan_per_s=0.5 / 3600,
                             late_per_s=1.0 / 1800, first_batch_extra=80.0),
    "③ 均衡（推荐）": Q2Weights(sortie_per_unit=0.10, makespan_per_s=1.0 / 3600,
                            late_per_s=1.0 / 1800, first_batch_extra=50.0),
    "④ 重及时性": Q2Weights(sortie_per_unit=0.05, makespan_per_s=0.5 / 3600,
                          late_per_s=1.0 / 900, first_batch_extra=100.0),
}


def run_case(name: str, w: Q2Weights) -> dict:
    boxes, uav_types, fleet, bat_inv, t_full, deadlines, bdf = load_inputs()
    leg_cache = load_cached()
    boxes_by_id = {b.box_id: b for b in boxes}
    best = None
    for code in ("C", "B", "A"):
        if code not in uav_types or not fleet.get(code):
            continue
        only_t, only_f = {code: uav_types[code]}, {code: fleet[code]}
        only_b = {code: bat_inv.get(code, 0)}
        only_tf = {code: t_full.get(code, 1800.0)}
        clear_caches()
        try:
            # 用该权重做局部搜索（先把权重注入模块级默认值）
            import src.q2_transport_schedule.solver as S
            S.DEFAULT_WEIGHTS = w
            cands = construct(boxes, only_t, leg_cache, deadlines, max_group=3)
            cands = local_search(cands, only_t, leg_cache, boxes_by_id, deadlines)
            plans = [c.plan for c in cands if c.plan.stops]
            pools = build_pools(only_f, only_b, only_tf)
            sched = schedule_dispatch(plans, only_t, leg_cache, boxes_by_id, pools)
        except Exception as exc:  # noqa: BLE001
            continue
        sc, detail = schedule_score(sched, boxes_by_id, deadlines, w)
        if best is None or sc < best[0]:
            best = (sc, code, detail)
    if best is None:
        return {"方案": name, "机型": "-", "架次": 0}
    _, code, d = best
    return {"方案": name, "机型": code, "架次": d["n_sorties"],
            "能耗": d["energy_kwh"], "完工h": d["makespan_h"],
            "准时率": d["on_time_rate"], "首批违规": d["n_late_first_batch"],
            "期望违规": d["n_late_boxes"], "score": d["score"]}


def main() -> int:
    rows = []
    for name, w in CASES.items():
        rows.append(run_case(name, w))
    print(f"{'权重方案':<20}{'机型':>5}{'架次':>5}{'能耗':>9}{'完工h':>8}"
          f"{'准时率':>8}{'首批违规':>9}{'期望违规':>9}{'score':>10}")
    print("-" * 92)
    for r in rows:
        print(f"{r['方案']:<20}{r['机型']:>5}{r['架次']:>5}{r.get('能耗',0):>9.2f}"
              f"{r.get('完工h',0):>8.2f}{r.get('准时率',0):>8.1%}"
              f"{r.get('首批违规',0):>9}{r.get('期望违规',0):>9}{r.get('score',0):>10.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
