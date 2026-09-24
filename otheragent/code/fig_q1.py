# -*- coding: utf-8 -*-
"""问题一图（fig13–fig19）。"""
from __future__ import annotations

import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.patches import Patch

from plotstyle import (fs, setup, save, load, metrics, PALETTE, TYPE_COLOR, BIND_COLOR,
                       C_BLUE, C_ORANGE, C_TEAL, C_PURPLE, C_RED, C_GRAY, C_GOLD,
                       SEQ, DIV)


# ---------------------------------------------------------------- fig13 载荷热力图
def fig13_payload_heatmap():
    p = load("t_q1_payload")
    piv = p.pivot(index="机型编号", columns="服务区编号", values="最大安全载荷（kg）")
    bind = p.pivot(index="机型编号", columns="服务区编号", values="生效约束")
    fig, axes = plt.subplots(1, 2, figsize=fs((12.4, 3.9)),
                             gridspec_kw={"width_ratios": [1.5, 1]})

    ax = axes[0]
    sns.heatmap(piv, annot=True, fmt=".1f", cmap=SEQ, ax=ax, linewidths=0.6,
                linecolor="white", cbar_kws={"label": "最大安全载荷 / kg"}, annot_kws={"fontsize": 7})
    ax.set_xlabel("服务区"); ax.set_ylabel("机型")
    ax.set_title("(a) 3 机型 × 15 服务区最大安全载荷", loc="left", fontsize=10.5,
                 fontweight="bold")

    ax = axes[1]
    coded = bind.replace({"结构上限": 0, "能量": 1, "体积": 2}).astype(float)
    sns.heatmap(coded, annot=bind, fmt="", cmap=plt.get_cmap("Set2", 3), ax=ax,
                linewidths=0.6, linecolor="white", cbar=False, annot_kws={"fontsize": 7})
    ax.set_xlabel("服务区"); ax.set_ylabel("机型")
    ax.set_title("(b) 实际生效的约束类型", loc="left", fontsize=10.5, fontweight="bold")
    fig.tight_layout()
    save(fig, "fig13_q1_payload_heatmap")


# ---------------------------------------------------------------- fig14 生效约束
def fig14_binding():
    p = load("t_q1_payload")
    cnt = p.groupby(["机型编号", "生效约束"]).size().unstack(fill_value=0)
    order = ["结构上限", "能量", "体积"]
    cnt = cnt[[c for c in order if c in cnt.columns]]
    fig, axes = plt.subplots(1, 2, figsize=fs((11.0, 4.2)))

    ax = axes[0]
    bottom = np.zeros(len(cnt))
    for c in cnt.columns:
        ax.bar(cnt.index, cnt[c].values, bottom=bottom, color=BIND_COLOR[c],
               edgecolor="white", linewidth=0.8, label=c)
        for i, v in enumerate(cnt[c].values):
            if v > 0:
                ax.annotate(f"{int(v)}", (i, bottom[i] + v / 2), ha="center", va="center",
                            fontsize=9, color="white", fontweight="bold")
        bottom += cnt[c].values
    ax.set_xlabel("机型"); ax.set_ylabel("服务区数")
    ax.set_ylim(0, 16)
    ax.set_title("(a) 各机型受何种约束主导", loc="left", fontsize=10.5, fontweight="bold")
    ax.legend(fontsize=8.5)
    ax.annotate("A 型 15/15 全部受结构载重约束\n能量从未成为紧约束", xy=(0, 15), xytext=(0.35, 12.4),
                fontsize=8.5, arrowprops=dict(arrowstyle="->", lw=1.1, color=C_GRAY))

    ax = axes[1]
    c = p[p["机型编号"] == "C"].sort_values("单向距离（m）")
    ax.plot(c["单向距离（m）"] / 1000, c["结构上限（kg）"], marker="s", ms=5, lw=1.4,
            color=C_GRAY, label="$Q_{g}$ 结构上限 80 kg")
    ax.plot(c["单向距离（m）"] / 1000, c["最大安全载荷（kg）"], marker="o", ms=5.5, lw=1.8,
            color=C_RED, label="$q_{max}$ 能量反解值")
    for _, r in c.iterrows():
        if r["生效约束"] == "能量":
            ax.annotate(r["服务区编号"], (r["单向距离（m）"] / 1000, r["最大安全载荷（kg）"]),
                        textcoords="offset points", xytext=(3, -11), fontsize=7, color=C_RED)
    ax.set_xlabel("O01 → 服务区 单向距离 / km"); ax.set_ylabel("载荷 / kg")
    ax.set_title("(b) C 型：能量约束仅在远距离生效", loc="left", fontsize=10.5,
                 fontweight="bold")
    ax.legend(fontsize=8.5)
    fig.tight_layout()
    save(fig, "fig14_q1_binding")


