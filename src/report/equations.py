"""公式辅助：用 OMML（Office Math Markup Language）生成**可在 Word 中编辑的公式**，
并支持进一步转换为 **MathType 原生公式对象**（`Equation.DSMT4` OLE）。

为什么用 OMML
-------------
    - OMML 是 Word 内置公式引擎的原生格式，插入后即为**可编辑公式**（非图片、非纯文本）
    - MathType 可直接读写 OMML，因此 OMML 是"公式使用 MathType"这一要求的正确落地方式
    - 进一步可用 `docx-equation` 把 OMML 批量转换为 MathType OLE 对象
      （见 `convert_to_mathtype`），转换后公式在 Word 中显示为 MathType 公式

设计
----
本模块提供一层轻量包装，把常见的数学结构（分式、上下标、根式、求和、希腊字母等）
映射为 OMML 片段，使论文生成器可以按"接近 LaTeX"的方式书写公式。
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

# ---------------------------------------------------------------- 符号表

GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ", "kappa": "κ",
    "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ",
    "sigma": "σ", "tau": "τ", "phi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ",
    "Pi": "Π", "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
}
OPS = {
    "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "ne": "≠", "neq": "≠",
    "approx": "≈", "in": "∈", "notin": "∉", "subset": "⊂", "subseteq": "⊆",
    "cup": "∪", "cap": "∩", "times": "×", "cdot": "·", "pm": "±",
    "to": "→", "rightarrow": "→", "leftrightarrow": "↔", "Rightarrow": "⇒",
    "infty": "∞", "partial": "∂", "nabla": "∇", "sum": "∑", "prod": "∏",
    "int": "∫", "forall": "∀", "exists": "∃", "emptyset": "∅", "angle": "∠",
    "uparrow": "↑", "downarrow": "↓", "iff": "⟺", "Leftrightarrow": "⟺",
    "lceil": "⌈", "rceil": "⌉", "lfloor": "⌊", "rfloor": "⌋",
    "ldots": "…", "cdots": "⋯", "\n": "\n",
}
FUNCS = {"max", "min", "log", "ln", "exp", "sin", "cos", "tan", "lim", "arg",
         "ceil", "floor", "sqrt", "abs", "det", "deg", "DEM", "FSPL", "SOC"}
"""函数名与整体正体记号。"""


def _rm(txt: str) -> str:
    """正体文本（`\\mathrm{...}` 的内容）。"""
    return "".join(_run(ch, italic=False) for ch in txt)

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"


def _esc(t: str) -> str:
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _run(text: str, italic: bool = True) -> str:
    """一个数学 run。变量斜体、数字与运算符正体（Word 默认排版规则）。"""
    sty = "" if italic else '<m:rPr><m:sty m:val="p"/></m:rPr>'
    return f'<m:r>{sty}<m:t xml:space="preserve">{_esc(text)}</m:t></m:r>'


def _atom(base: str) -> str:
    """把一个基础记号转成 OMML：希腊字母 / 运算符 / 函数名 / 变量 / 数字。

    排版规则（与 Word、MathType 默认一致）：
      - 单字母变量（含希腊字母）斜体
      - 函数名（max/min/log/log10/exp/ceil…）正体
      - 数字、单位、运算符、箭头正体
      - 多字母标识（FSPL、hor、up、ijt…）按"变量名"处理，整体斜体
    """
    if not base:
        return _run("", italic=False)
    if base in GREEK:
        return _run(GREEK[base], italic=True)
    if base in OPS:
        return _run(OPS[base], italic=False)
    if base in FUNCS:
        return _run(base, italic=False)
    if re.fullmatch(r"[\d.,%]+", base):
        return _run(base, italic=False)
    if re.fullmatch(r"[A-Za-z]+", base):
        return _run(base, italic=True)
    # 混合串：字母斜体、数字与其他字符正体
    out = []
    for ch in base:
        out.append(_run(ch, italic=ch.isalpha()))
    return "".join(out)


# ---------------------------------------------------------------- 结构

def frac(num: str, den: str) -> str:
    return f"<m:f><m:num>{_expr(num)}</m:num><m:den>{_expr(den)}</m:den></m:f>"


def sqrt(inner: str, degree: str | None = None) -> str:
    if degree:
        return (f"<m:rad><m:radPr><m:degHide m:val=\"0\"/></m:radPr>"
                f"<m:deg>{_expr(degree)}</m:deg><m:e>{_expr(inner)}</m:e></m:rad>")
    return (f"<m:rad><m:radPr><m:degHide m:val=\"1\"/></m:radPr>"
            f"<m:deg/><m:e>{_expr(inner)}</m:e></m:rad>")


def nary(inner: str, sub: str = "", sup: str = "", op: str = "∑") -> str:
    """大算符（求和/求积/积分）。"""
    return (
        "<m:nary><m:naryPr><m:chr m:val=\"" + op + "\"/>"
        "<m:limLoc m:val=\"undOvr\"/>"
        + ("<m:subHide m:val=\"1\"/>" if not sub else "")
        + ("<m:supHide m:val=\"1\"/>" if not sup else "")
        + "</m:naryPr>"
        f"<m:sub>{_expr(sub)}</m:sub><m:sup>{_expr(sup)}</m:sup>"
        f"<m:e>{_expr(inner)}</m:e></m:nary>"
    )


def bar(inner: str, pos: str = "top") -> str:
    """上划线 / 下划线（`\\overline`、`\\underline`）。"""
    pr = ('<m:barPr><m:pos m:val="bot"/></m:barPr>' if pos == "bot"
          else '<m:barPr><m:pos m:val="top"/></m:barPr>')
    return f"<m:bar>{pr}<m:e>{_expr(inner)}</m:e></m:bar>"


def paren(inner: str) -> str:
    return (f"<m:d><m:dPr><m:begChr m:val=\"(\"/><m:endChr m:val=\")\"/></m:dPr>"
            f"<m:e>{_expr(inner)}</m:e></m:d>")


def bracket(inner: str) -> str:
    return (f"<m:d><m:dPr><m:begChr m:val=\"[\"/><m:endChr m:val=\"]\"/></m:dPr>"
            f"<m:e>{_expr(inner)}</m:e></m:d>")


def brace(inner: str) -> str:
    return ('<m:d><m:dPr><m:begChr m:val="{"/><m:endChr m:val="}"/></m:dPr>'
            f"<m:e>{_expr(inner)}</m:e></m:d>")


def cases(rows: list[tuple[str, str]]) -> str:
    """分段函数：rows = [(表达式, 条件), ...]。"""
    body = "".join(f"<m:e>{_expr(e)}</m:e>" for e, _ in rows)
    return ('<m:d><m:dPr><m:begChr m:val="{"/><m:endChr m:val=""/></m:dPr>'
            f"<m:e><m:eqArr>{body}</m:eqArr></m:e></m:d>")


# ---------------------------------------------------------------- 解析

_IDENT = re.compile(r"[A-Za-z][A-Za-z0-9]*")


def _expr(s: str) -> str:
    """把"类 LaTeX"表达式转成 OMML 序列。

    支持：
      - `\\frac{a}{b}`、`\\sqrt{x}`、`\\sum_{}^{}`、`\\int`
      - 上下标：`x_{i,j}`、`E^{h}`、`x_a`、`E^h`（无花括号时下标吃字母数字串、
        上标只吃一个字符，与 LaTeX 一致）
      - 希腊字母与常用运算符：`\\rho_g`、`\\le`、`\\to`、`\\leftrightarrow`
      - 直书符号：`≤ ≥ ∈ Σ · × → ↔ ± ∞`
      - 函数名自动正体：`max min log log10 exp ceil`
    变量斜体、数字与运算符正体（Word / MathType 默认排版规则）。
    """
    if not s:
        return ""
    s = s.strip()
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch == " ":
            out.append(_run(" ", italic=False))
            i += 1
            continue
        if ch == "\\":
            if i + 1 < n and s[i + 1] in "{}":
                out.append(_run(s[i + 1], italic=False))
                i += 2
                continue
            m = _IDENT.match(s, i + 1)
            if m:
                name = m.group(0)
                i = m.end()
                if name == "frac":
                    num, i = _read_group(s, i)
                    den, i = _read_group(s, i)
                    out.append(frac(num, den))
                    continue
                if name == "sqrt":
                    inner, i = _read_group(s, i)
                    out.append(sqrt(inner))
                    continue
                if name in ("sum", "prod", "int"):
                    op = {"sum": "∑", "prod": "∏", "int": "∫"}[name]
                    sub = sup = ""
                    for _ in range(2):
                        if i < n and s[i] == "_":
                            sub, i = _read_group(s, i + 1)
                        elif i < n and s[i] == "^":
                            sup, i = _read_group(s, i + 1)
                    body, i = _read_group(s, i) if i < n and s[i] == "{" else ("", i)
                    out.append(nary(body, sub, sup, op))
                    continue
                if name in ("mathrm", "text", "operatorname"):
                    txt, i = _read_group(s, i)
                    out.append(_rm(txt))
                    continue
                if name in ("overline", "bar"):
                    inner, i = _read_group(s, i)
                    out.append(bar(inner, "top"))
                    continue
                if name in ("underline",):
                    inner, i = _read_group(s, i)
                    out.append(bar(inner, "bot"))
                    continue
                if name in ("left", "right", "quad", "qquad"):
                    if name in ("quad", "qquad"):
                        out.append(_run("  ", italic=False))
                    continue
                out.append(_atom(name))
                continue
            i += 1
            continue
        if ch in "{}":
            _skip, i = _read_group(s, i)
            continue
        if ch in "_^":
            if i + 1 < n and s[i + 1] == "{":
                val, i = _read_group(s, i + 1)
            elif ch == "_":
                m = _IDENT.match(s, i + 1)
                if m:
                    val, i = m.group(0), m.end()
                else:
                    val, i = (s[i + 1] if i + 1 < n else ""), i + 2
            else:
                val, i = (s[i + 1] if i + 1 < n else ""), i + 2
            prev = out.pop() if out else _run("", italic=False)
            tag = "sSub" if ch == "_" else "sSup"
            slot = "sub" if ch == "_" else "sup"
            out.append(f"<m:{tag}><m:e>{prev}</m:e>"
                       f"<m:{slot}>{_expr(val)}</m:{slot}></m:{tag}>")
            continue
        # 普通记号：累积到下一个特殊字符
        j = i
        while j < n and s[j] not in "\\{}_^ ":
            j += 1
        out.append(_atom(s[i:j]))
        i = j
    return "".join(out)


def _read_group(s: str, i: int) -> tuple[str, int]:
    """读取 `{...}` 分组，返回 (内容, 结束后的下标)；无花括号时吃一个字符。"""
    if i >= len(s):
        return "", i
    if s[i] != "{":
        if s[i] in "_^\\":
            return "", i
        return s[i], i + 1
    depth, k = 1, i + 1
    while k < len(s) and depth:
        if s[k] == "{":
            depth += 1
        elif s[k] == "}":
            depth -= 1
        k += 1
    return s[i + 1 : k - 1], k


# ---------------------------------------------------------------- 输出

def omml(expr: str, display: bool = True) -> str:
    """把表达式转成完整的 `<m:oMath>` 或 `<m:oMathPara>` 元素字符串。"""
    body = _expr(expr)
    if display:
        return (f'<m:oMathPara xmlns:m="{M_NS}"><m:oMath>{body}</m:oMath>'
                f'</m:oMathPara>')
    return f'<m:oMath xmlns:m="{M_NS}">{body}</m:oMath>'


def append_omml(paragraph, expr: str, display: bool = False) -> None:
    """把公式追加到指定段落（OMML 原生可编辑公式）。"""
    from docx.oxml import parse_xml

    paragraph._p.append(parse_xml(omml(expr, display=display)))


def set_run_math(run, expr: str) -> None:
    """把段落内某个 run 替换为公式（用于 `x_{t}` 这类行内公式）。"""
    from docx.oxml import parse_xml

    run._r.append(parse_xml(omml(expr, display=False)))


# ---------------------------------------------------------------- MathType 转换

WIN_OMML_XSL = Path(r"C:\Program Files\Microsoft Office\root\Office16\OMML2MML.XSL")
"""Microsoft Office 自带的 OMML→MathML 样式表（MathType 转换的前置步骤）。"""

PREVIEW_PT_PER_PX = 0.23
"""公式预览图的显示比例（点/像素）。

