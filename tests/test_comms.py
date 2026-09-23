"""通信层单元测试（题目附录 3）。

覆盖：
    - FSPL 公式与单位（f 用 MHz、D 用 **km**）
    - 单向 / 双向链路预算（双向取**较小值**）
    - 地形遮挡：有/无遮挡、视线上方掠过、地形穿透
    - 单链路可用性判定的边界（恰好等于门限）
    - 三态服务判定（直连 / 中继 / 中断）及优先级
    - 中继必须**两段同时可用**；不允许多跳
"""

from __future__ import annotations

import math

import pytest

from src.comms.link import (
    CommsParams,
    Endpoint,
    EndpointKind,
    DEFAULT_PARAMS,
    direction_max_loss_db,
    fspl_db,
    link_available,
    path_loss_db,
    bidirectional_max_loss_db,
)
from src.comms.los import has_terrain_obstruction, terrain_obstruction
from src.comms.service import (
    CommState,
    ServiceContext,
    access_ok,
    backhaul_ok,
    comm_status,
    direct_ok,
    relay_ok,
)
from src.geo.dem import AnalyticElevationProvider


# ================================================================ FSPL

def test_fspl_reference_value() -> None:
    """FSPL = 32.45 + 20log10(f_MHz) + 20log10(D_km)。

    f = 2400 MHz，D = 1 km：
        32.45 + 20*log10(2400) + 20*log10(1)
      = 32.45 + 67.6042 + 0 = 100.0542 dB
    """
    assert fspl_db(frequency_mhz=2400.0, distance_m=1000.0) == pytest.approx(
        100.0542, abs=1e-3
    )


def test_fspl_unit_is_km_not_m() -> None:
    """★ 单位陷阱：距离必须按 km 代入，差 1000 倍即差 60 dB。"""
    d_km = fspl_db(2400.0, 1000.0)
    d_if_misused = 32.45 + 20 * math.log10(2400.0) + 20 * math.log10(1000.0)
    assert d_if_misused - d_km == pytest.approx(60.0, abs=1e-9)


def test_fspl_increases_6db_per_doubling() -> None:
    """距离翻倍 → FSPL 增加约 6.02 dB。"""
    a = fspl_db(2400.0, 1000.0)
    b = fspl_db(2400.0, 2000.0)
    assert b - a == pytest.approx(6.0206, abs=1e-3)


def test_fspl_increases_6db_per_frequency_doubling() -> None:
    a = fspl_db(1000.0, 1000.0)
    b = fspl_db(2000.0, 1000.0)
    assert b - a == pytest.approx(6.0206, abs=1e-3)


def test_fspl_rejects_nonpositive() -> None:
    with pytest.raises(ValueError):
        fspl_db(2400.0, 0.0)
    with pytest.raises(ValueError):
        fspl_db(0.0, 100.0)


# ================================================================ 链路预算

def test_receiver_threshold() -> None:
    """P_th = P_sens + M = −98 + 8 = −90 dBm。"""
    assert DEFAULT_PARAMS.receiver_threshold_dbm == pytest.approx(-90.0)


def test_direction_max_loss_matches_hand_calc() -> None:
    """★ 各方向门限与手算一致（附件参数实测）。

    运输机 → G01 : 20 + 3 + 12 − 3 − (−90) = 122
    G01 → 运输机 : 27 + 12 + 3 − 3 − (−90) = 129
    中继接入 → 运输机 : 20 + 6 + 3 − 3 + 90 = 116
    中继回传 → G01 : 19 + 8 + 12 − 3 + 90 = 126
    """
    p = DEFAULT_PARAMS
    assert direction_max_loss_db(p, EndpointKind.TRANSPORT, EndpointKind.GATEWAY) == pytest.approx(122.0)
    assert direction_max_loss_db(p, EndpointKind.GATEWAY, EndpointKind.TRANSPORT) == pytest.approx(129.0)
    assert direction_max_loss_db(p, EndpointKind.RELAY_ACCESS, EndpointKind.TRANSPORT) == pytest.approx(116.0)
    assert direction_max_loss_db(p, EndpointKind.TRANSPORT, EndpointKind.RELAY_ACCESS) == pytest.approx(116.0)
    assert direction_max_loss_db(p, EndpointKind.RELAY_BACKHAUL, EndpointKind.GATEWAY) == pytest.approx(126.0)
    assert direction_max_loss_db(p, EndpointKind.GATEWAY, EndpointKind.RELAY_BACKHAUL) == pytest.approx(134.0)


