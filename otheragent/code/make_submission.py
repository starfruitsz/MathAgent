# -*- coding: utf-8 -*-
"""按赛题《结果提交模板.xlsx》生成 6 个交付 sheet。

sheet 与列序严格对齐附件模板：
  Q1_单点组批 / Q2_运输架次 / Q2_逐箱交付 / Q3_中继架次 / Q3_通信保障 / Q4_分区配置
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
TAB = ROOT / "tables"
OUT = ROOT / "results"
OUT.mkdir(exist_ok=True)


def main() -> None:
    g = pd.read_csv(TAB / "t_q1_groups.csv")
    q1 = pd.DataFrame({
        "架次编号": g["架次编号"],
        "服务区编号": g["服务区编号"],
        "机型编号": g["机型编号"],
        "货箱编号列表": g["货箱编号列表"],
        "总质量（kg）": g["总质量（kg）"],
        "总体积（m³）": g["总体积（m³）"],
        "往返时间（s）": g["往返时间（s）"],
        "架次能耗（kWh）": g["架次能耗（kWh）"],
        "返航SOC（%）": g["返航SOC（%）"],
    })

    s2 = pd.read_csv(TAB / "t_q2_sorties.csv")
    q2_sorties = pd.DataFrame({
        "架次编号": s2["架次编号"],
        "无人机编号": s2["无人机编号"],
        "机型编号": s2["机型编号"],
        "电池编号": s2["电池编号"],
        "开始时刻（s）": s2["开始时刻（s）"],
        "访问服务区顺序": s2["访问服务区顺序"],
        "返回O01时刻（s）": s2["返回O01时刻（s）"],
        "架次能耗（kWh）": s2["架次能耗（kWh）"],
    })

    t2 = pd.read_csv(TAB / "t_q2_timeliness.csv")
    q2_boxes = pd.DataFrame({
        "货箱编号": t2["货箱编号"],
        "架次编号": t2["架次"],
        "服务区编号": t2["服务区"],
        "交付完成时刻（s）": t2["实际交付（s）"],
    }).sort_values("货箱编号")

    r3 = pd.read_csv(TAB / "t_q3_relay_sorties.csv")
    q3_relay = pd.DataFrame({
        "中继架次编号": r3["中继架次编号"],
        "中继无人机编号": r3["中继无人机编号"],
        "能源组件编号": r3["能源组件编号"],
        "开始时刻（s）": r3["开始时刻（s）"],
        "悬停经度（°）": r3["悬停经度（°）"],
        "悬停纬度（°）": r3["悬停纬度（°）"],
        "悬停海拔（m）": r3["悬停海拔（m）"],
        "建链完成时刻（s）": r3["建链完成时刻（s）"],
        "服务结束时刻（s）": r3["服务结束时刻（s）"],
        "返回O01时刻（s）": r3["返回O01时刻（s）"],
        "架次能耗（kWh）": r3["架次能耗（kWh）"],
    })

    c3 = pd.read_csv(TAB / "q3_通信保障.csv")
    q3_comm = pd.DataFrame({
        "运输架次编号": c3["运输架次编号"],
        "通信阶段": c3["通信阶段"],
        "开始时刻（s）": c3["开始时刻（s）"],
        "结束时刻（s）": c3["结束时刻（s）"],
        "保障方式": c3["保障方式"],
        "中继架次编号": c3["中继架次编号"],
    })

    p4 = pd.read_csv(TAB / "q4_分区配置.csv")
    q4 = pd.DataFrame({
        "K（2或3）": p4["K（2或3）"],
        "任务组编号": p4["任务组编号"],
        "服务区列表": p4["服务区列表"],
        "A型运输无人机数": p4["A型运输无人机数"],
        "B型运输无人机数": p4["B型运输无人机数"],
        "C型运输无人机数": p4["C型运输无人机数"],
        "A型电池组数": p4["A型电池组数"],
        "B型电池组数": p4["B型电池组数"],
        "C型电池组数": p4["C型电池组数"],
        "中继无人机数": p4["中继无人机数"],
        "中继能源组件数": p4["中继能源组件数"],
    })

    sheets = {
        "Q1_单点组批": q1,
        "Q2_运输架次": q2_sorties,
        "Q2_逐箱交付": q2_boxes,
        "Q3_中继架次": q3_relay,
        "Q3_通信保障": q3_comm,
        "Q4_分区配置": q4,
    }

    xlsx = OUT / "结果提交文件.xlsx"
    with pd.ExcelWriter(xlsx, engine="openpyxl") as w:
        for name, df in sheets.items():
            df.to_excel(w, sheet_name=name, index=False)
            ws = w.sheets[name]
            for i, col in enumerate(df.columns, start=1):
                width = max(len(str(col)) * 2, *(len(str(v)) for v in df[col].head(40)))
                ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(
                    max(width + 2, 10), 60)
            ws.freeze_panes = "A2"

    for name, df in sheets.items():
        df.to_csv(OUT / f"{name}.csv", index=False, encoding="utf-8-sig")

    print(f"✓ {xlsx.name}")
    for name, df in sheets.items():
        print(f"   {name:12s} {df.shape[0]:3d} 行 × {df.shape[1]} 列")


if __name__ == "__main__":
    main()
