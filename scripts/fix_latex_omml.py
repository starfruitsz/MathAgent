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


def fix_empty_math_bases(root) -> int:
    """★ 修复 pandoc 生成的"空底数"上下标（Word 里渲染成 □ 的另一个根因）。

    源码写作 `m$^3$`、`(m$\\cdot$s$^{-1}$)` 时，pandoc 会产出**底数为空**的
    `m:sSup` / `m:sSubSup`：

        <w:t>/ m</w:t>
        <m:oMath><m:sSup><m:e><m:r><m:t/></m:r></m:e>
          <m:sup><m:r><m:t>3</m:t></m:r></m:sup></m:sSup></m:oMath>

    底数 `m:e` 里只有一个**空的** `<m:t/>`，Word 会把它渲染成一个 `□`
    （实测表 2「可用装载体积 V_g / m□³」「巡航速度 v_g^c /(m·s□⁻¹)」）。

    修法：把**紧邻在前的最后一个可见字符**搬进空底数 —— 这正是 LaTeX
    书写 `m$^3$` 的本意（`m` 是底数，`3` 是上标）。
    只处理"底数确实为空"的情形，不触碰任何正常公式。

    返回修好的数量。
    """
    fixed = 0
    for math in list(root.iter(f"{M}oMath")):
        for tag in ("sSup", "sSubSup"):
            for node in list(math.iter(f"{M}{tag}")):
                base = node.find(f"{M}e")
                if base is None or _base_text(base).strip():
                    continue
                prev = _prev_char_source(node)
                if prev is None:
                    continue
                container, text_el = prev
                text = text_el.text or ""
                last = text[-1]
                # 从原位置摘掉该字符
                text_el.text = text[:-1]
                if not text_el.text:
                    # 元素空了：若是公式内的 m:r，整段删除；若是 w:r，留着无害
                    pass
                # 写进空底数
                for r in list(base.findall(f"{M}r")):
                    base.remove(r)
                r = _mk_run(last)
                base.append(r)
                fixed += 1
    return fixed


def _base_text(base) -> str:
    return "".join(t.text or "" for t in base.iter(f"{M}t"))


def _mk_run(ch: str):
    """构造一个只含单个字符的 `m:r`。"""
    from lxml import etree

    NS_M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
    r = etree.SubElement(etree.Element("{%s}tmp" % NS_M), "{%s}r" % NS_M)
    t = etree.SubElement(r, "{%s}t" % NS_M)
    t.text = ch
    return r


def _prev_char_source(node):
    """向前找"最后一个可见字符"所在的文本元素。

    ★ 关键：pandoc 把公式包在 `w:r` 里，`m:oMath` 往往是该 `w:r` 的**第一个子元素**，
    因此在公式这一层**没有前置兄弟**。必须**逐层向上**找到第一个有"前置兄弟"的祖先，
    再在那个兄弟里取最后一个可见字符。

    返回 `(容器元素, m:t 或 w:t 元素)`；找不到返回 None。
    """
    NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    cur = node
    while cur is not None:
        parent = cur.getparent()
        if parent is None:
            return None
        kids = list(parent)
        try:
            idx = kids.index(cur)
        except ValueError:
            return None
        for k in range(idx - 1, -1, -1):
            sib = kids[k]
            # 普通文本 run（w:t）
            for wt in reversed(list(sib.iter(f"{{{NS_W}}}t"))):
                if (wt.text or "").strip():
                    return sib, wt
            # 公式文本（m:t）
            for mt in reversed(list(sib.iter(f"{M}t"))):
                if (mt.text or "").strip():
                    return sib, mt
        # 本层没有可用前置兄弟 → 上溯一层
        cur = parent
    return None


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
    n_base_fixed = 0

    for n in targets:
        try:
            txt = parts[n].decode("utf-8")
        except UnicodeDecodeError:
            continue

        # ---- ① 文件级修复：空底数上下标（必须走 XML 树）----
        if n == "word/document.xml":
            from lxml import etree

            root = etree.fromstring(txt.encode("utf-8"))
            n_base_fixed = fix_empty_math_bases(root)
            if n_base_fixed:
                txt = etree.tostring(
                    root, xml_declaration=True, encoding="UTF-8",
                    standalone=True,
                ).decode("utf-8")

        # ---- ② 文本级修复：不可渲染的空白字符 ----
        new, found = fix_part(txt)
        for k, v in found.items():
            total[k] = total.get(k, 0) + v
        if new != txt:
            changed[n] = new

    print(f"被检文件：{path.name}")
    print(f"检查 XML 部件 {len(targets)} 个")
    if n_base_fixed:
        print(f"★ 修复空底数上下标（Word 里会渲染成 □）：{n_base_fixed} 处")
    if not total and not n_base_fixed:
        print("✅ 未发现需要修复的问题（无需修改）")
        return 0

    if total:
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
        # 再查一遍空底数
        from lxml import etree

        _doc_bytes = z.read("word/document.xml")
        root = etree.fromstring(_doc_bytes)
        left_bases = sum(
            1
            for math in root.iter(f"{M}oMath")
            for tag in ("sSup", "sSubSup")
            for node in math.iter(f"{M}{tag}")
            if (b := node.find(f"{M}e")) is not None
            and not _base_text(b).strip()
        )
    print("复检残留：", left if left else "无 ✅")
    print("复检空底数：", left_bases if left_bases else "无 ✅")
    return 1 if (left or left_bases) else 0


if __name__ == "__main__":
    raise SystemExit(main())
