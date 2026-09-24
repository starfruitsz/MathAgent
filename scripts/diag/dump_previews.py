"""把 docx 中的 MathType 预览图导出为 PNG，用于肉眼核对公式排版是否正常。

用法：
    python scripts/diag/dump_previews.py [导出数量，默认 8]
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
DOCX = ROOT / "paper" / "山区洪涝灾害下无人机运输与通信协同优化_论文.docx"
OUT = ROOT / "paper" / "_preview" / "equations"


def main() -> int:
    from PIL import Image

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    OUT.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(DOCX) as z:
        names = sorted(n for n in z.namelist() if "mathtype_preview" in n)
        items = []
        for n in names:
            im = Image.open(io.BytesIO(z.read(n)))
            items.append((im.size[0], im.size[1], n, im.copy()))

    print(f"预览图共 {len(items)} 张")
    print("\n最宽的 6 张（长公式）：")
    for w, h, n, _ in sorted(items, key=lambda t: -t[0])[:6]:
        print(f"  {n.rsplit('/', 1)[-1]:<28} {w:>5}x{h:<4}  高={h*0.32:.1f}pt")
    print("\n最高的 6 张（含分式/求和）：")
    for w, h, n, _ in sorted(items, key=lambda t: -t[1])[:6]:
        print(f"  {n.rsplit('/', 1)[-1]:<28} {w:>5}x{h:<4}  高={h*0.32:.1f}pt")

    # 拼接成一张对照图，便于一次性肉眼检查
    picks = sorted(items, key=lambda t: -t[1])[:limit]
    max_w = max(w for w, _, _, _ in picks) + 20
    total_h = sum(h + 14 for _, h, _, _ in picks) + 10
    sheet = Image.new("RGB", (max_w, total_h), "white")
    y = 5
    for w, h, _, im in picks:
        sheet.paste(im, (10, y))
        y += h + 14
    f = OUT / "equations_sheet.png"
    sheet.save(f)
    print(f"\n对照图（最高的 {limit} 张，按原始像素 1:1 粘贴）→ {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
