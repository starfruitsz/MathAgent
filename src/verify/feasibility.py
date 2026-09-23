"""可行性校验器（★ 铁律 R8）。

设计原则
--------
1. **独立于求解器**：本模块只依赖 `physics/`、`comms/` 与它自己收到的方案数据，
   不 import 任何 `qN_*` 模块。求解器与校验器同源会"自证清白"。
2. **从零重算**：所有能耗、时间、SOC 都由物理层**重新计算**，
   并与方案上报值比对 —— 上报值不一致本身就是一种违规。
3. **负样本可测**：每种违规都有对应的 `ViolationType`，
   且 `tests/test_verify.py` 用**故意构造的违规方案**逐条验证能抓到。

校验项
------
运输（Q1–Q3 通用）：
    - 货箱：存在性、重复交付、缺失、与服务区匹配
    - 载荷：质量上限 Q_g、体积上限
    - 能量：架次总能耗 ≤ (1−ρ_g)·E_g^use；上报值一致性；返航 SOC
    - 时间：架次时长 ≥ 准备+装载+飞行+交接；首批截止；期望送达
    - 资源：无人机/电池的任务时段不重叠、机型与电池匹配、机队与库存规模
通信（Q3）：
    - 每个通信中断时段必须被某个中继架次完整覆盖
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from src.physics.battery import soc_after_energy
from src.physics.energy import Segment, segment_energy_kwh, segment_time_s
from src.physics.payload import UAVType
from src.verify._internal import DerivedStore, SortieDerived


class ViolationType(str, Enum):
    """违规类型。"""

    UNKNOWN_BOX = "未知货箱"
    DUPLICATE_BOX = "货箱重复交付"
    MISSING_BOX = "货箱缺失"
    BOX_SERVICE_MISMATCH = "货箱与服务区不匹配"
    MASS_OVERLOAD = "载质量超限"
    VOLUME_OVERLOAD = "装载体积超限"
    ENERGY_BUDGET_EXCEEDED = "超出能量预算"
    ENERGY_MISMATCH = "上报能耗与重算不一致"
    SOC_MISMATCH = "上报返航SOC与重算不一致"
    SOC_BELOW_RESERVE = "返航SOC低于下限"
    TIMING_INCONSISTENT = "架次时长不足以完成任务"
    FIRST_BATCH_DEADLINE_MISSED = "首批保障箱超时"
    EXPECTED_TIME_MISSED = "超出期望送达时间"
    RESOURCE_TIME_OVERLAP = "同一资源任务时段重叠"
    UNKNOWN_RESOURCE = "未知无人机/电池"
    FLEET_SIZE_EXCEEDED = "实体无人机数量超限"
    BATTERY_INVENTORY_EXCEEDED = "电池组数量超限"
    COMMS_UNSUPPORTED = "通信中断时段未获中继保障"


@dataclass(frozen=True)
class BoxBatch:
    """一个货箱（校验器视角）。"""

    box_id: str
    service_id: str
    mass_kg: float
    volume_m3: float
    is_first_batch: bool = False
    first_batch_deadline_s: float | None = None
    expected_time_s: float | None = None


@dataclass(frozen=True)
class Sortie:
    """一个运输架次（单点往返；多点访问时按顺序累加航段）。"""

    sortie_id: str
    uav_id: str
    type_code: str
    battery_id: str
    start_s: float
    service_sequence: tuple[str, ...]
    box_ids: tuple[str, ...]
    leg_distance_m: float
    """**单个**航段的水平距离（O01→S_i 或 S_i→S_{i+1}）。"""
    climb_out_m: float = 0.0
    descent_out_m: float = 0.0
    reported_energy_kwh: float | None = None
    reported_return_soc: float | None = None
    reported_delivery_times: dict[str, float] | None = None
    """{服务区: 交付完成时刻(s)}；None 表示不校验时间。"""
    outage_windows: tuple[tuple[float, float], ...] = ()
    """该架次的通信中断时段（绝对时刻，s）；Q3 用于检查中继覆盖。"""


@dataclass(frozen=True)
class RelayAssignment:
    """一个中继架次的服务窗口。"""

    relay_id: str
    start_s: float
    end_s: float
    sortie_ids: tuple[str, ...] = ()


@dataclass
class TransportPlan:
    """待校验的完整方案。"""

    sorties: tuple[Sortie, ...]
    relays: tuple[RelayAssignment, ...] = ()
    uav_fleet: dict[str, int] | None = None
    """{机型: 实体无人机台数}；None 表示不校验机队规模。"""
    battery_inventory: dict[str, int] | None = None
    """{机型: 电池组数}；None 表示不校验电池库存。"""
    known_uav_ids: frozenset[str] | None = None
    """机队中的实体无人机编号集合（如 U01–U08）；None 表示不校验编号合法性。"""
    known_battery_ids: frozenset[str] | None = None
    """共享电池编号集合；None 表示不校验编号合法性。"""
    uav_id_to_type: dict[str, str] | None = None
    """{无人机编号: 机型}；提供时会校验无人机与机型是否一致。"""


@dataclass(frozen=True)
class Violation:
    """一条违规记录。"""

    type: ViolationType
    sortie_id: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.type.value}] 架次 {self.sortie_id}：{self.detail}"


@dataclass
class VerifyReport:
    """校验报告。"""

    violations: list[Violation] = field(default_factory=list)
    n_sorties: int = 0
    n_boxes: int = 0
    total_energy_kwh: float = 0.0
    makespan_s: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.violations

    def has(self, t: ViolationType) -> bool:
        return any(v.type is t for v in self.violations)

    def count(self, t: ViolationType) -> int:
        return sum(1 for v in self.violations if v.type is t)

    def summary(self) -> str:
        if self.ok:
            return (
                f"✅ 方案可行：{self.n_sorties} 个架次 / {self.n_boxes} 个货箱 / "
                f"总能耗 {self.total_energy_kwh:.3f} kWh / 完工 {self.makespan_s:.1f} s"
            )
        lines = [f"❌ 发现 {len(self.violations)} 条违规："]
        lines += [f"   {v}" for v in self.violations[:20]]
        if len(self.violations) > 20:
            lines.append(f"   …（其余 {len(self.violations) - 20} 条略）")
        return "\n".join(lines)


# ---------------------------------------------------------------- 内部工具

def _sortie_energy(
    uav: UAVType, s: Sortie, d: SortieDerived
) -> tuple[float, float, float]:
    """重算架次的 (总能耗 kWh, 去程能耗 kWh, 总飞行时间 s)。

    单点往返模型：去程载货、回程空载，各飞一次 `leg_distance_m`。
    多点访问时按"每段几何相同、去程各段均按该架次总载荷计"的**保守**口径
    （偏保守 = 能耗估高 = 不会放过违规方案）。
    """
    seg_out = Segment(s.leg_distance_m, s.climb_out_m, s.descent_out_m)
    seg_back = Segment(s.leg_distance_m, s.descent_out_m, s.climb_out_m)

    payload = min(d.total_mass_kg, uav.max_payload_kg)
    e_out = segment_energy_kwh(uav, seg_out, payload)
    e_back = segment_energy_kwh(uav, seg_back, 0.0)

    n_legs = max(1, len(s.service_sequence))
    energy = (e_out + e_back) * n_legs
    t_fly = (segment_time_s(uav, seg_out) + segment_time_s(uav, seg_back)) * n_legs
    return energy, e_out, t_fly


def _compute_derived(
    plan: TransportPlan,
    uav_types: dict[str, UAVType],
    boxes: dict[str, BoxBatch],
) -> DerivedStore:
    """从零重算每个架次的载荷、能耗、SOC、结束时刻。"""
    store = DerivedStore()
    for s in plan.sorties:
        d = store.get(s.sortie_id)
        d.total_mass_kg = sum(boxes[b].mass_kg for b in s.box_ids if b in boxes)
        d.total_volume_m3 = sum(boxes[b].volume_m3 for b in s.box_ids if b in boxes)
        uav = uav_types.get(s.type_code)
        if uav is None:
            continue
        d.energy_kwh, _, d.flight_time_s = _sortie_energy(uav, s, d)
        d.return_soc = soc_after_energy(d.energy_kwh, uav.energy_kwh)
        d.end_s = _sortie_end_s(s, uav, d)
    return store


# ---------------------------------------------------------------- 主校验

def verify_transport_plan(
    plan: TransportPlan,
    uav_types: dict[str, UAVType],
    boxes: dict[str, BoxBatch],
    energy_rel_tol: float = 1e-3,
    soc_abs_tol: float = 1e-3,
    time_tol_s: float = 1.0,
) -> VerifyReport:
    """校验运输方案的全部硬约束，返回 `VerifyReport`。"""
    rep = VerifyReport()
    rep.n_sorties = len(plan.sorties)

    # 从零重算派生量（不信任方案上报值）
    derived = _compute_derived(plan, uav_types, boxes)

    delivered: list[str] = []
    for s in plan.sorties:
        _check_boxes(s, boxes, rep, delivered)
        uav = uav_types.get(s.type_code)
        if uav is None:
            rep.violations.append(
                Violation(ViolationType.UNKNOWN_RESOURCE, s.sortie_id,
                          f"未知机型 {s.type_code}")
            )
            continue
        d = derived.get(s.sortie_id)
        _check_load(s, uav, rep, d)
        _check_energy(s, uav, rep, d, energy_rel_tol, soc_abs_tol)
        _check_timing(s, uav, boxes, rep, d, time_tol_s)
        rep.total_energy_kwh += d.energy_kwh
        rep.makespan_s = max(rep.makespan_s, d.end_s)

    # 全部货箱必须交付且只交付一次
    check_all_boxes_delivered(plan, boxes, rep)

    _check_resources(plan, uav_types, derived, rep)
    _check_comms(plan, rep)

    rep.n_boxes = len({b for s in plan.sorties for b in s.box_ids})
    return rep


# ---------------------------------------------------------------- 分项检查

def _check_boxes(
    s: Sortie, boxes: dict[str, BoxBatch], rep: VerifyReport, delivered: list[str]
) -> None:
    for b in s.box_ids:
        if b not in boxes:
            rep.violations.append(
                Violation(ViolationType.UNKNOWN_BOX, s.sortie_id, f"货箱 {b} 不存在")
            )
            continue
        if b in delivered:
            rep.violations.append(
                Violation(ViolationType.DUPLICATE_BOX, s.sortie_id, f"货箱 {b} 被重复交付")
            )
        delivered.append(b)
        if boxes[b].service_id not in s.service_sequence:
            rep.violations.append(
                Violation(
                    ViolationType.BOX_SERVICE_MISMATCH,
                    s.sortie_id,
                    f"货箱 {b} 属于 {boxes[b].service_id}，但访问序列为 {s.service_sequence}",
                )
            )
    # 缺箱检查放在最后统一做（见 verify_transport_plan 末尾）


def _check_load(s: Sortie, uav: UAVType, rep: VerifyReport, d: SortieDerived) -> None:
    if d.total_mass_kg > uav.max_payload_kg + 1e-9:
        rep.violations.append(
            Violation(
                ViolationType.MASS_OVERLOAD, s.sortie_id,
                f"总质量 {d.total_mass_kg:.3f} kg > 机型 {uav.code} 上限 {uav.max_payload_kg} kg",
            )
        )
    if d.total_volume_m3 > uav.volume_m3 + 1e-12:
        rep.violations.append(
            Violation(
                ViolationType.VOLUME_OVERLOAD, s.sortie_id,
                f"总体积 {d.total_volume_m3:.5f} m³ > 机型 {uav.code} 上限 {uav.volume_m3} m³",
            )
        )


def _check_energy(
    s: Sortie,
    uav: UAVType,
    rep: VerifyReport,
    d: SortieDerived,
    rel_tol: float,
    soc_tol: float,
) -> None:
    energy = d.energy_kwh
    budget = uav.energy_budget_kwh
    if energy > budget * (1 + rel_tol):
        rep.violations.append(
            Violation(
                ViolationType.ENERGY_BUDGET_EXCEEDED, s.sortie_id,
                f"重算能耗 {energy:.4f} kWh > 预算 {budget:.4f} kWh",
            )
        )
    soc = d.return_soc

    if s.reported_energy_kwh is not None:
        if abs(s.reported_energy_kwh - energy) > max(rel_tol * max(energy, 1e-9), 1e-9):
            rep.violations.append(
                Violation(
                    ViolationType.ENERGY_MISMATCH, s.sortie_id,
                    f"上报 {s.reported_energy_kwh:.4f} kWh ≠ 重算 {energy:.4f} kWh",
                )
            )
    if s.reported_return_soc is not None:
        if abs(s.reported_return_soc - soc) > soc_tol:
            rep.violations.append(
                Violation(
                    ViolationType.SOC_MISMATCH, s.sortie_id,
                    f"上报 SOC {s.reported_return_soc:.4f} ≠ 重算 {soc:.4f}",
                )
            )
    if soc < uav.reserve_ratio - soc_tol:
        rep.violations.append(
            Violation(
                ViolationType.SOC_BELOW_RESERVE, s.sortie_id,
                f"返航 SOC {soc:.4f} < 下限 {uav.reserve_ratio:.4f}",
            )
        )


def _sortie_end_s(s: Sortie, uav: UAVType, d: SortieDerived) -> float:
    """架次结束时刻 = 开始 + 准备 + 装载 + 飞行 + 交接。"""
    n_boxes = len(s.box_ids)
    t_handover = (uav.handover_base_s + uav.handover_per_box_s * n_boxes) * max(
        1, len(s.service_sequence)
    )
    return (
        s.start_s
        + uav.prepare_time_s
        + uav.box_load_time_s * n_boxes
        + d.flight_time_s
        + t_handover
    )


def _check_timing(
    s: Sortie,
    uav: UAVType,
    boxes: dict[str, BoxBatch],
    rep: VerifyReport,
    d: SortieDerived,
    tol: float,
) -> None:
    if not s.reported_delivery_times:
        return
    # 最早可能送达时刻 = 开始 + 准备 + 装载 + **飞到第一个服务区的时间**
    t_first_leg = segment_time_s(
        uav, Segment(s.leg_distance_m, s.climb_out_m, s.descent_out_m)
    )
    earliest_possible = (
        s.start_s
        + uav.prepare_time_s
        + uav.box_load_time_s * len(s.box_ids)
        + t_first_leg
    )
    for svc, t in s.reported_delivery_times.items():
        if t < earliest_possible - tol:
            rep.violations.append(
                Violation(
                    ViolationType.TIMING_INCONSISTENT, s.sortie_id,
                    f"服务区 {svc} 交付时刻 {t:.1f}s 早于最早可能 "
                    f"{earliest_possible:.1f}s（准备+装载+首段飞行都不够）",
                )
            )
        # 该服务区的箱子时限
        for b in s.box_ids:
            if b not in boxes or boxes[b].service_id != svc:
                continue
            bx = boxes[b]
            if (
                bx.is_first_batch
                and bx.first_batch_deadline_s is not None
                and t > bx.first_batch_deadline_s + tol
            ):
                rep.violations.append(
                    Violation(
                        ViolationType.FIRST_BATCH_DEADLINE_MISSED, s.sortie_id,
                        f"首批箱 {b} 交付 {t:.1f}s > 截止 {bx.first_batch_deadline_s:.0f}s",
                    )
                )
            elif bx.expected_time_s is not None and t > bx.expected_time_s + tol:
                rep.violations.append(
                    Violation(
                        ViolationType.EXPECTED_TIME_MISSED, s.sortie_id,
                        f"货箱 {b} 交付 {t:.1f}s > 期望 {bx.expected_time_s:.0f}s",
                    )
                )


def _check_resources(
    plan: TransportPlan,
    uav_types: dict[str, UAVType],
    derived: DerivedStore,
    rep: VerifyReport,
) -> None:
    # 1) 资源时段不重叠 + 机型/电池一致性 + 编号合法性
    by_resource: dict[str, list[tuple[float, float, str]]] = {}
    for s in plan.sorties:
        uav = uav_types.get(s.type_code)
        if uav is None:
            continue
        d = derived.get(s.sortie_id)

        # 无人机编号必须在机队中
        if plan.known_uav_ids is not None and s.uav_id not in plan.known_uav_ids:
            rep.violations.append(
                Violation(
                    ViolationType.UNKNOWN_RESOURCE, s.sortie_id,
                    f"无人机编号 {s.uav_id} 不在机队中",
                )
            )
        # 无人机与机型必须一致
        if plan.uav_id_to_type is not None:
            actual = plan.uav_id_to_type.get(s.uav_id)
            if actual is not None and actual != s.type_code:
                rep.violations.append(
                    Violation(
                        ViolationType.UNKNOWN_RESOURCE, s.sortie_id,
                        f"无人机 {s.uav_id} 是 {actual} 型，但架次声明为 {s.type_code} 型",
                    )
                )
        # 电池编号必须在库存中
        if plan.known_battery_ids is not None and s.battery_id not in plan.known_battery_ids:
            rep.violations.append(
                Violation(
                    ViolationType.UNKNOWN_RESOURCE, s.sortie_id,
                    f"电池编号 {s.battery_id} 不在共享电池库存中",
                )
            )

        by_resource.setdefault(f"UAV:{s.uav_id}", []).append(
            (s.start_s, d.end_s, s.sortie_id)
        )
        by_resource.setdefault(f"BAT:{s.battery_id}", []).append(
            (s.start_s, d.end_s, s.sortie_id)
        )
        if s.battery_id and "-" in s.battery_id:
            bat_type = s.battery_id.split("-")[0]
            if bat_type != s.type_code:
                rep.violations.append(
                    Violation(
                        ViolationType.UNKNOWN_RESOURCE, s.sortie_id,
                        f"电池 {s.battery_id} 属 {bat_type} 型，与机型 {s.type_code} 不匹配",
                    )
                )

    for res, spans in by_resource.items():
        spans.sort()
        for (s1, e1, id1), (s2, e2, id2) in zip(spans, spans[1:]):
            if s2 < e1 - 1e-9:
                rep.violations.append(
                    Violation(
                        ViolationType.RESOURCE_TIME_OVERLAP, id2,
                        f"资源 {res} 在 [{s2:.1f}, {e2:.1f}] 与架次 {id1} "
                        f"的 [{s1:.1f}, {e1:.1f}] 重叠",
                    )
                )

    # 2) 机队规模
    if plan.uav_fleet is not None:
        used: dict[str, set[str]] = {}
        for s in plan.sorties:
            used.setdefault(s.type_code, set()).add(s.uav_id)
        for code, ids in used.items():
            cap = plan.uav_fleet.get(code, 0)
            if len(ids) > cap:
                rep.violations.append(
                    Violation(
                        ViolationType.FLEET_SIZE_EXCEEDED, "-",
                        f"机型 {code} 使用 {len(ids)} 架 > 库存 {cap} 架",
                    )
                )

    # 3) 电池库存
    if plan.battery_inventory is not None:
        used_b: dict[str, set[str]] = {}
        for s in plan.sorties:
            used_b.setdefault(s.type_code, set()).add(s.battery_id)
        for code, ids in used_b.items():
            cap = plan.battery_inventory.get(code, 0)
            if len(ids) > cap:
                rep.violations.append(
                    Violation(
                        ViolationType.BATTERY_INVENTORY_EXCEEDED, "-",
                        f"机型 {code} 使用 {len(ids)} 组电池 > 库存 {cap} 组",
                    )
                )


def _check_comms(plan: TransportPlan, rep: VerifyReport) -> None:
    """每个通信中断时段必须被某个中继架次**完整覆盖**。"""
    for s in plan.sorties:
        if not s.outage_windows:
            continue
        for (t0, t1) in s.outage_windows:
            covered = False
            for r in plan.relays:
                if s.sortie_id in r.sortie_ids and r.start_s <= t0 + 1e-9 and r.end_s >= t1 - 1e-9:
                    covered = True
                    break
            if not covered:
                rep.violations.append(
                    Violation(
                        ViolationType.COMMS_UNSUPPORTED, s.sortie_id,
                        f"中断时段 [{t0:.1f}, {t1:.1f}] 未被任何中继架次完整覆盖",
                    )
                )


def check_all_boxes_delivered(
    plan: TransportPlan, boxes: dict[str, BoxBatch], rep: VerifyReport
) -> None:
    """全部货箱必须交付且只交付一次。"""
    delivered = [b for s in plan.sorties for b in s.box_ids]
    for b in boxes:
        if b not in delivered:
            rep.violations.append(
                Violation(ViolationType.MISSING_BOX, "-", f"货箱 {b} 未被任何架次交付")
            )
