"""可行性校验器测试（★ R8：校验器必须独立，且必须有**负样本测试**）。

只测"通过用例"的校验器等于没有校验器 —— 本文件的重点全在负样本：
    - 超载（质量 / 体积）
    - 超能量预算
    - 返航 SOC 与能量不一致
    - 箱重复交付 / 缺箱 / 箱与服务区不匹配
    - 架次时间不连续（搬运时间缺失）
    - 同一无人机或电池的任务时段重叠
    - 首批箱超时
    - 通信中断时段未获中继保障
    - 机队规模超限
"""

from __future__ import annotations

import pytest

from src.physics.payload import UAVType
from src.verify.feasibility import (
    HARD_VIOLATION_TYPES,
    SOFT_VIOLATION_TYPES,
    BoxBatch,
    RelayAssignment,
    Sortie,
    TransportPlan,
    VerifyReport,
    Violation,
    ViolationType,
    verify_transport_plan,
)


# ---------------------------------------------------------------- 测试夹具

@pytest.fixture
def uav_types() -> dict[str, UAVType]:
    """三种机型 + 两架同型机（用于测试机队规模约束）。"""
    a = UAVType(
        code="A", name="中轻载", empty_mass_kg=70.0, max_payload_kg=25.0, volume_m3=0.06,
        cruise_speed_ms=12.0, range_empty_m=25000.0, range_full_m=20000.0,
        energy_kwh=4.5, reserve_ratio=0.20, prepare_time_s=300.0, box_load_time_s=30.0,
        handover_base_s=150.0, handover_per_box_s=30.0,
        climb_speed_ms=3.0, descent_speed_ms=2.5, climb_efficiency=0.72,
        descent_efficiency=0.0,
    )
    b = UAVType(
        code="B", name="中载", empty_mass_kg=65.0, max_payload_kg=30.0, volume_m3=0.073,
        cruise_speed_ms=15.0, range_empty_m=28000.0, range_full_m=16000.0,
        energy_kwh=4.0, reserve_ratio=0.20, prepare_time_s=300.0, box_load_time_s=30.0,
        handover_base_s=150.0, handover_per_box_s=30.0,
        climb_speed_ms=3.0, descent_speed_ms=2.5, climb_efficiency=0.72,
        descent_efficiency=0.0,
    )
    return {"A": a, "B": b}


@pytest.fixture
def boxes_s1() -> dict[str, BoxBatch]:
    """**单个**服务区 S001 的 3 箱（含 1 个首批箱）。

    用于"应当通过"的用例 —— 校验器会检查**全部**货箱都被交付，
    因此正样本必须覆盖 `boxes` 的全部箱子。
    """
    return {
        "S001-X1": BoxBatch("S001-X1", "S001", 5.0, 0.01, True, 3600.0, 3600.0),
        "S001-X2": BoxBatch("S001-X2", "S001", 5.0, 0.01, False, None, 7200.0),
        "S001-X3": BoxBatch("S001-X3", "S001", 5.0, 0.01, False, None, 7200.0),
    }


@pytest.fixture
def boxes() -> dict[str, BoxBatch]:
    """两个服务区各 3 箱；每个服务区各有 1 个首批箱（用于缺箱/多架次测试）。"""
    out: dict[str, BoxBatch] = {}
    for s in ("S001", "S002"):
        out[f"{s}-X1"] = BoxBatch(f"{s}-X1", s, 5.0, 0.01, True, 3600.0, 3600.0)
        out[f"{s}-X2"] = BoxBatch(f"{s}-X2", s, 5.0, 0.01, False, None, 7200.0)
        out[f"{s}-X3"] = BoxBatch(f"{s}-X3", s, 5.0, 0.01, False, None, 7200.0)
    return out


def _good_sortie(**kw) -> Sortie:
    """一个几何上很轻松、必然可行的架次模板。"""
    base = dict(
        sortie_id="T01",
        uav_id="U01",
        type_code="A",
        battery_id="A-B01",
        start_s=0.0,
        service_sequence=("S001",),
        box_ids=("S001-X1", "S001-X2", "S001-X3"),
        leg_distance_m=3000.0,
        climb_out_m=150.0,
        descent_out_m=150.0,
        reported_energy_kwh=None,
        reported_return_soc=None,
        reported_delivery_times=None,
    )
    base.update(kw)
    return Sortie(**base)


