"""在 300 dpi 下量测指定行的墨迹高度（cm/pt），用于精确校准公式字号。

用法：
    python scripts/diag/line_heights.py 15
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / "paper" / "山区洪涝灾害下无人机运输与通信协同优化_论文.pdf"
DPI = 300


def main() -> int:
    import fitz
    import numpy as np

    pages = [int(a) for a in sys.argv[1:]] or [15]
    doc = fitz.open(str(PDF))
    px_per_pt = DPI / 72.0
    for pno in pages:
        page = doc[pno - 1]
        pm = page.get_pixmap(dpi=DPI, colorspace=fitz.csGRAY)
        a = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width)
        ink = a < 150
        bands, start = [], None
        for y, v in enumerate(ink.any(axis=1)):
            if v and start is None:
                start = y
            elif not v and start is not None:
                bands.append((start, y))
                start = None
        if start is not None:
            bands.append((start, len(rows := ink.any(axis=1))))
        print(f"\n=== 第 {pno} 页 · {len(bands)} 行（{DPI} dpi，{px_per_pt:.2f} px/pt）===")
        print(f"{'y0':>6} {'高px':>6} {'高pt':>7} {'宽px':>6}")
        for y0, y1 in bands:
            band = ink[y0:y1]
            xs = np.nonzero(band.any(axis=0))[0]
            wpx = int(xs[-1] - xs[0]) if len(xs) else 0
            h = y1 - y0
            print(f"{y0:>6} {h:>6} {h / px_per_pt:>7.1f} {wpx:>6}")
    doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
