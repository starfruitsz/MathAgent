"""检查 docx 内 MathType 预览图的像素尺寸与换算后的显示高度。

用法：
    python scripts/check_mathtype_previews.py
"""

from __future__ import annotations

import io
import sys
import zipfile
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[1]
DOCX = ROOT / "paper" / "山区洪涝灾害下无人机运输与通信协同优化_论文.docx"
SCALE = 0.22  # 与 equations.convert_to_mathtype 的 preview_pt_per_px 一致


def main() -> int:
    from PIL import Image

    with zipfile.ZipFile(DOCX) as z:
        names = sorted(n for n in z.namelist() if "mathtype_preview" in n)
        sizes = [Image.open(io.BytesIO(z.read(n))).size for n in names]
    print(f"预览图数量：{len(sizes)}")
    hs = Counter(h for _, h in sizes)
    ws = [w for w, _ in sizes]
    print(f"像素宽度范围：{min(ws)}~{max(ws)}")
    print("像素高度分布（前 12）：")
    for h, c in sorted(hs.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {h:>4} px × {SCALE} = {h * SCALE:5.1f} pt   出现 {c} 次")
    body_pt = 12.0
    med = sorted(h for _, h in sizes)[len(sizes) // 2]
    print(f"\n中位高度 {med} px → {med * SCALE:.1f} pt（正文 {body_pt:.0f} pt）")
    print(f"比值 {med * SCALE / body_pt:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
