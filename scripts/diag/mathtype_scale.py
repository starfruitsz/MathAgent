"""MathType 预览图缩放标定。

背景：`docx-equation` 把公式渲染成 OLE 对象 + PNG 预览图，预览图在 docx 中的
显示尺寸由 `preview_pt_per_px`（点/像素）决定。取值不当会让公式明显小于正文。

方法：同一公式在若干 scale 下各生成一份 docx，用 Word 排版并导出 PDF，
再用 PyMuPDF 以固定 DPI 栅格化页面，量出"公式主体字高 / 普通文字字高"的比值。
比值 < 1 说明公式偏小，据此推算出合适 scale。

用法：
    python scripts/calibrate_mathtype_scale.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from report import equations as EQ  # noqa: E402

OUT = ROOT / "paper" / "_mathtype_smoke"
SCALES = [0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
BODY_PT = 12.0
EQ_TEXT = r"E^{h}_{i} = \frac{d_{i}}{L_{g}(q_{i})} \cdot E^{use}_{g}"
RENDER_DPI = 600


def build() -> Path:
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Times New Roman"
    st.font.size = Pt(BODY_PT)

    for s in SCALES:
        p = doc.add_paragraph()
        r = p.add_run(f"s={s:.2f} 参考字 Eghdq ")
        r.font.size = Pt(BODY_PT)
        EQ.append_omml(p, EQ_TEXT, display=False)
        p.add_run(" End").font.size = Pt(BODY_PT)
    src = OUT / "_calib_omml.docx"
    doc.save(str(src))
    return src


def convert(src: Path, scale: float) -> Path:
    from docx_equation.mathtype import legacy

    browser = EQ.find_browser()
    if browser is not None:
        import docx_equation.shared.mathml as _m

        _m._find_chrome = lambda *_a, **_k: Path(browser)  # noqa: SLF001

    dst = OUT / f"_calib_{scale:.2f}.docx"
    if dst.exists():
        dst.unlink()
    legacy._convert(src, dst, OUT / "_calib_work", EQ.WIN_OMML_XSL,
                    12.5, 21.0, 360.0, scale, "preserve", "DSMT4")
    return dst


def bands(page, dpi: int = RENDER_DPI):
    """返回页面上每个"文本行"的 (y0, y1, x0, x1)（单位 px）。"""
    import fitz
    import numpy as np

    pm = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
    a = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width)
    ink = a < 160
    rows = ink.any(axis=1)
    out, start = [], None
    for y, v in enumerate(rows):
        if v and start is None:
            start = y
        elif not v and start is not None:
            out.append((start, y)); start = None
    if start is not None:
        out.append((start, len(rows)))
    res = []
    for y0, y1 in out:
        band = ink[y0:y1]
        cols = band.any(axis=0)
        xs = np.nonzero(cols)[0]
        res.append((y0, y1, int(xs[0]), int(xs[-1])))
    return res, pm.height


def _retry(fn, *a, tries: int = 12, delay: float = 1.5, **kw):
    """Word 忙于处理 OLE 对象时会抛 "调用被拒绝"(-2147418111)，退避重试。"""
    import time

    for i in range(tries):
        try:
            return fn(*a, **kw)
        except Exception as exc:  # noqa: BLE001
            if "-2147418111" not in str(exc) and i == 0:
                raise
            if i == tries - 1:
                raise
            time.sleep(delay)


def main() -> int:
    import time

    import fitz

    OUT.mkdir(parents=True, exist_ok=True)
    src = build()
    print(f"标定源：{src.name}（正文 {BODY_PT:.0f} pt）\n")

    import win32com.client as win32

    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    try:
        for s in SCALES:
            dst = convert(src, s)
            pdf = dst.with_suffix(".pdf")
            if pdf.exists():
                pdf.unlink()
            doc = _retry(word.Documents.Open, str(dst), ReadOnly=False)
            try:
                time.sleep(1.0)
                _retry(doc.SaveAs2, str(pdf), FileFormat=17)
            finally:
                _retry(doc.Close, SaveChanges=False)
            print(f"  scale={s:.2f} → {pdf.name}  ({pdf.stat().st_size} bytes)")
    finally:
        word.Quit()

    px_per_pt = RENDER_DPI / 72.0
    print(f"栅格化：{RENDER_DPI} DPI → {px_per_pt:.3f} px/pt")
    print("每行由「参考文字 + 公式 + End」组成；公式行的墨水带高于纯文字行。\n")
    print(f"{'scale':>7} | {'公式带高(px)':>12} | {'纯文字带高(px)':>14} | {'比值':>6} | 显示高度(pt)")
    print("-" * 74)
    ratios: dict[float, float] = {}
    for s in SCALES:
        pdf = OUT / f"_calib_{s:.2f}.pdf"
        d = fitz.open(str(pdf))
        page = d[0]
        bs, _ = bands(page)
        d.close()
        # 最矮的带 ≈ 纯文字行；最高的带 ≈ 公式行
        hs = sorted((y1 - y0) for y0, y1, _, _ in bs)
        if len(hs) < 2:
            print(f"{s:>7.2f} | 行检测失败（{len(hs)} 行）")
            continue
        plain = hs[0]
        formula = hs[-1]
        ratio = formula / plain
        ratios[s] = ratio
        print(f"{s:>7.2f} | {formula:>12d} | {plain:>14d} | {ratio:>6.3f} | {formula / px_per_pt:>8.1f}")

    if not ratios:
        print("\n❌ 标定失败")
        return 1

    # 线性外推：公式行高 ≈ 参考行高 + k·scale
    xs = sorted(ratios)
    base = ratios[xs[0]]
    slope = (ratios[xs[-1]] - base) / (xs[-1] - xs[0]) if len(xs) > 1 else 0.0
    print(f"\n拟合：比值 ≈ {base:.3f} + {slope:.3f} × (scale − {xs[0]:.2f})")
    if slope > 0:
        target = 1.0
        need = xs[0] + (target - base) / slope
        need = max(0.10, min(0.60, need))
        print(f"→ 使公式行高与参考行高相当的 scale ≈ {need:.3f}")
        print("  （公式含分式，行高天然高于纯文字，比值略大于 1 属正常）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
