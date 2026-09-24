"""论文 docx 结构自检：分页、三线表、公式对象、图表同页设置。

不需要 Word，直接解析 docx 的 XML，用于快速回归。

用法：
    python scripts/check_docx_structure.py
"""

from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[1]
DOCX = ROOT / "paper" / "山区洪涝灾害下无人机运输与通信协同优化_论文.docx"

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"


def main() -> int:
    if not DOCX.exists():
        print(f"❌ 未找到 {DOCX}")
        return 1
    with zipfile.ZipFile(DOCX) as z:
        xml = z.read("word/document.xml").decode("utf-8")
        try:
            styles = z.read("word/styles.xml").decode("utf-8")
        except KeyError:
            styles = ""
    root = ET.fromstring(xml)
    sroot = ET.fromstring(styles) if styles else None

    ok = True

    # ---------------- 1. 一级标题分页 ----------------
    h1_style_pbb = False
    if sroot is not None:
        for st in sroot.iter(f"{W}style"):
            if st.get(f"{W}styleId") == "Heading1":
                ppr = st.find(f"{W}pPr")
                if ppr is not None:
                    pbb = ppr.find(f"{W}pageBreakBefore")
                    h1_style_pbb = pbb is not None and pbb.get(f"{W}val", "true") != "false"
    body = root.find(f"{W}body")
    h1 = []
    for p in body.iter(f"{W}p"):
        ppr = p.find(f"{W}pPr")
        if ppr is None:
            continue
        ps = ppr.find(f"{W}pStyle")
        if ps is not None and ps.get(f"{W}val") == "Heading1":
            text = "".join(t.text or "" for t in p.iter(f"{W}t"))
            pbb = ppr.find(f"{W}pageBreakBefore")
            eff = (pbb is None and h1_style_pbb) or (
                pbb is not None and pbb.get(f"{W}val", "true") != "false")
            h1.append((text, eff))
    print("— 一级标题分页 —")
    print(f"  Heading 1 样式 pageBreakBefore = {h1_style_pbb}")
    for text, eff in h1:
        flag = "✅" if eff else "⚠️ "
        print(f"  {flag} {text}")
    n_bad = sum(1 for _, e in h1 if not e)
    if n_bad:
        ok = False

    # ---------------- 2. 三线表 ----------------
    tables = body.findall(f"{W}tbl")
    stats = Counter()
    bad_tables = []
    for i, t in enumerate(tables, 1):
        tblPr = t.find(f"{W}tblPr")
        borders = tblPr.find(f"{W}tblBorders") if tblPr is not None else None
        has_three = False
        if borders is not None:
            top = borders.find(f"{W}top")
            bot = borders.find(f"{W}bottom")
            lv = borders.find(f"{W}left")
            rv = borders.find(f"{W}right")
            iv = borders.find(f"{W}insideV")
            has_three = (
                top is not None and top.get(f"{W}val") == "single"
                and bot is not None and bot.get(f"{W}val") == "single"
                and lv is not None and lv.get(f"{W}val") == "none"
                and rv is not None and rv.get(f"{W}val") == "none"
                and iv is not None and iv.get(f"{W}val") == "none"
            )
        # 表头下框线
        rows = t.findall(f"{W}tr")
        hdr_rule = False
        if rows:
            first_cell = rows[0].find(f"{W}tc")
            if first_cell is not None:
                tcPr = first_cell.find(f"{W}tcPr")
                if tcPr is not None:
                    tb = tcPr.find(f"{W}tcBorders")
                    hdr_rule = tb is not None and tb.find(f"{W}bottom") is not None
        style_used = None
        if tblPr is not None:
            ts = tblPr.find(f"{W}tblStyle")
            style_used = ts.get(f"{W}val") if ts is not None else None
        stats["三线表" if has_three else "非三线表"] += 1
        stats["有表头线" if hdr_rule else "无表头线"] += 1
        stats["有表格样式" if style_used else "无表格样式"] += 1
        if not (has_three and hdr_rule):
            bad_tables.append(i)
    print("\n— 表格版式 —")
    print(f"  表格总数 {len(tables)}")
    for k in ("三线表", "非三线表", "有表头线", "无表头线", "有表格样式", "无表格样式"):
        if stats[k]:
            print(f"  {k}: {stats[k]}")
    if bad_tables:
        ok = False
        print(f"  ⚠️  未达三线表标准：第 {bad_tables[:12]} 张"
              f"{' …' if len(bad_tables) > 12 else ''}")

    # ---------------- 3. 公式对象 ----------------
    n_omml_total = len(list(root.iter(f"{M}oMath")))
    n_ole = xml.count("<o:OLEObject")
    n_dsmt = xml.count("Equation.DSMT4")
    n_ole_in_tbl = 0
    for t in tables:
        if t.findall(f".//{W}object"):
            n_ole_in_tbl += len(t.findall(f".//{W}object"))
    print("\n— 公式 —")
    if n_dsmt:
        print(f"  MathType 公式对象（Equation.DSMT4）  {n_dsmt}")
        print(f"  o:OLEObject 元素                     {n_ole}")
        print(f"     · 位于表格内                      {n_ole_in_tbl}")
        print(f"     · 位于正文段落                    {n_ole - n_ole_in_tbl}")
        # ★ 预览图健全性检查：若所有公式高度相同（尤其是只有一个高度值），说明
        #   MathML 被当成普通文字渲染，上下标/分式全部丢失（曾经踩过这个坑）。
        from PIL import Image
        import io as _io

        with zipfile.ZipFile(DOCX) as z:
            pngs = sorted(n for n in z.namelist() if "mathtype_preview" in n)
            hs = [Image.open(_io.BytesIO(z.read(n))).size[1] for n in pngs]
        print(f"  预览图                               {len(pngs)} 张，"
              f"高 {min(hs)}~{max(hs)} px")
        if len(set(hs)) <= 2:
            ok = False
            print(f"  ⚠️  预览图高度几乎全部相同（{sorted(set(hs))}）——"
                  f"公式很可能被渲染成了普通文字（上下标/分式丢失）")
        elif max(hs) < 2.2 * min(hs):
            print("  ⚠️  预览图高度差异偏小，建议抽查确认分式与上下标是否正常")
    print(f"  m:oMath（OMML 回退/未转换）          {n_omml_total}")
    if n_dsmt == 0 and n_omml_total == 0:
        ok = False
        print("  ⚠️  没有任何公式对象")

    # ---------------- 4. 图表同页设置 ----------------
    # 规则（要求 4）：
    #   · 图片段落 keepNext=True      → 图与其下方图题同页
    #   · 表题 keepNext=True          → 表与其表体同页
    #   · 所有题注 keep_together=True → 题注本身不跨页断开
    cap_re = re.compile(r"^(图|表)\s*[A-Z]?\d+\s")
    paras = list(body.iter(f"{W}p"))
    pics = keep_next = 0
    fig_caps = tab_caps = 0
    caps_keep_together = 0
    miss: list[str] = []
    for p in paras:
        if p.find(f".//{W}drawing") is not None:
            pics += 1
            ppr = p.find(f"{W}pPr")
            if ppr is not None and ppr.find(f"{W}keepNext") is not None:
                keep_next += 1
    for idx, p in enumerate(paras):
        txt = "".join(t.text or "" for t in p.iter(f"{W}t")).strip()
        if not cap_re.match(txt):
            continue
        ppr = p.find(f"{W}pPr")
        jc = ppr.find(f"{W}jc") if ppr is not None else None
        if jc is None or jc.get(f"{W}val") != "center":
            continue          # 正文中"图 2 显示…"这类交叉引用，不是题注
        is_fig = txt.startswith("图")
        fig_caps += is_fig
        tab_caps += (not is_fig)
        if ppr.find(f"{W}keepLines") is not None:
            caps_keep_together += 1
        else:
            miss.append(txt[:34])
        # 图题靠"图片段落 keepNext"绑定；表题靠自身 keepNext 绑定
        if not is_fig:
            if ppr.find(f"{W}keepNext") is None:
                miss.append("（表题缺 keepNext）" + txt[:28])
    print("\n— 图表同页设置 —")
    print(f"  图片段落 {pics}，其中设 keepNext（与图题同页） {keep_next}")
    print(f"  题注 {fig_caps + tab_caps} 条（图 {fig_caps} / 表 {tab_caps}），"
          f"其中 keep_together {caps_keep_together}")
    if keep_next < pics:
        ok = False
        print(f"  ⚠️  {pics - keep_next} 个图片段落未设 keepNext")
    if miss:
        ok = False
        print(f"  ⚠️  {len(miss)} 处题注设置不完整：{miss[:6]}")

    print("\n" + ("✅ 结构自检通过" if ok else "❌ 结构自检发现问题"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
