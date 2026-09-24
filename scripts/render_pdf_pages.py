"""把论文 PDF 的指定页渲染成 PNG，供人工/图像检查排版。

用法：
    python scripts/render_pdf_pages.py 6 12 20 --out paper/_preview
    python scripts/render_pdf_pages.py --all       # 渲染全部页（低分辨率）
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "paper" / "山区洪涝灾害下无人机运输与通信协同优化_论文.pdf"


def main() -> int:
    import argparse

    import fitz

    ap = argparse.ArgumentParser()
    ap.add_argument("pages", nargs="*", type=int, help="页码（从 1 开始）")
    ap.add_argument("--out", default="paper/_preview")
    ap.add_argument("--dpi", type=int, default=110)
    ap.add_argument("--all", action="store_true", help="渲染全部页")
    args = ap.parse_args()

    if not PDF.exists():
        print(f"❌ 未找到 PDF：{PDF}\n请先运行 python scripts/check_paper.py --pdf")
        return 1
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(str(PDF))
    n = len(doc)
    pages = list(range(1, n + 1)) if args.all else args.pages
    if not pages:
        print(f"PDF 共 {n} 页；用法：python scripts/render_pdf_pages.py 6 12 20")
        return 0
    for pno in pages:
        if not 1 <= pno <= n:
            print(f"跳过越界页码 {pno}（共 {n} 页）")
            continue
        pix = doc[pno - 1].get_pixmap(dpi=args.dpi)
        f = out / f"page_{pno:03d}.png"
        pix.save(str(f))
        print(f"page {pno:>3}/{n} → {f.relative_to(ROOT)}  ({pix.width}x{pix.height})")
    doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
