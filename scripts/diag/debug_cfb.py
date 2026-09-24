"""调试：用新写的 CFB 生成器重建 OLE 容器，并让 Word 验证能否激活。

用法：
    python scripts/diag/debug_cfb.py
"""

from __future__ import annotations

import subprocess
import sys
import time
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "src"))

from check_ole_streams import cfb_streams  # noqa: E402
from report.cfb import build_cfb  # noqa: E402

WORK = ROOT / "paper" / "_probe_min"
ORDER = ["\x01CompObj", "\x01Ole", "\x03ObjInfo", "Equation Native"]


def main() -> int:
    base = WORK / "step1_convert_only.docx"
    ref = WORK / "ref_object.docx"
    if not base.exists() or not ref.exists():
        print("❌ 需要先跑 probe_minimal.py 与 make_reference_object.py")
        return 1

    our = cfb_streams(zipfile.ZipFile(base).read(
        [n for n in zipfile.ZipFile(base).namelist()
         if n.startswith("word/embeddings/")][0]))
    streams = [(n, our[n]) for n in ORDER if n in our]
    print("装入容器：", {n: len(d) for n, d in streams})

    built = build_cfb(streams)
    print(f"生成 CFB：{len(built)} bytes")
    got = cfb_streams(built)
    print("回读：", {k: len(v) for k, v in got.items()})
    ok = all(got.get(n) == d for n, d in streams) and set(got) == {n for n, _ in streams}
    print(f"  往返一致：{'✅' if ok else '❌'}")

    out = WORK / "var_repackage.docx"
    with zipfile.ZipFile(base) as z:
        items = {i.filename: z.read(i.filename) for i in z.infolist()}
    items[[n for n in items if n.startswith("word/embeddings/")][0]] = built
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in items.items():
            z.writestr(n, b)
    print(f"已写出 {out.name}")

    import win32com.client as win32

    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    try:
        doc = word.Documents.Open(str(out))
        try:
            time.sleep(2.0)
            n_sh = doc.InlineShapes.Count
            oles = [i for i in range(1, n_sh + 1)
                    if int(doc.InlineShapes.Item(i).Type) == 1]
            print(f"  InlineShapes={n_sh}  OLE={len(oles)}")
            if oles:
                sh = doc.InlineShapes.Item(oles[0])
                try:
                    print(f"  ProgID = {sh.OLEFormat.ProgID}")
                except Exception as exc:  # noqa: BLE001
                    print(f"  ❌ ProgID 读取失败：{str(exc)[:100]}")
                try:
                    sh.OLEFormat.Activate()
                    time.sleep(3.0)
                    print("  ✅ Activate 成功 —— 新容器可用！")
                except Exception as exc:  # noqa: BLE001
                    print(f"  ❌ Activate 失败：{str(exc)[:100]}")
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
