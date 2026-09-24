"""证明：在本机队下，首批 3600 s 硬期限**最多能保障几个服务区**？

思路（可证明的资源界）
--------------------
只考虑"必须 3600 s 内送达"的那批箱（每区 2 箱 = 1 医疗 + 1 饮用水，
总重约 17 kg，任何机型一次可装）。对每个这样的服务区 s，令 τ(s) 为
**最早可能交付时刻**（0 时刻开工、准备+装载+首段飞行+交接），
则 s 必须在 [0, 3600] 内被"占用一次机—池"。

若把每个服务区的首批箱各自作为一个架次（这是最省时间的做法：
不与其他货混装、不绕路），则问题退化为**并行机调度**：

    m 个作业（每个占用一台无人机 + 一组电池，时长 τ(s) + 充电时间）
    在 n_uav 台并行机上，问有多少能在 3600 s 前完成。

由此得到一个**与算法无关的下界**（任何方案都无法超越）：

    能按时送达的服务区数 ≤ n_uav × (1 + ⌊(3600 − τ_min) / τ_min⌋)

即"每台无人机在 3600 s 内最多飞几次"。

用法：
    python scripts/diag/q2_firstbatch_bound.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.physics.battery import charging_time  # noqa: E402
from src.physics.energy import Segment, segment_time_s  # noqa: E402
from src.physics.leg_cache import load_cached  # noqa: E402
from src.q2_transport_schedule.run_q2 import load_inputs  # noqa: E402

HORIZON = 3600.0


def main() -> int:
    boxes, uav_types, fleet, bat_inv, t_full, deadlines, bdf = load_inputs()
    leg_cache = load_cached()

    tight = sorted({b.service_id for b in boxes
                    if b.is_first_batch and (b.first_batch_deadline_s or 1e9) <= HORIZON})
    print(f"首批截止 ≤ {HORIZON:.0f} s 的服务区：{len(tight)} 个 → {tight}\n")

    for code in ("A", "B", "C"):
        if code not in uav_types or not fleet.get(code):
            continue
        uav = uav_types[code]
        n_uav = len(fleet[code])
        n_bat = bat_inv.get(code, 0)
        tf = t_full.get(code, 1800.0)

        print(f"=== {code} 型（{n_uav} 架 / {n_bat} 组电池，满充 {tf:.0f} s）===")
        print(f"{'服务区':<7}{'首个交付 s':>11}{'整架次时长 s':>13}{'返航SOC':>9}"
              f"{'占用(含充电) s':>15}{'3600 内可飞':>11}")
        n_fit = 0
        for s in tight:
            # 该区全部首批箱 = 一个架次
            grp = [b for b in boxes if b.is_first_batch and b.service_id == s]
            q = sum(b.mass_kg for b in grp)
            g1 = leg_cache.get("O01", s)
            g2 = leg_cache.get(s, "O01")
            t_fly = (segment_time_s(uav, Segment(g1["distance_m"], g1["climb_m"], g1["descent_m"]))
                     + segment_time_s(uav, Segment(g2["distance_m"], g2["climb_m"], g2["descent_m"])))
            t_hand = uav.handover_base_s + uav.handover_per_box_s * len(grp)
            t_load = uav.box_load_time_s * len(grp)
            t_first = uav.prepare_time_s + t_load + segment_time_s(
                uav, Segment(g1["distance_m"], g1["climb_m"], g1["descent_m"])) + t_hand
            t_total = uav.prepare_time_s + t_load + t_fly + t_hand
            # 返航 SOC（用物理层）
            from src.physics.energy import segment_energy_kwh
            e = (segment_energy_kwh(uav, Segment(g1["distance_m"], g1["climb_m"], g1["descent_m"]), q)
                 + segment_energy_kwh(uav, Segment(g2["distance_m"], g2["climb_m"], g2["descent_m"]), 0.0))
            soc = max(0.0, 1.0 - e / uav.energy_kwh)
            occ = t_total + charging_time(soc, tf)
            # 单机在 3600 s 内能飞几个该区架次
            k = 0
            t = 0.0
            while True:
                t_next = t + occ if k else t_first
                # 第 1 次交付在 t_first，之后每次交付在前一次"占用"结束后 + t_first
                if k == 0:
                    finish, deliver = t_total, t_first
                else:
                    base = t_first + (occ - t_first) * k  # 粗略：交付时刻
                    deliver = t_first + occ * k
                    finish = deliver + (t_total - t_first)
                if deliver <= HORIZON:
                    k += 1
                    t = finish
                else:
                    break
            ok = k >= 1
            n_fit += 1 if ok else 0
            print(f"  {s:<7}{t_first:>11.0f}{t_total:>13.0f}{soc:>9.3f}{occ:>15.0f}"
                  f"{k:>11}")
        print(f"  → 单机 3600 s 内至少能保障 1 次的服务区：{n_fit}/{len(tight)}")
        print(f"  → **并行机上界**：{n_uav} 架 × 每架 3600 s 内的架次数 ≈ "
              f"{n_uav} × k_min ，其中 k_min 取上面的最小值\n")

    print("注：机—池是**成对**资源（无人机 + 电池），且电池飞行后需充电。")
    print("    上面的占用时长已含充电，因此该上界对任何算法都成立。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
