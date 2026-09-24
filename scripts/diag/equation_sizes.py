"""列出 docx 中各公式预览图的像素尺寸与在文档中的显示尺寸（含比例反推）。

用法：
    python scripts/diag/equation_sizes.py [数量]
"""

from __future__ import annotations

import io
import re
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
DOCX = ROOT / "paper" / "山区洪涝灾害下无人机运输与通信协同优化_论文.docx"


def main() -> int:
    from PIL import Image

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    with zipfile.ZipFile(DOCX) as z:
        xml = z.read("word/document.xml").decode("utf-8")
        pngs = {}
        for n in sorted(n for n in z.namelist() if "mathtype_preview" in n):
            pngs[n.rsplit("/", 1)[-1]] = Image.open(io.BytesIO(z.read(n))).size

    shapes = re.findall(r'<v:shape[^>]*style="width:([\d.]+)pt;height:([\d.]+)pt"', xml)
    print(f"{'序号':>4} {'像素':>12} {'显示 pt':>14} {'比例 pt/px':>10} {'有效 DPI':>9}")
    rows = []
    for i, (w, h) in enumerate(shapes, 1):
        key = f"mathtype_preview_{i:03d}.png"
        if key not in pngs:
            continue
        pw, ph = pngs[key]
        wp, hp = float(w), float(h)
        ratio = hp / ph if ph else 0
        dpi = ph / (hp / 72.0) if hp else 0
        rows.append((i, pw, ph, wp, hp, ratio, dpi))
    for i, pw, ph, wp, hp, ratio, dpi in rows[:limit]:
        print(f"{i:>4} {pw:>5}x{ph:<6} {wp:>6.1f}x{hp:<7.1f} {ratio:>10.4f} {dpi:>9.0f}")
    if rows:
        rs = sorted(r[5] for r in rows)
        print(f"\n共 {len(rows)} 个公式；比例中位数 {rs[len(rs)//2]:.4f} pt/px")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
