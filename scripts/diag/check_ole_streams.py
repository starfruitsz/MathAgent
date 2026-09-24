"""诊断：解析 OLE2 复合文档内部流，判断 MathType 能否双击打开。

MathType 的 `Equation.DSMT4` 对象内部通常包含：
    \\1Ole              —— OLE1 头
    \\1Table / \\2Table  —— OLE1 数据表（Word 用来找 MTEF）
    Equation Native      —— ★ MathType 原生 MTEF 流（双击编辑靠它）

若缺少 `Equation Native`，双击就不会唤起 MathType。

用法：
    python scripts/diag/check_ole_streams.py
"""

from __future__ import annotations

import struct
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
DOCX = ROOT / "paper" / "山区洪涝灾害下无人机运输与通信协同优化_论文.docx"

FREESECT, ENDOFCHAIN, FATSECT, DIFSECT = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFC


def cfb_streams(data: bytes) -> dict[str, bytes]:
    """极简 CFB 解析：返回 {流名: 内容}（只处理本场景的小文件）。"""
    if data[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        raise ValueError("不是 OLE2 复合文档")
    sect_shift = struct.unpack_from("<H", data, 30)[0]
    mini_shift = struct.unpack_from("<H", data, 32)[0]
    sec_size, mini_size = 1 << sect_shift, 1 << mini_shift
    num_fat = struct.unpack_from("<I", data, 44)[0]
    dir_start = struct.unpack_from("<I", data, 48)[0]
    mini_cutoff = struct.unpack_from("<I", data, 56)[0]
    mini_fat_start = struct.unpack_from("<I", data, 60)[0]
    num_mini_fat = struct.unpack_from("<I", data, 64)[0]

    def sector_off(sid: int) -> int:
        return (sid + 1) * sec_size

    def read_chain(start: int, fat: list[int], size: int | None = None) -> bytes:
        out, sid, guard = bytearray(), start, 0
        while sid not in (ENDOFCHAIN, FREESECT) and guard < 100000:
            out += data[sector_off(sid): sector_off(sid) + sec_size]
            sid = fat[sid] if sid < len(fat) else ENDOFCHAIN
            guard += 1
        return bytes(out[:size]) if size is not None else bytes(out)

    # DIFAT → FAT
    difat = list(struct.unpack_from(f"<{min(num_fat, 109)}I", data, 76))
    fat: list[int] = []
    for fs in difat:
        if fs in (FREESECT, ENDOFCHAIN):
            continue
        raw = data[sector_off(fs): sector_off(fs) + sec_size]
        fat += list(struct.unpack_from(f"<{sec_size // 4}I", raw))

    # 目录项
    dir_raw = read_chain(dir_start, fat)
    entries = []
    for i in range(0, len(dir_raw), 128):
        e = dir_raw[i:i + 128]
        if len(e) < 128:
            break
        nlen = struct.unpack_from("<H", e, 64)[0]
        name = e[: max(0, nlen - 2)].decode("utf-16-le", "ignore")
        etype = e[66]
        start = struct.unpack_from("<I", e, 116)[0]
        size = struct.unpack_from("<Q", e, 120)[0]
        entries.append((name, etype, start, size))

    root = next((x for x in entries if x[1] == 5), None)
    mini_stream = read_chain(root[2], fat) if root else b""
    mini_fat: list[int] = []
    if mini_fat_start not in (ENDOFCHAIN, FREESECT):
        raw = read_chain(mini_fat_start, fat)
        mini_fat = list(struct.unpack_from(f"<{len(raw) // 4}I", raw))

    def read_mini(start: int, size: int) -> bytes:
        out, sid, guard = bytearray(), start, 0
        while sid not in (ENDOFCHAIN, FREESECT) and guard < 100000:
            off = sid * mini_size
            out += mini_stream[off: off + mini_size]
            sid = mini_fat[sid] if sid < len(mini_fat) else ENDOFCHAIN
            guard += 1
        return bytes(out[:size])

    out: dict[str, bytes] = {}
    for name, etype, start, size in entries:
        if etype != 2 or size == 0:
            continue
        out[name] = (read_mini(start, size) if size < mini_cutoff
                     else read_chain(start, fat, size))
    return out


def main() -> int:
    if not DOCX.exists():
        print(f"❌ 未找到 {DOCX}")
        return 1
    with zipfile.ZipFile(DOCX) as z:
        names = sorted(n for n in z.namelist() if n.startswith("word/embeddings/"))
        targets = [names[0], names[1], names[3]] if len(names) > 3 else names[:1]
        for n in targets:
            data = z.read(n)
            print(f"\n=== {n.rsplit('/', 1)[-1]} ({len(data)} bytes) ===")
            try:
                streams = cfb_streams(data)
            except Exception as exc:  # noqa: BLE001
                print(f"  ❌ 解析失败：{type(exc).__name__}: {exc}")
                continue
            for sname, sdata in streams.items():
                head = sdata[:24].hex(" ")
                print(f"  流 {sname!r:<24} {len(sdata):>6} bytes  头: {head}")
            need = [s for s in streams if "Equation Native" in s]
            print(f"  → 含 'Equation Native' 流：{'✅' if need else '❌'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
