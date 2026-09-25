"""把 PDF 转成 Word（docx）—— 用 Microsoft Word 自带的 PDF 重排（PDF Reflow）。

本机无 Acrobat；LibreOffice 对 PDF→docx 版面还原很差；Word 2013+ 内置 PDF 重排
是当前可用的最佳路径，且公式有机会被识别成 Word 原生 OMML 对象（而非图片）。

用法：python scripts/diag/pdf_to_docx.py <in.pdf> <out.docx>
"""

from __future__ import annotations

import re
import sys
import time
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import win32com.client as win32


def stats(p: Path) -> dict:
    z = zipfile.ZipFile(p)
    xml = z.read("word/document.xml").decode("utf-8")
    return {
        "oMath": len(re.findall(r"<m:oMath[ >]", xml)),
        "oMathPara": len(re.findall(r"<m:oMathPara[ >]", xml)),
        "media": sum(1 for n in z.namelist() if n.startswith("word/media/")),
        "tbl": len(re.findall(r"<w:tbl>", xml)),
        "p": len(re.findall(r"<w:p[ >]", xml)),
        "mb": p.stat().st_size / 1024 / 1024,
    }


def convert(src: Path, dst: Path) -> bool:
    if not src.exists():
        print(f"[错误] 找不到源 PDF：{src}")
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = False
    try:
        t0 = time.perf_counter()
        doc = word.Documents.Open(str(src), ConfirmConversions=False,
                                  ReadOnly=False, AddToRecentFiles=False)
        try:
            time.sleep(1.5)
            pages = int(doc.ComputeStatistics(2))
            print(f"  Word 已重排：{pages} 页，用时 {time.perf_counter()-t0:.1f}s")
            doc.SaveAs2(str(dst), FileFormat=16)   # 16 = wdFormatDocumentDefault (.docx)
            return True
        finally:
            doc.Close(SaveChanges=False)
    except Exception as e:
        print(f"  [失败] {type(e).__name__}: {str(e)[:200]}")
        return False
    finally:
        try:
            word.Quit()
        except Exception:
            pass


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    print(f"源：{src}  ({src.stat().st_size/1024/1024:.2f} MB)" if src.exists() else f"源缺失：{src}")
    if not convert(src, dst):
        return 1
    s = stats(dst)
    print(f"产物：{dst}")
    print(f"  m:oMath {s['oMath']}（公式段 {s['oMathPara']}）"
          f"，图片 {s['media']}，表格 {s['tbl']}，段落 {s['p']}，{s['mb']:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
