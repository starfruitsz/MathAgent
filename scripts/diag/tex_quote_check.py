"""统计 LaTeX 源里的引号字符，判断中文引号是否被写成同一种（排版会两边同向）。

背景：编译出的 PDF 里中文引号开合都显示成 ”，需要确认是
（a）源文件本身就写成了两个右引号，还是（b）字体/宏包把左引号映射错了。

用法：python scripts/diag/tex_quote_check.py
"""

from __future__ import annotations

import collections
import pathlib
import sys
import unicodedata

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

NAMES = {
    0x201C: "LEFT DOUBLE QUOTATION MARK  “",
    0x201D: "RIGHT DOUBLE QUOTATION MARK  ”",
    0x0022: "ASCII QUOTATION MARK  \"",
    0x300C: "LEFT CORNER BRACKET  「",
    0x300D: "RIGHT CORNER BRACKET  」",
    0x2018: "LEFT SINGLE QUOTATION MARK  ‘",
    0x2019: "RIGHT SINGLE QUOTATION MARK  ’",
}


def scan(paths) -> collections.Counter:
    c: collections.Counter = collections.Counter()
    for p in paths:
        s = p.read_text(encoding="utf-8")
        for ch in s:
            if ord(ch) in NAMES:
                c[ch] += 1
    return c


def main() -> int:
    root = pathlib.Path("otheragent")
    files = sorted(root.glob("texfile/*.tex")) + [root / "document.tex"]
    files = [f for f in files if f.exists()]
    c = scan(files)
    print(f"扫描 {len(files)} 个 .tex 文件")
    for ch in sorted(NAMES, key=lambda x: NAMES[x]):
        if c[ch]:
            print(f"  U+{ch:04X}  {NAMES[ch]:<40} x{c[ch]}")
    only = pathlib.Path("otheragent/texfile/1abstract.tex")
    if only.exists():
        s = only.read_text(encoding="utf-8")
        i = s.find("机队坍缩")
        if i > 0:
            print("\n1abstract.tex 片段（repr，可直接看出引号码位）:")
            print(" ", repr(s[i - 40:i + 70]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
