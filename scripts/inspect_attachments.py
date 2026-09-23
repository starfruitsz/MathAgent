"""P0 附件结构勘察：把全部 xlsx/csv/mat/tif 的结构写成 UTF-8 文本，便于逐项核对。

用法：
    python scripts/inspect_attachments.py
输出：
    outputs/p0_inspect/*.txt
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

RAW = REPO / "data" / "raw" / "D题"
BASE = RAW / "数据" / "无人机应急物资运输基础数据"
GEO = RAW / "数据" / "镇龙乡地理空间数据" / "镇龙乡及周边地理数据"
OUT = REPO / "outputs" / "p0_inspect"
OUT.mkdir(parents=True, exist_ok=True)


def w(name: str, text: str) -> None:
    (OUT / name).write_text(text, encoding="utf-8")
    print(f"  -> outputs/p0_inspect/{name}  ({len(text)} chars)")


def dump_excel(path: Path, name: str, max_rows: int = 200) -> None:
    buf = [f"### {path.name}", ""]
    xl = pd.ExcelFile(path)
    buf.append(f"sheets = {xl.sheet_names}")
    buf.append("")
    for sh in xl.sheet_names:
        df = xl.parse(sh, header=None)
        buf.append("=" * 78)
        buf.append(f"-- sheet: {sh}   shape={df.shape}   (header=None 原样输出)")
        buf.append("=" * 78)
        buf.append(df.head(max_rows).to_string())
        buf.append("")
        # 再按第 1 行做表头解析一次，方便看列名
        try:
            df2 = xl.parse(sh)
            buf.append(f"-- 按默认表头解析: columns = {list(df2.columns)}")
            buf.append(f"   dtypes = {dict(df2.dtypes.astype(str))}")
            buf.append("")
        except Exception as e:  # noqa: BLE001
            buf.append(f"   (默认表头解析失败: {e})")
            buf.append("")
    w(name, "\n".join(buf))


def main() -> int:
    print("=== 基础参数 xlsx ===")
    for f in [
        "调度中心与服务区",
        "物资需求与配送时限",
        "运输无人机数据",
        "中继无人机数据",
        "通信链路参数",
    ]:
        p = BASE / f"{f}.xlsx"
        if p.exists():
            dump_excel(p, f"xlsx_{f}.txt")
        else:
            print(f"  [缺失] {p}")

    print("\n=== 结果提交模板 ===")
    tmpl = RAW / "结果提交模板.xlsx"
    if tmpl.exists():
        dump_excel(tmpl, "xlsx_结果提交模板.txt")

    print("\n=== 地理空间 CSV ===")
    for p in sorted(GEO.rglob("*.csv")):
        try:
            df = pd.read_csv(p, nrows=15)
            full = sum(1 for _ in p.open(encoding="utf-8", errors="ignore")) - 1
            buf = [
                f"### {p.relative_to(GEO)}",
                f"n_rows≈{full}  n_cols={df.shape[1]}",
                f"columns = {list(df.columns)}",
                f"dtypes  = {dict(df.dtypes.astype(str))}",
                "",
                df.to_string(),
            ]
            w(f"csv_{p.stem}.txt", "\n".join(buf))
        except Exception as e:  # noqa: BLE001
            print(f"  [失败] {p.name}: {e}")

    print("\n=== DEM (.tif) ===")
    import rasterio

    tif = next(GEO.rglob("*.tif"), None)
    if tif:
        with rasterio.open(tif) as src:
            import numpy as np

            buf = [
                f"### {tif.name}",
                f"CRS        = {src.crs}",
                f"EPSG       = {src.crs.to_epsg()}",
                f"is_geographic = {src.crs.is_geographic}",
                f"size       = {src.width} x {src.height}",
                f"res        = {src.res}  (单位: 度, 因为是地理坐标系)",
                f"res_approx_m = {src.res[0] * 111320:.2f} m (经度方向, 赤道附近近似)",
                f"nodata     = {src.nodata}",
                f"bounds     = {src.bounds}",
                f"dtype      = {src.dtypes[0]}",
                f"n_bands    = {src.count}",
                "",
            ]
            a = src.read(1)
            valid = a[a != src.nodata] if src.nodata is not None else a.ravel()
            buf += [
                f"高程统计: min={valid.min():.2f}  max={valid.max():.2f}  "
                f"mean={valid.mean():.2f}  std={valid.std():.2f}",
                f"有效像元 = {valid.size} / {a.size} "
                f"(nodata 占比 {1 - valid.size / a.size:.4%})",
            ]
            w("dem_info.txt", "\n".join(buf))

    print("\n=== DEM (.mat) ===")
    from scipy.io import loadmat

    mat = next(GEO.rglob("*.mat"), None)
    mat_files = sorted(GEO.rglob("*.mat"))
    for m in mat_files:
        try:
            d = loadmat(m)
            keys = [k for k in d if not k.startswith("__")]
            buf = [f"### {m.relative_to(GEO)}", f"keys = {keys}", ""]
            for k in keys:
                v = d[k]
                buf.append(f"{k}: shape={getattr(v, 'shape', None)} dtype={getattr(v, 'dtype', None)}")
                if hasattr(v, "shape") and v.size and v.dtype.kind in "fiu":
                    buf.append(
                        f"    min={v.min()} max={v.max()} "
                        f"mean={float(v.mean()):.4f}"
                    )
                if hasattr(v, "shape") and v.size <= 20:
                    buf.append(f"    values={v.ravel().tolist()}")
                if hasattr(v, "shape") and v.size > 20:
                    buf.append(f"    head={v.ravel()[:8].tolist()}")
            w(f"mat_{m.stem}.txt", "\n".join(buf))
        except Exception as e:  # noqa: BLE001
            print(f"  [失败] {m.name}: {e}")

    print(f"\n完成。输出目录: {OUT}")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
