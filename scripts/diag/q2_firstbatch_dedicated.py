"""诊断：为"首批硬期限紧"的服务区安排**专架次**能否消除首批违规？

背景
----
实测当前最优方案（15~16 架次 / 全 C 型）首批达标仅 17/30。
硬期限分析（data/processed/boxes.csv）：
    · 首批截止 3600 s 的服务区 **8 个**（S001/S002/S006/S007/S010/S012/S013/S014）
    · 首批截止 7200 s 的 4 个、10800 s 的 4 个
而首批箱是每区 1 医疗 + 1 饮用水 = 2 箱，总重约 17 kg、总体积约 0.039 m³
—— **任何机型都能一次装下**。

因此"让每个 3600 s 区都有一次尽早起飞、只送该区首批箱的架次"是可行的，
且能把这 8 个硬期限从"和其他 60 箱挤在一起、被排到 4 h 后"中解耦出来。

本脚本对比：
    A) 现状（纯局部搜索的最优）
    B) A + 为 8 个紧期限区各追加一个"首批专架次"（原架次中移除相应箱）

用法：
    python scripts/diag/q2_firstbatch_dedicated.py
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
    SortiePlan,
    _Cand,
    _eval_plan,
    _improve_order,
    _remove_boxes,
    clear_caches,
    construct,
    local_search,
)

W = Q2Weights(late_per_s=1.0 / 1800, first_batch_extra=50.0,
              makespan_per_s=1.0 / 3600, energy_per_kwh=1.0, sortie_per_unit=0.02)


def report(tag: str, sched, boxes_by_id, deadlines) -> None:
    _, d = schedule_score(sched, boxes_by_id, deadlines, W)
    print(f"  {tag:<28} 架次 {d['n_sorties']:>2} | 能耗 {d['energy_kwh']:>6.2f} | "
          f"完工 {d['makespan_h']:>4.2f} h | 准时 {d['on_time_rate']:>5.1%} | "
          f"首批违规 {d['n_late_first_batch']:>2} | 期望违规 {d['n_late_boxes']:>2}")


def main() -> int:
    boxes, uav_types, fleet, bat_inv, t_full, deadlines, bdf = load_inputs()
    leg_cache = load_cached()
    boxes_by_id = {b.box_id: b for b in boxes}
    t_full_c = t_full.get("C", 1800.0)

    code = "C"
    only_t, only_f = {code: uav_types[code]}, {code: fleet[code]}
    only_b = {code: bat_inv.get(code, 0)}
    only_tf = {code: t_full_c}
    res = (len(only_f[code]), only_b[code], t_full_c)

    clear_caches()
    S.DEFAULT_WEIGHTS = W
    cands = construct(boxes, only_t, leg_cache, deadlines, max_group=3)
    cands = local_search(cands, only_t, leg_cache, boxes_by_id, deadlines,
                         weights=W, resources=res)

    def sched_of(cs):
        plans = [c.plan for c in cs if c.plan.stops]
        pools = build_pools(only_f, only_b, only_tf)
        return schedule_dispatch(plans, only_t, leg_cache, boxes_by_id, pools)

    print("=== A) 现状（纯局部搜索）===")
    report("局部搜索最优", sched_of(cands), boxes_by_id, deadlines)

    # ---- B) 为紧期限区追加"首批专架次" ----
    tight = sorted({b.service_id for b in boxes
                    if b.is_first_batch and (b.first_batch_deadline_s or 1e9) <= 3600})
    print(f"\n=== B) 首批截止 ≤3600 s 的服务区（{len(tight)} 个）：{tight} ===")
    target_bids = {b.box_id for b in boxes
                   if b.is_first_batch and b.service_id in tight}
    print(f"    这些区的首批箱共 {len(target_bids)} 个"
          f"（总重 {sum(boxes_by_id[x].mass_kg for x in target_bids):.1f} kg / "
          f"总体积 {sum(boxes_by_id[x].volume_m3 for x in target_bids):.4f} m³）")

    stripped: list[_Cand] = []
    for c in cands:
        st = _remove_boxes(c.plan, target_bids)
        if not st.stops:
            continue
        stripped.append(c if st is c.plan else _Cand(st, {}, {}, dict(c.boxes), c.ev))
    stripped = [_Cand(_improve_order(c.plan, only_t[code], leg_cache, boxes_by_id),
                      {}, {}, dict(c.boxes),
                      _eval_plan(_improve_order(c.plan, only_t[code], leg_cache, boxes_by_id),
                                 only_t[code], leg_cache, boxes_by_id))
                for c in stripped]
    stripped = [c for c in stripped if c.ev.feasible]

    new_sorts: list[_Cand] = []
    for svc in tight:
        grp = tuple(x for x in target_bids if boxes_by_id[x].service_id == svc)
        if not grp:
            continue
        plan = SortiePlan(code, (svc,), {svc: grp})
        plan = _improve_order(plan, only_t[code], leg_cache, boxes_by_id)
        ev = _eval_plan(plan, only_t[code], leg_cache, boxes_by_id)
        if not ev.feasible:
            print(f"    ⚠️ {svc} 首批专架次不可行：{ev.reason}")
            continue
        new_sorts.append(_Cand(plan, {}, {}, {x: boxes_by_id[x] for x in grp}, ev))

    cands_b = stripped + new_sorts
    print(f"    拆分后：普通架次 {len(stripped)} + 首批专架次 {len(new_sorts)}"
          f" = {len(cands_b)}")
    report("拆分 + 首批专架次", sched_of(cands_b), boxes_by_id, deadlines)

    # 再做一轮局部搜索看能否继续改进
    after = local_search(cands_b, only_t, leg_cache, boxes_by_id, deadlines,
                         weights=W, resources=res)
    report("再局部搜索", sched_of(after), boxes_by_id, deadlines)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
