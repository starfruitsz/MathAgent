"""隔离实验：逐步修改 docx-equation 的 OLE 对象，找出 Word 不接受的原因。

真品（Word + MathType 插入）与我们的产物，`\\x03ObjInfo` 流不同：
    真品  00 00 03 00 04 00
    我们  00 00 03 00 01 00
本脚本按变量逐个试：改 ObjInfo → 再改 CompObj → 再改 CFB 内流顺序，
每次都用 Word 检查 `OLEFormat.ProgID` 是否可读、能否 Activate。

用法：
    python scripts/diag/isolate_ole.py
"""

from __future__ import annotations

import subprocess
import struct
import sys
import time
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
WORK = ROOT / "paper" / "_probe_min"
BASE_DOCX = WORK / "step1_convert_only.docx"   # 单个公式、未重绘预览图
REF_DOCX = WORK / "ref_object.docx"            # 真品


def patch_cfb(data: bytes, edits: dict[bytes, bytes]) -> bytes:
    """直接替换 CFB 中的字节序列（流内容未压缩，简单替换即可用于实验）。"""
    out = data
    for old, new in edits.items():
        if old not in out:
            raise ValueError(f"未找到待替换字节：{old.hex(' ')}")
        out = out.replace(old, new)
    return out


def cfb_stream_bytes(data: bytes, stream: str) -> bytes:
    from check_ole_streams import cfb_streams
    return cfb_streams(data)[stream]


def variant(name: str, edits: dict[bytes, bytes]) -> Path:
    out = WORK / f"var_{name}.docx"
    with zipfile.ZipFile(BASE_DOCX) as z:
        items = {i.filename: z.read(i.filename) for i in z.infolist()}
    targets = [n for n in items if n.startswith("word/embeddings/")]
    for n in targets:
        items[n] = patch_cfb(items[n], edits)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in items.items():
            z.writestr(n, b)
    return out


def test(docx: Path, label: str) -> bool:
    import win32com.client as win32

    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    try:
        doc = word.Documents.Open(str(docx))
        try:
            time.sleep(2.0)
            n = doc.InlineShapes.Count
            ole = [i for i in range(1, n + 1)
                   if int(doc.InlineShapes.Item(i).Type) == 1]
            if not ole:
                print(f"  [{label}] ❌ 无 OLE 对象（InlineShapes={n}）")
                return False
            sh = doc.InlineShapes.Item(ole[0])
            try:
                prog = sh.OLEFormat.ProgID
            except Exception as exc:  # noqa: BLE001
                print(f"  [{label}] ❌ ProgID 读取失败：{str(exc)[:90]}")
                return False
            try:
                sh.OLEFormat.Activate()
                time.sleep(3.0)
                print(f"  [{label}] ✅ ProgID={prog} 且 Activate 成功")
                return True
            except Exception as exc:  # noqa: BLE001
                print(f"  [{label}] ⚠️  ProgID={prog} 但 Activate 失败：{str(exc)[:90]}")
                return False
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
        time.sleep(1.0)


def main() -> int:
    if not BASE_DOCX.exists():
        print(f"❌ 缺少基线 {BASE_DOCX}\n请先运行 scripts/diag/probe_minimal.py")
        return 1
    WORK.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(BASE_DOCX) as z:
        emb = [n for n in z.namelist() if n.startswith("word/embeddings/")][0]
        base = z.read(emb)
    objinfo = cfb_stream_bytes(base, "\x03ObjInfo")
    compobj = cfb_stream_bytes(base, "\x01CompObj")
    ole = cfb_stream_bytes(base, "\x01Ole")
    native = cfb_stream_bytes(base, "Equation Native")
    print(f"基线 OLE：{len(base)} bytes")
    print(f"  ObjInfo : {objinfo.hex(' ')}")
    print(f"  CompObj : {compobj.hex(' ')}")
    print(f"  \\1Ole   : {ole.hex(' ')}")
    print(f"  Native  : {len(native)} bytes  头 {native[:12].hex(' ')}")

    if REF_DOCX.exists():
        with zipfile.ZipFile(REF_DOCX) as z:
            ref = z.read([n for n in z.namelist()
                          if n.startswith("word/embeddings/")][0])
        print(f"\n真品 OLE：{len(ref)} bytes")
        print(f"  ObjInfo : {cfb_stream_bytes(ref, chr(3) + 'ObjInfo').hex(' ')}")
        print(f"  CompObj : {cfb_stream_bytes(ref, chr(1) + 'CompObj').hex(' ')}")
        print(f"  \\1Ole   : {cfb_stream_bytes(ref, chr(1) + 'Ole').hex(' ')}")
        rn = cfb_stream_bytes(ref, "Equation Native")
        print(f"  Native  : {len(rn)} bytes  头 {rn[:12].hex(' ')}")

    print("\n=== 逐变量测试 ===")
    tests = [
        ("baseline", {}),
        ("objinfo04", {objinfo: b"\x00\x00\x03\x00\x04\x00"}),
    ]
    for label, edits in tests:
        try:
            docx = variant(label, edits)
        except Exception as exc:  # noqa: BLE001
            print(f"  [{label}] 构造失败：{exc}")
            continue
        test(docx, label)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
