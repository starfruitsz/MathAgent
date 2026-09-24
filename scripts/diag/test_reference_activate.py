"""对照：真品 MathType 对象在 Word 里能否激活？（验证实验台本身是否可信）

若真品也不能激活，说明是实验方法问题而非对象问题。

用法：
    python scripts/diag/test_reference_activate.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "paper" / "_probe_min" / "ref_object.docx"


def main() -> int:
    import win32com.client as win32

    if not REF.exists():
        print(f"❌ 缺少真品样本 {REF}")
        return 1
    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    try:
        doc = word.Documents.Open(str(REF))
        try:
            time.sleep(2.0)
            n = doc.InlineShapes.Count
            print(f"InlineShapes = {n}")
            for i in range(1, n + 1):
                sh = doc.InlineShapes.Item(i)
                t = int(sh.Type)
                print(f"  [{i}] Type={t}", end="")
                if t == 1:
                    try:
                        print(f"  ProgID={sh.OLEFormat.ProgID}", end="")
                    except Exception as exc:  # noqa: BLE001
                        print(f"  ProgID 读取失败({str(exc)[:60]})", end="")
                    try:
                        sh.OLEFormat.Activate()
                        time.sleep(3.0)
                        print("  ✅ Activate 成功")
                    except Exception as exc:  # noqa: BLE001
                        print(f"  ❌ Activate 失败({str(exc)[:80]})")
                else:
                    print()
        finally:
            try:
                doc.Close(SaveChanges=False)
            except Exception:  # noqa: BLE001
                pass
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
