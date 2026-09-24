"""诊断：Q2 为何全部用 B 型机？对比三种机型的可行性与架次数。

Q1 的结论是"全部 C 型、18 架次、75.07 kWh"，而 Q2 得到"全部 B 型、35 架次、83.01 kWh"。
本脚本回答：C 型在 Q2 的规则下是否可用？为什么构造过程没选它？

用法：
    python scripts/diag/q2_type_choice.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.physics.energy import Segment, segment_energy_kwh, segment_time_s  # noqa: E402
from src.physics.leg_cache import load_cached  # noqa: E402
from src.q2_transport_schedule.run_q2 import load_inputs  # noqa: E402
from src.q2_transport_schedule.solver import construct  # noqa: E402


def main() -> int:
    boxes, uav_types, fleet, bat_inv, t_full, deadlines, bdf = load_inputs()
    leg_cache = load_cached()

    print("=== 机型关键参数 ===")
    for c, u in uav_types.items():
        print(f"  {c}: 载荷 {u.max_payload_kg:>5.1f} kg  舱容 {u.volume_m3:.3f} m³  "
              f"可用能量 {u.energy_kwh:.1f} kWh  预算 {(1-u.reserve_ratio)*u.energy_kwh:.2f} kWh  "
              f"空载航程 {u.range_empty_m/1000:.1f} km  满载 {u.range_full_m/1000:.1f} km  "
              f"巡航 {u.cruise_speed_ms} m/s")

    # 各机型"满载时能飞多远"（回程空载）
    print("\n=== 单点往返能力（O01→Si→O01，去程满载）===")
    print(f"{'机型':<4} {'满载可飞距离':>12} {'实际最远服务区':>14}  说明")
    for c, u in uav_types.items():
        # 解 d 使 满载去程 + 空载回程 = 预算
        best = None
        for d_km in range(1, 300):
            d = d_km * 100.0
            e = (segment_energy_kwh(u, Segment(d, 0, 0), u.max_payload_kg)
                 + segment_energy_kwh(u, Segment(d, 0, 0), 0.0))
            if e > u.energy_budget_kwh:
                best = (d_km - 1) * 100.0
                break
        # 实际最远服务区距离
        dmax = max(leg_cache.distance("O01", s) for s in
                   [f"S{i:03d}" for i in range(1, 16)])
        print(f"  {c:<4} {best/1000:>10.2f} km {dmax/1000:>12.2f} km  "
              f"{'✅ 可达' if best and best >= dmax else '⚠️ 满载不可达全部服务区'}")

    print("\n=== 用 construct() 强制各机型，看架次数 ===")
    from src.q2_transport_schedule.solver import clear_caches
    for c in uav_types:
        only = {c: uav_types[c]}
        clear_caches()
        try:
            cands = construct(boxes, only, leg_cache, deadlines, max_group=3)
            n = len(cands)
            tot = sum(x.ev.energy_kwh for x in cands)
            print(f"  仅用 {c} 型：{n:>3} 架次，总能耗 {tot:6.2f} kWh")
        except Exception as exc:  # noqa: BLE001
            print(f"  仅用 {c} 型：❌ {type(exc).__name__}: {str(exc)[:90]}")

    print("\n=== 实际求解结果：机型使用与每架次载荷 ===")
    import json
    rl = json.load(open(ROOT / "outputs/q2/run_log.json", encoding="utf-8"))
    ss = rl["sorties"]
    from collections import Counter
    types = Counter(s["机型编号"] for s in ss)
    print(f"  机型使用：{dict(types)}；架次总数 {len(ss)}")
    # 从逐箱交付表反推每架次箱数
    tl = rl["deliveries"]
    per = Counter(x["架次"] for x in tl)
    cnt = Counter(per.values())
    print(f"  每架次箱数分布：{dict(sorted(cnt.items()))}")
    boxmass = {b.box_id: b.mass_kg for b in boxes}
    print(f"  平均每架次 {len(tl)/len(ss):.1f} 箱 / "
          f"{sum(boxmass.values())/len(ss):.1f} kg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
