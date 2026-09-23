"""第 0 步：数据发现（★ D 题阻塞性前置任务）。

用途：
    在 data/raw/ 下清点竞赛官方附件，解析结构化文件的字段结构，
    生成"附件类别 ↔ 实际文件名"对照表，并输出 data_inventory.json。

为什么必须先做：
    附录 1 只给了**文件名**，没有给字段名。以下关键项必须以实测为准：
      - 坐标是经纬度还是投影坐标（决定 src/geo/crs.py 的实现）
      - DEM 的 CRS / 分辨率 / nodata / 高程基准（决定地形与遮挡计算）
      - 3 种机型的全部参数列名与单位
      - 8 架实体无人机在 3 种机型间如何分配
      - 货箱体积单位是否与机型装载体积上限一致
      - 链路预算参数在各主体（G01 / 运输机 / 中继机）间是否分别给值

用法：
    python -m src.q0_data.discover
    python -m src.q0_data.discover --root data/raw --out outputs/data_inventory.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from src.common.config import (
    ATTACH_BASE_PARAMS,
    ATTACH_GEOSPATIAL,
    DATA_RAW,
    OUTPUTS,
    REPO_ROOT,
)

# Windows 控制台默认 GBK，中文输出会乱码 —— 强制 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


# ---------------------------------------------------------------- D 题附件识别

# 附录 1 明确给出的 5 个基础参数文件（用关键词模糊匹配真实文件名）
BASE_PARAM_FILES = {
    "调度中心与服务区": ["调度中心", "服务区"],
    "物资需求与配送时限": ["物资需求", "配送时限"],
    "运输无人机数据": ["运输无人机"],
    "中继无人机数据": ["中继无人机"],
    "通信链路参数": ["通信链路", "链路参数"],
}

# 地理空间与 DEM
GEOSPATIAL_KEYWORDS = {
    "DEM": [".tif", ".tiff", ".hgt", ".asc", ".img", ".vrt", ".dem"],
    "地理空间数据说明": ["说明"],
}


def classify_file(path: Path) -> str:
    """按附录 1 的清单把文件归类。返回中文类别名或 '未分类'。"""
    name = path.name
    suffix = path.suffix.lower()

    # ① 栅格优先判定（★ 不能放在表格判定之后，否则 .tif 会被误判）
    if suffix in GEOSPATIAL_KEYWORDS["DEM"]:
        return "30m DEM"

    # ② 地理空间说明文档
    if suffix in {".docx", ".doc"} and "说明" in name:
        return "地理空间数据说明"

    # ③ 基础参数只能是表格类文件（★ 排除 .json/.txt/.csv 等非附件格式）
    if suffix in {".xlsx", ".xls"}:
        for label, keys in BASE_PARAM_FILES.items():
            if all(k in name for k in keys):
                return label
        # 容错：部分关键词命中即可
        for label, keys in BASE_PARAM_FILES.items():
            if any(k in name for k in keys):
                return f"{label}（模糊匹配）"

    return "未分类"


# ---------------------------------------------------------------- 文件名工具

def file_sha256(path: Path, chunk: int = 1 << 20) -> str:
    """计算文件 sha256（用于可追溯性与去重）。"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------- 结构化文件探测

def probe_csv(path: Path, nrows: int = 5) -> dict[str, Any]:
    """探测 CSV/TSV 的字段结构。"""
    import pandas as pd

    sep = "\t" if path.suffix.lower() in {".tsv", ".txt"} else ","
    try:
        df = pd.read_csv(path, sep=sep, nrows=200)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    full_rows = None
    try:
        with path.open("rb") as f:
            full_rows = sum(1 for _ in f) - 1
    except Exception:  # noqa: BLE001
        pass
    return {
        "kind": "table",
        "n_rows_est": full_rows,
        "n_cols": int(df.shape[1]),
        "columns": [str(c) for c in df.columns],
        "dtypes": {str(c): str(t) for c, t in df.dtypes.items()},
        "missing_rate": {
            str(c): round(float(df[c].isna().mean()), 6) for c in df.columns
        },
        "head": json.loads(df.head(nrows).to_json(orient="records", force_ascii=False)),
    }


def probe_excel(path: Path, nrows: int = 5) -> dict[str, Any]:
    """探测 Excel 的 sheet 与字段结构。"""
    import pandas as pd

    try:
        sheets = pd.read_excel(path, sheet_name=None, nrows=200)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    out: dict[str, Any] = {"kind": "excel", "n_sheets": len(sheets), "sheets": {}}
    for name, df in sheets.items():
        out["sheets"][name] = {
            "n_cols": int(df.shape[1]),
            "columns": [str(c) for c in df.columns],
            "dtypes": {str(c): str(t) for c, t in df.dtypes.items()},
            "missing_rate": {
                str(c): round(float(df[c].isna().mean()), 6) for c in df.columns
            },
            "head": json.loads(
                df.head(nrows).to_json(orient="records", force_ascii=False)
            ),
        }
    return out


