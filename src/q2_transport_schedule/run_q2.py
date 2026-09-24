"""问题二入口：异构无人机多点多架次运输调度。

用法：
    python -m src.q2_transport_schedule.run_q2
    python -m src.q2_transport_schedule.run_q2 --no-local-search

输出（outputs/q2/）：
    metrics.json / params.json / run_log.json
    tables/  Q2_运输架次、Q2_逐箱交付、资源使用、时限达成、方案对比
    figures/ 路线图、甘特图、及时性分析
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from src.common.config import DEFAULT_RESERVE_RATIO, outputs_dir
from src.common.io_utils import get_logger, save_json, save_metrics, save_table
from src.physics.leg_cache import load_cached
from src.physics.payload import UAVType
from src.q1_payload_grouping.grouping import Box
from src.q2_transport_schedule.models import CENTER_ID
from src.q2_transport_schedule.schedule import build_pools, schedule_dispatch
from src.q2_transport_schedule.solver import (
    Deadline,
    Q2Result,
    clear_caches,
    construct,
    lateness_of,
    local_search,
)
from src.verify.feasibility import (
    BoxBatch,
    Leg,
    Sortie,
    TransportPlan,
    verify_transport_plan,
)
from src.q0_data import build_processed as BP

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 130
plt.rcParams["savefig.bbox"] = "tight"


def to_uav_type(r: pd.Series) -> UAVType:
    return UAVType(
        code=str(r["code"]), name=str(r["name"]),
        empty_mass_kg=float(r["empty_mass_kg"]),
        max_payload_kg=float(r["max_payload_kg"]),
        volume_m3=float(r["volume_m3"]),
        cruise_speed_ms=float(r["cruise_speed_ms"]),
        range_empty_m=float(r["range_empty_m"]),
        range_full_m=float(r["range_full_m"]),
        energy_kwh=float(r["energy_kwh"]),
        reserve_ratio=float(r["reserve_ratio"]),
        prepare_time_s=float(r["prepare_time_s"]),
        box_load_time_s=float(r["box_load_time_s"]),
        handover_base_s=float(r["handover_base_s"]),
        handover_per_box_s=float(r["handover_per_box_s"]),
        climb_speed_ms=float(r["climb_speed_ms"]),
        descent_speed_ms=float(r["descent_speed_ms"]),
        climb_efficiency=float(r["climb_efficiency"]),
        descent_efficiency=float(r["descent_efficiency"]),
    )


def load_inputs():
    bdf = BP.load_boxes()
    tdf = BP.load_uav_types()
    fdf = BP.load_uav_fleet()
    bat = BP.load_battery_inventory()
    uav_types = {str(r["code"]): to_uav_type(r) for _, r in tdf.iterrows()}
    boxes: list[Box] = []
    deadlines: dict[str, Deadline] = {}
    for _, r in bdf.iterrows():
        b = Box(
            box_id=str(r["box_id"]), service_id=str(r["service_id"]),
            mass_kg=float(r["mass_kg"]), volume_m3=float(r["volume_m3"]),
            is_first_batch=bool(r["is_first_batch"]),
            first_batch_deadline_s=(
                float(r["first_batch_deadline_s"])
                if pd.notna(r["first_batch_deadline_s"]) else None
            ),
            expected_time_s=float(r["expected_time_s"]),
            priority=int(r["priority"]),
        )
        boxes.append(b)
        deadlines[b.box_id] = Deadline(
            expected_s=float(r["expected_time_s"]),
            first_batch_s=(
                float(r["first_batch_deadline_s"])
                if pd.notna(r["first_batch_deadline_s"]) else None
            ),
            is_first_batch=bool(r["is_first_batch"]),
        )
    fleet = {c: sorted(g["uav_id"].tolist()) for c, g in fdf.groupby("type_code")}
    bat_inv = {str(r["type_code"]): int(r["n_battery_packs"]) for _, r in bat.iterrows()}
    t_full = {str(r["type_code"]): float(r["t_full_s"]) for _, r in bat.iterrows()}
    return boxes, uav_types, fleet, bat_inv, t_full, deadlines, bdf


def solve(
    boxes: list[Box],
    uav_types: dict[str, UAVType],
    leg_cache,
    deadlines: dict[str, Deadline],
    fleet: dict[str, list[str]],
    bat_inv: dict[str, int],
    t_full: dict[str, float],
    do_local_search: bool = True,
    max_group: int = 3,
) -> Q2Result:
    t0 = time.perf_counter()
    boxes_by_id = {b.box_id: b for b in boxes}

    clear_caches()
    cands = construct(boxes, uav_types, leg_cache, deadlines, max_group=max_group)
    iters = 1
    if do_local_search:
        cands = local_search(cands, uav_types, leg_cache, boxes_by_id, deadlines)
        iters += 1

    plans = [c.plan for c in cands if c.plan.stops]
    pools = build_pools(fleet, bat_inv, t_full)
    sched = schedule_dispatch(plans, uav_types, leg_cache, boxes_by_id, pools)

    assert sched is not None
    pen = 0.0
    n_fb = n_exp = 0
    lates: list[float] = []
    n_on_time = 0
    n_total = 0
    for s in sched:
        p, a, b2, ml, xl = lateness_of(s, boxes_by_id, deadlines)
        pen += p
        n_fb += a
        n_exp += b2
        lates.append(xl)
        for svc, t in s.delivery_times.items():
            for bid in s.boxes_by_stop.get(svc, ()):
                dl = deadlines.get(bid)
                if dl is None:
                    continue
                n_total += 1
                if t <= dl.expected_s + 1e-6:
                    n_on_time += 1

    return Q2Result(
        sorties=sched,
        makespan_s=max((s.return_s for s in sched), default=0.0),
        total_energy_kwh=sum(s.energy_kwh for s in sched),
        n_sorties=len(sched),
        n_boxes=sum(s.n_boxes for s in sched),
        violations_first_batch=n_fb,
        violations_expected=n_exp,
        mean_lateness_s=(sum(lates) / len(lates) if lates else 0.0),
        max_lateness_s=(max(lates) if lates else 0.0),
        on_time_rate=(n_on_time / n_total if n_total else 1.0),
        objective=pen,
        runtime_s=time.perf_counter() - t0,
        iterations=iters,
    )


def sortie_records(res: Q2Result) -> list[dict]:
    """按 `结果提交模板.xlsx` 的 `Q2_运输架次` 列序输出。"""
    return [
        {
            "架次编号": s.sortie_id,
            "无人机编号": s.uav_id,
            "机型编号": s.type_code,
            "电池编号": s.battery_id,
            "开始时刻（s）": round(s.start_s, 1),
            "访问服务区顺序": "→".join(s.stops),
            "返回O01时刻（s）": round(s.return_s, 1),
            "架次能耗（kWh）": round(s.energy_kwh, 5),
        }
        for s in res.sorties
    ]


def box_delivery_records(res: Q2Result) -> list[dict]:
    """按 `Q2_逐箱交付` 列序输出。"""
    out = []
    for s in res.sorties:
        for svc in s.stops:
            for bid in s.boxes_by_stop.get(svc, ()):
                out.append(
                    {
                        "货箱编号": bid,
                        "架次编号": s.sortie_id,
                        "服务区编号": svc,
                        "交付完成时刻（s）": round(s.delivery_times.get(svc, float("nan")), 1),
                    }
                )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="D 题问题二求解器")
    ap.add_argument("--no-local-search", action="store_true")
    ap.add_argument("--max-group", type=int, default=3, help="单架次最多访问的服务区数")
    args = ap.parse_args(argv)

    log = get_logger("q2")
    out = outputs_dir("q2")
    (out / "tables").mkdir(exist_ok=True)
    (out / "figures").mkdir(exist_ok=True)

    log.info("载入输入 ...")
    boxes, uav_types, fleet, bat_inv, t_full, deadlines, bdf = load_inputs()
    leg_cache = load_cached()
    log.info("货箱 %d / 机型 %s / 机队 %s / 电池 %s",
             len(boxes), list(uav_types), fleet, bat_inv)

    res = solve(
        boxes, uav_types, leg_cache, deadlines, fleet, bat_inv, t_full,
        do_local_search=not args.no_local_search, max_group=args.max_group,
    )
    log.info(
        "求解完成：%d 架次 / %.2f kWh / makespan %.0f s / 首批违规 %d / 期望违规 %d",
        res.n_sorties, res.total_energy_kwh, res.makespan_s,
        res.violations_first_batch, res.violations_expected,
    )

    # ---------------- 落盘：交付格式 ----------------
    sdf = pd.DataFrame(sortie_records(res))
    save_table(sdf, out / "tables" / "q2_运输架次.csv")
    ddf = pd.DataFrame(box_delivery_records(res))
    save_table(ddf, out / "tables" / "q2_逐箱交付.csv")

    # ---------------- 资源使用 ----------------
    uav_use = []
    for uid, g in pd.DataFrame(
        [{"uav": s.uav_id, "type": s.type_code, "dur": s.return_s - s.start_s}
         for s in res.sorties]
    ).groupby("uav"):
        uav_use.append({"无人机编号": uid, "机型": g["type"].iloc[0],
                        "架次数": len(g), "总飞行时长（s）": round(g["dur"].sum(), 1)})
    save_table(pd.DataFrame(uav_use), out / "tables" / "q2_资源使用_无人机.csv")

    bat_use = pd.DataFrame(
        [{"电池编号": s.battery_id, "机型": s.type_code, "架次": s.sortie_id,
          "占用开始（s）": round(s.start_s, 1), "占用结束（s）": round(s.return_s, 1),
          "返航SOC（%）": round(s.soc_end * 100, 2)} for s in res.sorties]
    )
    save_table(bat_use, out / "tables" / "q2_资源使用_电池.csv")

    # ---------------- 时限达成 ----------------
    boxes_by_id = {b.box_id: b for b in boxes}
    tl = []
    for s in res.sorties:
        for svc in s.stops:
            t = s.delivery_times.get(svc, float("nan"))
            for bid in s.boxes_by_stop.get(svc, ()):
                dl = deadlines[bid]
                tl.append({
                    "货箱编号": bid, "服务区": svc, "架次": s.sortie_id,
                    "首批保障": "是" if dl.is_first_batch else "否",
                    "首批截止（s）": dl.first_batch_s,
                    "期望送达（s）": dl.expected_s,
                    "实际交付（s）": round(t, 1),
                    "首批达标": ("—" if not dl.is_first_batch
                               else ("是" if t <= (dl.first_batch_s or 0) + 1e-6 else "否")),
                    "期望达标": "是" if t <= dl.expected_s + 1e-6 else "否",
                })
    save_table(pd.DataFrame(tl), out / "tables" / "q2_时限达成.csv")

    # ---------------- 独立校验 ----------------
    boxes_map = {
        b.box_id: BoxBatch(b.box_id, b.service_id, b.mass_kg, b.volume_m3,
                           b.is_first_batch, b.first_batch_deadline_s, b.expected_time_s)
        for b in boxes
    }
    verify_sorties = []
    for s in res.sorties:
        # ★ 逐段传入几何（含回程），让校验器按真实航段重算能耗与时间
        nodes = [CENTER_ID, *s.stops, CENTER_ID]
        legs = []
        for a, b in zip(nodes, nodes[1:]):
            g = leg_cache.get(a, b)
            legs.append(Leg(g["distance_m"], g["climb_m"], g["descent_m"]))
        verify_sorties.append(
            Sortie(
                sortie_id=s.sortie_id, uav_id=s.uav_id, type_code=s.type_code,
                battery_id=s.battery_id, start_s=s.start_s,
                service_sequence=s.stops,
                box_ids=tuple(x for st in s.stops for x in s.boxes_by_stop.get(st, ())),
                legs=tuple(legs),
                boxes_per_stop={st: len(v) for st, v in s.boxes_by_stop.items()},
                reported_delivery_times=s.delivery_times,
            )
        )
    plan = TransportPlan(
        sorties=tuple(verify_sorties),
        uav_fleet={c: len(v) for c, v in fleet.items()},
        battery_inventory=bat_inv,
        known_uav_ids=frozenset(x for v in fleet.values() for x in v),
        known_battery_ids=frozenset(
            f"{c}-B{i:02d}" for c, n in bat_inv.items() for i in range(1, n + 1)
        ),
        battery_charge_s=t_full,
        uav_id_to_type={u: c for c, v in fleet.items() for u in v},
    )
    rep = verify_transport_plan(plan, uav_types, boxes_map)
    save_json({"ok": rep.ok, "violations": [str(v) for v in rep.violations]},
              out / "feasibility.json")
    log.info("独立校验：%s", "通过" if rep.ok else f"{len(rep.violations)} 条违规")
    if not rep.ok:
        for v in rep.violations[:10]:
            log.warning("  %s", v)

    # ---------------- ★ 硬约束闸门（R8 强化）----------------
    # 题目允许"首批/期望时限无法全部满足"（本文已论证为资源约束下的物理不可行），
    # 因此时限类违规**不阻断**产出；但**物理与资源类**违规（超载、超体积、
    # 超能量预算、返航 SOC 不足、资源时段冲突、架次时长不足、货箱缺失/重复）
    # 说明方案本身不可行，绝不能进入论文与交付文件。
    # 分类依据见 `verify.feasibility.HARD_VIOLATION_TYPES`。
    try:
        rep.assert_deliverable()
    except RuntimeError as exc:
        log.error("★ 硬约束闸门未通过：%s", exc)
        raise
    log.info("硬约束闸门：通过（物理/资源类违规 0 条；时限类 %d 条已按论文口径论证）",
             len(rep.violations))

    # ---------------- 图 ----------------
    fig, ax = plt.subplots(figsize=(10, 4.2))
    for s in res.sorties:
        ax.barh(s.uav_id, (s.return_s - s.start_s) / 60.0, left=s.start_s / 60.0,
                height=0.6, color={"A": "#3b7dd8", "B": "#2e8b57", "C": "#d85a3b"}[s.type_code],
                edgecolor="white")
    ax.set_xlabel("时间 (min)")
    ax.set_title("问题二 调度甘特图（按无人机）")
    ax.grid(alpha=0.3, axis="x")
    fig.savefig(out / "figures" / "q2_gantt.png")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 4.4))
    tldf = pd.DataFrame(tl)
    for kind, sub in tldf.groupby("首批保障"):
        ax.scatter(sub["期望送达（s）"] / 60, sub["实际交付（s）"] / 60,
                   s=28, label=f"首批={kind}", alpha=0.75)
    lim = max(tldf["期望送达（s）"].max(), tldf["实际交付（s）"].max()) / 60 * 1.05
    ax.plot([0, lim], [0, lim], "k--", lw=1, label="准时线")
    ax.set_xlabel("期望送达时间 (min)")
    ax.set_ylabel("实际交付时刻 (min)")
    ax.set_title("问题二 时限达成情况")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.savefig(out / "figures" / "q2_timeliness.png")
    plt.close(fig)

    # ---------------- 指标 ----------------
    metrics = {
        "n_sorties": res.n_sorties,
        "n_boxes": res.n_boxes,
        "total_energy_kwh": round(res.total_energy_kwh, 6),
        "makespan_s": round(res.makespan_s, 1),
        "makespan_h": round(res.makespan_s / 3600, 3),
        "violations_first_batch": res.violations_first_batch,
        "violations_expected": res.violations_expected,
        "on_time_rate": round(res.on_time_rate, 4),
        "max_lateness_s": round(res.max_lateness_s, 1),
        "objective_penalty": round(res.objective, 3),
        "runtime_sec": round(res.runtime_s, 2),
        "iterations": res.iterations,
        "feasible_by_verifier": rep.ok,
        "n_verifier_violations": len(rep.violations),
        "type_usage": {},
    }
    usage: dict[str, int] = {}
    for s in res.sorties:
        usage[s.type_code] = usage.get(s.type_code, 0) + 1
    metrics["type_usage"] = usage
    save_metrics("q2", metrics, params={"reserve_ratio": DEFAULT_RESERVE_RATIO},
                 extra={"data_sources": ["物资需求与配送时限.xlsx", "运输无人机数据.xlsx",
                                         "调度中心与服务区.xlsx", "30米DEM.tif"]})
    save_json({"sorties": sortie_records(res), "deliveries": box_delivery_records(res)},
              out / "run_log.json")

    print()
    print("=" * 84)
    print("问题二求解结果")
    print("=" * 84)
    print(sdf.to_string(index=False))
    print()
    print(f"架次数 {res.n_sorties} / 总能耗 {res.total_energy_kwh:.3f} kWh / "
          f"完工 {res.makespan_s/60:.1f} min")
    print(f"首批违规 {res.violations_first_batch} 箱 / 期望违规 {res.violations_expected} 箱 / "
          f"准时率 {res.on_time_rate:.1%}")
    print(f"机型使用 {usage}；独立校验 {'通过' if rep.ok else '未通过'}")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    raise SystemExit(main())
