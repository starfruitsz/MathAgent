# -*- coding: utf-8 -*-
"""生成四张"问题求解流程图"的 .drawio（手写 XML，路径 B）。

风格遵循 paper-diagram/references/authoring.md：
  · 画布固定、列基线固定、纵向步距固定；
  · 中文一律手动断行（行高 = 字号 + 3）；
  · 连接器端点离盒边 1px；
  · 分支画成"侧栏盒 + 回流箭头"，不画斜线。
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "diagrams"

# ---------------------------------------------------------------- 版式常量
W_CANVAS = 1120
X_MAIN, W_MAIN = 310, 420          # 主列
X_LEFT, W_LEFT = 50, 230           # 左侧注释
X_RIGHT, W_RIGHT = 760, 270        # 右侧分支盒
FONT = 16
LINE = 19
GAP = 44                           # 主列纵向箭头长度
TOP = 104                          # 首个盒子的 y

C_BLUE = "#eef6fd", "#3b547f", "#1f3f6b"
C_ORANGE = "#fcead9", "#c08b5c", "#7b5530"
C_PURPLE = "#e5dfeb", "#9b979f", "#7f5faf"
C_TEAL = "#dbeef4", "#668d89", "#5f8484"
C_GRAY = "#f2f4f6", "#8a97a3", "#6b7684"


_SUB = re.compile(r"_\{([^}]*)\}")
_SUP = re.compile(r"\^\{([^}]*)\}")


def esc(t: str) -> str:
    """先转义原文，再解析排版标记。

    源文本约定（都是在转义**之后**才生效，所以原文里的 < > 不会被吃）：
        \\n        → 换行
        _{...}    → 下标
        ^{...}    → 上标
    """
    out = html.escape(t, quote=True).replace("\n", "&lt;br&gt;")
    out = _SUB.sub(lambda m: f"&lt;sub&gt;{m.group(1)}&lt;/sub&gt;", out)
    out = _SUP.sub(lambda m: f"&lt;sup&gt;{m.group(1)}&lt;/sup&gt;", out)
    return out


def box_style(fill: str, stroke: str, rounded: int = 1, arc: int = 8) -> str:
    return (f"rounded={rounded};arcSize={arc};whiteSpace=wrap;html=1;"
            f"fillColor={fill};strokeColor={stroke};strokeWidth=1;"
            f"fontSize={FONT};fontStyle=1;fontColor=#262626;"
            f"fontFamily=Microsoft YaHei,PingFang SC,Helvetica;"
            f"align=center;verticalAlign=middle;")


def diamond_style(fill: str, stroke: str) -> str:
    return (f"rhombus;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};"
            f"strokeWidth=1;fontSize={FONT};fontStyle=1;fontColor=#262626;"
            f"fontFamily=Microsoft YaHei,PingFang SC,Helvetica;"
            f"align=center;verticalAlign=middle;")


def n_lines(text: str) -> int:
    return text.count("\n") + 1


def label_style() -> str:
    return (f"text;html=1;strokeColor=none;fillColor=none;align=center;"
            f"verticalAlign=middle;whiteSpace=wrap;fontSize={FONT - 2};"
            f"fontStyle=2;fontColor=#4a4a4a;"
            f"fontFamily=Microsoft YaHei,PingFang SC,Helvetica;")


def edge_style(color: str, width: int = 2) -> str:
    return (f"edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=block;"
            f"endFill=1;endSize=6;strokeColor={color};strokeWidth={width};")


class Builder:
    def __init__(self, title: str):
        self.title = title
        self.cells: list[str] = []
        self.y = TOP
        self.ids = 0

    def _nid(self, prefix: str) -> str:
        self.ids += 1
        return f"{prefix}{self.ids}"

    def add(self, xml: str) -> None:
        self.cells.append(xml)

    def vbox(self, x: int, y: int, w: int, h: int, text: str, pal, ident: str) -> str:
        fill, stroke, _ = pal
        self.add(f'<mxCell id="{ident}" value="{esc(text)}" '
                 f'style="{box_style(fill, stroke)}" vertex="1" parent="1">'
                 f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
        return ident

    def vdia(self, x: int, y: int, w: int, h: int, text: str, pal, ident: str) -> str:
        fill, stroke, _ = pal
        self.add(f'<mxCell id="{ident}" value="{esc(text)}" '
                 f'style="{diamond_style(fill, stroke)}" vertex="1" parent="1">'
                 f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
        return ident

    def vlabel(self, x: int, y: int, w: int, h: int, text: str, ident: str) -> str:
        self.add(f'<mxCell id="{ident}" value="{esc(text)}" style="{label_style()}" '
                 f'vertex="1" parent="1">'
                 f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
        return ident

    def edge(self, x1: int, y1: int, x2: int, y2: int, color: str,
             ident: str, pts: list[tuple[int, int]] | None = None, label: str = "") -> str:
        arr = ""
        if pts:
            inner = "".join(f'<mxPoint x="{px}" y="{py}"/>' for px, py in pts)
            arr = f'<Array as="points">{inner}</Array>'
        val = esc(label) if label else ""
        self.add(f'<mxCell id="{ident}" value="{val}" style="{edge_style(color)}" '
                 f'edge="1" parent="1"><mxGeometry relative="1" as="geometry">'
                 f'<mxPoint x="{x1}" y="{y1}" as="sourcePoint"/>'
                 f'<mxPoint x="{x2}" y="{y2}" as="targetPoint"/>{arr}'
                 f'</mxGeometry></mxCell>')
        return ident


def render(spec: dict, filename: str) -> None:
    b = Builder(spec["title"])
    cx = X_MAIN + W_MAIN // 2

    # 标题条
    b.add(f'<mxCell id="title" value="{esc(spec["title"])}" '
          f'style="{box_style("#e8edf4", "#3b547f", 0)}" vertex="1" parent="1">'
          f'<mxGeometry x="50" y="30" width="1020" height="48" as="geometry"/></mxCell>')

    y = TOP
    prev_bottom: int | None = None
    prev_center = cx
    pal_idx = 0

    for step in spec["steps"]:
        kind = step["t"]
        text = step["text"]
        pal = [C_BLUE, C_ORANGE, C_TEAL, C_PURPLE, C_GRAY][pal_idx % 5]
        pal_idx += 1

        if kind == "dec":
            w, h = 260, 104
            x = cx - w // 2
            ident = b.vdia(x, y, w, h, text, pal, b._nid("d"))
            if prev_bottom is not None:
                b.edge(prev_center, prev_bottom + 1, cx, y - 1, C_BLUE[2], b._nid("e"))
            # 分支：右栏
            branch = step.get("branch")
            if branch:
                bh = max(46, n_lines(branch["text"]) * (LINE + 4) + 18)
                bx, by = X_RIGHT, y - 10
                bid = b.vbox(bx, by, W_RIGHT, bh, branch["text"], C_GRAY, b._nid("b"))
                b.edge(x + w + 1, y + h // 2, bx - 1, by + bh // 2, C_GRAY[2],
                       b._nid("e"), label=branch.get("label", ""))
                # 回流箭头：从侧栏盒下方回到主列下一节点
                b._pending_rejoin = (bx + W_RIGHT // 2, by + bh + 1)
            prev_bottom = y + h
            prev_center = cx
            y = y + h + GAP
            continue

        w = W_MAIN
        h = max(48, n_lines(text) * (LINE + 4) + 18)
        x = cx - w // 2
        ident = b.vbox(x, y, w, h, text, pal, b._nid("n"))
        if prev_bottom is not None:
            b.edge(prev_center, prev_bottom + 1, cx, y - 1, C_BLUE[2], b._nid("e"))
        if getattr(b, "_pending_rejoin", None):
            px, py = b._pending_rejoin
            b.edge(px, py, cx, y - 1, C_GRAY[2], b._nid("e"),
                   pts=[(px, y - GAP // 2), (cx, y - GAP // 2)])
            b._pending_rejoin = None
        prev_bottom = y + h
        prev_center = cx
        y = y + h + GAP

    height = y - GAP + 60
    xml = (
        '<mxfile host="app.diagrams.net" agent="claude-code" version="24.7.17" pages="1">\n'
        f'  <diagram id="fig" name="{esc(spec["title"])}">\n'
        f'    <mxGraphModel dx="{W_CANVAS}" dy="{height}" grid="0" gridSize="10" '
        f'guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" '
        f'pageWidth="{W_CANVAS}" pageHeight="{height}" math="0" shadow="0">\n'
        '      <root>\n        <mxCell id="0"/><mxCell id="1" parent="0"/>\n        '
        + "\n        ".join(b.cells)
        + '\n      </root>\n    </mxGraphModel>\n  </diagram>\n</mxfile>\n'
    )
    (OUT / filename).write_text(xml, encoding="utf-8")
    print(f"✓ {filename}  ({len(b.cells)} 个图元, {W_CANVAS}x{height})")


SPECS = [
    {
        "title": "问题一求解流程：最大安全载荷反解与货箱组批",
        "steps": [
            {"t": "box", "text": "输入：15 个节点坐标 + 30 m DEM\n3 种机型参数 + 80 箱清单"},
            {"t": "box", "text": "逐航段几何\nH_{cruise} = 沿线最高地面高程 + 50 m\n得 d_{ij}、h⁺_{ij}、h⁻_{ij}（240 条航段）"},
            {"t": "box", "text": "载荷—航程关系\nL_{g}(q) = L_{g0} − (L_{g0}−L_{gF})·(q/Q_{g})^{3/2}"},
            {"t": "box", "text": "能量约束取等号反解\nE_{g}^{T}(q) = (1−ρ_{g})·E_{g}^{use}\n（单调 + Brent 法，回代误差 5.6e-15）"},
            {"t": "box", "text": "q_{max} = min(能量反解值, Q_{g}, 体积对应质量)\n记录实际生效的约束类型"},
            {"t": "dec", "text": "生效约束？",
             "branch": {"text": "结构/体积生效\n⇒ q_{max} = Q_{g}", "label": "结构"}},
            {"t": "box", "text": "逐服务区二维装箱（FFD）\n质量 Σm_{b} ≤ q_{max}，体积 Σv_{b} ≤ V_{g}"},
            {"t": "box", "text": "下界校验：Martello–Toth 型解析下界\nLB = max(⌈Σm/q_{max}⌉, ⌈Σv/V_{g}⌉)"},
            {"t": "dec", "text": "启发式解 = 下界？",
             "branch": {"text": "否 ⇒ 回局部搜索\n继续合并/重排", "label": "否"}},
            {"t": "box", "text": "输出：18 架次（全 C 型）\n总能耗 75.07 kWh｜ρ_{g} 敏感性曲线"},
        ],
    },
    {
        "title": "问题二求解流程：异构多点多架次运输调度",
        "steps": [
            {"t": "box", "text": "输入：Q1 组批方案 + 8 架实体机\n14 组共享电池 + 两类时限"},
            {"t": "box", "text": "构造：按「首批优先 → 期望升序 →\n优先系数降序 → 体积降序」入批或新开架次"},
            {"t": "box", "text": "选序：站点 ≤ 6 全排列\n> 6 用最近邻 + 2-opt"},
            {"t": "box", "text": "局部搜索：搬箱 / 合并架次\n字典序目标（及时性 → 架次数 → 能耗）"},
            {"t": "box", "text": "时段驱动贪心派发\n每决策时刻在资源就绪架次中择优"},
            {"t": "dec", "text": "资源就绪？",
             "branch": {"text": "否 ⇒ 等待充电周转\nΔ 为两阶段充电时长", "label": "否"}},
            {"t": "box", "text": "资源池周转：无人机 + 共享电池\n两阶段充电（SOC < 90% 占 65%，其后 35%）"},
            {"t": "box", "text": "独立复算校验\n逐段能耗、返航 SOC、资源占用区间"},
            {"t": "box", "text": "输出：35 架次（全 B 型）｜83.01 kWh\n完工 9.78 h｜准时率 38.8%（首批超时 23 箱）"},
        ],
    },
    {
        "title": "问题三求解流程：通信约束下运输与中继联合调度",
        "steps": [
            {"t": "box", "text": "输入：Q2 运输方案 + 链路预算参数\n中继参数 + 30 m DEM"},
            {"t": "box", "text": "沿完整轨迹逐时刻采样（Δt = 2 s）\n覆盖爬升 / 巡航 / 下降 / 投送四阶段"},
            {"t": "box", "text": "三态判定：直连 > 中继 > 中断\nFSPL 用 km、双向门限取两方向较小值"},
            {"t": "dec", "text": "存在中断？",
             "branch": {"text": "否 ⇒ 该架次无需中继\n直连全程可用", "label": "否"}},
            {"t": "box", "text": "生成悬停候选点：DEM 范围内\n服务区凸包外扩 3 km，400 m 网格 → 1885 点"},
            {"t": "box", "text": "单点全程覆盖判定\n∀t：直连 ∨ (接入(P) ∧ 回传(P))"},
            {"t": "dec", "text": "单点可覆盖？",
             "branch": {"text": "否 ⇒ 分时段接力\n多架中继分段保障", "label": "否"}},
            {"t": "box", "text": "选址择优：通过返航 SOC 校验的\n最低能耗悬停点（离地 ≤ 300 m）"},
            {"t": "box", "text": "输出：30 个中继架次｜覆盖 29/29\n总能耗 99.68 kWh｜联合完工 9.90 h"},
        ],
    },
    {
        "title": "问题四求解流程：救援任务分区与资源配置",
        "steps": [
            {"t": "box", "text": "输入：Q3 联合调度方案\n（架次划分、访问顺序、保障关系保持不变）"},
            {"t": "box", "text": "提取「架次—服务区」关联并构图\n15 个服务区为顶点，同架次服务区连边"},
            {"t": "box", "text": "求连通分量 = 原子单元\n（同架次服务区必须同组，不可拆）"},
            {"t": "dec", "text": "分量数 = 1？",
             "branch": {"text": "是 ⇒ 唯一合法分区为「全部一组」\nK = 2、K = 3 均不存在合法解", "label": "是"}},
            {"t": "box", "text": "定位桥接架次：移除后分量数增加\n得 T010 / T017 / T027 三个"},
            {"t": "box", "text": "最小改动方案\n拆 1 个架次得 2 组，拆 2 个得 3 组"},
            {"t": "box", "text": "组内资源核算：并行峰值 + 电池周转\n（资源不得跨组调配）"},
            {"t": "box", "text": "四维对比：配置规模 / 冗余 / 组间均衡 / 缺口\nK=1,2,3 ⇒ 资源总量 13 / 17 / 21"},
            {"t": "box", "text": "输出：分区不可行性论证 + 桥接架次清单\nK=1 唯一缺口为 1 组 B 型备用电池"},
        ],
    },
]


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for i, spec in enumerate(SPECS, 1):
        render(spec, f"f{i:02d}_flow.drawio")
    (OUT / "flow_specs.json").write_text(
        json.dumps(SPECS, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
