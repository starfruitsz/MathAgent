"""诊断：OMML → MathML 转换是否保留上下标/分式/大算符结构。

用法：
    python scripts/diag/omml_to_mathml.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from report import equations as EQ  # noqa: E402

SAMPLE = r"L_{g}(q) = L_{g0} - (L_{g0} - L_{gF}) \cdot \left( \frac{q}{Q_{g}} \right)^{3/2}"


def main() -> int:
    omml = EQ.omml(SAMPLE, display=False)
    print("=== 1) 我方生成的 OMML ===")
    print(omml[:1400])
    print()
    for tag in ("m:sSub", "m:sSup", "m:f", "m:sSubSup", "m:nary", "m:r", "m:t"):
        print(f"  {tag:<12} 出现 {omml.count('<' + tag)} 次")

    # 2) 用 Office 的 XSL 做 OMML→MathML
    from lxml import etree

    xslt = etree.XSLT(etree.parse(str(EQ.WIN_OMML_XSL)))
    node = etree.fromstring(omml.encode("utf-8"))
    mathml = xslt(node)
    out = str(mathml)
    print("\n=== 2) OMML2MML.XSL 产出的 MathML ===")
    print(out[:1800])
    print()
    for tag in ("msub", "msup", "msubsup", "mfrac", "munderover", "munder", "mo", "mi", "mn"):
        print(f"  {tag:<12} 出现 {out.count('<' + tag)} 次")

    # 3) 该库自己的 MathML 解析器怎么看
    from docx_equation.shared import mathml as _m

    dst = ROOT / "paper" / "_diag_struct.mml"
    dst.write_bytes(etree.tostring(mathml, encoding="utf-8",
                                   xml_declaration=True, pretty_print=True))
    expr = _m.parse_mathml_file(dst)
    print("\n=== 3) docx-equation 解析出的表达式树 ===")
    print(repr(expr)[:1500])
    dst.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
