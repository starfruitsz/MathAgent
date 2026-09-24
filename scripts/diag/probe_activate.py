"""诊断：让 Word 真正**激活**一个 MathType 公式对象，看 MathType 是否被唤起。

这是"双击打不开"的直接判据：把 Word 窗口显示出来，激活第 k 个 OLE 对象，
然后检查是否出现了 MathType 窗口 / 进程。

用法：
    python scripts/diag/probe_activate.py [对象序号，默认 1]
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
DOCX = ROOT / "paper" / "山区洪涝灾害下无人机运输与通信协同优化_论文.docx"


def windows_of(exe: str) -> list[str]:
    ps = ("Get-Process | Where-Object { $_.ProcessName -like '*%s*' } | "
          "Select-Object -ExpandProperty MainWindowTitle" % exe)
    r = subprocess.run(["pwsh", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True)
    return [t for t in r.stdout.splitlines() if t.strip()]


def main() -> int:
    import win32com.client as win32

    idx = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    print(f"文件：{DOCX.name}")
    print(f"激活前 MathType 窗口：{windows_of('MathType')}")

    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = True
    try:
        doc = word.Documents.Open(str(DOCX))
        time.sleep(2.0)
        n = doc.InlineShapes.Count
        oles = [i for i in range(1, n + 1)
                if int(doc.InlineShapes.Item(i).Type) == 1]
        print(f"InlineShapes={n}，其中 OLE 对象 {len(oles)} 个")
        if not oles:
            print("❌ 没有 OLE 对象")
            return 1
        target = oles[idx - 1]
        shape = doc.InlineShapes.Item(target)
        print(f"目标：第 {target} 个 InlineShape；"
              f"宽 {shape.Width:.1f}pt 高 {shape.Height:.1f}pt")
        try:
            print(f"  ProgID = {shape.OLEFormat.ProgID}")
            print(f"  ClassType = {shape.OLEFormat.ClassType}")
        except Exception as exc:  # noqa: BLE001
            print(f"  读取 OLEFormat 失败：{str(exc)[:140]}")
        print("\n尝试 Activate() …")
        try:
            shape.OLEFormat.Activate()
            time.sleep(6.0)
            print("  Activate 调用返回（无异常）")
        except Exception as exc:  # noqa: BLE001
            print(f"  ❌ Activate 抛异常：{type(exc).__name__}: {str(exc)[:200]}")
        w = windows_of("MathType")
        print(f"  激活后 MathType 窗口：{w}")
        print(f"  → {'✅ MathType 已被唤起（对象可编辑）' if w else '❌ 未唤起 MathType（双击同样打不开）'}")
    finally:
        try:
            doc.Close(SaveChanges=False)
        except Exception:  # noqa: BLE001
            pass
        try:
            word.Quit()
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
