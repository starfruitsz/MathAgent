"""统计 pandoc 产出的 docx 结构（公式/标题/表格/图片/样式）。

用法：python scripts/diag/docx_struct_stats.py <docx> [<docx> ...]
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

PATS = {
    "m:oMath 公式": r"<m:oMath[ >]",
    "m:oMathPara 公式段": r"<m:oMathPara[ >]",
    "标题 Heading1": r'w:val="Heading1"',
    "标题 Heading2": r'w:val="Heading2"',
    "标题 Heading3": r'w:val="Heading3"',
    "标题 Title": r'w:val="Title"',
    "表格 w:tbl": r"<w:tbl>",
    "段落 w:p": r"<w:p[ >]",
    "分页 w:br type=page": r'w:type="page"',
}


def main() -> int:
    for arg in sys.argv[1:]:
        p = Path(arg)
        z = zipfile.ZipFile(p)
        xml = z.read("word/document.xml").decode("utf-8")
        styles = z.read("word/styles.xml").decode("utf-8")
        media = sum(1 for n in z.namelist() if n.startswith("word/media/"))
        print(f"=== {p.name}  ({p.stat().st_size/1024/1024:.2f} MB) ===")
        for label, pat in PATS.items():
            print(f"  {label:<22} {len(re.findall(pat, xml))}")
        print(f"  {'图片 media':<22} {media}")
        print(f"  {'styles.xml 样式数':<22} {styles.count('<w:style ')}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
