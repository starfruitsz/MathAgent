"""尝试用 Word + MathType 的**官方批量转换**把 OMML 公式变成 MathType 对象。

MathType 的 Word 加载项提供「转换公式 / Convert Equations」命令。
本脚本在 Word 里插入一个内置公式（OMML），然后尝试通过多种途径调用该命令，
并检查转换后 `OLEFormat.ProgID` 是否可读、能否激活。

用法：
    python scripts/diag/try_batch_convert.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "paper" / "_probe_min"

CANDIDATES = [
    "MathTypeConvertEquations",
    "MathTypeCommandsConvertEquations",
    "ConvertEquations",
    "MTConvertEquations",
    "MathType.ConvertEquations",
]


def main() -> int:
    import win32com.client as win32

    WORK.mkdir(parents=True, exist_ok=True)
    docx = WORK / "batch_convert.docx"
    docx.unlink(missing_ok=True)

    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    try:
        doc = word.Documents.Add()
        time.sleep(1.0)
        doc.Content.Text = "公式："
        time.sleep(0.5)
        # 在文档末尾插入一个内置公式，并写入线性格式后 BuildUp
        end = doc.Range()
        end.Collapse(0)
        end.Text = "x=(-b+sqrt(b^2-4ac))/(2a)"
        time.sleep(0.5)
        m = doc.OMaths.Add(doc.Range(end.Start, end.End))
        doc.OMaths.BuildUp()
        time.sleep(1.5)
        print(f"OMMaths = {doc.OMaths.Count}")

        print("\n=== 尝试调用 MathType 转换命令 ===")
        for name in CANDIDATES:
            try:
                r = word.Run(name)
                time.sleep(3.0)
                n_ole = sum(1 for i in range(1, doc.InlineShapes.Count + 1)
                            if int(doc.InlineShapes.Item(i).Type) == 1)
                print(f"  {name}: Run 返回 {r!r}；InlineShapes={doc.InlineShapes.Count}"
                      f"  OLE={n_ole}  OMaths={doc.OMaths.Count}")
                if n_ole:
                    break
            except Exception as exc:  # noqa: BLE001
                print(f"  {name}: ❌ {type(exc).__name__}: {str(exc)[:110]}")

        print("\n=== 尝试 AddIns / Templates 里的 MathType 宏 ===")
        for coll, label in ((word.AddIns, "AddIns"), (word.Templates, "Templates")):
            try:
                for a in coll:
                    nm = getattr(a, "Name", "?")
                    if "ath" in str(nm) or "MT" in str(nm):
                        print(f"  {label}: {nm}")
            except Exception as exc:  # noqa: BLE001
                print(f"  {label} 枚举失败：{str(exc)[:80]}")

        # 状态
        n_ole = sum(1 for i in range(1, doc.InlineShapes.Count + 1)
                    if int(doc.InlineShapes.Item(i).Type) == 1)
        print(f"\n最终：InlineShapes={doc.InlineShapes.Count}  OLE={n_ole}"
              f"  OMaths={doc.OMaths.Count}")
        if n_ole:
            sh = [doc.InlineShapes.Item(i) for i in range(1, doc.InlineShapes.Count + 1)
                  if int(doc.InlineShapes.Item(i).Type) == 1][0]
            try:
                print(f"  ProgID = {sh.OLEFormat.ProgID}")
                sh.OLEFormat.Activate()
                time.sleep(3.0)
                print("  ✅ 转换出的对象可激活")
            except Exception as exc:  # noqa: BLE001
                print(f"  ❌ 激活/ProgID 失败：{str(exc)[:110]}")

        doc.SaveAs2(str(docx), FileFormat=16)
        print(f"\n已保存 {docx.name} ({docx.stat().st_size} bytes)")
        doc.Close(SaveChanges=False)
    finally:
        try:
            word.Quit()
        except Exception:  # noqa: BLE001
            pass
        subprocess.run(["taskkill", "/F", "/IM", "WINWORD.EXE"],
                       capture_output=True, check=False)
        subprocess.run(["taskkill", "/F", "/IM", "MathType.exe"],
                       capture_output=True, check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
