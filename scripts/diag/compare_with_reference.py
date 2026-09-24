"""诊断：把论文公式与**参考文稿2**中的公式做同尺度像素对比。

参考文稿2 的公式来自 MathType，是"正确比例"的基准。本脚本把两边的公式区域
按相同 DPI 渲染成 PNG 并排输出，同时量测字形高度，用于标定本仓库的预览图比例。

用法：
    python scripts/diag/compare_with_reference.py --ref-page 12 --our-page 20
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
OURS = ROOT / "paper" / "山区洪涝灾害下无人机运输与通信协同优化_论文.pdf"
REF = ROOT / "docs" / "reference" / "参考文稿2.pdf"
OUT = ROOT / "paper" / "_preview" / "compare"
DPI = 200


def ink_bands(page, dpi: int = DPI, thresh: int = 150):
    """返回该页所有文本行带的 (y0, y1, x0, x1)，单位 px。"""
    import fitz
    import numpy as np

    pm = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
    a = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width)
    ink = a < thresh
    bands, start = [], None
    for y, v in enumerate(ink.any(axis=1)):
        if v and start is None:
            start = y
        elif not v and start is not None:
            bands.append((start, y))
            start = None
    if start is not None:
        bands.append((start, pm.height))
    out = []
    for y0, y1 in bands:
        xs = np.nonzero(ink[y0:y1].any(axis=0))[0]
        out.append((y0, y1, int(xs[0]) if len(xs) else 0,
                    int(xs[-1]) if len(xs) else 0))
    return out, pm


def main() -> int:
    import fitz
    import numpy as np
    from PIL import Image

    ap = argparse.ArgumentParser()
    ap.add_argument("--ref-page", type=int, default=12)
    ap.add_argument("--our-page", type=int, default=20)
    ap.add_argument("--dpi", type=int, default=DPI)
    args = ap.parse_args()
    px_per_pt = args.dpi / 72.0

    OUT.mkdir(parents=True, exist_ok=True)
    for label, pdf, pno in (("参考文稿2", REF, args.ref_page),
                            ("本论文", OURS, args.our_page)):
        if not pdf.exists():
            print(f"❌ 缺少 {pdf}")
            return 1
        doc = fitz.open(str(pdf))
        page = doc[pno - 1]
        bands, pm = ink_bands(page, args.dpi)
        img = Image.frombytes("L", (pm.width, pm.height), pm.samples)
        f = OUT / f"{label}_p{pno}.png"
        img.save(f)
        print(f"\n=== {label} 第 {pno} 页（{len(bands)} 行，{args.dpi} dpi）→ {f.name} ===")
        for y0, y1, x0, x1 in bands:
            h = y1 - y0
            print(f"  高 {h:>4}px = {h / px_per_pt:>5.1f}pt   宽 {x1 - x0:>5}px   y={y0}")
        doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
