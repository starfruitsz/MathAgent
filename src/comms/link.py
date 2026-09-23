"""链路预算（题目附录 3 的**唯一实现**，铁律 R4）。

公式（题目原文）：

    P_th,b   = P_sens,b + M_b                                  接收门限
    L_max,a→b = P_t,a + G_t,a + G_r,b − L_sys − P_th,b          单向最大允许损耗
    L_max,a↔b = min(L_max,a→b, L_max,b→a)                       ★ 双向取较小值
    L_FSPL    = 32.45 + 20·log10(f_MHz) + 20·log10(D_km)        ★ 单位是 MHz 与 **km**
    L_path    = L_FSPL + L_obs · b                              b 为地形遮挡 0/1
    A = 1 若 L_path ≤ L_max 否则 0

★ 单位陷阱：内部距离一律用 m，代入 FSPL 前**必须除以 1000**。
  差 1000 倍 = 差 60 dB，足以让所有链路判定反过来。

★ ADR-018：附件只给一列"天线增益（dBi）"，即 `G_t = G_r = G`（各端点取自身值）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from src.common.config import M_TO_KM


class EndpointKind(str, Enum):
    """通信端点类型（对应附件"通信链路参数.xlsx"的分段名）。"""

    TRANSPORT = "transport"
    """运输无人机。"""
    RELAY_ACCESS = "relay_access"
    """中继无人机**接入端**（对运输无人机）。"""
    RELAY_BACKHAUL = "relay_backhaul"
    """中继无人机**回传端**（对固定网关）。"""
    GATEWAY = "gateway"
    """固定网关 G01。"""


@dataclass(frozen=True)
class Endpoint:
    """一个通信端点的设备参数。"""

    kind: EndpointKind
    tx_power_dbm: float
    """发射功率 P_t（dBm）。"""
    antenna_gain_dbi: float
    """天线增益 G（dBi）。附件只给一列 → 收发同值（ADR-018）。"""

    @property
    def tx_gain_dbi(self) -> float:
        """发射天线增益 G_t。"""
        return self.antenna_gain_dbi

    @property
    def rx_gain_dbi(self) -> float:
        """接收天线增益 G_r。"""
        return self.antenna_gain_dbi


@dataclass(frozen=True)
class CommsParams:
    """通信系统全局参数（附件实测值）。"""

    frequency_mhz: float = 2400.0
    """载波频率 f（MHz）。"""
    system_loss_db: float = 3.0
    """系统损耗 L_sys（dB）。"""
    obstruction_loss_db: float = 10.0
    """地形遮挡附加损耗 L_obs（dB）。"""
    rx_sensitivity_dbm: float = -98.0
    """接收灵敏度 P_sens（dBm）—— 所有接收端相同。"""
    fade_margin_db: float = 8.0
    """衰落裕量 M（dB）—— 所有接收端相同。"""
    gateway_antenna_height_m: float = 20.0
    """固定网关天线离地高度 h_G（m）。"""

    endpoints: dict[EndpointKind, Endpoint] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.endpoints is None:
            object.__setattr__(
                self,
                "endpoints",
                {
                    EndpointKind.TRANSPORT: Endpoint(EndpointKind.TRANSPORT, 20.0, 3.0),
                    EndpointKind.RELAY_ACCESS: Endpoint(
                        EndpointKind.RELAY_ACCESS, 20.0, 6.0
                    ),
                    EndpointKind.RELAY_BACKHAUL: Endpoint(
                        EndpointKind.RELAY_BACKHAUL, 19.0, 8.0
                    ),
                    EndpointKind.GATEWAY: Endpoint(EndpointKind.GATEWAY, 27.0, 12.0),
                },
            )

    def endpoint(self, kind: EndpointKind) -> Endpoint:
        return self.endpoints[kind]

    @property
    def receiver_threshold_dbm(self) -> float:
        """接收门限 P_th = P_sens + M（dBm）。附件值：−98 + 8 = −90 dBm。"""
        return self.rx_sensitivity_dbm + self.fade_margin_db


DEFAULT_PARAMS = CommsParams()
"""按附件实测值构造的默认参数。"""


# ---------------------------------------------------------------- 基本公式

def fspl_db(frequency_mhz: float, distance_m: float) -> float:
    """自由空间传播损耗（dB）。

        L_FSPL = 32.45 + 20·log10(f_MHz) + 20·log10(D_km)

    ★ 距离以**米**传入，内部转换为 km。
    """
    if frequency_mhz <= 0:
        raise ValueError(f"载波频率必须为正，收到 {frequency_mhz}")
    if distance_m <= 0:
        raise ValueError(f"距离必须为正，收到 {distance_m}")
    d_km = distance_m / M_TO_KM
    return 32.45 + 20.0 * math.log10(frequency_mhz) + 20.0 * math.log10(d_km)


def path_loss_db(
    params: CommsParams, distance_m: float, obstructed: bool = False
) -> float:
    """考虑地形遮挡后的总传播损耗：

        L_path = L_FSPL + L_obs · b
    """
    loss = fspl_db(params.frequency_mhz, distance_m)
    if obstructed:
        loss += params.obstruction_loss_db
    return loss


def distance_3d_m(
    lon1: float, lat1: float, alt1_m: float,
    lon2: float, lat2: float, alt2_m: float,
) -> float:
    """两端点的三维直线距离（m）。

    ★ 水平分量必须先投影到米制平面（ADR-011），不能直接用经纬度。
    """
    from src.geo.crs import horizontal_distance_m, make_local_plane

    plane = make_local_plane(center=((lon1 + lon2) / 2, (lat1 + lat2) / 2))
    d_h = horizontal_distance_m(lon1, lat1, lon2, lat2, plane)
    return math.hypot(d_h, alt2_m - alt1_m)


# ---------------------------------------------------------------- 链路预算

def direction_max_loss_db(
    params: CommsParams, a: EndpointKind, b: EndpointKind
) -> float:
    """方向 a→b 的最大允许总传播损耗（dB）。

        L_max,a→b = P_t,a + G_t,a + G_r,b − L_sys − P_th,b
    """
    ea = params.endpoint(a)
    eb = params.endpoint(b)
    return (
        ea.tx_power_dbm
        + ea.tx_gain_dbi
        + eb.rx_gain_dbi
        - params.system_loss_db
        - params.receiver_threshold_dbm
    )


def bidirectional_max_loss_db(
    params: CommsParams, a: EndpointKind, b: EndpointKind
) -> float:
    """双向链路门限：两个方向最大允许损耗中的**较小值**。

    题目明确："由于运输控制与状态回传均需要通信保障，主体 a 与 b 之间
    按照双向链路进行判定"。★ 不能只算单向。
    """
    return min(
        direction_max_loss_db(params, a, b),
        direction_max_loss_db(params, b, a),
    )


def link_available(path_loss: float, max_loss: float) -> bool:
    """单链路可用性：`A = 1 若 L_path ≤ L_max`。落在门限上算可用。"""
    return path_loss <= max_loss
