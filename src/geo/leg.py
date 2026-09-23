"""航段几何（题目附录 2 的**唯一实现**，铁律 R4）。

把 (起点节点, 终点节点, 高程提供者) 变成物理层需要的 `Segment`：

    巡航海拔 H_cruise(i,j) = max{ DEM(p) : p 在 i→j 水平直线段上 } + 50 m
    作业高度 H_op(O01)  = 地面海拔
    作业高度 H_op(S_i)  = 地面海拔 + 30 m
    d_ij = 水平距离（投影平面，m）
    h⁺_ij = H_cruise − H_op(i)
    h⁻_ij = H_cruise − H_op(j)

★ 本模块**不直接读 DEM**，只通过 `ElevationProvider` 协议拿高程 ——
   这是分层解耦的关键，使几何层可以用解析高程做单元测试。

★ 注意：H_cruise 可能**低于**某个端点的作业高度（例如终点在山顶、
   起点在谷底时，航段最高点 + 50 m 仍可能低于终点作业高度）。
   此时爬升/下降高度按定义仍为 H_cruise − H_op，可能为负。
   本题按题目原文实现，并把这种情况显式标记出来（`Segment.clamp_note`）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from src.common.config import (
    CRUISE_CLEARANCE_M,
    DEM_RESOLUTION_M,
    SERVICE_AREA_OP_HEIGHT_M,
)
from src.geo.crs import LocalPlane, horizontal_distance_m, make_local_plane
from src.geo.dem import ElevationProvider, OutOfBoundsError, max_elevation_along_line

NodeKind = Literal["center", "service"]


@dataclass(frozen=True)
class Node:
    """任务节点（调度中心或服务区）。"""

    id: str
    lon: float
    lat: float
    kind: NodeKind
    ground_elev_m: float | None = None
    """附件给出的地面海拔；None 时由 DEM 采样得到。"""

    @property
    def op_height_offset_m(self) -> float:
        """作业高度相对地面海拔的偏移量（m）。

        O01 = 0（取其地面海拔）；服务区 = +30 m。
        """
        return 0.0 if self.kind == "center" else SERVICE_AREA_OP_HEIGHT_M


@dataclass(frozen=True)
class LegGeometry:
    """航段几何量：直接喂给 `physics.energy.Segment`。"""

    from_id: str
    to_id: str
    distance_m: float
    """水平巡航距离 d_ij（m）。"""
    cruise_alt_m: float
    """巡航海拔 H_cruise（m，绝对高程）。"""
    op_from_m: float
    """起点作业高度（m，绝对高程）。"""
    op_to_m: float
    """终点作业高度（m，绝对高程）。"""
    climb_m: float
    """爬升高度 h⁺_ij = H_cruise − H_op(from)（m，可能为 0）。"""
    descent_m: float
    """下降高度 h⁻_ij = H_cruise − H_op(to)（m，可能为 0）。"""
    max_ground_elev_m: float
    """航段经过的最高地面高程（m）。"""
    sampling_step_m: float
    """沿线采样步长（m），用于可追溯性。"""
    note: str = ""
    """实现说明（如"巡航海拔低于起点作业高度，已按 0 处理"）。"""

    def as_segment(self) -> object:
        """转换为 `physics.energy.Segment`（延迟导入避免循环依赖）。"""
        from src.physics.energy import Segment

        return Segment(
            distance_m=self.distance_m, climb_m=self.climb_m, descent_m=self.descent_m
        )


def node_ground_elevation(provider: ElevationProvider, node: Node) -> float:
    """节点地面海拔：优先用附件给定值，缺失时向 DEM 索取。"""
    if node.ground_elev_m is not None:
        return float(node.ground_elev_m)
    return provider.elevation_at(node.lon, node.lat)


def node_op_height(provider: ElevationProvider, node: Node) -> float:
    """节点作业高度（m，绝对高程）。"""
    return node_ground_elevation(provider, node) + node.op_height_offset_m


def cruise_altitude(
    provider: ElevationProvider,
    lon1: float,
    lat1: float,
    lon2: float,
    lat2: float,
    sample_step_m: float = DEM_RESOLUTION_M,
    clearance_m: float = CRUISE_CLEARANCE_M,
) -> tuple[float, float]:
    """返回 (巡航海拔, 航段最高地面高程)，单位 m。

    巡航海拔 = 航段所经过 DEM 像元的最高地面高程 + 50 m（题目附录 2）。
    """
    z_max = max_elevation_along_line(
        provider, lon1, lat1, lon2, lat2, sample_step_m=sample_step_m
    )
    return z_max + clearance_m, z_max


def leg_geometry(
    provider: ElevationProvider,
    a: Node,
    b: Node,
    plane: LocalPlane | None = None,
    sample_step_m: float = DEM_RESOLUTION_M,
    clamp_negative: bool = True,
) -> LegGeometry:
    """计算航段 a → b 的完整几何量。

    参数
    ----
    plane : 局部切平面；None 时按两点中点自动构造
    sample_step_m : 沿线采样步长（m）
    clamp_negative : 若 H_cruise 低于端点作业高度，是否把爬升/下降截断到 0

    关于 `clamp_negative`
    --------------------
    题目定义 h⁺ = H_cruise − H_op(from)。当航段最高点 + 50 m 仍低于起点作业
    高度时该值为负。物理上负爬升没有意义（等价于"下降"），因此默认截断为 0
    并记录 `note` 以便追溯。
    **但严格照题面则不应截断** —— 两种口径都已实现，
    调用方通过 `clamp_negative` 显式选择，并在论文中说明。
    """
    if plane is None:
        plane = make_local_plane(center=((a.lon + b.lon) / 2, (a.lat + b.lat) / 2))

    d = horizontal_distance_m(a.lon, a.lat, b.lon, b.lat, plane)
    h_cruise, z_max = cruise_altitude(
        provider, a.lon, a.lat, b.lon, b.lat, sample_step_m=sample_step_m
    )
    op_a = node_op_height(provider, a)
    op_b = node_op_height(provider, b)

    climb = h_cruise - op_a
    descent = h_cruise - op_b
    notes: list[str] = []
    if clamp_negative:
        if climb < 0:
            notes.append(f"巡航海拔低于起点作业高度 {abs(climb):.2f} m，爬升按 0 处理")
            climb = 0.0
        if descent < 0:
            notes.append(f"巡航海拔低于终点作业高度 {abs(descent):.2f} m，下降按 0 处理")
            descent = 0.0

    return LegGeometry(
        from_id=a.id,
        to_id=b.id,
        distance_m=d,
        cruise_alt_m=h_cruise,
        op_from_m=op_a,
        op_to_m=op_b,
        climb_m=climb,
        descent_m=descent,
        max_ground_elev_m=z_max,
        sampling_step_m=sample_step_m,
        note="；".join(notes),
    )


def leg_geometry_pair(
    provider: ElevationProvider,
    a: Node,
    b: Node,
    plane: LocalPlane | None = None,
    sample_step_m: float = DEM_RESOLUTION_M,
    clamp_negative: bool = True,
) -> tuple[LegGeometry, LegGeometry]:
    """同时给出 a→b 与 b→a 两个航段。

    ★ 注意两者**不等价**：
      - 水平距离相同
      - H_cruise 相同（都是同一段直线的最高点 + 50 m）
      - 但爬升/下降高度互换，因此**时间与能耗不同**
    单点往返任务的能耗必须分别计算去程与回程。
    """
    return (
        leg_geometry(provider, a, b, plane, sample_step_m, clamp_negative),
        leg_geometry(provider, b, a, plane, sample_step_m, clamp_negative),
    )
