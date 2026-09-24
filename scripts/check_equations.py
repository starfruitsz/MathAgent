"""公式解析自检：把论文中出现的全部公式过一遍解析器，检查 OMML 良构且无遗漏。

用法：
    python scripts/check_equations.py
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from report import equations as EQ  # noqa: E402

DISPLAY = [
    r"H_{cruise}(i,j) = max\{ DEM(p) : p \in 直线段(i,j) \} + 50\ m",
    r"h^{+}(i,j) = H_{cruise} - H_{op}(i),\quad h^{-}(i,j) = H_{cruise} - H_{op}(j)",
    r"L_{g}(q) = L_{g0} - (L_{g0} - L_{gF}) \cdot (\frac{q}{Q_{g}})^{\frac{3}{2}}, \quad 0 \le q \le Q_{g}",
    r"E_{g}^{T}(q) = \sum_{i,j} E_{gij}(q_{pij}) \le (1 - \rho_{g}) \cdot E_{g}^{use}",
    r"t_{gij} = \frac{h^{+}}{v_{g}^{\uparrow}} + \frac{d_{ij}}{v_{g}^{c}} + \frac{h^{-}}{v_{g}^{\downarrow}}",
    r"E_{gij}(q) = E_{gij}^{hor}(q) + E_{gij}^{up}(q)",
    r"t_{chg}(s) = T_{full} \cdot [0.65 \cdot \frac{0.90 - s}{0.90} + 0.35], \quad 0 \le s < 0.90",
    r"t_{chg}(s) = T_{full} \cdot 0.35 \cdot \frac{1 - s}{0.10}, \quad 0.90 \le s \le 1",
    r"P_{th,b} = P_{sens,b} + M_{b}",
    r"L_{max,a \to b} = P_{t,a} + G_{t,a} + G_{r,b} - L_{sys} - P_{th,b}",
    r"L_{max,a \leftrightarrow b} = min( L_{max,a \to b}, L_{max,b \to a} )",
    r"L_{FSPL,ijt} = 32.45 + 20 \cdot log10(f) + 20 \cdot log10(D_{ijt})",
    r"L_{path,ijt} = L_{FSPL,ijt} + L_{obs} \cdot b_{ijt}, \quad A_{ijt} = 1 若 L_{path} \le L_{max}",
    r"LB = max( ceil(\frac{\sum m_{b}}{max_{g} q_{max}}), ceil(\frac{\sum v_{b}}{max_{g} V_{g}}) )",
    r"\forall m: \sum_{k \ge m} m_{k} \le Q_{g} 且 \sum_{k \ge m} v_{k} \le V_{g}",
    r"E_{p}^{T} = \sum_{m} E_{g}(seg_{m}, q_{m}) \le (1 - \rho_{g}) \cdot E_{g}^{use}",
    r"t_{p} = t_{prep} + n_{box} \cdot t_{load} + \sum_{m} t_{g}(seg_{m}) + \sum_{stops} (t_{h0} + k_{s} \cdot t_{h1})",
    r"t_{link} = t_{prep} + t_{fly}(O01 \to P) + t_{setup}, \quad t_{svc} = [t_{link}, 窗口结束]",
    r"E_{R} = E_{up}(m_{takeoff}, h^{+}) + P_{cruise} \cdot t_{cruise} + (P_{hover} + P_{comms}) \cdot t_{svc}",
]

INLINE = [
    r"\rho_{g} = 0.20", r"\rho_{g} > 0.40", r"q/Q_{g}", r"E_{g}^{T}(q)",
    r"E_{gij}^{hor}(q) = (d_{ij} / L_{g}(q)) \cdot E_{g}^{use}",
    r"E_{gij}^{up} = m \cdot g \cdot h^{+} / \eta_{up}", r"\eta_{up} = 0.72",
    r"(1-\rho) \cdot L_{g}(q)", r"s = 0.90", r"b_{ijt} = 1",
    r"L_{max,a \to b}", r"max_{g} q_{max}^{safe}(g,i)", r"\sum m_{b} \le q_{max}^{safe}(g,i)",
    r"\sum v_{b} \le V_{g}", r"S003", r"O01 \to S_{i} \to O01",
    r"t_{chg}", r"V_{g}", r"Q_{g}", r"30\ m", r"L_{obs}", r"M_{b}", r"P_{sens,b}",
]


def main() -> int:
    bad = 0
    for tag, items in (("display", DISPLAY), ("inline", INLINE)):
        for e in items:
            try:
                xml = EQ.omml(e, display=False)
                ET.fromstring(xml)
            except Exception as exc:  # noqa: BLE001
                bad += 1
                print(f"❌ [{tag}] {e}\n    {type(exc).__name__}: {exc}")
    print(f"共检查 {len(DISPLAY) + len(INLINE)} 条公式，失败 {bad} 条")

    print("\n—— 抽查 OMML 结构（前 3 条）——")
    for e in DISPLAY[:3]:
        x = EQ.omml(e, display=False)
        print(f"\n{e}\n  → {x[:300]}{'...' if len(x) > 300 else ''}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
