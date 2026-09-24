"""列出 PDF 各页 span 的字号与文本片段，用于核对正文/公式/表格的实际字号。

用法：
    python scripts/diag/span_sizes.py 13 15 20
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
DOCS = {
    "本论文": ROOT / "paper" / "山区洪涝灾害下无人机运输与通信协同优化_论文.pdf",
    "参考文稿2": ROOT / "docs" / "reference" / "参考文稿2.pdf",
}


def main() -> int:
    import fitz

    which = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in DOCS else "本论文"
    pages = [int(a) for a in sys.argv[2:]] or [13]
    pdf = DOCS[which]
    doc = fitz.open(str(pdf))
    print(f"文件：{which}（共 {len(doc)} 页）")
    for pno in pages:
        page = doc[pno - 1]
        print(f"\n=== 第 {pno} 页 ===")
        for b in page.get_text("dict").get("blocks", []):
            for line in b.get("lines", []):
                for s in line.get("spans", []):
                    t = s["text"].strip()
                    if not t:
                        continue
                    print(f"  {s['size']:>5.1f}pt {s['font'][:22]:<24} {t[:58]!r}")
    doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
