"""对照实验：Word 自己产生的 OLE 对象长什么样？我们的差在哪？

做法：在 Word 里插入一个 MathType 对象（`Shapes.AddOLEObject`，Word 会去实例化
真品 MathType），保存后解剖它的 XML 与 OLE 流，与 `docx-equation` 的产物逐项对比。

用法：
    python scripts/diag/make_reference_object.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
WORK = ROOT / "paper" / "_probe_min"


def main() -> int:
    import win32com.client as win32

    WORK.mkdir(parents=True, exist_ok=True)
    docx = WORK / "ref_object.docx"
    docx.unlink(missing_ok=True)

    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    try:
        doc = word.Documents.Add()
        time.sleep(1.0)
        doc.Content.Text = "参照："
        rng = doc.Content
        rng.Collapse(0)  # wdCollapseEnd
        print("插入 MathType OLE 对象（ProgID=Equation.DSMT4）…")
        shape = doc.InlineShapes.AddOLEObject(ClassType="Equation.DSMT4",
                                              Range=rng, LinkToFile=False,
                                              DisplayAsIcon=False)
        time.sleep(4.0)
        print(f"  插入完成：宽 {shape.Width:.1f}pt 高 {shape.Height:.1f}pt")
        try:
            print(f"  OLEFormat.ProgID = {shape.OLEFormat.ProgID}")
        except Exception as exc:  # noqa: BLE001
            print(f"  ❌ 读 ProgID 失败：{str(exc)[:120]}")

        doc.SaveAs2(str(docx), FileFormat=16)
        time.sleep(1.0)
        print(f"已保存：{docx.name} ({docx.stat().st_size} bytes)")
        doc.Close(SaveChanges=False)
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 插入失败：{type(exc).__name__}: {str(exc)[:300]}")
        return 1
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
