"""诊断 3：对比不同构建方式的 docx 在 Word 中能否正常分页/导出 PDF。

用法：
    python scripts/diag_word_compare.py file1.docx file2.docx ...
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[1]


def probe(path: Path) -> None:
    import win32com.client as win32

    out = path.with_name(path.stem + "_probe.pdf")
    if out.exists():
        out.unlink()
    print(f"\n=== {path.name}  ({path.stat().st_size/1024/1024:.2f} MB) ===")
    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = False
    try:
        word.DisplayAlerts = 0
    except Exception:  # noqa: BLE001
        pass
    try:
        doc = word.Documents.Open(str(path), ReadOnly=True)
        try:
            time.sleep(1.5)
            print(f"  pages(首次)        = {doc.ComputeStatistics(2)}")
            try:
                doc.Repaginate()
                print(f"  Repaginate         = OK → {doc.ComputeStatistics(2)} 页")
            except Exception as e:  # noqa: BLE001
                print(f"  Repaginate         = FAIL {str(e)[:100]}")
            try:
                doc.ExportAsFixedFormat(str(out), 17)
                print(f"  ExportAsFixedFormat= OK → {out.stat().st_size/1024/1024:.2f} MB")
            except Exception as e:  # noqa: BLE001
                print(f"  ExportAsFixedFormat= FAIL {str(e)[:120]}")
        finally:
            doc.Close(SaveChanges=False)
    finally:
        word.Quit()
        time.sleep(1.5)
    if out.exists():
        out.unlink()


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    for a in sys.argv[1:]:
        p = Path(a)
        if not p.is_absolute():
            p = ROOT / p
        if not p.exists():
            print(f"跳过不存在的文件：{p}")
            continue
        probe(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