def test_bidirectional_takes_minimum() -> None:
    """★ 双向门限取两方向的**较小值**（题目明确要求）。"""
    p = DEFAULT_PARAMS
    e1, e2 = EndpointKind.TRANSPORT, EndpointKind.GATEWAY
    fwd = direction_max_loss_db(p, e1, e2)
    rev = direction_max_loss_db(p, e2, e1)
    assert bidirectional_max_loss_db(p, e1, e2) == pytest.approx(min(fwd, rev))
    assert bidirectional_max_loss_db(p, e1, e2) == pytest.approx(122.0)
    # 对称性
    assert bidirectional_max_loss_db(p, e1, e2) == pytest.approx(
        bidirectional_max_loss_db(p, e2, e1)
    )


def test_three_link_budgets_ordering() -> None:
    """三条链路的双向门限：直连 122 > 中继接入 116，回传 126。

    ★ 这解释了"中继并不总是更好"：中继接入段门限比直连低 6 dB。
    """
    p = DEFAULT_PARAMS
    direct = bidirectional_max_loss_db(p, EndpointKind.TRANSPORT, EndpointKind.GATEWAY)
    access = bidirectional_max_loss_db(p, EndpointKind.TRANSPORT, EndpointKind.RELAY_ACCESS)
    backhaul = bidirectional_max_loss_db(p, EndpointKind.RELAY_BACKHAUL, EndpointKind.GATEWAY)
    assert direct == pytest.approx(122.0)
    assert access == pytest.approx(116.0)
    assert backhaul == pytest.approx(126.0)
    assert access < direct < backhaul


def test_path_loss_with_obstruction() -> None:
    """总损耗 = FSPL + L_obs·b。"""
    p = DEFAULT_PARAMS
    fspl = fspl_db(p.frequency_mhz, 5000.0)
    assert path_loss_db(p, 5000.0, obstructed=False) == pytest.approx(fspl)
    assert path_loss_db(p, 5000.0, obstructed=True) == pytest.approx(
        fspl + p.obstruction_loss_db
    )
    assert p.obstruction_loss_db == pytest.approx(10.0)


def test_link_available_boundary() -> None:
    """落在门限上算**可用**（≤ 判定）。"""
    assert link_available(122.0, 122.0)
    assert not link_available(122.0001, 122.0)
    assert link_available(121.9, 122.0)


def test_link_available_realistic_direct_range() -> None:
    """直连可用时，自由空间距离上限 ≈ 反解 FSPL = 122 dB → **12.511 km**。

    122 = 32.45 + 20log10(2400) + 20log10(D_km)
    ⇒ 20log10(D_km) = 21.9458 ⇒ D_km = 10^1.09729 = 12.5109 km
    """
    p = DEFAULT_PARAMS
    d_km = 10 ** ((122.0 - 32.45 - 20 * math.log10(2400.0)) / 20)
    assert d_km == pytest.approx(12.511, abs=1e-3)
    assert link_available(path_loss_db(p, d_km * 1000 * 0.99, False), 122.0)
    assert not link_available(path_loss_db(p, d_km * 1000 * 1.01, False), 122.0)