# ---------------------------------------------------------------- fig15 组批方案
def fig15_groups():
    g = load("t_q1_groups")
    fig, axes = plt.subplots(1, 3, figsize=fs((12.0, 4.1)))

    ax = axes[0]
    ax.scatter(g["总质量（kg）"], g["总体积（m³）"], s=g["箱数"] * 26, c=C_BLUE,
               alpha=0.75, edgecolor="white", linewidth=0.9, zorder=3)
    ax.axhline(0.25, ls="--", lw=1.2, color=C_RED, label="C 型体积上限 0.25 m³")
    ax.axvline(80, ls=":", lw=1.2, color=C_ORANGE, label="C 型质量上限 80 kg")
    ax.set_xlabel("架次总质量 / kg"); ax.set_ylabel("架次总体积 / m³")
    ax.set_title(f"(a) {len(g)} 个架次的载荷分布（点大小∝箱数）", loc="left",
                 fontsize=10, fontweight="bold")
    ax.legend(fontsize=8)

    ax = axes[1]
    per = g.groupby("服务区编号").size()
    ax.bar(per.index, per.values, color=C_TEAL, edgecolor="#2f6b60", linewidth=0.7)
    for i, v in enumerate(per.values):
        ax.annotate(str(v), (i, v), ha="center", va="bottom", fontsize=8)
    ax.set_xlabel("服务区"); ax.set_ylabel("架次数")
    ax.tick_params(axis="x", rotation=90)
    ax.set_ylim(0, max(per.values) * 1.25)
    ax.set_title("(b) 各服务区架次数", loc="left", fontsize=10.5, fontweight="bold")

    ax = axes[2]
    ax.bar(g["架次编号"], g["架次能耗（kWh）"], color=C_PURPLE, edgecolor="white",
           linewidth=0.7, label="架次能耗")
    ax.axhline(6.4, ls="--", lw=1.3, color=C_RED, label="能量预算 6.4 kWh")
    ax.set_xlabel("架次编号"); ax.set_ylabel("能耗 / kWh")
    ax.tick_params(axis="x", rotation=90, labelsize=6.5)
    ax.set_title("(c) 逐架次能耗均在预算内", loc="left", fontsize=10.5, fontweight="bold")
    ax.legend(fontsize=8)
    fig.tight_layout()
    save(fig, "fig15_q1_groups")


# ---------------------------------------------------------------- fig16 策略与Pareto
def fig16_strategy():
    s = load("t_q1_strategy")
    fig, axes = plt.subplots(1, 2, figsize=fs((11.4, 4.3)),
                             gridspec_kw={"width_ratios": [1.15, 1]})

    ax = axes[0]
    sc = ax.scatter(s["总运输能耗（kWh）"], s["累计作业时间（s）"] / 3600,
                    s=s["往返架次数"] * 16 + 60, c=s["往返架次数"], cmap=SEQ,
                    edgecolor="white", linewidth=1.1, zorder=3)
    for _, r in s.iterrows():
        ax.annotate(r["策略"], (r["总运输能耗（kWh）"], r["累计作业时间（s）"] / 3600),
                    textcoords="offset points", xytext=(6, 5), fontsize=7.5)
    cb = fig.colorbar(sc, ax=ax, pad=0.02); cb.set_label("往返架次数")
    ax.set_xlabel("总运输能耗 / kWh"); ax.set_ylabel("累计作业时间 / h")
    ax.set_title("(a) 8 种策略的三目标分布", loc="left", fontsize=10.5, fontweight="bold")

    ax = axes[1]
    pf = load("t_q1_strategy").head(0)  # 占位，Pareto 由策略表筛非支配解
    pts = s[["往返架次数", "总运输能耗（kWh）"]].values
    nd = []
    for i, a in enumerate(pts):
        if not any(all(b[j] <= a[j] for j in range(2)) and any(b[j] < a[j] for j in range(2))
                   for k, b in enumerate(pts) if k != i):
            nd.append(i)
    ax.scatter(s["往返架次数"], s["总运输能耗（kWh）"], s=70, c=C_GRAY, alpha=0.65,
               edgecolor="white", linewidth=0.9, label="全部策略", zorder=2)
    ax.scatter(s.iloc[nd]["往返架次数"], s.iloc[nd]["总运输能耗（kWh）"], s=170,
               marker="*", c=C_RED, edgecolor="white", linewidth=0.9,
               label="Pareto 非支配解", zorder=4)
    for i in nd:
        r = s.iloc[i]
        ax.annotate(r["策略"], (r["往返架次数"], r["总运输能耗（kWh）"]),
                    textcoords="offset points", xytext=(6, 6), fontsize=8, color=C_RED)
    ax.set_xlabel("往返架次数"); ax.set_ylabel("总运输能耗 / kWh")
    ax.set_title("(b) 架次数—能耗 Pareto 前沿", loc="left", fontsize=10.5, fontweight="bold")
    ax.legend(fontsize=8.5)
    fig.tight_layout()
    save(fig, "fig16_q1_strategy")


