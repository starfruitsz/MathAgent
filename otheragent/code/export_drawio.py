"""把 `diagrams/*.drawio` 渲染成 PNG（替代 draw.io 桌面版导出）。

背景：`make_flowcharts.py` 只生成 `.drawio` 源文件；本机未安装 draw.io CLI，
但论文引用的是 PNG。本脚本直接解析 drawio XML 的几何与样式，
用 matplotlib 画成同版式 PNG，使"改数据 → 重跑 → PNG 同步"这条链闭合。

用法：
    python otheragent/code/export_drawio.py

实现要点（踩过的坑，改前请先读）：
1. **中文字体**：drawio 标签全是中文，matplotlib 默认 DejaVu Sans 无 CJK 字形，
   会画出"豆腐块"。且 matplotlib 的逐字回退**只在 `font.family` 为列表时生效**；
   写成 `font.sans-serif = [...]` 只会解析到第一个字体，`⇒⌈⌉∀−⁺⁻` 依旧缺失。
2. **标签是富文本**：`value` 里含 `<br>`（作者手工换行）、`<sub>/<sup>`（下标上标）。
   早期版本用 `re.sub(r"<[^>]+>", "", ...)` 一把梭，既丢了换行（文字挤成一行、
   横向溢出边框），又丢了上下标。这里改成真正的解析 + 分行 + 上下标排版。
3. **自适应**：按盒子几何量文字宽度，先按宽度折行，再整体缩字号直到
   宽高都放得下，保证文字永不越框。
"""

from __future__ import annotations

import html
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.font_manager import FontProperties  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DIA = ROOT / "diagrams"
FIG = ROOT / "figures"

#: 中文字体回退链。SimSun 供正文中文，Microsoft YaHei 补 `−`/`⁺⁻`，
#: DejaVu Sans 补 `⇒`/`⌈⌉`/`∀`。Linux 上退到 Noto/思源。
FONT_CHAIN = ["SimSun", "Microsoft YaHei", "Noto Sans CJK SC",
              "Source Han Sans SC", "DejaVu Sans"]
plt.rcParams.update({
    "font.family": FONT_CHAIN,
    "axes.unicode_minus": False,
})

#: 1 pt = 1/72 in；画布 100 数据单位 = 1 in ⇒ 1 pt = 100/72 数据单位
PT2U = 100.0 / 72.0

# drawio 源 → 论文引用的 PNG 名
MAP = {
    "f00_roadmap": "fig01_roadmap",
    "f01_flow": "fig02_flow_q1",
    "f02_flow": "fig03_flow_q2",
    "f03_flow": "fig04_flow_q3",
    "f04_flow": "fig05_flow_q4",
}

#: 会被"继承"的行内样式标签
_INLINE = {"b": "bold", "strong": "bold", "i": "italic", "em": "italic",
           "u": "underline"}
_TAG = re.compile(r"</?([a-zA-Z][a-zA-Z0-9]*)[^>]*>")


def _style(s: str) -> dict:
    out: dict[str, str] = {}
    for part in s.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _color(c: str | None, default: str) -> str:
    if not c or c in ("none", "default"):
        return default
    return "#" + c.lstrip("#") if not c.startswith("#") else c


# --------------------------------------------------------------------------
# 标签解析：HTML 片段 → 行 → [(文本, 样式集)]
# --------------------------------------------------------------------------
def parse_label(raw: str) -> list[list[tuple[str, frozenset[str]]]]:
    """把 drawio 的富文本标签拆成"行 → 若干带样式的文本片段"。

    `<br>` 换行；`<sub>/<sup>` 记上下标；`<b>/<i>/<u>` 记粗斜下划线；
    `<div>/<span>/<font>` 等纯容器标签忽略（只丢弃标签本身，保留内部文字）。
    """
    s = html.unescape(raw or "")
    lines: list[list[tuple[str, frozenset[str]]]] = [[]]
    stack: list[str] = []
    pos = 0
    for m in _TAG.finditer(s):
        chunk = s[pos:m.start()]
        if chunk:
            lines[-1].append((chunk, frozenset(stack)))
        pos = m.end()
        name = m.group(1).lower()
        closing = s[m.start() + 1] == "/"
        if name == "br":
            lines.append([])
            continue
        key = name if name in ("sub", "sup") else _INLINE.get(name)
        if key is None:                       # 容器/未知标签：忽略
            continue
        if closing:
            if key in stack:
                stack.remove(key)
        else:
            stack.append(key)
    tail = s[pos:]
    if tail:
        lines[-1].append((tail, frozenset(stack)))
    # 去掉空行（连续 <br> 或首尾换行），但至少保留一行
    keep = [ln for ln in lines if any(t.strip() for t, _ in ln)]
    return keep or [[]]


