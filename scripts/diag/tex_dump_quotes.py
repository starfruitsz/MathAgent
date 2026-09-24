"""打印 LaTeX 源中"引号类"字符的真实码位（用于排查引号排版异常）。

用法：python scripts/diag/tex_dump_quotes.py [关键词]
"""

from __future__ import annotations

import pathlib
import sys
import unicodedata

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

KEY = sys.argv[1] if len(sys.argv) > 1 else "误判"
ROOT = pathlib.Path("otheragent/texfile")

# 常见的"看起来像引号"的码位
SUSPECT = {0x0022, 0x2018, 0x2019, 0x201C, 0x201D, 0x2032, 0x2033,
           0x300C, 0x300D, 0x300E, 0x300F, 0xFF02, 0xFF07, 0x301D, 0x301E,
           0x00AB, 0x00BB, 0x2039, 0x203A}


def main() -> int:
    hits = 0
    for p in sorted(ROOT.glob("*.tex")):
        s = p.read_text(encoding="utf-8")
        i = s.find(KEY)
        if i < 0:
            continue
        hits += 1
        seg = s[max(0, i - 60):i + 90]
        print(f"--- {p.name} ---")
        print("文本:", seg)
        print("码位:", " ".join(
            f"{ch}({ord(ch):04X}{'*' if ord(ch) in SUSPECT else ''})"
            for ch in seg if not ch.isascii() or ord(ch) in SUSPECT))
        print()
    if not hits:
        print(f"未找到关键词 {KEY!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
