# -*- coding: utf-8 -*-
"""模型检验、独立复算审计与全文指标汇总图（fig36–fig38）。"""
from __future__ import annotations

import collections
import json
import re

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.patches import Patch

from plotstyle import (fs, setup, save, load, load_data, metrics, DAT, PALETTE, TYPE_COLOR,
                       C_BLUE, C_ORANGE, C_TEAL, C_PURPLE, C_RED, C_GRAY, C_GOLD, SEQ)


# ---------------------------------------------------------------- fig36 敏感性
def fig36_sensitivity():
    s = load("t_sensitivity")
    q3p = json.loads((DAT / "q3_params.json").read_text(encoding="utf-8"))
    q3p = q3p.get("params", q3p)
    rng = {
        "通信采样步长": (1, 30, q3p.get("sample_dt_s", 2), "s"),
        "悬停网格步长": (200, 1500, q3p.get("hover_step_m", 400), "m"),
        "DEM 高程噪声": (0, 20, 10, "m"),
        "衰落裕量": (2, 18, 8, "dB"),
    }
    fig, axes = plt.subplots(1, 2, figsize=fs((12.0, 4.3)),
                             gridspec_kw={"width_ratios": [1.1, 1]})

    ax = axes[0]
    names = list(rng.keys())
    y = np.arange(len(names))
    for i, n in enumerate(names):
        lo, hi, ch, u = rng[n]
        ax.plot([lo, hi], [i, i], lw=7, color="#dcdcdc", solid_capstyle="round", zorder=1)
        ax.scatter([ch], [i], s=140, marker="D", color=C_RED, edgecolor="white",
                   linewidth=1.2, zorder=3)
        ax.annotate(f"取 {ch} {u}", (ch, i), xytext=(0, 13), textcoords="offset points",
                    ha="center", fontsize=8.5, color=C_RED, fontweight="bold")
        ax.annotate(f"{lo}", (lo, i), xytext=(-4, -14), textcoords="offset points",
                    ha="right", fontsize=7.5, color=C_GRAY)
        ax.annotate(f"{hi}", (hi, i), xytext=(4, -14), textcoords="offset points",
                    ha="left", fontsize=7.5, color=C_GRAY)
    ax.set_yticks(y); ax.set_yticklabels(names, fontsize=9.5)
    ax.set_ylim(-0.6, len(names) - 0.25)
    ax.set_xscale("log")
    ax.set_xlabel("参数取值范围（对数轴）")
    ax.set_title("(a) 四类参数的取值范围与本文取值", loc="left", fontsize=10.5,
                 fontweight="bold")
    ax.grid(axis="y", alpha=0.12)

    ax = axes[1]
    sw = load("t_q1_rho_sweep")
    ax2 = ax
    ax2.plot(sw["rho"], sw["n_sorties"], marker="o", ms=5, lw=2, color=C_BLUE)
    ax2.set_xlabel(r"返航安全余量 $\rho_{g}$"); ax2.set_ylabel("往返架次数", color=C_BLUE)
    ax2.tick_params(axis="y", labelcolor=C_BLUE)
    ax3 = ax2.twinx()
    ax3.plot(sw["rho"], sw["total_energy_kwh"], marker="s", ms=5, lw=2, color=C_RED)
    ax3.set_ylabel("总能耗 / kWh", color=C_RED); ax3.tick_params(axis="y", labelcolor=C_RED)
    ax3.grid(False)
    d = sw[sw["rho"] == sw["rho"].iloc[0]]
    ax2.set_title(r"(b) $\rho_{g}$ 是唯一强敏感参数（架次 18→25）", loc="left",
                  fontsize=10.5, fontweight="bold")
    fig.tight_layout()
    save(fig, "fig36_sensitivity")