def _tokens(pieces: list[tuple[str, frozenset[str]]]) -> list[tuple[str, frozenset[str]]]:
    """把片段切成可换行的最小单元：CJK 逐字，ASCII 按词，空白独立成段。"""
    out: list[tuple[str, frozenset[str]]] = []
    for text, st in pieces:
        for tok in re.findall(r"[\u2e80-\u9fff\uff00-\uffef]|[^\s\u2e80-\u9fff\uff00-\uffef]+|\s+", text):
            out.append((tok, st))
    return out


# --------------------------------------------------------------------------
# 文本量测与排版
# --------------------------------------------------------------------------
class Meter:
    """借一个隐藏 Text artist + Agg renderer 量文字尺寸（数据单位）。

    必须走 `Text.get_window_extent` 而不是 `renderer.get_text_width_height_descent`：
    只有前者会经过 matplotlib 的字体回退逻辑，中英混排的宽度才是对的。
    """

    def __init__(self, fig, ax, W: float, H: float) -> None:
        fig.canvas.draw()
        self.renderer = fig.canvas.get_renderer()
        self.ax, self.W, self.H = ax, W, H
        self.scratch = ax.text(0, 0, "", fontsize=8, alpha=0)
        self._cache: dict[tuple[str, float, bool, bool], float] = {}
        self._fp: dict[tuple[float, bool, bool], FontProperties] = {}

    @staticmethod
    def _eff(size: float, st: frozenset[str]) -> float:
        """上下标按 0.74 倍字号排。"""
        return size * (0.74 if ("sub" in st or "sup" in st) else 1.0)

    def _props(self, size: float, st: frozenset[str]) -> FontProperties:
        key = (size, "bold" in st, "italic" in st)
        fp = self._fp.get(key)
        if fp is None:
            fp = FontProperties(family=FONT_CHAIN, size=size, weight=key[1] and "bold" or "normal",
                                style=key[2] and "italic" or "normal")
            self._fp[key] = fp
        return fp

    def width(self, txt: str, size: float, st: frozenset[str] = frozenset()) -> float:
        if not txt:
            return 0.0
        key = (txt, round(size, 3), "bold" in st, "italic" in st)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        self.scratch.set_text(txt)
        self.scratch.set_fontproperties(self._props(size, st))
        bb = self.scratch.get_window_extent(self.renderer)
        val = bb.width / self.ax.bbox.width * self.W
        self._cache[key] = val
        return val

    def fit(self, box_w: float, box_h: float, lines, base: float):
        """折行 + 缩字号，返回 (最终字号, 行高, 折行后的行列表)。"""
        avail_w = max(box_w - 8.0, 12.0)
        avail_h = max(box_h - 6.0, 10.0)
        size = base
        while True:
            lh = 1.34 * size * PT2U
            wrapped: list[list[tuple[str, frozenset[str]]]] = []
            widest = 0.0
            for pieces in lines:
                cur: list[tuple[str, frozenset[str]]] = []
                cur_w = 0.0
                for tok, st in _tokens(pieces):
                    if tok.isspace() and not cur:
                        continue
                    tw = self.width(tok, self._eff(size, st), st)
                    if cur and cur_w + tw > avail_w:
                        wrapped.append(cur)
                        widest = max(widest, cur_w)
                        cur, cur_w = [], 0.0
                        if tok.isspace():
                            continue
                    cur.append((tok, st))
                    cur_w += tw
                if cur:
                    wrapped.append(cur)
                    widest = max(widest, cur_w)
            total_h = len(wrapped) * lh
            if (widest <= avail_w and total_h <= avail_h) or size <= 4.5:
                return size, lh, wrapped
            size *= 0.94          # ★ 必须有这一步，否则放不下时会死循环


