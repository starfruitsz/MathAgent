"""查 PDF 中 ①②③ 用的是哪个字体，判断是否为缺字形导致的"豆腐块"。

用法：python scripts/diag/pdf_glyph_font.py <pdf> [字符...]
"""

from __future__ import annotations

import sys
from pathlib import Path

import fitz

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]


def main() -> int:
    pdf = Path(sys.argv[1] if len(sys.argv) > 1 else "otheragent/document.pdf")
    chars = sys.argv[2] if len(sys.argv) > 2 else "①②③④⑤"
    doc = fitz.open(str(pdf))

    seen: dict[str, set[tuple[str, float]]] = {}
    for pno, page in enumerate(doc, 1):
        for b in page.get_text("dict")["blocks"]:
            for line in b.get("lines", []):
                for span in line["spans"]:
                    for ch in chars:
                        if ch in span["text"]:
                            seen.setdefault(ch, set()).add(
                                (f"{span['font']}@{pno}", round(span["size"], 1)))
    if not seen:
        print(f"（PDF 中未找到这些字符：{chars}）")
        return 0
    for ch in chars:
        if ch in seen:
            fonts = ", ".join(sorted({f.split("@")[0] for f, _ in seen[ch]}))
            pages = sorted({int(f.split("@")[1]) for f, _ in seen[ch]})
            print(f"{ch}  字体={fonts}  出现页={pages}")

    print("\n=== 该 PDF 用到的全部字体 ===")
    allf: set[str] = set()
    for page in doc:
        for f in page.get_fonts():
            allf.add(f[3])
    for f in sorted(allf):
        print("  ", f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
