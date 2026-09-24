"""按 MS-CFB 规范生成 OLE2 复合文档（本场景专用：所有流 < 4096 字节）。

为什么需要它
------------
`docx-equation` 自制的 OLE 容器 Word 不认（`OLEFormat.ProgID` 取不到、
无法激活 → 双击打不开），但它生成的 **MTEF 数据是有效的**。
因此这里用**真品容器的结构参数**重建一个合法容器，把自己的 MTEF 装进去。

扇区布局（严格按 MS-CFB 惯例，写盘顺序与扇区编号一致）：
    [0 .. nfat-1]        FAT 扇区
    [dir_start .. ]      目录扇区
    [minifat_start ..]   mini FAT 扇区
    [ministream_start]   mini stream 扇区
"""

from __future__ import annotations

import struct

SEC = 512
MINI = 64
MINI_CUTOFF = 4096
FREESECT = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
FATSECT = 0xFFFFFFFD


def build_cfb(streams: list[tuple[str, bytes]], root_clsid: bytes = b"") -> bytes:
    """把若干小流打包成合法的 OLE2 复合文档。"""
    for name, data in streams:
        if len(data) >= MINI_CUTOFF:
            raise NotImplementedError("本实现只处理 < 4096 字节的流")

    # ---------------- 1) 分配 mini 扇区
    mini_stream = bytearray()
    placed: list[tuple[str, int, int]] = []      # (名称, 起始 mini 扇区, 长度)
    mini_fat: list[int] = []
    for name, data in streams:
        start = len(mini_stream) // MINI
        n = max(1, (len(data) + MINI - 1) // MINI)
        mini_stream.extend(data)
        mini_stream.extend(b"\x00" * (n * MINI - len(data)))
        for k in range(n):
            mini_fat.append(start + k + 1 if k + 1 < n else ENDOFCHAIN)
        placed.append((name, start, len(data)))
    n_mini = len(mini_stream) // MINI
    n_mini = max(n_mini, 1)
    mini_stream.extend(b"\x00" * (n_mini * MINI - len(mini_stream)))

    while len(mini_fat) % (SEC // 4):
        mini_fat.append(FREESECT)

    n_minifat_sec = max(1, (len(mini_fat) * 4 + SEC - 1) // SEC)
    # ★ mini stream 必须按"向上取整"折算扇区数：768 字节要占 2 个 512 字节扇区，
    #   写成 len//SEC 会少算一个扇区，导致链在此截断、流内容被截短。
    n_ministream_sec = max(1, (len(mini_stream) + SEC - 1) // SEC)
    n_dir_sec = max(1, ((len(streams) + 1) * 128 + SEC - 1) // SEC)
    n_fat_sec = 1

    # ---------------- 2) 扇区编号（写盘顺序 = 编号顺序）
    fat_secs = list(range(0, n_fat_sec))
    dir_start = n_fat_sec
    dir_secs = list(range(dir_start, dir_start + n_dir_sec))
    minifat_start = dir_start + n_dir_sec
    minifat_secs = list(range(minifat_start, minifat_start + n_minifat_sec))
    ministream_start = minifat_start + n_minifat_sec
    ministream_secs = list(range(ministream_start,
                                  ministream_start + n_ministream_sec))
    total = ministream_start + n_ministream_sec

    fat = [FREESECT] * total
    for i, s in enumerate(fat_secs):
        fat[s] = fat_secs[i + 1] if i + 1 < len(fat_secs) else FATSECT
    for i, s in enumerate(dir_secs):
        fat[s] = dir_secs[i + 1] if i + 1 < len(dir_secs) else ENDOFCHAIN
    for i, s in enumerate(minifat_secs):
        fat[s] = minifat_secs[i + 1] if i + 1 < len(minifat_secs) else ENDOFCHAIN
    for i, s in enumerate(ministream_secs):
        fat[s] = (ministream_secs[i + 1] if i + 1 < len(ministream_secs)
                  else ENDOFCHAIN)

    fat_bytes = struct.pack(f"<{len(fat)}I", *fat)
    fat_bytes += b"\x00" * (n_fat_sec * SEC - len(fat_bytes))
    minifat_bytes = struct.pack(f"<{len(mini_fat)}I", *mini_fat)
    minifat_bytes += b"\x00" * (n_minifat_sec * SEC - len(minifat_bytes))
    ministream_bytes = bytes(mini_stream)

    # ---------------- 3) 目录项（MS-CFB 红黑树）
    names = ["Root Entry"] + [p[0] for p in placed]

    def cmp_key(idx: int) -> tuple[int, str]:
        nm = names[idx].upper()
        return (len(nm), nm)

    left = [-1] * len(names)

    def build(items: list[int], depth: int) -> int:
        if not items:
            return -1
        items = sorted(items, key=cmp_key)
        mid = len(items) // 2
        node = items[mid]
        left[node] = build(items[:mid], depth + 1)
        right[node] = build(items[mid + 1:], depth + 1)
        return node

    right = [-1] * len(names)
    color = [1] * len(names)
    stack: list[int] = []

    def build2(items: list[int], is_root: bool) -> int:
        if not items:
            return -1
        items = sorted(items, key=cmp_key)
        mid = len(items) // 2
        node = items[mid]
        color[node] = 0 if is_root else 1
        left[node] = build2(items[:mid], False)
        right[node] = build2(items[mid + 1:], False)
        return node

    root_child = build2(list(range(1, len(names))), False)
    color[0] = 1

    entries = bytearray()
    for idx in range(len(names)):
        nb = names[idx].encode("utf-16-le") + b"\x00\x00"
        e = bytearray(128)
        e[0:len(nb)] = nb
        struct.pack_into("<H", e, 64, len(nb))
        e[66] = 5 if idx == 0 else 2               # root storage / stream
        e[67] = color[idx]
        struct.pack_into("<I", e, 68, left[idx] & 0xFFFFFFFF)
        struct.pack_into("<I", e, 72, right[idx] & 0xFFFFFFFF)
        struct.pack_into("<I", e, 76,
                         (root_child if idx == 0 else -1) & 0xFFFFFFFF)
        e[80:96] = ((root_clsid if idx == 0 else b"") + b"\x00" * 16)[:16]
        struct.pack_into("<I", e, 96, 0)           # state bits
        struct.pack_into("<Q", e, 100, 0)          # creation time
        struct.pack_into("<Q", e, 108, 0)          # modified time
        if idx == 0:
            struct.pack_into("<I", e, 116, ministream_start)
            struct.pack_into("<Q", e, 120, len(ministream_bytes))
        else:
            struct.pack_into("<I", e, 116, placed[idx - 1][1])
            struct.pack_into("<Q", e, 120, placed[idx - 1][2])
        entries += e
    entries += b"\x00" * (n_dir_sec * SEC - len(entries))

    # ---------------- 4) 头部
    hdr = bytearray(SEC)
    hdr[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<H", hdr, 24, 0x003E)
    struct.pack_into("<H", hdr, 26, 0x0003)
    struct.pack_into("<H", hdr, 28, 0xFFFE)
    struct.pack_into("<H", hdr, 30, 9)
    struct.pack_into("<H", hdr, 32, 6)
    struct.pack_into("<I", hdr, 44, n_fat_sec)
    struct.pack_into("<I", hdr, 48, dir_start)
    struct.pack_into("<I", hdr, 56, MINI_CUTOFF)
    struct.pack_into("<I", hdr, 60, minifat_start)
    struct.pack_into("<I", hdr, 64, n_minifat_sec)
    struct.pack_into("<I", hdr, 68, ENDOFCHAIN)
    struct.pack_into("<I", hdr, 72, 0)
    for i in range(109):
        struct.pack_into("<I", hdr, 76 + i * 4,
                         fat_secs[0] if i == 0 else FREESECT)

    # ---------------- 5) 按扇区编号顺序拼装
    return bytes(hdr) + fat_bytes + entries + minifat_bytes + ministream_bytes
