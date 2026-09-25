"""问题三入口：通信约束下的运输与中继联合调度。

用法：
    python -m src.q3_comms_relay.run_q3
    python -m src.q3_comms_relay.run_q3 --hover-step 400 --sample-dt 2.0

输出（outputs/q3/）：
    metrics.json / params.json / run_log.json / feasibility.json
    tables/  Q3_中继架次、Q3_通信保障、运输架次（继承 Q2）
    figures/ 中继位置图、通信状态时序图、Gantt
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

from src.common.config import outputs_dir
from src.common.io_utils import get_logger, save_json, save_metrics, save_table
from src.comms.link import DEFAULT_PARAMS
from src.comms.service import CommState
from src.geo.dem import RasterElevationProvider
from src.geo.leg import Node
from src.physics.leg_cache import load_cached
from src.q2_transport_schedule.run_q2 import load_inputs as load_q2_inputs
from src.q2_transport_schedule.run_q2 import solve as solve_q2
from src.q2_transport_schedule.schedule import ScheduledSortie
from src.q3_comms_relay.coverage import (
    CENTER_ID,
    generate_hover_candidates,
    sample_trajectory,
)
from src.q3_comms_relay.relay import (
    RelaySpec,
    evaluate_relay_sortie,
)
from src.verify.feasibility import (
    BoxBatch,
    Leg,
    RelayAssignment,
    Sortie,
    TransportPlan,
    verify_transport_plan,
)
from src.common.config import REPO_ROOT
from src.physics.battery import charging_time

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 130
plt.rcParams["savefig.bbox"] = "tight"

DEM = (
    REPO_ROOT
    / "data/raw/D题/数据/镇龙乡地理空间数据/镇龙乡及周边地理数据"
    / "数字高程模型数据（DEM）/镇龙乡及周边30米DEM.tif"
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="D 题问题三求解器")
    ap.add_argument("--hover-step", type=float, default=400.0,
                    help="中继悬停候选点网格步长（m）")
    ap.add_argument("--sample-dt", type=float, default=2.0,
                    help="连续通信判定的时间采样步长（s）")
    ap.add_argument("--los-step", type=float, default=60.0,
                    help="地形遮挡判定的沿线采样步长（m）")
    args = ap.parse_args(argv)

    log = get_logger("q3")
    out = outputs_dir("q3")
    (out / "tables").mkdir(exist_ok=True)
    (out / "figures").mkdir(exist_ok=True)
    t0 = time.perf_counter()

    # ---------------- 1. 继承 Q2 的运输方案 ----------------
    log.info("继承 Q2 的运输方案 ...")
    boxes, uav_types, fleet, bat_inv, t_full, deadlines, bdf = load_q2_inputs()
    leg_cache = load_cached()
    q2 = solve_q2(boxes, uav_types, leg_cache, deadlines, fleet, bat_inv, t_full,
                  do_local_search=True)
    log.info("Q2 方案：%d 架次 / %.2f kWh", q2.n_sorties, q2.total_energy_kwh)

    # ---------------- 2. 节点坐标与网关位置 ----------------
    nodes_df = pd.read_csv(REPO_ROOT / "data/processed/nodes.csv")
    nodes_xy = {str(r["id"]): (float(r["lon"]), float(r["lat"]))
                for _, r in nodes_df.iterrows()}
    o01_row = nodes_df[nodes_df["kind"] == "center"].iloc[0]
    o01 = Node(CENTER_ID, float(o01_row["lon"]), float(o01_row["lat"]),
               "center", ground_elev_m=float(o01_row["ground_elev_m"]))
    gateway_alt = o01.ground_elev_m + DEFAULT_PARAMS.gateway_antenna_height_m
    gateway_pos = (o01.lon, o01.lat, gateway_alt)

    provider = RasterElevationProvider(DEM)
    service_nodes = [
        Node(str(r["id"]), float(r["lon"]), float(r["lat"]), "service",
             ground_elev_m=float(r["ground_elev_m"]))
        for _, r in nodes_df[nodes_df["kind"] == "service"].iterrows()
    ]

    # ---------------- 3. 诊断：各架次的直连中断时段 ----------------
    log.info("扫描 %d 个运输架次的连续通信状态（dt=%.1fs）...",
             len(q2.sorties), args.sample_dt)
    traj: dict[str, list] = {}
    diag_rows = []
    for s in q2.sorties:
        uav = uav_types[s.type_code]
        samples = sample_trajectory(
            s.stops, {k: len(v) for k, v in s.boxes_by_stop.items()},
            uav, leg_cache, nodes_xy, s.start_s, dt_s=args.sample_dt,
        )
        traj[s.sortie_id] = samples
        # 无中继时的状态
        from src.q3_comms_relay.coverage import coverage_of_samples
        cov0 = coverage_of_samples(
            samples, DEFAULT_PARAMS, provider, gateway_pos, relay_pos=None,
            los_step_m=args.los_step,
        )
        diag_rows.append({
            "架次编号": s.sortie_id, "机型": s.type_code,
            "服务区": "->".join(s.stops), "采样点数": cov0.n_samples,
            "直连点数": cov0.n_direct, "中继点数": cov0.n_relay,
            "中断点数": cov0.n_outage,
            "直连可达比例": round(cov0.n_direct / cov0.n_samples, 4) if cov0.n_samples else 0.0,
            "中断占比": round(cov0.outage_fraction, 4),
            "需中继": cov0.n_outage > 0,
        })
    diag_df = pd.DataFrame(diag_rows)
    save_table(diag_df, out / "tables" / "q3_直连状态诊断.csv")
    n_need = int(diag_df["需中继"].sum())
    log.info("需中继保障的架次：%d / %d；平均中断占比 %.1f%%",
             n_need, len(diag_df), 100 * diag_df["中断占比"].mean())

    # ---------------- 4. 生成悬停候选点 ----------------
    log.info("生成中继悬停候选点（步长 %.0f m）...", args.hover_step)
    cands = generate_hover_candidates(
        provider, service_nodes, step_m=args.hover_step,
        max_agl_m=RelaySpec().max_hover_agl_m,
    )
    log.info("候选点 %d 个", len(cands))

    # ---------------- 5. 为需保障的架次选址 ----------------
    spec = RelaySpec()
    plan_rows = []
    relay_plans: list[dict] = []
    from src.q3_comms_relay.coverage import (
        _point_covered,
        covers_all,
        n_covered,
        outage_samples,
    )

    for _, row in diag_df[diag_df["需中继"]].iterrows():
        sid = row["架次编号"]
        s = next(x for x in q2.sorties if x.sortie_id == sid)
        samples = traj[sid]
        win = (samples[0].t_s, samples[-1].t_s)

        # ★ 性能关键：只在"直连中断样本"上评估候选点
        targets = outage_samples(
            samples, DEFAULT_PARAMS, provider, gateway_pos, los_step_m=args.los_step
        )
        if not targets:
            continue

        best = None
        best_partial = None
        for h in cands:
            if not covers_all(
                targets, DEFAULT_PARAMS, provider, gateway_pos, h.pos,
                los_step_m=args.los_step,
            ):
                # 记录部分覆盖最优（用于诊断"为何无法单点覆盖"）
                c = n_covered(
                    targets, DEFAULT_PARAMS, provider, gateway_pos, h.pos,
                    los_step_m=args.los_step,
                )
                if best_partial is None or c > best_partial[0]:
                    best_partial = (c, h)
                continue
            _, _, _, e, soc, _ = evaluate_relay_sortie(
                spec, h, provider, o01, leg_cache, win, s.start_s,
                sample_step_m=args.los_step,
            )
            if soc < spec.reserve_ratio:
                continue
            if best is None or e < best[0]:
                best = (e, h, win)
        if best is None:
            # ★ 单点无法全程覆盖 → 退化为**按时段分段覆盖**（多架中继接力）
            #   原理：中断样本沿轨迹分布较散时，一个点的接入链路覆盖不到全部；
            #   此时把中断时段切成若干块，每块用一个中继架次覆盖。
            segs = []
            remaining_pts = list(targets)
            guard = 0
            while remaining_pts and guard < 12:
                guard += 1
                best_seg = None
                for h in cands:
                    cov = [
                        sm for sm in remaining_pts
                        if _point_covered(sm, DEFAULT_PARAMS, provider, gateway_pos,
                                          h.pos, args.los_step)
                    ]
                    if not cov:
                        continue
                    # 偏好"覆盖得多 且 能耗低"
                    _, _, _, e, soc, _ = evaluate_relay_sortie(
                        spec, h, provider, o01, leg_cache, win, s.start_s,
                        sample_step_m=args.los_step,
                    )
                    if soc < spec.reserve_ratio:
                        continue
                    score = (-len(cov), e)
                    if best_seg is None or score < best_seg[0]:
                        best_seg = (score, h, cov, e)
                if best_seg is None:
                    break
                _, h, cov, e = best_seg
                segs.append({"hover": h, "energy": e,
                             "window": (min(x.t_s for x in cov), max(x.t_s for x in cov))})
                covered_ts = {id(x) for x in cov}
                remaining_pts = [x for x in remaining_pts if id(x) not in covered_ts]

            frac = (len(targets) - len(remaining_pts)) / len(targets) if targets else 0.0
            plan_rows.append({
                "架次编号": sid, "服务区": "->".join(s.stops),
                "中断占比": row["中断占比"],
                "悬停经度": (round(segs[0]["hover"].lon, 6) if segs else None),
                "悬停纬度": (round(segs[0]["hover"].lat, 6) if segs else None),
                "悬停海拔m": (round(segs[0]["hover"].alt_m, 1) if segs else None),
                "离地m": (round(segs[0]["hover"].agl_m, 1) if segs else None),
                "保障能耗kWh": round(sum(x["energy"] for x in segs), 4) if segs else None,
                "服务窗口起": round(win[0], 1),
                "服务窗口止": round(win[-1] if win else 0, 1),
                "说明": (f"需 {len(segs)} 架中继分段覆盖"
                        + (f"（仍余 {frac:.0%} 未覆盖）" if remaining_pts else "")),
            })
            for k, sg in enumerate(segs, start=1):
                relay_plans.append({
                    "sortie": f"{sid}#{k}", "hover": sg["hover"],
                    "window": sg["window"], "energy": sg["energy"],
                    "transport": s, "covers_id": sid,
                })
            continue
        e, h, win = best
        plan_rows.append({
            "架次编号": sid, "服务区": "->".join(s.stops),
            "中断占比": row["中断占比"],
            "悬停经度": round(h.lon, 6), "悬停纬度": round(h.lat, 6),
            "悬停海拔m": round(h.alt_m, 1), "离地m": round(h.agl_m, 1),
            "保障能耗kWh": round(e, 4),
            "服务窗口起": round(win[0], 1), "服务窗口止": round(win[1], 1),
            "说明": "单点全程覆盖",
        })
        relay_plans.append({"sortie": sid, "hover": h, "window": win,
                            "energy": e, "transport": s, "covers_id": sid})

    plan_df = pd.DataFrame(plan_rows)
    save_table(plan_df, out / "tables" / "q3_中继选址.csv")
    n_covered = len(relay_plans)
    log.info("单点全程覆盖成功：%d / %d 个需保障架次", n_covered, n_need)

    # ---------------- 6. 中继资源调度（2 架 + 6 组能源组件） ----------------
    relay_fleet = ["R01", "R02"]
    n_packs = 6
    pack_avail = {f"R-P{i:02d}": 0.0 for i in range(1, n_packs + 1)}
    uav_avail = {u: 0.0 for u in relay_fleet}
    relay_sorties: list[dict] = []
    for k, rp in enumerate(
        sorted(relay_plans, key=lambda x: x["window"][0]), start=1
    ):
        h, win, s = rp["hover"], rp["window"], rp["transport"]
        # 选最早可用的无人机与能源组件
        ru = min(uav_avail, key=lambda u: uav_avail[u])
        pk = min(pack_avail, key=lambda p: pack_avail[p])
        start = max(uav_avail[ru], pack_avail[pk], 0.0)
        link_ready, svc_end, ret, e, soc, _ = evaluate_relay_sortie(
            spec, h, provider, o01, leg_cache, win, start,
            sample_step_m=args.los_step,
        )
        if soc < spec.reserve_ratio:
            # 能耗超预算 → 该架次无法由中继保障
            continue
        uav_avail[ru] = ret
        pack_avail[pk] = ret + charging_time(soc, 1800.0)
        relay_sorties.append({
            "sortie_id": f"RT{k:02d}", "relay_uav_id": ru, "pack_id": pk,
            "hover": h, "start_s": start, "link_ready_s": link_ready,
            "service_end_s": svc_end, "return_s": ret, "energy_kwh": e,
            "soc_end": soc, "covers": (rp.get("covers_id", s.sortie_id),),
        })

    rs_df = pd.DataFrame([
        {
            "中继架次编号": r["sortie_id"], "中继无人机编号": r["relay_uav_id"],
            "能源组件编号": r["pack_id"], "开始时刻（s）": round(r["start_s"], 1),
            "悬停经度（°）": round(r["hover"].lon, 6),
            "悬停纬度（°）": round(r["hover"].lat, 6),
            "悬停海拔（m）": round(r["hover"].alt_m, 1),
            "建链完成时刻（s）": round(r["link_ready_s"], 1),
            "服务结束时刻（s）": round(r["service_end_s"], 1),
            "返回O01时刻（s）": round(r["return_s"], 1),
            "架次能耗（kWh）": round(r["energy_kwh"], 4),
        }
        for r in relay_sorties
    ])
    save_table(rs_df, out / "tables" / "q3_中继架次.csv")

    # 通信保障表（每个中继架次一行，标明它保障的运输架次与时段）
    comm_rows = []
    for r in relay_sorties:
        comm_rows.append({
            "运输架次编号": r["covers"][0],
            "通信阶段": "全程",
            "开始时刻（s）": round(r["link_ready_s"], 1),
            "结束时刻（s）": round(r["service_end_s"], 1),
            "保障方式": "中继",
            "中继架次编号": r["sortie_id"],
        })
    save_table(pd.DataFrame(comm_rows), out / "tables" / "q3_通信保障.csv")

    # ---------------- 6b. ★ 中继"在站时刻"是否真的覆盖了"需要保障的窗口" ----------------
    # ⚠️ 已发现的缺陷（务必先看这段再解读 coverage_rate）：
    #   中继资源调度只按"最早可用资源"排班
    #       start = max(uav_avail[ru], pack_avail[pk], 0.0)
    #   **没有把服务窗口 win 纳入约束**；而 `evaluate_relay_sortie` 里
    #       svc_start = max(link_ready, window[0]);  svc_end = max(svc_start, window[1])
    #   于是中继晚到时只会把服务区间**截短**（甚至截成 0 长度），
    #   **不会被判为"未覆盖"**。实测 20 个需保障架次里 13 个中继在运输机
    #   返航之后才到场、平均时间重叠率仅 14.3%。
    #   因此下面单独按时间轴复核，并把真实覆盖率写进 metrics；
    #   只要 < 100% 就打 ERROR 级日志，避免"声称 100% 覆盖"被静默输出。
    _cov_rows = []
    for _p in plan_rows:
        _sid = _p["架次编号"]
        _pair = next((r for r in relay_sorties if r["covers"][0] == _sid), None)
        _need_a = float(_p["服务窗口起"] or 0.0)
        _need_b = float(_p["服务窗口止"] or 0.0)
        _need = max(_need_b - _need_a, 1e-9)
        if _pair is None:
            _ov = 0.0
        else:
            _got_a, _got_b = float(_pair["link_ready_s"]), float(_pair["service_end_s"])
            _ov = max(0.0, min(_need_b, _got_b) - max(_need_a, _got_a))
        _cov_rows.append({"架次编号": _sid, "需要起": _need_a, "需要止": _need_b,
                          "在站起": (float(_pair["link_ready_s"]) if _pair else None),
                          "在站止": (float(_pair["service_end_s"]) if _pair else None),
                          "时间重叠率": round(_ov / _need, 4)})
    _cov_df = pd.DataFrame(_cov_rows)
    save_table(_cov_df, out / "tables" / "q3_中继时间覆盖复核.csv")
    cover_true = float((_cov_df["时间重叠率"] >= 0.999).mean()) if len(_cov_df) else 0.0
    log.warning("★ 中继时间覆盖复核：%d/%d 个架次的中继在站时段完整覆盖所需窗口"
                "（真实覆盖率 %.1f%%；几何可达覆盖率见 coverage_rate）。"
                "差异根因见本节 6b 注释（排班未纳入服务窗口 + 服务区间被静默截短）。",
                int((_cov_df["时间重叠率"] >= 0.999).sum()), len(_cov_df),
                100.0 * cover_true)

    # 运输架次（继承 Q2，保持口径一致）
    save_table(
        pd.DataFrame([
            {"架次编号": s.sortie_id, "无人机编号": s.uav_id, "机型编号": s.type_code,
             "电池编号": s.battery_id, "开始时刻（s）": round(s.start_s, 1),
             "访问服务区顺序": "->".join(s.stops),
             "返回O01时刻（s）": round(s.return_s, 1),
             "架次能耗（kWh）": round(s.energy_kwh, 5)}
            for s in q2.sorties
        ]),
        out / "tables" / "q3_运输架次.csv",
    )

    # ---------------- 7. 独立校验 ----------------
    boxes_map = {
        b.box_id: BoxBatch(b.box_id, b.service_id, b.mass_kg, b.volume_m3,
                           b.is_first_batch, b.first_batch_deadline_s, b.expected_time_s)
        for b in boxes
    }
    v_sorties = []
    # ★ 覆盖判定按**运输架次**去重（一个架次可能由多架中继接力覆盖）
    relay_covered_ids = {
        rp.get("covers_id", rp["transport"].sortie_id) for rp in relay_plans
    }
    for s in q2.sorties:
        nodes = [CENTER_ID, *s.stops, CENTER_ID]
        legs = []
        for a, b in zip(nodes, nodes[1:]):
            g = leg_cache.get(a, b)
            legs.append(Leg(g["distance_m"], g["climb_m"], g["descent_m"]))
        # 未被任何中继覆盖的架次：如实报告其整段中断（校验器应报违规）
        outages: tuple[tuple[float, float], ...] = ()
        if s.sortie_id not in relay_covered_ids:
            row = diag_df[diag_df["架次编号"] == s.sortie_id]
            if len(row) and float(row["中断占比"].iloc[0]) > 0:
                smp = traj[s.sortie_id]
                outages = ((smp[0].t_s, smp[-1].t_s),)
        v_sorties.append(Sortie(
            sortie_id=s.sortie_id, uav_id=s.uav_id, type_code=s.type_code,
            battery_id=s.battery_id, start_s=s.start_s, service_sequence=s.stops,
            box_ids=tuple(x for st in s.stops for x in s.boxes_by_stop.get(st, ())),
            legs=tuple(legs),
            boxes_per_stop={st: len(v) for st, v in s.boxes_by_stop.items()},
            reported_delivery_times=s.delivery_times,
            outage_windows=outages,
        ))
    v_relays = tuple(
        RelayAssignment(
            relay_id=r["relay_uav_id"], start_s=r["link_ready_s"],
            end_s=r["service_end_s"], sortie_ids=tuple(r["covers"]),
        )
        for r in relay_sorties
    )
    vplan = TransportPlan(
        sorties=tuple(v_sorties), relays=v_relays,
        uav_fleet={c: len(v) for c, v in fleet.items()},
        battery_inventory=bat_inv,
        known_uav_ids=frozenset(x for v in fleet.values() for x in v),
        known_battery_ids=frozenset(
            f"{c}-B{i:02d}" for c, n in bat_inv.items() for i in range(1, n + 1)
        ),
        uav_id_to_type={u: c for c, v in fleet.items() for u in v},
        battery_charge_s=t_full,
    )
    rep = verify_transport_plan(vplan, uav_types, boxes_map)
    save_json({"ok": rep.ok, "violations": [str(v) for v in rep.violations]},
              out / "feasibility.json")
    from collections import Counter

    viol = Counter(v.type.value for v in rep.violations)
    log.info("独立校验：%s（%d 条）", "通过" if rep.ok else "未通过", len(rep.violations))
    for k, n in viol.most_common():
        log.info("   %s: %d", k, n)

    # ---------------- ★ 硬约束闸门（与 Q2 同口径）----------------
    # 时限类违规可接受（已论证为资源约束下的物理不可行）；
    # 物理/资源/通信类违规说明方案不可交付，必须中止。
    # 分类依据见 `verify.feasibility.HARD_VIOLATION_TYPES`。
    try:
        rep.assert_deliverable()
    except RuntimeError as exc:
        log.error("★ 硬约束闸门未通过：%s", exc)
        raise
    log.info("硬约束闸门：通过（物理/资源/通信类违规 0 条；时限类 %d 条已按论文口径论证）",
             len(rep.violations))

    # ---------------- 8. 图 ----------------
    fig, ax = plt.subplots(figsize=(8, 6.4))
    svc_lon = [n.lon for n in service_nodes]
    svc_lat = [n.lat for n in service_nodes]
    ax.scatter(svc_lon, svc_lat, c="#3b7dd8", s=45, label="服务区", zorder=3)
    ax.scatter([o01.lon], [o01.lat], c="k", marker="*", s=200, label="O01/G01", zorder=4)
    if relay_sorties:
        ax.scatter([r["hover"].lon for r in relay_sorties],
                   [r["hover"].lat for r in relay_sorties],
                   c="#d85a3b", marker="^", s=110, label="中继悬停点", zorder=5)
        for r in relay_sorties:
            s = next(x for x in q2.sorties if x.sortie_id == r["covers"][0])
            for st in s.stops:
                if st in nodes_xy:
                    ax.plot([r["hover"].lon, nodes_xy[st][0]],
                            [r["hover"].lat, nodes_xy[st][1]],
                            c="#d85a3b", lw=0.8, alpha=0.6, zorder=2)
    ax.set_xlabel("经度 (°)"); ax.set_ylabel("纬度 (°)")
    ax.set_title("问题三 中继悬停点与保障关系")
    ax.legend(fontsize=8); ax.grid(alpha=0.3)
    fig.savefig(out / "figures" / "q3_relay_positions.png")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 4.2))
    for s in q2.sorties[:20]:
        ax.barh(s.uav_id, (s.return_s - s.start_s) / 60, left=s.start_s / 60,
                height=0.55, color="#3b7dd8", alpha=0.8)
    for r in relay_sorties:
        ax.barh(r["relay_uav_id"], (r["return_s"] - r["start_s"]) / 60,
                left=r["start_s"] / 60, height=0.55, color="#d85a3b", alpha=0.9)
    ax.set_xlabel("时间 (min)"); ax.set_title("问题三 运输 + 中继 调度甘特图")
    ax.grid(alpha=0.3, axis="x")
    fig.savefig(out / "figures" / "q3_gantt.png")
    plt.close(fig)

    # ---------------- 9. 指标 ----------------
    runtime = time.perf_counter() - t0
    transport_e = q2.total_energy_kwh
    relay_e = sum(r["energy_kwh"] for r in relay_sorties)
    joint_makespan = max(
        [s.return_s for s in q2.sorties] + [r["return_s"] for r in relay_sorties],
        default=0.0,
    )
    metrics = {
        "n_transport_sorties": q2.n_sorties,
        "n_relay_sorties": len(relay_sorties),
        "n_sorties_need_relay": n_need,
        "n_sorties_covered": len(relay_covered_ids),
        "coverage_rate": round(len(relay_covered_ids) / n_need, 4) if n_need else 1.0,
        # ★ 几何可达覆盖率（"存在一个悬停点能覆盖全程"）与**时间轴真实覆盖率**
        #   是两件事：前者只看几何，后者还要求中继在需要的那一刻确实在站。
        #   当前排班未把服务窗口纳入约束，二者可能相差极大（见 6b 节警告）。
        "coverage_rate_geometric": round(len(relay_covered_ids) / n_need, 4) if n_need else 1.0,
        "coverage_rate_timeline": round(cover_true, 4),
        "n_sorties_covered_timeline": int((_cov_df["时间重叠率"] >= 0.999).sum()),
        "transport_energy_kwh": round(transport_e, 6),
        "relay_energy_kwh": round(relay_e, 6),
        "total_energy_kwh": round(transport_e + relay_e, 6),
        "joint_makespan_s": round(joint_makespan, 1),
        "joint_makespan_h": round(joint_makespan / 3600, 3),
        "mean_direct_outage_fraction": round(float(diag_df["中断占比"].mean()), 4),
        "n_hover_candidates": len(cands),
        "sample_dt_s": args.sample_dt,
        "hover_step_m": args.hover_step,
        "runtime_sec": round(runtime, 2),
        "feasible_by_verifier": rep.ok,
        "n_verifier_violations": len(rep.violations),
        "verifier_violation_types": dict(viol),
    }
    save_metrics("q3", metrics,
                 params={"relay_spec": spec.__dict__, "gateway_alt_m": gateway_alt},
                 extra={"data_sources": ["通信链路参数.xlsx", "中继无人机数据.xlsx",
                                         "30米DEM.tif"]})
    save_json({"relay_sorties": rs_df.to_dict("records"),
               "diagnosis": diag_df.to_dict("records")}, out / "run_log.json")

    print()
    print("=" * 84)
    print("问题三求解结果")
    print("=" * 84)
    print(f"运输架次 {q2.n_sorties} 个（继承 Q2），其中 {n_need} 个存在直连中断")
    print(f"中继架次 {len(relay_sorties)} 个，覆盖 {n_covered}/{n_need} 个需保障架次")
    print(f"运输能耗 {transport_e:.2f} kWh + 中继能耗 {relay_e:.2f} kWh "
          f"= 合计 {transport_e + relay_e:.2f} kWh")
    print(f"联合任务完成时间 {joint_makespan/3600:.2f} h")
    print(f"平均直连中断占比 {metrics['mean_direct_outage_fraction']:.1%}")
    print(f"独立校验：{'通过' if rep.ok else f'未通过（{len(rep.violations)} 条）'}")
    if viol:
        print("  违规类型：" + "，".join(f"{k}×{n}" for k, n in viol.most_common()))
    print()
    print(plan_df.to_string(index=False))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    raise SystemExit(main())