# ---------------------------------------------------------------- fig17 下界
def fig17_lowerbound():
    lb = load("t_q1_lowerbound")
    fig, axes = plt.subplots(1, 2, figsize=fs((11.4, 4.2)),
                             gridspec_kw={"width_ratios": [1.3, 1]})

    actual = lb["架次数下界"] + lb["与下界差距"]

    ax = axes[0]
    x = np.arange(len(lb)); w = 0.38
    ax.bar(x - w / 2, lb["架次数下界"], w, color=C_GRAY, edgecolor="white",
           linewidth=0.7, label="Martello–Toth 型解析下界")
    ax.bar(x + w / 2, actual, w, color=C_BLUE, edgecolor="white", linewidth=0.7,
           label="本文启发式结果")
    ax.set_xticks(x); ax.set_xticklabels(lb["服务区编号"], rotation=90, fontsize=8)
    ax.set_xlabel("服务区"); ax.set_ylabel("架次数")
    ax.set_ylim(0, max(actual.max(), lb["架次数下界"].max()) * 1.3)
    ax.set_title("(a) 逐服务区：启发式解 = 解析下界", loc="left", fontsize=10.5,
                 fontweight="bold")
    ax.legend(fontsize=8.5, loc="upper right")

    ax = axes[1]
    sc = ax.scatter(lb["总质量（kg）"], lb["总体积（m³）"], s=lb["箱数"] * 24,
                    c=lb["总质量（kg）"] / lb["总体积（m³）"], cmap=SEQ,
                    edgecolor="white", linewidth=0.9, zorder=3)
    cb = fig.colorbar(sc, ax=ax, pad=0.02)
    cb.set_label("质量/体积比 / ($\\mathrm{kg\\cdot m^{-3}}$)")
    for _, r in lb.iterrows():
        ax.annotate(r["服务区编号"], (r["总质量（kg）"], r["总体积（m³）"]),
                    textcoords="offset points", xytext=(5, 4), fontsize=7)
    ax.set_xlabel("服务区总质量 / kg"); ax.set_ylabel("服务区总体积 / m³")
    cb.set_label("质量/体积比 / ($\\mathrm{kg\\cdot m^{-3}}$)")
    ax.set_title("(b) 制约架次数的是体积而非质量", loc="left", fontsize=10.5,
                 fontweight="bold")
    fig.tight_layout()
    save(fig, "fig17_q1_lowerbound")


