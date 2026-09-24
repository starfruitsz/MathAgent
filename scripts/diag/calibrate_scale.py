"""标定：把"预览图像素"换算成"文档显示点数"的比例，使公式与正文相称。

方法
----
渲染一个**只含单个大写变量**的公式（如 `L`）。MathType/数学排版中，
大写字母高（cap height）约为字号的 0.66。因此在已知渲染字号 `font_px` 时：

    预览图墨迹高(px) ≈ 0.66 × font_px
    想要公式字号 = S pt  ⇒  pt_per_px = S / (0.66 × font_px)

再用一个复杂的实测样本交叉验证（分式/求和会更高，属正常）。

用法：
    python scripts/diag/calibrate_scale.py [目标公式字号，默认 12]
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from report import equations as EQ  # noqa: E402

SAMPLES = [
    ("大写H", r"H"),
    ("小写x", r"x"),
    ("变量对", r"L_{g}(q)"),
    ("分式", r"\frac{a}{b}"),
    ("求和", r"\sum_{k \ge m} m_{k}"),
    ("典型行内", r"E_{g}^{T}(q) \le (1 - \rho_{g}) \cdot E_{g}^{use}"),
]


def main() -> int:
    from lxml import etree

    from PIL import Image

    target_pt = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0
    font_px = 72
    browser = EQ.find_browser()
    if browser is None:
        print("❌ 未找到浏览器")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="caleq_"))
    mml, prev = tmp / "mml", tmp / "png"
    mml.mkdir(parents=True)
    xslt = etree.XSLT(etree.parse(str(EQ.WIN_OMML_XSL)))
    for i, (_, expr) in enumerate(SAMPLES, 1):
        (mml / f"equation_{i:03d}.mml").write_text(
            str(xslt(etree.fromstring(EQ.omml(expr, display=False).encode()))),
            encoding="utf-8")
    EQ.render_previews(mml, prev, browser=browser, font_px=font_px)

    print(f"渲染字号 font_px = {font_px}")
    print(f"{'样本':<12} {'表达式':<38} {'像素':>11} {'墨迹高':>7}")
    sizes = {}
    for i, (name, expr) in enumerate(SAMPLES, 1):
        im = Image.open(prev / f"equation_{i:03d}.png")
        sizes[name] = im.size
        print(f"{name:<12} {expr:<38} {im.size[0]:>5}x{im.size[1]:<5} {im.size[1]:>7}")

    cap_px = sizes["大写H"][1]
    print(f"\n大写字母 H 的墨迹高 = {cap_px} px")
    print(f"  → 推算该渲染字号下的 em ≈ {cap_px / 0.66:.1f} px")
    pt_per_px = target_pt / cap_px * 0.66
    print(f"  → 目标公式字号 {target_pt:.0f} pt 时，pt_per_px = "
          f"{target_pt} / ({cap_px} / 0.66) = {pt_per_px:.4f}")

    print(f"\n按 pt_per_px = {pt_per_px:.4f} 换算各样本的显示高度：")
    for name, expr in SAMPLES:
        h = sizes[name][1] * pt_per_px
        print(f"  {name:<12} {h:>6.1f} pt")

    import shutil

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n建议：PREVIEW_PT_PER_PX = {pt_per_px:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
