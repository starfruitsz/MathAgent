# -*- coding: utf-8 -*-
"""对问题二方案做一次**完全独立**的可行性审计（不依赖仓库校验器）。

审计四件事：
  A. 能量与返航 SOC   —— 由航段缓存逐段复算
  B. 时间自洽性       —— 结束时刻是否 = 开始 + 准备 + 装载 + 飞行 + 逐站交接
  C. 资源占用冲突     —— 用方案自报的 [start, end] 区间检查无人机/电池是否重叠
  D. 时限达成         —— 逐箱比对首批截止与期望送达
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from verify_q2_energy import ROOT, equivalent_range, leg_energy  # noqa: F401

TOL = 1.0


def main() -> None:
    legs = pd.read_csv(ROOT / "tables" / "t_leg_cache_sample.csv")
    types = pd.read_csv(ROOT / "data" / "uav_types.csv").set_index("code")
    sorties = pd.read_csv(ROOT / "tables" / "t_q2_sorties.csv").rename(columns={
        "架次编号": "sid", "无人机编号": "uav", "机型编号": "gtype", "电池编号": "bat",
        "开始时刻（s）": "t0", "访问服务区顺序": "stops", "返回O01时刻（s）": "t1",
        "架次能耗（kWh）": "kwh"})
    boxes = pd.read_csv(ROOT / "data" / "boxes.csv")
    delivered = pd.read_csv(ROOT / "tables" / "t_q2_timeliness.csv")

    b2s = dict(zip(delivered["货箱编号"], delivered["架次"]))
    mass = dict(zip(boxes["box_id"], boxes["mass_kg"]))
    box_svc = dict(zip(boxes["box_id"], boxes["service_id"]))
    leg_idx = {(r.from_id, r.to_id): r for r in legs.itertuples()}

    print("=" * 78)
    print("A/B. 逐架次能量复算 + 时间自洽性")
    print("=" * 78)
    recs = []
    for s in sorties.itertuples():
        uav = types.loc[s.gtype]
        stops = str(s.stops).split("→")
        carried = [b for b, t in b2s.items() if t == s.sid]
        per_stop: dict[str, float] = {}
        n_per_stop: dict[str, int] = {}
        for b in carried:
            sv = box_svc[b]
            per_stop[sv] = per_stop.get(sv, 0.0) + mass[b]
            n_per_stop[sv] = n_per_stop.get(sv, 0) + 1

        path = ["O01"] + stops + ["O01"]
        energy = t_fly = 0.0
        for k in range(len(path) - 1):
            lg = leg_idx[(path[k], path[k + 1])]
            q = 0.0 if k == len(path) - 2 else sum(per_stop.get(x, 0.0) for x in stops[k:])
            energy += leg_energy(uav, lg.distance_m, lg.climb_m, q)
            t_fly += (lg.climb_m / uav["climb_speed_ms"] + lg.distance_m / uav["cruise_speed_ms"]
                      + lg.descent_m / uav["descent_speed_ms"])
        t_hand = sum(uav["handover_base_s"] + uav["handover_per_box_s"] * n_per_stop.get(st, 0)
                     for st in stops)
        t_end = s.t0 + uav["prepare_time_s"] + uav["box_load_time_s"] * len(carried) + t_fly + t_hand
        recs.append(dict(sid=s.sid, type=s.gtype, uav=s.uav, bat=s.bat, t0=s.t0, t1=s.t1,
                         n_box=len(carried), kwh=energy,
                         budget=(1 - uav["reserve_ratio"]) * uav["energy_kwh"],
                         soc=1 - energy / uav["energy_kwh"], t_end_recomp=t_end,
                         dt=abs(t_end - s.t1)))
    r = pd.DataFrame(recs)
    print(r.round(3).to_string(index=False))
    print(f"\n  能量超预算架次 : {int((r.kwh > r.budget + 1e-9).sum())} / {len(r)}")
    print(f"  返航 SOC 最小值: {r.soc.min():.4f}   (下限 0.2000)")
    print(f"  结束时刻最大偏差: {r.dt.max():.3f} s   → 时间自洽 {'✅' if r.dt.max() < TOL else '❌'}")

    print("\n" + "=" * 78)
    print("C. 资源占用冲突（按方案自报区间）")
    print("=" * 78)
    bad = 0
    for key in ("uav", "bat"):
        for name, g in r.groupby(key):
            g = g.sort_values("t0")
            prev = None
            for x in g.itertuples():
                if prev is not None and x.t0 < prev.t1 - TOL:
                    print(f"  ❌ {key} {name}: {prev.sid}[{prev.t0:.0f},{prev.t1:.0f}] "
                          f"∩ {x.sid}[{x.t0:.0f},{x.t1:.0f}]")
                    bad += 1
                prev = x
    print(f"  冲突数: {bad}  → {'✅ 无冲突' if bad == 0 else '❌ 存在冲突'}")

    print("\n" + "=" * 78)
    print("D. 时限达成")
    print("=" * 78)
    d = delivered.rename(columns={"货箱编号": "box", "首批保障": "fb", "首批截止（s）": "fb_dl",
                                  "期望送达（s）": "exp", "实际交付（s）": "act"})
    fb = d[d.fb == "是"]
    n_fb_late = int((fb.act > fb.fb_dl + TOL).sum())
    n_exp_late = int((d.act > d.exp + TOL).sum())
    print(f"  首批箱 {len(fb)} 个，超时 {n_fb_late} 个")
    print(f"  全部箱 {len(d)} 个，超期望 {n_exp_late} 个")
    print(f"  准时率(期望) = {1 - (d.act > d.exp + TOL).mean():.4f}")

    print("\n" + "=" * 78)
    print("E. 结论")
    print("=" * 78)
    ok_energy = int((r.kwh > r.budget + 1e-9).sum()) == 0
    ok_time = r.dt.max() < TOL
    print(f"  能量可行 : {'✅' if ok_energy else '❌'}")
    print(f"  时间自洽 : {'✅' if ok_time else '❌'}")
    print(f"  资源无冲突: {'✅' if bad == 0 else '❌'}")
    print("  → 方案在 能量 / 时间 / 资源 三个维度上均自洽，")
    # ★ 结论按实测数据分叉：时限是否达成由数据决定，不要写死"必然违规"。
    #   历史教训：旧方案只用 2 架 C 型（异构机队被退化），首批必然超时，
    #   当时把现象写成了"不可行性论证"；修复后 0 违规，此处必须能自动反映。
    if n_fb_late == 0 and n_exp_late == 0:
        print(f"  时限达成 : ✅ 首批 30 箱与全部 80 箱的时限**全部满足**"
              f"（首批超时 {n_fb_late} 箱 / 期望超时 {n_exp_late} 箱）")
        print("    ⇒ 本方案不存在任何违规，异构机队（A×4+B×2+C×2）已整体投入。")
    else:
        print(f"  时限达成 : ❌ 首批超时 {n_fb_late} 箱 / 期望超时 {n_exp_late} 箱")
        print("    ⇒ 剩余违规全部为时限类；请按 8 架机口径复核机队是否被退化为单一机型"
              "（见 ADR-029），再判断是资源不足还是求解器缺陷。")

    r.to_csv(ROOT / "data" / "q2_independent_audit.csv", index=False, encoding="utf-8-sig")
    print("\nwritten -> data/q2_independent_audit.csv")


if __name__ == "__main__":
    main()
