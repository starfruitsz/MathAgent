"""检查 pandoc 产出的 docx：Word 能否打开、页数、公式数、导出 PDF。

用法：python scripts/diag/check_pandoc_docx.py <docx> [out.pdf]
"""

from __future__ import annotations

import re
import sys
import time
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

DOCX = Path(sys.argv[1] if len(sys.argv) > 1 else "otheragent/_pandoc/from_tex.docx")
PDF = Path(sys.argv[2]) if len(sys.argv) > 2 else None

WD_STAT_PAGES, WD_STAT_WORDS, WD_STAT_CHARS = 2, 0, 3
WD_FORMAT_PDF = 17


def main() -> int:
    z = zipfile.ZipFile(DOCX)
    xml = z.read("word/document.xml").decode("utf-8")
    print(f"文件: {DOCX}  ({DOCX.stat().st_size/1024/1024:.2f} MB)")
    print(f"  m:oMath {len(re.findall(r'<m:oMath[ >]', xml))} 个"
          f"（其中公式段落 m:oMathPara {len(re.findall(r'<m:oMathPara[ >]', xml))} 个）")
    print(f"  图片 {sum(1 for n in z.namelist() if n.startswith('word/media/'))} 张"
          f"，表格 {len(re.findall(r'<w:tbl>', xml))} 个")

    import win32com.client as win32
    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = False
    try:
        doc = word.Documents.Open(str(DOCX.resolve()), ReadOnly=False)
        try:
            time.sleep(2.0)
            doc.Repaginate()
            pages = int(doc.ComputeStatistics(WD_STAT_PAGES))
            print(f"  Word 页数 {pages}"
                  f"，字数 {int(doc.ComputeStatistics(WD_STAT_WORDS))}"
                  f"，表格 {int(doc.Tables.Count)}"
                  f"，内嵌图 {int(doc.InlineShapes.Count)}")
            # 公式是否可被 Word 识别为原生公式对象
            try:
                n_om = int(doc.OMaths.Count)
                print(f"  Word 识别到的公式对象 OMaths.Count = {n_om}")
                if n_om:
                    doc.OMaths(1).BuildUp()
                    print("  首个公式 BuildUp() 成功（原生可编辑）")
            except Exception as e:  # noqa: BLE001
                print(f"  （OMaths 查询失败：{str(e)[:80]}）")
            if PDF is not None:
                if PDF.exists():
                    PDF.unlink()
                doc.ExportAsFixedFormat(str(PDF.resolve()), WD_FORMAT_PDF)
                print(f"  已导出 {PDF}  ({PDF.stat().st_size/1024/1024:.2f} MB)")
        finally:
            doc.Close(SaveChanges=False)
    finally:
        word.Quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
