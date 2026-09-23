"""P0b 冒烟验证：用**真实附件数据**跑通地理层 + 物理层。

目的：在写 Q1 求解器之前，先确认物理量在真实场景下是合理的
（距离量级、巡航海拔、最大安全载荷、往返能耗、是否可行）。

用法：
    python scripts/smoke_physics_real_data.py

输出：
    outputs/p0_smoke/*.csv  与 控制台摘要
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.geo.dem import RasterElevationProvider  # noqa: E402
from src.geo.leg import Node, leg_geometry_pair  # noqa: E402
from src.physics.energy import segment_time_s, sortie_energy_kwh  # noqa: E402
from src.physics.payload import UAVType, max_safe_payload  # noqa: E402

RAW = REPO / "data" / "raw" / "D题"
BASE = RAW / "数据" / "无人机应急物资运输基础数据"
DEM = (
    RAW
    / "数据/镇龙乡地理空间数据/镇龙乡及周边地理数据"
    / "数字高程模型数据（DEM）/镇龙乡及周边30米DEM.tif"
)
OUT = REPO / "outputs" / "p0_smoke"
OUT.mkdir(parents=True, exist_ok=True)

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]


def load_nodes() -> list[Node]:
    """按 DATA_NOTES 记录的**分段表**结构解析节点（O01 在第 2 行，S001–S015 在第 6–20 行）。"""
    d = pd.read_excel(BASE / "调度中心与服务区.xlsx", header=None)
    nodes: list[Node] = []
    o = d.iloc[2]
    nodes.append(
        Node(str(o[0]), float(o[2]), float(o[3]), "center", ground_elev_m=float(o[4]))
    )
    for i in range(6, 21):
        r = d.iloc[i]
        nodes.append(
            Node(str(r[0]), float(r[2]), float(r[3]), "service", ground_elev_m=float(r[4]))
        )
    return nodes


def load_uav_types() -> list[UAVType]:
    """按附件表结构解析三种机型（机型行 2–4）。"""
    d = pd.read_excel(BASE / "运输无人机数据.xlsx", header=None)
    fleet: list[UAVType] = []
    for i in (2, 3, 4):
        r = d.iloc[i]
        fleet.append(
            UAVType(
                code=str(r[0]),
                name=str(r[1]),
                empty_mass_kg=float(r[2]),
                max_payload_kg=float(r[3]),
                volume_m3=float(r[4]),
                cruise_speed_ms=float(r[5]),
                range_empty_m=float(r[6]),
                range_full_m=float(r[7]),
                energy_kwh=float(r[8]),
                reserve_ratio=float(r[9]) / 100.0,
                prepare_time_s=float(r[10]),
                box_load_time_s=float(r[11]),
                handover_base_s=float(r[12]),
                handover_per_box_s=float(r[13]),
                climb_speed_ms=float(r[14]),
                descent_speed_ms=float(r[15]),
                climb_efficiency=float(r[16]),
                descent_efficiency=float(r[17]),
            )
        )
    return fleet


def main() -> int:
    nodes = load_nodes()
    fleet = load_uav_types()
    o01 = nodes[0]
    services = nodes[1:]

    print("=" * 78)
    print("P0b 冒烟验证：真实数据 + 地理层 + 物理层")
    print("=" * 78)
    print(f"调度中心 {o01.id}  海拔 {o01.ground_elev_m} m")
    print(f"服务区   {len(services)} 个")
    for u in fleet:
        print(
            f"机型 {u.code}: Q_g={u.max_payload_kg} kg, 体积={u.volume_m3} m³, "
            f"L0={u.range_empty_m:.0f} m, LF={u.range_full_m:.0f} m, "
            f"E={u.energy_kwh} kWh, 预算={u.energy_budget_kwh:.2f} kWh"
        )
    print()

    prov = RasterElevationProvider(DEM)
    print(f"DEM: EPSG={prov.epsg} bounds={tuple(round(v,4) for v in prov.bounds)}")

    # 单点往返：O01 → S_i → O01
    rows = []
    for s in services:
        out, back = leg_geometry_pair(prov, o01, s, sample_step_m=30.0)
        assert abs(out.distance_m - back.distance_m) < 1e-6, "往返水平距离应相同"
        rec = {
            "服务区": s.id,
            "地面海拔_m": s.ground_elev_m,
            "单向距离_m": round(out.distance_m, 1),
            "航段最高地面_m": round(out.max_ground_elev_m, 1),
            "巡航海拔_m": round(out.cruise_alt_m, 1),
            "去程爬升_m": round(out.climb_m, 1),
            "去程下降_m": round(out.descent_m, 1),
            "去程时间_s": round(segment_time_s(fleet[0], out.as_segment()), 1),
        }
        for u in fleet:
            try:
                q = max_safe_payload(
                    u,
                    horizontal_distance_m=out.distance_m,
                    climb_out_m=out.climb_m,
                    descent_out_m=out.descent_m,
                    climb_back_m=back.climb_m,
                    descent_back_m=back.descent_m,
                )
                energy_full = sortie_energy_kwh(
                    u, outbound=(out.as_segment(), q), inbound=(back.as_segment(), 0.0)
                )
                rec[f"{u.code}_q_max_kg"] = round(q, 2)
                rec[f"{u.code}_能耗_kWh"] = round(energy_full, 3)
                rec[f"{u.code}_往返时间_s"] = round(
                    segment_time_s(u, out.as_segment())
                    + segment_time_s(u, back.as_segment()),
                    1,
                )
            except ValueError:
                rec[f"{u.code}_q_max_kg"] = None
                rec[f"{u.code}_能耗_kWh"] = None
                rec[f"{u.code}_往返时间_s"] = None
        rows.append(rec)

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "q1_single_roundtrip.csv", index=False, encoding="utf-8-sig")

    print()
    print("--- 单点往返：距离与巡航海拔 ---")
    print(
        df[["服务区", "单向距离_m", "航段最高地面_m", "巡航海拔_m", "去程爬升_m"]]
        .to_string(index=False)
    )
    print()
    print("--- 单点往返：三种机型最大安全载荷 (kg) / 满往返能耗 (kWh) ---")
    show = df[["服务区", "单向距离_m"]].copy()
    for u in fleet:
        show[f"{u.code} 载荷"] = df[f"{u.code}_q_max_kg"]
        show[f"{u.code} 能耗"] = df[f"{u.code}_能耗_kWh"]
    print(show.to_string(index=False))

    print()
    print("--- 统计 ---")
    print(f"单向距离范围: {df['单向距离_m'].min():.0f} ~ {df['单向距离_m'].max():.0f} m")
    print(f"巡航海拔范围: {df['巡航海拔_m'].min():.0f} ~ {df['巡航海拔_m'].max():.0f} m")
    for u in fleet:
        col = df[f"{u.code}_q_max_kg"]
        n_struct = int((col >= u.max_payload_kg - 1e-9).sum())
        n_none = int(col.isna().sum())
        print(
            f"机型 {u.code}: 受结构上限(Q_g)约束 {n_struct}/15 个服务区, "
            f"不可行 {n_none} 个, 载荷中位数 {col.median():.2f} kg"
        )
    print()
    print(f"结果已写入 {OUT.relative_to(REPO)}/q1_single_roundtrip.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
