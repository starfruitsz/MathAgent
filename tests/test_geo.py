"""地理层单元测试。

分层解耦验证点：
    - 几何层（`geo/leg.py`）**只依赖 `ElevationProvider` 协议**，
      因此绝大多数测试用 `AnalyticElevationProvider`，**不需要加载真实 DEM**
    - 少量"对照测试"才读取真实附件 DEM（`pytest.mark.realdata`）
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from src.geo.crs import (
    WGS84_A,
    LocalPlane,
    geodesic_distance_m,
    horizontal_distance_m,
    interpolate_lonlat,
    make_local_plane,
    utm_epsg,
)
from src.geo.dem import (
    AnalyticElevationProvider,
    OutOfBoundsError,
    max_elevation_along_line,
)
from src.geo.leg import (
    Node,
    cruise_altitude,
    leg_geometry,
    leg_geometry_pair,
    node_ground_elevation,
    node_op_height,
)

REAL_DEM = (
    Path(__file__).resolve().parents[1]
    / "data/raw/D题/数据/镇龙乡地理空间数据/镇龙乡及周边地理数据"
    / "数字高程模型数据（DEM）/镇龙乡及周边30米DEM.tif"
)

# 附件实测的节点坐标（docs/DATA_NOTES.md 第 2.1 节）
O01 = Node("O01", 109.230852, 23.008509, "center", ground_elev_m=127.7)
S001 = Node("S001", 109.243232, 23.033593, "service", ground_elev_m=154.0)
S015 = Node("S015", 109.192379, 23.049455, "service", ground_elev_m=444.5)


# ================================================================ CRS

def test_local_plane_roundtrip() -> None:
    plane = make_local_plane(center=(109.23, 23.01))
    for lon, lat in [(109.24, 23.02), (109.17, 23.05), (109.28, 23.00)]:
        x, y = plane.to_xy(lon, lat)
        lon2, lat2 = plane.to_lonlat(x, y)
        assert lon2 == pytest.approx(lon, abs=1e-12)
        assert lat2 == pytest.approx(lat, abs=1e-12)


def test_meters_per_degree_at_test_latitude() -> None:
    """该纬度处的精确 WGS84 换算值。

    用子午圈曲率半径 M 与卯酉圈曲率半径 N（而非赤道半径）：
        1° 纬度 = M·π/180 = 110744.0 m
        1° 经度 = N·cos(23°)·π/180 = 102522.5 m

    注意：常见的 "1° ≈ 111132.92 m" 是平均值，在 23° 处偏高约 389 m（0.35%），
    因此本实现使用曲率半径以获得更高精度。
    """
    plane = LocalPlane(lon0=109.23, lat0=23.0)
    m_lat = plane._m_per_deg_lat
    m_lon = plane._m_per_deg_lon
    assert m_lat == pytest.approx(110744.0, rel=1e-5)
    assert m_lon == pytest.approx(102522.5, rel=1e-5)
    # 经度方向的米数应显著小于纬度方向（cos23° ≈ 0.9205）
    assert m_lon < m_lat
    assert m_lon / m_lat == pytest.approx(0.9258, rel=1e-3)


def test_horizontal_distance_uses_metric_plane() -> None:
    """★ 关键回归：不能把经纬度当平面直接算欧氏距离。

    0.01° 经度与 0.01° 纬度在该纬度处的真实米数不同（约 1022 m vs 1109 m）。
    """
    plane = make_local_plane(center=(109.23, 23.01))
    d_lon = horizontal_distance_m(109.23, 23.01, 109.24, 23.01, plane)
    d_lat = horizontal_distance_m(109.23, 23.01, 109.23, 23.02, plane)
    assert d_lon == pytest.approx(1022, rel=5e-3)
    assert d_lat == pytest.approx(1109, rel=5e-3)
    assert d_lon != pytest.approx(d_lat)


def test_horizontal_distance_zero_and_symmetry() -> None:
    plane = make_local_plane(center=(109.23, 23.01))
    assert horizontal_distance_m(109.2, 23.0, 109.2, 23.0, plane) == pytest.approx(0.0)
    d_ab = horizontal_distance_m(109.2, 23.0, 109.28, 23.06, plane)
    d_ba = horizontal_distance_m(109.28, 23.06, 109.2, 23.0, plane)
    assert d_ab == pytest.approx(d_ba)


def test_local_plane_close_to_geodesic() -> None:
    """局部切平面应与 pyproj 测地距离一致（相对误差 < 0.1%）。"""
    pts = [
        (109.230852, 23.008509, 109.283597, 23.005210),
        (109.230852, 23.008509, 109.168858, 23.040271),
        (109.230852, 23.008509, 109.192379, 23.049455),  # 最远节点
    ]
    plane = make_local_plane(center=(109.230852, 23.008509))
    for lon1, lat1, lon2, lat2 in pts:
        d_local = horizontal_distance_m(lon1, lat1, lon2, lat2, plane)
        d_geod = geodesic_distance_m(lon1, lat1, lon2, lat2)
        assert d_local == pytest.approx(d_geod, rel=1e-3), (d_local, d_geod)


def test_interpolate_lonlat() -> None:
    assert interpolate_lonlat(0.0, 0.0, 10.0, 20.0, 0.0) == (0.0, 0.0)
    assert interpolate_lonlat(0.0, 0.0, 10.0, 20.0, 1.0) == (10.0, 20.0)
    assert interpolate_lonlat(0.0, 0.0, 10.0, 20.0, 0.5) == (5.0, 10.0)


def test_utm_epsg_for_study_area() -> None:
    """镇龙乡（东经 109.2°）位于 UTM 49N 带 → EPSG:32649。"""
    assert utm_epsg(109.23, 23.01) == 32649


# ================================================================ 解析高程提供者

def test_analytic_provider_elevation() -> None:
    p = AnalyticElevationProvider(base=100.0, gx=0.0, gy=0.0)
    assert p.elevation_at(109.23, 23.01) == pytest.approx(100.0)


def test_analytic_provider_raises_out_of_bounds() -> None:
    p = AnalyticElevationProvider()
    with pytest.raises(OutOfBoundsError):
        p.elevation_at(100.0, 23.0)


def test_node_elevation_uses_attachment_value_when_given() -> None:
    """节点海拔优先取附件给定值，而不是 DEM 采样值。"""
    p = AnalyticElevationProvider(base=999.0)
    assert node_ground_elevation(p, O01) == pytest.approx(127.7)


def test_node_elevation_falls_back_to_provider() -> None:
    p = AnalyticElevationProvider(base=200.0)
    n = Node("X", 109.23, 23.01, "service", ground_elev_m=None)
    assert node_ground_elevation(p, n) == pytest.approx(200.0)


# ================================================================ 作业高度

def test_op_height_center_is_ground() -> None:
    p = AnalyticElevationProvider()
    assert node_op_height(p, O01) == pytest.approx(127.7)


def test_op_height_service_is_ground_plus_30() -> None:
    """★ 附录 2：服务区作业高度 = 地面海拔 + 30 m。"""
    p = AnalyticElevationProvider()
    assert node_op_height(p, S001) == pytest.approx(154.0 + 30.0)
    assert node_op_height(p, S015) == pytest.approx(444.5 + 30.0)


# ================================================================ 巡航海拔与沿线最高点

def test_cruise_altitude_flat_terrain() -> None:
    """平地：巡航海拔 = 地面 + 50 m。"""
    p = AnalyticElevationProvider(base=100.0)
    alt, zmax = cruise_altitude(p, O01.lon, O01.lat, S001.lon, S001.lat)
    assert zmax == pytest.approx(100.0)
    assert alt == pytest.approx(150.0)


def test_max_elevation_along_line_finds_peak_not_endpoints() -> None:
    """★ 关键规则：取的是**沿线最高点**，不是两端点的最大值。

    构造一个中间高、两端低的解析地形：z = 100 + gy·(lat − lat0)，
    两端取对称位置时两端高程相同，但中间更高（若地形为凸）。
    这里用线性地形，改测"最高点在端点"与"用最密采样"两种情形。
    """
    p = AnalyticElevationProvider(base=100.0, gy=1000.0)  # 向北每度升高 1000 m
    # 从南到北的一条线：最高点应是终点（北端）
    zmax = max_elevation_along_line(p, 109.23, 23.00, 109.23, 23.05)
    assert zmax == pytest.approx(p.elevation_at(109.23, 23.05), rel=1e-9)


def test_max_elevation_detects_interior_peak() -> None:
    """中间凸起的解析地形：最高点必须被采到。"""

    class TentProvider:
        """帐篷形地形：在 (lon0, lat0) 处达到峰值。"""

        def __init__(self) -> None:
            self.lon0, self.lat0 = 109.25, 23.03
            self.peak = 600.0
            self.base = 100.0
            self._bounds = (109.0, 22.85, 109.5, 23.25)

        def elevation_at(self, lon: float, lat: float) -> float:
            d = math.hypot((lon - self.lon0) * 102000, (lat - self.lat0) * 110900)
            if d > 1000:
                return self.base
            return self.base + (self.peak - self.base) * (1 - d / 1000)

        @property
        def bounds(self):
            return self._bounds

    p = TentProvider()
    # 一条穿过峰顶的线
    zmax = max_elevation_along_line(p, 109.23, 23.03, 109.27, 23.03, sample_step_m=30)
    assert zmax == pytest.approx(600.0, rel=2e-2)
    # 端点高程都远低于峰值
    assert p.elevation_at(109.23, 23.03) < 400
    assert p.elevation_at(109.27, 23.03) < 400


def test_max_elevation_sampling_step_affects_accuracy() -> None:
    """采样步长越粗，越容易漏掉窄峰 —— 这是必须做敏感性分析的原因。"""

    class SpikeProvider:
        def __init__(self) -> None:
            self.lon0, self.lat0 = 109.25, 23.03
            self._bounds = (109.0, 22.85, 109.5, 23.25)

        def elevation_at(self, lon: float, lat: float) -> float:
            d = math.hypot((lon - self.lon0) * 102000, (lat - self.lat0) * 110900)
            return 800.0 if d < 40 else 100.0

        @property
        def bounds(self):
            return self._bounds

    p = SpikeProvider()
    fine = max_elevation_along_line(p, 109.23, 23.03, 109.27, 23.03, sample_step_m=5)
    coarse = max_elevation_along_line(p, 109.23, 23.03, 109.27, 23.03, sample_step_m=400)
    assert fine == pytest.approx(800.0)
    assert coarse == pytest.approx(100.0), "粗采样会漏掉窄峰"


def test_max_elevation_all_out_of_bounds_raises() -> None:
    p = AnalyticElevationProvider()
    with pytest.raises(OutOfBoundsError):
        max_elevation_along_line(p, 100.0, 23.0, 100.1, 23.1)


def test_max_elevation_rejects_bad_step() -> None:
    p = AnalyticElevationProvider()
    with pytest.raises(ValueError):
        max_elevation_along_line(p, 109.23, 23.0, 109.24, 23.01, sample_step_m=0.0)


# ================================================================ 航段几何

def test_leg_geometry_flat_terrain() -> None:
    """平地 + 两端作业高度不同 → 爬升/下降符合定义。"""
    p = AnalyticElevationProvider(base=200.0)
    g = leg_geometry(p, O01, S001)
    # 巡航海拔 = 200 + 50 = 250
    assert g.cruise_alt_m == pytest.approx(250.0)
    assert g.op_from_m == pytest.approx(127.7)      # O01 用附件海拔
    assert g.op_to_m == pytest.approx(154.0 + 30.0)  # 服务区 +30
    assert g.climb_m == pytest.approx(250.0 - 127.7)
    assert g.descent_m == pytest.approx(250.0 - 184.0)
    assert g.distance_m > 0


def test_leg_geometry_pair_swaps_climb_descent() -> None:
    """★ a→b 与 b→a 的爬升/下降互换，但距离与巡航海拔相同。

    这正是单点往返必须**分别**计算去程与回程能耗的原因。
    """
    p = AnalyticElevationProvider(base=200.0)
    out, back = leg_geometry_pair(p, O01, S001)
    assert out.distance_m == pytest.approx(back.distance_m)
    assert out.cruise_alt_m == pytest.approx(back.cruise_alt_m)
    assert out.climb_m == pytest.approx(back.descent_m)
    assert out.descent_m == pytest.approx(back.climb_m)


def test_leg_geometry_clamp_negative_note() -> None:
    """终点在山顶时巡航海拔可能低于终点作业高度 → 记录 note。"""
    p = AnalyticElevationProvider(base=100.0)
    high = Node("HIGH", 109.25, 23.03, "service", ground_elev_m=800.0)
    g = leg_geometry(p, O01, high, clamp_negative=True)
    assert g.descent_m >= 0.0
    assert "下降按 0 处理" in g.note


def test_leg_geometry_can_disable_clamping() -> None:
    """不截断时允许负值（严格照题面 h = H_cruise − H_op）。"""
    p = AnalyticElevationProvider(base=100.0)
    high = Node("HIGH", 109.25, 23.03, "service", ground_elev_m=800.0)
    g = leg_geometry(p, O01, high, clamp_negative=False)
    assert g.descent_m < 0.0
    assert g.note == ""


def test_leg_geometry_as_segment_is_valid() -> None:
    """as_segment 在截断模式下必须产出合法 Segment（非负）。"""
    p = AnalyticElevationProvider(base=100.0)
    high = Node("HIGH", 109.25, 23.03, "service", ground_elev_m=800.0)
    g = leg_geometry(p, O01, high, clamp_negative=True)
    seg = g.as_segment()
    assert seg.distance_m >= 0 and seg.climb_m >= 0 and seg.descent_m >= 0


# ================================================================ 真实 DEM 对照（可选）

@pytest.mark.realdata
@pytest.mark.skipif(not REAL_DEM.exists(), reason="真实 DEM 不在工作区")
def test_real_dem_metadata_matches_attachment() -> None:
    """真实 DEM 的元信息必须与附件说明一致（EPSG:4326、约 30 m）。"""
    from src.geo.dem import RasterElevationProvider

    p = RasterElevationProvider(REAL_DEM)
    assert p.epsg == 4326
    assert p.is_geographic()
    lo, la, hi, ha = p.bounds
    assert lo == pytest.approx(109.0326, abs=1e-3)
    assert hi == pytest.approx(109.4454, abs=1e-3)
    assert la == pytest.approx(22.8613, abs=1e-3)
    assert ha == pytest.approx(23.2249, abs=1e-3)


@pytest.mark.realdata
@pytest.mark.skipif(not REAL_DEM.exists(), reason="真实 DEM 不在工作区")
def test_real_dem_node_elevations_match_attachment() -> None:
    """★ 核心校验：DEM 采样出的节点海拔应与附件给定海拔接近。

    附件给的是节点处的精确海拔，DEM 是 30 m 分辨率，两者允许有偏差，
    但应在合理范围内（否则说明采样位置或插值有误）。
    """
    from src.geo.dem import RasterElevationProvider

    p = RasterElevationProvider(REAL_DEM)
    cases = [O01, S001, S015]
    for node in cases:
        z_dem = p.elevation_at(node.lon, node.lat)
        assert z_dem == pytest.approx(node.ground_elev_m, abs=60.0), (
            f"{node.id}: DEM={z_dem:.1f} vs 附件={node.ground_elev_m}"
        )


@pytest.mark.realdata
@pytest.mark.skipif(not REAL_DEM.exists(), reason="真实 DEM 不在工作区")
def test_real_dem_leg_cruise_altitude_exceeds_both_nodes() -> None:
    """真实航段的巡航海拔应不低于两端地面海拔 + 50 m。"""
    from src.geo.dem import RasterElevationProvider

    p = RasterElevationProvider(REAL_DEM)
    g = leg_geometry(p, O01, S015, sample_step_m=30.0)
    assert g.cruise_alt_m >= max(O01.ground_elev_m, S015.ground_elev_m) + 49.9
    assert g.distance_m > 0
