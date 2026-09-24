# -*- coding: utf-8 -*-
"""从 tables/*.csv 生成论文用的 LaTeX 三线表片段。

每张表单独写一个 .tex 文件，供各章在引用处 \\input，保证浮动体落在正确章节。
所有数值直接来自 CSV，不手工誊抄，避免抄错。
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
TAB = ROOT / "tables"
TEX = ROOT / "texfile"

BIND = {"结构上限": "结构", "能量": "能量", "体积": "体积"}
TABLES: dict[str, str] = {}


def tl(fn: str, caption: str, label: str, colspec: str, header: list[str],
       rows: list[list[str]], size: str = "-5", note: str | None = None) -> None:
    body = "\n".join(" & ".join(r) + r" \\" for r in rows)
    s = [r"\begin{table}[htbp]", r"\caption{%s}" % caption, r"\label{%s}" % label,
         r"\centering", r"\zihao{%s}" % size,
         r"\setlength{\tabcolsep}{4pt}", r"\begin{tabular}{%s}" % colspec,
         r"\toprule", " & ".join(header) + r" \\", r"\midrule", body,
         r"\bottomrule", r"\end{tabular}"]
    if note:
        s.append(r"\\[2pt] \footnotesize " + note)
    s.append(r"\end{table}")
    TABLES[fn] = "\n".join(s)


_ESC = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
        "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}"}


def esc(t: str) -> str:
    """纯文本单元格转义。

    ★ 尤其注意 `%`：LaTeX 中它是注释符，会把该行末尾的 `\\\\` 一起注释掉，
      导致下一行并进同一行、报 "Extra alignment tab"（实测踩过）。
      `_` 是数学下标、`&` 是列分隔符，同样必须转义。
      `~` 故意保留（当作不换行空格），`<`/`>` 在 xelatex 文本模式下可正常显示。
    """
    return "".join(_ESC.get(ch, ch) for ch in str(t))


def main() -> None:
    # ---------------------------------------------------------- 分类物资
    d = pd.read_csv(TAB / "t_box_by_type.csv").sort_values("箱数", ascending=False)
    rows = [[esc(r["cargo_type"]), str(int(r["箱数"])), f"{r['总质量']:.0f}",
             f"{r['总体积']:.3f}", f"{r['总质量']/r['箱数']:.1f}",
             f"{r['总体积']/r['箱数']:.3f}"] for _, r in d.iterrows()]
    t = d[["箱数", "总质量", "总体积"]].sum()
    rows.append([r"\textbf{合计}", rf"\textbf{{{int(t['箱数'])}}}",
                 rf"\textbf{{{t['总质量']:.0f}}}", rf"\textbf{{{t['总体积']:.3f}}}", "—", "—"])
    tl("tab_box_type.tex", "分类物资总量统计", "tab:box_type", "lccccc",
       ["物资类型", "箱数", "总质量/kg", "总体积/m$^3$",
        "单箱质量/kg", "单箱体积/m$^3$"], rows)

    # ---------------------------------------------------------- 机型参数
    u = pd.read_csv(TAB / "t_uav_params.csv").set_index("code")
    fields = [("max_payload_kg", "最大载货质量 $Q_{g}$ / kg", "{:.0f}"),
              ("volume_m3", "可用装载体积 $V_{g}$ / m$^3$", "{:.3f}"),
              ("cruise_speed_ms", r"巡航速度 $v_{g}^{c}$ / (m$\cdot$s$^{-1}$)", "{:.0f}"),
              ("range_empty_m", "空载标准航程 $L_{g0}$ / km", "{:.0f}"),
              ("range_full_m", "满载标准航程 $L_{gF}$ / km", "{:.0f}"),
              ("energy_kwh", "电池可用能量 $E_{g}^{use}$ / kWh", "{:.1f}"),
              ("climb_speed_ms", r"爬升速度 $v_{g}^{\uparrow}$ / (m$\cdot$s$^{-1}$)", "{:.1f}"),
              ("descent_speed_ms", r"下降速度 $v_{g}^{\downarrow}$ / (m$\cdot$s$^{-1}$)", "{:.1f}"),
              ("handover_base_s", "基础交接时间 / s", "{:.0f}"),
              ("handover_per_box_s", "每箱增加交接 / s", "{:.0f}")]
    rows = []
    for key, label, fmt in fields:
        vals = [fmt.format(u.loc[c, key] / 1000 if "航程" in label else u.loc[c, key])
                for c in "ABC"]
        rows.append([label] + vals)
    rows.append([r"返航安全余量 $\rho_{g}$"] + [f"{u.loc[c,'reserve_ratio']*100:.0f}\\%"
                                                for c in "ABC"])
    rows.append(["共享电池组数 / 组", "6", "4", "4"])
    rows.append([r"等效完全充电时间 $T_{full}$ / s", "1800", "2400", "3000"])
    tl("tab_uav_params.tex", "三种运输机型主要参数", "tab:uav_params", "lccc",
       ["参数", "A 型", "B 型", "C 型"], rows)

    # ---------------------------------------------------------- 链路门限
    l = pd.read_csv(TAB / "t_link_thresholds.csv")
    rows = [[esc(r["链路"]), f"{r['双向门限(dB)']:.0f}", f"{r['无遮挡可达(km)']:.3f}",
             f"{r['含遮挡可达(km)']:.3f}"] for _, r in l.iterrows()]
    tl("tab_link_thresholds.tex", "三条链路的双向门限与可达距离", "tab:link_thresholds",
       "lccc", ["链路", "双向门限 / dB", "无遮挡可达 / km", "含遮挡可达 / km"], rows,
       note="注：含遮挡一列按叠加 10\\,dB 地形遮挡附加损耗计算。")

    # ---------------------------------------------------------- 最大安全载荷
    p = pd.read_csv(TAB / "t_q1_payload.csv")
    pq = p.pivot(index="服务区编号", columns="机型编号", values="最大安全载荷（kg）")
    pb = p.pivot(index="服务区编号", columns="机型编号", values="生效约束")
    pd_ = p.pivot(index="服务区编号", columns="机型编号", values="单向距离（m）")
    rows = [[s, f"{pd_.loc[s,'A']/1000:.2f}"]
            + [f"{pq.loc[s,c]:.1f}（{BIND.get(pb.loc[s,c],'')}）" for c in "ABC"]
            for s in sorted(pq.index)]
    tl("tab_q1_payload.tex",
       r"3 机型 $\times$ 15 服务区最大安全载荷与生效约束", "tab:q1_payload", "lcccc",
       ["服务区", "单向距离 / km", "A 型载荷 / kg", "B 型载荷 / kg", "C 型载荷 / kg"],
       rows, note="注：括号内为该组合实际生效的约束类型。")

    # ---------------------------------------------------------- 策略对比
    st = pd.read_csv(TAB / "t_q1_strategy.csv")
    rows = [[esc(r["策略"]), esc(r["说明"][:16]), str(int(r["往返架次数"])),
             f"{r['总运输能耗（kWh）']:.2f}", f"{r['累计作业时间（s）']/3600:.2f}",
             f"{r['并行完工时间（s）']/3600:.2f}"] for _, r in st.iterrows()]
    tl("tab_q1_strategy.tex", "各组批策略的多目标对比", "tab:q1_strategy", "llcccc",
       ["策略", "说明", "架次数", "总能耗 / kWh", "累计作业 / h", "并行完工 / h"], rows)

    # ---------------------------------------------------------- rho 扫描
    rs = pd.read_csv(TAB / "t_q1_rho_sweep.csv")
    keep = {0, 4, 8, 9, 10, 11, 14, 15}
    rows = []
    for i, r in rs.iterrows():
        if i not in keep:
            continue
        rows.append([f"{r['rho']:.3f}", str(int(r["n_sorties"])),
                     f"{r['total_energy_kwh']:.2f}",
                     f"{r['serial_total_time_s']/3600:.2f}" if r["n_sorties"] else "—",
                     "是" if r["feasible"] else "否", str(int(r["n_infeasible_areas"]))])
    tl("tab_q1_rho_sweep.tex", r"返航安全余量 $\rho_{g}$ 扫描结果（节选）",
       "tab:q1_rho_sweep", "cccccc",
       [r"$\rho_{g}$", "架次数", "总能耗 / kWh", "累计作业 / h", "有可行解",
        "不可行服务区数"], rows)

    # ---------------------------------------------------------- 敏感性
    se = pd.read_csv(TAB / "t_sensitivity.csv")
    # 「本文取值」以 q3 实际运行的参数为准（CSV 中记录的是敏感性研究期间的中间值）
    q3p = json.loads((ROOT / "data" / "q3_params.json").read_text(encoding="utf-8"))
    q3p = q3p.get("params", q3p)
    actual = {
        "通信采样步长": f"{q3p.get('sample_dt_s', 2):g} s",
        "悬停网格步长": f"{q3p.get('hover_step_m', 400):g} m",
    }
    rows = [[esc(r["敏感性维度"]), esc(r["取值范围"]),
             esc(actual.get(r["敏感性维度"], r["本文取值"])), esc(r["主要影响"])]
            for _, r in se.iterrows()]
    tl("tab_sensitivity.tex", "敏感性分析汇总", "tab:sensitivity", "llll",
       ["敏感性维度", "取值范围", "本文取值", "主要影响"], rows, size="-5")

    for fn, blk in TABLES.items():
        (TEX / fn).write_text(blk + "\n", encoding="utf-8")
        print(f"  ✓ {fn}")
    print(f"共 {len(TABLES)} 张表")


if __name__ == "__main__":
    main()
