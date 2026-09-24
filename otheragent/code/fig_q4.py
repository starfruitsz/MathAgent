# -*- coding: utf-8 -*-
"""问题四图（fig32–fig35）。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

from plotstyle import (fs, setup, save, load, nodes, PALETTE, TYPE_COLOR,
                       C_BLUE, C_ORANGE, C_TEAL, C_PURPLE, C_RED, C_GRAY, C_GOLD, SEQ)

CMP = load("t_q4_compare")
GAP = load("t_q4_gap")
GRP = load("t_q4_group")
BR = load("t_q4_bridge")
ND = nodes()


def _norm(s: pd.Series) -> pd.Series:
    """Q3 的交付表用 ASCII '->' 分隔，Q2 用 Unicode '→'；统一成后者。"""
    return s.astype(str).str.replace("->", "→", regex=False)


TR = load("q3_运输架次").rename(columns={"架次编号": "sid", "访问服务区顺序": "stops"})
TR["stops"] = _norm(TR["stops"])
BR["服务区顺序"] = _norm(BR["服务区顺序"])


def _xy(lon, lat):
    o = ND[ND["kind"] == "center"].iloc[0]
    return ((np.asarray(lon) - o["lon"]) * 111320 * np.cos(np.radians(o["lat"])) / 1000,
            (np.asarray(lat) - o["lat"]) * 110540 / 1000)


# ---------------------------------------------------------------- fig32 关联图
def fig32_graph():
    import networkx as nx
    serv = sorted(ND[ND["kind"] == "service"]["id"])
    G = nx.Graph()
    G.add_nodes_from(serv)
    multi = TR[TR["stops"].str.contains("→")]
    for _, r in multi.iterrows():
        st = r["stops"].split("→")
        for a, b in zip(st[:-1], st[1:]):
            if G.has_edge(a, b):
                G[a][b]["w"] += 1
            else:
                G.add_edge(a, b, w=1)
    bridge = set()
    for _, r in BR.iterrows():
        st = r["服务区顺序"].split("→")
        bridge.add(frozenset(st))

    pos_nd = ND.set_index("id")
    xy = {s: _xy(pos_nd.loc[s, "lon"], pos_nd.loc[s, "lat"]) for s in serv}
    pos = {s: (float(xy[s][0]), float(xy[s][1])) for s in serv}

    fig, axes = plt.subplots(1, 2, figsize=fs((12.2, 5.4)))

    ax = axes[0]
    deg = dict(G.degree())
    nx.draw_networkx_edges(G, pos, ax=ax, width=[G[a][b]["w"] * 1.5 for a, b in G.edges()],
                           edge_color=C_GRAY, alpha=0.65)
    nd_colors = [C_RED if deg[s] >= 5 else (C_ORANGE if deg[s] >= 3 else C_BLUE) for s in G.nodes()]
    nx.draw_networkx_nodes(G, pos, ax=ax, node_size=[260 + deg[s] * 130 for s in G.nodes()],
                           node_color=nd_colors, edgecolors="white", linewidths=1.4)
    nx.draw_networkx_labels(G, pos, ax=ax, font_size=7.5,
                            font_family="SimSun")
    ax.set_aspect("equal"); ax.axis("off")
    ax.set_title(f"(a) 架次—服务区关联图：1 个连通分量（15 顶点 / {G.number_of_edges()} 边）",
                 loc="left", fontsize=10.5, fontweight="bold")
    from matplotlib.lines import Line2D
    ax.legend(handles=[Line2D([], [], marker="o", ls="", ms=9, mfc=C_RED, mec="white",
                              label="度数 ≥ 5"),
                       Line2D([], [], marker="o", ls="", ms=9, mfc=C_ORANGE, mec="white",
                              label="度数 3–4"),
                       Line2D([], [], marker="o", ls="", ms=9, mfc=C_BLUE, mec="white",
                              label="度数 ≤ 2")],
              fontsize=8, loc="lower left")

    ax = axes[1]
    degs = pd.Series(deg).sort_values(ascending=False)
    ax.bar(degs.index, degs.values, color=[C_RED if v >= 5 else (C_ORANGE if v >= 3 else C_BLUE)
                                           for v in degs.values],
           edgecolor="white", linewidth=0.7)
    ax.set_xlabel("服务区"); ax.set_ylabel("关联架次数（度）")
    ax.tick_params(axis="x", rotation=90)
    ax.set_title("(b) 各服务区的关联度", loc="left", fontsize=10.5, fontweight="bold")
    ax.annotate("21 个多点架次把 15 个服务区\n串成单一连通分量\n$\\Rightarrow$ 不存在合法的 2/3 组分区",
                (0.40, 0.80), xycoords="axes fraction", fontsize=9, color=C_RED,
                bbox=dict(boxstyle="round,pad=0.45", fc="#fdf2f2", ec=C_RED, lw=1.0))
    fig.tight_layout()
    save(fig, "fig32_q4_graph")


# ---------------------------------------------------------------- fig33 方案对比
def fig33_compare():
    c = CMP.copy()
    fig = plt.figure(figsize=fs((12.4, 4.8)))
    gs = fig.add_gridspec(1, 3, width_ratios=[1, 1, 1.05], wspace=0.32)

    ax = fig.add_subplot(gs[0, 0])
    labels = ["运输无人机", "共享电池", "中继无人机", "中继能源组件"]
    cols = ["运输无人机", "共享电池", "中继无人机", "中继能源组件"]
    x = np.arange(len(labels)); w = 0.26
    for i, (_, r) in enumerate(c.iterrows()):
        ax.bar(x + (i - 1) * w, [r[k] for k in cols], w, label=r["方案"],
               color=[C_BLUE, C_ORANGE, C_TEAL][i], edgecolor="white", linewidth=0.7)
    ax.set_xticks(x); ax.set_xticklabels(labels, rotation=18, fontsize=8)
    ax.set_ylabel("资源需求")
    ax.set_title("(a) 四类资源的组内需求", loc="left", fontsize=10.5, fontweight="bold")
    ax.legend(fontsize=8)

    ax = fig.add_subplot(gs[0, 1])
    ax.bar(c["方案"], c["资源总量"], color=[C_BLUE, C_ORANGE, C_TEAL],
           edgecolor="white", linewidth=0.9)
    for i, v in enumerate(c["资源总量"]):
        ax.annotate(str(int(v)), (i, v), ha="center", va="bottom", fontsize=11,
                    fontweight="bold")
    ax.set_ylabel("资源总量（台·组）"); ax.set_ylim(0, c["资源总量"].max() * 1.25)
    ax.set_title("(b) 分区越多，资源需求越大", loc="left", fontsize=10.5, fontweight="bold")
    ax.tick_params(axis="x", labelsize=8)

    ax = fig.add_subplot(gs[0, 2])
    feat = ["资源总量", "组间不均衡"]
    norms = c[feat] / c[feat].max()
    ang = np.linspace(0, 2 * np.pi, len(feat), endpoint=False).tolist(); ang += ang[:1]
    for i, (_, r) in enumerate(c.iterrows()):
        v = norms.iloc[i].tolist(); v += v[:1]
        ax.plot(ang, v, lw=2, marker="o", ms=5, color=[C_BLUE, C_ORANGE, C_TEAL][i],
                label=r["方案"])
        ax.fill(ang, v, color=[C_BLUE, C_ORANGE, C_TEAL][i], alpha=0.12)
    ax.set_xticks(ang[:-1]); ax.set_xticklabels(feat, fontsize=9)
    ax.set_yticks([0.25, 0.5, 0.75, 1.0]); ax.set_yticklabels(["25%", "50%", "75%", "100%"],
                                                              fontsize=7.5)
    ax.set_title("(c) 归一化综合对比", loc="left", fontsize=10.5, fontweight="bold")
    ax.legend(fontsize=8, loc="lower right")
    save(fig, "fig33_q4_compare")


# ---------------------------------------------------------------- fig34 逐组明细
def fig34_group():
    g = GRP.copy()
    fig, axes = plt.subplots(1, 2, figsize=fs((12.0, 4.4)),
                             gridspec_kw={"width_ratios": [1.15, 1]})

    ax = axes[0]
    res = ["A机", "B机", "C机", "A电池", "B电池", "C电池", "中继机", "中继组件"]
    k1 = g[g["方案"].str.contains("K=1")]
    x = np.arange(len(res))
    ax.bar(x, k1[res].values[0] if len(k1) else np.zeros(len(res)),
           color=PALETTE[:len(res)], edgecolor="white", linewidth=0.8)
    if len(k1):
        for i, v in enumerate(k1[res].values[0]):
            ax.annotate(str(int(v)), (i, v), ha="center", va="bottom", fontsize=9)
    ax.set_xticks(x); ax.set_xticklabels(res, rotation=35, fontsize=8.5)
    ax.set_ylabel("需求数量")
    ax.set_ylim(0, max(k1[res].values[0].max() if len(k1) else 1, 1) * 1.3)
    ax.set_title("(a) K=1（唯一合法分区）的资源配置", loc="left", fontsize=10.5,
                 fontweight="bold")

    ax = axes[1]
    ax.bar(g["任务组"], g["工作量h"], color=C_PURPLE, edgecolor="white", linewidth=0.8,
           label="组内工作量")
    ax.set_xlabel("任务组"); ax.set_ylabel("工作量 / h")
    ax.tick_params(axis="x", rotation=90, labelsize=6.5)
    ax.set_title("(b) 逐组工作量与均衡性", loc="left", fontsize=10.5, fontweight="bold")
    ax.legend(fontsize=8)
    fig.tight_layout()
    save(fig, "fig34_q4_group")


# ---------------------------------------------------------------- fig35 缺口
def fig35_gap():
    gp = GAP.copy()
    fig, axes = plt.subplots(1, 2, figsize=fs((12.0, 4.4)),
                             gridspec_kw={"width_ratios": [1.2, 1]})

    ax = axes[0]
    plans = gp["方案"].unique()
    res = gp["资源"].unique()
    x = np.arange(len(res)); w = 0.8 / len(plans)
    for i, p in enumerate(plans):
        sub = gp[gp["方案"] == p].set_index("资源").reindex(res)
        vals = sub["缺口"].fillna(0).values
        ax.bar(x + i * w - 0.4 + w / 2, vals, w, label=p,
               color=[C_BLUE, C_ORANGE, C_TEAL][i % 3], edgecolor="white", linewidth=0.6)
    ax.axhline(0, lw=1.1, color="#333333")
    ax.set_xticks(x); ax.set_xticklabels(res, rotation=25, fontsize=8)
    ax.set_ylabel("资源缺口（需求 $-$ 库存）")
    ax.set_title("(a) 逐方案逐类资源缺口", loc="left", fontsize=10.5, fontweight="bold")
    ax.legend(fontsize=8)

    ax = axes[1]
    k1 = gp[gp["方案"].str.contains("K=1")]
    if len(k1):
        y = np.arange(len(k1))
        ax.barh(y, k1["库存"], color="#e6e6e6", edgecolor=C_GRAY, linewidth=0.8,
                label="现有库存")
        ax.barh(y, k1["需求"], height=0.5, color=C_BLUE, edgecolor="white",
                linewidth=0.7, label="组内需求")
        for i, r in enumerate(k1.itertuples()):
            if r.缺口 > 0:
                ax.annotate(f"缺 {int(r.缺口)}", (r.需求, i), xytext=(6, 0),
                            textcoords="offset points", va="center", fontsize=9,
                            color=C_RED, fontweight="bold")
        ax.set_yticks(y); ax.set_yticklabels(k1["资源"], fontsize=8.5)
        ax.set_xlabel("数量")
        ax.set_title("(b) K=1 唯一缺口：1 组 B 型备用电池", loc="left", fontsize=10.5,
                     fontweight="bold")
        ax.legend(fontsize=8.5)
    fig.tight_layout()
    save(fig, "fig35_q4_gap")


def main():
    setup()
    print("fig_q4:")
    for f in (fig32_graph, fig33_compare, fig34_group, fig35_gap):
        try:
            f()
        except Exception as e:
            print(f"    ✗ {f.__name__}: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
