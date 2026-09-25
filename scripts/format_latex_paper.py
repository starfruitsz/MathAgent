"""把 pandoc 产出的「LaTeX 公式版」Word 改造为**标准格式**（参照 otheragent/document.pdf 的版式规范）。

背景
----
`_LaTeX公式版.docx` 由 pandoc 从 `otheragent/document.tex` 直接转换而来：
它的**公式质量最好**（554 个 Word 原生 OMML 对象，与 XeLaTeX 排版的
`otheragent/document.pdf` 同源），但 **pandoc 不做任何竞赛排版控制**：

| 项 | pandoc 产出 | 标准格式要求 |
|---|---|---|
| 每章另起新页 | Heading1 样式已带 `pageBreakBefore`（未确认取值） | 必须显式为真 |
| 三线表 | 15 张表**无任何边框**、用内置 `Table` 样式 | 顶线/表头下线/底线，无竖线，清掉表格样式 |
| 图与图题同页 | **38 个图片段落全都没设 `keepNext`** | 图片段落 `keepNext` |
| 表与表题同页 | 表题无 `keepNext` | 表题 `keepNext` + 题注 `keepLines` |
| 题注编号 | 图题/表题**没有编号**（只有纯标题文字） | `图 N 标题` / `表 N 标题` |
| 页边距/字体/行距 | pandoc 默认 | A4、宋体正文、Times New Roman 西文、1.45 倍行距 |

关键：本脚本**只加格式、不动公式** —— 公式仍是 Word 原生 OMML 对象（双击可编辑）。

用法
----
    python scripts\\format_latex_paper.py            # 就地改造 _LaTeX公式版.docx
    python scripts\\format_latex_paper.py --check    # 只做结构自检

前置：先跑 `pwsh -File scripts\\build_word_from_latex.ps1` 生成 pandoc 产出。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docx import Document  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.oxml import OxmlElement  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.shared import Cm, Pt, RGBColor  # noqa: E402
from docx.table import Table  # noqa: E402
from docx.text.paragraph import Paragraph  # noqa: E402

from src.report.build_paper import (  # noqa: E402
    CN_FONT,
    CN_HEI,
    EN_FONT,
    _header_bottom_rule,
    _no_split,
    _order_tblpr,
    _page_number_footer,
    _repeat_header,
    _set_font,
    _three_line_borders,
)

DOCX = (ROOT / "paper"
        / "山区洪涝灾害下无人机运输与通信协同优化_论文_LaTeX公式版.docx")

# 版心宽度：A4(21cm) − 左右边距(2.6cm × 2) = 15.8cm
TEXT_WIDTH_CM = 15.8


# ---------------------------------------------------------------- 基础工具

def _pPr(p: Paragraph):
    return p._p.get_or_add_pPr()


def _add_flag(p: Paragraph, tag: str) -> None:
    """加一个布尔型段落属性（如 w:keepNext）。"""
    ppr = _pPr(p)
    if ppr.find(qn(tag)) is None:
        ppr.append(OxmlElement(tag))


def _drop_flag(p: Paragraph, tag: str) -> None:
    ppr = _pPr(p)
    el = ppr.find(qn(tag))
    if el is not None:
        ppr.remove(el)


def _set_page_break_before(p: Paragraph) -> None:
    ppr = _pPr(p)
    el = ppr.find(qn("w:pageBreakBefore"))
    if el is None:
        el = OxmlElement("w:pageBreakBefore")
        ppr.append(el)
    el.set(qn("w:val"), "true")


def _has_image(p: Paragraph) -> bool:
    return p._p.find(".//" + qn("a:blip")) is not None


def _has_math(p: Paragraph) -> bool:
    return p._p.find(".//" + qn("m:oMath")) is not None


def _has_drawing_or_math(p: Paragraph) -> bool:
    return _has_image(p) or _has_math(p)


def _plain_text(p: Paragraph) -> str:
    return "".join(t.text or "" for t in p._p.iter(qn("w:t"))).strip()


# ---------------------------------------------------------------- 1. 页面与样式

def apply_page_setup(doc: Document) -> None:
    """A4 版心 + 正文字体 + 标题字体 + 章页分页（四项硬性要求之 2）。"""
    for s in doc.sections:
        s.page_width, s.page_height = Cm(21.0), Cm(29.7)
        s.left_margin = s.right_margin = Cm(2.6)
        s.top_margin = Cm(2.6)
        s.bottom_margin = Cm(2.4)

    st = doc.styles["Normal"]
    st.font.name = EN_FONT
    st.font.size = Pt(12)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), CN_FONT)
    pf = st.paragraph_format
    pf.line_spacing = 1.45
    pf.space_after = Pt(4)

    for name, size in (("Heading 1", 16), ("Heading 2", 14), ("Heading 3", 12.5),
                       ("Heading 4", 12)):
        try:
            s = doc.styles[name]
        except KeyError:
            continue
        s.font.name = EN_FONT
        s.font.size = Pt(size)
        s.font.bold = True
        s.font.color.rgb = RGBColor(0, 0, 0)
        s.element.rPr.rFonts.set(qn("w:eastAsia"), CN_HEI)
        s.paragraph_format.space_before = Pt(10)
        s.paragraph_format.space_after = Pt(6)
        s.paragraph_format.first_line_indent = Pt(0)

    # ★ 要求 2：每一章（一级标题）必须另起新页 —— 写进样式，一处生效
    h1 = doc.styles["Heading 1"].paragraph_format
    h1.page_break_before = True
    h1.keep_with_next = True
    for lv in ("Heading 2", "Heading 3", "Heading 4"):
        try:
            doc.styles[lv].paragraph_format.keep_with_next = True
        except KeyError:
            pass
    # Heading1 样式里若残留 val="0" 会**显式关闭**分页，必须清掉
    hel = doc.styles["Heading 1"].element
    ppr = hel.find(qn("w:pPr"))
    if ppr is not None:
        pbb = ppr.find(qn("w:pageBreakBefore"))
        if pbb is None:
            pbb = OxmlElement("w:pageBreakBefore")
            ppr.append(pbb)
        pbb.set(qn("w:val"), "true")


# ---------------------------------------------------------------- 2. 三线表

def _cell_texts(tbl: Table) -> list[list[str]]:
    return [[c.text.strip() for c in row.cells] for row in tbl.rows]


def _set_col_widths(tbl: Table, texts: list[list[str]]) -> None:
    """按内容自适应列宽，并**同步写入 `w:tblGrid`**（幂律压缩，避免等宽列换行）。

    ★★ 两个必须同时做对的地方（否则表格会溢出/被裁剪）：

    1. **`w:tblGrid` 才是"固定版式"下的权威列宽**。
       本仓表一律带 `w:tblLayout type="fixed"`，此时 Word 按 `w:gridCol/@w:w`
       布局，`w:tcW` 只是单元格的"期望值"。只改 `cell.width`（写到 `tcW`）
       而不同步 `tblGrid`，两者就会打架——
       实测表 2：`gridCol` 各 1980 twips（3.49 cm）而 `tcW` 首列 3792 twips
       （6.69 cm），合计 8958 twips > 版心 7920 twips ⇒ 表格溢出、
       公式上标被裁掉、长文本列被压成竖排单字。
    2. **单位必须是 twips**。`docx` 的 `cell.width = Cm(x)` 存的是 **EMU**；
       而 `w:tcW/@w:w` 与 `w:gridCol/@w:w` 要求 **twips**（1 twip = 635 EMU）。
       务必用 `Cm(x).twips`，不要用 `int(Cm(x))`。
    """
    ncol = len(tbl.columns)
    if ncol == 0 or not texts:
        return

    def est(s: str) -> float:
        n = 0.0
        for ch in s:
            n += 2.0 if ("\u2e80" <= ch <= "\u9fff"
                         or "\uff00" <= ch <= "\uffef") else 1.0
        return max(n, 2.0)

    # 含公式的单元格：`cell.text` 取不到公式，会被严重低估 ⇒ 给一个下限
    M_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
    has_math_cols = [
        any(c._tc.findall(f".//{M_NS}oMath") for c in col.cells)
        for col in tbl.columns
    ]

    ests = []
    for j in range(ncol):
        w = max((est(r[j]) for r in texts if j < len(r)), default=2.0)
        if has_math_cols[j]:
            w = max(w, 22.0)      # ≈ 11 个汉字宽，容得下"符号 / 单位"
        ests.append(max(w, 2.0))

    # 幂律压缩：列宽比不超过约 4:1
    power = 0.55
    comp = [e ** power for e in ests]
    total = sum(comp)
    widths = [TEXT_WIDTH_CM * c / total for c in comp]
    widths = [max(w, 1.4) for w in widths]          # 每列至少 1.4 cm
    scale = TEXT_WIDTH_CM / sum(widths)
    widths = [w * scale for w in widths]

    # ---- ① 写 w:tblGrid（固定版式下的权威列宽）----
    grid = tbl._tbl.find(qn("w:tblGrid"))
    if grid is not None:
        tbl._tbl.remove(grid)
    grid = OxmlElement("w:tblGrid")
    for w in widths:
        gc = OxmlElement("w:gridCol")
        gc.set(qn("w:w"), str(Cm(w).twips))
        grid.append(gc)
    # tblGrid 必须紧跟在 tblPr 之后（schema 要求）
    tblPr = tbl._tbl.find(qn("w:tblPr"))
    if tblPr is not None:
        tblPr.addnext(grid)
    else:
        tbl._tbl.insert(0, grid)

    # ---- ② 写每个单元格的 tcW（同一套 twips）----
    for row in tbl.rows:
        for j, cell in enumerate(row.cells):
            if j >= len(widths):
                continue
            tcPr = cell._tc.get_or_add_tcPr()
            old = tcPr.find(qn("w:tcW"))
            if old is not None:
                tcPr.remove(old)
            tcW = OxmlElement("w:tcW")
            tcW.set(qn("w:type"), "dxa")
            tcW.set(qn("w:w"), str(Cm(widths[j]).twips))
            tcPr.append(tcW)

    # ---- ③ 表格总宽 + 固定版式 ----
    tblPr = tbl._tbl.find(qn("w:tblPr"))
    if tblPr is not None:
        old_w = tblPr.find(qn("w:tblW"))
        if old_w is not None:
            tblPr.remove(old_w)
        tblW = OxmlElement("w:tblW")
        tblW.set(qn("w:type"), "dxa")
        tblW.set(qn("w:w"), str(Cm(TEXT_WIDTH_CM).twips))
        tblPr.append(tblW)
        if tblPr.find(qn("w:tblLayout")) is None:
            lay = OxmlElement("w:tblLayout")
            lay.set(qn("w:type"), "fixed")
            tblPr.append(lay)
    tbl.autofit = False


def format_tables(doc: Document) -> int:
    """把全部表格改成三线表（要求 3）。"""
    n = 0
    for tbl in doc.tables:
        texts = _cell_texts(tbl)
        _three_line_borders(tbl)            # 顶线 + 底线，无竖线/内横线
        tbl.style = None                    # 清表格样式，否则样式边框覆盖三线
        if tbl.rows:
            _header_bottom_rule(tbl.rows[0])  # 表头下中线
            _repeat_header(tbl.rows[0])       # 跨页时重复表头
        for row in tbl.rows:
            _no_split(row)                    # 行内不断页
        try:
            _set_col_widths(tbl, texts)
        except Exception:                     # noqa: BLE001
            pass
        _order_tblpr(tbl)                     # ★ 子元素顺序必须符合 schema
        n += 1
    return n


# ---------------------------------------------------------------- 3. 题注与图表同页

def _style_id(p: Paragraph) -> str:
    """段落样式 ID（pandoc 会给出语义化样式名，比按位置猜测可靠得多）。"""
    ppr = p._p.find(qn("w:pPr"))
    if ppr is None:
        return ""
    s = ppr.find(qn("w:pStyle"))
    return s.get(qn("w:val")) if s is not None else ""


def format_captions(doc: Document) -> tuple[int, int]:
    """给图题/表题编号并设置同页属性（要求 4）。

    ★ 不靠位置猜测：pandoc 会给出**语义化段落样式**（本仓实测）——
    `CaptionedFigure`（装图片的段落）/ `ImageCaption`（图题）/ `TableCaption`（表题）。
    按样式定位，既不会把正文里的"图 N 显示…"交叉引用误判成题注，
    也不会漏掉**题注里含行内公式**的表格（实测有 2 张，位置法会漏）。
    """
    n_fig = n_tab = 0

    # --- 图：图片段落 keepNext → 与图题同页 ---
    for p in doc.paragraphs:
        if _has_image(p):
            _add_flag(p, "w:keepNext")

    # --- 图题 ---
    for p in doc.paragraphs:
        if _style_id(p) != "ImageCaption":
            continue
        n_fig += 1
        _rewrite_caption(p, f"图 {n_fig}")
        _add_flag(p, "w:keepLines")      # 题注自身不跨页断开
        _drop_flag(p, "w:keepNext")      # ★ 图题**不设** keepNext（否则图+题注+后文连块，制造大片留白）
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # --- 表题：keepNext → 与表同页 ---
    for p in doc.paragraphs:
        if _style_id(p) != "TableCaption":
            continue
        n_tab += 1
        _rewrite_caption(p, f"表 {n_tab}")
        _add_flag(p, "w:keepNext")
        _add_flag(p, "w:keepLines")
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    return n_fig, n_tab


def _rewrite_caption(p: Paragraph, prefix: str) -> None:
    """把题注改写成 `图 N  标题` / `表 N  标题`（幂等）。

    ★ 题注里可能含**行内公式**（`m:oMath`），必须原样保留。
    做法：只**在段首插入**一个编号 run，其余子元素（含 `m:oMath`）**一概不动** ——
    不重建、不包裹，避免改变公式对象的数量与层级。
    """
    import re

    txt = _plain_text(p)
    if re.match(r"^(图|表)\s*[A-Z]?\d+\s", txt):
        return

    core = txt.rstrip("。.：:")
    # 清掉纯文本 run（含标题原文），保留 m:oMath / drawing 等
    for r in list(p._p.findall(qn("w:r"))):
        if r.find(qn("w:t")) is not None:
            p._p.remove(r)
    # 段首（pPr 之后）插入 `图 N  标题`
    ppr = p._p.find(qn("w:pPr"))
    idx = 1 if ppr is not None else 0
    head = p.add_run(f"{prefix}  {core}")
    _set_font(head, 10.5, bold=False)
    p._p.remove(head._r)
    p._p.insert(idx, head._r)


# ---------------------------------------------------------------- 4. 分页兜底

def ensure_chapter_breaks(doc: Document) -> int:
    """在**每个一级标题段落**上也显式设 pageBreakBefore（不依赖样式继承）。"""
    n = 0
    for p in doc.paragraphs:
        if p.style.name == "Heading 1":
            _set_page_break_before(p)
            _add_flag(p, "w:keepNext")
            # 章标题不要首行缩进
            p.paragraph_format.first_line_indent = Pt(0)
            n += 1
    return n


# ---------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser(description="LaTeX 公式版论文 → 标准格式")
    ap.add_argument("--check", action="store_true", help="只做结构自检，不改造")
    ap.add_argument("--docx", default=str(DOCX), help="目标 docx 路径")
    args = ap.parse_args()

    path = Path(args.docx)
    if not path.exists():
        print(f"❌ 未找到 {path}\n   请先运行：pwsh -File scripts\\build_word_from_latex.ps1")
        return 1

    doc = Document(str(path))
    before_math = len(list(doc.element.body.iter(qn("m:oMath"))))

    if not args.check:
        apply_page_setup(doc)
        n_tbl = format_tables(doc)
        n_fig, n_tab = format_captions(doc)
        n_ch = ensure_chapter_breaks(doc)
        _page_number_footer(doc)
        doc.save(str(path))
        print(f"✅ 已改造：{path.name}")
        print(f"   三线表 {n_tbl} 张 / 图题 {n_fig} 条 / 表题 {n_tab} 条 "
              f"/ 一级标题 {n_ch} 个")

    # 复检：公式数量必须不变（只加格式、不动公式）
    after = Document(str(path))
    after_math = len(list(after.element.body.iter(qn("m:oMath"))))
    print(f"\n— 公式完整性 —")
    print(f"  m:oMath  改造前 {before_math} → 改造后 {after_math}")
    if after_math != before_math:
        print("  ❌ 公式数量发生变化！")
        return 1
    print("  ✅ 公式数量不变（仍为 Word 原生 OMML 对象，双击可编辑）")

    # 用仓库既有自检脚本复核（它固定读 _论文.docx，故此处内联同规则）
    print("\n— 关键格式复核 —")
    pics = keep = 0
    for p in after.paragraphs:
        if _has_image(p):
            pics += 1
            ppr = p._p.find(qn("w:pPr"))
            if ppr is not None and ppr.find(qn("w:keepNext")) is not None:
                keep += 1
    print(f"  图片段落 {pics}，设 keepNext {keep}")
    import re as _re

    caps = 0
    for p in after.paragraphs:
        if _re.match(r"^(图|表)\s*[A-Z]?\d+\s", _plain_text(p)):
            caps += 1
    print(f"  带编号题注 {caps} 条")
    three = sum(
        1 for t in after.tables
        if t._tbl.tblPr.find(qn("w:tblBorders")) is not None
    )
    print(f"  三线表 {three}/{len(after.tables)} 张")

    # ★ 列宽一致性：tblGrid 与 tcW 必须一致（不一致会导致表格溢出/裁剪）
    bad = []
    for ti, t in enumerate(after.tables, 1):
        grid = t._tbl.find(qn("w:tblGrid"))
        gw = [int(g.get(qn("w:w"))) for g in grid.findall(qn("w:gridCol"))] \
            if grid is not None else []
        if not gw:
            bad.append(f"表{ti}:无 tblGrid")
            continue
        for row in t.rows[:1]:
            tw = []
            for c in row.cells:
                tcPr = c._tc.find(qn("w:tcPr"))
                e = tcPr.find(qn("w:tcW")) if tcPr is not None else None
                tw.append(int(e.get(qn("w:w"))) if e is not None else -1)
            if len(tw) == len(gw) and any(abs(a - b) > 2 for a, b in zip(gw, tw)):
                bad.append(f"表{ti}: grid={gw} vs tcW={tw}")
        total = sum(gw)
        limit = Cm(TEXT_WIDTH_CM).twips
        if total > limit + 2:
            bad.append(f"表{ti}: 总宽 {total} twips > 版心 {int(limit)}")
    if bad:
        print("  ⚠️  列宽一致性检查未通过：")
        for b in bad[:8]:
            print(f"      {b}")
    else:
        print(f"  列宽一致性：{len(after.tables)} 张表 tblGrid 与 tcW 一致、"
              f"总宽均 ≤ {TEXT_WIDTH_CM} cm ✅")

    h1 = sum(1 for p in after.paragraphs if p.style.name == "Heading 1")
    print(f"  一级标题 {h1} 个（样式 + 段落均设 pageBreakBefore）")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
