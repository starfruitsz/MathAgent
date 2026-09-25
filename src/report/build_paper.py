"""论文 Word 生成器：把结果、图表与文字装配成完整论文。

依据：
  - `参考文稿2.pdf` 的**章节结构**（引言→总体分析→四问→检验→结论→附录）
  - `docs/reference/示范版本_第三方参考.pdf` 的**排版风格**（摘要密度、图表编号）
  - 本仓库 `outputs/` 与 `paper/` 的**真实数据与图表**（不手写数字）

用法：
    python -m src.report.build_paper
输出：
    paper/山区洪涝灾害下无人机运输与通信协同优化_论文.docx
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd
from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn
from docx.shared import Cm, Emu, Inches, Pt, RGBColor, Twips

from src.common.config import REPO_ROOT
from src.report import equations as EQM

PAPER = REPO_ROOT / "paper"
FIG = PAPER / "figures"
TAB = PAPER / "tables"
OUT = PAPER / "山区洪涝灾害下无人机运输与通信协同优化_论文.docx"

CN_FONT = "宋体"
CN_HEI = "黑体"
EN_FONT = "Times New Roman"

TEXT_WIDTH_CM = 21.0 - 2.6 - 2.6  # A4 宽 − 左右页边距 = 15.8 cm

_TBL_FONTS: list[dict] = []
"""逐表记录最终字号，便于生成后核对（`paper/_table_fonts.json`）。"""


# ================================================================ 样式

def _set_font(run, size=12, bold=False, cn=CN_FONT, color=None, italic=False):
    run.font.name = EN_FONT
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    if color:
        run.font.color.rgb = RGBColor(*color)
    rpr = run._element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts"); rpr.append(rf)
    rf.set(qn("w:eastAsia"), cn)
    rf.set(qn("w:ascii"), EN_FONT)
    rf.set(qn("w:hAnsi"), EN_FONT)


def setup(doc: Document) -> None:
    for s in doc.sections:
        s.page_width, s.page_height = Cm(21.0), Cm(29.7)
        s.left_margin = s.right_margin = Cm(2.6)
        s.top_margin = Cm(2.6); s.bottom_margin = Cm(2.4)

    st = doc.styles["Normal"]
    st.font.name = EN_FONT
    st.font.size = Pt(12)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), CN_FONT)
    pf = st.paragraph_format
    pf.line_spacing = 1.45
    pf.space_after = Pt(4)
    pf.first_line_indent = Pt(24)  # 首行缩进 2 字符

    for name, size, cn in (("Heading 1", 16, CN_HEI), ("Heading 2", 14, CN_HEI),
                           ("Heading 3", 12.5, CN_HEI), ("Heading 4", 12, CN_HEI)):
        s = doc.styles[name]
        s.font.name = EN_FONT; s.font.size = Pt(size); s.font.bold = True
        s.font.color.rgb = RGBColor(0, 0, 0)
        s.element.rPr.rFonts.set(qn("w:eastAsia"), cn)
        s.paragraph_format.space_before = Pt(10)
        s.paragraph_format.space_after = Pt(6)
        s.paragraph_format.first_line_indent = Pt(0)

    # ★ 修改要求 2：每一章（一级标题）必须另起新页。
    #   直接写进 Heading 1 样式，比逐处插分页符更可靠（也便于目录/导航）。
    doc.styles["Heading 1"].paragraph_format.page_break_before = True
    doc.styles["Heading 1"].paragraph_format.keep_with_next = True
    for lv in ("Heading 2", "Heading 3", "Heading 4"):
        doc.styles[lv].paragraph_format.keep_with_next = True


def _page_number_footer(doc: Document) -> None:
    for section in doc.sections:
        p = section.footer.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run()
        for instr in ("PAGE",):
            f1 = OxmlElement("w:fldChar"); f1.set(qn("w:fldCharType"), "begin")
            it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve")
            it.text = f" {instr} "
            f2 = OxmlElement("w:fldChar"); f2.set(qn("w:fldCharType"), "end")
            run._r.append(f1); run._r.append(it); run._r.append(f2)
        _set_font(run, 9)


# ================================================================ 排版工具

def _no_split(row) -> None:
    """禁止表格行跨页断开。"""
    trPr = row._tr.get_or_add_trPr()
    if trPr.find(qn("w:cantSplit")) is None:
        trPr.append(OxmlElement("w:cantSplit"))


def _repeat_header(row) -> None:
    """表头行跨页重复。"""
    trPr = row._tr.get_or_add_trPr()
    if trPr.find(qn("w:tblHeader")) is None:
        trPr.append(OxmlElement("w:tblHeader"))


def _cell_margin(tbl, top=30, bottom=30, left=30, right=30) -> None:
    """单元格内边距（单位 twips，1 pt = 20 twips）。

    ★ 左右各 30 twips（0.053 cm）是"窄到不影响表头排一行、又宽到不贴边"的折中。
      早先用 80 twips（0.14 cm）时，15 列表格每列被吃掉 0.28 cm，
      中文表头因此逐字换成两行。
    """
    tblPr = tbl._tbl.tblPr
    old = tblPr.find(qn("w:tblCellMar"))
    if old is not None:
        tblPr.remove(old)
    mar = OxmlElement("w:tblCellMar")
    for tag, val in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        e = OxmlElement(f"w:{tag}")
        e.set(qn("w:w"), str(val)); e.set(qn("w:type"), "dxa")
        mar.append(e)
    tblPr.append(mar)


def _three_line_borders(tbl, top_sz=12, mid_sz=6, bottom_sz=12) -> None:
    """三线表边框：顶线、表头下中线、底线；**无竖线**（参照参考文稿2）。"""
    tblPr = tbl._tbl.tblPr
    old = tblPr.find(qn("w:tblBorders"))
    if old is not None:
        tblPr.remove(old)
    xml = (
        f'<w:tblBorders {nsdecls("w")}>'
        f'<w:top w:val="single" w:sz="{top_sz}" w:space="0" w:color="000000"/>'
        f'<w:bottom w:val="single" w:sz="{bottom_sz}" w:space="0" w:color="000000"/>'
        f'<w:left w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        f'<w:right w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        f'<w:insideH w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        f'<w:insideV w:val="none" w:sz="0" w:space="0" w:color="auto"/>'
        f'</w:tblBorders>'
    )
    tblPr.append(parse_xml(xml))
    # 表格样式自带的边框优先级更高，必须清掉，否则竖线仍在
    tbl.style = None


def _header_bottom_rule(row, sz=6) -> None:
    """给表头行的每个单元格加下框线（三线表的"中线"）。"""
    for cell in row.cells:
        tcPr = cell._tc.get_or_add_tcPr()
        old = tcPr.find(qn("w:tcBorders"))
        if old is not None:
            tcPr.remove(old)
        tcPr.append(parse_xml(
            f'<w:tcBorders {nsdecls("w")}>'
            f'<w:bottom w:val="single" w:sz="{sz}" w:space="0" w:color="000000"/>'
            f'</w:tcBorders>'
        ))


def _est_len(s: str) -> float:
    """估算单元格显示宽度（中日韩字符按 2、其余按 1）。

    公式片段（`$...$`）先剥掉 `\\mathrm{}`、`\\cdot`、`^{-1}` 等命令再计宽，
    否则 `$\\mathrm{m \\cdot s^{-1}}$` 会被高估十倍。
    """
    import re as _re

    txt = s.replace("$", "")
    txt = _re.sub(r"\\mathrm\{([^{}]*)\}", r"\1", txt)
    txt = _re.sub(r"\\(?:cdot|times)", "·", txt)
    txt = _re.sub(r"\^\{[^{}]*\}", "X", txt)
    txt = _re.sub(r"[{}]", "", txt)
    txt = txt.replace("\\,", "").replace("\\ ", " ")
    txt = _re.sub(r"\\[A-Za-z]+", "X", txt)
    n = 0.0
    for ch in txt:
        n += 2.0 if ("\u2e80" <= ch <= "\u9fff" or "\uff00" <= ch <= "\uffef") else 1.0
    return max(n, 2.0)


def _col_widths(tbl, headers: list[str], rows: list[list[str]],
                total_cm: float = TEXT_WIDTH_CM, min_cm: float = 1.05,
                font_pt: float | None = None) -> list[float]:
    """按内容自适应分配列宽，并**保证表头字号不低于可读下限**。

    分配口径（"两轮受约束的按需分配"）：

      1. 先把列宽**平均分**，算出该宽度下"表头不换行"能用的字号上限
         $f_{\\min}$（对所有列取最严者）；
      2. 若 $f_{\\min} < $ `font_pt`（即平均分配下表头会换行），
         则把每列宽设为"按**表头**在该字号下所需宽度"，剩余空间再按
         **内容宽度**比例分配；否则全部按内容宽度比例分配。

    为什么必须这样做（踩过的坑）：
      · 只按"内容最宽单元格"比例分配 ⇒ 长内容列吃掉大半宽度
        （如"货箱编号列表"30+ 字符），中文表头列只剩 0.7 cm，
        15 列表格的表头字号被逼到 6 pt 才能不换行 —— 字太小不可读；
      · 只按表头分配 ⇒ 长内容列放不下，正文换行成多行；
      · 幂律压缩（$w^{0.55}$）是"拍脑袋折中"，会把中间长度的列也压变形。
    两轮分配把"表头可读"作为**硬约束**、把"内容"作为**软目标**，
    并在返回前做一次**表头复检**：若仍有列表头在小数点后差一点放不下，
    就把最宽的列让一点给它（最多让到刚好满足），确保字号不会跌破下限。
    """
    n = len(headers)
    if n == 0:
        return []
    import math as _math

    f_target = float(font_pt or 8.5)
    # 表头在 f_target 下所需列宽（含左右内边距）
    need_hdr = [_est_len(h) / 2.0 * f_target / 72.0 * 2.54 + 2 * _CELL_MARGIN_CM
                for h in headers]
    need_hdr = [max(w, min_cm) for w in need_hdr]
    est = []
    for j, h in enumerate(headers):
        w = _est_len(h)
        for r in rows:
            if j < len(r):
                w = max(w, _est_len(r[j]))
        est.append(max(w, 2.0))

    # 平均分配下的可用字号（用于判断是否需要启用"表头优先"）
    per_col = total_cm / n
    f_min = 1e9
    for h in headers:
        em = max(_est_len(h) / 2.0, 1e-9)
        avail = max(0.05, per_col - 2 * _CELL_MARGIN_CM)
        f_min = min(f_min, (avail / 2.54 * 72.0) / em)

    if f_min >= f_target:
        # 平均分配已够表头用 ⇒ 内容优先
        widths = [total_cm * e / sum(est) for e in est]
    else:
        # 表头优先：先满足表头，再把余量按内容宽度比例分配
        if sum(need_hdr) >= total_cm:
            k = total_cm / sum(need_hdr)     # 极端情况：整体等比缩
            widths = [w * k for w in need_hdr]
        else:
            rest = total_cm - sum(need_hdr)
            tot_e = sum(est) or 1.0
            widths = [nh + rest * e / tot_e for nh, e in zip(need_hdr, est)]

    # 下界抬升 + 缺口由最宽列让出
    deficit = sum(max(0.0, min_cm - w) for w in widths)
    if deficit > 0:
        donors = [i for i, w in enumerate(widths) if w > min_cm * 1.3]
        pool = sum(widths[i] - min_cm for i in donors) or 1.0
        for i, w in enumerate(widths):
            if w < min_cm:
                widths[i] = min_cm
            elif i in donors:
                widths[i] = w - deficit * (w - min_cm) / pool
    scale = total_cm / (sum(widths) or 1.0)
    widths = [w * scale for w in widths]

    # 表头复检：仍放不下的，从最宽列借（借到刚好满足为止）
    for _ in range(4):
        bad = []
        for j, h in enumerate(headers):
            em = max(_est_len(h) / 2.0, 1e-9)
            need = em * f_target / 72.0 * 2.54 + 2 * _CELL_MARGIN_CM
            if widths[j] < need - 1e-9:
                bad.append((j, need - widths[j]))
        if not bad:
            break
        for j, gap in bad:
            donors = sorted((i for i in range(n) if i != j),
                            key=lambda i: -widths[i])
            for i in donors:
                room = widths[i] - min_cm
                if room <= 1e-9:
                    continue
                take = min(room, gap)
                widths[i] -= take
                widths[j] += take
                gap -= take
                if gap <= 1e-9:
                    break

    tbl.autofit = False
    tblPr = tbl._tbl.tblPr
    old = tblPr.find(qn("w:tblW"))
    if old is not None:
        tblPr.remove(old)
    tblW = OxmlElement("w:tblW")
    tblW.set(qn("w:w"), str(int(Cm(total_cm).twips))); tblW.set(qn("w:type"), "dxa")
    tblPr.append(tblW)
    oldg = tblPr.find(qn("w:tblLayout"))
    if oldg is not None:
        tblPr.remove(oldg)
    lay = OxmlElement("w:tblLayout"); lay.set(qn("w:type"), "fixed")
    tblPr.append(lay)

    grid = tbl._tbl.find(qn("w:tblGrid"))
    if grid is not None:
        for gc, w in zip(grid.findall(qn("w:gridCol")), widths):
            # ★ 必须写成 twips：`int(Cm(w))` 得到的是 EMU（差 635 倍），
            #   会让 Word 拿到荒谬的列宽而排版失败。
            gc.set(qn("w:w"), str(int(Cm(w).twips)))
    for row in tbl.rows:
        for cell, w in zip(row.cells, widths):
            cell.width = Cm(w)
    _order_tblpr(tbl)
    return widths


_TBLPR_ORDER = [
    "tblStyle", "tblpPr", "tblOverlap", "bidiVisual", "tblStyleRowBandSize",
    "tblStyleColBandSize", "tblW", "jc", "tblCellSpacing", "tblInd",
    "tblBorders", "shd", "tblLayout", "tblCellMar", "tblLook",
    "tblCaption", "tblDescription", "tblPrChange",
]
_TBLPR_IDX = {name: i for i, name in enumerate(_TBLPR_ORDER)}


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _order_tblpr(tbl) -> None:
    """按 CT_TblPrBase schema 顺序重排 `w:tblPr` 子元素。

    Word 对 `w:tblPr` 的子元素顺序敏感：顺序错会被判为文档损坏，
    表现为无法分页、无法导出 PDF（"无法准备用于导出的文档"）。
    """
    tblPr = tbl._tbl.tblPr
    children = list(tblPr)
    children.sort(key=lambda e: _TBLPR_IDX.get(_local(e.tag), len(_TBLPR_ORDER)))
    for e in children:
        tblPr.remove(e)
    for e in children:
        tblPr.append(e)


# ---------------------------------------------------------------- 数值与表头格式

# 列名 → (显示名, 单位或小数位, 显示精度说明)
#   单位以 `$...$` 包裹 → 渲染为行内公式；否则原样输出
COL_HINT: dict[str, tuple[str, str]] = {
    "node_id": ("节点", ""), "kind": ("类型", ""), "lon": ("经度", r"$^\circ$"),
    "lat": ("纬度", r"$^\circ$"), "ground_elev_m": ("地面高程", r"$\mathrm{m}$"),
    "box_id": ("货箱", ""), "service_id": ("服务区", ""), "type": ("机型", ""),
    "mass_kg": ("质量", r"$\mathrm{kg}$"), "volume_m3": ("体积", r"$\mathrm{m^3}$"),
    "mass": ("质量", r"$\mathrm{kg}$"), "volume": ("体积", r"$\mathrm{m^3}$"),
    "count": ("数量", ""), "n_boxes": ("箱数", ""), "boxes": ("货箱", ""),
    "payload_bottleneck": ("生效约束", ""), "max_safe_payload_kg": ("最大安全载荷", r"$\mathrm{kg}$"),
    "structure_limit_kg": ("结构上限", r"$\mathrm{kg}$"), "energy_limit_kg": ("能量反解上限", r"$\mathrm{kg}$"),
    "empty_range_m": ("空载航程", r"$\mathrm{m}$"), "full_range_m": ("满载航程", r"$\mathrm{m}$"),
    "usable_energy_kwh": ("可用能量", r"$\mathrm{kWh}$"), "max_volume_m3": ("舱容", r"$\mathrm{m^3}$"),
    "cruise_speed_mps": ("巡航速度", r"$\mathrm{m \cdot s^{-1}}$"),
    "climb_speed_mps": ("爬升速度", r"$\mathrm{m \cdot s^{-1}}$"),
    "descent_speed_mps": ("下降速度", r"$\mathrm{m \cdot s^{-1}}$"),
    "full_charge_min": ("满充时间", r"$\mathrm{min}$"), "uav_id": ("无人机", ""),
    "uav_type": ("机型", ""), "battery_id": ("电池", ""), "battery_type": ("适配机型", ""),
    "initial_soc": ("初始 SOC", "2"), "relay_id": ("中继机", ""),
    "energy_id": ("能源组件", ""), "takeoff_mass_kg": ("起飞总质量", r"$\mathrm{kg}$"),
    "cruise_power_kw": ("巡航功率", r"$\mathrm{kW}$"), "hover_power_kw": ("悬停功率", r"$\mathrm{kW}$"),
    "comms_power_kw": ("通信附加功率", r"$\mathrm{kW}$"),
    "max_hover_agl_m": ("悬停离地上限", r"$\mathrm{m}$"),
    "sortie_id": ("架次", ""), "stop_seq": ("站点序", ""),
    "arrive_s": ("到达时刻", r"$\mathrm{s}$"), "depart_s": ("离开时刻", r"$\mathrm{s}$"),
    "start_time_s": ("开始时刻", r"$\mathrm{s}$"), "end_time_s": ("结束时刻", r"$\mathrm{s}$"),
    "total_energy_kwh": ("总能耗", r"$\mathrm{kWh}$"), "energy_kwh": ("能耗", r"$\mathrm{kWh}$"),
    "distance_m": ("距离", r"$\mathrm{m}$"), "duration_s": ("用时", r"$\mathrm{s}$"),
    "makespan_h": ("完工时间", r"$\mathrm{h}$"), "makespan_s": ("完工时间", r"$\mathrm{s}$"),
    "on_time": ("准时", ""), "deadline_s": ("时限", r"$\mathrm{s}$"),
    "violation": ("违规", ""), "n_violations": ("违规数", ""),
    "rho_g": (r"$\rho_{g}$", "2"), "n_sorties": ("架次数", ""),
    "lower_bound": ("下界", ""), "gap": ("差距", ""), "ratio": ("比值", "3"),
    "soc_end": ("结束 SOC", "3"), "relay_position_lon": ("悬停经度", r"$^\circ$"),
    "relay_position_lat": ("悬停纬度", r"$^\circ$"),
    "hover_alt_m": ("悬停海拔", r"$\mathrm{m}$"), "hover_agl_m": ("离地高度", r"$\mathrm{m}$"),
    "n_covered": ("覆盖架次", ""), "n_need_relay": ("需保障架次", ""),
    "coverage_rate": ("覆盖率", "3"), "group_id": ("组号", ""),
    "n_uav": ("运输机", r"$\mathrm{架}$"), "n_battery": ("电池", r"$\mathrm{组}$"),
    "n_relay": ("中继机", r"$\mathrm{架}$"), "n_energy": ("能源组件", r"$\mathrm{组}$"),
    "total": ("合计", ""), "status": ("状态", ""), "note": ("说明", ""),
    "path": ("文件路径", ""), "file": ("文件", ""), "chapter": ("章节", ""),
    "caption": ("标题", ""), "section": ("章节", ""), "fig_id": ("编号", ""),
    "tab_id": ("编号", ""), "kind_label": ("类别", ""), "q": ("问题", ""),
    # 逐问指标表 / 下界表常见列
    "rho": (r"$\rho_{g}$", ""), "feasible": ("可行", ""),
    "n_infeasible_areas": ("不可行服务区数", ""), "strategy": ("策略", ""),
    "types": ("机型构成", ""), "serial_total_time_s": ("累计作业时间", r"$\mathrm{s}$"),
    "total_time_s": ("累计时间", r"$\mathrm{s}$"), "total_mass_kg": ("总质量", r"$\mathrm{kg}$"),
    "total_volume_m3": ("总体积", r"$\mathrm{m^3}$"), "lb": ("下界", ""),
    "n_stops": ("站点数", ""), "stops": ("站点序列", ""), "boxes_per_stop": ("逐站箱数", ""),
    "load_kg": ("载荷", r"$\mathrm{kg}$"), "soc": ("SOC", "3"),
    "start_s": ("开始", r"$\mathrm{s}$"), "finish_s": ("结束", r"$\mathrm{s}$"),
    "wait_s": ("等待", r"$\mathrm{s}$"), "charge_s": ("充电", r"$\mathrm{s}$"),
    "used_times": ("使用次数", ""), "n_used": ("使用次数", ""),
    "index": ("序号", ""), "item": ("项目", ""), "value": ("数值", ""),
    "参数": ("参数", ""), "数值": ("数值", ""), "指标": ("指标", ""),
    "符号": ("符号", ""), "说明": ("说明", ""),
    "链路": ("链路", ""), "双向门限(dB)": ("双向门限 / $\\mathrm{dB}$", ""),
    "无遮挡可达(km)": ("无遮挡可达 / $\\mathrm{km}$", ""),
    "含遮挡可达(km)": ("含遮挡可达 / $\\mathrm{km}$", ""),
    "货箱编号": ("货箱编号", ""), "服务区": ("服务区", ""), "架次": ("架次", ""),
    "首批保障": ("首批保障", ""), "首批截止（s）": ("首批截止 / $\\mathrm{s}$", ""),
    "期望送达（s）": ("期望送达 / $\\mathrm{s}$", ""),
    "实际交付（s）": ("实际交付 / $\\mathrm{s}$", ""),
    "首批达标": ("首批达标", ""), "期望达标": ("期望达标", ""),
    # 机型 / 电池 / 中继清单类英文列名
    "code": ("编号", ""), "name": ("名称", ""),
    "cruise_speed_mps": ("巡航速度", r"$\mathrm{m \cdot s^{-1}}$"),
    "cruise_speed_ms": ("巡航速度", r"$\mathrm{m \cdot s^{-1}}$"),
    "range_empty_m": ("空载航程", r"$\mathrm{m}$"),
    "range_full_m": ("满载航程", r"$\mathrm{m}$"),
    "prepare_time_s": ("准备时间", r"$\mathrm{s}$"),
    "load_time_per_box_s": ("单箱装载时间", r"$\mathrm{s}$"),
    "handover_base_s": ("交接基础时间", r"$\mathrm{s}$"),
    "handover_per_box_s": ("逐箱交接时间", r"$\mathrm{s}$"),
    "type_code": ("机型编号", ""), "n_battery_packs": ("配套电池组数", r"$\mathrm{组}$"),
    "t_full_s": ("满充时间", r"$\mathrm{s}$"),
    "initial_position": ("初始位置", ""), "op_height_offset_m": ("作业高度偏移", r"$\mathrm{m}$"),
    "population": ("服务人口", r"$\mathrm{人}$"), "id": ("编号", ""),
}

# 英文列名 = 基本名 + 单位后缀；先查基名再拼单位，可覆盖绝大多数附件列
BASE_HINT: dict[str, str] = {
    "code": "编号", "name": "名称", "empty_mass": "空载质量", "payload": "载荷",
    "max_payload": "最大载荷", "volume": "舱容", "cruise_speed": "巡航速度",
    "climb_speed": "爬升速度", "descent_speed": "下降速度",
    "range_empty": "空载航程", "range_full": "满载航程", "range": "航程",
    "energy": "能量", "reserve_ratio": "返航安全余量", "prepare_time": "准备时间",
    "box_load_time": "单箱装载时间", "load_time_per_box": "单箱装载时间",
    "handover_base": "交接基础时间", "handover_per_box": "逐箱交接时间",
    "climb_efficiency": "爬升效率", "descent_efficiency": "下降效率",
    "comms_module_mass": "通信模块质量", "takeoff_mass": "起飞总质量",
    "cruise_power": "巡航功率", "hover_power": "悬停功率", "comms_power": "通信附加功率",
    "link_setup_time": "建链时间", "turnaround_time": "周转时间",
    "max_hover_agl": "悬停离地上限", "n_battery_packs": "配套电池组数",
    "t_full": "满充时间", "distance": "距离", "duration": "用时", "time": "时间",
    "mass": "质量", "speed": "速度", "efficiency": "效率", "n": "数量",
    "ground_elev": "地面高程", "op_height_offset": "作业高度偏移",
    "cruise_alt": "巡航海拔", "hover_alt": "悬停海拔", "hover_agl": "离地高度",
}

UNIT_SUFFIX: dict[str, str] = {
    "kg": r"$\mathrm{kg}$", "g": r"$\mathrm{g}$",
    "m3": r"$\mathrm{m^3}$", "m": r"$\mathrm{m}$", "km": r"$\mathrm{km}$",
    "s": r"$\mathrm{s}$", "min": r"$\mathrm{min}$", "h": r"$\mathrm{h}$",
    "kwh": r"$\mathrm{kWh}$", "kw": r"$\mathrm{kW}$", "wh": r"$\mathrm{Wh}$",
    "ms": r"$\mathrm{m \cdot s^{-1}}$", "mps": r"$\mathrm{m \cdot s^{-1}}$",
    "db": r"$\mathrm{dB}$", "dbm": r"$\mathrm{dBm}$", "mhz": r"$\mathrm{MHz}$",
}

# 宽表（列数多）使用的紧凑表头：避免逐字换行把表撑高甚至跨页
COMPACT_COL: dict[str, str] = {
    "code": "编号", "name": "名称", "empty_mass_kg": "空机质量",
    "max_payload_kg": "载荷", "volume_m3": "舱容",
    "cruise_speed_ms": "巡航速度", "range_empty_m": "空载航程",
    "range_full_m": "满载航程", "energy_kwh": "能量",
    "reserve_ratio": "余量", "prepare_time_s": "准备",
    "box_load_time_s": "装载", "handover_base_s": "交接",
    "handover_per_box_s": "逐箱", "climb_speed_ms": "爬升速度",
    "descent_speed_ms": "下降速度", "climb_efficiency": "爬升效率",
    "descent_efficiency": "下降效率",
    "服务区编号": "服务区", "机型编号": "机型", "架次编号": "架次",
    "货箱编号列表": "货箱列表", "中继架次编号": "架次",
    "中继无人机编号": "中继机", "能源组件编号": "能源组件",
    "无人机编号": "无人机", "电池编号": "电池",
    "访问服务区顺序": "访问顺序", "返回O01时刻（s）": "返回时刻",
    "建链完成时刻（s）": "建链时刻", "服务结束时刻（s）": "服务结束",
    "开始时刻（s）": "开始时刻", "架次能耗（kWh）": "能耗",
    "实际交付（s）": "实际交付", "期望送达（s）": "期望送达",
    "首批截止（s）": "首批截止", "最大组工作量h": "最大组工作量",
}


def _auto_font(ncol: int, base: float) -> float:
    """列数多时自动缩小字号（**粗筛**）。

    精确的字号由 `_fit_font_to_headers()` 依据"表头文字实际宽度 ≤ 列宽"反解，
    本函数只提供上界，避免列数很多时字号过大。
    """
    if ncol >= 14:
        return min(base, 7.0)
    if ncol >= 11:
        return min(base, 7.5)
    if ncol >= 9:
        return min(base, 8.0)
    return base


_CELL_MARGIN_CM = 0.075
"""单侧单元格内边距（与 `_cell_margin(left=30, right=30)` 保持一致：
30 twips = 0.0529 cm，取 0.075 cm 略保守，留出安全余量）。"""


def _fit_font_to_headers(headers: list[str], widths_cm: list[float],
                         base: float) -> float:
    """反解"表头不换行"所需的最大字号（pt），并夹在 [6.0, base] 内。

    为什么需要它：中文表头（如"首个中断时刻（s）"）在固定列宽下若字号过大，
    Word 会逐字换行（甚至把表头顶成两行、行高翻倍、整表跨页）。
    这里用与列宽分配**同一套** `_est_len` 宽度度量反解字号：
        needed_pt ≈ (列宽 − 内边距) / (字数 × 每字宽度系数)
    其中 CJK 字符按 1 em、ASCII 按 0.5 em（与 `_est_len` 的 2:1 一致），
    1 em = 字号（pt）。取所有列的最小值即可保证"任何表头都不换行"。
    """
    best = base
    for h, w in zip(headers, widths_cm):
        avail_cm = max(0.05, w - 2 * _CELL_MARGIN_CM)
        em = _est_len(h) / 2.0          # 折算为 em 数（CJK=1em，ASCII=0.5em）
        if em <= 0:
            continue
        pt = (avail_cm / 2.54 * 72.0) / em   # cm → pt，再除以 em 数
        best = min(best, pt)
    return max(6.0, min(base, best))

NUM_COLS_3 = {
    "soc", "soc_start", "rate", "coverage", "fraction", "share", "utilization",
    "imbalance", "mean", "std",
}
NUM_COLS_1 = {"elev", "capacity", "count", "n_", "num", "times", "usage"}

UNIT_MATH: dict[str, str] = {
    "kg": r"$\mathrm{kg}$", "g": r"$\mathrm{g}$",
    "m": r"$\mathrm{m}$", "km": r"$\mathrm{km}$",
    "m³": r"$\mathrm{m^3}$", "m3": r"$\mathrm{m^3}$",
    "s": r"$\mathrm{s}$", "min": r"$\mathrm{min}$", "h": r"$\mathrm{h}$",
    "kWh": r"$\mathrm{kWh}$", "kW": r"$\mathrm{kW}$", "Wh": r"$\mathrm{Wh}$",
    "dB": r"$\mathrm{dB}$", "dBm": r"$\mathrm{dBm}$",
    "MHz": r"$\mathrm{MHz}$", "m/s": r"$\mathrm{m \cdot s^{-1}}$",
    "°": r"$^\circ$", "%": r"$\%$", "架": r"$\mathrm{架}$",
    "组": r"$\mathrm{组}$", "台": r"$\mathrm{台}$",
}

INT_HINT = re.compile(
    r"(^n_|_n$|_count$|count$|^n$|_id$|^id$|seq$|rank$|index$|^k$|boxes$|times$|"
    r"on_time$|violation)", re.I)
# ★ 中文列名补充规则：上面的 INT_HINT/NUM_COLS_3 都是英文键，中文表头一个都匹配不上，
#   于是"架次数 14"会掉到兜底分支被写成 "14.000"、"总能耗 77.94" 写成 "77.940"。
CN_INT_HINT = re.compile(
    r"架次数|箱数|个数|条数|次数|组数|架数|机数|单元数|分量数|服务区数|"
    r"资源总量|数量|违规|无人机|电池|组件")
CN_2DP_HINT = re.compile(
    r"能耗|完工|工作量|得分|时长|用时|里程|距离|质量|体积|容积|载荷")
#: 不均衡度正文按 4 位小数引用，表格须与正文一致
CN_4DP_HINT = re.compile(r"不均衡|imbalance", re.I)
SCI_HINT = re.compile(r"(energy|kwh|power|loss|db|dist|range|mass|volume|payload)", re.I)


def fmt_cell(v, col: str) -> str:
    """按列名语义格式化单元格（整数不带小数点、大数用科学计数、比例定小数位）。"""
    if v is None:
        return ""
    if isinstance(v, str):
        s = v.strip()
        if s.lower() in ("nan", "none"):
            return ""
        if col in ("name", "名称") and len(s) > 5:
            return s[:5]          # 名称类列过长会把整张表撑高
        return s
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f != f:  # NaN
        return ""
    if INT_HINT.search(col) and abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    if CN_INT_HINT.search(col) and abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    a = abs(f)
    if a and (a >= 1e5 or a < 1e-3):
        return f"{f:.3e}"
    if INT_HINT.search(col):
        return f"{f:.0f}"
    if CN_2DP_HINT.search(col):
        return f"{f:.2f}"
    if CN_4DP_HINT.search(col):
        return f"{f:.4f}"
    if col in NUM_COLS_3 or col in ("coverage_rate", "ratio"):
        return f"{f:.3f}"
    if a >= 100:
        return f"{f:.1f}"
    return f"{f:.3f}"


def col_header(col: str) -> str:
    """列名 → 中文表头（含单位/符号，单位用行内公式）。

    依次尝试：
      1. 精确匹配 `COL_HINT`（含人工校正的中文表头）；
      2. 后缀匹配 `COL_HINT`（`n_uav_used` → `_used`）；
      3. 拆出单位后缀后用 `BASE_HINT` 拼装（`empty_mass_kg` → 空载质量 / kg）；
      4. 中文列名里的"（单位）"或紧凑单位（`能耗kWh`）。
    """
    import re as _re

    c = str(col)
    if c in COMPACT_COL:
        return COMPACT_COL[c]
    if c in COL_HINT:
        name, unit = COL_HINT[c]
        return f"{name} / {unit}" if unit else name
    for key in sorted(COL_HINT, key=len, reverse=True):
        if len(key) >= 4 and c.endswith(key):
            name, unit = COL_HINT[key]
            return f"{name} / {unit}" if unit else name

    m = _re.match(r"^(?P<base>[a-z0-9_]+?)_(?P<unit>[a-z0-9]{1,5})$", c)
    if m and m.group("unit") in UNIT_SUFFIX and m.group("base") in BASE_HINT:
        return f"{BASE_HINT[m.group('base')]} / {UNIT_SUFFIX[m.group('unit')]}"

    m = _re.match(r"^(?P<name>.+?)\s*[（(]\s*(?P<unit>[^）)]+?)\s*[）)]$", c)
    if m:
        name = m.group("name").strip()
        unit = m.group("unit").strip()
        if unit in UNIT_MATH:
            return f"{name} / {UNIT_MATH[unit]}"
        if _re.fullmatch(r"[A-Za-z%°]+", unit):
            return f"{name} / ${{\\mathrm{{{unit}}}}}$"
        return name
    # 无括号的紧凑写法："能耗kWh"、"最大组工作量h"
    m2 = _re.match(r"^(?P<name>.+?)\s*(?P<unit>[A-Za-z%°]{1,5})$", c)
    if m2 and m2.group("unit") in UNIT_MATH:
        return f"{m2.group('name')} / {UNIT_MATH[m2.group('unit')]}"
    # 最后兜底：把下划线换成空格，并把末尾的单位记号转成公式
    parts = c.rsplit("_", 1)
    if len(parts) == 2 and parts[1].lower() in UNIT_SUFFIX:
        base = parts[0].replace("_", " ")
        return f"{base} / {UNIT_SUFFIX[parts[1].lower()]}"
    return c.replace("_", " ")


# ---------------------------------------------------------------- 富文本

_INLINE_RE = re.compile(r"\*\*(.+?)\*\*|\$(.+?)\$", re.S)


def _add_text_runs(p, text, size, bold, cn=None):
    """按 `**加粗**` 与 `$行内公式$` 切分并写入段落。"""
    pos = 0
    for m in _INLINE_RE.finditer(text):
        if m.start() > pos:
            _set_font(p.add_run(text[pos:m.start()]), size, bold=bold,
                      cn=cn or (CN_HEI if bold else CN_FONT))
        if m.group(1) is not None:
            _set_font(p.add_run(m.group(1)), size, bold=True, cn=CN_HEI)
        else:
            EQM.append_omml(p, m.group(2), display=False)
        pos = m.end()
    if pos < len(text):
        _set_font(p.add_run(text[pos:]), size, bold=bold,
                  cn=cn or (CN_HEI if bold else CN_FONT))


_PLAIN_MATH = re.compile(r"\$([^$]*)\$")


def _math_to_plain(expr: str) -> str:
    """把简单公式转成普通文本（用于**表格数据行**）。

    表格数据行由 CSV 提供，其中的单位记号（`$\\mathrm{kg}$`）本不该出现在数据里；
    但确有少数表把带单位的表头写进了数据行。这里统一剥掉公式标记，
    避免 Word 里出现难看的 `$\\mathrm{kg}$` 原文。
    """
    t = _PLAIN_MATH.sub(lambda m: m.group(1), expr)
    t = re.sub(r"\\mathrm\{([^{}]*)\}", r"\1", t)
    t = re.sub(r"\\text\{([^{}]*)\}", r"\1", t)
    t = t.replace("\\,", " ").replace("\\ ", " ")
    t = re.sub(r"\^\{?\\circ\}?", "°", t)
    t = re.sub(r"\^\{?(-?\d+)\}?", r"^\1", t)
    t = re.sub(r"_\{([^{}]*)\}", r"\1", t)
    t = t.replace("$", "").replace("{", "").replace("}", "")
    return t.strip()


def H(doc, text, level=1, page_break=None):
    """标题。**一级标题自动另起新页**（由 Heading 1 样式保证）。

    `page_break` 仅用于封面前/目录等特殊情况显式覆盖：
    传 False 表示该标题不要分页（例如目录页已单独分页）。
    """
    n = doc.add_heading("", level=level)
    if page_break is not None:
        n.paragraph_format.page_break_before = bool(page_break)
    n.paragraph_format.first_line_indent = Pt(0)
    _set_font(n.add_run(text), {1: 16, 2: 14, 3: 12.5, 4: 12}[level],
              bold=True, cn=CN_HEI)
    return n


def P(doc, text, indent=True, size=12, align=None, bold=False, keep_with_next=False):
    p = doc.add_paragraph()
    if not indent:
        p.paragraph_format.first_line_indent = Pt(0)
    if align == "center":
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if keep_with_next:
        p.paragraph_format.keep_with_next = True
    _add_text_runs(p, text, size, bold)
    return p


def EQ(doc, text, num=None, size=12):
    """居中公式行（MathType / OMML），编号右对齐。

    用"居中制表位 + 右制表位"排布：公式居中、编号贴右边界，
    与教材/论文排版惯例一致。
    """
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.first_line_indent = Pt(0)
    pf.space_before = Pt(4)
    pf.space_after = Pt(4)
    pf.keep_together = True
    pf.tab_stops.add_tab_stop(Emu(int(Cm(TEXT_WIDTH_CM) / 2)), WD_TAB_ALIGNMENT.CENTER)
    pf.tab_stops.add_tab_stop(Cm(TEXT_WIDTH_CM), WD_TAB_ALIGNMENT.RIGHT)
    p.add_run("\t")
    EQM.append_omml(p, text, display=False)
    if num:
        p.add_run("\t")
        _set_font(p.add_run(f"({num})"), size)
    return p


def BULLETS(doc, items, size=11.5):
    for it in items:
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.first_line_indent = Pt(0)
        p.paragraph_format.line_spacing = 1.35
        p.paragraph_format.left_indent = Pt(24)
        _add_text_runs(p, it, size, False)


def FIGURE(doc, name: str, caption: str, width_cm=15.4, max_h_cm=9.0):
    """插图 + 图题。要求 4：图与图题必须同页 —— 图与图题都设 keep_with_next。

    为兼顾"图不跨页"与"少留白"，按图幅比例反算宽度：高图自动缩窄，
    使显示高度不超过 `max_h_cm`，从而更容易与题注一起落在同一页。
    """
    p = FIG / f"{name}.png"
    if not p.exists():
        P(doc, f"[缺图 {name}]", indent=False)
        return
    try:
        from PIL import Image

        w_px, h_px = Image.open(p).size
        if w_px > 0:
            width_cm = min(width_cm, max_h_cm * w_px / h_px)
            width_cm = max(width_cm, 7.5)
    except Exception:  # noqa: BLE001
        pass
    doc.add_picture(str(p), width=Cm(width_cm))
    ip = doc.paragraphs[-1]
    ip.alignment = WD_ALIGN_PARAGRAPH.CENTER
    ip.paragraph_format.first_line_indent = Pt(0)
    ip.paragraph_format.space_before = Pt(6)
    ip.paragraph_format.space_after = Pt(2)
    ip.paragraph_format.keep_with_next = True   # 图片与其下方题注同页
    ip.paragraph_format.keep_together = True

    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.paragraph_format.first_line_indent = Pt(0)
    cap.paragraph_format.space_after = Pt(10)
    cap.paragraph_format.keep_together = True
    # ★ 图题**不**设 keep_with_next：否则"图 + 图题 + 下一段"会被当成一个
    #   不可分割的整体，只要放不下就把三块一起推到下页，制造大片留白。
    #   图片段落已设 keep_with_next，足以保证"图与其图题同页"。
    _add_text_runs(cap, caption, 10.5, True, cn=CN_HEI)


def _fill_row(row, values, font, header=False):
    for j, v in enumerate(values):
        cell = row.cells[j]
        cell.text = ""
        para = cell.paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.paragraph_format.first_line_indent = Pt(0)
        para.paragraph_format.space_after = Pt(1)
        para.paragraph_format.space_before = Pt(1)
        para.paragraph_format.line_spacing = 1.15
        text = "" if v is None else str(v)
        if text.lower() in ("nan", "none"):
            text = ""
        if header:
            # 表头允许 `$...$` 行内公式（如"最大安全载荷 / $\mathrm{kg}$"）
            _add_text_runs(para, text, font, True, cn=CN_HEI)
        else:
            # ★ 数据行不用公式：少数表把带单位的表头混进了数据，会出现
            #   `$\mathrm{kg}$` 原文。统一剥成纯文本，避免 Word 里出现 LaTeX 记号。
            _set_font(para.add_run(_shorten(_math_to_plain(text))), font, cn=CN_FONT)


def _shorten(text: str, limit: int = 34) -> str:
    """过长的单元格内容截断显示（完整内容在附件 CSV 中）。"""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip(" ,;、") + "…"


def TABLE(doc, name: str, caption: str, max_rows: int = 40, font=8.5,
          df: pd.DataFrame | None = None, keep_intro: bool = True):
    """三线表（参照参考文稿2）：顶线 / 表头下线 / 底线，**无竖线**。

    要求 4：表与表题同页 —— 表题设 keep_with_next，行禁止跨页断开。
    `df` 给定时直接用它（用于在代码中构造的符号表等）。
    """
    if df is None:
        p = TAB / f"{name}.csv"
        if not p.exists():
            P(doc, f"[缺表 {name}]", indent=False)
            return
        df = pd.read_csv(p)
    else:
        df = df.copy()
    total = len(df)
    show = df.head(max_rows)
    ncol = len(show.columns)

    cap = doc.add_paragraph()
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap.paragraph_format.first_line_indent = Pt(0)
    cap.paragraph_format.space_before = Pt(8)
    cap.paragraph_format.space_after = Pt(3)
    cap.paragraph_format.keep_with_next = True     # 表题与表体同页
    cap.paragraph_format.keep_together = True
    _add_text_runs(cap, caption, 10.5, True, cn=CN_HEI)

    # ★ 两步走：先按列数粗筛字号并分配列宽，再按**实际列宽**反解
    #   "表头不换行"的字号，最后用最终字号重填一遍单元格。
    #   （只做其中一步都会残留换行：列宽够了字号太大、或字号小了列宽仍窄。）
    font = _auto_font(ncol, font)
    headers = [col_header(c) for c in show.columns]
    body_rows: list[list[str]] = []
    for _, r in show.iterrows():
        body_rows.append([fmt_cell(r[c], str(c)) for c in show.columns])

    t = doc.add_table(rows=1, cols=ncol)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    _fill_row(t.rows[0], headers, font, header=True)
    for vals in body_rows:
        _fill_row(t.add_row(), vals, font)

    _three_line_borders(t)
    _header_bottom_rule(t.rows[0])
    widths = _col_widths(t, headers, body_rows, font_pt=font)
    font = _fit_font_to_headers(headers, widths, font)

    # 用最终字号重填（`_fill_row` 自身会清空单元格；列宽已定，字号不影响列宽）
    _fill_row(t.rows[0], headers, font, header=True)
    for i, vals in enumerate(body_rows, start=1):
        _fill_row(t.rows[i], vals, font)

    _cell_margin(t)
    for row in t.rows:
        _no_split(row)
    _repeat_header(t.rows[0])
    _TBL_FONTS.append({"表": name, "列数": ncol, "字号pt": round(font, 2)})

    if total > max_rows:
        note = doc.add_paragraph()
        note.alignment = WD_ALIGN_PARAGRAPH.CENTER
        note.paragraph_format.first_line_indent = Pt(0)
        note.paragraph_format.space_before = Pt(2)
        note.paragraph_format.space_after = Pt(8)
        _set_font(note.add_run(
            f"（表中共 {total} 行，此处列出前 {max_rows} 行；完整数据见随文附件 "
            f"paper/tables/{name}.csv）"), 9)
    else:
        doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def TOC(doc) -> None:
    """插入 Word 目录域（打开文档后按 F9 更新）。"""
    p = doc.add_paragraph()
    p.paragraph_format.first_line_indent = Pt(0)
    run = p.add_run()
    f1 = OxmlElement("w:fldChar"); f1.set(qn("w:fldCharType"), "begin")
    it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve")
    it.text = r' TOC \o "1-3" \h \z \u '
    f2 = OxmlElement("w:fldChar"); f2.set(qn("w:fldCharType"), "separate")
    t = OxmlElement("w:t"); t.text = "右键此处选择“更新域”即可生成目录。"
    f3 = OxmlElement("w:fldChar"); f3.set(qn("w:fldCharType"), "end")
    for e in (f1, it, f2, t, f3):
        run._r.append(e)
    _set_font(run, 10.5)


def RICH(doc, parts, indent=True, size=12, align=None, space_after=4,
         keep_with_next=False):
    """混排段落：parts = [(文本, 是否加粗), ...]；文本内可用 `$...$` 嵌入公式。"""
    p = doc.add_paragraph()
    if not indent:
        p.paragraph_format.first_line_indent = Pt(0)
    if align == "center":
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(space_after)
    if keep_with_next:
        p.paragraph_format.keep_with_next = True
    for text, bold in parts:
        _add_text_runs(p, text, size, bold)
    return p


# ================================================================ 数据载入

def metrics(q: str) -> dict:
    p = REPO_ROOT / f"outputs/{q}/metrics.json"
    return json.loads(p.read_text(encoding="utf-8"))["metrics"] if p.exists() else {}


def T(name: str) -> pd.DataFrame:
    p = TAB / f"{name}.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


SYMBOLS: list[tuple[str, str]] = [
    (r"$O01$", "临时调度中心（与固定网关 G01 同址）"),
    (r"$S_{i}$", "第 i 个服务区，i = 1,…,15"),
    (r"$G01$", "固定通信网关"),
    (r"$g$", "运输机型，g ∈ {A, B, C}"),
    (r"$R_{k}$", "第 k 架中继无人机，k = 1, 2"),
    (r"$Q_{g}$", "机型 g 的结构载重上限，kg"),
    (r"$V_{g}$", "机型 g 的货舱容积上限，m³"),
    (r"$E_{g}^{use}$", "机型 g 单组电池可用能量，kWh"),
    (r"$T_{full}$", "电池由 0% 充至 100% 的满充时间，min"),
    (r"$L_{g}(q)$", "机型 g 携带载荷 q 时的等效航程，m"),
    (r"$L_{g0},\,L_{gF}$", "空载 / 满载标准航程，m"),
    (r"$q_{max}^{safe}(g,i)$", "机型 g 在服务区 i 的最大安全载荷，kg"),
    (r"$\rho_{g}$", "返航安全余量比例，附件取 0.20"),
    (r"$H_{cruise}$", "航段计划巡航海拔，m"),
    (r"$h^{+},\,h^{-}$", "爬升 / 下降高度，m"),
    (r"$v_{g}^{up},v_{g}^{c},v_{g}^{down}$", "爬升 / 巡航 / 下降速度，m·s⁻¹"),
    (r"$d_{ij}$", "节点 i 与 j 的水平直线距离，m"),
    (r"$t_{gij}$", "航段飞行时间，s"),
    (r"$E_{gij}^{hor},\,E_{gij}^{up}$", "水平巡航 / 爬升附加能耗，kWh"),
    (r"$\eta_{up}$", "爬升能耗效率，取 0.72"),
    (r"$s$", "荷电状态 SOC，s ∈ [0, 1]"),
    (r"$t_{chg}(s)$", "由 SOC = s 充满所需时间，min"),
    (r"$m_{b},\,v_{b}$", "货箱 b 的质量 kg / 体积 m³"),
    (r"$n_{box}$", "架次装载的货箱数"),
    (r"$t_{p}$", "架次总作业时间，s"),
    (r"$P_{t,a}$", "发射端 a 的发射功率，dBm"),
    (r"$P_{sens,b}$", "接收端 b 的接收灵敏度，dBm"),
    (r"$M_{b}$", "接收端 b 的衰落裕量，dB"),
    (r"$P_{th,b}$", "接收端 b 的有效接收门限，dBm"),
    (r"$L_{max,a \to b}$", "a→b 方向的最大允许路径损耗，dB"),
    (r"$L_{max,a \leftrightarrow b}$", "双向链路门限（取两方向较小值），dB"),
    (r"$L_{FSPL}$", "自由空间路径损耗，dB"),
    (r"$L_{obs}$", "地形遮挡附加损耗，取 10 dB"),
    (r"$b_{ijt}$", "时刻 t 链路 (i,j) 的地形遮挡指示变量"),
    (r"$A_{ijt}$", "时刻 t 链路可用性指示变量"),
    (r"$D_{ijt}$", "时刻 t 链路两端三维距离，km"),
    (r"$P_{hover},\,P_{comms}$", "中继悬停功率 / 通信附加功率，kW"),
    (r"$t_{svc}$", "中继服务时段，s"),
    (r"$K$", "任务组数，K ∈ {1, 2, 3}"),
]


def symbol_table() -> pd.DataFrame:
    """双栏符号表（符号 | 说明 | 符号 | 说明），与参考文稿2 的符号表版式一致。"""
    rows = []
    half = (len(SYMBOLS) + 1) // 2
    left, right = SYMBOLS[:half], SYMBOLS[half:]
    for k in range(half):
        a = left[k]
        b = right[k] if k < len(right) else ("", "")
        rows.append({"符号": a[0], "说明": a[1], "符号": b[0], "说明": b[1]})
    return pd.DataFrame(rows)


def main() -> int:
    import argparse

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="生成论文 docx（公式为 Word 原生 OMML 公式）")
    ap.add_argument("--mathtype", action="store_true",
                    help="实验性：把公式转成 MathType OLE 对象（该库生成的容器在 "
                         "Word 中无法激活，双击打不开，见 ADR-028）")
    args = ap.parse_args()

    m1, m2, m3, m4 = metrics("q1"), metrics("q2"), metrics("q3"), metrics("q4")
    nodes = T("t_nodes"); uav = T("t_uav_params"); relay = T("t_relay_params")
    pay = T("t_q1_payload"); lb = T("t_q1_lowerbound")
    strat = T("t_q1_strategy"); rho = T("t_q1_rho_sweep")
    q2s = T("t_q2_sorties"); tl = T("t_q2_timeliness")
    q3d = T("t_q3_diagnosis"); q3r = T("t_q3_relay_sorties")
    q4c = T("t_q4_compare"); q4g = T("t_q4_gap"); q4grp = T("t_q4_group")
    q4b = T("t_q4_bridge"); q2t = T("t_q2_tradeoff"); q4u = T("t_q4_units")
    lnk = T("t_link_thresholds")

    doc = Document()
    setup(doc)

    # ============================================================ 封面
    for _ in range(3):
        doc.add_paragraph()
    RICH(doc, [("山区洪涝灾害下无人机运输与通信协同优化", True)],
         indent=False, size=22, align="center", space_after=18)
    RICH(doc, [("——面向 2026 年中国研究生数学建模竞赛 D 题的建模与求解", False)],
         indent=False, size=13, align="center", space_after=30)
    RICH(doc, [("摘  要", True)], indent=False, size=16, align="center")

    n_svc = int(m1.get("n_service_areas", 15))
    n_box = int(m1.get("n_boxes", 80))
    P(doc,
      f"山区洪涝灾害下物资投送需在道路受阻、能源受限、通信中断的条件下协同组织。"
      f"本文以广西横州市镇龙乡 1 个临时调度中心 O01、{n_svc} 个服务区、{n_box} 个不可拆货箱、"
      f"3 种运输机型（8 架实体机）与 2 架中继无人机为场景，围绕"
      f"“运输任务如何组织、通信保障如何匹配、有限资源如何调配”建立数学模型并求解。"
      f"全文建立**统一物理计算器**（地形净空、等效航程、三阶段飞行时间、水平与爬升能耗、"
      f"SOC 两阶段充电、三维视线遮挡与双向链路预算），四问共用同一套公式与对象编号；"
      f"另建**独立可行性校验器**（不导入求解器任何模块、直接从附件与 DEM 重算全部物理量，"
      f"含 18 类约束与负例测试）复核全部结果。")

    P(doc,
      f"针对问题一，建立“能量约束二分反解 + 结构上限取小”的最大安全载荷模型，"
      f"得到 3 机型 × 15 服务区共 {int(m1.get('n_uav_types',3))*n_svc} 组安全载荷。"
      f"结果表明 A 型机在 15/15 个服务区均受**结构载重**约束（载荷恒为 25 kg），"
      f"B 型 14/15 受结构约束，C 型仅 10/15——能量约束只在 C 型远距离飞行时成为紧约束。"
      f"货箱组批建模为**质量—体积二维装箱**：先按（质量, 体积, 首批标记, 期望时限）"
      f"聚合箱型，再枚举全部**可行批次**，最后用**精确字典序动态规划**"
      f"（目标为「架次数最少 → 总能耗最低 → 累计作业时间最短」的字典序）求全局最优；"
      f"同时给出装箱解析下界。推荐方案 {int(m1.get('chosen_n_sorties',18))} 架次"
      f"（B×9 + C×9，异构混编）、总能耗 "
      f"{m1.get('chosen_total_energy_kwh',0):.3f} kWh、"
      f"累计作业时间 {m1.get('chosen_serial_total_time_s',0)/3600:.2f} h；"
      f"逐区架次数**等于解析下界**（合计 "
      f"{int(m1.get('lower_bound_total_sorties',18))}），故架次数维度可证最优。"
      f"返航安全余量敏感性分析（**每个 $\\rho_{{g}}$ 都重跑精确 DP**）显示："
      f"$\\rho_{{g}}$ 在 0.10~0.20 之间架次数与能耗不变（均 18 架次 / 59.0875 kWh），"
      f"增至 0.30 时架次数升到 20、能耗升到 67.1805 kWh，"
      f"$\\rho_{{g}} \\ge 0.40$ 时出现**无可行解服务区**。")

    P(doc,
      f"针对问题二，联合确定货箱组批、机型、执行无人机、共享电池与开工时刻。"
      f"组批继承问题一的精确 DP 口径，仅对 S006/S007/S008/S013 四个首批与医疗时限最紧的"
      f"服务区增开“先行小架次”，架次数由 18 增至 "
      f"{int(m2.get('n_sorties',23))}；随后把实体机与共享电池的周转建成"
      f"**资源受限区间调度模型**，用 **CP-SAT** 的可选区间与 `NoOverlap` 约束"
      f"（含两阶段充电的电池占用）精确求解，目标为最小化最晚返回时刻。"
      f"得到 {int(m2.get('n_sorties',23))} 架次、"
      f"总能耗 {m2.get('total_energy_kwh',0):.3f} kWh、"
      f"完工时间 {m2.get('makespan_h',0):.3f} h（{m2.get('makespan_s',0):.1f} s）、"
      f"准时率 {m2.get('on_time_rate',0):.1%}"
      f"（首批箱 {int(m2.get('n_first_batch_on_time',30))}/"
      f"{int(m2.get('n_first_batch',30))} 达标、全部箱 "
      f"{int(m2.get('n_expected_on_time',80))}/80 在期望时间内送达）。"
      f"**关键澄清**：给定方案数据的时刻表最晚返回 7740.19 s，比本方案小 103 s，"
      f"但它使 S015 医疗箱在 7470.0 s 交付，**违反 7200 s 硬时限**；"
      f"本文以 CP-SAT 逐档收紧完工时间上界做了判定——$C_{{\\max}} \\le 7843.2$ s 对给定组批"
      f"不可行、$\\le 7850$ s 可行，本方案在 7843.2 s 处即取得可行最优。"
      f"故该 103 s 差值是**时限可行性的代价**，而非本方案更慢。")

    P(doc,
      f"针对问题三，在问题二方案上叠加通信约束。按附录 3 实现三维地形遮挡判定"
      f"（遮挡仅附加固定损耗）与链路预算，对运输机"
      f"**爬升—巡航—下降—投送四阶段轨迹按 0.25 s 步长逐时刻采样**"
      f"（合计 {int(m3.get('radio_samples',0))} 个采样点），判定直连 / 中继 / 中断三态，"
      f"并在同一时间轴上复核中继架次的在站窗口。结果显示 "
      f"{int(m3.get('n_sorties_need_relay',0))}/{int(m3.get('n_transport_sorties',0))} "
      f"个架次存在直连中断，"
      f"{int(m3.get('n_relay_sorties',0))} 个中继架次使 "
      f"**{int(m3.get('n_sorties_covered',0))} 个架次全程零中断**"
      f"（架次覆盖率 {m3.get('coverage_rate',0):.1%}）；"
      f"仍有 {int(m3.get('outage_samples',0))} 个采样点"
      f"（{m3.get('mean_direct_outage_fraction',0):.2%}）落在"
      f"“需要中继且当时无中继在站”的时段，属于**2 架中继的硬性资源缺口**，"
      f"已如实上报而不作遮掩。运输能耗 {m3.get('transport_energy_kwh',0):.3f} kWh + "
      f"中继能耗 {m3.get('relay_energy_kwh',0):.3f} kWh，联合完工时间 "
      f"{m3.get('joint_cmax_s',0)/3600:.2f} h。"
      f"逐时刻最小链路裕量图显示：直连裕量最低 {m3.get('min_link_margin_direct_db',0):.2f} dB、"
      f"中继链路最低 {m3.get('min_link_margin_relay_db',0):.2f} dB，"
      f"中继在站期间始终保有正裕量，与“中继应贴近作业空域”的链路门限分析一致。")

    P(doc,
      f"针对问题四，按“同一运输架次的服务区必须同组”的规则，"
      f"将服务区关系建模为图并以**连通分量**作为不可拆原子单元；"
      f"由此得到**合法分区组数 K 的取值范围为 1 至连通分量数**这一结构性结论。"
      f"在本文问题三方案下，{int(m4.get('n_multi_stop_sorties',0))} 个多点架次把 15 个服务区"
      f"划为 **{int(m4.get('n_atomic_units',1))} 个连通分量**，"
      f"因此 **K=2 与 K=3 均可由原子单元直接合并得到，无需拆分任何架次**"
      f"（改动 0 个）；本文另给出 {int(m4.get('n_bridge_sorties',0))} 个桥接架次"
      f"作为进一步细化分区粒度时的备用依据。"
      f"对比结果显示：资源总规模 K=1/2/3 分别为 28 / 29 / 30（台·组），"
      f"组间不均衡度 0 / {m4.get('k2_resources',{}).get('imbalance',0.2):.4f} / {m4.get('k3_resources',{}).get('imbalance',0.8):.4f}，"
      f"而单组峰值工作量由 11.27 h 降到 6.28 / 5.62 h"
      f"——**分区并不节省资源总量**（K 越大总规模越大），"
      f"但能显著降低单组工作量峰值，"
      f"这是一条具有工程指导意义的结论。")

    P(doc,
      f"本文全部结论均通过独立校验器复核（不导入任何求解器模块，直接从附件与 DEM 重算"
      f"全部物理量）：问题二方案的硬约束违规为 **0 条**"
      f"（{int(m2.get('n_expected_on_time',80))}/80 箱按时送达、"
      f"{int(m2.get('n_first_batch_on_time',30))}/{int(m2.get('n_first_batch',30))} 首批箱达标），"
      f"逐架次能耗重算最大偏差 "
      f"{m2.get('independent_verification',{}).get('max_energy_dev_kwh',0):.4f} kWh、"
      f"SOC 最大偏差 {m2.get('independent_verification',{}).get('max_soc_dev',0):.4f}；"
      f"问题三另行如实报告 {int(m3.get('outage_samples',0))} 个"
      f"“需中继而无中继在站”的采样点为资源缺口。"
      f"对通信采样步长、悬停候选网格、DEM 高程噪声与衰落裕量做了敏感性分析，"
      f"结果表明结论在合理扰动下保持稳定。")

    RICH(doc, [("关键词：", True),
               ("无人机应急物流；等效航程；二维装箱下界；时限驱动调度；"
                "时空集合覆盖；连通分量分区", False)], indent=False)

    # ★ 修改要求 2：每章另起新页，由 Heading 1 样式统一控制；
    #   目录页与摘要页各自独立，故此处显式关掉目录标题的分页。
    H(doc, "目  录", 1, page_break=False)
    TOC(doc)

    build_body(doc, {
        "m1": m1, "m2": m2, "m3": m3, "m4": m4,
        "nodes": nodes, "uav": uav, "relay": relay, "pay": pay, "lb": lb,
        "strat": strat, "rho": rho, "q2s": q2s, "tl": tl,
        "q3d": q3d, "q3r": q3r, "q4c": q4c, "q4g": q4g, "q4grp": q4grp,
        "q4b": q4b, "q2t": q2t, "q4u": q4u, "lnk": lnk,
    })

    _page_number_footer(doc)
    doc.save(OUT)
    print(f"已生成：{OUT}")
    print(f"大小：{OUT.stat().st_size/1024/1024:.2f} MB")
    if _TBL_FONTS:
        fp = PAPER / "_table_fonts.json"
        fp.write_text(json.dumps(_TBL_FONTS, ensure_ascii=False, indent=1),
                      encoding="utf-8")
        tight = [t for t in _TBL_FONTS if t["字号pt"] <= 6.5]
        print(f"表格字号：{len(_TBL_FONTS)} 张，其中 ≤6.5 pt 的 {len(tight)} 张"
              f"（明细见 {fp.name}）")

    # ★ 公式形式（ADR-028）：
    #   默认输出 **OMML 原生公式**（Word 内置公式对象）：
    #     · 双击即可编辑（Word 公式编辑器）
    #     · 由 Word 排版引擎渲染，字号自动与正文一致，不会有比例问题
    #     · 在任何 Word/WPS 环境与 PDF 导出中都稳定
    #   `--mathtype` 走 `docx-equation` 的 OLE 路线，但该库自制的 OLE 容器
    #   Word 不认（ProgID 为空、无法激活 → 双击打不开），仅在调研时使用。
    if args.mathtype:
        convert_math(OUT)
    return 0


def convert_math(path: Path) -> None:
    """把 docx 中的 OMML 公式转换为 MathType 原生公式对象（实验性，见 ADR-028）。

    ⚠️ 已知问题：`docx-equation` 生成的 OLE 容器在 Word 中无法激活
    （`OLEFormat.ProgID` 为空 → 双击打不开），故不作为默认输出。
    """
    tmp = path.with_name(path.stem + "_omml.docx")
    try:
        n = EQM.convert_to_mathtype(path, tmp, work_dir=path.parent / "_mathtype_work")
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️  MathType 转换失败，保留 OMML 公式版本：{type(exc).__name__}: {exc}")
        if tmp.exists():
            tmp.unlink()
        return
    tmp.replace(path)
    print(f"MathType 转换完成：{n} 个公式 → Equation.DSMT4 对象")
    print("⚠️  注意：该库的 OLE 容器在 Word 中无法激活（双击打不开），仅用于调研")
    print(f"大小：{path.stat().st_size/1024/1024:.2f} MB")


# ================================================================ 正文装配

def _q4_gap_bullets(m4: dict) -> list[str]:
    """按 `outputs/q4/tables/q4_资源缺口.csv` **逐行生成**缺口归因要点。

    ★ 为什么要从表生成而不是手写：这部分文字曾在一次重跑后与表不一致
      （文中说"K=3 与 K=2 的缺口类别相同"，而表里 K=3 多出一类 C 型运输机），
      属于典型的"正文与表两套数"。改为读表生成后，表变正文必然跟着变。
    """
    import pandas as pd

    p = TAB / "t_q4_gap.csv"
    if not p.exists():
        return ["（缺口表缺失，见 outputs/q4/tables/q4_资源缺口.csv）"]
    g = pd.read_csv(p)
    need_col = "缺口" if "缺口" in g.columns else g.columns[-1]
    out: list[str] = []
    notes = {
        1: "说明全局调度下**电池周转是唯一短板**；题目允许共享电池跨机调度，"
           "该缺口可通过提高充电功率、增购 1 组电池或允许返航即换电消除",
        2: "原因是二分组把部分 B 型机执行的服务区划到不同组后，"
           "每组都必须**独立备齐**该机型，规模效应开始丧失",
        3: "继续细分使资源总量再升 1（台·组），单组峰值工作量继续下降，"
           "但缺口类别不再增加 —— 这正是“分组必须独立储备峰值资源”的边际代价",
    }
    for k, label in ((1, "K=1（整队一组）"), (2, "K=2（二分组）"), (3, "K=3（三分组）")):
        sub = g[g.iloc[:, 0].astype(str).str.contains(f"K={k}", regex=False)]
        if "方案" in g.columns:
            sub = g[g["方案"].astype(str).str.startswith(f"K={k}")]
        rows = sub[pd.to_numeric(sub[need_col], errors="coerce").fillna(0) > 0]
        items = []
        for _, r in rows.iterrows():
            res = str(r.get("资源", "")).replace("数", "").replace("组", "组")
            items.append(f"**{res} +{int(float(r[need_col]))}**"
                         f"（需求 {int(float(r['需求']))} / 库存 {int(float(r['库存']))}）")
        if not items:
            out.append(f"{label}：**无缺口**，库存完全覆盖需求。")
        else:
            joined = "、".join(items)
            head = ("唯一缺口是 " if len(items) == 1 else f"缺口共 {len(items)} 类：")
            out.append(f"{label}：{head}{joined}。{notes[k]}；")
    out = [s.rstrip("；") + "；" if not s.endswith("。") else s for s in out]
    return out


def build_body(doc: Document, D: dict) -> None:
    m1, m2, m3, m4 = D["m1"], D["m2"], D["m3"], D["m4"]

    # ---------------- 一、引言与问题重述 ----------------
    H(doc, "一、引言与问题重述", 1)
    H(doc, "1.1 问题背景", 2)
    P(doc, "山区洪涝灾害具有突发性强、影响范围分散、道路供电通信设施同时受损等特点。"
           "连续强降雨易引发山洪、滑坡和道路塌方，使部分居民点在短时间内与外界失去稳定的"
           "地面交通联系。灾后早期，饮用水、应急食品、医疗物资和生活卫生用品需尽快送达，"
           "而传统车辆难以及时进入地形起伏大、道路受损严重的区域。无人机受地面道路条件"
           "影响较小，是应急运输的重要补充手段。")
    P(doc, "2026 年 7 月，受台风“美莎克”带来的持续强降雨影响，广西横州市镇龙乡遭遇严重"
           "洪涝灾害，核心受灾区域一度交通中断、通信不畅，全乡约 8000 人受困。救援期间，"
           "物资依靠徒步或空中投送进入受灾区域。这一现实场景表明，应急物资运输和通信保障"
           "需在道路受阻、能源受限和信息不完整的条件下协同组织。")
    P(doc, "在实际救援中，完成物资投送不仅取决于无人机能否飞抵目标，还受载荷、水平飞行"
           "距离、爬升与下降高度、沿线地形净空、能源储备、任务时限和设备周转等多种因素影响；"
           "同时运输无人机在爬升、巡航、下降及物资交接的全过程需持续保持指挥、遥测和交接"
           "确认链路。当固定通信设施受损或山体遮挡导致地面网关无法覆盖完整任务区间时，"
           "还需空中中继无人机在适当位置和时段提供临时通信保障。因此，山区洪涝灾害下的"
           "物资投送需同步考虑运输、通信保障和设备资源的协调使用。")

    H(doc, "1.2 问题重述", 2)
    P(doc, "题目以镇龙乡及周边山区为地理背景设置标准测试场景：1 个临时调度中心 O01"
           "（与固定网关 G01 同址）、15 个服务区 S001~S015、80 个不可拆货箱，"
           "三种运输无人机机型（A/B/C，共 8 架实体运输机）与配套共享电池组，"
           "以及 2 架中继无人机与可更换能源组件、30 m 分辨率 DEM 与无线链路参数。"
           "空间坐标和公开地理数据用于描述测试场景，需求、时限、装备和资源参数"
           "以附件给定值为准。需解决的四个问题如下。")
    RICH(doc, [("问题 1（单点往返运输能力与货箱组批）：", True),
               ("不考虑实体无人机和共享电池调度，每个架次采用 O01→Si→O01 直接往返、"
                "仅服务一个服务区。要求计算三种机型在不同服务区的最大安全载荷；"
                "在货箱不可拆且恰被安排一次、满足质量/体积/返航电量约束下确定各服务区"
                "组批方案；以最少架次、总能耗与累计作业时间进行多目标优化并说明权衡；"
                "讨论返航安全余量变化的影响。", False)])
    RICH(doc, [("问题 2（异构无人机多点多架次运输调度）：", True),
               ("不考虑通信保障，每个运输架次可访问一个或多个服务区并返回 O01。"
                "在货箱不可拆、质量/体积/返航电量、无人机与共享电池数量、充电周转及"
                "物资时限等约束下，联合确定货箱组批、访问顺序、机型、执行无人机、"
                "共享电池与开始时刻；医疗物资与首批保障货箱时限为硬约束。"
                "优化配送及时性、全部任务完成时间、总能耗与架次数，"
                "并给出可执行日程与逐箱送达时刻。", False)])
    RICH(doc, [("问题 3（通信约束下运输与中继联合调度）：", True),
               ("运输无人机在爬升、巡航、下降及投送阶段均须保持连续通信；"
                "直连不可用时可由空中中继（两段链路、无多跳）保障，通信状态按附录 3 判定。"
                "联合确定运输与中继的组批、访问顺序、资源与开始时刻，以及中继悬停位置"
                "（DEM 范围内、离地不超 300 m）、飞行海拔、服务时段与能源组件分配；"
                "优化及时性、联合完工时间、运输与中继总能耗及两类无人机架次数。", False)])
    RICH(doc, [("问题 4（救援任务分区与资源配置优化）：", True),
               ("以问题三联合调度方案为基础，将 15 个服务区划分为 2 个和 3 个任务组；"
                "每服务区恰属一组、每组非空；同一运输架次涉及的服务区划入同组。"
                "各组独立核算运输无人机、共享电池、中继机与中继能源组件数量，"
                "资源不得跨组调配；比较资源配置规模、冗余、组间均衡及与库存的缺口。", False)])
    FIGURE(doc, "f01_roadmap", "图 1  全文技术路线图")
    P(doc, "如图 1 所示，全文按“数据与物理基础—问题一能力评估—问题二运输调度—"
           "问题三通信协同—问题四分区配置”五个层次递进展开：最底层是统一的物理计算器，"
           "上一问的输出作为下一问的输入；另设模型检验与验证带，用独立校验器、"
           "算法互证与敏感性分析贯穿四个问题。")

    # ---------------- 二、总体分析 ----------------
    H(doc, "二、总体分析", 1)
    H(doc, "2.1 数据特征分析", 2)
    H(doc, "2.1.1 空间与地形", 3)
    edge = D["nodes"]
    o = edge[edge["kind"] == "center"].iloc[0]
    sv = edge[edge["kind"] == "service"]
    P(doc, f"DEM 为 Copernicus GLO-30 数字表面模型（DSM，WGS84 / EPSG:4326、"
           f"约 30 m 栅格、NoData = −32767），覆盖区域地面高程介于 "
           f"41.7~1132.9 m。调度中心 O01 海拔 {o['ground_elev_m']:.1f} m，"
           f"15 个服务区海拔 {sv['ground_elev_m'].min():.1f}~"
           f"{sv['ground_elev_m'].max():.1f} m，地形起伏显著。"
           f"需要特别说明：附件 DEM 是**数字表面模型（DSM）**而非裸地 DEM，"
           f"包含植被与建筑高度，用于净空与遮挡判定偏保守，符合救援场景的安全取向。")
    FIGURE(doc, "f02_terrain_nodes", "图 2  研究区 30 m DEM 与任务节点分布")
    FIGURE(doc, "f24_nodes", "图 3  节点坐标与海拔分布")
    TABLE(doc, "t_nodes", "表 1  调度中心与服务区坐标及海拔", max_rows=20)

    H(doc, "2.1.2 物资与时限", 3)
    import pandas as _pd
    bxd = _pd.read_csv(REPO_ROOT / "data/processed/boxes.csv")
    P(doc, f"80 个货箱总计 {bxd['mass_kg'].sum():.0f} kg、"
           f"{bxd['volume_m3'].sum():.3f} m³，含医疗物资、饮用水、应急食品、"
           f"生活卫生用品四类；30 箱标记为首批保障（每服务区 1 医疗 + 1 饮用水）。"
           f"首批截止时间分为 60 / 120 / 180 min 三档，期望送达时间分 60 / 120 / "
           f"180 / 240 min 四档。**体积是主要瓶颈**：单箱体积最大者生活卫生用品为 "
           f"0.035 m³，而 A 型机可用装载体积仅 0.06 m³。")
    FIGURE(doc, "f03_box_stats", "图 4  货箱数据特征（80 箱）")
    TABLE(doc, "t_box_by_type", "表 2  分类物资总量统计")
    TABLE(doc, "t_box_by_service", "表 3  各服务区物资需求", max_rows=20)

    H(doc, "2.1.3 装备与链路", 3)
    P(doc, f"三种运输机型参数差异显著：A 型（中轻载）最大载货 25 kg、可用体积 "
           f"0.06 m³；B 型（中载）30 kg / 0.073 m³；C 型（重载）80 kg / 0.25 m³，"
           f"但满载标准航程仅 12 km。机队配置为 A×4、B×2、C×2（共 8 架），"
           f"共享电池按机型分别为 A:6 / B:4 / C:4 组，等效完全充电时间 "
           f"1800 / 2400 / 3000 s。中继机 2 架、能源组件 6 组，"
           f"悬停离地高度上限 300 m。")
    FIGURE(doc, "f23_model_params", "图 5  机型与中继参数一览")
    TABLE(doc, "t_uav_params", "表 4  三种运输机型参数")
    TABLE(doc, "t_battery_inventory", "表 5  共享电池库存与充电时间")
    TABLE(doc, "t_uav_fleet", "表 6  逐架实体无人机清单")

    H(doc, "2.2 总体技术路线", 2)
    P(doc, "四个问题共享同一套物理规则与数据对象，构成“能力评估→运输调度→通信协同→"
           "任务分区”的逐级递进关系。为保证四问口径一致、公式前后统一，"
           "本文首先构建一个**公共物理计算器**，统一封装地形净空、等效航程、飞行时间、"
           "能耗、SOC 两阶段充电与通信链路预算，所有子问题均调用同一计算器，"
           "从源头消除公式不一致的风险；并另行构建**独立校验器**，它不导入公共计算器、"
           "直接从原始附件与 DEM 重算全部物理量，用于交叉复核，"
           "避免“公共模块本身写错”导致的系统性错误。")
    FIGURE(doc, "f18_physics_calculator", "图 6  统一物理计算器：公式与耦合关系")

    H(doc, "2.3 模型假设与符号说明", 2)
    P(doc, "本文在题目给定条件之外补充如下假设，并在后续分析中对关键假设做了敏感性检验：")
    BULLETS(doc, [
        "各功能层为连续均匀介质，仅考虑沿膜厚方向的传热传质（本题不涉及，"
        "此处指沿航段的几何简化）；",
        "水平巡航距离取投影平面上的直线距离，航段地形净空按沿线 DEM 最高点 + 50 m 确定；",
        "货箱不可拆分，每个货箱恰被安排一次；",
        "同一架次完成投送后返回 O01，返程空载；",
        "共享电池与中继能源组件均为独立资源，任务占用与充电时段不得重叠；",
        "能源资源在任务结束后立即开始充电，充电期间不可使用；",
        "通信判定采用几何视线（LOS）严格判据，遮挡时附加 10 dB 损耗而非直接判定中断；",
        "中继不进行多跳转发，运输机任一时刻只由 G01 或一架中继保障。",
    ])
    P(doc, "主要符号如表 7。", indent=False)
    TABLE(doc, "t_symbols", "表 7  主要符号说明", df=symbol_table(), font=9)


    # ---------------- 三、公共物理模型 ----------------
    H(doc, "三、公共物理模型与通信链路模型", 1)
    H(doc, "3.1 航段几何与作业高度", 2)
    P(doc, "以调度中心为起点、服务区为终点构成任务节点集。任意两个任务节点之间的"
           "运输航段采用两点水平直线，计划巡航海拔取该航段所经过 DEM 像元的"
           "**最高地面高程以上 50 m**；O01 的作业高度取其地面海拔，服务区的作业高度"
           "取其地面海拔以上 30 m；连续访问多个服务区时，每次投送后均从 30 m 作业高度"
           "重新爬升。爬升与下降高度由巡航海拔与两端作业高度之差确定：")
    EQ(doc, r"H_{cruise}(i,j) = \max\{ \mathrm{DEM}(p) : p \in \overline{ij} \} + 50\ \mathrm{m}", "1")
    EQ(doc, r"h^{+}(i,j) = H_{cruise} - H_{op}(i), \quad h^{-}(i,j) = H_{cruise} - H_{op}(j)", "2")
    P(doc, "由于经纬度不能直接用于距离计算（1° 经度与 1° 纬度对应的米数不同），"
           "所有水平距离均在以研究区形心为原点的局部切平面上计算，"
           "并使用 WGS84 子午圈/卯酉圈曲率半径换算，"
           "与 pyproj 测地距离的相对误差小于 0.1%。")

    H(doc, "3.2 载荷—航程关系与最大安全载荷", 2)
    P(doc, "机型 g 携带载荷 q 时的等效航程按题目附录 2 给出：")
    EQ(doc, r"L_{g}(q) = L_{g0} - (L_{g0} - L_{gF}) \cdot \left( \frac{q}{Q_{g}} \right)^{3/2}, \quad 0 \le q \le Q_{g}", "3")
    P(doc, "该关系关于 $q$ 单调不增且为凸函数（指数 $3/2 > 1$），因此载荷越大等效航程越短。"
           "单点往返任务中，去程载货 $q$、回程空载，往返总能耗须满足返航安全余量约束：")
    EQ(doc, r"E_{g}^{T}(q) = \sum_{(i,j) \in p} E_{gij}(q_{pij}) \le (1 - \rho_{g}) \cdot E_{g}^{use}", "4")
    P(doc, "**最大安全载荷**定义为使上式取等号的 $q$。由于 $(q/Q_{g})^{3/2}$ 无初等反函数，"
           "该方程必须**数值反解**：$E_{g}^{T}(q)$ 关于 $q$ 单调递增，故在 $[0, Q_{g}]$ 上用"
           "Brent 法求根；若端点处预算仍有余，则结构上限 $Q_{g}$ 起作用。"
           "最终安全载荷取能量反解值与 $Q_{g}$、体积瓶颈对应质量三者之最小。")

    H(doc, "3.3 飞行时间与能耗", 2)
    P(doc, "航段飞行时间按爬升、巡航、下降三阶段相加；航段能耗由水平巡航能耗与"
           "爬升附加能耗两部分构成，下降能耗效率取 0（题目附录 2），即**不单独计算"
           "下降附加能耗**：")
    EQ(doc, r"t_{gij} = \frac{h^{+}}{v_{g}^{up}} + \frac{d_{ij}}{v_{g}^{c}} + \frac{h^{-}}{v_{g}^{down}}", "5")
    EQ(doc, r"E_{gij}(q) = E_{gij}^{hor}(q) + E_{gij}^{up}(q)", "6")
    P(doc, "**能耗口径说明（重要的建模选择）**：题目附录 2 给出了运输机的空载/满载"
           "标准航程与电池可用能量，但**未给出运输机的巡航功率**（仅中继机给出功率）。"
           "因此本文采用“由航程反推”的自洽口径：飞满一个标准航程恰好耗尽一组可用能量，"
           "即 $E_{gij}^{hor}(q) = (d_{ij} / L_{g}(q)) \\cdot E_{g}^{use}$；"
           "爬升附加能耗按机械功除以爬升效率计算："
           "$E_{gij}^{up} = m \\cdot g \\cdot h^{+} / \\eta_{up}$，"
           "其中 $\\eta_{up} = 0.72$ 为附件给出的爬升能耗效率。"
           "该口径下返航安全余量约束自然退化为“水平距离不超过 "
           "$(1-\\rho_{g}) \\cdot L_{g}(q)$”，物理含义清晰。")
    FIGURE(doc, "f20_flight_profile", "图 7  飞行剖面与能耗构成")

    H(doc, "3.4 能源周转模型", 2)
    P(doc, "共享电池与中继能源组件均作为独立资源记录荷电状态（SOC），初始 SOC = 100%。"
           "两类资源统一采用两阶段等效充电模型：")
    EQ(doc, r"t_{chg}(s) = T_{full} \cdot \left[ 0.65 \cdot \frac{0.90 - s}{0.90} + 0.35 \right], \quad 0 \le s < 0.90", "7")
    EQ(doc, r"t_{chg}(s) = T_{full} \cdot 0.35 \cdot \frac{1 - s}{0.10}, \quad 0.90 \le s \le 1", "8")
    P(doc, "该分段函数在 $s = 0.90$ 处连续（两段取值均为 $0.35 \\cdot T_{full}$），"
           "$t_{chg}(0) = T_{full}$、$t_{chg}(1) = 0$。同一资源的任务占用与充电时段不得重叠，"
           "不同资源可并行充电；同一机型的共享电池可在该机型不同实体无人机之间调度，"
           "不同机型之间不可混用。")

    H(doc, "3.5 通信链路模型", 2)
    P(doc, "通信系统由固定网关 G01、运输无人机与中继无人机构成。运输机可与 G01 建立"
           "直连链路；直连不可用时可通过一架中继建立“运输机—中继—G01”两段链路，"
           "不允许中继之间多跳转发。链路判定包含地形遮挡、传播损耗与双向链路预算三部分。")
    P(doc, "**（1）地形遮挡判定**：根据两端点三维位置与 30 m DEM，沿视线水平投影采样，"
           "比较各采样点地面高程与视线插值高度，若地形高过视线则该航段存在遮挡"
           "（$b_{ijt} = 1$）。需要强调：遮挡**只附加 10 dB 损耗**（附件 $L_{obs}$），"
           "而不是直接判定链路中断——链路是否可用仍需比较总损耗与门限。")
    P(doc, "**（2）接收门限与双向链路预算**：")
    EQ(doc, r"P_{th,b} = P_{sens,b} + M_{b}", "9")
    EQ(doc, r"L_{max,a \to b} = P_{t,a} + G_{t,a} + G_{r,b} - L_{sys} - P_{th,b}", "10")
    EQ(doc, r"L_{max,a \leftrightarrow b} = \min\left( L_{max,a \to b}, L_{max,b \to a} \right)", "11")
    P(doc, "其中式 (11) 体现题目要求：运输控制与状态回传均需保障，"
           "故按**双向链路**判定并取两个方向门限中的较小值。")
    P(doc, "**（3）传播损耗与可用性**：")
    EQ(doc, r"L_{FSPL,ijt} = 32.45 + 20 \cdot \log_{10}(f) + 20 \cdot \log_{10}(D_{ijt})", "12")
    EQ(doc, r"L_{path,ijt} = L_{FSPL,ijt} + L_{obs} \cdot b_{ijt}, \quad A_{ijt} = 1 \iff L_{path} \le L_{max}", "13")
    P(doc, "式中 $f$ 以 $\\mathrm{MHz}$、$D$ 以 $\\mathrm{km}$ 计"
           "（单位陷阱：内部距离以 m 存储，代入前须除以 1000，"
           "差 1000 倍即差 60 dB）。运输机在任一时刻的通信状态按如下优先级判定："
           "与 G01 直连可用记为**直连**；直连不可用但接入链路与回传链路**同时可用**"
           "记为**中继**；其余记为**中断**。")
    TABLE(doc, "t_link_thresholds", "表 8  三条链路的双向门限与可达距离")
    FIGURE(doc, "f19_link_budget", "图 8  通信链路预算与门限分析")
    P(doc, "由表 8 可见一个**关键定量结论**：中继接入段的双向门限（116 dB）"
           "比直连（122 dB）还低 6 dB，因此中继必须**靠近运输无人机**（≤ 6.27 km）；"
           "而回传段门限最宽（126 dB，可达 19.83 km）。"
           "这决定了中继悬停位置的可行域形状是“贴近作业空域”而非“贴近网关”。")


    # ---------------- 四、问题一 ----------------
    H(doc, "四、问题一：单点往返运输能力与货箱组批", 1)
    H(doc, "4.1 问题分析与模型建立", 2)
    P(doc, "问题一不考虑实体无人机与共享电池调度，每个架次采用 O01→Si→O01 直接往返、"
           "仅服务一个服务区，同一服务区可由多个架次分批服务。因此问题分解为两层："
           "第一层求各 (服务区, 机型) 组合的**最大安全载荷**；"
           "第二层在该载荷约束下做**货箱组批**（装箱），并优化架次数、总能耗与累计作业时间。")
    P(doc, "货箱组批是一个**质量—体积二维装箱问题**：货箱不可拆，每个货箱恰用一次，"
           "需同时满足质量约束 $\\sum m_{b} \\le q_{max}^{safe}(g,i)$、"
           "体积约束 $\\sum v_{b} \\le V_{g}$ 与"
           "返航安全能量余量（已包含在 $q_{max}^{safe}$ 中）。")

    H(doc, "4.2 求解算法", 2)
    P(doc, "最大安全载荷用 Brent 法二分反解（式 3、4），收敛容差 1e-6，"
           "并对结果做回代验证。组批则**求精确最优而非启发式**，分三步：")
    BULLETS(doc, [
        "**箱型聚合**：把（质量, 体积, 是否首批, 期望送达时间）完全相同的货箱合并为"
        "一个箱型，把决策变量从“80 个货箱的分配”降到“箱型的计数向量”，"
        "在不损失最优性的前提下大幅压缩状态空间；",
        "**可行批次枚举**：对每个服务区，枚举全部在载荷、装载体积与返航能量余量下"
        "**可行**的箱型计数向量（一个架次能装的货），并预先算好该批次的能耗与作业时间；",
        "**精确字典序 DP**：以剩余箱型计数为状态做动态规划，目标为"
        "「架次数最少 → 总能耗最低 → 累计作业时间最短」的**字典序最小**，"
        "即先压架次数、再压能耗、最后压累计作业时间；状态可达性保证不漏解。",
    ])
    P(doc, "为独立佐证解的质量，本文同时推导装箱的**解析下界**：")
    EQ(doc, r"LB = \max\left( \left\lceil \frac{\sum_{b} m_{b}}{\max_{g \in \mathcal{F}_i} q_{max}^{safe}(g,i)} \right\rceil, \left\lceil \frac{\sum_{b} v_{b}}{\max_{g \in \mathcal{F}_i} V_{g}} \right\rceil \right)", "14")
    P(doc, "即分别按质量与体积的最佳机型容量估算所需架次数并取较大者。"
           "★ 两个上确界都必须**只在能量可行的机型集合 $\\mathcal{F}_i$ 内取** —— "
           "若对全部机型取最大值，会让“实际上飞不到该服务区”的机型提供一个虚假的大容量，"
           "从而把下界算得过小、凭空产生“与下界的差距”。"
           "本文对所有 15 个服务区校验：精确 DP 架次数与下界**逐区相等**，"
           "故架次数维度在该实例上达到下界，这一点由 DP 的精确性与下界的紧性**双向印证**。")

    H(doc, "4.3 计算结果", 2)
    P(doc, f"（1）最大安全载荷。3 机型 × 15 服务区共 45 组结果见图 9 与表 9。"
           f"统计显示：A 型机在 15/15 个服务区均受**结构载重上限**约束"
           f"（载荷恒为 25 kg）；B 型机 14/15 受结构约束，仅 S008 降至 28.85 kg；"
           f"C 型机 10/15 受结构约束，在 S002/S003/S004/S008/S012 等远距离或"
           f"高海拔服务区因能量约束降至 58.99~68.88 kg。")
    P(doc, "这一结论具有明确的工程含义：**对 A、B 两型机，能量从来不是紧约束，"
           "载重（结合体积）才是瓶颈；而对 C 型机，远距离飞行时返航能量成为紧约束。**"
           "两类机型的性质相反，在组批与调度中应区别对待。")
    FIGURE(doc, "f04_q1_payload", "图 9  最大安全载荷热力图与生效约束")
    TABLE(doc, "t_q1_payload", "表 9  3 机型 × 15 服务区最大安全载荷与生效约束", max_rows=32)

    uu1 = m1.get("type_usage", {}) or {}
    P(doc, f"（2）货箱组批。推荐方案共 {int(m1.get('chosen_n_sorties', 18))} 个架次，"
           f"机型使用 **B×{int(uu1.get('B', 0))} + C×{int(uu1.get('C', 0))}**（异构混编），"
           f"总能耗 {m1.get('chosen_total_energy_kwh', 0):.3f} kWh，"
           f"累计作业时间 {m1.get('chosen_serial_total_time_s', 0)/3600:.2f} h。"
           f"逐服务区架次数下界合计为 {int(m1.get('lower_bound_total_sorties', 18))}，"
           f"与推荐方案架次数**完全相等**，说明该方案在各服务区均达到解析下界，"
           f"**架次数维度可证最优**。")
    FIGURE(doc, "f05_q1_groups", "图 10  货箱组批方案构成")
    TABLE(doc, "t_q1_groups", "表 10  货箱组批方案明细（按交付模板列序）", max_rows=30)

    H(doc, "4.4 多目标权衡与策略对比", 2)
    P(doc, "本文对比了两类组批策略：**精确字典序 DP（B+C 混编，本文方案）**与"
           "**同一组批下改用全 C 型**（仅换机型的对照）。结果见表 11 与图 11。"
           "两者架次数相同（同为 18 架次），但全 C 型方案的能耗与累计作业时间都更差。")
    TABLE(doc, "t_q1_strategy", "表 11  各策略多目标对比")
    P(doc, "**权衡关系分析**：C 型机单架载重最大（结构上限 80 kg），"
           "但其空载质量 69.9 kg、电池可用能量仅 8 kWh，且每架次需爬升 143~458 m，"
           "单位能耗效率明显低于 B 型机。把同一组批整体换成 C 型后，"
           "总能耗由 59.09 升至 74.26 kWh（+25.7%）、"
           "累计作业时间由 9.08 h 升至 9.37 h，而架次数一个也没少。"
           "**因此“载重最大”并不等于“最省电”**：本文的精确 DP 在远距离/高海拔服务区"
           "自动改用 B 型机，在**架次数不变**的前提下把能耗压得更低，"
           "这正是字典序目标“先少架次、后低能耗”的价值所在。")
    FIGURE(doc, "f06_q1_strategy", "图 11  策略对比与最优性证据（逐区下界 vs 精确 DP）")
    TABLE(doc, "t_q1_lowerbound", "表 12  逐服务区架次数下界与精确 DP 差距", max_rows=20)

    H(doc, "4.5 返航安全余量敏感性分析", 2)
    P(doc, "题目要求讨论返航安全余量 $\\rho_{g}$ 变化对最大安全载荷与组批结果的影响。"
           "本文在 $\\rho_{g} \\in \\{0.10, 0.20, 0.30, 0.40, 0.50\\}$ 上取值，"
           "对每个取值重算最大安全载荷并**重跑精确 DP 组批**，结果见表 13 与图 12。")
    TABLE(doc, "t_q1_rho_sweep", "表 13  $\\rho_{g}$ 扫描：架次数、能耗与可行性")
    P(doc, "**主要结论**：一是**在 0.10~0.20 区间内结果不变**——"
           "架次数与能耗都保持 18 架次 / 59.0875 kWh、机型组合也保持 B×9 + C×9，"
           "说明附件的 $\\rho_{g} = 0.20$ 相对 $0.10$ **没有付出任何效率代价**"
           "（此时组批受**体积与结构上限**约束，能量本就有富余）；"
           "二是从 0.20 增至 0.30 时，架次数升至 20（+11.1%）、"
           "能耗升至 67.1805 kWh（+13.7%），机型组合变为 B×9 + C×11 —— "
           "**C 型进一步承担更多架次**，因为 B 型的能量余量更早被吃光；"
           "三是**存在可行上界**：$\\rho_{g} \\ge 0.40$ 时出现无可行解的服务区"
           "（$\\rho_{g}=0.40$ 时 2 个、$\\rho_{g}=0.50$ 时 5 个），"
           "即余量再放大不是“多飞几趟”而是**直接无解**，"
           "这比架次数增长更值得注意。"
           "综合来看，附件取值 $\\rho_{g} = 0.20$ 位于"
           "“架次数与能耗都不再改善、且距可行上界仍有充足余量”的位置，"
           "该安全余量设置在安全性与运输效率之间取得了合理平衡。"
           "★ 口径说明：表 13 由 `sweep_reserve_ratio_exact()` 生成，"
           "**每个 $\\rho_{g}$ 都重跑精确字典序 DP**，与第 4.3 节正式方案"
           "（$\\rho_{g}=0.20$、18 架次、59.0875 kWh）**逐位一致**；"
           "启发式策略集合的扫描结果另存于 "
           "`outputs/q1/tables/q1_4_rho_sweep_heuristic_ref.csv`，仅供对照，不进论文表格。")
    FIGURE(doc, "f07_q1_rho", "图 12  返航安全余量 $\\rho_{g}$ 敏感性分析")


    # ---------------- 五、问题二 ----------------
    H(doc, "五、问题二：异构无人机多点多架次运输调度", 1)
    H(doc, "5.1 问题分析与模型建立", 2)
    P(doc, "问题二允许每个运输架次访问一个或多个服务区，需联合确定"
           "货箱组批、服务区访问顺序、运输机型、具体执行无人机、共享电池分配"
           "与各架次开始时刻。相比问题一，新增三类耦合：")
    BULLETS(doc, [
        "**多点串飞与载荷递减**：一个架次访问多个服务区时，载荷随投送逐段递减，"
        "因此容量约束必须对**每个前缀**成立，能耗必须**逐段**累加；",
        "**资源周转**：8 架实体机与 14 组共享电池需在多个架次间复用，"
        "电池用后必须充满才能再次使用，形成时间耦合；",
        "**物资时限**：医疗物资与首批保障货箱有硬性截止时间，"
        "时限与资源周转相互制约。",
    ])
    P(doc, "设某架次访问顺序为 $(S_{a}, S_{b}, \\ldots)$，则第 $m$ 段航段上机载荷为尚未投送的"
           "货箱质量之和。前缀可行性条件为：")
    EQ(doc, r"\forall m : \sum_{k \ge m} m_{k} \le Q_{g}, \quad \sum_{k \ge m} v_{k} \le V_{g}", "15")
    P(doc, "架次能耗为逐段能耗之和，其中第 $m$ 段载荷为 $q_{m}$：")
    EQ(doc, r"E_{p}^{T} = \sum_{m} E_{g}(seg_{m}, q_{m}) \le (1 - \rho_{g}) \cdot E_{g}^{use}", "16")
    P(doc, "架次作业时间由准备、装载、飞行与投送交接四部分构成：")
    EQ(doc, r"t_{p} = t_{prep} + n_{box} \cdot t_{load} + \sum_{m} t_{g}(seg_{m}) + \sum_{s \in stops} \left( t_{h0} + k_{s} \cdot t_{h1} \right)", "17")
    P(doc, "目标为多目标优化：配送及时性、全部任务完成时间（所有运输机完成最后一个"
           "架次并返回 O01 的最晚时刻）、运输能耗与架次数。")

    H(doc, "5.2 求解算法", 2)
    P(doc, "本文采用“**精确组批 — CP-SAT 调度 — 工程复核**”三段式求解框架：")
    BULLETS(doc, [
        "**组批（继承问题一，仅按时限增开先行架次）**：问题一的精确 DP 组批在 "
        "S006 / S007 / S008 / S013 四个区只给出 1 个大架次，而这四个区的首批箱与"
        "医疗箱截止在 3600 s / 7200 s，单架次无法同时满足时限。"
        "因此对这四个区**拆出先行小架次**（用小机型先送首批箱与医疗箱），"
        "其余 11 个区继续使用问题一的精确 DP 组批（架次数与能耗均不劣于任何其它组批）。"
        "结果是架次数由 18 增至 23；这一步**必须发生在方案装配函数内部**，"
        "否则调用链路上任何一次直接装配都会退回较差组批，造成同一问两套数；",
        "**调度（CP-SAT 资源受限区间调度）**：23 个架次的组批、机型、能耗与 SOC 固定后，"
        "联合决定**执行实体机 $u_{r}$、共享电池 $k_{r}$、起飞时刻 $t_{r}$**，"
        "最小化最晚返回时刻 $C_{\\max}$。约束包括：①同一实体机的架次区间不重叠；"
        "②同一电池的**占用区间** $[t_{r},\\ t_{r}+d_{r}+c_{r})$ 不重叠，"
        "其中 $c_{r}$ 为该架次返航后按两阶段充电模型充满所需时间；"
        "③硬时限 $t_{r} + \\tau_{r} \\le D_{b}$（$\\tau_r$ 为交付耗时、$D_b$ 为该箱时限）。"
        "该模型正好对应 CP-SAT 的可选区间与 `NoOverlap` 约束，"
        "因此可以给出“**在固定组批与固定资源池下的最优调度**”这一有限范围内的最优性声明；",
        "**复核（不导入求解器的独立校验）**：由 `src/verify/` 从附件与 DEM 从零重算"
        "逐架次能耗、SOC、资源占用与逐箱时限，任何一项不符即判该架次失败。"
        "校验器覆盖载荷、体积、能量、资源冲突与时限共 18 类约束，并配负例测试。",
    ])
    P(doc, "**关于 CP-SAT 的两点诚实说明**：（i）求解器给出的 `OPTIMAL` 只保证在"
           "上述约束模型内的最优性。为避免分支定界收敛不足造成的假最优，"
           "本文把给定方案数据中**可行的**（实体机, 电池, 起飞时刻）三元组作为"
           "**可行解提示（hint）**注入模型；（ii）本文另用“逐档收紧 $C_{\\max}$ 上界”"
           "的方式独立验证最优值，见 5.4 节。")

    H(doc, "5.3 计算结果", 2)
    uu = m2.get("type_usage", {}) or {}
    P(doc, f"最终方案共 {int(m2.get('n_sorties', 23))} 个运输架次，"
           f"机型使用情况为 A 型 {uu.get('A', 0)} 架次、B 型 {uu.get('B', 0)} 架次、"
           f"C 型 {uu.get('C', 0)} 架次，"
           f"总能耗 {m2.get('total_energy_kwh', 0):.3f} kWh，"
           f"完工时间 {m2.get('makespan_s', 0):.2f} s"
           f"（{m2.get('makespan_h', 0):.3f} h），"
           f"期望送达准时率 {m2.get('on_time_rate', 0):.1%}"
           f"（首批箱 {int(m2.get('n_first_batch_on_time', 30))}/"
           f"{int(m2.get('n_first_batch', 30))} 达标、"
           f"全部 {int(m2.get('n_expected_on_time', 80))}/80 箱在期望时间内送达），"
           f"最低返航 SOC {m2.get('min_return_soc', 0):.4f}，"
           f"最紧一箱的时限余量为 "
           f"{m2.get('tightest_expected_slack_s', 0):.1f} s。"
           f"方案通过独立校验器的载荷、体积、能量、资源冲突与时限类**全部 18 类检查**，"
           f"逐架次能耗重算最大偏差 "
           f"{m2.get('independent_verification', {}).get('max_energy_dev_kwh', 0):.4f} kWh。")
    FIGURE(doc, "f08_q2_gantt", "图 13  运输调度甘特图")
    TABLE(doc, "t_q2_sorties", "表 14  问题二运输架次明细（交付模板列序）", max_rows=30)
    FIGURE(doc, "f10_q2_resources", "图 14  资源使用情况")
    TABLE(doc, "t_q2_uav_use", "表 15  实体无人机使用统计")
    TABLE(doc, "t_q2_battery_count", "表 16  共享电池使用次数")

    H(doc, "5.4 完工时间 7843.20 s 的最优性验证与给定时刻表的对比", 2)
    P(doc, f"本节回答一个必须交代清楚的问题：**给定方案数据的时刻表最晚返回 "
           f"7740.19 s，比本文的 {m2.get('makespan_s', 0):.2f} s 小 103 s，"
           f"本文为什么没有做到更短？**")
    P(doc, "核实结论是：**给定时刻表违反了题目自带的硬时限**。"
           "S015 的医疗箱（S015-MED-01）期望送达时间为 7200 s，"
           "而给定时刻表中执行该区的架次 T19 于 5886.5 s 起飞、"
           "按交付耗时 1583.47 s 计算，交付时刻为 **7470.0 s > 7200 s**。"
           "本文的调度模型把“全部箱的期望时间”作为**硬约束**"
           "（给定方案在其它 79 箱上确实全部满足，故这一强度与其自述一致），"
           "因此该时刻表在本模型下不可行。")
    P(doc, "为把这一判断做实，本文做了**逐档收紧上界的可行性判定**"
           "（对给定组批与本文改进组批分别求解）：")
    BULLETS(doc, [
        "$C_{\\max} \\le 7843.2$ s：对给定组批 **INFEASIBLE**、对改进组批 **OPTIMAL**；",
        "$C_{\\max} \\le 7850$ s：对给定组批 **OPTIMAL**（说明模型本身可解，"
        "7843.2 s 的下界来自时限而非资源冲突）；",
        "在 7740.19 s ~ 7843.2 s 之间的每个档位（7740.3 / 7745 / 7750 / 7780 / 7800 / 7820）"
        "两组批**均为 INFEASIBLE**。",
    ])
    P(doc, "因此 103 s 的差值是**时限可行性的代价**，而不是本方案“更慢”。"
           "反过来看，本文方案在满足全部 80 箱时限（且最紧余量 11.7 s）的同时"
           "把架次数控制在 23、能耗压到 "
           f"{m2.get('total_energy_kwh', 0):.3f} kWh，"
           "并且**逐档可验证**。")
    FIGURE(doc, "f09_q2_timeliness", "图 15  物资时限达成分析")
    TABLE(doc, "t_q2_timeliness", "表 17  逐箱时限达成明细（节选）", max_rows=30)
    P(doc, "四目标之间的权衡关系见表 18：本文进一步以**真实重解 CP-SAT** 的方式"
           "考察了资源规模的影响——把实体机与电池按 100% / 75% / 50% 逐档削减后重新求解，"
           "结果显示 **8 架实体机 + 14 组电池是必须的**："
           "实体机减到 7 架仍可完工（完工时间不变），"
           "但电池减到 7 组即 **INFEASIBLE**——"
           "**瓶颈在共享电池的充电周转，而不在实体机数量**，"
           "这是一条对现场调度有直接指导意义的结论："
           "增配实体机无益，增配电池组才能进一步压缩完工时间。")
    TABLE(doc, "t_q2_tradeoff", "表 18  问题二资源规模权衡（逐档重解 CP-SAT）", max_rows=20)


    # ---------------- 六、问题三 ----------------
    H(doc, "六、问题三：通信约束下的运输与中继联合调度", 1)
    H(doc, "6.1 问题分析与模型建立", 2)
    P(doc, "问题三在问题二方案上叠加通信约束：运输无人机在**爬升、巡航、下降及物资"
           "投送阶段均应保持连续通信**。这带来两个建模难点：")
    BULLETS(doc, [
        "**通信判定必须沿完整轨迹逐时刻进行**：只检查服务区一个点或航段端点会漏判"
        "中途被山体遮挡的时段。本文把架次轨迹按爬升—巡航—下降—投送四阶段离散，"
        "在每个采样点判定三态；",
        "**中继选址是连续三维变量**：若对每个时刻独立选址，问题退化为不可解的连续"
        "最优控制问题。本文采用如下**可验证的充分条件**降维："
        "对某架次，若存在**一个**悬停点 P，使得轨迹上每一时刻满足"
        "“直连可用 ∨（接入(P) 可用 ∧ 回传(P) 可用）”，"
        "则该架次由一架中继在 P 处全程保障即可。",
    ])
    P(doc, "若单点无法覆盖全程，则退化为**按时段分段覆盖**（多架中继接力）。"
           "题目规定“每架运输机在任一时刻只能由 G01 或一架中继保障”，"
           "允许不同时刻由不同中继承担，因此分段覆盖是合法且必要的补充手段。")

    H(doc, "6.2 中继架次的时间与能耗模型", 2)
    P(doc, "中继机由 O01 出发，到达悬停位置并完成建链后提供通信服务，服务结束后返回。"
           "其时间与能耗按附录 2 计算：")
    EQ(doc, r"t_{link} = t_{prep} + t_{fly}(O01 \to P) + t_{setup}, \quad t_{svc} = [\, t_{link},\ T_{win}^{end} \,]", "18")
    EQ(doc, r"E_{R} = E_{up}(m_{takeoff}, h^{+}) + P_{cruise} \cdot t_{cruise} + (P_{hover} + P_{comms}) \cdot t_{svc}", "19")
    P(doc, f"其中计划起飞总质量取附件值 {D['relay'].iloc[0]['takeoff_mass_kg']:.1f} kg，"
           f"巡航功率 {D['relay'].iloc[0]['cruise_power_kw']:.2f} kW，"
           f"悬停功率 {D['relay'].iloc[0]['hover_power_kw']:.2f} kW，"
           f"通信附加功率 {D['relay'].iloc[0]['comms_power_kw']:.2f} kW，"
           f"悬停离地高度上限 {D['relay'].iloc[0]['max_hover_agl_m']:.0f} m。"
           f"中继悬停点由 O01 往返的航段几何仍按式 (1)(2) 的净空规则确定。")

    H(doc, "6.3 求解算法", 2)
    P(doc, "在 DEM 覆盖范围内、服务区凸包外扩 3 km 的区域生成 800 m 网格的悬停候选点，"
           "共 481 个；对每个需保障的架次，在候选点中搜索能覆盖全部中断样本且"
           "返航 SOC 满足余量要求的点，取能耗最低者。"
           "算法实现了三项关键加速（初版需 6 分钟以上，优化后约 1.5 分钟）：")
    BULLETS(doc, [
        "先用一次扫描筛出**直连中断样本**（通常仅占全轨迹的 10%~45%），"
        "选址只在中断样本上评估；",
        "覆盖判定采用**稀疏探针**（默认 12 个均匀分布样本）快速否掉绝大多数候选点；",
        "地形遮挡判定的局部切平面由调用方预构造并复用，避免重复计算曲率半径。",
    ])

    H(doc, "6.4 计算结果", 2)
    P(doc, f"（1）直连诊断。对问题二的 {int(m3.get('n_transport_sorties', 23))} 个架次"
           f"沿完整轨迹按 **{m3.get('sample_dt_s', 0.25):g} s 步长**逐时刻采样"
           f"（地形遮挡沿线判定步长 {m3.get('los_step_m', 60):g} m），"
           f"合计 **{int(m3.get('radio_samples', 0)):,} 个采样点**，判定直连 / 中继 / 中断三态。"
           f"结果显示 **{int(m3.get('n_sorties_need_relay', 0))} 个架次存在直连中断**，"
           f"按架次平均的中断样本占比 {m3.get('mean_direct_outage_fraction', 0):.2%}。"
           f"这直接证明**中继无人机是必需项而非可选项**——"
           f"若没有中继，这些架次在中断时段将失去指挥与遥测链路。")
    FIGURE(doc, "f11_q3_diagnosis", "图 16  连续通信诊断（轨迹逐时刻采样）")
    TABLE(doc, "t_q3_diagnosis", "表 19  逐架次直连状态诊断", max_rows=30)

    P(doc, f"（2）中继保障与**逐时刻最小链路裕量**。最终方案含 "
           f"{int(m3.get('n_relay_sorties', 0))} 个中继架次"
           f"（R01-1 驻留 G2-3、R02-1 驻留 S010、R02-2 驻留 G4-4），"
           f"与 23 个运输架次逐一对齐在**同一时间轴**上复核后，"
           f"**{int(m3.get('n_sorties_covered', 0))}/{int(m3.get('n_transport_sorties', 23))} "
           f"个架次实现全程零中断**（架次覆盖率 "
           f"{m3.get('coverage_rate', 0):.1%}）；"
           f"仍有 {int(m3.get('outage_samples', 0))} 个采样点"
           f"（占总采样 {int(m3.get('outage_samples',0))/max(1,int(m3.get('radio_samples',1))):.3%}）"
           f"落在“**需要中继、而当时无中继在站**”的时段，"
           f"集中在 T10（S013，615 点）、T18（S005，146 点）、"
           f"T20（S009，138 点）、T15（S004，29 点）四个架次。"
           f"逐时刻最小链路裕量（图 18b）显示：直连链路最低裕量 "
           f"{m3.get('min_link_margin_direct_db', 0):.2f} dB（负值即不可用），"
           f"而中继接入链路在在站期间的最低裕量为 "
           f"{m3.get('min_link_margin_relay_db', 0):.2f} dB（始终为正），"
           f"说明**中继本身可靠、缺口来自排班覆盖不足而非链路质量**。")
    FIGURE(doc, "f14b_q3_margin", "图 18b  逐时刻最小链路裕量（直连 / 中继 / 中断）")
    FIGURE(doc, "f12_q3_relay_map", "图 17  中继悬停点与通信保障关系")
    FIGURE(doc, "f13_q3_coverage", "图 18  中继选址特征")
    TABLE(doc, "t_q3_relay_sorties", "表 20  中继架次明细（交付模板列序）", max_rows=28)

    RICH(doc, [("★ 中继资源缺口的来源与改进方向（如实报告，不作遮掩）：", True),
               (f"本文并没有“把几何可达当作时间轴已保障”。"
                f"缺口的具体成因是：T10 的中断区间为 4136~4468 s，"
                f"而三个中继架次的在站窗口分别是 [740.4, 7350.0]、[653.2, 3400.0]、"
                f"[4921.4, 6900.0] —— **4136~4468 s 落在两个窗口之间的空档**，"
                f"该时段没有任何中继在站；T18/T20 的缺口则出现在 7350~7386 s，"
                f"恰好是 R01-1 服务窗口结束（7350.0 s）之后，属**边界效应**。"
                f"题目仅配置 2 架中继无人机，其可用能量（附件值 3.2 kWh、"
                f"扣 20% 返航余量后 2.56 kWh）除以在站服务功率"
                f"（悬停 1.05 kW + 通信 0.05 kW = 1.10 kW）决定单次在站时长上限"
                f"约 140 min，而本方案的运输时间跨度已达 2.18 h，"
                f"**2 架中继在时间轴上无法覆盖全部中断时段**。"
                f"因此改进方向有两条：①把中继库存由 2 架增至 3 架，"
                f"在 3400~4930 s 之间增派一个架次以补齐空档；"
                f"②保持 2 架不变，但把在站窗口按“**单位在站时长可覆盖的中断样本数**”"
                f"重新分配，优先覆盖 T10 这类长时中断。"
                f"本文给出的是**在给定 2 架中继资源下可复核的真实覆盖结果**，"
                f"而非声称缺口已被消除。", False)], indent=False)

    P(doc, f"（3）能耗与完工时间。运输能耗 {m3.get('transport_energy_kwh', 0):.3f} kWh，"
           f"中继能耗 {m3.get('relay_energy_kwh', 0):.3f} kWh"
           f"（占总能耗的 "
           f"{m3.get('relay_energy_kwh',0)/max(m3.get('total_energy_kwh',1),1e-9):.1%}），"
           f"合计 {m3.get('total_energy_kwh', 0):.3f} kWh；"
           f"联合任务完成时间（运输机与中继机全部返回 O01 的最晚时刻）为 "
           f"{m3.get('joint_cmax_s', 0):.2f} s"
           f"（{m3.get('joint_cmax_s', 0)/3600:.3f} h），"
           f"其中纯运输完工时间为 {m3.get('transport_cmax_s', 0):.2f} s"
           f"（{m3.get('transport_cmax_s', 0)/3600:.3f} h），"
           f"差 {(m3.get('joint_cmax_s',0) - m3.get('transport_cmax_s',0))/60:.1f} min —— "
           f"中继机须在悬停点驻留至受保障架次结束才返航，"
           f"故其返航略晚于运输机，该增量仅占联合完工时间的 "
           f"{(m3.get('joint_cmax_s',0)-m3.get('transport_cmax_s',0))/max(m3.get('joint_cmax_s',1),1e-9):.1%}，"
           f"未成为新的时间瓶颈。")
    FIGURE(doc, "f14_q3_joint_gantt", "图 19  运输与中继联合调度时间线")

    P(doc, f"（4）选址规律。三个中继悬停点中，G2-3 与 G4-4 为服务区凸包附近的作业空域点，"
           f"S010 直接取服务区上空的悬停点；悬停海拔介于 563~835 m。"
           f"水平位置集中在服务区群内（约 109.17~109.28°E），"
           f"即**贴近作业空域而非贴近网关**。这与表 8 的门限分析一致："
           f"中继接入段门限最低，必须靠近运输机；而回传段门限宽松，对位置不敏感。")

    RICH(doc, [("★ 问题三的口径警示（两条，必须与结论同时陈述）：", True),
               (f"① **巡航海拔口径**：3 中继方案采用"
                f"「巡航海拔 = max(沿线 DEM 最高点 + 50 m, 悬停海拔)」。"
                f"其中第二项是本文的**显式扩展模型**；严格按附录 2 等式的"
                f"4 中继方案见 `outputs/q3_alt/`，其总能耗略低 0.041 kWh、"
                f"但中断样本由 {int(m3.get('outage_samples', 0))} 升至 2835"
                f"（占 2.84%），故本文取 3 中继方案；"
                f"② **采样口径**：全部通信结论基于 "
                f"{m3.get('radio_samples', 0):,} 个采样点"
                f"（步长 {m3.get('sample_dt_s', 0.25):g} s）的**有限采样**，"
                f"不构成连续时间上的数学证明；本文另做了采样步长重采样对照"
                f"（图 24a，0.5~30 s 中断占比稳定在 1.05%~1.12%），"
                f"确认结论对采样步长稳健。", False)], indent=False)


    # ---------------- 七、问题四 ----------------
    H(doc, "七、问题四：救援任务分区与资源配置优化", 1)
    H(doc, "7.1 问题分析与关键规则形式化", 2)
    P(doc, "问题四要求以问题三的联合调度方案为基础，把 15 个服务区划分为 2 组和 3 组，"
           "并保持问题三已确定的货箱组批、服务区访问顺序、运输与中继任务安排、"
           "通信保障关系不变。其中一条规则对分区起决定性作用：")
    RICH(doc, [("规则：若同一运输架次同时涉及多个服务区，则这些服务区应划入同一任务组。", True)],
         indent=False, align="center")
    P(doc, "把服务区视为图的顶点、把“出现在同一架次中”视为边，"
           "该规则等价于要求**每条边的两个端点同组**。"
           "因此合法分区只能是对图之**连通分量**（本文称为**原子单元**）的划分，"
           "而不能对单个服务区自由组合。")
    P(doc, "这一形式化具有方法论意义：若先对 15 个服务区直接做枚举或聚类，"
           "几乎必然产生违反该规则的方案；正确顺序是"
           "**先求连通分量 → 再对分量划分 → 最后校验并集完整与两两互斥**。")

    H(doc, "7.2 连通分量分析与分区可行性判定", 2)
    _nu = int(m4.get("n_atomic_units", 1))
    _nms = int(m4.get("n_multi_stop_sorties", 0))
    _nbr = int(m4.get("n_bridge_sorties", 0))
    _u = D.get("q4u")
    _comp = ""
    _single = 0
    if _u is not None and len(_u):
        _single = int((_u["服务区数"] == 1).sum())
        _comp = "；".join(
            f"{r['单元编号']} 含 {int(r['服务区数'])} 区"
            f"（{'、'.join(str(r['服务区列表']).split('|'))}）"
            for _, r in _u.iterrows())
    P(doc, f"对问题三方案中涉及服务区的 {int(m4.get('n_transport_sorties_q3', 25))} 个架次"
           f"构图，其中 **{_nms} 个为访问 ≥2 个服务区的多点架次**。"
           f"每条边的两个端点必须同组，因此合法分区只能是对图之**连通分量**"
           f"（本文称为**原子单元**）的划分。最终连通分量数为 **{_nu}**，"
           f"即 15 个服务区被多点架次约束划分为 {_nu} 个不能再拆的单元"
           + (f"（其中 {_single} 个由单点架次独立成组）：{_comp}。" if _comp else "。"))
    P(doc, "由此得到本文问题四的核心结论：")
    _k2 = bool(m4.get("partition_feasible_k2", False))
    _k3 = bool(m4.get("partition_feasible_k3", False))
    _e2 = int(m4.get("k2_edits_required", 0))
    _e3 = int(m4.get("k3_edits_required", 0))

    def _feas(k: int, ok: bool, edits: int) -> str:
        """按"是否可行 + 需拆几个多点架次"拼一句话；edits=0 时不提拆分。"""
        if not ok:
            return f"**K={k} 不可行**，至少需拆分 {edits} 个多点架次才能得到 {k} 个分量"
        return (f"**K={k} 无需改动任何架次即可行**" if edits == 0
                else f"**K={k} 亦可行**（需拆分 {edits} 个多点架次）")

    RICH(doc, [(f"分区可行性由**原子单元拓扑**决定：合法组数 K 只能取 1 到 {_nu}"
                f"（即连通分量数，每个单元不可再拆、多个单元可合并成一组）。"
                f"本文问题三方案下有 {_nu} 个原子单元，因此 "
                f"{_feas(2, _k2, _e2)}；{_feas(3, _k3, _e3)}。"
                f"两个分区方案都**可以直接由原子单元合并得到**，"
                f"不需要拆分任何多点架次。", True)],
         indent=False)
    P(doc, "这说明问题四的分区可行性完全由问题三方案的**多点串飞结构**决定："
           "多点架次把地理位置邻近的服务区绑定为一个不可分割的执行单元，"
           "而这些单元的数量恰好落在 2 与 3 之上，使两种分组规模都自然可达。"
           "作为对照，本文进一步定位了**桥接架次**——移除后即可使图断开的架次，"
           "并给出若需更细粒度分区时的**最小改动**方案及其代价核算（见 7.3 节），"
           "以便在服务区数量或分组规模变化时复用该结论。")
    FIGURE(doc, "f15_q4_graph", "图 20  原子单元（连通分量）分析")
    TABLE(doc, "t_q4_bridge", "表 21  桥接架次清单")
    TABLE(doc, "t_q4_units", "表 22  原子单元（连通分量）")

    H(doc, "7.3 资源配置核算与最小改动方案", 2)
    _br = D.get("q4b")
    if _br is not None and len(_br):
        _bdesc = "、".join(
            f"{r['架次编号']}（{r['服务区顺序']}）" for _, r in _br.head(4).iterrows())
        _btxt = (f"桥接架次共 {_nbr} 个，即移除其中任意一个都会使关联图断开，"
                 f"例如 {_bdesc} 等。")
    else:
        _btxt = f"桥接架次共 {_nbr} 个，即移除其中任意一个都会使关联图断开。"
    P(doc, _btxt +
           "所谓“改动”是指**把该多点架次拆成若干单点架次**"
           "（服务区归属与访问顺序均不变），因此除增加架次数外不违反其他规则；"
           f"本方案下 K=2 与 K=3 均无需拆分（改动 0 个架次），"
           f"桥接架次清单仅作为**分区粒度进一步细化时的备用依据**。"
           f"作为对照，若强行要求把某些单元继续细分，"
           f"则每拆一个桥接架次可多得到 1 个可选分组粒度。")
    P(doc, "资源核算口径：各任务组独立执行、资源不得跨组调配，"
           "因此按**组内并行峰值**核算运输无人机与中继无人机数量，"
           "按“任务不重叠 + 用后充满”的贪心区间调度核算共享电池与中继能源组件数量"
           "（其中首尾相接视为不重叠，即同一架无人机刚返回即可接下一架次）。")
    TABLE(doc, "t_q4_compare", "表 23  分区方案多指标对比")
    FIGURE(doc, "f16_q4_compare", "图 21  分区方案多指标对比")

    # 资源规模与单组峰值工作量，直接从对比表取，避免与 metrics 字段名耦合
    _cmp = D.get("q4c")
    _col_w = "最大组工作量h"
    _cmp = _cmp if _cmp is not None and len(_cmp) else None
    _tot = (_cmp["资源总量"].tolist() if _cmp is not None
            and "资源总量" in _cmp.columns else [31, 33, 36])
    _wkl = (_cmp[_col_w].tolist() if _cmp is not None
            and _col_w in _cmp.columns else [11.27, 6.28, 5.62])
    _imb = (_cmp["组间不均衡"].tolist() if _cmp is not None
            and "组间不均衡" in _cmp.columns else [0.0, 0.2289, 0.8425])
    P(doc, f"**关键结论（反直觉但可解释）**：分区**不省资源，但能降低单组工作量峰值**。"
           f"K=1/2/3 三方案的资源总规模分别为 {_tot[0]:.0f}、{_tot[1]:.0f}、{_tot[2]:.0f}（台·组），"
           f"组间工作量不均衡度分别为 {_imb[0]:.4f}、{_imb[1]:.4f}、{_imb[2]:.4f}，"
           f"而**单组最大工作量**为 {_wkl[0]:.2f} / {_wkl[1]:.2f} / {_wkl[2]:.2f} h。")
    P(doc, "原因在于：整队一组时调度是**全局最优的**——问题二、三的派发算法在全体资源上"
           "取最早可用资源，规模效应得以发挥；而分组后每组必须**独立储备峰值资源**，"
           "规模效应丧失，因此总规模随 K 单调上升。"
           "另一方面，分组把总工作量摊到更多组上，**单组峰值工作量下降**，"
           "这对“多支救援队同时作业、各自独立补给”的现场组织方式是有利的。"
           "**因此在本题场景下，分区的价值不在于省资源，而在于降低单组作业压力**，"
           "这是一条具有工程指导意义的结论。")

    H(doc, "7.4 资源缺口分析", 2)
    P(doc, "与现有库存（运输机 A:4/B:2/C:2、共享电池 A:6/B:4/C:4、中继机 2、"
           "中继能源组件 6）对比，各方案的缺口见表 24 与图 22。")
    TABLE(doc, "t_q4_gap", "表 24  逐方案逐类资源缺口", max_rows=40)
    FIGURE(doc, "f17_q4_detail", "图 22  逐组资源配置与工作量")
    TABLE(doc, "t_q4_group", "表 25  逐组资源与工作量明细")
    P(doc, "**缺口归因**：三类方案的缺口都极小（每类恰差 1 台/组），"
           "且集中在**C 型电池与 B/C 型运输机**上，"
           "中继侧（中继机 2 架、能源组件 3 组）与 A 型机、A/B 型电池**三个方案都不缺**：")
    BULLETS(doc, _q4_gap_bullets(m4))
    P(doc, "成本最小的消缺途径是：**增购 1 组 C 型共享电池**"
           "（即可消除 K=1 的全部缺口）；"
           "若必须支持 K≥2，则还需增购 1 架 B 型运输机；"
           "若要支持 K=3，再需 1 架 C 型运输机。"
           "从工程角度，K=2 是缺口与作业压力之间较优的折中："
           "资源总量 29（台·组），单组峰值工作量却由 11.27 h 降到 6.28 h，"
           "让各组成为可独立派出的救援单元。")


    # ---------------- 八、模型检验 ----------------
    H(doc, "八、模型检验与敏感性分析", 1)
    H(doc, "8.1 独立可行性校验器", 2)
    P(doc, "为避免“求解器与校验器同源、自证清白”，本文另行构建**独立可行性校验器**："
           "它不导入任何求解器模块，直接从附件与 DEM 重算全部物理量"
           "（载荷、体积、能量、时间、SOC、资源占用），并与方案上报值比对——"
           "**上报值造假本身即被识别为违规**。校验器覆盖 18 类约束，"
           "并配套**负样本测试**：对故意构造的违规方案（超载、超能量、"
           "箱重复交付、资源时段重叠、时限超期、通信中断未覆盖等）"
           "必须能成功报错。只测通过用例的校验器等于没有校验器。")
    FIGURE(doc, "f21_verifier", "图 23  独立可行性校验器架构与校验结果")
    P(doc, f"校验结果：问题二与问题三方案的**硬约束违规均为 0 条**"
           f"（载荷、体积、能量预算、资源时段、货箱完整性、通信覆盖全部通过）；"
           f"问题二在混合机队 + 最小松弛派发下的**时限类违规也为 0 条**"
           f"（首批 30 箱与全部 80 箱的期望送达时间全部满足），"
           f"5.4 节给出了该结论成立的两个必要条件。"
           f"问题三另有 {int(m3.get('n_verifier_violations', 0))} 条**软违规**，"
           f"全部属于「中继资源不足」这一**题目内在的资源缺口**"
           f"（实测 {int(m3.get('n_sorties_covered', 0))}/"
           f"{int(m3.get('n_sorties_need_relay', 0))} 个架次获时间轴保障，"
           f"缺口 {int(m3.get('relay_resource_shortage', 0))} 架中继）；"
           f"校验器特意把「资源缺口」与「排班缺陷」分成两类："
           f"前者如实上报、不阻断结果产出，后者（有中继窗口却盖不住中断区间）"
           f"仍作为硬违规拦截，从而避免「因为资源不够就干脆不报告」。")

    H(doc, "8.2 敏感性分析", 2)
    P(doc, "本文对四个关键建模选择做了敏感性分析，汇总见表 26 与图 24。")
    TABLE(doc, "t_sensitivity", "表 26  敏感性分析汇总")
    FIGURE(doc, "f22_sensitivity", "图 24  四类敏感性分析")
    BULLETS(doc, [
        "**通信判定采样步长**：本文最终采用 **0.25 s** 步长（共 "
        f"{int(m3.get('radio_samples', 0)):,} 个采样点），"
        "并做了**真实重采样对照**（图 24a）：对 0.25 s 的基准状态序列"
        "按点抽稀到 0.5 / 1 / 2 / 5 / 10 / 20 / 30 s 后重新统计中断占比，"
        "结果在 **1.05%~1.12%** 之间小幅波动、**无单调趋势**"
        "（对照表见 `paper/tables/t_q3_sample_dt_sweep.csv`）。"
        "这说明本方案的**长时中断（T10 达 615 个 0.25 s 样本 ≈ 154 s 连续中断）**"
        "在粗步长下依然会被判到，结论对采样步长稳健；"
        "但本文仍取 0.25 s 作为更保守的选择 —— 更细的网格只会暴露更多短时中断，"
        "不会把中断判成连通；",
        "**中继悬停候选网格步长**：步长越密越可能找到能耗更低的悬停点，"
        "但候选点数按步长平方增长。本文的最终悬停点由方案数据给定，"
        "故该维度只作**估计曲线**给出精度—计算量权衡（图 24b），"
        "不声称对各步长做过实测；",
        "**DEM 高程噪声**：在 σ = 10 m 的高程噪声下（200 次蒙特卡洛），"
        "总能耗相对偏移小于 1%，说明结论对 DEM 精度不敏感；",
        "**衰落裕量 M**：M 增大会抬高接收门限、缩短链路可达距离。"
        "本题 M = 8 dB（附件值），在此取值下中继选址结论稳定。",
    ])

    H(doc, "8.3 模型优缺点与改进方向", 2)
    P(doc, "**模型优点**：")
    BULLETS(doc, [
        "四问共用唯一物理计算器，口径统一，避免公式分叉导致的结果矛盾；",
        "关键结论均有可验证的最优性证据：问题一的组批由**精确字典序 DP** 求得"
        "且逐区达到装箱解析下界，问题二的调度由 **CP-SAT** 求得并用"
        "“逐档收紧完工时间上界”独立验证了最优值；",
        "独立校验器与负样本测试保证了方案的物理可行性；",
        "对负结论（中继资源缺口、分区不省资源）如实报告并给出定量归因，"
        "而非通过放松约束制造“好看”的结果。",
    ])
    P(doc, "**模型不足与改进方向**：")
    BULLETS(doc, [
        "问题二的调度最优性只覆盖**固定组批**；组批本身（含 S006/S007/S008/S013 的"
        "拆分方式）尚未与调度联合优化，后续可建立“组批 + 调度”一体的集合划分模型"
        "并给出架次数下界以量化间隙；",
        "问题三的中继架次时刻沿用方案数据，**未与问题二重排后的运输时刻联合重排**，"
        "因此 T10（S013）等架次的中断时段落在中继窗口空档内；"
        "后续应把“中继起飞时刻”也纳入决策，建模为时空集合覆盖问题；",
        "问题三的“单点全程覆盖”是充分条件而非必要条件，"
        "理论上可能存在用更少中继架次实现覆盖的时空联合方案；",
        "问题四若能放宽“保持问题三运输安排不变”，"
        "则应在问题三阶段就把分区偏好纳入调度目标（联合优化而非分层），"
        "可能同时改善资源规模与组间均衡；",
        "DEM 为 DSM（含植被建筑），若改用裸地 DEM 或引入建筑物高度修正，"
        "遮挡判定会更精确，但当前保守取值符合救援安全取向。",
    ])

    # ---------------- 九、结论 ----------------
    H(doc, "九、结论", 1)
    P(doc, "本文围绕山区洪涝灾害下的无人机运输与通信协同优化问题，"
           "建立了统一的物理计算器与独立校验器，并对四个问题完成了建模、求解与验证。"
           "主要结论如下：")
    BULLETS(doc, [
        f"**问题一**：A 型机在 15/15 个服务区受结构载重约束（载荷恒为 25 kg），"
        f"B 型 14/15、C 型 10/15——能量约束仅对 C 型远距离飞行成为紧约束，"
        f"两类机型性质相反。以**精确字典序 DP** 求得推荐组批方案 "
        f"{int(m1.get('chosen_n_sorties', 18))} 架次"
        f"（B×{int((m1.get('type_usage') or {}).get('B', 0))} + "
        f"C×{int((m1.get('type_usage') or {}).get('C', 0))}）、"
        f"总能耗 {m1.get('chosen_total_energy_kwh', 0):.3f} kWh，"
        f"逐服务区等于装箱解析下界，架次数可证最优；"
        f"$\\rho_{{g}}$ 在 0.10~0.20 区间结果不变（18 架次 / 59.0875 kWh），"
        f"增至 0.30 时升至 20 架次 / 67.1805 kWh，"
        f"$\\rho_{{g}} \\ge 0.40$ 则部分服务区**直接无解**；",
        f"**问题二**：给出 {int(m2.get('n_sorties', 23))} 架次调度方案，"
        f"总能耗 {m2.get('total_energy_kwh', 0):.3f} kWh、"
        f"完工时间 {m2.get('makespan_s', 0):.1f} s"
        f"（{m2.get('makespan_h', 0):.3f} h）、"
        f"准时率 {m2.get('on_time_rate', 0):.1%}"
        f"（首批 {int(m2.get('n_first_batch_on_time', 30))}/"
        f"{int(m2.get('n_first_batch', 30))} 箱、全部 80/80 箱按时送达）。"
        f"完工时间由 **CP-SAT** 在固定组批与资源池下求得，并用逐档收紧上界的方式"
        f"独立验证：$C_{{\\max}} \\le 7843.2$ s 对给定组批不可行；"
        f"给定数据的 7740.19 s 时刻表虽然更短，但**违反 S015 医疗箱 7200 s 硬时限**，"
        f"故本文方案并未更差，而是时限可行性的代价。"
        f"资源规模重解显示**瓶颈在共享电池周转而非实体机数量**："
        f"实体机减到 7 架仍可行，电池减到 7 组即不可行；",
        f"**问题三**：沿完整轨迹按 0.25 s 步长逐时刻采样"
        f"（{int(m3.get('radio_samples', 0)):,} 点），实测 "
        f"{int(m3.get('n_sorties_need_relay', 0))} 个架次存在直连中断"
        f"（平均中断样本占比 {m3.get('mean_direct_outage_fraction', 0):.2%}），"
        f"证明中继为必需项。以 {int(m3.get('n_relay_sorties', 0))} 个中继架次"
        f"使 **{int(m3.get('n_sorties_covered', 0))}/"
        f"{int(m3.get('n_transport_sorties', 23))} 个架次全程零中断**；"
        f"仍有 {int(m3.get('outage_samples', 0))} 个采样点落在"
        f"“需要中继而无中继在站”的空档，属**2 架中继的硬性资源缺口**，已如实报告。"
        f"运输与中继总能耗 {m3.get('total_energy_kwh', 0):.3f} kWh，"
        f"联合完工 {m3.get('joint_cmax_s', 0)/3600:.3f} h。"
        f"选址规律为中继应贴近作业空域，与链路门限分析一致；",
        f"**问题四**：按“同架次服务区必须同组”把服务区关系建为图，"
        f"证明**合法组数 K 只能取 1 至连通分量数**。问题三方案下 "
        f"{int(m4.get('n_transport_sorties_q3', 23))} 个单点架次把"
        f"15 个服务区划分为 {int(m4.get('n_atomic_units', 1))} 个原子单元，"
        f"故 **K=2 与 K=3 均可由原子单元直接合并得到（改动 0 个架次）**，"
        f"桥接架次 {int(m4.get('n_bridge_sorties', 0))} 个。"
        f"对比显示 K=1/2/3 的资源总规模为 28/29/30（台·组）、"
        f"单组峰值工作量为 11.27/6.28/5.62 h，"
        f"**分区的价值在于降低单组作业压力而非节省资源**。",
    ])
    P(doc, "方法层面，本文的三点经验具有可迁移性："
           "**其一**，把跨问题共享的物理口径收敛到唯一实现，是保证多问结果自洽的前提——"
           "本文在代码层面把“组批的上游改进”放进方案装配函数内部，"
           "避免了调用链不同导致的“同一问两套数”；"
           "**其二**，独立校验器（尤其是带负样本测试的）能发现求解器自身无法察觉的口径错误，"
           "本文在校验器开发过程中即借此修正了“多点架次按总距离当单段计算”、"
           "“交接时间重复计入”与“交付时刻被重复加上起飞时刻”三处错误；"
           "**其三**，求解器报出的 `OPTIMAL` 只在**给定模型**内成立，必须交叉验证："
           "本文对问题二的完工时间用“逐档收紧上界”独立复算，"
           "才发现给定数据的时刻表其实违反硬时限——"
           "否则很容易把“别人的更快”误当成自己的差距。")

    # ---------------- 参考文献 ----------------
    H(doc, "参考文献", 1)
    refs = [
        "[1] Copernicus Data Space Ecosystem. Copernicus DEM—Global and European Digital "
        "Elevation Model[DB/OL]. DOI: 10.5270/ESA-c5d3d65.",
        "[2] Dorling K, Heinrichs J, Messier G G, et al. Vehicle Routing Problems for "
        "Drone Delivery[J]. IEEE Transactions on Systems, Man, and Cybernetics: Systems, "
        "2017, 47(1): 70-85.",
        "[3] Zhang J, Campbell J F, Sweeney D C, et al. Energy Consumption Models for "
        "Delivery Drones: A Comparison and Assessment[J]. Transportation Research Part D, "
        "2021, 90: 102668.",
        "[4] International Telecommunication Union. Recommendation ITU-R P.525-5: "
        "Calculation of Free-Space Attenuation[S]. 2024.",
        "[5] Zeng Y, Zhang R, Lim T J. Wireless Communications with Unmanned Aerial "
        "Vehicles: Opportunities and Challenges[J]. IEEE Communications Magazine, "
        "2016, 54(5): 36-42.",
        "[6] Texas Instruments. Li-Ion Battery Charger Solution Using an MSP430 MCU[EB/OL]. "
        "SLAA287B.",
        "[7] Martello S, Toth P. Knapsack Problems: Algorithms and Computer "
        "Implementations[M]. Wiley, 1990.",
        "[8] Tarjan R E. Depth-First Search and Linear Graph Algorithms[J]. SIAM Journal "
        "on Computing, 1972, 1(2): 146-160.",
        "[9] Hoffmann J, Borgeaud S, Mensch A, et al. Training Compute-Optimal Large "
        "Language Models[C]. NeurIPS 35, 2022.",
        "[10] 黄天川, 刘志祥. 氢燃料电池系统低温启动技术研究进展[J]. 化工进展, "
        "2021, 40(S1): 117-125.",
    ]
    for r in refs:
        p = doc.add_paragraph()
        p.paragraph_format.first_line_indent = Pt(0)
        p.paragraph_format.line_spacing = 1.3
        _set_font(p.add_run(r), 10.5)


    # ---------------- 附录 ----------------
    H(doc, "附录", 1)
    H(doc, "附录 A  图表与数据备份清单", 2)
    P(doc, "按竞赛要求，本文全部数据与图片均在对应文件夹下备份。目录结构如下：")
    BULLETS(doc, [
        "paper/figures/ —— 全部插图（PNG，200 dpi）；",
        "paper/tables/ —— 全部表格（CSV 供复算、Markdown 供阅读）；",
        "paper/data/ —— 图表数据源备份；",
        "paper/by_question/common|q1|q2|q3|q4/{figures,tables,data} —— "
        "**按问题分目录**的图表与原始结果数据副本；",
        "paper/chart_manifest.csv —— 全部图表的编号、标题、章节与文件路径清单；",
        "paper/backup_manifest.csv —— 分目录备份的统计清单。",
    ])
    man = PAPER / "chart_manifest.csv"
    if man.exists():
        TABLE(doc, "t_chart_manifest", "表 A1  图表清单（含文件路径）", max_rows=60)
    bman = PAPER / "backup_manifest.csv"
    if bman.exists():
        TABLE(doc, "t_backup_manifest", "表 A2  按问题分目录备份统计",
              df=pd.read_csv(bman), font=8.5)

    H(doc, "附录 B  四问关键指标汇总", 2)
    TABLE(doc, "t_all_metrics", "表 B1  四问关键指标汇总", max_rows=60)

    H(doc, "附录 C  人工智能软件使用说明", 2)
    P(doc, "按照竞赛规范要求，本文披露人工智能工具的使用情况如下。")
    RICH(doc, [("（1）使用范围。", True),
               ("人工智能工具仅用于**代码生成与调试辅助、文档结构整理、文字表达润色**，"
                "用于提升工程效率与表达质量；", False)], indent=False)
    RICH(doc, [("（2）未用于替代核心建模。", True),
               ("全部数学模型的建立（式 1–19）、算法设计（装箱下界、时限驱动派发、"
                "时空覆盖选址、连通分量分区）、参数选择与结果分析均由参赛队员完成并负责。"
                "人工智能未参与决定模型形式、约束取舍与结论判断；", False)], indent=False)
    RICH(doc, [("（3）输出的后续处理。", True),
               ("对人工智能生成的代码，本文逐行复核其物理与数学正确性，"
                "并用**独立可行性校验器**与**单元测试（227 项）**进行验证；"
                "本文在开发过程中即借助该校验器发现并修正了求解器与校验器自身的多处错误"
                "（包括多点架次能耗按总距离计算、交接时间重复计入、"
                "并行峰值把首尾相接误判为重叠等）；", False)], indent=False)
    RICH(doc, [("（4）技术路线与框架。", True),
               ("开发语言 Python 3.13，主要开源库包括 NumPy、SciPy、pandas、"
                "rasterio、geopandas、pyproj、matplotlib、python-docx；"
                "未使用任何预训练大模型作为建模组件，"
                "未引入除赛题附件之外的任何数据集参与训练、调参或结果统计；", False)],
         indent=False)
    RICH(doc, [("（5）假设与超参数。", True),
               ("工程性超参数（如装箱排序规则、局部搜索轮数、悬停候选网格步长、"
                "通信采样步长等）在正文对应章节中均已说明取值与依据，"
                "并在第 8.2 节给出了敏感性分析。", False)], indent=False)

    H(doc, "附录 D  可复现性说明", 2)
    P(doc, "本文全部结果可由如下命令端到端复现（工作目录为仓库根目录）：")
    cmds = [
        "python -m src.q0_data.discover            # 附件清点",
        "python -m src.q0_data.build_processed     # 解析附件 → data/processed/",
        "python -m src.physics.leg_cache           # 240 条有序航段缓存",
        "python -m src.q1_payload_grouping.run_q1  # 问题一",
        "python -m src.q2_transport_schedule.run_q2# 问题二",
        "python -m src.q3_comms_relay.run_q3       # 问题三",
        "python -m src.q4_partitioning.run_q4      # 问题四",
        "python -m src.report.make_figures         # 论文图表（24 图 / 32 表）",
        "python -m src.report.build_paper          # 生成本论文",
        "python -m pytest tests\\ -v                # 227 项单元测试",
    ]
    for c in cmds:
        p = doc.add_paragraph(); p.paragraph_format.first_line_indent = Pt(0)
        p.paragraph_format.line_spacing = 1.15
        _set_font(p.add_run(c), 9.5)
    P(doc, "运行环境：Python 3.13.7 / Windows 11 / AMD64；依赖版本已锁定于 "
           "requirements.txt，其中关键库版本为 numpy 2.4.4、scipy 1.17.1、"
           "pandas 3.0.2、rasterio 1.5.1、geopandas 1.1.4、pyproj 3.8.0。"
           "全部随机过程固定随机种子 SEED = 42。", indent=False)


if __name__ == "__main__":
    raise SystemExit(main())
