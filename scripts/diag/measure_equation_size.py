"""量测 PDF 页面上"公式行"与"正文行"的实际墨迹高度，判断公式字号是否协调。

用法：
    python scripts/measure_equation_size.py 13 14
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "paper" / "山区洪涝灾害下无人机运输与通信协同优化_论文.pdf"
DPI = 300


def main() -> int:
    import fitz
    import numpy as np

    pages = [int(a) for a in sys.argv[1:]] or [13]
    doc = fitz.open(str(PDF))
    px_per_pt = DPI / 72.0
    for pno in pages:
        page = doc[pno - 1]
        pm = page.get_pixmap(dpi=DPI, colorspace=fitz.csGRAY)
        a = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width)
        ink = a < 150
        rows = ink.any(axis=1)
        bands, start = [], None
        for y, v in enumerate(rows):
            if v and start is None:
                start = y
            elif not v and start is not None:
                bands.append((start, y))
                start = None
        if start is not None:
            bands.append((start, len(rows)))
        print(f"\n=== 第 {pno} 页：{len(bands)} 个文本行 ===")
        hs = []
        for y0, y1 in bands:
            band = ink[y0:y1]
            xs = np.nonzero(band.any(axis=0))[0]
            w = int(xs[-1] - xs[0]) if len(xs) else 0
            h = y1 - y0
            hs.append(h)
            print(f"  y={y0:>5}  高={h:>4}px = {h / px_per_pt:>5.1f}pt  宽={w:>5}px")
        if hs:
            med = sorted(hs)[len(hs) // 2]
            print(f"  中位行高 {med}px = {med / px_per_pt:.1f}pt")
    doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
