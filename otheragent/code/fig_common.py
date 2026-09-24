# -*- coding: utf-8 -*-
"""总体分析章与公共模型章的图（fig06–fig12）。"""
from __future__ import annotations

import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.patches import Rectangle

from plotstyle import (fs, setup, save, load, load_data, uav_types, legs, nodes, boxes,
                       PALETTE, TYPE_COLOR, C_BLUE, C_ORANGE, C_TEAL, C_PURPLE,
                       C_RED, C_GRAY, C_GOLD, SEQ)

G = 9.80665
J_KWH = 3.6e6


def to_xy(lon, lat, lon0, lat0):
    return (np.asarray(lon) - lon0) * 111320.0 * np.cos(np.radians(lat0)), \
           (np.asarray(lat) - lat0) * 110540.0


# ---------------------------------------------------------------- fig06 节点
def fig06_nodes():
    nd = nodes()
    o = nd[nd["kind"] == "center"].iloc[0]
    s = nd[nd["kind"] == "service"].sort_values("id")
    x0, y0 = to_xy(o["lon"], o["lat"], o["lon"], o["lat"])
    xs, ys = to_xy(s["lon"], s["lat"], o["lon"], o["lat"])
    xo, yo = 0.0, 0.0

    fig, axes = plt.subplots(1, 2, figsize=fs((11.2, 4.5)),
                             gridspec_kw={"width_ratios": [1.25, 1]})

    ax = axes[0]
    sc = ax.scatter(xs / 1000, ys / 1000, c=s["ground_elev_m"], s=40 + s["population"] / 8,
                    cmap=SEQ, edgecolor="white", linewidth=0.8, zorder=3, label="服务区 S001–S015")
    ax.scatter([xo / 1000], [yo / 1000], marker="*", s=340, c=C_RED,
               edgecolor="white", linewidth=0.9, zorder=4, label="调度中心 O01")
    for sid, px, py in zip(s["id"], xs, ys):
        ax.annotate(sid, (px / 1000, py / 1000),
                    textcoords="offset points", xytext=(4, 4), fontsize=7)
    cb = fig.colorbar(sc, ax=ax, pad=0.02)
    cb.set_label("地面海拔 / m")
    ax.set_xlabel("东向距离 / km"); ax.set_ylabel("北向距离 / km")
    ax.set_title("(a) 节点空间分布（气泡大小 ∝ 需保护人口）", loc="left", fontsize=10.5,
                 fontweight="bold")
    ax.legend(loc="upper left", fontsize=8)
    ax.set_aspect("equal")

    ax = axes[1]
    sns.barplot(x="id", y="ground_elev_m", data=s, ax=ax, color=C_TEAL,
                edgecolor="#2f6b60", linewidth=0.6)
    ax.axhline(o["ground_elev_m"], color=C_RED, ls="--", lw=1.3,
               label=f"O01 海拔 {o['ground_elev_m']:.1f} m")
    ax.set_xlabel("服务区"); ax.set_ylabel("地面海拔 / m")
    ax.tick_params(axis="x", rotation=90)
    ax.set_title("(b) 各服务区地面海拔", loc="left", fontsize=10.5, fontweight="bold")
    ax.legend(fontsize=8)
    fig.tight_layout()
    save(fig, "fig06_nodes")


