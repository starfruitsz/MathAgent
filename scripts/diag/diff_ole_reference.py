"""对比"真品" MathType 对象与 docx-equation 产物的差异。

用法：
    python scripts/diag/diff_ole_reference.py
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_ole_streams import cfb_streams  # noqa: E402

REF = ROOT / "paper" / "_probe_min" / "ref_object.docx"
OURS = ROOT / "paper" / "山区洪涝灾害下无人机运输与通信协同优化_论文.docx"


def show(label: str, docx: Path) -> dict:
    print(f"\n{'=' * 74}\n{label}：{docx.name}\n{'=' * 74}")
    with zipfile.ZipFile(docx) as z:
        xml = z.read("word/document.xml").decode("utf-8")
        rels = z.read("word/_rels/document.xml.rels").decode("utf-8")
        ct = z.read("[Content_Types].xml").decode("utf-8")
        emb = sorted(n for n in z.namelist() if n.startswith("word/embeddings/"))
        media = sorted(n for n in z.namelist() if "media/" in n)
        print(f"  embeddings: {[n.rsplit('/', 1)[-1] for n in emb]}")
        print(f"  media     : {[n.rsplit('/', 1)[-1] for n in media][:4]}"
              f"{' …' if len(media) > 4 else ''}")

        j = xml.find("<w:object")
        if j < 0:
            j = xml.find("<w:pict")
        print("\n  --- w:object / w:pict 片段 ---")
        print("  " + xml[j:j + 1600].replace("><", ">\n  <")[:2600])

        print("\n  --- OLE 相关 Relationship ---")
        for m in re.finditer(r'<Relationship[^>]*Type="[^"]*oleObject"[^>]*/>', rels):
            print("  " + m.group(0))
        print("\n  --- Content_Types 中的 oleObject 默认项 ---")
        for m in re.finditer(r'<Default Extension="[^"]*"[^>]*/>', ct):
            if "ole" in m.group(0).lower() or "bin" in m.group(0).lower():
                print("  " + m.group(0))

        if emb:
            data = z.read(emb[0])
            print(f"\n  --- {emb[0].rsplit('/', 1)[-1]} ({len(data)} bytes) 内部流 ---")
            try:
                streams = cfb_streams(data)
                for sn, sd in streams.items():
                    print(f"    {sn!r:<24} {len(sd):>5} bytes  头 {sd[:20].hex(' ')}")
            except Exception as exc:  # noqa: BLE001
                print(f"    解析失败：{exc}")
            return {"xml": xml, "rel": rels, "data": data}
    return {}


def main() -> int:
    if not REF.exists():
        print(f"❌ 缺少真品样本 {REF}\n请先运行 scripts/diag/make_reference_object.py")
        return 1
    show("① 真品（Word + MathType 插入）", REF)
    if OURS.exists():
        show("② 本仓库产物（docx-equation）", OURS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