预览图按 72 px 字号、`--force-device-scale-factor=1` 渲染，量测得到的换算关系为
**1 pt 字号 ≈ 4.1 px**（大写字母高约 55 px → 12 pt 字号）。因此：

  · 需要与 12 pt 正文相称的行内公式，其"基字高"应约 49 px → 0.23 pt/px；
  · 在 300 dpi 的成品 PDF 上实测：正文行墨迹高 11.5 pt，行内公式带 12 pt，二者相称。

标定过程见 `scripts/diag/line_heights.py`（逐行量测）与 `scripts/diag/mathtype_scale.py`。
"""

BROWSER_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
)
"""`docx-equation` 渲染公式预览图需要 Chromium 内核浏览器（Windows 上通常是 Edge）。"""


def find_browser() -> Path | None:
    """定位 Chromium 内核浏览器（Chrome / Edge）。"""
    import shutil

    for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
        found = shutil.which(name)
        if found:
            return Path(found)
    for cand in BROWSER_CANDIDATES:
        if Path(cand).exists():
            return Path(cand)
    return None


# ---------------------------------------------------------------- 预览图重绘

_HTML_TMPL = """<!doctype html>
<html><head><meta charset="utf-8">
<style>
  html, body {{ margin: 0; padding: 0; background: #fff; }}
  .box {{ display: inline-flex; align-items: center; justify-content: center;
          padding: 30px; background: #fff; }}
  math {{ font-family: "Cambria Math", "STIX Two Math", "Times New Roman", serif;
          font-size: {font_px}px; math-style: normal; }}
</style></head>
<body><div class="box">{mathml}</div></body></html>
"""


def _to_html_mathml(mml_text: str) -> str:
    """`mml:math` → `math`（去掉前缀与 XML 声明），并压掉多余空白。

    ★ 关键：**HTML 解析器不做命名空间解析**。形如 `mml:math` 的标签在 HTML 中
    会被当作"未知内联元素"，其内容退化为一行普通文字（上下标、分式全部丢失）。
    必须去掉 `mml:` 前缀、让根元素就叫 `math`，浏览器才会按 MathML Core 排版。
    """
    import re as _re

    t = mml_text
    t = _re.sub(r"<\?xml[^>]*\?>", "", t)
    t = _re.sub(r'\s+xmlns:mml="[^"]*"', "", t)
    t = _re.sub(r"\bmml:", "", t)
    # 压掉 pretty-print 引入的缩进/换行，避免在 <mi> 里产生多余空格
    t = _re.sub(r">\s+<", "><", t)
    return t.strip()


def render_previews(
    mathml_dir: Path,
    preview_dir: Path,
    browser: Path | None = None,
    font_px: int = 72,
    window: tuple[int, int] = (6000, 1200),
    padding_px: int = 6,
) -> int:
    """用浏览器把 MathML 渲染成**正确排版**的预览图（覆盖库生成的降级版本）。

    背景：`docx-equation` 把 `mml:math` 原样塞进 HTML，Chrome/Edge 会当成未知元素，
    渲染结果是"一行普通文字"（上下标、分式、大算符全部丢失）。这里改为
    去前缀后渲染，并用 `--force-device-scale-factor=1` + 高窗口宽度保证长公式不被裁断。

    返回成功渲染的图片数。
    """
    import shutil
    import subprocess
    import tempfile

    from PIL import Image

    browser = browser or find_browser()
    if browser is None:
        raise FileNotFoundError("未找到 Chromium 内核浏览器（Chrome / Edge），无法渲染公式预览图")

    files = sorted(mathml_dir.glob("equation_*.mml"))
    if not files:
        raise FileNotFoundError(f"未找到 MathML 文件：{mathml_dir}")
    preview_dir.mkdir(parents=True, exist_ok=True)

    tmp = Path(tempfile.mkdtemp(prefix="eq_preview_"))
    n = 0
    try:
        for src in files:
            html = tmp / f"{src.stem}.html"
            html.write_text(
                _HTML_TMPL.format(font_px=font_px,
                                  mathml=_to_html_mathml(src.read_text(encoding="utf-8"))),
                encoding="utf-8")
            raw = tmp / f"{src.stem}.raw.png"
            subprocess.run(
                [str(browser), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                 "--force-device-scale-factor=1",
                 f"--window-size={window[0]},{window[1]}",
                 f"--screenshot={raw}", html.resolve().as_uri()],
                check=True, capture_output=True, timeout=180)
            _crop_png(raw, preview_dir / f"{src.stem}.png", padding_px)
            n += 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return n


def _crop_png(source: Path, target: Path, padding_px: int = 6) -> None:
    """裁掉白边（保留少量内边距），使图片尺寸即公式墨迹尺寸。"""
    from PIL import Image, ImageChops

    image = Image.open(source).convert("RGB")
    white = Image.new("RGB", image.size, "white")
    diff = ImageChops.difference(image, white)
    mask = diff.convert("L").point(lambda v: 255 if v > 12 else 0)
    bbox = mask.getbbox()
    if bbox is None:
        image.save(target)
        return
    box = (max(0, bbox[0] - padding_px), max(0, bbox[1] - padding_px),
           min(image.width, bbox[2] + padding_px), min(image.height, bbox[3] + padding_px))
    image.crop(box).save(target)


def reembed_previews(docx: Path, preview_dir: Path) -> int:
    """把重绘后的预览图写回 docx，并按新尺寸修正显示宽高与 `w:dxaOrig/dyaOrig`。"""
    import shutil
    import zipfile

    import numpy as np
    from PIL import Image
    from lxml import etree

    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    V = "urn:schemas-microsoft-com:vml"
    A = "http://schemas.openxmlformats.org/drawingml/2006/main"
    EMU_PT = 12700

    def q(tag: str) -> str:
        p, l = tag.split(":")
        ns = {"w": W, "v": V, "a": A}[p]
        return f"{{{ns}}}{l}"

    tmp_out = docx.with_name(docx.stem + "_reprev.docx")
    images: dict[str, bytes] = {}
    with zipfile.ZipFile(docx) as z:
        doc_xml = z.read("word/document.xml")
        root = etree.fromstring(doc_xml)
        other = {i.filename: z.read(i.filename) for i in z.infolist()
                 if i.filename != "word/document.xml"}

    shapes = root.findall(f".//{q('v:shape')}")
    if not shapes:
        return 0

    for idx, shape in enumerate(shapes, 1):
        img_path = preview_dir / f"equation_{idx:03d}.png"
        if not img_path.exists():
            continue
        w_px, h_px = Image.open(img_path).size
        w_pt, h_pt = w_px * PREVIEW_PT_PER_PX, h_px * PREVIEW_PT_PER_PX
        shape.set("style", f"width:{w_pt:.1f}pt;height:{h_pt:.1f}pt")
        a_el = shape.find(f".//{q('a:ext')}")
        if a_el is not None:
            a_el.set("cx", str(int(w_pt * EMU_PT)))
            a_el.set("cy", str(int(h_pt * EMU_PT)))
        obj = shape.getparent()
        obj.set(q("w:dxaOrig"), str(int(w_pt * 20)))
        obj.set(q("w:dyaOrig"), str(int(h_pt * 20)))
        images[f"equation_{idx:03d}.png"] = img_path.read_bytes()

    if not images:
        return 0

    # 覆盖 word/media/mathtype_preview_XXX.png（按公式序号一一对应）
    for name, data in images.items():
        other[f"word/media/mathtype_preview_{name.replace('equation_', '')}"] = data

    with zipfile.ZipFile(tmp_out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", etree.tostring(
            root, xml_declaration=True, encoding="UTF-8", standalone=True))
        for name, data in other.items():
            z.writestr(name, data)
    shutil.move(str(tmp_out), str(docx))
    return len(images)


def convert_to_mathtype(
    src: Path,
    dst: Path,
    xsl: Path | None = None,
    mathtype_version: str = "DSMT4",
    work_dir: Path | None = None,
    browser: Path | None = None,
    preview_pt_per_px: float = PREVIEW_PT_PER_PX,
    inline_height_pt: float = 12.5,
    display_height_pt: float = 21.0,
    max_width_pt: float = 380.0,
) -> int:
    """把 docx 中的 OMML 公式批量转换为 **MathType 原生公式对象**。

    依赖 `docx-equation`（MIT 许可证）。该库通过 OMML→MathML→MTEF 的链路
    生成 `Equation.DSMT4` OLE 对象 + PNG 预览图（预览图保证无 MathType
    的环境也能正常显示与打印公式）。

    ★ 该库的预览图渲染有缺陷：它把 `mml:math` 原样嵌入 HTML，而 **HTML 解析器
    不做命名空间解析**，`mml:math` 会被当成未知内联元素，渲染成"一行普通文字"
    （上下标、分式、大算符全部丢失）。因此这里在转换之后**用正确的方式重绘
    预览图并写回 docx**，使公式排版与 MathType 的呈现一致。

    返回转换的公式数量；失败时抛异常（不静默跳过）。
    """
    import shutil
    import zipfile

    from docx_equation import convert_omml_docx_to_mathtype
    from docx_equation.shared import mathml as _mathml

    xsl = xsl or WIN_OMML_XSL
    if not Path(xsl).exists():
        raise FileNotFoundError(
            f"未找到 OMML→MathML 样式表：{xsl}\n"
            f"该文件随 Microsoft Office 安装（通常在 Office16 目录下）。"
        )

    # 该库只按 PATH 名查找浏览器，找不到 Windows 默认安装路径下的 Edge，
    # 因此这里显式定位并注入；不改动第三方库源码。
    browser = browser or find_browser()
    if browser is not None:
        _mathml._find_chrome = lambda *_a, **_k: Path(browser)  # noqa: SLF001

    work = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="eq_convert_"))
    work.mkdir(parents=True, exist_ok=True)
    keep = work_dir is not None
    try:
        n = int(convert_omml_docx_to_mathtype(
            str(src), str(dst), work_dir=str(work),
            omml2mathml_xsl=str(xsl), mathtype_version=mathtype_version,
            preview_pt_per_px=preview_pt_per_px,
            inline_height_pt=inline_height_pt,
            display_height_pt=display_height_pt,
            max_width_pt=max_width_pt,
        ))
        # ★ 重绘预览图（修正上下标/分式丢失），并按新尺寸写回 docx
        mathml_dir = work / "mathml"
        preview_dir = work / "preview_png"
        if browser is not None and mathml_dir.exists():
            render_previews(mathml_dir, preview_dir, browser=browser)
            reembed_previews(dst, preview_dir)
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)
    return n