# ---------------------------------------------------------------- fig07 航段
def fig07_legs():
    lg = legs()
    out = lg[lg["from_id"] == "O01"].copy()
    fig, axes = plt.subplots(2, 2, figsize=fs((11.2, 7.4)))

    ax = axes[0, 0]
    ax.hist(lg["distance_m"] / 1000, bins=24, color=C_BLUE, edgecolor="white", linewidth=0.6)
    ax.set_xlabel("航段水平距离 / km"); ax.set_ylabel("航段数")
    ax.set_title("(a) 240 条有序航段距离分布", loc="left", fontsize=10.5, fontweight="bold")

    ax = axes[0, 1]
    ax.hist(lg["climb_m"], bins=24, color=C_ORANGE, edgecolor="white", linewidth=0.6,
            alpha=0.85, label="爬升高度 $h^+$")
    ax.hist(lg["descent_m"], bins=24, color=C_TEAL, edgecolor="white", linewidth=0.6,
            alpha=0.75, label="下降高度 $h^-$")
    ax.set_xlabel("高度 / m"); ax.set_ylabel("航段数")
    ax.set_title("(b) 爬升与下降高度分布", loc="left", fontsize=10.5, fontweight="bold")
    ax.legend(fontsize=8)

    ax = axes[1, 0]
    ax.scatter(out["distance_m"] / 1000, out["max_ground_elev_m"], s=56, c=C_PURPLE,
               edgecolor="white", linewidth=0.8, zorder=3)
    for _, r in out.iterrows():
        ax.annotate(r["to_id"], (r["distance_m"] / 1000, r["max_ground_elev_m"]),
                    textcoords="offset points", xytext=(4, 3), fontsize=6.5)
    ax.set_xlabel("O01 → 服务区 水平距离 / km")
    ax.set_ylabel("沿线最高地面高程 / m")
    ax.set_title("(c) 出港航段：距离—沿线最高点", loc="left", fontsize=10.5, fontweight="bold")

    ax = axes[1, 1]
    ax.scatter(out["max_ground_elev_m"], out["cruise_alt_m"], s=56, c=C_GOLD,
               edgecolor="white", linewidth=0.8, zorder=3)
    lo, hi = out["max_ground_elev_m"].min(), out["cruise_alt_m"].max()
    ax.plot([lo, hi], [lo, hi], ls="--", lw=1, color=C_GRAY, label="净空 0 m")
    ax.plot([lo, hi - 50], [lo + 50, hi], ls=":", lw=1.2, color=C_RED,
            label="净空 50 m 设计线")
    ax.set_xlabel("沿线最高地面高程 / m"); ax.set_ylabel("巡航海拔 / m")
    ax.set_title("(d) 巡航海拔 = 最高点 + 50 m", loc="left", fontsize=10.5, fontweight="bold")
    ax.legend(fontsize=8)
    fig.tight_layout()
    save(fig, "fig07_legs")


# ---------------------------------------------------------------- fig08 货箱
def fig08_boxes():
    bx = boxes()
    dm = load_data("demand_summary")
    fig = plt.figure(figsize=fs((11.6, 7.2)))
    gs = fig.add_gridspec(2, 3, hspace=0.42, wspace=0.3)

    ax = fig.add_subplot(gs[0, 0])
    cnt = bx["cargo_type"].value_counts()
    ax.pie(cnt, labels=cnt.index, autopct="%1.0f%%", colors=PALETTE[:4],
           wedgeprops=dict(edgecolor="white", linewidth=1.2), textprops={"fontsize": 8.5})
    ax.set_title("(a) 80 箱物资类型构成", loc="left", fontsize=10.5, fontweight="bold")

    ax = fig.add_subplot(gs[0, 1])
    piv = bx.pivot_table(index="service_id", columns="cargo_type",
                         values="box_id", aggfunc="count").fillna(0)
    piv = piv.reindex(sorted(piv.index))
    bottom = np.zeros(len(piv))
    for i, ct in enumerate(piv.columns):
        ax.bar(piv.index, piv[ct].values, bottom=bottom, color=PALETTE[i],
               edgecolor="white", linewidth=0.6, label=ct)
        bottom += piv[ct].values
    ax.set_xlabel("服务区"); ax.set_ylabel("箱数")
    ax.tick_params(axis="x", rotation=90)
    ax.set_title("(b) 各服务区物资类型构成（堆叠）", loc="left", fontsize=10.5,
                 fontweight="bold")
    ax.legend(fontsize=7.5, ncol=2)

    ax = fig.add_subplot(gs[0, 2])
    sns.scatterplot(x="mass_kg", y="volume_m3", hue="cargo_type", data=bx, ax=ax,
                    palette=PALETTE[:4], s=48, edgecolor="white", linewidth=0.7)
    ax.set_xlabel("单箱质量 / kg"); ax.set_ylabel("单箱体积 / m³")
    ax.set_xlim(bx["mass_kg"].min() - 2, bx["mass_kg"].max() + 3)
    ax.set_ylim(bx["volume_m3"].min() - 0.004, bx["volume_m3"].max() + 0.004)
    ax.set_title("(c) 质量—体积关系（每类取值唯一）", loc="left", fontsize=10.5,
                 fontweight="bold")
    ax.legend(fontsize=7.5, title=None, loc="center right")

    ax = fig.add_subplot(gs[1, 0])
    per = bx.groupby("service_id").size().sort_values(ascending=False)
    sns.barplot(x=per.index, y=per.values, ax=ax, color=C_BLUE,
                edgecolor="#28527a", linewidth=0.6)
    ax.set_xlabel("服务区"); ax.set_ylabel("箱数")
    ax.tick_params(axis="x", rotation=90)
    ax.set_title("(d) 各服务区箱数", loc="left", fontsize=10.5, fontweight="bold")

    ax = fig.add_subplot(gs[1, 1])
    m = bx.groupby("service_id")["mass_kg"].sum().sort_values(ascending=False)
    cum = m.cumsum() / m.sum() * 100
    ax.bar(m.index, m.values, color=C_ORANGE, edgecolor="white", linewidth=0.7,
           label="服务区总质量")
    ax.set_xlabel("服务区（按质量降序）"); ax.set_ylabel("总质量 / kg")
    ax.tick_params(axis="x", rotation=90)
    ax2 = ax.twinx()
    ax2.plot(m.index, cum.values, marker="o", ms=4, lw=1.5, color=C_RED, label="累计占比")
    ax2.axhline(80, ls="--", lw=1, color=C_GRAY)
    ax2.set_ylabel("累计占比 / %"); ax2.set_ylim(0, 105); ax2.grid(False)
    h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=7.5, loc="center right")
    ax.set_title("(e) 需求规模帕累托图", loc="left", fontsize=10.5, fontweight="bold")

    ax = fig.add_subplot(gs[1, 2])
    dl = dm.groupby("service_id")["first_batch_deadline_s"].first() / 60.0
    colors = [C_RED if d <= 60 else (C_ORANGE if d <= 120 else C_TEAL) for d in dl]
    ax.bar(dl.index, dl.values, color=colors, edgecolor="white", linewidth=0.7)
    ax.set_xlabel("服务区"); ax.set_ylabel("首批截止时间 / min")
    ax.tick_params(axis="x", rotation=90)
    ax.set_title("(f) 首批保障截止时间分档", loc="left", fontsize=10.5, fontweight="bold")
    handles = [Rectangle((0, 0), 1, 1, fc=c) for c in (C_RED, C_ORANGE, C_TEAL)]
    ax.legend(handles, ["≤ 60 min", "≤ 120 min", "180 min"], fontsize=8)
    save(fig, "fig08_boxes")


