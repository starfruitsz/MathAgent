"""统计 LaTeX 源中的引号码位，并判断"中文引号是否被写成 ASCII 直引号"。

背景：ASCII `"`（U+0022）在 xeCJK 的全角标点风格下会被映射成**同一个** CJK 引号
字形，于是开引号与闭引号在 PDF 里看起来都像 `”`。正确写法是直接用
`“`（U+201C）/`”`（U+201D）。

本脚本只做**只读统计**，并标出每处 ASCII `"` 是否落在代码/verbatim 环境内
（那些地方不能改）。

用法：python scripts/diag/tex_quote_audit.py
"""

from __future__ import annotations

import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = pathlib.Path("otheragent")
CODE_ENVS = ("lstlisting", "verbatim", "minted", "Verbatim")


def code_spans(s: str) -> list[tuple[int, int]]:
    """返回代码环境（不能改引号）的字符区间。"""
    spans: list[tuple[int, int]] = []
    for env in CODE_ENVS:
        for m in re.finditer(rf"\\begin\{{{env}\}}(.*?)\\end\{{{env}\}}", s, re.S):
            spans.append((m.start(1), m.end(1)))
    for m in re.finditer(r"\\verb(.)(.*?)\1", s):
        spans.append((m.start(2), m.end(2)))
    for m in re.finditer(r"\\url\{[^}]*\}", s):
        spans.append((m.start(), m.end()))
    return spans


def main() -> int:
    files = sorted(ROOT.glob("texfile/*.tex")) + [ROOT / "document.tex"]
    files = [f for f in files if f.exists()]
    total = {"ascii": 0, "open": 0, "close": 0, "incode": 0}
    per_file: list[tuple[str, int, int]] = []

    for p in files:
        s = p.read_text(encoding="utf-8")
        spans = code_spans(s)
        na = s.count('"')
        no, nc = s.count("\u201c"), s.count("\u201d")
        incode = sum(1 for i, ch in enumerate(s)
                     if ch == '"' and any(a <= i < b for a, b in spans))
        total["ascii"] += na
        total["open"] += no
        total["close"] += nc
        total["incode"] += incode
        if na or no or nc:
            per_file.append((p.name, na, no + nc))

    print(f"扫描 {len(files)} 个 .tex 文件\n")
    print(f"{'文件':<28}{'ASCII \"':>9}{'中文引号':>10}")
    print("-" * 48)
    for name, na, ncn in per_file:
        print(f"{name:<28}{na:>9}{ncn:>10}")
    print("-" * 48)
    print(f"{'合计':<28}{total['ascii']:>9}{total['open'] + total['close']:>10}")
    print(f"\n其中位于代码/verbatim/url 环境内的 ASCII 引号：{total['incode']}")
    print(f"正文中的 ASCII 引号（可替换）：{total['ascii'] - total['incode']}")
    print(f"\n中文左引号 “ = {total['open']}，右引号 ” = {total['close']}")
    if total["ascii"] - total["incode"] > 0:
        print("\n⚠️  正文仍在用 ASCII 直引号 ⇒ PDF 中开/闭引号会显示成同一形状。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