def test_free_space_range_thresholds() -> None:
    """★ 三条链路的自由空间可达距离（本层最重要的定量结论）。

    | 链路 | 双向门限 | 可达距离 |
    |---|---|---|
    | 直连（运输机↔G01） | 122 dB | **12.511 km** |
    | 中继接入（运输机↔中继） | 116 dB | **6.270 km** |
    | 中继回传（中继↔G01） | 126 dB | **19.828 km** |

    结论：**中继接入段是最弱的一环**。
    因此中继只在「直连被地形遮挡」或「接力几何明显优于直连」时才有价值，
    并不是"加了中继就一定更好"。
    """
    p = DEFAULT_PARAMS

    def dmax(threshold_db: float) -> float:
        return 10 ** ((threshold_db - 32.45 - 20 * math.log10(2400.0)) / 20)

    assert dmax(122.0) == pytest.approx(12.511, abs=1e-3)  # 直连
    assert dmax(116.0) == pytest.approx(6.270, abs=1e-3)  # 中继接入
    assert dmax(126.0) == pytest.approx(19.828, abs=1e-3)  # 中继回传

    # 含 10 dB 遮挡损耗后的等效距离
    assert dmax(122.0 - 10.0) == pytest.approx(3.956, abs=1e-3)
    assert dmax(116.0 - 10.0) == pytest.approx(2.0, abs=0.02)


# ================================================================ 地形遮挡

def test_no_obstruction_over_flat_terrain() -> None:
    """平地 + 两端抬高 → 视线无遮挡。"""
    prov = AnalyticElevationProvider(base=100.0)
    assert not has_terrain_obstruction(prov, 109.23, 23.01, 150.0, 109.25, 23.03, 150.0)


def test_obstruction_by_ridge() -> None:
    """★ 中间有高脊 → 视线被遮挡。"""

    class Ridge:
        def __init__(self) -> None:
            self._bounds = (109.0, 22.85, 109.5, 23.25)

        def elevation_at(self, lon: float, lat: float) -> float:
            return 600.0 if abs(lon - 109.24) < 0.005 else 100.0

        @property
        def bounds(self):
            return self._bounds

    prov = Ridge()
    # 两端都在 200 m 高度，中间地形 600 m → 遮挡
    assert has_terrain_obstruction(prov, 109.23, 23.01, 200.0, 109.25, 23.01, 200.0)


def test_clearance_above_ridge_no_obstruction() -> None:
    """端点抬高到足够高 → 视线越过山脊，无遮挡。"""

    class Ridge:
        def __init__(self) -> None:
            self._bounds = (109.0, 22.85, 109.5, 23.25)

        def elevation_at(self, lon: float, lat: float) -> float:
            return 600.0 if abs(lon - 109.24) < 0.005 else 100.0

        @property
        def bounds(self):
            return self._bounds

    prov = Ridge()
    assert not has_terrain_obstruction(
        prov, 109.23, 23.01, 700.0, 109.25, 23.01, 700.0
    )


def test_obstruction_returns_worst_margin() -> None:
    """返回的是最差余量（地形 − 视线），正值表示被遮挡。"""

    class Ridge:
        def __init__(self) -> None:
            self._bounds = (109.0, 22.85, 109.5, 23.25)

        def elevation_at(self, lon: float, lat: float) -> float:
            return 600.0 if abs(lon - 109.24) < 0.005 else 100.0

        @property
        def bounds(self):
            return self._bounds

    prov = Ridge()
    margin, flag = terrain_obstruction(prov, 109.23, 23.01, 200.0, 109.25, 23.01, 200.0)
    assert flag is True
    assert margin > 300.0


def test_obstruction_ignores_out_of_bounds() -> None:
    """采样越界应被跳过而不是抛异常（DEM 覆盖可能不完全）。"""

    class Tiny:
        def __init__(self) -> None:
            self._bounds = (109.239, 23.009, 109.241, 23.011)

        def elevation_at(self, lon: float, lat: float) -> float:
            from src.geo.dem import OutOfBoundsError

            lo, la, hi, ha = self._bounds
            if not (lo <= lon <= hi and la <= lat <= ha):
                raise OutOfBoundsError("out")
            return 100.0

        @property
        def bounds(self):
            return self._bounds

    prov = Tiny()
    # 整条线几乎都在范围外，但不应抛异常（返回无遮挡/或按实现处理）
    margin, flag = terrain_obstruction(prov, 109.0, 23.0, 200.0, 109.5, 23.0, 200.0)
    assert isinstance(flag, bool)


