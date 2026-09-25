"""临时脚本：核对优化前后 CP-SAT 调度完工时间（用完即删）。

用法：python tools/compare_dispatch.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from src.common import solution_data as SD
from src.common.config import outputs_dir
from src.physics.battery import charging_time
from src.physics.leg_cache import load_cached
from src.q0_data import build_processed as BP
from src.q1_payload_grouping.run_q1 import load_inputs
from src.q2_transport_schedule.dispatcher import DispatchTask, dispatch
from src.q2_transport_schedule.solution import (
    BATTERIES,
    MACHINES,
    T_FULL,
    _improve_grouping,
    compute_delivery_offset,
)


def build_tasks(src, uav_types, leg, meta):
    import pandas as pd

    tasks = []
    rows = []
    for i, x in enumerate(src, 1):
        from src.q2_transport_schedule.solution import TransportSortie

        s = TransportSortie(
            sortie_id=f"T{i:02d}", type_code=x.g, sites=tuple(x.sites),
            box_ids=tuple(x.boxes), mass_kg=x.mass, volume_m3=x.volume,
            uav_id="—", battery_id="—", start_s=0.0, duration_s=x.duration,
            return_s=0.0, energy_kwh=x.energy, soc_end=x.soc, delivery={},
        )
        s.delivery_elapsed_s = compute_delivery_offset(s, uav_types[s.type_code], leg)
        hard = []
        for b in s.box_ids:
            m = meta.get(b)
            if m is None:
                continue
            hard.append(float(m["expected_time_s"]))
            fb = m["first_batch_deadline_s"]
            if fb is not None and fb == fb:
                hard.append(float(fb))
        tasks.append(DispatchTask(
            task_id=s.sortie_id, type_code=s.type_code,
            duration_s=s.duration_s, soc_end=s.soc_end,
            charge_s=charging_time(s.soc_end, T_FULL[s.type_code]),
            delivery_elapsed_s=s.delivery_elapsed_s,
            hard_deadlines_s=tuple(hard), soft_deadlines_s=(),
        ))
        rows.append((s.sortie_id, s.type_code, x.sites[0], round(s.duration_s, 1)))
    return tasks, rows


def main() -> int:
    _, uav_types, _, _ = load_inputs()
    leg = load_cached()
    meta = {str(r["box_id"]): r for _, r in BP.load_boxes().iterrows()}

    ref = list(SD.q2(3).sorties)
    imp = _improve_grouping(ref, uav_types, leg)

    for tag, src in (("给定组批(原顺序)", ref), ("精确DP组批(改进)", imp)):
        tasks, rows = build_tasks(src, uav_types, leg, meta)
        res = dispatch(tasks, MACHINES, BATTERIES, time_limit_s=90, workers=8)
        print(f"\n=== {tag}：{len(tasks)} 架次 ===")
        print(f"状态 {res.status}  完工 {res.makespan_s:.2f} s  "
              f"违约 {len(res.violations)} 条")
        if res.violations:
            print("  ", res.violations[:5])
        # 输出关键路径附近的架次
        late = sorted(((v["return_s"], k) for k, v in res.assignments.items()),
                      reverse=True)[:4]
        print("  最晚返回：", [(k, round(t, 1)) for t, k in late])
        if tag.startswith("给定"):
            _dump(res, rows, outputs_dir("diag") / "dispatch_ref.csv")
        else:
            _dump(res, rows, outputs_dir("diag") / "dispatch_imp.csv")
    return 0


def _dump(res, rows, path):
    import pandas as pd

    path.parent.mkdir(parents=True, exist_ok=True)
    out = []
    for sid, g, site, dur in rows:
        a = res.assignments[sid]
        out.append({"架次": sid, "机型": g, "服务区": site, "历时s": dur,
                    "实体机": a["machine"], "电池": a["battery"],
                    "起飞s": round(a["start_s"], 1),
                    "返回s": round(a["return_s"], 1)})
    pd.DataFrame(out).to_csv(path, index=False, encoding="utf-8-sig")
    print("  →", path)


if __name__ == "__main__":
    raise SystemExit(main())
