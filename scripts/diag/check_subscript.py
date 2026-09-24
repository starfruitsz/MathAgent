"""诊断：检查多字母下标（如 `\\mathrm{FSPL}`）是否出现字符重叠。

用法：
    python scripts/diag/check_subscript.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from report import equations as EQ  # noqa: E402

OUT = ROOT / "paper" / "_preview" / "equations"

SAMPLES = [
    ("A", r"L_{FSPL}"),                          # 修复前的写法（裸多字母下标）
    ("B", r"L_{\mathrm{FSPL}}"),                 # 显式正体
    ("C", r"L_{path,ijt}"),                      # 混合下标（字母 + 逗号）
    ("D", r"E_{gij}^{hor}(q)"),                  # 上下标同时出现
    ("E", r"q_{max}^{safe}(g,i)"),               # 长下标 + 长上标
    ("F", r"\sum_{(i,j) \in p} E_{gij}(q_{pij})"),
    ("G", r"t_{chg}(s) = T_{full} \cdot 0.35"),
    ("H", r"v_{g}^{up}"),
]


def main() -> int:
    from lxml import etree

    OUT.mkdir(parents=True, exist_ok=True)
    browser = EQ.find_browser()
    if browser is None:
        print("❌ 未找到浏览器")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="subchk_"))
    mml_dir = tmp / "mml"
    prev_dir = tmp / "png"
    mml_dir.mkdir(parents=True, exist_ok=True)

    xslt = etree.XSLT(etree.parse(str(EQ.WIN_OMML_XSL)))
    for i, (tag, expr) in enumerate(SAMPLES, 1):
        omml = EQ.omml(expr, display=False)
        mathml = str(xslt(etree.fromstring(omml.encode("utf-8"))))
        (mml_dir / f"equation_{i:03d}.mml").write_text(mathml, encoding="utf-8")
    n = EQ.render_previews(mml_dir, prev_dir, browser=browser)
    print(f"渲染 {n} 张")

    from PIL import Image

    rows = []
    for i, (tag, expr) in enumerate(SAMPLES, 1):
        p = prev_dir / f"equation_{i:03d}.png"
        im = Image.open(p)
        rows.append((tag, expr, im))
        print(f"  {tag}: {expr:<34} {im.size[0]:>4}x{im.size[1]:<4}")

    # 拼版：公式左侧标注编号，便于肉眼比较
    from PIL import ImageDraw

    pad, gap = 12, 16
    font = None
    w = max(im.width for _, _, im in rows) + 90 + pad * 2
    h = sum(im.height + gap for _, _, im in rows) + pad * 2
    sheet = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(sheet)
    y = pad
    for tag, expr, im in rows:
        d.text((8, y + im.height // 2 - 6), tag, fill="black")
        sheet.paste(im, (70, y))
        y += im.height + gap
    f = OUT / "subscript_check.png"
    sheet.save(f)
    print(f"\n对照图 → {f}")

    # 自动检测：数字符墨迹的连通块数量，若明显少于字符数说明有重叠
    import numpy as np

    for tag, expr, im in rows:
        a = np.array(im.convert("L"))
        col_ink = (a < 170).any(axis=0)
        runs, prev = 0, False
        for v in col_ink:
            if v and not prev:
                runs += 1
            prev = v
        print(f"  {tag}: 墨迹列连通段 {runs} 段（{expr}）")
    import shutil

    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
