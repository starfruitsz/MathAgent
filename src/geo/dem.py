"""DEM 读取、高程采样与沿线最高点。

★ 解耦要点：本模块通过 `ElevationProvider` **协议**对外提供高程，
   上层（`geo/leg.py`、`physics/`）只依赖协议，不依赖 rasterio。
   于是测试可以用 `AnalyticElevationProvider`（解析高程）跑，
   完全不需要加载 7.5 MB 的真实 DEM。

★ ADR-019：附件 DEM 是 **DSM（数字表面模型）**，含植被与建筑。
   按原样使用，不做"去建筑"处理 —— DSM 高程 ≥ 真实地形，
   用于净空与遮挡判定偏保守（更安全），符合救援场景。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence, runtime_checkable

from src.common.config import DEM_RESOLUTION_M


class OutOfBoundsError(ValueError):
    """请求的高程点落在 DEM 覆盖范围之外。"""


@runtime_checkable
class ElevationProvider(Protocol):
    """高程提供者协议（★ 分层解耦的关键接口）。

    任何实现只要提供 `elevation_at(lon, lat) -> float` 即可被上层使用。
    """

    def elevation_at(self, lon: float, lat: float) -> float:
        """返回该经纬度处的地面高程（m）。越界应抛 `OutOfBoundsError`。"""
        ...

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """覆盖范围 (lon_min, lat_min, lon_max, lat_max)。"""
        ...


# ---------------------------------------------------------------- 解析实现（测试用）

@dataclass(frozen=True)
class AnalyticElevationProvider:
    """解析高程提供者：`z = base + gx·(lon−lon0) + gy·(lat−lat0)`。

    专用于单元测试，让几何/物理层**脱离真实 DEM** 也能验证。
    """

    base: float = 100.0
    gx: float = 0.0
    gy: float = 0.0
    lon0: float = 109.230852
    lat0: float = 23.008509
    _bounds: tuple[float, float, float, float] = (
        109.0,
        22.85,
        109.5,
        23.25,
    )

    def elevation_at(self, lon: float, lat: float) -> float:
        lo, la, hi, ha = self._bounds
        if not (lo <= lon <= hi and la <= lat <= ha):
            raise OutOfBoundsError(f"({lon}, {lat}) 超出解析 DEM 范围 {self._bounds}")
        return self.base + self.gx * (lon - self.lon0) + self.gy * (lat - self.lat0)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return self._bounds


# ---------------------------------------------------------------- 真实实现（rasterio）

@dataclass
class RasterElevationProvider:
    """基于 GeoTIFF 的高程提供者（真实 DEM）。

    栅格**一次性读入内存**（题目 DEM 为 1486×1309 float32 ≈ 7.8 MB），
    避免每次采样都触碰磁盘 —— 这是性能关键。

    参数
    ----
    path : GeoTIFF 路径
    nodata : 无效值；None 时取栅格自带的 nodata
    """

    path: Path
    nodata: float | None = None
    _array: object = None
    _transform: object = None
    _bounds: tuple[float, float, float, float] | None = None
    _crs_epsg: int | None = None
    _inv_transform: object = None

    def __post_init__(self) -> None:
        import rasterio

        self.path = Path(self.path)
        with rasterio.open(self.path) as src:
            self._array = src.read(1).astype("float64")
            self._transform = src.transform
            # 预先求逆，避免每次采样都算一遍（性能关键）
            self._inv_transform = ~src.transform
            b = src.bounds
            self._bounds = (b.left, b.bottom, b.right, b.top)
            self._crs_epsg = src.crs.to_epsg() if src.crs else None
            if self.nodata is None:
                self.nodata = src.nodata

    # ---- 元信息 ----

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        assert self._bounds is not None
        return self._bounds

    @property
    def epsg(self) -> int | None:
        """栅格 CRS 的 EPSG 代码（附件实测为 4326）。"""
        return self._crs_epsg

    def is_geographic(self) -> bool:
        """栅格是否为地理坐标系（经纬度）。

        ★ 附件 DEM 为 EPSG:4326 → 采样必须用经纬度索引，
          而水平距离必须另行投影（见 `geo/crs.py`）。
        """
        return self._crs_epsg == 4326

    # ---- 采样 ----

    def _rowcol(self, lon: float, lat: float) -> tuple[float, float]:
        """经纬度 → 连续（行, 列）坐标（栅格左上角为原点）。

        使用 `@`（矩阵乘）而非 `*`：rasterio 已把 `*` 标记为
        PendingDeprecationWarning，`@` 是官方推荐写法。
        """
        inv = self._inv_transform
        col, row = inv @ (lon, lat)  # type: ignore[operator]
        return float(row), float(col)
    def elevation_at(self, lon: float, lat: float) -> float:
        """双线性插值采样高程（m）。

        注意：附件栅格是**像元中心**对齐，但双线性插值在连续坐标上
        使用 0.5 偏移更稳妥，此处采用 `row-0.5` / `col-0.5` 的像元中心约定。
        """
        lo, la, hi, ha = self.bounds
        if not (lo <= lon <= hi and la <= lat <= ha):
            raise OutOfBoundsError(
                f"({lon:.6f}, {lat:.6f}) 超出 DEM 范围 "
                f"lon[{lo:.6f}, {hi:.6f}] lat[{la:.6f}, {ha:.6f}]"
            )
        return self._bilinear(lon, lat)

    def _bilinear(self, lon: float, lat: float) -> float:
        import numpy as np

        arr = self._array
        assert isinstance(arr, np.ndarray)
        row, col = self._rowcol(lon, lat)
        # 像元中心约定
        r = row - 0.5
        c = col - 0.5
        r0, c0 = int(math.floor(r)), int(math.floor(c))
        dr, dc = r - r0, c - c0

        nrows, ncols = arr.shape
        r0 = min(max(r0, 0), nrows - 2) if nrows > 1 else 0
        c0 = min(max(c0, 0), ncols - 2) if ncols > 1 else 0
        r1, c1 = min(r0 + 1, nrows - 1), min(c0 + 1, ncols - 1)

        v00, v01 = arr[r0, c0], arr[r0, c1]
        v10, v11 = arr[r1, c0], arr[r1, c1]
        val = (
            v00 * (1 - dr) * (1 - dc)
            + v01 * (1 - dr) * dc
            + v10 * dr * (1 - dc)
            + v11 * dr * dc
        )
        if self.nodata is not None and float(val) == float(self.nodata):
            raise OutOfBoundsError(f"({lon}, {lat}) 落在 DEM 的 nodata 像元上")
        return float(val)

    # ---- 沿线最高点 ----

    def max_elevation_along_line(
        self,
        lon1: float,
        lat1: float,
        lon2: float,
        lat2: float,
        sample_step_m: float = DEM_RESOLUTION_M,
    ) -> float:
        """沿水平直线段采样并返回**最高地面高程**（m）。

        这是附录 2 的核心规则：
            巡航海拔 = 该航段所经过 DEM 像元的最高地面高程 + 50 m

        参数
        ----
        sample_step_m : 采样步长（m）。默认取 DEM 分辨率 30 m
                        （即"每个像元至少采一次"）。
        """
        return max_elevation_along_line(
            self, lon1, lat1, lon2, lat2, sample_step_m=sample_step_m
        )


# ---------------------------------------------------------------- 通用函数（对协议编程）

def max_elevation_along_line(
    provider: ElevationProvider,
    lon1: float,
    lat1: float,
    lon2: float,
    lat2: float,
    sample_step_m: float = DEM_RESOLUTION_M,
) -> float:
    """沿线最高地面高程（m）—— **只依赖 ElevationProvider 协议**。

    实现要点
    --------
    - 步长按**米**给定，再折算成参数比例，保证不同距离的采样密度一致
    - 端点必采（`frac` 含 0 与 1）
    - 越界点会被跳过并记录；若全部越界则抛 OutOfBoundsError
    """
    from src.geo.crs import make_local_plane

    if sample_step_m <= 0:
        raise ValueError("采样步长必须为正")

    plane = make_local_plane(center=((lon1 + lon2) / 2, (lat1 + lat2) / 2))
    x1, y1 = plane.to_xy(lon1, lat1)
    x2, y2 = plane.to_xy(lon2, lat2)
    length = math.hypot(x2 - x1, y2 - y1)

    n = max(1, int(math.ceil(length / sample_step_m)))
    fracs = [i / n for i in range(n + 1)]

    best = -math.inf
    n_valid = 0
    for f in fracs:
        lon = lon1 + (lon2 - lon1) * f
        lat = lat1 + (lat2 - lat1) * f
        try:
            z = provider.elevation_at(lon, lat)
        except OutOfBoundsError:
            continue
        n_valid += 1
        if z > best:
            best = z

    if n_valid == 0:
        raise OutOfBoundsError(
            f"航段 ({lon1}, {lat1}) → ({lon2}, {lat2}) 的全部采样点都在 DEM 范围外"
        )
    return best
