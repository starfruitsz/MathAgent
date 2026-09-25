"""Q3 中继"在站时刻"与"需要保障的时间窗"是否真的重叠？

发现的问题
----------
`run_q3.py` 的中继资源调度只按"最早可用资源"排班：
    start = max(uav_avail[ru], pack_avail[pk], 0.0)
**没有把服务窗口 win 纳入约束**；而 `evaluate_relay_sortie` 里
    svc_start = max(link_ready, window[0]);  svc_end = max(svc_start, window[1])
于是中继晚到时只会把服务区间**截短**（甚至截成 0 长度），
**不会**被判为"未覆盖"。结果可能把"中继在运输机返航之后才到场"的架次
也算成已保障。

本脚本按时间轴算真实重叠率，输出"声称覆盖 vs 实际覆盖"的差集。

用法：python scripts/diag/q3_relay_window_audit.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]


def main() -> int:
    sit = pd.read_csv("outputs/q3/tables/q3_中继选址.csv")
    rel = pd.read_csv("outputs/q3/tables/q3_中继架次.csv")
    com = pd.read_csv("outputs/q3/tables/q3_通信保障.csv")
    # 运输架次 → 中继架次 的映射在通信保障表里（中继架次编号形如 RT01，
    # 并不包含运输架次号，不能直接字符串匹配）
    m = (com.dropna(subset=["中继架次编号"])
            .groupby("运输架次编号")["中继架次编号"].first().to_dict())
    rel_by_id = rel.set_index("中继架次编号")
    rows = []
    for _, s in sit.iterrows():
        sid = s["架次编号"]
        need_a, need_b = float(s["服务窗口起"]), float(s["服务窗口止"])
        need = max(need_b - need_a, 1e-9)
        rid = m.get(sid)
        if rid is None or rid not in rel_by_id.index:
            rows.append({"架次": sid, "需要起": need_a, "需要止": need_b,
                         "中继架次": rid, "在站起": None, "在站止": None,
                         "重叠s": 0.0, "需要s": round(need, 1), "重叠率": 0.0})
            continue
        r = rel_by_id.loc[rid]
        got_a, got_b = float(r["建链完成时刻（s）"]), float(r["服务结束时刻（s）"])
        ov = max(0.0, min(need_b, got_b) - max(need_a, got_a))
        rows.append({"架次": sid, "需要起": need_a, "需要止": need_b,
                     "中继架次": rid, "在站起": got_a, "在站止": got_b,
                     "重叠s": round(ov, 1), "需要s": round(need, 1),
                     "重叠率": round(ov / need, 4)})
    df = pd.DataFrame(rows)
    print(df.to_string(index=False))
    full = int((df["重叠率"] >= 0.999).sum())
    zero = int((df["重叠率"] <= 1e-9).sum())
    print(f"\n需要保障架次 {len(df)} 个：完全重叠 {full} 个，"
          f"**零重叠 {zero} 个**，部分重叠 {len(df)-full-zero} 个")
    print(f"平均重叠率 {df['重叠率'].mean():.1%}")
    Path("outputs/diag").mkdir(parents=True, exist_ok=True)
    df.to_csv("outputs/diag/q3_relay_window_audit.csv", index=False, encoding="utf-8-sig")
    print("已写入 outputs/diag/q3_relay_window_audit.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
