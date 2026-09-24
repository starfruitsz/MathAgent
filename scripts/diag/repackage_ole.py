"""关键实验：把 docx-equation 的 MTEF 塞进**真品 OLE 容器**，看 Word 能否激活。

思路：`docx-equation` 生成的 MTEF 有效（预览图能正确排版），但它自制的 OLE
容器 Word 不认。这里用真品容器的**结构参数**（扇区/目录项属性）重建一个
符合规范的 CFB，把我们自己的 `Equation Native` 写进去。

用法：
    python scripts/diag/repackage_ole.py
"""

from __future__ import annotations

import struct
import subprocess
import sys
import time
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_ole_streams import cfb_streams  # noqa: E402

WORK = ROOT / "paper" / "_probe_min"
SEC = 512
MINI = 64
MINI_CUTOFF = 4096


def build_cfb(streams: list[tuple[str, bytes]], clsid_root: bytes) -> bytes:
    """按 MS-CFB 规范生成复合文档（仅覆盖本场景：全部流 < 4096，走 mini stream）。

    目录项按 MS-CFB 3.1 的**红黑树**规则构造：
      · 所有流名按长度排序时，若长度 2 的幂则比较大小写折叠前的原始 UTF-16 码元；
      · 取"按 CFB 比较序"的**中位项**作为根，左右递归建树；
      · 颜色除根为黑外，用一条简单的全黑链即可（平衡性不影响读取）。
    """
    n_mini_sectors = sum((len(d) + MINI - 1) // MINI for _, d in streams)
    n_mini_sectors = max(n_mini_sectors, 1)
    mini_stream_len = n_mini_sectors * MINI
    n_mini_fat_sectors = max(1, (n_mini_sectors * 4 + SEC - 1) // SEC)
    n_dir_sectors = max(1, (1 + len(streams)) * 128 // SEC +
                        (1 if ((1 + len(streams)) * 128) % SEC else 0))
    n_fat_sectors = 1

    mini_fat_start = 0
    mini_stream_start = mini_fat_start + n_mini_fat_sectors
    dir_start = mini_stream_start + 1
    fat_sector = dir_start + n_dir_sectors
    total_sectors = fat_sector + n_fat_sectors

    fat: list[int] = [0xFFFFFFFF] * total_sectors
    for i in range(n_mini_fat_sectors):
        fat[mini_fat_start + i] = (mini_fat_start + i + 1
                                   if i + 1 < n_mini_fat_sectors else 0xFFFFFFFE)
    fat[mini_stream_start] = 0xFFFFFFFE
    for i in range(n_dir_sectors):
        fat[dir_start + i] = (dir_start + i + 1
                              if i + 1 < n_dir_sectors else 0xFFFFFFFE)
    for i in range(n_fat_sectors):
        fat[fat_sector + i] = (fat_sector + i + 1
                               if i + 1 < n_fat_sectors else 0xFFFFFFFD)
    while len(fat) % (SEC // 4):
        fat.append(0xFFFFFFFF)

    mini_fat: list[int] = []
    mini_stream = bytearray()
    starts: list[tuple[str, int, int]] = []

    def add_mini(data: bytes) -> tuple[int, int]:
        start = len(mini_stream) // MINI
        n = max(1, (len(data) + MINI - 1) // MINI)
        mini_stream.extend(data)
        mini_stream.extend(b"\x00" * (n * MINI - len(data)))
        for k in range(n):
            mini_fat.append(start + k + 1 if k + 1 < n else 0xFFFFFFFE)
        return start, len(data)

    for name, data in streams:
        if len(data) >= MINI_CUTOFF:
            raise NotImplementedError("本实现只处理 < 4096 字节的流")
        start, size = add_mini(data)
        starts.append((name, start, size))
    mini_stream.extend(b"\x00" * (mini_stream_len - len(mini_stream)))

    while len(mini_fat) % (SEC // 4):
        mini_fat.append(0xFFFFFFFF)
    mini_fat_bytes = struct.pack(f"<{len(mini_fat)}I", *mini_fat)
    mini_fat_bytes += b"\x00" * (n_mini_fat_sectors * SEC - len(mini_fat_bytes))

    n_streams = len(starts)
    dir_name = ["Root Entry"] + [s[0] for s in starts]
    dir_start_sec = [mini_stream_start] + [s[1] for s in starts]
    dir_size = [mini_stream_len] + [s[2] for s in starts]

    # ---- 按 CFB 规范建红黑树（左/右/颜色）
    def key(i: int) -> tuple[int, int]:
        """CFB 名称比较键：先比长度，再按大写后的 UTF-16 码元比较。"""
        nm = dir_name[i].upper()
        return (len(dir_name[i]), 0) if not nm else (len(dir_name[i]), 0)

    def name_lt(a: int, b: int) -> bool:
        na, nb = dir_name[a].upper(), dir_name[b].upper()
        if len(na) != len(nb):
            return len(na) < len(nb)
        return na < nb

    left = [-1] * (n_streams + 1)
    right = [-1] * (n_streams + 1)
    color = [1] * (n_streams + 1)

    def build(items: list[int]) -> int:
        if not items:
            return -1
        items = sorted(items, key=lambda i: (len(dir_name[i].upper()),
                                             dir_name[i].upper()))
        mid = len(items) // 2
        node = items[mid]
        left[node] = build(items[:mid])
        right[node] = build(items[mid + 1:])
        color[node] = 0 if len(items) == n_streams else 1   # 根为黑
        return node

    root_child = build(list(range(1, n_streams + 1)))

    def dirent(idx: int) -> bytes:
        name = dir_name[idx]
        nb = name.encode("utf-16-le") + b"\x00\x00"
        e = bytearray(128)
        e[0:len(nb)] = nb
        struct.pack_into("<H", e, 64, len(nb))
        e[66] = 5 if idx == 0 else 2
        e[67] = color[idx]
        struct.pack_into("<I", e, 68, left[idx] & 0xFFFFFFFF)
        struct.pack_into("<I", e, 72, right[idx] & 0xFFFFFFFF)
        struct.pack_into("<I", e, 76,
                         (root_child if idx == 0 else -1) & 0xFFFFFFFF)
        e[80:96] = ((clsid_root if idx == 0 else b"") + b"\x00" * 16)[:16]
        struct.pack_into("<Q", e, 100, 0)
        struct.pack_into("<Q", e, 108, 0)
        struct.pack_into("<I", e, 116, dir_start_sec[idx])
        struct.pack_into("<Q", e, 120, dir_size[idx])
        return bytes(e)

    entries = bytearray()
    for idx in range(n_streams + 1):
        entries += dirent(idx)
    entries += b"\x00" * (n_dir_sectors * SEC - len(entries))

    # ---- 头部
    hdr = bytearray(512)
    hdr[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<H", hdr, 24, 0x003E)     # minor version
    struct.pack_into("<H", hdr, 26, 0x0003)     # major version (512B sectors)
    struct.pack_into("<H", hdr, 28, 0xFFFE)     # byte order
    struct.pack_into("<H", hdr, 30, 9)          # sector shift
    struct.pack_into("<H", hdr, 32, 6)          # mini sector shift
    struct.pack_into("<I", hdr, 44, n_fat_sectors)
    struct.pack_into("<I", hdr, 48, dir_start)
    struct.pack_into("<I", hdr, 56, MINI_CUTOFF)
    struct.pack_into("<I", hdr, 60, mini_fat_start)
    struct.pack_into("<I", hdr, 64, n_mini_fat_sectors)
    struct.pack_into("<I", hdr, 68, 0xFFFFFFFE)  # first DIFAT sector
    struct.pack_into("<I", hdr, 72, 0)           # number of DIFAT sectors
    for i in range(109):
        struct.pack_into("<I", hdr, 76 + i * 4,
                         fat_sector if i == 0 else 0xFFFFFFFF)

    out = bytearray(hdr)
    out += mini_fat_bytes
    out += mini_stream
    out += entries
    out += struct.pack(f"<{len(fat)}I", *fat)
    return bytes(out)


def main() -> int:
    base = WORK / "step1_convert_only.docx"
    ref = WORK / "ref_object.docx"
    if not base.exists() or not ref.exists():
        print("❌ 需要先跑 probe_minimal.py 与 make_reference_object.py")
        return 1

    with zipfile.ZipFile(base) as z:
        our_streams = cfb_streams(z.read(
            [n for n in z.namelist() if n.startswith("word/embeddings/")][0]))
    with zipfile.ZipFile(ref) as z:
        ref_streams = cfb_streams(z.read(
            [n for n in z.namelist() if n.startswith("word/embeddings/")][0]))

    print("我们的流：", {k: len(v) for k, v in our_streams.items()})
    print("真品流  ：", {k: len(v) for k, v in ref_streams.items()})

    order = ["\x01CompObj", "\x01Ole", "\x03ObjInfo", "Equation Native"]
    streams = []
    for name in order:
        if name in our_streams:
            streams.append((name, our_streams[name]))
        elif name in ref_streams:
            streams.append((name, ref_streams[name]))
    # 根 CLSID 用真品的
    root_clsid = b""

    built = build_cfb(streams, root_clsid)
    print(f"\n重建 CFB：{len(built)} bytes")
    got = cfb_streams(built)
    print("解析回读：", {k: len(v) for k, v in got.items()})
    ok_parse = set(got) == {n for n, _ in streams}
    print(f"  往返一致：{'✅' if ok_parse else '❌'}")
    for name, data in streams:
        same = got.get(name) == data
        print(f"    {name!r}: {len(data)} bytes  一致={same}")

    # 写进 docx
    out_docx = WORK / "var_repackage.docx"
    with zipfile.ZipFile(base) as z:
        items = {i.filename: z.read(i.filename) for i in z.infolist()}
    tgt = [n for n in items if n.startswith("word/embeddings/")][0]
    items[tgt] = built
    with zipfile.ZipFile(out_docx, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in items.items():
            z.writestr(n, b)
    print(f"\n已写出 {out_docx.name}")

    # Word 验证
    import win32com.client as win32

    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    try:
        doc = word.Documents.Open(str(out_docx))
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
                    print(f"  ❌ ProgID 读取失败：{str(exc)[:90]}")
                try:
                    sh.OLEFormat.Activate()
                    time.sleep(3.0)
                    print("  ✅ Activate 成功 —— 换容器可行！")
                except Exception as exc:  # noqa: BLE001
                    print(f"  ❌ Activate 失败：{str(exc)[:90]}")
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

