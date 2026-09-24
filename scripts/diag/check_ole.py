"""诊断：docx 中的 MathType OLE 对象是否为**合法的 OLE 复合文档**。

Word/MathType 双击打开公式时，读的是 `word/embeddings/oleObjectMathTypeNNN.bin`。
若它不是合法的 OLE2 复合文件（CFB），双击就不会唤起 MathType。

用法：
    python scripts/diag/check_ole.py
"""

from __future__ import annotations

import io
import struct
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
DOCX = ROOT / "paper" / "山区洪涝灾害下无人机运输与通信协同优化_论文.docx"

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"   # CFB 复合文档签名
EQNO_MAGIC = b"\x1c\x00\x00\x00"                    # MathType "EQNO" 片段头
MTEF_MAGIC = b"\x03\x00\x00\x00"                    # MathType "MTEF" 片段头


def describe(data: bytes) -> list[str]:
    out = []
    out.append(f"    前 32 字节: {data[:32].hex(' ')}")
    out.append(f"    ASCII 视图 : "
               f"{''.join(chr(b) if 32 <= b < 127 else '.' for b in data[:32])}")
    out.append(f"    是否 OLE2 CFB  : {data[:8] == OLE_MAGIC}")
    if data[:8] != OLE_MAGIC:
        # 尝试按 OLE1 / MathType 原生流解析
        if data[:4] == b"\x01\x02\x00\x00" or data[:2] in (b"\x01\x02", b"\x02\x01"):
            out.append("    疑似 OLE1 (Word 6/95) …")
        # MathType 原生格式：0x0000001C(EQNO) / 0x00000003(MTEF) 等片段
        frag = struct.unpack_from("<I", data, 0)[0] if len(data) >= 4 else -1
        out.append(f"    首 4 字节小端 = {frag} (0x{frag & 0xFFFFFFFF:08X})")
        if data[:4] == EQNO_MAGIC:
            out.append("    → 像 MathType EQNO 片段（OLE1 式，无 CFB 容器）")
        elif data[:4] == MTEF_MAGIC:
            out.append("    → 像 MathType MTEF 片段")
        else:
            out.append("    → 无法识别的容器格式")
    return out


def main() -> int:
    if not DOCX.exists():
        print(f"❌ 未找到 {DOCX}")
        return 1
    with zipfile.ZipFile(DOCX) as z:
        bins = sorted(n for n in z.namelist() if n.startswith("word/embeddings/"))
        print(f"embeddings 文件数：{len(bins)}\n")
        for n in bins[:3]:
            data = z.read(n)
            print(f"  {n.rsplit('/', 1)[-1]}  ({len(data)} bytes)")
            for line in describe(data):
                print(line)
            print()
        sizes = {z.getinfo(n).file_size for n in bins}
        print(f"全部 embeddings 大小集合：{sorted(sizes)}")

    # 该库是通过什么函数生成 OLE 字节的？
    import inspect

    from docx_equation.mathtype import mtef as _mtef

    src = inspect.getsource(_mtef)
    for key in ("def build_mathtype_ole_object", "def encode_mtef"):
        i = src.find(key)
        if i >= 0:
            print(f"\n--- {key} ---")
            print(src[i:i + 1200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