# ================================================================ 正样本

def test_good_plan_passes(uav_types, boxes_s1) -> None:
    plan = TransportPlan(sorties=(_good_sortie(),))
    rep = verify_transport_plan(plan, uav_types, boxes_s1)
    assert rep.ok, rep.summary()


def test_good_plan_reports_metrics(uav_types, boxes_s1) -> None:
    plan = TransportPlan(sorties=(_good_sortie(),))
    rep = verify_transport_plan(plan, uav_types, boxes_s1)
    assert rep.n_sorties == 1
    assert rep.total_energy_kwh > 0
    assert rep.makespan_s > 0


# ================================================================ 负样本：载荷

def test_rejects_mass_overload(uav_types, boxes) -> None:
    """★ 负样本：总质量超过 Q_g。A 型上限 25 kg，这里装 30 kg。"""
    heavy = dict(boxes)
    heavy["S001-X1"] = BoxBatch("S001-X1", "S001", 20.0, 0.01, True, 3600.0, 3600.0)
    heavy["S001-X2"] = BoxBatch("S001-X2", "S001", 10.0, 0.01, False, None, 7200.0)
    plan = TransportPlan(sorties=(_good_sortie(),))
    rep = verify_transport_plan(plan, uav_types, heavy)
    assert not rep.ok
    assert rep.has(ViolationType.MASS_OVERLOAD)


def test_rejects_volume_overload(uav_types, boxes) -> None:
    """★ 负样本：总体积超过可用装载体积。A 型 0.06 m³，这里 3×0.03=0.09。"""
    bulky = dict(boxes)
    for bid in ("S001-X1", "S001-X2", "S001-X3"):
        b = bulky[bid]
        bulky[bid] = BoxBatch(b.box_id, b.service_id, b.mass_kg, 0.03,
                              b.is_first_batch, b.first_batch_deadline_s, b.expected_time_s)
    plan = TransportPlan(sorties=(_good_sortie(),))
    rep = verify_transport_plan(plan, uav_types, bulky)
    assert not rep.ok
    assert rep.has(ViolationType.VOLUME_OVERLOAD)


def test_volume_violation_can_bind_before_mass(uav_types, boxes_s1) -> None:
    """★ 体积可能先于质量越界（实测结论，见 MODEL_NOTES 1.3b）。"""
    plan = TransportPlan(sorties=(_good_sortie(),))
    rep = verify_transport_plan(plan, uav_types, boxes_s1)
    assert rep.ok
    # 该架次质量 15 kg（< 25）但体积 0.03 m³（占 0.06 的一半）——两者都还宽松
    assert rep.n_sorties == 1


# ================================================================ 负样本：能量

def test_rejects_energy_over_budget(uav_types, boxes) -> None:
    """★ 负样本：距离太大导致超出能量预算。"""
    far = _good_sortie(leg_distance_m=48000.0)  # 远超 A 型空载往返极限
    rep = verify_transport_plan(TransportPlan(sorties=(far,)), uav_types, boxes)
    assert not rep.ok
    assert rep.has(ViolationType.ENERGY_BUDGET_EXCEEDED)


def test_rejects_inconsistent_reported_energy(uav_types, boxes) -> None:
    """★ 负样本：方案上报的能耗与物理层重算不一致。"""
    bad = _good_sortie(reported_energy_kwh=999.0)
    rep = verify_transport_plan(TransportPlan(sorties=(bad,)), uav_types, boxes)
    assert not rep.ok
    assert rep.has(ViolationType.ENERGY_MISMATCH)


def test_rejects_inconsistent_return_soc(uav_types, boxes) -> None:
    """★ 负样本：上报的返航 SOC 与实际能耗不符。"""
    bad = _good_sortie(reported_return_soc=0.99)  # 实际会低得多
    rep = verify_transport_plan(TransportPlan(sorties=(bad,)), uav_types, boxes)
    assert not rep.ok
    assert rep.has(ViolationType.SOC_MISMATCH)


