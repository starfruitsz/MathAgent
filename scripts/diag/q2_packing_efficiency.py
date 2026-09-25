"""Q2 装箱效率诊断：逐架次装载率 + 逐服务区碎片化 + 轮次下界。

回答的问题：28 架次里到底有多少"装不满"的余量？理论上能不能压到 20~25？

用法：
    python scripts/diag/q2_packing_efficiency.py
"""

from __future__ import annotations

import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

from src.physics.leg_cache import load_cached          # noqa: E402
from src.q2_transport_schedule.run_q2 import load_inputs, solve  # noqa: E402

logging.disable(logging.INFO)
OUT = Path("outputs/diag")


def main() -> int:
    boxes, ut, fleet, bi, tf, dl, _ = load_inputs()
    lc = load_cached()
    bid = {b.box_id: b for b in boxes}
    r = solve(boxes, ut, lc, dl, fleet, bi, tf,
              do_local_search=True, fleet_mode="auto")

    print(f"方案：{r.n_sorties} 架次 / {r.total_energy_kwh:.2f} kWh / "
          f"{r.makespan_s/3600:.2f} h / 准时 {r.on_time_rate:.1%} / "
          f"违规 {r.violations_first_batch}+{r.violations_expected}")

    # ---- 逐架次装载率 ----
    print(f"\n{'架次':<6}{'机型':<5}{'站点':<4}{'箱数':>5}{'质量kg':>9}{'质量上限':>9}"
          f"{'质量率':>8}{'体积m³':>9}{'体积上限':>9}{'体积率':>8}")
    print("-" * 78)
    tot_m = tot_v = cap_m = cap_v = 0.0
    rows = []
    for s in sorted(r.sorties, key=lambda x: (x.type_code, x.sortie_id)):
        u = ut[s.type_code]
        m = sum(bid[b].mass_kg for svc in s.stops
                for b in s.boxes_by_stop.get(svc, ()))
        v = sum(bid[b].volume_m3 for svc in s.stops
                for b in s.boxes_by_stop.get(svc, ()))
        nb = sum(len(s.boxes_by_stop.get(svc, ())) for svc in s.stops)
        tot_m += m; tot_v += v
        cap_m += u.max_payload_kg; cap_v += u.volume_m3
        rows.append((s, u, m, v, nb, m / u.max_payload_kg, v / u.volume_m3))
        print(f"{s.sortie_id:<6}{s.type_code:<5}{len(s.stops):<4}{nb:>5}{m:>9.1f}"
              f"{u.max_payload_kg:>9.1f}{m/u.max_payload_kg:>8.0%}{v:>9.3f}"
              f"{u.volume_m3:>9.3f}{v/u.volume_m3:>8.0%}")
    print("-" * 78)
    print(f"{'合计':<15}{sum(x[4] for x in rows):>5}{tot_m:>9.1f}{cap_m:>9.1f}"
          f"{tot_m/cap_m:>8.0%}{tot_v:>9.3f}{cap_v:>9.3f}{tot_v/cap_v:>8.0%}")

    # ---- 理论轮次下界 ----
    wave_m = sum(ut[c].max_payload_kg * len(fleet[c]) for c in fleet if fleet[c])
    wave_v = sum(ut[c].volume_m3 * len(fleet[c]) for c in fleet if fleet[c])
    tot_box_m = sum(b.mass_kg for b in boxes)
    tot_box_v = sum(b.volume_m3 for b in boxes)
    w_m = tot_box_m / wave_m
    w_v = tot_box_v / wave_v
    n_uav = sum(len(v) for v in fleet.values())
    print(f"\n单轮容量：{wave_m:.0f} kg / {wave_v:.3f} m³（{n_uav} 架）")
    print(f"总需求  ：{tot_box_m:.0f} kg / {tot_box_v:.3f} m³（{len(boxes)} 箱）")
    print(f"质量需要 {w_m:.2f} 轮，体积需要 {w_v:.2f} 轮"
          f" ⇒ 下界 ⌈max⌉={int(-(-max(w_m, w_v)//1))} 轮"
          f" × {n_uav} 架 = "
          f"{int(-(-max(w_m, w_v)//1)) * n_uav} 架次")

    # ---- 逐服务区碎片化 ----
    print("\n逐服务区架次碎片化（同区箱被拆到几个架次）：")
    frag: dict[str, list[str]] = defaultdict(list)
    for s in r.sorties:
        for svc in s.stops:
            if s.boxes_by_stop.get(svc):
                frag[svc].append(s.sortie_id)
    for svc in sorted(frag, key=lambda k: -len(frag[k])):
        n_box = sum(1 for b in boxes if b.service_id == svc)
        print(f"  {svc}: {n_box:2d} 箱 → {len(frag[svc])} 个架次 "
              f"({', '.join(frag[svc])})")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "q2_packing_efficiency.json").write_text(json.dumps({
        "n_sorties": r.n_sorties,
        "mass_util": round(tot_m / cap_m, 4),
        "vol_util": round(tot_v / cap_v, 4),
        "total_mass_kg": round(tot_box_m, 1),
        "total_vol_m3": round(tot_box_v, 3),
        "wave_mass_kg": round(wave_m, 1),
        "wave_vol_m3": round(wave_v, 3),
        "lb_waves": int(-(-max(w_m, w_v) // 1)),
        "lb_sorties": int(-(-max(w_m, w_v) // 1)) * n_uav,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写入 {OUT / 'q2_packing_efficiency.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