# ---------------------------------------------------------------- fig18 rho 敏感性
def fig18_rho():
    sw = load("t_q1_rho_sweep")
    pv = load("q1_4_payload_vs_rho").rename(
        columns={"type_code": "type", "service_id": "服务区编号"})
    fig, axes = plt.subplots(1, 3, figsize=fs((12.6, 4.0)))

    ax = axes[0]
    if "type" in pv.columns or "机型" in pv.columns:
        tcol = "type" if "type" in pv.columns else "机型"
        qcol = [c for c in pv.columns if c not in (tcol, "rho", "服务区编号")][0]
        for t, g in pv.groupby(tcol):
            ax.plot(g["rho"], g[qcol], lw=1.8, color=TYPE_COLOR.get(t, C_GRAY), label=f"{t} 型")
    ax.set_xlabel(r"返航安全余量 $\rho_{g}$"); ax.set_ylabel("最大安全载荷 / kg")
    ax.set_title(r"(a) $\rho_{g}$ 对最大安全载荷的影响", loc="left", fontsize=10.5,
                 fontweight="bold")
    ax.legend(fontsize=8.5)

    ax = axes[1]
    ax.plot(sw["rho"], sw["n_sorties"], marker="o", ms=5, lw=2, color=C_BLUE,
            label="往返架次数")
    ax.set_xlabel(r"返航安全余量 $\rho_{g}$"); ax.set_ylabel("往返架次数", color=C_BLUE)
    ax.tick_params(axis="y", labelcolor=C_BLUE)
    ax2 = ax.twinx()
    ax2.plot(sw["rho"], sw["total_energy_kwh"], marker="s", ms=5, lw=2, color=C_RED,
             label="总能耗")
    ax2.set_ylabel("总能耗 / kWh", color=C_RED); ax2.tick_params(axis="y", labelcolor=C_RED)
    ax2.grid(False)
    inf = sw[~sw["feasible"].astype(bool)]
    if len(inf):
        ax.axvspan(inf["rho"].min(), sw["rho"].max(), color=C_RED, alpha=0.12)
        ax.annotate("无可行解", xy=((inf["rho"].min() + sw["rho"].max()) / 2, sw["n_sorties"].max() * 0.9),
                    ha="center", fontsize=9, color=C_RED, fontweight="bold")
    ax.set_title(r"(b) $\rho_{g}$ 对架次数与能耗的影响", loc="left", fontsize=10.5,
                 fontweight="bold")

    ax = axes[2]
    ax.plot(sw["rho"], sw["serial_total_time_s"] / 3600, marker="^", ms=5, lw=2,
            color=C_TEAL)
    ax.set_xlabel(r"返航安全余量 $\rho_{g}$"); ax.set_ylabel("累计作业时间 / h")
    ax.set_title(r"(c) $\rho_{g}$ 对作业时间的影响", loc="left", fontsize=10.5,
                 fontweight="bold")
    ax.annotate(r"附件取值 $\rho_{g}=0.20$" "\n" "恰在效率最优区间",
                xy=(0.20, sw["serial_total_time_s"].iloc[0] / 3600),
                xytext=(0.26, sw["serial_total_time_s"].max() / 3600 * 0.55),
                fontsize=8.5, arrowprops=dict(arrowstyle="->", lw=1.2, color=C_GRAY))
    fig.tight_layout()
    save(fig, "fig18_q1_rho")


# ---------------------------------------------------------------- fig19 rho×服务区热力图
def fig19_rho_heatmap():
    pv = load("q1_4_payload_vs_rho").rename(
        columns={"type_code": "type", "service_id": "服务区编号"})
    tcol = "type" if "type" in pv.columns else "机型"
    scol = "服务区编号" if "服务区编号" in pv.columns else None
    qcol = [c for c in pv.columns if c not in (tcol, "rho", "服务区编号")][0]
    if scol is None:
        print("    (skip fig19: 缺少服务区列)")
        return
    sub = pv[pv[tcol] == "C"]
    piv = sub.pivot(index=scol, columns="rho", values=qcol)

    fig, axes = plt.subplots(1, 2, figsize=fs((12.2, 4.4)),
                             gridspec_kw={"width_ratios": [1.45, 1]})
    ax = axes[0]
    sns.heatmap(piv, cmap=SEQ, ax=ax, linewidths=0.4, linecolor="white",
                cbar_kws={"label": "最大安全载荷 / kg"}, annot=True, fmt=".0f",
                annot_kws={"fontsize": 6})
    ax.set_xlabel(r"返航安全余量 $\rho_{g}$"); ax.set_ylabel("服务区")
    ax.set_title("(a) C 型最大安全载荷随 $\\rho_{g}$ 的演化", loc="left",
                 fontsize=10.5, fontweight="bold")

    ax = axes[1]
    n_inf = sub.groupby("rho").apply(
        lambda g: (g[qcol] <= 0).sum() if (g[qcol] <= 0).any() else 0, include_groups=False)
    ax.plot(n_inf.index, n_inf.values, marker="o", ms=5, lw=2, color=C_RED)
    ax.fill_between(n_inf.index, 0, n_inf.values, color=C_RED, alpha=0.15)
    ax.set_xlabel(r"返航安全余量 $\rho_{g}$"); ax.set_ylabel("失去可行性的服务区数")
    ax.set_title("(b) 高 $\\rho_{g}$ 下的不可行服务区", loc="left", fontsize=10.5,
                 fontweight="bold")
    fig.tight_layout()
    save(fig, "fig19_q1_rho_heatmap")


def main():
    setup()
    print("fig_q1:")
    for f in (fig13_payload_heatmap, fig14_binding, fig15_groups, fig16_strategy,
              fig17_lowerbound, fig18_rho, fig19_rho_heatmap):
        try:
            f()
        except Exception as e:
            print(f"    ✗ {f.__name__}: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