def _draw_label(ax, meter: Meter, b: dict) -> None:
    lines = parse_label(b["raw"])
    if not any(t.strip() for ln in lines for t, _ in ln):
        return
    base_pt = b["font"] * 0.78
    size, lh, wrapped = meter.fit(b["w"], b["h"], lines, base_pt)

    cx = b["x"] + b["w"] / 2
    cy = b["y"] + b["h"] / 2
    top = cy - len(wrapped) * lh / 2
    for i, pieces in enumerate(wrapped):
        baseline = top + i * lh + 0.80 * lh
        # 该行总宽（上下标按缩小字号计），用于整行居中
        wsum = sum(meter.width(t, meter._eff(size, st), st) for t, st in pieces)
        x = cx - wsum / 2
        for tok, st in pieces:
            is_sub, is_sup = "sub" in st, "sup" in st
            eff = meter._eff(size, st)
            # 画布 y 轴向下（ylim=H..0），所以"上标"取负偏移
            dy = (-0.32 * size * PT2U) if is_sup else (0.20 * size * PT2U if is_sub else 0.0)
            ax.text(x, baseline + dy, tok, ha="left", va="baseline", fontsize=eff,
                    fontproperties=meter._props(eff, st),
                    color="#1a1a1a", zorder=3)
            x += meter.width(tok, eff, st)


# --------------------------------------------------------------------------
def render(src: Path, dst_png: Path) -> tuple[int, int]:
    root = ET.parse(src).getroot()
    boxes, edges = [], []
    for c in root.findall(".//mxCell"):
        st = _style(c.get("style", ""))
        geo = c.find("mxGeometry")
        if geo is None:
            continue
        if c.get("edge") == "1":
            edges.append((c.get("source"), c.get("target")))
            continue
        x = float(geo.get("x", 0) or 0)
        y = float(geo.get("y", 0) or 0)
        w = float(geo.get("width", 0) or 0)
        h = float(geo.get("height", 0) or 0)
        if w <= 0 or h <= 0:
            continue
        boxes.append({
            "id": c.get("id"), "x": x, "y": y, "w": w, "h": h,
            "raw": c.get("value") or "",
            "fill": _color(st.get("fillColor"), "#ffffff"),
            "stroke": _color(st.get("strokeColor"), "#333333"),
            "font": float(st.get("fontSize", 16)),
            "bold": "1" in (st.get("fontStyle", "") or ""),
            "rounded": st.get("rounded") == "1" or st.get("shape") == "rounded",
        })

    W = max((b["x"] + b["w"] for b in boxes), default=1120) + 20
    H = max((b["y"] + b["h"] for b in boxes), default=800) + 20
    fig, ax = plt.subplots(figsize=(W / 100, H / 100), dpi=300)
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)
    ax.axis("off")
    ax.set_position([0, 0, 1, 1])

    by_id = {b["id"]: b for b in boxes}
    for b in boxes:
        ax.add_patch(FancyBboxPatch(
            (b["x"], b["y"]), b["w"], b["h"],
            boxstyle="round,pad=0,rounding_size=10" if b["rounded"] else "square,pad=0",
            linewidth=1.4, facecolor=b["fill"], edgecolor=b["stroke"], zorder=2))

    meter = Meter(fig, ax, W, H)
    for b in boxes:
        _draw_label(ax, meter, b)

    for sid, tid in edges:
        a, b = by_id.get(sid), by_id.get(tid)
        if not a or not b:
            continue
        x1, y1 = a["x"] + a["w"] / 2, a["y"] + a["h"]
        x2, y2 = b["x"] + b["w"] / 2, b["y"]
        if y2 < y1:                      # 反向（回流）箭头从侧面绕
            x1, y1 = a["x"], a["y"] + a["h"] / 2
            x2, y2 = b["x"] + b["w"], b["y"] + b["h"] / 2
        ax.add_patch(FancyArrowPatch(
            (x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=16,
            linewidth=1.3, color="#5a5a5a", zorder=1,
            connectionstyle="arc3,rad=0.0"))

    dst_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(dst_png, dpi=300, facecolor="white", bbox_inches="tight", pad_inches=0.06)
    plt.close(fig)
    return int(W), int(H)


def main() -> int:
    n = 0
    for stem, out in MAP.items():
        src = DIA / f"{stem}.drawio"
        if not src.exists():
            print(f"  ✗ 缺 {src.name}")
            continue
        w, h = render(src, FIG / f"{out}.png")
        print(f"  ✓ {stem}.drawio -> {out}.png  ({w}x{h})")
        n += 1
    print(f"共导出 {n} 张")
    return 0


if __name__ == "__main__":
    sys.exit(main())
