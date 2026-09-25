"""问题四入口：救援任务分区与资源配置优化。

用法：
    python -m src.q4_partitioning.run_q4

输出（outputs/q4/）：
    metrics.json / params.json / run_log.json
    tables/  q4_分区配置（交付模板）、原子单元、桥接分析、方案对比、资源缺口
    tables/*.csv   原子单元、分区配置、资源缺口、逐组明细

★★ 核心结论（由数据推出，**不要硬编码**）★★
    题目规则要求"同一运输架次涉及的多服务区必须划入同一任务组"，
    因此分区被**原子单元（连通分量）**拓扑决定：

        合法分区的组数 K ∈ [1, 连通分量数]

    ★ 该数取决于 Q3 方案的形态，会随 Q3 重跑而变，**必须由代码打印**。
      例如某次 Q4 运行得到 2 个分量（S014 由单点架次单独成组，
      其余 14 区连成一片），则 **K=2 无需改动任何架次即可行**，
      而 K=3 需拆分 1 个多点架次才能得到 3 个分量。

    本模块的做法：
      (1) 求原子单元并定位**桥接架次**（移除后能增加分量数者）；
      (2) 若 K 超出现有分量数，给出**最小改动**方案（拆最少的多点架次）；
      (3) 在得到的方案上完成题目要求的全部核算与对比。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd


from src.common.config import DATA_PROCESSED, REPO_ROOT, outputs_dir
from src.common.io_utils import get_logger, save_json, save_metrics, save_table
from src.q0_data import build_processed as BP
from src.q4_partitioning.partition import (
    PartitionPlan,
    RelayRec,
    SortieRec,
    atomic_units,
    bridge_sorties,
    components,
    enumerate_partitions,
    group_resources,
    minimal_edits_for_partition,
    score_plan,
    select_best_partition,
)


TEMPLATE_COLS = [
    "K（2或3）", "任务组编号", "服务区列表",
    "A型运输无人机数", "B型运输无人机数", "C型运输无人机数",
    "A型电池组数", "B型电池组数", "C型电池组数",
    "中继无人机数", "中继能源组件数",
]


def load_q3() -> tuple[list[SortieRec], list[RelayRec]]:
    """读取 Q3 的运输与中继架次。"""
    s = pd.read_csv(REPO_ROOT / "outputs/q3/tables/q3_运输架次.csv")
    sorties = [
        SortieRec(
            sortie_id=str(r["架次编号"]), type_code=str(r["机型编号"]),
            uav_id=str(r["无人机编号"]), battery_id=str(r["电池编号"]),
            start_s=float(r["开始时刻（s）"]), return_s=float(r["返回O01时刻（s）"]),
            stops=tuple(str(r["访问服务区顺序"]).split("->")),
            energy_kwh=float(r["架次能耗（kWh）"]),
        )
        for _, r in s.iterrows()
    ]
    rp = REPO_ROOT / "outputs/q3/tables/q3_中继架次.csv"
    relays: list[RelayRec] = []
    if rp.exists():
        rr = pd.read_csv(rp)
        # ★ `q3_通信保障.csv` 现为**逐对**明细（一个中继架次可保障多个运输架次，
        #   本方案为 47 行）。早先按 "中继架次编号 → 运输架次编号" 建单值字典，
        #   后面的行会把前面的覆盖掉，导致每个中继只认最后一个受保障架次。
        #   这里改为一对多聚合。
        cov = pd.read_csv(REPO_ROOT / "outputs/q3/tables/q3_通信保障.csv")
        cover_of: dict[str, list[str]] = {}
        for _, c in cov.iterrows():
            cover_of.setdefault(str(c["中继架次编号"]), []).append(
                str(c["运输架次编号"]))
        relays = [
            RelayRec(
                sortie_id=str(r["中继架次编号"]), relay_uav_id=str(r["中继无人机编号"]),
                pack_id=str(r["能源组件编号"]), start_s=float(r["开始时刻（s）"]),
                link_ready_s=float(r["建链完成时刻（s）"]),
                service_end_s=float(r["服务结束时刻（s）"]),
                return_s=float(r["返回O01时刻（s）"]),
                energy_kwh=float(r["架次能耗（kWh）"]),
                covers=tuple(cover_of.get(str(r["中继架次编号"]), ())),
            )
            for _, r in rr.iterrows()
        ]
    return sorties, relays


def plan_rows(plan: PartitionPlan) -> list[dict]:
    """按 `结果提交模板.xlsx` 的 `Q4_分区配置` 列序输出。"""
    rows = []
    for g in plan.groups:
        rows.append({
            "K（2或3）": plan.k,
            "任务组编号": g.group_id,
            "服务区列表": "|".join(g.services),
            "A型运输无人机数": g.uav_by_type.get("A", 0),
            "B型运输无人机数": g.uav_by_type.get("B", 0),
            "C型运输无人机数": g.uav_by_type.get("C", 0),
            "A型电池组数": g.battery_by_type.get("A", 0),
            "B型电池组数": g.battery_by_type.get("B", 0),
            "C型电池组数": g.battery_by_type.get("C", 0),
            "中继无人机数": g.relay_uavs,
            "中继能源组件数": g.relay_packs,
        })
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="D 题问题四求解器")
    ap.add_argument("--max-enum", type=int, default=200_000,
                    help="分区枚举上限")
    args = ap.parse_args(argv)

    log = get_logger("q4")
    out = outputs_dir("q4")
    (out / "tables").mkdir(exist_ok=True)
    t0 = time.perf_counter()

    # ---------------- 载入 Q3 方案与库存 ----------------
    sorties, relays = load_q3()
    nodes = pd.read_csv(DATA_PROCESSED / "nodes.csv")
    all_services = sorted(nodes.loc[nodes["kind"] == "service", "id"].astype(str))
    uav_types = BP.load_uav_types()
    fleet_df = BP.load_uav_fleet()
    bat_df = BP.load_battery_inventory()
    relay_fleet = BP.load_relay_fleet()
    relay_inv = BP.load_relay_inventory()

    uav_energy = {str(r["code"]): float(r["energy_kwh"]) for _, r in uav_types.iterrows()}
    bat_t_full = {str(r["type_code"]): float(r["t_full_s"]) for _, r in bat_df.iterrows()}
    inventory = {c: int(n) for c, n in fleet_df.groupby("type_code").size().items()}
    battery_inventory = {
        str(r["type_code"]): int(r["n_battery_packs"]) for _, r in bat_df.iterrows()
    }
    relay_inventory = {
        "relay_uavs": len(relay_fleet),
        "relay_packs": int(relay_inv["n_energy_packs"].iloc[0]),
    }
    log.info("Q3 方案：运输 %d 架次 / 中继 %d 架次", len(sorties), len(relays))
    log.info("库存：运输机 %s / 电池 %s / 中继 %s / 能源组件 %d",
             inventory, battery_inventory, relay_inventory["relay_uavs"],
             relay_inventory["relay_packs"])

    # ---------------- (1) 原子单元与不可行性论证 ----------------
    units = atomic_units(sorties)
    bridges = bridge_sorties(sorties, all_services)
    log.info("原子单元 %d 个；桥接架次 %d 个", len(units), len(bridges))

    unit_rows = [
        {"单元编号": f"U{i+1:02d}", "服务区数": len(u), "服务区列表": "|".join(sorted(u))}
        for i, u in enumerate(sorted(units, key=lambda x: (len(x), sorted(x))))
    ]
    save_table(pd.DataFrame(unit_rows), out / "tables" / "q4_原子单元.csv")

    bridge_rows = [
        {"架次编号": b.sortie_id, "机型": b.type_code,
         "服务区顺序": "->".join(b.stops), "服务区数": len(b.stops),
         "移除后分量数": n}
        for b, n in bridges
    ]
    save_table(pd.DataFrame(
        bridge_rows,
        columns=["架次编号", "机型", "服务区顺序", "服务区数", "移除后分量数"],
    ), out / "tables" / "q4_桥接架次.csv")

    feasible_2 = len(units) >= 2
    feasible_3 = len(units) >= 3
    log.info("按题目规则直接分区：2 组可行=%s，3 组可行=%s", feasible_2, feasible_3)

    # 全部方案记录（含不可行的单组基线）
    comparison: list[dict] = []

    # ---- 基线：整队一组（唯一合法分区）----
    base_groups = [
        group_resources("G1", tuple(all_services), sorties, relays,
                        uav_energy, bat_t_full, owned_relays=list(relays))
    ]
    base_plan = PartitionPlan(k=1, groups=base_groups)
    g0 = base_plan.groups[0]
    comparison.append({
        "方案": "K=1（全部 15 区一组）", "K": 1,
        "可行": "是", "改动架次数": 0,
        "运输无人机": sum(base_plan.total_uavs.values()),
        "共享电池": sum(base_plan.total_batteries.values()),
        "中继无人机": base_plan.total_relay_uavs,
        "中继能源组件": base_plan.total_relay_packs,
        "资源总量": (sum(base_plan.total_uavs.values())
                  + sum(base_plan.total_batteries.values())
                  + base_plan.total_relay_uavs + base_plan.total_relay_packs),
        "组间不均衡": 0.0,
        "最大组工作量h": round(base_plan.max_group_workload / 3600, 2),
    })

    # ---------------- (2) 最小改动使分区可行 ----------------
    plans: dict[int, PartitionPlan] = {}
    edits_info: dict[int, list[SortieRec]] = {}
    for k in (2, 3):
        if len(units) >= k:
            best, n_enum = select_best_partition(
                units, k, sorties, relays, uav_energy, bat_t_full,
                inventory, battery_inventory, relay_inventory, args.max_enum,
            )
            plans[k] = best
            edits_info[k] = []
            log.info("K=%d：枚举 %d 个分区，选出资源总量 %d", k, n_enum,
                     sum(best.total_uavs.values()) + sum(best.total_batteries.values())
                     + best.total_relay_uavs + best.total_relay_packs)
        else:
            removed, n_comp = minimal_edits_for_partition(sorties, all_services, k)
            kept = [s for s in sorties if s not in removed]
            units2 = atomic_units(kept)
            if len(units2) < k:
                log.warning("K=%d：最小改动后分量数仍为 %d，无法分区", k, len(units2))
                continue
            # 被移除的架次：其服务区改为**单点架次**（工程可执行的改法）
            rebuilt = list(kept)
            # ★ 同步重映射中继保障关系：
            #   原 A→B 架次被拆成 A→x、A→y 后，原本保障 A 的中继
            #   需要分别保障这两条新架次（同一中继按其服务窗口逐个覆盖）。
            relay_map: dict[str, list[str]] = {}
            for r in removed:
                for st in r.stops:
                    relay_map.setdefault(r.sortie_id, []).append(f"{r.sortie_id}-{st}")
                    rebuilt.append(SortieRec(
                        sortie_id=f"{r.sortie_id}-{st}", type_code=r.type_code,
                        uav_id=r.uav_id, battery_id=r.battery_id,
                        start_s=r.start_s, return_s=r.return_s, stops=(st,),
                        energy_kwh=0.0,
                    ))
            rebuilt_relays = [
                RelayRec(
                    sortie_id=r.sortie_id, relay_uav_id=r.relay_uav_id,
                    pack_id=r.pack_id, start_s=r.start_s,
                    link_ready_s=r.link_ready_s, service_end_s=r.service_end_s,
                    return_s=r.return_s, energy_kwh=r.energy_kwh,
                    covers=tuple(
                        nid
                        for old in r.covers
                        for nid in relay_map.get(old, [old])
                    ),
                )
                for r in relays
            ]
            best, n_enum = select_best_partition(
                units2, k, rebuilt, rebuilt_relays, uav_energy, bat_t_full,
                inventory, battery_inventory, relay_inventory, args.max_enum,
            )
            plans[k] = best
            edits_info[k] = removed
            log.info("K=%d：需拆分 %d 个多点架次为单点（+%d 架次），枚举 %d 个分区",
                     k, len(removed), len(removed) * 2 - len(removed), n_enum)

    # ---------------- (3) 方案对比与缺口 ----------------
    for k, plan in sorted(plans.items()):
        removed = edits_info.get(k, [])
        direct = len(units) >= k
        comparison.append({
            "方案": (f"K={k}（直接可行）" if direct and not removed
                     else f"K={k}（需拆分 {len(removed)} 个多点架次）"),
            "K": k,
            "可行": ("是" if direct and not removed else "改动后可行"),
            "改动架次数": len(removed),
            "运输无人机": sum(plan.total_uavs.values()),
            "共享电池": sum(plan.total_batteries.values()),
            "中继无人机": plan.total_relay_uavs,
            "中继能源组件": plan.total_relay_packs,
            "资源总量": (sum(plan.total_uavs.values())
                      + sum(plan.total_batteries.values())
                      + plan.total_relay_uavs + plan.total_relay_packs),
            "组间不均衡": round(plan.workload_imbalance, 4),
            "最大组工作量h": round(plan.max_group_workload / 3600, 2),
        })
    cmp_df = pd.DataFrame(comparison)
    save_table(cmp_df, out / "tables" / "q4_方案对比.csv")
    log.info("方案对比完成：%d 个方案", len(cmp_df))

    # 交付模板表：输出全部可行方案（K=1 基线 + 改动后的 K=2/3）
    rows = plan_rows(base_plan)
    for k, plan in sorted(plans.items()):
        rows.extend(plan_rows(plan))
    save_table(pd.DataFrame(rows, columns=TEMPLATE_COLS),
               out / "tables" / "q4_分区配置.csv")

    # 资源缺口（逐方案、逐类）
    gap_rows = []
    caps = {
        "A型运输无人机数": ("A", inventory),
        "B型运输无人机数": ("B", inventory),
        "C型运输无人机数": ("C", inventory),
        "A型电池组数": ("A", battery_inventory),
        "B型电池组数": ("B", battery_inventory),
        "C型电池组数": ("C", battery_inventory),
    }
    for name, plan in [("K=1", base_plan)] + [(f"K={k}", p) for k, p in sorted(plans.items())]:
        uav_tot = plan.total_uavs
        bat_tot = plan.total_batteries
        for label, (code, src) in caps.items():
            need = uav_tot.get(code, 0) if "无人机" in label else bat_tot.get(code, 0)
            have = src.get(code, 0)
            gap_rows.append({
                "方案": name, "资源": label, "需求": need, "库存": have,
                "冗余": have - need, "缺口": max(0, need - have),
            })
        for label, need, have in (
            ("中继无人机数", plan.total_relay_uavs, relay_inventory["relay_uavs"]),
            ("中继能源组件数", plan.total_relay_packs, relay_inventory["relay_packs"]),
        ):
            gap_rows.append({
                "方案": name, "资源": label, "需求": need, "库存": have,
                "冗余": have - need, "缺口": max(0, need - have),
            })
    gap_df = pd.DataFrame(gap_rows)
    save_table(gap_df, out / "tables" / "q4_资源缺口.csv")

    # 逐组明细
    grp_rows = []
    for name, plan in [("K=1", base_plan)] + [(f"K={k}", p) for k, p in sorted(plans.items())]:
        for g in plan.groups:
            grp_rows.append({
                "方案": name, "任务组": g.group_id, "服务区数": len(g.services),
                "服务区列表": "|".join(g.services),
                "运输架次": g.n_sorties, "中继架次": g.n_relay_sorties,
                "A机": g.uav_by_type.get("A", 0), "B机": g.uav_by_type.get("B", 0),
                "C机": g.uav_by_type.get("C", 0),
                "A电池": g.battery_by_type.get("A", 0),
                "B电池": g.battery_by_type.get("B", 0),
                "C电池": g.battery_by_type.get("C", 0),
                "中继机": g.relay_uavs, "中继组件": g.relay_packs,
                "能耗kWh": round(g.total_energy_kwh, 3),
                "工作量h": round(g.workload_s / 3600, 2),
            })
    save_table(pd.DataFrame(grp_rows), out / "tables" / "q4_逐组明细.csv")

    # ---------------- 图 ----------------
    log.info("图已改由 src/report/make_figures.py 统一生成（论文图表唯一产出点）；"
             "本模块只产出 outputs/ 下的数据表，不再自绘图片。")
    log.info("完成，用时 %.1f s", time.perf_counter() - t0)
    return 0


if __name__ == "__main__":
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    raise SystemExit(main())
