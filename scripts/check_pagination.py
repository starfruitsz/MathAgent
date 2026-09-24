"""排版体检：找出内容明显偏少（留白过多）的页面。

原理：逐页栅格化，扫描页面底部到最后一个墨水像素之间的距离，
换算成"页尾空白高度"。空白 > 阈值的页面通常意味着图表被整体推到下一页。

用法：
    python scripts/check_pagination.py            # 默认阈值 6 cm
    python scripts/check_pagination.py --min-gap 4
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "paper" / "山区洪涝灾害下无人机运输与通信协同优化_论文.pdf"
DPI = 100
CM_PER_IN = 2.54


def main() -> int:
    import argparse

    import fitz
    import numpy as np

    ap = argparse.ArgumentParser()
    ap.add_argument("--min-gap", type=float, default=6.0, help="报告阈值（cm）")
    ap.add_argument("--top", type=int, default=0, help="只看空白最多的 N 页")
    args = ap.parse_args()

    if not PDF.exists():
        print(f"❌ 未找到 PDF：{PDF}")
        return 1
    doc = fitz.open(str(PDF))
    # 页脚页码会拉低"最后墨水行"，裁掉底部 1.6 cm 再测
    px_per_cm = DPI / CM_PER_IN
    rows = []
    for i, page in enumerate(doc, 1):
        pm = page.get_pixmap(dpi=DPI, colorspace=fitz.csGRAY)
        a = np.frombuffer(pm.samples, dtype=np.uint8).reshape(pm.height, pm.width)
        h_cut = int(pm.height - 1.6 * px_per_cm)
        ink = (a[:h_cut] < 170).any(axis=1)
        idx = np.nonzero(ink)[0]
        last = int(idx[-1]) if len(idx) else 0
        gap_cm = (h_cut - last) / px_per_cm
        rows.append((i, gap_cm))
    doc.close()

    bad = [r for r in rows if r[1] >= args.min_gap]
    print(f"PDF 共 {len(rows)} 页；页尾空白 ≥ {args.min_gap} cm 的页面：{len(bad)}")
    listed = sorted(bad, key=lambda r: -r[1])[: args.top] if args.top else bad
    for pno, gap in listed:
        print(f"  第 {pno:>3} 页  空白 {gap:5.1f} cm")
    if not bad:
        print("  ✅ 没有明显留白过大的页面")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
