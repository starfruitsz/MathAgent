# -*- coding: utf-8 -*-
"""问题三图（fig26–fig31）。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.patches import Patch

from plotstyle import (fs, setup, save, load, load_data, metrics, nodes, PALETTE, TYPE_COLOR,
                       C_BLUE, C_ORANGE, C_TEAL, C_PURPLE, C_RED, C_GRAY, C_GOLD, SEQ)

DIAG = load("t_q3_diagnosis").rename(columns={
    "架次编号": "sid", "机型": "g", "服务区": "svc", "中断占比": "outage",
    "直连可达比例": "direct", "需中继": "need", "航段长": "nleg", "采样点数": "ns"})
SIT = load("t_q3_siting").rename(columns={
    "架次编号": "sid", "中断占比": "outage", "悬停经度": "lon", "悬停纬度": "lat",
    "悬停海拔m": "alt", "离地m": "agl", "保障能耗kWh": "e", "说明": "note"})
RELAY = load("t_q3_relay_sorties").rename(columns={
    "中继架次编号": "rid", "中继无人机编号": "uav", "开始时刻（s）": "t0",
    "建链完成时刻（s）": "tlink", "服务结束时刻（s）": "tend", "返回O01时刻（s）": "t1",
    "架次能耗（kWh）": "kwh", "悬停海拔（m）": "alt"})
TRANSPORT = load("q3_运输架次")
ND = nodes()


def _xy(lon, lat):
    o = ND[ND["kind"] == "center"].iloc[0]
    return ((np.asarray(lon) - o["lon"]) * 111320 * np.cos(np.radians(o["lat"])) / 1000,
            (np.asarray(lat) - o["lat"]) * 110540 / 1000)


# ---------------------------------------------------------------- fig26 诊断
def fig26_diagnosis():
    d = DIAG.copy()
    fig, axes = plt.subplots(1, 3, figsize=fs((12.8, 4.2)))

    ax = axes[0]
    d2 = d.sort_values("outage", ascending=False)
    colors = [C_RED if v > 0 else C_TEAL for v in d2["outage"]]
    ax.barh(d2["sid"], d2["outage"] * 100, color=colors, edgecolor="white", linewidth=0.6)
    ax.axvline(0.1, ls="--", lw=1, color=C_GRAY)
    ax.set_xlabel("直连中断时间占比 / %"); ax.set_ylabel("运输架次")
    ax.tick_params(axis="y", labelsize=6.5)
    ax.set_title("(a) 逐架次直连中断占比", loc="left", fontsize=10.5, fontweight="bold")

    ax = axes[1]
    ax.scatter(d["outage"] * 100, d["ns"], s=60, c=[TYPE_COLOR[g] for g in d["g"]],
               edgecolor="white", linewidth=0.9, zorder=3)
    ax.set_xlabel("直连中断时间占比 / %"); ax.set_ylabel("轨迹采样点数")
    ax.set_title("(b) 中断占比与航段规模", loc="left", fontsize=10.5, fontweight="bold")
    ax.legend(handles=[Patch(color=c, label=f"{t} 型") for t, c in TYPE_COLOR.items()],
              fontsize=8)

    ax = axes[2]
    need = int(d["need"].sum()); tot = len(d)
    ax.pie([need, tot - need], labels=["需中继保障", "直连全程可用"],
           colors=[C_RED, C_TEAL], autopct=lambda p: f"{p:.1f}%\n({round(p*tot/100)} 架次)",
           wedgeprops=dict(edgecolor="white", linewidth=1.4), textprops={"fontsize": 9},
           startangle=90)
    ax.set_title(f"(c) {tot} 个架次的通信状态", loc="left", fontsize=10.5, fontweight="bold")
    fig.tight_layout()
    save(fig, "fig26_q3_diagnosis")


# ---------------------------------------------------------------- fig27 中继地图
def fig27_relay_map():
    s = SIT.copy()
    fig, axes = plt.subplots(1, 2, figsize=fs((12.2, 5.0)),
                             gridspec_kw={"width_ratios": [1.15, 1]})

    ax = axes[0]
    xs, ys = _xy(ND[ND["kind"] == "service"]["lon"], ND[ND["kind"] == "service"]["lat"])
    ax.scatter(xs, ys, s=90, c=C_BLUE, marker="s", edgecolor="white", linewidth=0.9,
               zorder=3, label="服务区")
    for _, r in ND[ND["kind"] == "service"].iterrows():
        px, py = _xy(r["lon"], r["lat"])
        ax.annotate(r["id"], (px, py), textcoords="offset points", xytext=(5, 4), fontsize=7)
    ox, oy = _xy(ND[ND["kind"] == "center"]["lon"], ND[ND["kind"] == "center"]["lat"])
    ax.scatter(ox, oy, marker="*", s=380, c=C_RED, edgecolor="white", linewidth=1.0,
               zorder=5, label="调度中心 O01 / 网关 G01")
    hx, hy = _xy(s["lon"], s["lat"])
    sc = ax.scatter(hx, hy, s=110, c=s["alt"], cmap=SEQ, marker="^",
                    edgecolor="white", linewidth=0.9, zorder=4,
                    label="中继悬停点（颜色=悬停海拔）")
    cb = fig.colorbar(sc, ax=ax, pad=0.02); cb.set_label("悬停海拔 / m")
    ax.set_xlabel("东向距离 / km"); ax.set_ylabel("北向距离 / km")
    ax.set_aspect("equal")
    ax.set_title("(a) 中继悬停点空间分布", loc="left", fontsize=10.5, fontweight="bold")
    ax.legend(fontsize=8, loc="lower right")

    ax = axes[1]
    ax.scatter(s["outage"] * 100, s["e"], s=70, c=s["alt"], cmap=SEQ,
               edgecolor="white", linewidth=0.9, zorder=3)
    cb = fig.colorbar(ax.collections[0], ax=ax, pad=0.02); cb.set_label("悬停海拔 / m")
    ax.set_xlabel("该架次直连中断占比 / %"); ax.set_ylabel("中继保障能耗 / kWh")
    ax.set_title("(b) 中断越严重，中继能耗越高", loc="left", fontsize=10.5, fontweight="bold")
    z = np.polyfit(s["outage"] * 100, s["e"], 1)
    xx = np.linspace((s["outage"] * 100).min(), (s["outage"] * 100).max(), 50)
    ax.plot(xx, np.polyval(z, xx), ls="--", lw=1.4, color=C_RED,
            label=f"线性趋势 (斜率 {z[0]:.4f})")
    ax.legend(fontsize=8.5)
    fig.tight_layout()
    save(fig, "fig27_q3_relay_map")


# ---------------------------------------------------------------- fig28 选址特征
def fig28_siting():
    s = SIT.copy()
    fig, axes = plt.subplots(1, 3, figsize=fs((12.6, 4.0)))

    ax = axes[0]
    ax.hist(s["agl"], bins=14, color=C_PURPLE, edgecolor="white", linewidth=0.7)
    ax.axvline(300, ls="--", lw=1.4, color=C_RED, label="离地上限 300 m")
    ax.set_xlabel("悬停离地高度 / m"); ax.set_ylabel("中继架次数")
    ax.set_title("(a) 悬停离地高度", loc="left", fontsize=10.5, fontweight="bold")
    ax.legend(fontsize=8.5)

    ax = axes[1]
    ax.hist(s["e"], bins=14, color=C_TEAL, edgecolor="white", linewidth=0.7)
    ax.axvline(s["e"].mean(), ls="--", lw=1.4, color=C_RED,
               label=f"均值 {s['e'].mean():.3f} kWh")
    ax.set_xlabel("保障能耗 / kWh"); ax.set_ylabel("中继架次数")
    ax.set_title("(b) 单架次保障能耗分布", loc="left", fontsize=10.5, fontweight="bold")
    ax.legend(fontsize=8.5)

    ax = axes[2]
    dur = (s["服务窗口止"] - s["服务窗口起"]) / 60
    ax.scatter(s["outage"] * 100, dur, s=70, c=C_ORANGE, edgecolor="white",
               linewidth=0.9, zorder=3)
    ax.set_xlabel("直连中断占比 / %"); ax.set_ylabel("中继服务时长 / min")
    ax.set_title("(c) 服务时长随中断占比增长", loc="left", fontsize=10.5, fontweight="bold")
    fig.tight_layout()
    save(fig, "fig28_q3_siting")


# ---------------------------------------------------------------- fig29 联合甘特
def fig29_joint_gantt():
    t = load("q3_运输架次").rename(columns={
        "架次编号": "sid", "无人机编号": "uav", "机型编号": "g",
        "开始时刻（s）": "t0", "返回O01时刻（s）": "t1", "访问服务区顺序": "stops"})
    r = RELAY.copy()
    fig, ax = plt.subplots(figsize=fs((12.2, 6.4)))

    for i, x in enumerate(t.sort_values("t0").itertuples()):
        ax.barh(i + 0.0, x.t1 - x.t0, left=x.t0, height=0.42, color=C_BLUE,
                edgecolor="white", linewidth=0.5, zorder=3)
    off = len(t) + 2
    for i, x in enumerate(r.sort_values("t0").itertuples()):
        ax.barh(off + i, x.tend - x.tlink, left=x.tlink, height=0.42, color=C_ORANGE,
                edgecolor="white", linewidth=0.5, zorder=3)
        ax.barh(off + i, x.tlink - x.t0, left=x.t0, height=0.42, color="#f3ddc4",
                edgecolor="white", linewidth=0.5, zorder=3)
    ax.axhline(len(t) + 1, color="#999999", lw=1.0, ls="--")
    ax.set_xlabel("时刻 / s"); ax.set_ylabel("架次")
    ax.set_yticks([0, len(t) - 1, off, off + len(r) - 1])
    ax.set_yticklabels(["运输 T001", f"运输 T{len(t):03d}", "中继 RT01",
                        f"中继 RT{len(r):02d}"], fontsize=8.5)
    ax.set_title("问题三运输与中继联合调度时间线（上：运输 35 架次；下：中继 30 架次）",
                 loc="left", fontsize=11, fontweight="bold")
    ax.legend(handles=[Patch(color=C_BLUE, label="运输架次飞行+投送"),
                       Patch(color="#f3ddc4", label="中继飞往悬停点+建链"),
                       Patch(color=C_ORANGE, label="中继悬停保障")],
              loc="lower right", fontsize=8.5)
    ax.grid(axis="y", alpha=0.15)
    fig.tight_layout()
    save(fig, "fig29_q3_joint_gantt")


# ---------------------------------------------------------------- fig30 桑基
def fig30_sankey():
    try:
        import plotly.graph_objects as go
    except Exception as e:
        print(f"    (skip fig30: plotly 不可用 {e})")
        return
    n_direct = int((~DIAG["need"]).sum())
    n_relay = int(DIAG["need"].sum())
    r01 = int((RELAY["uav"] == "R01").sum())
    r02 = int((RELAY["uav"] == "R02").sum())

    labels = ["直连全程可用", "需中继保障", "G01 网关直连", "中继 R01", "中继 R02"]
    fig = go.Figure(go.Sankey(
        arrangement="snap",
        node=dict(label=labels, pad=18, thickness=20,
                  color=[C_TEAL, C_RED, C_TEAL, C_ORANGE, C_PURPLE],
                  line=dict(color="white", width=0.8)),
        link=dict(source=[0, 1, 1], target=[2, 3, 4],
                  value=[n_direct, r01, r02],
                  color=["rgba(79,157,143,0.45)", "rgba(224,138,60,0.45)",
                         "rgba(155,111,176,0.45)"])))
    fig.update_layout(font=dict(family="SimSun, Microsoft YaHei", size=14, color="#262626"),
                      paper_bgcolor="white", width=1000, height=560,
                      margin=dict(l=20, r=20, t=50, b=20),
                      title=dict(text="问题三通信保障方式流向：35 个运输架次的保障资源分配",
                                 font=dict(size=15)))
    from plotstyle import FIG as FIGDIR
    out = FIGDIR / "fig30_q3_sankey.png"
    fig.write_image(str(out), scale=3)
    print(f"  ✓ fig30_q3_sankey.png")


# ---------------------------------------------------------------- fig31 覆盖质量
def fig31_coverage():
    d = DIAG.copy()
    fig, axes = plt.subplots(1, 2, figsize=fs((11.6, 4.3)))

    ax = axes[0]
    order = d.sort_values("outage")["sid"]
    ax.plot(range(len(d)), d.sort_values("outage")["direct"].values * 100,
            marker="o", ms=5, lw=1.6, color=C_BLUE, label="直连可达比例")
    ax.plot(range(len(d)), (1 - d.sort_values("outage")["outage"]).values * 100,
            marker="s", ms=4, lw=1.2, ls="--", color=C_GRAY, label="（对照）")
    ax.axhline(100, ls=":", lw=1, color=C_TEAL)
    ax.set_xlabel("运输架次（按中断占比升序）"); ax.set_ylabel("直连可达比例 / %")
    ax.set_title("(a) 直连可达比例排序", loc="left", fontsize=10.5, fontweight="bold")
    ax.legend(fontsize=8)

    ax = axes[1]
    sns.histplot(d["outage"] * 100, bins=12, kde=True, ax=ax, color=C_ORANGE,
                 edgecolor="white", linewidth=0.7)
    ax.axvline(d["outage"].mean() * 100, ls="--", lw=1.5, color=C_RED,
               label=f"均值 {d['outage'].mean()*100:.1f}%")
    ax.set_xlabel("直连中断时间占比 / %"); ax.set_ylabel("架次数")
    ax.set_title("(b) 中断占比分布（核密度）", loc="left", fontsize=10.5, fontweight="bold")
    ax.legend(fontsize=8.5)
    fig.tight_layout()
    save(fig, "fig31_q3_coverage")


def main():
    setup()
    print("fig_q3:")
    for f in (fig26_diagnosis, fig27_relay_map, fig28_siting, fig29_joint_gantt,
              fig30_sankey, fig31_coverage):
        try:
            f()
        except Exception as e:
            print(f"    ✗ {f.__name__}: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
