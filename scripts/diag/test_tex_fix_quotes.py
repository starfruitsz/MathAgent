"""自测 tex_fix_quotes.convert 的护栏：不能把 TeX 十六进制前缀 `"2460` 当引号。

用法：python scripts/diag/test_tex_fix_quotes.py
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

_spec = importlib.util.spec_from_file_location(
    "tfq", pathlib.Path(__file__).with_name("tex_fix_quotes.py"))
tfq = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tfq)

CASES = [
    # (输入, 期望输出)
    (r'\xeCJKDeclareCharClass{CJK}{"2460 -> "24FF}',
     r'\xeCJKDeclareCharClass{CJK}{"2460 -> "24FF}'),      # 全部保留
    ('他说"你好"然后走了', '他说\u201c你好\u201d然后走了'),   # 成对替换
    (r'\symbol{"2460} 与 "文字"', '\\symbol{"2460} 与 \u201c文字\u201d'),
    (r'\begin{lstlisting}print("x")\end{lstlisting}', r'\begin{lstlisting}print("x")\end{lstlisting}'),
]


def main() -> int:
    bad = 0
    for src, want in CASES:
        got, n, sk = tfq.convert(src)
        ok = got == want
        bad += 0 if ok else 1
        print(f"{'✅' if ok else '❌'} {src}")
        if not ok:
            print(f"   want: {want}")
            print(f"   got : {got}")
    print(f"\n{len(CASES) - bad}/{len(CASES)} 通过")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
