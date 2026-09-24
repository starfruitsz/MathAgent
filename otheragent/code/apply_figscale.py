# -*- coding: utf-8 -*-
"""把各绘图脚本里的 figsize=(w, h) 统一改成 figsize=fs(w, h)。

配合 plotstyle.FS 使用：画布缩小、字号不变 ⇒ 排入 A4 后纸面字号更大。
幂等：已经是 figsize=fs(...) 的不会重复包。
"""
from __future__ import annotations

import re
from pathlib import Path

CODE = Path(__file__).resolve().parent
FILES = ["fig_common.py", "fig_q1.py", "fig_q2.py", "fig_q3.py", "fig_q4.py",
         "fig_check.py"]

pat = re.compile(r"figsize=\((?!fs\()")


def main() -> None:
    for name in FILES:
        p = CODE / name
        src = p.read_text(encoding="utf-8")
        n = len(pat.findall(src))
        src = pat.sub("figsize=fs((", src)
        # 在每个 figsize=fs(( ... )) 的匹配右括号后再补一个右括号
        # 做法：逐行处理，找出 figsize=fs(( 开头的行并平衡括号
        out_lines = []
        for line in src.split("\n"):
            if "figsize=fs((" in line:
                # 找到 figsize=fs(( 的位置，向右平衡括号
                i = line.index("figsize=fs((")
                depth = 0
                j = i + len("figsize=fs(")
                while j < len(line):
                    if line[j] == "(":
                        depth += 1
                    elif line[j] == ")":
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                line = line[:j + 1] + ")" + line[j + 1:]
            out_lines.append(line)
        p.write_text("\n".join(out_lines), encoding="utf-8")
        print(f"  {name}: 改写 {n} 处 figsize")


if __name__ == "__main__":
    main()
