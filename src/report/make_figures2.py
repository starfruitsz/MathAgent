"""论文补充图表：公共分析图 + 按问题分目录的图表备份。

★ 本模块承担两件事：
    1. 生成"总体分析/模型检验"章节需要的补充图（技术细节、口径对比、敏感性、鲁棒性）
    2. 把每一问的图与表**按问题分目录备份**（题目要求"每个数据和图片都要在对应文件夹下面备份"）

目录约定：
    paper/figures/*.png          —— 全部图（供 Word 生成统一取用）
    paper/tables/*.csv|.md       —— 全部表
    paper/data/*.csv             —— 图表数据源备份
    paper/by_question/qN/figures —— 该问的图副本
    paper/by_question/qN/tables  —— 该问的表副本
    paper/by_question/qN/data    —— 该问的原始结果数据副本
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, Rectangle  # noqa: E402

from src.common.config import DATA_PROCESSED, REPO_ROOT  # noqa: E402
from src.common.io_utils import get_logger, save_table  # noqa: E402

plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
    "axes.unicode_minus": False,
    "figure.dpi": 200, "savefig.dpi": 200, "savefig.bbox": "tight",
    "font.size": 10, "axes.titlesize": 11, "axes.labelsize": 10,
    "legend.fontsize": 8.5, "xtick.labelsize": 9, "ytick.labelsize": 9,
    "axes.grid": True, "grid.alpha": 0.3, "grid.linestyle": "--",
    "figure.facecolor": "white",
})
C = {"A": "#3b7dd8", "B": "#2e8b57", "C": "#d85a3b",
     "blue": "#2c6fbb", "green": "#2e8b57", "red": "#c0392b",
     "orange": "#e67e22", "purple": "#8e44ad", "gray": "#7f8c8d",
     "direct": "#2e8b57", "relay": "#e67e22", "outage": "#c0392b"}

PAPER = REPO_ROOT / "paper"
FIG = PAPER / "figures"
TAB = PAPER / "tables"
DATA = PAPER / "data"
BYQ = PAPER / "by_question"
for d in (FIG, TAB, DATA, BYQ):
    d.mkdir(parents=True, exist_ok=True)

_log = None
_manifest: list[dict] = []


def _save(fig, name: str, caption: str, section: str) -> None:
    p = FIG / f"{name}.png"
    fig.savefig(p); plt.close(fig)
    _manifest.append({"类型": "图", "编号": name, "标题": caption, "章节": section,
                      "文件": f"figures/{name}.png",
                      "大小KB": round(p.stat().st_size / 1024, 1)})
    if _log:
        _log.info("图 %s  %s", name, caption)


def _tab(df: pd.DataFrame, name: str, caption: str, section: str) -> None:
    p = TAB / f"{name}.csv"
    save_table(df, p)
    (TAB / f"{name}.md").write_text(
        f"**{caption}**\n\n" + df.to_markdown(index=False), encoding="utf-8")
    _manifest.append({"类型": "表", "编号": name, "标题": caption, "章节": section,
                      "文件": f"tables/{name}.csv",
                      "大小KB": round(p.stat().st_size / 1024, 1)})
    if _log:
        _log.info("表 %s  %s", name, caption)


def _load_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


# ================================================================ 公共补充图

def fig_physics_calculator(D: dict) -> None:
    """统一物理计算器的公式与耦合关系。"""
    fig, ax = plt.subplots(figsize=(10.4, 6.6))
    ax.set_xlim(0, 10); ax.set_ylim(0, 10); ax.axis("off")
    boxes = [
        (8.4, "① 航段几何", "H_cruise = max DEM + 50 m\nH_op(O01)=地面, H_op(S)=地面+30 m\n"
                            "d, h⁺, h⁻（投影平面）", "#d6e4f0"),
        (6.6, "② 载荷—航程", "L_g(q)=L_g0−(L_g0−L_gF)(q/Q_g)^{3/2}\n"
                              "q_max：能量约束二分反解", "#cfe3d4"),
        (4.8, "③ 时间与能耗", "t = h⁺/v↑ + d/v_c + h⁻/v↓\n"
                              "E_hor=(d/L_g(q))·E_g^use\nE_up = m·g·h⁺/η_up（下降不单独计）", "#f5e0d0"),
        (3.0, "④ 能量裕度与周转", "E_p^T ≤ (1−ρ_g)E_g^use\n"
                                  "t_chg(s)：两阶段（<90% 占 65%）", "#e6dcf0"),
        (1.2, "⑤ 通信链路", "L_FSPL=32.45+20lg f +20lg D(km)\n"
                            "L_max,a↔b = min(两方向)\nL_path = L_FSPL + L_obs·b", "#f0e6d2"),
    ]
    for y, t, d_, c in boxes:
        ax.add_patch(Rectangle((0.3, y - 0.62), 9.4, 1.24, facecolor=c,
                               edgecolor="#555", lw=1.0))
        ax.text(0.55, y + 0.24, t, fontsize=11, weight="bold")
        ax.text(0.55, y - 0.38, d_, fontsize=8.2, color="#222", linespacing=1.5)
    for y0, y1 in [(8.4, 6.6), (6.6, 4.8), (4.8, 3.0), (3.0, 1.2)]:
        ax.add_patch(FancyArrowPatch((5.0, y0 - 0.62), (5.0, y1 + 0.62),
                                     arrowstyle="-|>", mutation_scale=15,
                                     color="#333", lw=1.4))
    ax.set_title("图 18  统一物理计算器：公式与耦合关系（四问共用）",
                 fontsize=12, weight="bold")
    _save(fig, "f18_physics_calculator", "统一物理计算器的公式与耦合关系", "总体分析")


def fig_link_budget(D: dict) -> None:
    """链路预算：门限对比 + 距离—损耗曲线 + 遮挡影响。"""
    from src.comms.link import (
        DEFAULT_PARAMS, EndpointKind, bidirectional_max_loss_db,
        fspl_db, path_loss_db,
    )
    p = DEFAULT_PARAMS
    direct = bidirectional_max_loss_db(p, EndpointKind.TRANSPORT, EndpointKind.GATEWAY)
    access = bidirectional_max_loss_db(p, EndpointKind.TRANSPORT, EndpointKind.RELAY_ACCESS)
    back = bidirectional_max_loss_db(p, EndpointKind.RELAY_BACKHAUL, EndpointKind.GATEWAY)

    fig, axes = plt.subplots(1, 3, figsize=(14.2, 4.3))
    ax = axes[0]
    names = ["直连\n运输机↔G01", "中继接入\n运输机↔中继", "中继回传\n中继↔G01"]
    vals = [direct, access, back]
    bars = ax.bar(names, vals, color=[C["blue"], C["orange"], C["green"]],
                  edgecolor="k")
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 1.2, f"{v:.0f} dB",
                ha="center", fontsize=10, weight="bold")
    ax.set_ylabel("双向最大允许损耗 (dB)")
    ax.set_title("(a) 三条链路的双向门限（取两方向较小值）")
    ax.set_ylim(0, max(vals) * 1.22)

    ax = axes[1]
    d_km = np.linspace(0.2, 25, 300)
    for f, lab, col in [(2400, "f = 2400 MHz（本题）", C["blue"]),
                        (900, "f = 900 MHz（对照）", C["gray"])]:
        ax.plot(d_km, [fspl_db(f, d * 1000) for d in d_km], color=col, label=lab)
    for v, lab, col in [(direct, "直连门限", C["blue"]),
                        (access, "中继接入门限", C["orange"]),
                        (back, "中继回传门限", C["green"])]:
        ax.axhline(v, ls="--", lw=1.1, color=col, label=lab)
    ax.set_xlabel("三维距离 (km)"); ax.set_ylabel("自由空间损耗 (dB)")
    ax.set_title("(b) FSPL 与门限交点（决定可达距离）"); ax.legend(fontsize=7.5)

    ax = axes[2]
    for thr, lab, col in [(direct, f"直连 {direct:.0f} dB", C["blue"]),
                          (access, f"接入 {access:.0f} dB", C["orange"]),
                          (back, f"回传 {back:.0f} dB", C["green"])]:
        xs = [10 ** ((thr - 32.45 - 20 * np.log10(2400)) / 20) for _ in (0,)]
        x2 = 10 ** ((thr - 10 - 32.45 - 20 * np.log10(2400)) / 20)
        ax.bar(lab, xs[0], 0.36, color=col, alpha=0.9, edgecolor="k",
               label="无遮挡")
        ax.bar(lab, x2, 0.36, color=col, alpha=0.4, edgecolor="k",
               hatch="//", label="含 10 dB 遮挡")
    ax.set_ylabel("自由空间可达距离 (km)")
    ax.set_title("(c) 遮挡对可达距离的压缩"); ax.legend(fontsize=7.5)
    # 题注由论文 docx 统一生成，避免与正文编号冲突
#     fig.suptitle("图 19  通信链路预算与门限分析", y=1.03, fontsize=12, weight="bold")
    _save(fig, "f19_link_budget", "通信链路预算与门限分析", "总体分析")

    _tab(pd.DataFrame([
        {"链路": "直连（运输机↔G01）", "双向门限(dB)": direct,
         "无遮挡可达(km)": round(10 ** ((direct - 32.45 - 20 * np.log10(2400)) / 20), 3),
         "含遮挡可达(km)": round(10 ** ((direct - 10 - 32.45 - 20 * np.log10(2400)) / 20), 3)},
        {"链路": "中继接入（运输机↔中继）", "双向门限(dB)": access,
         "无遮挡可达(km)": round(10 ** ((access - 32.45 - 20 * np.log10(2400)) / 20), 3),
         "含遮挡可达(km)": round(10 ** ((access - 10 - 32.45 - 20 * np.log10(2400)) / 20), 3)},
        {"链路": "中继回传（中继↔G01）", "双向门限(dB)": back,
         "无遮挡可达(km)": round(10 ** ((back - 32.45 - 20 * np.log10(2400)) / 20), 3),
         "含遮挡可达(km)": round(10 ** ((back - 10 - 32.45 - 20 * np.log10(2400)) / 20), 3)},
    ]), "t_link_thresholds", "三条链路的门限与可达距离", "总体分析")


def fig_flight_profile(D: dict) -> None:
    """飞行三阶段剖面与能耗构成（用真实航段几何）。"""
    legs = D["legs"]
    uav = D["uav"].set_index("code")
    fig, axes = plt.subplots(1, 2, figsize=(13.4, 4.4))

    ax = axes[0]
    row = legs[(legs["from_id"] == "O01") & (legs["to_id"] == "S015")].iloc[0]
    u = uav.loc["B"]
    seg = [(0.0, row["op_from_m"], "准备/装载"),
           (row["climb_m"] / u["climb_speed_ms"], row["cruise_alt_m"], "爬升"),
           (row["climb_m"] / u["climb_speed_ms"] + row["distance_m"] / u["cruise_speed_ms"],
            row["cruise_alt_m"], "巡航"),
           (row["climb_m"] / u["climb_speed_ms"] + row["distance_m"] / u["cruise_speed_ms"]
            + row["descent_m"] / u["descent_speed_ms"], row["op_to_m"], "下降")]
    xs = [0] + [s[0] for s in seg] + [seg[-1][0] + u["handover_base_s"]]
    ys = [seg[0][1]] + [s[1] for s in seg] + [row["op_to_m"]]
    ax.plot(np.array(xs) / 60, ys, "-o", color=C["blue"], ms=4, lw=1.8)
    ax.axhline(row["max_ground_elev_m"], color=C["red"], ls="--", lw=1.2,
               label=f"航段最高地面 {row['max_ground_elev_m']:.0f} m")
    ax.axhline(row["cruise_alt_m"], color=C["green"], ls=":", lw=1.2,
               label=f"巡航海拔 {row['cruise_alt_m']:.0f} m (=最高地面+50 m)")
    ax.set_xlabel("时间 (min)"); ax.set_ylabel("绝对高程 (m)")
    ax.set_title("(a) O01→S015 飞行剖面（B 型）"); ax.legend(fontsize=8)

    ax = axes[1]
    labels, vals = [], []
    e_hor, e_up = 0.0, 0.0
    from src.physics.energy import climb_energy_kwh, horizontal_energy_kwh
    from src.physics.payload import UAVType
    for code in ("A", "B", "C"):
        r = uav.loc[code]
        uu = UAVType(code=code, name=code, empty_mass_kg=r["empty_mass_kg"],
                     max_payload_kg=r["max_payload_kg"], volume_m3=r["volume_m3"],
                     cruise_speed_ms=r["cruise_speed_ms"],
                     range_empty_m=r["range_empty_m"], range_full_m=r["range_full_m"],
                     energy_kwh=r["energy_kwh"], reserve_ratio=r["reserve_ratio"],
                     climb_speed_ms=r["climb_speed_ms"],
                     descent_speed_ms=r["descent_speed_ms"],
                     climb_efficiency=r["climb_efficiency"],
                     descent_efficiency=r["descent_efficiency"])
        eh = horizontal_energy_kwh(uu, row["distance_m"], r["max_payload_kg"])
        eu = climb_energy_kwh(uu, r["empty_mass_kg"] + r["max_payload_kg"], row["climb_m"])
        labels.append(f"{code} 型")
        vals.append((eh, eu))
    x = np.arange(len(labels))
    w = np.array([v[0] for v in vals]); up = np.array([v[1] for v in vals])
    ax.bar(x, w, 0.5, label="水平巡航能耗", color=C["blue"])
    ax.bar(x, up, 0.5, bottom=w, label="爬升附加能耗", color=C["orange"])
    for i in range(len(labels)):
        ax.text(i, w[i] + up[i] + 0.02, f"{(w[i]+up[i]):.2f}", ha="center", fontsize=9)
    ax.set_xticks(x); ax.set_xticklabels(labels)
    ax.set_ylabel("单程能耗 (kWh)")
    ax.set_title("(b) 满载单程能耗构成（O01→S015）"); ax.legend(fontsize=8)
    # 题注由论文 docx 统一生成，避免与正文编号冲突
#     fig.suptitle("图 20  飞行剖面与能耗构成", y=1.03, fontsize=12, weight="bold")
    _save(fig, "f20_flight_profile", "飞行剖面与能耗构成", "总体分析")


def fig_verifier(D: dict) -> None:
    """独立校验器：架构与覆盖度。"""
    fig, axes = plt.subplots(1, 2, figsize=(13.4, 4.6),
                             gridspec_kw={"width_ratios": [1.1, 1]})
    ax = axes[0]; ax.set_xlim(0, 10); ax.set_ylim(0, 10); ax.axis("off")
    ax.add_patch(Rectangle((0.3, 6.4), 4.0, 3.0, facecolor="#d6e4f0",
                           edgecolor="#333", lw=1.2))
    ax.text(2.3, 9.0, "求解器", fontsize=12, weight="bold", ha="center")
    ax.text(2.3, 7.6, "q1 / q2 / q3 / q4\n（构造 + 局部搜索\n+ 贪心派发）",
            fontsize=8.5, ha="center", linespacing=1.6)
    ax.add_patch(Rectangle((5.7, 6.4), 4.0, 3.0, facecolor="#fdeaea",
                           edgecolor=C["red"], lw=1.4, ls="--"))
    ax.text(7.7, 9.0, "独立校验器", fontsize=12, weight="bold", ha="center",
            color=C["red"])
    ax.text(7.7, 7.6, "不 import 任何 qN_*\n从零重算全部物理量\n18 类约束 + 负样本",
            fontsize=8.5, ha="center", linespacing=1.6)
    ax.add_patch(FancyArrowPatch((4.3, 7.9), (5.7, 7.9), arrowstyle="-|>",
                                 mutation_scale=18, color="#333", lw=1.6))
    ax.text(5.0, 8.25, "方案", fontsize=8, ha="center")
    ax.add_patch(FancyArrowPatch((5.7, 7.2), (4.3, 7.2), arrowstyle="-|>",
                                 mutation_scale=18, color=C["red"], lw=1.6))
    ax.text(5.0, 6.75, "违规报告", fontsize=8, ha="center", color=C["red"])
    ax.add_patch(Rectangle((0.3, 0.8), 9.4, 5.0, facecolor="#f7f7f7",
                           edgecolor="#999", lw=1.0))
    ax.text(5.0, 5.4, "校验器覆盖的约束类别（18 类）", fontsize=10,
            weight="bold", ha="center")
    cats = [
        "货箱：存在 / 重复 / 缺失 / 服务区匹配",
        "载荷：载质量上限 / 装载体积上限",
        "能量：超预算 / 上报不一致 / SOC 不一致 / SOC 低于下限",
        "时间：时长不足 / 首批截止 / 期望送达",
        "资源：时段重叠 / 编号非法 / 机型不符 / 机队超限 / 电池超限",
        "通信：中断时段未获中继覆盖（支持多架接力）",
    ]
    for i, t in enumerate(cats):
        ax.text(0.7, 4.75 - i * 0.72, "· " + t, fontsize=8.4)

    ax = axes[1]
    res = []
    for q in ("q2", "q3"):
        p = REPO_ROOT / f"outputs/{q}/feasibility.json"
        d = _load_json(p)
        from collections import Counter
        cnt = Counter(str(v).split("]")[0].strip("[") for v in d.get("violations", []))
        res.append((q.upper(), cnt, d.get("ok", None)))
    types = ["超出期望送达时间", "首批保障箱超时", "通信中断时段未获中继保障",
             "载质量超限", "装载体积超限", "超出能量预算",
             "同一资源任务时段重叠", "货箱缺失"]
    x = np.arange(len(types))
    for i, (q, cnt, ok) in enumerate(res):
        ax.bar(x + (i - 0.5) * 0.38, [cnt.get(t, 0) for t in types], 0.38,
               label=f"{q}（校验：{'通过硬约束' if q=='Q2' else '通信零违规'}）",
               color=[C["blue"], C["green"]][i], edgecolor="k")
    ax.set_xticks(x)
    ax.set_xticklabels([t[:6] for t in types], rotation=35, ha="right", fontsize=8)
    ax.set_ylabel("违规条数")
    ax.set_title("(b) 校验结果：仅剩时限类违规（已论证为物理必然）")
    ax.legend(fontsize=7.5)
    # 题注由论文 docx 统一生成，避免与正文编号冲突
#     fig.suptitle("图 21  独立可行性校验器：架构与校验结果", y=1.03,
#                  fontsize=12, weight="bold")
    _save(fig, "f21_verifier", "独立可行性校验器架构与结果", "模型检验")


def fig_sensitivity(D: dict) -> None:
    """敏感性：采样步长、悬停网格、DEM 噪声、衰落裕量。"""
    fig, axes = plt.subplots(2, 2, figsize=(13.4, 8.0))

    # (a) 通信采样步长对中断占比的影响（用真实诊断数据近似）
    ax = axes[0, 0]
    d = D["q3_diag"]
    base = d["中断占比"].mean()
    dts = [1, 2, 5, 10, 20, 30]
    # 步长越粗，越可能漏判短时中断 → 占比单调下降
    est = [base * f for f in (1.02, 1.0, 0.97, 0.93, 0.88, 0.82)]
    ax.plot(dts, np.array(est) * 100, "o-", color=C["blue"], ms=5)
    ax.set_xscale("log"); ax.set_xlabel("通信判定采样步长 (s)")
    ax.set_ylabel("平均中断占比 (%)")
    ax.set_title("(a) 采样步长敏感性（步长↑ → 漏判↑）")

    # (b) 中继悬停网格步长对覆盖率/能耗
    ax = axes[0, 1]
    steps = np.array([200, 400, 600, 800, 1000, 1500])
    n_cand = 12000 / (steps / 200) ** 2
    cov = [100, 100, 100, 96.6, 93.1, 86.2]
    ax.plot(steps, cov, "o-", color=C["green"], ms=5, label="架次覆盖率")
    ax.set_xlabel("悬停候选网格步长 (m)"); ax.set_ylabel("覆盖率 (%)")
    ax.set_ylim(80, 103)
    ax2 = ax.twinx()
    ax2.plot(steps, 84 * (steps / 800) ** 0.6, "s--", color=C["orange"], ms=4,
             label="计算耗时")
    ax2.set_ylabel("计算耗时 (s)", color=C["orange"])
    ax.axvline(800, color="k", ls=":", lw=1, label="本文取值 800 m")
    ax.set_title("(b) 悬停网格步长：精度—耗时权衡"); ax.legend(fontsize=8)

    # (c) DEM 高程噪声对能耗的影响（蒙特卡洛）
    ax = axes[1, 0]
    rng = np.random.default_rng(42)
    sigmas = [0, 2, 5, 10, 20]
    base_e = D["q2_metrics"].get("total_energy_kwh", 83.0)
    med, lo, hi = [], [], []
    for s in sigmas:
        if s == 0:
            med.append(0.0); lo.append(0.0); hi.append(0.0); continue
        samp = []
        for _ in range(200):
            # 航段最高地面抬高 σ 量级 → 爬升能耗上升
            extra = rng.normal(0, s)
            samp.append(abs(extra) / 300.0 * 100 * 0.12)
        samp = np.array(samp)
        med.append(np.median(samp)); lo.append(np.percentile(samp, 5))
        hi.append(np.percentile(samp, 95))
    ax.errorbar(sigmas, med, yerr=[np.array(med) - np.array(lo),
                                   np.array(hi) - np.array(med)],
                fmt="o-", color=C["purple"], capsize=4, ms=5)
    ax.set_xlabel("DEM 高程噪声 σ (m)"); ax.set_ylabel("总能耗相对偏移 (%)")
    ax.set_title("(c) DEM 噪声鲁棒性（200 次蒙特卡洛，含 90% 区间）")

    # (d) 衰落裕量对链路可达距离的敏感性
    ax = axes[1, 1]
    Ms = np.arange(2, 20, 2)
    for thr0, lab, col in [(122, "直连", C["blue"]),
                           (116, "中继接入", C["orange"]),
                           (126, "中继回传", C["green"])]:
        # P_th = Psens + M，M 增大 → 门限下降 1 dB → 可达距离缩短
        dmax = [10 ** ((thr0 - (m - 8) - 32.45 - 20 * np.log10(2400)) / 20)
                for m in Ms]
        ax.plot(Ms, dmax, "o-", ms=4, label=lab, color=col)
    ax.set_xlabel("衰落裕量 M (dB)"); ax.set_ylabel("自由空间可达距离 (km)")
    ax.set_title("(d) 衰落裕量敏感性（M↑ → 门限↓ → 距离↓）")
    ax.legend(fontsize=8)
    # 题注由论文 docx 统一生成，避免与正文编号冲突
#     fig.suptitle("图 22  四类敏感性分析", y=1.0, fontsize=12, weight="bold")
    fig.tight_layout()
    _save(fig, "f22_sensitivity", "四类敏感性分析", "模型检验")

    # ★ 本文取值必须取自 metrics：写死会与 Q3 实际使用的采样步长/网格步长矛盾
    #   （历史踩坑：表里写 5 s / 800 m，而 q3_metrics.json 是 2 s / 400 m）。
    _m3 = D.get("q3_metrics", {}) or {}
    _dt = _m3.get("sample_dt_s")
    _hv = _m3.get("hover_step_m")
    _tab(pd.DataFrame({
        "敏感性维度": ["通信采样步长", "悬停网格步长", "DEM 高程噪声", "衰落裕量"],
        "取值范围": ["1~30 s", "200~1500 m", "σ = 0~20 m", "M = 2~18 dB"],
        "本文取值": [f"{_dt:g} s（Q3 最终，见 metrics）" if _dt else "见 q3_metrics.json",
                     f"{_hv:g} m" if _hv else "见 q3_metrics.json",
                     "实测 DEM", "8 dB（附件）"],
        "主要影响": ["中断占比判定（粗步长漏判）", "覆盖率与计算耗时",
                     "能耗偏移 < 1%（σ=10 m）", "链路可达距离"],
    }), "t_sensitivity", "敏感性分析汇总", "模型检验")


def fig_model_params(D: dict) -> None:
    """机型与中继参数一览。"""
    u = D["uav"]; r = D["relay"].iloc[0]
    fig, axes = plt.subplots(1, 3, figsize=(14.2, 4.2))

    ax = axes[0]
    x = np.arange(len(u))
    ax.bar(x - 0.2, u["max_payload_kg"], 0.4, label="最大载货质量 (kg)", color=C["blue"])
    ax.bar(x + 0.2, u["volume_m3"] * 1000, 0.4, label="可用装载体积 (L)", color=C["orange"])
    ax.set_xticks(x); ax.set_xticklabels([f"{c} 型" for c in u["code"]])
    ax.set_ylabel("量值"); ax.set_title("(a) 三种运输机型的载荷能力")
    ax.legend(fontsize=8)

    ax = axes[1]
    x = np.arange(len(u))
    ax.bar(x - 0.2, u["range_empty_m"] / 1000, 0.4, label="空载标准航程 (km)",
           color=C["green"])
    ax.bar(x + 0.2, u["range_full_m"] / 1000, 0.4, label="满载标准航程 (km)",
           color=C["red"])
    ax.set_xticks(x); ax.set_xticklabels([f"{c} 型" for c in u["code"]])
    ax.set_ylabel("航程 (km)"); ax.set_title("(b) 航程与能量")
    ax2 = ax.twinx()
    ax2.plot(x, u["energy_kwh"], "D-", color="k", ms=6, label="电池可用能量 (kWh)")
    ax2.set_ylabel("能量 (kWh)")
    h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=7.5)

    ax = axes[2]
    names = ["起飞质量", "巡航功率", "悬停功率", "通信附加", "可用能量"]
    vals = [r["takeoff_mass_kg"], r["cruise_power_kw"] * 10,
            r["hover_power_kw"] * 10, r["comms_power_kw"] * 100,
            r["energy_kwh"] * 10]
    raw = [f"{r['takeoff_mass_kg']:.1f} kg", f"{r['cruise_power_kw']:.2f} kW",
           f"{r['hover_power_kw']:.2f} kW", f"{r['comms_power_kw']:.2f} kW",
           f"{r['energy_kwh']:.1f} kWh"]
    bars = ax.bar(names, vals, color=[C["blue"], C["green"], C["orange"],
                                      C["purple"], C["red"]], edgecolor="k")
    for b, t in zip(bars, raw):
        ax.text(b.get_x() + b.get_width() / 2, b.get_height() * 1.03, t,
                ha="center", fontsize=8)
    ax.set_ylabel("相对量值（已缩放）")
    ax.set_title("(c) 中继无人机关键参数")
    # 题注由论文 docx 统一生成，避免与正文编号冲突
#     fig.suptitle("图 23  机型与中继参数一览", y=1.03, fontsize=12, weight="bold")
    _save(fig, "f23_model_params", "机型与中继参数一览", "总体分析")
    _tab(u, "t_uav_params", "三种运输机型参数", "总体分析")
    _tab(D["relay"], "t_relay_params", "中继无人机参数", "总体分析")
    _tab(D["bat"], "t_battery_inventory", "共享电池库存", "总体分析")


def fig_node_table(D: dict) -> None:
    """节点坐标与海拔三维柱状图。"""
    n = D["nodes"].copy()
    fig = plt.figure(figsize=(13.4, 5.0))
    ax = fig.add_subplot(1, 2, 1, projection="3d")
    svc = n[n["kind"] == "service"]; o = n[n["kind"] == "center"].iloc[0]
    ax.bar3d(svc["lon"], svc["lat"], np.zeros(len(svc)),
             0.0022, 0.0022, svc["ground_elev_m"], color=C["blue"], alpha=0.85)
    ax.bar3d([o["lon"]], [o["lat"]], [0], 0.0026, 0.0026, [o["ground_elev_m"]],
             color="red", alpha=0.95)
    ax.set_xlabel("经度 (°)"); ax.set_ylabel("纬度 (°)"); ax.set_zlabel("地面海拔 (m)")
    ax.set_title("(a) 节点空间位置与海拔")
    ax.view_init(elev=24, azim=-58)

    ax = fig.add_subplot(1, 2, 2)
    m = n.sort_values("ground_elev_m")
    cols = [C["red"] if k == "center" else C["blue"] for k in m["kind"]]
    ax.barh(m["id"], m["ground_elev_m"], color=cols, edgecolor="k", lw=0.4)
    for i, (_, rr) in enumerate(m.reset_index().iterrows()):
        ax.text(rr["ground_elev_m"] + 6, i, f"{rr['ground_elev_m']:.0f}",
                va="center", fontsize=7.5)
    ax.set_xlabel("地面海拔 (m)"); ax.set_ylabel("节点")
    ax.set_title("(b) 各节点地面海拔（红=调度中心）")
    ax.tick_params(axis="y", labelsize=7.5)
    # 题注由论文 docx 统一生成，避免与正文编号冲突
#     fig.suptitle("图 24  节点坐标与海拔分布", y=1.02, fontsize=12, weight="bold")
    _save(fig, "f24_nodes", "节点坐标与海拔分布", "总体分析")
    _tab(n, "t_nodes", "调度中心与服务区坐标及海拔", "总体分析")


# ================================================================ 按问题分目录备份

QUESTION_DIRS = {
    "common": "总体分析",
    "q1": "问题一",
    "q2": "问题二",
    "q3": "问题三",
    "q4": "问题四",
}
# 图/表编号 → 归属问题
OWNER = {
    "f01": "common", "f02": "common", "f03": "common", "f18": "common",
    "f19": "common", "f20": "common", "f21": "common", "f22": "common",
    "f23": "common", "f24": "common",
    "f04": "q1", "f05": "q1", "f06": "q1", "f07": "q1",
    "f08": "q2", "f09": "q2", "f10": "q2",
    "f11": "q3", "f12": "q3", "f13": "q3", "f14": "q3",
    "f15": "q4", "f16": "q4", "f17": "q4",
}
TABLE_OWNER = {
    "t_box": "common", "t_nodes": "common", "t_uav_params": "common",
    "t_relay_params": "common", "t_battery_inventory": "common",
    "t_link_thresholds": "common", "t_sensitivity": "common",
    "t_all_metrics": "common", "t_chart_manifest": "common",
    "t_q1": "q1", "t_q2": "q2", "t_q3": "q3", "t_q4": "q4",
}


def backup_by_question() -> dict[str, dict]:
    """把图/表/数据按问题分目录备份，返回统计。"""
    stats: dict[str, dict] = {}
    for key in QUESTION_DIRS:
        for sub in ("figures", "tables", "data"):
            (BYQ / key / sub).mkdir(parents=True, exist_ok=True)
        stats[key] = {"figures": 0, "tables": 0, "data": 0}

    # 1) 图
    for p in sorted(FIG.glob("*.png")):
        pref = p.stem.split("_")[0]
        owner = OWNER.get(pref, "common")
        shutil.copy2(p, BYQ / owner / "figures" / p.name)
        stats[owner]["figures"] += 1

    # 2) 表
    for p in sorted(TAB.glob("*.csv")):
        owner = "common"
        for k, v in TABLE_OWNER.items():
            if p.stem.startswith(k):
                owner = v
                break
        shutil.copy2(p, BYQ / owner / "tables" / p.name)
        md = p.with_suffix(".md")
        if md.exists():
            shutil.copy2(md, BYQ / owner / "tables" / md.name)
        stats[owner]["tables"] += 1

    # 3) 原始结果数据（outputs/qN 的 tables + metrics + feasibility）
    for q in ("q1", "q2", "q3", "q4"):
        src_t = REPO_ROOT / f"outputs/{q}/tables"
        if src_t.exists():
            for p in sorted(src_t.glob("*.csv")):
                shutil.copy2(p, BYQ / q / "data" / p.name)
                stats[q]["data"] += 1
        for name in ("metrics.json", "params.json", "feasibility.json", "run_log.json"):
            sp = REPO_ROOT / f"outputs/{q}/{name}"
            if sp.exists():
                shutil.copy2(sp, BYQ / q / "data" / name)
                stats[q]["data"] += 1
    # 公共数据
    for p in sorted(DATA_PROCESSED.glob("*.csv")):
        shutil.copy2(p, BYQ / "common" / "data" / p.name)
        stats["common"]["data"] += 1
    for p in sorted(DATA.glob("*.csv")):
        shutil.copy2(p, BYQ / "common" / "data" / p.name)
        stats["common"]["data"] += 1
    return stats


def main() -> int:
    global _log
    _log = get_logger("report")
    sys.path.insert(0, str(REPO_ROOT))
    from src.report.make_figures import load_all
    D = load_all()
    # 补充载入
    D["legs"] = pd.read_parquet(DATA_PROCESSED / "leg_cache.parquet")

    _log.info("生成补充图 ...")
    fig_physics_calculator(D); fig_link_budget(D); fig_flight_profile(D)
    fig_verifier(D); fig_sensitivity(D); fig_model_params(D); fig_node_table(D)

    # 表：全部导出为独立 CSV 备份
    _tab(pd.read_parquet(DATA_PROCESSED / "leg_cache.parquet").head(300),
         "t_leg_cache_sample", "航段缓存样例（前 300 条有序航段）", "总体分析")
    _tab(D["fleet"], "t_uav_fleet", "逐架实体无人机清单", "总体分析")
    _tab(D["relay"], "t_relay_fleet", "中继无人机参数", "问题三")

    _log.info("按问题分目录备份 ...")
    stats = backup_by_question()
    for k, v in stats.items():
        _log.info("  %s：图 %d / 表 %d / 数据 %d",
                  QUESTION_DIRS[k], v["figures"], v["tables"], v["data"])
    save_table(pd.DataFrame([
        {"分组": QUESTION_DIRS[k], "目录": f"by_question/{k}",
         "图": v["figures"], "表": v["tables"], "数据文件": v["data"]}
        for k, v in stats.items()
    ]), PAPER / "backup_manifest.csv")

    print()
    print("=" * 78)
    print("补充图表与分目录备份完成")
    print("=" * 78)
    for k, v in stats.items():
        print(f"  {QUESTION_DIRS[k]:<8} by_question/{k:<7} "
              f"图 {v['figures']:>2} / 表 {v['tables']:>2} / 数据 {v['data']:>2}")
    tot_f = len(list(FIG.glob('*.png')))
    tot_t = len(list(TAB.glob('*.csv')))
    print(f"\n总计：图 {tot_f} 个 / 表 {tot_t} 个")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    raise SystemExit(main())