# ---------------------------------------------------------------- fig09 机型雷达
def fig09_uav_radar():
    t = uav_types()
    dims = [("max_payload_kg", "最大载货质量"), ("volume_m3", "装载体积"),
            ("cruise_speed_ms", "巡航速度"), ("range_empty_m", "空载航程"),
            ("range_full_m", "满载航程"), ("energy_kwh", "电池能量")]
    fig, axes = plt.subplots(1, 2, figsize=fs((11.2, 4.8)),
                             gridspec_kw={"width_ratios": [1, 1.1]})

    ax = axes[0]
    ang = np.linspace(0, 2 * np.pi, len(dims), endpoint=False).tolist()
    ang += ang[:1]
    for code, row in t.iterrows():
        vals = [row[c] for c, _ in dims]
        mx = [t[c].max() for c, _ in dims]
        vals = [v / m for v, m in zip(vals, mx)] + [row[dims[0][0]] / t[dims[0][0]].max()]
        ax.plot(ang, vals, lw=1.8, color=TYPE_COLOR[code], label=f"{code} 型")
        ax.fill(ang, vals, color=TYPE_COLOR[code], alpha=0.13)
    ax.set_xticks(ang[:-1]); ax.set_xticklabels([n for _, n in dims], fontsize=8.5)
    ax.set_yticks([0.25, 0.5, 0.75, 1.0]); ax.set_yticklabels(["25%", "50%", "75%", "100%"], fontsize=7.5)
    ax.set_title("(a) 三种机型能力归一化对比", loc="left", fontsize=10.5, fontweight="bold")
    ax.legend(loc="lower right", fontsize=8); ax.grid(alpha=0.35)

    ax = axes[1]
    x = np.arange(len(t))
    w = 0.38
    ax.bar(x - w / 2, t["range_empty_m"] / 1000, w, color=C_BLUE, edgecolor="white",
           linewidth=0.8, label="$L_{g0}$ 空载标准航程")
    ax.bar(x + w / 2, t["range_full_m"] / 1000, w, color=C_ORANGE, edgecolor="white",
           linewidth=0.8, label="$L_{gF}$ 满载标准航程")
    for i, (_, r) in enumerate(t.iterrows()):
        ax.annotate(f"{r['range_empty_m']/1000:.0f}", (i - w / 2, r["range_empty_m"] / 1000),
                    ha="center", va="bottom", fontsize=8)
        ax.annotate(f"{r['range_full_m']/1000:.0f}", (i + w / 2, r["range_full_m"] / 1000),
                    ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x); ax.set_xticklabels([f"{c} 型" for c in t.index])
    ax.set_ylabel("标准航程 / km")
    ax.set_title("(b) 空载 / 满载标准航程差距", loc="left", fontsize=10.5, fontweight="bold")
    ax.legend(fontsize=8, loc="upper right")
    ax.set_ylim(0, 36)
    for i, (_, r) in enumerate(t.iterrows()):
        d = (r["range_empty_m"] - r["range_full_m"]) / r["range_empty_m"] * 100
        ax.annotate(f"衰减 {d:.0f}%", (i, 1.2), ha="center", va="bottom", fontsize=8.5,
                    color=C_RED, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.25", fc="#fdf2f2", ec=C_RED, lw=0.8))
    fig.tight_layout()
    save(fig, "fig09_uav_radar")


# ---------------------------------------------------------------- fig10 链路
def fig10_link():
    lt = load("t_link_thresholds")
    fig, axes = plt.subplots(1, 2, figsize=fs((11.2, 4.6)))

    ax = axes[0]
    names = ["直连\n(运输机$\\leftrightarrow$G01)", "中继接入\n(运输机$\\leftrightarrow$中继)",
             "中继回传\n(中继$\\leftrightarrow$G01)"]
    x = np.arange(3); w = 0.38
    ax.bar(x - w / 2, lt["无遮挡可达(km)"], w, color=C_BLUE, edgecolor="white",
           linewidth=0.8, label="无遮挡可达距离")
    ax.bar(x + w / 2, lt["含遮挡可达(km)"], w, color=C_RED, edgecolor="white",
           linewidth=0.8, label="含 10 dB 遮挡附加损耗")
    for i in range(3):
        ax.annotate(f"{lt['无遮挡可达(km)'][i]:.2f}", (i - w / 2, lt["无遮挡可达(km)"][i]),
                    ha="center", va="bottom", fontsize=8)
        ax.annotate(f"{lt['含遮挡可达(km)'][i]:.2f}", (i + w / 2, lt["含遮挡可达(km)"][i]),
                    ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x); ax.set_xticklabels(names, fontsize=8.5)
    ax.set_ylabel("可达距离 / km")
    ax.set_title("(a) 三条链路的可达距离", loc="left", fontsize=10.5, fontweight="bold")
    ax.legend(fontsize=8)

    ax = axes[1]
    lab = ["直连", "中继接入", "中继回传"]
    val = lt["双向门限(dB)"].values
    b = ax.barh(lab, val, color=[C_BLUE, C_RED, C_TEAL], edgecolor="white", linewidth=0.9)
    for r, v in zip(b, val):
        ax.annotate(f"{v:.0f} dB", (v, r.get_y() + r.get_height() / 2),
                    xytext=(5, 0), textcoords="offset points", va="center", fontsize=9)
    ax.set_xlim(100, 136); ax.set_xlabel("双向门限 $L_{max}$ / dB")
    ax.set_title("(b) 双向门限取两方向较小值", loc="left", fontsize=10.5, fontweight="bold")
    ax.annotate("接入段最弱\n（比直连低 6 dB）", xy=(116, 1), xytext=(122, 1.42),
                fontsize=8.5, color=C_RED,
                arrowprops=dict(arrowstyle="->", color=C_RED, lw=1.2))
    fig.tight_layout()
    save(fig, "fig10_link")


# ---------------------------------------------------------------- fig11 载荷航程
def fig11_payload_range():
    t = uav_types()
    q = np.linspace(0, 1, 200)
    fig, axes = plt.subplots(1, 2, figsize=fs((11.2, 4.5)))

    ax = axes[0]
    for code, r in t.iterrows():
        qq = q * r["max_payload_kg"]
        L = r["range_empty_m"] - (r["range_empty_m"] - r["range_full_m"]) * q ** 1.5
        ax.plot(qq, L / 1000, lw=2, color=TYPE_COLOR[code], label=f"{code} 型")
    ax.set_xlabel("载荷 $q$ / kg"); ax.set_ylabel("等效航程 $L_{g}(q)$ / km")
    ax.set_title("(a) 载荷—航程关系 $L_{g}(q)=L_{g0}-(L_{g0}-L_{gF})(q/Q_{g})^{3/2}$",
                 loc="left", fontsize=10, fontweight="bold")
    ax.legend(fontsize=8.5)

    ax = axes[1]
    for code, r in t.iterrows():
        qq = q * r["max_payload_kg"]
        L = r["range_empty_m"] - (r["range_empty_m"] - r["range_full_m"]) * q ** 1.5
        e = (1 - r["reserve_ratio"]) * r["energy_kwh"] / (L / 1000)
        ax.plot(qq, e, lw=2, color=TYPE_COLOR[code], label=f"{code} 型")
    ax.set_xlabel("载荷 $q$ / kg")
    ax.set_ylabel("单位距离能耗 / ($\\mathrm{kWh\\cdot km^{-1}}$)")
    ax.set_title("(b) 单位距离能耗随载荷上升（凸性）", loc="left", fontsize=10.5,
                 fontweight="bold")
    ax.legend(fontsize=8.5)
    ax.annotate("指数 $3/2>1$ $\\Rightarrow$ 曲线下凸\n载荷越大，边际能耗越高", xy=(0.42, 0.72),
                xycoords="axes fraction", fontsize=8.5,
                bbox=dict(boxstyle="round,pad=0.4", fc="#f7f7f7", ec="#bbbbbb"))
    fig.tight_layout()
    save(fig, "fig11_payload_range")


# ---------------------------------------------------------------- fig12 飞行剖面
def fig12_profile():
    t = uav_types()
    lg = legs()
    o = lg[(lg.from_id == "O01") & (lg.to_id == "S008")].iloc[0]
    r = t.loc["C"]
    h_op_o = o["op_from_m"]; h_op_s = o["op_to_m"]; hc = o["cruise_alt_m"]
    d = o["distance_m"]
    tc = hc - h_op_o; td = hc - h_op_s
    t_up = tc / r["climb_speed_ms"]; t_cr = d / r["cruise_speed_ms"]
    t_dn = td / r["descent_speed_ms"]

    fig, axes = plt.subplots(1, 2, figsize=fs((11.2, 4.4)),
                             gridspec_kw={"width_ratios": [1.35, 1]})
    ax = axes[0]
    xs = [0, 0, t_up, t_up + t_cr, t_up + t_cr + t_dn, t_up + t_cr + t_dn]
    ys = [h_op_o, hc, hc, hc, h_op_s, h_op_s]
    ax.plot([0, t_up], [h_op_o, hc], lw=2.2, color=C_RED, label="爬升 $h^+$")
    ax.plot([t_up, t_up + t_cr], [hc, hc], lw=2.2, color=C_BLUE, label="巡航 $d$")
    ax.plot([t_up + t_cr, t_up + t_cr + t_dn], [hc, h_op_s], lw=2.2, color=C_TEAL,
            label="下降 $h^-$（不单独计能耗）")
    ax.axhline(o["max_ground_elev_m"], ls="--", lw=1.1, color=C_GRAY,
               label=f"沿线最高地面 {o['max_ground_elev_m']:.0f} m")
    ax.axhline(hc, ls=":", lw=1.0, color=C_GOLD)
    ax.annotate("巡航海拔 = 最高点 + 50 m", xy=(t_up + t_cr * 0.5, hc), xytext=(t_up * 0.5, hc + 32),
                fontsize=8.5, arrowprops=dict(arrowstyle="->", lw=1, color=C_GOLD))
    ax.fill_between([0, t_up + t_cr + t_dn], 0, o["max_ground_elev_m"], color="#e8e2d5", alpha=0.55)
    ax.set_xlabel("时间 / s"); ax.set_ylabel("海拔 / m")
    ax.set_title("(a) O01 → S008 飞行剖面（C 型，最远航段）", loc="left", fontsize=10.5,
                 fontweight="bold")
    ax.legend(fontsize=8, loc="lower right")

    ax = axes[1]
    q = 60.0
    L = r["range_empty_m"] - (r["range_empty_m"] - r["range_full_m"]) * (q / r["max_payload_kg"]) ** 1.5
    e_hor = d / L * r["energy_kwh"]
    e_up = (r["empty_mass_kg"] + q) * G * tc / r["climb_efficiency"] / J_KWH
    e_dn = 0.0
    parts = [("水平巡航", e_hor, C_BLUE), ("爬升附加", e_up, C_RED), ("下降附加", e_dn, C_TEAL)]
    b = ax.barh([p[0] for p in parts], [p[1] for p in parts],
                color=[p[2] for p in parts], edgecolor="white", linewidth=0.9)
    for rr, (_, v, _) in zip(b, parts):
        ax.annotate(f"{v:.4f} kWh", (v, rr.get_y() + rr.get_height() / 2),
                    xytext=(5, 0), textcoords="offset points", va="center", fontsize=8.5)
    ax.set_xlim(0, max(e_hor, e_up) * 1.42)
    ax.set_xlabel("能耗 / kWh")
    ax.set_title("(b) 去程能耗构成（载 60 kg）", loc="left", fontsize=10.5, fontweight="bold")
    fig.tight_layout()
    save(fig, "fig12_profile")


def main():
    setup()
    print("fig_common:")
    for f in (fig06_nodes, fig07_legs, fig08_boxes, fig09_uav_radar,
              fig10_link, fig11_payload_range, fig12_profile):
        f()


if __name__ == "__main__":
    main()
