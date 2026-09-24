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


def convert_to_mathtype(
    src: Path,
    dst: Path,
    xsl: Path | None = None,
    mathtype_version: str = "DSMT4",
    work_dir: Path | None = None,
    browser: Path | None = None,
    preview_pt_per_px: float = 0.32,
    inline_height_pt: float = 12.5,
    display_height_pt: float = 21.0,
    max_width_pt: float = 380.0,
) -> int:
    """把 docx 中的 OMML 公式批量转换为 **MathType 原生公式对象**。

    依赖 `docx-equation`（MIT 许可证）。该库通过 OMML→MathML→MTEF 的链路
    生成 `Equation.DSMT4` OLE 对象，并保留 PNG 预览图用于显示与打印，
    因此即使阅读环境没有 MathType 也能正常显示公式。

    `preview_pt_per_px` 决定预览图在文档中的显示尺寸：库默认 0.15 会使公式
    比 12 pt 正文偏小；经标定取 0.19，使行内公式的大小与正文协调。

    返回转换的公式数量；失败时抛异常（不静默跳过）。
    """
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
    if browser is None:
        browser = find_browser()
        if browser is not None:
            _mathml._find_chrome = lambda *_a, **_k: Path(browser)  # noqa: SLF001

    return int(convert_omml_docx_to_mathtype(
        str(src), str(dst), work_dir=str(work_dir) if work_dir else None,
        omml2mathml_xsl=str(xsl), mathtype_version=mathtype_version,
        preview_pt_per_px=preview_pt_per_px,
        inline_height_pt=inline_height_pt,
        display_height_pt=display_height_pt,
        max_width_pt=max_width_pt,
    ))
