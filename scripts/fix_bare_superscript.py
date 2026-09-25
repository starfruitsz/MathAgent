"""修复"底数在数学环境外"导致的空底数上下标（Word 里渲染成 □）。

问题
----
源码写作 `0.06\\,m$^3$`（底数 `m` 在文本模式、上标在数学环境里）时，
pandoc 会生成**底数为空**的 `<m:sSup>`：

    <w:t>/ m</w:t>
    <m:oMath><m:sSup><m:e><m:r><m:t/></m:r></m:e>
      <m:sup><m:r><m:t>3</m:t></m:r></m:sup></m:sSup></m:oMath>

Word 把空底数渲染成一个 `□`（实测「可用装载体积 V_g / m□³」「巡航速度 v_g^c /(m·s□⁻¹)」）。

★ 实测（pandoc 3.11）三种写法的产出：
    | 源码写法                | sSup 底数        |
    |-------------------------|------------------|
    | `m$^3$`                 | 空（仅 U+200B）   |
    | `m$^{3}$`               | 空（仅 U+200B）   |
    | `$\\mathrm{m}^{3}$`     | `m` ✅            |
  即**只把上标加括号是不够的**，必须把**底数一起移进数学环境**。

修法
----
`([A-Za-z])$^{...}$`  →  `$\\1^{...}$`
即 `0.06\\,m$^{3}$` → `0.06\\,$m^{3}$`。XeLaTeX 渲染视觉不变，pandoc 产出完整底数。

用法：
    python scripts/fix_bare_superscript.py --report   # 只统计
    python scripts/fix_bare_superscript.py            # 就地修复
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
TEXDIR = ROOT / "otheragent" / "texfile"
EXTRA = [ROOT / "otheragent" / "document.tex"]

# 底数(字母/汉字) + $^{...}$  →  $\1^{...}$
# ★ 必须把底数搬进数学环境，否则 pandoc 仍生成空底数（见模块文档的实验）。
PAT_IN = re.compile(r"([A-Za-z\u4e00-\u9fff])\$\^(\{[^}]*\}|[0-9A-Za-z])\$")
# 兼容历史误产物 m${3}$（丢了 ^）
PAT_BAD = re.compile(r"([A-Za-z\u4e00-\u9fff])\$\{(-?[0-9A-Za-z]+)\}\$")


def _scan(t: str) -> int:
    return len(PAT_IN.findall(t)) + len(PAT_BAD.findall(t))


def _fix(t: str) -> tuple[str, int]:
    n = PAT_BAD.sub(lambda m: f"${m.group(1)}^{{{m.group(2)}}}$", t)
    nb = len(PAT_BAD.findall(t))

    def repl(m: re.Match) -> str:
        sup = m.group(2)
        if not sup.startswith("{"):
            sup = "{" + sup + "}"
        return f"${m.group(1)}^{sup}$"

    out = PAT_IN.sub(repl, n)
    return out, nb + len(PAT_IN.findall(n))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    files = sorted(TEXDIR.glob("*.tex")) + [p for p in EXTRA if p.exists()]
    total = 0
    remaining = 0
    for f in files:
        t = f.read_text(encoding="utf-8")
        remaining += _scan(t)
        new, n = _fix(t)
        total += n
        if n and not args.report:
            f.write_text(new, encoding="utf-8")

    print(f"扫描 {len(files)} 个 .tex")
    print(f"待修复（底数在数学环境外）: {total} 处")
    print(f"修复后仍残留: {_scan(new) if total and not args.report else remaining} 处")
    print("(--report：未写回)" if args.report else "✅ 已就地修复")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

