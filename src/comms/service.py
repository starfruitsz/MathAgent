"""通信服务状态判定（题目附录 3 第（5）条）。

    运输无人机在任一时刻的通信状态按以下规则确定：
      · 与固定网关 G01 的链路可用时，记为**直连状态**；
      · 直连不可用，但 运输无人机—中继无人机接入链路 与 中继无人机—G01回传链路
        **同时可用**时，记为**中继状态**；
      · 其余情况记为**通信中断状态**。

    采用中继服务时，接入链路和回传链路必须在**同一时刻同时可用**。
    每架运输无人机在任一时刻**只能由 G01 或一架中继无人机**提供通信保障。
    ★ 不允许中继无人机之间进行多跳转发。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.comms.link import (
    CommsParams,
    EndpointKind,
    bidirectional_max_loss_db,
    distance_3d_m,
    link_available,
    path_loss_db,
)
from src.comms.los import has_terrain_obstruction
from src.geo.dem import ElevationProvider


class CommState(str, Enum):
    """运输无人机在某一时刻的通信服务状态。"""

    DIRECT = "直连"
    RELAY = "中继"
    OUTAGE = "中断"


@dataclass(frozen=True)
class ServiceContext:
    """某一时刻的通信几何快照。"""

    uav_lon: float
    uav_lat: float
    uav_alt_m: float
    """运输无人机的**绝对**飞行海拔（m）。"""

    gateway_lon: float
    gateway_lat: float
    gateway_alt_m: float
    """固定网关通信端点的绝对海拔 = O01 地面海拔 + 天线离地高度（m）。"""

    relay: tuple[float, float, float] | None = None
    """中继无人机悬停位置 (lon, lat, alt_m)；None 表示当前无中继可用。"""


# ---------------------------------------------------------------- 单链路判定

def _link_ok(
    params: CommsParams,
    provider: ElevationProvider,
    a_kind: EndpointKind,
    a_pos: tuple[float, float, float],
    b_kind: EndpointKind,
    b_pos: tuple[float, float, float],
    sample_step_m: float,
) -> bool:
    """判定一条双向链路是否可用（含地形遮挡）。"""
    d = distance_3d_m(a_pos[0], a_pos[1], a_pos[2], b_pos[0], b_pos[1], b_pos[2])
    blocked = has_terrain_obstruction(
        provider, a_pos[0], a_pos[1], a_pos[2], b_pos[0], b_pos[1], b_pos[2],
        sample_step_m=sample_step_m,
    )
    loss = path_loss_db(params, d, obstructed=blocked)
    return link_available(loss, bidirectional_max_loss_db(params, a_kind, b_kind))


def direct_ok(
    ctx: ServiceContext,
    params: CommsParams,
    provider: ElevationProvider,
    sample_step_m: float = 30.0,
) -> bool:
    """运输无人机 ↔ G01 直连是否可用。"""
    return _link_ok(
        params,
        provider,
        EndpointKind.TRANSPORT,
        (ctx.uav_lon, ctx.uav_lat, ctx.uav_alt_m),
        EndpointKind.GATEWAY,
        (ctx.gateway_lon, ctx.gateway_lat, ctx.gateway_alt_m),
        sample_step_m,
    )


def access_ok(
    ctx: ServiceContext,
    params: CommsParams,
    provider: ElevationProvider,
    sample_step_m: float = 30.0,
) -> bool:
    """运输无人机 ↔ 中继**接入端**是否可用。"""
    if ctx.relay is None:
        return False
    return _link_ok(
        params,
        provider,
        EndpointKind.TRANSPORT,
        (ctx.uav_lon, ctx.uav_lat, ctx.uav_alt_m),
        EndpointKind.RELAY_ACCESS,
        ctx.relay,
        sample_step_m,
    )


def backhaul_ok(
    ctx: ServiceContext,
    params: CommsParams,
    provider: ElevationProvider,
    sample_step_m: float = 30.0,
) -> bool:
    """中继**回传端** ↔ G01 是否可用。"""
    if ctx.relay is None:
        return False
    return _link_ok(
        params,
        provider,
        EndpointKind.RELAY_BACKHAUL,
        ctx.relay,
        EndpointKind.GATEWAY,
        (ctx.gateway_lon, ctx.gateway_lat, ctx.gateway_alt_m),
        sample_step_m,
    )


def relay_ok(
    ctx: ServiceContext,
    params: CommsParams,
    provider: ElevationProvider,
    sample_step_m: float = 30.0,
) -> bool:
    """中继链路是否可用：**接入段与回传段必须同时可用**。

    ★ 题目明确要求"同时可用"，且"每架运输无人机在任一时刻只能由
      G01 或一架中继无人机提供通信保障"、"不允许中继之间多跳"。
      因此这里只判定**单跳**（运输机—中继—G01），不做多跳串联。
    """
    if ctx.relay is None:
        return False
    return access_ok(ctx, params, provider, sample_step_m) and backhaul_ok(
        ctx, params, provider, sample_step_m
    )


# ---------------------------------------------------------------- 三态判定

def comm_status(
    ctx: ServiceContext,
    params: CommsParams,
    provider: ElevationProvider,
    sample_step_m: float = 30.0,
) -> CommState:
    """判定通信服务状态：直连 > 中继 > 中断（**优先级从上到下**）。"""
    if direct_ok(ctx, params, provider, sample_step_m):
        return CommState.DIRECT
    if relay_ok(ctx, params, provider, sample_step_m):
        return CommState.RELAY
    return CommState.OUTAGE


def required_state_ok(
    ctx: ServiceContext,
    params: CommsParams,
    provider: ElevationProvider,
    sample_step_m: float = 30.0,
) -> bool:
    """该时刻是否满足"连续通信"要求（非中断即满足）。"""
    return comm_status(ctx, params, provider, sample_step_m) is not CommState.OUTAGE