def probe_json(path: Path) -> dict[str, Any]:
    """探测 JSON 的顶层结构。"""
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    top = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            top[str(k)] = (
                f"list[{len(v)}]" if isinstance(v, list) else type(v).__name__
            )
    return {"kind": "json", "top_level": top}


def probe_pickle(path: Path) -> dict[str, Any]:
    """探测 pickle 的顶层键与数组形状（不加载全部数据）。"""
    import pickle

    try:
        with path.open("rb") as f:
            obj = pickle.load(f)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}

    def describe(v: Any, depth: int = 0) -> Any:
        if depth > 2:
            return type(v).__name__
        if isinstance(v, dict):
            return {str(k): describe(x, depth + 1) for k, x in list(v.items())[:40]}
        if isinstance(v, (list, tuple)):
            inner = describe(v[0], depth + 1) if v else "empty"
            return f"seq[{len(v)}] of {inner}"
        if hasattr(v, "shape"):
            return f"ndarray{v.shape} {getattr(v, 'dtype', '')}"
        return type(v).__name__

    return {"kind": "pickle", "structure": describe(obj)}


def probe_npz(path: Path) -> dict[str, Any]:
    """探测 .npz 的数组清单与形状。"""
    import numpy as np

    try:
        with np.load(path, allow_pickle=True) as z:
            return {
                "kind": "npz",
                "arrays": {k: f"{z[k].shape} {z[k].dtype}" for k in z.files},
            }
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def probe_raster(path: Path) -> dict[str, Any]:
    """探测 DEM 栅格：CRS、分辨率、范围、nodata、高程统计（★ D 题关键）。"""
    try:
        import rasterio
    except Exception as e:  # noqa: BLE001
        return {"error": f"rasterio 不可用: {type(e).__name__}: {e}"}

    try:
        with rasterio.open(path) as src:
            info: dict[str, Any] = {
                "kind": "raster",
                "crs": str(src.crs) if src.crs else None,
                "crs_epsg": src.crs.to_epsg() if src.crs else None,
                "width": src.width,
                "height": src.height,
                "n_bands": src.count,
                "dtype": str(src.dtypes[0]),
                "nodata": src.nodata,
                # 分辨率：★ 若 CRS 是经纬度，单位是度，需换算成米（约 ×111320）
                "res": [float(r) for r in src.res],
                "bounds": {
                    "left": src.bounds.left,
                    "bottom": src.bounds.bottom,
                    "right": src.bounds.right,
                    "top": src.bounds.top,
                },
                "is_geographic": bool(src.crs.is_geographic) if src.crs else None,
            }
            # 抽样读取以控制内存（大步长降采样）
            step = max(1, min(src.height, src.width) // 512)
            arr = src.read(
                1,
                out_shape=(max(1, src.height // step), max(1, src.width // step)),
            )
            import numpy as np

            valid = arr[arr != src.nodata] if src.nodata is not None else arr
            if valid.size:
                info["elevation_stats"] = {
                    "min": float(np.min(valid)),
                    "max": float(np.max(valid)),
                    "mean": float(np.mean(valid)),
                    "sampled_pixels": int(valid.size),
                    "nodata_fraction": float(1 - valid.size / arr.size),
                }
            # 经纬度栅格的分辨率换算提示
            if info["is_geographic"] and info["res"]:
                deg = info["res"][0]
                info["res_approx_m"] = round(deg * 111320.0, 2)
                info["WARNING"] = (
                    "CRS 是地理坐标系（经纬度），分辨率单位是度；"
                    "计算水平距离前必须先投影到米制 CRS（见 OPS_SPEC 2.3 节 / ADR-011）"
                )
            return info
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


PROBES = {
    ".csv": probe_csv,
    ".tsv": probe_csv,
    ".xlsx": probe_excel,
    ".xls": probe_excel,
    ".json": probe_json,
    ".pkl": probe_pickle,
    ".pickle": probe_pickle,
    ".npz": probe_npz,
    ".tif": probe_raster,
    ".tiff": probe_raster,
    ".img": probe_raster,
    ".vrt": probe_raster,
    ".hgt": probe_raster,
    ".asc": probe_raster,
}


# ---------------------------------------------------------------- 主流程

def git_commit() -> str:
    import subprocess

    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _rel_to_repo(p: Path) -> str:
    """返回相对仓库根的 POSIX 路径；若在仓库外则返回绝对路径。"""
    try:
        return p.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return p.resolve().as_posix()


def discover(root: Path, out: Path, deep: bool = True) -> dict[str, Any]:
    root = root.resolve()
    if not root.exists():
        return {
            "status": "blocked",
            "reason": f"数据目录不存在：{root}",
            "action": "请先下载竞赛官方附件到 data/raw/，再重新运行本脚本。",
        }

    # 只统计"真实数据文件"，忽略版本控制占位符与临时文件
    IGNORED_NAMES = {".gitkeep", ".gitignore", ".DS_Store", "Thumbs.db"}
    IGNORED_SUFFIXES = {".tmp", ".crdownload", ".part"}
    files = sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and p.name not in IGNORED_NAMES
        and not p.name.startswith("~$")
        and p.suffix.lower() not in IGNORED_SUFFIXES
    )
    if not files:
        return {
            "status": "blocked",
            "root": _rel_to_repo(root),
            "reason": f"数据目录内没有任何数据文件：{_rel_to_repo(root)}",
            "action": "请先下载竞赛官方附件到 data/raw/，再重新运行本脚本。",
        }

    records: list[dict[str, Any]] = []
    for p in files:
        rel = _rel_to_repo(p)
        rec: dict[str, Any] = {
            "path": rel,
            "name": p.name,
            "suffix": p.suffix.lower(),
            "size_bytes": p.stat().st_size,
            "attachment_class": classify_file(p),
            "sha256": file_sha256(p) if p.stat().st_size < 50 * 1024 * 1024 else "skipped(large)",
        }
        if deep and p.suffix.lower() in PROBES:
            rec["probe"] = PROBES[p.suffix.lower()](p)
        records.append(rec)

    # 类别 → 文件 对照表
    class_map: dict[str, list[str]] = {}
    for r in records:
        class_map.setdefault(r["attachment_class"], []).append(r["path"])

    # 附录 1 声明必须存在的附件（用于完整性检查）
    expected = list(BASE_PARAM_FILES.keys()) + ["30m DEM", "地理空间数据说明"]
    missing = [
        c
        for c in expected
        if not any(k.startswith(c) for k in class_map)
    ]

    report = {
        "status": "ok",
        "timestamp": datetime.now().astimezone().isoformat(),
        "git_commit": git_commit(),
        "root": _rel_to_repo(root),
        "n_files": len(records),
        "total_bytes": sum(r["size_bytes"] for r in records),
        "class_to_files": class_map,
        "attachments_missing": missing,
        "files": records,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(
        description="D 题数据发现（P0 阻塞性前置任务）"
    )
    ap.add_argument("--root", type=Path, default=DATA_RAW, help="原始数据根目录")
    ap.add_argument(
        "--out",
        type=Path,
        default=OUTPUTS / "data_inventory.json",
        help="清单输出路径",
    )
    ap.add_argument("--shallow", action="store_true", help="只清点文件，不解析结构")
    args = ap.parse_args()

    rep = discover(args.root, args.out, deep=not args.shallow)

    print("=" * 70)
    print("D 题 · P0 数据发现")
    print("=" * 70)
    print(f"根目录   : {rep.get('root')}")
    print(f"状态     : {rep['status']}")
    print(f"文件数   : {rep.get('n_files', 0)}")
    print(f"总大小   : {rep.get('total_bytes', 0) / 1024 / 1024:.2f} MB")
    print(f"清单输出 : {args.out}")

    if rep["status"] == "blocked":
        print()
        print("⚠️  阻塞：数据目录为空或不存在。")
        print(f"   原因：{rep.get('reason', '目录内没有任何文件')}")
        print(f"   动作：{rep.get('action', '请先下载竞赛官方附件到 data/raw/。')}")
        print("   详见：docs/PROGRESS.md 的『阻塞项』")
        return 1

    print()
    print("附件类别 → 文件：")
    for cls in sorted(rep["class_to_files"]):
        for f in rep["class_to_files"][cls]:
            print(f"  [{cls:<22}] {f}")

    if rep["attachments_missing"]:
        print()
        print(f"⚠️  附录 1 声明但未匹配到的附件（{len(rep['attachments_missing'])} 项）：")
        for c in rep["attachments_missing"]:
            print(f"   - {c}")
        print("   注：文件名可能不含预期关键词，请人工核对 docs/DATA_NOTES.md")

    # DEM 是地理坐标系的警告要显式提示（★ 单位陷阱）
    for r in rep["files"]:
        probe = r.get("probe") or {}
        if probe.get("kind") == "raster" and probe.get("WARNING"):
            print()
            print("⚠️  DEM 警告：")
            print(f"   {r['name']}: {probe['WARNING']}")

    print()
    print("下一步：把实测字段结构回填到 docs/DATA_NOTES.md，")
    print("        并确认坐标 CRS、8 架机的机型分配、货箱体积单位等未决项。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
