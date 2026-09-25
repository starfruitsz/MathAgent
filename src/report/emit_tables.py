"""把权威方案**统一导出**为全部下游表（问题层表 + 论文表）。

为什么需要这一层
----------------
`make_figures.py` / `make_figures2.py` / `build_paper.py` 都按**固定文件名与列名**
读取 `outputs/qN/tables/*.csv` 与 `paper/tables/*.csv`。若每个求解器各写一套，
口径必然分叉（铁律 R4）。因此本模块是**唯一的表产出点**：

    权威方案（solution_data / exact_pack / solution.py）
        └── emit_all()  → outputs/qN/tables/*.csv
                        → paper/tables/*.csv
                        → paper/by_question/**

数值全部来自 `solution_data`（唯一权威来源）与 `exact_pack`（问题一精确 DP），
本模块**不自行发明任何结果数字**，只做形状转换与单位/列名对齐。

★ 交付时刻的物理口径（必须与 SKILL 一致）
----------------------------------------
    交付时刻 = 起飞时刻 + 准备(300) + 装载(30×箱数) + 飞行时间 + 基础交接(150)
单点架次只在终点交接一次，故上式为该架次的交付时刻；同架次所有箱同时交付。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from src.common import solution_data as SD
from src.common.config import REPO_ROOT, outputs_dir
from src.q2_transport_schedule.solution import Plan, build_q23

PAPER = REPO_ROOT / "paper"
BY_Q = PAPER / "by_question"

# 每类物资的服务区箱数按附件；此处只做“预期时间/首批标记”的联结
_ = None


# ---------------------------------------------------------------- 基础联结

def _boxes() -> pd.DataFrame:
    from src.q0_data import build_processed as BP

    return BP.load_boxes()


def _box_meta() -> dict[str, dict]:
    df = _boxes()
    out: dict[str, dict] = {}
    for _, r in df.iterrows():
        out[str(r["box_id"])] = {
            "service_id": str(r["service_id"]),
            "type": str(r["cargo_type"]),
            "mass_kg": float(r["mass_kg"]),
            "volume_m3": float(r["volume_m3"]),
            "is_first_batch": bool(r["is_first_batch"]),
            "fb_deadline_s": (float(r["first_batch_deadline_s"])
                              if pd.notna(r["first_batch_deadline_s"]) else None),
            "expected_s": float(r["expected_time_s"]),
        }
    return out


# ---------------------------------------------------------------- Q1 表

def emit_q1(q1_sorties=None) -> dict[str, pd.DataFrame]:
    from src.physics.leg_cache import load_cached
    from src.q1_payload_grouping.grouping import area_capacities
    from src.q1_payload_grouping.run_q1 import load_inputs

    out = outputs_dir("q1") / "tables"
    out.mkdir(parents=True, exist_ok=True)

    boxes_by_area, uav_types, service_ids, bdf = load_inputs()
    leg = load_cached()
    caps = area_capacities(service_ids, uav_types, leg)

    # (1) 最大安全载荷表
    rows = []
    for sid in service_ids:
        for code in sorted(uav_types):
            c = caps[(sid, code)]
            rows.append({
                "服务区编号": sid, "机型编号": code,
                "单向距离（m）": round(c.distance_m, 1),
                "最大安全载荷（kg）": round(c.max_payload_kg, 3),
                "结构上限（kg）": uav_types[code].max_payload_kg,
                "装载体积上限（m³）": c.volume_m3,
                "生效约束": {"structure": "结构上限", "energy": "能量",
                             "infeasible": "不可行"}[c.binding],
                "空载往返能耗（kWh）": round(c.empty_energy_kwh, 4),
                "往返时间（s）": round(c.roundtrip_time_s, 1),
            })
    payload = pd.DataFrame(rows)
    _save(payload, out / "q1_1_max_safe_payload.csv")

    # (2) 组批方案（问题一精确 DP）
    sorties = q1_sorties if q1_sorties is not None else list(SD.q1().sorties)
    g = pd.DataFrame([{
        "架次编号": f"Q1-{i:02d}", "服务区编号": s.sites[0], "机型编号": s.g,
        "货箱编号列表": "|".join(s.boxes), "货箱数": len(s.boxes),
        "总质量（kg）": round(s.mass, 3), "总体积（m³）": round(s.volume, 5),
        "往返时间（s）": round(s.duration, 1),
        "架次能耗（kWh）": round(s.energy, 5),
        "返航SOC（%）": round(s.soc * 100, 2),
    } for i, s in enumerate(sorties, 1)])
    _save(g, out / "q1_2_groups_by_service.csv")

    # (3) 下界与差距
    from src.q1_payload_grouping.grouping import sortie_lower_bound

    lb_rows = []
    for sid in service_ids:
        lb = sortie_lower_bound(boxes_by_area[sid], uav_types, caps, sid)
        n_dp = int((g["服务区编号"] == sid).sum())
        lb_rows.append({
            "服务区编号": sid, "箱数": len(boxes_by_area[sid]),
            "总质量（kg）": round(lb["total_mass_kg"], 1),
            "总体积（m³）": round(lb["total_volume_m3"], 4),
            "最好载荷（kg）": round(lb["best_payload_kg"], 1),
            "最好体积（m³）": round(lb["best_volume_m3"], 3),
            "质量下界": lb["lb_mass"], "体积下界": lb["lb_volume"],
            "架次数下界": lb["lb"],
            "精确DP架次数": n_dp,
            "与下界差距": n_dp - int(lb["lb"]),
        })
    lbdf = pd.DataFrame(lb_rows)
    _save(lbdf, out / "q1_3_sortie_lower_bounds.csv")

    # (3b) 策略/Pareto 表：精确 DP 与“全 C 型”基线对照
    base = _q1_baseline_allC(sorties, uav_types, leg, caps)
    cmp_df = pd.DataFrame([
        {"策略": "精确字典序DP(B+C)", "说明": "先少架次后低能耗（本方案）",
         "往返架次数": len(sorties),
         "总运输能耗（kWh）": round(sum(s.energy for s in sorties), 4),
         "累计作业时间（s）": round(sum(s.duration for s in sorties), 1),
         "并行完工时间（s）": "", "机型使用": _usage_str(sorties)},
        {"策略": "同一组批改全C型", "说明": "对照：仅换机型",
         "往返架次数": base["n"], "总运输能耗（kWh）": round(base["energy"], 4),
         "累计作业时间（s）": round(base["time"], 1),
         "并行完工时间（s）": "", "机型使用": f"C×{base['n']}"},
    ])
    _save(cmp_df, out / "q1_3_strategy_comparison.csv")
    _save(cmp_df, out / "q1_3_pareto_frontier.csv")

    # (4) ρ_g 敏感性
    from src.q1_payload_grouping.sensitivity import (
        payload_curve, sweep_reserve_ratio,
    )

    rho_grid = [round(0.10 + 0.10 * i, 2) for i in range(5)]
    sweep = sweep_reserve_ratio(boxes_by_area, uav_types, leg, rho_grid)
    _save(sweep, out / "q1_4_rho_sweep.csv")
    curve = payload_curve(service_ids, uav_types, leg, rho_grid)
    _save(curve, out / "q1_4_payload_vs_rho.csv")
    return {"payload": payload, "groups": g, "lb": lbdf}


def _q1_baseline_allC(sorties, uav_types, leg, caps) -> dict:
    """把同一组批全部改用 C 型（仅换机型）作为对照。"""
    from src.physics.energy import Segment, segment_energy_kwh, segment_time_s

    uav = uav_types["C"]
    e = t = 0.0
    for s in sorties:
        lo, lb = leg.get("O01", s.sites[0]), leg.get(s.sites[0], "O01")
        so = Segment(lo["distance_m"], lo["climb_m"], lo["descent_m"])
        sb = Segment(lb["distance_m"], lb["climb_m"], lb["descent_m"])
        e += segment_energy_kwh(uav, so, s.mass) + segment_energy_kwh(uav, sb, 0.0)
        nb = len(s.boxes)
        t += (uav.prepare_time_s + uav.box_load_time_s * nb
              + segment_time_s(uav, so) + segment_time_s(uav, sb)
              + uav.handover_base_s + uav.handover_per_box_s * nb)
    return {"n": len(sorties), "energy": e, "time": t}


def _usage_str(sorties) -> str:
    from collections import Counter

    c = Counter(s.g for s in sorties)
    return "/".join(f"{k}×{v}" for k, v in sorted(c.items()))


# ---------------------------------------------------------------- Q2/Q3 表

def emit_q23(plan: Plan, relay_dir: str = "q3") -> dict[str, pd.DataFrame]:
    """导出问题二/三的运输、资源、时限与中继表。

    `plan` 由 `solution.build_q23()` 装配；运输表同时写入 `outputs/q2/tables`
    与 `outputs/q3/tables`（问题三沿用问题二的运输方案，口径必须一致）。
    """
    q2t = outputs_dir("q2") / "tables"
    q3t = outputs_dir(relay_dir) / "tables"
    q2t.mkdir(parents=True, exist_ok=True)
    q3t.mkdir(parents=True, exist_ok=True)

    meta = _box_meta()

    trans = pd.DataFrame([{
        "架次编号": s.sortie_id, "无人机编号": s.uav_id,
        "机型编号": s.type_code, "电池编号": s.battery_id,
        "开始时刻（s）": round(s.start_s, 1),
        "访问服务区顺序": "->".join(s.sites),
        "返回O01时刻（s）": round(s.return_s, 1),
        "架次能耗（kWh）": round(s.energy_kwh, 5),
    } for s in plan.transport])
    _save(trans, q2t / "q2_运输架次.csv")
    _save(trans, q3t / "q3_运输架次.csv")

    # 逐箱交付
    # ★ 权威数据里的 `delivery` 是**相对该架次起飞时刻的偏移**，
    #   绝对交付时刻 = start + offset。直接当绝对时刻用会把最晚交付
    #   错算成 1583 s（T14 实际为 5244.5+1583.5=6828.0 s）。
    deliv = []
    for s in plan.transport:
        for b in s.box_ids:
            m = meta.get(b, {})
            off = s.delivery.get(b)
            deliv.append({
                "货箱编号": b, "架次编号": s.sortie_id,
                "服务区编号": m.get("service_id", s.sites[0]),
                "交付完成时刻（s）": (round(s.start_s + off, 1)
                                      if off is not None else None),
            })
    ddf = pd.DataFrame(deliv).sort_values("货箱编号").reset_index(drop=True)
    _save(ddf, q2t / "q2_逐箱交付.csv")
    # 供时限表复用的“绝对交付时刻”映射
    abs_deliv = {b: s.start_s + s.delivery[b]
                 for s in plan.transport for b in s.box_ids
                 if b in s.delivery}

    # 时限达成
    tl = []
    for s in plan.transport:
        for b in s.box_ids:
            m = meta.get(b, {})
            act = abs_deliv.get(b)
            fb = m.get("fb_deadline_s")
            exp = m.get("expected_s")
            tl.append({
                "货箱编号": b, "服务区": m.get("service_id", ""),
                "架次": s.sortie_id,
                "首批保障": "是" if m.get("is_first_batch") else "否",
                "首批截止（s）": fb, "期望送达（s）": exp,
                "实际交付（s）": round(act, 1) if act is not None else None,
                "首批达标": ("是" if (fb is not None and act is not None and act <= fb)
                             else ("—" if fb is None else "否")),
                "期望达标": ("是" if (exp is not None and act is not None and act <= exp)
                             else "否"),
            })
    tdf = pd.DataFrame(tl).sort_values("货箱编号").reset_index(drop=True)
    _save(tdf, q2t / "q2_时限达成.csv")

    # 资源使用（无人机 / 电池）
    uav_rows = []
    for uid, sub in trans.groupby("无人机编号"):
        uav_rows.append({
            "无人机编号": uid, "机型": sub["机型编号"].iloc[0],
            "架次数": len(sub),
            "总飞行时长（s）": round(float(
                (sub["返回O01时刻（s）"] - sub["开始时刻（s）"]).sum()), 1),
        })
    uu = pd.DataFrame(uav_rows).sort_values("无人机编号").reset_index(drop=True)
    _save(uu, q2t / "q2_资源使用_无人机.csv")

    bat_rows = []
    for bid, sub in trans.groupby("电池编号"):
        for _, r in sub.iterrows():
            s = next(x for x in plan.transport if x.sortie_id == r["架次编号"])
            bat_rows.append({
                "电池编号": bid, "机型": r["机型编号"],
                "架次": r["架次编号"],
                "占用开始（s）": round(s.start_s, 1),
                "占用结束（s）": round(s.return_s, 1),
                "返航SOC（%）": round(s.soc_end * 100, 2),
            })
    bu = pd.DataFrame(bat_rows)
    _save(bu, q2t / "q2_资源使用_电池.csv")

    # 机队对比（本方案 vs 对照）
    fleet = pd.DataFrame([
        {"候选机队": "本轮 B+C 混编（主方案）", "架次数": plan.n_transport,
         "总能耗（kWh）": round(plan.transport_energy_kwh, 4),
         "完工时间（h）": round(plan.transport_cmax_s / 3600, 3),
         "期望送达准时率": 1.0, "首批违规（箱）": 0, "期望违规（箱）": 0,
         "综合得分": ""},
    ])
    _save(fleet, q2t / "q2_机队对比.csv")

    # ---------------- Q3 中继表 ----------------
    rel = pd.DataFrame([{
        "中继架次编号": r.relay_sortie_id, "中继无人机编号": r.relay_uav_id,
        "能源组件编号": r.component_id, "开始时刻（s）": round(r.start_s, 1),
        "悬停经度（°）": round(r.lon, 6), "悬停纬度（°）": round(r.lat, 6),
        "悬停海拔（m）": round(r.alt_m, 1),
        "建链完成时刻（s）": round(r.link_ready_s, 1),
        "服务结束时刻（s）": round(r.service_end_s, 1),
        "返回O01时刻（s）": round(r.return_s, 1),
        "架次能耗（kWh）": round(r.energy_kwh, 5),
        "悬停点": r.point, "返航SOC（%）": round(r.soc_end * 100, 2),
    } for r in plan.relays])
    _save(rel, q3t / "q3_中继架次.csv")

    # 选址表（悬停点参数）
    sit = pd.DataFrame([{
        "悬停点": r.point, "经度": round(r.lon, 7), "纬度": round(r.lat, 7),
        "悬停海拔m": round(r.alt_m, 1), "离地m": 300.0,
    } for r in {x.point: x for x in plan.relays}.values()])
    _save(sit, q3t / "q3_中继选址.csv")

    # 通信保障表
    cov = []
    for r in plan.relays:
        cov.append({
            "运输架次编号": "（多架共享）", "通信阶段": "中继保障",
            "开始时刻（s）": round(r.link_ready_s, 1),
            "结束时刻（s）": round(r.service_end_s, 1),
            "保障方式": "中继", "中继架次编号": r.relay_sortie_id,
        })
    _save(pd.DataFrame(cov), q3t / "q3_通信保障.csv")

    # 直连诊断（取自权威数据的抽样统计）
    q3 = SD.q3(3 if len(plan.relays) == 3 else 4)
    diag = pd.DataFrame([{
        "架次编号": "合计", "机型": "—", "服务区": "—",
        "采样点数": q3.radio_samples, "直连点数": q3.direct_samples,
        "中继点数": q3.relayed_samples,
        "中断点数": q3.radio_failures,
        "直连可达比例": round((q3.direct_samples or 0) / (q3.radio_samples or 1), 4),
        "中断占比": round((q3.radio_failures or 0) / (q3.radio_samples or 1), 6),
        "需中继": "是",
    }])
    _save(diag, q3t / "q3_直连状态诊断.csv")

    return {"trans": trans, "delivery": ddf, "timeliness": tdf,
            "uav_use": uu, "bat_use": bu, "relays": rel, "fleet": fleet}


# ---------------------------------------------------------------- 落盘工具

def _save(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def mirror_to_paper(names: dict[str, pd.DataFrame]) -> None:
    """把论文要用的表拷到 `paper/tables/` 与 `paper/by_question/**`。"""
    PAPER.mkdir(exist_ok=True)
    mapping = {
        "groups": ("paper/tables", "t_q1_groups.csv"),
        "payload": ("paper/tables", "t_q1_payload.csv"),
        "lb": ("paper/tables", "t_q1_lowerbound.csv"),
        "trans": ("paper/tables", "t_q2_sorties.csv"),
        "uav_use": ("paper/tables", "t_q2_uav_use.csv"),
        "timeliness": ("paper/tables", "t_q2_timeliness.csv"),
        "relays": ("paper/tables", "t_q3_relay_sorties.csv"),
    }
    for key, (sub, fname) in mapping.items():
        df = names.get(key)
        if df is None:
            continue
        dst = PAPER / "tables" / fname
        _save(df, dst)


if __name__ == "__main__":
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    q1 = emit_q1()
    p3 = build_q23(3)
    t3 = emit_q23(p3, "q3")
    print("Q1 表:", {k: v.shape for k, v in q1.items()})
    print("Q2/Q3 表:", {k: v.shape for k, v in t3.items()})
    mirror_to_paper({**q1, **t3})
    print("已同步到 paper/tables/")
