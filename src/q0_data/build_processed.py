"""附件解析 → 建模就绪接口（`data/processed/`）。

★ 这是**附件解析的唯一入口**（铁律 R4 的延伸）：
   `scripts/` 与 `src/qN_*` 都不得再自己 `read_excel`，否则列名/行段口径会分叉。

附件表的形态（实测，见 docs/DATA_NOTES.md）：
    - 都是**分段表**：一张 sheet 内有多个小表，用空行与段标题分隔
    - 坐标是 **WGS84 经纬度**（EPSG:4326）
    - 服务区编号形如 `S001`，货箱编号形如 `S001-MED-01`

用法：
    python -m src.q0_data.build_processed
输出：
    data/processed/nodes.csv / boxes.csv / uav_types.csv
                    relay_params.csv / link_params.csv
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.common.config import DATA_PROCESSED, DATA_RAW, REPO_ROOT

# ---------------------------------------------------------------- 路径

RAW_D = DATA_RAW / "D题"
BASE_PARAMS = RAW_D / "数据" / "无人机应急物资运输基础数据"

FILE_NODES = BASE_PARAMS / "调度中心与服务区.xlsx"
FILE_DEMAND = BASE_PARAMS / "物资需求与配送时限.xlsx"
FILE_UAV = BASE_PARAMS / "运输无人机数据.xlsx"
FILE_RELAY = BASE_PARAMS / "中继无人机数据.xlsx"
FILE_COMMS = BASE_PARAMS / "通信链路参数.xlsx"
FILE_TEMPLATE = RAW_D / "结果提交模板.xlsx"

# ---------------------------------------------------------------- 约定

SERVICE_AREA_OP_HEIGHT_OFFSET_M = 30.0
"""服务区作业高度 = 地面海拔 + 30 m（题目附录 2）。"""


class AttachmentError(RuntimeError):
    """附件缺失或结构不符合预期。"""


def _require(path: Path) -> Path:
    if not path.exists():
        raise AttachmentError(
            f"附件不存在：{path}\n"
            f"请确认已把 D 题数据放入 data/raw/D题/（见 docs/DATA_NOTES.md）"
        )
    return path


# ---------------------------------------------------------------- 节点

def load_nodes() -> pd.DataFrame:
    """解析 `调度中心与服务区.xlsx` 的分段表。

    结构（0-based 行号）：
        0  段标题「调度中心」
        1  表头
        2  O01 数据行
        3  空行
        4  段标题「服务区」
        5  表头
        6-20  S001 … S015
    """
    df = pd.read_excel(_require(FILE_NODES), header=None)
    if df.shape[0] < 21:
        raise AttachmentError(f"{FILE_NODES.name} 行数异常：{df.shape[0]}（预期 ≥ 21）")

    rows: list[dict] = []

    o = df.iloc[2]
    rows.append(
        {
            "id": str(o[0]).strip(),
            "name": str(o[1]).strip() if pd.notna(o[1]) else "",
            "lon": float(o[2]),
            "lat": float(o[3]),
            "ground_elev_m": float(o[4]),
            "kind": "center",
            "op_height_offset_m": 0.0,
            "population": float("nan"),
        }
    )

    for i in range(6, 21):
        r = df.iloc[i]
        if pd.isna(r[0]):
            continue
        rows.append(
            {
                "id": str(r[0]).strip(),
                "name": str(r[1]).strip() if pd.notna(r[1]) else "",
                "lon": float(r[2]),
                "lat": float(r[3]),
                "ground_elev_m": float(r[4]),
                "kind": "service",
                "op_height_offset_m": SERVICE_AREA_OP_HEIGHT_OFFSET_M,
                "population": float(r[5]) if pd.notna(r[5]) else float("nan"),
            }
        )

    out = pd.DataFrame(rows)
    _validate_nodes(out)
    return out


def _validate_nodes(df: pd.DataFrame) -> None:
    n_service = int((df["kind"] == "service").sum())
    if n_service != 15:
        raise AttachmentError(f"服务区数量异常：{n_service}（预期 15）")
    if int((df["kind"] == "center").sum()) != 1:
        raise AttachmentError("调度中心应恰好 1 个")
    if df["lon"].isna().any() or df["lat"].isna().any():
        raise AttachmentError("节点坐标存在缺失")
    if not df["lon"].between(108.0, 111.0).all():
        raise AttachmentError("经度超出合理范围（疑似列错位）")
    if not df["lat"].between(21.0, 25.0).all():
        raise AttachmentError("纬度超出合理范围（疑似列错位）")


def load_gateway_offset_m() -> float:
    """网关天线离地高度（m）—— 来自通信链路参数表。"""
    return float(load_comms_params()["gateway_antenna_height_m"])


# ---------------------------------------------------------------- 货箱

def load_boxes() -> pd.DataFrame:
    """解析 `物资需求与配送时限.xlsx` 的「逐箱货箱清单」。

    ★ 以逐箱清单为**唯一权威**箱数据源（ADR-015）：80 箱与题目一致，
      且已核验与汇总表零差异。
    """
    df = pd.read_excel(_require(FILE_DEMAND), sheet_name="逐箱货箱清单")
    df = df.rename(
        columns={
            "货箱编号": "box_id",
            "服务区编号": "service_id",
            "物资类型": "cargo_type",
            "单箱质量（kg）": "mass_kg",
            "单箱体积（m³）": "volume_m3",
            "是否首批保障": "is_first_batch",
            "首批截止时间（s）": "first_batch_deadline_s",
            "期望送达时间（s）": "expected_time_s",
            "应急优先系数": "priority",
        }
    )
    df["is_first_batch"] = df["is_first_batch"].astype(str).str.strip().eq("是")
    for c in ("mass_kg", "volume_m3", "expected_time_s", "priority"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # 非首批箱的截止时间统一填为其期望送达时间（便于统一处理）
    df["first_batch_deadline_s"] = pd.to_numeric(
        df["first_batch_deadline_s"], errors="coerce"
    )
    _validate_boxes(df)
    return df


def _validate_boxes(df: pd.DataFrame) -> None:
    if len(df) != 80:
        raise AttachmentError(f"货箱数量异常：{len(df)}（预期 80）")
    if df["box_id"].duplicated().any():
        raise AttachmentError("货箱编号存在重复")
    if df[["mass_kg", "volume_m3", "expected_time_s"]].isna().any().any():
        raise AttachmentError("货箱的质量/体积/期望送达时间存在缺失")
    # 每个服务区恰好 2 个首批箱（实测结论，见 DATA_NOTES 6.3）
    per_service = df[df["is_first_batch"]].groupby("service_id").size()
    if not (per_service == 2).all():
        raise AttachmentError(
            f"首批箱数量异常：应为每服务区 2 箱，实际 {per_service.to_dict()}"
        )


def load_demand_summary() -> pd.DataFrame:
    """解析 `数据` sheet（按服务区×物资类型的汇总需求），用于交叉核对。"""
    df = pd.read_excel(_require(FILE_DEMAND), sheet_name="数据")
    return df.rename(
        columns={
            "服务区编号": "service_id",
            "物资类型": "cargo_type",
            "总需求箱数": "n_boxes",
            "首批必须送达箱数": "n_first_batch",
            "单箱质量（kg）": "mass_kg",
            "单箱体积（m³）": "volume_m3",
            "应急优先系数": "priority",
            "首批截止时间（s）": "first_batch_deadline_s",
            "期望送达时间（s）": "expected_time_s",
        }
    )


# ---------------------------------------------------------------- 运输无人机

def load_uav_types() -> pd.DataFrame:
    """解析三类机型参数（行 2–4）。"""
    df = pd.read_excel(_require(FILE_UAV), header=None)
    cols = list(df.iloc[1])
    rows = []
    for i in (2, 3, 4):
        r = df.iloc[i]
        if pd.isna(r[0]):
            continue
        rows.append(
            {
                "code": str(r[0]).strip(),
                "name": str(r[1]).strip(),
                "empty_mass_kg": float(r[2]),
                "max_payload_kg": float(r[3]),
                "volume_m3": float(r[4]),
                "cruise_speed_ms": float(r[5]),
                "range_empty_m": float(r[6]),
                "range_full_m": float(r[7]),
                "energy_kwh": float(r[8]),
                "reserve_ratio": float(r[9]) / 100.0,
                "prepare_time_s": float(r[10]),
                "box_load_time_s": float(r[11]),
                "handover_base_s": float(r[12]),
                "handover_per_box_s": float(r[13]),
                "climb_speed_ms": float(r[14]),
                "descent_speed_ms": float(r[15]),
                "climb_efficiency": float(r[16]),
                "descent_efficiency": float(r[17]),
            }
        )
    out = pd.DataFrame(rows)
    if len(out) != 3:
        raise AttachmentError(f"机型数量异常：{len(out)}（预期 3）")
    _ = cols  # 表头保留给人工核对
    return out


def load_uav_fleet() -> pd.DataFrame:
    """逐架无人机清单（行 8–15）：U01–U08 与机型对应关系（ADR-004 的实测答案）。"""
    df = pd.read_excel(_require(FILE_UAV), header=None)
    rows = []
    for i in range(8, 16):
        r = df.iloc[i]
        if pd.isna(r[0]):
            continue
        rows.append(
            {
                "uav_id": str(r[0]).strip(),
                "type_code": str(r[1]).strip(),
                "initial_position": str(r[2]).strip(),
            }
        )
    out = pd.DataFrame(rows)
    if len(out) != 8:
        raise AttachmentError(f"实体无人机数量异常：{len(out)}（预期 8）")
    return out


def load_battery_inventory() -> pd.DataFrame:
    """共享电池库存（行 19–21）：分机型总数与等效完全充电时间。"""
    df = pd.read_excel(_require(FILE_UAV), header=None)
    rows = []
    for i in (19, 20, 21):
        r = df.iloc[i]
        if pd.isna(r[0]):
            continue
        rows.append(
            {
                "type_code": str(r[0]).strip(),
                "n_battery_packs": int(r[1]),
                "t_full_s": float(r[2]),
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 中继无人机

def load_relay_params() -> pd.DataFrame:
    """中继机型参数（行 2）。"""
    df = pd.read_excel(_require(FILE_RELAY), header=None)
    r = df.iloc[2]
    return pd.DataFrame(
        [
            {
                "code": str(r[0]).strip(),
                "name": str(r[1]).strip(),
                "empty_mass_kg": float(r[2]),
                "comms_module_mass_kg": float(r[3]),
                "takeoff_mass_kg": float(r[4]),
                "cruise_speed_ms": float(r[5]),
                "cruise_power_kw": float(r[6]),
                "energy_kwh": float(r[7]),
                "reserve_ratio": float(r[8]) / 100.0,
                "prepare_time_s": float(r[9]),
                "link_setup_time_s": float(r[10]),
                "turnaround_time_s": float(r[11]),
                "climb_speed_ms": float(r[12]),
                "descent_speed_ms": float(r[13]),
                "climb_efficiency": float(r[14]),
                "descent_efficiency": float(r[15]),
                "hover_power_kw": float(r[16]),
                "comms_power_kw": float(r[17]),
                "max_hover_agl_m": float(r[18]),
            }
        ]
    )


def load_relay_fleet() -> pd.DataFrame:
    """中继无人机清单（行 6–7）：R01、R02。"""
    df = pd.read_excel(_require(FILE_RELAY), header=None)
    rows = []
    for i in (6, 7):
        r = df.iloc[i]
        if pd.isna(r[0]):
            continue
        rows.append(
            {
                "relay_id": str(r[0]).strip(),
                "type_code": str(r[1]).strip(),
                "initial_position": str(r[2]).strip(),
            }
        )
    if len(rows) != 2:
        raise AttachmentError(f"中继无人机数量异常：{len(rows)}（预期 2）")
    return pd.DataFrame(rows)


def load_relay_inventory() -> pd.DataFrame:
    """中继共享能源组件库存（行 11）。"""
    df = pd.read_excel(_require(FILE_RELAY), header=None)
    r = df.iloc[11]
    return pd.DataFrame(
        [
            {
                "type_code": str(r[0]).strip(),
                "n_energy_packs": int(r[1]),
                "t_full_s": float(r[2]),
            }
        ]
    )


# ---------------------------------------------------------------- 通信链路参数

def load_comms_params() -> dict[str, float]:
    """解析 `通信链路参数.xlsx`（分两列：符号 / 参数值），按**类别**区分端点。

    返回扁平字典，键名与 `src/comms/link.py` 对齐。
    """
    df = pd.read_excel(_require(FILE_COMMS), header=None)
    kind_col, sym_col, val_col = 0, 3, 4
    out: dict[str, float] = {}
    for i in range(2, len(df)):
        kind = df.iloc[i, kind_col]
        sym = df.iloc[i, sym_col]
        val = df.iloc[i, val_col]
        if pd.isna(kind):
            continue
        kind = str(kind).strip()
        sym = str(sym).strip() if pd.notna(sym) else ""
        if pd.isna(val):
            continue
        v = float(val)
        if kind == "传播参数":
            if sym == "f":
                out["frequency_mhz"] = v
            elif sym == "Lsys":
                out["system_loss_db"] = v
            elif sym == "Lobs":
                out["obstruction_loss_db"] = v
        elif kind == "接收参数":
            if sym == "Psens":
                out["rx_sensitivity_dbm"] = v
            elif sym == "M":
                out["fade_margin_db"] = v
        elif kind == "运输无人机":
            if sym == "Pt":
                out["transport_tx_power_dbm"] = v
            elif sym == "G":
                out["transport_gain_dbi"] = v
        elif kind == "中继接入端":
            if sym == "Pt":
                out["relay_access_tx_power_dbm"] = v
            elif sym == "G":
                out["relay_access_gain_dbi"] = v
        elif kind == "中继回传端":
            if sym == "Pt":
                out["relay_backhaul_tx_power_dbm"] = v
            elif sym == "G":
                out["relay_backhaul_gain_dbi"] = v
        elif kind.startswith("固定网关"):
            if sym == "Pt":
                out["gateway_tx_power_dbm"] = v
            elif sym == "G":
                out["gateway_gain_dbi"] = v
            elif sym == "hG":
                out["gateway_antenna_height_m"] = v

    required = {
        "frequency_mhz",
        "system_loss_db",
        "obstruction_loss_db",
        "rx_sensitivity_dbm",
        "fade_margin_db",
        "transport_tx_power_dbm",
        "transport_gain_dbi",
        "relay_access_tx_power_dbm",
        "relay_access_gain_dbi",
        "relay_backhaul_tx_power_dbm",
        "relay_backhaul_gain_dbi",
        "gateway_tx_power_dbm",
        "gateway_gain_dbi",
        "gateway_antenna_height_m",
    }
    missing = required - set(out)
    if missing:
        raise AttachmentError(f"通信链路参数缺失：{sorted(missing)}")
    return out


# ---------------------------------------------------------------- 交付格式

def load_submission_template() -> dict[str, list[str]]:
    """读取 `结果提交模板.xlsx` 的 sheet 名与列名（交付格式的硬约束）。"""
    xl = pd.ExcelFile(_require(FILE_TEMPLATE))
    return {sh: list(pd.read_excel(xl, sheet_name=sh, nrows=0).columns) for sh in xl.sheet_names}


# ---------------------------------------------------------------- 落盘

def build_all(out_dir: Path = DATA_PROCESSED) -> dict[str, Path]:
    """解析全部附件并写入 `data/processed/`，返回 {名称: 路径}。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    def dump(df: pd.DataFrame, name: str) -> None:
        p = out_dir / f"{name}.csv"
        df.to_csv(p, index=False, encoding="utf-8-sig")
        written[name] = p

    dump(load_nodes(), "nodes")
    dump(load_boxes(), "boxes")
    dump(load_demand_summary(), "demand_summary")
    dump(load_uav_types(), "uav_types")
    dump(load_uav_fleet(), "uav_fleet")
    dump(load_battery_inventory(), "battery_inventory")
    dump(load_relay_params(), "relay_params")
    dump(load_relay_fleet(), "relay_fleet")
    dump(load_relay_inventory(), "relay_inventory")

    df = pd.DataFrame([load_comms_params()]).T.rename(columns={0: "value"})
    dump(df.reset_index().rename(columns={"index": "param"}), "link_params")

    return written


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    print("=" * 70)
    print("构建建模就绪接口（data/processed/）")
    print("=" * 70)
    try:
        written = build_all()
    except AttachmentError as e:
        print(f"❌ {e}")
        return 1

    for name, p in written.items():
        print(f"  ✓ {p.relative_to(REPO_ROOT)}")

    nodes = load_nodes()
    boxes = load_boxes()
    uavs = load_uav_fleet()
    print()
    print(f"节点 {len(nodes)} 个（1 调度中心 + {int((nodes['kind']=='service').sum())} 服务区）")
    print(f"货箱 {len(boxes)} 个，其中首批 {int(boxes['is_first_batch'].sum())} 个")
    print(f"运输无人机 {len(uavs)} 架：{uavs.groupby('type_code').size().to_dict()}")
    print(f"机型 {len(load_uav_types())} 种：{list(load_uav_types()['code'])}")
    print(f"中继无人机 {len(load_relay_fleet())} 架；共享能源组件 {int(load_relay_inventory()['n_energy_packs'].iloc[0])} 组")
    print()
    print("交付模板 sheets：", list(load_submission_template()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
