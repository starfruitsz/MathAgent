"""中继悬停候选点与单架次通信覆盖判定（问题三的核心）。

问题结构
--------
运输无人机在**爬升 / 巡航 / 下降 / 投送**全程都要保持通信。
直连 G01 不可用时，需要一架中继提供"运输机—中继—G01"单跳链路。

★ 本模块的建模思路（把连续轨迹问题降维）
------------------------------------------
题目要求的是**轨迹上每一时刻**都满足通信。若对每个时刻都独立选址，
问题会变成不可解的连续最优控制问题。我们采用如下**可验证的充分条件**：

    对某架次，若存在**一个**悬停点 `P`（三维），使得
        ∀ t ∈ [开工, 返回]： 直连可用  或  (接入(P) 可用 且 回传(P) 可用)
    则该架次在 `P` 处由一架中继全程保障即可。

这样只需对候选点做**一次窗口扫描**，复杂度从"连续轨迹 × 连续选址"降到
"离散候选点 × 时间采样"。

若单点无法覆盖全程，则允许按时间段**分段覆盖**（多架次中继接力），
由 `cover_windows` 返回需要的中继段数与各自的候选点。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence

from src.comms.link import (
    DEFAULT_PARAMS,
    CommsParams,
    EndpointKind,
    bidirectional_max_loss_db,
    distance_3d_m,
    link_available,
    path_loss_db,
)
from src.comms.los import has_terrain_obstruction
from src.comms.service import CommState, ServiceContext, comm_status
from src.common.config import SERVICE_AREA_OP_HEIGHT_M
from src.geo.dem import ElevationProvider, OutOfBoundsError
from src.geo.leg import Node, cruise_altitude, node_op_height
from src.physics.leg_cache import LegCache
from src.physics.payload import UAVType

CENTER_ID = "O01"


# ---------------------------------------------------------------- 悬停候选点

@dataclass(frozen=True)
class HoverCandidate:
    """一个中继悬停候选点。"""

    lon: float
    lat: float
    ground_m: float
    """该点地面高程（DSM）m。"""
    alt_m: float
    """飞行海拔（绝对高程）m。"""
    agl_m: float
    """离地高度 m（必须 ≤ 附件上限）。"""

    @property
    def pos(self) -> tuple[float, float, float]:
        return (self.lon, self.lat, self.alt_m)


def generate_hover_candidates(
    provider: ElevationProvider,
    service_nodes: Sequence[Node],
    step_m: float = 300.0,
    max_agl_m: float = 300.0,
    clearance_m: float = 50.0,
    margin_m: float = 3000.0,
    target_agl: float = 250.0,
) -> list[HoverCandidate]:
    """在 DEM 覆盖范围内、服务区周边生成中继悬停候选点。

    只生成**服务区凸包外扩 `margin_m`** 范围内的点 ——
    因为中继必须靠近运输机（接入段门限最低，见 MODEL_NOTES 3.3c），
    远离作业空域的候选点没有实用价值，还会浪费扫描时间。

    参数
    ----
    step_m : 候选点网格步长（m）。步长与通信判定的敏感性分析在论文中讨论。
    max_agl_m : 悬停离地高度上限（附件值 300 m）
    target_agl : 期望悬停离地高度（取 `max_agl_m` 内较优的值，越高视线越好）
    """
    from src.geo.crs import make_local_plane

    lons = [n.lon for n in service_nodes]
    lats = [n.lat for n in service_nodes]
    plane = make_local_plane(points=list(zip(lons, lats)))
    cx, cy = plane.to_xy(sum(lons) / len(lons), sum(lats) / len(lats))

    # 目标区域半径（覆盖全部服务区 + margin）
    rs = [math.hypot(*[a - b for a, b in zip(plane.to_xy(n.lon, n.lat), (cx, cy))])
          for n in service_nodes]
    radius = max(rs) + margin_m

    out: list[HoverCandidate] = []
    n_steps = int(radius / step_m) + 1
    seen: set[tuple[float, float]] = set()
    for i in range(-n_steps, n_steps + 1):
        for j in range(-n_steps, n_steps + 1):
            x, y = cx + i * step_m, cy + j * step_m
            if math.hypot(x - cx, y - cy) > radius:
                continue
            lon, lat = plane.to_lonlat(x, y)
            key = (round(lon, 6), round(lat, 6))
            if key in seen:
                continue
            seen.add(key)
            try:
                g = provider.elevation_at(lon, lat)
            except OutOfBoundsError:
                continue
            agl = min(target_agl, max_agl_m)
            out.append(
                HoverCandidate(
                    lon=lon, lat=lat, ground_m=g, alt_m=g + agl, agl_m=agl
                )
            )
    return out


# ---------------------------------------------------------------- 单点覆盖判定

@dataclass(frozen=True)
class Sample:
    """轨迹上的一个采样点。"""

    t_s: float
    lon: float
    lat: float
    alt_m: float
    phase: str
    """所处阶段：climb / cruise / descent / handover。"""


@dataclass
class CoverageResult:
    """一个架次在给定中继点（或纯直连）下的通信覆盖结果。"""

    covered: bool
    n_samples: int
    n_direct: int
    n_relay: int
    n_outage: int
    outage_fraction: float
    first_outage_s: float | None
    last_outage_s: float | None
    access_ok: bool
    backhaul_ok: bool


def sample_trajectory(
    stops: Sequence[str],
    boxes_per_stop: dict[str, int],
    uav: UAVType,
    leg_cache: LegCache,
    nodes_xy: dict[str, tuple[float, float]],
    start_s: float,
    center_id: str = CENTER_ID,
    dt_s: float | None = None,
    step_m: float = 0.0,
) -> list[Sample]:
    """把架次轨迹离散为 `(t, lon, lat, alt, phase)` 采样序列。

    覆盖题目要求的四个阶段：**爬升 → 巡航 → 下降 → 投送（交接停留）**。

    高度剖面按"作业高度 → 巡航海拔 → 作业高度"的梯形，逐段推进：
        爬升段 : h⁺/v↑      ，高度 op_a → cruise
        巡航段 : d/v_c      ，高度恒为 cruise
        下降段 : h⁻/v↓      ，高度 cruise → op_b
        投送   : 交接时间    ，高度恒为 op_b

    ★ 采样步长：按时间 `dt_s`（默认取 `config.COMM_SAMPLE_DT_S`）与
      距离 `step_m`（>0 时启用）两者**取更密**者，保证长航段不漏判。

    返回按时间升序的采样点列表。
    """
    from src.common.config import COMM_SAMPLE_DT_S

    dt = COMM_SAMPLE_DT_S if dt_s is None else dt_s
    out: list[Sample] = []
    t = start_s + uav.prepare_time_s + uav.box_load_time_s * sum(
        boxes_per_stop.get(s, 0) for s in stops
    )
    seq = [center_id, *stops, center_id]

    def _n_samples(dur: float, dist: float) -> int:
        n_t = math.ceil(dur / dt) if dt > 0 else 1
        n_d = math.ceil(dist / step_m) if step_m > 0 else 1
        return max(2, n_t, n_d)

    for a, b in zip(seq, seq[1:]):
        g = leg_cache.get(a, b)
        d = g["distance_m"]
        cruise, op_a, op_b = g["cruise_alt_m"], g["op_from_m"], g["op_to_m"]
        lon_a, lat_a = nodes_xy[a]
        lon_b, lat_b = nodes_xy[b]

        # ★ 高度剖面按**端点作业高度与巡航海拔之差**构造，保证三段首尾相接：
        #   爬升末值 = 巡航海拔 = 下降首值。不直接用 leg_cache 的 climb/descent，
        #   因为那两者与 cruise_alt 在数值上未必自洽（可能造成高度跳变）。
        h_up = max(0.0, cruise - op_a)
        h_dn = max(0.0, cruise - op_b)

        def _pt(frac: float) -> tuple[float, float]:
            return (lon_a + (lon_b - lon_a) * frac, lat_a + (lat_b - lat_a) * frac)

        # --- 爬升（垂直）---
        if h_up > 1e-9 and uav.climb_speed_ms > 0:
            dur = h_up / uav.climb_speed_ms
            n = _n_samples(dur, 0.0)
            lon, lat = _pt(0.0)
            for k in range(n + 1):
                out.append(
                    Sample(t + dur * k / n, lon, lat, op_a + h_up * k / n, "climb")
                )
            t += dur

        # --- 巡航 ---
        dur = d / uav.cruise_speed_ms if uav.cruise_speed_ms > 0 else 0.0
        n = _n_samples(dur, d)
        for k in range(n + 1):
            lon, lat = _pt(k / n)
            out.append(Sample(t + dur * k / n, lon, lat, cruise, "cruise"))
        t += dur

        # --- 下降（垂直）---
        if h_dn > 1e-9 and uav.descent_speed_ms > 0:
            dur = h_dn / uav.descent_speed_ms
            n = _n_samples(dur, 0.0)
            lon, lat = _pt(1.0)
            for k in range(n + 1):
                out.append(
                    Sample(t + dur * k / n, lon, lat, cruise - h_dn * k / n, "descent")
                )
            t += dur

        # --- 投送（交接停留）---
        if b in boxes_per_stop:
            k_boxes = boxes_per_stop.get(b, 0)
            dur = uav.handover_base_s + uav.handover_per_box_s * k_boxes
            lon, lat = _pt(1.0)
            for k in (0, 1):
                out.append(Sample(t + dur * k, lon, lat, op_b, "handover"))
            t += dur

    out.sort(key=lambda s: s.t_s)
    return out


def coverage_of_samples(
    samples: Sequence[Sample],
    params: CommsParams,
    provider: ElevationProvider,
    gateway_pos: tuple[float, float, float],
    relay_pos: tuple[float, float, float] | None = None,
    los_step_m: float = 50.0,
) -> CoverageResult:
    """统计采样序列的通信状态（直连 / 中继 / 中断）。

    ★ 性能：先用一次直连扫描筛出**中断样本**，再只对这些样本判定中继。
      中继判定里"回传段"（中继↔G01）与运输机位置无关，只算一次。
    """
    direct_thr = bidirectional_max_loss_db(
        params, EndpointKind.TRANSPORT, EndpointKind.GATEWAY
    )
    acc_thr = bidirectional_max_loss_db(
        params, EndpointKind.TRANSPORT, EndpointKind.RELAY_ACCESS
    )
    back_thr = bidirectional_max_loss_db(
        params, EndpointKind.RELAY_BACKHAUL, EndpointKind.GATEWAY
    )

    # --- 第一遍：直连 ---
    direct_flags: list[bool] = []
    n_direct = 0
    for sm in samples:
        d_dir = distance_3d_m(sm.lon, sm.lat, sm.alt_m, *gateway_pos)
        obs_dir = has_terrain_obstruction(
            provider, sm.lon, sm.lat, sm.alt_m, *gateway_pos, sample_step_m=los_step_m
        )
        ok = link_available(path_loss_db(params, d_dir, obs_dir), direct_thr)
        direct_flags.append(ok)
        n_direct += int(ok)

    outage_idx = [i for i, ok in enumerate(direct_flags) if not ok]

    # --- 第二遍：只对中断样本判中继 ---
    n_relay = n_outage = 0
    first_out: float | None = None
    last_out: float | None = None
    acc_ok_all = True
    back_ok_all = True

    back_ok = False
    if relay_pos is not None:
        d_back = distance_3d_m(*relay_pos, *gateway_pos)
        obs_back = has_terrain_obstruction(
            provider, *relay_pos, *gateway_pos, sample_step_m=los_step_m
        )
        back_ok = link_available(path_loss_db(params, d_back, obs_back), back_thr)
        back_ok_all = back_ok

    for i in outage_idx:
        sm = samples[i]
        if relay_pos is not None and back_ok:
            d_acc = distance_3d_m(sm.lon, sm.lat, sm.alt_m, *relay_pos)
            obs_acc = has_terrain_obstruction(
                provider, sm.lon, sm.lat, sm.alt_m, *relay_pos, sample_step_m=los_step_m
            )
            acc_ok = link_available(path_loss_db(params, d_acc, obs_acc), acc_thr)
            if acc_ok:
                n_relay += 1
                continue
            acc_ok_all = False
        n_outage += 1
        if first_out is None:
            first_out = sm.t_s
        last_out = sm.t_s

    n = len(samples)
    return CoverageResult(
        covered=n_outage == 0,
        n_samples=n,
        n_direct=n_direct,
        n_relay=n_relay,
        n_outage=n_outage,
        outage_fraction=(n_outage / n) if n else 0.0,
        first_outage_s=first_out,
        last_outage_s=last_out,
        access_ok=acc_ok_all,
        backhaul_ok=back_ok_all,
    )


def outage_samples(
    samples: Sequence[Sample],
    params: CommsParams,
    provider: ElevationProvider,
    gateway_pos: tuple[float, float, float],
    los_step_m: float = 50.0,
) -> list[Sample]:
    """返回**直连不可用**的样本子集（供选址时快速评估）。

    ★ 这是问题三的性能关键：若一个候选点能覆盖全部中断样本，
      则该架次全程被覆盖（非中断样本本来就靠直连）。
      于是选址只需扫描"中断样本"，通常只占全轨迹的 10%~45%。
    """
    direct_thr = bidirectional_max_loss_db(
        params, EndpointKind.TRANSPORT, EndpointKind.GATEWAY
    )
    out: list[Sample] = []
    for sm in samples:
        d_dir = distance_3d_m(sm.lon, sm.lat, sm.alt_m, *gateway_pos)
        obs_dir = has_terrain_obstruction(
            provider, sm.lon, sm.lat, sm.alt_m, *gateway_pos, sample_step_m=los_step_m
        )
        if not link_available(path_loss_db(params, d_dir, obs_dir), direct_thr):
            out.append(sm)
    return out


def _point_covered(
    sm: Sample,
    params: CommsParams,
    provider: ElevationProvider,
    gateway_pos: tuple[float, float, float],
    relay_pos: tuple[float, float, float],
    los_step_m: float = 50.0,
) -> bool:
    """单个采样点是否被该中继点覆盖（接入段 + 回传段同时可用）。

    供"分段覆盖"使用：需要逐点判定哪些中断样本能被某个候选点救回。
    """
    acc_thr = bidirectional_max_loss_db(
        params, EndpointKind.TRANSPORT, EndpointKind.RELAY_ACCESS
    )
    back_thr = bidirectional_max_loss_db(
        params, EndpointKind.RELAY_BACKHAUL, EndpointKind.GATEWAY
    )
    d_back = distance_3d_m(*relay_pos, *gateway_pos)
    obs_back = has_terrain_obstruction(
        provider, *relay_pos, *gateway_pos, sample_step_m=los_step_m
    )
    if not link_available(path_loss_db(params, d_back, obs_back), back_thr):
        return False
    d_acc = distance_3d_m(sm.lon, sm.lat, sm.alt_m, *relay_pos)
    if not link_available(path_loss_db(params, d_acc, False), acc_thr):
        return False
    obs_acc = has_terrain_obstruction(
        provider, sm.lon, sm.lat, sm.alt_m, *relay_pos, sample_step_m=los_step_m
    )
    return link_available(path_loss_db(params, d_acc, obs_acc), acc_thr)


def covers_all(
    targets: Sequence[Sample],
    params: CommsParams,
    provider: ElevationProvider,
    gateway_pos: tuple[float, float, float],
    relay_pos: tuple[float, float, float],
    los_step_m: float = 50.0,
    probe_limit: int = 12,
    probe_stride: int | None = None,
) -> bool:
    """候选点能否覆盖全部给定样本（接入段 + 回传段都要可用）。

    ★ 性能：先用**稀疏探针**（最多 `probe_limit` 个均匀分布的样本）快速否掉
      绝大多数候选点 —— 绝大多数候选连探针都过不了，无需扫全量。
      探针全过后再逐点确认。

    `probe_stride` 可显式指定探针间隔；None 时按 `probe_limit` 自动取。
    """
    acc_thr = bidirectional_max_loss_db(
        params, EndpointKind.TRANSPORT, EndpointKind.RELAY_ACCESS
    )
    back_thr = bidirectional_max_loss_db(
        params, EndpointKind.RELAY_BACKHAUL, EndpointKind.GATEWAY
    )
    # 回传段与运输机位置无关 → 只算一次
    # ★ 必须**先行判定并直接返回**：否则后面按 target 循环时，
    #   某次迭代可能"侥幸"通过接入段就提前 return True，从而漏掉回传段不可用的事实。
    d_back = distance_3d_m(*relay_pos, *gateway_pos)
    obs_back = has_terrain_obstruction(
        provider, *relay_pos, *gateway_pos, sample_step_m=los_step_m
    )
    if not link_available(path_loss_db(params, d_back, obs_back), back_thr):
        return False
    if not targets:
        return True

    n = len(targets)

    def _ok(sm: Sample) -> bool:
        d_acc = distance_3d_m(sm.lon, sm.lat, sm.alt_m, *relay_pos)
        # 先按自由空间快速否掉（距离太远必然不可用）
        if not link_available(path_loss_db(params, d_acc, False), acc_thr):
            return False
        obs_acc = has_terrain_obstruction(
            provider, sm.lon, sm.lat, sm.alt_m, *relay_pos, sample_step_m=los_step_m
        )
        return link_available(path_loss_db(params, d_acc, obs_acc), acc_thr)

    # --- 稀疏探针 ---
    stride = probe_stride if probe_stride is not None else max(1, n // probe_limit)
    for i in range(0, n, stride):
        if not _ok(targets[i]):
            return False
    if stride == 1:
        return True
    # --- 全量确认（跳过已探过的点）---
    for i in range(n):
        if i % stride == 0:
            continue
        if not _ok(targets[i]):
            return False
    return True


def n_covered(
    targets: Sequence[Sample],
    params: CommsParams,
    provider: ElevationProvider,
    gateway_pos: tuple[float, float, float],
    relay_pos: tuple[float, float, float],
    los_step_m: float = 50.0,
    probe_limit: int = 10,
) -> int:
    """候选点能覆盖多少个给定样本（用于"无法全程覆盖"时的择优）。

    ★ 同为性能敏感函数：只抽查最多 `probe_limit` 个均匀样本做**估计**，
      避免在 481 个候选点上全量扫描。
    """
    acc_thr = bidirectional_max_loss_db(
        params, EndpointKind.TRANSPORT, EndpointKind.RELAY_ACCESS
    )
    back_thr = bidirectional_max_loss_db(
        params, EndpointKind.RELAY_BACKHAUL, EndpointKind.GATEWAY
    )
    d_back = distance_3d_m(*relay_pos, *gateway_pos)
    obs_back = has_terrain_obstruction(
        provider, *relay_pos, *gateway_pos, sample_step_m=los_step_m
    )
    if not link_available(path_loss_db(params, d_back, obs_back), back_thr):
        return 0
    n = len(targets)
    if n == 0:
        return 0
    stride = max(1, n // probe_limit)
    idxs = list(range(0, n, stride))
    c = 0
    for i in idxs:
        sm = targets[i]
        d_acc = distance_3d_m(sm.lon, sm.lat, sm.alt_m, *relay_pos)
        obs_acc = has_terrain_obstruction(
            provider, sm.lon, sm.lat, sm.alt_m, *relay_pos, sample_step_m=los_step_m
        )
        if link_available(path_loss_db(params, d_acc, obs_acc), acc_thr):
            c += 1
    return c
