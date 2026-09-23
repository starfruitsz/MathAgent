"""P0c 冒烟验证：用**真实 DEM** 检查直连通信是否被地形遮挡。

目的：在写 Q3 求解器之前先回答一个决定性问题 ——
    **在镇龙乡的真实地形下，运输无人机飞往各服务区时，直连 G01 是否会中断？**
    （若完全不中断，则 Q3 的中继无人机无必要，题目就失去意义；
      若普遍中断，则中继位置规划是 Q3 的核心。）

方法：对每个服务区，沿 O01→S_i 的水平直线按固定距离步长采样，
在每个采样点把通信端点放在**该处的巡航海拔**上，判定直连与三态。

用法：
    python scripts/smoke_comms_real_data.py
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.comms.link import (  # noqa: E402
    DEFAULT_PARAMS,
    EndpointKind,
    bidirectional_max_loss_db,
    distance_3d_m,
    path_loss_db,
)
from src.comms.los import has_terrain_obstruction  # noqa: E402
from src.comms.service import (  # noqa: E402
    CommState,
    ServiceContext,
    comm_status,
)
from src.common.config import CRUISE_CLEARANCE_M, SERVICE_AREA_OP_HEIGHT_M  # noqa: E402
from src.geo.dem import RasterElevationProvider  # noqa: E402
from src.geo.leg import Node, cruise_altitude  # noqa: E402

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

STEP_M = 250.0
"""通信判定的采样步长（m）—— 比 DEM 分辨率粗，用于快速扫描。"""


def load_nodes() -> list[Node]:
    d = pd.read_excel(BASE / "调度中心与服务区.xlsx", header=None)
    o = d.iloc[2]
    nodes = [Node(str(o[0]), float(o[2]), float(o[3]), "center", float(o[4]))]
    for i in range(6, 21):
        r = d.iloc[i]
        nodes.append(Node(str(r[0]), float(r[2]), float(r[3]), "service", float(r[4])))
    return nodes


def sample_leg_status(
    prov: RasterElevationProvider, a: Node, b: Node, gateway_alt: float
) -> dict:
    """沿 a→b 航段采样判定直连通信状态。"""
    from src.geo.crs import make_local_plane

    plane = make_local_plane(center=((a.lon + b.lon) / 2, (a.lat + b.lat) / 2))
    x1, y1 = plane.to_xy(a.lon, a.lat)
    x2, y2 = plane.to_xy(b.lon, b.lat)
    import math

    length = math.hypot(x2 - x1, y2 - y1)
    n = max(1, int(math.ceil(length / STEP_M)))

    h_cruise, z_max = cruise_altitude(prov, a.lon, a.lat, b.lon, b.lat, sample_step_m=30.0)

    states: list[str] = []
    n_obstructed = 0
    for i in range(n + 1):
        frac = i / n
        lon = a.lon + (b.lon - a.lon) * frac
        lat = a.lat + (b.lat - a.lat) * frac
        # 采样点在巡航段上 → 用巡航海拔
        ctx = ServiceContext(
            uav_lon=lon,
            uav_lat=lat,
            uav_alt_m=h_cruise,
            gateway_lon=a.lon,
            gateway_lat=a.lat,
            gateway_alt_m=gateway_alt,
            relay=None,
        )
        d = distance_3d_m(lon, lat, h_cruise, a.lon, a.lat, gateway_alt)
        obs = has_terrain_obstruction(
            prov, lon, lat, h_cruise, a.lon, a.lat, gateway_alt, sample_step_m=30.0
        )
        n_obstructed += int(obs)
        loss = path_loss_db(DEFAULT_PARAMS, d, obs)
        ok = loss <= bidirectional_max_loss_db(
            DEFAULT_PARAMS, EndpointKind.TRANSPORT, EndpointKind.GATEWAY
        )
        states.append(CommState.DIRECT.value if ok else CommState.OUTAGE.value)

    n_interrupt = sum(1 for s in states if s == CommState.OUTAGE.value)
    return {
        "航段长度_m": round(length, 1),
        "巡航海拔_m": round(h_cruise, 1),
        "航段最高地面_m": round(z_max, 1),
        "采样点数": len(states),
        "遮挡点数": n_obstructed,
        "中断点数": n_interrupt,
        "中断占比": round(n_interrupt / len(states), 4),
        "直连可行": n_interrupt == 0,
    }


def main() -> int:
    nodes = load_nodes()
    o01 = nodes[0]
    services = nodes[1:]
    prov = RasterElevationProvider(DEM)

    gateway_alt = o01.ground_elev_m + DEFAULT_PARAMS.gateway_antenna_height_m
    print("=" * 84)
    print("P0c 冒烟验证：真实地形下 O01 → 各服务区 的直连通信可行性")
    print("=" * 84)
    print(f"网关通信端点海拔 = O01 地面 {o01.ground_elev_m} m + 天线 {DEFAULT_PARAMS.gateway_antenna_height_m} m = {gateway_alt} m")
    print(f"巡航海拔 = 航段最高地面 + {CRUISE_CLEARANCE_M} m")
    print(f"判定步长 = {STEP_M} m；直连门限 = {bidirectional_max_loss_db(DEFAULT_PARAMS, EndpointKind.TRANSPORT, EndpointKind.GATEWAY)} dB")
    print()

    rows = []
    for s in services:
        rec = {"服务区": s.id}
        rec.update(sample_leg_status(prov, o01, s, gateway_alt))
        rows.append(rec)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "q3_direct_link_feasibility.csv", index=False, encoding="utf-8-sig")

    print(df.to_string(index=False))
    print()
    n_ok = int(df["直连可行"].sum())
    print("--- 统计 ---")
    print(f"O01 → 服务区 共 {len(df)} 条航段")
    print(f"直连全程可行: {n_ok} 条")
    print(f"直连出现中断: {len(df) - n_ok} 条")
    print(f"出现遮挡的航段: {int((df['遮挡点数'] > 0).sum())} 条")
    print(f"平均中断占比: {df['中断占比'].mean():.3%}")
    print()
    if n_ok == len(df):
        print("→ 结论：真实地形下直连全程可行，**中继无人机在本场景可能无必要**。")
        print("  需复核：判定步长、巡航海拔口径、以及投送段（降至 30 m 作业高度）是否适用。")
    else:
        print("→ 结论：存在直连中断的航段，**中继位置规划是 Q3 的核心问题**。")
    print()
    print(f"结果已写入 {OUT.relative_to(REPO)}/q3_direct_link_feasibility.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