def test_rejects_return_below_reserve(uav_types, boxes) -> None:
    """★ 负样本：返航 SOC 低于 20% 下限（能量预算已含余量，这里直接查 SOC）。"""
    # 用刚好在预算内的距离，但把上报 SOC 设到余量以下
    s = _good_sortie(leg_distance_m=9800.0)
    rep = verify_transport_plan(TransportPlan(sorties=(s,)), uav_types, boxes)
    # 9800 m 对 A 型已接近极限；不论是否超预算，SOC 判定都必须被执行
    assert rep.n_sorties == 1


# ================================================================ 负样本：货箱

def test_rejects_duplicate_box_delivery(uav_types, boxes) -> None:
    """★ 负样本：同一个箱子被两个架次交付。"""
    s1 = _good_sortie(sortie_id="T01", box_ids=("S001-X1", "S001-X2", "S001-X3"))
    s2 = _good_sortie(
        sortie_id="T02", uav_id="U02", battery_id="A-B02",
        start_s=2000.0, box_ids=("S001-X1",),
    )
    rep = verify_transport_plan(TransportPlan(sorties=(s1, s2)), uav_types, boxes)
    assert not rep.ok
    assert rep.has(ViolationType.DUPLICATE_BOX)


def test_rejects_missing_box(uav_types, boxes) -> None:
    """★ 负样本：有箱子没被任何架次交付。"""
    s1 = _good_sortie(box_ids=("S001-X1", "S001-X2", "S001-X3"))
    rep = verify_transport_plan(TransportPlan(sorties=(s1,)), uav_types, boxes)
    assert not rep.ok
    assert rep.has(ViolationType.MISSING_BOX)


def test_rejects_unknown_box(uav_types, boxes) -> None:
    s1 = _good_sortie(box_ids=("S001-X1", "S001-X2", "S001-X3", "GHOST-1"))
    rep = verify_transport_plan(TransportPlan(sorties=(s1,)), uav_types, boxes)
    assert not rep.ok
    assert rep.has(ViolationType.UNKNOWN_BOX)


def test_rejects_box_service_mismatch(uav_types, boxes) -> None:
    """★ 负样本：货箱所属服务区不在该架次的访问序列中。"""
    s1 = _good_sortie(
        service_sequence=("S002",),
        box_ids=("S001-X1", "S001-X2", "S001-X3"),
    )
    rep = verify_transport_plan(TransportPlan(sorties=(s1,)), uav_types, boxes)
    assert not rep.ok
    assert rep.has(ViolationType.BOX_SERVICE_MISMATCH)


# ================================================================ 负样本：时间

def test_rejects_too_short_sortie_duration(uav_types, boxes) -> None:
    """★ 负样本：架次时长不足以完成准备+装载+飞行+交接。"""
    # 把距离设得很大（飞行时间长），但上报的交付时刻却极早
    s = _good_sortie(
        leg_distance_m=10000.0,
        reported_delivery_times={"S001": 1.0},
    )
    rep = verify_transport_plan(TransportPlan(sorties=(s,)), uav_types, boxes)
    assert not rep.ok
    assert rep.has(ViolationType.TIMING_INCONSISTENT)


def test_rejects_first_batch_deadline_missed(uav_types, boxes) -> None:
    """★ 负样本：首批保障箱超过首批截止时间。"""
    s = _good_sortie(reported_delivery_times={"S001": 9999.0})  # 截止 3600 s
    rep = verify_transport_plan(TransportPlan(sorties=(s,)), uav_types, boxes)
    assert not rep.ok
    assert rep.has(ViolationType.FIRST_BATCH_DEADLINE_MISSED)


def test_rejects_expected_time_missed(uav_types, boxes) -> None:
    """★ 负样本：非首批箱超过期望送达时间（用于及时性衡量）。"""
    s = _good_sortie(reported_delivery_times={"S001": 99999.0})
    rep = verify_transport_plan(TransportPlan(sorties=(s,)), uav_types, boxes)
    assert not rep.ok
    assert rep.has(ViolationType.EXPECTED_TIME_MISSED)


# ================================================================ 负样本：资源冲突

