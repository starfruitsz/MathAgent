"""诊断：按服务区核对"箱数 vs 架次数"，量化装箱碎片化。

若某服务区的箱被拆到很多架次（而不是装满一个架次再换新），
说明构造过程倾向"每架次少装"，这正是 35 架次偏多的直接原因。

用法：
    python scripts/diag/q2_fragmentation.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.q2_transport_schedule.run_q2 import load_inputs  # noqa: E402
from src.q2_transport_schedule.solver import clear_caches, construct, local_search  # noqa: E402
from src.physics.leg_cache import load_cached  # noqa: E402


def report(cands, uav_types, boxes_by_id, tag: str) -> None:
    per_svc: dict[str, int] = defaultdict(int)
    boxes_svc: dict[str, set[str]] = defaultdict(set)
    type_cnt: dict[str, int] = defaultdict(int)
    for c in cands:
        type_cnt[c.plan.type_code] += 1
        for s in c.plan.stops:
            per_svc[s] += 1
            boxes_svc[s].update(c.plan.boxes_by_stop.get(s, ()))
    total_boxes = sum(len(v) for v in boxes_svc.values())
    print(f"\n=== {tag}（{len(cands)} 架次 / {total_boxes} 箱 / 机型 {dict(type_cnt)}）===")
    print(f"{'服务区':<7}{'箱数':>5}{'涉及架次':>9}{'箱/架次':>9}  单架次能否装下")
    frag = 0
    for s in sorted(per_svc):
        nb = len(boxes_svc[s])
        ns = per_svc[s]
        mass = sum(boxes_by_id[b].mass_kg for b in boxes_svc[s])
        vol = sum(boxes_by_id[b].volume_m3 for b in boxes_svc[s])
        fitC = ("✅" if mass <= uav_types["C"].max_payload_kg + 1e-9
                and vol <= uav_types["C"].volume_m3 + 1e-12 else "❌ 需拆分")
        print(f"  {s:<7}{nb:>4}{ns:>8}{nb/ns:>9.1f}  {fitC}  ({mass:.0f}kg/{vol:.3f}m³)")
        if ns > 1:
            frag += 1
    print(f"  → 被拆到多个架次的服务区：{frag} / {len(per_svc)}")


def main() -> int:
    boxes, uav_types, fleet, bat_inv, t_full, deadlines, bdf = load_inputs()
    leg_cache = load_cached()
    boxes_by_id = {b.box_id: b for b in boxes}

    clear_caches()
    c1 = construct(boxes, uav_types, leg_cache, deadlines, max_group=3)
    report(c1, uav_types, boxes_by_id, "construct 之后")

    c2 = local_search(c1, uav_types, leg_cache, boxes_by_id, deadlines)
    report(c2, uav_types, boxes_by_id, "local_search 之后")

    print("\n=== 理论上界估计（按服务区独立装箱 + 机型容量）===")
    from collections import defaultdict as dd
    mass_s: dict[str, float] = dd(float)
    vol_s: dict[str, float] = dd(float)
    for b in boxes:
        mass_s[b.service_id] += b.mass_kg
        vol_s[b.service_id] += b.volume_m3
    lb = 0
    for s in sorted(mass_s):
        m, v = mass_s[s], vol_s[s]
        k = max(
            -(-m // uav_types["C"].max_payload_kg),      # 质量下界
            -(-v // uav_types["C"].volume_m3),           # 体积下界
        )
        k = max(1, int(k))
        lb += k
        print(f"  {s}: {m:6.1f} kg / {v:.3f} m³  → 至少 {k} 架次（C 型）")
    print(f"  合计下界（按区独立、全部 C 型）：{lb} 架次")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
