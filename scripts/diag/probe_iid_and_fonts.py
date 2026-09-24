"""诊断：① 枚举候选 IEquation IID，找 MathType 7 真正支持的那个；
② 用 PDF 字体信息读出参考文稿2 与本论文的**字号**，直接对标公式比例。

用法：
    python scripts/diag/probe_iid_and_fonts.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
OURS = ROOT / "paper" / "山区洪涝灾害下无人机运输与通信协同优化_论文.pdf"
REF = ROOT / "docs" / "reference" / "参考文稿2.pdf"

IID_CANDIDATES = [
    "{0002CE01-0000-0000-C000-000000000046}",
    "{0002CE02-0000-0000-C000-000000000046}",
    "{0002CE04-0000-0000-C000-000000000046}",
    "{0002CE05-0000-0000-C000-000000000046}",
    "{0002CE06-0000-0000-C000-000000000046}",
    "{0002CE07-0000-0000-C000-000000000046}",
    "{0002CE08-0000-0000-C000-000000000046}",
]


def probe_iids() -> None:
    import comtypes
    from comtypes import GUID, CoInitialize

    CoInitialize()
    clsid = GUID("{0002CE03-0000-0000-C000-000000000046}")
    print("=== 候选 IEquation IID 探测（QueryInterface）===")
    # 先用 IDispatch 拿到对象，再逐个 QueryInterface
    import comtypes.client

    raw = comtypes.client.CreateObject("Equation.DSMT4")
    punk = raw._com_pointers_[0] if hasattr(raw, "_com_pointers_") else None
    print(f"  IDispatch 对象：{raw}  punk={punk}")
    for iid in IID_CANDIDATES:
        try:
            iface = raw.QueryInterface(GUID(iid))
            print(f"  ✅ {iid} 受支持 → {iface}")
        except Exception as exc:  # noqa: BLE001
            print(f"  ❌ {iid}  {str(exc)[:80]}")


def font_report(pdf: Path, pno: int, note: str) -> None:
    import fitz

    doc = fitz.open(str(pdf))
    page = doc[pno - 1]
    d = page.get_text("dict")
    sizes: dict[float, int] = {}
    for block in d.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                sz = round(float(span["size"]), 1)
                sizes[sz] = sizes.get(sz, 0) + len(span["text"].strip())
    print(f"\n=== {note} 第 {pno} 页 · 字号分布（按字符数）===")
    for sz, cnt in sorted(sizes.items(), key=lambda kv: -kv[1])[:10]:
        print(f"  {sz:>6.1f} pt   {cnt:>5} 字符")
    doc.close()


def main() -> int:
    try:
        probe_iids()
    except Exception as exc:  # noqa: BLE001
        print(f"IID 探测失败：{type(exc).__name__}: {exc}")

    if REF.exists():
        font_report(REF, 11, "参考文稿2")
    if OURS.exists():
        font_report(OURS, 20, "本论文")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
