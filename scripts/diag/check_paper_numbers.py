"""核对论文正文数字与 outputs 的 metrics 是否一致（防止论文混用不同版本的数据）。

用法：
    python scripts/diag/check_paper_numbers.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / "paper" / "山区洪涝灾害下无人机运输与通信协同优化_论文.pdf"


def main() -> int:
    import fitz

    doc = fitz.open(str(PDF))
    text = "".join(p.get_text() for p in doc)
    doc.close()

    m = {q: json.load(open(ROOT / f"outputs/{q}/metrics.json", encoding="utf-8"))["metrics"]
         for q in ("q1", "q2", "q3", "q4")}
    m1, m2, m3, m4 = m["q1"], m["q2"], m["q3"], m["q4"]

    print("=== 论文正文中的关键数字出现次数 ===")
    probes = [
        "22 架次", "35 架次", "35 个运输架次", "75.06", "83.01",
        "4.04 h", "9.78 h", "9.90 h", "587 min", "62.5%", "38.8%",
        "30 个中继架次", "29/29", "31.3%", "31.0%", "18 架次", "99.68",
    ]
    for p in probes:
        print(f"  {p!r:<20} {text.count(p)} 次")

    print("\n=== 当前 metrics（论文应引用这些值）===")
    print(f"  Q1: {m1['chosen_n_sorties']} 架次 / {m1['chosen_total_energy_kwh']:.2f} kWh "
          f"/ 下界 {m1['lower_bound_total_sorties']}")
    print(f"  Q2: {m2['n_sorties']} 架次 / {m2['total_energy_kwh']:.2f} kWh "
          f"/ {m2['makespan_h']:.2f} h / 准时 {m2['on_time_rate']:.1%} "
          f"/ 违规 {m2['n_verifier_violations']}")
    print(f"  Q3: 运输 {m3['n_transport_sorties']} / 中继 {m3['n_relay_sorties']} "
          f"/ 覆盖 {m3['n_sorties_covered']}-{m3['n_sorties_need_relay']} "
          f"/ 能耗 {m3['total_energy_kwh']:.2f} / 完工 {m3['joint_makespan_h']:.2f} h "
          f"/ 中断占比 {m3['mean_direct_outage_fraction']:.1%}")
    print(f"  Q4: 分量 {m4['n_atomic_units']} / 桥接 {m4['n_bridge_sorties']} "
          f"/ K2 可行 {m4['partition_feasible_k2']} / K3 可行 {m4['partition_feasible_k3']}")

    # 一致性断言
    print("\n=== 一致性检查 ===")
    checks = [
        ("Q3 运输架次数 == Q2 架次数",
         m3["n_transport_sorties"] == m2["n_sorties"]),
        ("Q3 运输能耗 == Q2 总能耗",
         abs(m3["transport_energy_kwh"] - m2["total_energy_kwh"]) < 1e-6),
        ("论文出现 Q2 的实际架次数",
         f"{m2['n_sorties']} 架次" in text or f"{m2['n_sorties']} 个运输架次" in text),
        ("论文未出现过期架次数 22",
         "22 架次" not in text),
        ("论文出现 Q3 总能耗 99.68",
         "99.68" in text),
        ("论文未出现过期中断占比 31.3%",
         "31.3%" not in text),
    ]
    ok = True
    for name, good in checks:
        print(f"  {'✅' if good else '❌'} {name}")
        ok &= good
    print("\n" + ("✅ 论文数字与 metrics 一致" if ok else "❌ 存在不一致，需重新生成论文"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