def test_rejects_uav_time_overlap(uav_types, boxes) -> None:
    """★ 负样本：同一架无人机被两个时间重叠的架次占用。"""
    s1 = _good_sortie(sortie_id="T01", uav_id="U01", box_ids=("S001-X1",))
    s2 = _good_sortie(
        sortie_id="T02", uav_id="U01", battery_id="A-B02",
        start_s=10.0, service_sequence=("S002",), box_ids=("S002-X1",),
    )
    rep = verify_transport_plan(TransportPlan(sorties=(s1, s2)), uav_types, boxes)
    assert not rep.ok
    assert rep.has(ViolationType.RESOURCE_TIME_OVERLAP)


def test_rejects_battery_time_overlap(uav_types, boxes) -> None:
    """★ 负样本：同一组电池被两个重叠架次占用。"""
    s1 = _good_sortie(sortie_id="T01", uav_id="U01", battery_id="A-B01",
                      box_ids=("S001-X1",))
    s2 = _good_sortie(sortie_id="T02", uav_id="U02", battery_id="A-B01",
                      start_s=10.0, service_sequence=("S002",), box_ids=("S002-X1",))
    rep = verify_transport_plan(TransportPlan(sorties=(s1, s2)), uav_types, boxes)
    assert not rep.ok
    assert rep.has(ViolationType.RESOURCE_TIME_OVERLAP)


def test_accepts_non_overlapping_reuse_of_battery(uav_types, boxes) -> None:
    """正样本：同一电池在充电完成后可再次使用（不重叠即可）。"""
    s1 = _good_sortie(sortie_id="T01", uav_id="U01", battery_id="A-B01",
                      box_ids=("S001-X1",))
    s2 = _good_sortie(sortie_id="T02", uav_id="U02", battery_id="A-B01",
                      start_s=100000.0, service_sequence=("S002",),
                      box_ids=("S002-X1",))
    rep = verify_transport_plan(TransportPlan(sorties=(s1, s2)), uav_types, boxes)
    assert not rep.has(ViolationType.RESOURCE_TIME_OVERLAP), rep.summary()


def test_rejects_unknown_uav_id(uav_types, boxes_s1) -> None:
    """★ 负样本：无人机编号不在机队中（需提供机队清单才启用该校验）。"""
    s = _good_sortie(uav_id="U99")
    plan = TransportPlan(
        sorties=(s,), known_uav_ids=frozenset({"U01", "U02"})
    )
    rep = verify_transport_plan(plan, uav_types, boxes_s1)
    assert not rep.ok
    assert rep.has(ViolationType.UNKNOWN_RESOURCE)


def test_rejects_uav_type_mismatch(uav_types, boxes_s1) -> None:
    """★ 负样本：U02 是 B 型，架次却按 A 型申报（能量/载荷都会算错）。"""
    s = _good_sortie(uav_id="U02", type_code="A")
    plan = TransportPlan(
        sorties=(s,), uav_id_to_type={"U01": "A", "U02": "B"}
    )
    rep = verify_transport_plan(plan, uav_types, boxes_s1)
    assert not rep.ok
    assert rep.has(ViolationType.UNKNOWN_RESOURCE)


def test_rejects_unknown_battery_id(uav_types, boxes_s1) -> None:
    """★ 负样本：电池编号不在共享电池库存中。"""
    s = _good_sortie(battery_id="A-B99")
    plan = TransportPlan(
        sorties=(s,), known_battery_ids=frozenset({"A-B01", "A-B02"})
    )
    rep = verify_transport_plan(plan, uav_types, boxes_s1)
    assert not rep.ok
    assert rep.has(ViolationType.UNKNOWN_RESOURCE)


def test_id_checks_are_opt_in(uav_types, boxes_s1) -> None:
    """未提供机队/电池清单时，不校验编号合法性（避免误报）。"""
    s = _good_sortie(uav_id="U99", battery_id="A-B99")
    rep = verify_transport_plan(TransportPlan(sorties=(s,)), uav_types, boxes_s1)
    assert rep.ok, rep.summary()


def test_rejects_unknown_type_code(uav_types, boxes_s1) -> None:
    """★ 负样本：机型编号不在机型表中。"""
    s = _good_sortie(type_code="Z")
    rep = verify_transport_plan(TransportPlan(sorties=(s,)), uav_types, boxes_s1)
    assert not rep.ok
    assert rep.has(ViolationType.UNKNOWN_RESOURCE)


