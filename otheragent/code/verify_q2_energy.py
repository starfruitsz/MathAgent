# -*- coding: utf-8 -*-
"""独立复算问题二每个架次的能耗与返航 SOC，判定"求解器"与"校验器"孰是孰非。

口径来源（与 src/physics/ 完全一致，此处**独立重写**以便交叉验证）：
    L_g(q)   = L_g0 - (L_g0 - L_gF) * (q / Q_g) ** 1.5
    E_hor    = (d / L_g(q)) * E_g^use
    E_up     = m * g * h+ / eta_up / 3.6e6 ,  m = empty_mass + payload
    下降不单独计能耗（附件下降能耗效率 = 0）
    能量预算  = (1 - rho_g) * E_g^use
    SOC_返航  = 1 - E_sortie / E_g^use

输入全部来自仓库既有结果（航段缓存 tables/t_leg_cache_sample.csv 实为完整 240 段）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
G = 9.80665
J_PER_KWH = 3.6e6


def equivalent_range(uav: pd.Series, q: float) -> float:
    q = min(max(q, 0.0), uav["max_payload_kg"])
    r = (q / uav["max_payload_kg"]) ** 1.5
    return uav["range_empty_m"] - (uav["range_empty_m"] - uav["range_full_m"]) * r


def leg_energy(uav: pd.Series, d: float, h_up: float, q: float) -> float:
    """单航段能耗（kWh）：水平巡航 + 爬升附加（下降不单独计）。"""
    e_hor = d / equivalent_range(uav, q) * uav["energy_kwh"] if d > 0 else 0.0
    m = uav["empty_mass_kg"] + q
    e_up = m * G * h_up / uav["climb_efficiency"] / J_PER_KWH if h_up > 0 else 0.0
    return e_hor + e_up


def main() -> None:
    legs = pd.read_csv(ROOT / "tables" / "t_leg_cache_sample.csv")
    types = pd.read_csv(ROOT / "data" / "uav_types.csv").set_index("code")
    sorties = pd.read_csv(ROOT / "tables" / "t_q2_sorties.csv").rename(
        columns={"架次编号": "sid", "机型编号": "gtype", "访问服务区顺序": "stops",
                 "架次能耗（kWh）": "kwh"}
    )
    boxes = pd.read_csv(ROOT / "data" / "boxes.csv")
    delivered = pd.read_csv(ROOT / "tables" / "t_q2_timeliness.csv")

    b2s = dict(zip(delivered["货箱编号"], delivered["架次"]))
    mass = dict(zip(boxes["box_id"], boxes["mass_kg"]))
    box_svc = dict(zip(boxes["box_id"], boxes["service_id"]))
    leg_idx = {(r.from_id, r.to_id): r for r in legs.itertuples()}

    rows = []
    for s in sorties.itertuples():
        uav = types.loc[s.gtype]
        stops = str(s.stops).split("→")

        carried = [b for b, t in b2s.items() if t == s.sid]
        per_stop: dict[str, float] = {}
        for b in carried:
            per_stop[box_svc[b]] = per_stop.get(box_svc[b], 0.0) + mass[b]

        path = ["O01"] + stops + ["O01"]
        total, detail = 0.0, []
        for k in range(len(path) - 1):
            a, b = path[k], path[k + 1]
            leg = leg_idx[(a, b)]
            # 该航段机上载荷 = 尚未投送的货；末段（返程）为空载
            q = 0.0 if k == len(path) - 2 else sum(per_stop.get(x, 0.0) for x in stops[k:])
            e = leg_energy(uav, leg.distance_m, leg.climb_m, q)
            total += e
            detail.append((f"{a}->{b}", round(leg.distance_m, 1), round(leg.climb_m, 1),
                           round(q, 1), round(e, 4)))

        budget = (1 - uav["reserve_ratio"]) * uav["energy_kwh"]
        rows.append(dict(
            sortie=s.sid, type=s.gtype, n_boxes=len(carried),
            payload_kg=round(sum(mass[b] for b in carried), 2),
            solver_kwh=round(float(s.kwh), 4), recomputed_kwh=round(total, 4),
            budget_kwh=round(budget, 4), soc_return=round(1 - total / uav["energy_kwh"], 4),
            feasible=bool(total <= budget + 1e-9), legs=detail,
        ))

    df = pd.DataFrame(rows)
    print(df.drop(columns=["legs"]).to_string(index=False))
    print()
    print("solver  total kWh :", round(df.solver_kwh.sum(), 4))
    print("recomputed total  :", round(df.recomputed_kwh.sum(), 4))
    print("infeasible sorties:", int((~df.feasible).sum()), "/", len(df))
    print("\n--- worst 3 sorties, leg detail ---")
    for r in df.sort_values("recomputed_kwh", ascending=False).head(3).itertuples():
        print(f"\n{r.sortie} ({r.type}) 用箱 {r.n_boxes} 总重 {r.payload_kg} kg  "
              f"复算 {r.recomputed_kwh} kWh / 预算 {r.budget_kwh} kWh")
        for d in r.legs:
            print("    from->to %-14s d=%-9s climb=%-8s q=%-7s E=%s" % d)

    (ROOT / "data" / "q2_energy_recheck.json").write_text(
        json.dumps(df.drop(columns=["legs"]).to_dict("records"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("\nwritten -> data/q2_energy_recheck.json")


if __name__ == "__main__":
    main()
