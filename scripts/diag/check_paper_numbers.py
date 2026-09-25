"""核对论文正文数字与 outputs 的 metrics 是否一致（防止论文混用不同版本的数据）。

用法：
    python scripts/diag/check_paper_numbers.py

判据分两类：
  A. **当前口径**的数值必须出现（否则说明正文没跟上重跑）；
  B. **历史口径**的数值必须不出现（否则说明有漏改的陈旧文本）。

两个列表都由 `outputs/qN/metrics.json` 与固定历史值构成，不手写当前结果。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / "paper" / "山区洪涝灾害下无人机运输与通信协同优化_论文.pdf"

#: 历史版本出现过、现已作废的数值（出现即为漏改）
#: ★ 只放**确实作废**的写法。例如 "20 个架次" 曾在旧口径下表示"20 个架次需中继"，
#:   但现口径下 "20/23 个架次零中断" 是正确表述，故不再列入 —— 否则会误报。
STALE = [
    "75.07", "77.30", "82.30", "72.86", "106.60", "79.65", "10968",
    "3.02 h", "2.45 h", "77.94", "62.5%", "38.8%", "25 架次", "28 架次",
    "35 架次", "6 个中继", "30 个中继架次", "13.95", "13.43",
    "13.00 h", "1.8517", "2.7035", "31.0%", "31.3%", "99.68",
    "中继时间覆盖复核", "几何可达覆盖率",
]


def main() -> int:
    import fitz

    doc = fitz.open(str(PDF))
    text = "".join(p.get_text() for p in doc)
    doc.close()

    m = {q: json.load(open(ROOT / f"outputs/{q}/metrics.json", encoding="utf-8"))["metrics"]
         for q in ("q1", "q2", "q3", "q4")}
    m1, m2, m3, m4 = m["q1"], m["q2"], m["q3"], m["q4"]

    def _h(sec: float) -> float:
        return float(sec) / 3600.0

    print("=== 当前 metrics（论文应引用这些值）===")
    print(f"  Q1: {m1['chosen_n_sorties']} 架次 / {m1['chosen_total_energy_kwh']:.3f} kWh "
          f"/ 下界 {m1['lower_bound_total_sorties']} / 达到下界 {m1['at_lower_bound']}")
    print(f"  Q2: {m2['n_sorties']} 架次 / {m2['total_energy_kwh']:.3f} kWh "
          f"/ 完工 {m2['makespan_s']:.2f} s ({m2['makespan_h']:.3f} h) "
          f"/ 准时 {m2['on_time_rate']:.1%} / 硬约束违规 {m2['n_verifier_violations']}")
    print(f"  Q3: 运输 {m3['n_transport_sorties']} / 中继 {m3['n_relay_sorties']} "
          f"/ 零中断架次 {m3['n_sorties_covered']}-{m3['n_transport_sorties']} "
          f"/ 总能耗 {m3['total_energy_kwh']:.3f} kWh "
          f"/ 联合完工 {m3['joint_cmax_s']:.2f} s ({_h(m3['joint_cmax_s']):.3f} h) "
          f"/ 中断样本 {m3['outage_samples']}/{m3['radio_samples']}")
    print(f"  Q4: 原子单元 {m4['n_atomic_units']} / 桥接 {m4['n_bridge_sorties']} "
          f"/ K2 可行 {m4['partition_feasible_k2']} / K3 可行 {m4['partition_feasible_k3']}")

    print("\n=== 一致性断言（全部由 metrics 推导，不硬编码历史数值）===")

    def num_appears(v: float, nd: int = 2) -> bool:
        """只找**数字本身**：表格里数值与表头单位在不同单元格，
        因此 `"3.05 h" in text` 会假报缺失。同时排除"更长数字的前缀"。"""
        s = f"{v:.{nd}f}"
        start = 0
        while True:
            j = text.find(s, start)
            if j < 0:
                return False
            before = text[j - 1] if j > 0 else ""
            after = text[j + len(s)] if j + len(s) < len(text) else ""
            if not (before.isdigit() or before == ".") and not (
                after.isdigit() or after == "."
            ):
                return True
            start = j + 1

    checks = [
        ("Q3 运输架次数 == Q2 架次数",
         m3["n_transport_sorties"] == m2["n_sorties"]),
        ("Q3 运输能耗 == Q2 总能耗",
         abs(m3["transport_energy_kwh"] - m2["total_energy_kwh"]) < 1e-6),
        ("Q3 总能耗 == 运输 + 中继",
         abs(m3["total_energy_kwh"]
             - m3["transport_energy_kwh"] - m3["relay_energy_kwh"]) < 1e-6),
        ("Q3 中断样本 < 总采样", m3["outage_samples"] < m3["radio_samples"]),
        (f"论文出现 Q1 架次数 {m1['chosen_n_sorties']}",
         f"{m1['chosen_n_sorties']} 架次" in text),
        (f"论文出现 Q1 能耗 {m1['chosen_total_energy_kwh']:.3f}",
         num_appears(m1["chosen_total_energy_kwh"], 3)),
        (f"论文出现 Q2 架次数 {m2['n_sorties']}",
         f"{m2['n_sorties']} 架次" in text or f"{m2['n_sorties']} 个运输架次" in text),
        (f"论文出现 Q2 能耗 {m2['total_energy_kwh']:.3f}",
         num_appears(m2["total_energy_kwh"], 3)),
        (f"论文出现 Q2 完工 {m2['makespan_s']:.2f} s",
         num_appears(m2["makespan_s"])),
        (f"论文出现 Q3 总能耗 {m3['total_energy_kwh']:.3f}",
         num_appears(m3["total_energy_kwh"], 3)),
        (f"论文出现 Q3 联合完工 {m3['joint_cmax_s']:.2f} s",
         num_appears(m3["joint_cmax_s"])),
        (f"论文出现 Q3 中继架次数 {m3['n_relay_sorties']}",
         num_appears(float(m3["n_relay_sorties"]), 0)),
        (f"论文出现 Q3 采样点数 {m3['radio_samples']:,}",
         f"{m3['radio_samples']:,}" in text or str(m3["radio_samples"]) in text),
        (f"论文出现 Q4 原子单元数 {m4['n_atomic_units']}",
         str(m4["n_atomic_units"]) in text),
    ]

    print("\n=== 历史口径数值（应已全部清除）===")
    for s in STALE:
        n = text.count(s)
        print(f"  {s!r:<16} {n} 次" + ("" if n == 0 else "   ← 仍有陈旧文本"))

    ok = True
    for name, good in checks:
        print(f"  {'✅' if good else '❌'} {name}")
        ok &= bool(good)
    stale_bad = [s for s in STALE if text.count(s) > 0]
    if stale_bad:
        print(f"\n❌ 论文仍含历史口径数值：{stale_bad}")
        ok = False

    print("\n" + ("✅ 论文数字与 metrics 一致" if ok else "❌ 存在不一致，请修正"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