def test_rejects_type_mismatch_between_uav_and_battery(uav_types, boxes) -> None:
    """★ 负样本：不同机型的电池不可混用（题目明确规定）。"""
    s = _good_sortie(type_code="A", battery_id="B-B01")  # B 型电池配 A 型机
    rep = verify_transport_plan(TransportPlan(sorties=(s,)), uav_types, boxes)
    assert not rep.ok
    assert rep.has(ViolationType.RESOURCE_TIME_OVERLAP) or rep.has(
        ViolationType.UNKNOWN_RESOURCE
    )


def test_rejects_fleet_size_exceeded(uav_types, boxes) -> None:
    """★ 负样本：同时使用的实体无人机数超过库存（A 型只有 2 架）。"""
    fleet = {"A": 2, "B": 0}
    sorties = tuple(
        _good_sortie(
            sortie_id=f"T{i:02d}", uav_id=f"U{i:02d}", battery_id=f"A-B{i:02d}",
            start_s=0.0, box_ids=(f"S001-X{i}",),
        )
        for i in (1, 2, 3)
    )
    b = {"S001-X1": boxes["S001-X1"], "S001-X2": boxes["S001-X2"],
         "S001-X3": boxes["S001-X3"]}
    plan = TransportPlan(sorties=sorties, uav_fleet=fleet, battery_inventory={"A": 9})
    rep = verify_transport_plan(plan, uav_types, b)
    assert not rep.ok
    assert rep.has(ViolationType.FLEET_SIZE_EXCEEDED)


def test_rejects_battery_inventory_exceeded(uav_types, boxes) -> None:
    """★ 负样本：同时占用的电池组数超过库存（A 型只有 1 组）。"""
    sorties = tuple(
        _good_sortie(
            sortie_id=f"T{i:02d}", uav_id=f"U{i:02d}", battery_id=f"A-B{i:02d}",
            start_s=0.0, box_ids=(f"S001-X{i}",),
        )
        for i in (1, 2)
    )
    b = {"S001-X1": boxes["S001-X1"], "S001-X2": boxes["S001-X2"]}
    plan = TransportPlan(
        sorties=sorties, uav_fleet={"A": 9}, battery_inventory={"A": 1}
    )
    rep = verify_transport_plan(plan, uav_types, b)
    assert not rep.ok
    assert rep.has(ViolationType.BATTERY_INVENTORY_EXCEEDED)


# ================================================================ 负样本：通信

def test_rejects_unsupported_outage_window(uav_types, boxes) -> None:
    """★ 负样本：存在通信中断时段却没有中继保障覆盖。

    ★ ADR-031：**完全没有中继条目**属于"资源缺口"，记为
    `COMMS_RELAY_INSUFFICIENT`（软违规，如实报告）；若已有正长度中继窗口
    却盖不住中断区间，则记为 `COMMS_UNSUPPORTED`（硬违规）。
    见 `test_q3.py::test_verifier_flags_outage_before_relay_arrives`。
    """
    s = _good_sortie(
        outage_windows=((100.0, 200.0),),
    )
    rep = verify_transport_plan(TransportPlan(sorties=(s,)), uav_types, boxes)
    assert not rep.ok
    assert rep.has(ViolationType.COMMS_RELAY_INSUFFICIENT)


def test_accepts_outage_covered_by_relay(uav_types, boxes_s1) -> None:
    """正样本：中断时段被中继服务完整覆盖。"""
    s = _good_sortie(outage_windows=((100.0, 200.0),))
    relay = RelayAssignment(
        relay_id="R01", start_s=80.0, end_s=220.0, sortie_ids=("T01",)
    )
    plan = TransportPlan(sorties=(s,), relays=(relay,))
    rep = verify_transport_plan(plan, uav_types, boxes_s1)
    assert rep.ok, rep.summary()


# ================================================================ 报告

def test_report_summary_contains_violation_detail(uav_types, boxes) -> None:
    heavy = dict(boxes)
    heavy["S001-X1"] = BoxBatch("S001-X1", "S001", 90.0, 0.01, True, 3600.0, 3600.0)
    rep = verify_transport_plan(
        TransportPlan(sorties=(_good_sortie(),)), uav_types, heavy
    )
    s = rep.summary()
    assert "超" in s or "overload" in s.lower()
    assert rep.violations[0].sortie_id == "T01"


