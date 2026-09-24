"""调试：检查自建 CFB 的 mini stream 与目录项是否正确。

用法：
    python scripts/diag/inspect_cfb.py
"""

from __future__ import annotations

import struct
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_ole_streams import cfb_streams  # noqa: E402
from report.cfb import build_cfb  # noqa: E402

ORDER = ["\x01CompObj", "\x01Ole", "\x03ObjInfo", "Equation Native"]


def main() -> int:
    base = ROOT / "paper" / "_probe_min" / "step1_convert_only.docx"
    with zipfile.ZipFile(base) as z:
        n = [x for x in z.namelist() if x.startswith("word/embeddings/")][0]
        our = cfb_streams(z.read(n))
    streams = [(k, our[k]) for k in ORDER if k in our]
    b = build_cfb(streams)
    print(f"built = {len(b)} bytes")

    print("\n--- 头部 ---")
    for off, name in ((44, "FAT 扇区数"), (48, "目录起始"), (56, "mini 阈值"),
                      (60, "miniFAT 起始"), (64, "miniFAT 扇区数"),
                      (68, "首个 DIFAT"), (72, "DIFAT 数")):
        print(f"  [{off:>2}] {name:<12} = {struct.unpack_from('<I', b, off)[0]}")
    print(f"  DIFAT[0..3] = "
          f"{[struct.unpack_from('<I', b, 76 + i * 4)[0] for i in range(4)]}")

    dir_start = struct.unpack_from("<I", b, 48)[0]
    print(f"\n--- 目录（起始扇区 {dir_start}）---")
    for k in range(len(streams) + 1):
        e = b[512 + dir_start * 512 + k * 128:][:128]
        nlen = struct.unpack_from("<H", e, 64)[0]
        nm = (e[: max(0, nlen - 2)].decode("utf-16-le", "ignore")
              if 0 < nlen <= 64 else "<bad>")
        print(f"  [{k}] {nm!r:<18} type={e[66]} L={struct.unpack_from('<I', e, 68)[0]:>10} "
              f"R={struct.unpack_from('<I', e, 72)[0]:>10} "
              f"C={struct.unpack_from('<I', e, 76)[0]:>10} "
              f"start={struct.unpack_from('<I', e, 116)[0]:>3} "
              f"size={struct.unpack_from('<Q', e, 120)[0]}")

    # mini stream 是否包含原数据？
    print("\n--- mini stream 内容校验 ---")
    ms_start = None
    for k in range(len(streams) + 1):
        e = b[512 + dir_start * 512 + k * 128:][:128]
        nlen = struct.unpack_from("<H", e, 64)[0]
        nm = (e[: max(0, nlen - 2)].decode("utf-16-le", "ignore")
              if 0 < nlen <= 64 else "")
        if nm == "Root Entry":
            ms_start = struct.unpack_from("<I", e, 116)[0]
    print(f"  mini stream 起始扇区 = {ms_start}")
    ms = b[512 + ms_start * 512:]
    for name, data in streams:
        pos = ms.find(data)
        print(f"    {name!r:<18} 在 mini stream 中偏移 {pos}  (期望 = 起始×64)")

    got = cfb_streams(b)
    print(f"\n--- 回读 ---\n  {[(k, len(v)) for k, v in got.items()]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
