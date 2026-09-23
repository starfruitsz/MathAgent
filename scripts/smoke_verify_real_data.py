"""P0d 冒烟验证：用**真实附件数据**端到端跑通 数据层 → 地理层 → 物理层 → 校验器。

构造一个最简单的真实方案（一个服务区、单架次），
用真实航段几何 + 真实货箱 + 真实机型参数，交给**独立校验器**判定，
并同时验证校验器能抓出被人为破坏的方案。

用法：
    python scripts/smoke_verify_real_data.py
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.geo.dem import RasterElevationProvider  # noqa: E402
from src.geo.leg import Node, leg_geometry_pair  # noqa: E402
from src.physics.payload import UAVType, max_safe_payload  # noqa: E402
from src.q0_data import build_processed as BP  # noqa: E402
from src.verify.feasibility import (  # noqa: E402
    BoxBatch,
    Sortie,
    TransportPlan,
    verify_transport_plan,
)

DEM = (
    REPO
    / "data/raw/D题/数据/镇龙乡地理空间数据/镇龙乡及周边地理数据"
    / "数字高程模型数据（DEM）/镇龙乡及周边30米DEM.tif"
)

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]


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


def main() -> int:
    print("=" * 80)
    print("P0d 冒烟验证：真实数据 → 地理/物理层 → 独立校验器")
    print("=" * 80)

    # ---------- 载入真实数据 ----------
    nodes_df = BP.load_nodes()
    boxes_df = BP.load_boxes()
    types_df = BP.load_uav_types()
    fleet_df = BP.load_uav_fleet()
    bat_df = BP.load_battery_inventory()

    uav_types = {str(r["code"]): to_uav_type(r) for _, r in types_df.iterrows()}
    known_uav = frozenset(fleet_df["uav_id"])
    uav_id_to_type = dict(zip(fleet_df["uav_id"], fleet_df["type_code"]))
    # 给共享电池编号（按机型 + 序号），并建立库存集合
    bat_inv = {str(r["type_code"]): int(r["n_battery_packs"]) for _, r in bat_df.iterrows()}
    known_bat = frozenset(
        f"{code}-B{i:02d}" for code, n in bat_inv.items() for i in range(1, n + 1)
    )

    print(f"节点 {len(nodes_df)} / 货箱 {len(boxes_df)} / 机型 {len(uav_types)} / "
          f"实体机 {len(known_uav)} / 电池 {len(known_bat)} 组")

    o01 = nodes_df[nodes_df["kind"] == "center"].iloc[0]
    o01_node = Node(str(o01["id"]), float(o01["lon"]), float(o01["lat"]),
                    "center", float(o01["ground_elev_m"]))
    prov = RasterElevationProvider(DEM)
    gateway_alt = float(o01["ground_elev_m"]) + BP.load_comms_params()["gateway_antenna_height_m"]

    # ---------- 为每个服务区构造"一区一架次"的朴素方案 ----------
    boxes: dict[str, BoxBatch] = {}
    for _, r in boxes_df.iterrows():
        boxes[str(r["box_id"])] = BoxBatch(
            box_id=str(r["box_id"]),
            service_id=str(r["service_id"]),
            mass_kg=float(r["mass_kg"]),
            volume_m3=float(r["volume_m3"]),
            is_first_batch=bool(r["is_first_batch"]),
            first_batch_deadline_s=(
                float(r["first_batch_deadline_s"])
                if pd.notna(r["first_batch_deadline_s"]) else None
            ),
            expected_time_s=float(r["expected_time_s"]),
        )

    sorties: list[Sortie] = []
    rows = []
    t_cursor = 0.0
    for _, srow in nodes_df[nodes_df["kind"] == "service"].iterrows():
        sid = str(srow["id"])
        svc_node = Node(sid, float(srow["lon"]), float(srow["lat"]), "service",
                        float(srow["ground_elev_m"]))
        out, back = leg_geometry_pair(prov, o01_node, svc_node, sample_step_m=30.0)
        pool = boxes_df[boxes_df["service_id"] == sid]
        total_mass = float(pool["mass_kg"].sum())
        total_vol = float(pool["volume_m3"].sum())

        # 选一个装得下的机型（质量 + 体积都满足）
        chosen = None
        for code in ("C", "B", "A"):
            u = uav_types[code]
            if total_mass <= u.max_payload_kg + 1e-9 and total_vol <= u.volume_m3 + 1e-12:
                try:
                    q = max_safe_payload(
                        u, out.distance_m, out.climb_m, out.descent_m,
                        back.climb_m, back.descent_m,
                    )
                except ValueError:
                    continue
                if total_mass <= q + 1e-9:
                    chosen = code
                    break
        if chosen is None:
            rows.append({"服务区": sid, "箱数": len(pool), "总质量": round(total_mass, 1),
                         "总体积": round(total_vol, 4), "机型": "—",
                         "备注": "无机型可一次装载（需拆分架次）"})
            continue

        u = uav_types[chosen]
        n = len(sorties)
        # ★ 必须按机型分别取用未占用的无人机与电池（循环复用会造成时段重叠）
        pool_ids = sorted(k for k, v in uav_id_to_type.items() if v == chosen)
        used_in_type = sum(1 for x in sorties if x.type_code == chosen)
        if used_in_type >= len(pool_ids):
            rows.append({"服务区": sid, "箱数": len(pool), "总质量": round(total_mass, 1),
                         "总体积": round(total_vol, 4), "机型": chosen,
                         "备注": f"{chosen} 型实体机耗尽（{len(pool_ids)} 架）"})
            continue
        uav_id = pool_ids[used_in_type]
        if used_in_type >= bat_inv[chosen]:
            rows.append({"服务区": sid, "箱数": len(pool), "总质量": round(total_mass, 1),
                         "总体积": round(total_vol, 4), "机型": chosen,
                         "备注": f"{chosen} 型电池耗尽（{bat_inv[chosen]} 组）"})
            continue
        bat_id = f"{chosen}-B{used_in_type + 1:02d}"
        from src.physics.energy import segment_time_s

        sorties.append(
            Sortie(
                sortie_id=f"T{n + 1:02d}",
                uav_id=uav_id,
                type_code=chosen,
                battery_id=bat_id,
                start_s=t_cursor,
                service_sequence=(sid,),
                box_ids=tuple(pool["box_id"].astype(str)),
                leg_distance_m=out.distance_m,
                climb_out_m=out.climb_m,
                descent_out_m=out.descent_m,
            )
        )
        t_cursor += 10.0
        rows.append({"服务区": sid, "箱数": len(pool), "总质量": round(total_mass, 1),
                     "总体积": round(total_vol, 4), "机型": chosen,
                     "往返时间_s": round(
                         segment_time_s(u, out.as_segment())
                         + segment_time_s(u, back.as_segment()), 1),
                     "备注": ""})

    df = pd.DataFrame(rows)
    out_dir = REPO / "outputs" / "p0_smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / "q1_naive_plan_by_service.csv", index=False, encoding="utf-8-sig")
    print()
    print(df.to_string(index=False))

    # ---------- 校验方案 ----------
    plan = TransportPlan(
        sorties=tuple(sorties),
        uav_fleet={k: int(v) for k, v in fleet_df.groupby("type_code").size().items()},
        battery_inventory=bat_inv,
        known_uav_ids=known_uav,
        known_battery_ids=known_bat,
        uav_id_to_type=uav_id_to_type,
    )
    rep = verify_transport_plan(plan, uav_types, boxes)
    print()
    print("--- 校验器结果（完整 80 箱、按服务区独立组批）---")
    print(rep.summary())
    if not rep.ok:
        from collections import Counter

        print()
        print("违规类型统计：")
        for t, c in Counter(v.type.value for v in rep.violations).most_common():
            print(f"  {t}: {c} 条")
        print()
        print("说明：本方案只做**每区一架次**的朴素组批，")
        print("      因此若某些服务区的箱数超过单机容量，必然出现缺箱 —— 这是预期的。")

    # ---------- 可行政方案：只覆盖 S011（单机一次可装完） ----------
    print()
    print("--- 可行政方案：只交付 S011 的 3 箱（单架次）---")
    s011_pool = boxes_df[boxes_df["service_id"] == "S011"]
    s011_node = Node("S011",
                     float(nodes_df.loc[nodes_df["id"] == "S011", "lon"].iloc[0]),
                     float(nodes_df.loc[nodes_df["id"] == "S011", "lat"].iloc[0]),
                     "service",
                     float(nodes_df.loc[nodes_df["id"] == "S011", "ground_elev_m"].iloc[0]))
    o11, b11 = leg_geometry_pair(prov, o01_node, s011_node, sample_step_m=30.0)
    good = Sortie(
        sortie_id="T01", uav_id="U07", type_code="C", battery_id="C-B01",
        start_s=0.0, service_sequence=("S011",),
        box_ids=tuple(s011_pool["box_id"].astype(str)),
        leg_distance_m=o11.distance_m, climb_out_m=o11.climb_m, descent_out_m=o11.descent_m,
        reported_delivery_times={"S011": 900.0},
    )
    only_s011 = {b: boxes[b] for b in s011_pool["box_id"].astype(str)}
    rep2 = verify_transport_plan(
        TransportPlan(
            sorties=(good,),
            uav_fleet={k: int(v) for k, v in fleet_df.groupby("type_code").size().items()},
            battery_inventory=bat_inv,
            known_uav_ids=known_uav,
            known_battery_ids=known_bat,
            uav_id_to_type=uav_id_to_type,
        ),
        uav_types,
        only_s011,
    )
    print(rep2.summary())

    # ---------- 负样本 A：漏交一箱 ----------
    print()
    print("--- 负样本 A：删掉一个货箱（校验器必须抓到缺箱）---")
    partial = Sortie(
        sortie_id="T01", uav_id="U07", type_code="C", battery_id="C-B01",
        start_s=0.0, service_sequence=("S011",),
        box_ids=tuple(s011_pool["box_id"].astype(str))[:-1],
        leg_distance_m=o11.distance_m, climb_out_m=o11.climb_m, descent_out_m=o11.descent_m,
    )
    rA = verify_transport_plan(TransportPlan(sorties=(partial,)), uav_types, only_s011)
    print(f"违规 {len(rA.violations)} 条；抓到缺箱 = "
          f"{rA.has(__import__('src.verify.feasibility', fromlist=['x']).ViolationType.MISSING_BOX)}")
    for v in rA.violations:
        print(f"   {v}")

    # ---------- 负样本 B：上报能耗造假 ----------
    print()
    print("--- 负样本 B：把上报能耗改成 0.1（校验器必须抓到不一致）---")
    fake = Sortie(
        sortie_id="T01", uav_id="U07", type_code="C", battery_id="C-B01",
        start_s=0.0, service_sequence=("S011",),
        box_ids=tuple(s011_pool["box_id"].astype(str)),
        leg_distance_m=o11.distance_m, climb_out_m=o11.climb_m, descent_out_m=o11.descent_m,
        reported_energy_kwh=0.1, reported_return_soc=0.99,
    )
    rB = verify_transport_plan(TransportPlan(sorties=(fake,)), uav_types, only_s011)
    print(f"违规 {len(rB.violations)} 条；真实能耗应为 "
          f"{verify_transport_plan(TransportPlan(sorties=(good,)), uav_types, only_s011).total_energy_kwh:.4f} kWh")
    for v in rB.violations:
        print(f"   {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