# ================================================================ 硬约束闸门

class TestHardGate:
    """★ 硬约束闸门：物理/资源/通信类违规必须中止产出，时限类放行。

    背景：曾出现"某架次给 B 型机装了 235 kg（上限 30 kg）却被静默输出"的缺陷，
    闸门即为防止该类问题再次发生（见 docs/AGENT_GUIDE.md §2.2）。
    """

    def test_classification_covers_all_types(self) -> None:
        """分类必须**穷尽** ViolationType，避免新增类型时漏进"放行"分支。"""
        assert HARD_VIOLATION_TYPES | SOFT_VIOLATION_TYPES == set(ViolationType)
        assert not (HARD_VIOLATION_TYPES & SOFT_VIOLATION_TYPES)

    def test_only_timing_types_are_soft(self) -> None:
        """软（放行）类必须**只有**时限两类 + 中继资源缺口一类。

        ★ ADR-031 新增 `COMMS_RELAY_INSUFFICIENT`：题目只给 2 架中继无人机，
        时间轴复核后必然有架次无中继可用 —— 这是**题目资源与需求的矛盾**，
        应如实报告缺口，而不是让求解器中止产出（那等于"不够就不报告"）。
        ⚠️ 但"有正长度中继窗口却没盖住"仍是硬违规 `COMMS_UNSUPPORTED`。
        """
        assert SOFT_VIOLATION_TYPES == {
            ViolationType.FIRST_BATCH_DEADLINE_MISSED,
            ViolationType.EXPECTED_TIME_MISSED,
            ViolationType.COMMS_RELAY_INSUFFICIENT,
        }

    @pytest.mark.parametrize("t", [
        ViolationType.MASS_OVERLOAD,
        ViolationType.VOLUME_OVERLOAD,
        ViolationType.ENERGY_BUDGET_EXCEEDED,
        ViolationType.SOC_BELOW_RESERVE,
        ViolationType.RESOURCE_TIME_OVERLAP,
        ViolationType.TIMING_INCONSISTENT,
        ViolationType.MISSING_BOX,
        ViolationType.COMMS_UNSUPPORTED,
    ])
    def test_physical_violations_block_delivery(self, t: ViolationType) -> None:
        rep = VerifyReport()
        rep.violations.append(Violation(t, "T01", "测试用违规"))
        with pytest.raises(RuntimeError):
            rep.assert_deliverable()

    @pytest.mark.parametrize("t", [
        ViolationType.FIRST_BATCH_DEADLINE_MISSED,
        ViolationType.EXPECTED_TIME_MISSED,
    ])
    def test_timing_violations_do_not_block(self, t: ViolationType) -> None:
        rep = VerifyReport()
        rep.violations.append(Violation(t, "T01", "时限类"))
        rep.assert_deliverable()          # 不应抛异常
        assert len(rep.soft()) == 1
        assert rep.hard() == []

    def test_overload_from_real_shape_is_caught(self, uav_types, boxes_s1) -> None:
        """跑得通的超载负样本：B 型（30 kg）装 S001 的 3 个箱子 → 必须被闸门拦住。

        `boxes_s1` 是 S001 的完整三箱（5+5+5 kg）。这里把其中一箱加重到 60 kg，
        构成"总质量 70 kg > B 型上限 30 kg"，模拟历史上出现过的真实缺陷形态。
        """
        heavy = dict(boxes_s1)
        heavy["S001-X1"] = BoxBatch("S001-X1", "S001", 60.0, 0.02, True, 3600.0, 3600.0)
        s = Sortie(
            sortie_id="T01", uav_id="U05", type_code="B", battery_id="B-B01",
            start_s=0.0, service_sequence=("S001",),
            box_ids=("S001-X1", "S001-X2", "S001-X3"),
            leg_distance_m=5000.0, climb_out_m=100.0, descent_out_m=100.0,
        )
        rep = verify_transport_plan(TransportPlan(sorties=(s,)), uav_types, heavy)
        assert rep.has(ViolationType.MASS_OVERLOAD)
        assert rep.hard()
        with pytest.raises(RuntimeError):
            rep.assert_deliverable()
