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
import time
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


def _retry(fn, *a, tries: int = 15, delay: float = 2.0, **kw):
    """Word 忙于加载 MathType OLE 对象时会抛"调用被拒绝"(-2147418111)，退避重试。"""
    for i in range(tries):
        try:
            return fn(*a, **kw)
        except Exception as exc:  # noqa: BLE001
            if "-2147418111" not in str(exc):
                raise
            if i == tries - 1:
                raise
            time.sleep(delay)


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
    # ★ 含 71 个 MathType OLE 的文档必须让 Word 完成真实排版。
    #   实测：Visible=False + ReadOnly=True 最稳；设 Visible=True 会让
    #   Word 尝试激活 OLE 服务器，反而使 COM 调用被拒（-2147418111）。
    word.Visible = False
    word.DisplayAlerts = 0
    rep: dict = {}
    pdf_ok = False
    try:
        doc = _retry(word.Documents.Open, str(DOCX), ReadOnly=True)
        try:
            time.sleep(2.0)
            # ★ 顺序很关键：先做一次统计（触发 Word 完成首轮排版），
            #   再 Repaginate。反过来在含大量 OLE 对象时会被拒（-2147418111）。
            pages = int(_retry(doc.ComputeStatistics, WD_STAT_PAGES))
            _retry(doc.Repaginate)
            pages = int(_retry(doc.ComputeStatistics, WD_STAT_PAGES))
            rep = {
                "文件": DOCX.name,
                "大小MB": round(DOCX.stat().st_size / 1024 / 1024, 2),
                "页数": pages,
                "字数": int(_retry(doc.ComputeStatistics, WD_STAT_WORDS)),
                "字符数": int(_retry(doc.ComputeStatistics, WD_STAT_CHARS)),
                "表格数": int(_retry(lambda: doc.Tables.Count)),
                "内嵌对象数": int(_retry(lambda: doc.InlineShapes.Count)),
            }
            # ★ 先导出 PDF，再关闭：SaveAs2 会把"当前文档"指向 PDF 导出物，
            #   若之后再用同一个 doc 引用 Save/Close 会抛出"对象已断开连接"。
            if args.pdf and PDF.exists():
                PDF.unlink()
            if args.pdf:
                try:
                    _retry(doc.ExportAsFixedFormat, str(PDF), WD_FORMAT_PDF)
                    pdf_ok = PDF.exists()
                except Exception as e:  # noqa: BLE001
                    print(f"⚠️  PDF 导出失败（不影响页数统计）：{e}")
        finally:
            try:
                _retry(doc.Close, SaveChanges=False, tries=5, delay=2.0)
            except Exception as e:  # noqa: BLE001
                # 文档含大量 OLE 时 Close 偶尔被拒；此时强制结束 Word 即可，
                # 统计与 PDF 均已取到，不影响结果。
                print(f"（提示：文档 Close 被拒，将强制结束 Word：{str(e)[:60]}）")
    finally:
        try:
            word.Quit()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1.0)
        # 兜底：若 COM 未能正常退出 Word，清理残留进程，避免影响后续构建
        import subprocess

        subprocess.run(["taskkill", "/F", "/IM", "WINWORD.EXE"],
                       capture_output=True, check=False)

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