# ================================================================ 三态服务判定

def _ctx(**kw) -> ServiceContext:
    base = dict(
        uav_lon=109.230852,
        uav_lat=23.008509,
        uav_alt_m=200.0,
        gateway_lon=109.230852,
        gateway_lat=23.008509,
        gateway_alt_m=147.7,
        relay=None,
    )
    base.update(kw)
    return ServiceContext(**base)


def test_direct_when_link_ok() -> None:
    """近距离高空 → 直连。"""
    prov = AnalyticElevationProvider(base=100.0)
    st = comm_status(_ctx(), DEFAULT_PARAMS, prov)
    assert st is CommState.DIRECT


def test_direct_still_ok_at_8km_flat() -> None:
    """8 km 平地仍在直连极限（12.51 km）之内 → 直连。"""
    prov = AnalyticElevationProvider(base=100.0)
    ctx = _ctx(uav_lon=109.3090, uav_lat=23.0085, uav_alt_m=200.0)
    assert direct_ok(ctx, DEFAULT_PARAMS, prov)


def test_outage_when_too_far() -> None:
    """远离网关且无中继 → 中断（13.2 km 已超 12.51 km 极限）。"""
    prov = AnalyticElevationProvider(base=100.0)
    far = _ctx(uav_lon=109.3600, uav_lat=23.0085, uav_alt_m=200.0)
    assert not direct_ok(far, DEFAULT_PARAMS, prov)
    assert comm_status(far, DEFAULT_PARAMS, prov) is CommState.OUTAGE


def test_flat_terrain_never_needs_relay() -> None:
    """★ 平地场景下，只要直连可达就永远走直连（中继接入段门限更低）。

    这说明中继的价值来自**地形遮挡**或**接力几何优势**，而非"多一层更保险"。
    """
    prov = AnalyticElevationProvider(base=100.0)
    for lon in (109.2320, 109.2600, 109.3090):
        ctx = _ctx(uav_lon=lon, uav_lat=23.0085, uav_alt_m=200.0)
        assert comm_status(ctx, DEFAULT_PARAMS, prov) is CommState.DIRECT


class _Ridge:
    """南北走向的山脊，位于 lon = 109.240 处，峰值 900 m；其余为 100 m 平地。"""

    _bounds = (109.0, 22.85, 109.5, 23.25)

    def elevation_at(self, lon: float, lat: float) -> float:
        return 900.0 if abs(lon - 109.240) < 0.004 else 100.0

    @property
    def bounds(self):
        return self._bounds


def test_relay_when_direct_fails_but_relay_works() -> None:
    """★ 直连被地形遮挡且超出遮挡后极限，但中继两段均可用 → 中继。

    几何设计（阈值见 `test_free_space_range_thresholds`）：
      - 运输机在 6 km 处，视线穿过山脊 → 直连损耗 ≈ FSPL(6km) + 10 > 122 dB
      - 中继高悬 1200 m 于山脊上方：
          接入段 < 6.27 km（且无遮挡）
          回传段 < 19.83 km（且无遮挡）
    """
    ctx = _ctx(
        uav_lon=109.2820,
        uav_lat=23.0085,
        uav_alt_m=250.0,
        relay=(109.2400, 23.0192, 1200.0),
    )
    ridge = _Ridge()
    assert not direct_ok(ctx, DEFAULT_PARAMS, ridge), "直连应因遮挡+距离而不可用"
    assert access_ok(ctx, DEFAULT_PARAMS, ridge), "接入段应可用"
    assert backhaul_ok(ctx, DEFAULT_PARAMS, ridge), "回传段应可用"
    assert comm_status(ctx, DEFAULT_PARAMS, ridge) is CommState.RELAY


