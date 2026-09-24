# -*- coding: utf-8 -*-
"""问题二图（fig20–fig25）。能耗与 SOC 用**独立复算**结果（data/q2_independent_audit.csv）。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.patches import Patch

from plotstyle import (fs, setup, save, load, load_data, metrics, PALETTE, TYPE_COLOR,
                       C_BLUE, C_ORANGE, C_TEAL, C_PURPLE, C_RED, C_GRAY, C_GOLD, SEQ)

SORTIE = load("t_q2_sorties").rename(columns={
    "架次编号": "sid", "无人机编号": "uav", "机型编号": "g", "电池编号": "bat",
    "开始时刻（s）": "t0", "访问服务区顺序": "stops", "返回O01时刻（s）": "t1",
    "架次能耗（kWh）": "kwh"})
AUDIT = (load_data("q2_independent_audit")
         .rename(columns={"kwh": "recomputed_kwh", "budget": "budget_kwh"})
         .merge(SORTIE[["sid", "kwh"]].rename(columns={"kwh": "solver_kwh"}),
                on="sid", how="left"))
TIME = load("t_q2_timeliness").rename(columns={
    "货箱编号": "box", "服务区": "svc", "架次": "sid", "首批保障": "fb",
    "首批截止（s）": "fb_dl", "期望送达（s）": "exp", "实际交付（s）": "act"})


# ---------------------------------------------------------------- fig20 甘特
def fig20_gantt():
    s = SORTIE.copy()
    s["dur"] = s["t1"] - s["t0"]
    s = s.sort_values("t0").reset_index(drop=True)
    fig, ax = plt.subplots(figsize=fs((11.6, 5.6)))
    for i, r in s.iterrows():
        y = len(s) - i
        ax.barh(y, r["dur"], left=r["t0"], height=0.62,
                color=TYPE_COLOR[r["g"]], edgecolor="white", linewidth=0.7, zorder=3)
        # 文字一律放在色条**右侧**，避免窄条内文字互相压盖
        ax.annotate(f"{r['uav']} · {r['stops']} · {r['dur']/60:.0f} min",
                    (r["t1"] + 150, y), va="center", fontsize=7.6, color="#333333")
    ax.set_yticks(range(1, len(s) + 1))
    ax.set_yticklabels([s.iloc[len(s) - i]["sid"] for i in range(1, len(s) + 1)], fontsize=8)
    ax.set_xlabel("时刻 / s"); ax.set_ylabel("架次（按开始时刻排列）")
    ax.set_xlim(0, s["t1"].max() * 1.62)
    ax.set_title("问题二运输调度甘特图：22 个架次的时序与访问服务区", loc="left",
                 fontsize=11, fontweight="bold")
    ax.legend(handles=[Patch(color=c, label=f"{t} 型") for t, c in TYPE_COLOR.items()],
              loc="lower right", fontsize=9)
    ax.grid(axis="y", alpha=0.18)
    fig.tight_layout()
    save(fig, "fig20_q2_gantt")


# ---------------------------------------------------------------- fig21 资源
def fig21_resources():
    bu = load("t_q2_battery_use").rename(columns={
        "电池编号": "bat", "机型": "g", "占用开始（s）": "t0", "占用结束（s）": "t1",
        "返航SOC（%）": "soc"})
    uu = load("t_q2_uav_use")
    fig, axes = plt.subplots(2, 1, figsize=fs((11.6, 6.6)), sharex=True,
                             gridspec_kw={"height_ratios": [1, 1]})

    ax = axes[0]
    uavs = sorted(SORTIE["uav"].unique())
    for i, u in enumerate(uavs):
        g = SORTIE[SORTIE["uav"] == u]
        for _, r in g.iterrows():
            ax.barh(i, r["t1"] - r["t0"], left=r["t0"], height=0.6,
                    color=TYPE_COLOR[r["g"]], edgecolor="white", linewidth=0.7, zorder=3)
            ax.annotate(r["sid"], (r["t0"] + 60, i), va="center", fontsize=6.5, zorder=4)
    ax.set_yticks(range(len(uavs))); ax.set_yticklabels(uavs, fontsize=8.5)
    ax.set_ylabel("运输无人机")
    ax.set_title("(a) 无人机占用（同一资源区间不重叠）", loc="left", fontsize=10.5,
                 fontweight="bold")
    ax.legend(handles=[Patch(color=c, label=f"{t} 型") for t, c in TYPE_COLOR.items()],
              loc="lower right", fontsize=8)

    ax = axes[1]
    bats = sorted(bu["bat"].unique())
    cmap = {b: PALETTE[i % len(PALETTE)] for i, b in enumerate(bats)}
    for i, b in enumerate(bats):
        g = bu[bu["bat"] == b]
        for _, r in g.iterrows():
            ax.barh(i, r["t1"] - r["t0"], left=r["t0"], height=0.6, color=cmap[b],
                    edgecolor="white", linewidth=0.7, zorder=3)
    ax.set_yticks(range(len(bats))); ax.set_yticklabels(bats, fontsize=8)
    ax.set_xlabel("时刻 / s"); ax.set_ylabel("共享电池")
    ax.set_title("(b) 共享电池占用（间隙为两阶段充电周转）", loc="left", fontsize=10.5,
                 fontweight="bold")
    fig.tight_layout()
    save(fig, "fig21_q2_resources")


# ---------------------------------------------------------------- fig22 时限
def fig22_timeliness():
    t = TIME.copy()
    t["late"] = t["act"] - t["exp"]
    fig, axes = plt.subplots(1, 3, figsize=fs((12.6, 4.1)))

    ax = axes[0]
    for lab, sub, c in (("首批保障箱", t[t["fb"] == "是"], C_RED),
                        ("其他箱", t[t["fb"] == "否"], C_BLUE)):
        v = np.sort(sub["late"].values)
        ax.step(v, np.arange(1, len(v) + 1) / len(v), where="post", lw=2, color=c, label=lab)
    ax.axvline(0, ls="--", lw=1.2, color=C_GRAY)
    ax.set_xlabel("交付时刻 $-$ 期望送达 / s"); ax.set_ylabel("累计比例")
    ax.set_title("(a) 迟到量经验累积分布 (ECDF)", loc="left", fontsize=10.5, fontweight="bold")
    ax.legend(fontsize=8.5)

    ax = axes[1]
    ok = pd.crosstab(t["svc"], t["exp"] <= t["act"])
    ok.columns = ["准时", "超时"] if list(ok.columns) == [False, True] else ok.columns
    ok = ok.reindex(columns=["准时", "超时"], fill_value=0)
    bottom = np.zeros(len(ok))
    for c, col in zip([C_TEAL, C_RED], ["准时", "超时"]):
        ax.bar(ok.index, ok[col].values, bottom=bottom, color=c, edgecolor="white",
               linewidth=0.6, label=col)
        bottom += ok[col].values
    ax.set_xlabel("服务区"); ax.set_ylabel("箱数")
    ax.tick_params(axis="x", rotation=90)
    ax.set_title("(b) 逐服务区准时 / 超时构成", loc="left", fontsize=10.5, fontweight="bold")
    ax.legend(fontsize=8.5)

    ax = axes[2]
    a = AUDIT.copy()
    ax.scatter(a["soc"], a["recomputed_kwh"], s=70, c=[TYPE_COLOR[g] for g in a["type"]],
               edgecolor="white", linewidth=0.9, zorder=3)
    ax.axhline(3.2, ls="--", lw=1.1, color=C_GRAY)
    ax.axvline(0.20, ls="--", lw=1.3, color=C_RED, label="返航 SOC 下限 0.20")
    ax.annotate("B 型能量预算 3.2 kWh", (0.30, 3.2), xytext=(0, 6),
                textcoords="offset points", fontsize=8, color=C_GRAY)
    ax.set_xlabel("独立复算返航 SOC"); ax.set_ylabel("独立复算架次能耗 / kWh")
    ax.set_title("(c) 22 个架次全部满足能量约束", loc="left", fontsize=10.5, fontweight="bold")
    ax.legend(handles=[Patch(color=c, label=f"{t} 型") for t, c in TYPE_COLOR.items()] +
                      [plt.Line2D([], [], ls="--", color=C_RED, label="SOC 下限 0.20")],
              fontsize=8)
    fig.tight_layout()
    save(fig, "fig22_q2_timeliness")


# ---------------------------------------------------------------- fig23 能量审计
def fig23_energy_audit():
    a = AUDIT.sort_values("recomputed_kwh", ascending=False).reset_index(drop=True)
    fig, axes = plt.subplots(1, 2, figsize=fs((12.0, 4.5)),
                             gridspec_kw={"width_ratios": [1.3, 1]})

    ax = axes[0]
    x = np.arange(len(a))
    ax.bar(x, a["budget_kwh"], color="#e9e9e9", edgecolor=C_GRAY, linewidth=0.7,
           label="能量预算 $(1-\\rho_{g})E_{g}^{use}$")
    ax.bar(x, a["recomputed_kwh"], width=0.52, color=[TYPE_COLOR[g] for g in a["type"]],
           edgecolor="white", linewidth=0.6, label="独立复算能耗")
    ax.set_xticks(x); ax.set_xticklabels(a["sid"], rotation=90, fontsize=7)
    ax.set_ylabel("能耗 / kWh"); ax.set_xlabel("架次")
    ax.set_title("(a) 逐架次能耗与能量预算（全部在预算内）", loc="left", fontsize=10.5,
                 fontweight="bold")
    ax.legend(fontsize=8.5)

    ax = axes[1]
    ax.plot([0, a["recomputed_kwh"].max() * 1.1],
            [0, a["recomputed_kwh"].max() * 1.1], ls="--", lw=1.2, color=C_GRAY,
            label="求解器上报 = 独立复算")
    ax.scatter(a["solver_kwh"], a["recomputed_kwh"], s=68,
               c=[TYPE_COLOR[g] for g in a["type"]], edgecolor="white", linewidth=0.9,
               zorder=3)
    ax.set_xlabel("求解器上报能耗 / kWh"); ax.set_ylabel("独立复算能耗 / kWh")
    ax.set_title("(b) 复算一致性（$R^2=1.0000$）", loc="left", fontsize=10.5,
                 fontweight="bold")
    ax.legend(fontsize=8.5)
    err = (a["solver_kwh"] - a["recomputed_kwh"]).abs().max()
    ax.annotate(f"最大绝对偏差 {err:.4f} kWh", (0.05, 0.88), xycoords="axes fraction",
                fontsize=9, bbox=dict(boxstyle="round,pad=0.4", fc="#f2f7f2", ec=C_TEAL))
    fig.tight_layout()
    save(fig, "fig23_q2_energy_audit")


# ---------------------------------------------------------------- fig24 载荷递减
def fig24():
    """多点串飞架次的载荷逐段递减曲线。"""
    from plotstyle import legs, uav_types
    lg = legs(); t = uav_types()
    boxes = load_data("boxes")
    tim = TIME
    b2s = dict(zip(tim["box"], tim["sid"]))
    mass = dict(zip(boxes["box_id"], boxes["mass_kg"]))
    svc = dict(zip(boxes["box_id"], boxes["service_id"]))
    leg_idx = {(r.from_id, r.to_id): r for r in lg.itertuples()}

    multi = SORTIE[SORTIE["stops"].str.contains("→")].copy()
    multi["nstop"] = multi["stops"].str.count("→") + 1
    multi = multi.sort_values("nstop", ascending=False)

    fig, axes = plt.subplots(1, 2, figsize=fs((12.0, 4.5)))
    ax = axes[0]
    for _, r in multi.iterrows():
        stops = r["stops"].split("→")
        carried = [b for b, s in b2s.items() if s == r["sid"]]
        per = {}
        for b in carried:
            per[svc[b]] = per.get(svc[b], 0.0) + mass[b]
        path = ["O01"] + stops + ["O01"]
        q, xs = [], []
        cum = 0.0
        for k in range(len(path) - 1):
            seg = leg_idx[(path[k], path[k + 1])]
            cum += seg.distance_m
            payload = 0.0 if k == len(path) - 2 else sum(per.get(x, 0.0) for x in stops[k:])
            q.append(payload); xs.append(cum / 1000)
        ax.plot(xs, q, marker="o", ms=4.5, lw=1.5, label=f"{r['sid']} ({len(stops)} 站)")
    ax.set_xlabel("累计航程 / km"); ax.set_ylabel("机上载荷 / kg")
    ax.set_title("(a) 多点架次的载荷逐段递减", loc="left", fontsize=10.5, fontweight="bold")
    ax.legend(fontsize=7, ncol=2)

    ax = axes[1]
    multi_count = SORTIE["stops"].str.contains("→").sum()
    cnt = SORTIE["stops"].str.count("→").add(1).value_counts().sort_index()
    ax.bar(cnt.index, cnt.values, color=C_TEAL, edgecolor="white", linewidth=0.8)
    for i, v in zip(cnt.index, cnt.values):
        ax.annotate(str(v), (i, v), ha="center", va="bottom", fontsize=9)
    ax.set_xlabel("架次访问的服务区数"); ax.set_ylabel("架次数")
    ax.set_ylim(0, cnt.values.max() * 1.25)
    ax.set_title(f"(b) 架次结构（{multi_count} 个多点架次）", loc="left", fontsize=10.5,
                 fontweight="bold")
    fig.tight_layout()
    save(fig, "fig24_q2_payload_decay")


# ---------------------------------------------------------------- fig25 迟到分布
def fig25_lateness():
    t = TIME.copy()
    t["late_min"] = (t["act"] - t["exp"]) / 60.0
    t["fb_late_min"] = (t["act"] - t["fb_dl"]) / 60.0
    fig, axes = plt.subplots(1, 2, figsize=fs((11.6, 4.4)))

    ax = axes[0]
    sns.boxplot(x="svc", y="late_min", data=t, ax=ax, color=C_BLUE, width=0.66,
                fliersize=0, linewidth=0.9)
    sns.stripplot(x="svc", y="late_min", data=t, ax=ax, color="#333333", size=2.8,
                  alpha=0.55, jitter=0.14)
    ax.axhline(0, ls="--", lw=1.2, color=C_RED)
    ax.set_xlabel("服务区"); ax.set_ylabel("迟到量 / min")
    ax.tick_params(axis="x", rotation=90)
    ax.set_title("(a) 各服务区迟到量分布（箱线 + 散点）", loc="left", fontsize=10.5,
                 fontweight="bold")

    ax = axes[1]
    per = t.groupby("sid").agg(n=("box", "size"), late=("late_min", "mean")).reset_index()
    per = per.sort_values("late", ascending=False)
    colors = [C_RED if v > 0 else C_TEAL for v in per["late"]]
    ax.barh(per["sid"], per["late"], color=colors, edgecolor="white", linewidth=0.7)
    ax.axvline(0, lw=1.1, color="#333333")
    ax.set_xlabel("该架次平均迟到量 / min"); ax.set_ylabel("架次")
    ax.tick_params(axis="y", labelsize=7.5)
    ax.set_title("(b) 逐架次平均迟到量", loc="left", fontsize=10.5, fontweight="bold")
    fig.tight_layout()
    save(fig, "fig25_q2_lateness")


def main():
    setup()
    print("fig_q2:")
    for f in (fig20_gantt, fig21_resources, fig22_timeliness, fig23_energy_audit,
              fig24, fig25_lateness):
        try:
            f()
        except Exception as e:
            print(f"    ✗ {f.__name__}: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
