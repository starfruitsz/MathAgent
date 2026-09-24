"""诊断：确认 Edge/Chrome 是否把 .mml 渲染成真正的数学排版。

用 `--dump-dom` 看浏览器实际解析出的 DOM（判断是否被当作未知内联元素），
再截图保存，供肉眼核对。

用法：
    python scripts/diag/render_mml_test.py
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

HTML_TMPL = """<!doctype html>
<html><head><meta charset="utf-8">
<style>
  html, body {{ margin: 0; padding: 0; background: #fff; }}
  .box {{ display: inline-flex; align-items: center; justify-content: center;
          padding: 26px; background: #fff; }}
  math {{ font-family: "Times New Roman", "STIX Two Math", "Cambria Math", serif;
          font-size: 38px; math-style: normal; }}
</style></head>
<body><div class="box">{mathml}</div></body></html>
"""


def main() -> int:
    browser = EQ.find_browser()
    print(f"浏览器：{browser}")
    if browser is None:
        return 1
    OUT.mkdir(parents=True, exist_ok=True)

    mml_dir = ROOT / "paper" / "_mathtype_work" / "mathml"
    files = sorted(mml_dir.glob("equation_*.mml"))
    if not files:
        print(f"❌ 没有 .mml 文件：{mml_dir}")
        return 1

    # 取一个含分式的（较长的那条）
    src = max(files, key=lambda p: p.stat().st_size)
    print(f"样本：{src.name}  ({src.stat().st_size} bytes)")
    mathml = src.read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory() as td:
        html = Path(td) / "t.html"
        html.write_text(HTML_TMPL.format(mathml=mathml), encoding="utf-8")

        # 1) DOM 结构
        r = subprocess.run([str(browser), "--headless=new", "--disable-gpu",
                            "--dump-dom", html.resolve().as_uri()],
                           capture_output=True, timeout=120)
        dom = r.stdout.decode("utf-8", "ignore")
        print("\n=== 浏览器解析后的 DOM（节选）===")
        i = dom.find("<div class=\"box\">")
        print(dom[i:i + 900] if i >= 0 else dom[:900])
        print("\n统计：")
        for tag in ("math", "msub", "msup", "mfrac", "munderover", "mo", "mi", "mn"):
            print(f"  <{tag}> 出现 {dom.count('<' + tag)} 次")

        # 2) 截图
        png = OUT / "browser_render.png"
        r2 = subprocess.run([str(browser), "--headless=new", "--disable-gpu",
                             "--hide-scrollbars", "--force-device-scale-factor=2",
                             "--window-size=2600,700", f"--screenshot={png}",
                             html.resolve().as_uri()],
                            capture_output=True, timeout=120)
        print(f"\n截图：{png}  存在={png.exists()}")
        if not png.exists():
            print(r2.stderr.decode("utf-8", "ignore")[-500:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
