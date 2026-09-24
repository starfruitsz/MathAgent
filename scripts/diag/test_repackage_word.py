"""让 Word 验证"用新 CFB 容器重打包"的 OLE 对象能否被识别与激活。

用法：
    python -u scripts/diag/test_repackage_word.py
"""

from __future__ import annotations

import subprocess
import sys
import time
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_ole_streams import cfb_streams  # noqa: E402
from report.cfb import build_cfb  # noqa: E402

ORDER = ["\x01CompObj", "\x01Ole", "\x03ObjInfo", "Equation Native"]
WORK = ROOT / "paper" / "_probe_min"


def make() -> Path:
    base = WORK / "step1_convert_only.docx"
    with zipfile.ZipFile(base) as z:
        n = [x for x in z.namelist() if x.startswith("word/embeddings/")][0]
        our = cfb_streams(z.read(n))
        items = {i.filename: z.read(i.filename) for i in z.infolist()}
    streams = [(k, our[k]) for k in ORDER if k in our]
    built = build_cfb(streams)
    print(f"重建容器：{len(built)} bytes；"
          f"回读 {[(k, len(v)) for k, v in cfb_streams(built).items()]}", flush=True)
    emb = [x for x in items if x.startswith("word/embeddings/")][0]
    items[emb] = built
    out = WORK / "var_repackage.docx"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for k, v in items.items():
            z.writestr(k, v)
    print(f"写出 {out.name}", flush=True)
    return out


def main() -> int:
    out = make()
    import win32com.client as win32

    print("启动 Word …", flush=True)
    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    try:
        print("打开文档 …", flush=True)
        doc = word.Documents.Open(str(out))
        print("已打开", flush=True)
        try:
            n_sh = doc.InlineShapes.Count
            oles = [i for i in range(1, n_sh + 1)
                    if int(doc.InlineShapes.Item(i).Type) == 1]
            print(f"  InlineShapes={n_sh}  OLE={len(oles)}", flush=True)
            if oles:
                sh = doc.InlineShapes.Item(oles[0])
                try:
                    print(f"  ProgID = {sh.OLEFormat.ProgID}", flush=True)
                except Exception as exc:  # noqa: BLE001
                    print(f"  ❌ ProgID 读取失败：{str(exc)[:100]}", flush=True)
                try:
                    sh.OLEFormat.Activate()
                    time.sleep(3.0)
                    print("  ✅ Activate 成功 —— 新容器可用！", flush=True)
                except Exception as exc:  # noqa: BLE001
                    print(f"  ❌ Activate 失败：{str(exc)[:100]}", flush=True)
        finally:
            try:
                doc.Close(SaveChanges=False)
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        print(f"❌ 打开/处理失败：{type(exc).__name__}: {str(exc)[:200]}", flush=True)
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
