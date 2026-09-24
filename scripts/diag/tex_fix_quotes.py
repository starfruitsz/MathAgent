"""把 LaTeX 正文里的 ASCII 直引号 `"` 成对替换为中文引号 `“` / `”`。

为什么必须改
------------
xeCJK 在全角标点风格下会把 ASCII `"` 映射成**同一个** CJK 引号字形，
于是 PDF 里开引号与闭引号长得一样（都像 `”`），中文排版明显不对。
正确做法是源文件直接写 `“` / `”`。

安全性
------
只替换**代码 / verbatim / url 环境之外**的引号；且仅当该文件引号数为偶数时处理
（奇数说明有落单引号，宁可跳过并报警，也不猜）。按出现顺序交替赋开/闭。

用法：
    python scripts/diag/tex_fix_quotes.py            # 只预览
    python scripts/diag/tex_fix_quotes.py --apply    # 实际写入
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = pathlib.Path("otheragent")
CODE_ENVS = ("lstlisting", "verbatim", "minted", "Verbatim")


def code_spans(s: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for env in CODE_ENVS:
        for m in re.finditer(rf"\\begin\{{{env}\}}(.*?)\\end\{{{env}\}}", s, re.S):
            spans.append((m.start(1), m.end(1)))
    for m in re.finditer(r"\\verb(.)(.*?)\1", s):
        spans.append((m.start(2), m.end(2)))
    for m in re.finditer(r"\\url\{[^}]*\}", s):
        spans.append((m.start(), m.end()))
    return spans


#: ★ TeX 里 `"` 还是**十六进制数字前缀**（`"2460` = 0x2460），
#:   典型出现在 \xeCJKDeclareCharClass / \char / \symbol 这类命令里。
#:   早期版本的"成对替换"脚本把 `{"2460 -> "24FF}` 改成了 `{“2460 -> ”24FF}`，
#:   直接导致 xelatex 报一片 "Missing number, treated as zero"。
#:   这里用"后随 2+ 个十六进制数字，且前面是 { , -> 或空白"识别并跳过。
TEX_HEXNUM = re.compile(r'(?<=[{,\s])"[0-9A-Fa-f]{2,}')


def convert(s: str) -> tuple[str, int, int]:
    """返回 (新文本, 替换数, 跳过数)。"""
    spans = code_spans(s)
    hexnum = {m.start() for m in TEX_HEXNUM.finditer(s)}
    idx = [i for i, ch in enumerate(s)
           if ch == '"'
           and i not in hexnum
           and not any(a <= i < b for a, b in spans)]
    if len(idx) % 2 != 0:
        return s, 0, len(idx)
    out = list(s)
    for n, i in enumerate(idx):
        out[i] = "\u201c" if n % 2 == 0 else "\u201d"
    return "".join(out), len(idx), 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    files = sorted(ROOT.glob("texfile/*.tex")) + [ROOT / "document.tex"]
    files = [f for f in files if f.exists()]
    n_all = skipped = 0
    for p in files:
        s = p.read_text(encoding="utf-8")
        new, n, sk = convert(s)
        n_all += n
        skipped += sk
        if sk:
            print(f"  ⚠️  {p.name}: {sk} 个引号落单（奇数），已跳过")
        elif n:
            print(f"  ✓ {p.name}: 替换 {n} 个")
            if args.apply:
                p.write_text(new, encoding="utf-8")
    print(f"\n共替换 {n_all} 个引号；跳过 {skipped} 个"
          f"{'（已写入）' if args.apply else '（未写入，加 --apply 执行）'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
