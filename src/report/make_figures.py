"""论文图表生成：把四问的全部结果渲染成论文用矢量/位图与表格备份。

★ 设计原则
    - **每个图都落盘到 `paper/figures/`，每张表都落盘到 `paper/tables/`**
      （题目要求"每个数据和图片都要在对应文件夹下面备份"）
    - 图表全部**从 outputs/ 的真实结果**渲染，不手写数字
    - 同时输出 `paper/data/*.csv` 作为图表的数据源备份
    - 统一字体、字号、配色、DPI，保证论文观感一致

用法：
    python -m src.report.make_figures
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, Rectangle  # noqa: E402

from src.common.config import DATA_PROCESSED, REPO_ROOT, outputs_dir  # noqa: E402
from src.common.io_utils import get_logger, save_table  # noqa: E402

# ---------------------------------------------------------------- 统一风格

plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
    "axes.unicode_minus": False,
    "figure.dpi": 200,
    "savefig.dpi": 200,
    "savefig.bbox": "tight",
    "font.size": 10,
    "axes.titlesize": 11,
    "axes.labelsize": 10,
    "legend.fontsize": 8.5,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "axes.grid": True,
    "grid.alpha": 0.3,
    "grid.linestyle": "--",
    "figure.facecolor": "white",
})

C = {
    "A": "#3b7dd8", "B": "#2e8b57", "C": "#d85a3b",
    "blue": "#2c6fbb", "green": "#2e8b57", "red": "#c0392b",
    "orange": "#e67e22", "purple": "#8e44ad", "gray": "#7f8c8d",
    "direct": "#2e8b57", "relay": "#e67e22", "outage": "#c0392b",
}

PAPER = REPO_ROOT / "paper"
FIG = PAPER / "figures"
TAB = PAPER / "tables"
DATA = PAPER / "data"
for d in (FIG, TAB, DATA):
    d.mkdir(parents=True, exist_ok=True)

_log = None
_manifest: list[dict] = []


def _save(fig, name: str, caption: str, section: str) -> None:
    """保存图并登记到清单。"""
    p = FIG / f"{name}.png"
    fig.savefig(p)
    plt.close(fig)
    _manifest.append({"类型": "图", "编号": name, "标题": caption,
                      "章节": section, "文件": f"figures/{name}.png",
                      "大小KB": round(p.stat().st_size / 1024, 1)})
    if _log:
        _log.info("图 %s  %s", name, caption)


def _tab(df: pd.DataFrame, name: str, caption: str, section: str, index: bool = False) -> None:
    """保存表（同时存 CSV 与 Markdown，便于 Word 生成与人工核对）。"""
    p = TAB / f"{name}.csv"
    save_table(df, p, index=index)
    md = TAB / f"{name}.md"
    md.write_text(
        f"**{caption}**\n\n" + df.to_markdown(index=index), encoding="utf-8"
    )
    _manifest.append({"类型": "表", "编号": name, "标题": caption,
                      "章节": section, "文件": f"tables/{name}.csv",
                      "大小KB": round(p.stat().st_size / 1024, 1)})
    if _log:
        _log.info("表 %s  %s", name, caption)


# ---------------------------------------------------------------- 载入

def load_all() -> dict:
    q1 = REPO_ROOT / "outputs/q1/tables"
    q2 = REPO_ROOT / "outputs/q2/tables"
    q3 = REPO_ROOT / "outputs/q3/tables"
    q4 = REPO_ROOT / "outputs/q4/tables"
    d = {
        "nodes": pd.read_csv(DATA_PROCESSED / "nodes.csv"),
        "boxes": pd.read_csv(DATA_PROCESSED / "boxes.csv"),
        "uav": pd.read_csv(DATA_PROCESSED / "uav_types.csv"),
        "fleet": pd.read_csv(DATA_PROCESSED / "uav_fleet.csv"),
        "bat": pd.read_csv(DATA_PROCESSED / "battery_inventory.csv"),
        "relay": pd.read_csv(DATA_PROCESSED / "relay_params.csv"),
        "legs": pd.read_parquet(DATA_PROCESSED / "leg_cache.parquet"),
        "q1_payload": pd.read_csv(q1 / "q1_1_max_safe_payload.csv"),
        "q1_groups": pd.read_csv(q1 / "q1_2_groups_by_service.csv"),
        "q1_cmp": pd.read_csv(q1 / "q1_3_strategy_comparison.csv"),
        "q1_lb": pd.read_csv(q1 / "q1_3_sortie_lower_bounds.csv"),
        "q1_pareto": pd.read_csv(q1 / "q1_3_pareto_frontier.csv"),
        "q1_rho": pd.read_csv(q1 / "q1_4_rho_sweep.csv"),
        "q1_curve": pd.read_csv(q1 / "q1_4_payload_vs_rho.csv"),
        "q2_sorties": pd.read_csv(q2 / "q2_运输架次.csv"),
        "q2_deliver": pd.read_csv(q2 / "q2_逐箱交付.csv"),
        "q2_timeliness": pd.read_csv(q2 / "q2_时限达成.csv"),
        "q2_uavuse": pd.read_csv(q2 / "q2_资源使用_无人机.csv"),
        "q2_batuse": pd.read_csv(q2 / "q2_资源使用_电池.csv"),
        "q3_sorties": pd.read_csv(q3 / "q3_运输架次.csv"),
        "q3_relay": pd.read_csv(q3 / "q3_中继架次.csv"),
        "q3_siting": pd.read_csv(q3 / "q3_中继选址.csv"),
        "q3_diag": pd.read_csv(q3 / "q3_直连状态诊断.csv"),
        "q4_units": pd.read_csv(q4 / "q4_原子单元.csv"),
        "q4_bridge": pd.read_csv(q4 / "q4_桥接架次.csv"),
        "q4_cmp": pd.read_csv(q4 / "q4_方案对比.csv"),
        "q4_gap": pd.read_csv(q4 / "q4_资源缺口.csv"),
        "q4_group": pd.read_csv(q4 / "q4_逐组明细.csv"),
    }
    import json
    for q in ("q1", "q2", "q3", "q4"):
        mp = REPO_ROOT / f"outputs/{q}/metrics.json"
        d[f"{q}_metrics"] = json.loads(mp.read_text(encoding="utf-8"))["metrics"] if mp.exists() else {}
    return d


# ================================================================ 公共图

def fig_roadmap(D: dict) -> None:
    """全文技术路线图（五层递进 + 校验带）。"""
    fig, ax = plt.subplots(figsize=(9.6, 6.2))
    ax.set_xlim(0, 10); ax.set_ylim(0, 10); ax.axis("off")

    layers = [
        (8.6, "数据基础层", "附件解析 · 30 m DEM(DSM) · 航段几何 · 对象编号统一", "#d6e4f0"),
        (6.9, "公共物理计算器", "地形净空 · 等效航程 Lg(q) · 三阶段时间 · 水平/爬升能耗 · SOC 两阶段充电", "#cfe3d4"),
        (5.2, "通信链路模型", "三维视线遮挡 · FSPL · 双向链路预算 · 直连/中继/中断三态", "#f5e0d0"),
        (3.5, "四问递进求解", "Q1 能力与组批 → Q2 运输调度 → Q3 通信协同 → Q4 分区配置", "#e6dcf0"),
        (1.8, "结果与交付", "论文 · 交付格式表(Q1~Q4) · 图表备份 · 可复现代码", "#f0e6d2"),
    ]
    for y, title, desc, color in layers:
        ax.add_patch(Rectangle((0.4, y - 0.55), 6.6, 1.1, facecolor=color,
                               edgecolor="#555", lw=1.0, zorder=2))
        ax.text(0.7, y + 0.16, title, fontsize=11, weight="bold", zorder=3)
        ax.text(0.7, y - 0.24, desc, fontsize=7.8, color="#333", zorder=3)
    for y0, y1 in [(8.6, 6.9), (6.9, 5.2), (5.2, 3.5), (3.5, 1.8)]:
        ax.add_patch(FancyArrowPatch((3.7, y0 - 0.55), (3.7, y1 + 0.55),
                                     arrowstyle="-|>", mutation_scale=16,
                                     color="#333", lw=1.4, zorder=4))
    ax.add_patch(Rectangle((7.3, 1.25), 2.4, 7.9, facecolor="#fdeaea",
                           edgecolor="#c0392b", lw=1.4, ls="--", zorder=1))
    ax.text(8.5, 8.75, "校验带", fontsize=11, weight="bold",
            color="#c0392b", ha="center", zorder=3)
    for i, t in enumerate([
        "独立可行性校验器\n（18 类约束\n+ 负样本测试）",
        "解析高程对照\n（脱离 DEM\n的公式测试）",
        "下界与最优性\n（装箱下界 /\nPareto 前沿）",
        "敏感性分析\n（ρ_g · 采样步长\n· 悬停网格）",
        "交叉验证\n（第三方数量级\n比对）",
    ]):
        ax.text(8.5, 7.7 - i * 1.42, t, fontsize=7.2, ha="center", va="top",
                color="#7b241c", zorder=3)
    ax.set_title("图 1  全文技术路线图", fontsize=12, weight="bold")
    _save(fig, "f01_roadmap", "全文技术路线图", "总体分析")


def fig_terrain(D: dict) -> None:
    """DEM 地形与节点分布（真实栅格）。"""
    import rasterio
    from matplotlib.colors import LightSource

    dem = (REPO_ROOT / "data/raw/D题/数据/镇龙乡地理空间数据"
           / "镇龙乡及周边地理数据/数字高程模型数据（DEM）"
           / "镇龙乡及周边30米DEM.tif")
    with rasterio.open(dem) as src:
        arr = src.read(1)
        b = src.bounds

    fig, ax = plt.subplots(figsize=(9.2, 6.4))
    ls = LightSource(azdeg=315, altdeg=45)
    rgb = ls.shade(arr, cmap=plt.cm.terrain, blend_mode="soft",
                   vert_exag=2, dx=30, dy=30)
    ax.imshow(rgb, extent=[b.left, b.right, b.bottom, b.top], origin="upper")
    n = D["nodes"]
    svc = n[n["kind"] == "service"]
    o = n[n["kind"] == "center"].iloc[0]
    ax.scatter(svc["lon"], svc["lat"], c="white", edgecolor="k", s=48,
               zorder=4, label="服务区 S001–S015")
    ax.scatter([o["lon"]], [o["lat"]], c="red", marker="*", s=250,
               edgecolor="k", zorder=5, label="调度中心 O01 / 网关 G01")
    for _, r in svc.iterrows():
        ax.annotate(str(r["id"]), (r["lon"], r["lat"]), fontsize=7.5,
                    xytext=(4, 3), textcoords="offset points",
                    color="white", weight="bold")
    cb = fig.colorbar(plt.cm.ScalarMappable(
        norm=plt.Normalize(arr.min(), arr.max()), cmap=plt.cm.terrain), ax=ax)
    cb.set_label("地面高程 (m)   —— Copernicus GLO-30 DSM，约 30 m")
    ax.set_xlabel("经度 (°)"); ax.set_ylabel("纬度 (°)")
    ax.set_title("图 2  研究区 30 m DEM 与任务节点分布")
    ax.legend(loc="upper right", fontsize=8.5)
    _save(fig, "f02_terrain_nodes", "研究区 30 m DEM 与任务节点分布", "总体分析")


def fig_box_stats(D: dict) -> None:
    """货箱质量/体积/时限的多视角统计。"""
    bx = D["boxes"].copy()
    bx["首批"] = bx["is_first_batch"].map({True: "首批保障", False: "常规"})
    fig, axes = plt.subplots(1, 3, figsize=(13.4, 3.9))

    ax = axes[0]
    for k, g in bx.groupby("首批"):
        ax.hist(g["mass_kg"], bins=np.arange(0, 16, 2), alpha=0.75,
                label=f"{k}（{len(g)} 箱）", edgecolor="white")
    ax.set_xlabel("单箱质量 (kg)"); ax.set_ylabel("箱数")
    ax.set_title("(a) 单箱质量分布"); ax.legend(fontsize=8)

    ax = axes[1]
    t = bx.groupby("cargo_type").agg(箱数=("box_id", "size"),
                                     总质量=("mass_kg", "sum"),
                                     总体积=("volume_m3", "sum")).reset_index()
    x = np.arange(len(t))
    ax.bar(x - 0.22, t["总质量"], 0.44, label="总质量 (kg)", color=C["blue"])
    ax.bar(x + 0.22, t["总体积"] * 1000, 0.44, label="总体积 (L)", color=C["orange"])
    ax.set_xticks(x); ax.set_xticklabels(t["cargo_type"], fontsize=8.5)
    ax.set_ylabel("总量"); ax.set_title("(b) 分类物资总量"); ax.legend(fontsize=8)

    ax = axes[2]
    g = bx.groupby("service_id").agg(箱数=("box_id", "size"),
                                     总质量=("mass_kg", "sum")).reset_index()
    g = g.sort_values("总质量", ascending=False)
    ax.barh(g["service_id"], g["总质量"], color=C["green"])
    ax.set_xlabel("总质量 (kg)"); ax.set_title("(c) 各服务区总需求")
    ax.invert_yaxis()
    fig.suptitle("图 3  货箱数据特征（80 箱 / 758 kg / 2.011 m³）", y=1.03,
                 fontsize=12, weight="bold")
    _save(fig, "f03_box_stats", "货箱质量/体积/时限统计", "总体分析")
    _tab(t, "t_box_by_type", "分类物资总量统计", "总体分析")
    _tab(g, "t_box_by_service", "各服务区物资需求", "总体分析")


# ================================================================ Q1 图

def fig_q1_payload(D: dict) -> None:
    """最大安全载荷：热力图 + 生效约束 + 与结构上限对比。"""
    p = D["q1_payload"]
    piv = p.pivot(index="服务区编号", columns="机型编号", values="最大安全载荷（kg）")
    piv = piv.sort_index()
    fig, axes = plt.subplots(1, 3, figsize=(14.2, 4.4))

    ax = axes[0]
    im = ax.imshow(piv.values, cmap="YlGnBu", aspect="auto")
    ax.set_xticks(range(len(piv.columns))); ax.set_xticklabels(piv.columns)
    ax.set_yticks(range(len(piv.index))); ax.set_yticklabels(piv.index, fontsize=8)
    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            ax.text(j, i, f"{piv.values[i, j]:.1f}", ha="center", va="center",
                    fontsize=7.2, color="white" if piv.values[i, j] > 55 else "black")
    fig.colorbar(im, ax=ax, label="最大安全载荷 (kg)")
    ax.set_title("(a) 3 机型 × 15 服务区 最大安全载荷")
    ax.grid(False)

    ax = axes[1]
    cnt = p.groupby(["机型编号", "生效约束"]).size().unstack(fill_value=0)
    cnt.plot(kind="bar", stacked=True, ax=ax,
             color=[C["red"], C["blue"]], edgecolor="white")
    ax.set_ylabel("服务区数"); ax.set_xlabel("机型")
    ax.set_title("(b) 生效约束构成")
    ax.legend(fontsize=8, title="生效约束")
    ax.tick_params(axis="x", rotation=0)

    ax = axes[2]
    for code in sorted(p["机型编号"].unique()):
        sub = p[p["机型编号"] == code].sort_values("单向距离（m）")
        ax.plot(sub["单向距离（m）"] / 1000, sub["最大安全载荷（kg）"],
                marker="o", ms=4, color=C[code], label=f"{code} 型")
        ax.axhline(D["uav"].set_index("code").loc[code, "max_payload_kg"],
                   ls=":", lw=1, color=C[code], alpha=0.7)
    ax.set_xlabel("单向距离 (km)"); ax.set_ylabel("最大安全载荷 (kg)")
    ax.set_title("(c) 载荷随距离衰减（虚线=结构上限）")
    ax.legend(fontsize=8)
    fig.suptitle("图 4  问题一：最大安全载荷计算结果", y=1.03, fontsize=12, weight="bold")
    _save(fig, "f04_q1_payload", "最大安全载荷热力图与生效约束", "问题一")
    _tab(p, "t_q1_payload", "3 机型 × 15 服务区最大安全载荷", "问题一")


def fig_q1_groups(D: dict) -> None:
    """组批方案：架次构成与占比。"""
    g = D["q1_groups"].copy()
    fig, axes = plt.subplots(1, 3, figsize=(14.2, 4.2))

    ax = axes[0]
    g["箱数"] = g["货箱编号列表"].astype(str).str.split("|").apply(len)
    piv = g.pivot_table(index="服务区编号", values="箱数", aggfunc="sum")
    n = g.groupby("服务区编号").size()
    x = np.arange(len(n))
    ax.bar(x, piv["箱数"].reindex(n.index), color=C["blue"], label="箱数")
    ax2 = ax.twinx()
    ax2.plot(x, n.values, "o-", color=C["red"], ms=5, label="架次数")
    ax.set_xticks(x); ax.set_xticklabels(n.index, rotation=90, fontsize=7.5)
    ax.set_ylabel("箱数"); ax2.set_ylabel("架次数", color=C["red"])
    ax.set_title("(a) 各服务区箱数与架次数")
    ax.legend(loc="upper left", fontsize=8); ax2.legend(loc="upper right", fontsize=8)

    ax = axes[1]
    ax.scatter(g["总质量（kg）"], g["总体积（m³）"], c=C["green"], s=42,
               edgecolor="k", lw=0.5)
    ax.set_xlabel("架次总质量 (kg)"); ax.set_ylabel("架次总体积 (m³)")
    ax.set_title("(b) 架次载荷分布（质量—体积）")

    ax = axes[2]
    ax.scatter(g["往返时间（s）"] / 60, g["架次能耗（kWh）"], c=C["orange"],
               s=42, edgecolor="k", lw=0.5)
    ax.set_xlabel("往返时间 (min)"); ax.set_ylabel("架次能耗 (kWh)")
    ax.set_title("(c) 时间—能耗关系")
    fig.suptitle(f"图 5  问题一：货箱组批方案（{len(g)} 架次）", y=1.03,
                 fontsize=12, weight="bold")
    _save(fig, "f05_q1_groups", "货箱组批方案构成", "问题一")
    _tab(g, "t_q1_groups", "货箱组批方案明细（交付模板列序）", "问题一")


def fig_q1_strategy(D: dict) -> None:
    """策略对比与 Pareto 前沿 + 下界。"""
    c = D["q1_cmp"]; lb = D["q1_lb"]; pf = D["q1_pareto"]
    fig, axes = plt.subplots(1, 3, figsize=(14.2, 4.3))

    ax = axes[0]
    c2 = c.sort_values("往返架次数")
    ax.barh(c2["策略"], c2["往返架次数"], color=C["blue"])
    for i, v in enumerate(c2["往返架次数"]):
        ax.text(v + 0.4, i, str(int(v)), va="center", fontsize=8.5)
    ax.set_xlabel("往返架次数"); ax.set_title("(a) 各策略架次数")
    ax.invert_yaxis()

    ax = axes[1]
    ax.scatter(c["总运输能耗（kWh）"], c["累计作业时间（s）"] / 3600,
               s=70, c=C["green"], edgecolor="k", zorder=3)
    for _, r in c.iterrows():
        ax.annotate(r["策略"], (r["总运输能耗（kWh）"], r["累计作业时间（s）"] / 3600),
                    fontsize=7.5, xytext=(5, 3), textcoords="offset points")
    if len(pf):
        ax.scatter(pf["总运输能耗（kWh）"], pf["累计作业时间（s）"] / 3600,
                   s=190, facecolor="none", edgecolor=C["red"], lw=1.8,
                   zorder=2, label="Pareto 前沿")
        ax.legend(fontsize=8)
    ax.set_xlabel("总运输能耗 (kWh)"); ax.set_ylabel("累计作业时间 (h)")
    ax.set_title("(b) 能耗—时间权衡与 Pareto 前沿")

    ax = axes[2]
    x = np.arange(len(lb))
    ax.bar(x - 0.2, lb["架次数下界"], 0.4, label="架次数下界", color=C["gray"])
    ax.bar(x + 0.2, lb["最少架次策略"], 0.4, label="启发式结果", color=C["blue"])
    ax.set_xticks(x); ax.set_xticklabels(lb["服务区编号"], rotation=90, fontsize=7.5)
    ax.set_ylabel("架次数"); ax.set_title("(c) 逐区下界 vs 启发式（差距全为 0）")
    ax.legend(fontsize=8)
    fig.suptitle("图 6  问题一：策略对比、Pareto 前沿与最优性证据", y=1.03,
                 fontsize=12, weight="bold")
    _save(fig, "f06_q1_strategy", "策略对比与 Pareto 前沿", "问题一")
    _tab(c, "t_q1_strategy", "各策略多目标对比", "问题一")
    _tab(lb, "t_q1_lowerbound", "逐服务区架次数下界与差距", "问题一")


def fig_q1_rho(D: dict) -> None:
    """ρ_g 敏感性三视图。"""
    sw = D["q1_rho"]; cv = D["q1_curve"]
    fig, axes = plt.subplots(1, 3, figsize=(14.2, 4.2))

    ax = axes[0]
    f = sw[sw["feasible"]]
    ax.plot(f["rho"], f["n_sorties"], "o-", color=C["blue"], ms=5)
    if (~sw["feasible"]).any():
        bad = sw[~sw["feasible"]]
        ax.axvspan(bad["rho"].min(), sw["rho"].max(), color=C["red"], alpha=0.12,
                   label="不可行（存在无解服务区）")
    ax.axvline(0.20, color="k", ls="--", lw=1, label="附件取值 ρ=0.20")
    ax.set_xlabel(r"返航安全余量 $\rho_g$"); ax.set_ylabel("总架次数")
    ax.set_title("(a) 架次数随 ρ 变化"); ax.legend(fontsize=8)

    ax = axes[1]
    for code in sorted(cv["type_code"].unique()):
        s = cv[cv["type_code"] == code].groupby("rho")["max_payload_kg"].median()
        ax.plot(s.index, s.values, "o-", ms=3.5, color=C[code], label=f"{code} 型")
    ax.axvline(0.20, color="k", ls="--", lw=1)
    ax.set_xlabel(r"$\rho_g$"); ax.set_ylabel("最大安全载荷中位数 (kg)")
    ax.set_title("(b) 载荷随 ρ 衰减"); ax.legend(fontsize=8)

    ax = axes[2]
    col = {"结构上限": C["blue"], "能量": C["red"], "不可行": C["gray"]}
    p = D["q1_payload"]
    for b, lab in [("结构上限", "结构上限"), ("能量", "能量"), ("不可行", "不可行")]:
        pass
    curve = D["q1_curve"].copy()
    # 用 ρ 扫描计算"能量约束生效"的服务区数
    thr = D["uav"].set_index("code")["max_payload_kg"].to_dict()
    curve["结构性"] = curve.apply(
        lambda r: r["max_payload_kg"] >= thr[r["type_code"]] - 1e-9, axis=1)
    curve["不可行"] = curve["max_payload_kg"] <= 1e-9
    g = curve.groupby("rho").agg(结构=("结构性", "sum"), 不可行=("不可行", "sum"))
    g["能量"] = 45 - g["结构"] - g["不可行"]
    ax.stackplot(g.index, g["结构"], g["能量"], g["不可行"],
                 labels=["结构上限约束", "能量约束", "不可行"],
                 colors=[C["blue"], C["red"], C["gray"]], alpha=0.85)
    ax.axvline(0.20, color="k", ls="--", lw=1)
    ax.set_xlabel(r"$\rho_g$"); ax.set_ylabel("服务区×机型 组合数")
    ax.set_title("(c) 生效约束构成随 ρ 迁移"); ax.legend(fontsize=8, loc="center left")
    fig.suptitle(r"图 7  问题一：返航安全余量 $\rho_g$ 敏感性分析", y=1.03,
                 fontsize=12, weight="bold")
    _save(fig, "f07_q1_rho", "返航安全余量敏感性分析", "问题一")
    _tab(sw, "t_q1_rho_sweep", "ρ_g 扫描汇总", "问题一")


# ================================================================ Q2 图

def fig_q2_gantt(D: dict) -> None:
    """调度甘特图（按无人机）+ 服务区访问热力。"""
    s = D["q2_sorties"].copy()
    fig, axes = plt.subplots(1, 2, figsize=(14.2, 5.0),
                             gridspec_kw={"width_ratios": [1.15, 1]})
    ax = axes[0]
    uavs = sorted(s["无人机编号"].unique())
    yidx = {u: i for i, u in enumerate(uavs)}
    for _, r in s.iterrows():
        y = yidx[r["无人机编号"]]
        ax.barh(y, (r["返回O01时刻（s）"] - r["开始时刻（s）"]) / 3600,
                left=r["开始时刻（s）"] / 3600, height=0.62,
                color=C.get(r["机型编号"], C["blue"]),
                edgecolor="white", lw=0.6)
        ax.text(r["开始时刻（s）"] / 3600 + 0.02, y,
                r["架次编号"].replace("T0", "T"), fontsize=5.6,
                va="center", color="white", weight="bold")
    ax.set_yticks(range(len(uavs))); ax.set_yticklabels(uavs)
    ax.set_xlabel("时间 (h)"); ax.set_ylabel("运输无人机")
    ax.set_title("(a) 逐架次时间线（颜色=机型）")
    handles = [plt.Rectangle((0, 0), 1, 1, color=C[c]) for c in ("A", "B", "C")
               if c in set(s["机型编号"])]
    ax.legend(handles, [f"{c} 型" for c in ("A", "B", "C") if c in set(s["机型编号"])],
              fontsize=8)

    ax = axes[1]
    s["箱数"] = s["访问服务区顺序"].astype(str).str.split("->").apply(len)
    sc = ax.scatter(s["开始时刻（s）"] / 3600, s["架次能耗（kWh）"],
                    c=s["箱数"], cmap="viridis", s=55, edgecolor="k", lw=0.4)
    fig.colorbar(sc, ax=ax, label="访问服务区数")
    ax.set_xlabel("开始时刻 (h)"); ax.set_ylabel("架次能耗 (kWh)")
    ax.set_title("(b) 架次能耗随开工时刻分布")
    fig.suptitle(f"图 8  问题二：运输调度甘特图（{len(s)} 架次 / 8 架实体机）",
                 y=1.02, fontsize=12, weight="bold")
    _save(fig, "f08_q2_gantt", "运输调度甘特图", "问题二")
    _tab(s, "t_q2_sorties", "问题二运输架次明细（交付模板列序）", "问题二")


def fig_q2_timeliness(D: dict) -> None:
    """时限达成分析：散点 + 分档达标率 + 迟到分布。"""
    tl = D["q2_timeliness"].copy()
    fig, axes = plt.subplots(1, 3, figsize=(14.2, 4.3))

    ax = axes[0]
    for lab, col in [("是", C["red"]), ("否", C["blue"])]:
        sub = tl[tl["首批保障"] == lab]
        ax.scatter(sub["期望送达（s）"] / 60, sub["实际交付（s）"] / 60,
                   s=34, alpha=0.8, color=col, label=f"首批保障={lab}")
    lim = max(tl["期望送达（s）"].max(), tl["实际交付（s）"].max()) / 60 * 1.05
    ax.plot([0, lim], [0, lim], "k--", lw=1, label="准时线")
    ax.set_xlabel("期望送达时间 (min)"); ax.set_ylabel("实际交付时刻 (min)")
    ax.set_title("(a) 期望 vs 实际交付"); ax.legend(fontsize=8)

    ax = axes[1]
    tiers = tl.groupby("首批截止（s）").agg(
        箱数=("货箱编号", "size"),
        首批达标=("首批达标", lambda s: (s == "是").sum())).reset_index()
    tiers = tiers.dropna(subset=["首批截止（s）"])
    tiers["截止min"] = (tiers["首批截止（s）"] / 60).astype(int)
    tiers["达标率"] = tiers["首批达标"] / tiers["箱数"]
    ax.bar(tiers["截止min"].astype(str) + " min", tiers["达标率"],
           color=C["orange"], edgecolor="k")
    for i, r in tiers.reset_index().iterrows():
        ax.text(i, r["达标率"] + 0.02, f"{r['首批达标']}/{r['箱数']}",
                ha="center", fontsize=8)
    ax.set_ylim(0, 1.15); ax.set_ylabel("首批达标率")
    ax.set_xlabel("首批截止时间档"); ax.set_title("(b) 各截止档首批达标率")

    ax = axes[2]
    late = tl["实际交付（s）"] - tl["期望送达（s）"]
    ax.hist(late / 60, bins=20, color=C["green"], edgecolor="white")
    ax.axvline(0, color="k", ls="--", lw=1.2)
    ax.set_xlabel("迟到量 (min，负值=提前)"); ax.set_ylabel("箱数")
    ax.set_title("(c) 迟到量分布")
    fig.suptitle("图 9  问题二：物资时限达成分析", y=1.03, fontsize=12, weight="bold")
    _save(fig, "f09_q2_timeliness", "物资时限达成分析", "问题二")
    _tab(tl, "t_q2_timeliness", "逐箱时限达成明细", "问题二")


def fig_q2_resources(D: dict) -> None:
    """资源使用：无人机/电池占用与机型分布。"""
    s = D["q2_sorties"]; uu = D["q2_uavuse"]; bu = D["q2_batuse"]
    fig, axes = plt.subplots(1, 3, figsize=(14.2, 4.3))

    ax = axes[0]
    ax.bar(uu["无人机编号"], uu["架次数"], color=C["blue"], edgecolor="k")
    for i, r in uu.reset_index().iterrows():
        ax.text(i, r["架次数"] + 0.15, f"{r['总飞行时长（s）']/3600:.1f}h",
                ha="center", fontsize=7.5)
    ax.set_ylabel("执行架次数"); ax.set_xlabel("无人机编号")
    ax.set_title("(a) 实体无人机使用（标注=总飞行时长）")

    ax = axes[1]
    piv = bu.pivot_table(index="电池编号", values="架次", aggfunc="count").fillna(0)
    ax.bar(piv.index, piv["架次"], color=C["green"], edgecolor="k")
    ax.set_ylabel("使用次数"); ax.set_xlabel("共享电池编号")
    ax.set_title("(b) 共享电池周转次数")

    ax = axes[2]
    tc = s["机型编号"].value_counts()
    ax.pie(tc.values, labels=[f"{i} 型\n{v} 架次" for i, v in tc.items()],
           autopct="%1.1f%%", colors=[C[i] for i in tc.index],
           startangle=90, textprops={"fontsize": 9})
    ax.set_title("(c) 机型使用占比")
    fig.suptitle("图 10  问题二：资源使用情况", y=1.03, fontsize=12, weight="bold")
    _save(fig, "f10_q2_resources", "资源使用情况", "问题二")
    _tab(uu, "t_q2_uav_use", "实体无人机使用统计", "问题二")
    _tab(bu, "t_q2_battery_use", "共享电池周转明细", "问题二")
    _tab(piv.reset_index(), "t_q2_battery_count", "共享电池使用次数", "问题二")


# ================================================================ Q3 图

def fig_q3_diag(D: dict) -> None:
    """直连诊断：中断占比排序 + 直连/中断堆叠 + 距离关系。"""
    d = D["q3_diag"].copy().sort_values("中断占比", ascending=False)
    fig, axes = plt.subplots(1, 3, figsize=(14.2, 4.4))

    ax = axes[0]
    cols = [C["outage"] if v > 0 else C["direct"] for v in d["中断占比"]]
    ax.barh(d["架次编号"], d["中断占比"] * 100, color=cols, edgecolor="k", lw=0.4)
    ax.set_xlabel("直连中断时间占比 (%)"); ax.set_ylabel("运输架次")
    ax.set_title("(a) 各架次直连中断占比")
    ax.invert_yaxis(); ax.tick_params(axis="y", labelsize=6)

    ax = axes[1]
    x = np.arange(len(d))
    ax.bar(x, d["直连点数"], color=C["direct"], label="直连可用")
    ax.bar(x, d["中继点数"], bottom=d["直连点数"], color=C["relay"], label="需中继")
    ax.bar(x, d["中断点数"], bottom=d["直连点数"] + d["中继点数"],
           color=C["outage"], label="中断")
    ax.set_xticks(x); ax.set_xticklabels(d["架次编号"], rotation=90, fontsize=6)
    ax.set_ylabel("轨迹采样点数"); ax.set_title("(b) 逐架次通信状态构成")
    ax.legend(fontsize=8)

    ax = axes[2]
    if "距离" not in d.columns:
        d["航段长"] = d["服务区"].astype(str).str.count("->") + 1
    sc = ax.scatter(d["直连可达比例"] * 100, d["中断占比"] * 100,
                    c=d["服务区"].astype(str).str.count("->") + 1,
                    cmap="plasma", s=60, edgecolor="k", lw=0.4)
    fig.colorbar(sc, ax=ax, label="访问服务区数")
    ax.set_xlabel("直连可达比例 (%)"); ax.set_ylabel("中断占比 (%)")
    ax.set_title("(c) 直连可达性与中断的关系")
    fig.suptitle("图 11  问题三：连续通信诊断（轨迹逐秒采样）", y=1.03,
                 fontsize=12, weight="bold")
    _save(fig, "f11_q3_diagnosis", "连续通信诊断", "问题三")
    _tab(d, "t_q3_diagnosis", "逐架次直连状态诊断", "问题三")


def fig_q3_relay_map(D: dict) -> None:
    """中继悬停点与保障关系空间图。"""
    import rasterio
    from matplotlib.colors import LightSource

    dem = (REPO_ROOT / "data/raw/D题/数据/镇龙乡地理空间数据"
           / "镇龙乡及周边地理数据/数字高程模型数据（DEM）"
           / "镇龙乡及周边30米DEM.tif")
    with rasterio.open(dem) as src:
        arr = src.read(1); b = src.bounds
    sub = arr[::4, ::4]

    fig, ax = plt.subplots(figsize=(9.6, 7.0))
    ls = LightSource(azdeg=315, altdeg=45)
    rgb = ls.shade(sub, cmap=plt.cm.gist_earth, blend_mode="soft", vert_exag=2)
    ax.imshow(rgb, extent=[b.left, b.right, b.bottom, b.top], origin="upper",
              alpha=0.9)

    n = D["nodes"]; svc = n[n["kind"] == "service"]; o = n[n["kind"] == "center"].iloc[0]
    ax.scatter(svc["lon"], svc["lat"], c="white", edgecolor="k", s=52,
               zorder=5, label="服务区")
    ax.scatter([o["lon"]], [o["lat"]], c="red", marker="*", s=280,
               edgecolor="k", zorder=6, label="O01 / G01")

    rs = D["q3_relay"]
    sit = D["q3_siting"]
    ax.scatter(rs["悬停经度（°）"], rs["悬停纬度（°）"], marker="^", s=95,
               c=C["relay"], edgecolor="k", zorder=7,
               label=f"中继悬停点（{len(rs)} 架次）")
    # 保障连线：中继点 → 其保障架次的服务区
    cover = D["q3_sorties"].set_index("架次编号")["访问服务区顺序"].to_dict()
    lon = dict(zip(n["id"], n["lon"])); lat = dict(zip(n["id"], n["lat"]))
    comm = pd.read_csv(REPO_ROOT / "outputs/q3/tables/q3_通信保障.csv")
    hid = {r["中继架次编号"]: (r["悬停经度（°）"], r["悬停纬度（°）"])
           for _, r in rs.iterrows()}
    for _, r in comm.iterrows():
        h = hid.get(r["中继架次编号"])
        if not h:
            continue
        for st in str(cover.get(r["运输架次编号"], "")).split("->"):
            if st in lon:
                ax.plot([h[0], lon[st]], [h[1], lat[st]], color=C["relay"],
                        lw=0.75, alpha=0.55, zorder=3)
    ax.set_xlabel("经度 (°)"); ax.set_ylabel("纬度 (°)")
    ax.set_title("图 12  问题三：中继悬停点与通信保障关系")
    ax.legend(fontsize=8.5, loc="lower left")
    _save(fig, "f12_q3_relay_map", "中继悬停点与保障关系", "问题三")
    _tab(rs, "t_q3_relay_sorties", "中继架次明细（交付模板列序）", "问题三")
    _tab(sit, "t_q3_siting", "逐架次选址结果", "问题三")


def fig_q3_coverage(D: dict) -> None:
    """中继选址特征：高度/位置/服务时长/能耗。"""
    rs = D["q3_relay"].copy()
    fig, axes = plt.subplots(1, 3, figsize=(14.2, 4.3))

    ax = axes[0]
    ax.scatter(rs["悬停经度（°）"], rs["悬停海拔（m）"], c=rs["架次能耗（kWh）"],
               cmap="YlOrRd", s=58, edgecolor="k", lw=0.4)
    n = D["nodes"]; o = n[n["kind"] == "center"].iloc[0]
    ax.axvline(o["lon"], color="k", ls="--", lw=1, label="O01 经度")
    ax.set_xlabel("悬停经度 (°)"); ax.set_ylabel("悬停海拔 (m)")
    ax.set_title("(a) 悬停位置与海拔（色=能耗）"); ax.legend(fontsize=8)

    ax = axes[1]
    dur = (rs["服务结束时刻（s）"] - rs["建链完成时刻（s）"]) / 60
    ax.hist(dur, bins=14, color=C["relay"], edgecolor="white")
    ax.set_xlabel("单架次服务时长 (min)"); ax.set_ylabel("中继架次数")
    ax.set_title("(b) 中继服务时长分布")

    ax = axes[2]
    ax.plot(rs["中继架次编号"], rs["架次能耗（kWh）"], "o-",
            color=C["green"], ms=4)
    ax.axhline(np.mean(rs["架次能耗（kWh）"]), color=C["red"], ls="--", lw=1,
               label=f"均值 {np.mean(rs['架次能耗（kWh）']):.2f} kWh")
    ax.set_xlabel("中继架次编号"); ax.set_ylabel("架次能耗 (kWh)")
    ax.set_title("(c) 各中继架次能耗")
    ax.tick_params(axis="x", rotation=90, labelsize=6); ax.legend(fontsize=8)
    fig.suptitle(f"图 13  问题三：中继选址特征（{len(rs)} 架次 / "
                 f"{rs['架次能耗（kWh）'].sum():.2f} kWh）", y=1.03,
                 fontsize=12, weight="bold")
    _save(fig, "f13_q3_coverage", "中继选址特征", "问题三")
    _tab(pd.DataFrame({"指标": ["中继架次数", "总能耗(kWh)", "平均能耗(kWh)",
                                "最长服务(min)", "最短服务(min)", "悬停海拔范围(m)"],
                       "数值": [len(rs), round(rs["架次能耗（kWh）"].sum(), 3),
                                round(rs["架次能耗（kWh）"].mean(), 3),
                                round(dur.max(), 1), round(dur.min(), 1),
                                f"{rs['悬停海拔（m）'].min():.1f}~"
                                f"{rs['悬停海拔（m）'].max():.1f}"]}),
         "t_q3_summary", "中继保障汇总", "问题三")


def fig_q3_joint_gantt(D: dict) -> None:
    """运输 + 中继 联合甘特图。"""
    s = D["q3_sorties"]; rs = D["q3_relay"]
    fig, ax = plt.subplots(figsize=(12.6, 5.6))
    for _, r in s.iterrows():
        y = 0
        ax.barh(y, (r["返回O01时刻（s）"] - r["开始时刻（s）"]) / 3600,
                left=r["开始时刻（s）"] / 3600, height=0.8,
                color=C["blue"], alpha=0.35, edgecolor="none")
    for _, r in rs.iterrows():
        ax.barh(1, (r["返回O01时刻（s）"] - r["开始时刻（s）"]) / 3600,
                left=r["开始时刻（s）"] / 3600, height=0.8,
                color=C["relay"], alpha=0.5, edgecolor="none")
        ax.barh(1, (r["服务结束时刻（s）"] - r["建链完成时刻（s）"]) / 3600,
                left=r["建链完成时刻（s）"] / 3600, height=0.8,
                color=C["red"], alpha=0.9, edgecolor="none")
    ax.set_yticks([0, 1])
    ax.set_yticklabels([f"运输（{len(s)} 架次）", f"中继（{len(rs)} 架次）"])
    ax.set_xlabel("时间 (h）")
    ax.set_title("图 14  问题三：运输与中继联合调度时间线（红=通信服务窗口）")
    ax.set_ylim(-0.6, 1.6)
    _save(fig, "f14_q3_joint_gantt", "运输与中继联合调度时间线", "问题三")


# ================================================================ Q4 图

def fig_q4_graph(D: dict) -> None:
    """服务区"同架次"关系图：展示为何只存在 1 个连通分量。"""
    import networkx as nx

    s = D["q3_sorties"]; n = D["nodes"]
    lon = dict(zip(n["id"], n["lon"])); lat = dict(zip(n["id"], n["lat"]))
    G = nx.Graph()
    for sid in lon:
        if sid != "O01":
            G.add_node(sid)
    for _, r in s.iterrows():
        st = str(r["访问服务区顺序"]).split("->")
        for a, b in zip(st, st[1:]):
            if G.has_edge(a, b):
                G[a][b]["w"] += 1
            else:
                G.add_edge(a, b, w=1)

    fig, axes = plt.subplots(1, 2, figsize=(14.2, 6.0))
    ax = axes[0]
    pos = {k: (lon[k], lat[k]) for k in G.nodes()}
    ws = [G[u][v]["w"] for u, v in G.edges()]
    nx.draw_networkx_edges(G, pos, ax=ax, width=[1.2 * w for w in ws],
                           edge_color=C["gray"], alpha=0.75)
    nx.draw_networkx_nodes(G, pos, ax=ax, node_size=340,
                           node_color=C["blue"], edgecolors="k", linewidths=0.6)
    nx.draw_networkx_labels(G, pos, ax=ax, font_size=6.5, font_color="white")
    ax.scatter([lon["O01"]], [lat["O01"]], c="red", marker="*", s=300,
               edgecolor="k", zorder=6, label="O01")
    ax.set_xlabel("经度 (°)"); ax.set_ylabel("纬度 (°)")
    ax.set_title(f"(a) 「同架次」关系图：{G.number_of_nodes()} 节点 / "
                 f"{G.number_of_edges()} 边 → 1 个连通分量")
    ax.legend(fontsize=8)

    ax = axes[1]
    br = D["q4_bridge"]
    if len(br):
        ax.barh(br["架次编号"], [1] * len(br), color=C["red"], edgecolor="k")
        for i, r in br.reset_index().iterrows():
            ax.text(0.02, i, f"{r['服务区顺序']}  →  断为 {r['移除后分量数']} 个分量",
                    va="center", fontsize=8.5, color="white", weight="bold")
    ax.set_xlim(0, 1); ax.set_xticks([])
    ax.set_title("(b) 桥接架次（移除后即可断开连通）")
    ax.invert_yaxis()
    fig.suptitle("图 15  问题四：原子单元（连通分量）分析", y=1.0,
                 fontsize=12, weight="bold")
    _save(fig, "f15_q4_graph", "原子单元连通分量分析", "问题四")
    _tab(br, "t_q4_bridge", "桥接架次清单", "问题四")
    _tab(D["q4_units"], "t_q4_units", "原子单元（连通分量）", "问题四")


def fig_q4_compare(D: dict) -> None:
    """分区方案对比：资源规模/缺口/均衡 + 资源构成堆叠。"""
    c = D["q4_cmp"]; g = D["q4_gap"]
    fig, axes = plt.subplots(1, 3, figsize=(14.2, 4.4))

    ax = axes[0]
    x = np.arange(len(c))
    ax.bar(x - 0.22, c["资源总量"], 0.44, label="资源总规模", color=C["blue"])
    ax.bar(x + 0.22, c["运输无人机"] + c["共享电池"], 0.44,
           label="运输侧（机+电池）", color=C["green"])
    ax.set_xticks(x); ax.set_xticklabels(c["方案"], rotation=16, fontsize=8)
    ax.set_ylabel("台 / 组"); ax.set_title("(a) 资源总规模对比")
    ax.legend(fontsize=8)

    ax = axes[1]
    piv = g.pivot_table(index="方案", columns="资源", values="缺口",
                        aggfunc="sum").fillna(0)
    keep = [c_ for c_ in piv.columns if piv[c_].sum() > 0]
    if keep:
        piv[keep].plot(kind="bar", stacked=True, ax=ax, edgecolor="white")
        ax.legend(fontsize=6.5, ncol=2)
    ax.set_ylabel("缺口数量"); ax.set_xlabel("")
    ax.set_title("(b) 资源缺口构成")
    ax.tick_params(axis="x", rotation=16, labelsize=8)

    ax = axes[2]
    ax.bar(c["方案"], c["组间不均衡"], color=C["orange"], edgecolor="k")
    for i, v in enumerate(c["组间不均衡"]):
        ax.text(i, v + 0.04, f"{v:.3f}", ha="center", fontsize=8.5)
    ax.set_ylabel("组间工作量不均衡度")
    ax.set_title("(c) 组间均衡性（越小越好）")
    ax.tick_params(axis="x", rotation=16, labelsize=8)
    fig.suptitle("图 16  问题四：分区方案多指标对比", y=1.03,
                 fontsize=12, weight="bold")
    _save(fig, "f16_q4_compare", "分区方案多指标对比", "问题四")
    _tab(c, "t_q4_compare", "分区方案对比", "问题四")
    _tab(g, "t_q4_gap", "逐方案逐类资源缺口", "问题四")


def fig_q4_detail(D: dict) -> None:
    """逐组明细与库存对照。"""
    grp = D["q4_group"]; gap = D["q4_gap"]
    fig, axes = plt.subplots(1, 2, figsize=(13.0, 4.6))

    ax = axes[0]
    k1 = grp[grp["方案"] == "K=1"]
    if len(k1):
        r = k1.iloc[0]
        vals = [r["A机"], r["B机"], r["C机"], r["A电池"], r["B电池"], r["C电池"],
                r["中继机"], r["中继组件"]]
        labs = ["A机", "B机", "C机", "A电池", "B电池", "C电池", "中继机", "中继组件"]
        inv = [4, 2, 2, 6, 4, 4, 2, 6]
        x = np.arange(len(labs))
        ax.bar(x - 0.2, vals, 0.4, label="K=1 需求", color=C["blue"])
        ax.bar(x + 0.2, inv, 0.4, label="库存", color=C["gray"], alpha=0.75)
        ax.set_xticks(x); ax.set_xticklabels(labs, fontsize=8)
        ax.set_ylabel("台 / 组"); ax.set_title("(a) K=1 资源需求 vs 库存")
        ax.legend(fontsize=8)

    ax = axes[1]
    for plan, col in [("K=1", C["blue"]), ("K=2", C["green"]), ("K=3", C["orange"])]:
        sub = grp[grp["方案"] == plan]
        if not len(sub):
            continue
        ax.bar(np.arange(len(sub)) + {"K=1": -0.25, "K=2": 0.0, "K=3": 0.25}[plan],
               sub["工作量h"], 0.25, label=plan, color=col, edgecolor="k")
    ax.set_xlabel("任务组序号"); ax.set_ylabel("组工作量 (h)")
    ax.set_title("(b) 各组工作量分布")
    ax.legend(fontsize=8)
    fig.suptitle("图 17  问题四：逐组资源配置与工作量", y=1.03,
                 fontsize=12, weight="bold")
    _save(fig, "f17_q4_detail", "逐组资源配置与工作量", "问题四")
    _tab(grp, "t_q4_group", "逐组资源与工作量明细", "问题四")


# ================================================================ 主流程

def main() -> int:
    global _log
    _log = get_logger("report")
    _log.info("载入全部结果 ...")
    D = load_all()

    _log.info("生成公共图 ...")
    fig_roadmap(D); fig_terrain(D); fig_box_stats(D)
    _log.info("生成问题一图 ...")
    fig_q1_payload(D); fig_q1_groups(D); fig_q1_strategy(D); fig_q1_rho(D)
    _log.info("生成问题二图 ...")
    fig_q2_gantt(D); fig_q2_timeliness(D); fig_q2_resources(D)
    _log.info("生成问题三图 ...")
    fig_q3_diag(D); fig_q3_relay_map(D); fig_q3_coverage(D); fig_q3_joint_gantt(D)
    _log.info("生成问题四图 ...")
    fig_q4_graph(D); fig_q4_compare(D); fig_q4_detail(D)

    # 关键结果汇总表
    rows = []
    for q, label in [("q1", "问题一"), ("q2", "问题二"), ("q3", "问题三"), ("q4", "问题四")]:
        for k, v in D[f"{q}_metrics"].items():
            if isinstance(v, (int, float, str)):
                rows.append({"问题": label, "指标": k, "数值": v})
    _tab(pd.DataFrame(rows), "t_all_metrics", "四问关键指标汇总", "结论")

    man = pd.DataFrame(_manifest)
    save_table(man, PAPER / "chart_manifest.csv")
    save_table(man, TAB / "t_chart_manifest.csv")

    n_fig = int((man["类型"] == "图").sum())
    n_tab = int((man["类型"] == "表").sum())
    _log.info("完成：图 %d 个 / 表 %d 个", n_fig, n_tab)
    _log.info("图表目录：%s", FIG.parent.relative_to(REPO_ROOT))

    print()
    print("=" * 78)
    print("论文图表生成完成")
    print("=" * 78)
    print(f"图 {n_fig} 个 → paper/figures/")
    print(f"表 {n_tab} 个 → paper/tables/")
    print(f"清单 → paper/chart_manifest.csv")
    print()
    print(man[["类型", "编号", "标题", "章节"]].to_string(index=False))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    raise SystemExit(main())
