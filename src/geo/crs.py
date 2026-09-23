"""坐标换算与水平距离（★ ADR-011：经纬度 → 米制投影的**唯一入口**）。

为什么要单独一层：
    附件坐标与 DEM 都是 **WGS84 经纬度（EPSG:4326）**。
    直接用经纬度算欧氏距离是**错的**（1° 经度 ≈ 102 km，1° 纬度 ≈ 111 km，
    在高纬度差异更大）。因此所有水平距离必须先把经纬度投影到米制平面。

本模块提供两条路径：
    1. **局部切平面（默认）**：以参考纬度为基准的等距圆柱近似。
       在题目场景范围（约 12 km × 8 km）内相对误差 ~1e-5，且**无需 PROJ 数据、
       无投影往返开销、结果稳定可复现**。
    2. **pyproj 精确投影**：需要更高精度或跨区域时使用。

两种实现都必须通过 `tests/test_geo.py` 的一致性检验（差异 < 0.1%）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# WGS84 椭球参数
WGS84_A = 6378137.0
"""WGS84 长半轴（m）。"""
WGS84_F = 1.0 / 298.257223563
"""WGS84 扁率。"""
WGS84_E2 = WGS84_F * (2 - WGS84_F)
"""第一偏心率平方。"""

METERS_PER_DEG_LAT = 111132.92
"""纬度 1° 对应的米数（近似，随纬度略有变化）。"""


@dataclass(frozen=True)
class LocalPlane:
    """以参考点为原点的局部切平面（等距圆柱近似）。

    投影公式：
        x = (lon − lon0) · cos(lat0) · R · π/180
        y = (lat − lat0) · R · π/180
    其中 R 取参考纬度处的**子午圈曲率半径**，比直接用赤道半径更准。
    """

    lon0: float
    lat0: float

    @property
    def _m_per_deg_lat(self) -> float:
        """该纬度处 1° 纬度对应的米数（子午圈曲率半径 × π/180）。"""
        s = math.sin(math.radians(self.lat0))
        denom = 1.0 - WGS84_E2 * s * s
        meridional = WGS84_A * (1 - WGS84_E2) / (denom**1.5)
        return meridional * math.pi / 180.0

    @property
    def _m_per_deg_lon(self) -> float:
        """该纬度处 1° 经度对应的米数（卯酉圈曲率半径 × cosφ × π/180）。"""
        s = math.sin(math.radians(self.lat0))
        denom = 1.0 - WGS84_E2 * s * s
        normal = WGS84_A / math.sqrt(denom)
        return normal * math.cos(math.radians(self.lat0)) * math.pi / 180.0

    def to_xy(self, lon: float, lat: float) -> tuple[float, float]:
        """经纬度 → 局部平面坐标（m）。"""
        return (
            (lon - self.lon0) * self._m_per_deg_lon,
            (lat - self.lat0) * self._m_per_deg_lat,
        )

    def to_lonlat(self, x: float, y: float) -> tuple[float, float]:
        """局部平面坐标（m）→ 经纬度。"""
        return (
            self.lon0 + x / self._m_per_deg_lon,
            self.lat0 + y / self._m_per_deg_lat,
        )


def make_local_plane(points: list[tuple[float, float]] | None = None,
                     center: tuple[float, float] | None = None) -> LocalPlane:
    """构造局部切平面。

    参数
    ----
     points : [(lon, lat), ...] —— 自动取形心为参考点（推荐）
     center : (lon, lat) —— 显式指定参考点

    若两者都不给，以题目场景（镇龙乡）的近似中心为默认值。
    """
    if center is not None:
        return LocalPlane(lon0=center[0], lat0=center[1])
    if points:
        lon0 = sum(p[0] for p in points) / len(points)
        lat0 = sum(p[1] for p in points) / len(points)
        return LocalPlane(lon0=lon0, lat0=lat0)
    # 题目附件实测：16 个节点聚集区中心
    return LocalPlane(lon0=109.230852, lat0=23.008509)


def horizontal_distance_m(
    lon1: float, lat1: float, lon2: float, lat2: float, plane: LocalPlane
) -> float:
    """两点的水平距离（m），在给定局部平面上计算。"""
    x1, y1 = plane.to_xy(lon1, lat1)
    x2, y2 = plane.to_xy(lon2, lat2)
    return math.hypot(x2 - x1, y2 - y1)


def interpolate_lonlat(
    lon1: float, lat1: float, lon2: float, lat2: float, frac: float
) -> tuple[float, float]:
    """按比例 frac ∈ [0, 1] 线性插值经纬度（用于沿线采样）。"""
    return (lon1 + (lon2 - lon1) * frac, lat1 + (lat2 - lat1) * frac)


def geodesic_distance_m(
    lon1: float, lat1: float, lon2: float, lat2: float
) -> float:
    """pyproj 精确测地距离（m），用于校验局部切平面的精度。

    需要 pyproj；若不可用则抛 ImportError。
    """
    from pyproj import Geod

    geod = Geod(ellps="WGS84")
    _, _, dist = geod.inv(lon1, lat1, lon2, lat2)
    return float(dist)


def utm_epsg(lon: float, lat: float) -> int:
    """给定经纬度返回所处 UTM 带的 EPSG 代码（北半球 326xx / 南半球 327xx）。"""
    zone = int((lon + 180.0) // 6.0) + 1
    return (32600 if lat >= 0 else 32700) + zone


@dataclass(frozen=True)
class MetricsPlane:
    """基于 pyproj 的精确米制投影（备用路径）。

    用于需要跨更大范围、或需要与 GIS 软件结果严格对齐的场合。
    """

    epsg: int

    def to_xy(self, lon: float, lat: float) -> tuple[float, float]:
        from pyproj import Transformer

        tr = Transformer.from_crs(4326, self.epsg, always_xy=True)
        return tr.transform(lon, lat)

    def to_lonlat(self, x: float, y: float) -> tuple[float, float]:
        from pyproj import Transformer

        tr = Transformer.from_crs(self.epsg, 4326, always_xy=True)
        return tr.transform(x, y)
