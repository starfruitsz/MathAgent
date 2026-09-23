"""航段几何与能耗（题目附录 2 的**唯一实现**，铁律 R4）。

能耗模型（并说明为何这样选）：

    E_gij(q) = E_hor(d, q) + E_up(h⁺, m)

1. **水平巡航能耗** —— 由**航程反推**（ADR-021）：

       E_hor(d, q) = (d / L_g(q)) · E_g^use

   附件只给运输机的"空载/满载标准航程"与"电池可用能量"，**未给巡航功率**
   （只有中继机才给功率）。由航程定义反推是唯一自洽的做法：
   飞满一个"标准航程"恰好耗尽一个"可用能量"。

2. **爬升附加能耗** —— 势能除以效率（ADR-020）：

       E_up(h⁺, m) = m · g · h⁺ / η_up

   附件列名为"爬升能耗效率"（0.72）。

3. **下降不单独计能耗** —— 附件"下降能耗效率 = 0"。

时间按爬升/巡航/下降三段相加（题目附录 2）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from src.physics.payload import UAVType, _check_payload, equivalent_range_m

GRAVITY_MS2 = 9.80665
"""标准重力加速度（m/s²）。"""

JOULE_PER_KWH = 3.6e6
"""1 kWh = 3.6e6 J。"""


@dataclass(frozen=True)
class Segment:
    """一个航段的几何量（由 `geo/leg.py` 生成，物理层不关心它怎么算出来的）。

    Attributes
    ----------
    distance_m : 水平巡航距离 d_ij（m）
    climb_m : 爬升高度 h⁺_ij（m）
    descent_m : 下降高度 h⁻_ij（m）
    """

    distance_m: float
    climb_m: float = 0.0
    descent_m: float = 0.0

    def __post_init__(self) -> None:
        if self.distance_m < -1e-9:
            raise ValueError(f"水平距离不得为负：{self.distance_m}")
        if self.climb_m < -1e-9:
            raise ValueError(f"爬升高度不得为负：{self.climb_m}")
        if self.descent_m < -1e-9:
            raise ValueError(f"下降高度不得为负：{self.descent_m}")


def segment_time_s(uav: UAVType, seg: Segment) -> float:
    """航段飞行时间（s）：t = h⁺/v↑ + d/v_c + h⁻/v↓。"""
    return (
        seg.climb_m / uav.climb_speed_ms
        + seg.distance_m / uav.cruise_speed_ms
        + seg.descent_m / uav.descent_speed_ms
    )


def horizontal_energy_kwh(uav: UAVType, distance_m: float, payload_kg: float) -> float:
    """水平巡航能耗（kWh）：E = (d / L_g(q)) · E_g^use。"""
    if distance_m < 0:
        raise ValueError("水平距离不得为负")
    if distance_m == 0.0:
        return 0.0
    payload = _check_payload(uav, payload_kg)
    rng = equivalent_range_m(uav, payload)
    if rng <= 0:
        raise ValueError(
            f"机型 {uav.code} 在载荷 {payload:.3f} kg 下等效航程为 {rng:.1f} m，无法执行该航段"
        )
    return distance_m / rng * uav.energy_kwh


def climb_energy_kwh(uav: UAVType, mass_kg: float, climb_m: float) -> float:
    """爬升附加能耗（kWh）：E = m·g·h⁺ / η_up。"""
    if climb_m < 0:
        raise ValueError("爬升高度不得为负")
    if climb_m == 0.0:
        return 0.0
    eta = uav.climb_efficiency
    if eta <= 0:
        raise ValueError(
            f"机型 {uav.code} 的爬升能耗效率为 {eta}，无法计算爬升能耗"
        )
    return mass_kg * GRAVITY_MS2 * climb_m / eta / JOULE_PER_KWH


def segment_energy_kwh(uav: UAVType, seg: Segment, payload_kg: float) -> float:
    """航段总能耗（kWh）= 水平巡航 + 爬升附加（**下降不单独计**）。"""
    payload = _check_payload(uav, payload_kg)
    e_hor = horizontal_energy_kwh(uav, seg.distance_m, payload)
    e_up = climb_energy_kwh(uav, uav.empty_mass_kg + payload, seg.climb_m)
    return e_hor + e_up


def sortie_energy_kwh(
    uav: UAVType,
    outbound: tuple[Segment, float],
    inbound: tuple[Segment, float],
) -> float:
    """单点往返架次的总能耗（kWh）。

    参数
    ----
    outbound : (去程航段, 去程载荷) —— 去程载货
    inbound  : (回程航段, 回程载荷) —— **必须为 0**（回程空载）

    说明
    ----
    题目规定返航为安全余量约束 `E_p^T ≤ (1−ρ_g)·E_g^use`，
    且每个架次完成投送后返回 O01，因此回程必为空载。
    传入非零回程载荷会被显式拒绝，以防把去程载荷误用到回程。
    """
    seg_out, q_out = outbound
    seg_in, q_in = inbound
    if abs(q_in) > 1e-12:
        raise ValueError(
            f"回程必须空载，但收到 {q_in} kg —— 请检查是否误用了去程载荷"
        )
    return segment_energy_kwh(uav, seg_out, q_out) + segment_energy_kwh(
        uav, seg_in, 0.0
    )


def energy_budget_kwh(uav: UAVType) -> float:
    """架次能量上限：(1 − ρ_g) · E_g^use。"""
    return uav.energy_budget_kwh


def reserve_soc(uav: UAVType) -> float:
    """返航后剩余 SOC（小数）：即返航电量下限 ρ_g。"""
    return uav.reserve_ratio
