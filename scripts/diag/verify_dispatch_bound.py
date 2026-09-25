"""诊断脚本：用**更长时限**复核 CP-SAT 调度器的最优性声明（论文 5.4 节的证据）。

问题背景
--------
论文给出 Q2 完工时间 7843.2266 s，并称其为 CP-SAT 在**固定组批 + 固定资源池**
下的最优值。CP-SAT 报 `OPTIMAL` 只说明它在自己那个模型里没找到更好的解；
为了排除"分支定界过早收敛"，本脚本做两件事：

1. **时限敏感性**：用 60 / 300 / 900 s 三档时限分别求解，看最优值是否稳定
   （若随时限下降，说明原报告值是搜索问题而非最优）；
2. **逐档收紧 Cmax 上界**：从给定方案时刻表的最晚返回时刻 (7740.19 s) 起
   逐步抬高上界，找出模型**第一次可行**的那一档 —— 那就是真实最优值
   （前提是模型本身正确）。

对"给定组批"与"本文改进组批"各做一遍，从而把
"给定时刻表 7740.19 s 更短"这一表面现象归因到**硬时限可行性**上。

用法：
    python scripts/diag/verify_dispatch_bound.py
产物：
    outputs/diag/dispatch_bound_probe.csv          逐档可行性
    outputs/diag/dispatch_ref.csv / dispatch_imp.csv   长时限下的指派明细
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
from ortools.sat.python import cp_model

from src.common import solution_data as SD
from src.common.config import outputs_dir
from src.physics.battery import charging_time
from src.physics.leg_cache import load_cached
from src.q0_data import build_processed as BP
from src.q1_payload_grouping.run_q1 import load_inputs
from src.q2_transport_schedule.dispatcher import TIME_SCALE, DispatchTask, dispatch
from src.q2_transport_schedule.solution import (
    BATTERIES,
    MACHINES,
    T_FULL,
    TransportSortie,
    _improve_grouping,
    compute_delivery_offset,
)

#: 给定方案时刻表的最晚返回（上界搜索的起点）
REF_CMAX_S = 7740.19


def build_tasks(src, uav_types, leg, meta):
    """把组批装配为调度任务（时限口径与 `solution._reschedule` 完全一致）。"""
    tasks = []
    for i, x in enumerate(src, 1):
        s = TransportSortie(
            sortie_id=f"T{i:02d}", type_code=x.g, sites=tuple(x.sites),
            box_ids=tuple(x.boxes), mass_kg=x.mass, volume_m3=x.volume,
            uav_id="—", battery_id="—", start_s=0.0, duration_s=x.duration,
            return_s=0.0, energy_kwh=x.energy, soc_end=x.soc, delivery={},
        )
        off = compute_delivery_offset(s, uav_types[s.type_code], leg)
        hard: list[float] = []
        for b in s.box_ids:
            r = meta.get(b)
            if r is None:
                continue
            hard.append(float(r["expected_time_s"]))
            fb = r["first_batch_deadline_s"]
            if fb == fb:
                hard.append(float(fb))
        tasks.append(DispatchTask(
            task_id=s.sortie_id, type_code=s.type_code,
            duration_s=s.duration_s, soc_end=s.soc_end,
            charge_s=charging_time(s.soc_end, T_FULL[s.type_code]),
            delivery_elapsed_s=off, hard_deadlines_s=tuple(hard),
            soft_deadlines_s=(),
        ))
    return tasks


def probe_cap(tasks, cap_s: float, time_limit_s: float = 60.0) -> str:
    """在 `Cmax <= cap_s` 下求可行性，返回 CP-SAT 状态名。"""
    m = cp_model.CpModel()
    H = int(12000 * TIME_SCALE)
    mach: dict[str, list] = {u: [] for ids in MACHINES.values() for u in ids}
    bat: dict[str, list] = {k: [] for ids in BATTERIES.values() for k in ids}
    ends = []
    for i, t in enumerate(tasks):
        dur = max(1, int(round(t.duration_s * TIME_SCALE)))
        st = m.NewIntVar(0, H - dur, f"t{i}")
        ms = []
        for u in MACHINES[t.type_code]:
            b = m.NewBoolVar(f"mu{i}_{u}")
            ms.append((u, b, m.NewOptionalIntervalVar(st, dur, st + dur, b,
                                                      f"iu{i}_{u}")))
        m.AddExactlyOne(b for _, b, _ in ms)
        for u, _, iv in ms:
            mach[u].append(iv)
        ch = max(0, int(round(t.charge_s * TIME_SCALE)))
        bs = []
        for k in BATTERIES[t.type_code]:
            b = m.NewBoolVar(f"bk{i}_{k}")
            bs.append((k, b, m.NewOptionalIntervalVar(
                st, dur + ch, st + dur + ch, b, f"ik{i}_{k}")))
        m.AddExactlyOne(b for _, b, _ in bs)
        for k, _, iv in bs:
            bat[k].append(iv)
        for dl in t.hard_deadlines_s:
            lim = int(round((dl - t.delivery_elapsed_s) * TIME_SCALE))
            if lim < 0:
                return "DEADLINE_INFEASIBLE"
            m.Add(st <= lim)
        ends.append(st + dur)
    for ivs in mach.values():
        if ivs:
            m.AddNoOverlap(ivs)
    for ivs in bat.values():
        if ivs:
            m.AddNoOverlap(ivs)
    cmax = m.NewIntVar(0, H, "C")
    m.AddMaxEquality(cmax, ends)
    m.Add(cmax <= int(round(cap_s * TIME_SCALE)))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = 8
    return solver.StatusName(solver.Solve(m))


def main() -> int:
    _, uav_types, _, _ = load_inputs()
    leg = load_cached()
    meta = {str(r["box_id"]): r for _, r in BP.load_boxes().iterrows()}

    ref = list(SD.q2(3).sorties)
    imp = _improve_grouping(ref, uav_types, leg)

    # ---- 1) 时限敏感性：最优值是否随时限稳定 ----
    print("=== 时限敏感性（同一组批，不同求解时限）===")
    for tag, src in (("给定组批", ref), ("改进组批", imp)):
        tasks = build_tasks(src, uav_types, leg, meta)
        for tl in (60.0, 300.0, 900.0):
            t0 = time.perf_counter()
            res = dispatch(tasks, MACHINES, BATTERIES, time_limit_s=tl)
            print(f"  {tag}  时限 {tl:5.0f}s → {res.status:9s} "
                  f"Cmax = {res.makespan_s:9.2f} s  "
                  f"（{time.perf_counter()-t0:.0f}s，违约 {len(res.violations)}）")

    # ---- 2) 逐档收紧 Cmax 上界，定位真实最优值 ----
    print(f"\n=== 逐档上界可行性（起点 {REF_CMAX_S:.2f} s = 给定方案时刻表）===")
    rows = []
    for tag, src in (("给定组批", ref), ("改进组批", imp)):
        tasks = build_tasks(src, uav_types, leg, meta)
        caps = [REF_CMAX_S, REF_CMAX_S + 0.2, 7745.0, 7750.0, 7780.0, 7800.0,
                7820.0, 7843.2, 7850.0, 7900.0]
        first_ok = None
        for cap in caps:
            st = probe_cap(tasks, cap)
            rows.append({"组批": tag, "Cmax上界（s）": cap, "状态": st})
            print(f"  {tag}  Cmax ≤ {cap:8.2f} s → {st}")
            if st in ("OPTIMAL", "FEASIBLE") and first_ok is None:
                first_ok = cap
        print(f"  → {tag} 首次可行上界：{first_ok} s")
        res = dispatch(tasks, MACHINES, BATTERIES, time_limit_s=300.0)
        out = []
        for i, x in enumerate(src, 1):
            a = res.assignments[f"T{i:02d}"]
            out.append({"架次": f"T{i:02d}", "机型": x.g, "服务区": x.sites[0],
                        "历时s": round(x.duration, 1),
                        "实体机": a["machine"], "电池": a["battery"],
                        "起飞s": round(a["start_s"], 1),
                        "返回s": round(a["return_s"], 1)})
        d = outputs_dir("diag")
        d.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(out).to_csv(
            d / ("dispatch_ref.csv" if tag == "给定组批" else "dispatch_imp.csv"),
            index=False, encoding="utf-8-sig")

    d = outputs_dir("diag")
    pd.DataFrame(rows).to_csv(d / "dispatch_bound_probe.csv",
                              index=False, encoding="utf-8-sig")
    print(f"\n已写 {d / 'dispatch_bound_probe.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
