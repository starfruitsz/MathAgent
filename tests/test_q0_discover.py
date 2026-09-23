"""P0 数据发现模块的测试。

覆盖 OPS_SPEC 第 7.3 节要求的测试类型：
    - 形状与类型
    - 边界条件（空目录、无数据文件）
    - 可复现性
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.common.config import (
    CHG_FAST_FRACTION,
    CHG_FAST_SOC_BOUNDARY,
    CHG_SLOW_FRACTION,
    CRUISE_CLEARANCE_M,
    DEM_RESOLUTION_M,
    DOWNWARD_ENERGY_EFFICIENCY,
    FSPL_CONSTANT,
    M_TO_KM,
    N_BOXES,
    N_SERVICE_AREAS,
    N_TASK_GROUPS,
    N_UAV_PHYSICAL,
    N_UAV_TYPES,
    PAYLOAD_RANGE_EXPONENT,
    SERVICE_AREA_OP_HEIGHT_M,
    SOC_INITIAL,
)
from src.q0_data.discover import classify_file, discover


# ---------------------------------------------------------------- 附件分类（D 题）

@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        # 附录 1 的 5 个基础参数文件
        ("调度中心与服务区.xlsx", "调度中心与服务区"),
        ("物资需求与配送时限.xlsx", "物资需求与配送时限"),
        ("运输无人机数据.xlsx", "运输无人机数据"),
        ("中继无人机数据.xlsx", "中继无人机数据"),
        ("通信链路参数.xlsx", "通信链路参数"),
        # 容错：文件名带前后缀
        ("附件3-运输无人机数据表.xlsx", "运输无人机数据"),
        # DEM 栅格的各种扩展名
        ("zhenlong_dem.tif", "30m DEM"),
        ("dem.tiff", "30m DEM"),
        ("copdem_30m.vrt", "30m DEM"),
        # 地理空间说明文档
        ("镇龙乡地理空间数据说明.docx", "地理空间数据说明"),
        # 未分类
        ("readme.txt", "未分类"),
        ("random.xlsx", "未分类"),
        # ★ 回归测试：非 xlsx 的表格/文本文件不得被误判为附件，
        #    即使文件名含"运输无人机数据"关键词
        ("运输无人机数据.json", "未分类"),
        ("运输无人机数据.csv", "未分类"),
        ("运输无人机数据.txt", "未分类"),
    ],
)
def test_classify_file(filename: str, expected: str) -> None:
    assert classify_file(Path(filename)) == expected


def test_classify_excel_is_not_mistaken_for_dem() -> None:
    """回归测试：'.tif' 等栅格扩展名判定必须优先于表格判定。"""
    assert classify_file(Path("dem.tif")) == "30m DEM"
    assert classify_file(Path("运输无人机数据.xlsx")) == "运输无人机数据"


# ---------------------------------------------------------------- 空数据目录

def test_discover_empty_dir_is_blocked(tmp_path: Path) -> None:
    """空目录必须报告 blocked，且不抛异常。"""
    rep = discover(root=tmp_path, out=tmp_path / "inv.json", deep=False)
    assert rep["status"] == "blocked"
    assert "reason" in rep
    assert "action" in rep


def test_discover_ignores_gitkeep(tmp_path: Path) -> None:
    """只有 .gitkeep 的目录应视为空（这是仓库的默认状态）。"""
    (tmp_path / ".gitkeep").write_text("", encoding="utf-8")
    rep = discover(root=tmp_path, out=tmp_path / "inv.json", deep=False)
    assert rep["status"] == "blocked"
    assert rep.get("n_files", 0) == 0


def test_discover_nonexistent_dir_is_blocked(tmp_path: Path) -> None:
    rep = discover(root=tmp_path / "does_not_exist", out=tmp_path / "inv.json", deep=False)
    assert rep["status"] == "blocked"


# ---------------------------------------------------------------- 正常解析

def test_discover_relative_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """回归测试：相对路径作为 root 时不得抛 ValueError（原先的 bug）。"""
    import os

    (tmp_path / "B1_x.csv").write_text("N,D,loss\n1e8,1e9,3.2\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    rep = discover(root=Path("."), out=tmp_path / "inv.json", deep=True)
    assert rep["status"] == "ok"
    assert rep["n_files"] == 1


def test_discover_parses_csv(tmp_path: Path) -> None:
    """CSV 不是附件格式，但结构探测功能本身必须正常。"""
    (tmp_path / "nodes.csv").write_text(
        "id,lon,lat,elev\nO01,109.1,22.9,120\n", encoding="utf-8"
    )
    rep = discover(root=tmp_path, out=tmp_path / "inv.json", deep=True)
    assert rep["status"] == "ok"
    probe = rep["files"][0]["probe"]
    assert probe["kind"] == "table"
    assert probe["columns"] == ["id", "lon", "lat", "elev"]
    assert probe["n_rows_est"] == 1


def test_discover_reports_missing_attachments(tmp_path: Path) -> None:
    """附录 1 声明的 7 项附件若缺失，必须被如实列出。"""
    (tmp_path / "运输无人机数据.xlsx").write_text("x", encoding="utf-8")
    rep = discover(root=tmp_path, out=tmp_path / "inv.json", deep=False)
    missing = rep["attachments_missing"]
    assert "30m DEM" in missing
    assert "通信链路参数" in missing
    # 已提供的这一项不应出现在缺失列表
    assert "运输无人机数据" not in missing


def test_discover_writes_json(tmp_path: Path) -> None:
    (tmp_path / "中继无人机数据.xlsx").write_text("x", encoding="utf-8")
    out = tmp_path / "sub" / "inv.json"
    discover(root=tmp_path, out=out, deep=False)
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["status"] == "ok"
    assert data["n_files"] == 1


def test_discover_is_reproducible(tmp_path: Path) -> None:
    """同输入两次运行，除时间戳外结果应一致（OPS_SPEC 第 7.3 节可复现性）。

    注意：清单文件必须写到**被扫描目录之外**，否则第二次扫描会把上一轮的
    输出当成输入数据，导致结果不可复现。这也是 discover 的实际用法
    （扫描 data/raw，输出到 outputs/）。
    """
    scan_dir = tmp_path / "raw"
    scan_dir.mkdir()
    out_dir = tmp_path / "out"
    (scan_dir / "B2.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    r1 = discover(root=scan_dir, out=out_dir / "i1.json", deep=True)
    r2 = discover(root=scan_dir, out=out_dir / "i2.json", deep=True)
    r1.pop("timestamp"), r2.pop("timestamp")
    assert r1 == r2


def test_discover_output_inside_scan_dir_is_not_reproducible(tmp_path: Path) -> None:
    """固化已知陷阱：清单写进被扫描目录会让结果自我污染。

    这条测试记录的是**设计约束**，不是 bug —— 调用方必须把 out 放在扫描目录外。
    """
    (tmp_path / "B2.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    r1 = discover(root=tmp_path, out=tmp_path / "inv.json", deep=False)
    r2 = discover(root=tmp_path, out=tmp_path / "inv.json", deep=False)
    assert r1["n_files"] == 1
    assert r2["n_files"] == 2  # 上一轮的 inv.json 被当成了输入


# ---------------------------------------------------------------- 题目常量（防手误）

def test_d_problem_scenario_constants() -> None:
    """D 题场景规模：1 个调度中心 + 15 服务区 + 80 货箱 + 3 机型 8 架。"""
    assert N_SERVICE_AREAS == 15
    assert N_BOXES == 80
    assert N_UAV_TYPES == 3
    assert N_UAV_PHYSICAL == 8
    assert DEM_RESOLUTION_M == 30.0


def test_d_physics_constants() -> None:
    """附录 2 的关键口径，锁死防止手误。"""
    assert CRUISE_CLEARANCE_M == 50.0, "巡航海拔 = 最高地面高程 + 50 m"
    assert SERVICE_AREA_OP_HEIGHT_M == 30.0, "服务区作业高度 = 地面海拔 + 30 m"
    assert DOWNWARD_ENERGY_EFFICIENCY == 0.0, "下降能耗效率取 0，不单独计能耗"
    assert PAYLOAD_RANGE_EXPONENT == 1.5, "载荷-航程关系是 3/2 次幂"


def test_d_battery_constants() -> None:
    """附录 2 的两阶段充电模型常数。"""
    assert CHG_FAST_SOC_BOUNDARY == 0.90
    assert CHG_FAST_FRACTION == 0.65
    assert CHG_SLOW_FRACTION == 0.35
    assert CHG_FAST_FRACTION + CHG_SLOW_FRACTION == pytest.approx(1.0)
    assert SOC_INITIAL == 1.0


def test_d_comms_constants() -> None:
    """附录 3 的链路常量与单位换算。"""
    assert FSPL_CONSTANT == 32.45
    assert M_TO_KM == 1000.0
    assert N_TASK_GROUPS == (2, 3), "Q4 要求考察 2 组与 3 组"
