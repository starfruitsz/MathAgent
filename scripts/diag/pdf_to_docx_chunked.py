"""PDF → Word：分块用 Word 的 PDF 重排转换，再合并为一个 docx。

为什么分块：整本 56 页一次性重排会崩（RPC 不可用）且极慢；
按 4 页切片后单片约 15 s，全量约 3~4 min，且产出的是
**Word 原生公式对象（OMML）**，不是图片。

用法：python scripts/diag/pdf_to_docx_chunked.py <in.pdf> <out.docx> [chunk_pages]
"""
import re, sys, time, zipfile
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
import fitz, win32com.client as win32

WD_PAGES, WD_DOCX = 2, 16


def count_omath(p: Path) -> tuple[int, int]:
    z = zipfile.ZipFile(p)
    xml = z.read("word/document.xml").decode("utf-8")
    return (len(re.findall(r"<m:oMath[ >]", xml)),
            len(re.findall(r"<m:oMathPara[ >]", xml)))


def main() -> int:
    # ★ Word COM 不继承进程 cwd，相对路径会被解析到 C:\\Windows\\system32
    #   ⇒ 必须转成绝对路径，否则报「很抱歉，找不到您的文件」。
    src = Path(sys.argv[1]).resolve(); dst = Path(sys.argv[2]).resolve()
    chunk = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    work = dst.parent / "_reflow_chunks"
    work.mkdir(parents=True, exist_ok=True)
    for f in work.glob("*"):
        f.unlink()

    doc = fitz.open(str(src)); n = doc.page_count
    chunks = []
    for k in range(0, n, chunk):
        out = fitz.open()
        for i in range(k, min(k + chunk, n)):
            out.insert_pdf(doc, from_page=i, to_page=i)
        p = work / f"c{k//chunk+1:03d}.pdf"; out.save(str(p)); out.close()
        chunks.append(p)
    doc.close()
    print(f"源 {n} 页 → {len(chunks)} 片（每片 {chunk} 页）")

    app = win32.Dispatch("Word.Application")
    app.Visible = False
    try: app.DisplayAlerts = 0
    except Exception: pass

    docxs, t0 = [], time.perf_counter()
    try:
        for k, p in enumerate(chunks, 1):
            d = app.Documents.Open(str(p), ConfirmConversions=False,
                                   ReadOnly=False, AddToRecentFiles=False)
            try:
                dx = p.with_suffix(".docx")
                d.SaveAs2(str(dx), FileFormat=WD_DOCX)
                docxs.append(dx)
            finally:
                d.Close(SaveChanges=False)
            print(f"  重排 {k}/{len(chunks)}  ({time.perf_counter()-t0:.0f}s)", end="\r")
        print()
        # 合并
        target = app.Documents.Add()
        for dx in docxs:
            rng = target.Content
            rng.Collapse(0)              # 0 = wdCollapseEnd
            rng.InsertFile(FileName=str(dx))
        if dst.exists(): dst.unlink()
        target.SaveAs2(str(dst), FileFormat=WD_DOCX)
        pages = int(target.ComputeStatistics(WD_PAGES))
        target.Close(SaveChanges=False)
        print(f"合并完成：{pages} 页")
    finally:
        try: app.Quit()
        except Exception: pass

    om, omp = count_omath(dst)
    print(f"产物 {dst.name}  {dst.stat().st_size/1024/1024:.2f} MB"
          f"  公式 m:oMath {om}（公式段 {omp}）")
    for f in work.glob("*"):
        f.unlink()
    work.rmdir()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