def test_relay_loses_when_access_leg_too_long() -> None:
    """★ 中继要求两段**同时**可用 —— 用"接入段超距、回传段正常"来隔离这一条。

    几何（阈值：接入 6.27 km、回传 19.83 km、直连 12.51 km）：
      - 运输机在 5 km 处：直连 5 km < 12.51 km，**直连本身可用**
      - 中继放在 11.5 km 处：
          接入段 = |11.5 − 5| = 6.5 km > **6.27 km** → 接入不可用
          回传段 = 11.5 km < 19.83 km → 回传可用
      - 因此中继不可用；又因题目优先级是「直连可用即直连」，
        该时刻状态为**直连**。

    若把中继换到 6 km 处（接入 1 km < 6.27 km），中继即变为可用 ——
    但直连仍优先，故状态不变。这说明**判定逻辑正确**：
    中继只有在直连失败时才被采用。
    """
    flat = AnalyticElevationProvider(base=100.0)

    uav_5km = _ctx(uav_lon=109.2765, uav_lat=23.0085, uav_alt_m=250.0)
    relay_far = (109.3445, 23.0085, 400.0)   # ≈ 11.5 km
    relay_ok_pos = (109.2885, 23.0085, 400.0)  # ≈ 6 km

    ctx_far = _ctx(
        uav_lon=uav_5km.uav_lon, uav_lat=uav_5km.uav_lat, uav_alt_m=250.0,
        relay=relay_far,
    )
    ctx_near = _ctx(
        uav_lon=uav_5km.uav_lon, uav_lat=uav_5km.uav_lat, uav_alt_m=250.0,
        relay=relay_ok_pos,
    )

    # 接入段：远的失败、近的成立
    assert not access_ok(ctx_far, DEFAULT_PARAMS, flat), "接入段超 6.27 km 应不可用"
    assert access_ok(ctx_near, DEFAULT_PARAMS, flat), "接入段 1 km 应可用"
    # 回传段两者都成立
    assert backhaul_ok(ctx_far, DEFAULT_PARAMS, flat), "回传段 11.5 km < 19.83 km 应可用"

    # relay_ok = 两段同时可用
    assert not relay_ok(ctx_far, DEFAULT_PARAMS, flat)
    assert relay_ok(ctx_near, DEFAULT_PARAMS, flat)


def test_relay_requires_both_legs_access_blocked() -> None:
    """★ 两段**同时**可用是硬要求：接入段被遮挡 → 中继整体不可用。

    几何：在**运输机与中继之间**（lon ≈ 109.2610）加一道 2000 m 高脊。
    它不在中继→G01 的回传路径上，因此回传仍可用 —— 精确隔离出
    "接入段失败即中继失败"这一条。

    注：本测试用**遮挡**而非超距来切断接入段，原因是几何上的耦合 ——
    中继必须靠近运输机才能维持接入链路，而中继又必须靠近网关才能维持回传；
    在中继离网关较远时，接入段与回传段会**同时**变长，
    因此无法用"单纯超距"把两段的影响分离开。
    """

    class AccessBlocker:
        """在中继与运输机之间加一道高脊，且运输机侧也有山脊（切断直连）。"""

        _bounds = (109.0, 22.85, 109.5, 23.25)

        def elevation_at(self, lon: float, lat: float) -> float:
            if abs(lon - 109.2610) < 0.0015:   # 运输机→中继 之间的高脊
                return 2000.0
            if abs(lon - 109.240) < 0.004:     # 主山脊，切断直连
                return 900.0
            return 100.0

        @property
        def bounds(self):
            return self._bounds

    ctx = _ctx(
        uav_lon=109.2820,
        uav_lat=23.0085,
        uav_alt_m=250.0,
        relay=(109.2400, 23.0192, 1200.0),
    )
    prov = AccessBlocker()
    assert not direct_ok(ctx, DEFAULT_PARAMS, prov), "直连应被主山脊切断"
    assert not access_ok(ctx, DEFAULT_PARAMS, prov), "接入段应被高脊遮挡"
    assert backhaul_ok(ctx, DEFAULT_PARAMS, prov), "回传段不受影响，应仍可用"
    assert not relay_ok(ctx, DEFAULT_PARAMS, prov), "接入段失败 → 中继不可用"
    assert comm_status(ctx, DEFAULT_PARAMS, prov) is CommState.OUTAGE


