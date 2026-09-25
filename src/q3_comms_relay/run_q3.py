"""问题三入口：通信约束下的运输与中继联合调度。

用法：
    python -m src.q3_comms_relay.run_q3
    python -m src.q3_comms_relay.run_q3 --hover-step 400 --sample-dt 2.0

输出（outputs/q3/）：
    metrics.json / params.json / run_log.json / feasibility.json
    tables/  Q3_中继架次、Q3_通信保障、运输架次（继承 Q2）
    tables/*.csv   直连诊断、中继架次、通信保障、链路裕量
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd


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
    RelayRequest,
    RelaySpec,
    _flight_time,
    evaluate_relay_sortie,
    plan_relay_sorties,
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


DEM = (
    REPO_ROOT
    / "data/raw/D题/数据/镇龙乡地理空间数据/镇龙乡及周边地理数据"
    / "数字高程模型数据（DEM）/镇龙乡及周边30米DEM.tif"
)


def _outage_intervals(targets, sample_dt_s: float) -> tuple[tuple[float, float], ...]:
    """把中断样本合并成**互不相交的中断区间**（相邻样本间隔 ≤1.5×步长视为连续）。

    ★ 这是保障需求的正确口径：一个架次可能断好几次，中间夹着直连可用的时段，
    那些时段**不需要**中继。用包络 `(首, 末)` 会多算出约 39% 的站岗时长。
    """
    ts = sorted(x.t_s for x in targets)
    ivs: list[list[float]] = []
    for t in ts:
        if ivs and t - ivs[-1][1] <= sample_dt_s * 1.5:
            ivs[-1][1] = t
        else:
            ivs.append([t, t])
    return tuple((float(a), float(b)) for a, b in ivs)


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
        # ★★ ADR-031 修复点（之二）：保障需求是**真实中断区间集合**，
        #    不是整条轨迹、也不是"首末中断样本的包络"。
        #    包络会把中间"其实直连可用"的时段也算成需要中继驻留，
        #    实测虚高 39% 的站岗时长（277 min vs 168 min），
        #    既浪费续航又压低可保障的架次数。
        need_ivs = _outage_intervals(targets, args.sample_dt)
        need_env = (need_ivs[0][0], need_ivs[-1][1])
        need_s = sum(b - a for a, b in need_ivs)

        # 本阶段（5）只判"几何上能不能被单个悬停点覆盖"，
        # 真正的挑点与排班放到第 6 节统一做（那里才知道窗口与资源）。
        covering = [
            h for h in cands
            if covers_all(targets, DEFAULT_PARAMS, provider, gateway_pos, h.pos,
                          los_step_m=args.los_step)
        ]
        if not covering:
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
                    score = -len(cov)          # 覆盖得多者优先
                    if best_seg is None or score < best_seg[0]:
                        best_seg = (score, h, cov)
                if best_seg is None:
                    break
                _, h, cov = best_seg
                segs.append({"hover": h,
                             "window": (min(x.t_s for x in cov), max(x.t_s for x in cov))})
                covered_ids = {id(x) for x in cov}
                remaining_pts = [x for x in remaining_pts if id(x) not in covered_ids]

            frac = (len(targets) - len(remaining_pts)) / len(targets) if targets else 0.0
            plan_rows.append({
                "架次编号": sid, "服务区": "->".join(s.stops),
                "中断占比": row["中断占比"],
                "悬停经度": (round(segs[0]["hover"].lon, 6) if segs else None),
                "悬停纬度": (round(segs[0]["hover"].lat, 6) if segs else None),
                "悬停海拔m": (round(segs[0]["hover"].alt_m, 1) if segs else None),
                "离地m": (round(segs[0]["hover"].agl_m, 1) if segs else None),
                "服务窗口起": round(need_env[0], 1),
                "服务窗口止": round(need_env[1], 1),
                "中断区间数": len(need_ivs),
                "需保障时长s": round(need_s, 1),
                "说明": (f"需 {len(segs)} 架中继分段覆盖"
                        + (f"（仍余 {frac:.0%} 未覆盖）" if remaining_pts else "")),
            })
            for k, sg in enumerate(segs, start=1):
                relay_plans.append({
                    "sortie": f"{sid}#{k}", "hover": sg["hover"],
                    "window": sg["window"], "windows": (sg["window"],),
                    "transport": s, "covers_id": sid,
                })
            continue
        plan_rows.append({
            "架次编号": sid, "服务区": "->".join(s.stops),
            "中断占比": row["中断占比"],
            "悬停经度": round(covering[0].lon, 6),
            "悬停纬度": round(covering[0].lat, 6),
            "悬停海拔m": round(covering[0].alt_m, 1),
            "离地m": round(covering[0].agl_m, 1),
            "服务窗口起": round(need_env[0], 1), "服务窗口止": round(need_env[1], 1),
            "中断区间数": len(need_ivs),
            "需保障时长s": round(need_s, 1),
            "说明": "单点可覆盖全部中断样本",
        })
        relay_plans.append({"sortie": sid, "hover": covering[0],
                            "window": need_env, "windows": need_ivs,
                            "transport": s, "covers_id": sid})

    plan_df = pd.DataFrame(plan_rows)
    save_table(plan_df, out / "tables" / "q3_中继选址.csv")
    n_covered = len(relay_plans)
    log.info("单点可覆盖全部中断样本的架次：%d / %d", n_covered, n_need)

    # ---------------- 6. 中继资源调度（2 架 + 6 组能源组件） ----------------
    # ★★ ADR-031 修复：排班把"服务窗口"当作**硬约束** ——
    #    中继必须在窗口起点_之前_完成建链（strict=True），来不及就如实记为不可行，
    #    不再像旧实现那样把服务区间静默截短（截到 0 长度也算"已保障"）。
    # ★ A 口径：允许**同一悬停点被多架运输机共享**（题目附录 3 只限制
    #    "每架运输无人机任一时刻只能由 G01 或一架中继保障"，
    #    未限制一架中继同时保障几架运输机）。
    relay_fleet = ["R01", "R02"]
    n_packs = 6

    # 每个保障需求：用"能覆盖其全部中断样本"的候选点（按能耗升序）
    requests = []
    for rp in relay_plans:
        sid = rp["covers_id"]
        samples = traj[sid]
        targets = outage_samples(
            samples, DEFAULT_PARAMS, provider, gateway_pos, los_step_m=args.los_step
        )
        win_ivs = rp["windows"]
        # 几何上能覆盖全部中断样本的点（分段覆盖时各段窗口不同）
        covering = [
            h for h in cands
            if covers_all(targets, DEFAULT_PARAMS, provider, gateway_pos, h.pos,
                          los_step_m=args.los_step)
        ] if targets else []
        if rp["hover"] not in covering:
            covering = [rp["hover"], *covering]
        scored = []
        for h in covering:
            t_fly = _flight_time(spec, h, provider, o01, args.los_step)
            ev = evaluate_relay_sortie(
                spec, h, provider, o01, leg_cache, win_ivs,
                max(0.0, win_ivs[0][0] - spec.prepare_time_s - t_fly
                    - spec.link_setup_time_s),
                sample_step_m=args.los_step,
            )
            if ev is not None:
                scored.append((ev.energy_kwh, h))
        scored.sort(key=lambda x: x[0])
        requests.append(RelayRequest(
            sortie_id=sid, windows=win_ivs,
            candidates=tuple(h for _, h in scored) or (rp["hover"],),
        ))

    planned, relay_records = plan_relay_sorties(
        spec, requests, provider, o01, leg_cache,
        relay_uav_ids=relay_fleet, n_energy_packs=n_packs,
        pack_t_full_s=1800.0, sample_step_m=args.los_step, share=True,
    )
    relay_sorties = [
        {"sortie_id": p.sortie_id, "relay_uav_id": p.relay_uav_id,
         "pack_id": p.energy_pack_id, "hover": p.hover, "start_s": p.start_s,
         "link_ready_s": p.link_ready_s, "service_end_s": p.service_end_s,
         "return_s": p.return_s, "energy_kwh": p.evaluation.energy_kwh,
         "soc_end": p.evaluation.soc_end, "covers": p.covers}
        for p in planned
    ]
    infeasible_ids = sorted(r["sortie_id"] for r in relay_records
                            if not r["feasible"])
    log.info("中继排班：%d 个中继架次保障 %d 个运输架次；不可行 %d 个 %s",
             len(relay_sorties), sum(len(r["covers"]) for r in relay_sorties),
             len(infeasible_ids), infeasible_ids)

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

    # 通信保障表（每个 中继架次×运输架次 一行；A 口径下一架中继可保障多架运输机）
    comm_rows = []
    for r in relay_sorties:
        for cid in r["covers"]:
            comm_rows.append({
                "运输架次编号": cid,
                "通信阶段": "全程",
                "开始时刻（s）": round(r["link_ready_s"], 1),
                "结束时刻（s）": round(r["service_end_s"], 1),
                "保障方式": "中继",
                "中继架次编号": r["sortie_id"],
            })
    save_table(pd.DataFrame(comm_rows), out / "tables" / "q3_通信保障.csv")

    # ---------------- 6b. ★ 时间轴复核：中继"在站时段"是否覆盖"所需保障窗口" ----------------
    # ADR-031 修复后：排班已把窗口作为硬约束，因此这里的重叠率应当接近 1.0。
    # 本表仍是**独立于排班的复核**（从输出表反算），用来证明"修好了"而不是"声称修好了"；
    # 覆盖不到 100% 的架次会逐条列出缺口，绝不静默。
    _cov_rows = []
    for _p in plan_rows:
        _sid = _p["架次编号"]
        _pairs = [r for r in relay_sorties if _sid in r["covers"]]
        _need_a = min((float(r["window"][0]) for r in relay_plans
                       if r["covers_id"] == _sid), default=0.0)
        _need_b = max((float(r["window"][1]) for r in relay_plans
                       if r["covers_id"] == _sid), default=0.0)
        _need = max(_need_b - _need_a, 1e-9)
        # 中继在站时段取并集
        ivs = sorted((float(r["link_ready_s"]), float(r["service_end_s"]))
                     for r in _pairs)
        merged: list[list[float]] = []
        for a, b in ivs:
            if merged and a <= merged[-1][1] + 1e-9:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        _ov = sum(max(0.0, min(_need_b, b) - max(_need_a, a)) for a, b in merged)
        _cov_rows.append({
            "架次编号": _sid,
            "需要起": round(_need_a, 1), "需要止": round(_need_b, 1),
            "在站起": (round(merged[0][0], 1) if merged else None),
            "在站止": (round(merged[-1][1], 1) if merged else None),
            "时间重叠率": round(_ov / _need, 4),
        })
    _cov_df = pd.DataFrame(_cov_rows)
    save_table(_cov_df, out / "tables" / "q3_中继时间覆盖复核.csv")
    _ok_mask = _cov_df["时间重叠率"] >= 0.999
    cover_true = float(_ok_mask.mean()) if len(_cov_df) else 0.0
    n_covered_timeline = int(_ok_mask.sum())
    log.info("★ 时间轴覆盖复核：%d/%d 个需保障架次被中继完整覆盖（真实覆盖率 %.1f%%）",
             n_covered_timeline, len(_cov_df), 100.0 * cover_true)
    if n_covered_timeline < len(_cov_df):
        _bad = _cov_df[~_ok_mask]
        log.warning("★ 未获时间轴保障的架次 %d 个（中继资源不足，如实报告）：\n%s",
                    len(_bad), _bad.to_string(index=False))
    # 中继资源缺口：覆盖全部需保障架次所需的最少中继台数 vs 现有库存
    relay_shortage = max(0, len(relay_sorties) - len(relay_fleet))

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
    # ★★ ADR-031 修复点：**每个架次都如实上报它的直连中断窗口**。
    #   旧实现只对"未被任何中继计划覆盖"的架次赋值 `outage_windows`，
    #   于是凡进了 `relay_plans` 的架次其 `outage_windows` **恒为空**
    #   ⇒ 校验器 `_check_comms` 直接 continue，**该架次的通信检查从未执行**
    #   ⇒ 中继晚到（甚至运输机返航后才到场）也报 0 违规。
    #   现在不再按"有没有中继"来决定是否上报，而是**一律上报真实中断窗口**，
    #   由独立校验器在时间轴上判定"是否真的被中继覆盖"。
    outage_by_sortie: dict[str, tuple[tuple[float, float], ...]] = {}
    for _, _r in diag_df.iterrows():
        _sid = _r["架次编号"]
        if not bool(_r["需中继"]):
            outage_by_sortie[_sid] = ()
            continue
        _tgt = outage_samples(
            traj[_sid], DEFAULT_PARAMS, provider, gateway_pos,
            los_step_m=args.los_step,
        )
        outage_by_sortie[_sid] = _outage_intervals(_tgt, args.sample_dt) if _tgt else ()

    for s in q2.sorties:
        nodes = [CENTER_ID, *s.stops, CENTER_ID]
        legs = []
        for a, b in zip(nodes, nodes[1:]):
            g = leg_cache.get(a, b)
            legs.append(Leg(g["distance_m"], g["climb_m"], g["descent_m"]))
        v_sorties.append(Sortie(
            sortie_id=s.sortie_id, uav_id=s.uav_id, type_code=s.type_code,
            battery_id=s.battery_id, start_s=s.start_s, service_sequence=s.stops,
            box_ids=tuple(x for st in s.stops for x in s.boxes_by_stop.get(st, ())),
            legs=tuple(legs),
            boxes_per_stop={st: len(v) for st, v in s.boxes_by_stop.items()},
            reported_delivery_times=s.delivery_times,
            outage_windows=outage_by_sortie.get(s.sortie_id, ()),
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
    # 物理/资源/通信类违规说明方案不可交付，必须中止。
    # ★ ADR-031 补充：`COMMS_RELAY_INSUFFICIENT`（中继站岗能力不足导致的
    #   架次未获保障）属**软违规**，不中止产出 —— 它是应当如实报告的
    #   "题目资源与需求的矛盾"，不是排班缺陷。反之若已有正长度中继窗口
    #   却盖不住中断区间，仍是硬违规 `COMMS_UNSUPPORTED`，闸门会拦下。
    # 分类依据见 `verify.feasibility.HARD_VIOLATION_TYPES`。
    try:
        rep.assert_deliverable()
    except RuntimeError as exc:
        log.error("★ 硬约束闸门未通过：%s", exc)
        raise
    log.info("硬约束闸门：通过（物理/资源/通信缺陷类 0 条；时限类与中继资源缺口类 "
             "共 %d 条已按论文口径如实上报）", len(rep.soft()))

    # ---------------- 8. 图 ----------------
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
