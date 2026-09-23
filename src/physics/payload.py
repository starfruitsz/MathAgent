"""载荷-航程关系与最大安全载荷（问题一的核心）。

口径来源：题目附录 2。

    L_g(q) = L_g0 − (L_g0 − L_gF) · (q / Q_g)^(3/2),   0 ≤ q ≤ Q_g

★ 指数是 **3/2**，不是 1 或 2。附件实测确认（见 docs/DATA_NOTES.md 第 3 节）。

为什么最大安全载荷要**数值反解**：
    能量约束 `E_g^T(q) = (1−ρ_g)·E_g^use` 中，E 经由 L_g(q) 与 q 呈非线性关系，
    而 (q/Q)^{3/2} 没有初等反函数 → 用单调性 + brentq 求根。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from scipy.optimize import brentq

from src.common.config import PAYLOAD_RANGE_EXPONENT, PAYLOAD_ROOT_TOL


@dataclass(frozen=True)
class UAVType:
    """运输无人机机型参数（字段名对应附件"运输无人机数据.xlsx"）。"""

    code: str
    """机型编号，A / B / C。"""
    name: str
    """机型名称。"""
    empty_mass_kg: float
    """含电池空载总质量（kg）。"""
    max_payload_kg: float
    """最大载货质量 Q_g（kg）—— 结构硬上限。"""
    volume_m3: float
    """可用装载体积（m³）—— 结构硬上限。"""
    cruise_speed_ms: float
    """计划巡航速度 v_g^c（m/s）。"""
    range_empty_m: float
    """空载标准航程 L_g0（m）。"""
    range_full_m: float
    """满载标准航程 L_gF（m）。"""
    energy_kwh: float
    """电池可用能量 E_g^use（kWh）。"""
    reserve_ratio: float
    """返航电量下限 ρ_g（0~1 小数）。附件为 20% → 0.20。"""
    climb_speed_ms: float
    """最大爬升速度 v_g↑（m/s）。"""
    descent_speed_ms: float
    """最大下降速度 v_g↓（m/s）。"""
    climb_efficiency: float
    """爬升能耗效率 η_up（附件值 0.72，见 ADR-020）。"""
    descent_efficiency: float
    """下降能耗效率（附件值 0，表示不单独计下降能耗）。"""
    prepare_time_s: float = 0.0
    """工位固定准备时间（s）。"""
    box_load_time_s: float = 0.0
    """每箱装载时间（s）。"""
    handover_base_s: float = 0.0
    """接收点基础交接时间（s）。"""
    handover_per_box_s: float = 0.0
    """每箱增加交接时间（s）。"""

    @property
    def energy_budget_kwh(self) -> float:
        """可用于飞行的能量上限（已扣除返航安全余量）：(1−ρ_g)·E_g^use。"""
        return (1.0 - self.reserve_ratio) * self.energy_kwh

    def __post_init__(self) -> None:
        if self.max_payload_kg <= 0:
            raise ValueError("最大载货质量必须为正")
        if not 0.0 <= self.reserve_ratio < 1.0:
            raise ValueError("返航安全余量比例必须在 [0, 1) 内")
        if self.range_empty_m <= 0 or self.range_full_m <= 0:
            raise ValueError("标准航程必须为正")
        if self.range_full_m > self.range_empty_m:
            raise ValueError("满载航程不应大于空载航程")
        if self.energy_kwh <= 0:
            raise ValueError("电池可用能量必须为正")


def payload_fraction(uav: UAVType, payload_kg: float) -> float:
    """载荷比 q / Q_g ∈ [0, 1]。"""
    q = _check_payload(uav, payload_kg)
    return q / uav.max_payload_kg


def _check_payload(uav: UAVType, payload_kg: float) -> float:
    if payload_kg < 0:
        raise ValueError(f"载荷不得为负：{payload_kg}")
    if payload_kg > uav.max_payload_kg + 1e-9:
        raise ValueError(
            f"载荷 {payload_kg} 超过机型 {uav.code} 的最大载货质量 {uav.max_payload_kg}"
        )
    return min(payload_kg, uav.max_payload_kg)


def equivalent_range_m(uav: UAVType, payload_kg: float) -> float:
    """载荷为 q 时的等效航程 L_g(q)（m）。

    性质（由 tests/test_physics.py 锁死）：
        L_g(0)   = L_g0
        L_g(Q_g) = L_gF
        关于 q 单调不增且**凸**（因 (q/Q)^{3/2} 是凸函数）
    """
    q = _check_payload(uav, payload_kg)
    ratio = (q / uav.max_payload_kg) ** PAYLOAD_RANGE_EXPONENT
    return uav.range_empty_m - (uav.range_empty_m - uav.range_full_m) * ratio


def max_safe_payload(
    uav: UAVType,
    horizontal_distance_m: float,
    climb_out_m: float = 0.0,
    descent_out_m: float = 0.0,
    climb_back_m: float = 0.0,
    descent_back_m: float = 0.0,
) -> float:
    """单点往返任务下的**最大安全载荷**（kg）。

    定义：使往返总能耗恰好等于能量预算的载荷。

        E_g^T(q; 航段) = (1 − ρ_g) · E_g^use

    去程载货 q、回程空载。

    参数
    ----
    horizontal_distance_m : 往返的水平巡航距离（同一航段来回，故只传一个 d）
    climb_out_m, descent_out_m : 去程爬升/下降高度
    climb_back_m, descent_back_m : 回程爬升/下降高度

    返回
    ----
    q_max ∈ [0, Q_g]。若距离太大导致连空载都飞不到，抛 ValueError。

    实现
    ----
    总能耗关于 q **单调递增**（载荷↑ → 等效航程↓ → 单位距离能耗↑），
    因此在 [0, Q_g] 上用 brentq 求根；若端点处预算仍有余，则结构上限 Q_g 起作用。
    """
    from src.physics.energy import Segment, sortie_energy_kwh

    if horizontal_distance_m < 0:
        raise ValueError("水平距离不得为负")

    seg_out = Segment(horizontal_distance_m, climb_out_m, descent_out_m)
    seg_back = Segment(horizontal_distance_m, climb_back_m, descent_back_m)
    budget = uav.energy_budget_kwh

    def deficit(q: float) -> float:
        """已用能量 − 预算；根即使约束取等号。"""
        used = sortie_energy_kwh(uav, outbound=(seg_out, q), inbound=(seg_back, 0.0))
        return used - budget

    # 空载都超预算 → 该机型无法执行此任务
    if deficit(0.0) > 0:
        raise ValueError(
            f"机型 {uav.code} 在水平距离 {horizontal_distance_m:.0f} m 处"
            f"即使空载也超出能量预算（空载已用 {deficit(0.0) + budget:.4f} kWh，"
            f"预算 {budget:.4f} kWh）"
        )
    # 满载仍在预算内 → 结构上限起作用
    if deficit(uav.max_payload_kg) <= 0:
        return uav.max_payload_kg

    return float(
        brentq(deficit, 0.0, uav.max_payload_kg, xtol=PAYLOAD_ROOT_TOL, rtol=1e-12)
    )