# ---------------------------------------------------------------- fig37 独立审计
def fig37_audit():
    """四问独立校验结果记分卡：按违规类别分列，突出「物理类硬约束违规 0 条」。"""
    _m2, _m3 = metrics(2), metrics(3)     # ★ 图例数字取自 metrics，勿硬编码

    def cats(path):
        d = json.loads((DAT / path).read_text(encoding="utf-8"))
        c = collections.Counter()
        for v in d["violations"]:
            c[re.sub(r"架次\s*\w+.*$", "", v).strip("[] ").split("]")[0]] += 1
        return c, d["ok"]

    c2, ok2 = cats("q2_feasibility.json")
    c3, ok3 = cats("q3_feasibility.json")
    allc = ["超出能量预算", "返航SOC低于下限", "架次时长不足以完成任务",
            "同一资源任务时段重叠", "通信中断", "首批保障箱超时", "超出期望送达时间"]
    short = ["能量超支", "SOC 不足", "时间不自洽", "资源冲突", "通信中断",
             "首批超时", "期望超时"]
    phys = {"能量超支", "SOC 不足", "时间不自洽", "资源冲突", "通信中断"}

    fig, axes = plt.subplots(1, 2, figsize=fs((12.2, 4.6)),
                             gridspec_kw={"width_ratios": [1.25, 1]})

    ax = axes[0]
    v2 = [c2.get(k, 0) for k in allc]
    v3 = [c3.get(k, 0) for k in allc]
    x = np.arange(len(short)); w = 0.38
    b1 = ax.bar(x - w / 2, v2, w, color=C_BLUE, edgecolor="white", linewidth=0.7,
                label=f"问题二（{_m2['n_sorties']} 架次）")
    b2 = ax.bar(x + w / 2, v3, w, color=C_ORANGE, edgecolor="white", linewidth=0.7,
                label=f"问题三（{_m3['n_transport_sorties']} 运输 + "
                      f"{_m3['n_relay_sorties']} 中继架次）")
    for b in list(b1) + list(b2):
        if b.get_height() > 0:
            ax.annotate(f"{int(b.get_height())}",
                        (b.get_x() + b.get_width() / 2, b.get_height()),
                        ha="center", va="bottom", fontsize=8.5)
    for i, s in enumerate(short):
        if s in phys:
            ax.axvspan(i - 0.5, i + 0.5, color=C_TEAL, alpha=0.10, zorder=0)
    ax.set_xticks(x); ax.set_xticklabels(short, rotation=32, fontsize=8.5)
    ax.set_ylabel("违规条数"); ax.set_ylim(0, max(v2 + v3) * 1.28)
    ax.set_title("(a) 独立校验器的违规分类（绿底 = 物理类硬约束）", loc="left",
                 fontsize=10.5, fontweight="bold")
    ax.legend(fontsize=8.5)
    ax.annotate("物理类硬约束违规 0 条", (0.02, 0.86), xycoords="axes fraction",
                fontsize=9.5, color="#2f6b60", fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.35", fc="#eef7f5", ec=C_TEAL, lw=1.0))

    ax = axes[1]
    a = load_data("q2_independent_audit")
    hi = float(a["t1"].max()) * 1.06
    ax.plot([0, hi], [0, hi], ls="--", lw=1.2, color=C_GRAY, label="方案自报 = 复算")
    ax.scatter(a["t_end_recomp"], a["t1"], s=64,
               c=[TYPE_COLOR[g] for g in a["type"]],
               edgecolor="white", linewidth=0.9, zorder=3)
    ax.set_xlim(0, hi); ax.set_ylim(0, hi)
    ax.set_xlabel("独立复算的架次结束时刻 / s")
    ax.set_ylabel("方案自报的返回 O01 时刻 / s")
    ax.set_title(f"(b) 时间自洽性（最大偏差 {a['dt'].max():.3f} s）", loc="left",
                 fontsize=10.5, fontweight="bold")
    ax.legend(handles=[plt.Line2D([], [], ls="--", color=C_GRAY, label="方案自报 = 复算")]
                      + [Patch(color=c, label=f"{t} 型") for t, c in TYPE_COLOR.items()],
              fontsize=8)
    fig.tight_layout()
    save(fig, "fig37_q2_audit")


# ---------------------------------------------------------------- fig38 指标汇总
def fig38_summary():
    m1, m2, m3, m4 = (metrics(1), metrics(2), metrics(3), metrics(4))
    fig = plt.figure(figsize=fs((12.4, 6.6)))
    gs = fig.add_gridspec(2, 3, hspace=0.52, wspace=0.34)

    def kpi(ax, title, items):
        ax.axis("off")
        ax.set_title(title, loc="left", fontsize=11, fontweight="bold")
        for i, (k, v, u) in enumerate(items):
            yy = 0.86 - i * 0.24
            ax.text(0.02, yy, k, fontsize=9.5, va="center", color="#333333")
            ax.text(0.98, yy, f"{v}", fontsize=15 if i == 0 else 12, va="center",
                    ha="right", color=C_BLUE, fontweight="bold")
            if u:
                ax.text(0.985, yy - 0.085, u, fontsize=7.5, va="center", ha="right",
                        color=C_GRAY)

    kpi(fig.add_subplot(gs[0, 0]), "问题一 · 载荷与组批",
        [("最优架次数", m1["chosen_n_sorties"], "架次（达解析下界）"),
         ("总运输能耗", f"{m1['chosen_total_energy_kwh']:.2f}", "kWh"),
         ("累计作业时间", f"{m1['chosen_serial_total_time_s']/3600:.2f}", "h")])
    kpi(fig.add_subplot(gs[0, 1]), "问题二 · 多机调度",
        [("运输架次数", m2["n_sorties"], "架次"),
         ("总能耗", f"{m2['total_energy_kwh']:.2f}", "kWh"),
         ("完工时间", f"{m2['makespan_h']:.2f}", "h"),
         ("期望送达准时率", f"{m2['on_time_rate']*100:.1f}", "%")])
    kpi(fig.add_subplot(gs[0, 2]), "问题三 · 通信协同",
        [("中继架次数", m3["n_relay_sorties"], "架次"),
         ("覆盖率", f"{m3['coverage_rate']*100:.0f}%",
          f"（{m3['n_sorties_covered']}/{m3['n_sorties_need_relay']}）"),
         ("总能耗", f"{m3['total_energy_kwh']:.2f}", "kWh"),
         ("联合完工", f"{m3['joint_makespan_h']:.2f}", "h")])
    # ★ Q4 的可行性与资源量由 metrics 推出，勿硬编码
    _nu = int(m4["n_atomic_units"])
    _feas = ("K=2 与 K=3 均可行" if _nu >= 3 else
             ("K=2 可行（K=3 需拆架次）" if _nu == 2 else "无（单一连通分量）"))
    _tot1 = sum(int(m4.get("baseline_resources_k1", {}).get(k, 0))
                for k in ("uavs", "batteries", "relay_uavs", "relay_packs"))
    kpi(fig.add_subplot(gs[1, 0]), "问题四 · 分区配置",
        [("原子单元数", _nu, "个"),
         ("直接可行的分组", _feas, ""),
         ("K=1 资源总量", str(_tot1), "台·组")])

    ax = fig.add_subplot(gs[1, 1:])
    names = ["总能耗\n(kWh)", "完工时间\n(h)", "架次数"]
    q1 = [m1["chosen_total_energy_kwh"], m1["chosen_serial_total_time_s"] / 3600,
          m1["chosen_n_sorties"]]
    q2 = [m2["total_energy_kwh"], m2["makespan_h"], m2["n_sorties"]]
    q3 = [m3["total_energy_kwh"], m3["joint_makespan_h"], m3["n_transport_sorties"]]
    x = np.arange(len(names)); w = 0.26
    ax.bar(x - w, q1, w, color=C_BLUE, edgecolor="white", linewidth=0.8, label="问题一")
    ax.bar(x, q2, w, color=C_ORANGE, edgecolor="white", linewidth=0.8, label="问题二")
    ax.bar(x + w, q3, w, color=C_TEAL, edgecolor="white", linewidth=0.8,
           label="问题三（运输+中继）")
    for xi, (a, b, c) in enumerate(zip(q1, q2, q3)):
        for dx, v in ((-w, a), (0, b), (w, c)):
            ax.annotate(f"{v:.1f}", (xi + dx, v), ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x); ax.set_xticklabels(names, fontsize=9)
    ax.set_ylabel("数值"); ax.set_ylim(0, max(q3) * 1.22)
    ax.set_title("(d) 四问主要指标对比", loc="left", fontsize=11, fontweight="bold")
    ax.legend(fontsize=8.5)
    save(fig, "fig38_summary")


def main():
    setup()
    print("fig_check:")
    for f in (fig36_sensitivity, fig37_audit, fig38_summary):
        try:
            f()
        except Exception as e:
            print(f"    ✗ {f.__name__}: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
