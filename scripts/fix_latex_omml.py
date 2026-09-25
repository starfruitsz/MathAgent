"""修正 pandoc 产出的 OMML 中"Word 渲染不出字形"的空白字符（□ 的根因）。

问题
----
pandoc 把 LaTeX 的空白命令转成**特殊 Unicode 空白字符**写进 `m:t`：

| LaTeX | pandoc 产出 | 字符名 | 本仓实测处数 |
|---|---|---|---|
| `\\quad`  | U+2001 | EM QUAD          | 24 |
| `\\qquad` | U+2005 | FOUR-PER-EM SPACE| 21 |
| `\\,`     | U+2009 | THIN SPACE       | 36 |
| （残留）   | U+200B | ZERO WIDTH SPACE | 42 |

Word 的数学字体（Cambria Math）**没有这些字形的可见形式**，
于是渲染成 `□`（尤其 `\\qquad` 会连出两个 `□□`，`\\sum_{k\\ge m}` 的空上标
会多出一个孤立 `□`）。PDF 侧看不出问题是因为 XeLaTeX 用的是另一套字体。

修法
----
把这些字符**规范化成普通空格 `U+0020`**：
- `U+200B`（零宽）→ **直接删除**（它本就是不可见残留，留着只会变 `□`）
- `U+2001` → 2 个空格（em quad = 2 em，数学字体里 2 个空格宽度正好）
- `U+2005` → 2 个空格
- `U+2009` → 1 个空格（细空格，1 个空格已足够相近）
- `U+2004` → 1 个空格

普通空格在 Word 的 OMML 里会被**数学排版引擎**正确处理（不会画成 `□`），
公式语义与视觉间距都保留。

用法
----
    python scripts\\fix_latex_omml.py                      # 默认修 LaTeX 公式版
    python scripts\\fix_latex_omml.py <docx 路径> [--report]

建议接在 pandoc 之后、`format_latex_paper.py` 之前执行。
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_DOCX = (ROOT / "paper"
                / "山区洪涝灾害下无人机运输与通信协同优化_论文_LaTeX公式版.docx")

M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"

# 字符 → 替换（"" 表示删除）
#
# 分两类：
#   A. **公式内**的特殊数学空白（`\quad`/`\qquad`/`\,` 的产物）—— 这是 □ 的根因，
#      在 Word 里一定渲染不出可见字形（Cambria Math 无此字形）。
#   B. pandoc 在**正文**里也用的隐形空白（U+2006 用于 "30 m" 这类单位，
#      U+00A0 用于超链接前的不换行空格）。它们视觉上是空白，但在中文字体下
#      同样是"字体里没有的码位"，存在同样的 □ 风险。
#      统一规范化为普通空格：视觉不变、语义不变（仅失去不换行语义），
#      但**彻底消除字体回退**。
REPLACEMENTS: dict[str, str] = {
    # ---- A. 公式内（□ 的根因）----
    "\u200b": "",      # ZERO WIDTH SPACE —— pandoc 残留，纯删除
    "\u200c": "",      # ZWNJ
    "\u200d": "",      # ZWJ
    "\ufeff": "",      # BOM / ZWNBSP
    "\u2001": "  ",    # EM QUAD          ← \quad
    "\u2002": "  ",    # EN SPACE
    "\u2003": "  ",    # EM SPACE
    "\u2004": " ",     # THREE-PER-EM     ← \;
    "\u2005": "  ",    # FOUR-PER-EM      ← \qquad
    "\u2009": " ",     # THIN SPACE       ← \,
    "\u200a": " ",     # HAIR SPACE
    "\u205f": " ",     # MEDIUM MATHEMATICAL SPACE
    # ---- B. 正文里的隐形空白 ----
    "\u2006": " ",     # SIX-PER-EM SPACE —— 单位前的空格（"30 m"）
    "\u2007": " ",     # FIGURE SPACE
    "\u2008": " ",     # PUNCTUATION SPACE
    "\u00a0": " ",     # NO-BREAK SPACE
    "\u202f": " ",     # NARROW NO-BREAK SPACE
}

# 只在这些字符上做替换（避免误伤正常文本）
MATH_SPACES = set(REPLACEMENTS)


def count_offenders(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for ch in text:
        if ch in MATH_SPACES:
            out[f"U+{ord(ch):04X}"] = out.get(f"U+{ord(ch):04X}", 0) + 1
    return out


def fix_part(xml_text: str) -> tuple[str, dict[str, int]]:
    """在**整个 document.xml 上做字符级替换**。

    安全前提：这些字符在正文里也不该出现（它们是不可见空白/格式符），
    因此全局替换不会破坏可见内容，且能一并清掉表内公式里的同类字符。
    """
    found = count_offenders(xml_text)
    out = xml_text
    for ch, rep in REPLACEMENTS.items():
        if ch in out:
            out = out.replace(ch, rep)
    return out, found


def main() -> int:
    ap = argparse.ArgumentParser(description="清理 OMML 中不可渲染的空白字符")
    ap.add_argument("docx", nargs="?", default=str(DEFAULT_DOCX))
    ap.add_argument("--report", action="store_true", help="只报告不修改")
    args = ap.parse_args()

    path = Path(args.docx)
    if not path.exists():
        print(f"❌ 未找到 {path}")
        return 1

    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        parts = {n: z.read(n) for n in names}

    targets = [n for n in names
               if n.startswith("word/") and n.endswith(".xml")]
    total: dict[str, int] = {}
    changed: dict[str, str] = {}
    for n in targets:
        try:
            txt = parts[n].decode("utf-8")
        except UnicodeDecodeError:
            continue
        new, found = fix_part(txt)
        for k, v in found.items():
            total[k] = total.get(k, 0) + v
        if new != txt:
            changed[n] = new

    print(f"被检文件：{path.name}")
    print(f"检查 XML 部件 {len(targets)} 个")
    if not total:
        print("✅ 未发现不可渲染的空白字符（无需修改）")
        return 0

    print("\n=== 发现并处理的字符 ===")
    import unicodedata

    for k, v in sorted(total.items(), key=lambda kv: -kv[1]):
        ch = chr(int(k[2:], 16))
        print(f"  {k} ×{v:4}  {unicodedata.name(ch, '?'):26}"
              f" → {REPLACEMENTS[ch]!r}")
    print(f"  合计 {sum(total.values())} 个字符，涉及部件：{list(changed)}")

    if args.report:
        print("\n(--report：未写回文件)")
        return 0

    # 重新打包（保留原压缩方式与顺序）
    tmp = path.with_suffix(".fixing.docx")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n in names:
            data = changed.get(n)
            z.writestr(n, data.encode("utf-8") if data is not None else parts[n])
    tmp.replace(path)
    print(f"\n✅ 已修正并写回：{path.name}")

    # 复检
    with zipfile.ZipFile(path) as z:
        left: dict[str, int] = {}
        for n in z.namelist():
            if n.startswith("word/") and n.endswith(".xml"):
                try:
                    left.update(count_offenders(z.read(n).decode("utf-8")))
                except UnicodeDecodeError:
                    pass
    print("复检残留：", left if left else "无 ✅")
    return 1 if left else 0


if __name__ == "__main__":
    raise SystemExit(main())
