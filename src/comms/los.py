"""地形遮挡判定（题目附录 3 第（1）条）。

    任意两个通信端点之间，根据其三维位置及 30 m DEM 判断视线连线是否受到地形遮挡。

实现：沿两端点的**水平投影直线**采样，比较每个采样点的地面高程与
视线在该处的插值高度：

    视线高度(frac) = alt1 + (alt2 − alt1) · frac
    遮挡余量(frac) = 地面高程(frac) − 视线高度(frac)
    b = 1 若 max_frac 遮挡余量 > 0，否则 0

★ 只依赖 `ElevationProvider` 协议 → 可用解析地形做单元测试（分层解耦）。

★ 说明：题目未给出 Fresnel 半径或额外安全间隔，因此这里采用
   **几何视线（LOS）严格判定**：地形高过视线即为遮挡。
   如需保守余量，可通过 `clearance_m` 参数额外抬高视线。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.common.config import DEM_RESOLUTION_M
from src.geo.dem import ElevationProvider, OutOfBoundsError


@dataclass(frozen=True)
class LosResult:
    """视线判定结果。"""

    obstructed: bool
    """是否存在地形遮挡（b_ijt）。"""
    worst_margin_m: float
    """最差遮挡余量（m）：地形高程 − 视线高度。正值表示被遮挡。"""
    worst_fraction: float
    """最差余量出现的位置比例 ∈ [0, 1]。"""
    n_samples: int
    """有效采样点数（越界点已跳过）。"""
    n_skipped: int
    """被跳过的越界采样点数。"""


def line_of_sight_margin(
    provider: ElevationProvider,
    lon1: float,
    lat1: float,
    alt1_m: float,
    lon2: float,
    lat2: float,
    alt2_m: float,
    sample_step_m: float = DEM_RESOLUTION_M,
    clearance_m: float = 0.0,
    plane: object = None,
) -> LosResult:
    """沿视线采样并返回最差余量。

    参数
    ----
    alt1_m, alt2_m : 两端点的**绝对高程**（m）
    sample_step_m  : 采样步长（m）
    clearance_m    : 视线额外抬高量（m），用于保守判定；0 表示严格几何视线
    plane          : 预先构造的局部切平面。★ 性能：高频调用时应由调用方
                     预构造一次并复用，避免每次重复计算曲率半径与三角函数。
    """
    import math

    from src.geo.crs import make_local_plane

    if sample_step_m <= 0:
        raise ValueError("采样步长必须为正")

    if plane is None:
        plane = make_local_plane(center=((lon1 + lon2) / 2, (lat1 + lat2) / 2))
    x1, y1 = plane.to_xy(lon1, lat1)  # type: ignore[attr-defined]
    x2, y2 = plane.to_xy(lon2, lat2)  # type: ignore[attr-defined]
    length = math.hypot(x2 - x1, y2 - y1)
    n = max(1, int(math.ceil(length / sample_step_m)))

    worst = -math.inf
    worst_frac = 0.0
    n_valid = 0
    n_skipped = 0
    dl = (lon2 - lon1) / n
    da = (alt2_m - alt1_m) / n
    dlat = (lat2 - lat1) / n
    for i in range(n + 1):
        frac = i / n
        try:
            z_ground = provider.elevation_at(lon1 + dl * i, lat1 + dlat * i)
        except OutOfBoundsError:
            n_skipped += 1
            continue
        n_valid += 1
        z_los = alt1_m + da * i + clearance_m
        margin = z_ground - z_los
        if margin > worst:
            worst = margin
            worst_frac = frac

    if n_valid == 0:
        # 全部越界：无法判定，保守起见视为**无遮挡**并按 0 余量返回
        return LosResult(False, 0.0, 0.0, 0, n_skipped)

    return LosResult(
        obstructed=worst > 0.0,
        worst_margin_m=float(worst),
        worst_fraction=float(worst_frac),
        n_samples=n_valid,
        n_skipped=n_skipped,
    )


def terrain_obstruction(
    provider: ElevationProvider,
    lon1: float,
    lat1: float,
    alt1_m: float,
    lon2: float,
    lat2: float,
    alt2_m: float,
    sample_step_m: float = DEM_RESOLUTION_M,
    clearance_m: float = 0.0,
    plane: object = None,
) -> tuple[float, bool]:
    """返回 (最差遮挡余量, 是否有遮挡)。"""
    r = line_of_sight_margin(
        provider, lon1, lat1, alt1_m, lon2, lat2, alt2_m, sample_step_m, clearance_m,
        plane=plane,
    )
    return r.worst_margin_m, r.obstructed


def has_terrain_obstruction(
    provider: ElevationProvider,
    lon1: float,
    lat1: float,
    alt1_m: float,
    lon2: float,
    lat2: float,
    alt2_m: float,
    sample_step_m: float = DEM_RESOLUTION_M,
    clearance_m: float = 0.0,
    plane: object = None,
) -> bool:
    """是否存在地形遮挡（b_ijt = 1）。"""
    return terrain_obstruction(
        provider, lon1, lat1, alt1_m, lon2, lat2, alt2_m, sample_step_m, clearance_m,
        plane=plane,
    )[1]
