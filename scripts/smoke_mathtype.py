"""MathType 公式链路冒烟测试。

验证：OMML 原生公式 → docx-equation → MathType (Equation.DSMT4) OLE 对象。

用法：
    python scripts/smoke_mathtype.py
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from report import equations as EQ  # noqa: E402  (路径注入后导入)


SAMPLES = [
    ("display", r"t_{i,j} = \frac{h^{+}_{i,j}}{v^{up}} + \frac{d_{i,j}}{v_{c}} + \frac{h^{-}_{i,j}}{v^{down}}"),
    ("display", r"E^{h}_{i} = \frac{d_{i}}{L_{g}(q_{i})} \cdot E^{use}_{g}"),
    ("display", r"L_{g}(q) = L_{g0} - (L_{g0} - L_{gF}) \cdot (\frac{q}{Q_{g}})^{\frac{3}{2}}"),
    ("inline", r"\rho_{g} = 0.20"),
    ("inline", r"L_{max,a \leftrightarrow b} = min(L_{a \to b}, L_{b \to a})"),
]


def check_zip(dst: Path) -> dict:
    from PIL import Image

    with zipfile.ZipFile(dst) as z:
        names = z.namelist()
        embeds = [n for n in names if n.startswith("word/embeddings/")]
        previews = sorted(n for n in names if n.startswith("word/media/mathtype_preview"))
        doc_xml = z.read("word/document.xml").decode("utf-8", "ignore")
        sizes = []
        for n in previews:
            im = Image.open(io.BytesIO(z.read(n)))
            sizes.append((n.rsplit("/", 1)[-1], im.size))
    return {
        "embeds": len(embeds),
        "previews": len(previews),
        "sizes": sizes,
        "ole": doc_xml.count("<o:OLEObject"),
        "dsmt": doc_xml.count("Equation.DSMT4"),
        "omml": doc_xml.count("<m:oMath"),
        "alt": doc_xml.count("mc:AlternateContent"),
    }


def check_word(dst: Path, pdf: Path | None) -> None:
    """用 Word 实际打开产物：确认 Word 能识别 OLE 公式对象（不报"无法打开"）。"""
    try:
        import win32com.client as win32
    except ImportError:
        print("      （跳过 Word 校验：未安装 pywin32）")
        return
    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = False
    try:
        doc = word.Documents.Open(str(dst), ReadOnly=False)
        try:
            doc.Repaginate()
            n_shapes = int(doc.InlineShapes.Count)
            types: dict[int, int] = {}
            for i in range(1, n_shapes + 1):
                t = int(doc.InlineShapes.Item(i).Type)
                types[t] = types.get(t, 0) + 1
            print(f"      Word 打开成功，页数 = {int(doc.ComputeStatistics(2))}")
            print(f"      InlineShapes 总数 = {n_shapes}，按 Type 分布 = {types}")
            print("      （Type 1 = 嵌入 OLE 对象；Type 3 = 图片）")
            if pdf is not None:
                doc.SaveAs2(str(pdf), FileFormat=17)
                print(f"      已导出 PDF 预览：{pdf.name}")
        finally:
            doc.Close(SaveChanges=False)
    finally:
        word.Quit()


def main() -> int:
    from docx import Document

    out_dir = ROOT / "paper" / "_mathtype_smoke"
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = Document()
    doc.add_heading("MathType 公式链路冒烟测试", level=1)
    for kind, expr in SAMPLES:
        p = doc.add_paragraph()
        if kind == "display":
            p.alignment = 1
            EQ.append_omml(p, expr, display=False)
        else:
            p.add_run("行内公式：")
            EQ.append_omml(p, expr, display=False)
    src = out_dir / "omml_only.docx"
    doc.save(str(src))
    print(f"[1/3] OMML 源文件已生成：{src.name}  ({src.stat().st_size} bytes)")

    dst = out_dir / "mathtype.docx"
    if dst.exists():
        dst.unlink()
    try:
        n = EQ.convert_to_mathtype(src, dst, work_dir=out_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] MathType 转换异常：{type(exc).__name__}: {exc}")
        return 1
    print(f"[2/3] 转换完成：{dst.name}  ({dst.stat().st_size} bytes, 报告转换 {n} 个公式)")

    info = check_zip(dst)
    print("[3/3] 产物检查：")
    print(f"      embeddings (OLE .bin) : {info['embeds']}")
    print(f"      预览图 (PNG)          : {info['previews']}")
    for name, size in info["sizes"]:
        print(f"        - {name}: {size[0]}x{size[1]} px")
    print(f"      o:OLEObject           : {info['ole']}")
    print(f"      Equation.DSMT4        : {info['dsmt']}")
    print(f"      m:oMath（OMML 回退）   : {info['omml']}")
    print(f"      mc:AlternateContent   : {info['alt']}")

    print("[4/4] Word 实际打开校验：")
    check_word(dst, out_dir / "mathtype_preview.pdf")

    ok = info["dsmt"] > 0 and info["ole"] > 0 and info["previews"] > 0
    print("\n结论：" + ("✅ MathType 公式链路可用" if ok else "❌ 链路异常，需排查"))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
