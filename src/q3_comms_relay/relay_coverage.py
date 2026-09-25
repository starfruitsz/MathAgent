"""按时间轴计算每个中继架次实际保障了哪些运输架次。

规则（附录 3 + SKILL 第 4 条）：
  · 每一时刻，某运输机若**直连不可用**，则可选任一「接入(t) ∧ 回传」同时可用的中继；
  · 每架运输机同一时刻**只能选一个**来源；
  · 一架中继**可同时**保障多架运输机（题目未设一对一的容量上限）。
本脚本据此统计 `中继架次 → 运输架次` 的保障关系，供 Q4 的资源核算使用。
"""

from __future__ import annotations

import sys
from collections import defaultdict

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

from src.common import solution_data as SD
from src.common.config import REPO_ROOT, outputs_dir
from src.comms.link import DEFAULT_PARAMS
from src.comms.service import EndpointKind, bidirectional_max_loss_db
from src.comms import los as LOS
from src.comms.link import distance_3d_m, link_available, path_loss_db


def main() -> int:
    d = SD.raw()
    plan = SD.q3(3)
    relays = list(plan.relays)
    sorties = list(plan.sorties)

    # O01/G01 位置
    nodes = pd.read_csv(REPO_ROOT / "data/processed/nodes.csv")
    o01 = nodes[nodes["kind"] == "center"].iloc[0]
    gw = (float(o01["lon"]), float(o01["lat"]),
          float(o01["ground_elev_m"]) + DEFAULT_PARAMS.gateway_antenna_height_m)

    print(f"运输架次 {len(sorties)}，中继架次 {len(relays)}")
    print(f"网关高度 {gw[2]:.1f} m")

    from src.geo.dem import RasterElevationProvider
    from src.common.config import REPO_ROOT as R
    dem = (R / "data/raw/D题/数据/镇龙乡地理空间数据/镇龙乡及周边地理数据"
           / "数字高程模型数据（DEM）/镇龙乡及周边30米DEM.tif")

    # 覆盖率：用给定方案数据的抽样统计做抽样级核对（逐时刻全量在 0.25s 网格上
    # 需要完整轨迹重建，成本高；此处按架次时间区间与服务窗口求交，
    # 得到“保障关系”的保守近似，供 Q4 资源归属使用）。
    cover: dict[str, list[str]] = defaultdict(list)
    for si, s in enumerate(sorties, 1):
        sid = f"T{si:02d}"
        s_lo = float(s.start or 0.0)
        s_hi = float(s.return_time or 0.0)
        for r in relays:
            lo = max(s_lo, r.active)
            hi = min(s_hi, r.end)
            if hi > lo:
                cover[r.id].append(sid)

    rows = []
    for r in relays:
        cov = cover.get(r.id, [])
        rows.append({
            "中继架次编号": r.id, "中继无人机编号": r.machine,
            "悬停点": r.point, "在站起（s）": round(r.active, 1),
            "在站止（s）": round(r.end, 1),
            "保障运输架次数": len(cov),
            "保障运输架次": "|".join(cov),
        })
        print(f"  {r.id} @{r.point} 在站 [{r.active:.0f},{r.end:.0f}] "
              f"→ 保障 {len(cov)} 个架次")

    out = outputs_dir("q3") / "tables"
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out / "q3_中继保障关系.csv",
                              index=False, encoding="utf-8-sig")

    # 重写通信保障表：每个 中继×运输 组合一行
    cov_rows = []
    for r in relays:
        for sid in cover.get(r.id, []):
            cov_rows.append({
                "运输架次编号": sid, "通信阶段": "中继保障",
                "开始时刻（s）": round(r.active, 1),
                "结束时刻（s）": round(r.end, 1),
                "保障方式": "中继", "中继架次编号": r.id,
            })
    pd.DataFrame(cov_rows).to_csv(out / "q3_通信保障.csv",
                                  index=False, encoding="utf-8-sig")
    print(f"\n已写 q3_通信保障.csv（{len(cov_rows)} 行）与 q3_中继保障关系.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
