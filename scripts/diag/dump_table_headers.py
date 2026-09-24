"""抽取 docx 中的表格表头，人工核对表头（含单位公式）是否正确。

用法：
    python scripts/dump_table_headers.py
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[1]
DOCX = ROOT / "paper" / "山区洪涝灾害下无人机运输与通信协同优化_论文.docx"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"


def cell_text(tc) -> str:
    """单元格文本；OMML 公式用 <公式> 占位以显示其位置与数量。"""
    parts = []
    for child in tc.iter():
        if child.tag == f"{M}oMath":
            parts.append("<公式>")
        elif child.tag == f"{W}t":
            # 跳过已在 oMath 内统计过的 w:t
            anc = child
            inside = False
            while anc is not None:
                if anc.tag == f"{M}oMath":
                    inside = True
                    break
                anc = None
            if not inside:
                parts.append(child.text or "")
    return "".join(parts).strip()


def main() -> int:
    with zipfile.ZipFile(DOCX) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(f"{W}body")
    tables = body.findall(f"{W}tbl")
    print(f"表格总数：{len(tables)}\n")
    for i, t in enumerate(tables, 1):
        rows = t.findall(f"{W}tr")
        hdr = rows[0].findall(f"{W}tc") if rows else []
        names = " | ".join(cell_text(c) for c in hdr)
        print(f"[{i:2d}] 行数 {len(rows):>3}  列数 {len(hdr):>2}  {names[:170]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
