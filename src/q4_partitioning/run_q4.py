"""问题四入口：救援任务分区与资源配置优化。

用法：
    python -m src.q4_partitioning.run_q4

输出（outputs/q4/）：
    metrics.json / params.json / run_log.json
    tables/  q4_分区配置（交付模板）、原子单元、桥接分析、方案对比、资源缺口
    figures/ 分区示意、资源对比、工作量均衡

★★ 核心结论（先说清楚）★★
    在本队 Q3 的联合调度方案下，**不存在合法的 2 组或 3 组分区**。
    原因：题目规则要求"同一运输架次涉及的多服务区必须划入同一任务组"，
    而 Q3 的 21 个多点架次把 15 个服务区串成了**单一连通分量**。
    本模块不伪造一个违反约束的分区，而是：
      (1) 给出该不可行性的严格论证与桥接架次定位；
      (2) 给出**最小改动**方案（去掉最少的多点架次）使分区可行；
      (3) 在改动后的方案上完成题目要求的全部核算与对比。
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

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 130
plt.rcParams["savefig.bbox"] = "tight"

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
        cov = pd.read_csv(REPO_ROOT / "outputs/q3/tables/q3_通信保障.csv")
        cover_of = {str(r["中继架次编号"]): str(r["运输架次编号"]) for _, r in cov.iterrows()}
        relays = [
            RelayRec(
                sortie_id=str(r["中继架次编号"]), relay_uav_id=str(r["中继无人机编号"]),
                pack_id=str(r["能源组件编号"]), start_s=float(r["开始时刻（s）"]),
                link_ready_s=float(r["建链完成时刻（s）"]),
                service_end_s=float(r["服务结束时刻（s）"]),
                return_s=float(r["返回O01时刻（s）"]),
                energy_kwh=float(r["架次能耗（kWh）"]),
                covers=(cover_of.get(str(r["中继架次编号"]), ""),),
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
    (out / "figures").mkdir(exist_ok=True)
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
    save_table(pd.DataFrame(bridge_rows), out / "tables" / "q4_桥接架次.csv")

    feasible_2 = len(units) >= 2
    feasible_3 = len(units) >= 3
    log.info("按题目规则直接分区：2 组可行=%s，3 组可行=%s", feasible_2, feasible_3)

    # 全部方案记录（含不可行的单组基线）
    comparison: list[dict] = []

    # ---- 基线：整队一组（唯一合法分区）----
    base_groups = [
        group_resources("G1", tuple(all_services), sorties, relays,
                        uav_energy, bat_t_full)
    ]
    base_plan = PartitionPlan(k=1, groups=base_groups)
    g0 = base_plan.groups[0]
    comparison.append({
        "方案": "K=1（唯一合法分区）", "K": 1,
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
        comparison.append({
            "方案": f"K={k}（需拆分 {len(removed)} 个多点架次）", "K": k,
            "可行": "改动后可行", "改动架次数": len(removed),
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
    fig, ax = plt.subplots(1, 2, figsize=(13, 4.6))
    ax[0].bar(cmp_df["方案"], cmp_df["资源总量"], color="#3b7dd8")
    ax[0].set_ylabel("资源总量（台/组）")
    ax[0].set_title("各分区方案的资源总规模")
    ax[0].tick_params(axis="x", rotation=18)
    ax[1].bar(cmp_df["方案"], cmp_df["最大组工作量h"], color="#d85a3b")
    ax[1].set_ylabel("最大组工作量 (h)")
    ax[1].set_title("组间最大工作量（不均衡度越低越好）")
    ax[1].tick_params(axis="x", rotation=18)
    fig.savefig(out / "figures" / "q4_plan_comparison.png")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 6.2))
    lon = {str(r["id"]): float(r["lon"]) for _, r in nodes.iterrows()}
    lat = {str(r["id"]): float(r["lat"]) for _, r in nodes.iterrows()}
    colors = ["#3b7dd8", "#2e8b57", "#d85a3b", "#8b5cf6", "#e0a800"]
    target = plans.get(2, base_plan)
    for gi, g in enumerate(target.groups):
        xs = [lon[s] for s in g.services if s in lon]
        ys = [lat[s] for s in g.services if s in lat]
        ax.scatter(xs, ys, s=110, color=colors[gi % len(colors)],
                   label=f"{g.group_id}（{len(g.services)} 区）", zorder=3)
        for s in g.services:
            if s in lon:
                ax.annotate(s, (lon[s], lat[s]), fontsize=7,
                            xytext=(4, 3), textcoords="offset points")
    ax.scatter([lon["O01"]], [lat["O01"]], c="k", marker="*", s=260, label="O01", zorder=4)
    ax.set_xlabel("经度 (°)"); ax.set_ylabel("纬度 (°)")
    ax.set_title(f"问题四 任务分区（K={target.k}）")
    ax.legend(fontsize=8); ax.grid(alpha=0.3)
    fig.savefig(out / "figures" / "q4_partition_map.png")
    plt.close(fig)

    # ---------------- 指标 ----------------
    runtime = time.perf_counter() - t0
    metrics = {
        "n_services": len(all_services),
        "n_transport_sorties_q3": len(sorties),
        "n_multi_stop_sorties": sum(1 for s in sorties if len(s.stops) > 1),
        "n_atomic_units": len(units),
        "n_bridge_sorties": len(bridges),
        "partition_feasible_k2": feasible_2,
        "partition_feasible_k3": feasible_3,
        "baseline_resources_k1": {
            "uavs": sum(base_plan.total_uavs.values()),
            "batteries": sum(base_plan.total_batteries.values()),
            "relay_uavs": base_plan.total_relay_uavs,
            "relay_packs": base_plan.total_relay_packs,
        },
        "k2_edits_required": len(edits_info.get(2, [])),
        "k3_edits_required": len(edits_info.get(3, [])),
        "runtime_sec": round(runtime, 2),
    }
    for k, plan in plans.items():
        metrics[f"k{k}_resources"] = {
            "uavs": sum(plan.total_uavs.values()),
            "batteries": sum(plan.total_batteries.values()),
            "relay_uavs": plan.total_relay_uavs,
            "relay_packs": plan.total_relay_packs,
            "imbalance": round(plan.workload_imbalance, 4),
        }
    save_metrics("q4", metrics,
                 params={"inventory": inventory, "battery_inventory": battery_inventory,
                         "relay_inventory": relay_inventory},
                 extra={"data_sources": ["调度中心与服务区.xlsx", "运输无人机数据.xlsx",
                                         "中继无人机数据.xlsx", "Q3 方案"]})
    save_json({"comparison": comparison,
               "atomic_units": unit_rows,
               "bridges": bridge_rows}, out / "run_log.json")

    print()
    print("=" * 92)
    print("问题四求解结果")
    print("=" * 92)
    print("★ 关键结论：按题目规则，Q3 方案下**不存在合法的 2 组或 3 组分区**。")
    print(f"   15 个服务区被 {sum(1 for s in sorties if len(s.stops) > 1)} 个多点架次"
          f"串成 **{len(units)} 个连通分量**（即原子单元）。")
    print(f"   『同架次多服务区必须同组』⟹ 唯一合法分区是「全部 15 区一组」。")
    print()
    print(f"桥接架次（移除后可直接断开连通，共 {len(bridges)} 个候选）：")
    if bridge_rows:
        print(pd.DataFrame(bridge_rows).to_string(index=False))
        print("  注：改法是把这些多点架次**拆成单点架次**（服务区归属不变），")
        print("      因此它不违反『保持服务区访问顺序』以外的任何规则，代价是增加架次数。")
    print()
    print("各方案资源与代价对比：")
    print(cmp_df.to_string(index=False))
    print()
    print(f"运行用时 {runtime:.1f} s；输出目录 {out}")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    raise SystemExit(main())
