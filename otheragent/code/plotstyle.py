# -*- coding: utf-8 -*-
"""全局统一绘图样式与数据加载（全论文所有图共用）。

约定
----
* 中文字体 **SimSun**（宋体），保证不出现方框乱码；
* 全局 DPI ≥ 300，导出 PNG（论文插图）+ PDF（矢量备份）；
* 一套调色板贯穿全篇，同族同色；
* 所有图统一保存到 `figures/`，文件名 `figNN_slug.png`。
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
FIG = ROOT / "figures"
TAB = ROOT / "tables"
DAT = ROOT / "data"
FIG.mkdir(exist_ok=True)

# ---------------------------------------------------------------- 调色板
C_BLUE = "#3b6ea5"
C_ORANGE = "#e08a3c"
C_TEAL = "#4f9d8f"
C_PURPLE = "#9b6fb0"
C_RED = "#c0504d"
C_GRAY = "#8a97a3"
C_GOLD = "#c9a227"

PALETTE = [C_BLUE, C_ORANGE, C_TEAL, C_PURPLE, C_RED, C_GRAY, C_GOLD]
SEQ = "viridis"
DIV = "RdBu_r"

#: 机型固定配色（全篇一致）
TYPE_COLOR = {"A": C_BLUE, "B": C_ORANGE, "C": C_TEAL}
#: 生效约束固定配色
BIND_COLOR = {"结构上限": C_BLUE, "能量": C_RED, "体积": C_GOLD}


#: 画布缩放系数。图最终按 0.98\textwidth（≈6.3 in）排入 A4 版面，
#: 若在 11.6 in 的画布上作图，缩印后 7 pt 的字只剩约 4 pt，不可读。
#: 统一把画布缩到 ~0.72 倍，使缩印比例接近 0.8，字号才是纸面真实字号。
FS = 0.72


def fs(size: tuple[float, float]) -> tuple[float, float]:
    """按 FS 缩放的 figsize（保持字号不变 ⇒ 纸面字号变大）。用法：figsize=fs((11.6, 5.6))"""
    w, h = size
    return (w * FS, h * FS)


def setup() -> None:
    """设定全局 rcParams。每张图开画前调用一次。"""
    plt.rcParams.update({
        "font.sans-serif": ["SimSun", "SimHei", "Microsoft YaHei"],
        "font.family": "sans-serif",
        "axes.unicode_minus": False,          # 负号正常显示
        "mathtext.fontset": "stix",           # 数学符号用 STIX，与宋体协调
        "figure.dpi": 120,
        "savefig.dpi": 330,                   # ≥300
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.05,
        "axes.titlesize": 11,
        "axes.labelsize": 10,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "legend.fontsize": 9,
        "axes.grid": True,
        "grid.alpha": 0.28,
        "grid.linewidth": 0.6,
        "axes.axisbelow": True,
        "axes.edgecolor": "#4a4a4a",
        "axes.linewidth": 0.8,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "legend.frameon": True,
        "legend.framealpha": 0.92,
        "legend.edgecolor": "#cccccc",
    })


_CMAP: set[str] | None = None


def _simsun_chars() -> set[str]:
    """SimSun 可渲染的字符集合（用于缺字自检）。"""
    global _CMAP
    if _CMAP is None:
        from matplotlib import font_manager as fm
        path = fm.findfont(fm.FontProperties(family="SimSun"))
        from matplotlib.ft2font import FT2Font
        _CMAP = set(FT2Font(path).get_charmap().keys())
    return _CMAP


def check_glyphs(fig) -> list[str]:
    """扫描图内所有文本，报出 SimSun 无法渲染的字符（会显示成方框）。"""
    cmap = _simsun_chars()
    bad: set[str] = set()
    for t in fig.findobj(match=lambda o: hasattr(o, "get_text")):
        try:
            s = t.get_text()
        except Exception:
            continue
        for ch in s or "":
            if ch in "\n\t " or ord(ch) < 128:
                continue
            if ord(ch) not in cmap:
                bad.add(ch)
    if bad:
        print(f"    ⚠ 缺字（会显示为方框）: {' '.join(sorted(bad))} "
              f"→ {' '.join(f'U+{ord(c):04X}' for c in sorted(bad))}")
    return sorted(bad)


def save(fig, name: str, also_pdf: bool = True) -> None:
    """保存到 figures/<name>.png（并可选导出同名 PDF 矢量图）。"""
    check_glyphs(fig)
    png = FIG / f"{name}.png"
    fig.savefig(png)
    if also_pdf:
        fig.savefig(FIG / f"{name}.pdf")
    plt.close(fig)
    print(f"  ✓ {name}.png")


def panel_label(ax, text: str) -> None:
    """子图 (a)(b)(c) 标注，统一放在左上角外侧。"""
    ax.set_title(text, loc="left", fontsize=10.5, fontweight="bold", pad=6)


# ---------------------------------------------------------------- 数据加载
def load(name: str) -> pd.DataFrame:
    """读 tables/<name>.csv。"""
    return pd.read_csv(TAB / f"{name}.csv")


def load_data(name: str) -> pd.DataFrame:
    """读 data/<name>.csv。"""
    return pd.read_csv(DAT / f"{name}.csv")


def metrics(q: int) -> dict:
    """读 data/q<N>_metrics.json 的 metrics 段。"""
    p = DAT / f"q{q}_metrics.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    return d.get("metrics", d)


def params(q: int) -> dict:
    p = DAT / f"q{q}_params.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    return d.get("params", d)


def uav_types() -> pd.DataFrame:
    return load_data("uav_types").set_index("code")


def legs() -> pd.DataFrame:
    """完整 240 条有序航段（仓库中名为 _sample，实为全量）。"""
    return load("t_leg_cache_sample")


def nodes() -> pd.DataFrame:
    return load_data("nodes")


def boxes() -> pd.DataFrame:
    return load_data("boxes")
