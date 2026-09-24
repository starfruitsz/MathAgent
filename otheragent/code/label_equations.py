# -*- coding: utf-8 -*-
"""给 texfile/*.tex 中的 equation 环境按出现顺序插入 \\label{eq:N}。

按 5a → 5b → 5c → 5d → 5e 的 \\input 顺序编号，与编译出的公式号一致。
已带 \\label 的公式跳过（幂等，可重复运行）。
"""
from __future__ import annotations

import re
from pathlib import Path

TEX = Path(__file__).resolve().parent.parent / "texfile"
ORDER = ["5a_common.tex", "5b_q1.tex", "5c_q2.tex", "5d_q3.tex", "5e_q4.tex"]

n = 0
for name in ORDER:
    p = TEX / name
    src = p.read_text(encoding="utf-8")
    out, idx = [], 0
    while True:
        m = re.search(r"\\begin\{equation\}", src[idx:])
        if not m:
            out.append(src[idx:])
            break
        start = idx + m.end()
        out.append(src[idx:start])
        # 该 equation 环境内是否已有 label
        end = src.find(r"\end{equation}", start)
        body = src[start:end]
        if r"\label{" in body:
            out.append(body)
        else:
            n += 1
            out.append(f"\n\t\\label{{eq:{n}}}")
            out.append(body)
        idx = end
    p.write_text("".join(out), encoding="utf-8")
    print(f"  {name}: 累计 {n} 条公式")

print(f"共 {n} 条编号公式")
