"""论文页数与体量核算（用 Word COM 精确统计）。

用途：竞赛要求正文页数落在 50~100 页，本脚本用于生成后自检。

用法：
    python scripts/check_paper.py
    python scripts/check_paper.py --pdf          # 同时导出 PDF

输出：
    paper/论文体量报告.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCX = REPO / "paper" / "山区洪涝灾害下无人机运输与通信协同优化_论文.docx"
PDF = REPO / "paper" / "山区洪涝灾害下无人机运输与通信协同优化_论文.pdf"
REPORT = REPO / "paper" / "论文体量报告.json"

# Word 统计常量
WD_STAT_WORDS = 0
WD_STAT_PAGES = 2
WD_STAT_CHARS = 3
WD_FORMAT_PDF = 17


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", action="store_true", help="同时导出 PDF")
    args = ap.parse_args()

    if not DOCX.exists():
        print(f"❌ 论文不存在：{DOCX}\n请先运行 python -m src.report.build_paper")
        return 1

    try:
        import win32com.client as win32
    except ImportError:
        print("❌ 需要 pywin32：pip install pywin32")
        return 1

    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = False
    rep: dict = {}
    pdf_ok = False
    try:
        doc = word.Documents.Open(str(DOCX), ReadOnly=False)
        try:
            doc.Fields.Update()
            for toc in doc.TablesOfContents:
                toc.Update()
            doc.Repaginate()
            rep = {
                "文件": DOCX.name,
                "大小MB": round(DOCX.stat().st_size / 1024 / 1024, 2),
                "页数": int(doc.ComputeStatistics(WD_STAT_PAGES)),
                "字数": int(doc.ComputeStatistics(WD_STAT_WORDS)),
                "字符数": int(doc.ComputeStatistics(WD_STAT_CHARS)),
                "表格数": int(doc.Tables.Count),
                "内嵌图片数": int(doc.InlineShapes.Count),
            }
            doc.Save()
            # ★ 先导出 PDF，再关闭：SaveAs2 会把"当前文档"指向 PDF 导出物，
            #   若之后再用同一个 doc 引用 Save/Close 会抛出"对象已断开连接"。
            if args.pdf:
                try:
                    doc.SaveAs2(str(PDF), FileFormat=WD_FORMAT_PDF)
                    pdf_ok = True
                except Exception as e:  # noqa: BLE001
                    print(f"⚠️  PDF 导出失败（不影响页数统计）：{e}")
        finally:
            doc.Close(SaveChanges=False)
    finally:
        word.Quit()

    if pdf_ok and PDF.exists():
        rep["PDF文件"] = PDF.name
        rep["PDF大小MB"] = round(PDF.stat().st_size / 1024 / 1024, 2)

    rep["页数达标(50~100)"] = bool(50 <= rep["页数"] <= 100)
    REPORT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 62)
    print("论文体量核算")
    print("=" * 62)
    for k, v in rep.items():
        print(f"  {k:<18} {v}")
    print()
    if rep["页数达标(50~100)"]:
        print("✅ 页数符合 50~100 页要求")
    else:
        print("⚠️  页数不在 50~100 页区间，需要调整内容量")
    print(f"报告：{REPORT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