def test_relay_is_used_only_when_direct_fails() -> None:
    """★ 优先级验证：直连失败且两段可用时，才落到"中继"状态。"""
    ctx = _ctx(
        uav_lon=109.2820,
        uav_lat=23.0085,
        uav_alt_m=250.0,
        relay=(109.2400, 23.0192, 1200.0),
    )
    ridge = _Ridge()
    assert not direct_ok(ctx, DEFAULT_PARAMS, ridge)
    assert relay_ok(ctx, DEFAULT_PARAMS, ridge)
    assert comm_status(ctx, DEFAULT_PARAMS, ridge) is CommState.RELAY


def test_no_relay_means_no_relay_state() -> None:
    """未提供中继位置时，relay_ok 必须为 False（不能"凭空"有中继）。"""
    prov = AnalyticElevationProvider(base=100.0)
    far = _ctx(uav_lon=109.3600, uav_lat=23.0085, uav_alt_m=200.0, relay=None)
    assert not relay_ok(far, DEFAULT_PARAMS, prov)
    assert comm_status(far, DEFAULT_PARAMS, prov) is CommState.OUTAGE


def test_obstruction_can_break_link() -> None:
    """★ 遮挡的代价是固定的 10 dB，因此它**只在距离接近极限时**才导致中断。

    设计：把运输机放在 6 km 处（FSPL ≈ 113.6 dB）。
      - 平地：113.6 ≤ 122 → 直连
      - 有山脊遮挡：123.6 > 122 → 中断
    这量化了"10 dB 遮挡损耗"的实际影响范围：
    等效于把可用距离从 12.51 km 压缩到 3.96 km。
    """
    flat = AnalyticElevationProvider(base=100.0)
    ctx = _ctx(uav_lon=109.2820, uav_lat=23.0085, uav_alt_m=250.0)
    assert comm_status(ctx, DEFAULT_PARAMS, flat) is CommState.DIRECT
    assert comm_status(ctx, DEFAULT_PARAMS, _Ridge()) is CommState.OUTAGE


def test_obstruction_alone_does_not_break_short_link() -> None:
    """回归：短距离（<3.96 km）即使被遮挡，10 dB 也不足以让链路中断。

    这条测试固化一个容易被误解的点：**遮挡不等于中断**。
    """
    short = _ctx(uav_lon=109.2450, uav_lat=23.0300, uav_alt_m=350.0)
    assert has_terrain_obstruction(
        _Ridge(), short.uav_lon, short.uav_lat, short.uav_alt_m,
        short.gateway_lon, short.gateway_lat, short.gateway_alt_m,
    ), "该几何确实被山脊遮挡"
    assert direct_ok(short, DEFAULT_PARAMS, _Ridge()), "但短距离下 10 dB 不足以中断"


def test_comm_state_values() -> None:
    assert CommState.DIRECT.value == "直连"
    assert CommState.RELAY.value == "中继"
    assert CommState.OUTAGE.value == "中断"


def test_endpoint_kinds_covered() -> None:
    """附件四类端点都要有参数。"""
    p = DEFAULT_PARAMS
    for k in (
        EndpointKind.TRANSPORT,
        EndpointKind.RELAY_ACCESS,
        EndpointKind.RELAY_BACKHAUL,
        EndpointKind.GATEWAY,
    ):
        e: Endpoint = p.endpoint(k)
        assert e.antenna_gain_dbi > 0
